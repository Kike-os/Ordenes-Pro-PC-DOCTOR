#!/usr/bin/env bash
# Publica los cambios: verifica, crea un commit y lo sube a GitHub. Vercel despliega solo cada subida a main.
# Uso: bash publicar.sh "descripción del cambio"
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ -n "$(git status --porcelain)" ]]; then
    printf 'Verificando antes de publicar…\n'
    python -m unittest discover -s local/tests
    node --check local/static/app.js
    python -m py_compile local/app.py
    printf '\nCambios que se publicarán:\n'
    git status --short
    mensaje="${1:-}"
    [[ -n "$mensaje" ]] || read -r -p 'Describe el cambio: ' mensaje
    [[ -n "$mensaje" ]] || { printf 'Sin descripción no se publica.\n'; exit 1; }
    git add -A
    git commit -m "$mensaje"
elif [[ -z "$(git log origin/main..HEAD --oneline)" ]]; then
    printf 'No hay cambios que publicar.\n'
    exit 0
fi

git push origin main
printf '\nSubido a GitHub. Vercel lo publica en alrededor de un minuto:\nhttps://ordenes-pro.ecuadorpcdoctor.com\n'
