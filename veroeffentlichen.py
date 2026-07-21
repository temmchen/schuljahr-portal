#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
veroeffentlichen.py — Ein-Klick-Veröffentlichung fürs Schuljahr-Portal
=======================================================================

Gedacht für den Doppelklick auf „Portal veröffentlichen.command" im
OneDrive-Dashboard-Ordner. Prüft alles und erledigt dann alles:

  1. holt den GitHub-Stand ab und ERKENNT Browser-Aktionen (Uploads,
     neue Kollegen) — die müssen erst in OneDrive bzw. zugangsdaten.json
     übernommen sein, sonst wird NICHT gebaut (sie gingen sonst verloren)
  2. erkennt NEUE Klassen-Ordner in OneDrive → fragt, ob die Klasse
     angelegt werden soll (Fächer werden aus den Modul-Ordnern abgeleitet)
  3. warnt bei Stolperfallen: Ordnernamen mit Leerzeichen, unbekannte
     Modul-Ordner, Dateien in Unterordnern oder direkt im Modulordner
  4. zeigt, was sich seit der letzten Veröffentlichung geändert hat
  5. baut, committet, pusht — nur wenn es wirklich etwas zu tun gibt
  6. erneuert bei Noten-Änderungen das OFFLINE-Noten-Dashboard (nie online)

Ohne Änderungen passiert nichts.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
KONFIG = HIER / "zugangsdaten.json"
STAND = HIER / ".letzter-stand.json"          # lokales Gedächtnis (gitignored)

BEREICHE_ONLINE = ["Skripte", "Pruefungen", "Aufgaben", "Sonstiges", "Referentiels"]
ALLE_BEREICHE = BEREICHE_ONLINE + ["Noten"]
AKZENTE = ["eltec", "mint", "prodi"]

sys.path.insert(0, str(HIER))
import verwaltung                              # neues_passwort(), speichere()


def sag(text=""):
    print(text, flush=True)


def git(*args, fehler_ok=False):
    r = subprocess.run(["git", "-C", str(HIER)] + list(args),
                       capture_output=True, text=True)
    if r.returncode != 0 and not fehler_ok:
        sag(f"❌ git {' '.join(args)} fehlgeschlagen:\n{r.stderr.strip()}")
        sys.exit(1)
    return r


# ─────────────────────── Scan-Helfer ────────────────────────────────────────

def dateien_in(ordner: Path):
    if not ordner.is_dir():
        return []
    return [p for p in sorted(ordner.iterdir(), key=lambda p: p.name.lower())
            if p.is_file() and not p.name.startswith(".")]


def modul_keys(kl):
    keys = []
    for f in kl.get("faecher", []):
        for name in f.get("modul", {}).values():
            keys.append(name.replace(" ", ""))
    return keys


def inventar(cfg, inhalt: Path):
    """Online-relevante Dateien + Noten-Dateien getrennt erfassen."""
    online, noten, warnungen = {}, {}, []
    for kl in cfg.get("klassen", []):
        basis = inhalt / kl["key"]
        if not basis.is_dir():
            continue
        mks = set(modul_keys(kl))
        for unter in sorted(p for p in basis.iterdir()
                            if p.is_dir() and not p.name.startswith(".")):
            if unter.name not in mks:
                warnungen.append(f"{kl['key']}/{unter.name}/: Modul-Ordner ohne "
                                 f"Fächer-Eintrag — wird NICHT hochgeladen "
                                 f"(Fach in zugangsdaten.json ergänzen"
                                 + (" — Achtung, Ordnername enthält Leerzeichen, "
                                    "bitte ohne Leerzeichen benennen" if " " in unter.name else "")
                                 + ")")
        for mk in sorted(mks):
            mdir = basis / mk
            if not mdir.is_dir():
                continue
            lose = dateien_in(mdir)
            if lose:
                warnungen.append(f"{kl['key']}/{mk}/: {len(lose)} Datei(en) liegen "
                                 f"direkt im Modulordner — bitte in einen "
                                 f"Bereichsordner ({', '.join(BEREICHE_ONLINE)}) legen")
            for bereich in ALLE_BEREICHE:
                bdir = mdir / bereich
                if not bdir.is_dir():
                    continue
                ziel = noten if bereich == "Noten" else online
                for p in dateien_in(bdir):
                    st = p.stat()
                    ziel[f"{kl['key']}/{mk}/{bereich}/{p.name}"] = [st.st_size,
                                                                   int(st.st_mtime)]
                vergraben = [u for u in bdir.iterdir()
                             if u.is_dir() and not u.name.startswith(".")
                             and any(x.is_file() and not x.name.startswith(".")
                                     for x in u.rglob("*"))]
                if vergraben and bereich != "Noten":
                    warnungen.append(f"{kl['key']}/{mk}/{bereich}/: Dateien in "
                                     f"Unterordnern ({', '.join(u.name for u in vergraben)}) "
                                     f"werden NICHT hochgeladen — bitte direkt in den "
                                     f"Bereichsordner legen")
    return online, noten, warnungen


