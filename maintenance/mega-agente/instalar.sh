#!/usr/bin/env bash
# Instala el agente de respaldos MEGA de Órdenes Pro en este equipo (usuario normal, sin privilegios de administrador).
# Requisito previo (una sola vez, con contraseña de administrador): sudo pacman -S --needed podman
# No pide ni guarda la contraseña de MEGA: el inicio de sesión se hace después, en la terminal, con mega-login.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SHARE="$HOME/.local/share/ordenes-pro"
UNITS="$HOME/.config/systemd/user"
QUADLET="$HOME/.config/containers/systemd"
EXCHANGE="$HOME/Respaldos-OrdenesPro/mega-intercambio"

command -v podman >/dev/null || { echo "Falta Podman. Ejecuta primero: sudo pacman -S --needed podman"; exit 1; }
umask 077
mkdir -p "$SHARE/mega-sesion" "$EXCHANGE/pendientes" "$EXCHANGE/verificacion" "$UNITS" "$QUADLET" "$HOME/.config/ordenes-pro"
chmod 700 "$SHARE" "$SHARE/mega-sesion" "$EXCHANGE" "$EXCHANGE/pendientes" "$EXCHANGE/verificacion" "$HOME/.config/ordenes-pro"

echo "1/5 · Imagen con MEGAcmd oficial (repositorio de MEGA para Ubuntu 24.04, clave comprobada por su huella)…"
podman build -q -t localhost/ordenes-mega:2.7.1 "$ROOT/maintenance/mega-agente"

echo "2/5 · Entorno de Python del agente (cifrado AES-256-GCM)…"
[ -x "$SHARE/venv/bin/python" ] || python -m venv --system-site-packages "$SHARE/venv"
"$SHARE/venv/bin/pip" install -q "cryptography>=43,<47"

echo "3/5 · Clave de cifrado de los respaldos…"
if [ ! -s "$HOME/.config/ordenes-pro/backup.key" ]; then
  if [ -s "$HOME/CLAVE-RESPALDOS-ORDENES-PRO.txt" ]; then
    tail -n1 "$HOME/CLAVE-RESPALDOS-ORDENES-PRO.txt" | tr -d '\n' > "$HOME/.config/ordenes-pro/backup.key"
    chmod 600 "$HOME/.config/ordenes-pro/backup.key"
  else
    echo "   Falta la clave: crea $HOME/.config/ordenes-pro/backup.key (permisos 600) con BACKUP_ENCRYPTION_KEY."; exit 1
  fi
fi

echo "4/5 · Servicios automáticos (contenedor, agente y respaldo diario a las 02:00)…"
cp "$ROOT/maintenance/mega-agente/ordenes-mega.container" "$QUADLET/"
cp "$ROOT/maintenance/mega-agente/ordenes-pro-mega-agente.service" "$ROOT/maintenance/ordenes-pro-respaldo.service" "$ROOT/maintenance/ordenes-pro-respaldo.timer" "$UNITS/"
systemctl --user daemon-reload
systemctl --user start ordenes-mega.service
systemctl --user enable --now ordenes-pro-mega-agente.service
systemctl --user enable --now ordenes-pro-respaldo.timer

echo "5/5 · Comprobación…"
for i in $(seq 1 20); do podman exec ordenes-mega mega-version >/dev/null 2>&1 && break; sleep 2; done
podman exec ordenes-mega mega-version | head -1 || true
echo
echo "Listo. Último paso (solo tú, en esta terminal): inicia sesión en MEGA una vez:"
echo "   podman exec -it ordenes-mega mega-login tu-correo@ejemplo.com"
echo "La contraseña se escribe solo ahí; nunca pasa por Órdenes Pro."
