# Referencia de la API

Todas las funciones públicas por módulo, y **a qué registro pega cada una**. La
nomenclatura de tres capas está en [`README.md`](README.md).

Los mapas de registros completos (con la semántica de cada bit) viven aparte:
[MCA](../mca/register_map_mca.md) · [scope/multitrigger](../multitrigger/register_map_multitrigger_rp_scope_cfg.md) · [event_ring](../event_ring/diseno_y_register_map.md).

---

## 1. `API.mca` — analizador multicanal

Base `0x4070_0000` (slot 7). Código: [`API/mca.py`](../../software/API/mca.py).

### 1.1 Ciclo de vida

| Función | Efecto |
|---|---|
| `mca_open(phys, size, check_magic=True)` | mmap de `/dev/mem`, valida el magic `"MCA1"`. Devuelve el **handle** que usan las demás |
| `mca_close(h)` | cierra mmap y fd |
| `mca_identify(h, verbose=True)` | lee magic/caps/widths, devuelve `n_channels` y `map2d_shape` |
| `mca_start(h)` / `mca_stop(h)` | bit `run` de `R_CTRL` (`0x00C`) |
| `mca_clear(h, timeout_s=1.0)` | bit `clear` autolimpiante; espera a que baje `clear_busy` |

> `mca_open()` valida el magic porque **en el bitstream del scope el slot 7 es un
> `sys_bus_stub`**. Sin esa comprobación, la primera lectura sobre una PL sin MCA
> mata el proceso con SIGBUS y sin traceback.

### 1.2 Configuración — un `get`/`set` por campo

Todos toman el handle: `mca_get_thr(h)` / `mca_set_thr(h, 200)`.

| Campo | Registro | Bits | Nota |
|---|---|---|---|
| `thr` | `0x014` | `[13:0]` | umbral de disparo |
| `hyst` | `0x018` | `[13:0]` | histéresis |
| `baseline` | `0x01C` | `[13:0]` | línea de base fija |
| `bl_auto` | `0x020` | `[0]` | seguidor automático de base |
| `bl_k` | `0x020` | `[7:4]` | τ = 2^k muestras — **ver aviso abajo** |
| `bl_holdoff` | `0x020` | `[31:16]` | |
| `maxlen` | `0x028` | `[15:0]` | largo máximo de pulso |
| `tail_dly` | `0x02C` | `[15:0]` | retardo de la compuerta de cola, **≥ 1** |
| `amp_min` / `amp_max` | `0x030` / `0x034` | `[15:0]` | ventana de aceptación |
| `amp_src` | `0x038` | `[0]` | 0 = muestra de pico, 1 = integral de carga |
| `q_shift` | `0x038` | `[12:8]` | escala de la integral |
| `h_shift` | `0x03C` | `[4:0]` | |
| `h2_shift` | `0x040` | `[4:0]` | |
| `dec` | `0x044` | `[15:0]` | **≥ 1** |
| `gate_mode` | `0x048` | `[0]` | |
| `gate_short` | `0x04C` | `[15:0]` | |
| `gate_long` | `0x04C` | `[31:16]` | |
| `channel` | `0x00C` | `[8]` | 0 = IN1, 1 = IN2 |

**Cinco campos comparten registro con otros** (`bl_*` en `0x020`, `amp_src`/
`q_shift` en `0x038`, `gate_short`/`gate_long` en `0x04C`, `channel` con `run` en
`0x00C`). Los `set_` hacen **read-modify-write**, así que poner uno no borra sus
vecinos. Es seguro porque el RTL relee esos registros enteros
(`mca_top.sv:340,346,351`). Lo verifica
[`test_api_mca.py::test_rmw_no_pisa_campos_vecinos`](../../software/tests/test_api_mca.py).

> **`bl_k` tiene que ser MUCHO más largo que el pulso.** La constante es 2^k
> muestras (8 ns cada una). Si es comparable al pulso, el seguidor lo persigue y
> lo borra: la señal nunca cruza el umbral y **no se detecta nada**. Medido en la
> placa con un pulso de 62 µs: `bl_k=6` → 0 eventos; `bl_k=9,12,15` → los ~2000
> esperados. Regla práctica: τ ≥ 100× la duración del pulso. Ante la duda, base
> fija (`bl_auto=False`), que es inmune.

