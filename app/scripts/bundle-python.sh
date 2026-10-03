#!/bin/sh
# Standalone CPython + backend dependencies for the packaged app.
#   build/python  ->  Clover.app/Contents/Resources/python
# uv's managed CPython (python-build-standalone) is relocatable, so a copy
# runs from inside the bundle. The backend's own code ships separately as
# Resources/backend (electron-builder extraResources), not installed here.
set -eu
cd "$(dirname "$0")/.."
PY_VER=3.12
uv python install "$PY_VER" >/dev/null
SRC="$(dirname "$(dirname "$(uv python find "$PY_VER")")")"
rm -rf build/python
cp -R "$SRC" build/python
# a private copy: drop the externally-managed marker uv puts on it
rm -f build/python/lib/python$PY_VER/EXTERNALLY-MANAGED
# dependencies only, read from pyproject.toml (no dev/local extras)
DEPS=$(build/python/bin/python3 -c "import tomllib;print(' '.join(tomllib.load(open('../backend/pyproject.toml','rb'))['project']['dependencies']))")
uv pip install --python build/python/bin/python3 --no-compile --quiet $DEPS
# trim what a server process never imports
L=build/python/lib/python$PY_VER
rm -rf "$L/test" "$L/idlelib" "$L/tkinter" "$L/turtledemo" "$L/ensurepip" \
  "$L/lib2to3" build/python/lib/libtcl* build/python/lib/libtk* \
  build/python/lib/tcl* build/python/lib/tk* build/python/share build/python/include
find build/python -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$L/site-packages" -type d \( -name tests -o -name test \) -prune -exec rm -rf {} +
du -sh build/python
