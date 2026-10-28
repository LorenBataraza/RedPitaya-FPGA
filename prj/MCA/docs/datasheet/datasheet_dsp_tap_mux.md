# Datasheet — `dsp_tap_mux`

<!-- Generado por `modulos/mk/datasheet.py`. Lo que está entre las marcas
     AUTO:x y /AUTO:x se REESCRIBE en cada corrida: editar ahí no sirve.
     Todo el resto es prosa a mano y no se toca.
     La §1.1 «Qué hace» se escribe en prosa/dsp_tap_mux.md.
     Regenerar:  make -C modulos/comun/work datasheet              -->

## 1. Función y funcionamiento

### 1.1 Descripción breve

<!-- AUTO:resumen -->
|  |  |
|---|---|
| Módulo RTL | `dsp_tap_mux` |
| Archivo | [`dsp_tap_mux.sv`](../../modulos/comun/rtl/dsp_tap_mux.sv) |
| Parámetros | 1 |
| Puertos | 4 (2 in / 2 out) |


![Interfaz de dsp_tap_mux](figuras/dsp_tap_mux_interfaz.svg)

**Cabecera del RTL** (se copia tal cual de [`dsp_tap_mux.sv`](../../modulos/comun/rtl/dsp_tap_mux.sv)):

> dsp_tap_mux — elige de qué punto de la cadena DSP toma un consumidor
>
> La cadena DSP del scope tiene varios nodos utilizables, y hasta el refactor
> cada consumidor estaba cableado a uno fijo:
>
>   adc_dat ─→ calib ─→ osc_filter ─→ [byp] ─→ adc_dec_in ──────── TAP_DEC_IN
>      │                                            │                  └→ MCA
>   TAP_ADC                                     rp_decim ─→ adc_dly_in
>                                                    │           └→ rp_adc_trig (MTRG)
>                                               rp_delay ─→ adc_bram_in ── TAP_BRAM_IN
>                                                                  └→ rp_acq_bram (OSC)
>
> Este mux deja que el software lo decida en runtime, desde los registros
> ROUTE_* de la región de TOP (integration_cfg, slot 6).
>
> EL DATO Y SU VALID VIAJAN JUNTOS. Los nodos post-decimación llevan estrobo
> (dec_val, dly_val) porque la decimación no es 1; los pre-decimación son
> continuos a 125 MSPS y su valid es constante. Mezclarlos sin arrastrar el
> valid daría un consumidor que lee muestras repetidas o se saltea muestras,
> según el sentido del cambio.
>
> POR QUÉ EL MUX ES COMBINACIONAL Y NO REGISTRADO. Registrar la salida sería
> lo natural para timing, pero correría el dato UN ciclo respecto de las
> señales de control que lo acompañan (adc_we y el write pointer en el caso
> del OSC, la alineación trigger-vs-captura en el del multitrigger), y en modo
> NATIVO el hardware dejaría de ser idéntico al de antes del refactor — que es
> justamente la propiedad que se quiso preservar. Un mux 4:1 de 14 bits es un
> LUT6 por bit, un solo nivel de lógica, y no cae sobre el camino crítico del
> diseño (que era el lazo IIR de osc_filter, deshabilitado con EN_FILT=0).
> Si alguna vez hiciera falta registrarlo, hay que registrar TAMBIÉN el valid
> y las señales de control de cada consumidor, en conjunto.
<!-- /AUTO:resumen -->

<!-- AUTO:prosa -->
<!-- Prosa a mano: se edita en prosa/dsp_tap_mux.md, no aca. -->

**Qué hace.** Es un mux 4:1 de 14 bits que decide **de qué punto de la cadena
DSP del scope toma las muestras un consumidor**. Hay tres instancias dentro de
[`rp_scope_mt_com`](datasheet_rp_scope_mt_com.md) —una por
consumidor: OSC, multitrigger y MCA— y las tres se controlan desde los
registros `ROUTE_*` de la región de TOP
([`integration_cfg`](datasheet_integration_cfg.md), slot 6).

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
[`comun_b_taps.png`](../comun/figuras/transacciones/comun_b_taps.png) y en el
tríptico [`comun_transaccion.png`](../comun/figuras/transacciones/comun_transaccion.png).

