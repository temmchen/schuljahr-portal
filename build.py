#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — Schuljahr-Portal · Verschlüsselungs-Build
=====================================================

Liest die Inhalte aus dem OneDrive-Dashboard-Ordner (siehe zugangsdaten.json),
verschlüsselt ALLES mit AES-256-GCM und legt nur Chiffrat unter docs/vaults/ ab.
docs/ ist die GitHub-Pages-Wurzel — im öffentlichen Repo liegt also kein
einziges Klartext-Dokument und kein Passwort.

Aufruf:
    python3 build.py                # normaler Build
    python3 build.py --beispiele   # legt zusätzlich Beispiel-PDFs in leere Ordner

Krypto-Design (muss zu docs/index.html passen!):
  * Schlüsselableitung: PBKDF2-HMAC-SHA256, 600 000 Iterationen, Salt 16 B je Zugang
  * Umschlag-Verfahren: pro Vault ein zufälliger 256-Bit-Inhaltsschlüssel K;
    K wird für jeden berechtigten Zugang einzeln "eingewickelt"
    (AES-GCM über JSON {k, rolle, klasse, label})
  * Dateien/Manifeste: 12-B-Nonce || AES-256-GCM-Chiffrat (Tag enthalten)
  * Vault-/Datei-Namen im Repo sind Zufalls-IDs → keine Rückschlüsse auf Inhalte
