'use strict';
// Tarjeta de seguimiento: botón para imprimir o guardar como PDF con el diálogo del navegador.
document.addEventListener('click',event=>{if(event.target.closest('[data-print]'))window.print();});
