"""RYVO Lab: regelbasierte Papier-Trades und Momentum-Hinweise für den Discord (Python 3.9+).

VORAB festgelegt (25.11.2026, vor dem ersten Trade, wird nicht nachträglich angepasst):
  Universum: große Krypto-Werte, die großen Memecoins auf Hyperliquid und Index-/Rohstoff-/Aktien-Kontrakte (xyz).
  Prüfung einmal am Tag nach dem Tagesschluss (ab 00:10 UTC), nur abgeschlossene Tageskerzen:
    LONG  wenn Schluss > höchstes Hoch der 20 Tage davor UND Schluss > 50-Tage-Schnitt
    SHORT wenn Schluss < tiefstes Tief der 20 Tage davor UND Schluss < 50-Tage-Schnitt
  Einstieg = Markpreis beim Posten. Stop = 1,5 × ATR(14), Ziel = 3 × ATR(14) (also 2R). Höchstens 15 Tage, dann Ausstieg zum Markpreis.
  Je Markt höchstens ein offener Trade. Kosten: 0,1 % je Trade (Ein- und Ausstieg zusammen) werden vom Ergebnis abgezogen.
  Geprüft wird alle paar Minuten am Markpreis (kein Tick-genauer Ausstieg: Lücken zählen voll).
Alles Papier, kein echtes Geld, keine Anlageberatung. Jeder Trade bleibt in lab/trades.json – Gewinner wie Verlierer.
"""
import json
import os
import time
from datetime import datetime, timezone

import markt
import grafik

HIER = os.path.dirname(os.path.abspath(__file__))
TRADES = os.path.join(HIER, "lab", "trades.json")
BIBLIOTHEK = os.path.join(HIER, "lab", "BIBLIOTHEK.md")
KOSTEN = 0.001

MAJORS = [("BTC", "BTC"), ("ETH", "ETH"), ("SOL", "SOL"), ("HYPE", "HYPE"), ("XRP", "XRP")]
MEMES = [("DOGE", "DOGE"), ("kPEPE", "PEPE"), ("kBONK", "BONK"), ("WIF", "WIF"), ("POPCAT", "POPCAT"), ("FARTCOIN", "FARTCOIN"),
         ("PENGU", "PENGU"), ("TRUMP", "TRUMP"), ("MOODENG", "MOODENG"), ("BRETT", "BRETT"), ("SPX", "SPX6900"), ("kSHIB", "SHIB")]
TRAD = [("xyz:SP500", "S&P 500"), ("xyz:XYZ100", "Nasdaq 100"), ("xyz:GOLD", "Gold"), ("xyz:SILVER", "Silver"), ("xyz:CL", "WTI crude"),
        ("xyz:EUR", "EUR/USD"), ("xyz:NVDA", "NVDA"), ("xyz:TSLA", "TSLA")]
UNIVERSUM = MAJORS + MEMES + TRAD
NAME = dict(UNIVERSUM)
FUSS = "-# RYVO Lab · simulated paper trade · fixed rule set · not financial advice"


def laden():
    try:
        with open(TRADES, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def speichern(trades):
    os.makedirs(os.path.dirname(TRADES), exist_ok=True)
    tmp = TRADES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TRADES)
    bibliothek(trades)


def atr(k, n=14):
    tr = []
    for i in range(1, len(k)):
        _, _, h, l, _ = k[i]
        c0 = k[i - 1][4]
        tr.append(max(h - l, abs(h - c0), abs(l - c0)))
    return sum(tr[-n:]) / n if len(tr) >= n else None


def abgeschlossen(k):
    jetzt = time.time() * 1000
    return [x for x in k if x[0] + 86400000 <= jetzt]


def signal(k):
    k = abgeschlossen(k)
    if len(k) < 60:
        return None
    s = [x[4] for x in k]
    schluss = s[-1]
    vor = k[-21:-1]
    hoch, tief = max(x[2] for x in vor), min(x[3] for x in vor)
    g50 = sum(s[-50:]) / 50
    a = atr(k)
    if not a:
        return None
    if schluss > hoch and schluss > g50:
        return {"seite": "long", "grund": "Daily close %s above the prior 20-day high %s and above the 50-day average %s." % (markt.zahl(schluss), markt.zahl(hoch), markt.zahl(g50)), "atr": a}
    if schluss < tief and schluss < g50:
        return {"seite": "short", "grund": "Daily close %s below the prior 20-day low %s and below the 50-day average %s." % (markt.zahl(schluss), markt.zahl(tief), markt.zahl(g50)), "atr": a}
    return None


def r_wert(t, preis):
    risiko = abs(t["einstieg"] - t["stop"])
    roh = (preis - t["einstieg"]) if t["seite"] == "long" else (t["einstieg"] - preis)
    return (roh - t["einstieg"] * KOSTEN) / risiko if risiko else 0.0


