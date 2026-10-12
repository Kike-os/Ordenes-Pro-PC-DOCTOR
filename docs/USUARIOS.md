# Gestión de Usuarios y Accesos

Desde el 12/10/2026 no existe registro público de cuentas.

## Qué se retiró

- El enlace «¿No tienes cuenta? Solicitar acceso» de la pantalla de inicio de sesión.
- La página pública `/registro`: sin sesión de administrador responde 404; a un administrador lo lleva a Configuración → Gestión de Usuarios y Accesos.
- El alta por `POST /api/register`: responde 404 siempre y deja constancia en la auditoría (`public_registration_blocked`). La variable `REGISTRATION` ya no tiene efecto.

En el acceso solo quedan el inicio de sesión y la recuperación de contraseña, que no cambiaron.

## Crear una cuenta (solo administración)

Configuración → Gestión de Usuarios y Accesos → «Crear cuenta de usuario»: nombre completo, correo, usuario (opcional; se deriva del correo) y rol.

1. El servidor valida los datos y comprueba que el correo y el usuario no existan (`POST /api/users/create`, rol administrador y CSRF obligatorios; 20 por hora).
2. La cuenta se guarda aprobada y activa con una contraseña aleatoria que nadie conoce.
3. Se envía un correo de invitación con un enlace temporal de un solo uso (72 horas) para que la persona establezca su propia contraseña. Nunca se envían contraseñas.
4. Si el correo no está configurado o falla, el enlace se muestra una única vez a quien administra, para entregarlo por un medio seguro.
5. Auditoría: `account_created`, `account_invitation_sent|failed|unavailable` y, cuando la persona establece su contraseña, `account_activated`.

## Otras acciones

- **Rol y estado**: cambiar rol, activar o desactivar (cierra las sesiones de esa cuenta); siempre queda al menos un administrador activo.
- **Restablecer acceso** (`POST /api/users/access`): envía un enlace temporal nuevo; el anterior deja de servir. Auditoría `account_access_reset`.
- **Solicitudes anteriores**: las recibidas antes del cierre del registro siguen pudiendo aprobarse o rechazarse; el bloque solo aparece si queda alguna.
