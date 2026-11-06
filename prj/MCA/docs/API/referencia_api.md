# Referencia de la API

Todas las funciones públicas por módulo, y **a qué registro pega cada una**. La
nomenclatura de tres capas está en [`README.md`](README.md).

Los mapas de registros completos (con la semántica de cada bit) viven aparte:
[MCA](../mca/register_map_mca.md) · [OSC](../osc/register_map_osc.md) · [multitrigger](../mt/register_map_mt.md) · [event_ring](../event_ring/diseno_y_register_map.md).

---

## 1. `API.mca` — analizador multicanal ("MCA2", las ranuras)

Base `0x4070_0000` (slot 7). Código: [`API/mca.py`](../../software/API/mca.py),
binding de [`libmca`](../../software/libmca/) (C); la referencia Python es
[`API/ref_py/mca2.py`](../../software/API/ref_py/mca2.py). El mapa:
[`register_map_mca.md`](../mca/register_map_mca.md).

> **La ventana la abre el disparo del multitrigger, no el MCA.** Sin
> `multitrigger_armar_mca` (§3.4) no se abre ninguna ventana y el espectro
> queda vacío. El MCA1 (Schmitt interno, histéresis, re-armado) ya no lo habla
> libmca: se abre con `mca_open(impl='py')`, que usa la referencia congelada
> [`API/ref_py/mca.py`](../../software/API/ref_py/mca.py).

### 1.1 Ciclo de vida

| Función | Efecto |
|---|---|
| `mca_open(phys, size, check_magic=True, impl=None)` | mmap de `/dev/mem`, valida el magic `"MCA2"`. Devuelve el **handle** que usan las demás. `impl='py'`: la referencia Python (y la del MCA1 si ése es el bitstream) |
| `mca_close(h)` | cierra mmap y fd |
| `mca_identify(h, verbose=True)` | magic, caps, widths, `n_channels`, `map2d_shape`, `n_acc_max` (ranuras del RTL) y `trap` (CAPS bit 2) |
| `mca_start(h)` / `mca_stop(h)` | bit `run` de `R_CTRL` (`0x00C`) |
| `mca_clear(h, timeout_s=1.0)` | bit `clear` autolimpiante; espera a que baje `clear_busy` |

> `mca_open()` valida el magic porque **en el bitstream del scope el slot 7 es un
> `sys_bus_stub`**, y porque el decodificador del MCA ignora en silencio las
> escrituras a direcciones que no tiene: con el MCA1 cargado, una configuración
> del MCA2 escribiría al vacío. Con el MCA1 el mensaje lo dice.

### 1.2 Configuración — un `get`/`set` por campo

Todos toman el handle: `mca_get_n_acc(h)` / `mca_set_n_acc(h, 4)`.

