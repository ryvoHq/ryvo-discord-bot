#!/usr/bin/env python3
"""Cloud-Schleife für den RYVO-Bot (GitHub Actions): läuft `--minuten` lang, alle `--takt` Sekunden ein Durchgang von posten.py
(inkl. RYVO Lab), sichert danach den Zustand per git commit/push ins Repo. Braucht keine Claude-Credits und keinen Mac."""
import os
import subprocess
import sys
import time

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
import posten  # noqa: E402


def arg(name, standard):
    return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else standard


def git(*a, pruefen=False):
    return subprocess.run(["git", "-C", os.path.dirname(HIER)] + list(a), capture_output=True, text=True, check=pruefen)


def sichern():
    git("add", "bot/posten-zustand.json", "bot/lab")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return
    git("commit", "-q", "-m", "Zustand %s [skip ci]" % time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
    for _ in range(3):
        if git("push", "-q").returncode == 0:
            return
        git("pull", "-q", "--rebase", "-X", "theirs")
    print("WARNUNG: Zustand nicht gepusht")


def main():
    minuten, takt = arg("--minuten", 55), arg("--takt", 300)
    git("config", "user.name", "RYVO Bot")
    git("config", "user.email", "bot@ryvo.studio")
    ende = time.time() + minuten * 60
    while True:
        start = time.time()
        try:
            posten.main()
        except Exception as e:
            print("FEHLER im Durchgang:", e)
        sichern()
        if time.time() + takt > ende:
            break
        time.sleep(max(5, takt - (time.time() - start)))


if __name__ == "__main__":
    main()
