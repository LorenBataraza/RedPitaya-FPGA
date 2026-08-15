# Mapa de registros — `mca_top` (Analizador Multicanal)

**Base:** `0x4070_0000` (slot 7 del bus de sistema) · **Tamaño de mmap:** `0x30000`
**RTL:** [`prj/MCA/rtl/mine/mca/mca_top.sv`](../../rtl/mine/mca/mca_top.sv)
**Driver:** [`prj/MCA/software/mca_utils.py`](../../software/mca_utils.py)
**Bitstream:** `mca_red_pitaya.bit` (top `mca_red_pitaya_top`) — **no** el del scope

Todos los registros son de 32 bits y viven en el dominio `adc_clk` (125 MHz).
El cruce a `clk_fpga_0` lo hace `sys_bus_cdc` por slot, igual que el scope.

> **El slot 7 en el bitstream del scope es un `sys_bus_stub`**, que responde con
> `err=1`. Por eso el registro `0x000` tiene un valor mágico: permite distinguir
> "bitstream sin MCA" de "MCA presente" sin adivinar.

---

## Identificación

| Offset | R/W | Campo | Descripción |
|---|---|---|---|
| `0x000` | R | `MAGIC` | `0x4D434131` (`"MCA1"`). Si no coincide, no hay MCA cargado. |
| `0x004` | R | `CAPS` | bit0 `EN_HIST_H` (espectro 1D), bit1 `EN_HIST_H_PSD` (mapa 2D) |
| `0x008` | R | `WIDTHS` | `{PSD_AW[23:16], H2_AW[15:8], H_AW[7:0]}` |

`WIDTHS` existe para que el software **derive** los tamaños de apertura en vez de
hardcodearlos: los motores se instancian por parámetro, así que un bitstream
puede traer 4096 canales y otro 16384.

Valores del build por defecto: `H_AW=14` (16384 canales), `H2_AW=7` × `PSD_AW=6`
(mapa de 128 × 64).

---

## Control y estado

| Offset | R/W | Bits | Campo | Descripción |
|---|---|---|---|---|
| `0x00C` | RW | 0 | `run` | Habilita la adquisición y los relojes |
| | W | 1 | `clear` | **Autolimpiante.** Borra histogramas, contadores y relojes |
| | RW | 8 | `chan_sel` | 0 = IN1, 1 = IN2 |
| `0x010` | R | 0 | `clear_busy` | Barrido de borrado en curso |
| | R | 1 | `busy` | Pulso activo o divisor de PSD ocupado |
| | R | 2 | `baseline_stale` | El seguidor de línea de base lleva demasiado congelado |

El barrido de borrado recorre `2^H_AW` bins: **131 µs** con 16384 canales. Durante
ese lapso el puerto de lectura sigue vivo (el bus **no** se cuelga), pero los
eventos que lleguen se descartan y se cuentan en `cnt_dropped`.

---

## Configuración

| Offset | R/W | Campo | Descripción |
|---|---|---|---|
| `0x014` | RW | `cfg_thr` | Umbral sobre la línea de base, 14 b con signo |
| `0x018` | RW | `cfg_hyst` | Histéresis (positiva). Cierra al bajar de `thr − hyst` |
| `0x01C` | RW | `cfg_baseline` | Línea de base fija (si `bl_auto = 0`) |
| `0x020` | RW | `cfg_bl_ctrl` | `{holdoff[31:16], k[7:4], auto[0]}` |
| `0x024` | R | `baseline_now` | Línea de base seguida, para calibrar |
| `0x028` | RW | `cfg_maxlen` | Largo máximo de ventana; al llegar cuenta como apilamiento |
| `0x02C` | RW | `cfg_tail_dly` | Muestras desde el pico hasta el inicio de la cola. **≥ 1** |
| `0x030` | RW | `cfg_amp_min` | Ventana de aceptación en amplitud |
| `0x034` | RW | `cfg_amp_max` | |
| `0x038` | RW | `cfg_amp_src` | bit0: 0 = muestra de pico, 1 = integral. `q_shift` en `[12:8]` |
| `0x03C` | RW | `cfg_h_shift` | Desplazamiento del eje del espectro 1D |
| `0x040` | RW | `cfg_h2_shift` | Desplazamiento del eje de amplitud del mapa 2D |
| `0x044` | RW | `cfg_dec` | Decimación propia del MCA (1 = sin decimar) |
| `0x048` | RW | `cfg_gate_mode` | bit0: **0** = ventana por histéresis, **1** = compuertas de largo fijo |
| `0x04C` | RW | `cfg_gate_len` | `{larga[31:16], corta[15:0]}` en muestras. Sólo con `gate_mode = 1` |

