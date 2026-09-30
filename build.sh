#!/usr/bin/env bash
set -euo pipefail

APP_ID="ducky-voice-optimizer"
APP_NAME="Ducky Voice Optimizer"
VERSION="1.3.0"
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_VENV="$ROOT_DIR/.build-venv"
RELEASE_DIR="$ROOT_DIR/release"
PYINSTALLER_DIST="$ROOT_DIR/dist/$APP_ID"

case "$(uname -m)" in
  x86_64)
    DEB_ARCH="amd64"
    APPIMAGE_ARCH="x86_64"
    ;;
  aarch64|arm64)
    DEB_ARCH="arm64"
    APPIMAGE_ARCH="aarch64"
    ;;
  *)
    echo "Unsupported Linux build architecture: $(uname -m)" >&2
    echo "Supported release targets are x86_64/amd64 and aarch64/arm64." >&2
    exit 2
    ;;
esac

for command in python3 dpkg-deb apt-get curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing build dependency: $command" >&2
    echo "Ubuntu setup: sudo apt install python3-venv dpkg-dev curl libportaudio2 libsndfile1 ffmpeg" >&2
    exit 2
  fi
done

mkdir -p "$RELEASE_DIR"
if [[ ! -d "$BUILD_VENV" ]]; then
  python3 -m venv "$BUILD_VENV"
fi

"$BUILD_VENV/bin/python" -m pip install --upgrade pip
"$BUILD_VENV/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt" -r "$ROOT_DIR/requirements-build.txt"
"$BUILD_VENV/bin/python" "$ROOT_DIR/packaging/make_icons.py"
"$BUILD_VENV/bin/python" -m PyInstaller --clean --noconfirm "$ROOT_DIR/packaging/ducky-voice-optimizer.spec"

if [[ ! -x "$PYINSTALLER_DIST/$APP_ID" ]]; then
  echo "PyInstaller output was not created: $PYINSTALLER_DIST/$APP_ID" >&2
  exit 1
fi

# Qt 6 requires libxcb-cursor on X11. Bundle it for AppImage portability when
# it is not installed on the build host; the Debian package declares it normally.
if ! ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor.so.0'; then
  XCB_CACHE="$ROOT_DIR/build/xcb-cursor"
  rm -rf "$XCB_CACHE"
  mkdir -p "$XCB_CACHE/packages" "$XCB_CACHE/extracted"
  (
    cd "$XCB_CACHE/packages"
    apt-get download "libxcb-cursor0:$DEB_ARCH"
  )
  XCB_PACKAGE="$(find "$XCB_CACHE/packages" -maxdepth 1 -name '*.deb' -print -quit)"
  dpkg-deb -x "$XCB_PACKAGE" "$XCB_CACHE/extracted"
  XCB_LIBRARY="$(find "$XCB_CACHE/extracted" -name 'libxcb-cursor.so.0' -print -quit)"
  if [[ -z "$XCB_LIBRARY" ]]; then
    echo "Unable to obtain libxcb-cursor.so.0 for the AppImage." >&2
    exit 1
  fi
  cp -L "$XCB_LIBRARY" "$PYINSTALLER_DIST/_internal/libxcb-cursor.so.0"
fi

# Build Debian package for the current native architecture.
DEB_ROOT="$ROOT_DIR/build/deb-root"
rm -rf "$DEB_ROOT"
mkdir -p \
  "$DEB_ROOT/DEBIAN" \
  "$DEB_ROOT/opt/$APP_ID" \
  "$DEB_ROOT/usr/bin" \
  "$DEB_ROOT/usr/share/applications" \
  "$DEB_ROOT/usr/share/icons/hicolor/512x512/apps" \
  "$DEB_ROOT/usr/share/doc/$APP_ID"
