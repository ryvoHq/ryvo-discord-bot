#!/usr/bin/env python3
"""RYVO-Bot: automatische Beiträge im RYVO-Discord (Python 3.9+, nur Standardbibliothek). Läuft alle 10 Min. per LaunchAgent.

Was er tut (alles nur lesend aus öffentlichen RYVO-Quellen, nichts aus dem privaten Trading-Bot):
  #market-news       neue Schlagzeilen aus der Terminal-Beta (Titel, Quelle, Link) – keine Artikeltexte
  #market-brief      der Lage-Bericht, sobald ein neuer da ist (Englisch) – dazu in jeder Sprachkanal seine Sprache
  #terminal-updates  Hinweis, wenn sich die öffentliche Terminal-Beta ändert
  Postausgang        jede Datei ausgang/*.json wird gepostet (für andere Chats/Agenten), danach nach ausgang/gesendet/
  #bot-status        eine Nachricht, die bei jedem Lauf aktualisiert wird (Gesundheit des Bots)

Aufruf: python3 posten.py [--trocken]
Postausgang-Format: {"kanal": "terminal-updates", "titel": "...", "text": "...", "ping": "Terminal Updates Ping"}
"""
import fcntl
import glob
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
import urllib.request
from datetime import datetime, timezone

from discord_api import Discord, DiscordFehler, token_lesen
import markt
import lab
import grafik
import signale

HIER = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(HIER, "bauplan.json")
SERVER = os.path.join(HIER, "server-zustand.json")
ZUSTAND = os.path.join(HIER, "posten-zustand.json")
LOG = os.path.join(HIER, "posten.log")
AUSGANG = os.path.join(HIER, "ausgang")
TROCKEN = "--trocken" in sys.argv
FARBE = 0xFFFFFF
SPRACHEN = ["de", "es", "fr", "it", "tr"]


def log(text):
    zeile = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), text)
    print(zeile)
    if not TROCKEN and not os.environ.get("RYVO_CLOUD"):
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(zeile + "\n")
        if os.path.getsize(LOG) > 2_000_000:
            os.replace(LOG, LOG + ".alt")


def laden(pfad, standard):
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return standard


def speichern(pfad, daten):
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, pfad)


