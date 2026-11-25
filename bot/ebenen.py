"""Tages-Ebenen („desk levels“): jeden Tag je Markt ein Stunden-Chart mit den Marken, auf die Händler am Tag schauen –
Vortageshoch und -tief, Wochen- und Monatseröffnung, Vorwochenhoch und -tief, offene 1H-FVGs – als Linien und Boxen im Stil
des RYVO Terminals. Nur beschreibend: wo die Marken liegen und wo der Kurs dazu steht. Kein Signal, keine Richtung.

Krypto (BTC, ETH, SOL) ab 06 UTC in #crypto-trading, Indizes und Gold ab 12 UTC (vor der US-Eröffnung) in #futures-indices.
Daten: Stunden-Kerzen von Hyperliquid (dieselbe Quelle wie die übrigen Charts des Bots). Läuft in der Cloud-Schleife mit.
"""
import time
from datetime import datetime, timedelta, timezone

import grafik
import markt
import signale

STUNDE = 3600 * 1000
TAGE = 36                      # so viele Tage Stunden-Kerzen werden geholt (Monatseröffnung, Vorwoche)
SICHTBAR = 120                 # so viele Stunden zeigt der Chart
FVG_AB = 0.6                   # eine Lücke zählt ab 0,6 ATR (wie in signale.py)
GRUPPEN = [
    ("ebenen_krypto", 6, "crypto-trading", [("BTC", "BTC"), ("ETH", "ETH"), ("SOL", "SOL")]),
    ("ebenen_trad", 12, "futures-indices", [("xyz:SP500", "S&P 500"), ("xyz:XYZ100", "Nasdaq 100"), ("xyz:GOLD", "Gold")]),
]
FUSS = "-# Levels from hourly Hyperliquid perps, as shown in the RYVO Terminal. Descriptive only – not a signal, not financial advice."


