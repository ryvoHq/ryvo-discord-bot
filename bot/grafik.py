"""Candlestick-Grafiken im Stil des RYVO Terminals (Schwarz/Weiß, Preisachse rechts, letzter Kurs als Marke).

kerzen: Liste (t_ms, o, h, l, c[, v]) – ältere zuerst.
"""
import io
import math
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

HG = "#0A0A0A"
RASTER = "#171717"
ACHSE = "#7A7A7A"
AUF = "#EDEDED"
AB = "#3C3C3C"
AB_RAND = "#9A9A9A"
TP = "#2BB673"
SL = "#E5484D"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})


def zahl(x):
    if x >= 10000:
        return "{:,.0f}".format(x)
    if x >= 100:
        return "{:,.1f}".format(x)
    if x >= 10:
        return "{:,.2f}".format(x)
    if x >= 1:
        return "{:,.4f}".format(x)
    return "{:.5f}".format(x)


def _achse(ax):
    ax.set_facecolor(HG)
    for s in ("top", "left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.spines["right"].set_color("#262626")
    ax.yaxis.tick_right()
    ax.tick_params(colors=ACHSE, labelsize=8, length=0)
    ax.grid(color=RASTER, linewidth=0.7)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: zahl(v)))
    ax.yaxis.set_major_locator(MaxNLocator(7))


