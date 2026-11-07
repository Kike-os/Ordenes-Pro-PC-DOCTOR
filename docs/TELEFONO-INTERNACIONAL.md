# Teléfono / WhatsApp internacional (1.5.251)

## Qué cambia

- **Campo «Teléfono / WhatsApp»:**
  - selector de país con bandera y prefijo, y búsqueda por nombre del país o por prefijo (por ejemplo «peru» o «+34»);
  - campo del número con mensajes claros de validez («Número válido · Colombia · celular», «El número está incompleto para Perú»…);
  - **Ecuador (+593)** es el país predeterminado.
  - Funciona en la recepción de órdenes y el registro de clientes, la edición rápida de clientes, las citas (pública, nueva cita y edición), la facturación (teléfono del comprador) y las proformas.
- **Validación con las reglas de cada país**, sin largo fijo de 10 cifras:
  - en el navegador, `libphonenumber-js` (MIT, `static/libphonenumber-max.js`);
  - en el servidor, su equivalente `phonenumbers` (Apache-2.0, en `vendor/`), con las mismas reglas.
  - No se agregaron React ni compilación: el proyecto usa JavaScript sin framework.
- **Guardado en E.164** (por ejemplo `+593991234567`):
  - se acepta escribir con espacios o guiones;
  - un número pegado con «+», «00» o con el código sin «+» cambia el país solo y nunca duplica el prefijo.
- **WhatsApp:**
  - los enlaces y el envío por la API usan el número internacional normalizado;
  - los teléfonos fijos no sirven para WhatsApp;
  - un celular no se da por «con WhatsApp activo»;
  - la configuración de WhatsApp Business no cambió.
- **Búsqueda:** «0991234567», «099 123 4567», «+593 99 123 4567» y «593991234567» encuentran al mismo cliente u orden, esté guardado en formato antiguo o internacional.

## Números antiguos

- No se reescriben en la base: se interpretan al leerlos (búsqueda, enlaces de WhatsApp, formulario).
- Un número antiguo de Ecuador se muestra con formato al abrir la ficha y se guarda en E.164 solo cuando alguien edita y guarda esa ficha.
- Un texto que no se puede interpretar (por ejemplo dos números juntos) se conserva tal como está y el formulario pide revisarlo.
- En facturas y proformas, un teléfono no interpretable se guarda tal como se escribió; nunca se pierde un dato.

## Archivos

| Archivo | Uso |
|---|---|
| `phones.py` | Regla común del servidor. |
| `static/phone-input.js` y `static/phone-input.css` | Componente del formulario; se activa con `data-phone-intl` o con `intlPhone(input)` en `app.js`. |
| `static/flags/*.svg` | Banderas de `country-flag-icons` (MIT), servidas solo por código de dos letras. |
| `static/libphonenumber-max.js` | Reglas telefónicas para el navegador. |
| `vendor/phonenumbers` | Reglas telefónicas para el servidor. |

Las licencias de cada biblioteca están junto a sus archivos.

## Pruebas

- **Unitarias:** `tests/test_phones.py` revisa:
  - Ecuador, Colombia, Perú, Estados Unidos, España, México, Argentina y Alemania;
  - que el prefijo no se duplique;
  - los errores claros;
  - WhatsApp;
  - la búsqueda en ambos formatos;
  - que los números antiguos queden intactos;
  - los archivos servidos.
- **Navegador:** 20 comprobaciones con datos ficticios.
