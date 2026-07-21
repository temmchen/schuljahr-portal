# 🔐 Schuljahr-Portal

Verschlüsseltes Online-Dashboard für Klassen und Lehrpersonen — gehostet **kostenlos
auf GitHub Pages**, obwohl das Repository öffentlich ist: Sämtliche Dokumente liegen
ausschließlich als **AES-256-GCM-Chiffrat** im Repo. Entschlüsselt wird erst im
Browser, nach Eingabe des Passworts. Im Repo steht **kein einziges Passwort** und
kein Klartext-Dokument.

## Wer sieht was?

| Zugang | sieht |
|---|---|
| **Klasse** (ein Passwort pro Klasse) | nur 📘 **Skripte** der eigenen Klasse |
| **Prof** (ein Passwort pro Lehrperson) | **alles**: Skripte, Prüfungen, Aufgaben, Sonstiges, Référentiels — aller Klassen |
| **Admin** | wie Prof + 🛠️-Verwaltungskarte; verwaltet Passwörter & Build |

**📊 Noten sind bewusst KEIN Teil des Portals.** Notenlisten sind personenbezogene
Daten und dürfen nicht online — `build.py` ignoriert alle `Noten/`-Ordner
grundsätzlich (Ausgabe: „bleiben OFFLINE"). Dafür gibt es das separate
**Noten-Dashboard offline**: im OneDrive-Dashboard-Ordner
`python3 baue_noten_dashboard.py` ausführen → `Noten-Dashboard.html` per
Doppelklick öffnen. Beides liegt außerhalb dieses Repos und wird nie gepusht.

Die Trennung ist **kryptographisch**, nicht kosmetisch: Der Schüler-Vault und der
interne Vault (Prüfungen usw.) haben verschiedene Schlüssel. Mit einem
Klassen-Passwort lässt sich der interne Vault mathematisch nicht öffnen —
auch nicht durch Manipulation der Webseite.

## Alltag: neue Datei veröffentlichen

1. PDF wie gewohnt in den OneDrive-Ordner legen, z. B.
   `…/Dashboard/DP2ET/ELTEC3/Skripte/Mein_Skript.pdf`
2. Im Portal-Ordner ausführen:
   ```bash
   python3 build.py
   git add docs && git commit -m "Neue Inhalte" && git push
   ```
3. Nach 1–2 Minuten ist die Datei online — verschlüsselt.

Der Dateiname (ohne Endung, `_` → Leerzeichen) wird zum Anzeigenamen.
Ordner-Konvention pro Modul: `Skripte/ Pruefungen/ Aufgaben/ Sonstiges/ Referentiels/`
(im `Referentiels/`-Ordner werden Dateien mit „formation" bzw. „evaluation" im Namen
automatisch den beiden festen Slots zugeordnet). Der `Noten/`-Ordner existiert
weiterhin, wird aber **nie** hochgeladen.

## Passwörter & Zugänge verwalten

Am einfachsten mit dem Admin-Werkzeug (im Portal-Ordner):

```bash
python3 verwaltung.py liste                 # alle Zugänge + Passwörter anzeigen
python3 verwaltung.py klasse DP1ET          # neue Klasse (fragt Fächer ab, legt Ordner an)
python3 verwaltung.py prof "Marc Lichter"   # neuer Kollege
python3 verwaltung.py passwort DP2ET        # Passwort neu würfeln (Klasse/Prof/admin)
```

Jeder Befehl speichert `zugangsdaten.json`, baut das Portal neu und sagt dir den
Push-Befehl. Alternativ von Hand — alle Zugänge stehen in **`zugangsdaten.json`**
(liegt NUR lokal, ist per `.gitignore` vom Repo ausgeschlossen — niemals committen!):

- **Klasse hinzufügen:** Block in `klassen` kopieren, `key`/`name`/`passwort`/`faecher`
  anpassen, Ordner `…/Dashboard/<KEY>/<Modul>/<Bereich>/` anlegen.
- **Prof entfernen:** Eintrag in `profs` löschen (danach `build.py` + push).
- **Passwort ändern** (z. B. zum Schuljahresende): Passwort in der JSON ändern,
  dann `python3 build.py` + committen + pushen. Ab dann öffnet nur noch das neue
  Passwort die **aktuellen und künftigen** Inhalte.

> ⚠️ **Wichtig — was Passwort-Wechsel NICHT kann:** Git vergisst nichts. Alte
> Commits enthalten die früheren verschlüsselten Stände weiter, und die bleiben
> mit dem **alten** Passwort entschlüsselbar. Ist ein Prof-Passwort wirklich
> durchgesickert, gilt: alles, was bis dahin veröffentlicht war, ist als
> offengelegt zu betrachten. Wer das ausschließen will, legt das Repo neu an
> (Historie löschen: Repo löschen → neu erstellen → aktuellen Stand pushen)
> **und** verwendet die betroffenen Prüfungen nicht mehr unverändert.

Nach **jeder** Änderung an `zugangsdaten.json`: `build.py` ausführen und `docs/` pushen.

## Sicherheit (Kurzfassung)

- **Schlüsselableitung:** PBKDF2-HMAC-SHA256, 600 000 Iterationen, 16-Byte-Zufalls-Salt
  pro Zugang (OWASP-Empfehlung).
- **Verschlüsselung:** AES-256-GCM (authentifiziert — Manipulation fliegt auf),
  frischer Zufallsschlüssel pro Vault bei jedem Build, frische Nonce pro Datei.
- **Umschlag-Prinzip:** Der Vault-Schlüssel wird pro berechtigtem Zugang einzeln
  „eingewickelt". Rollen sind dadurch kryptographisch getrennt.
- **Öffentlich sichtbar** sind nur: Anzahl und Größe der verschlüsselten Dateien
  sowie die Anzahl der Zugänge. Keine Namen, keine Inhalte, keine Ordnerstruktur.
- **Sitzung:** bleibt bis zum Schließen des Tabs (sessionStorage). „Abmelden" löscht sie.

**Grenzen:** Wer ein Klassen-Passwort kennt, kann die Skripte natürlich weitergeben —
wie bei jedem geteilten Passwort. Und: **keine personenbezogenen Daten** hochladen.
Notenlisten sind deshalb komplett ausgeklammert (Noten-Dashboard offline, s. o.);
auch korrigierte Arbeiten mit Schülernamen gehören nicht in die Bereichsordner.

## Technik

```
Schuljahr-Portal/
├── build.py                    # scannt OneDrive-Inhalte, verschlüsselt → docs/vaults/
├── verwaltung.py               # Admin-Werkzeug: Klassen/Profs/Passwörter verwalten
├── zugangsdaten.json           # GEHEIM (gitignored): Passwörter, Klassen, Fächer
├── zugangsdaten.beispiel.json  # Vorlage ohne echte Passwörter
└── docs/                       # GitHub-Pages-Wurzel (öffentlich, nur Chiffrat)
    ├── index.html              # Portal: Login + Entschlüsselung im Browser (WebCrypto)
    └── vaults/
        ├── index.json          # Salts + eingewickelte Schlüssel (ohne Geheimnisse)
        └── <zufalls-id>/       # pro Vault: m.enc (Manifest) + f/<id>.enc (Dateien)
```

Einmalige Voraussetzung auf einem neuen Rechner: `pip3 install --user cryptography`

Lokal testen: `cd docs && python3 -m http.server 8125` → http://localhost:8125
(Direktes Öffnen der Datei per Doppelklick funktioniert nicht — `fetch()` braucht http/https.)

## Grenzen von GitHub Pages

- max. ~1 GB Site-Größe, max. 100 MB pro Datei — `build.py` warnt bei großen Dateien.
- Die Seite ist unter `https://<benutzer>.github.io/<repo>/` erreichbar; die URL darf
  man weitergeben, ohne Passwort ist dort nichts zu holen.