`mca_configure(h, **kw)` escribe el bloque entero de una vez, con la misma firma
que `MCA.configure()`. Es lo que usa `testbench_mca.py`.

### 1.3 Estatus (sólo lectura)

| Función | Registro |
|---|---|
| `mca_get_status(h)` | `0x010` crudo |
| `mca_get_running(h)` | `0x00C[0]` |
| `mca_get_clear_busy(h)` | `0x010[0]` |
| `mca_get_baseline_stale(h)` | `0x010[2]` |
| `mca_get_baseline_now(h)` | `0x024`, con extensión de signo a 14 bits |
| `mca_get_caps(h)` | `0x004` |
| `mca_get_widths(h)` | `0x008` → `{h_aw, h2_aw, psd_aw}` |
| `mca_get_config(h)` | los 19 campos de arriba, releídos del hardware |
| `mca_get_metadata(h)` | config + contadores + geometría + sello de tiempo (39 claves) |

`mca_get_metadata()` es lo que acompaña a un espectro guardado para que el
fichero se entienda solo dentro de un año.

### 1.4 Lectura

| Función | Devuelve |
|---|---|
| `mca_read_histogram(h)` | `uint32[2**h_aw]` — espectro 1D |
| `mca_read_map2d(h)` | `uint32[2**h2_aw, 2**psd_aw]` — amplitud × forma |
| `mca_read_counters(h)` | dict: `total`, `accepted`, `rej_amp`, `rej_psd`, `pileup`, `dropped`, `realtime_s`, `livetime_s`, `deadtime_s` |
| `mca_read_last_event(h)` | dict: `amp`, `psd`, `q_tot`, `q_tail`, `baseline` |
| `mca_read_acquire(h, seconds, clear_first=True)` | `(hist, map2d\|None, counters)` |
| `mca_read_acquire_chunks(h, seconds, chunk_s, on_chunk=None)` | acumula en el mismo histograma, llamando a `on_chunk` por rebanada |

> **Un espectro de 16384 canales tarda ~110 ms y eso NO es optimizable.** Se lee
> palabra a palabra a propósito: `rtl/axi4_slave.sv` rechaza toda ráfaga, y en
> esta placa el error de AXI no da SIGBUS sino que **reinicia el sistema**. Ver
> el docstring de `MCA._read_words` y [`patrones_memoria_hw.md`](../patrones_memoria_hw.md).

### 1.5 Guardado

| Función | Formato | Cuándo |
|---|---|---|
| `mca_write_file_histogram(hist, path, meta=None)` | csv con cabecera `# clave: valor` | por defecto; se abre en cualquier lado |
| `mca_save_file_binary(hist, path, meta=None)` | `.npz` | compacto, es lo que usa el resto del árbol |
| `mca_save_file_json(hist, path, meta=None)` | `.json` | legible sin numpy |
| `mca_load_file(path)` | — | relee los tres → `(histograma, metadata)` |

El formato se elige por la extensión al releer, así que **es una decisión de
almacenamiento y no cambia el análisis**. El csv se ve así:

```
# schema_version: 1
# thr: 317
# gate_long: 400
# livetime_s: 10.0
canal,cuentas
0,0
1,3
```

La metadata vuelve tipada (int/float/bool), no como cadenas: sin eso un `thr`
releído del csv no comparaba igual que el que se escribió.

---

### 1.6 El mismo MCA, por red

Código: [`API/mca_net.py`](../../software/API/mca_net.py) (protocolo) y
[`API/mca_remote.py`](../../software/API/mca_remote.py) (handles). La
aplicación que los usa está en [`software/app/`](../../software/app/README.md).

`MCARemote` **hereda de `class MCA`** y sólo redefine `r32`/`w32` y las
lecturas en bloque. Como todas las funciones de arriba acceden al hardware
únicamente a través del handle, **la superficie `mca_*` entera funciona por
socket sin cambiar nada**:

```python
h = MCARemote.connect('10.73.28.27')     # en vez de mca_open()
mca_set_thr(h, 317)                      # todo lo demás, igual
hist = mca_read_histogram(h)
```

| Handle | Qué es |
|---|---|
| `MCARemote.connect(host, port=1001, timeout=10)` | el MCA de la placa, por TCP |
| `FakeMCA(h_aw=14, …)` | un MCA que no existe: fotopico gaussiano que crece con el tiempo vivo, y respeta `amp_min`/`amp_max`. Es a `mca.py` lo que `FakeSource` a `osciloscope_store` |

Extras que sólo tienen sentido por red — `h.status()` (contadores + tasas +
exposición en una vuelta), `h.config()`, `h.metadata()`, `h.fpga_state()` y
`h.load_bitstream(path)`.

> **La exposición la implementa el servidor, no el hardware.** El MCA es
> free-running y no tiene registro de tiempo de medida: `ctrl.start` con
> `seconds` arma un hilo que poléa `livetime_s` y para al llegar. Es la misma
> cuenta que hace `mca_read_acquire`, movida al lado de la placa para que
> sobreviva a que el cliente se desconecte.

> **Refrescar el espectro en vivo cuesta ~0.01 % de los eventos.** La lectura
> del bus tiene prioridad sobre el pipeline del histograma
> (`mca_hist.sv:30-37`) y el evento que colisiona se cuenta en `dropped`, pero
> ocupa el puerto ~2 ciclos cada 6.7 µs. Con un refresco por segundo es
> despreciable, y el contador lo deja verificar en vez de suponerlo.

---

## 2. `API.osciloscope` — osciloscopio clásico

Base `0x4010_0000` (slot 1). Código: [`API/osciloscope.py`](../../software/API/osciloscope.py).

### 2.1 Ciclo de vida y comandos

`osciloscope_open(phys, size, check_pl=True)` · `osciloscope_close(osc)` ·
`osciloscope_reset(osc)` · `osciloscope_sw_trigger(osc)` ·
`osciloscope_wait_triggered(timeout_ms)` · `osciloscope_wait_fill(timeout_ms)`

> `check_pl=True` mira el FPGA manager **antes** de mapear: si la PL no está
> `operating` no hay quién conteste en el bus y la primera lectura mata el
> proceso con SIGBUS. Es barato comprobarlo en vez de perder el kernel.

### 2.2 Configuración

| Campo | Registro ch0 / ch1 | Nota |
|---|---|---|
| `thr` | `0x008` / `0x00C` | en **volts**; escala fija 8192 cuentas/V, sin calibración de EEPROM |
| `delay` | `0x010` / `0x110` | crudo. **Es dead-time real** |
| `decim` | `0x014` / `0x114` | sólo `(1, 8, 64, 1024, 8192, 65536)` |
| `hysteresis` | `0x020` / `0x024` | en volts |
| `avg` | `0x028` | |
| `deb_len` | `0x090` | |
| `filter_bypass` | `0x098` | |
| `calibration` | `0x200`/`0x204`, `0x208`/`0x20C` | offset y ganancia |

Los `set_` aceptan `ch=None` (los dos canales, por defecto) o `ch=0`/`ch=1`.

> **`delay` es dead-time real**: mientras corre, `adc_dly_do` bloquea la
> actualización de `adc_wp_trig` (`rp_bram_sm.v:91`). Para medir dead-time hay
> que dejarlo en el mínimo y subirlo sólo cuando se quiere ventana post-trigger.
> Y **`delay=0` es un caso degenerado**: la FSM trata el contador en 0 como
> "delay completo" antes de ver el trigger, se saltea la espera y **ignora los
> triggers**. Por eso el mínimo efectivo es 1.

### 2.3 Estatus

`osciloscope_get_adc_state` (`0x000`) · `get_trg_state` (`0x004`) ·
`get_wp_cur` (`0x018`/`0x118`) · `get_wp_trig` (`0x01C`/`0x11C`) ·
`get_we_cnt` (`0x02C`/`0x12C`)

