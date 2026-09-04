# Tiempo muerto: qué mide cada curva, y por qué el estímulo periódico engaña

Las dos arquitecturas de adquisición son **K=1**: un evento a la vez, sin cola.
Mientras se procesa uno, lo que llega se pierde. Con esa arquitectura fija, **la
fracción de eventos perdidos depende de cómo llegan los eventos**, y ahí está el
problema: toda la caracterización se hizo con el Rigol en modo PULSE, que es un
tren **periódico**, y una fuente radiactiva entrega **Poisson**.

Un tren periódico con período mayor que el servicio no pierde **nada**: el
siguiente evento siempre encuentra el sistema libre. Poisson pierde a
**cualquier** tasa, porque los arribos se agrupan. Los 99.1 % de eficiencia
medidos a 2 kev/s son entonces una propiedad del estímulo, no del equipo.

## Qué hay acá

| archivo | qué hace | dónde corre |
|---|---|---|
| [`plot_modelos_tasa.py`](../../software/campanas/plot_modelos_tasa.py) | las dos figuras: tasas medidas, ajuste y residuos | PC, sin placa |
| [`run_poisson_loss.py`](../../software/campanas/run_poisson_loss.py) | mide las pérdidas del **lector de Python** con estímulo Poisson | Pitaya + Rigol |
| [`test_poisson_wave.py`](../../software/API/tests/test_poisson_wave.py) | valida el generador Poisson (KS, conteo, costura, pile-up, escala) | PC |
| [`test_poisson_sweep_sim.py`](../../software/campanas/tests/test_poisson_sweep_sim.py) | corre el barrido entero contra un servidor K=1 **simulado** | PC |
| [`test_deadtime_estimadores.py`](../../software/API/tests/test_deadtime_estimadores.py) | valida los estimadores **en tiempo de corrida** (ver abajo) | PC |

```bash
python3 campanas/plot_modelos_tasa.py          # -> ../../datos/modelos_tasa/*.png
python3 test_poisson_wave.py          # RESULT: PASS
python3 test_poisson_sweep_sim.py     # RESULT: PASS
python3 test_deadtime_estimadores.py  # RESULT: PASS
python3 campanas/run_poisson_loss.py <outdir>  # en la Pitaya
```

---

## Estimar τ **durante** la corrida

Todo lo de arriba necesita un **barrido** de tasas: `deadtime_fit` ajusta `m(n)`
sobre varios puntos, y eso es una campaña, no algo que se pueda hacer mientras
se toma un espectro. Para el camino del lector hay dos formas de sacar τ de
**una sola corrida**.

El MCA no las necesita: ya trae contadores de 64 bits a 125 MHz
(`mca_read_counters()` → `livetime_s` / `deadtime_s` / `realtime_s`, de
`feat_busy` en [`mca_top.sv`](../../rtl/mine/mca/mca_top.sv)). Esto es para el
lector de Python, que no tiene contador en hardware.

### A · Cronometrar el período ocupado — `DeadTimeAnnotator`

```python
from API.osciloscope_store import AcquisitionSession, DeadTimeAnnotator

dt = DeadTimeAnnotator()
with AcquisitionSession(src, run_dir, annotators=(dt,)) as s:
    s.wait(duration_s=60)
    print(f'ocupado {dt.busy_fraction()*100:.1f} %')     # en vivo
```

Funciona porque `sample_into` corre **justo después de `rearm()`**, así que
`perf_counter_ns() − batch.t_ns[i]` es el intervalo en que el scope estuvo
congelado — la misma definición que el `deadtime_cnt` del RTL. Cuesta un
`perf_counter_ns()` por evento y **no hay que tocar el lector**: la columna
`dead_ns` se propaga sola al esquema y al `.npz`.

Es **independiente del estímulo**: sirve igual con fuente Poisson y con el Rigol
en PULSE. No ve la latencia de detección (≤ 2.3 µs sobre ~250, < 1 %) ni el
período ocupado de los eventos tirados por backpressure (ésos van en
`stats['n_dropped']`).

