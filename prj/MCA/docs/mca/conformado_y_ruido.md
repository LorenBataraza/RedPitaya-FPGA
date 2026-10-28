# Conformado y ruido: qué mide el S/N de Nicholson y por qué acá el orden se invierte

Monte-Carlo de [`conformado.py`](../../software/monte-carlo/conformado.py).
**Corre en la PC, sin placa**, en ~30 s.

```bash
cd software
make montecarlo-conformado                 # los dos experimentos, figuras en datos/conformado_<fecha>/
python3 monte-carlo/conformado.py --solo adc --n 20000
python3 monte-carlo/conformado.py --amplitud 1000 --sigma 5
python3 -m pytest monte-carlo/test_conformado.py -q
```

## La pregunta

La figura 17.24 de Nicholson (reproducida en Knoll, cap. 17) ordena los
conformadores por su relación señal/ruido relativa al *cusp infinito*:

| forma | S/N |
|---|---|
| cusp infinito | 1.000 |
| triangular | 0.930 |
| DL–RC | 0.911 |
| CR–(RC)⁴ | 0.858 |
| CR–RC | 0.736 |
| (CR)²–(RC)⁴ | 0.725 |
| (CR)²–RC | 0.709 |

La intuición dice que conformar **promedia** el ruido, así que ¿de qué S/N se
"pierde"? De ninguna contra no conformar. La figura no compara conformar con
no conformar: compara conformadores **entre sí**, cada uno en su constante de
tiempo de mínimo ruido, y contra el filtro óptimo. Y tiene tres supuestos
implícitos que conviene decir en voz alta, porque ninguno vale para nuestra
cadena:

1. **El ruido entra antes del conformador.** Es el caso del preamplificador de
   carga: la señal es un escalón y el ruido tiene dos componentes con
   dependencia *opuesta* de la constante de tiempo:
   - *serie* (ruido de tensión del FET, "delta noise"): blanco a la salida del
     preamp; se reduce integrando **más** tiempo;
   - *paralelo* (corriente de fuga, "step noise"): el preamp lo integra y sale
     como escalones aleatorios; se reduce integrando **menos** tiempo, porque
     cuanto más ventana se abre, más escalones entran.

   El "promediar" de la intuición es lo que baja el serie; el precio es que
   sube el paralelo. Para cada forma hay un τ donde se equilibran — la leyenda
   dice *"time constants chosen to yield minimum noise"*.

2. **El conformador es un filtro, y su S/N es `pico / σ_salida`.** Todos
   promedian; lo que cambia es con qué *función de peso*. Para serie + paralelo
   blancos la función de peso óptima —el filtro adaptado— es el cusp
   `e^{-|t|/τ}`. Por eso vale 1.000 y todo lo demás es fracción. Que CR–RC dé
   0.736 no dice que promedie "menos que nada": dice que en su mejor τ tiene
   36 % más ruido rms que el óptimo.

3. **Los pulsos se normalizan a igual altura**, así que el número es
   directamente el cociente de ruidos rms para la misma señal.

En nuestra cadena el pulso **ya llega conformado** (el Rigol en las campañas, el
conformador analógico con un detector real) y el ruido dominante entra **después**
del conformador. Es casi todo blanco a 125 MSPS, con σ = 4.47 cuentas por muestra
—de las que el ADC pone 1.28 y el front-end de la placa el resto— más un término
correlacionado de 0.87 cuentas que el conformado no toca de la misma manera
([`../ruido_del_sistema.md`](../ruido_del_sistema.md) §3; los 2.8 cuentas que
este documento citaba son el ancho del fotopico, o sea el blanco ya angostado
por el `max` del experimento B). Ese ruido el conformador no lo
puede filtrar, porque entra después. La forma actúa entonces por dos caminos
que en Nicholson no existen: cuántas muestras caen sobre el ápice (el estimador
`max` del RTL sobre N muestras ruidosas) y la fase de muestreo por la pendiente
en el ápice. De ahí los dos experimentos.

## Experimento A — ruido antes del conformador (Nicholson)

### El modelo, y por qué la respuesta es cerrada

Salida del preamp: `v(t) = Q·u(t) + n_s(t) + n_p(t)`, con `n_s` blanco de
densidad `a` y `n_p` la integral de un blanco de densidad `b` (proceso de
Wiener). El conformador es lineal con respuesta al escalón `s(t/τ)`, la forma
del catálogo normalizada a pico 1. La salida es `y = s * dv/dt`; en el instante
del pico la señal vale `Q` y la varianza del ruido

    σ²(τ) = a·A₁/τ + b·A₂·τ        A₁ = ∫ s'(u)² du     A₂ = ∫ s(u)² du

