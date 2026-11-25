# RYVO-Discord (Server „RYVO“)

Baut den Discord-Server zu einem internationalen Trading-Discord um und hält ihn mit einem Bot aktuell. Nur Python vom Mac, kein Fremdpaket, keine laufenden Kosten.

| Datei | Zweck |
|---|---|
| `bauplan.json` | Der ganze Server: Kategorien, Kanäle, Rollen, Rechte, Onboarding, Willkommensseite, AutoMod, Bot-Quellen |
| `texte/*.md` | Alle angepinnten Texte (Willkommen, Regeln, Risiko-Hinweis, FAQ, Roadmap, Pro, Sprachkanäle). `---` trennt Blöcke, `{kanal:name}` wird zum Kanal-Link, `{customize}` zu „Kanäle & Rollen“ |
| `bauen.py` | Baut den Server nach dem Bauplan. Ohne `--los` nur Trockenlauf. Mehrfach ausführbar, löscht nie etwas |
| `posten.py` | Der Bot (alle 10 Min.): Live-Board, Schlagzeilen, Lage-Bericht (6 Sprachen), Terminal-Updates, Postausgang, Status; täglich: Daily discussion, Chart of the day, Swing-Board, EZB-Kurse, Krypto-/Aktien-/Indizes-Übersicht |
| `markt.py` | Marktdaten (Hyperliquid, alternative.me, EZB), Boards und Charts (matplotlib). `python3 markt.py` = Selbsttest |
| `ausgang/` | Postausgang für andere Chats/Agenten: eine JSON-Datei hineinlegen, der Bot postet sie beim nächsten Lauf |
| `bot.token` | **geheim** – legt nur Mio an. Nie teilen, nie ins Gehirn, nie in ein Repo |
| `server-zustand.json` | IDs von Kanälen, Rollen und Texten (von bauen.py geschrieben) |

## Ablauf
1. Mio: Bot in discord.com/developers anlegen, Token in `bot.token` legen.
2. `python3 bauen.py --bot-link` → Link öffnen, Server wählen, Autorisieren.
3. `python3 bauen.py` (Trockenlauf prüfen) → `python3 bauen.py --los`.
4. `./einrichten.sh` → Bot läuft dauerhaft (LaunchAgent `de.ryvo.discord.bot`).

Abschalten: `launchctl unload ~/Library/LaunchAgents/de.ryvo.discord.bot.plist`

## Postausgang (für alle Chats)
```json
{"kanal": "terminal-updates", "titel": "RYVO Terminal r174", "text": "Was neu ist …", "ping": "Terminal Updates Ping", "link": "https://ryvohq.github.io/ryvo-terminal/"}
```
Erlaubte Kanäle: jeder Kanal aus dem Bauplan. Für öffentliche Kanäle gilt: nur Englisch, nur beschreibend, keine Signale, keine Bot-Trades.

## Feste Regeln
- Der private Trading-Bot und der Meme-Sniper posten **nie** in öffentliche Kanäle. Die alten Kanäle (Dashboard, Trading …) bleiben nur fürs Team sichtbar.
- Keine Signale, keine Kauf-/Verkaufsempfehlungen von RYVO. Lage-Bericht und Schlagzeilen sind beschreibend.
- Discord-Server-Abos gibt es nur für Server-Besitzer in den USA. RYVO Pro läuft deshalb später über eine eigene Bezahlung (z. B. Stripe) mit Rollen-Vergabe – erst wenn Gewerbe und Impressum stehen.
