# Referencia de la API

Todas las funciones públicas por módulo, y **a qué registro pega cada una**. La
nomenclatura de tres capas está en [`README.md`](README.md).

Los mapas de registros completos (con la semántica de cada bit) viven aparte:
[MCA](../mca/register_map_mca.md) · [OSC](../osc/register_map_osc.md) · [multitrigger](../mt/register_map_mt.md) · [event_ring](../event_ring/diseno_y_register_map.md) · [TOP](../TOP/register_map_top.md).

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
> = t_win + t_div + t_rearm` es el tiempo muerto: sin ranura libre, o con
> ranura libre pero el disparo del multitrigger esperando re-armar (`t_rearm_s`,
> desde libmca 0.11.0; `rearm_pend` es ese estado ahora). `deadtime_s` es la
> **ocupación** (alguna ranura ocupada), que con varias ranuras no es tiempo
> muerto. `t_ocup_s[j]` es el tiempo con exactamente j ranuras ocupadas. El
> período muerto (`dead_*`) es sólo el del MCA, `t_win + t_div`.

> **Un espectro de 8192 canales tarda ~1.9 ms en C** (~34 ms en Python): se lee
> palabra a palabra a propósito, porque `rtl/axi4_slave.sv` rechaza toda ráfaga
> y en esta placa el error de AXI **reinicia el sistema**. Ver
> [`libmca.md`](libmca.md) §6.2.

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

**El event_ring por red** (las ops `ring.*`, [`protocolo.md`](../APP/protocolo.md)): una
adquisición que corre en la placa y escribe en un camino de la placa. La forma de que los
archivos lleguen a la PC es que ese camino sea un directorio de la PC montado por NFS.

| Método | Qué hace |
|---|---|
| `h.has_ring`, `h.has_gen` | si el bitstream de la placa trae el ring y su generador |
| `h.ring_iniciar(run_dir, **kw)` | arranca una `AdquisicionRing` en la placa, con sus argumentos. Devuelve `run_dir`, `fs`, `n_slots` y `pool` |
| `h.ring_estado()` | `corriendo`, `motivo`, `stats`, `hw` y `error`, sin frenarla |
| `h.ring_parar()` | la para; devuelve `stats`, `hw_final`, `n_slots` y `error` |

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

Base `0x4010_0000` (slot 1). Código: [`API/osciloscope.py`](../../software/API/osciloscope.py),
sobre [`libmca/include/osciloscope.h`](../../software/libmca/include/osciloscope.h).
`open(..., impl='py')` abre la referencia (`API/ref_py/osciloscope2.py`), y si libmca no
carga se cae a ella avisando.

### 2.1 Ciclo de vida y comandos

`osciloscope_open(phys, size, check_pl=True, impl=None)` · `osciloscope_close(osc)` ·
`osciloscope_reset(osc)` · `osciloscope_sw_trigger(osc)` ·
`osciloscope_wait_triggered(osc, timeout_ms)` · `osciloscope_wait_fill(osc, timeout_ms)`

> Las esperas reciben el `osc` desde la Parte 6: miran los bits 2 (`adc_trg_rd`) y 4
> (`adc_dly_end`) de `0x000` del canal 0, que es lo que leía librp. Antes eran estáticas
> y llamaban a `rp`.

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

Los `set_` aceptan `ch=None` (los dos canales, por defecto) o `ch=0`/`ch=1`. Otro canal
es un `ValueError`, sin escribir nada.

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
| `osciloscope_read_bram(osc, ch, start, n)` | `n` muestras de la BRAM desde `start`, en un `np.int16`: cuentas con signo y **sin calibrar**, de a una palabra. La ventana da la vuelta al anillo y `wp - pre` se puede pasar tal cual. Más que el anillo es un `ValueError`. Sólo en C |
| `osciloscope_read_cal(osc, ch, start, n, cal)` | lo mismo, **calibrado** con la cuenta de librp: `cal` es `{'gain', 'base', 'offset'}`. En LV, la cuenta sobre 8192 es el volt de `rp_AcqGetDataPosV`. Sólo en C |
| `osciloscope_calibrar(cal, crudo, dw=14)` | la cuenta de librp sobre palabras crudas, sin hardware |
| `calibracion_adc(canales=(0, 1))` | la calibración de cada canal, leída de la EEPROM por `rp_hw_calib` (LV, DC). Si no se puede leer, `RuntimeError`; con HV pedido a librp, `ValueError` |

Desde la Parte 6, `read_buffers`, `read_window` (`capture_window_np`) y `read_events`
(`capture_n_events`) leen por libmca, no por `librp`: los volts son la cuenta calibrada
sobre 8192, los mismos que daba librp. La calibración la guarda cada handle
(`osc.calibracion(ch)`, que la lee la primera vez; `osc.set_calibracion(...)` la fija a
mano, para los tests y los simuladores). `rp_Init()` ya no hace falta para leer.

### 2.4.1 El lazo por evento

`Lector(osc, mt, pre, post, n_ch, mascara, cal, wp_off, single_shot, rearmar,
leer_snap)` envuelve `osciloscope_leer_lote`: `iniciar()` después de armar, y
`leer(cols, i0, n_max, plazo_ns)` llena las columnas (`wave`, `t_ns`, `wp`, `snap`, `gap`,
`dead_ns`, las que estén) desde la fila `i0` hasta `n_max` eventos o el plazo, en el
reloj de `time.perf_counter_ns`. Con `cols=None` descarta y re-arma. Devuelve
`(guardados, descartados, asignados)`, y `pendientes` son los descartados que todavía no
fueron a un `gap`. Lo usan `BramSource.read_batch` y `capture_n_events`; el contrato
de C está en [`osciloscope_lote.h`](../../software/libmca/include/osciloscope_lote.h).

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

`MultiTrigger.open(osc=None, phys=MTRG_PHYS, size=MTRG_SIZE, check_magic=True,
impl=None)` abre la región y comprueba el MAGIC: un bitstream sin ella falla acá. `osc`
se acepta y no se usa. `phys` es para otro top: `Integration.base('mtrg')` da la base
real. `impl` es como en `mca_open`: `'c'` (libmca) o `'py'` (la referencia), y si libmca
no carga se cae a Python avisando. `Osciloscope.mt` da un handle ya abierto.

Los métodos son las funciones de
[`libmca/include/multitrigger.h`](../../software/libmca/include/multitrigger.h). Un
canal fuera de 0..3 da `ValueError` y no escribe nada.

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

Base `0x4020_0000` (slot 2), magic `"EVNT"`, y una región reservada de DDR donde el
ring escribe un slot por evento. Código:
[`API/osciloscope_ring.py`](../../software/API/osciloscope_ring.py), sobre
[`libmca/include/osciloscope_ring.h`](../../software/libmca/include/osciloscope_ring.h).
Necesita el bitstream del ring (`make bitstream-event-ring`); la prueba es
`make verificar-placa-ring`, que pasa con los bitstreams del 2026-11-09 (e58f7888 y
78e26188).

```python
from API.osciloscope_ring import OsciloscopeRing, RingSource