Y guarda τ **por evento**, no sólo el total: la distribución es lo que distingue
un ciclo de `τ ± σ` de uno con cola larga por stalls de GIL.

### B · Inferirlo de los Δt — y acá **sí** cambia según la fuente

El proceso de arribos cambia la matemática, no es un parámetro del mismo ajuste.
Por eso son dos funciones ([`API/analisis.py`](../../software/API/analisis.py)):

| | `tau_poisson(t_ns, gap)` | `tau_periodico(t_ns, gap, T_s)` |
|---|---|---|
| Estímulo | fuente real | Rigol en PULSE |
| Modelo de Δt | `τ + Exp(n)`, exponencial **desplazada** | `k·T`, **cuantizado**, `k = ⌈τ/T⌉` |
| τ | sí, ±3 % | **sólo un bracket** `((k−1)T, kT]` |
| Tasa incidente `n` | **sí** — no hay otra forma sin fuente calibrada | trivial, `n = 1/T` |
| Pérdida | `ρ/(1+ρ)`, del modelo | **exacta**, `1 − 1/⟨k⟩`, sin modelo |

Son complementarias en un sentido fuerte: la fuente Poisson da τ pero la pérdida
sale de un modelo; la periódica da la pérdida exacta pero τ sólo acotado.

**El bracket no es debilidad del estimador.** El modelo D/D/1/1 es discontinuo
en τ y con un solo `k` poblado la información no está en los datos — es el mismo
"cualquier τ entre 200 y 250 µs da la misma predicción" de más arriba. Lo que lo
aprieta es **barrer T e intersecar los brackets**; el test lo hace con 8 valores
de T y recupera exactamente `(200, 250] µs`, por un camino independiente del
ajuste de la curva de tasas.

Caso especial: cuando `τ/T` cae cerca de un entero se pueblan **dos `k`
adyacentes**, y el borde entre ellos **sí** localiza τ. Es lo que pasa en el
punto de 20 kev/s (`τ/T = 5.00`), el mismo que el ajuste no podía acertar.

### Por qué el modelo se declara y no se adivina

Tienta clasificar solo por la forma de los Δt. **No funciona.** El CV del
residuo tiene anclajes limpios (exponencial 1.00, jitter gaussiano 0.33), pero
cuando `τ/T` cae cerca de un entero el periódico se vuelve bimodal y sube a
~0.91 — indistinguible de Poisson. Medido: se equivoca en 3 de 5 casos
periódicos, **incluido el de 20 kev/s**.

Lo que sí funciona es el **error de cuantización**, `|Δt/T − round(Δt/T)|`: ~0
para periódico, 0.25 para Poisson porque la parte fraccionaria queda uniforme.
`tau_periodico` lo lleva adentro como guarda y **se niega** ante un estímulo que
no es periódico, en vez de devolver un número plausible y falso. `cv_residuo`
queda expuesta como diagnóstico, documentada como no-selector.

### El detalle de `gap` del que depende todo

Las pérdidas por **tiempo muerto no se anotan en `gap`**: el scope no estaba
armado, no hubo trigger, el lector nunca se enteró. `gap` sólo lleva los
descartes por **backpressure** (la rama `queue.Empty`).

Esa asimetría es justo lo que hace válido el método. Los Δt tienen que *incluir*
las pérdidas por tiempo muerto —son la señal que se mide— y *no* las de
backpressure, que son artefacto del pipeline. Filtrar por `gap == 0` deja
exactamente eso. Con 20 % de backpressure encima, sin filtrar la tasa incidente
sale sesgada **24 %**.

`plot_modelos_tasa.py` toma las mediciones de los `.npz` de los barridos, así
que **rehacer las figuras con datos nuevos no toca el código**:

