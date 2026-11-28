# Battery Health Premium 5.0 — Dynamic Health Animation System

## Implementación

El indicador de cada portátil convencional y gaming usa la evaluación vigente de su unidad. La carcasa, el contorno, el terminal, los cinco segmentos y el `viewBox` del SVG aprobado conservan su geometría. La iluminación se añade dentro de los grupos de relleno mediante recortes SVG por segmento y una máscara de gradiente. El espacio del indicador se mantiene estable al modificar el desgaste desde el diálogo o guardar una revisión.

| Salud registrada | Estado | Iluminación |
| --- | --- | --- |
| 90–100 % | Excelente | Onda verde de 3,6 s y pulso del contorno |
| 80–<90 % | Buen estado | Pulso interno verde de intensidad moderada |
| 60–<80 % | Desgaste moderado | Onda amarilla y pulso suave del contorno |
| 40–<60 % | Desgaste elevado | Brillo naranja escalonado y pulso del contorno |
| 0–<40 % | Estado crítico | Pulso rojo de 4,8 s en contorno y terminal |
| Pendiente de diagnóstico | Pendiente | Gris azulado estático y sin porcentaje |

La salud equivale a 100 menos el desgaste. El cálculo existente en puntos básicos conserva hasta dos decimales. Cada segmento representa 20 puntos porcentuales. Los cambios de escala horizontal y color duran 600 ms. La iluminación representa salud registrada. La carga eléctrica actual se mide por separado.

El diálogo permite desactivar el movimiento y guarda la preferencia en el navegador. El componente respeta `prefers-reduced-motion`. Un observador compartido pausa las animaciones fuera de pantalla. La visibilidad de la pestaña controla la pausa en segundo plano.

El informe de situación de ADI incorpora una explicación técnica y un borrador para el cliente. ADI toma el registro vigente y presenta los rangos como orientativos. La capacidad de diseño, la autonomía bajo carga y la inspección física aportan contexto a la decisión técnica. El cliente recibe el texto solo cuando el responsable decide compartirlo. Se conservan los permisos actuales del diagnóstico y el historial de revisiones.

## Verificación

- Pruebas de persistencia y API con datos ficticios para 0 %, 0,1 %, 35 %, 50 %, 65 %, 85 %, 99,9 % y 100 %. También cubren dispositivos excluidos y la respuesta de ADI ante un diagnóstico pendiente y uno crítico.
- Chromium a 320, 390, 768 y 1280 px. Se verificaron los temas claro explícito y oscuro, el contraste, el foco de teclado, Escape, la geometría SVG, los límites decimales, el relleno proporcional, las duraciones y los desbordamientos.
- Un listado de 80 indicadores verificó la pausa fuera del área visible y la reanudación al desplazarse. El navegador también verificó la inactividad en segundo plano y con movimiento reducido.
- Regresión pública de identidad con datos ficticios y verificaciones de sintaxis de JavaScript y Python. El control de migraciones pasó. Esta actualización reutiliza la migración 133.

Las pruebas focalizadas terminaron correctamente. Para repetirlas desde la raíz:

```bash
PYTHONPATH=local:local/tests python -m unittest test_order_battery test_order_battery_visual test_adi_order test_adi_7 test_db_migrations test_public_identity_visual
```

La suite general se ejecutó con `PYTHONPATH=local` y se reanudó desde el registro tras dos interrupciones del entorno. Pasaron 1.193 pruebas. Se omitieron cuatro pruebas de integración que requieren un servidor libSQL local y una prueba de lectura de QR que requiere zbarimg y magick.

## Versión

La versión v1.6.2 sigue directamente a v1.6.1. El registro local y el CHANGELOG conservan ambas entradas. La comprobación previa al despliegue confirmó v1.6.1 y la compilación 5964434 en producción, correspondientes al main remoto. Después del despliegue se comprobarán el número de versión y la compilación activos.
