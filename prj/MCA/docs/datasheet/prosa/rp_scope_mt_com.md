<!-- Prosa a mano del datasheet de `rp_scope_mt_com`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_rp_scope_mt_com.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es **la región del osciloscopio entera**: el contenedor que los
tres tops instancian y que tiene adentro toda la cadena de adquisición, los
dos esclavos de registros y la lógica de disparo. No es un bloque con una
función, es el lugar donde se cablea el sistema — por eso es el archivo que
hay que leer para saber de dónde sale cada señal.

Viene de `red_pitaya_scope.v` de fábrica, y lo que le agregó este proyecto es
la cadena de taps, el multitrigger y las dos salidas nuevas hacia los
consumidores propios.

**Qué tiene adentro.** Por canal: calibración → ecualizador
([`osc_filter`](../datasheet_osc_filter.md), si `EN_FILT = 1`) → decimación
(`rp_decim`) → retardo (`rp_delay`) → buffer de captura (`rp_bram_sm`,
`rp_acq_bram`), y los tres [`dsp_tap_mux`](../datasheet_dsp_tap_mux.md) que
eligen desde dónde lee cada consumidor. Comunes: el multitrigger entero,
[`mt_top`](../datasheet_mt_top.md) (los disparos de nivel y de pendiente de
cada canal, la lógica de evento y [`mt_cfg`](../datasheet_mt_cfg.md), el
esclavo del slot 3), y [`osc_cfg`](../datasheet_osc_cfg.md), el esclavo del
slot 1.

**Las dos salidas que lo conectan con el resto del proyecto:**

- `mca_dat_o` / `mca_val_o` — la muestra acondicionada hacia el
  [`mca_top`](../datasheet_mca_top.md): post-calibración, post-ecualizador y
  **pre-decimación**, a 125 MSPS. Es el mismo nodo que alimenta a `rp_decim`,
  así que los umbrales del MCA y los del scope son comparables; pero el MCA
  lleva **su propia** decimación y queda desacoplado del `set_dec` del scope.
- `event_trig_o` / `event_snap_o` — hacia el
  [`event_ring_top`](../datasheet_event_ring_top.md). Es **el mismo**
  `trigger_event` que alimenta a `rp_bram_sm` y `rp_axi_sm`, y el mismo
  snapshot que se lee en `SNAPSHOT` (`0x018` del slot 3): el anillo **no introduce una fuente de
  disparo nueva**, se cuelga de la que ya existe.

En `red_pitaya_top` esos puertos quedan sin conectar y se podan: el netlist
del scope de fábrica no cambia.

**`EN_FILT` es la decisión de diseño que más se nota.** El lazo IIR del
ecualizador no cierra timing a 125 MHz en el -1: registro → multiplicación →
suma de 48 bits → registro en **un** ciclo, 9.421 ns contra 8 ns de período, y
son **137 de los 221 endpoints en falla** del diseño, con la peor severidad
(−1.820 ns contra ≤0.2 ns del resto). Se probaron dos reescrituras equivalentes
bit a bit y ninguna mejoró —plegar el término al coeficiente lleva a 27 bits y
Vivado parte el multiplicador en dos DSP en cascada **dentro** del lazo
(−3.514 ns); reasociar en dos pasos deja igual un sumador en el lazo
(−1.957 ns)—, así que es una limitación estructural y no de codificación. El
default es `1` para que el top de fábrica no cambie en nada; los tops del MCA y
del anillo usan `0`, que saca el lazo del diseño y con él el camino crítico.

El mapa de slots completo está en
[`register_map_top.md`](../../TOP/register_map_top.md), y cómo se recorre el
sistema de punta a punta en
[`cadena_de_medicion.md`](../../cadena_de_medicion.md).
