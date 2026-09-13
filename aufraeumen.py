#!/usr/bin/env python3
"""
Repo aufräumen — hält das Schuljahr-Portal-Repo klein.

Warum: Jede Veröffentlichung legt Chiffrate ab. Seit dem inkrementellen Build
ändern sich pro Lauf nur noch ~50 KB, aber ALTE Stände bleiben für immer in der
Git-Historie liegen (Stand 13.09.2026: rund 1,4 GB).

Zwei Stufen:
  1) AUFRÄUMEN (ungefährlich) — löst nur ungenutzte Objekte auf
     (abgebrochene Pushes, zurückgenommene Commits). Historie bleibt.
  2) HISTORIE ZURÜCKSETZEN (einmalig, kräftig) — presst den kompletten Verlauf
     auf EINEN Commit mit dem aktuellen Stand und überschreibt GitHub.
     Danach ist das Repo so groß wie der aktuelle Inhalt — nicht größer.
     Nebeneffekt: alte Chiffrate verschwinden aus der Historie (gut fürs
     Passwort-Rotieren). Der Verlauf ist danach weg — inhaltlich verliert man
     nichts, das Portal enthält nur den jeweils aktuellen Stand.

Aufruf:  python3 aufraeumen.py            (fragt, was gemacht werden soll)
         python3 aufraeumen.py --nur-gc   (nur Stufe 1, ohne Nachfrage)
"""
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent


def git(*args, pruefen=True):
    r = subprocess.run(["git", "-C", str(HIER)] + list(args),
                       capture_output=True, text=True)
    if pruefen and r.returncode != 0:
        print(f"❌ git {' '.join(args)}:\n{(r.stderr or r.stdout).strip()}")
        sys.exit(1)
    return r.stdout.strip()


def groesse_mb() -> float:
    roh = subprocess.run(["du", "-sk", str(HIER / ".git")],
                         capture_output=True, text=True).stdout.split()[0]
    return int(roh) / 1024


def zeige(titel):
    print(f"\n{titel}")
    print(f"   .git-Größe : {groesse_mb():.0f} MB")
    print(f"   Commits    : {git('rev-list', '--count', 'HEAD')}")


def stufe1():
    print("\n① Ungenutzte Objekte auflösen …")
    git("reflog", "expire", "--expire=now", "--all")
    git("gc", "--prune=now", "--aggressive")
    print("   fertig.")


def stufe2():
    """Historie auf einen einzigen Commit zusammenlegen und GitHub überschreiben."""
    print("\n② Historie auf einen Commit zusammenlegen …")
    zweig = git("rev-parse", "--abbrev-ref", "HEAD")
    git("checkout", "--orphan", "_aufgeraeumt")
    git("add", "-A")
    git("commit", "-q", "-m",
        "Schuljahr-Portal — aktueller Stand (Historie zusammengelegt)")
    git("branch", "-D", zweig)
    git("branch", "-m", zweig)
    print("   → überschreibe GitHub (force-push) …")
    git("push", "--force", "origin", zweig)
    git("reflog", "expire", "--expire=now", "--all")
    git("gc", "--prune=now", "--aggressive")
    print("   fertig.")


def main():
    if not (HIER / ".git").is_dir():
        sys.exit("Kein Git-Repo gefunden.")

    # Sicherheitsnetze
    if git("status", "--porcelain"):
        sys.exit("❌ Es gibt uncommittete Änderungen.\n"
                 "   Erst veröffentlichen (Portal veröffentlichen.command), dann aufräumen.")
    git("fetch", "--quiet", "origin", pruefen=False)
    voraus = git("rev-list", "--count", "HEAD..origin/main", pruefen=False)
    if voraus and voraus != "0":
        sys.exit(f"❌ GitHub ist {voraus} Commit(s) voraus (Browser-Uploads?).\n"
                 "   Erst  git pull  und veröffentlichen, dann aufräumen.")

    print("🧹 Schuljahr-Portal — Repo aufräumen")
    print("=" * 38)
    zeige("Vorher:")

    if "--nur-gc" in sys.argv:
        stufe1()
        zeige("Nachher:")
        return

    stufe1()
    zeige("Nach Stufe 1:")

    print("\n" + "─" * 60)
    print("Stufe 2 legt den GESAMTEN Verlauf auf einen Commit zusammen und")
    print("überschreibt GitHub. Der aktuelle Inhalt bleibt vollständig erhalten,")
    print("nur die alten Zwischenstände verschwinden — das Repo schrumpft dann")
    print("auf die Größe des aktuellen Inhalts.")
    print("Das lässt sich NICHT rückgängig machen.")
    print("─" * 60)
    try:
        antwort = input('Stufe 2 ausführen? Tippe genau  JA  (alles andere bricht ab): ').strip()
    except EOFError:
        antwort = ""
    if antwort != "JA":
        print("\nAbgebrochen — nur Stufe 1 wurde ausgeführt. Das ist völlig in Ordnung.")
        return
    stufe2()
    zeige("Nachher:")
    print("\n✅ Fertig. Das Portal ist unverändert online — nur der Verlauf ist aufgeräumt.")


if __name__ == "__main__":
    main()
