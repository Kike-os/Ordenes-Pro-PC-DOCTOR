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

## Actualización — confirmación, conflictos y ficha del equipo

**Por qué una serie HP nueva no se identifica sola:** no hay ningún servicio de fabricante conectado. El único proveedor automático activo es el historial interno. Para HP el siguiente paso es solicitar la Product Warranty API en https://developers.hp.com (cuenta de desarrollador, solicitud de credenciales y aprobación de HP) y, con el acceso, escribir y probar su adaptador.

**Lectura desde el propio equipo:** se publicó en la 1.5.21 y se retiró en la versión siguiente a pedido del taller. No queda ningún botón, panel ni ruta de esa función.

**Aprendizaje del historial:** al registrar la orden, el equipo guarda quién confirmó la marca y el modelo y cuándo (`identity_confirmed_by`, `identity_confirmed_at`, migración 023). La siguiente recepción de la misma serie los propone con su procedencia. Las órdenes y equipos anteriores no se modifican.

**Conflictos:** si una serie figura en el historial con marcas distintas, la búsqueda lo avisa y no elige ninguna por su cuenta.

**Ficha del equipo:** marca y modelo, tipo y serie, origen (Historial interno, Fabricante oficial o Selección manual) e identificación (Confirmada, Pendiente o No disponible).

## Ficha del equipo (1.5.116)

Estados que muestra la ficha: **Identificado** (historial del taller o servicio oficial del fabricante), **Registro manual completo**, **Datos incompletos** y **No identificado** (hay serie pero no marca ni modelo; se indica que no figura en el historial y se ofrece la consulta al soporte oficial). Ya no aparece «Marca sin indicar — Modelo pendiente de identificación».

La consulta automática a fabricantes sigue pendiente de credenciales: ninguna integración está activa. Tras la limpieza de registros de prueba del 12/10/2026 el historial propio empieza vacío, así que las primeras series no se reconocerán hasta registrar los equipos.

## Identificación automática, tarjeta y logotipos (rama `identificacion-serie`, 13/10/2026, pendiente de aprobación)

**Qué cambia**

- Al escribir o escanear una serie válida la consulta empieza sola (450 ms después de la última tecla; inmediata con Enter del lector). No hay botón.
- **Autocompletado:** con un único resultado sin conflictos se rellenan tipo, marca, modelo y color, y aparece «Equipo identificado correctamente» con un destello de estrella. Queda el botón «Deshacer» y los campos siguen editables. Con varios resultados o marcas en conflicto no se elige nada por cuenta propia.
- **Equipo ya registrado del mismo cliente:** el ingreso se asocia a ese equipo (su identificador `EQ-…` e historial), sin duplicarlo. Si ese equipo tiene un ingreso sin entregar, se avisa y no se asocia.
- **Tarjeta del equipo:** logotipo de la marca, modelo, identificador permanente, serie, cliente, ingresos anteriores, «Historial técnico» y «Ver orden anterior».
- **Sin resultado:** «No fue posible identificar automáticamente este equipo. Puedes completar sus datos manualmente.» La recepción continúa.
- El aviso «Consultando información del fabricante…» solo aparece cuando la marca tiene un servicio oficial conectado; si no, dice «Buscando el equipo en el historial del taller…», que es lo que realmente ocurre.
- Los resultados verificados de un fabricante se guardan seis horas en memoria: repetir la misma serie no vuelve a consultar.
- El logotipo de la marca se muestra también en el listado de Equipos, la ficha del equipo, las tarjetas de equipos de la orden y el historial de equipos del cliente.

**Logotipos.** Catálogo central en `local/static/brands/` (29 marcas). Se añadieron Framework, Fujifilm, Google, NEC, Sharp, System76 y Zebra, de Simple Icons 13.21.0 (CC0), en el color que ese catálogo registra para cada marca. **No se añadieron** Brother, Canon, Compaq, Dynabook, Gigabyte, IBM, Konica Minolta, Lexmark, Microsoft, OKI, Ricoh, VAIO ni Xerox: no figuran en ese catálogo de uso libre y un logotipo corporativo debe bajarse del portal de marca del fabricante aceptando sus condiciones. Para esas marcas se muestra el icono genérico; basta guardar el archivo oficial en la carpeta (ver su README). Son la marca en un solo color, no la versión corporativa completa.

**Fabricantes: estado real y qué hace falta (consultado el 13/10/2026)**

| Fabricante | Qué existe | Qué se necesita para conectarlo |
|---|---|---|
| Dell | API de garantía de TechDirect (OAuth 2.0, versión 5). El adaptador está escrito pero **nunca se probó contra Dell**. | Cuenta empresarial de TechDirect asociada a la empresa, solicitar la clave en Servicios → API, pasar el periodo de pruebas (sandbox) y la promoción a producción que hace Dell (días o semanas). Luego `DELL_API_CLIENT_ID` y `DELL_API_CLIENT_SECRET` en el servidor y una prueba con un Service Tag del taller. |
| HP | «HP Warranty API» en developers.hp.com. | La solicita el gestor de cuenta de HP de la empresa a warrantyapi.customers@hp.com; HP aprueba a mano. Sin acceso no se puede ver la documentación de parámetros ni escribir el adaptador. |
| Lenovo | API de garantía de eSupport. | Un `ClientID` que entrega Lenovo por su canal comercial o de soporte empresarial. |
| Acer, ASUS, Epson, MSI, Samsung, Apple, Dynabook/Toshiba | Solo consulta web (varias con CAPTCHA). No se encontró API pública. | Nada que se pueda activar. Queda la consulta manual asistida, que abre el portal oficial sin enviarle la serie. |

Fuentes: documentación de integradores de la API de Dell (SysAid, Patch My PC, JupiterOne), la comunidad de Lansweeper y ManageEngine para HP, y Omnissa y ServiceNow para Lenovo. Son terceros; las condiciones vigentes deben confirmarse en el portal de cada fabricante al pedir el acceso.

**No verificado:** ninguna identificación real contra un fabricante. No hay credenciales, así que no se puede afirmar que Dell, HP ni ninguna otra marca identifique equipos automáticamente. Lo probado es el historial propio, el autocompletado, la asociación al equipo existente, la caché y el comportamiento cuando el servicio falla (con un proveedor simulado). No se obtienen imágenes del modelo ni estado de garantía: dependen de esas mismas API.
