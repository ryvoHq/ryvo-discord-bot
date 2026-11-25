#!/usr/bin/env python3
"""Baut den RYVO-Discord nach bauplan.json auf (Python 3.9+, nur Standardbibliothek).

Aufrufe:
  python3 bauen.py --bot-link        zeigt den Link, mit dem Mio den Bot in seinen Server holt
  python3 bauen.py                   Trockenlauf: liest den Server und zeigt, was geändert würde (schreibt nichts)
  python3 bauen.py --los             baut wirklich (mehrfach ausführbar: legt nur an, was fehlt, und gleicht den Rest an)
  Optionen: --server <ID> (wenn der Bot in mehreren Servern ist)

Regeln: Es wird nichts gelöscht. Kanäle und Kategorien, die nicht im Bauplan stehen (z. B. die alten RYVO-GmbH-Kanäle mit
ihren Webhooks), werden nur für das Team sichtbar gemacht und nach unten sortiert.
"""
import base64
import hashlib
import json
import os
import re
import sys
import time

from discord_api import Discord, DiscordFehler, rechte, token_lesen, RECHTE

HIER = os.path.dirname(os.path.abspath(__file__))
ZUSTAND = os.path.join(HIER, "server-zustand.json")
BERICHT = os.path.join(HIER, "bericht.txt")
FARBE = 0xFFFFFF
TYP = {"text": 0, "sprache": 2, "kategorie": 4, "ankuendigung": 5, "forum": 15}
GRUND = "RYVO-Aufbau (bauen.py)"

zeilen = []


def log(text):
    print(text)
    zeilen.append(text)


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


def norm(name):
    return re.sub(r"\s+", "-", name.strip().lower())


def snowflake(n):
    return str(((int(time.time() * 1000) - 1420070400000) << 22) + n)


