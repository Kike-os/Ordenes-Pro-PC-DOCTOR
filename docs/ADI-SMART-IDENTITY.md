# ADI Smart Identity Verification 2.0

La verificación usa el tipo de la identificación asociada al documento. Si una ficha antigua carece de tipo, el servidor comprueba la cédula o el RUC con las reglas de recepción. Para otros registros usa la instrucción de identificación genérica. La pantalla recibe el nombre del tipo de documento y los errores de validación.

| Ruta | Comprobación |
| --- | --- |
| Proforma y PDF | Últimos cuatro dígitos y clave aleatoria de 30 minutos para la decisión y el PDF |
| Presupuesto y QR | Últimos cuatro dígitos y clave temporal del presupuesto |
| Autorización de servicio y QR | Últimos cuatro dígitos y código de un solo uso por correo |
| Seguimiento y cancelación de repuestos | Últimos cuatro dígitos al enviar una solicitud de cancelación |
| Portal de cuenta desde seguimiento o QR | Últimos cuatro dígitos y sesión de 15 minutos para saldos, estados de cuenta, recibos, comprobantes de entrega y facturas autorizadas |
| Reserva de citas web y ADI | Últimos cuatro dígitos de la identificación indicada para registrar la autorización |
| Entrega de licencias | Documento del titular y código de un solo uso por correo |

La consulta de órdenes en ADI mantiene su reto por correo o WhatsApp. Los enlaces de gestión de citas conservan su token. Los errores de identidad se registran mediante contadores y eventos de auditoría sin copiar los dígitos introducidos en esos registros.

## Producción

1. Verificar que el respaldo de la base central está completo y tiene menos de 24 horas. Comprobar la migración con `python local/db_guardian.py`.
2. Al desplegar, aplicar la migración aditiva `130_proforma_identity_passkey.sql` desde **Sistema → Migraciones**. Durante el intervalo, las proformas pendientes muestran «Verificación en actualización». Las claves de proformas emitidas antes del cambio requieren una nueva comprobación.
3. Confirmar el estado de la migración en Database Guardian y probar el portal, una proforma y sus descargas con datos ficticios en el entorno de validación.
4. En un entorno autorizado con acceso a la cuenta de WhatsApp Business, auditar el catálogo con `python local/proforma_whatsapp.py --identidad`. Si la plantilla v2 todavía no existe, `python local/proforma_whatsapp.py --identidad --presentar` la registra para revisión. La versión aprobada anterior sigue disponible mientras Meta revisa la nueva.
