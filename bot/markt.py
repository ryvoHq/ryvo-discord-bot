"""Marktdaten und Boards für den RYVO-Discord (Python 3.9+, matplotlib nur für Charts).

Quellen (wie in der öffentlichen Terminal-Beta, release/DATENRECHTE.md):
  Hyperliquid (Perpetual-Kontrakte; folgen dem Basiswert, sind nicht der amtliche Kurs) – 🟡 wie in der Beta
  alternative.me Fear & Greed – 🟢 nur mit Quelle direkt daneben
  EZB-Referenzkurse – 🟢 „Source: ECB statistics“ unverändert
Alles beschreibend: Kurse, Veränderungen, Abstände zu Durchschnitten. Keine Richtung, keine Ziele, keine Signale.
"""
import csv
import io
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timezone

HL = "https://api.hyperliquid.xyz/info"
UA = {"User-Agent": "RYVO-Discord-Bot/1.0 (+https://ryvo.studio)", "Content-Type": "application/json"}

GRUPPEN = [
    ("Crypto", [("BTC", "BTC"), ("ETH", "ETH"), ("SOL", "SOL"), ("HYPE", "HYPE"), ("XRP", "XRP"), ("DOGE", "DOGE")]),
    ("Indices", [("xyz:SP500", "S&P 500"), ("xyz:XYZ100", "Nasdaq 100"), ("xyz:JP225", "Nikkei 225"), ("xyz:KR200", "KOSPI 200")]),
    ("Commodities", [("xyz:GOLD", "Gold"), ("xyz:SILVER", "Silver"), ("xyz:CL", "WTI crude"), ("xyz:BRENTOIL", "Brent"), ("xyz:NATGAS", "Nat gas"), ("xyz:COPPER", "Copper")]),
    ("FX", [("xyz:EUR", "EUR/USD"), ("xyz:JPY", "USD/JPY")]),
    ("Stocks", [("xyz:NVDA", "NVDA"), ("xyz:AAPL", "AAPL"), ("xyz:MSFT", "MSFT"), ("xyz:GOOGL", "GOOGL"), ("xyz:AMZN", "AMZN"), ("xyz:META", "META"), ("xyz:TSLA", "TSLA"), ("xyz:AMD", "AMD"), ("xyz:PLTR", "PLTR"), ("xyz:COIN", "COIN"), ("xyz:MSTR", "MSTR")]),
]
SWING = [("BTC", "BTC"), ("ETH", "ETH"), ("SOL", "SOL"), ("xyz:SP500", "S&P 500"), ("xyz:XYZ100", "Nasdaq 100"),
         ("xyz:GOLD", "Gold"), ("xyz:SILVER", "Silver"), ("xyz:CL", "WTI crude"), ("xyz:EUR", "EUR/USD"),
         ("xyz:NVDA", "NVDA"), ("xyz:TSLA", "TSLA")]
QUELLE_HL = "Prices: Hyperliquid perpetual contracts. They track the underlying market but are not official exchange quotes."


def _post(daten, versuche=3):
    for i in range(versuche):
        try:
            req = urllib.request.Request(HL, data=json.dumps(daten).encode(), headers=UA, method="POST")
            with urllib.request.urlopen(req, timeout=30) as f:
                return json.loads(f.read())
        except Exception:
            if i == versuche - 1:
                raise
            time.sleep(3 * (i + 1))


def kontexte():
    """{name: {preis, vortag, funding, oi_usd, volumen}} für Haupt-Börse und HIP-3 (xyz)."""
    aus = {}
    for dex in ("", "xyz"):
        anfrage = {"type": "metaAndAssetCtxs"}
        if dex:
            anfrage["dex"] = dex
        meta, ctx = _post(anfrage)
        for u, c in zip(meta["universe"], ctx):
            try:
                preis = float(c.get("markPx") or c.get("midPx") or 0)
                aus[u["name"]] = {"preis": preis, "vortag": float(c.get("prevDayPx") or 0),
                                  "funding": float(c.get("funding") or 0), "oi_usd": float(c.get("openInterest") or 0) * preis,
                                  "volumen": float(c.get("dayNtlVlm") or 0)}
            except (TypeError, ValueError):
                continue
    return aus