### 2.4 Lectura

| Función | Qué hace |
|---|---|
| `osciloscope_read_buffers(osc, n_buf)` | los buffers completos |
| `osciloscope_read_window(osc, channels, pre, post, at_trigger)` | ventana alrededor del trigger |
| `osciloscope_read_events(osc, n, timeout_ms)` | captura `n` eventos |
| `osciloscope_read_capture_sw(osc, thr, delay, timeout_ms)` | captura forzada por SW trigger (no depende de que haya señal) |

### 2.5 Análisis offline de buffers

`events_to_intervals(events)` · `efficiency(observed_n, target_freq_hz, duration_s)` ·
`pulses_from_buffer(d, threshold, hyst)` — no tocan hardware.

---

## 3. `API.multitrigger` — máscaras OR, shield y snapshot

Base `0x4010_0000`, registros `0x210`–`0x24C`. Código:
[`API/multitrigger.py`](../../software/API/multitrigger.py).

### 3.1 Registros

| Constante | Offset | Contenido |
|---|---|---|
| `R_SHIELD_CFG` | `0x210` | `{dur[31:16], dst[11:8], src[3:0]}` |
| `R_SHIELD_RUN` | `0x214` | runtime del shield (R) |
| `R_TRIG_SNAP` | `0x218` | snapshot de 17 b, **sticky** (R) |
| `R_FLAGS` | `0x21C` | `dis_act` / `we_keep` (R) |
| `R_OR_MASK_CH0..CH3` | `0x240`–`0x24C` | máscara OR por canal |

El fichero original no tenía constantes de offset: cada dirección era un literal
hex inline. Nombrarlas es lo que permite que el test de compatibilidad verifique
sus valores en vez de confiar en la vista.

### 3.2 Clase `MultiTrigger`

`MultiTrigger.open(osc=None)` — si se le pasa un `Osciloscope` **reutiliza su
mmap** en vez de abrir otro; son la misma región física.

Métodos: `set_or_mask` · `configure_shield_autorearm` · `disable_shield` ·
`get_or_mask` · `get_shield` · `read_snapshot` · `read_snapshot_raw` ·
`get_flags`.

`decode_snap(s)` da los nombres de las fuentes activas en un snapshot.

### 3.3 Secuencias que cruzan los dos módulos

```python
multitrigger_arm(osc, mt, mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                 thr=0.0, hyst=0.01, delay=0, we_keep_both=True,
                 auto_rearm=True)
multitrigger_disarm(osc, mt)
```

**Reciben los dos handles a propósito**: la secuencia cruza registros de los dos
bloques (histéresis y arm son del osciloscopio, shield y máscara OR del
multitrigger). Con la firma explícita la dependencia se ve; escondida dentro de
una clase sería accidental.

> **ORDEN CRÍTICO: armar ANTES de habilitar la máscara.** Se arma la `bram_sm`
> (`0x00`) y recién después se escribe la OR-mask (`0x240`/`0x244`). Al revés,
> con una señal viva un flanco de ADC puede disparar en la ventana pre-arm:
> engancha `adc_trg_dis` y, en single-shot, auto-limpia `set_trig_src` antes de
> que la máquina esté armada, dejándola esperando un trigger imposible
> (`wp_trig=0` permanente). Detalle completo en
> [`orden_arm_trigger_captura.md`](../multitrigger/orden_arm_trigger_captura.md).
>
> Ese orden lo congela una traza del test de compatibilidad, así que reordenarlo
> falla en la PC en vez de en la placa.

`auto_rearm=True` (por defecto) activa el `trigger_shield` para clear automático
de `adc_trg_dis` y escribe `set_dly` crudo, lo que baja el dead-time del sistema
de ~65 µs a ~µs. Con `auto_rearm=False` el software tiene que pulsar `0x94`
entre triggers.

---

## 4. `API.osciloscope_ring` — event_ring en DDR

Base `0x4020_0000` (slot 2), magic `"EVNT"`. Código:
[`API/osciloscope_ring.py`](../../software/API/osciloscope_ring.py).

