#!/usr/bin/env python3
"""
Web-Uploads einsammeln — macht beide Wege gleichwertig.

Problem: Der Mac-Build erzeugt das Portal komplett aus OneDrive. Eine Datei, die
nur im Browser hochgeladen wurde, gibt es dort nicht — sie verschwände beim
nächsten Veröffentlichen.

Lösung: Vor jedem Build wird geprüft, welche Dateien im (frisch gepullten)
Portal stehen, aber nicht aus einem Mac-Build stammen. Genau die werden
entschlüsselt und in den passenden OneDrive-Bereichsordner geschrieben.
Danach sind sie ganz normale Inhalte — beide Wege führen zum selben Ziel.

Unterscheidung „Web-Upload" ↔ „am Mac gelöscht":
  .build-state.json listet jede Datei-ID, die ein Mac-Build erzeugt hat.
  · ID unbekannt        → kam aus dem Browser  → wird eingesammelt.
  · ID bekannt, Quelle weg → wurde bewusst gelöscht → wird NICHT zurückgeholt.

Aufruf:  python3 web_einsammeln.py [--trocken]
"""
import base64
import json
import sys
import unicodedata
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    sys.exit("Fehlendes Paket: pip3 install --user cryptography")

HIER = Path(__file__).resolve().parent
VAULTS = HIER / "docs" / "vaults"
KONFIG = HIER / "zugangsdaten.json"
BUILD_STATE = HIER / ".build-state.json"

ORDNER = {"skripte": "Skripte", "pruefungen": "Pruefungen", "aufgaben": "Aufgaben",
          "sonstiges": "Sonstiges", "referentiels": "Referentiels"}


# ───────────────────────── Schuljahr ────────────────────────────────────────
# EINE Quelle der Wahrheit: <Dashboard>/aktuelles-jahr.txt (z. B. "2026-2027").
# Veröffentlicht wird immer nur dieses Jahr — ältere Jahrgänge bleiben in
# OneDrive liegen und halten das Portal klein.

def jahr_von(dashboard) -> str:
    from pathlib import Path as _P
    marke = _P(dashboard) / "aktuelles-jahr.txt"
    try:
        j = marke.read_text(encoding="utf-8").strip()
        if j:
            return j
    except Exception:
        pass
    jahre = sorted(p.name for p in _P(dashboard).iterdir()
                   if p.is_dir() and len(p.name) == 9 and p.name[4] == "-" and p.name[:4].isdigit())
    return jahre[-1] if jahre else "2026-2027"


def jahr_anzeige(j: str) -> str:
    return j.replace("-", " – ")


def entschluessele(key: bytes, blob: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)


def sicherer_name(name: str, typ: str) -> str:
    """Dateiname aus dem Manifest zurückbauen — ohne Pfad-Tricks."""
    roh = f"{unicodedata.normalize('NFC', name).strip()}.{typ.strip().lower()}"
    roh = roh.replace("/", "-").replace("\\", "-").lstrip(".")
    return roh or "Dokument.pdf"


def eintraege_des_moduls(bereiche: dict):
    """→ (bereich_key, eintrag) für alle Dateien eines Moduls."""
    for b_key, wert in bereiche.items():
        if b_key == "referentiels":
            for e in [wert.get("formation"), wert.get("evaluation")] + (wert.get("weitere") or []):
                if e:
                    yield b_key, e
        else:
            for e in (wert or []):
                yield b_key, e


def einsammeln(trocken=False):
    if not BUILD_STATE.exists():
        return {"geholt": [], "hinweise": ["kein .build-state.json — erster Build, nichts einzusammeln"],
                "fehler": []}
    state = json.loads(BUILD_STATE.read_text(encoding="utf-8"))
    schluessel = {v["id"]: base64.b64decode(v["key"]) for v in state.get("vaults", {}).values()}
    bekannt = {d["fid"] for d in state.get("dateien", {}).values()}
    dashboard = Path(json.loads(KONFIG.read_text(encoding="utf-8"))["inhalt"])
    inhalt = dashboard / jahr_von(dashboard)

    idx_datei = VAULTS / "index.json"
    if not idx_datei.exists():
        return {"geholt": [], "hinweise": ["docs/vaults/index.json fehlt"], "fehler": []}
    idx = json.loads(idx_datei.read_text(encoding="utf-8"))

    geholt, hinweise, fehler = [], [], []
    for v in idx.get("vaults", []):
        vid = v["id"]
        key = schluessel.get(vid)
        if key is None:
            hinweise.append(f"Tresor {vid[:8]}… ist dem Mac unbekannt "
                            f"(im Browser angelegt?) — bitte Klasse in zugangsdaten.json ergänzen")
            continue
        m_datei = VAULTS / vid / "m.enc"
        if not m_datei.exists():
            continue
        try:
            manifest = json.loads(entschluessele(key, m_datei.read_bytes()))
        except Exception as ex:
            fehler.append(f"Manifest {vid[:8]}… nicht lesbar: {ex}")
            continue
        klasse = manifest.get("klasse", "?")
        for mk, bereiche in (manifest.get("module") or {}).items():
            for b_key, e in eintraege_des_moduls(bereiche):
                fid = e.get("id")
                if not fid or fid in bekannt:
                    continue                      # stammt aus einem Mac-Build
                ordner = ORDNER.get(b_key)
                if not ordner:
                    continue
                ziel = inhalt / klasse / mk / ordner / sicherer_name(e.get("name", ""), e.get("typ", "pdf"))
                if ziel.exists():
                    continue                      # liegt schon in OneDrive
                blob = VAULTS / vid / "f" / f"{fid}.enc"
                if not blob.exists():
                    fehler.append(f"{ziel.name}: Chiffrat {fid[:8]}… fehlt")
                    continue
                try:
                    daten = entschluessele(key, blob.read_bytes())
                except Exception as ex:
                    fehler.append(f"{ziel.name}: nicht entschlüsselbar ({ex})")
                    continue
                if not trocken:
                    ziel.parent.mkdir(parents=True, exist_ok=True)
                    ziel.write_bytes(daten)
                geholt.append(f"{klasse}/{mk}/{ordner}/{ziel.name}")
    return {"geholt": geholt, "hinweise": hinweise, "fehler": fehler}


def main():
    trocken = "--trocken" in sys.argv
    e = einsammeln(trocken)
    if trocken:
        print("TROCKENLAUF — es wird nichts geschrieben.\n")
    if e["geholt"]:
        print(f"Aus dem Portal nach OneDrive geholt: {len(e['geholt'])}")
        for x in e["geholt"]:
            print(f"  ↓ {x}")
    else:
        print("Keine Browser-Uploads offen — OneDrive ist vollständig.")
    for h in e["hinweise"]:
        print(f"  ℹ️  {h}")
    for f in e["fehler"]:
        print(f"  ❌ {f}")
    return 1 if e["fehler"] else 0


if __name__ == "__main__":
    sys.exit(main())
