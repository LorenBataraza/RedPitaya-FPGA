<!-- Prosa a mano del datasheet de `dsp_tap_mux`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_dsp_tap_mux.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es un mux 4:1 de 14 bits que decide **de qué punto de la cadena
DSP del scope toma las muestras un consumidor**. Hay tres instancias dentro de
[`rp_scope_mt_com`](../datasheet_rp_scope_mt_com.md) —una por
consumidor: OSC, multitrigger y MCA— y las tres se controlan desde los
registros `ROUTE_*` de la región de TOP
([`integration_cfg`](../datasheet_integration_cfg.md), slot 6).

Antes del refactor cada consumidor estaba **cableado** a un nodo fijo de la
cadena. Eso hacía que una pregunta como «¿cuánto del ensanchamiento del
fotopico lo pone el ecualizador y cuánto la decimación?» exigiera un bitstream
por respuesta. Con el mux la pregunta se contesta escribiendo un registro y
repitiendo la medición sobre el **mismo** hardware, que es la única forma de
atribuir una diferencia al bloque y no a la síntesis.

Tres cosas que hacen a su contrato:

- **El `valid` viaja con el dato.** Los nodos post-decimación llevan estrobo y
  los pre-decimación son continuos a 125 MSPS. Rutear el dato sin arrastrar su
  `valid` daría un consumidor que lee muestras repetidas o se saltea muestras,
  según hacia dónde se mueva la selección — y sin ningún síntoma evidente.
- **Hay un tap `NATIVO` y es el default.** Con `tap_sel = 0` cada consumidor
  recibe exactamente el nodo al que estaba cableado antes del refactor, así que
  el reset reproduce el hardware viejo. Es lo que permite usar el mux como
  instrumento: si un resultado cambia, es porque alguien escribió un `ROUTE_*`.
- **Es combinacional a propósito.** Registrarlo correría el dato un ciclo
  respecto de las señales de control que lo acompañan (`adc_we` y el write
  pointer del OSC, la alineación trigger-captura del multitrigger) y el modo
  nativo dejaría de ser idéntico al original. Un mux 4:1 de 14 b es un LUT6 por
  bit y no cae sobre el camino crítico.

Los cuatro taps, medidos sobre la misma señal y comparados entre sí, están en
[`comun_b_taps.png`](../../comun/figuras/transacciones/comun_b_taps.png) y en el
tríptico [`comun_transaccion.png`](../../comun/figuras/transacciones/comun_transaccion.png).

> **Un cuarto destino que existe en el mapa y no en el hardware.**
> `integration_cfg` expone `route_ring_tap_o` / `route_ring_en_o`, pero el top
> del anillo de eventos los deja **sin conectar**
> (`rtl/mine/tops/event_ring_red_pitaya_top.sv:882`): el `event_ring` toma
> siempre su nodo nativo y escribir ese registro no hace nada. Está acá para
> que no se lea el mapa de registros como si el ruteo del ring ya existiera.