### Los dos modos de ventana

Con **`cfg_gate_mode = 0`** (default, y el comportamiento histórico) la ventana
cierra al bajar de `cfg_thr − cfg_hyst`, o al llegar a `cfg_maxlen` — esto último
cuenta como apilamiento. La cola arranca `cfg_tail_dly` muestras después del pico.

Con **`cfg_gate_mode = 1`** la ventana cierra a `gate_larga` muestras del
disparo, pase lo que pase, y la cola arranca en `gate_corta` — las dos medidas
**desde el disparo**, no desde el pico. Es el método de comparación de carga
(Brooks 1959; Knoll cap. 17).

**Apilamiento en modo 1:** se marca cuando llega un **segundo pulso dentro de la
compuerta**, o sea que la señal bajó de `cfg_thr − cfg_hyst` y **volvió a
cruzar** `cfg_thr` con la ventana todavía abierta.

> La regla obvia —"si al cerrar la señal sigue alta, hay apilamiento"— es
> **incorrecta**, y se descubrió midiendo en la placa. La cola del *propio*
> pulso tarda cientos de muestras en bajar del umbral (~700 con un pulso de 2 µs
> y `thr_lo = 60` cuentas), así que esa regla descartaba el **100 %** de los
> eventos con cualquier compuerta más corta que la cola — justo el rango útil.
> Y como el cruce cae en la parte más chata del pulso, el punto se movía
> cientos de muestras con cualquier deriva de línea de base: el resultado no era
> ni siquiera reproducible entre corridas.

**`cfg_maxlen` no actúa en el modo 1**: el largo ya está acotado por la
compuerta, así que dejarlo activo sólo agregaría un modo de falla si alguien
configurara `maxlen < gate_larga`.

Por qué existe el modo 1: con histéresis el largo de la ventana lo decide dónde
la cola cruza el umbral, que es la parte más chata del pulso — o sea que lo
decide el ruido. Medido offline sobre 7054 pulsos reales, la resolución de la
integral pasa de **0.528 %** (histéresis) a **0.149 %** (compuerta fija), y
también mejora 1.8× sobre la muestra de pico. Ver
[`../../software/tests/estimadores/`](../../software/tests/estimadores/).

### El estimador de amplitud (`cfg_amp_src`) es el parámetro más importante

- **`0` — muestra de pico**: la amplitud sale de *una* muestra, así que arrastra
  el ruido completo del ADC. Peor: el muestreo casi nunca cae en el máximo
  verdadero, y esa subestimación variable **ensancha el fotopico** por razones
  puramente instrumentales. A 125 MSPS con subida de 100 ns hay ~12 muestras en
  el flanco y el error es chico; con subida de 20 ns hay 2.5 y es severo.
- **`1` — integral de carga** (`Q_total >> q_shift`): el ruido blanco promedia
  como σ/√N y desaparece el jitter de muestreo. Es lo que hace cualquier MCA
  digital serio, y lo único que justifica un eje de 16384 canales: con N = 256
  muestras `Q_total` tiene ~21 bits significativos.

Poder alternar entre los dos sobre el mismo estímulo **es** el experimento que
mide la contribución de jitter de muestreo (`compare_estimators()` en
`testbench_mca.py`).

### `cfg_tail_dly` tiene que ser ≥ 1

Con `0` la cola integra desde el arranque del pulso y queda `Q_cola == Q_total`,
que el RTL rechaza y contabiliza en `cnt_rej_psd`. Sin esa guarda el cociente
daría `2^PSD_AW`, que no entra en `PSD_AW` bits y **envolvería a 0**, mandando el
evento al extremo *opuesto* del eje de forma.

---

## Contadores de eventos