| Campo | Registro | Bits | Nota |
|---|---|---|---|
| `baseline` | `0x01C` | `[13:0]` | línea de base fija |
| `bl_auto` | `0x020` | `[0]` | seguidor automático de base |
| `bl_k` | `0x020` | `[7:4]` | τ = 2^k muestras — **ver aviso abajo** |
| `bl_holdoff` | `0x020` | `[31:16]` | |
| `amp_min` / `amp_max` | `0x030` / `0x034` | `[15:0]` | ventana de aceptación, **sobre la feature de 16 b** (no en canales: `mca_amplitud_de_canal`) |
| `amp_src` | `0x038` | `[0]` | 0 = muestra de pico, 1 = integral de carga; mueve `sel_1d`/`sel_2dx` |
| `q_shift` | `0x038` | `[12:8]` | escala de la integral |
| `dec` | `0x044` | `[15:0]` | **≥ 1** |
| `gate_short` | `0x04C` | `[15:0]` | muestras desde el disparo hasta la cola |
| `gate_long` | `0x04C` | `[31:16]` | muestras desde el disparo hasta el cierre |
| `channel` | `0x00C` | `[8]` | 0 = IN1, 1 = IN2 |
| `n_acc` | `0x120` | `[2:0]` | ranuras habilitadas, **1..N_ACC** (el RTL satura sin avisar) |
| `pre_dly` | `0x124` | `[6:0]` | retardo de la muestra respecto del disparo, **0..127** ciclos |
| `trap_k` / `trap_m` | `0x128` | `[9:0]` / `[25:16]` | subida (**1..1023**) y meseta del trapecio; escribir reinicia su estado |
| `trap_mq` | `0x12C` | `[19:0]` | M·16, la constante polo-cero; **< 2^20** |
| `trap_off` / `trap_lw` / `trap_sh` | `0x130` | `[15:0]` / `[18:16]` / `[29:24]` | la ventana sobre la meseta y la escala |
| `n_formas` | `0x134` | `[2:0]` | formas del banco en uso, **1..N_FORMAS** (el RTL recorta sin avisar) |
| `trap_antes` / `trap_despues` | `0x188` | `[15:0]` / `[31:16]` | los umbrales de la forma 0 (las otras cosas de esa forma son los `trap_*`) |
| `forma<f>_k` / `_m`, f = 1..3 | `0x180 + 16f` | `[9:0]` / `[25:16]` | subida (**1..1023**) y meseta de la forma f |
| `forma<f>_off` / `_lw` / `_sh` | `0x184 + 16f` | `[15:0]` / `[18:16]` / `[29:24]` | su ventana y su escala |
| `forma<f>_antes` / `_despues` | `0x188 + 16f` | `[15:0]` / `[31:16]` | sus umbrales |
| `sel_1d` / `sel_2dx` / `sel_2dy` | `0x090` | `[3:0]` / `[7:4]` / `[11:8]` | qué feature alimenta cada eje (nombre o índice); `trapecio` sólo con CAPS bit 2, `forma` sólo con el banco |
| `zoom_1d_z` / `_k`, `zoom_2dx_*`, `zoom_2dy_*` | `0x094` / `0x0B8` / `0x0BC` | `[3:0]` / `[15:8]` | el zoom de cada eje; `z` se satura como en el RTL |
| `discr_en` / `discr_ext` / `discr_sel` | `0x098` | `[0]` / `[1]` / `[7:4]` | el discriminador |
| `discr_min` / `discr_max` | `0x09C` / `0x0A0` | `[15:0]` | |
| `keep_if_full` | `0x0A4` | `[0]` | seguir contando con un bin lleno |

Las features son `pico`, `integral`, `psd`, `ancho_inv`, `largo`, `t_subida`,
`dt_anterior`, `dt_siguiente`, `solape`, `trapecio` y `forma` (índices 0..10).

**Varios campos comparten registro** (`bl_*` en `0x020`, `amp_src`/`q_shift` en
`0x038`, las compuertas en `0x04C`, `channel` con `run` en `0x00C`, el trapecio
en `0x128` y `0x130`). Los `set_` hacen **read-modify-write**, así que poner uno
no borra sus vecinos. Lo verifica
[`test_api_mca.py::test_rmw_no_pisa_campos_vecinos`](../../software/API/tests/test_api_mca.py).
Los que validan (`dec`, `n_acc`, `pre_dly`, `trap_k`, `trap_mq`, `n_formas`, los
`forma<f>_k`, los selectores) lanzan `ValueError` antes de escribir.

> **`bl_k` tiene que ser MUCHO más largo que el pulso.** La constante es 2^k
> muestras (8 ns cada una). Si es comparable al pulso, el seguidor lo persigue y
> lo borra. Medido en la placa con un pulso de 62 µs: `bl_k=6` → 0 eventos;
> `bl_k=9,12,15` → los ~2000 esperados. Regla práctica: τ ≥ 100× la duración
> del pulso. Ante la duda, base fija (`bl_auto=False`), que es inmune.

`mca_configure(h, **kw)` escribe **todo el estado**, con la misma firma que
`MCA.configure()`: **valida todo antes de escribir** (una configuración mala no
deja nada escrito), para el MCA primero (`run=0`) y relee seis campos (más
`trap_k` con el trapecio y `n_formas` con el banco). Los defaults son el reset
del RTL salvo `bl_k=12`, `keep_if_full=True` y `pre_dly=16` (lo medido con el
pulso de la campaña). Los registros del trapecio se escriben siempre: en un
bitstream sin él no existen y la escritura no hace nada. Los del banco se
escriben sólo si `0x134` dice que está.

