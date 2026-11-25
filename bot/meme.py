"""Meme-Radar: neue Solana-Memecoins, die ihre Startkurve bei pump.fun ganz gefüllt haben – live aus der Kette gelesen.

Was hier passiert: Ein Faden hört über einen öffentlichen Solana-Knoten die Logs des pump.fun-Programms mit (logsSubscribe)
und liest drei Ereignisse nach der öffentlichen Programm-Beschreibung (github.com/pump-fun/pump-public-docs, idl/pump.json):
Start eines Coins, Kauf/Verkauf, Kurve voll. Daraus entstehen nur Zählungen: wie lange die Kurve gebraucht hat, wie viele
verschiedene Käufer es mindestens gab, wie viel SOL mindestens hineinfloss (öffentliche Knoten lassen Nachrichten aus – die
Zahlen sind Untergrenzen und tragen ein „+“). Gepostet wird in #meme-momentum, beschreibend:
- sofort, wenn eine Kurve mit vielen Käufern voll wird (höchstens ein paar je Stunde),
- einmal je Stunde eine Übersicht der letzten Stunde.

Keine Empfehlung, kein Signal. Ein Coin, der seine Kurve füllt, kann Minuten später wertlos sein – das steht unter jedem Beitrag.
Nur Standardbibliothek. Der Faden lebt, solange der Cloud-Lauf lebt; was er vor seinem Start verpasst hat, kennt er nicht
(dann fehlen Dauer und Käufer und der Coin erscheint nur in der Stunden-Übersicht als „seen late“).
"""
import base64
import json
import os
import socket
import ssl
import struct
import threading
import time

PROGRAMM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
KNOTEN = ["solana-rpc.publicnode.com", "api.mainnet-beta.solana.com", "solana-rpc.publicnode.com"]   # drei Leitungen zugleich: eine allein tröpfelt oft nur
STILL_SEK = 12                  # so lange ohne Nachricht: Leitung neu aufbauen
ART = {bytes.fromhex("1b72a94ddeeb6376"): "start", bytes.fromhex("bddb7fd34ee661ee"): "handel", bytes.fromhex("5f72619cd42e9808"): "voll"}
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
MERKEN_SEK = 3 * 3600           # so lange bleibt ein Coin ohne volle Kurve im Gedächtnis
KAEUFER_AB = 250                # ab so vielen verschiedenen Käufern gibt es sofort einen Beitrag
DAUER_AB = 180                  # … und nur, wenn die Kurve mindestens so viele Sekunden gebraucht hat (sonst hat sie meist einer allein gefüllt)
JE_STUNDE = 4                   # höchstens so viele Sofort-Beiträge je Stunde
FUSS = "-# On-chain events read from a public Solana node. A filled curve says nothing about what comes next – most new tokens go to zero. Not a signal, not financial advice."


def b58(roh):
    n, s = int.from_bytes(roh, "big"), ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(roh) - len(roh.lstrip(b"\0"))) + s


def _text(d, i):
    n = struct.unpack_from("<I", d, i)[0]
    return d[i + 4:i + 4 + n].decode("utf-8", "replace"), i + 4 + n


def ereignis(zeile):
    """Eine Log-Zeile „Program data: …“ → dict(art, …) oder None. Liest nur die vorderen Felder, die hier gebraucht werden."""
    if not zeile.startswith("Program data: "):
        return None
    try:
        d = base64.b64decode(zeile[14:])
        art = ART.get(d[:8])
        if art == "start":
            name, i = _text(d, 8)
            symbol, i = _text(d, i)
            _, i = _text(d, i)
            return {"art": art, "name": name[:40], "symbol": symbol[:16], "mint": b58(d[i:i + 32]), "ersteller": b58(d[i + 96:i + 128])}
        if art == "handel":
            return {"art": art, "mint": b58(d[8:40]), "sol": struct.unpack_from("<Q", d, 40)[0] / 1e9, "kauf": bool(d[56]), "wer": b58(d[57:89])}
        if art == "voll":
            return {"art": art, "mint": b58(d[40:72])}
    except (ValueError, IndexError, struct.error):
        return None
    return None


