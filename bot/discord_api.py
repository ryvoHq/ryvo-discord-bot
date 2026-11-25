"""Kleiner Discord-REST-Client für den RYVO-Bot. Nur Python-Standardbibliothek (3.9+), kein Gateway, kein Fremdpaket.

Token: Datei bot.token neben diesem Skript (nur Mio legt sie an; wird nie ausgegeben, nie geloggt, nie ins Gehirn kopiert).
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

HIER = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("RYVO_DISCORD_API", "https://discord.com/api/v10")
UA = "DiscordBot (https://ryvo.studio, 1.0) RYVO-Server-Bot"

RECHTE = {
    "CREATE_INSTANT_INVITE": 1 << 0, "KICK_MEMBERS": 1 << 1, "BAN_MEMBERS": 1 << 2, "ADMINISTRATOR": 1 << 3,
    "MANAGE_CHANNELS": 1 << 4, "MANAGE_GUILD": 1 << 5, "ADD_REACTIONS": 1 << 6, "VIEW_AUDIT_LOG": 1 << 7,
    "STREAM": 1 << 9, "VIEW_CHANNEL": 1 << 10, "SEND_MESSAGES": 1 << 11, "MANAGE_MESSAGES": 1 << 13,
    "EMBED_LINKS": 1 << 14, "ATTACH_FILES": 1 << 15, "READ_MESSAGE_HISTORY": 1 << 16, "MENTION_EVERYONE": 1 << 17,
    "USE_EXTERNAL_EMOJIS": 1 << 18, "CONNECT": 1 << 20, "SPEAK": 1 << 21, "MUTE_MEMBERS": 1 << 22,
    "MOVE_MEMBERS": 1 << 24, "USE_VAD": 1 << 25, "CHANGE_NICKNAME": 1 << 26, "MANAGE_NICKNAMES": 1 << 27,
    "MANAGE_ROLES": 1 << 28, "USE_APPLICATION_COMMANDS": 1 << 31, "MANAGE_EVENTS": 1 << 33,
    "MANAGE_THREADS": 1 << 34, "CREATE_PUBLIC_THREADS": 1 << 35, "SEND_MESSAGES_IN_THREADS": 1 << 38,
    "MODERATE_MEMBERS": 1 << 40,
}


def rechte(namen):
    wert = 0
    for n in namen:
        wert |= RECHTE[n]
    return wert


class DiscordFehler(Exception):
    def __init__(self, status, text, pfad):
        super().__init__("HTTP %s bei %s: %s" % (status, pfad, text[:400]))
        self.status = status
        self.text = text


def token_lesen(pfad=None):
    if os.environ.get("DISCORD_BOT_TOKEN"):
        return os.environ["DISCORD_BOT_TOKEN"].strip()
    pfad = pfad or os.environ.get("RYVO_BOT_TOKEN_DATEI") or os.path.join(HIER, "bot.token")
    if not os.path.exists(pfad):
        return None
    t = open(pfad, encoding="utf-8").read().strip()
    if t.lower().startswith("bot "):
        t = t[4:].strip()
    return t or None


class Discord:
    def __init__(self, token, trocken=False, protokoll=print):
        self.token = token
        self.trocken = trocken
        self.log = protokoll
        self.schreibzaehler = 0
        self._fake = 900000000000000000

    def _fake_id(self):
        self._fake += 1
        return str(self._fake)

    def anfrage(self, methode, pfad, daten=None, grund=None, versuche=5):
        if self.trocken and methode != "GET":
            self.schreibzaehler += 1
            kurz = ""
            if isinstance(daten, dict):
                kurz = daten.get("name") or daten.get("title") or ""
            self.log("  [trocken] %s %s %s" % (methode, pfad, kurz))
            antwort = dict(daten or {}) if isinstance(daten, dict) else {}
            antwort.setdefault("id", self._fake_id())
            return antwort
        url = API + pfad
        koerper = None if daten is None else json.dumps(daten).encode("utf-8")
        for versuch in range(versuche):
            req = urllib.request.Request(url, data=koerper, method=methode)
            req.add_header("Authorization", "Bot " + self.token)
            req.add_header("User-Agent", UA)
            if koerper is not None:
                req.add_header("Content-Type", "application/json")
            if grund:
                req.add_header("X-Audit-Log-Reason", urllib.parse.quote(grund[:500]))
            try:
                with urllib.request.urlopen(req, timeout=30) as f:
                    rest = f.headers.get("X-RateLimit-Remaining")
                    nach = f.headers.get("X-RateLimit-Reset-After")
                    inhalt = f.read()
                    if methode != "GET":
                        self.schreibzaehler += 1
                    if rest == "0" and nach:
                        time.sleep(min(float(nach), 10))
                    return json.loads(inhalt) if inhalt else None
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                if e.code == 429:
                    try:
                        warte = float(json.loads(text).get("retry_after", 2))
                    except Exception:
                        warte = 2.0
                    self.log("  Discord bremst (429), warte %.1f s" % warte)
                    time.sleep(min(warte, 60) + 0.25)
                    continue
                if 500 <= e.code < 600 and versuch < versuche - 1:
                    time.sleep(2 * (versuch + 1))
                    continue
                raise DiscordFehler(e.code, text, pfad)
            except urllib.error.URLError as e:
                if versuch < versuche - 1:
                    time.sleep(2 * (versuch + 1))
                    continue
                raise DiscordFehler(0, str(e), pfad)
        raise DiscordFehler(429, "zu oft gebremst", pfad)

    def get(self, pfad):
        return self.anfrage("GET", pfad)

    def post(self, pfad, daten, grund=None):
        return self.anfrage("POST", pfad, daten, grund)

    def patch(self, pfad, daten, grund=None):
        return self.anfrage("PATCH", pfad, daten, grund)

    def put(self, pfad, daten, grund=None):
        return self.anfrage("PUT", pfad, daten, grund)

    def datei(self, methode, pfad, daten, dateiname, inhalt, versuche=5):
        """Nachricht mit Bild (multipart/form-data). daten = normale Nachricht; das Bild ist attachment://dateiname."""
        if self.trocken:
            self.log("  [trocken] %s %s + Bild %s (%d Bytes)" % (methode, pfad, dateiname, len(inhalt)))
            return {"id": self._fake_id()}
        grenze = "----ryvo%d" % int(time.time() * 1000)
        daten = dict(daten, attachments=[{"id": 0, "filename": dateiname}])
        teile = [
            ("--%s\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n" % grenze).encode()
            + json.dumps(daten).encode("utf-8") + b"\r\n",
            ("--%s\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"%s\"\r\nContent-Type: image/png\r\n\r\n" % (grenze, dateiname)).encode()
            + inhalt + b"\r\n",
            ("--%s--\r\n" % grenze).encode(),
        ]
        koerper = b"".join(teile)
        for versuch in range(versuche):
            req = urllib.request.Request(API + pfad, data=koerper, method=methode)
            req.add_header("Authorization", "Bot " + self.token)
            req.add_header("User-Agent", UA)
            req.add_header("Content-Type", "multipart/form-data; boundary=" + grenze)
            try:
                with urllib.request.urlopen(req, timeout=60) as f:
                    self.schreibzaehler += 1
                    return json.loads(f.read() or b"null")
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                if e.code == 429:
                    time.sleep(min(float(json.loads(text).get("retry_after", 2)), 60) + 0.25)
                    continue
                if 500 <= e.code < 600 and versuch < versuche - 1:
                    time.sleep(2 * (versuch + 1))
                    continue
                raise DiscordFehler(e.code, text, pfad)
        raise DiscordFehler(429, "zu oft gebremst", pfad)