"""

import argparse
import base64
import json
import secrets
import shutil
import sys
import unicodedata
from datetime import date
from pathlib import Path

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:
    sys.exit("Fehlendes Paket: bitte einmalig  pip3 install --user cryptography  ausführen.")

HIER = Path(__file__).resolve().parent
DOCS = HIER / "docs"
VAULTS = DOCS / "vaults"
KONFIG = HIER / "zugangsdaten.json"

PBKDF2_ITER = 600_000

# Bereiche wie im bisherigen Schuljahr-Dashboard (Ordnernamen identisch).
# BEWUSST OHNE "Noten": Notenlisten sind personenbezogene Daten und dürfen
# NICHT online — sie bleiben lokal (Noten-Dashboard offline, siehe README).
KATEGORIEN = [
    ("skripte",    "Skripte"),
    ("pruefungen", "Pruefungen"),
    ("aufgaben",   "Aufgaben"),
    ("sonstiges",  "Sonstiges"),
]
NIE_HOCHLADEN = "Noten"   # Ordner wird beim Build ignoriert (nur Hinweis ausgegeben)
SCHUELER_BEREICHE = {"skripte"}          # Schüler sehen NUR Skripte
REFERENTIELS_ORDNER = "Referentiels"


# ─────────────────────────── Krypto-Bausteine ───────────────────────────────

def b64(daten: bytes) -> str:
    return base64.b64encode(daten).decode("ascii")


def leite_kek_ab(passwort: str, salt: bytes) -> bytes:
    """Key-Encryption-Key aus Passwort ableiten (NFC-normalisiert wie im Browser)."""
    pw = unicodedata.normalize("NFC", passwort).encode("utf-8")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER)
    return kdf.derive(pw)


def verschluessele(key: bytes, klartext: bytes) -> bytes:
    """12-B-Nonce || GCM-Chiffrat — Format für Manifeste und Dateien."""
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, klartext, None)


def wickle_ein(kek: bytes, nutzlast: dict) -> dict:
    """Vault-Schlüssel + Rolleninfo für einen Zugang einwickeln."""
    nonce = secrets.token_bytes(12)
    ct = AESGCM(kek).encrypt(nonce, json.dumps(nutzlast, ensure_ascii=False).encode("utf-8"), None)
    return {"iv": b64(nonce), "ct": b64(ct)}


# ─────────────────────────── Inhalte einsammeln ─────────────────────────────

def anzeige_name(pfad: Path) -> str:
    return pfad.stem.replace("_", " ").strip()


def sammle_dateien(ordner: Path):
    """Alle sichtbaren Dateien eines Bereichsordners, alphabetisch."""
    if not ordner.is_dir():
        return []
    dateien = [p for p in sorted(ordner.iterdir(), key=lambda p: p.name.lower())
               if p.is_file() and not p.name.startswith(".")]
    return dateien


def modul_schluessel(fach: dict) -> list:
    """z. B. {'1':'ELTEC 3','2':'ELTEC 4'} → ['ELTEC3','ELTEC4'] (mit Semester)."""
    out = []
    for sem, name in sorted(fach.get("modul", {}).items()):
        out.append((sem, name, name.replace(" ", "")))
    return out


# ─────────────────────────── Beispiel-PDFs ──────────────────────────────────

def schreibe_beispiel_pdf(ziel: Path, titel: str, zeilen: list):
    """Minimal gültiges Ein-Seiten-PDF (Helvetica) ohne externe Pakete."""
    def esc(s):
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    inhalt = [f"BT /F1 22 Tf 72 770 Td ({esc(titel)}) Tj ET"]
    y = 728
    for z in zeilen:
        inhalt.append(f"BT /F1 12 Tf 72 {y} Td ({esc(z)}) Tj ET")
        y -= 20
    strom = "\n".join(inhalt).encode("latin-1", "replace")

    objekte = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(strom)).encode() + b" >>\nstream\n" + strom + b"\nendstream",
    ]
    puffer = bytearray(b"%PDF-1.4\n")
    versaetze = []
    for i, obj in enumerate(objekte, start=1):
        versaetze.append(len(puffer))
        puffer += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_start = len(puffer)
    puffer += f"xref\n0 {len(objekte)+1}\n".encode()
    puffer += b"0000000000 65535 f \n"
    for v in versaetze:
        puffer += f"{v:010d} 00000 n \n".encode()
    puffer += (f"trailer\n<< /Size {len(objekte)+1} /Root 1 0 R >>\n"
               f"startxref\n{xref_start}\n%%EOF\n").encode()
    ziel.write_bytes(bytes(puffer))


def lege_beispiele_an(inhalt: Path, klassen: list):
    """Ein paar BEISPIEL-PDFs in leere Bereichsordner legen (zum Online-Testen)."""
    angelegt = []
    for kl in klassen:
        basis = inhalt / kl["key"]
        beispiel_plan = [
            ("Skripte",    "BEISPIEL_Semesterskript.pdf", "Beispiel-Skript",
             ["Dies ist ein Beispiel-Dokument des Schuljahr-Portals.",
              "Es wurde AES-256-verschluesselt veroeffentlicht.",
              "Schueler-Logins sehen nur den Bereich Skripte."]),
            ("Pruefungen", "BEISPIEL_Klassenarbeit.pdf", "Beispiel-Klassenarbeit",
             ["Nur fuer Profs sichtbar.",
              "Schueler-Logins koennen diesen Bereich nicht entschluesseln."]),
            ("Aufgaben",   "BEISPIEL_Uebungsblatt.pdf", "Beispiel-Uebungsblatt",
             ["Nur fuer Profs sichtbar."]),
        ]
        for fach in kl.get("faecher", []):
            for _sem, _name, mk in modul_schluessel(fach):
                for ordner, dateiname, titel, zeilen in beispiel_plan:
                    ziel_ordner = basis / mk / ordner
                    if not ziel_ordner.is_dir():
                        continue
                    if sammle_dateien(ziel_ordner):
                        continue  # Ordner hat schon echte Inhalte
                    ziel = ziel_ordner / dateiname
                    schreibe_beispiel_pdf(ziel, f"{titel} · {_name}",
                                          zeilen + ["", f"Modul: {_name}   Klasse: {kl['key']}"])
                    angelegt.append(ziel)
    return angelegt


# ─────────────────────────── Haupt-Build ────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Schuljahr-Portal verschlüsselt bauen")
    parser.add_argument("--beispiele", action="store_true",
                        help="legt Beispiel-PDFs in leere Bereichsordner")
    args = parser.parse_args()

    if not KONFIG.is_file():
        sys.exit("zugangsdaten.json fehlt — Vorlage: zugangsdaten.beispiel.json")
    cfg = json.loads(KONFIG.read_text(encoding="utf-8"))

    inhalt = Path(cfg["inhalt"]).expanduser()
    if not inhalt.is_dir():
        sys.exit(f"Inhalts-Ordner nicht gefunden: {inhalt}")

    klassen = cfg.get("klassen", [])
    profs = cfg.get("profs", [])
    admin = cfg.get("admin")
    if not klassen or not admin:
        sys.exit("zugangsdaten.json braucht mindestens eine Klasse und einen Admin.")

    # Ordner-Existenz VOR der Zugangs-Registrierung prüfen — sonst entsteht ein
    # "verwaister" Zugang, dessen korrektes Passwort im Portal nichts öffnet.
    for kl in klassen:
        if not (inhalt / kl["key"]).is_dir():
            sys.exit(f"Ordner für Klasse {kl['key']} fehlt: {inhalt / kl['key']}\n"
                     f"→ Ordner anlegen oder Klasse aus zugangsdaten.json entfernen.")

    # ── Zugänge (Principals) einsammeln + Passwörter prüfen ──
    principals = []   # (id, salt, kek, rolle, klasse|None, label)
    passwoerter = []

    def registriere(passwort, rolle, klasse, label):
        # NFC-normalisiert prüfen — sonst rutschen NFD/NFC-"Zwillinge" (macOS!)
        # durch den Duplikat-Check, obwohl sie kryptographisch identisch sind.
        passwort = unicodedata.normalize("NFC", passwort or "")
        if len(passwort) < 8:
            sys.exit(f"Passwort für '{label}' fehlt oder ist kürzer als 8 Zeichen.")
        if passwort in passwoerter:
            sys.exit(f"Passwort für '{label}' ist doppelt vergeben — jedes Login braucht ein eigenes.")
        passwoerter.append(passwort)
        salt = secrets.token_bytes(16)
        pid = f"p{len(principals)}"
        print(f"  · Zugang {pid}: {label} ({rolle}) — leite Schlüssel ab …")
        kek = leite_kek_ab(passwort, salt)
        principals.append({"id": pid, "salt": salt, "kek": kek,
                           "rolle": rolle, "klasse": klasse, "label": label})

    print("Zugänge:")
    for kl in klassen:
        registriere(kl["passwort"], "schueler", kl["key"], f"Klasse {kl['name']}")
    for p in profs:
        registriere(p["passwort"], "prof", None, p.get("name", "Prof"))
    registriere(admin["passwort"], "admin", None, admin.get("name", "Admin"))

    # ── Beispiel-Inhalte (optional) ──
    if args.beispiele:
        neu = lege_beispiele_an(inhalt, klassen)
        if neu:
            print(f"\nBeispiel-PDFs angelegt ({len(neu)}):")
            for p in neu:
                print(f"  + {p.relative_to(inhalt)}")

    # ── Vaults bauen ──
    if VAULTS.exists():
        shutil.rmtree(VAULTS)
    VAULTS.mkdir(parents=True)

    index_vaults = []
    statistik = []

    def baue_vault(klasse_cfg, bereich_typ, module_daten, berechtigte):
        """bereich_typ: 'skripte' (Schüler+Profs) oder 'intern' (nur Profs/Admin)."""
        vid = secrets.token_hex(8)
        k_vault = secrets.token_bytes(32)
        vdir = VAULTS / vid
        (vdir / "f").mkdir(parents=True)

        gesamt = 0
        anzahl = 0
        for mk, bereiche in module_daten.items():
            for b_key, eintraege in bereiche.items():
                if b_key == "referentiels":
                    slots = [eintraege.get("formation"), eintraege.get("evaluation")] + \
                            eintraege.get("weitere", [])
                    eintraege = [e for e in slots if e]
                for e in eintraege:
                    quelle = Path(e.pop("_pfad"))
                    daten = quelle.read_bytes()
                    fid = secrets.token_hex(12)
                    (vdir / "f" / f"{fid}.enc").write_bytes(verschluessele(k_vault, daten))
                    e["id"] = fid
                    e["groesse"] = len(daten)
                    gesamt += len(daten)
                    anzahl += 1
                    if len(daten) > 95 * 1024 * 1024:
                        print(f"  ⚠️  {quelle.name}: über 95 MB — GitHub-Limit ist 100 MB/Datei!")

        # Modul-Schlüssel EXPLIZIT mitliefern (mkeys), damit der Browser exakt die
        # Keys benutzt, mit denen dieses Manifest gebaut wurde — keine getrennte
        # Ableitung Python/JS (Whitespace-Semantik von \s+ vs. replace(" ","")).
        faecher_mit_keys = []
        for f in klasse_cfg.get("faecher", []):
            f2 = dict(f)
            f2["mkeys"] = {sem: name.replace(" ", "")
                           for sem, name in f.get("modul", {}).items()}
            faecher_mit_keys.append(f2)
        manifest = {
            "klasse": klasse_cfg["key"],
            "name": klasse_cfg["name"],
            "bereich": bereich_typ,
            "faecher": faecher_mit_keys,
            "module": module_daten,
        }
        (vdir / "m.enc").write_bytes(
            verschluessele(k_vault, json.dumps(manifest, ensure_ascii=False).encode("utf-8")))

        wraps = []
        for pr in berechtigte:
            nutzlast = {"k": b64(k_vault), "rolle": pr["rolle"],
                        "klasse": pr["klasse"], "label": pr["label"]}
            w = wickle_ein(pr["kek"], nutzlast)
            w["p"] = pr["id"]
            wraps.append(w)

        index_vaults.append({"id": vid, "wraps": wraps, "manifest": f"vaults/{vid}/m.enc"})
        statistik.append((klasse_cfg["key"], bereich_typ, anzahl, gesamt))

    profs_und_admin = [p for p in principals if p["rolle"] in ("prof", "admin")]

    for kl in klassen:
        basis = inhalt / kl["key"]
        if not basis.is_dir():
            print(f"  ⚠️  Ordner fehlt für Klasse {kl['key']}: {basis}")
            continue

        skripte_module, intern_module = {}, {}
        for fach in kl.get("faecher", []):
            for _sem, _mname, mk in modul_schluessel(fach):
                mdir = basis / mk
                if not mdir.is_dir():
                    print(f"  ⚠️  Modul-Ordner fehlt (Modul erscheint leer): {mdir}")
                noten_dateien = sammle_dateien(mdir / NIE_HOCHLADEN)
                if noten_dateien:
                    print(f"  🔒 {mk}/{NIE_HOCHLADEN}: {len(noten_dateien)} Datei(en) bleiben "
                          f"OFFLINE (werden nie hochgeladen)")
                sk = [{"name": anzeige_name(p), "typ": p.suffix.lstrip(".").lower(), "_pfad": str(p)}
                      for p in sammle_dateien(mdir / "Skripte")]
                skripte_module[mk] = {"skripte": sk}

                intern = {}
                for b_key, ordner in KATEGORIEN:
                    if b_key == "skripte":
                        continue
                    intern[b_key] = [{"name": anzeige_name(p), "typ": p.suffix.lstrip(".").lower(),
                                      "_pfad": str(p)} for p in sammle_dateien(mdir / ordner)]
                refs = {"formation": None, "evaluation": None, "weitere": []}
                for p in sammle_dateien(mdir / REFERENTIELS_ORDNER):
                    eintrag = {"name": anzeige_name(p), "typ": p.suffix.lstrip(".").lower(),
                               "_pfad": str(p)}
                    nl = p.name.lower()
                    if "formation" in nl and not refs["formation"]:
                        refs["formation"] = eintrag
                    elif "evaluation" in nl and not refs["evaluation"]:
                        refs["evaluation"] = eintrag
                    else:
                        refs["weitere"].append(eintrag)
                intern["referentiels"] = refs
                intern_module[mk] = intern

        schueler_zugang = [p for p in principals if p["rolle"] == "schueler" and p["klasse"] == kl["key"]]
        baue_vault(kl, "skripte", skripte_module, schueler_zugang + profs_und_admin)
        baue_vault(kl, "intern", intern_module, profs_und_admin)

    # ── Öffentlicher Index (enthält KEIN Geheimnis) ──
    index = {
        "v": 1,
        "schuljahr": cfg.get("schuljahr", ""),
        "erstellt": date.today().isoformat(),
        "kdf": {"typ": "PBKDF2-SHA256", "iter": PBKDF2_ITER},
        "principals": [{"id": p["id"], "salt": b64(p["salt"])} for p in principals],
        "vaults": index_vaults,
    }
    (VAULTS / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    (DOCS / ".nojekyll").write_text("")

    # ── Zusammenfassung ──
    print("\nVaults:")
    gesamt_bytes = 0
    for klasse, typ, anzahl, groesse in statistik:
        gesamt_bytes += groesse
        print(f"  {klasse:10s} {typ:8s} {anzahl:3d} Datei(en)  {groesse/1024:8.1f} KiB")
    print(f"\nGesamt verschlüsselt: {gesamt_bytes/1024/1024:.2f} MiB "
          f"(GitHub-Pages-Limit ≈ 1 GB pro Site)")
    print("Fertig. → docs/ committen und pushen, Passwörter bleiben lokal.")


if __name__ == "__main__":
    main()