def bilanz(trades):
    zu = [t for t in trades if t["status"] == "zu"]
    g = [t for t in zu if t["r"] > 0]
    summe = sum(t["r"] for t in zu)
    return len(zu), len(g), summe


def bilanz_text(trades):
    n, g, summe = bilanz(trades)
    offen = sum(1 for t in trades if t["status"] == "offen")
    if not n:
        return "Lab record: no closed trades yet · %d open" % offen
    return "Lab record: %d closed · %d wins / %d losses (%.0f%%) · total %+.1fR · %d open" % (n, g, n - g, 100.0 * g / n, summe, offen)


def bibliothek(trades):
    n, g, summe = bilanz(trades)
    zeilen = ["# RYVO Lab – Trade-Bibliothek", "",
              "Alle Papier-Trades des RYVO-Lab-Modells (Regeln: siehe Kopf von `lab.py`, VORAB 25.11.2026). Für Menschen und KI-Agenten zum Lernen:",
              "jede Zeile = ein Trade mit Grund, Ergebnis in R und Lehre. Nichts wird gelöscht oder geschönt.", "",
              "**Stand:** %s · %d abgeschlossen · %d Gewinner · Summe %+.2fR · %d offen" % (
                  datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC"), n, g, summe, sum(1 for t in trades if t["status"] == "offen")), "",
              "| # | Markt | Seite | Eröffnet | Einstieg | Stop | Ziel | Status | Ausstieg | R | Lehre |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, t in enumerate(trades, 1):
        zeilen.append("| %d | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            i, t["name"], t["seite"], t["eroeffnet"][:16], markt.zahl(t["einstieg"]), markt.zahl(t["stop"]), markt.zahl(t["ziel"]),
            t["status"] + (" (%s)" % t.get("ausgang", "") if t["status"] == "zu" else ""),
            markt.zahl(t["ausstieg"]) if t.get("ausstieg") else "–", ("%+.2f" % t["r"]) if t.get("r") is not None else "–",
            t.get("lehre", "")))
    with open(BIBLIOTHEK, "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")


class Lab:
    def __init__(self, poster):
        self.p = poster
        self.z = poster.z

    def embed(self, titel, text, farbe=0xFFFFFF):
        return {"color": farbe, "title": titel, "description": text[:4096], "footer": {"text": FUSS}}

    # --- einmal am Tag: neue Ideen ---
    def scan(self):
        heute = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.z.get("lab_scan") == heute:
            return
        if self.z.get("lab_scan") and datetime.now(timezone.utc).hour == 0 and datetime.now(timezone.utc).minute < 10:
            return
        ctx = self.p.ctx_holen()
        trades = laden()
        offen = {t["coin"] for t in trades if t["status"] == "offen"}
        neu = 0
        for coin, name in UNIVERSUM:
            if coin in offen or coin not in ctx:
                continue
            try:
                s = signal(markt.kerzen(coin, 120))
            except Exception:
                continue
            if not s:
                continue
            preis = ctx[coin]["preis"]
            a = s["atr"]
            stop = preis - 1.5 * a if s["seite"] == "long" else preis + 1.5 * a
            ziel = preis + 3 * a if s["seite"] == "long" else preis - 3 * a
            if stop <= 0 or ziel <= 0:
                continue
            t = {"id": "%s-%s" % (heute, coin), "coin": coin, "name": name, "seite": s["seite"], "eroeffnet": datetime.now(timezone.utc).isoformat(),
                 "einstieg": preis, "stop": stop, "ziel": ziel, "grund": s["grund"], "status": "offen", "hoch": preis, "tief": preis}
            text = "**%s %s** · entry %s · SL %s · TP %s (2R)\n%s\n%s" % (
                s["seite"].upper(), name, markt.zahl(preis), markt.zahl(stop), markt.zahl(ziel), s["grund"], FUSS)
            try:
                k = markt.kerzen(coin, 200)
                kv = k[-90:]
                bild = grafik.kerzenchart(kv, "RYVO Lab · %s %s" % (s["seite"].upper(), name), s["grund"], intervall="1d",
                                          position=dict(von=len(kv) - 1, einstieg=preis, stop=stop, ziel=ziel, seite=s["seite"]), mittel=[50])
                m = self.p.dc.datei("POST", "/channels/%s/messages" % self.p.kanal("lab-trades"), {"content": text, "allowed_mentions": {"parse": []}}, "lab.png", bild)
            except Exception:
                m = self.p.dc.post("/channels/%s/messages" % self.p.kanal("lab-trades"), {"content": text, "allowed_mentions": {"parse": []}})
            t["nachricht"] = (m or {}).get("id")
            self.z.setdefault("lab_tageslog", []).append("%s %s %s UTC, open at %s" % (s["seite"].capitalize(), name, datetime.now(timezone.utc).strftime("%H:%M"), markt.zahl(preis)))
            trades.append(t)
            neu += 1
        speichern(trades)
        self.z["lab_scan"] = heute
        self.p.ergebnis["Lab-Scan"] = "%d neue Papier-Trades" % neu

    # --- jeden Lauf: offene Trades prüfen ---
    def pruefen(self):
        trades = laden()
        offene = [t for t in trades if t["status"] == "offen"]
        if not offene:
            return
        ctx = self.p.ctx_holen()
        geschlossen = 0
        for t in offene:
            c = ctx.get(t["coin"])
            if not c or not c["preis"]:
                continue
            p = c["preis"]
            t["hoch"], t["tief"] = max(t["hoch"], p), min(t["tief"], p)
            alter = (datetime.now(timezone.utc) - datetime.fromisoformat(t["eroeffnet"])).total_seconds() / 86400
            ausgang = None
            if (t["seite"] == "long" and p <= t["stop"]) or (t["seite"] == "short" and p >= t["stop"]):
                ausgang = "stop"
            elif (t["seite"] == "long" and p >= t["ziel"]) or (t["seite"] == "short" and p <= t["ziel"]):
                ausgang = "target"
            elif alter >= 15:
                ausgang = "time"
            if not ausgang:
                continue
            t.update(status="zu", ausgang=ausgang, ausstieg=p, geschlossen=datetime.now(timezone.utc).isoformat(), r=round(r_wert(t, p), 2))
            bestes = r_wert(t, t["hoch"] if t["seite"] == "long" else t["tief"])
            if ausgang == "stop" and alter < 1:
                t["lehre"] = "Breakout failed within a day (best point %+.1fR)." % bestes
            elif ausgang == "stop":
                t["lehre"] = "Stopped after %.0f days; best point was %+.1fR." % (alter, bestes)
            elif ausgang == "target":
                t["lehre"] = "Breakout carried to 2R in %.0f days." % alter
            else:
                t["lehre"] = "No follow-through in 15 days (best point %+.1fR)." % bestes
            text = "**%s %s closed** · %s at %s · **%+.2fR** · %.1f days\n%s\n%s\n%s" % (
                t["seite"].upper(), t["name"], {"stop": "stop hit", "target": "target hit", "time": "time exit"}[ausgang], markt.zahl(p), t["r"], alter,
                t["lehre"], bilanz_text(trades), FUSS)
            self.p.dc.post("/channels/%s/messages" % self.p.kanal("lab-trades"), {"content": text, "allowed_mentions": {"parse": []}})
            self.z.setdefault("lab_tageslog", []).append("%s %s closed, %s %+.2fR" % (t["seite"].capitalize(), t["name"], "win" if t["r"] > 0 else "loss", t["r"]))
            try:
                self.ergebnis_bild(t, trades, alter)
            except Exception:
                pass                                         # das Bild ist Zugabe: der Abschluss steht schon in #lab-trades
            geschlossen += 1
        speichern(trades)
        if geschlossen:
            self.p.ergebnis["Lab"] = "%d geschlossen" % geschlossen

    # --- jeder Abschluss als Chart in #wins-and-losses: Gewinner wie Verlierer, ohne Auswahl ---
    def ergebnis_bild(self, t, trades, alter):
        if not self.p.kanaele.get("wins-and-losses"):
            return
        k = markt.kerzen(t["coin"], 200)[-90:]
        auf = datetime.fromisoformat(t["eroeffnet"]).timestamp() * 1000
        von = next((i for i, x in enumerate(k) if x[0] + 86400 * 1000 > auf), len(k) - 1)      # die Tageskerze, in der eröffnet wurde
        wort = "WIN" if t["r"] > 0 else "LOSS"
        ausgang = {"stop": "stop hit", "target": "target hit", "time": "time exit"}[t["ausgang"]]
        titel = "%s · %s %s · %+.2fR" % (wort, t["seite"].upper(), t["name"], t["r"])
        bild = grafik.kerzenchart(k, "RYVO Lab · " + titel, "Entry %s · exit %s (%s) · %.1f days" % (markt.zahl(t["einstieg"]), markt.zahl(t["ausstieg"]), ausgang, alter),
                                  intervall="1d", position=dict(von=von, einstieg=t["einstieg"], stop=t["stop"], ziel=t["ziel"], seite=t["seite"]),
                                  marken=[(len(k) - 1, t["ausstieg"], "v" if t["ausstieg"] >= t["einstieg"] else "^", "exit")])
        text = "**%s** · entry %s → exit %s (%s) · %.1f days\n%s\n%s\n%s" % (
            titel, markt.zahl(t["einstieg"]), markt.zahl(t["ausstieg"]), ausgang, alter, t.get("lehre", ""), bilanz_text(trades), FUSS)
        self.p.dc.datei("POST", "/channels/%s/messages" % self.p.kanal("wins-and-losses"), {"content": text, "allowed_mentions": {"parse": []}}, "lab-result.png", bild)

    # --- Sonntag 18 UTC: Wochenbilanz ---
    def wochenbilanz(self):
        jetzt = datetime.now(timezone.utc)
        woche = jetzt.strftime("%G-W%V")
        if jetzt.weekday() != 6 or jetzt.hour < 18 or self.z.get("lab_woche") == woche:
            return
        trades = laden()
        n, g, summe = bilanz(trades)
        zu_woche = [t for t in trades if t["status"] == "zu" and (jetzt - datetime.fromisoformat(t["geschlossen"])).days < 7]
        zeilen = ["**This week:** %d closed · %+.1fR" % (len(zu_woche), sum(t["r"] for t in zu_woche))]
        for t in zu_woche:
            zeilen.append("· %s %s %+.2fR – %s" % (t["seite"], t["name"], t["r"], t.get("lehre", "")))
        zeilen.append("\n**All time:** " + bilanz_text(trades))
        zeilen.append("Full trade library: https://github.com/ryvoHq/ryvo-discord-bot/blob/main/bot/lab/BIBLIOTHEK.md")
        self.p.dc.post("/channels/%s/messages" % self.p.kanal("lab-scorecard"), {"content": "**RYVO Lab · week %s**\n%s\n%s" % (woche, "\n".join(zeilen), FUSS), "allowed_mentions": {"parse": []}})
        self.z["lab_woche"] = woche

    # --- 23:50 UTC: Tageslog (eine Nachricht je Tag) ---
    def tageslog(self):
        jetzt = datetime.now(timezone.utc)
        tag = jetzt.strftime("%Y-%m-%d")
        if jetzt.hour != 23 or jetzt.minute < 50 or self.z.get("lab_log_tag") == tag:
            return
        eintraege = self.z.get("lab_tageslog", [])
        if eintraege:
            self.p.dc.post("/channels/%s/messages" % self.p.kanal("lab-trades"),
                           {"content": "%s\n%s\n%s" % (jetzt.strftime("%m-%d-%Y"), "\n".join(eintraege), bilanz_text(laden())), "allowed_mentions": {"parse": []}})
        self.z["lab_tageslog"] = []
        self.z["lab_log_tag"] = tag

    # --- jeden Lauf: Momentum-Hinweise (beschreibend) ---
    SCHWELLE = {"major": 0.025, "meme": 0.06, "trad": 0.015}

    def momentum(self):
        jetzt = time.time()
        sperre = self.z.setdefault("momentum_sperre", {})
        gruppen = [("major", MAJORS, "momentum-alerts"), ("meme", MEMES, "meme-momentum"), ("trad", TRAD, "momentum-alerts")]
        n = 0
        for art, liste, kanal in gruppen:
            for coin, name in liste:
                if jetzt - sperre.get(coin, 0) < 3 * 3600:
                    continue
                try:
                    roh = markt._post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": int((jetzt - 50 * 3600) * 1000), "endTime": int(jetzt * 1000)}})
                except Exception:
                    continue
                if not roh or len(roh) < 3:
                    continue
                k = [(float(x["o"]), float(x["c"]), float(x["v"])) for x in roh]
                o, c, v = k[-1]
                p = k[-2][1]  # Schluss der letzten vollen Stunde
                aend = c / p - 1 if p else 0
                if abs(aend) < self.SCHWELLE[art]:
                    continue
                mittel = sum(x[2] for x in k[-25:-1]) / max(1, len(k[-25:-1]))
                tag = c / k[-25][0] - 1 if len(k) >= 25 else c / k[0][0] - 1
                text = "**%s %+.1f%%** this hour · %s · 24h %+.1f%% · volume %.1f× hourly avg\n-# Hyperliquid perps · describes a move, not a signal · not financial advice" % (
                    name, aend * 100, markt.zahl(c), tag * 100, (v / mittel) if mittel else 0)
                try:
                    kk = [(int(x["t"]), float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x["v"])) for x in roh][-48:]
                    bild = grafik.kerzenchart(kk, "%s %+.1f%% this hour" % (name, aend * 100), "Hourly candles, last 48 hours", intervall="1h")
                    self.p.dc.datei("POST", "/channels/%s/messages" % self.p.kanal(kanal), {"content": text, "allowed_mentions": {"parse": []}}, "move.png", bild)
                except Exception:
                    self.p.dc.post("/channels/%s/messages" % self.p.kanal(kanal), {"content": text, "allowed_mentions": {"parse": []}})
                sperre[coin] = jetzt
                n += 1
        if n:
            self.p.ergebnis["Momentum"] = "%d Hinweise" % n
