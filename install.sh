#!/usr/bin/env bash
# CHDKCam installer – Zeitraffer mit Canon-Kamera unter CHDK, mit Weboberflaeche
#
#   curl -fsSL https://raw.githubusercontent.com/JoergSH/chdkcam/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/JoergSH/chdkcam/main/install.sh | bash -s -- --port 8082
#
# oder im geklonten Repo:  bash install.sh [Optionen]
#
# Erneut ausfuehren = Update (Einstellungen und Bilder bleiben erhalten).
set -euo pipefail

REPO="${CHDKCAM_REPO:-JoergSH/chdkcam}"
BRANCH="${CHDKCAM_BRANCH:-main}"
APPDIR="/opt/chdkcam"
ENVFILE="/etc/default/chdkcam"
UNITDIR="/etc/systemd/system"

PORT=""
DATA=""
RUN_USER=""
START=1
BUILD_PTP=auto

c_ok=$'\e[32m'; c_warn=$'\e[33m'; c_err=$'\e[31m'; c_0=$'\e[0m'
[ -t 1 ] || { c_ok=""; c_warn=""; c_err=""; c_0=""; }
say()  { echo "${c_ok}==>${c_0} $*"; }
warn() { echo "${c_warn}WARNUNG:${c_0} $*" >&2; }
die()  { echo "${c_err}FEHLER:${c_0} $*" >&2; exit 1; }

usage() {
  cat <<EOF
CHDKCam installieren / aktualisieren

Optionen:
  --port N          Port der Weboberflaeche (Standard: 8081)
  --data DIR        Datenordner fuer Bilder/Videos/Einstellungen (Standard: ~/chdkcam)
  --user NAME       Benutzer, unter dem CHDKCam laeuft (Standard: aufrufender Benutzer)
  --rebuild-chdkptp chdkptp neu bauen, auch wenn es schon vorhanden ist
  --no-chdkptp      chdkptp nicht bauen (muss dann unter ~/chdkptp vorhanden sein)
  --no-start        Dienste installieren, aber nicht starten
  -h, --help        Diese Hilfe
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:?}"; shift 2 ;;
    --data) DATA="${2:?}"; shift 2 ;;
    --user) RUN_USER="${2:?}"; shift 2 ;;
    --rebuild-chdkptp) BUILD_PTP=1; shift ;;
    --no-chdkptp) BUILD_PTP=0; shift ;;
    --no-start) START=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unbekannte Option: $1 (siehe --help)" ;;
  esac
done

# ---------------------------------------------------------------- Benutzer / sudo
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
  RUN_USER="${RUN_USER:-${SUDO_USER:-}}"
  [ -n "$RUN_USER" ] && [ "$RUN_USER" != root ] \
    || die "Bitte als normaler Benutzer starten (nicht als root), oder --user NAME angeben."
else
  command -v sudo >/dev/null || die "sudo fehlt"
  SUDO="sudo"
  RUN_USER="${RUN_USER:-$(id -un)}"
fi
RUN_HOME=$(getent passwd "$RUN_USER" | cut -d: -f6)
[ -d "$RUN_HOME" ] || die "Benutzer $RUN_USER unbekannt"
as_user() { if [ "$(id -un)" = "$RUN_USER" ]; then "$@"; else $SUDO -u "$RUN_USER" "$@"; fi; }

# vorhandene Einstellungen beim Update beibehalten
if [ -f "$ENVFILE" ]; then
  OLD_PORT=$(sed -n 's/^CHDKCAM_PORT=//p' "$ENVFILE")
  OLD_DATA=$(sed -n 's/^CHDKCAM_DATA=//p' "$ENVFILE")
fi
PORT="${PORT:-${OLD_PORT:-8081}}"
DATA="${DATA:-${OLD_DATA:-$RUN_HOME/chdkcam}}"
[[ "$PORT" =~ ^[0-9]+$ ]] || die "--port: Zahl erwartet"

# ---------------------------------------------------------------- Quellen
SRC=""
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/chdkcam/core.py" ]; then
  SRC="$HERE"
