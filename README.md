# CHDKCam

Zeitraffer mit einer Canon-Kompaktkamera unter [CHDK](https://chdk.fandom.com/wiki/CHDK)
(getestet: PowerShot SX20 IS, Firmware 1.02D, CHDK 1.6.1), gesteuert per USB von einem Linux-Rechner.

Pro Aufnahme-Runde werden mehrere **Positionen** angefahren – z. B. ein Übersichtsbild und ein
Bild mit Zoom auf eine Blüte. Jede Position hat eigene Einstellungen für Zoom, Fokus, Belichtungszeit,
ISO, Blitz und Weißabgleich. Die Bilder werden direkt auf den Rechner übertragen (`remoteshoot`),
auf der SD-Karte wird nichts gespeichert.

Weboberfläche: aktuelle Bilder, Positionen einrichten (Sucherbild/Probebild), Galerie,
Zeitraffer-Videos pro Position, Einstellungen und Logs.

## Unterstützte Kameras

Grundsätzlich jede Canon PowerShot/IXUS, für die es CHDK gibt – entscheidend sind Modell **und**
Firmware-Version:

- [CHDK Autobuild](https://mighty-hoernsche.de/) – alle Builds nach Modell und Firmware
- [CHDK Wiki: Downloads](https://chdk.fandom.com/wiki/Downloads) – Übersicht und Installation
- [CHDK Wiki: SX20](https://chdk.fandom.com/wiki/SX20) – Hinweise zur getesteten Kamera

Zoomstufen, Blitz- und Weißabgleich-Werte sind an der SX20 ermittelt; bei anderen Modellen
können sie abweichen.

## Installation

Ein Befehl auf dem Linux-Rechner (Debian, Ubuntu, Mint, Raspberry Pi OS …), als normaler Benutzer:

```
curl -fsSL https://raw.githubusercontent.com/JoergSH/chdkcam/main/install.sh | bash
```

Der Installer installiert die nötigen Pakete, baut [chdkptp](https://app.assembla.com/spaces/chdkptp)
nach `~/chdkptp`, kopiert das Programm nach `/opt/chdkcam` und richtet die Dienste ein.
Danach im Browser `http://<IP-des-Rechners>:8081` öffnen.

Mit Optionen:
```
curl -fsSL https://raw.githubusercontent.com/JoergSH/chdkcam/main/install.sh | bash -s -- --port 8082 --data /mnt/usb/chdkcam
```

| Option | Bedeutung | Standard |
|---|---|---|
| `--port N` | Port der Weboberfläche | 8081 |
| `--data DIR` | Datenordner für Bilder, Videos, Einstellungen | `~/chdkcam` |
| `--user NAME` | Benutzer, unter dem CHDKCam läuft | aufrufender Benutzer |
| `--rebuild-chdkptp` | chdkptp neu bauen | nur wenn es fehlt |
| `--no-chdkptp` | chdkptp nicht bauen | – |
| `--no-start` | nur installieren, nicht starten | – |

Alternativ aus dem geklonten Repo: `git clone https://github.com/JoergSH/chdkcam.git && cd chdkcam && bash install.sh`

**Update:** den Installer einfach erneut ausführen. Einstellungen und Bilder bleiben erhalten.

**Entfernen:** `sudo bash /opt/chdkcam/uninstall.sh` (mit `--purge` wird auch der Datenordner gelöscht).

## Kamera vorbereiten

1. Firmware-Version ermitteln: Foto machen, `exiftool -FirmwareVersion IMG_xxxx.JPG`
   (der Buchstabe, z. B. 1.02**D**, steht nur im Kamera-Display: leere Datei `ver.req` auf die Karte,
   im Wiedergabemodus FUNC.SET halten + DISP).
2. Passenden **full**-Build von [mighty-hoernsche.de](https://mighty-hoernsche.de/) laden.
3. Karte bootfähig machen. Bei der SX20 gibt es kein `PS.FI2`, CHDK startet nur von einer
   **FAT16**-Karte mit Boot-Marker (Karte ≤ 4 GB, hier `/dev/sdX1`):
   ```
   sudo sfdisk --part-type /dev/sdX 1 6
   sudo mkfs.fat -F 16 -s 128 -n CANON_DC /dev/sdX1
   echo -n BOOTDISK | sudo dd of=/dev/sdX1 bs=1 seek=64 count=8 conv=notrunc
   ```
   Danach den Inhalt der ZIP-Datei auf die Karte entpacken, Schreibschutz auf **LOCK**, einlegen.
4. Falls nur der kleine Build drauf ist: `/opt/chdkcam/tools/upload-lualib.sh sx20-102d`
5. An der Kamera: *Autom. Abschaltung: Aus*, Modus **P**, ggf. manuellen Weißabgleich messen.
6. Dauerbetrieb nur mit Netzteil (SX20: DC IN 7,4 V, 2 A).

## Hinweise SX20

- Nach dem Auslösen braucht die Kamera eine Pause, bevor gezoomt wird, sonst stürzt sie ab
  („Pause nach Auslösen“, Standard 4000 ms).
- 129 Zoomstufen: 0 = 28 mm, 128 = 560 mm.

## Kommandozeile

```
python3 /opt/chdkcam/core.py camera      # Kamera-Status
python3 /opt/chdkcam/core.py capture     # Runde sofort aufnehmen
```
Daten: `~/chdkcam` (Bilder, Miniaturen, Videos, Logs, `config.json`).
