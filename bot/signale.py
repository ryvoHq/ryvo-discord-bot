"""Indikator-Ereignisse wie im RYVO Terminal (FVG, SMT) – beschreibend, mit Candlestick-Chart. Nur abgeschlossene Kerzen.

FVG (fair value gap) auf 1H: Kerze i-2 und i lassen eine Lücke (bullisch: Tief[i] > Hoch[i-2]; bärisch: Hoch[i] < Tief[i-2]),
  gemeldet nur, wenn die Lücke mindestens 0,6 × ATR(14, 1H) groß ist und gerade erst entstanden ist (i = letzte volle Kerze).
SMT-Divergenz auf 1H: Markt A macht ein neues 24-Stunden-Hoch (bzw. -Tief), der verwandte Markt B nicht – Paare BTC/ETH und S&P 500/Nasdaq 100.
"""
import time

import grafik
import markt

FVG_MAERKTE = [("BTC", "BTC"), ("ETH", "ETH"), ("SOL", "SOL"), ("xyz:SP500", "S&P 500"), ("xyz:XYZ100", "Nasdaq 100"), ("xyz:GOLD", "Gold")]
SMT_PAARE = [(("BTC", "BTC"), ("ETH", "ETH")), (("xyz:SP500", "S&P 500"), ("xyz:XYZ100", "Nasdaq 100"))]
STUNDE = 3600 * 1000


def kerzen_1h(coin, stunden=120):
    jetzt = int(time.time() * 1000)
    roh = markt._post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": jetzt - stunden * STUNDE, "endTime": jetzt}})
    k = [(int(x["t"]), float(x["o"]), float(x["h"]), float(x["l"]), float(x["c"]), float(x["v"])) for x in roh or []]
    return k


def voll(k):
    jetzt = time.time() * 1000
    return [x for x in k if x[0] + STUNDE <= jetzt]


def atr(k, n=14):
    tr = [max(k[i][2] - k[i][3], abs(k[i][2] - k[i - 1][4]), abs(k[i][3] - k[i - 1][4])) for i in range(1, len(k))]
    return sum(tr[-n:]) / n if len(tr) >= n else None


def fvg(k):
    k = voll(k)
    if len(k) < 20:
        return None
    a = atr(k)
    i = len(k) - 1
    h2, l2 = k[i - 2][2], k[i - 2][3]
    h0, l0 = k[i][2], k[i][3]
    if l0 > h2 and (l0 - h2) >= 0.6 * a:
        return {"art": "bullish", "unten": h2, "oben": l0, "t": k[i][0]}
    if h0 < l2 and (l2 - h0) >= 0.6 * a:
        return {"art": "bearish", "unten": h0, "oben": l2, "t": k[i][0]}
    return None


def smt(ka, kb):
    ka, kb = voll(ka), voll(kb)
    zeiten = set(x[0] for x in ka) & set(x[0] for x in kb)
    ka = [x for x in ka if x[0] in zeiten][-25:]
    kb = [x for x in kb if x[0] in zeiten][-25:]
    if len(ka) < 25:
        return None
    a_hoch = ka[-1][2] > max(x[2] for x in ka[:-1])
    b_hoch = kb[-1][2] > max(x[2] for x in kb[:-1])
    a_tief = ka[-1][3] < min(x[3] for x in ka[:-1])
    b_tief = kb[-1][3] < min(x[3] for x in kb[:-1])
    if a_hoch != b_hoch:
        return {"art": "bearish", "fuehrt": "a" if a_hoch else "b", "t": ka[-1][0]}
    if a_tief != b_tief:
        return {"art": "bullish", "fuehrt": "a" if a_tief else "b", "t": ka[-1][0]}
    return None


class Signale:
    def __init__(self, poster):
        self.p = poster
        self.z = poster.z

    def lauf(self):
        gemeldet = self.z.setdefault("signale", {})
        jetzt = time.time()
        n = 0
        cache = {}

        def hole(coin):
            if coin not in cache:
                cache[coin] = kerzen_1h(coin)
            return cache[coin]

        for coin, name in FVG_MAERKTE:
            schl = "fvg:" + coin
            if jetzt - gemeldet.get(schl, {}).get("zeit", 0) < 4 * 3600:
                continue
            try:
                k = hole(coin)
                s = fvg(k)
            except Exception:
                continue
            if not s or gemeldet.get(schl, {}).get("t") == s["t"]:
                continue
            kv = voll(k)[-96:]
            von = len(kv) - 3
            preis = k[-1][4]
            bild = grafik.kerzenchart(kv, "%s · 1H %s FVG" % (name, s["art"]), "Gap %s – %s · last %s" % (grafik.zahl(s["unten"]), grafik.zahl(s["oben"]), grafik.zahl(preis)),
                                      intervall="1h", zonen=[(von, s["unten"], s["oben"], "FVG")])
            text = "**%s · 1H %s FVG** %s – %s · last %s\n-# Fair value gap on the hourly chart, as shown in the RYVO Terminal. Not a signal, not financial advice." % (
                name, s["art"], grafik.zahl(s["unten"]), grafik.zahl(s["oben"]), grafik.zahl(preis))
            self.p.dc.datei("POST", "/channels/%s/messages" % self.p.kanal("indicators"), {"content": text, "allowed_mentions": {"parse": []}}, "fvg.png", bild)
            gemeldet[schl] = {"zeit": jetzt, "t": s["t"]}
            n += 1
        for (ca, na), (cb, nb) in SMT_PAARE:
            schl = "smt:%s:%s" % (ca, cb)
            if jetzt - gemeldet.get(schl, {}).get("zeit", 0) < 6 * 3600:
                continue
            try:
                ka, kb = hole(ca), hole(cb)
                s = smt(ka, kb)
            except Exception:
                continue
            if not s or gemeldet.get(schl, {}).get("t") == s["t"]:
                continue
            fuehrt, folgt = (na, nb) if s["fuehrt"] == "a" else (nb, na)
            wort = "high" if s["art"] == "bearish" else "low"
            kf = voll(ka if s["fuehrt"] == "a" else kb)[-72:]
            ko = voll(kb if s["fuehrt"] == "a" else ka)[-72:]
            i = len(kf) - 1
            punkt = kf[-1][2] if wort == "high" else kf[-1][3]
            bild = grafik.raster([(fuehrt + " · new 24h " + wort, kf), (folgt + " · no new " + wort, ko)],
                                 "SMT divergence · %s / %s · 1H" % (na, nb), "%s %s, %s did not confirm" % (fuehrt, "made a new 24-hour " + wort, folgt), intervall="1h")
            text = "**SMT divergence · %s / %s · 1H** (%s)\n%s made a new 24-hour %s at %s, %s did not.\n-# Descriptive, as shown in the RYVO Terminal. Not a signal, not financial advice." % (
                na, nb, s["art"], fuehrt, wort, grafik.zahl(punkt), folgt)
            self.p.dc.datei("POST", "/channels/%s/messages" % self.p.kanal("indicators"), {"content": text, "allowed_mentions": {"parse": []}}, "smt.png", bild)
            gemeldet[schl] = {"zeit": jetzt, "t": s["t"]}
            n += 1
        if n:
            self.p.ergebnis["Indikatoren"] = "%d Meldungen" % n