`class RingSource` implementa la **misma interfaz** que `BramSource`
(`arm` / `wait_event` / `snapshot` / `read_into` / `rearm` / `close` / `meta`),
así que el lector no distingue una fuente de otra. Añade `hw_counters()`.

> El ring prefetchea en lote: leer un slot suelto de 512 B cuesta ~27 µs, y en
> bloques de 64 KB baja a ~2.3 µs/slot. La ganancia de ~20× **sólo existe
> leyendo en lote**. Y se miran dos cosas — `WR_SLOT` para saber cuántos pedir y
> el footer `{~seq, seq}` para validar cada slot — porque `WR_SLOT` se
> incrementa cuando el footer fue aceptado por el FIFO, no cuando llegó a DDR.

---

## 5. `API.osciloscope_store` — guardado continuo

Código: [`API/osciloscope_store/`](../../software/API/osciloscope_store/).
Arquitectura y números medidos:
[`arquitectura_adquisicion_software.md`](../multitrigger/arquitectura_adquisicion_software.md).

Es el antiguo paquete `mca/`, renombrado por lo que hace. Exporta
`AcquisitionSession`, `ReaderThread`, `ChunkWriter`, `BramSource`, `FakeSource`,
`EventBatch`, `load_chunk`, los anotadores y `scope_regs`.

Es la **API de guardado** del flujo OSC: mientras la API de lectura da una
estructura puntual, ésta hace guardado continuo del flujo de entrada, un `.npz`
por chunk más un `run_summary.json` por corrida.

### Anotadores

Información externa que se *adjunta* a cada evento sin definir cuándo ocurre.
Añaden columnas al esquema del batch, así que el lector, el escritor y el formato
de archivo no se tocan.

| Clase | Qué añade |
|---|---|
| `ConstantAnnotator(**valores)` | valores fijos por corrida |
| `CachedAnnotator` | base para fuentes lentas y asincrónicas (GPS, temperatura), con su `*_age_ns` |
| `DeadTimeAnnotator` | columna `dead_ns`: **el período ocupado del lector**, evento por evento |

`DeadTimeAnnotator` es la medición *directa* del tiempo muerto del camino del
lector, que no tiene contador en hardware como sí lo tiene el MCA. Funciona
porque `sample_into` corre justo después de `rearm()`, así que la diferencia
contra `t_ns` es exactamente el intervalo en que el scope estuvo congelado — la
misma definición que el `deadtime_cnt` del RTL. Expone además `busy_fraction()`
para leer rho en vivo.

> **rho no es la fracción perdida.** Con arribos periódicos se puede estar 28 %
> ocupado y no perder ni un evento. Para la pérdida con fuente Poisson,
> `rho/(1+rho)`; ver
> [`tests/tiempo-muerto/README.md`](../../software/tests/tiempo-muerto/README.md).

---

## 6. `API.analisis` — helpers puros

Código: [`API/analisis.py`](../../software/API/analisis.py). **No tocan
hardware**, así que se prueban contra `.npz` guardados sin la placa.

| Función | Qué da |
|---|---|
| `gauss_fit_peak(spec, lo, hi)` | centroide, sigma, fwhm, área, `resolution_pct` |
| `energy_calibration(centroids, energies)` | recta canal(E) + INL como % de fondo de escala |
| `dnl(spec, lo, hi, smooth)` | no-linealidad diferencial desde un pulser deslizante |
| `fom(map2d, amp_lo, amp_hi)` | figura de mérito de discriminación por forma |
| `deadtime_fit(rate_in, rate_out)` | modelos paralizable y no paralizable, y cuál gana (necesita un **barrido**) |
| `tau_poisson(t_ns, gap)` | de **una corrida**: tau, **tasa incidente**, rho y pérdida — fuente real |
| `tau_periodico(t_ns, gap, T_s)` | de una corrida: `k`, bracket de tau y **pérdida exacta** — Rigol en PULSE |
| `error_cuantizacion(t_ns, gap, T_s)` | verifica que el estímulo sea periódico (~0) o no (0.25) |
| `cv_residuo(t_ns, gap)` | forma de los Δt. **Diagnóstico, no selector** — se equivoca en los bordes |
| `counts_to_volts(bins, h_shift, amp_src, q_shift)` | canal → volts de amplitud de pico |
| `axis_calibration(ref, centroids, ...)` | mapa directo del eje, con chequeo de invertibilidad |
| `apply_calibration(bins, cal)` | corrige números de canal sueltos |
| `linearize_spectrum(spec, cal)` | corrige un espectro entero rebineando por bordes |
| `inl_residual_vs_knots(cal, n_knots)` | INL residual según el tamaño de la LUT del RTL |
| `propagar_calibracion_muestra(ondas, f, estimadores, baseline)` | replica pulsos reales por una corrección por muestra |