def _tag(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date()


def marken(k, jetzt=None):
    """Aus abgeschlossenen Stunden-Kerzen (älteste zuerst) die Marken des Tages. → dict oder None, wenn zu wenig Daten.
    pdh/pdl = Hoch/Tief des letzten ganzen UTC-Tages vor heute, wo/mo = erste Kerze dieser Woche/dieses Monats,
    pwh/pwl = Hoch/Tief der Vorwoche (Montag–Sonntag UTC). Was das Band nicht hergibt, fehlt im Ergebnis."""
    if len(k) < 30:
        return None
    heute = _tag(jetzt * 1000 if jetzt else k[-1][0])
    je_tag = {}
    for x in k:
        je_tag.setdefault(_tag(x[0]), []).append(x)
    out = {"letzter": k[-1][4]}
    frueher = sorted(t for t in je_tag if t < heute and len(je_tag[t]) >= 12)     # ein Tag zählt nur mit mindestens 12 Stunden (Börsen-Märkte haben Pausen)
    if frueher:
        gestern = je_tag[frueher[-1]]
        out["pdh"], out["pdl"] = max(x[2] for x in gestern), min(x[3] for x in gestern)
    montag = heute - timedelta(days=heute.weekday())
    woche = [x for x in k if _tag(x[0]) >= montag]
    if woche and _tag(k[0][0]) < montag:
        out["wo"] = woche[0][1]
    vorwoche = [x for x in k if montag - timedelta(days=7) <= _tag(x[0]) < montag]
    if len(vorwoche) >= 48 and _tag(k[0][0]) <= montag - timedelta(days=7):
        out["pwh"], out["pwl"] = max(x[2] for x in vorwoche), min(x[3] for x in vorwoche)
    erster = heute.replace(day=1)
    monat = [x for x in k if _tag(x[0]) >= erster]
    if monat and _tag(k[0][0]) < erster:
        out["mo"] = monat[0][1]
    return out


def offene_fvgs(k, fenster=SICHTBAR):
    """Alle 1H-Lücken der letzten `fenster` Kerzen ab FVG_AB × ATR, die der Kurs seither nicht ganz geschlossen hat.
    → [dict(art, unten, oben, i)] mit i = Index der dritten Kerze in k."""
    a = signale.atr(k)
    if not a:
        return []
    out = []
    for i in range(max(2, len(k) - fenster), len(k)):
        h2, l2, h0, l0 = k[i - 2][2], k[i - 2][3], k[i][2], k[i][3]
        danach = k[i + 1:]
        if l0 > h2 and l0 - h2 >= FVG_AB * a:
            if not danach or min(x[3] for x in danach) > h2:                       # bullische Lücke: offen, solange kein Tief bis an ihren unteren Rand kam
                unten, oben = h2, min([l0] + [x[3] for x in danach])               # der schon gefüllte Teil zählt nicht mehr
                if oben > unten:
                    out.append({"art": "bullish", "unten": unten, "oben": oben, "i": i})
        elif h0 < l2 and l2 - h0 >= FVG_AB * a:
            if not danach or max(x[2] for x in danach) < l2:
                unten, oben = max([h0] + [x[2] for x in danach]), l2
                if oben > unten:
                    out.append({"art": "bearish", "unten": unten, "oben": oben, "i": i})
    return out


def naechste(luecken, preis):
    """Die nächste offene Lücke über und unter dem Kurs. → (oben oder None, unten oder None)"""
    ueber = sorted((x for x in luecken if x["unten"] >= preis), key=lambda x: x["unten"])
    unter = sorted((x for x in luecken if x["oben"] <= preis), key=lambda x: -x["oben"])
    return (ueber[0] if ueber else None), (unter[0] if unter else None)


NAMEN = (("pdh", "PDH"), ("pdl", "PDL"), ("wo", "Weekly open"), ("mo", "Monthly open"), ("pwh", "PWH"), ("pwl", "PWL"))


def linien(m, unten, oben):
    """Marken im sichtbaren Bereich als Linien für grafik.kerzenchart; Marken, die fast gleich liegen, teilen sich ein Etikett."""
    spanne = oben - unten
    sicht = sorted(((m[s], text) for s, text in NAMEN if s in m and unten - spanne * 0.04 <= m[s] <= oben + spanne * 0.04), key=lambda x: x[0])
    out = []
    for preis, text in sicht:
        if out and preis - out[-1][0] < spanne * 0.025:
            out[-1] = (out[-1][0], out[-1][1] + " / " + text)
        else:
            out.append((preis, text))
    return [(p, "%s %s" % (t, grafik.zahl(p))) for p, t in out]


def lage(m):
    """Ein Satz, wo der Kurs zu den Marken steht – nur Lage, keine Richtung."""
    p, teile = m["letzter"], []
    if "pdh" in m:
        teile.append("above yesterday's high" if p > m["pdh"] else "below yesterday's low" if p < m["pdl"] else "inside yesterday's range")
    for s, text in (("wo", "weekly open"), ("mo", "monthly open")):
        if s in m:
            teile.append("%s the %s" % ("above" if p >= m[s] else "below", text))
    return ", ".join(teile)


def text(name, m, ueber, unter, tag):
    z = grafik.zahl
    zeilen = ["**%s · levels · %s**" % (name, tag), "Last %s · %s" % (z(m["letzter"]), lage(m))]
    paare = [("PDH", "pdh"), ("PDL", "pdl"), ("Weekly open", "wo"), ("Monthly open", "mo"), ("PWH", "pwh"), ("PWL", "pwl")]
    zeilen.append(" · ".join("%s %s" % (t, z(m[s])) for t, s in paare if s in m))
    fvg = []
    if ueber:
        fvg.append("above %s – %s" % (z(ueber["unten"]), z(ueber["oben"])))
    if unter:
        fvg.append("below %s – %s" % (z(unter["unten"]), z(unter["oben"])))
    zeilen.append("Open 1H FVG: " + (" · ".join(fvg) if fvg else "none in the last 5 days"))
    zeilen.append(FUSS)
    return "\n".join(zeilen)


def bild(name, k, m, ueber, unter, tag):
    kv = k[-SICHTBAR:]
    versatz = len(k) - len(kv)
    unten, oben = min(x[3] for x in kv), max(x[2] for x in kv)
    zonen = [(max(0, x["i"] - versatz), x["unten"], x["oben"], "FVG") for x in (ueber, unter) if x]
    return grafik.kerzenchart(kv, "%s · 1H · levels" % name, "%s · %s" % (tag, lage(m)), intervall="1h", zonen=zonen, linien=linien(m, unten, oben))


def beitrag(coin, name, jetzt=None):
    """→ (Text, PNG) oder None, wenn die Daten nicht reichen."""
    jetzt = jetzt or time.time()
    k = signale.voll(signale.kerzen_1h(coin, TAGE * 24))
    if len(k) < 60 or jetzt * 1000 - k[-1][0] > 6 * STUNDE:                      # Markt hat keine frischen Kerzen (Wochenende, Feiertag): kein Beitrag
        return None
    m = marken(k, jetzt)
    if not m or "pdh" not in m:
        return None
    ueber, unter = naechste(offene_fvgs(k), m["letzter"])
    tag = datetime.fromtimestamp(jetzt, timezone.utc).strftime("%a %d %b")
    return text(name, m, ueber, unter, tag), bild(name, k, m, ueber, unter, tag)


class Ebenen:
    def __init__(self, poster):
        self.p = poster
        self.z = poster.z

    def lauf(self):
        for schluessel, ab_stunde, kanal, maerkte in GRUPPEN:
            heute = self.p._faellig(schluessel, ab_stunde)
            if not heute or not self.p.kanaele.get(kanal):
                continue
            n = 0
            for coin, name in maerkte:
                try:
                    b = beitrag(coin, name)
                except Exception:
                    b = None
                if not b:
                    continue
                self.p.dc.datei("POST", "/channels/%s/messages" % self.p.kanal(kanal), {"content": b[0], "allowed_mentions": {"parse": []}},
                                "levels-%s.png" % name.lower().replace("&", "").replace(" ", "-"), b[1])
                n += 1
            self.z[schluessel] = heute
            self.p.ergebnis["Ebenen " + kanal] = "%d Märkte" % n
