# Testbench de software del MCA (`testbench_mca.py` + `tests/`)

Cómo está organizada la caracterización del Analizador Multicanal, qué cierra
cada test, y **cuáles de los resultados hay que creerle y cuáles no**. Los
números de la última campaña están en
[`resultados_validacion_hw.md`](resultados_validacion_hw.md); acá está el
*método*.

Código:

| Archivo | Qué es |
|---|---|
| [`../software/mca_utils.py`](../software/mca_utils.py) | driver (`class MCA`) + helpers de análisis **puros** |
| [`../software/testbench_mca.py`](../software/testbench_mca.py) | suite de caracterización: sólo lo que necesita hardware |
| [`../software/tests/test_mca_hw.py`](../software/tests/test_mca_hw.py) | smoke test del bus y los registros, **sin generador** |
| [`../software/tests/test_mca_datapath.py`](../software/tests/test_mca_datapath.py) | camino de datos completo, con señal |
| [`../software/tests/diag_mca_hw.py`](../software/tests/diag_mca_hw.py) | diagnóstico incremental, un paso por invocación |
| [`../software/tests/test_wave_builders.py`](../software/tests/test_wave_builders.py) | estímulo y análisis, **en la PC sin instrumento** |

---

## 1. La división driver / análisis / medición

Es la misma separación que en el scope, con una capa más:

- **`mca_utils.py`** — `class MCA` (mmap, `configure`, `clear`, `acquire`,
  `spectrum`, `map2d`, `counters`, `last_event`) **más los helpers de análisis
  puros**: `gauss_fit_peak`, `energy_calibration`, `dnl`, `fom`,
  `deadtime_fit`. Al ser funciones puras se pueden probar **contra `.npz`
  guardados, sin la placa**.
- **`testbench_mca.py`** — sólo lo que necesita hardware. Cada función devuelve
  **los datos crudos además del resultado**, para poder re-graficar y
  re-analizar sin volver a medir.

Convenciones que hacen la suite reutilizable:

- `_save(outdir, name, **arrays)` deja un `.npz` comprimido por medición.
- `plot_all(outdir)` y `--plot-only` regrafican una campaña entera **en la PC,
  sin hardware**.
- CLI: `--list`, `<test>`, `all`, `--outdir`, `--channel` (0=IN1, 1=IN2),
  `--gen-ch`.

```bash
python3 testbench_mca.py --list
python3 testbench_mca.py single_peak
python3 testbench_mca.py all --outdir datos/mca_2026-08-11
python3 testbench_mca.py --plot-only --outdir datos/mca_2026-08-11   # sin placa
```

---

## 2. Un test por fila de la tabla de parámetros de un MCA