def _zeitachse(ax, kerzen, intervall):
    n = len(kerzen)
    schritte = max(1, n // 7)
    pos = list(range(schritte // 2, n, schritte))               # nicht bei 0 beginnen: das erste Etikett wurde am linken Rand abgeschnitten
    fmt = "%d %b" if intervall in ("1d", "4h") else "%d %b %H:%M"
    ax.set_xticks(pos)
    ax.set_xticklabels([datetime.fromtimestamp(kerzen[i][0] / 1000, timezone.utc).strftime(fmt) for i in pos])
    ax.set_xlim(-1, n + max(3, n // 10))


def _kerzen(ax, kerzen, bis=None):
    bis = len(kerzen) if bis is None else bis
    breite = 0.62
    for i, k in enumerate(kerzen[:bis]):
        _, o, h, l, c = k[:5]
        auf = c >= o
        ax.vlines(i, l, h, color=AUF if auf else AB_RAND, linewidth=0.9, zorder=2)
        unten, hoehe = min(o, c), max(abs(c - o), (h - l) * 0.004 or 1e-12)
        ax.add_patch(Rectangle((i - breite / 2, unten), breite, hoehe, facecolor=AUF if auf else AB,
                               edgecolor=AUF if auf else AB_RAND, linewidth=0.6, zorder=3))


def _preismarke(ax, preis, n):
    ax.axhline(preis, color="#5A5A5A", linewidth=0.7, linestyle=(0, (2, 2)), zorder=1)
    ax.annotate(zahl(preis), xy=(1.0, preis), xycoords=("axes fraction", "data"), xytext=(2, 0), textcoords="offset points",
                va="center", ha="left", fontsize=8, color="#000000", fontweight="bold",
                bbox=dict(boxstyle="square,pad=0.25", facecolor="#FFFFFF", edgecolor="none"), annotation_clip=False, zorder=10)


def _rahmen(fig, titel, unterzeile, quelle):
    fig.patch.set_facecolor(HG)
    fig.text(0.012, 0.975, titel, color="#FFFFFF", fontsize=13, fontweight="bold", ha="left", va="top")
    if unterzeile:
        fig.text(0.012, 0.925, unterzeile, color="#9A9A9A", fontsize=9, ha="left", va="top")
    fig.text(0.012, 0.012, quelle, color="#555555", fontsize=7, ha="left", va="bottom")
    fig.text(0.985, 0.012, "RYVO", color="#FFFFFF", fontsize=11, fontweight="bold", ha="right", va="bottom")


def _png(fig):
    puffer = io.BytesIO()
    fig.savefig(puffer, format="png", facecolor=fig.get_facecolor(), dpi=fig.dpi)
    plt.close(fig)
    return puffer.getvalue()


def _volumen(ax, kerzen):
    if len(kerzen[0]) < 6:
        ax.set_visible(False)
        return
    _achse(ax)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: ""))
    for i, k in enumerate(kerzen):
        ax.bar(i, k[5], width=0.62, color="#3A3A3A" if k[4] < k[1] else "#6E6E6E", zorder=2)
    ax.set_ylim(0, max(k[5] for k in kerzen) * 1.15 or 1)


QUELLE = "Hyperliquid perpetual contracts · not official exchange quotes · not financial advice"


def kerzenchart(kerzen, titel, unterzeile="", intervall="1h", zonen=(), position=None, marken=(), linien=(), mittel=(), quelle=QUELLE):
    """zonen: [(von_index, unten, oben, text)] · position: dict(von, einstieg, stop, ziel, seite) ·
    marken: [(index, preis, 'v'|'^', text)] · linien: [(preis, text)] · mittel: [50, 200] (gleitende Durchschnitte der Schlusskurse)"""
    fig = plt.figure(figsize=(11, 6.2), dpi=120)
    _rahmen(fig, titel, unterzeile, quelle)
    ax = fig.add_axes([0.012, 0.15, 0.905, 0.72])
    axv = fig.add_axes([0.012, 0.06, 0.905, 0.08], sharex=ax)
    _achse(ax)
    _kerzen(ax, kerzen)
    n = len(kerzen)
    schluss = [k[4] for k in kerzen]
    for m, farbe in zip(mittel, ("#BDBDBD", "#6A6A6A")):
        if n >= m:
            werte = [sum(schluss[i - m + 1:i + 1]) / m if i >= m - 1 else float("nan") for i in range(n)]
            ax.plot(range(n), werte, color=farbe, linewidth=1.0, zorder=4, label="%d avg" % m)
    for von, unten, oben, text in zonen:
        ax.add_patch(Rectangle((von - 0.5, unten), n - von + 2, oben - unten, facecolor="#FFFFFF", alpha=0.10,
                               edgecolor="#FFFFFF", linewidth=0.8, linestyle=(0, (3, 2)), zorder=1))
        ax.text(n + 1.5, (unten + oben) / 2, text, color="#FFFFFF", fontsize=8, va="center", ha="right", fontweight="bold", zorder=6)
    if position:
        von = position["von"]
        e, s, z = position["einstieg"], position["stop"], position["ziel"]
        rechts = n + max(3, n // 10) - 1 - von
        ax.add_patch(Rectangle((von - 0.5, min(e, z)), rechts, abs(z - e), facecolor=TP, alpha=0.22, edgecolor=TP, linewidth=0.8, zorder=1))
        ax.add_patch(Rectangle((von - 0.5, min(e, s)), rechts, abs(e - s), facecolor=SL, alpha=0.22, edgecolor=SL, linewidth=0.8, zorder=1))
        ax.hlines(e, von - 0.5, von - 0.5 + rechts, color="#FFFFFF", linewidth=0.9, zorder=5)
        for preis, text, farbe in ((z, "TP " + zahl(z), TP), (s, "SL " + zahl(s), SL), (e, "Entry " + zahl(e), "#FFFFFF")):
            ax.text(von + 0.3, preis, text, color=farbe, fontsize=8, va="bottom", ha="left", fontweight="bold", zorder=6)
    for i, preis, art, text in marken:
        ax.scatter([i], [preis], marker=art, s=46, color="#FFFFFF", zorder=7)
        if text:
            ax.annotate(text, (i, preis), textcoords="offset points", xytext=(0, 9 if art == "v" else -14), ha="center",
                        color="#FFFFFF", fontsize=8, fontweight="bold", zorder=7)
    for preis, text in linien:
        ax.axhline(preis, color="#8A8A8A", linewidth=0.8, linestyle=(0, (5, 3)), zorder=1)
        ax.text(0, preis, " " + text, color="#BDBDBD", fontsize=7.5, va="bottom", ha="left", zorder=6)
    unten = min(k[3] for k in kerzen)
    oben = max(k[2] for k in kerzen)
    if position:
        unten, oben = min(unten, position["stop"], position["ziel"]), max(oben, position["stop"], position["ziel"])
    rand = (oben - unten) * 0.06
    ax.set_ylim(unten - rand, oben + rand)
    _preismarke(ax, schluss[-1], n)
    _zeitachse(ax, kerzen, intervall)
    plt.setp(ax.get_xticklabels(), visible=False)
    _volumen(axv, kerzen)
    _zeitachse(axv, kerzen, intervall)
    if mittel:
        leg = ax.legend(loc="upper left", fontsize=7.5, frameon=False)
        for t in leg.get_texts():
            t.set_color("#9A9A9A")
    return _png(fig)


def raster(felder, titel, unterzeile="", intervall="1d", quelle=QUELLE):
    """felder: [(name, kerzen)] – 2 bis 4 kleine Candlestick-Charts in einem Bild."""
    n = len(felder)
    spalten = 2
    zeilen = int(math.ceil(n / 2))
    fig = plt.figure(figsize=(12, 3.5 * zeilen + 0.9), dpi=110)
    _rahmen(fig, titel, unterzeile, quelle)
    oben_rand = 0.86 if zeilen > 1 else 0.80
    hoehe = (oben_rand - 0.06) / zeilen
    for idx, (name, k) in enumerate(felder):
        r, s = idx // spalten, idx % spalten
        ax = fig.add_axes([0.012 + s * 0.495, oben_rand - (r + 1) * hoehe + 0.03, 0.43, hoehe - 0.07])
        _achse(ax)
        _kerzen(ax, k)
        schluss = [x[4] for x in k]
        aend = schluss[-1] / schluss[0] - 1
        ax.set_title("%s   %s   %+.1f%%" % (name, zahl(schluss[-1]), aend * 100), color="#FFFFFF", loc="left", fontsize=10, fontweight="bold", pad=4)
        unten, oben = min(x[3] for x in k), max(x[2] for x in k)
        rand = (oben - unten) * 0.06
        ax.set_ylim(unten - rand, oben + rand)
        _preismarke(ax, schluss[-1], len(k))
        _zeitachse(ax, k, intervall)
    return _png(fig)


def video(kerzen, titel, unterzeile="", intervall="1d", sekunden=8, fps=12, quelle=QUELLE):
    """Kerzen bauen sich nacheinander auf, am Ende 1,5 s Standbild. Gibt (bytes, dateiendung) zurück: mp4 mit ffmpeg, sonst gif."""
    from matplotlib.animation import FuncAnimation, FFMpegWriter, PillowWriter

    n = len(kerzen)
    bilder = int(sekunden * fps)
    halten = int(1.5 * fps)
    fig = plt.figure(figsize=(9.6, 5.4), dpi=100)
    _rahmen(fig, titel, unterzeile, quelle)
    ax = fig.add_axes([0.012, 0.09, 0.905, 0.78])
    unten, oben = min(k[3] for k in kerzen), max(k[2] for k in kerzen)
    rand = (oben - unten) * 0.06

    def zeichne(f):
        ax.clear()
        _achse(ax)
        bis = max(1, min(n, int(n * (f + 1) / (bilder - halten))))
        _kerzen(ax, kerzen, bis)
        ax.set_ylim(unten - rand, oben + rand)
        _zeitachse(ax, kerzen, intervall)
        _preismarke(ax, kerzen[bis - 1][4], n)
        return []

    anim = FuncAnimation(fig, zeichne, frames=bilder, blit=False)
    tmp = tempfile.mkdtemp()
    try:
        if shutil.which("ffmpeg"):
            pfad = os.path.join(tmp, "v.mp4")
            anim.save(pfad, writer=FFMpegWriter(fps=fps, bitrate=1800, extra_args=["-pix_fmt", "yuv420p", "-movflags", "+faststart"]))
            endung = "mp4"
        else:
            pfad = os.path.join(tmp, "v.gif")
            anim.save(pfad, writer=PillowWriter(fps=fps))
            endung = "gif"
        plt.close(fig)
        return open(pfad, "rb").read(), endung
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