| Offset | Campo | Descripción |
|---|---|---|
| `0x050` | `cnt_total` | Pulsos cerrados (aceptados + rechazados) |
| `0x054` | `cnt_accepted` | Entraron al espectro 1D |
| `0x058` | `cnt_rej_amp` | Amplitud fuera de `[amp_min, amp_max]` |
| `0x05C` | `cnt_rej_psd` | `Q_total = 0` o `Q_cola ≥ Q_total`: entran al 1D pero **no** al 2D |
| `0x060` | `cnt_pileup` | Cerrados por `maxlen`: contaminados, **no** se histogramean |
| `0x064` | `cnt_dropped` | Perdidos por divisor ocupado, colisión de lectura o borrado |

Todos se ponen a cero con `clear` (`0x00C` bit 1).

## Relojes (64 bits)

| Offset | Campo |
|---|---|
| `0x068` / `0x06C` | `realtime` lo / hi |
| `0x070` / `0x074` | `livetime` lo / hi |
| `0x078` / `0x07C` | `deadtime` lo / hi |

Cuentan ciclos de `adc_clk` mientras `run = 1`. Dividir por 125e6 para segundos.
`livetime + deadtime = realtime`.

> **Leer siempre la palabra BAJA primero.** Leer `lo` congela `hi` en un registro
> sombra del RTL. Al revés la lectura se parte: a 125 MHz el contador avanza
> entre los dos accesos. `mca_utils._r64()` respeta el orden.

## Último evento (depuración)

| Offset | Campo |
|---|---|
| `0x080` | `amp` (16 b) |
| `0x084` | `psd` (`PSD_AW` b) |
| `0x088` | `Q_total` |
| `0x08C` | `Q_cola` |

Sirve para ajustar umbrales: si `cnt_total` no sube, mirar `baseline_now` y
`Q_total` dice enseguida si el problema es la base o el umbral.

---

## Aperturas de histograma

| Offset | Contenido | Tamaño |
|---|---|---|
| `0x10000` | Espectro 1D de amplitud | `2^H_AW` palabras (64 KB con `H_AW=14`) |
| `0x20000` | Amplitud × factor de forma | `2^(H2_AW+PSD_AW)` palabras |

Bins **uint32 sin signo**, saturantes (se quedan en `0xFFFFFFFF`, no envuelven).
A diferencia del buffer del scope, acá **no** hay que extender el signo.

El mapa 2D se lee como un bloque y se hace `reshape(2^H2_AW, 2^PSD_AW)`: filas =
amplitud, columnas = factor de forma.

Las aperturas decodifican `sys_addr[19:16]`, o sea 64 KB cada una, mientras que
el histograma ocupa menos: los offsets de más **aliasan** sobre el mismo
contenido. Fijar `count = 2**AW` al armar la vista numpy para no caminar sobre el
espejo.

---

## Notas de implementación

**Ack de latencia fija.** El esclavo hace ack a los 4 ciclos para *cualquier*
dirección, desde un shift register incondicional. No existe ninguna ruta de ack
por motor, así que un motor apagado por parámetro no puede colgar el bus: su
apertura simplemente devuelve 0. Es deliberado — el scope tiene un bug latente
justo de esa clase (`multitrigger_rp_scope_cfg.sv:506-507` nunca hace ack para
los canales no construidos y el bus se cuelga hasta el timeout de 32 ciclos de
`rtl/axi4_slave.sv:193`). `tb_mca_top.sv` es la regresión contra eso.

**Escritura.** `sys_bus_cdc` sostiene `wen` hasta el ack (~5 ciclos), así que el
RTL usa un estrobo de un ciclo: sin él cada transacción ejecutaría la escritura
5 veces y `clear` quedaría activo 5 ciclos en vez de uno.

**Lectura del histograma.** El puerto B de la BRAM se comparte entre el bus y el
pipeline de incremento; el dato del bus se retiene en un registro con enable. Sin
ese enable el valor vivía un solo ciclo y, como el ack llega 4 ciclos después,
toda lectura devolvía el bin del **último evento** en vez del pedido.

**Sin ecualizador.** `mca_red_pitaya_top` instancia el scope con `EN_FILT(0)`: el
lazo IIR de `osc_filter` no cierra timing a 125 MHz en el `-1` (9.421 ns contra
8 ns) y aportaba 137 de los 221 endpoints en falla. Para espectroscopía no hace
falta, y con los coeficientes de reset era un pass-through de todos modos. El
bitstream del scope conserva el filtro (`EN_FILT` default = 1).
