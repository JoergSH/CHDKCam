#!/bin/sh
# CHDKCam installieren: sudo ./install.sh [benutzer]
set -e
[ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo starten: sudo ./install.sh"; exit 1; }
U="${1:-${SUDO_USER:-}}"
[ -n "$U" ] && [ "$U" != root ] || { echo "Benutzer angeben: sudo ./install.sh <benutzer>"; exit 1; }
H=$(getent passwd "$U" | cut -d: -f6)
SRC=$(cd "$(dirname "$0")" && pwd)
APP=/opt/chdkcam
ENVF=/etc/default/chdkcam

echo "Installiere nach $APP fuer Benutzer $U (Daten: $H/chdkcam)"
command -v ffmpeg >/dev/null || apt-get install -y ffmpeg
[ -x "$H/chdkptp/chdkptp-run.sh" ] || echo "HINWEIS: chdkptp fehlt - als $U ausfuehren: ./tools/build-chdkptp.sh"
mkdir -p "$APP"
cp -r "$SRC/chdkcam/." "$APP/"
chmod 755 "$APP"/*.py

[ -f "$ENVF" ] || cat > "$ENVF" <<EOF
CHDKCAM_DATA=$H/chdkcam
CHDKCAM_PORT=8081
EOF

for f in "$SRC"/systemd/*; do
  sed -e "s#@USER@#$U#g" -e "s#@APPDIR@#$APP#g" -e "s#@ENVFILE@#$ENVF#g" "$f" \
    > "/etc/systemd/system/$(basename "$f")"
done

# Benutzer braucht Zugriff auf die Kamera (udev von libgphoto2: Gruppe plugdev)
usermod -aG plugdev "$U" || true

# gvfs (Desktop) soll sich die Kamera nicht schnappen
sudo -u "$U" mkdir -p "$H/.config/systemd/user"
sudo -u "$U" ln -sf /dev/null "$H/.config/systemd/user/gvfs-gphoto2-volume-monitor.service"
pkill -f gvfs-gphoto2-volume-monitor 2>/dev/null || true
pkill -f gvfsd-gphoto2 2>/dev/null || true

sudo -u "$U" mkdir -p "$H/chdkcam"
systemctl daemon-reload
systemctl enable --now chdkcam-web.service chdkcam-capture.timer
systemctl restart chdkcam-web.service
IP=$(hostname -I | awk '{print $1}')
echo "Fertig. Weboberflaeche: http://$IP:8081"