def klassen_kandidaten(cfg, inhalt: Path):
    """Ordner, die wie eine neue Klasse aussehen (Module mit Bereichsordnern)."""
    bekannt = {kl["key"].lower() for kl in cfg.get("klassen", [])}
    kandidaten = []
    for d in sorted(p for p in inhalt.iterdir()
                    if p.is_dir() and not p.name.startswith(".")):
        if d.name.lower() in bekannt:
            continue
        module = [m for m in d.iterdir() if m.is_dir() and not m.name.startswith(".")
                  and any((m / b).is_dir() for b in ALLE_BEREICHE)]
        if module:
            kandidaten.append((d, sorted(module, key=lambda m: m.name)))
    return kandidaten


def leite_faecher_ab(module):
    """Aus Modul-Ordnernamen Fächer ableiten: MINT1+MINT2 → Fach MINT, Sem 1/2.

    WICHTIG: build.py adressiert den Ordner über modulname.replace(" ","") —
    Ordnernamen MIT Leerzeichen können daher nie gelesen werden und werden
    als 'problematisch' zurückgegeben (User soll umbenennen)."""
    problematisch = [m.name for m in module if " " in m.name]
    module = [m for m in module if " " not in m.name]
    gruppen = {}
    for m in module:
        t = re.match(r"^(.*?)(\d+)$", m.name)
        stamm, nr = (t.group(1), int(t.group(2))) if t else (m.name, None)
        gruppen.setdefault(stamm or m.name, []).append((nr, m.name))
    faecher, uebrig = [], []
    for i, (stamm, eintraege) in enumerate(sorted(gruppen.items())):
        eintraege.sort(key=lambda e: (e[0] is None, e[0]))
        modul = {}
        for sem, (nr, ordner) in enumerate(eintraege[:2], start=1):
            # Anzeigename: Leerzeichen vor der Zahl (MINT1 → "MINT 1"); die
            # Invariante anzeigename.replace(" ","") == ordnername wird geprüft.
            name = re.sub(r"\s+", " ", re.sub(r"^(.*?)(\d+)$", r"\1 \2", ordner)).strip()
            if name.replace(" ", "") != ordner:
                name = ordner
            modul[str(sem)] = name
        uebrig += [ordner for _nr, ordner in eintraege[2:]]
        faecher.append({"key": stamm.upper().strip() or "FACH",
                        "name": stamm.strip() or "Fach",
                        "accent": AKZENTE[i % len(AKZENTE)], "modul": modul})
    return faecher, uebrig, problematisch


def frage(text):
    try:
        return input(text).strip().lower()
    except EOFError:
        return ""


# ─────────────────────── Hauptablauf ────────────────────────────────────────

