<!-- Prosa a mano del datasheet de `event_window_capture`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_event_window_capture.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Por cada trigger extrae una **ventana** de muestras —`pre` antes
y `post` desde el disparo— y la emite como un stream de 16 bits hacia
[`event_stage_fifo`](../datasheet_event_stage_fifo.md). Es la primera etapa del
[`event_ring_top`](../datasheet_event_ring_top.md) y lo que reemplaza el rol de
`rp_bram_sm` en el camino de eventos.

**La diferencia con el camino del scope es estructural, no de tamaño.**
`rp_bram_sm` **congela** un buffer de 16384 muestras y no puede volver a
capturar hasta que el PS lo re-arma: son ~**252 µs** de tiempo muerto por
evento. Acá la ventana se copia a un stream aguas abajo y el bloque vuelve a
estar listo en `pre+post` ciclos —~**256 ns**— sin que el PS intervenga. Eso es
lo que convierte el osciloscopio en un adquisidor de eventos.

**Una sola memoria para el pre y el post.** El pre-trigger vive en un buffer
circular que se escribe siempre, y la lectura de la ventana sale del **mismo**
buffer, arrancando `pre` muestras atrás del trigger. El puntero de lectura
queda rezagado y, como se consume una muestra por ciclo y se produce a lo sumo
una, el rezago **nunca crece**: alcanza al productor y después va en lock-step
durante el post. Por eso la profundidad sólo tiene que cubrir `pre`, no
`pre+post`.

**El evento se acepta o se descarta entero, y se decide en el SOF.** El
handshake con el consumidor ocurre en el ciclo del trigger: si la ventana
completa no entra, el evento se descarta completo. Nunca se emite media
ventana, porque un evento parcial en el ring sería **indistinguible de uno
bueno** del lado del PS.

**Las dos causas de pérdida se cuentan por separado** porque son diagnósticos
distintos: `drop_busy` es el trigger que cayó mientras se drenaba la ventana
anterior —el tiempo muerto **intrínseco** del PL, `pre+post` ciclos— y
`drop_full` es que aguas abajo no aceptó —la stage llena, o sin créditos de DDR
porque el PS no drena: tiempo muerto del **consumidor**—. Confundirlos llevaría
a agrandar el buffer cuando el problema es el software, o al revés.

> **El trigger se toma por FLANCO, y eso costó un bug en la placa.**
> `mt_trig_src` registra `adc_trig` como un **nivel**, y el estrobo
> de escritura que llega por el `sys_bus_cdc` puede durar más de un ciclo de
> `adc_clk`: cada trigger por software producía **dos** eventos, uno capturado
> y uno contado como `drop_busy`. Depender del ancho del pulso de un módulo que
> no controlamos es frágil; el flanco no.

La ventana tal como sale, con sus tiempos medidos, está en
[`event_ring_a_ventana.png`](../../event_ring/figuras/transacciones/event_ring_a_ventana.png);
el diseño completo del camino, en
[`logica_de_captura_y_axi.md`](../../event_ring/logica_de_captura_y_axi.md).
