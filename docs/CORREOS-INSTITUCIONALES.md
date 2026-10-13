# Correos institucionales (rama `correos-institucionales`, pendiente de aprobación)

Requiere la migración 043 (solo tablas nuevas: `mail_archive` y `mail_review_cache`).

## Un solo servicio

`local/mailing.py` y `send_institutional` (en `local/app.py`) concentran lo que antes hacía cada correo por su cuenta:

1. El módulo genera el texto con sus datos.
2. **ADI revisa la redacción** de los párrafos (ortografía, gramática y tono formal).
3. Se comprueba que los datos volvieron intactos; si no, se usa el texto de la plantilla.
4. Se aplica la **plantilla institucional**.
5. Se incorpora la **firma autorizada** (la que ya está guardada en Órdenes Pro: Correo → Firma).
6. Se guarda la **copia exacta** como «preparado» y se vincula a la orden.
7. Se envía; el estado pasa a «enviado» (el servidor de correo aceptó el mensaje) o «error».

## Plantilla

Fondo claro, 600 px, encabezado **textual** («PC-DOCTOR S.A.» y el título del mensaje) sin logotipo, párrafos con interlineado cómodo y justificados cuando son largos (en pantallas de hasta 480 px pasan a la izquierda), las líneas «Dato: valor» como tabla, los enlaces como botón con la dirección visible debajo, y la firma al final. Tablas y estilos en línea: la estructura la da la plantilla, nunca la IA, y no se usan espacios para alinear. La firma institucional sustituye a la despedida escrita a mano («Departamento de Servicio Técnico…»), para no duplicarla.

## Revisión de ADI

- Revisa todos los párrafos del mensaje. El saludo con el nombre, las tablas de datos, la despedida y, dentro de los párrafos, los códigos de orden, importes, fechas, horas, teléfonos, correos y enlaces viajan como marcadores y se restituyen tal cual: la IA no los ve ni puede cambiarlos.
- Si la respuesta pierde o inventa un marcador, cambia el número de párrafos, crece o se encoge en exceso, tarda más de 9 segundos o el proveedor falla, el correo sale con la plantilla y queda registrado como **plantilla**, no como revisado.
- El resultado se guarda por texto de plantilla, así que el mismo tipo de correo no vuelve a consultar a la IA en cada envío.
- Se puede desactivar en Configuración → ADI → Corrección Inteligente → «Revisión de los correos automáticos».

## Qué correos pasan por el servicio

Comprobante de recepción, enlace de autorización del cliente, presupuesto, avisos de permanencia, recordatorios de mantenimiento y el aviso interno de autorización registrada (este último sin revisión de ADI ni firma, porque va al buzón del taller). Los correos de citas usan la misma plantilla y firma y se archivan, sin revisión de ADI.

**Excepciones deliberadas:** los correos de seguridad (código de verificación, invitación de acceso, recuperación de contraseña) no pasan por ADI, no llevan la firma personal ni se archivan, porque contienen códigos y enlaces de acceso; solo se les quitó el logotipo del encabezado. Los guiones heredados `appointments_cron.py` y `maintenance_cron.py` (instalación cPanel) no se modificaron.

## Historial de correos y copia exacta

En el detalle de cada orden, «Historial de correos»: fecha y hora, destinatario, asunto, estado, **✦ Revisado por ADI** (solo si ADI completó de verdad la revisión de ese mensaje) y «Ver correo». La ventana muestra el texto exacto y enlaza la versión con formato (`/correo/<id>`, con sesión). La copia no se puede modificar ni borrar y no cambia aunque cambien las plantillas. Los enlaces privados de un solo uso (autorización, presupuesto) se omiten de la copia.

## Vinculación con órdenes

- Todo correo enviado desde una orden queda vinculado a ella automáticamente.
- Un correo **recibido** se vincula solo cuando la referencia es inequívoca: responde a un mensaje que el sistema envió desde una orden, o su asunto nombra una única orden y el remitente es el correo registrado de su cliente. Con dudas no se vincula.
- El campo «Vincular a orden» sale del flujo habitual: queda plegado como herramienta de administración para casos excepcionales.

## No verificado

- Cómo se ve la plantilla en Gmail, Outlook y aplicaciones móviles reales (solo en un navegador).
- La revisión con el proveedor de IA real: las pruebas usan una IA simulada.
- Ningún envío real a clientes.

Pruebas: `local/tests/test_mailing.py`.
