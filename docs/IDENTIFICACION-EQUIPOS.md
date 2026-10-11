# Identificación de equipos por número de serie — 11/10/2026

## Cómo funciona

1. La serie se normaliza (sin espacios, en mayúsculas) y se valida: 4 a 150 letras, números y guiones.
2. Se busca primero en el historial propio de Órdenes Pro. Si el equipo ya ingresó, se proponen marca, modelo y tipo.
3. Solo si no está en el historial, la marca está indicada y existe un adaptador oficial **configurado con credenciales propias**, se consulta al fabricante.
4. El técnico confirma con «Usar estos datos» o corrige a mano. Nada se completa sin confirmación.
5. La procedencia se guarda en `devices.identity_source`: `historial`, `fabricante:<marca>` o `manual`.
6. Sin resultado, queda la **consulta manual asistida**: abre el portal oficial sin enviarle la serie (se copia al portapapeles).

Nunca se deduce la marca ni el modelo por el formato de la serie. Un fallo del fabricante no impide registrar la orden.

## Matriz de compatibilidad

| Fabricante | Identificadores | Estado | Detalle |
|---|---|---|---|
| Dell | Service Tag | Integración pendiente de autorización | Adaptador implementado para la API de TechDirect; **no probado contra el servicio real**. Requiere cuenta TechDirect y clave aprobada por Dell. |
| HP | Serie y número de producto | Integración pendiente de autorización | Existe la «Product Warranty API» en developers.hp.com (OAuth con clave y secreto; la consulta pide serie y, a menudo, número de producto). El acceso lo aprueba HP caso por caso. La página `support.hp.com/…/drivers` es un formulario web, no una API, y no se automatiza. Sin adaptador hasta tener acceso y documentación. |
| Lenovo | Serie o tipo de máquina | Integración pendiente de autorización | La API de soporte exige un ClientID que entrega Lenovo por vía comercial. Sin adaptador. Existe una consulta no oficial del sitio web que **no se usa**. |
| Acer | Serie (22 caracteres) o SNID | Consulta manual disponible | No se encontró API pública documentada. |
| ASUS | Serie | Consulta manual disponible | El portal puede pedir verificación. Sin API documentada. |
| Apple | Serie | Consulta manual disponible | El portal usa CAPTCHA. La API existente es solo para proveedores de servicio autorizados. |
| MSI | Serie o modelo | Consulta manual disponible | Sin API pública documentada. |
| Samsung | Modelo o serie | Consulta manual disponible | Sin API pública documentada. |
| Huawei | Serie | Consulta manual disponible | El portal puede pedir verificación. Sin API documentada. |
| Epson | Modelo | Consulta manual disponible | El portal busca por modelo, no por serie. |
| Historial PC-DOCTOR | Serie | Disponible y probado | Funciona con los equipos ya ingresados. |

Ninguna integración de fabricante está en el estado «API oficial disponible y probada». La información sobre las API proviene de documentación de terceros que integran esos servicios; debe confirmarse en el portal de cada fabricante al solicitar acceso.

## Activar Dell cuando haya credenciales

En el servidor (Vercel y `local/.env`), nunca en el navegador ni en el repositorio:

```
DELL_API_CLIENT_ID=
DELL_API_CLIENT_SECRET=
DELL_API_HOST=        # opcional; por defecto apigtwb2c.us.dell.com
```

Después hay que probarla con un Service Tag propio del taller antes de darla por funcional. Límite: 40 consultas externas por usuario y hora, 8 s de espera.

## Arquitectura

- `local/device_lookup.py`: validación, búsqueda interna, orquestación y procedencia.
- `local/device_brands.py`: catálogo de fabricantes, portales e identificadores.
- `local/device_manufacturers.py`: adaptadores oficiales, tiempo de espera, errores y credenciales.
- `local/static/brands/`: logotipos locales (ver su README).
- `local/migrations/022_device_identity_source.sql`: columna de procedencia.

Al registrar una orden, si el cliente ya tiene exactamente el mismo equipo (serie, tipo, marca, modelo y color), se reutiliza su registro en lugar de duplicarlo. Las órdenes y equipos anteriores no se modifican.

## Actualización — lectura desde el propio equipo, confirmación y conflictos

**Por qué una serie HP nueva no se identifica sola:** no hay ningún servicio de fabricante conectado. El único proveedor automático activo es el historial interno. Para HP el siguiente paso es solicitar la Product Warranty API en https://developers.hp.com (cuenta de desarrollador, solicitud de credenciales y aprobación de HP) y, con el acceso, escribir y probar su adaptador.

**Leer del equipo (cualquier marca, si enciende):** el botón «Leer del equipo» muestra un comando de PowerShell. El técnico lo ejecuta en el equipo recibido y pega el resultado; `local/device_hardware.py` interpreta fabricante, modelo, serie, procesador, memoria y disco. También acepta la salida de `systeminfo`, `wmic csproduct`, `dmidecode` y `system_profiler`. No se ejecuta nada en el servidor ni se consulta ningún servicio. Los valores de relleno («To Be Filled By O.E.M.», «System Product Name»…) se descartan. Procedencia guardada: `equipo`. El comando aún no se ha probado en un equipo Windows real; el analizador se probó con salidas de ejemplo de cada herramienta.

**Aprendizaje del historial:** al registrar la orden, el equipo guarda quién confirmó la marca y el modelo y cuándo (`identity_confirmed_by`, `identity_confirmed_at`, migración 023). La siguiente recepción de la misma serie los propone con su procedencia. Las órdenes y equipos anteriores no se modifican.

**Conflictos:** si una serie figura en el historial con marcas distintas, la búsqueda lo avisa y no elige ninguna por su cuenta.

**Ficha del equipo:** marca y modelo, tipo y serie, origen (Historial interno, Fabricante oficial, Leído del equipo o Selección manual) e identificación (Confirmada, Pendiente o No disponible).