def kerzen(coin, tage=420):
    jetzt = int(time.time() * 1000)
    roh = _post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1d", "startTime": jetzt - tage * 86400000, "endTime": jetzt}})
    return [(int(k["t"]), float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"])) for k in roh or []]


def angst_gier():
    req = urllib.request.Request("https://api.alternative.me/fng/?limit=2", headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as f:
        d = json.loads(f.read())["data"]
    return int(d[0]["value"]), d[0]["value_classification"], int(d[1]["value"])


def ezb_kurse():
    url = ("https://data-api.ecb.europa.eu/service/data/EXR/D.USD+JPY+GBP+CHF+CNY+AUD+CAD.EUR.SP00.A"
           "?lastNObservations=2&format=csvdata")
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as f:
        zeilen = list(csv.DictReader(io.StringIO(f.read().decode("utf-8"))))
    aus = {}
    for z in zeilen:
        aus.setdefault(z["CURRENCY"], []).append((z["TIME_PERIOD"], float(z["OBS_VALUE"])))
    for k in aus:
        aus[k].sort()
    return aus


# ---------- Formatierung ----------
def zahl(x):
    if x >= 10000:
        return "{:,.0f}".format(x)
    if x >= 100:
        return "{:,.1f}".format(x)
    if x >= 10:
        return "{:,.2f}".format(x)
    return "{:.4f}".format(x)


def proz(x):
    if x is None or math.isnan(x):
        return "   –  "
    return "{:+.1f}%".format(x * 100).rjust(6)


def geld(x):
    if x >= 1e9:
        return "${:.1f}B".format(x / 1e9)
    if x >= 1e6:
        return "${:.0f}M".format(x / 1e6)
    return "${:.0f}K".format(x / 1e3)


def uhrzeit(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%d %b %H:%M UTC")


def board_embeds(ctx, fg=None):
    embeds = []
    for titel, liste in GRUPPEN:
        zeilen, funding = [], []
        for coin, name in liste:
            c = ctx.get(coin)
            if not c or not c["preis"]:
                continue
            aend = c["preis"] / c["vortag"] - 1 if c["vortag"] else float("nan")
            zeile = "%-10s %10s %s" % (name[:10], zahl(c["preis"]), proz(aend))
            if titel == "Crypto":
                zeile += " %7s" % geld(c["oi_usd"])
                funding.append("%s %+.4f%%" % (name, c["funding"] * 100))
            zeilen.append(zeile)
        if zeilen:
            kopf = "%-10s %10s %6s" % ("Market", "Price", "24h")
            if titel == "Crypto":
                kopf += " %7s" % "OI"
            text = "```\n%s\n%s\n```" % (kopf, "\n".join(zeilen))
            if funding:
                text += "Funding per hour: " + " · ".join(funding)
            embeds.append({"color": 0xFFFFFF, "title": titel, "description": text})
    if fg:
        wert, klasse, gestern = fg
        embeds.append({"color": 0xFFFFFF, "title": "Sentiment",
                       "description": "Crypto Fear & Greed Index: **%d** (%s), yesterday %d.\nSource: [alternative.me](https://alternative.me/crypto/fear-and-greed-index/)" % (wert, klasse.lower(), gestern)})
    if embeds:
        embeds[-1]["footer"] = {"text": "Live board, updated every 5 min · last update %s · %s Descriptive only. Not investment advice, no signals." % (uhrzeit(), QUELLE_HL)}
    return embeds


def gleitend(werte, n):
    return sum(werte[-n:]) / n if len(werte) >= n else None


def swing_zeilen(daten):
    """Je Markt eine kurze Zeile: 1W, 1M, Abstand 50T/200T, Lage in der 20-Tage-Spanne."""
    zeilen = []
    def p(x):
        return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else "%+.1f%%" % (x * 100)
    for coin, name in SWING:
        k = daten.get(coin) or []
        if len(k) < 25:
            continue
        kz = kennzahlen(k)
        lage = (kz["preis"] - kz["tief20"]) / (kz["hoch20"] - kz["tief20"]) if kz["hoch20"] > kz["tief20"] else None
        zeilen.append("**%s** %s\n1W %s · 1M %s · 50D %s · 200D %s · 20D range %s" % (
            name, zahl(kz["preis"]), p(kz["1w"]), p(kz["1m"]), p(kz["50d"]), p(kz["200d"]),
            ("%d%%" % round(lage * 100)) if lage is not None else "–"))
    return zeilen


def swing_embed(daten):
    zeilen = swing_zeilen(daten)
    beschreibung = ("Daily snapshot for swing traders. **50D / 200D** = distance to the 50- and 200-day average. "
                    "**20D range** = where price sits between its 20-day low (0%) and high (100%).\n\n" + "\n\n".join(zeilen))
    return {"color": 0xFFFFFF, "title": "Swing board · " + datetime.now(timezone.utc).strftime("%a %d %b %Y"),
            "description": beschreibung[:4096],
            "footer": {"text": "Daily closes (UTC) · %s Descriptive only. Not investment advice, no signals." % QUELLE_HL}}


# ---------- Charts ----------
def chart_png(reihen, titel, unterzeile, tage=180):
    """reihen: [(name, kerzen)] – 1 bis 4 Felder, Schwarz/Weiß wie die RYVO-Marke. Durchschnitte über die ganze Reihe,
    gezeigt werden die letzten `tage` Tage. Gibt PNG-Bytes zurück."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter

    n = len(reihen)
    spalten = 2 if n > 1 else 1
    zeilen_n = int(math.ceil(n / spalten))
    hoehe = 3.6 * zeilen_n + 0.9 if n > 1 else 5.6
    fig, achsen = plt.subplots(zeilen_n, spalten, figsize=(12, hoehe), dpi=110, squeeze=False)
    fig.patch.set_facecolor("#000000")
    for i, (name, k) in enumerate(reihen):
        ax = achsen[i // spalten][i % spalten]
        ax.set_facecolor("#000000")
        x_alle = [datetime.fromtimestamp(t / 1000, timezone.utc) for t, *_ in k]
        y_alle = [c for *_, c in k]
        ab = max(0, len(y_alle) - tage)
        ax.plot(x_alle[ab:], y_alle[ab:], color="#FFFFFF", linewidth=1.4)
        for n_ma, farbe, stil in ((50, "#9A9A9A", "-"), (200, "#5A5A5A", "--")):
            if len(y_alle) >= n_ma:
                ma = [None] * (n_ma - 1) + [sum(y_alle[j - n_ma + 1:j + 1]) / n_ma for j in range(n_ma - 1, len(y_alle))]
                ax.plot(x_alle[ab:], ma[ab:], color=farbe, linewidth=1.0, linestyle=stil, label="%dD avg" % n_ma)
        y = y_alle
        aend = y[-1] / y[-22] - 1 if len(y) > 22 else 0
        ax.set_title("%s   %s   %+.1f%% (1M)" % (name, zahl(y[-1]), aend * 100), color="#FFFFFF", loc="left", fontsize=12, fontweight="bold")
        for seite in ("top", "right"):
            ax.spines[seite].set_visible(False)
        for seite in ("left", "bottom"):
            ax.spines[seite].set_color("#333333")
        ax.tick_params(colors="#9A9A9A", labelsize=8)
        ax.grid(color="#1A1A1A", linewidth=0.6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: zahl(v)))
        if i == 0:
            leg = ax.legend(loc="upper left", fontsize=8, frameon=False)
            for t in leg.get_texts():
                t.set_color("#9A9A9A")
    for j in range(n, zeilen_n * spalten):
        achsen[j // spalten][j % spalten].axis("off")
    fig.suptitle(titel, color="#FFFFFF", fontsize=15, fontweight="bold", x=0.012, ha="left", y=0.995)
    fig.text(0.012, 0.005, unterzeile, color="#6A6A6A", fontsize=8, ha="left", va="bottom")
    fig.text(0.988, 0.005, "RYVO", color="#FFFFFF", fontsize=11, fontweight="bold", ha="right", va="bottom")
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    puffer = io.BytesIO()
    fig.savefig(puffer, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return puffer.getvalue()


def kennzahlen(k):
    """Beschreibende Kennzahlen einer Tagesreihe."""
    s = [x[4] for x in k]
    p = s[-1]
    g50, g200 = gleitend(s, 50), gleitend(s, 200)
    h20, t20 = max(x[2] for x in k[-20:]), min(x[3] for x in k[-20:])
    return {"preis": p, "1w": p / s[-6] - 1 if len(s) > 6 else None, "1m": p / s[-22] - 1 if len(s) > 22 else None,
            "50d": p / g50 - 1 if g50 else None, "200d": p / g200 - 1 if g200 else None,
            "hoch20": h20, "tief20": t20, "hoch52": max(x[2] for x in k[-252:]), "tief52": min(x[3] for x in k[-252:])}


if __name__ == "__main__":
    # Selbsttest: Daten holen, Boards ausgeben, Chart als Datei schreiben
    ctx = kontexte()
    for e in board_embeds(ctx, angst_gier()):
        print(e["title"]); print(e["description"])
    d = {c: kerzen(c) for c, _ in SWING}
    print(swing_embed(d)["description"])
    open("/tmp/ryvo_chart_test.png", "wb").write(chart_png([("BTC", d["BTC"]), ("S&P 500", d["xyz:SP500"]), ("Gold", d["xyz:GOLD"]), ("Nasdaq 100", d["xyz:XYZ100"])],
                                                         "Markets · last 6 months", QUELLE_HL))
    print(ezb_kurse())