```bash
python3 campanas/plot_modelos_tasa.py \
    --mca         ../../datos/<campana>/sweep_rate.npz \
    --mca-poisson ../../datos/<campana>/sweep_rate_poisson.npz \
    --lector-poisson ../../datos/<corrida>/poisson_loss_lector.npz
```

Sin `--lector` usa la tabla de 6 puntos del documento. Los puntos con estímulo
**Poisson** se dibujan en **naranja** y los periódicos en **negro**; mientras no
existan, el panel de pérdidas lo dice explícitamente.

Las figuras van a `software/datos/`, que está en `.gitignore`: se regeneran con
el script, que corre en la PC en segundos.

## Los tres modelos

Todos con un servidor y sin cola. Lo único que cambia es **el proceso de
arribos**; `n` es la tasa incidente, `m` la registrada, `τ` el tiempo de
servicio y `ρ = nτ` la ocupación.

| modelo | arribos | fórmula | pérdida a ρ pequeño |
|---|---|---|---|
| **D/D/1/1** | periódicos (el Rigol en PULSE) | `m = n/⌈nτ⌉` | **0** hasta ρ=1 |
| **M/G/1/1** ("no paralizable") | **Poisson** (fuente real) | `m = n/(1+nτ)` | **ρ** |
| **paralizable** | Poisson, y cada arribo **re-extiende** el tiempo muerto | `m = n·e^{−nτ}` | ρ |

La diferencia entre las dos primeras a tasa baja es todo el asunto: a ρ=0.1 una
predice 0 % de pérdida y la otra 9.1 %.

---

## Figura 1 — `modelos_tasa_lector.png` (lector de Python)

Los 6 puntos medidos salen de
[`arquitectura_adquisicion_software.md`](../multitrigger/arquitectura_adquisicion_software.md),
"El techo real, medido end-to-end": barrido de 4 s por punto, pulsos 0→1 V,
ventana de 8+24 muestras, 2 canales, **estímulo periódico**.

### Panel de arriba — tasa registrada contra tasa incidente (log-log)

| curva | qué es | cómo leerla |
|---|---|---|
| `medido` (puntos negros) | los 6 puntos de la campaña | es el dato; todo lo demás son modelos |
| `ideal (sin pérdidas)` (punteada negra) | la diagonal `m = n` | referencia: lo que se registraría sin perder nada. La separación vertical contra los puntos **es** la pérdida |
| `periodico, tau constante` (azul fina) | **D/D/1/1** con τ fijo | la **escalera**. Con τ constante el sistema acepta un arribo cada `⌈τ/T⌉` períodos, así que `m = n/k` con `k` entero: entre dientes `k` no cambia y `m` **crece** con `n`; en cada diente `k` sube de golpe y `m` **cae**. Los dientes están en `n = k/τ` (con τ=250 µs: 4000, 8000, 12000 ev/s). A la izquierda del primero **no se pierde nada** y la curva se pega a la diagonal |
| `periodico + dispersion` (azul gruesa) | **D/G/1/1**: el mismo modelo pero con τ ~ Normal(µ,σ) | es **el ajuste**. Suaviza los dientes porque, cerca de un borde, unos eventos caen con `k` y otros con `k+1` |
| `Poisson M/G/1/1` (roja a trazos) | la curva de una fuente real | suave y **sin tramo plano**: empieza a perder desde el primer punto. Satura en `1/τ` (4000 ev/s) |
| `paralizable` (verde punto-raya) | cada arribo reinicia el tiempo muerto | tiene un **máximo** en `n = 1/τ` (m = 1/(eτ) ≈ 1472 ev/s) y después **se desploma**: a tasa alta el sistema nunca se libera. Se muestra para descartarlo, no describe a este equipo |

**La anotación sobre el punto de 20 kev/s** marca lo que ningún τ constante
puede acertar: ahí `τ/T = 5.00` cae **justo en un borde**, entre `k=5` (4000
ev/s) y `k=6` (3333). El valor medido, 3684, está entre los dos — exactamente lo
que produce un servicio con dispersión, y la razón de que el ajuste use el
modelo con σ.