**Estas funciones no llevan prefijo de módulo**, y es deliberado: no son
cfg/read/store ni pegan a ningún bloque del bus. El porqué está en
[`decisiones_del_refactor.md`](decisiones_del_refactor.md#4-el-análisis-no-lleva-prefijo).

`counts_to_volts` **rechaza `amp_src=1`** con un `ValueError`: con la integral de
carga el eje ya no es amplitud, y convertirlo a volts daría un número sin
significado físico. Hay que calibrar contra el generador.

### Tiempo muerto en tiempo de corrida

`tau_poisson` y `tau_periodico` **no son variantes del mismo ajuste**: el proceso
de arribos cambia la matemática. La primera determina tau y además la tasa
incidente; la segunda sólo *acota* tau, y a cambio da la pérdida exacta sin pasar
por ningún modelo. Cuál usar se **declara** —`T_s` obligatorio es lo que impide
equivocarse de función por accidente—, y `tau_periodico` se niega con un
`ValueError` si los Δt no están cuantizados.

Las dos filtran por `gap == 0`, y de ahí depende su validez: `gap` cuenta sólo
los descartes por *backpressure*, mientras que las pérdidas por tiempo muerto no
dejan rastro. Los Δt tienen que incluir las segundas y no las primeras.

Miden el camino del **lector de Python**; el MCA ya trae los contadores en
hardware (`mca_read_counters()` → `livetime_s`/`deadtime_s`). La medición directa
complementaria es el `DeadTimeAnnotator` de
[`API.osciloscope_store`](#5-apiosciloscope_store--guardado-continuo). Todo el
detalle y la validación por Monte-Carlo:
[`tests/tiempo-muerto/README.md`](../../software/tests/tiempo-muerto/README.md).

---

## 7. `API.fpga` — bring-up de la PL

Código: [`API/fpga.py`](../../software/API/fpga.py).

`load_bitstream(path, ...)` · `fpga_state()` · `fpga_bridges()` ·
`set_fpga_bridges(enable)` · `pl_probe(phys, off)` · `pl_bus_ready(...)` ·
`fpgautil_bin()`

Esto es de **placa**, no del osciloscopio: vivía en `multitrigger_utils.py` por
accidente histórico —el scope fue lo primero que hubo que arrancar— pero cargar
un bitstream distinto lo usa igual.

> **Reprogramar la PL con mapeos abiertos** produce el `external abort ...
> *pte=40100743` de dmesg y puede dejar el puerto GP0 trabado hasta reiniciar la
> placa. Hay que cerrar los mmap **antes** de cargar.
>
> `pl_probe` hace la lectura en un **proceso hijo**: si el bus no está listo, el
> que muere con SIGBUS es el hijo y nos enteramos por el returncode, en vez de
> perder el kernel de Jupyter.

---

## 8. `API.rigol_dg4162` — generador

Código: [`API/rigol_dg4162.py`](../../software/API/rigol_dg4162.py). Se movió tal
cual, sin partirlo: es el driver de un **instrumento externo**, no un bloque de
la PL, así que no le aplica la nomenclatura de tres capas.

`class RigolDG4162` más los constructores de onda (`detector_pulse`,
`poisson_train_wave`, `sliding_pulser_wave`, …) y la familia de formas de Knoll
(`FORMAS_KNOLL`). Descritos en
[`testbenches_software_mca.md`](../mca/testbenches_software_mca.md).
