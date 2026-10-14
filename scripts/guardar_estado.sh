#!/usr/bin/env bash
# Guarda la carpeta estado/ en la rama "estado" como un único commit (sin historial que crezca).
# Lo ejecuta el colector antes de enviar avisos y al final de cada ciclo.
set -euo pipefail
: "${GITHUB_TOKEN:?falta GITHUB_TOKEN}"
: "${GITHUB_REPOSITORY:?falta GITHUB_REPOSITORY}"
ORIGEN="$(pwd)/estado"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp -r "$ORIGEN"/. "$TMP"/
rm -f "$TMP"/*.tmp
cd "$TMP"
git init -q -b estado
git -c user.name="mapa-conflictos[bot]" -c user.email="mapa-conflictos@users.noreply.github.com" \
  add -A
git -c user.name="mapa-conflictos[bot]" -c user.email="mapa-conflictos@users.noreply.github.com" \
  commit -q -m "Estado $(date -u +%Y-%m-%dT%H:%MZ)"
AUTH="$(printf 'x-access-token:%s' "$GITHUB_TOKEN" | base64 -w0)"
for intento in 1 2 3; do
  if git -c http.extraheader="AUTHORIZATION: basic $AUTH" push -q -f \
      "${ESTADO_REMOTO:-https://github.com/${GITHUB_REPOSITORY}.git}" estado:estado 2>/dev/null; then
    exit 0
  fi
  sleep $((intento * 5))
done
echo "No se pudo guardar el estado en la rama 'estado'" >&2
exit 1
