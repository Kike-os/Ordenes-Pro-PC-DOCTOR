#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
printf 'Acceso desde otra PC de la misma red local.\nBuscando direcciones reales de Omarchy…\n'
pcdoctor_addresses="$(python - <<'PY'
import ipaddress
import json
import subprocess
import sys
try:
    result = subprocess.run(['ip','-4','-j','address','show','scope','global'],capture_output=True,text=True,check=True)
    interfaces = json.loads(result.stdout)
except (OSError,ValueError,subprocess.CalledProcessError):
    raise SystemExit('No se pudieron consultar las interfaces. Ejecuta este script en la terminal de Omarchy, fuera del chat.')
addresses = []
for interface in interfaces:
    if 'UP' not in interface.get('flags',[]):
        continue
    for item in interface.get('addr_info',[]):
        addr = ipaddress.IPv4Address(item['local'])
        if addr.is_private and not (addr.is_loopback or addr.is_unspecified or addr.is_link_local or addr.is_multicast):
            if str(addr) not in addresses:
                addresses.append(str(addr))
if not addresses:
    raise SystemExit('No se detectó una IPv4 privada activa. Conecta Omarchy a la red local.')
print('\n'.join(addresses))
PY
)"
mapfile -t pcdoctor_ip_list <<< "$pcdoctor_addresses"
if [[ "${#pcdoctor_ip_list[@]}" == "1" ]]; then
    pcdoctor_lan_ip="${pcdoctor_ip_list[0]}"
else
    printf '\nHay varias direcciones; selecciona la interfaz que comparte red con la otra PC:\n'
    PS3='Número de la dirección: '
    select pcdoctor_lan_ip in "${pcdoctor_ip_list[@]}"; do
        if [[ -n "$pcdoctor_lan_ip" ]]; then break; fi
    done
fi
export BIND_HOST="$pcdoctor_lan_ip"
export PORT=8010
export APP_URL="http://${pcdoctor_lan_ip}:8010"
export SESSION_SECURE=false
printf '\nDesde ambas PCs abre: %s\nSolo para evaluación con datos ficticios en una red de confianza.\nNo abras este puerto en el router hacia internet.\n\n' "$APP_URL"
exec bash ./iniciar-local.sh
