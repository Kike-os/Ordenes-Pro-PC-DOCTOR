# ADI 3.0 · fase 3: gracia de 90 días e intereses — SOLO SIMULACIÓN (1.5.327)

**El modo único habilitado es Simulación.** Calcula un estimado y nada más:

- no se guarda;
- no cambia saldos, pagos ni facturas;
- no emite documentos tributarios;
- no se comunica al cliente.

Los modos **Revisión administrativa** y **Aplicación autorizada** están definidos, pero el servidor rechaza activarlos con un 403. Activarlos requiere:

- validación jurídica: tipo de obligación, tasa, fecha de exigibilidad y metodología;
- validación contable y tributaria;
- una autorización expresa e independiente de administración.

**Archivos:**

- Módulo: `local/interest_engine.py`.
- Migración: `120_financial_rates.sql`. Solo crea la tabla `financial_rates`. Hay que aplicarla desde Sistema → Migraciones.
- Rutas:
  - `GET` y `POST /api/finance/rates`;
  - `POST /api/orders/<id>/interest-sim`.
- Acceso: solo administración.
- Interfaz: ventana Mensaje de seguimiento → Análisis integral → bloque «Compromiso de pago» → **Simular intereses** y **Tasas legales Ecuador**.

## Motor (en el servidor; la IA nunca calcula)

- **Cálculo:**
  - aritmética `Decimal`;
  - interés **simple** con **base 365**;
  - redondeo a centavos al final (mitad hacia arriba).
- **Solo sobre el capital vencido:**
  - los pagos parciales confirmados lo reducen desde el día del pago, y ese día ya no genera interés;
  - una transferencia por conciliar suspende la simulación hasta conciliarla en Caja.
- **Gracia:**
  - del día 1 al 90 de retraso no hay intereses (la gracia se configura entre 30 y 180 días);
  - el interés empieza el día 91 y **nunca** se cobra la gracia de forma retroactiva.
- **Tasa:** se usa, día por día, la tasa **validada** vigente. Si cambia, se generan tramos separados.
- **Prohibido:**
  - capitalizar;
  - cobrar interés sobre interés;
  - calcular sobre cargos de cobranza;
  - aplicar multas o cargos duplicados.
- **Cuándo no hay simulación (no exigible):**
  - si hay un retraso atribuible a PC-DOCTOR;
  - si no hay una obligación vencida registrada. Elegir pagar en efectivo no genera intereses.
- **Vencimiento usado:** la fecha acordada de un **compromiso de pago incumplido**. Nunca se usa la fecha de ingreso del equipo.
- **Comparación:** administración puede indicar otro capital y otro vencimiento para comparar.

**Ejemplo de la orden** (cubierto por las pruebas, con 6,88 % como dato de prueba):

- capital $150,00, 120 días de retraso, 90 de gracia;
- 30 días con interés;
- interés **$0,85**, total **$150,85**.

## Tasas legales Ecuador

Cada tasa registra:

- tipo: legal anual o máxima convencional anual;
- porcentaje;
- vigencia: desde y, si corresponde, hasta;
- fecha de consulta;
- fuente oficial: `https` de bce.fin.ec, bce.ec o gob.ec;
- evidencia de publicación;
- usuario;
- estado.

Reglas:

- **Estado:** toda tasa nace «sin validar» y no se usa hasta que se valida.
  - Valida otra persona de administración distinta de quien la registró (doble control), salvo que solo haya una.
  - Validar o anular exige una nota.
  - Una corrección se registra como una tasa nueva, así se conserva el historial.
- **Sin tasa validada para algún día:** la simulación se **suspende** con un aviso. El sistema **nunca** inventa ni sustituye una tasa.
- **Tasas no válidas:** no se usan tasas bancarias de consumo ni de microcrédito.
- **Consulta del BCE:** la consulta periódica es manual. El diálogo enlaza la página oficial del BCE. El sistema no descarga tasas por su cuenta.
- **Tasas de noviembre de 2026** (legal 6,88 %, máxima convencional 7,74 %): la orden las da como referencia. Administración debe **registrarlas y validarlas** con la publicación oficial. El sistema no las cargó por su cuenta.

## Validaciones jurídicas pendientes (antes de cualquier aplicación real)

- Tipo de obligación y exigibilidad: Código Civil, arts. 1567 y 1575.
- Tasa aplicable: legal o convencional pactada (art. 2109).
- Ley Orgánica de Defensa del Consumidor, arts. 47, 48, 49 y 93.
- Condiciones aceptadas por el cliente y evidencia contractual. No se aplican de forma retroactiva.
- Tratamiento contable y tributario de los intereses.

## Pruebas

`local/tests/test_interest_engine.py` cubre estos casos:

- el ejemplo de $150 / 120 días;
- retrasos de 89, 90 y 91 días;
- interés lineal, sin capitalizar;
- cambio de tasa;
- pago parcial y pago total durante la mora;
- tasa faltante, que suspende la simulación;
- solo el modo simulación;
- registro con fuente oficial y validación;
- simulación desde un compromiso incumplido, sin efectos;
- retraso de PC-DOCTOR (no exigible);
- pago en efectivo sin obligación vencida.