def holen(url, roh=False):
    req = urllib.request.Request(url, headers={"User-Agent": "RYVO-Discord-Bot/1.0 (+https://ryvo.studio)", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as f:
        daten = f.read()
    return daten if roh else json.loads(daten.decode("utf-8"))


def uhr(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m. %H:%M UTC")


class Poster:
    def __init__(self, dc, plan, server, z):
        self.dc, self.p, self.server, self.z = dc, plan["posten"], server, z
        self.kanaele = server.get("kanaele", {})
        self.rollen = server.get("rollen", {})
        self.ergebnis = {}

    def kanal(self, name):
        kid = self.kanaele.get(name)
        if not kid:
            raise RuntimeError("Kanal #%s unbekannt – erst bauen.py --los ausführen" % name)
        return kid

    def senden(self, kanal, embeds, ping=None):
        daten = {"embeds": embeds[:10], "allowed_mentions": {"parse": []}}
        if ping and self.rollen.get(ping):
            daten["content"] = "<@&%s>" % self.rollen[ping]
            daten["allowed_mentions"] = {"roles": [self.rollen[ping]]}
        return self.dc.post("/channels/%s/messages" % self.kanal(kanal), daten)

    # --- Schlagzeilen ---
    QUELLE_EN = {"EZB": "ECB", "Bundesbank": "Bundesbank"}
    SCHLAGZEILEN_SPRACHE = {
        "en": ("market-news", "Market headlines", "Title and link only. Read the full story at the source. "),
        "de": ("deutsch", "Schlagzeilen", "Nur Titel und Link. Den ganzen Artikel liest du bei der Quelle. "),
    }

    def schlagzeilen(self):
        d = holen(self.p["schlagzeilen_url"])
        eintraege = d.get("eintraege", [])
        gesehen = set(self.z.get("gesehen", []))
        erstlauf = not gesehen
        grenze = time.time() - self.p["schlagzeilen_hoechstalter_std"] * 3600
        neu = [e for e in eintraege if e.get("url") and e["url"] not in gesehen and e.get("zeit", 0) >= grenze]
        neu.sort(key=lambda e: e.get("zeit", 0), reverse=True)
        bericht = []
        for sprache, (kanal, titel_kopf, fuss_kopf) in self.SCHLAGZEILEN_SPRACHE.items():
            teil = [e for e in neu if (e.get("sprache") or "en") == sprache][: self.p["schlagzeilen_je_lauf"]]
            if erstlauf:
                teil = teil[:5]
            if not teil or not self.kanaele.get(kanal):
                continue
            zeilen = []
            for e in teil:
                titel = e["titel"].replace("[", "(").replace("]", ")")[:180]
                quelle = e.get("quelle", "?")
                if sprache == "en":
                    quelle = self.QUELLE_EN.get(quelle, quelle)
                zeilen.append("**[%s](%s)**\n%s · %s" % (titel, e["url"], quelle, uhr(e.get("zeit", 0))))
            embed = {"color": FARBE, "title": titel_kopf, "description": "\n\n".join(zeilen)[:4096],
                     "footer": {"text": fuss_kopf + self.p["fusszeile"][sprache]}}
            self.senden(kanal, [embed])
            bericht.append("%s %d" % (sprache, len(teil)))
        alle = [e["url"] for e in eintraege if e.get("url")]
        self.z["gesehen"] = (alle + [u for u in self.z.get("gesehen", []) if u not in alle])[:3000]
        self.ergebnis["Schlagzeilen"] = "%s gepostet (%d neu)" % (", ".join(bericht) or "0", len(neu))

    # --- Lage-Bericht ---
    def lagebrief_embed(self, d, sprache):
        def t(obj):
            if isinstance(obj, dict):
                return obj.get(sprache) or obj.get("en") or ""
            return obj or ""
        teile, quellen = [], []
        for ab in d.get("abschnitte", []):
            kopf = t(ab.get("titel"))
            zeilen = []
            for z in ab.get("zeilen", []):
                text = t(z.get("text")).strip()
                if text:
                    zeilen.append("· " + text)
                for q in z.get("quellen", []) or []:
                    if q.get("name") and q["name"] not in quellen:
                        quellen.append(q["name"])
            if zeilen:
                teile.append(("**%s**\n" % kopf if kopf else "") + "\n".join(zeilen))
        beschreibung = "\n\n".join(teile)
        if len(beschreibung) > 4000:
            beschreibung = beschreibung[:3990].rsplit("\n", 1)[0] + "\n…"
        fuss = self.p["fusszeile"].get(sprache, self.p["fusszeile"]["en"])
        if quellen:
            fuss = ", ".join(quellen[:12]) + " · " + fuss
        return {"color": FARBE, "title": t(d.get("titel"))[:256] or "Market brief",
                "url": self.p["terminal_url"], "description": beschreibung, "footer": {"text": fuss[:2048]}}

    def lagebrief(self):
        d = holen(self.p["lagebrief_url"])
        stand = d.get("stand")
        if not stand or stand == self.z.get("lagebrief_stand"):
            self.ergebnis["Lage-Bericht"] = "unverändert (Stand %s)" % (uhr(stand) if stand else "?")
            return
        if time.time() - stand > 12 * 3600:
            self.z["lagebrief_stand"] = stand
            self.ergebnis["Lage-Bericht"] = "zu alt, nicht gepostet (%s)" % uhr(stand)
            return
        self.senden(self.p["lagebrief_kanal"], [self.lagebrief_embed(d, "en")], ping=self.p.get("lagebrief_ping"))
        sprach_kanal = {"de": "deutsch", "es": "español", "fr": "français", "it": "italiano", "tr": "türkçe"}
        for s in SPRACHEN:
            if self.kanaele.get(sprach_kanal[s]):
                self.senden(sprach_kanal[s], [self.lagebrief_embed(d, s)])
        self.z["lagebrief_stand"] = stand
        self.ergebnis["Lage-Bericht"] = "gepostet (Stand %s)" % uhr(stand)

    # --- Terminal ---
    def terminal(self):
        html = holen(self.p["terminal_url"], roh=True)
        h = hashlib.sha256(html).hexdigest()
        alt = self.z.get("terminal_hash")
        self.z["terminal_hash"] = h
        if alt is None:
            self.ergebnis["Terminal"] = "Stand gemerkt"
            return
        if h == alt:
            self.ergebnis["Terminal"] = "unverändert"
            return
        if time.time() - self.z.get("terminal_notiz_zeit", 0) < 2 * 3600:
            self.ergebnis["Terminal"] = "geändert, Notiz aus dem Postausgang deckt es ab"
            return
        embed = {"color": FARBE, "title": "RYVO Terminal beta updated", "url": self.p["terminal_url"],
                 "description": "A new build of the public RYVO Terminal beta is live. Reload the page to get it.\nSomething looks off? Tell us in the bug-reports forum.",
                 "footer": {"text": "RYVO Terminal · " + self.p["fusszeile"]["en"]}}
        self.senden(self.p["terminal_kanal"], [embed], ping=self.p.get("terminal_ping"))
        self.ergebnis["Terminal"] = "neue Fassung gemeldet"

    # --- Postausgang ---
    def postausgang(self):
        os.makedirs(os.path.join(AUSGANG, "gesendet"), exist_ok=True)
        n = 0
        for pfad in sorted(glob.glob(os.path.join(AUSGANG, "*.json"))):
            try:
                m = json.load(open(pfad, encoding="utf-8"))
                embed = {"color": FARBE, "title": m.get("titel", "")[:256], "description": m["text"][:4096]}
                if m.get("link"):
                    embed["url"] = m["link"]
                self.senden(m["kanal"], [embed], ping=m.get("ping"))
                if m["kanal"] == self.p["terminal_kanal"]:
                    self.z["terminal_notiz_zeit"] = time.time()
                if not TROCKEN:
                    shutil.move(pfad, os.path.join(AUSGANG, "gesendet", os.path.basename(pfad)))
                n += 1
            except Exception as e:
                self.ergebnis["Postausgang-Fehler"] = "%s: %s" % (os.path.basename(pfad), e)
        self.ergebnis["Postausgang"] = "%d gesendet" % n

    # --- Live-Board (#market-board): eine Nachricht, bei jedem Lauf aktualisiert ---
    def board(self):
        kid = self.kanal("market-board")
        ctx = markt.kontexte()
        self._ctx = ctx
        try:
            fg = markt.angst_gier()
        except Exception:
            fg = None
        embeds = markt.board_embeds(ctx, fg)
        mid = self.z.get("board_nachricht")
        if mid:
            try:
                self.dc.patch("/channels/%s/messages/%s" % (kid, mid), {"embeds": embeds})
                self.ergebnis["Board"] = "aktualisiert"
                return
            except DiscordFehler as e:
                if e.status != 404:
                    raise
        m = self.dc.post("/channels/%s/messages" % kid, {"embeds": embeds})
        self.z["board_nachricht"] = m["id"]
        try:
            self.dc.put("/channels/%s/pins/%s" % (kid, m["id"]), None)
        except DiscordFehler:
            pass
        self.ergebnis["Board"] = "neu angelegt"

    def _faellig(self, schluessel, ab_stunde_utc):
        heute = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.z.get(schluessel) == heute:
            return None
        if self.z.get(schluessel) and datetime.now(timezone.utc).hour < ab_stunde_utc:
            return None
        return heute

    # --- Swing-Board (#swing-board): einmal am Tag nach US-Schluss, mit Chart ---
    def swing_board(self):
        heute = self._faellig("swing_tag", 22)
        if not heute:
            return
        daten = {c: markt.kerzen(c) for c, _ in markt.SWING}
        embed = markt.swing_embed(daten)
        bild = grafik.raster([("BTC", daten["BTC"][-90:]), ("S&P 500", daten["xyz:SP500"][-90:]), ("Nasdaq 100", daten["xyz:XYZ100"][-90:]), ("Gold", daten["xyz:GOLD"][-90:])],
                             "Swing board · " + datetime.now(timezone.utc).strftime("%d %b %Y"), "Daily candles, last 90 days", intervall="1d")
        embed["image"] = {"url": "attachment://swing-board.png"}
        self.dc.datei("POST", "/channels/%s/messages" % self.kanal("swing-board"), {"embeds": [embed]}, "swing-board.png", bild)
        self.z["swing_tag"] = heute
        self.ergebnis["Swing-Board"] = "gepostet"

    # --- Chart of the day (#charts): einmal am Tag ab 07 UTC, wechselnder Markt ---
    CHART_REIHE = [("BTC", "Bitcoin"), ("xyz:SP500", "S&P 500"), ("xyz:GOLD", "Gold"), ("ETH", "Ethereum"), ("xyz:XYZ100", "Nasdaq 100"),
                   ("xyz:EUR", "EUR/USD"), ("SOL", "Solana"), ("xyz:CL", "WTI crude"), ("xyz:NVDA", "NVIDIA (NVDA)"), ("xyz:SILVER", "Silver"),
                   ("xyz:TSLA", "Tesla (TSLA)"), ("xyz:JP225", "Nikkei 225")]

    def chart_des_tages(self):
        heute = self._faellig("chart_tag", 7)
        if not heute:
            return
        nr = datetime.now(timezone.utc).timetuple().tm_yday % len(self.CHART_REIHE)
        coin, name = self.CHART_REIHE[nr]
        k = markt.kerzen(coin)
        kz = markt.kennzahlen(k)
        def p(x):
            return "–" if x is None else "%+.1f%%" % (x * 100)
        text = ("**Chart of the day · %s · 1D**\nLast %s · 1W %s · 1M %s · vs 50D %s · vs 200D %s\n52-week range %s – %s\n"
                "-# Hyperliquid perps, not official quotes. Not financial advice.") % (
            name, markt.zahl(kz["preis"]), p(kz["1w"]), p(kz["1m"]), p(kz["50d"]), p(kz["200d"]), markt.zahl(kz["tief52"]), markt.zahl(kz["hoch52"]))
        try:
            inhalt, endung = grafik.video(k[-90:], "Chart of the day · %s · 1D" % name, "Last 90 daily candles", intervall="1d")
        except Exception:
            inhalt, endung = grafik.kerzenchart(k[-120:], "Chart of the day · %s · 1D" % name, "Last 120 daily candles", intervall="1d", mittel=[50]), "png"
        self.dc.datei("POST", "/channels/%s/messages" % self.kanal("charts"), {"content": text, "allowed_mentions": {"parse": []}}, "chart-of-the-day." + endung, inhalt)
        self.z["chart_tag"] = heute
        self.ergebnis["Chart des Tages"] = name

    # --- Daily discussion (#general): jeden Tag ab 05 UTC ein Thread ---
    def tagesthread(self):
        heute = self._faellig("thread_tag", 5)
        if not heute:
            return
        ctx = getattr(self, "_ctx", None) or markt.kontexte()
        zeilen = []
        for coin, name in (("BTC", "BTC"), ("ETH", "ETH"), ("xyz:SP500", "S&P 500"), ("xyz:XYZ100", "Nasdaq 100"), ("xyz:GOLD", "Gold"), ("xyz:CL", "WTI crude")):
            c = ctx.get(coin)
            if c and c["vortag"]:
                zeilen.append("%s %s %+.1f%%" % (name, markt.zahl(c["preis"]), (c["preis"] / c["vortag"] - 1) * 100))
        tag = datetime.now(timezone.utc).strftime("%a %d %b")
        m = self.dc.post("/channels/%s/messages" % self.kanal("general"), {"content": "**%s** · %s" % (tag, " · ".join(zeilen)), "allowed_mentions": {"parse": []}})
        self.dc.post("/channels/%s/messages/%s/threads" % (self.kanal("general"), m["id"]),
                     {"name": "Daily thread · " + datetime.now(timezone.utc).strftime("%d %b"), "auto_archive_duration": 1440})
        self.z["thread_tag"] = heute
        self.ergebnis["Tagesthread"] = "gepostet"

    # --- EZB-Referenzkurse (#forex): sobald ein neuer Tag da ist ---
    def ezb(self):
        kurse = markt.ezb_kurse()
        tag = max(v[-1][0] for v in kurse.values())
        if self.z.get("ezb_tag") == tag:
            return
        zeilen = []
        for wae in ("USD", "GBP", "CHF", "JPY", "CNY", "AUD", "CAD"):
            r = kurse.get(wae)
            if not r:
                continue
            neu = r[-1][1]
            alt = r[-2][1] if len(r) > 1 else None
            aend = ("%+.2f%%" % ((neu / alt - 1) * 100)) if alt else "–"
            zeilen.append("EUR/%s %10s %8s" % (wae, ("{:.4f}" if neu < 20 else "{:.2f}").format(neu), aend))
        embed = {"color": 0xFFFFFF, "title": "ECB euro reference rates · " + tag,
                 "description": "Official daily reference rates (about 14:15 CET), change vs the previous fixing.\n```\n%s\n```" % "\n".join(zeilen),
                 "footer": {"text": "Source: ECB statistics · Reference rates are for information only, not trading prices."}}
        self.dc.post("/channels/%s/messages" % self.kanal("forex"), {"embeds": [embed]})
        self.z["ezb_tag"] = tag
        self.ergebnis["EZB"] = tag

    # --- Tages-Übersichten je Kanal (aus denselben Hyperliquid-Daten wie das Board) ---
    NICHT_AKTIEN = {"xyz:SP500", "xyz:XYZ100", "xyz:JP225", "xyz:KR200", "xyz:VIX", "xyz:DXY", "xyz:GOLD", "xyz:SILVER", "xyz:CL",
                    "xyz:BRENTOIL", "xyz:NATGAS", "xyz:COPPER", "xyz:EUR", "xyz:JPY", "xyz:PLATINUM", "xyz:PALLADIUM", "xyz:URANIUM",
                    "xyz:ALUMINIUM", "xyz:CORN", "xyz:WHEAT", "xyz:TTF", "xyz:XLE", "xyz:EWY", "xyz:EWJ", "xyz:URNM", "xyz:XYZ100"}

    AKTIEN = {"xyz:" + t for t in ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD", "AVGO", "NFLX", "ORCL", "PLTR", "COIN",
                                    "MSTR", "HOOD", "INTC", "MU", "TSM", "ASML", "ARM", "BABA", "COST", "LLY", "CRCL", "RIVN", "GME",
                                    "SNDK", "SMSN", "SKHX", "AMAT", "ACN", "CRWV", "DKNG", "HIMS", "BX", "LITE")}

    def _zeile(self, name, c):
        aend = (c["preis"] / c["vortag"] - 1) * 100 if c["vortag"] else 0
        return "**%s** %s (%+.1f%%) · vol %s" % (name, markt.zahl(c["preis"]), aend, markt.geld(c["volumen"]))

    def ctx_holen(self):
        if not isinstance(getattr(self, "_ctx", None), dict):
            self._ctx = markt.kontexte()
        return self._ctx

    def _senden_embed(self, kanal, titel, teile, fuss_zusatz=""):
        embed = {"color": 0xFFFFFF, "title": titel, "description": "\n\n".join(teile)[:4096],
                 "footer": {"text": (fuss_zusatz + markt.QUELLE_HL + " 24h vs previous UTC day. Not financial advice.")[:2048]}}
        ziel = getattr(self, "_bearbeiten", {}).get(kanal)
        if ziel:
            self.dc.patch("/channels/%s/messages/%s" % (self.kanal(kanal), ziel), {"embeds": [embed]})
        else:
            self.dc.post("/channels/%s/messages" % self.kanal(kanal), {"embeds": [embed]})

    def krypto_tag(self):
        heute = self._faellig("krypto_tag", 7)
        if not heute:
            return
        ctx = self.ctx_holen()
        perps = {k: v for k, v in ctx.items() if ":" not in k and v["preis"] and v["vortag"]}
        nach_oi = sorted(perps.items(), key=lambda kv: -kv[1]["oi_usd"])[:10]
        liquide = {k: v for k, v in perps.items() if v["volumen"] >= 5e6}
        aend = lambda kv: kv[1]["preis"] / kv[1]["vortag"] - 1
        hoch = [kv for kv in sorted(liquide.items(), key=aend, reverse=True) if aend(kv) > 0][:5]
        tief = [kv for kv in sorted(liquide.items(), key=aend) if aend(kv) < 0][:5]
        teile = ["**Largest by open interest**\n" + "\n".join("%s · OI %s · funding %+.4f%%/h · %+.1f%%" % (k, markt.geld(v["oi_usd"]), v["funding"] * 100, aend((k, v)) * 100) for k, v in nach_oi),
                 "**Biggest moves up** (24h volume over $5M)\n" + ("\n".join(self._zeile(k, v) for k, v in hoch) or "none"),
                 "**Biggest moves down** (24h volume over $5M)\n" + ("\n".join(self._zeile(k, v) for k, v in tief) or "none")]
        self._senden_embed("crypto-trading", "Crypto derivatives · " + datetime.now(timezone.utc).strftime("%a %d %b"), teile)
        self.z["krypto_tag"] = heute
        self.ergebnis["Krypto-Übersicht"] = "gepostet"

    def aktien_tag(self):
        heute = self._faellig("aktien_tag", 21)
        if not heute:
            return
        ctx = self.ctx_holen()
        aktien = {k: v for k, v in ctx.items() if k in self.AKTIEN and v["preis"] and v["vortag"]}
        aend = lambda kv: kv[1]["preis"] / kv[1]["vortag"] - 1
        hoch = [kv for kv in sorted(aktien.items(), key=aend, reverse=True) if aend(kv) > 0][:6]
        tief = [kv for kv in sorted(aktien.items(), key=aend) if aend(kv) < 0][:6]
        aktiv = sorted(aktien.items(), key=lambda kv: -kv[1]["volumen"])[:6]
        n = lambda k: k.split(":", 1)[1]
        teile = ["**Top gainers**\n" + ("\n".join(self._zeile(n(k), v) for k, v in hoch) or "none"),
                 "**Top losers**\n" + ("\n".join(self._zeile(n(k), v) for k, v in tief) or "none"),
                 "**Most traded**\n" + "\n".join(self._zeile(n(k), v) for k, v in aktiv)]
        self._senden_embed("stocks", "Stock movers · " + datetime.now(timezone.utc).strftime("%a %d %b"), teile,
                           "%d large-cap stocks (no ETFs, no leveraged products). " % len(aktien))
        self.z["aktien_tag"] = heute
        self.ergebnis["Aktien-Übersicht"] = "gepostet"

    def indizes_tag(self):
        heute = self._faellig("indizes_tag", 13)
        if not heute:
            return
        ctx = self.ctx_holen()
        gruppen = [("Indices", [("xyz:SP500", "S&P 500"), ("xyz:XYZ100", "Nasdaq 100"), ("xyz:JP225", "Nikkei 225"), ("xyz:KR200", "KOSPI 200")]),
                   ("Currencies", [("xyz:EUR", "EUR/USD"), ("xyz:JPY", "USD/JPY")]),
                   ("Energy & metals", [("xyz:CL", "WTI crude"), ("xyz:BRENTOIL", "Brent"), ("xyz:GOLD", "Gold"), ("xyz:SILVER", "Silver")])]
        teile = []
        for titel, liste in gruppen:
            z = [self._zeile(name, ctx[c]) for c, name in liste if c in ctx and ctx[c]["vortag"]]
            if z:
                teile.append("**%s**\n%s" % (titel, "\n".join(z)))
        try:
            from zoneinfo import ZoneInfo
            ny = datetime.now(ZoneInfo("America/New_York")).replace(hour=9, minute=30, second=0, microsecond=0)
            teile.append("US cash open %s UTC" % ny.astimezone(timezone.utc).strftime("%H:%M"))
        except Exception:
            pass
        self._senden_embed("futures-indices", "Pre-market · " + datetime.now(timezone.utc).strftime("%a %d %b"), teile)
        self.z["indizes_tag"] = heute
        self.ergebnis["Indizes-Übersicht"] = "gepostet"

    # --- Status ---
    def status(self, fehler):
        jetzt = time.time()
        zeilen = ["**%s**: %s" % (k, v) for k, v in self.ergebnis.items()]
        if fehler:
            zeilen.append("**Fehler**: " + "; ".join(fehler)[:900])
        self.z["laeufe"] = self.z.get("laeufe", 0) + 1
        embed = {"color": 0xE5484D if fehler else FARBE, "title": ("🔴 " if fehler else "🟢 ") + "RYVO bot",
                 "description": "\n".join(zeilen)[:4000],
                 "footer": {"text": "Last run %s · run #%d · every 5 min · %s" % (uhr(jetzt), self.z["laeufe"], "GitHub cloud" if os.environ.get("RYVO_CLOUD") else "Mac")}}
        kid = self.kanaele.get(self.p["status_kanal"])
        if not kid:
            return
        mid = self.z.get("status_nachricht")
        if mid:
            try:
                self.dc.patch("/channels/%s/messages/%s" % (kid, mid), {"embeds": [embed]})
                return
            except DiscordFehler as e:
                if e.status != 404:
                    raise
        m = self.dc.post("/channels/%s/messages" % kid, {"embeds": [embed]})
        self.z["status_nachricht"] = m["id"]


def main():
    sperre = open(os.path.join(HIER, ".posten.sperre"), "w")
    try:
        fcntl.flock(sperre, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("läuft schon")
        return
    token = token_lesen()
    if not token:
        log("kein bot.token – nichts zu tun")
        return
    plan = laden(PLAN, {})
    server = laden(SERVER, {})
    if not server.get("kanaele"):
        log("server-zustand.json fehlt – erst bauen.py --los")
        return
    z = laden(ZUSTAND, {})
    dc = Discord(token, trocken=TROCKEN, protokoll=log)
    p = Poster(dc, plan, server, z)
    fehler = []
    for schritt in (p.postausgang, p.board, signale.Signale(p).lauf, p.schlagzeilen, p.lagebrief, p.terminal, p.tagesthread, p.chart_des_tages, p.swing_board, p.ezb, p.krypto_tag, p.aktien_tag, p.indizes_tag,
                    lab.Lab(p).pruefen, lab.Lab(p).scan, lab.Lab(p).momentum, lab.Lab(p).wochenbilanz, lab.Lab(p).tageslog):
        try:
            schritt()
        except Exception as e:
            fehler.append("%s: %s" % (schritt.__name__, e))
            log("FEHLER %s: %s" % (schritt.__name__, traceback.format_exc(limit=2)))
    try:
        p.status(fehler)
    except Exception as e:
        log("FEHLER Status: %s" % e)
    if not TROCKEN:
        speichern(ZUSTAND, z)
    log("Lauf fertig: " + " | ".join("%s %s" % kv for kv in p.ergebnis.items()) + (" | FEHLER " + "; ".join(fehler) if fehler else ""))


if __name__ == "__main__":
    main()