### Panel del medio — **pérdida vs tasa**: el que discrimina

En el panel de arriba los dos modelos **convergen a tasa alta** y la medición
deja de distinguirlos. La pérdida los separa desde el primer punto: el modelo
periódico da **cero** hasta ρ=1 y el de Poisson da `ρ/(1+ρ)`. El par
**(tasa registrada, eventos perdidos)** es el observable a mirar, y es el que el
sistema exporta.

| curva | qué es |
|---|---|
| `periodico: CERO hasta rho=1` (azul) | escalón: no se pierde nada hasta que el período iguala al servicio |
| `Poisson: rho/(1+rho)` (roja) | la fuente real: 11 % ya a ρ=0.125 |
| `medido — PERIODICO` (puntos negros) | `1 − registrada/incidente` |
| `medido — POISSON` (cuadrados naranjas) | **falta medirlo**; van sobre la curva roja si el modelo K=1 es correcto |
| `tiempo muerto medido` (triángulos violeta, sólo MCA) | la fracción de tiempo que el sistema estuvo ocupado |
| línea vertical `rho = 1` | donde el período iguala al servicio |

**`tiempo muerto` no es `eventos perdidos`.** Es la confusión más fácil de
cometer y la figura la muestra: a 100 kcps el MCA estuvo **ocupado el 28.6 % del
tiempo** y perdió **0 eventos**, porque los arribos eran periódicos y siempre
encontraban el sistema libre.

Y de ahí sale algo útil: como sin pérdidas la fracción muerta vale exactamente
`ρ = n·τ` (verificado: 4.3, 8.1, 15.3, 28.6 % contra `n·τ` en los cuatro puntos
más altos del MCA), **se puede predecir la pérdida con fuente Poisson sin tener
una**, con `ρ/(1+ρ)` sobre el tiempo muerto que ya exporta el FPGA. La medición
con estímulo Poisson es la **confirmación** de esa predicción, no la única forma
de obtenerla.

### Panel de abajo — residuos de la pérdida

`medido − modelo`, en **puntos porcentuales** de pérdida (no en % relativo: a
pérdida cero el error relativo no está definido).

| serie | lectura |
|---|---|
| `medido − modelo periodico` | ~0 en todo el rango: es el modelo que describe al estímulo usado |
| `medido − modelo Poisson` | **−11, −20, −32 pp** en 500, 1000 y 2000 ev/s (el MCA: hasta −22 pp a 100 kcps). Negativo = se perdió **menos** de lo que Poisson predice, que es la firma de que los arribos **no eran Poisson** |

En el ajuste de la tasa (no de la pérdida) los residuos relativos son: modelo
periódico ±2.3 %, Poisson +9 %, +17 %, +28 % a tasa baja. A tasa alta las dos
curvas convergen y la medición ya **no discrimina** — por eso no alcanza con
mirar el extremo del barrido.

### Los números

| n [ev/s] | medido | per+disp | residuo | Poisson | residuo | τ/T |
|---|---|---|---|---|---|---|
| 500 | 500 | 500 | 0.0 % | 454 | +9.1 % | 0.12 |
| 1000 | 999 | 1000 | −0.1 % | 833 | +16.6 % | 0.25 |
| 2000 | 1983 | 2000 | −0.9 % | 1427 | +28.1 % | 0.50 |
| 5000 | 2473 | 2500 | −1.1 % | 2494 | −0.9 % | 1.25 |
| 10000 | 3259 | 3333 | −2.3 % | 3323 | −2.0 % | 2.50 |
| 20000 | 3684 | 3671 | +0.4 % | 3986 | −8.2 % | 5.00 |

