#!/bin/sh
# chdkptp (CHDK-PTP-Client) aus dem Quellcode bauen.
# Aufruf als normaler Benutzer: ./tools/build-chdkptp.sh   (fragt fuer apt nach sudo)
# Ergebnis: ~/chdkptp/chdkptp-run.sh
set -e
DEST="${CHDKPTP_DIR:-$HOME/chdkptp}"
SRC_ZIP=https://github.com/svn2github/chdkptp/archive/refs/heads/master.zip

if [ -z "${SKIP_APT:-}" ]; then
  echo "Pakete installieren ..."
  sudo apt-get install -y build-essential liblua5.2-dev libusb-dev libreadline-dev curl unzip
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -sL -o "$TMP/src.zip" "$SRC_ZIP"
unzip -q "$TMP/src.zip" -d "$TMP"
rm -rf "$DEST"
mv "$TMP/chdkptp-master" "$DEST"
cd "$DEST"
cp config-sample-linux.mk config.mk
sed -i 's/^DEBUG=1/#DEBUG=1/' config.mk
# neuere gcc-Versionen nutzen C23; der alte Code braucht gnu17
make CC="gcc -std=gnu17" >"$TMP/build.log" 2>&1 || { tail -30 "$TMP/build.log"; echo "Bau fehlgeschlagen"; exit 1; }

cat > chdkptp-run.sh <<EOF
#!/bin/sh
CHDKPTP_DIR=$DEST
export LUA_PATH="\$CHDKPTP_DIR/lua/?.lua;;"
exec "\$CHDKPTP_DIR/chdkptp" "\$@"
EOF
chmod +x chdkptp-run.sh
echo "Fertig: $DEST/chdkptp-run.sh"
"$DEST/chdkptp-run.sh" -e"version"
