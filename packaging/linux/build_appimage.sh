#!/usr/bin/env bash
# Build a Linux AppImage from the PyInstaller output (dist/NeuroCrunch or dist/NeuroCrunch/).
# Usage: bash packaging/linux/build_appimage.sh <version>
# Produces: dist/NeuroCrunch-<version>-linux.AppImage
#
# AppImage is a single self-contained executable — no install, no root — which makes
# it the cleanest target for the in-app updater (download new file, chmod +x, replace).
set -euo pipefail

VERSION="${1:?usage: build_appimage.sh <version>}"
ARCH="x86_64"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DIST="$ROOT/dist"
APPDIR="$DIST/NeuroCrunch.AppDir"

echo ">> Assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"

if [ -d "$DIST/NeuroCrunch" ]; then
  cp -a "$DIST/NeuroCrunch/." "$APPDIR/usr/bin/"
else
  cp "$DIST/NeuroCrunch" "$APPDIR/usr/bin/"
fi

# Launcher: resolve our own location and exec the frozen binary.
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/NeuroCrunch" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# Desktop entry (required by appimagetool; must live at the AppDir root).
cat > "$APPDIR/neurocrunch.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=NeuroCrunch
Exec=NeuroCrunch
Icon=neurocrunch
Categories=Science;Education;
Terminal=false
EOF

# Icon (also required). Use the bundled PNG if present, otherwise drop in a tiny
# placeholder so the build still succeeds until a real icon is added.
if [ -f "$ROOT/assets/icons/icon.png" ]; then
  cp "$ROOT/assets/icons/icon.png" "$APPDIR/neurocrunch.png"
else
  echo ">> assets/icons/icon.png not found — using placeholder icon"
  base64 -d > "$APPDIR/neurocrunch.png" <<'EOF'
iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAQAAADZc7J/AAAAHUlEQVR42u3BAQ0AAADCoPdPbQ43
oAAAAAAAAAAAAL4NIQAAAWnyKuUAAAAASUVORK5CYII=
EOF
fi
cp "$APPDIR/neurocrunch.png" "$APPDIR/.DirIcon"

echo ">> Fetching appimagetool"
TOOL="$DIST/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
  curl -fsSL -o "$TOOL" \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$ARCH.AppImage"
  chmod +x "$TOOL"
fi

echo ">> Building AppImage"
OUT="$DIST/NeuroCrunch-$VERSION-linux.AppImage"
# --appimage-extract-and-run avoids needing FUSE on CI runners.
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"

echo ">> Done: $OUT"
