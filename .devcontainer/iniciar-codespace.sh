#!/usr/bin/env bash
# Inicia Órdenes Pro dentro de Codespaces con la base local de pruebas (local/var/), nunca la de producción.
#   bash .devcontainer/iniciar-codespace.sh               -> inicia (8010 escritorio + 8011 navegador)
#   bash .devcontainer/iniciar-codespace.sh --crear-admin -> crea el administrador de PRUEBAS
#   bash .devcontainer/iniciar-codespace.sh --pruebas     -> ejecuta las pruebas del proyecto
# Ctrl+C detiene ambos servidores.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# Sin servicios externos reales: ni base central, ni correo, ni IA, ni Google Drive, ni facturación.
unset TURSO_DATABASE_URL TURSO_AUTH_TOKEN SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD SMTP_FROM \
      FACTURACION_MAIL_USERNAME FACTURACION_MAIL_PASSWORD OPENAI_API_KEY OPEN_API_KEY ANTHROPIC_API_KEY \
      GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET CRON_SECRET BACKUP_ENCRYPTION_KEY BACKUP_TOKEN_KEY ONEDRIVE_TOKEN_KEY \
      DELL_API_CLIENT_ID DELL_API_CLIENT_SECRET TURNSTILE_SITE_KEY TURNSTILE_SECRET_KEY APP_URL PUBLIC_APP_URL || true
export MAINTENANCE_EMAIL_ENABLED=false
if [[ -f local/.env ]]; then
    printf 'Aviso: existe local/.env. Revísalo: en Codespaces no debe contener credenciales reales ni TURSO_*.\n' >&2
    if grep -qE '^\s*TURSO_' local/.env; then printf 'ALTO: local/.env contiene TURSO_*.\n' >&2; exit 1; fi
fi

case "${1:-}" in
    --crear-admin) cd local && exec python app.py create-admin ;;
    --pruebas)
        python -m unittest discover -s local/tests
        node --check local/static/app.js
        python -m py_compile local/app.py
        exit 0 ;;
esac

(cd local && python app.py migrate)
(cd local && BIND_HOST=127.0.0.1 PORT=8010 exec python app.py serve) &
escritorio=$!
python .devcontainer/servidor-navegador.py &
navegador=$!
trap 'kill $escritorio $navegador 2>/dev/null || true; printf "\nServidores detenidos.\n"' INT TERM EXIT
printf '\nVS Code de escritorio: abre http://localhost:8010 en Windows (pestaña PUERTOS).\n'
printf 'Navegador: usa la dirección «navegador» que aparece abajo (puerto 8011, privado).\n'
printf 'Ctrl+C detiene ambos.\n\n'
wait