El diseño de la suite es literal: cada función cierra una fila de la tabla de
parámetros a caracterizar (ver
[`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) §1).

| Función (`TESTS`) | Eje | Qué cierra | Campaña 2026-08-11 | Estado del código |
|---|---|---|---|---|
| `single_peak` | resolución | FWHM del pulser = contribución de ruido electrónico | válido | estímulo nuevo (§6) |
| `sweep_amplitude` | amplitud | ganancia, INL, offset de cero | 3718.3 canales/Vpp; **INL 0.501 % FS con el generador incluido** | + ida y vuelta (§6) |
| `dnl` | amplitud | no linealidad diferencial | **inválido**: líneas discretas | corregido, falta re-medir |
| `compare_estimators` | resolución | jitter de muestreo: pico vs integral | limitado por `q_shift` fijo | corregido, falta re-medir |
| `sweep_rate` | tasa | throughput, tiempo muerto, live time, corrimiento del centroide | válido hasta 100 kcps; **no se alcanzó el techo** | corregido, falta re-medir |
| `pulse_pair` | tasa | resolución par-pulso | **inválido**: normalización | corregido, falta re-medir |
| `sweep_threshold` | umbral | curva S, LLD, piso de ruido | válido; LLD 1300, 262 kcps de ruido a `thr=20` | estímulo nuevo |
| `psd_fom` | forma | FOM y su dependencia con la energía | FOM global **1.462** válida; por rebanadas `nan` | corregido, falta re-medir |
| `baseline_k` | — | constante del seguidor de línea de base | válido para pulsos de 240 µs | **hay que re-correrlo primero** |
| `cross_check` | — | `cnt_total` contra la tasa conocida del generador | válido | estímulo nuevo |

> Los "corregido" son cambios de estímulo y de análisis hechos después de la
> campaña; están descritos en §6 y verificados sin hardware con
> `test_wave_builders.py`, pero **todavía no se re-midieron en la placa**.

### Los que tienen una idea no obvia atrás

**`test_psd_fom`** — las dos poblaciones tienen la **misma amplitud** y difieren
sólo en `tau`. Al no moverse en el eje de amplitud, *cualquier* separación que
aparezca viene del eje de forma: es el caso limpio para medir la FOM, y por eso
el 1.462 es creíble. FOM > 1.27 se considera buena separación.

**`compare_estimators`** — es EL experimento que justifica (o no) los 16384
canales. Con la muestra de pico la amplitud sale de una sola muestra y el
muestreo casi nunca cae en el máximo verdadero; ese error crece cuando el pulso
es rápido. La integral promedia el ruido como σ/√N y es inmune a ese jitter, así
que la diferencia entre las dos curvas mide directamente la contribución
instrumental.

**`sweep_threshold`** — la referencia es la **meseta**, no el máximo. A umbral
muy bajo el sistema dispara con ruido y la tasa se dispara (se midieron
**262 kcps a `thr=20`** con una señal de 2 kHz): tomar el máximo hacía que el
"50 %" cayera en la zona de ruido en vez de en el flanco de la curva S. Además
el rango de umbrales se deriva de la **amplitud medida** (`last_event()`), no de
un rango fijo: con un rango fijo bajo la curva sale plana y no dice nada.

**`sweep_rate`** — es el único que usa modo **PULSE y no ARB**. Con el ARB la
forma se estira sobre el período de repetición, así que al barrer la tasa el
pulso cambiaría de *ancho* al mismo tiempo; el modo PULSE da período y ancho
independientes. (El resto de los tests ya no tiene ese problema: `pulse_train_wave`
fija el ancho, ver §3.) El ancho igual escala con el período —`min(width, 0.2·T)`—
porque `set_pulse_periodic` exige `width < T/2` y a 500 kHz el período son 2 µs.

**`sweep_baseline_k`** — si la constante del seguidor (2^`bl_k` muestras, o sea
2^k · 8 ns) es comparable a la duración del pulso, el seguidor **persigue la
señal y la borra**: nunca cruza el umbral y no se detecta nada. Este barrido
encuentra el piso utilizable, y **hay que repetirlo con los pulsos reales**,
porque el valor correcto depende de cuánto duran.

---

## 3. Dos cosas de `testbench_mca.py` que hay que entender antes de leer un número

### El ancho del pulso es ahora un parámetro: `PULSE_WIDTH_S`

`set_arb(freq_hz)` estira la forma **completa** sobre `1/freq`, así que el ancho
del pulso no era un parámetro sino una consecuencia de cuántos puntos ocupaba
dentro de la forma. Con 128 puntos a 2 kHz cada punto dura 3.9 µs y **el pulso
terminaba durando ~336 µs = 42 000 muestras a 125 MSPS**. Con `maxlen=1024`
*todos* los eventos cerraban por longitud y se contaban como apilamiento sin
entrar a los histogramas (verificado en la placa), y de ahí salía el
`maxlen=60000` de la campaña — un parche sobre un estímulo mal escalado.

Ahora `rg.pulse_train_wave(width_s, rate_hz)` invierte la relación: se le pide
el ancho en segundos y devuelve la forma **junto con la frecuencia** a la que
hay que aplicarla. `PULSE_WIDTH_S = 2e-6` es el default de toda la suite y
`DEFAULT_CFG['maxlen']` bajó a 4096 en consecuencia.

**`bl_k` y `maxlen` dependen de la duración del pulso**, así que al cambiarla
hay que re-correr `sweep_baseline_k` antes que nada. `run_campana.py` ya lo hace
primero y propaga el resultado a `DEFAULT_CFG`.

### `cnt_dropped` **no** se normaliza contra `cnt_total`

`cnt_dropped` (offset `0x064`) es la suma de dos cosas
([`mca_top.sv:346`](../rtl/mine/mca/mca_top.sv)):

```systemverilog
sys_rdata <= c_lost + hist_h_drop + hist_2d_drop;
```

- `c_lost` — eventos que llegaron con el extractor de características **ocupado**
  (divisor en curso). **Nunca entraron en `cnt_total`.**
- `hist_*_drop` — eventos descartados durante un barrido de borrado. Esos sí
  están en `cnt_total`.

Consecuencia: **`dropped / total > 1` es perfectamente posible** y no indica un
contador roto. El aviso de `_acquire()` que compara los dos es lo que produjo el
"101 % de descartes" del test de par-pulso, y se corrige normalizando por
`total + dropped`.

---

## 4. Los tests de placa (`software/tests/`)

Son la otra mitad de la verificación: mientras `testbench_mca.py` mide
*parámetros*, éstos verifican que el bloque **funciona**.

### `test_mca_hw.py` — smoke test, sin generador

Es el equivalente en hardware de `tb_mca_top.sv`: lo que allá se verifica con un
BFM, acá se verifica contra el bus real, **incluido el CDC que la simulación no
modela**. Cubre:

- identificación: magic, `H_AW = 14` (16384 canales), `H2_AW = 7`/`PSD_AW = 6`,
  y que los dos motores estén presentes;
- ida y vuelta de cada registro RW con su máscara;
- barrido de lecturas **sin colgarse**;
- borrado: espectro y mapa 2D enteros en cero, forma del mapa `(128, 64)`,
  contadores en cero;
- relojes: `realtime` avanza ~0.5 s en 0.5 s, `livetime + deadtime = realtime`,
  el reloj medido coincide con el del sistema, y con `run=0` **no** avanza;
- `chan_sel` (IN1/IN2), `clear_busy` bajo en reposo, y convergencia de la línea
  de base.

### `test_mca_datapath.py` — el lazo cerrado

Con señal real del DG4162 en IN1: pulsos → segmentador → histogramas. Si
`cnt_total` sigue a la tasa del generador y el espectro tiene un pico único,
**todo el camino está validado**.

### `diag_mca_hw.py` — la herramienta que salvó la campaña

Existe porque el smoke test completo **reinició la placa dos veces** y hubo que
aislar qué operación lo disparaba. Corre **un paso por invocación** y se chequea
`/proc/uptime` entre uno y otro, así un reinicio queda atribuido sin ambigüedad.
El orden de sospecha, del menos al más peligroso, es reutilizable para cualquier
bloque nuevo sobre este bus:

```
regs      lectura/escritura de registros sueltos (ya sabemos que anda)
sweep     barrido de ~650 direcciones, incluidas no mapeadas
bulk      lectura masiva del espectro con copia numpy   <-- principal sospechoso
word      el mismo espectro pero palabra por palabra
clear     barrido de borrado
counters  relojes y contadores
```

**Culpable encontrado:** `np.frombuffer(...).copy()` de 16384 palabras sobre la
apertura del histograma. La lectura en bloque colgaba la placa; la lectura
palabra por palabra no. De ahí sale el `_read_words()` de `mca_utils.py`, que
desenrolla el acceso con `struct.unpack_from` en un list comprehension:

```python
unpack = _U32.unpack_from
mem = self._mmap
return np.array([unpack(mem, offset + 4 * i)[0] for i in range(n)], dtype=np.uint32)
```

Cuesta ~110 ms para el espectro completo, y es el precio de no reiniciar la
placa.

---

## 5. Los runners de campaña

La campaña completa no entra en una sola sesión (entre otras cosas porque
`sweep_threshold` pide desconectar la entrada a mitad de camino), así que quedó
partida en tres scripts que comparten `--outdir`:

| Runner | Qué corre |
|---|---|
| [`run_campana.py`](../software/run_campana.py) | `baseline_k` **primero**, después `single_peak`, `cross_check`, `compare_estimators` → `resumen.json` + `plot_all` |
| [`run_resto.py`](../software/run_resto.py) | `sweep_amplitude`, `pulse_pair`, `sweep_rate` → `resumen_resto.json` |
| [`run_resto2.py`](../software/run_resto2.py) | `sweep_threshold`, `psd_fom`, `dnl` → `resumen_resto2.json` |

Cada uno deja los `.npz` crudos en el mismo directorio y un JSON con los números
resumidos. La campaña del 2026-08-11 está en
[`../software/datos/mca_20260811_113136/`](../software/datos/mca_20260811_113136/).

---

## 6. Lo que estaba roto y cómo se corrigió

**Ninguno de los problemas era del MCA**: todos eran de diseño de estímulo y de
análisis, y casi todos compartían una raíz — el ARB producía pulsos de ~240 µs,
cuatro órdenes de magnitud más largos que un pulso de detector.

| Test | Qué reportaba mal | Qué cambió |
|---|---|---|
| **todos** | el ancho del pulso no era un parámetro | `pulse_train_wave(width_s, rate_hz)`: el ancho se pide en segundos y la frecuencia sale despejada |
| `dnl` | 467 % sobre un espectro con 40 canales vacíos | estímulo con amplitud continua (AM de ruido, con recarga del ARB como alternativa); `dnl()` compara contra la **envolvente local** y **rechaza** un espectro con canales vacíos en vez de devolver un número |
| `pulse_pair` | 101 % de descartes; 1.00 por debajo del tiempo muerto | ancho y período del burst **fijos**; normalización contra la **medición a gap máximo** en vez de un número de bursts estimado; `dropped` como número absoluto |
| `compare_estimators` | "mejora" que podía ser del `q_shift` | `autoscale_q_shift()` lleva los dos estimadores a la misma escala de canales; los puntos con FWHM < 3 canales se marcan **no comparables** |
| `psd_fom` por rebanadas | `nan` en tres de cuatro | segundo estímulo con amplitud variable (`amp_range`) y `autoscale_h2_shift()`; las rebanadas sin estadística se dicen como tales |
| `sweep_rate` | 100 kcps tomado como techo | barrido hasta ~800 kcps, ancho que escala con el período, y el **techo** se reporta explícitamente; sin saturación **no se ajusta** el tiempo muerto |
| `sweep_amplitude` | INL 0.501 % sin separar del generador | pasada de **ida y vuelta**: si el residuo se repite es sistemático, si no es la estadística del ajuste |

Los cambios están verificados sin hardware por
[`test_wave_builders.py`](../software/tests/test_wave_builders.py), que
comprueba que el ancho y la tasa del estímulo son los pedidos, que las
combinaciones imposibles fallan con mensaje, y que `dnl()` recupera una DNL
inyectada del 3 % sobre una envolvente no plana (contra la media global el mismo
espectro daba 19.5 %, seis veces más).

**Falta re-medir todo en la placa.** El orden importa: `sweep_baseline_k`
primero, porque el resto depende del `bl_k` que salga.

## 7. Qué NO cubre

- **Pulsos de detector reales**: la campaña entera se hizo con el generador. El
  cambio de §6 pone el estímulo en la escala temporal correcta, pero un pulso
  sintético sigue sin tener el ruido ni la variabilidad de uno real.
- **Deriva de ganancia y offset** con el tiempo y la temperatura: pide horas de
  adquisición repetida del mismo pico.
- **Separar la INL del ADC de la del generador**: la pasada de ida y vuelta
  distingue sistemático de ruido, pero no cuál de los dos instrumentos aporta el
  sistemático. Eso pide un patrón de tensión trazable.
- **El conformado trapezoidal**, fuera de alcance del diseño (ver
  [`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) §5).

---

## Ver también

- [`register_map_mca.md`](register_map_mca.md) — los offsets que usa el driver.
- [`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) — por qué el hardware es
  como es.
- [`bus_sistema_redpitaya.md`](bus_sistema_redpitaya.md) — el bus, el timeout de
  32 ciclos y la clase de cuelgue que `test_mca_hw.py` verifica que no ocurra.
- [`testbenches_escritura_archivos.md`](testbenches_escritura_archivos.md) — la
  otra suite de software.
