#!/usr/bin/env bash
# Baja EmulatorJS y deja en web/emulatorjs/ solo lo que usa Gameflix: el cargador,
# los cores de NES, SNES, GB/GBC y GBA (normal y "legacy" para equipos sin WebGL2),
# los descompresores de ZIP/7z/RAR y la traducción al español.
#
#     herramientas/traer-emulatorjs.sh
set -euo pipefail

VERSION=4.2.3
SHA256=07d451bc06fa3ad04ab30d9b94eb63ac34ad0babee52d60357b002bde8f3850b
CORES="fceumm snes9x gambatte mgba"

proyecto="$(cd "$(dirname "$0")/.." && pwd)"
destino="$proyecto/web/emulatorjs"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "Bajando EmulatorJS $VERSION (~290 MB)..."
curl -fL --progress-bar -o "$tmp/ejs.7z" \
    "https://github.com/EmulatorJS/EmulatorJS/releases/download/v$VERSION/$VERSION.7z"
echo "$SHA256  $tmp/ejs.7z" | sha256sum -c -

archivos=(data/loader.js data/emulator.min.js data/emulator.min.css data/version.json
          'data/compression/*' data/localization/es-ES.json 'data/cores/reports/*' LICENSE)
for c in $CORES; do archivos+=("data/cores/$c-wasm.data" "data/cores/$c-legacy-wasm.data"); done
7z x -y -bso0 -o"$tmp/x" "$tmp/ejs.7z" "${archivos[@]}"

rm -rf "$destino"
mv "$tmp/x/data" "$destino"
mv "$tmp/x/LICENSE" "$destino/LICENSE"
echo "Listo: $destino ($(du -sh "$destino" | cut -f1))"