def main():
    sag("🔐 Schuljahr-Portal — Prüfen & Veröffentlichen")
    sag("=" * 46)
    if not KONFIG.is_file():
        sys.exit("zugangsdaten.json fehlt im Portal-Ordner.")
    cfg = json.loads(KONFIG.read_text(encoding="utf-8"))
    inhalt = Path(cfg["inhalt"]).expanduser()
    if not inhalt.is_dir():
        sys.exit(f"Inhalts-Ordner nicht gefunden: {inhalt}")

    stand_alt = {}
    if STAND.is_file():
        try:
            stand_alt = json.loads(STAND.read_text(encoding="utf-8"))
        except Exception:
            stand_alt = {}

    # 1) GitHub-Stand holen + Browser-Aktionen erkennen (Uploads, neue Kollegen)
    sag("\n① Hole aktuellen Stand von GitHub …")
    alter_head = git("rev-parse", "HEAD").stdout.strip()
    pull = git("pull", "--no-rebase", "--quiet", "origin", "main", fehler_ok=True)
    if pull.returncode != 0:
        sag(f"❌ git pull fehlgeschlagen — bitte zuerst am Mac aufräumen:\n"
            f"{pull.stderr.strip()}")
        sys.exit(1)
    neue_commits = git("log", "--pretty=%s", f"{alter_head}..HEAD",
                       fehler_ok=True).stdout.splitlines()
    browser_aktionen = sorted(set(stand_alt.get("browser_aktionen", []))
                              | {z for z in neue_commits
                                 if z.startswith("Portal-Upload") or z.startswith("Portal:")})
    if browser_aktionen:
        sag("\n⚠️  Es gibt Browser-Aktionen, die der Mac-Build ÜBERSCHREIBEN würde:")
        for z in browser_aktionen:
            sag(f"     · {z}")
        sag("   → Hochgeladene Dateien zuerst in den OneDrive-Bereichsordner legen,")
        sag("     neue Kollegen zuerst in zugangsdaten.json eintragen (Snippet im Portal).")
        antwort = frage("   Ist das alles übernommen? Sonst geht es verloren! [j/N] ")
        if antwort != "j":
            stand_alt["browser_aktionen"] = browser_aktionen
            STAND.write_text(json.dumps(stand_alt), encoding="utf-8")
            sag("\n🛑 Abgebrochen — es wurde nichts überschrieben. Erst übernehmen,")
            sag("   dann den Button erneut drücken.")
            return
    # ab hier gelten die Browser-Aktionen als übernommen
    browser_aktionen = []

    # 2) Neue Klassen-Ordner?
    config_geaendert = False
    for ordner, module in klassen_kandidaten(cfg, inhalt):
        faecher, uebrig, problematisch = leite_faecher_ab(module)
        sag(f"\n② Neuer Klassen-Ordner gefunden: {ordner.name}")
        if problematisch:
            sag(f"   ⚠️  Modul-Ordner mit Leerzeichen können NICHT verarbeitet werden: "
                f"{', '.join(problematisch)}")
            sag(f"      Bitte ohne Leerzeichen benennen (z. B. 'MINT 1' → 'MINT1').")
        if not faecher:
            sag("   → Keine verwertbaren Modul-Ordner — Klasse wird übersprungen.")
            continue
        for f in faecher:
            mods = " / ".join(f["modul"].values())
            sag(f"     Fach {f['name']:10s} → {mods}  ({f['accent']})")
        if uebrig:
            sag(f"     ⚠️  Mehr als 2 Module je Fach: {', '.join(uebrig)} — "
                f"bitte von Hand in zugangsdaten.json einsortieren.")
        antwort = frage(f"   Klasse {ordner.name} so anlegen? [j/N] ")
        if antwort == "j":
            passwort = verwaltung.neues_passwort(3)
            cfg.setdefault("klassen", []).append(
                {"key": ordner.name, "name": ordner.name,
                 "passwort": passwort, "faecher": faecher})
            for fach in faecher:
                for name in fach["modul"].values():
                    for b in ALLE_BEREICHE:
                        (inhalt / ordner.name / name.replace(" ", "") / b).mkdir(
                            parents=True, exist_ok=True)
            verwaltung.speichere(cfg)
            config_geaendert = True
            sag(f"   ✅ Klasse {ordner.name} angelegt — Passwort: {passwort}")
            sag(f"      (steht auch in: python3 verwaltung.py liste)")
        else:
            sag(f"   → übersprungen (Ordner wird ignoriert, bis die Klasse angelegt ist)")

    # 3) Inventar + Warnungen
    online, noten, warnungen = inventar(cfg, inhalt)
    if warnungen:
        sag("\n③ Hinweise:")
        for w in warnungen:
            sag(f"   ⚠️  {w}")

    alt_online = stand_alt.get("online", {})
    alt_noten = stand_alt.get("noten", {})
    neu = sorted(set(online) - set(alt_online))
    weg = sorted(set(alt_online) - set(online))
    geaendert = sorted(k for k in set(online) & set(alt_online)
                       if online[k] != alt_online[k])
    noten_diff = (noten != alt_noten)

    if stand_alt:
        sag("\n④ Änderungen seit der letzten Veröffentlichung:")
    else:
        sag("\n④ Erste Veröffentlichung mit diesem Werkzeug — nehme alles auf:")
    for k in neu[:15]:
        sag(f"   + {k}")
    if len(neu) > 15:
        sag(f"   + … und {len(neu)-15} weitere")
    for k in geaendert[:10]:
        sag(f"   ~ {k}")
    for k in weg[:10]:
        sag(f"   − {k}")
    if not (neu or geaendert or weg):
        sag("   (keine Datei-Änderungen)")

    # 4) Offline-Noten-Dashboard bei Bedarf erneuern (bleibt lokal!)
    noten_ok = True
    if noten_diff:
        nd = inhalt / "baue_noten_dashboard.py"
        if nd.is_file():
            sag("\n📊 Noten haben sich geändert — erneuere das OFFLINE-Noten-Dashboard …")
            r = subprocess.run([sys.executable, str(nd)], cwd=str(inhalt))
            noten_ok = (r.returncode == 0)
            if not noten_ok:
                sag("   ⚠️  Noten-Dashboard-Neubau fehlgeschlagen — wird beim "
                    "nächsten Lauf erneut versucht.")
        else:
            noten_ok = False
            sag(f"\n⚠️  {nd.name} nicht gefunden — Offline-Noten-Dashboard "
                f"konnte nicht erneuert werden.")

    def speichere_stand():
        STAND.write_text(json.dumps({
            "online": online,
            "noten": noten if noten_ok else alt_noten,
            "browser_aktionen": browser_aktionen,
        }), encoding="utf-8")

    # 5) Veröffentlichen — nur wenn nötig
    if not (neu or geaendert or weg or config_geaendert):
        sag("\n✅ Alles aktuell — nichts zu veröffentlichen.")
        speichere_stand()
        return

    sag("\n⑤ Baue verschlüsselt neu …")
    r = subprocess.run([sys.executable, str(HIER / "build.py")])
    if r.returncode != 0:
        sys.exit("❌ build.py fehlgeschlagen — es wurde nichts veröffentlicht.")

    teile = []
    if config_geaendert:
        teile.append("neue Klasse(n)")
    if neu:
        teile.append(f"{len(neu)} neu")
    if geaendert:
        teile.append(f"{len(geaendert)} geändert")
    if weg:
        teile.append(f"{len(weg)} entfernt")
    nachricht = "Inhalte aktualisiert: " + ", ".join(teile)

    sag("⑥ Veröffentliche …")
    # bewusst NUR die Vault-Daten — sonst gingen halbfertige Änderungen an
    # index.html o. Ä. ungeprüft mit online
    git("add", "docs/vaults", "docs/.nojekyll")
    andere = [z for z in git("status", "--porcelain", "--", "docs",
                             fehler_ok=True).stdout.splitlines()
              if z and not z[3:].startswith("docs/vaults")
              and not z[3:].endswith(".nojekyll") and z[0] == " "]
    if andere:
        sag("   ℹ️  Lokal geändert, wird NICHT mitveröffentlicht "
            "(bei Bedarf manuell committen):")
        for z in andere[:5]:
            sag(f"      {z[3:]}")
    commit = git("commit", "-q", "-m", nachricht, fehler_ok=True)
    if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
        sag(f"❌ git commit: {commit.stderr.strip()}")
        sys.exit(1)
    git("push", "-q", "origin", "main")

    speichere_stand()
    sag("\n✅ Fertig! In 1–2 Minuten online: https://temmchen.github.io/schuljahr-portal/")
    sag("   (Noten wurden wie immer NICHT hochgeladen.)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sag("\nAbgebrochen — es wurde nichts veröffentlicht.")
