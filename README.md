# RYVO Discord Bot

Runs the RYVO Discord server bot on GitHub Actions: live market board, headlines, market brief in six languages, swing board, chart of the day, daily desk levels (prior-day and prior-week highs and lows, weekly and monthly opens, open hourly fair value gaps), momentum alerts, a meme radar (pump.fun bonding curves that filled, read live from a public Solana node) and the **RYVO Lab** (a fixed rules-based model trading on paper, every result logged).

- Code: `bot/` · schedule: `.github/workflows/bot.yml` (a 55-minute loop, one pass every 5 minutes)
- Secret: `DISCORD_BOT_TOKEN` (repository secret, never in the code)
- Lab trade library: [`bot/lab/BIBLIOTHEK.md`](bot/lab/BIBLIOTHEK.md)

Everything the bot posts is descriptive or simulated. Nothing here is financial advice.
