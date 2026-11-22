#!/usr/bin/env bash
# Se ejecuta una sola vez al crear el Codespace. Instala dependencias y crea una base local VACÍA en local/var/.
# Nunca se conecta a la base central (Turso) ni crea cuentas: el administrador de pruebas lo creas tú.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

if [[ -n "${TURSO_DATABASE_URL:-}" || -n "${TURSO_AUTH_TOKEN:-}" ]]; then
    printf 'ALTO: hay variables TURSO_* en este Codespace. Este entorno no debe usar la base de producción.\n' >&2
    printf 'Elimina esos secretos de Codespaces (github.com/settings/codespaces) y vuelve a crear el entorno.\n' >&2
    exit 1
fi

printf 'Python: %s · Node: %s\n' "$(python --version 2>&1)" "$(node --version)"
python -m pip install --user --disable-pip-version-check -q -r local/requirements.txt
mkdir -p local/var
chmod 700 local/var
(cd local && python app.py migrate)
printf '\nListo. Para crear tu administrador de PRUEBAS (datos ficticios):\n  bash .devcontainer/iniciar-codespace.sh --crear-admin\n'
printf 'Para iniciar Órdenes Pro:\n  bash .devcontainer/iniciar-codespace.sh\n'
