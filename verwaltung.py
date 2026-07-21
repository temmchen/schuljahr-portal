#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verwaltung.py — Schuljahr-Portal · Admin-Werkzeug
==================================================

Verwaltet Zugänge und Klassen in zugangsdaten.json, legt die Ordnerstruktur
im OneDrive-Inhaltsordner an und baut das Portal danach automatisch neu.

    python3 verwaltung.py liste                 Übersicht aller Zugänge
    python3 verwaltung.py klasse DP1ET          neue Klasse anlegen (fragt Fächer ab)
    python3 verwaltung.py prof "Marc Lichter"   neuen Kollegen anlegen
    python3 verwaltung.py passwort DP2ET        Passwort neu würfeln
    python3 verwaltung.py passwort "Kollege A"  (Klasse, Prof-Name oder 'admin')

Nach jedem Befehl (außer liste) läuft build.py; danach nur noch:
    git add docs && git commit -m "Update" && git push
"""

import argparse
import json
import secrets
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
KONFIG = HIER / "zugangsdaten.json"

BEREICHS_ORDNER = ["Referentiels", "Skripte", "Pruefungen", "Aufgaben", "Noten", "Sonstiges"]
AKZENTE = ["eltec", "mint", "prodi"]

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # ohne 0/O, 1/l/i — tippfreundlich


def neues_passwort(gruppen):
    return "-".join("".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(gruppen))


def lade():
    if not KONFIG.is_file():
        sys.exit("zugangsdaten.json fehlt — Vorlage: zugangsdaten.beispiel.json")
    return json.loads(KONFIG.read_text(encoding="utf-8"))


def speichere(cfg):
    KONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def baue(cfg):
    print("\n— Portal wird neu gebaut —", flush=True)
    ergebnis = subprocess.run([sys.executable, str(HIER / "build.py")])
    if ergebnis.returncode != 0:
        sys.exit("build.py ist fehlgeschlagen — Änderung ist gespeichert, "
                 "aber noch nichts veröffentlicht.")


def abschluss(*zeilen):
    """Zusammenfassung NACH dem Build ausgeben, damit das Passwort sichtbar bleibt."""
    print()
    for z in zeilen:
        print(z)
    print('\nJetzt veröffentlichen:  git add docs && git commit -m "Update" && git push')


# ─────────────────────────── Befehle ────────────────────────────────────────

def cmd_liste(cfg):
    print(f"Schuljahr {cfg.get('schuljahr','?')} — Inhalte aus: {cfg.get('inhalt','?')}\n")
    print("Klassen (sehen nur Skripte der eigenen Klasse):")
    for kl in cfg.get("klassen", []):
        faecher = ", ".join(f["name"] for f in kl.get("faecher", []))
        print(f"  {kl['key']:10s} Passwort: {kl['passwort']:22s} Fächer: {faecher}")
    print("\nProfs (sehen alles außer Noten — Noten sind nie online):")
    for p in cfg.get("profs", []):
        print(f"  {p.get('name','?'):18s} Passwort: {p['passwort']}")
    a = cfg.get("admin", {})
    print(f"\nAdmin:\n  {a.get('name','?'):18s} Passwort: {a['passwort']}")


def frage_faecher():
    """Fächer interaktiv abfragen: Name, Akzentfarbe, Modulnamen je Semester."""
    faecher = []
    print("\nFächer der Klasse eingeben (leerer Fach-Name = fertig).")
    print("Beispiel: Fach MINT mit Modulen 'MINT 1' (Sem. 1) und 'MINT 2' (Sem. 2)\n")
    while True:
        name = input(f"Fach {len(faecher)+1} — Name (leer = fertig): ").strip()
        if not name:
            break
        m1 = input(f"  Modulname Semester 1 [{name} 1]: ").strip() or f"{name} 1"
        m2 = input(f"  Modulname Semester 2 [{name} 2]: ").strip() or f"{name} 2"
        vorschlag = AKZENTE[len(faecher) % len(AKZENTE)]
        farbe = input(f"  Farbe {AKZENTE} [{vorschlag}]: ").strip().lower() or vorschlag
        if farbe not in AKZENTE and not farbe.startswith("#"):
            print(f"  → unbekannte Farbe, nehme {vorschlag}")
            farbe = vorschlag
        faecher.append({"key": name.upper().replace(" ", ""), "name": name,
                        "accent": farbe, "modul": {"1": m1, "2": m2}})
    if not faecher:
        sys.exit("Keine Fächer eingegeben — abgebrochen.")
    return faecher


def cmd_klasse(cfg, key):
    key = key.strip()
    if not key or not all(c.isalnum() or c in "-_" for c in key):
        sys.exit("Klassen-Kürzel bitte nur aus Buchstaben/Ziffern/-/_ (wird Ordner- und "
                 "URL-Bestandteil), z. B. DP1ET.")
    if any(kl["key"].lower() == key.lower() for kl in cfg.get("klassen", [])):
        sys.exit(f"Klasse {key} existiert schon — Passwort neu würfeln geht mit:  "
                 f"python3 verwaltung.py passwort {key}")
    name = input(f"Anzeigename [{key}]: ").strip() or key
    faecher = frage_faecher()

    inhalt = Path(cfg["inhalt"]).expanduser()
    for fach in faecher:
        for mname in fach["modul"].values():
            mdir = inhalt / key / mname.replace(" ", "")
            for b in BEREICHS_ORDNER:
                (mdir / b).mkdir(parents=True, exist_ok=True)

    passwort = neues_passwort(3)
    cfg.setdefault("klassen", []).append(
        {"key": key, "name": name, "passwort": passwort, "faecher": faecher})
    speichere(cfg)
    baue(cfg)
    abschluss(f"✅ Klasse {key} angelegt — Ordner unter {inhalt / key}",
              f"   Passwort für die Klasse: {passwort}",
              "   (Skripte in die Skripte-Ordner legen; Noten-Ordner bleibt immer offline.)")


def cmd_prof(cfg, name):
    name = name.strip()
    if any(p.get("name","").lower() == name.lower() for p in cfg.get("profs", [])):
        sys.exit(f"Prof '{name}' existiert schon.")
    passwort = neues_passwort(4)
    cfg.setdefault("profs", []).append({"name": name, "passwort": passwort})
    speichere(cfg)
    baue(cfg)
    abschluss(f"✅ Prof '{name}' angelegt — Passwort: {passwort}",
              "   Sieht nach dem Push alle Klassen (Skripte, Prüfungen, Aufgaben, "
              "Sonstiges, Référentiels — keine Noten, die sind nie online).")


def cmd_passwort(cfg, wer):
    wer_norm = wer.strip().lower()
    if wer_norm in ("admin", cfg.get("admin", {}).get("name", "").lower()):
        cfg["admin"]["passwort"] = neues_passwort(4)
        neu, label = cfg["admin"]["passwort"], "Admin"
    else:
        for kl in cfg.get("klassen", []):
            if kl["key"].lower() == wer_norm or kl["name"].lower() == wer_norm:
                kl["passwort"] = neues_passwort(3)
                neu, label = kl["passwort"], f"Klasse {kl['key']}"
                break
        else:
            for p in cfg.get("profs", []):
                if p.get("name", "").lower() == wer_norm:
                    p["passwort"] = neues_passwort(4)
                    neu, label = p["passwort"], f"Prof {p['name']}"
                    break
            else:
                sys.exit(f"'{wer}' nicht gefunden — python3 verwaltung.py liste zeigt alle Zugänge.")
    speichere(cfg)
    baue(cfg)
    abschluss(f"✅ Neues Passwort für {label}: {neu}",
              "   Gilt nach dem Push. Achtung: Früher veröffentlichte Stände bleiben in der",
              "   Git-Historie mit dem alten Passwort lesbar (siehe README).")


def main():
    parser = argparse.ArgumentParser(description="Schuljahr-Portal verwalten")
    sub = parser.add_subparsers(dest="befehl", required=True)
    sub.add_parser("liste", help="alle Zugänge anzeigen")
    p_k = sub.add_parser("klasse", help="neue Klasse anlegen")
    p_k.add_argument("key", help="Kürzel/Ordnername, z. B. DP1ET")
    p_p = sub.add_parser("prof", help="neuen Kollegen anlegen")
    p_p.add_argument("name", help='Anzeigename, z. B. "Marc Lichter"')
    p_w = sub.add_parser("passwort", help="Passwort neu würfeln")
    p_w.add_argument("wer", help="Klassen-Kürzel, Prof-Name oder 'admin'")
    args = parser.parse_args()

    cfg = lade()
    if args.befehl == "liste":
        cmd_liste(cfg)
    elif args.befehl == "klasse":
        cmd_klasse(cfg, args.key)
    elif args.befehl == "prof":
        cmd_prof(cfg, args.name)
    elif args.befehl == "passwort":
        cmd_passwort(cfg, args.wer)


if __name__ == "__main__":
    main()