`A₁` pesa el serie (cae con τ), `A₂` el paralelo (crece con τ). El mínimo está
en `τ* = √(a·A₁ / (b·A₂))` y vale `σ²_min = 2·√(a·b·A₁·A₂)`. El cusp tiene
`A₁ = A₂ = 1`, así que

    S/N relativo al cusp = (A₁·A₂)^(-1/4)

Para CR–RC, `s = e·u·e^{-u}` y `A₁ = A₂ = e²/4`, o sea `(e⁴/16)^(-1/4) = 0.736`:
el número de la figura. Triangular: `A₁ = 2, A₂ = 2/3`, `(4/3)^(-1/4) = 0.930`.
Son los índices de forma de Radeka/Goulding (`ENC² = a·A₁/τ + b·A₂·τ + c·A₃`,
sin el término 1/f) colapsados a un número.

### Qué hace el Monte-Carlo

Sortea el ruido serie y los incrementos del paralelo en una grilla fina
(64 puntos por unidad de τ), los pasa por el conformador y mide la σ en el
pico, para 15 valores de τ y para cada familia. Como el filtro es lineal y el
ruido estacionario, la muestra del pico es un funcional lineal del ruido y se
calcula sin convolver la traza entera (`mc_nicholson`). Familias: las seis de
[`FORMAS_KNOLL`](../../software/API/rigol_dg4162.py) más el cusp, definido en el
propio script.

### Resultado

```
  familia           A1      A2   tau*  S/N teo  S/N MC  Nicholson     dif
  cusp           1.000   1.000  1.000    1.000   0.987      1.000  -0.000
  triangular     2.000   0.667  1.732    0.931   0.940      0.930  +0.001
  trapezoidal    2.000   1.667  1.095    0.740   0.738          —
  CR-RC⁴         0.512   3.582  0.378    0.859   0.851      0.858  +0.001
  CR-RC          1.847   1.847  1.000    0.736   0.727      0.736  -0.000
  CR            13.581   0.647  4.581    0.581   0.581          —
  (CR)²-RC       3.527   1.176  1.732    0.701   0.700      0.709  -0.008
```

Las cuatro familias que la figura tabula cierran a ±0.001 con la fórmula, y el
Monte-Carlo cierra con la fórmula dentro de su error estadístico (n = 4000: la
σ muestral tiene un error relativo de `1/√(2n) ≈ 1.1 %`, y el S/N relativo
compara dos de esas). La bipolar da 0.701 contra 0.709: la (CR)²–RC del catálogo
tiene las tres constantes iguales y la de Nicholson probablemente no; es una
diferencia del 1 % y no cambia el orden.

Dos cosas que la figura no dice y el barrido sí:

- **El trapecio es peor que el triángulo, y casi igual que CR–RC** (0.740 contra
  0.736). El techo plano suma `A₂` (más tiempo integrando el paralelo) sin
  cambiar `A₁`: en el mundo de Nicholson el techo es puro costo.
- **La CR sola es la peor de todas** (0.581): el flanco casi vertical
  (`r = 0.05`) dispara `A₁` a 13.6. Un flanco rápido es caro en ruido serie.

![codo de ruido y S/N relativo](../../software/datos/conformado_20260917_163201/conformado_nicholson.png)

*Izquierda: σ en el pico contra τ, en unidades donde `a = b = 1`, normalizada al
mínimo del cusp. Rama descendente ∝ 1/√τ (serie), ascendente ∝ √τ (paralelo);
líneas: fórmula, puntos: Monte-Carlo, ▼: el mínimo de cada familia. Derecha: el
S/N relativo al cusp en el mínimo — barra: `(A₁A₂)^(-1/4)`; punto: Monte-Carlo;
cruz: el valor de Nicholson.*

## Experimento B — ruido en el ADC (nuestra cadena)

### El modelo

Las mismas siete familias con el **mismo FWHM (2 µs)** y la **misma altura**
(1920 cuentas, la línea del estudio de apilamiento), muestreadas a 125 MSPS con
fase `U[0, Ts)` y ruido blanco de σ = 2.8 cuentas, redondeadas y saturadas como
el ADC. Cada pulso pasa por el segmentador del RTL
([`segmentar_rapido`](../../software/monte-carlo/pileup.py), modo 0) y la amplitud
se estima de tres maneras sobre las **mismas muestras**:

| estimador | qué es |
|---|---|
| `pico` | el máximo de la ventana, tal cual lo calcula `mca_pulse_feature.sv` |
| `boxcar` | media móvil de 9 muestras (72 ns) y después el máximo — el conformado digital mínimo |
| `adaptado` | correlación con la propia plantilla y máximo sobre lags enteros — el filtro adaptado para ruido blanco; su cota es `σ_ADC / √Σ s_n²` |

Cada familia se corre tres veces —(ruido, fase), (sin ruido, fase), (ruido,
fase 0)— para separar `σ_fase` de `σ_ruido`. "Fase 0" significa que una muestra
cae exactamente sobre el ápice continuo; la normalización es por ese ápice, así
que la verdad es exactamente 1920.

### Resultado

```
  familia      ápice │              pico              │             boxcar             │            adaptado
                 [n] │  sesgo      σ σ_fase  σ_rui FWHM%│  sesgo      σ σ_fase  σ_rui FWHM%│  sesgo      σ σ_fase  σ_rui FWHM%
  cusp             3 │  -2.35   2.84   1.59   2.82 0.35│ -23.75   0.96   0.20   0.94 0.12│  -0.01   0.21   0.02   0.21 0.03
  triangular       5 │  -1.45   2.62   1.18   2.73 0.32│ -17.25   0.94   0.14   0.92 0.12│  -0.01   0.21   0.01   0.22 0.03
  trapezoidal    128 │  +7.23   1.19   0.00   1.19 0.15│  +2.07   0.50   0.00   0.52 0.06│  -0.02   0.20   0.01   0.20 0.02
  CR-RC⁴          30 │  +3.78   1.68   0.00   1.66 0.21│  -0.26   0.91   0.08   0.88 0.11│  +0.00   0.21   0.02   0.20 0.03
  CR-RC           29 │  +3.78   1.65   0.00   1.66 0.20│  -0.29   0.86   0.07   0.87 0.11│  -0.01   0.20   0.02   0.20 0.02
  CR              19 │  +3.06   1.80   0.00   1.79 0.22│  -1.42   0.92   0.08   0.90 0.11│  -0.02   0.21   0.03   0.20 0.03
  (CR)²-RC        32 │  +3.88   1.61   0.00   1.62 0.20│  -0.13   0.85   0.03   0.87 0.10│  +0.00   0.20   0.02   0.21 0.02
```

`ápice` es cuántas muestras de la plantilla superan el 99 % del pico. Sesgo y σ
en cuentas; `FWHM%` es `2.355·σ/1920`.

Lo que dice, columna por columna:

- **`pico`, el estimador del RTL.** Dos regímenes, separados por el ápice:
  - *Ápice de 20–130 muestras* (todas las unipolares con integración, el
    trapecio): la fase no se ve (`σ_fase = 0.00`: la muestra más cercana al
    máximo difiere de él en menos de media cuenta) y el máximo de N muestras
    ruidosas se **sesga hacia arriba** (+3 a +7 cuentas, creciendo con N como
    `√(2 ln N)`) y tiene **menos dispersión que el ruido** (σ = 1.2–1.8 contra
    2.8: la distribución del máximo es más angosta que la de una muestra). El
    trapecio es el mejor de todos en σ, y el más sesgado.
  - *Ápice de 3–5 muestras* (cusp, triangular): la fase manda. `σ_fase` vale
    1.2–1.6 cuentas y el sesgo es **negativo** (−1.5 a −2.4): la muestra
    nunca cae exactamente en la punta. La σ total es ≈ la del ADC.

  El sesgo es sistemático y absoluto, no relativo: se calibra con el pulser
  y no ensancha el fotopico. Lo que ensancha es σ, y ahí gana el trapecio.

- **`boxcar`.** Baja σ a ~0.9 (≈ 2.8/√9) en todas, pero el promedio sobre un
  ápice puntiagudo lo aplasta: −24 cuentas en el cusp, −17 en el triángulo, casi
  nada en las que tienen ápice ancho. Es el compromiso sesgo–varianza de
  cualquier conformado digital: el ancho del filtro tiene que ser menor que el
  del ápice, y ahí el ápice ancho vuelve a ganar.

- **`adaptado`.** Sin sesgo, sin término de fase, y **σ = 0.20–0.21 para todas**.
  Con ruido blanco a la salida del conformador la σ del filtro adaptado es
  `σ_ADC/√Σ s_n²`, y `Σ s_n²` a FWHM fijo vale ~180 muestras para cualquier
  forma del catálogo: a igual ancho, todas tienen la misma "energía". La forma
  deja de importar; lo único que importa es cuánto dura el pulso. Es la lógica
  de Nicholson otra vez —el filtro adaptado al ruido es el óptimo— pero con el
  ADC como espectro de ruido, y como ese espectro es blanco, la respuesta es
  otra.