src = RingSource(MultiTriggerScope.open(), pre=8, post=24)   # abre el ring al armar
ses = AcquisitionSession(src, run_dir)
```

| Qué | Para qué |
|---|---|
| `region_ddr()` | `(phys, size)` de la región: `$RING_DDR` (`"0xADDR:SIZE"`) o la del device tree (`labuf@a000000`, 32 MB) |
| `geometria(pre, post, n_ch=2, slot_shift=None, ring_bytes=None, ddr_size=0)` | la geometría de una ventana sin tocar el hardware, o `ValueError` con el motivo del RTL |
| `registros()` | `{nombre: offset}`, como lo exporta libmca |
| `OsciloscopeRing.open(phys, size, ddr=None, check_magic=True)` | el handle: registros y DDR. `RingNotPresent` sin el ring |
| `OsciloscopeRing.sobre(bus, mem)` | sobre un `Bus` y una `Mem` de `API._libmca`: los tests |
| `.r32`, `.w32`, `.ddr`, `.correr()`, `.parar(timeout_s)`, `.contadores()` | acceso crudo, la región, y el control |
| `LectorRing(ring, pre, post, n_ch, cal, …)` | el lazo por lote: `.configurar()`, `.leer(cols, i0, n_max, plazo_ns)`, `.pendientes` |
| `.medir(modo, plazo_ns, n_max, disparos=None)`, `.medida` | consume sin entregar, para medir la tasa: `'creditos'`, `'copia'` o `'verificar'` (`MEDIR_*`), con lo medido acumulado hasta `configurar`. Los campos y qué verifica: [`generador.md`](../event_ring/generador.md) §6 |
| `RingSource(scope, ring=None, pre, post, n_ch, thr, hyst, mask, slot_shift, ring_bytes, calib, generador=None)` | la fuente de eventos, por lote. Con `generador` (un dict de `disparos`), los disparos salen del generador del ring y cada slot trae el patrón: el scope no se toca y puede ser None. `hw_counters()` suma `hw_gen_cnt` y `hw_gen_terminado`, y `meta()['hw_final']` son los contadores de después de parar, con `hw_gen_cortado` si se paró antes de llegar a N. `detener()` corta el estímulo con el ring corriendo (con el generador, N ← 1; con el ADC, la máscara OR en 0), y `vaciado()` dice si no quedó nada en vuelo ni sin leer: los usa `AcquisitionSession.stop()` antes de parar el lector. Si al cerrar el ring no para (lleno y sin créditos), lo destraba: `.destrabe` y `hw_destrabe` dicen cómo |
| `destrabar(ring, lector)` | para un ring que `parar` no pudo parar. Devuelve `'creditos'` (devolvió los créditos), `'parado'` (ya había parado) o `'clr'` (`CTRL ← 0x2`: **borra los contadores**) |
| `AdquisicionRing(ring, run_dir, pre, post, n_ch, slot_shift, generador=None, disparo=None, osc=None, mt=None, calib=None, formato, capacity, ram_mb, margen_mb, meta)` | una adquisición entera: `RingSource` y `AcquisitionSession`, con argumentos que viajan en JSON. El estímulo es `generador` o `disparo` (`{thr, hyst, mask}`, con `osc` y `mt`). `run_dir` es absoluto y su padre tiene que existir. `.iniciar()` → `run_dir`, `fs` (el tipo del sistema de archivos), `n_slots`, `pool`; `.estado()` sin bloquear; `.parar()`, idempotente, vacía el ring antes de pararlo y dice en `error` si no pudo. Es lo que corre el servidor con las ops `ring.*` |

`RingSource` cumple la interfaz `EventSource` por lote (`arm` / `read_batch` /
`pending` / `close` / `meta`), como `BramSource`: el lector no distingue una de otra.
Añade `hw_counters()`, y `meta()['hw_final']` trae los contadores del hardware al
cerrar.

- **`wave`** son cuentas calibradas (int16), las de la BRAM. `calib=None` las lee de la
  EEPROM al armar.
- **Las columnas propias:** `ts_hw` (ciclos de 8 ns desde que arrancó el ring) y `seq`.
  `snap` sale de la cabecera del mismo slot. `wp` es -1 y `dead_ns` 0.
- **`gap` es por bloque.** Los descartes los cuenta el hardware (`DROP_BUSY`, PL
  ocupado; `DROP_FULL`, el PS no consumió) y van al primer evento leído después; el
  total es exacto.
- **Sin batch libre no se consume:** los eventos esperan en la DDR y, si el ring se
  llena, el hardware los descarta y los cuenta.
- **`n_ch=1`** entrega sólo IN1, pero el RTL escribe los dos canales: el slot no se
  achica.

> El ring se lee por bloque: leer un slot suelto de 512 B costaba ~27 µs desde Python,
> y en bloques de 64 KB, ~2.3 µs/slot. `WR_SLOT` dice cuántos slots pedir, y el footer
> `{~seq, seq}` valida cada uno, **antes** de leer sus datos: `WR_SLOT` se incrementa
> cuando el footer fue aceptado por el FIFO, no cuando llegó a DDR. El crédito
> (`RD_SLOT`) se devuelve una vez por bloque.

La región de DDR es `API._libmca.Mem` (`mca_mem*`): `Mem.devmem(phys, size)`,
`Mem.archivo(path, phys, size)`, `Mem.sobre(arreglo, phys)` y `Mem.callbacks(leer,
size, escribir=None, phys=0)`, con `.read(off, n)` y `.write(off, datos)` en palabras
de 64 b.

### 4.1 El generador de eventos

Lo trae el bitstream del ring desde 78e26188 (`EN_GEN = 1`): adentro del ring,
reemplaza los disparos del multitrigger por los del motor de disparos y el dato por un
patrón que se verifica en forma absoluta. Qué genera y por qué:
[`docs/event_ring/generador.md`](../event_ring/generador.md). Registros `R_GEN_*`, desde
`0x100`.

| Qué | Para qué |
|---|---|
| `.gen_presente()` | `True` si el ring tiene el generador (`GEN_MAGIC` `"GEN1"`) |
| `.gen_configurar(disparos=None, patron=False)` | con el ring parado (`ValueError` si no): los disparos (un dict de `API.generadores.disparos`; `None` deja los del multitrigger) y el patrón. Lo deja prendido: corre cuando corra el ring. `LibMCAError` (`MCA_ENOSYS`) si el bitstream no lo tiene |
| `.gen_apagar()` | el ring vuelve a los disparos y al dato del scope |
| `.gen_estado()` | `{gen_cnt, estado, generando, terminado, desborde}`. Después de parar, `ev_cnt + drop_busy + drop_full == gen_cnt` |
| `patron_gen(ts, pre, muestras)` | la ventana que tiene que haber en un slot de marca `ts` (int16, como la entrega `LectorRing` con la calibración identidad); con un arreglo de marcas, todas. Con `ts < pre`, las primeras `pre − ts` muestras no son ésas sino lo que quedó en el buffer de pre-trigger ([logica_de_captura_y_axi.md §2.3](../event_ring/logica_de_captura_y_axi.md#23-una-sola-memoria-para-el-pre-y-el-post)) |

La marca de cada slot generado es `predecir(n_ciclos, GEN_LAT_TS, **disparos)[k]`, con
`k` el índice del snapshot (`{1, k[15:0]}`, `GEN_SNAP_MARCA`). La prueba en la placa es
la parte C de `make verificar-placa-generadores`.

---

## 5. `API.osciloscope_store` — guardado continuo

Código: [`API/osciloscope_store/`](../../software/API/osciloscope_store/).
Arquitectura y números medidos:
[`arquitectura_adquisicion_software.md`](arquitectura_adquisicion_software.md).

Es el antiguo paquete `mca/`, renombrado por lo que hace. Exporta
`AcquisitionSession`, `ReaderThread`, `ChunkWriter`, `BramSource`, `FakeSource`,
`EventBatch`, `load_chunk`, los anotadores y `scope_regs`.

Es la **API de guardado** del flujo OSC: mientras la API de lectura da una
estructura puntual, ésta hace guardado continuo del flujo de entrada, un archivo
por chunk más un `run_summary.json` por corrida. El archivo es `.npz`, o `.lh5` con
`AcquisitionSession(..., formato='lh5')`, que necesita `h5py`. `load_chunk(path)` lee
los dos, y `archivos_de_corrida(dir)` los encuentra.

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

---

## 9. `API.integration` — región de TOP

Código: [`API/integration.py`](../../software/API/integration.py), sobre
[`libmca/include/integration.h`](../../software/libmca/include/integration.h). Slot 6,
base `0x4060_0000`. Dice qué bitstream está cargado, qué módulos trae, en qué slot vive
cada uno y de dónde toma sus muestras cada consumidor de la cadena DSP.

Que falte no es fatal: un bitstream anterior al refactor de registros no la trae, y los
demás bloques andan igual con sus bases por defecto.

| Función | Registro | Qué hace |
|---|---|---|
| `integration_open(phys, size, check_magic, impl=None)` | `MAGIC` | el handle. `IntegrationNotPresent` si el magic no es `"INTG"`. `impl` como en `mca_open` |
| `integration_close(ig)` | — | |
| `integration_identify(ig, verbose=True)` | `MAGIC`, `VERSION`, `GITH_*` | `{magic, version, gith}` |
| `integration_get_modules(ig)` | `MODULES` | `{osc, mtrg, mca, ring, asg, pid, pulsos}`, de bool |
| `integration_get_slots(ig)` | `SLOTS` | `{osc, ring, mtrg, top, mca, pulsos}` |
| `integration_get_base(ig, m)` | `SLOTS` | la dirección física del módulo; la de `pulsos`, `PULSOS_OFFSET` (64 KB) arriba de su slot. `KeyError` si no publica su slot |
| `integration_get_caps(ig)` | `CAPS_0`, `CAPS_1` | `{n_ch, dw, rsz, en_filt, h_aw, h2_aw, psd_aw}` |
| `integration_get_route_{osc,mtrg,mca,ring}(ig)` | `ROUTE_*` | `{tap, nombre, enable}` |
| `integration_get_routes(ig)` | `ROUTE_*` | los cuatro, por consumidor |
| `integration_set_route_{osc,mtrg,mca,ring}(ig, tap, enable)` | `ROUTE_*` | escribe y relee. `ValueError` si el tap no es válido; `RuntimeError` si no latchea |
| `integration_reset_routes(ig)` | `ROUTE_*` | los cuatro a nativo y habilitados: el estado de reset |
| `integration_get_run(ig)`, `integration_set_run(ig, on)` | `CTRL` bit 0 | |
| `integration_clear(ig)`, `integration_soft_reset(ig)` | `CTRL` bits 1 y 2 | pulsos autolimpiantes; conservan el run |
| `integration_get_status(ig)` | `STATUS` | `{pll_locked, adc_rstn}` |
| `integration_dump(ig)` | todos | imprime la región entera |
| `slot_base(modulo, default=None)` | `SLOTS` | abre, lee y cierra. Sin región de TOP, sin `/dev/mem` o con un módulo sin slot da `default`, sin lanzar |

Los taps son `TAP_NATIVE` (el reset), `TAP_ADC`, `TAP_DEC_IN` y `TAP_BRAM_IN`. Cambiar de
tap corre la latencia, y el camino a DDR por AXI no se rutea: ver el docstring de
`Integration.set_route`.

La clase `Integration` tiene los mismos métodos: `identify`, `modules`, `slots`, `base`,
`caps`, `get_route(consumidor)`, `set_route(consumidor, tap, enable, verify)`, `routes`,
`reset_routes`, `set_run`, `get_run`, `clear`, `soft_reset`, `status` y `dump`. Agrega
`geometria_coincide(mca)`, que compara la geometría de `CAPS_1` con la del MCA: **la
fuente de verdad es `WIDTHS` del MCA**, y estas dos copias ya divergieron una vez.

`pulsos` es el generador de pulsos (bit 6 de `MODULES`, `SLOTS[23:20]`). Un bitstream
sin él lo publica en el slot 0, y su base no sirve: mirar antes `modules()['pulsos']`.

---

## 10. `API.generadores` — los generadores de prueba

Código: [`API/generadores.py`](../../software/API/generadores.py), sobre
[`libmca/include/gen_pulsos.h`](../../software/libmca/include/gen_pulsos.h) y
[`gen_disparos.h`](../../software/libmca/include/gen_disparos.h). Qué genera cada uno y
cómo se verificó: [el generador de pulsos](../gen_eventos/generador_pulsos.md) y
[el del ring](../event_ring/generador.md). El del ring se maneja desde
`OsciloscopeRing` (§4.1); este módulo tiene el de pulsos y las cuentas del motor que
comparten.

```python
from API.generadores import GenPulsos, mq_de, tabla_cdf