| modelo | τ ajustado | rms del residuo |
|---|---|---|
| **periódico + dispersión** | **250 ± 2 µs** | **1.10 %** |
| periódico, τ constante | 200 µs (indistinguible en 200–250 µs) | 3.67 % |
| Poisson | 201 µs | 14.25 % |
| paralizable | 96 µs | 17.02 % |

Dos cosas que valen más que el ajuste en sí:

1. **τ = 250 µs coincide con los 252.7 µs de la atribución por fases**
   (`read` 172.7 + `rearm` 38.0 + `book` 30.8 + `snap` 11.2), que es una
   medición **independiente**: cronometrar el ciclo, no ajustar la curva. Que
   los dos caminos den lo mismo es la evidencia de que K=1 describe al sistema.
2. El modelo de escalones es **discontinuo en τ**, así que un τ puntual engaña:
   con estos 6 puntos, cualquier τ entre 200 y 250 µs da la misma predicción.
   Por eso el script reporta el **intervalo**.

> El σ = 2 µs del ajuste **no es una medición de la dispersión del ciclo**: como
> `τ/T = 5.00` cae justo en el borde, alcanza una dispersión mínima para
> repartir los eventos entre `k=5` y `k=6`. Sólo dice que ese punto está en el
> borde y que el escalón puro no aplica ahí.

### Qué daría una fuente real

Con τ = 250 µs, arribos de Poisson:

| tasa | ρ | pérdida periódica (lo medido) | pérdida Poisson | tasa registrada |
|---|---|---|---|---|
| 500 ev/s | 0.125 | 0 % | **11.1 %** | 444 ev/s |
| 2000 ev/s | 0.500 | 0 % | **33.3 %** | 1333 ev/s |
| 5000 ev/s | 1.250 | 50 % | 55.6 % | 2222 ev/s |

---

## Figura 2 — `modelos_tasa_mca.png` (MCA en RTL)

Datos de `datos/mca_20260811_113136/sweep_rate.npz`. Mismos tres paneles.

Los puntos caen **sobre la diagonal**: el MCA sigue al generador con 99.95 %
hasta 100 kcps, no hay saturación y por lo tanto **no hay curvatura que
ajustar** — es el "no se alcanzó el techo" del doc. τ no sale de la curva sino
del **tiempo muerto que mide el FPGA**: la pendiente de `(1 − live)` contra la
tasa da **τ = 2.86 µs**, o sea ρ=1 recién a ~350 kcps. Con arribos periódicos,
no perder nada hasta 100 kcps es exactamente lo esperado.

El panel del medio es el que resume todo: la fracción de tiempo muerto sube
hasta 28.6 % mientras la pérdida medida se queda clavada en **0 %**, y la curva
de Poisson pasa por 22 %. El residuo contra Poisson llega a **−22 pp**.

## Cuántos puntos, y por qué

Las mediciones que hay son de **6 puntos** (lector) y **11** (MCA), y con eso la
zona que decide —la década ρ = 0.01 … 1— queda con 3 o 4 puntos. Los barridos
nuevos usan grillas **log-espaciadas y densas** por default:

| barrido | puntos | rango | costo aproximado |
|---|---|---|---|
| `sweep_rate_poisson` (MCA) | 20 | ρ = 0.005 … 2 | ~6 min con `seconds=6` |
| `run_poisson_loss.py` (lector) | 16 | ρ = 0.02 … 2 | `puntos × semillas × sub_s`; con los defaults, ~12 min (lo imprime al arrancar) |

Se pueden pasar a mano: `--rhos 0.01,0.02,...` o `rhos=np.logspace(...)`.

## Referencias

Los números de capítulo y de página cambian entre ediciones; verificá contra la
que tengas a mano.

**Tiempo muerto en conteo de radiación** — es donde están los dos modelos con el
nombre que usa la comunidad (*paralizable* = tipo II, *no paralizable* = tipo I):

- G. F. Knoll, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010,
  **cap. 4**. Deduce `m = n·e^{−nτ}` (paralizable) y `m = n/(1+nτ)` (no
  paralizable), y discute cómo distinguirlos midiendo. Es la referencia estándar
  del área y la que ya usa el resto del proyecto.