class Buch:
    """Merkt sich je Coin Start, Käufer und SOL; liefert die vollen Kurven. Ohne Netz, damit es sich prüfen lässt."""

    def __init__(self):
        self.coins, self.fertig, self.schloss = {}, [], threading.Lock()
        self.zaehler = {"start": 0, "handel": 0, "voll": 0}
        self.gesehen, self.reihe, self.letzte = set(), [], 0.0

    def neu(self, sig, jetzt):
        """Diese Transaktion zum ersten Mal gesehen? (Mehrere Leitungen liefern dieselbe.)"""
        with self.schloss:
            self.letzte = jetzt
            if sig in self.gesehen:
                return False
            self.gesehen.add(sig)
            self.reihe.append(sig)
            if len(self.reihe) > 90000:
                for alt in self.reihe[:30000]:
                    self.gesehen.discard(alt)
                del self.reihe[:30000]
            return True

    def nehmen(self, e, jetzt):
        with self.schloss:
            self.zaehler[e["art"]] += 1
            if e["art"] == "start":
                self.coins.setdefault(e["mint"], {"name": e["name"], "symbol": e["symbol"], "t": jetzt, "ersteller": e["ersteller"], "kaeufer": set(), "sol": 0.0,
                                                  "ersteller_verkauft": False})
            elif e["art"] == "handel":
                c = self.coins.get(e["mint"])
                if c is None:
                    return
                if e["kauf"]:
                    if len(c["kaeufer"]) < 5000:
                        c["kaeufer"].add(e["wer"])
                    c["sol"] += e["sol"]
                else:
                    c["sol"] -= e["sol"]
                    if e["wer"] == c["ersteller"]:
                        c["ersteller_verkauft"] = True
            else:
                c = self.coins.pop(e["mint"], None)
                if c is None:
                    self.fertig.append({"mint": e["mint"], "t": jetzt, "spaet": True})
                else:
                    self.fertig.append({"mint": e["mint"], "t": jetzt, "spaet": False, "name": c["name"], "symbol": c["symbol"], "dauer": jetzt - c["t"],
                                        "kaeufer": len(c["kaeufer"]), "sol": c["sol"], "ersteller_verkauft": c["ersteller_verkauft"]})
            if self.zaehler["handel"] % 5000 == 0:
                for mint in [m for m, c in self.coins.items() if jetzt - c["t"] > MERKEN_SEK]:
                    del self.coins[mint]

    def holen(self):
        with self.schloss:
            out, self.fertig = self.fertig, []
            return out


