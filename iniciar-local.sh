#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/local"
python app.py migrate
has_admin="$(python - <<'PY'
import app
with app.connect() as c:
    print(int(c.execute("SELECT 1 FROM users WHERE role='administrador' AND active=1").fetchone() is not None))
PY
)"
if [[ "$has_admin" == "0" ]]; then
    printf 'Primera ejecución: completa nombre, usuario, correo y contraseña para crear tu administrador.\nLa contraseña no se muestra mientras escribes.\n'
    python app.py create-admin
fi
printf '\nEl servidor mostrará abajo la dirección para abrir en el navegador.\nMantén esta terminal abierta; Ctrl+C detiene el servidor.\n\n'
exec python app.py serve