> **Un cuarto destino que existe en el mapa y no en el hardware.**
> `integration_cfg` expone `route_ring_tap_o` / `route_ring_en_o`, pero el top
> del anillo de eventos los deja **sin conectar**
> (`rtl/mine/tops/event_ring_red_pitaya_top.sv:882`): el `event_ring` toma
> siempre su nodo nativo y escribir ese registro no hace nada. Está acá para
> que no se lea el mapa de registros como si el ruteo del ring ya existiera.
<!-- /AUTO:prosa -->

### 1.2 Interfaces

<!-- AUTO:interfaces -->
#### Parámetros

| Parámetro | Tipo | Default |
|---|---|---|
| `DW` | `integer` | `14` |


#### Puertos

##### Señales

Selección (desde integration_cfg). Ver la lista canónica de taps en integration_cfg.sv; si cambia allá, cambia acá.

| Puerto | Dir | Bits | Dominio |
|---|---|---|---|
| `tap_sel_i` | in | 2 | sin reloj |
| `en_i` | in | 1 | sin reloj |
| `dat_o` | out | 14 `[DW-1:0]` | sin reloj |
| `val_o` | out | 1 | sin reloj |
<!-- /AUTO:interfaces -->

### 1.3 Mapa de registros

<!-- AUTO:regmap -->
No hay un mapa de registros para este módulo en `docs/comun/`. Si es un esclavo del bus de sistema, falta escribirlo; si no lo es, esta sección no aplica.
<!-- /AUTO:regmap -->

### 1.4 Clock domains

<!-- AUTO:clocks -->
_(nada)_


**Combinacional:** el módulo no tiene puerto de reloj.
<!-- /AUTO:clocks -->

<!-- A mano: si hay más de un reloj, cuál es el cruce, con qué se sincroniza y
     qué se asume de la relación de frecuencias. Si hay uno solo, borrar. -->

### 1.5 Frecuencia máxima de trabajo

<!-- AUTO:timing -->
Sin datos de síntesis todavía. Correr:

```bash
make -C modulos/comun/work syn
make -C modulos/comun/work sweep-all
```

y volver a generar esta página.
<!-- /AUTO:timing -->

<!-- A mano: qué hay en el camino crítico y qué se haría para romperlo si
     hubiera que subir la frecuencia. -->

### 1.6 Transacciones

<!-- AUTO:transacciones -->
**LO QUE ENTRA: EL PULSO AL RITMO DEL ADC**

![LO QUE ENTRA: EL PULSO AL RITMO DEL ADC](../comun/figuras/transacciones/comun_a_pulso.png)

Que entra a la cadena. Una muestra por ciclo de adc_clk, 125 MSPS, continua: en este nodo el valid vale siempre 1, asi que no hay nada que un consumidor pueda esperar. Son las 160 muestras del flanco de un pulso real de la campana e2e, el mismo que usa la figura de event_ring --hay una sola copia del dato en el repo--.

_Origen: campaña e2e, `software/datos/e2e_20260528_013404/principal/chunk_000000.npz`, evento 1._

**UNA SOLA CADENA, CUATRO NODOS**

![UNA SOLA CADENA, CUATRO NODOS](../comun/figuras/transacciones/comun_b_taps.png)

Que viaja. No hay una cadena por consumidor: hay UNA, y cuatro puntos utilizables sobre ella. Cada consumidor tiene su propio mux 4:1 y elige el suyo en runtime con los registros ROUTE_* de la region de TOP. El mux es COMBINACIONAL a proposito: registrarlo corrorria el dato un ciclo respecto de las senales de control que lo acompanan --adc_we y el write pointer del osciloscopio, la alineacion trigger-vs-captura del multitrigger-- y en modo nativo el hardware dejaria de ser identico al de antes del refactor, que es justo la propiedad que se quiso preservar.

_Origen: estructura de `dsp_tap_mux.sv` y del top._

**EL MISMO PULSO EN LOS CUATRO NODOS**

![EL MISMO PULSO EN LOS CUATRO NODOS](../comun/figuras/transacciones/comun_c_nodos.png)

