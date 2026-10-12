# Correo con código de verificación

Plantilla corporativa única (`local/verification_mail.py`) para los dos correos con código que envía el sistema:

| Uso | Dónde se ingresa | Validez |
|-----|------------------|---------|
| Autorización digital del cliente (`/autorizar/<token>`) | En la página de autorización de la orden | 10 minutos |
| Consulta de reparación desde ADI | En el chat de ADI | 10 minutos |

## Presentación

- Asunto: «Tu código de verificación | PC-DOCTOR S.A.». Remitente visible: «PC-DOCTOR S.A. · Seguridad», desde el buzón del sistema ya configurado (mismo proveedor).
- Logo oficial desde una dirección HTTPS pública (`/static/logo-firma.png`), encabezado con el nombre, título «Verifica tu correo electrónico», código de seis dígitos en un recuadro central, validez real, dónde ingresarlo, aviso de seguridad y pie con el nombre y el sitio web.
- HTML con tablas y estilos en línea, sin JavaScript ni hojas de estilo; alternativa en texto plano; fondo claro explícito para que se lea igual en modo oscuro.

## Seguridad

- El código lo genera el servidor con `secrets` en cada solicitud; la plantilla rechaza cualquier valor que no sean seis dígitos. En la base solo se guarda su huella.
- Un solo uso, expiración coordinada con el servidor, intentos limitados y límite de solicitudes repetidas.
- La consulta de reparación no revela si la orden o el correo existen. La auditoría registra `verification_code_sent` o `verification_code_failed`, nunca el código.
- Si el envío de la autorización falla, la página lo indica sin detalles técnicos.

## Autenticación del dominio (revisado el 2026-10-12)

- SPF: publicado en `ordenes-pro.ecuadorpcdoctor.com` y `ecuadorpcdoctor.com`.
- DKIM: clave publicada en `default._domainkey` de ambos.
- DMARC: **no hay registro `_dmarc`**. Conviene añadirlo en el DNS, por ejemplo `v=DMARC1; p=none; rua=mailto:<buzón de informes>` para empezar en modo observación.