else
  say "Lade CHDKCam von github.com/$REPO ($BRANCH) ..."
  command -v curl >/dev/null || $SUDO apt-get install -y curl
  TMPSRC=$(mktemp -d)
  trap 'rm -rf "$TMPSRC"' EXIT
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" \
    | tar xz -C "$TMPSRC" --strip-components=1 || die "Download fehlgeschlagen"
  chmod a+rx "$TMPSRC"
  SRC="$TMPSRC"
fi

# ---------------------------------------------------------------- Pakete
say "Pakete pruefen ..."
NEED=()
for p in python3 ffmpeg; do command -v "$p" >/dev/null || NEED+=("$p"); done
PTP="$RUN_HOME/chdkptp/chdkptp-run.sh"
if [ "$BUILD_PTP" = 1 ] || { [ "$BUILD_PTP" = auto ] && [ ! -x "$PTP" ]; }; then
  NEED+=(build-essential liblua5.2-dev libusb-dev libreadline-dev curl unzip)
  DO_PTP=1
else
  DO_PTP=0
fi
if [ ${#NEED[@]} -gt 0 ]; then
  $SUDO apt-get update -qq
  $SUDO apt-get install -y "${NEED[@]}"
fi

# ---------------------------------------------------------------- chdkptp
if [ "$DO_PTP" = 1 ]; then
  say "Baue chdkptp nach $RUN_HOME/chdkptp ..."
  as_user env CHDKPTP_DIR="$RUN_HOME/chdkptp" SKIP_APT=1 bash "$SRC/tools/build-chdkptp.sh"
fi
[ -x "$PTP" ] || warn "chdkptp nicht gefunden ($PTP) - Aufnahmen werden fehlschlagen"

# ---------------------------------------------------------------- Programm
say "Installiere nach $APPDIR ..."
$SUDO mkdir -p "$APPDIR"
$SUDO cp -r "$SRC/chdkcam/." "$APPDIR/"
$SUDO cp "$SRC/uninstall.sh" "$APPDIR/" 2>/dev/null || true
$SUDO mkdir -p "$APPDIR/tools"
$SUDO cp "$SRC/tools/"*.sh "$APPDIR/tools/"
$SUDO chmod 755 "$APPDIR"/*.py "$APPDIR"/tools/*.sh
$SUDO find "$APPDIR" -name __pycache__ -prune -exec rm -rf {} +

printf 'CHDKCAM_DATA=%s\nCHDKCAM_PORT=%s\n' "$DATA" "$PORT" | $SUDO tee "$ENVFILE" >/dev/null
as_user mkdir -p "$DATA"

for f in "$SRC"/systemd/*; do
  sed -e "s#@USER@#$RUN_USER#g" -e "s#@APPDIR@#$APPDIR#g" -e "s#@ENVFILE@#$ENVFILE#g" "$f" \
    | $SUDO tee "$UNITDIR/$(basename "$f")" >/dev/null
done

# Kamera-Zugriff: libgphoto2-udev-Regeln geben der Gruppe plugdev Zugriff
$SUDO usermod -aG plugdev "$RUN_USER" || true

# gvfs (Desktop) soll sich die Kamera nicht schnappen
as_user mkdir -p "$RUN_HOME/.config/systemd/user"
as_user ln -sf /dev/null "$RUN_HOME/.config/systemd/user/gvfs-gphoto2-volume-monitor.service"
$SUDO pkill -f gvfs-gphoto2-volume-monitor 2>/dev/null || true
$SUDO pkill -f gvfsd-gphoto2 2>/dev/null || true

$SUDO systemctl daemon-reload
if [ "$START" = 1 ]; then
  $SUDO systemctl enable --now chdkcam-web.service chdkcam-capture.timer
  $SUDO systemctl restart chdkcam-web.service
else
  $SUDO systemctl enable chdkcam-web.service chdkcam-capture.timer
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
say "Fertig. Weboberflaeche: http://${IP:-<rechner>}:$PORT   (Daten: $DATA)"
echo "    Kamera vorbereiten: siehe https://github.com/$REPO#kamera-vorbereiten"