**El banco entra en `configure`, con los mismos nombres que `mca_get_config`.**
Sin pasarlo queda el reset del RTL, el MCA de un solo trapecio: lo que dejó una
corrida anterior no se filtra en la siguiente, y `trap_mq` vuelve a 0. Va ahí y no
en una función aparte porque su validez depende de la compuerta. `configure`
rechaza lo que el RTL haría en silencio:

- `n_formas` fuera de 1..`N_FORMAS`, un `k` en 0, `k + m` > 1023;
- una ventana que no entra en la compuerta (`off + 8 + 2^lw > gate_long`: ninguna
  ranura la completa y `F_TRAP` vale cero). Se exige si alguien la usa: más de una
  forma, o un eje o el discriminador en `trapecio` o `forma`;
- un `despues > gate_long`: `F_DTNEXT` no vería al vecino;
- **una forma con otra ganancia que la 0** (`k / 2^sh` distinto): el pico se
  partiría en dos. Por la fórmula, `k = 48` queda al 75 % de `k = 64`.

Los setters sueltos no pueden mirar todo eso; para eso están los avisos de §1.3.

La cuenta de los registros no hay que hacerla a mano:

```python
mca_configure(h, n_acc=4, sel_1d='trapecio', **mca_banco_config(mq))
```

`mca_banco_config(mq, pre_dly=16, formas=BANCO_PZ, gate_long=None, altura=8.0)` es
una función pura que devuelve esos argumentos: `off = c + pre_dly + 2`, `sh` por la
altura pedida, y la compuerta más corta que las contiene (112 con el banco de la
campaña). Trae `pre_dly` y `gate_long`, así no se pueden pasar otros. Para armar
también el disparo, con el mismo `mq`: `multitrigger_armar_banco` (§3.4).

> **`mq` y la base deciden el resultado, y ninguno da error.** Medido en la placa a 1 Mcps
> ([`pruebas_banco_trapecios.md`](../mca/pruebas_banco_trapecios.md) §6): con M ajustado para
> un par a 1 µs los buenos bajan de 665 a 514 k/s, porque la cola real no es una sola
> exponencial; hay que ajustarlo con un tren a la tasa de trabajo. Y la base va fija
> (`baseline=<mediana con pocos pulsos>`): sin configurarla cada forma queda corrida distinto,
> y con el seguidor (`bl_auto`) los buenos caen a 7 k/s, porque a tasa alta no le queda dónde
> medir.

> **`pre_dly` mueve las ventanas del trapecio.** Cambiarlo solo las corre, y
> `trap_ok` no lo nota: mira que entren en la compuerta, no que caigan sobre la
> meseta. La GUI lo avisa si alguien está mirando el trapecio.

### 1.3 Estatus (sólo lectura)

| Función | Registro |
|---|---|
| `mca_get_status(h)` | `0x010` crudo |
| `mca_get_running(h)` | `0x00C[0]` |
| `mca_get_clear_busy(h)` / `mca_get_busy(h)` | `0x010[0]` / `[1]` (alguna ranura ocupada) |
| `mca_get_baseline_stale(h)` / `mca_get_vetoed(h)` | `0x010[2]` / `[3]` |
| `mca_get_puede_abrir(h)` | `0x010[5]`: hay alguna ranura libre |
| `mca_get_n_ocup(h)` | `0x010[10:8]`: ranuras ocupadas ahora |
| `mca_get_n_acc_max(h)` | `0x11C`: ranuras con que se sintetizó |
| `mca_get_trap_ok(h)` | `0x130[31]`: la ventana de la forma 0 entra en la compuerta |
| `mca_get_n_formas_max(h)` | `0x134[10:8]`: `N_FORMAS` del bitstream, 0 sin banco. También en `mca_identify` |
| `mca_get_umbr_ok(h)` | `0x134[31]`: los `despues` de las formas en uso entran en la compuerta |
| `mca_get_formas_ok(h)` | el bit 31 de cada `FORMA_MED`: lista de bools, **sólo de las formas en uso** |
| `mca_get_baseline_now(h)` | `0x024`, con extensión de signo a 14 bits |
| `mca_get_caps(h)` / `mca_get_widths(h)` | `0x004` / `0x008` → `{h_aw, h2_aw, psd_aw}` |
| `mca_get_config(h)` | los 59 campos de arriba, releídos del hardware |
| `mca_get_metadata(h)` | config + contadores + geometría + sello de tiempo, con `mapa`, `api_impl` y `schema_version` 2 |

