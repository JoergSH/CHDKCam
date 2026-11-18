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

```
git clone https://github.com/JoergSH/CHDKCam.git
cd CHDKCam
./tools/build-chdkptp.sh        # chdkptp bauen (einmalig, ~/chdkptp)
sudo ./install.sh               # App nach /opt/chdkcam, Dienste einrichten
```
Weboberfläche: `http://<rechner>:8081`

Update: `git pull && sudo ./install.sh`

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
4. Falls nur der kleine Build drauf ist: `./tools/upload-lualib.sh sx20-102d`
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
