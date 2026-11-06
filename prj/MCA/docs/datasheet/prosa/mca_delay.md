<!-- Prosa a mano del datasheet de `mca_delay`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro
     del bloque AUTO:prosa de la pagina en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada. Estos comentarios no se copian.

       pagina:  ../datasheet_mca_delay.md

     Que va aca: que problema resuelve el bloque, como encaja en la cadena y
     las dos o tres decisiones de diseno que explican por que esta hecho asi.
     Lo que se deriva del RTL —puertos, registros, relojes, Fmax, casos de
     test— NO: eso lo escribe el generador y se desactualiza solo.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                           -->

**Qué hace.** Retrasa la muestra (`{val, dat}`) de 0 a 127 ciclos, según
`cfg_pre_dly`. Hace falta porque la ventana la abre el disparo del multitrigger,
y ese disparo llega **tarde** respecto del pie del pulso: el disparo por
pendiente tarda unas L muestras en cruzar su umbral, más sus registros. Con la
muestra retrasada lo justo, el disparo llega cuando el pie está entrando a la
ventana. Cuánto hace falta lo mide `sim/tb_mca_mt_latencia.sv`; la tabla está en
[`register_map_mca.md`](../../mca/register_map_mca.md) §La línea de retardo.

**Dos decisiones.** El retardo es en **ciclos**, no en muestras válidas: la
latencia del trigger es de hardware y no depende de la decimación del MCA, y
`val` viaja con el dato. Y se infiere en SRL con la salida **registrada**: el
clock-to-out de un SRL es lento, y esto es el comienzo del camino de la muestra.