### 1.4 Lectura

| Función | Devuelve |
|---|---|
| `mca_read_histogram(h)` | `uint32[2**h_aw]` — espectro 1D |
| `mca_read_map2d(h)` | `uint32[2**h2_aw, 2**psd_aw]` — el par de features del mapa |
| `mca_read_counters(h)` | dict con eventos, relojes, `t_ocup_s` (lista de N_ACC + 1), período muerto, atribución de disparos, cola de publicación y estado: ver el docstring de `counters()` |
| `mca_read_last_event(h)` | dict: `amp`, `psd`, `q_tot`, `q_tail`, `baseline` |
| `mca_read_acquire(h, seconds, clear_first=True)` | `(hist, map2d\|None, counters)`; después de parar espera a que se vacíen las ranuras |
| `mca_read_acquire_chunks(h, seconds, chunk_s, on_chunk=None)` | acumula en el mismo histograma, llamando a `on_chunk` por rebanada |

> **Los relojes cambiaron de significado respecto del MCA1.** `deadtime_real_s
> = t_win + t_div` es el tiempo muerto (sin ranura libre); `deadtime_s` es la
> **ocupación** (alguna ranura ocupada), que con varias ranuras no es tiempo
> muerto. `t_ocup_s[j]` es el tiempo con exactamente j ranuras ocupadas.

> **Un espectro de 8192 canales tarda ~1.9 ms en C** (~34 ms en Python): se lee
> palabra a palabra a propósito, porque `rtl/axi4_slave.sv` rechaza toda ráfaga
> y en esta placa el error de AXI **reinicia el sistema**. Ver
> [`diseno_de_clases.md`](diseno_de_clases.md) §9.4.

### 1.5 Guardado

| Función | Formato | Cuándo |
|---|---|---|
| `mca_write_file_histogram(hist, path, meta=None)` | csv con cabecera `# clave: valor` | por defecto; se abre en cualquier lado |
| `mca_save_file_binary(hist, path, meta=None)` | `.npz` | compacto, es lo que usa el resto del árbol |
| `mca_save_file_json(hist, path, meta=None)` | `.json` | legible sin numpy |
| `mca_save_file_n42(hist, path, meta, detector=None, calibracion=None, clase=None, instrumento=None)` | `.n42`, ANSI N42.42-2011 | para abrirlo con otros programas de espectroscopía; sólo el espectro 1D |
| `mca_load_file(path)` | — | relee los cuatro → `(histograma, metadata)`; con `.n42` también lee archivos ajenos |

El formato se elige por la extensión al releer, así que **es una decisión de
almacenamiento y no cambia el análisis**. El csv se ve así:

```
# schema_version: 2
# n_acc: 4
# gate_long: 400
# livetime_s: 10.0
canal,cuentas
0,0
1,3
```

La metadata vuelve tipada (int/float/bool), no como cadenas: sin eso un campo
releído del csv no comparaba igual que el que se escribió.

---

### 1.6 El mismo MCA, por red
Código: [`API/mca_net.py`](../../software/API/mca_net.py) (protocolo) y
[`API/mca_remote.py`](../../software/API/mca_remote.py) (handles). La
aplicación que los usa está en [`software/app/`](../../software/app/README.md).