![el ápice y los tres estimadores](../../software/datos/conformado_20260917_163201/conformado_adc.png)

*Arriba: ±17 muestras alrededor del ápice de cada familia (curva continua),
las muestras del ADC para fase 0.5 y, en negro, la muestra que el RTL toma como
pico para tres fases distintas: en el cusp y el triángulo baila, en las demás
no se mueve. Abajo: σ total, σ por fase sola, y sesgo, por familia y
estimador.*

## Los dos órdenes, lado a lado

```
  A: preamp (S/N)          B: ADC, pico del RTL (σ)     B: ADC, filtro adaptado (σ)
  cusp         1.000       trapezoidal  1.19            trapezoidal  0.20
  triangular   0.931       (CR)²-RC     1.61            CR-RC        0.20
  CR-RC⁴       0.859       CR-RC        1.65            (CR)²-RC     0.20
  trapezoidal  0.740       CR-RC⁴       1.68            CR           0.21
  CR-RC        0.736       CR           1.80            cusp         0.21
  (CR)²-RC     0.701       triangular   2.62            CR-RC⁴       0.21
  CR           0.581       cusp         2.84            triangular   0.21
```

El cusp y el triángulo, los dos mejores de Nicholson, son los dos **peores**
para el estimador de pico del RTL; el trapecio, el peor de Nicholson entre los
unipolares, es el mejor. No es una contradicción: son dos preguntas distintas.
Nicholson pregunta *qué filtro le saca menos ruido al preamplificador*; el
experimento B pregunta *qué forma se deja medir mejor por un `max` sobre
muestras con ruido propio*. Con un detector real las dos preguntas se apilan:
el conformador analógico fija el ruido que llega al ADC (A), y la forma que ese
conformador entrega fija cuánto agrega el estimador digital (B). La solución
que satisface a las dos es la del filtro trapezoidal digital de Jordanov: el
techo plano para el estimador, y el ancho de las rampas elegido con el codo de
ruido de A.

Para las campañas con el Rigol —donde A no existe porque no hay preamp— la
consecuencia es la que ya midió [`formas_de_pulso.md`](formas_de_pulso.md): el
trapecio es el estímulo que menos castiga al estimador de pico, y las familias
con ápice de pocas muestras miden la fase de muestreo tanto como la amplitud.

## Qué valida el simulador, y qué no

- El experimento A es un modelo de dos ruidos blancos sin término 1/f ni
  déficit balístico; con eso reproduce la figura, así que es el mismo modelo
  que usó Nicholson. No modela el tiempo de colección finito del detector.
- El experimento B usa el segmentador del RTL para el `pico` (mismo umbral,
  misma histéresis, mismo recorte a cero), pero `boxcar` y `adaptado` son
  estimadores hipotéticos calculados sobre la matriz de muestras: no existen en
  el hardware. El `adaptado` busca el máximo sólo sobre lags enteros: su
  sesgo residual por fase (−0.02) es el error de tomar la autocorrelación en
  el entero más cercano, despreciable con pulsos de 250 muestras.
- La bipolar entra por el segmentador con el lóbulo negativo recortado a cero,
  como en la placa; para `boxcar` y `adaptado` se usa la traza sin recortar.

## Archivos

| archivo | qué |
|---|---|
| [`conformado.py`](../../software/monte-carlo/conformado.py) | los dos experimentos; guarda `resumen.json` y las dos figuras en `software/datos/conformado_<fecha>/` |
| [`test_conformado.py`](../../software/monte-carlo/test_conformado.py) | los índices contra Nicholson, el MC contra la fórmula, y las propiedades del experimento B |

## Bibliografía

- **P. W. Nicholson**, *Nuclear Electronics*, Wiley, 1974 — la figura de
  formas y S/N (reproducida como fig. 17.24 en Knoll).
- **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010 —
  cap. 17 (conformado de pulsos y ruido).
- **V. Radeka**, *Optimum signal-processing for pulse-amplitude spectrometry in
  the presence of high-rate effects and noise*, IEEE Trans. Nucl. Sci. **15**
  (1968) 455 — los índices de forma `A₁`, `A₂` y el cusp como óptimo.
- **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real
  time for high resolution radiation spectroscopy*, Nucl. Instrum. Methods A
  **345** (1994) 337 — el trapezoidal digital.