# ---------- kleinster WebSocket-Client (Text-Nachrichten, ohne Kompression) ----------
class Leitung:
    def __init__(self, host):
        roh = socket.create_connection((host, 443), timeout=20)
        self.s = ssl.create_default_context().wrap_socket(roh, server_hostname=host)
        schluessel = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(("GET / HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                        "Sec-WebSocket-Version: 13\r\nUser-Agent: RYVO-Discord-Bot/1.0\r\n\r\n" % (host, schluessel)).encode())
        self.f = self.s.makefile("rb")
        kopf = self.f.readline()
        if b" 101 " not in kopf:
            raise ConnectionError("kein WebSocket: %r" % kopf[:60])
        while self.f.readline() not in (b"\r\n", b""):
            pass
        self.s.settimeout(STILL_SEK)

    def senden(self, daten, opcode=1):
        daten = daten.encode() if isinstance(daten, str) else daten
        maske = os.urandom(4)
        n = len(daten)
        kopf = bytes([0x80 | opcode]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(kopf + maske + bytes(b ^ maske[i % 4] for i, b in enumerate(daten)))

    def _genau(self, n):
        d = self.f.read(n)
        if d is None or len(d) < n:
            raise ConnectionError("Leitung zu")
        return d

    def lesen(self):
        """Nächste ganze Text-Nachricht (setzt Teilstücke zusammen, beantwortet Pings)."""
        teile = []
        while True:
            a, b = self._genau(2)
            opcode, n = a & 0x0F, b & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._genau(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._genau(8))[0]
            daten = self._genau(n) if n else b""
            if opcode == 9:
                self.senden(daten, opcode=10)
                continue
            if opcode == 8:
                raise ConnectionError("Knoten hat geschlossen")
            if opcode in (0, 1, 2):
                teile.append(daten)
                if a & 0x80:
                    return b"".join(teile)

    def zu(self):
        try:
            self.s.close()
        except OSError:
            pass


class Leser(threading.Thread):
    """Hört die Logs eines Knotens mit und füttert das Buch. Bleibt die Leitung still oder fällt sie, verbindet er neu."""

    def __init__(self, buch, host):
        super().__init__(daemon=True, name="meme-leser")
        self.buch, self.host, self.stand = buch, host, {"verbunden": 0, "fehler": ""}

    def run(self):
        versuch = 0
        while True:
            host = self.host
            versuch += 1
            leitung, bekam = None, 0
            try:
                leitung = Leitung(host)
                leitung.senden(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe", "params": [{"mentions": [PROGRAMM]}, {"commitment": "confirmed"}]}))
                self.stand["verbunden"] += 1
                bekam = 0
                while True:
                    self.nachricht(json.loads(leitung.lesen()))
                    bekam += 1
            except Exception as e:  # noqa: BLE001 – der Faden darf nie sterben
                self.stand["fehler"] = "%s: %s" % (type(e).__name__, str(e)[:80])
            finally:
                if leitung:
                    leitung.zu()
            time.sleep(1 if bekam > 5 else 6)                  # lieferte die Leitung, gleich wieder; sonst kurz warten (kein Dauerfeuer auf den Knoten)

    def nachricht(self, m):
        wert = ((m.get("params") or {}).get("result") or {}).get("value") or {}
        sig = wert.get("signature")
        jetzt = time.time()
        if not sig or not self.buch.neu(sig, jetzt) or wert.get("err"):
            return
        for zeile in wert.get("logs") or ():
            e = ereignis(zeile)
            if e:
                self.buch.nehmen(e, jetzt)


def minuten(sek):
    return "%d min" % round(sek / 60) if sek >= 90 else "%d s" % round(sek)


def zeile(f):
    """Ein voller Coin als eine Zeile für Discord."""
    link = "[`%s…%s`](https://solscan.io/token/%s)" % (f["mint"][:4], f["mint"][-4:], f["mint"])
    if f["spaet"]:
        return "%s · seen late" % link
    name = f["symbol"].replace("*", "").replace("`", "").replace("[", "(").replace("]", ")").replace("@", "") or "?"
    return "**$%s** %s · filled in %s · %d+ buyers · %.0f+ SOL in%s" % (name, link, minuten(f["dauer"]), f["kaeufer"], max(0.0, f["sol"]),
                                                                    " · creator sold on the way" if f["ersteller_verkauft"] else "")


_FADEN = {}


def faden():
    """Der eine Leser dieses Prozesses (startet beim ersten Aufruf)."""
    if "leser" not in _FADEN:
        buch = Buch()
        leser = [Leser(buch, host) for host in KNOTEN]
        for x in leser:
            x.start()
        _FADEN.update(buch=buch, leser=leser, seit=time.time())
    return _FADEN["buch"], _FADEN["leser"]


class Meme:
    def __init__(self, poster, quelle=faden, uhr=time.time):
        self.p, self.z, self.quelle, self.uhr = poster, poster.z, quelle, uhr

    def lauf(self):
        if not self.p.kanaele.get("meme-momentum"):
            return
        buch, leser = self.quelle()
        jetzt = self.uhr()
        z = self.z.setdefault("meme", {"sofort": [], "stunde": [], "uebersicht": 0})
        neu = buch.holen()
        z["stunde"] = [f for f in z["stunde"] if jetzt - f["t"] < 3600] + neu
        z["sofort"] = [t for t in z["sofort"] if jetzt - t < 3600]
        gepostet = 0
        for f in sorted((f for f in neu if not f["spaet"] and f["kaeufer"] >= KAEUFER_AB and f["dauer"] >= DAUER_AB), key=lambda f: -f["kaeufer"]):
            if len(z["sofort"]) >= JE_STUNDE:
                break
            self.senden("**Curve filled** · " + zeile(f) + "\n" + FUSS)
            z["sofort"].append(jetzt)
            gepostet += 1
        if jetzt - z.get("uebersicht", 0) >= 3600 and z["stunde"] and jetzt - _FADEN.get("seit", jetzt - 3600) >= 900:
            voll = [f for f in z["stunde"] if not f["spaet"]]
            oben = sorted(voll, key=lambda f: -f["kaeufer"])[:5]
            kopf = "**pump.fun · last hour** · %d curves filled" % len(z["stunde"])
            if voll:
                dauern = sorted(f["dauer"] for f in voll)
                kopf += " · median time to fill %s" % minuten(dauern[len(dauern) // 2])
            self.senden("\n".join([kopf] + [zeile(f) for f in oben] + [FUSS]))
            z["uebersicht"] = jetzt
            gepostet += 1
        self.p.ergebnis["Meme-Radar"] = "%d gepostet · %d Kurven/Std. · Leitung %s" % (
            gepostet, len(z["stunde"]), "ok" if jetzt - buch.letzte < 120 else "still (%s)" % (next((x.stand["fehler"] for x in leser if x.stand["fehler"]), "") or "startet"))

    def senden(self, text):
        self.p.dc.post("/channels/%s/messages" % self.p.kanal("meme-momentum"), {"content": text[:1990], "allowed_mentions": {"parse": []}, "flags": 4})