with GenPulsos.open() as g:                       # 0x4021_0000 y la página de HK
    cfg = g.configurar(aleatorio=True, tasa=200e3, n=100_000, tau=250.0,
                       amp_aleat=True, ruido=True, ruido_sh=6)
    g.cargar_tabla(tabla_cdf([1500, 4000], [0.6, 0.4]))
    g.lazo = True                                 # adc_dat <- el generador
    # ... el MCA corriendo, con trap_mq = mq_de(cfg['decae']) ...
    g.arrancar()
    g.esperar(timeout_s=5)
    g.parar()
    g.lazo = False
```

La configuración usa los nombres de `CFG` del modelo (`gen_pulsos_model.py`), más
`salidas` (`SAL_OUT1`, `SAL_OUT2`), `tasa` (Hz, en lugar de `umbral` o `periodo`) y `tau`
(muestras, en lugar de `decae`). Lo que no se pasa queda en el reset del RTL, con
`salidas = SAL_OUT1`.

| Qué | Registro | Para qué |
|---|---|---|
| `GenPulsos.open(phys, size, check_magic=True)` | `MAGIC` | el generador y la página de HK. `GenPulsosNotPresent` si el slot 2 no lo tiene |
| `GenPulsos.sobre(bus, hk=None)` | — | sobre `Bus` de `API._libmca`: los tests. Sin `hk` no hay lazo |
| `.configurar(tasa=None, tau=None, **cfg)` | todos menos la tabla | lo apaga, escribe, relee y devuelve lo escrito. No lo arranca. `ValueError` con el motivo si algo no entra en su registro |
| `.leer_config()` | ídem | lo escrito (`amp_n` 0 se lee como 1024) |
| `.cargar_tabla(amp)`, `.leer_tabla(n=1024)` | `TABLA` | hasta 1024 amplitudes de 14 bits con signo, el resto en 0; relee |
| `.arrancar()`, `.parar()` | `CTRL.en` | arrancar reinicia todo el estado (siempre, aunque estuviera prendido); parar pone la salida y el disparo en cero |
| `.estado()` | `GEN_CNT`, `ESTADO` | `{gen_cnt, estado, generando, terminado, desborde}` |
| `.esperar(timeout_s)` | `ESTADO` | hasta N. `ValueError` sin N o apagado; `TimeoutError` |
| `.lazo` | HK `digital_loop[0]` | propiedad: con `True`, `adc_dat` toma el generador. No toca `digital_loop[1]` |
| `.r32`, `.w32`, `registros()` | — | acceso crudo y el mapa |

Las cuentas, sin hardware (en C, iguales a las del modelo):

| Qué | Para qué |
|---|---|
| `disparos(tasa=None, **cfg)` | la configuración del motor, como dict |
| `umbral_para(tasa_hz, dt_min=2)`, `periodo_para(tasa_hz)` | el `UMBRAL` (aleatorio) o el `PERIODO` de una tasa |
| `tasa(**cfg)` | la tasa media de una configuración |
| `predecir(n_ciclos, lat, n_max=None, **cfg)` | los ciclos de cada disparo: con `LAT_TRIG`, los de `trig_o` del generador de pulsos; con `GEN_LAT_TS` (del ring), la marca de cada slot del ring |
| `decae_para(tau)`, `tau_de(decae)`, `mq_de(decae)` | la caída y la `Mq` del polo-cero que la cancela (`trap_mq` y el disparo con polo-cero) |
| `sigma_ruido(sh)` | el sigma del ruido para un `ruido_sh` |
| `tabla_cdf(valores, pesos)` | la tabla del modo `amp_aleat` para un espectro de líneas |

Para el MCA por el lazo digital hacen falta además el tap ADC en el multitrigger y el MCA
(`integration_set_route_*`) y, con el disparo del ASG (`OR_MASK = 0x800`), `DEB_LEN = 0`
en el osciloscopio. Lo hace, bloque por bloque, la parte B de
`make verificar-placa-generadores`, contra la réplica del MCA.