Que sale, y lo que importa no es solo el valor: es el RITMO. En A y B hay una muestra por ciclo y el valid es constante; en C y D sale una cada 8 ciclos y el dato viaja con estrobo --512 muestras contra 64, 8x menos--. Por eso la cabecera del RTL insiste en que el dato y su valid viajan JUNTOS: un consumidor que cambie de nodo sin arrastrar el valid leeria muestras repetidas o se saltearia muestras, segun el sentido del cambio. El diezmado es con promediado, o sea un promedio de bloque de 8 muestras: es el unico bloque de la cadena que cambia la FORMA del pulso, y lo paga en ritmo. D es C corrido 4 muestras diezmadas (32 ciclos). A y B salen IGUALES en el dibujo y eso no es que la calibracion no haga nada: es que esta captura ya paso por ella y el archivo no guarda los coeficientes, asi que re-aplicarlos seria inventarlos.

_Origen: el pulso medido, con el diezmado y el retardo aplicados._

**LA TRANSACCION COMPLETA**

![LA TRANSACCION COMPLETA](../comun/figuras/transacciones/comun_transaccion.png)

Las tres preguntas en una imagen: que entra, que viaja y que sale.

_Origen: las tres anteriores, en una figura._

---

Las figuras **recalculan cada número al dibujar** en vez de tomarlo escrito. Las genera [`transacciones_comun.py`](../comun/figuras/transacciones/transacciones_comun.py); de dónde sale el dato de cada una está en la columna «Datos» de [`README.md`](../comun/figuras/transacciones/README.md); los epígrafes completos, en [`epigrafes.txt`](../comun/figuras/transacciones/epigrafes.txt).
<!-- /AUTO:transacciones -->

### 1.7 Waveforms

<!-- AUTO:ondas -->
_Sin figuras de ondas._ Se generan con un script en `docs/comun/figuras/ondas/`, que saca las ondas de un VCD de los testbenches del módulo; el patrón está en [`docs/figuras/ondas.py`](../figuras/ondas.py).
<!-- /AUTO:ondas -->

<!-- A mano: lo que las figuras no pueden mostrar solas. Para agregar una,
     editar docs/comun/figuras/ondas/ondas_comun.py: la onda
     sale de un VCD de los testbenches y los tiempos los mide el script.
       make -C modulos/comun/work wave TB=<tb>   # mirar en Questa
       make -C modulos/comun/work vcd  TB=<tb>   # VCD exportable -->

### 1.8 Verificación realizada

<!-- AUTO:verificacion -->
Todo corre en batch y se chequea el `RESULT: PASS` del testbench; las ondas quedan en `work/waves/<tb>.wlf`.

```bash
make -C modulos/comun/work            # el 1 testbench
make -C modulos/comun/work cov        # + cobertura
make -C modulos/comun/work lint
```

| Testbench | DUT | Escenas | Casos | Contra qué compara | Es el de este módulo |
|---|---|---|---|---|---|
| [`tb_integration_cfg`](../../modulos/comun/sim/tb_integration_cfg.sv) | `integration_cfg` | 7 | 36 | vectores a mano |  |


**36 casos con nombre** en 1 testbench (7 escenas). La lista completa, caso por caso, está en el plan de verificación.

> **`dsp_tap_mux` no tiene testbench propio.** Ningún `TBS` del `work/Makefile` lo instancia como DUT: lo que se verifica de este módulo es lo que arrastre el TB de otro. Es deuda de verificación, no una omisión de esta página.

**Assertions** — en `sim/sva/`, enganchadas por `bind` (no tocan el RTL sintetizable).

- [`bind_comun.sv`](../../modulos/comun/sim/sva/bind_comun.sv)
- [`integration_cfg_sva.sv`](../../modulos/comun/sim/sva/integration_cfg_sva.sv)

> **Los archivos de assertions están vacíos.** Son el scaffold de `create_module.py`: tienen el `bind`, el `default clocking` y un `// TODO:`, pero **ninguna propiedad**. O sea que hoy no aportan nada a la verificación; el enganche ya está hecho y lo que falta es escribirlas. Ver [`verificacion_formal.md`](../verificacion_formal.md), que discute cuáles convienen primero.

Plan de verificación, casos cubiertos y deuda: [`comun/sim/VERIFICACION.md`](../../modulos/comun/sim/VERIFICACION.md).
<!-- /AUTO:verificacion -->

#### Esquema de laboratorio

TODO — qué instrumento, cómo se conecta, qué se mide y contra qué se compara.