`MCARemote` es un handle del MCA cuyo acceso sale por el socket: **la
superficie `mca_*` entera funciona por red sin cambiar nada**:

```python
h = MCARemote.connect('10.73.28.27')     # en vez de mca_open()
mca_set_n_acc(h, 4)                      # todo lo demás, igual
hist = mca_read_histogram(h)
```

| Handle | Qué es |
|---|---|
| `MCARemote.connect(host, port=1001, timeout=10)` | el MCA de la placa, por TCP |
| `FakeMCA(h_aw=14, …, trap=False)` | un MCA2 que no existe: fotopico gaussiano que crece con el tiempo vivo, y respeta `amp_min`/`amp_max` y el zoom. Corre la lógica de C contra su modelo de registros. Es a `mca.py` lo que `FakeSource` a `osciloscope_store` |

Extras que sólo tienen sentido por red — `h.status()` (contadores + tasas + exposición en una vuelta), `h.config()`, `h.metadata()`, `h.fpga_state()` y `h.load_bitstream(path)`.

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

`osciloscope_open` va con `size=None`, que **mide** el mapeo en vez de suponerlo:
mapea una página, lee el `CAPS` del mapa canónico y re-mapea con lo que haga
falta. `Osciloscope.open()` conserva el default histórico de `0x30000` por
compatibilidad, y con 4 canales ese valor deja afuera dos aperturas.

### 2.1.1 La geometría, y el alias que no avisa

Dos parámetros de síntesis la fijan y los dos varían entre bitstreams: `RSZ`
(profundidad del anillo, `n_buf = 2^RSZ`) y `N_CH` (canales construidos).
`Osciloscope.geometria()` los lee del `CAPS` de `osc_cfg` (`0x01004`) y devuelve
`{rsz, n_ch, dw, n_buf, aperturas, size, descubierta}`; `osc.n_buf` es el atajo.

**Por qué no puede ser una constante.** Las aperturas de BRAM las decodifica
`sys_addr[19:16]`, o sea 64 KB por canal sea cual sea `RSZ`; el puntero de
lectura es `sys_addr[RSZ+1:2]`. Con `RSZ < 14` sobra apertura y la mitad alta es
**un espejo de la baja**. Consecuencias, las dos silenciosas:

- pedir 16384 muestras a un bitstream de `RSZ=13` devuelve **el anillo dos
  veces**, con ack normal y sin error;
- el `% 16384` de la aritmética de ventanas **tampoco falla**, porque 2¹⁴ = 2·2¹³
  y el alias cancela el módulo de más.

No hay excepción que sustituya al límite: por eso `capture_window_np` toma
`n_buf` y rechaza `pre+post` mayor que el anillo real, y el servidor publica el
`n_buf` del scope y no el del módulo.

`geometria()` falla **abierta**, igual que la guarda de variante de §7: un
bitstream anterior al refactor no trae el mapa canónico, y ahí devuelve los
valores por defecto con `descubierta=False` en vez de negarse a operar.

> La copia de `RSZ`/`DW`/`N_CH` que publica `integration_cfg` en su `CAPS_0`
> **no** es la buena. Esa región ya se desincronizó con `H_AW` porque cada top
> escribía los literales dos veces; ésta la imprime el mismo parámetro que
> dimensiona la BRAM. En los tops las dos salen ahora de un `localparam` único.

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
| `osciloscope_read_buffers(osc, n_buf=None)` | los buffers completos; `None` = el anillo del bitstream |
| `osciloscope_read_window(osc, channels, pre, post=None, at_trigger)` | ventana alrededor del trigger; rechaza `pre+post` mayor que el anillo |
| `osciloscope_read_events(osc, n, timeout_ms)` | captura `n` eventos |
| `osciloscope_read_capture_sw(osc, thr, delay, timeout_ms)` | captura forzada por SW trigger (no depende de que haya señal) |

### 2.5 Análisis offline de buffers

`events_to_intervals(events)` · `efficiency(observed_n, target_freq_hz, duration_s)` ·
`pulses_from_buffer(d, threshold, hyst)` — no tocan hardware.

---

