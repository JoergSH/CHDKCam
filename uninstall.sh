#!/usr/bin/env bash
# CHDKCam entfernen:  sudo bash /opt/chdkcam/uninstall.sh [--purge]
# Bilder/Einstellungen bleiben erhalten, ausser mit --purge.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Bitte mit sudo starten"; exit 1; }
DATA=$(sed -n 's/^CHDKCAM_DATA=//p' /etc/default/chdkcam 2>/dev/null || true)
systemctl disable --now chdkcam-web.service chdkcam-capture.timer 2>/dev/null || true
rm -f /etc/systemd/system/chdkcam-*.service /etc/systemd/system/chdkcam-*.timer
systemctl daemon-reload
rm -rf /opt/chdkcam /etc/default/chdkcam
if [ "${1:-}" = "--purge" ] && [ -n "$DATA" ]; then
  rm -rf "$DATA"
  echo "Datenordner $DATA geloescht."
fi
echo "CHDKCam entfernt."
