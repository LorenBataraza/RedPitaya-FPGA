<!-- Prosa a mano del datasheet de `event_ring_top`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_event_ring_top.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Convierte cada evento en un **slot de DDR** y los encadena en una
cola productor/consumidor de `N_SLOTS`. Reemplaza el ciclo «capturar → congelar
→ que el PS lea por GP0 → re-armar» por uno donde **el hardware sigue
capturando mientras el PS drena**.

El problema que resuelve es el techo de tasa. En el esquema K=1 el PS está en el
camino crítico de cada evento: τ = 252.7 µs por evento, o sea ~3.7 kev/s, y lo
que se pierde no es una fracción de los pulsos sino **períodos enteros** (está
medido en [`multitrigger`](../datasheet_mt_cfg.md#16-transacciones):
a 8 kHz entra uno de cada cinco). Acá la PL escribe por AXI HP0 por DMA y
mientras queden créditos no espera a nadie.

Tres decisiones que lo hacen funcionar:

- **El footer es la marca de commit, y por eso no hace falta el `BRESP`.** La
  última palabra de cada slot vale `{~seq, seq}`. Como todas las escrituras
  salen por un único master con un único ID, AXI garantiza que se observan en
  orden: si el footer está bien formado y trae el `seq` esperado, **todo lo
  anterior ya llegó a DDR**. El plan original decía «incrementar `wr_slot` con
  el `BRESP` del último burst», que es correcto pero inaplicable — ni
  `axi_wr_fifo` ni `axi_master` exponen el canal B.
- **El PS no lee ningún registro por GP0 en el lazo caliente.** Polea el footer
  del próximo slot directamente en DDR, y publica `RD_SLOT` una vez **por
  batch**, no por evento. Publicarlo por evento devolvería el GP0 al camino
  crítico, que es exactamente lo que se está sacando.
- **La geometría se congela en `STOPPED`.** `SLOT_BASE`, `RING_SZ`,
  `SLOT_SHIFT`, `PRE` y `POST` sólo latchean con la adquisición parada, para que
  nunca convivan dos geometrías en el mismo ring. Escribirlos corriendo se
  ignora y levanta `err_cfg` (sticky).

Un detalle que conviene tener presente al dimensionar: el slot tiene que ser
**potencia de dos** para que su dirección salga de un shift, así que una ventana
de 512 muestras × 2 canales ocupa 4096 B de los cuales sólo la mitad son
muestras. El layout palabra por palabra, con los valores de un evento real,
está en [§1.6](#16-transacciones).