## 3. `API.multitrigger` — máscaras OR, shield y snapshot

Base `0x4030_0000` (slot 3 en el top del MCA). Código:
[`../../software/API/multitrigger.py`](../../software/API/multitrigger.py).

### 3.1 Registros

| Constante | Offset | Contenido |
|---|---|---|
| `R_SHIELD_CFG` | `0x010` | `{dur[31:16], dst[12:8], src[6:0]}` |
| `R_SHIELD_RUN` | `0x014` | runtime del shield (R) |
| `R_TRIG_SNAP` | `0x018` | snapshot de 29 b, **sticky** (R) |
| `R_FLAGS` | `0x01C` | `dis_act` / `we_keep` (R) |
| `R_OR_MASK_CH0..CH3` | `0x040`–`0x04C` | máscara OR por canal |

Antes vivían 0x200 más arriba, en el slot 1: ese espejo ya no existe, y lo que se
escribía ahí se perdía sin error. El mapa completo está en
[`../mt/register_map_mt.md`](../mt/register_map_mt.md).

### 3.2 Clase `MultiTrigger`

`MultiTrigger.open(osc=None, phys=MTRG_PHYS, size=MTRG_SIZE, check_magic=True)` abre
la región y comprueba el MAGIC: un bitstream sin ella falla acá. `osc` se acepta y no
se usa. `phys` es para otro top: `Integration.base('mtrg')` da la base real.
`Osciloscope.mt` da un handle ya abierto.

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
> (`0x00`) y recién después se escribe la OR-mask. Al revés,
> con una señal viva un flanco de ADC puede disparar en la ventana pre-arm:
> engancha `adc_trg_dis` y, en single-shot, auto-limpia `set_trig_src` antes de
> que la máquina esté armada, dejándola esperando un trigger imposible
> (`wp_trig=0` permanente). Detalle completo en
> [`orden_arm_trigger_captura.md`](../osc/orden_arm_trigger_captura.md).
>
> Ese orden lo congela una traza del test de compatibilidad, así que reordenarlo
> falla en la PC en vez de en la placa.

`auto_rearm=True` (por defecto) activa el `trigger_shield` para clear automático
de `adc_trg_dis` y escribe `set_dly` crudo, lo que baja el dead-time del sistema
de ~65 µs a ~µs. Con `auto_rearm=False` el software tiene que pulsar `0x94`
entre triggers.

### 3.4 El disparo del MCA2

```python
mtr = MtRegion.open()                                    # región propia, slot 3
multitrigger_armar_mca(osc, mtr, ch=0, L=8, G=4, thr=600, hyst=300,
                       fuente='pendiente', mq=3992, k=2, m=1, sh=10,
                       thr_cuentas=50.0, hyst_cuentas=25.0)
multitrigger_disparo_mca(mtr, ch=0)                      # estado, para mostrarlo
multitrigger_desarmar_mca(osc, mtr, ch=0)                # apaga las dos fuentes

multitrigger_armar_banco(h, osc, mtr, mq, ch=0, pre_dly=16, n_acc=4, **config)
```

En el MCA2 la ventana la abre **sólo** el disparo del multitrigger. Esto lo
arma en modo continuo: el disparo por pendiente del canal (`MtRegion.set_slope`),
el shield con fuente y destino en el canal (`dur = 0`, re-arma solo), `we_keep`
en el scope y, **después del arm**, el bit `slope_p<ch>` en la máscara de la
región propia. Comprueba
que `we_keep` quedó puesto. `thr` y `hyst` están en unidades de la pendiente s
(para un escalón de alto A, s = L·A; ver `slope_pico`); los defaults son los
medidos en la placa con el pulso de la campaña.

Es la secuencia de `test_mca2_placa.py` (`Pendiente.armar`), validada en la
placa, y [`test_disparo_mca.py`](../../software/API/tests/test_disparo_mca.py)
exige que sea la misma escritura por escritura. Por red: la op `mca.disparo`.