def arg(name, standard=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else standard
    return standard


class Bau:
    def __init__(self, dc, plan, zustand, trocken):
        self.dc = dc
        self.plan = plan
        self.z = zustand
        self.trocken = trocken
        self.z.setdefault("kanaele", {})
        self.z.setdefault("rollen", {})
        self.z.setdefault("nachrichten", {})
        self.offen = []

    # ---------- Server wählen ----------
    def server_waehlen(self):
        self.ich = self.dc.get("/users/@me")
        gewuenscht = arg("--server") or self.z.get("server_id")
        server = self.dc.get("/users/@me/guilds")
        if gewuenscht:
            treffer = [s for s in server if s["id"] == gewuenscht]
        else:
            treffer = server
        if len(treffer) != 1:
            namen = ", ".join("%s (%s)" % (s["name"], s["id"]) for s in server) or "keiner"
            raise SystemExit("Bitte Server angeben mit --server <ID>. Der Bot ist in: " + namen)
        self.gid = treffer[0]["id"]
        self.z["server_id"] = self.gid
        self.guild = self.dc.get("/guilds/%s" % self.gid)
        log("Server: %s (%s), Bot: %s" % (self.guild["name"], self.gid, self.ich["username"]))

    # ---------- Grundeinstellungen ----------
    def grundeinstellungen(self):
        s = self.plan["server"]
        daten = {}
        if self.guild.get("name") != s["name"]:
            daten["name"] = s["name"]
        for schl, feld in (("verifizierung", "verification_level"), ("inhaltsfilter", "explicit_content_filter"),
                           ("benachrichtigungen", "default_message_notifications")):
            if self.guild.get(feld) != s[schl]:
                daten[feld] = s[schl]
        icon_pfad = os.path.normpath(os.path.join(HIER, s["icon"]))
        if os.path.exists(icon_pfad):
            roh = open(icon_pfad, "rb").read()
            h = hashlib.sha256(roh).hexdigest()
            if self.z.get("icon_hash") != h or not self.guild.get("icon"):
                daten["icon"] = "data:image/png;base64," + base64.b64encode(roh).decode()
                self.z["icon_hash"] = h
        else:
            self.offen.append("Server-Icon fehlt: %s" % icon_pfad)
        if daten:
            log("Server-Einstellungen: " + ", ".join(k for k in daten if k != "icon") + (" + Icon" if "icon" in daten else ""))
            self.guild.update(self.dc.patch("/guilds/%s" % self.gid, daten, GRUND) or {})

    # ---------- Rollen ----------
    def rollen(self):
        vorhanden = self.dc.get("/guilds/%s/roles" % self.gid)
        nach_id = {r["id"]: r for r in vorhanden}
        nach_name = {r["name"].lower(): r for r in vorhanden}
        bot_mitglied = self.dc.get("/guilds/%s/members/%s" % (self.gid, self.ich["id"]))
        bot_oben = max([nach_id[r]["position"] for r in bot_mitglied.get("roles", []) if r in nach_id] or [0])
        self.rolle = {}
        jedermann = nach_id[self.gid]
        basis = str(rechte(self.plan["everyone_rechte"]))
        if jedermann["permissions"] != basis:
            log("@everyone: Grundrechte gesetzt")
            self.dc.patch("/guilds/%s/roles/%s" % (self.gid, self.gid), {"permissions": basis}, GRUND)
        for r in self.plan["rollen"]:
            ziel = {"name": r["name"], "permissions": str(rechte(r.get("rechte", []))),
                    "color": int(r.get("farbe", "#000000").lstrip("#"), 16),
                    "hoist": bool(r.get("abgesetzt", False)), "mentionable": bool(r.get("erwaehnbar", False))}
            alt = nach_id.get(self.z["rollen"].get(r["name"], "")) or nach_name.get(r["name"].lower())
            if alt and alt.get("managed"):
                alt = None
            if alt is None:
                neu = self.dc.post("/guilds/%s/roles" % self.gid, ziel, GRUND)
                log("Rolle angelegt: " + r["name"])
                self.rolle[r["name"]] = neu["id"]
            else:
                self.rolle[r["name"]] = alt["id"]
                diff = {k: v for k, v in ziel.items() if alt.get(k) != v}
                if diff and alt["position"] >= bot_oben:
                    self.offen.append("Rolle '%s' steht über dem Bot und kann nicht angepasst werden – Bot-Rolle in den Servereinstellungen ganz nach oben ziehen und erneut bauen" % r["name"])
                elif diff:
                    self.dc.patch("/guilds/%s/roles/%s" % (self.gid, alt["id"]), diff, GRUND)
                    log("Rolle angepasst: %s (%s)" % (r["name"], ", ".join(diff)))
            self.z["rollen"][r["name"]] = self.rolle[r["name"]]
        # Farbverlauf (Discord „Enhanced Role Styles“, braucht 3 Server-Boosts) und Besitzer-Rolle
        for r in self.plan["rollen"]:
            rid = self.rolle[r["name"]]
            if r.get("farbverlauf") and not self.trocken:
                a, b = [int(x.lstrip("#"), 16) for x in r["farbverlauf"][:2]]
                aktuell = (nach_id.get(rid) or {}).get("colors") or {}
                if aktuell.get("secondary_color") != b:
                    try:
                        self.dc.patch("/guilds/%s/roles/%s" % (self.gid, rid), {"colors": {"primary_color": a, "secondary_color": b, "tertiary_color": None}}, GRUND)
                        log("Farbverlauf gesetzt: %s" % r["name"])
                    except DiscordFehler as e:
                        self.offen.append("Farbverlauf für '%s' noch nicht möglich (Discord verlangt 3 Server-Boosts) – Rolle ist vorerst weiß; wird beim nächsten Bau automatisch gesetzt" % r["name"])
            if r.get("besitzer") and not self.trocken:
                besitzer = self.guild.get("owner_id")
                try:
                    mitglied = self.dc.get("/guilds/%s/members/%s" % (self.gid, besitzer))
                    if rid not in mitglied.get("roles", []):
                        self.dc.put("/guilds/%s/members/%s/roles/%s" % (self.gid, besitzer, rid), None, GRUND)
                        log("Rolle %s an den Server-Besitzer vergeben" % r["name"])
                except DiscordFehler as e:
                    self.offen.append("Rolle %s nicht vergeben: %s" % (r["name"], e.status))
        # Reihenfolge: Bauplan-Rollen direkt unter dem Bot, in Bauplan-Reihenfolge
        if not self.trocken:
            vorhanden = self.dc.get("/guilds/%s/roles" % self.gid)
            nach_id = {r["id"]: r for r in vorhanden}
            bot_oben = max([nach_id[r]["position"] for r in bot_mitglied.get("roles", []) if r in nach_id] or [0])
            unten = [r for r in vorhanden if r["position"] < bot_oben and r["id"] != self.gid and not r.get("managed")]
            unsere = [self.rolle[r["name"]] for r in self.plan["rollen"]]
            fremde = sorted([r for r in unten if r["id"] not in unsere], key=lambda r: -r["position"])
            reihe = unsere + [r["id"] for r in fremde]
            pos = {r["id"]: r["position"] for r in vorhanden}
            # Discord legt neue Rollen alle auf Position 1 (Gleichstand). Darum die ganze Reihe samt eigener Bot-Rolle
            # oben neu durchnummerieren: Bot-Rolle ganz oben, dann die Bauplan-Rollen, dann die übrigen.
            bot_rolle = max([r for r in bot_mitglied.get("roles", []) if r in nach_id], key=lambda r: nach_id[r]["position"], default=None)
            ziel_pos = {rid: len(reihe) - i for i, rid in enumerate(reihe)}
            if bot_rolle:
                ziel_pos[bot_rolle] = len(reihe) + 1
            if any(pos.get(rid) != p for rid, p in ziel_pos.items()):
                try:
                    self.dc.patch("/guilds/%s/roles" % self.gid, [{"id": k, "position": v} for k, v in ziel_pos.items()], GRUND)
                    log("Rollen-Reihenfolge gesetzt")
                except DiscordFehler as e:
                    self.offen.append("Rollen-Reihenfolge nicht gesetzt (%s) – Bot-Rolle RYVO in den Servereinstellungen ganz nach oben ziehen" % e.status)

    # ---------- Rechte je Kanal ----------
    def ueberschreibungen(self, kat, kanal):
        zugang = kanal.get("zugang", kat.get("zugang", "alle"))
        schreiben = kanal.get("schreiben", kat.get("schreiben", "alle"))
        ow = {}

        def setze(rid, allow=0, deny=0):
            a, d = ow.get(rid, (0, 0))
            ow[rid] = ((a | allow) & ~deny, (d | deny) & ~allow)

        sicht = RECHTE["VIEW_CHANNEL"]
        team = [self.rolle["RYVO Team"], self.rolle["Moderator"]]
        if zugang == "team":
            setze(self.gid, deny=sicht)
            for t in team:
                setze(t, allow=sicht)
        elif zugang.startswith("rolle:"):
            setze(self.gid, deny=sicht)
            setze(self.rolle[zugang[6:]], allow=sicht)
            for t in team:
                setze(t, allow=sicht)
        if schreiben == "niemand":
            schreib = RECHTE["SEND_MESSAGES"] | RECHTE["CREATE_PUBLIC_THREADS"] | RECHTE["SEND_MESSAGES_IN_THREADS"]
            setze(self.gid, deny=schreib)
            setze(self.rolle["RYVO Team"], allow=schreib)
        return [{"id": k, "type": 0, "allow": str(a), "deny": str(d)} for k, (a, d) in sorted(ow.items())]

    @staticmethod
    def ow_gleich(a, b):
        f = lambda l: sorted((o["id"], int(o.get("type", 0)), str(o["allow"]), str(o["deny"])) for o in l or [])
        return f(a) == f(b)

    # ---------- Kanäle ----------
    def kanaele_laden(self):
        self.alle = self.dc.get("/guilds/%s/channels" % self.gid)
        self.nach_id = {k["id"]: k for k in self.alle}
        self.benutzt = set()

    def finden(self, name, typ_liste, eltern=None):
        kid = self.z["kanaele"].get(name)
        if kid in self.nach_id and self.nach_id[kid]["type"] in typ_liste:
            return self.nach_id[kid]
        kandidaten = [k for k in self.alle if norm(k["name"]) == norm(name) and k["type"] in typ_liste and k["id"] not in self.benutzt]
        if eltern:
            bevorzugt = [k for k in kandidaten if k.get("parent_id") == eltern]
            if bevorzugt:
                return bevorzugt[0]
        return kandidaten[0] if kandidaten else None

    def kanal_sichern(self, name, typ, daten, eltern=None):
        typen = {0: [0, 5], 5: [0, 5], 2: [2], 4: [4], 15: [15]}[typ]
        alt = self.finden(name, typen, eltern)
        if alt is None:
            daten = dict(daten, name=name, type=typ)
            neu = self.dc.post("/guilds/%s/channels" % self.gid, daten, GRUND)
            log("Angelegt: %s %s" % ({0: "#", 2: "🔊", 4: "▸", 5: "📣", 15: "🗂"}[typ], name))
            neu.setdefault("type", typ)
            self.alle.append(neu)
            self.nach_id[neu["id"]] = neu
            kanal = neu
        else:
            kanal = alt
            diff = {}
            if alt["name"] != name and norm(alt["name"]) != norm(name):
                diff["name"] = name
            for k, v in daten.items():
                if k == "permission_overwrites":
                    if not self.ow_gleich(alt.get(k), v):
                        diff[k] = v
                elif k == "available_tags":
                    namen = {t["name"] for t in alt.get(k, [])}
                    fehlend = [t for t in v if t["name"] not in namen]
                    if fehlend:
                        diff[k] = alt.get(k, []) + fehlend
                elif k == "type":
                    continue
                elif alt.get(k) != v and not (v in ("", None) and not alt.get(k)):
                    diff[k] = v
            if typ == 5 and alt["type"] == 0 and self.community:
                diff["type"] = 5
            if diff:
                erg = self.dc.patch("/channels/%s" % alt["id"], diff, GRUND)
                log("Angepasst: %s (%s)" % (name, ", ".join(diff)))
                if isinstance(erg, dict) and not self.trocken:
                    alt.update(erg)
        self.benutzt.add(kanal["id"])
        self.z["kanaele"][name] = kanal["id"]
        return kanal

    def struktur(self, phase):
        """phase 1: alles außer Foren; phase 2: Foren und Ankündigungs-Umstellung (braucht Community)."""
        self.kat_ids = []
        for ki, kat in enumerate(self.plan["kategorien"]):
            k = self.kanal_sichern(kat["name"], 4, {"permission_overwrites": self.ueberschreibungen(kat, {})})
            self.kat_ids.append(k["id"])
            for kanal in kat["kanaele"]:
                typ = TYP[kanal.get("typ", "text")]
                if typ == 15 and phase == 1:
                    if self.finden(kanal["name"], [15], k["id"]):
                        self.benutzt.add(self.finden(kanal["name"], [15], k["id"])["id"])
                    continue
                if typ == 5 and not self.community:
                    typ_anlegen = 0
                else:
                    typ_anlegen = typ
                daten = {"parent_id": k["id"], "permission_overwrites": self.ueberschreibungen(kat, kanal)}
                if typ in (0, 5, 15):
                    daten["topic"] = kanal.get("thema", "")
                if typ == 0:
                    daten["rate_limit_per_user"] = int(kanal.get("langsam", 0))
                if typ == 15:
                    daten["available_tags"] = [{"name": t[:20]} for t in kanal.get("tags", [])][:20]
                    daten["default_forum_layout"] = 1
                    if kanal["name"] == "feature-requests":
                        daten["default_reaction_emoji"] = {"emoji_id": None, "emoji_name": "👍"}
                self.kanal_sichern(kanal["name"], typ_anlegen, daten, k["id"])

    # ---------- Community ----------
    def community_an(self):
        self.community = "COMMUNITY" in self.guild.get("features", [])
        if self.community:
            return
        s = self.plan["server"]
        daten = {"features": list(set(self.guild.get("features", []) + ["COMMUNITY"])),
                 "rules_channel_id": self.z["kanaele"][s["regelkanal"]],
                 "public_updates_channel_id": self.z["kanaele"][s["updatekanal"]],
                 "verification_level": s["verifizierung"], "explicit_content_filter": s["inhaltsfilter"]}
        self.dc.patch("/guilds/%s" % self.gid, daten, GRUND)
        log("Community-Funktionen eingeschaltet (Regeln: #%s, Discord-Hinweise: #%s)" % (s["regelkanal"], s["updatekanal"]))
        self.community = True
        if not self.trocken:
            self.guild = self.dc.get("/guilds/%s" % self.gid)

    def community_details(self):
        s = self.plan["server"]
        daten = {}
        soll = {"description": s["beschreibung"], "preferred_locale": s["sprache"],
                "system_channel_id": self.z["kanaele"].get(s["systemkanal"]),
                "rules_channel_id": self.z["kanaele"][s["regelkanal"]],
                "public_updates_channel_id": self.z["kanaele"][s["updatekanal"]]}
        for k, v in soll.items():
            if self.guild.get(k) != v:
                daten[k] = v
        if daten:
            self.dc.patch("/guilds/%s" % self.gid, daten, GRUND)
            log("Community-Details: " + ", ".join(daten))

    # ---------- Alte Kanäle ----------
    def alte_sichern(self):
        a = self.plan["alte_kategorien"]
        team = self.rolle["RYVO Team"]
        intern = [{"id": self.gid, "type": 0, "allow": "0", "deny": str(RECHTE["VIEW_CHANNEL"])},
                  {"id": team, "type": 0, "allow": str(RECHTE["VIEW_CHANNEL"]), "deny": "0"}]
        alte_kat = [k for k in self.alle if k["type"] == 4 and k["id"] not in self.benutzt]
        alte_kat_ids = {k["id"] for k in alte_kat}
        self.alte_kat_ids = []
        for k in alte_kat:
            diff = {}
            if not k["name"].startswith(a["praefix"]):
                diff["name"] = (a["praefix"] + k["name"])[:100]
            if not self.ow_gleich(k.get("permission_overwrites"), intern):
                diff["permission_overwrites"] = intern
            if diff:
                self.dc.patch("/channels/%s" % k["id"], diff, GRUND)
                log("Intern gemacht (Kategorie): %s" % k["name"])
            self.alte_kat_ids.append(k["id"])
            self.benutzt.add(k["id"])
        lose = []
        for k in self.alle:
            if k["id"] in self.benutzt or k["type"] == 4:
                continue
            if k.get("parent_id") in alte_kat_ids:
                if not self.ow_gleich(k.get("permission_overwrites"), intern):
                    self.dc.patch("/channels/%s" % k["id"], {"permission_overwrites": intern}, GRUND)
                    log("Intern gemacht: %s" % k["name"])
            elif not k.get("parent_id"):
                lose.append(k)
            else:
                log("Nicht im Bauplan, unverändert gelassen: %s" % k["name"])
            self.benutzt.add(k["id"])
        if lose:
            sammel = self.kanal_sichern(a["sammelkategorie"], 4, {"permission_overwrites": intern})
            self.alte_kat_ids.append(sammel["id"])
            for k in lose:
                self.dc.patch("/channels/%s" % k["id"], {"parent_id": sammel["id"], "permission_overwrites": intern}, GRUND)
                log("Ins Archiv (nur Team): %s" % k["name"])

    def reihenfolge(self):
        if self.trocken:
            return
        self.alle = self.dc.get("/guilds/%s/channels" % self.gid)
        akt = {k["id"]: k for k in self.alle}
        ziel = []
        for i, kid in enumerate(self.kat_ids + [k for k in self.alte_kat_ids if k not in self.kat_ids]):
            ziel.append({"id": kid, "position": i})
        for kat in self.plan["kategorien"]:
            for j, kanal in enumerate(kat["kanaele"]):
                kid = self.z["kanaele"].get(kanal["name"])
                if kid:
                    ziel.append({"id": kid, "position": j})
        ziel = [z for z in ziel if z["id"] in akt and akt[z["id"]].get("position") != z["position"]]
        if ziel:
            for i in range(0, len(ziel), 50):
                self.dc.patch("/guilds/%s/channels" % self.gid, ziel[i:i + 50], GRUND)
            log("Reihenfolge: %d Kanäle sortiert" % len(ziel))

    # ---------- Texte ----------
    def text_ersetzen(self, text):
        def kanal(m):
            kid = self.z["kanaele"].get(m.group(1))
            if not kid:
                self.offen.append("Text verweist auf unbekannten Kanal: %s" % m.group(1))
                return "#" + m.group(1)
            return "<#%s>" % kid
        text = re.sub(r"\{kanal:([^}]+)\}", kanal, text)
        text = re.sub(r"\{rolle:([^}]+)\}", lambda m: "<@&%s>" % self.rolle.get(m.group(1), "0"), text)
        return text.replace("{customize}", "<id:customize>").replace("{browse}", "<id:browse>")

    def embeds_aus(self, datei):
        roh = open(os.path.join(HIER, "texte", datei), encoding="utf-8").read().strip()
        embeds = []
        for teil in re.split(r"\n---\n", roh):
            teil = self.text_ersetzen(teil.strip())
            e = {"color": FARBE}
            if teil.startswith("# "):
                titel, _, rest = teil.partition("\n")
                e["title"] = titel[2:].strip()[:256]
                teil = rest.strip()
            e["description"] = teil[:4096]
            embeds.append(e)
        return embeds[:10]

    def texte(self):
        for kat in self.plan["kategorien"]:
            for kanal in kat["kanaele"]:
                if not kanal.get("text"):
                    continue
                kid = self.z["kanaele"][kanal["name"]]
                embeds = self.embeds_aus(kanal["text"])
                h = hashlib.sha256(json.dumps(embeds, sort_keys=True).encode()).hexdigest()
                eintrag = self.z["nachrichten"].get(kanal["name"], {})
                if eintrag.get("hash") == h:
                    continue
                daten = {"embeds": embeds, "allowed_mentions": {"parse": []}}
                mid = eintrag.get("id")
                if mid:
                    try:
                        self.dc.patch("/channels/%s/messages/%s" % (kid, mid), daten)
                        log("Text aktualisiert: #%s" % kanal["name"])
                    except DiscordFehler as e:
                        if e.status != 404:
                            raise
                        mid = None
                if not mid:
                    m = self.dc.post("/channels/%s/messages" % kid, daten)
                    mid = m["id"]
                    log("Text gepostet: #%s" % kanal["name"])
                    try:
                        self.dc.put("/channels/%s/pins/%s" % (kid, mid), None)
                    except DiscordFehler:
                        pass
                self.z["nachrichten"][kanal["name"]] = {"id": mid, "hash": h}

    def beitraege(self):
        """Feste Beiträge in Foren (Anleitungen, geplante Funktionen). Einmal anlegen, bei Textänderung den Startbeitrag anpassen."""
        for kat in self.plan["kategorien"]:
            for kanal in kat["kanaele"]:
                if not kanal.get("beitraege"):
                    continue
                fid = self.z["kanaele"][kanal["name"]]
                forum = self.dc.get("/channels/%s" % fid) if not self.trocken else {"available_tags": []}
                tag_id = {t["name"]: t["id"] for t in forum.get("available_tags", [])}
                for b in kanal["beitraege"]:
                    schl = "%s#%s" % (kanal["name"], b["titel"])
                    embeds = self.embeds_aus(b["text"])
                    h = hashlib.sha256(json.dumps([embeds, b.get("tags", [])], sort_keys=True).encode()).hexdigest()
                    eintrag = self.z["nachrichten"].get(schl, {})
                    if eintrag.get("hash") == h:
                        continue
                    tags = [tag_id[t] for t in b.get("tags", []) if t in tag_id]
                    tid = eintrag.get("thread")
                    if tid:
                        try:
                            self.dc.patch("/channels/%s/messages/%s" % (tid, tid), {"embeds": embeds})
                            self.dc.patch("/channels/%s" % tid, {"applied_tags": tags})
                            log("Forum-Beitrag aktualisiert: %s" % schl)
                        except DiscordFehler as e:
                            if e.status != 404:
                                raise
                            tid = None
                    if not tid:
                        t = self.dc.post("/channels/%s/threads" % fid, {"name": b["titel"][:100], "applied_tags": tags,
                                                                       "message": {"embeds": embeds, "allowed_mentions": {"parse": []}}}, GRUND)
                        tid = t["id"]
                        log("Forum-Beitrag angelegt: %s" % schl)
                        if b.get("angepinnt"):
                            try:
                                self.dc.patch("/channels/%s" % tid, {"flags": 2}, GRUND)
                            except DiscordFehler as e:
                                self.offen.append("Beitrag nicht angepinnt (%s): %s" % (schl, e.status))
                    self.z["nachrichten"][schl] = {"thread": tid, "hash": h}

    def aufraeumen(self):
        """Löscht, was nicht mehr im Bauplan steht: alte Texte, Forum-Beiträge, Kanäle aus 'entfernen' und die
        Discord-Hinweise „hat eine Nachricht angepinnt“. Nur Beiträge des Bots, nie Beiträge von Mitgliedern."""
        soll_text = set()
        soll_beitrag = set()
        for kat in self.plan["kategorien"]:
            for kanal in kat["kanaele"]:
                if kanal.get("text"):
                    soll_text.add(kanal["name"])
                for b in kanal.get("beitraege", []):
                    soll_beitrag.add("%s#%s" % (kanal["name"], b["titel"]))
        for schl in list(self.z["nachrichten"]):
            eintrag = self.z["nachrichten"][schl]
            try:
                if "#" in schl and schl not in soll_beitrag and eintrag.get("thread"):
                    self.dc.anfrage("DELETE", "/channels/%s" % eintrag["thread"], grund=GRUND)
                    log("Forum-Beitrag gelöscht: %s" % schl)
                elif "#" not in schl and schl not in soll_text and eintrag.get("id"):
                    self.dc.anfrage("DELETE", "/channels/%s/messages/%s" % (self.z["kanaele"][schl], eintrag["id"]), grund=GRUND)
                    log("Text gelöscht: #%s" % schl)
                else:
                    continue
            except DiscordFehler as e:
                if e.status != 404:
                    self.offen.append("Löschen %s: %s" % (schl, e.status))
                    continue
            del self.z["nachrichten"][schl]
        for name in self.plan.get("entfernen", []):
            kid = self.z["kanaele"].get(name)
            if not kid:
                continue
            try:
                self.dc.anfrage("DELETE", "/channels/%s" % kid, grund=GRUND)
                log("Kanal gelöscht: #%s" % name)
            except DiscordFehler as e:
                if e.status != 404:
                    self.offen.append("Kanal %s nicht gelöscht: %s" % (name, e.status))
                    continue
            del self.z["kanaele"][name]
        if self.trocken:
            return
        for kat in self.plan["kategorien"]:
            for kanal in kat["kanaele"]:
                kid = self.z["kanaele"].get(kanal["name"])
                if not kid or kanal.get("typ", "text") not in ("text", "ankuendigung"):
                    continue
                try:
                    for m in self.dc.get("/channels/%s/messages?limit=50" % kid) or []:
                        if m.get("type") == 6 and m.get("author", {}).get("id") == self.ich["id"]:
                            self.dc.anfrage("DELETE", "/channels/%s/messages/%s" % (kid, m["id"]))
                except DiscordFehler:
                    pass

    # ---------- Onboarding, Willkommensseite, AutoMod, Einladung ----------
    def onboarding(self):
        o = self.plan["onboarding"]
        try:
            alt = self.dc.get("/guilds/%s/onboarding" % self.gid) or {}
        except DiscordFehler:
            alt = {}
        alte_fragen = {p["title"]: p for p in alt.get("prompts", [])}
        n = 0
        fragen = []
        for f in o["fragen"]:
            altf = alte_fragen.get(f["titel"], {})
            alte_opt = {op["title"]: op for op in altf.get("options", [])}
            n += 1
            optionen = []
            for op in f["optionen"]:
                n += 1
                optionen.append({
                    "id": alte_opt.get(op["titel"], {}).get("id") or snowflake(n),
                    "title": op["titel"], "description": op.get("beschreibung", ""),
                    "emoji_name": op.get("emoji"), "emoji_id": None, "emoji_animated": False,
                    "role_ids": [self.rolle[r] for r in op.get("rollen", [])],
                    "channel_ids": [self.z["kanaele"][c] for c in op.get("kanaele", [])]})
            fragen.append({"id": altf.get("id") or snowflake(n), "type": 0, "title": f["titel"], "options": optionen,
                           "single_select": not f.get("mehrfach", True), "required": bool(f.get("pflicht")),
                           "in_onboarding": bool(f.get("im_onboarding", True))})
        daten = {"prompts": fragen, "default_channel_ids": [self.z["kanaele"][c] for c in o["standardkanaele"]],
                 "enabled": True, "mode": 0}
        try:
            self.dc.put("/guilds/%s/onboarding" % self.gid, daten, GRUND)
            log("Onboarding gesetzt: %d Fragen, %d Standardkanäle" % (len(fragen), len(daten["default_channel_ids"])))
        except DiscordFehler as e:
            self.offen.append("Onboarding nicht gesetzt: %s" % e)

    def willkommensseite(self):
        w = self.plan["willkommensseite"]
        daten = {"enabled": True, "description": w["beschreibung"][:140],
                 "welcome_channels": [{"channel_id": self.z["kanaele"][x["kanal"]], "description": x["text"][:42],
                                       "emoji_name": x["emoji"], "emoji_id": None} for x in w["kanaele"]][:5]}
        try:
            self.dc.patch("/guilds/%s/welcome-screen" % self.gid, daten, GRUND)
            log("Willkommensseite gesetzt")
        except DiscordFehler as e:
            self.offen.append("Willkommensseite nicht gesetzt: %s" % e)

    def automod(self):
        try:
            alt = {r["name"]: r for r in self.dc.get("/guilds/%s/auto-moderation/rules" % self.gid)}
        except DiscordFehler as e:
            self.offen.append("AutoMod nicht lesbar: %s" % e)
            return
        modlog = self.z["kanaele"].get("mod-log")
        ausnahme = [self.rolle["RYVO Team"], self.rolle["Moderator"]]
        for r in self.plan["automod"]:
            aktionen = [{"type": 1, "metadata": {}}]
            if r["art"] in ("woerter", "muster"):
                aktionen = [{"type": 1, "metadata": {"custom_message": "Blocked by RYVO AutoMod. See #rules (scams, invites and referral links are not allowed)."[:150]}}]
            if modlog:
                aktionen.append({"type": 2, "metadata": {"channel_id": modlog}})
            daten = {"name": r["name"], "event_type": 1, "actions": aktionen, "enabled": True, "exempt_roles": ausnahme}
            if r["art"] == "vorlage":
                daten.update(trigger_type=4, trigger_metadata={"presets": r["vorlagen"], "allow_list": []})
            elif r["art"] == "spam":
                daten.update(trigger_type=3)
            elif r["art"] == "erwaehnungen":
                daten.update(trigger_type=5, trigger_metadata={"mention_total_limit": r["grenze"], "mention_raid_protection_enabled": True})
            elif r["art"] == "woerter":
                daten.update(trigger_type=1, trigger_metadata={"keyword_filter": r["woerter"], "allow_list": r.get("erlaubt", [])})
            elif r["art"] == "muster":
                daten.update(trigger_type=1, trigger_metadata={"regex_patterns": r["muster"]})
            try:
                if r["name"] in alt:
                    d = dict(daten)
                    d.pop("trigger_type", None)
                    d.pop("event_type", None)
                    self.dc.patch("/guilds/%s/auto-moderation/rules/%s" % (self.gid, alt[r["name"]]["id"]), d, GRUND)
                else:
                    self.dc.post("/guilds/%s/auto-moderation/rules" % self.gid, daten, GRUND)
                    log("AutoMod-Regel angelegt: %s" % r["name"])
            except DiscordFehler as e:
                self.offen.append("AutoMod '%s': %s" % (r["name"], e))

    def einladung(self):
        kanal = self.z["kanaele"][self.plan["server"]["einladungskanal"]]
        try:
            for inv in self.dc.get("/guilds/%s/invites" % self.gid) or []:
                if inv.get("channel", {}).get("id") == kanal and inv.get("max_age") == 0 and inv.get("max_uses") == 0 \
                        and inv.get("inviter", {}).get("id") == self.ich["id"]:
                    self.z["einladung"] = "https://discord.gg/" + inv["code"]
                    return
        except DiscordFehler:
            pass
        inv = self.dc.post("/channels/%s/invites" % kanal, {"max_age": 0, "max_uses": 0, "unique": False}, GRUND)
        if not self.trocken:
            self.z["einladung"] = "https://discord.gg/" + inv["code"]
            log("Dauer-Einladung erstellt: " + self.z["einladung"])

    # ---------- Ablauf ----------
    def los(self):
        self.server_waehlen()
        self.community = "COMMUNITY" in self.guild.get("features", [])
        self.grundeinstellungen()
        self.rollen()
        self.kanaele_laden()
        self.struktur(1)
        self.community_an()
        self.struktur(2)
        self.community_details()
        self.alte_sichern()
        self.reihenfolge()
        self.texte()
        self.beitraege()
        self.aufraeumen()
        self.onboarding()
        self.willkommensseite()
        self.automod()
        self.einladung()


def bot_link(dc):
    app = dc.get("/oauth2/applications/@me")
    url = "https://discord.com/oauth2/authorize?client_id=%s&scope=bot&permissions=%d" % (app["id"], RECHTE["ADMINISTRATOR"])
    print("Bot-Anwendung: %s" % app.get("name"))
    print("Link zum Hinzufügen (im Browser öffnen, Server 'RYVO GmbH' wählen, Autorisieren):")
    print(url)


def main():
    token = token_lesen()
    if not token:
        raise SystemExit("Kein Bot-Token: Datei bot.token neben bauen.py fehlt oder ist leer.")
    trocken = "--los" not in sys.argv
    dc = Discord(token, trocken=trocken)
    if "--bot-link" in sys.argv:
        bot_link(dc)
        return
    plan = laden(os.path.join(HIER, "bauplan.json"), None)
    zustand = laden(ZUSTAND, {})
    log("== RYVO-Discord bauen %s – %s ==" % ("(TROCKENLAUF, nichts wird geändert)" if trocken else "(ECHT)", time.strftime("%d.%m.%Y %H:%M")))
    bau = Bau(dc, plan, zustand, trocken)
    try:
        bau.los()
    finally:
        if not trocken:
            speichern(ZUSTAND, zustand)
    log("Schreibvorgänge: %d" % dc.schreibzaehler)
    if bau.offen:
        log("OFFEN:")
        for o in bau.offen:
            log("  - " + o)
    if zustand.get("einladung"):
        log("Einladung: " + zustand["einladung"])
    with open(BERICHT, "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")


if __name__ == "__main__":
    main()