- W. R. Leo, *Techniques for Nuclear and Particle Physics Experiments*, 2ª ed.,
  Springer, 1994 — el mismo par de modelos, más corto.
- J. W. Müller, "Dead-time problems", *Nuclear Instruments and Methods* **112**
  (1973) 47. Revisión clásica: combinaciones de tiempos muertos en serie,
  correcciones y sus límites de validez.

**Teoría de colas** — de ahí sale la notación y el resultado `ρ/(1+ρ)`:

- D. G. Kendall, "Stochastic processes occurring in the theory of queues and
  their analysis by the method of the imbedded Markov chain", *Annals of
  Mathematical Statistics* **24** (1953) 338. Es el origen de la notación
  `A/B/c`: llegadas / servicio / servidores. La cuarta posición (capacidad del
  sistema, el `/1` final de `M/G/1/1`) es una extensión posterior, habitualmente
  atribuida a Lee (1966).
  - `D` = determinista, `M` = markoviano (Poisson / exponencial), `G` = general.
    Entonces **D/D/1/1** = arribos periódicos, servicio fijo, un servidor, lugar
    para uno solo (sin cola); **M/G/1/1** = arribos Poisson y servicio de
    distribución cualquiera.
- **`M/G/1/1` es el sistema de pérdidas de Erlang con un servidor**, y su
  probabilidad de bloqueo es la fórmula B de Erlang, que para `c=1` se reduce a
  `B = ρ/(1+ρ)`. El origen es A. K. Erlang (1917), en telefonía.
- B. A. Sevastyanov (1957) probó la **insensibilidad** del sistema de pérdidas
  de Erlang: la probabilidad de bloqueo depende **sólo de la media** del tiempo
  de servicio, no de su distribución. Es lo que justifica que acá alcance con un
  τ y no haga falta modelar la forma del ciclo — y por eso `M/G/1/1` (con `G`
  general) tiene la misma fórmula que `M/M/1/1`.
- L. Kleinrock, *Queueing Systems, Vol. 1: Theory*, Wiley, 1975, o
  Gross, Shortle, Thompson & Harris, *Fundamentals of Queueing Theory*, Wiley
  — cualquiera de los dos como texto de base.

**Procesos puntuales y renovación** — para la parte de estadística de intervalos
(y para la costura del ARB, que es la paradoja de la inspección):

- D. R. Cox, *Renewal Theory*, Methuen, 1962 — muestreo sesgado por longitud:
  el intervalo que **contiene un instante fijo** tiene media `2/λ`, no `1/λ`.
  Es exactamente lo que verifica `test_poisson_wave.py`.
- W. Feller, *An Introduction to Probability Theory and Its Applications*,
  Vol. II, Wiley — la paradoja del tiempo de espera, con la deducción completa.

---

## Cómo re-medir bien

El estímulo Poisson lo arma
[`poisson_train_wave`](../../software/rigol_dg4162.py) (sortea `N ~ Poisson(λT)` y pone
las N posiciones uniformes en el ciclo del ARB). Después:

- **MCA**: `testbench_mca.sweep_rate_poisson(mca, gen, outdir=...)`. La pérdida
  sale **directo del hardware**, `dropped/(total+dropped)`, sin depender del
  generador, y τ del propio contador de tiempo muerto.
- **Lector de Python**: `run_poisson_loss.py`. Acá `stats['n_dropped']` cuenta
  sólo *backpressure*, no los eventos perdidos mientras leía, así que la verdad
  de referencia la da el estímulo:
  `P_loss = 1 − n_leídos/(n_events × freq × T)`.

El primer punto a mirar es el de **ρ chico**: si a ρ=0.02 la pérdida medida da
~2 % y no cero, la fuente Poisson está funcionando y toda la eficiencia medida
hasta ahora hay que releerla.