**`fuente='pz'`** arma el disparo con polo-cero, el del banco de trapecios
([`../mt/disparo_polo_cero.md`](../mt/disparo_polo_cero.md)): `mq` es la constante
polo-cero, `k`, `m` y `sh` la forma, y el umbral y el re-armado van en cuentas de
amplitud (`thr_cuentas`, `hyst_cuentas`). Todavía sin probar en la placa.

**`mq` está dos veces en el hardware**, en el MCA y en el disparo, y tiene que ser
la misma. `multitrigger_armar_banco` configura el MCA con `mca_banco_config` (§1.2)
y arma el disparo con el mismo valor; no tiene default, porque es la del ajuste de
la cola en la placa, no la nominal.

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
[`arquitectura_adquisicion_software.md`](arquitectura_adquisicion_software.md).

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
> [`../docs/mca/tiempo_muerto.md`](../../software/../docs/mca/tiempo_muerto.md).

---

## 6. `API.analisis` — helpers puros

Código: [`API/analisis.py`](../../software/API/analisis.py). **No tocan
hardware**, así que se prueban contra `.npz` guardados sin la placa.

| Función | Qué da |
|---|---|
| `gauss_fit_peak(spec, lo, hi)` | centroide, sigma, fwhm, área, `resolution_pct` de **una región dada** |
| `buscar_picos(spec, ...)` | **todos** los picos del espectro: canal, `fwhm`, `resolucion_pct`, área, `truncado` |
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
[`../docs/mca/tiempo_muerto.md`](../../software/../docs/mca/tiempo_muerto.md).

---

## 7. `API.fpga` — bring-up de la PL

Código: [`API/fpga.py`](../../software/API/fpga.py).

`load_bitstream(path, ...)` · `fpga_state()` · `fpga_bridges()` ·
`set_fpga_bridges(enable)` · `pl_probe(phys, off)` · `pl_bus_ready(...)` ·
`fpgautil_bin()`

Y la guarda de variante: `modelo_de_placa()` · `parte_del_bitstream(bit)` ·
`parte_declarada(bit_bin)` · `bitstream_compatible(parte, modelo)` ·
la tabla `PARTE_POR_MODELO`.

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

### La guarda de variante

`load_bitstream` comprueba, **antes de escribir nada**, que el bitstream sea
para el Zynq de esta placa, y aborta si no. Cargar uno de otro Zynq no falla y
ya: el IDCODE no coincide, el FPGA manager devuelve `-ETIMEDOUT` y **queda
trabado**, con lo que toda programación posterior falla —incluida la de
fábrica— hasta reiniciar.

Tres detalles que hacen falta para entender la implementación:

- **La parte está en el `.bit`, no en el `.bit.bin`.** `bootgen` le quita la
  cabecera al generar el binario, que es justo el que se carga. `parte_declarada`
  la busca en el `.bit` hermano (árbol de desarrollo) y, si no, en el `VERSION`
  del paquete instalado, donde `make release` la dejó escrita.
- **`monitor -f` necesita root** y, sin permiso sobre la EEPROM, imprime
  `undefined` **con código de salida 0**. Mirar sólo el returncode haría que
  "undefined" pasara por el nombre de un modelo.
- **Falla abierta.** Si falta la parte, falta el modelo, o el modelo no está en
  la tabla, **deja pasar y lo dice**. El riesgo es asimétrico: bloquear un
  bitstream válido en una placa que la tabla no conoce sería peor, y el caso que
  importa —dos partes conocidas que no coinciden— se detecta igual.

---

## 8. `API.rigol_dg4162` — generador

Código: [`API/rigol_dg4162.py`](../../software/API/rigol_dg4162.py). Se movió tal
cual, sin partirlo: es el driver de un **instrumento externo**, no un bloque de
la PL, así que no le aplica la nomenclatura de tres capas.

`class RigolDG4162` más los constructores de onda (`detector_pulse`,
`poisson_train_wave`, `sliding_pulser_wave`, …) y la familia de formas de Knoll
(`FORMAS_KNOLL`). Descritos en
[`testbenches_software_mca.md`](../mca/testbenches_software_mca.md).
