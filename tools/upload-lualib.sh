#!/bin/sh
# Laedt die CHDK-Lua-Bibliothek (CHDK/LUALIB) aus einem CHDK-"full"-Build auf die Kamera.
# Noetig, wenn auf der Karte nur der kleine Build liegt (sonst funktionieren Fokus/Belichtung nicht).
# Aufruf: ./tools/upload-lualib.sh <kamera-firmware>   z. B. sx20-102d
set -e
CAM="$1"
[ -n "$CAM" ] || { echo "Aufruf: $0 <modell-firmware>, z. B. sx20-102d"; exit 1; }
PTP="${CHDKPTP:-$HOME/chdkptp/chdkptp-run.sh}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
URL=$(curl -sL https://mighty-hoernsche.de/ | grep -oE "bins/$CAM-[0-9.]+-[0-9]+-full\.zip" | head -1)
[ -n "$URL" ] || { echo "Kein Build fuer $CAM gefunden"; exit 1; }
echo "Lade $URL"
curl -sL -o "$TMP/full.zip" "https://mighty-hoernsche.de/$URL"
unzip -q "$TMP/full.zip" -d "$TMP/full"
"$PTP" -c -e"mkdir A/CHDK/LUALIB" -e"mup $TMP/full/CHDK/LUALIB/ A/CHDK/LUALIB" -e"ls A/CHDK/LUALIB"