cp -a "$PYINSTALLER_DIST/." "$DEB_ROOT/opt/$APP_ID/"
ln -s "/opt/$APP_ID/$APP_ID" "$DEB_ROOT/usr/bin/$APP_ID"
cp "$ROOT_DIR/packaging/linux/ducky-voice-optimizer.desktop" "$DEB_ROOT/usr/share/applications/$APP_ID.desktop"
cp "$ROOT_DIR/assets/ducky-voice-optimizer-512.png" "$DEB_ROOT/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"
cp "$ROOT_DIR/TERMS.txt" "$DEB_ROOT/usr/share/doc/$APP_ID/terms"
cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $APP_ID
Version: $VERSION
Section: sound
Priority: optional
Architecture: $DEB_ARCH
Maintainer: Ducky Voice Optimizer contributors
Depends: libportaudio2, libsndfile1, libglib2.0-0, libgl1, libegl1, libxkbcommon-x11-0, libxcb-cursor0, ffmpeg
Installed-Size: $(du -sk "$DEB_ROOT/opt/$APP_ID" | cut -f1)
Description: Local AI voice enhancement and vocal separation
 DeepFilterNet3 fast enhancement, DPDFNet high-quality enhancement, voice mastering, microphone recording,
 project management, and UVR MDX-Net vocal/background separation.
EOF
chmod 0755 "$DEB_ROOT/opt/$APP_ID/$APP_ID"
dpkg-deb --root-owner-group --build "$DEB_ROOT" "$RELEASE_DIR/${APP_ID}_${VERSION}_${DEB_ARCH}.deb"

# Build an AppImage from the same tested PyInstaller bundle.
APPDIR="$ROOT_DIR/build/${APP_ID}.AppDir"
rm -rf "$APPDIR"
mkdir -p \
  "$APPDIR/usr/lib/$APP_ID" \
  "$APPDIR/usr/bin" \
  "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/512x512/apps"
cp -a "$PYINSTALLER_DIST/." "$APPDIR/usr/lib/$APP_ID/"
ln -s "../lib/$APP_ID/$APP_ID" "$APPDIR/usr/bin/$APP_ID"
cp "$ROOT_DIR/packaging/linux/AppRun" "$APPDIR/AppRun"
cp "$ROOT_DIR/packaging/linux/ducky-voice-optimizer.desktop" "$APPDIR/$APP_ID.desktop"
cp "$ROOT_DIR/packaging/linux/ducky-voice-optimizer.desktop" "$APPDIR/usr/share/applications/$APP_ID.desktop"
cp "$ROOT_DIR/assets/ducky-voice-optimizer-512.png" "$APPDIR/$APP_ID.png"
cp "$ROOT_DIR/assets/ducky-voice-optimizer-512.png" "$APPDIR/usr/share/icons/hicolor/512x512/apps/$APP_ID.png"
chmod 0755 "$APPDIR/AppRun" "$APPDIR/usr/lib/$APP_ID/$APP_ID"

APPIMAGETOOL="$ROOT_DIR/build/appimagetool-$APPIMAGE_ARCH.AppImage"
if [[ ! -x "$APPIMAGETOOL" ]]; then
  mkdir -p "$ROOT_DIR/build"
  curl --fail --location --retry 3 \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$APPIMAGE_ARCH.AppImage" \
    --output "$APPIMAGETOOL"
  chmod 0755 "$APPIMAGETOOL"
fi

APPIMAGE_OUTPUT="$RELEASE_DIR/${APP_ID}-${VERSION}-${APPIMAGE_ARCH}.AppImage"
ARCH="$APPIMAGE_ARCH" "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_OUTPUT" || \
  ARCH="$APPIMAGE_ARCH" "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$APPIMAGE_OUTPUT"
chmod 0755 "$APPIMAGE_OUTPUT"

echo
echo "$APP_NAME release artifacts created:"
echo "  $RELEASE_DIR/${APP_ID}_${VERSION}_${DEB_ARCH}.deb"
echo "  $APPIMAGE_OUTPUT"
echo
echo "Install the Debian package with:"
echo "  sudo dpkg -i $RELEASE_DIR/${APP_ID}_${VERSION}_${DEB_ARCH}.deb"
