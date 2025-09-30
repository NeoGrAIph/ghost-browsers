#!/usr/bin/env bash
set -euo pipefail

FONT_DIR="/usr/share/fonts/truetype/windows10"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$FONT_DIR"
chmod 755 "$FONT_DIR"

# Map of filename -> download URL
cat <<'URLS' > "$TMP_DIR/fonts.list"
segoeui.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/segoeui.ttf
segoeuib.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/segoeuib.ttf
segoeuii.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/segoeuii.ttf
segoeuiz.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/segoeuiz.ttf
segoeuil.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/segoeuil.ttf
seguili.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguili.ttf
segoeuisl.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/segoeuisl.ttf
seguisli.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguisli.ttf
seguisb.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguisb.ttf
seguisbi.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguisbi.ttf
seguibl.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguibl.ttf
seguibli.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguibli.ttf
seguiemj.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguiemj.ttf
seguisym.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguisym.ttf
seguihis.ttf https://raw.githubusercontent.com/mrbvrz/segoe-ui-linux/master/font/seguihis.ttf
calibri.ttf https://raw.githubusercontent.com/theouys/MSFonts/main/calibri.ttf
calibrib.ttf https://raw.githubusercontent.com/theouys/MSFonts/main/calibrib.ttf
calibrii.ttf https://raw.githubusercontent.com/theouys/MSFonts/main/calibrii.ttf
URLS

while read -r name url; do
  echo "Downloading ${name}"
  curl -fsSL "$url" -o "$FONT_DIR/$name"
  chmod 644 "$FONT_DIR/$name"
done < "$TMP_DIR/fonts.list"
