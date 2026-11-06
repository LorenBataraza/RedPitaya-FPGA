# Fuentes de jitter en la cadena digital

Tenemos una conversión analógico-digital en la base del sistema. La palabra
*jitter* se usa para tres cosas distintas que conviene separar antes de sumar
nada:

1. **Jitter del clock de muestreo** (aleatorio, en ps): el instante real en que
   el ADC toma la muestra no es exactamente `n·Ts`.
2. **Fase de muestreo** (aleatoria pero *no* del clock, en ns): el pulso llega
   asincrónico al clock, así que dónde caen las muestras sobre el pulso es una
   variable uniforme en `[0, Ts)`.
3. **Jitter de estimación** (propagación del ruido de amplitud a tiempo, o de
   tiempo a amplitud): un umbral cruzado con ruido se cruza en un instante
   incierto; un instante incierto sobre una pendiente da una amplitud incierta.

Las tres terminan en el mismo lugar — ancho del fotopico y ancho de la
distribución de timestamps — pero tienen magnitudes que difieren en órdenes de
magnitud y se atacan con herramientas distintas. Este documento las pone en la
misma unidad y las ordena.

> El presupuesto del eje de **amplitud** —todas las fuentes de ruido, no sólo
> las que se parecen a jitter— está en
> [`../ruido_del_sistema.md`](../ruido_del_sistema.md). Este documento es el del
> eje de **tiempo**; las filas de amplitud de §6 y §7 de acá están ahí abiertas
> y medidas. Lo que sí está acá es **§5**: la varianza de cada estimador de
> amplitud sobre cada familia de forma, que es donde las tres clases de jitter
> de arriba se vuelven cuentas de ADC.

Números fijos del sistema:

| | |
|---|---|
| `Ts` | 8 ns (125 MSPS) |
| ADC | 14 bits, 1 LSB = 2 V / 16384 ≈ 122 µV |
| Ruido **por muestra**, medido ([`../ruido_del_sistema.md`](../ruido_del_sistema.md) §3) | σ_w = 4.47 cuentas (blanco) + σ_c = 0.87 (correlacionado, τ = 12 µs) |
| Ancho del fotopico con muestra de pico (§2.2 de [`decisiones_diseno_mca.md`](decisiones_diseno_mca.md)) | σ ≈ 2.8 cuentas, FWHM ≈ 6.6 canales sobre 1920 — **ya pasado por el estimador**, ver §5.3 |
| Fondo de escala del MCA | 8192 canales |

---

## 1. Cómo se suman

Si las fuentes son **independientes**, las varianzas se suman:

    σ_total² = σ_detector² + σ_electrónica²
    σ_electrónica² = σ_ADC² + σ_cuantización² + σ_fase² + σ_apertura² + σ_estimador² + …

y con todo gaussiano eso se escribe en FWHM:

    FWHM_total² = FWHM_detector² + FWHM_electrónica²          (FWHM = 2.355 σ)

Dos advertencias que se saltan siempre:

- **No todo es gaussiano.** La fase de muestreo y la cuantización son
  *uniformes*; el FWHM de una uniforme es su ancho completo, no `2.355 σ`. Lo que
  se suma en cuadratura son las **varianzas**; el FWHM del total sólo vale
  `2.355 σ_total` cuando hay suficientes términos comparables para que el
  resultado sea aproximadamente gaussiano (teorema central del límite) o cuando
  domina un término gaussiano. En la práctica domina el ruido del ADC, así que la
  regla FWHM funciona — pero por eso, no por principio.
- **No todo es independiente.** La fase de muestreo afecta a la vez al
  estimador de amplitud y al timestamp del mismo evento: sus errores están
  correlacionados. Para el fotopico no importa (sólo se mira amplitud), para una
  corrección de amplitud en función de tiempo sí.

---

## 2. Jitter del clock (apertura) — el que da nombre al tema y el que menos pesa

El ADC toma la muestra en `t_n = n·Ts + ε_n`, con `ε_n` gaussiano de desvío
`σ_t`. Tiene dos componentes en cuadratura: el jitter de apertura propio del ADC
(LTC2145-14: del orden de **0.1 ps rms** según hoja de datos) y el del oscilador
de 125 MHz que lo maneja (un XO de propósito general: **1–10 ps rms** integrado
en 12 kHz–20 MHz; verificar el componente que monta la placa). El del oscilador
manda.

Cómo llega el clock a cada lado, según el top
([`mca_red_pitaya_top.sv`](../../rtl/mine/tops/mca_red_pitaya_top.sv), líneas
~290–308): el oscilador de la placa maneja **directamente** al ADC y entra a la
FPGA por `adc_clk_i` (ADCLKP/N) → `IBUFDS` → PLL → `BUFG` → `adc_clk`. La salida
`adc_clk_o` está sin uso. Consecuencia: **el jitter del PLL de la FPGA no toca el
instante de muestreo.** Sólo mueve el flanco con el que la lógica captura los
datos ya convertidos, y para eso hay margen de setup/hold de sobra a 8 ns. El
único jitter que entra en la conversión es el del oscilador más la apertura del
ADC; lo demás es digital y determinista.

### Cómo se convierte en error de amplitud

Un error de tiempo sobre una señal con pendiente es un error de tensión:

    σ_v = |dV/dt| · σ_t

Para un pulso de amplitud `A` y tiempo de subida `t_r` (10–90 %) la pendiente
máxima es `≈ 0.8·A/t_r`. Con `A = 8192` cuentas (fondo de escala) y
`t_r = 100 ns`:

| σ_t | σ_v en el flanco | vs σ_ADC = 2.8 |
|---|---|---|
| 0.1 ps | 0.007 cuentas | nada |
| 1 ps | 0.07 cuentas | nada |
| 10 ps | 0.65 cuentas | 5 % del ruido, en cuadratura 2.7 % |

Y **en el pico `dV/dt = 0`**: el jitter del clock no mueve la muestra de pico a
primer orden. El estimador `cfg_amp_src = 0` es *inmune* al jitter de apertura;
sólo lo ven las muestras del flanco, o sea la integral (donde promedia `1/√N`) y
el timestamp.

La forma equivalente en dB, para comparar con la hoja de datos del ADC:

    SNR_jitter = −20·log10(2π · f_señal · σ_t)

con `f_señal ≈ 0.35 / t_r = 3.5 MHz` para `t_r = 100 ns`: 93 dB con 1 ps, 73 dB
con 10 ps. El LTC2145-14 tiene SNR ≈ 73 dB. O sea: **sólo con un oscilador
mediocre (10 ps) y en el flanco más rápido el jitter de apertura alcanza al piso
del ADC.** En todos los demás casos es despreciable, y a menos que aparezcan
pulsos con `t_r < 20 ns` no vale la pena medirlo.

### Estabilidad de frecuencia (ppm) — no es jitter, pero se confunde

Un XO tiene ±20–50 ppm de exactitud y deriva térmica. Eso **no ensancha nada**:
es un error de escala en el eje de tiempo. Afecta a

- los timestamps absolutos (`timestamp[63:0]` del event ring): 50 µs de error
  por segundo transcurrido,
- las medidas de tasa y tiempo muerto: 50 ppm relativos, invisible,
- coincidencias entre **dos placas** con clocks distintos: la diferencia de
  timestamps camina a 50 ppm × Δt, que en 1 ms ya son 50 ns. Para eso hace
  falta clock común, no mejor clock.

---

## 3. Fase de muestreo — el "jitter de muestreo" de los otros documentos

El pulso llega en un instante arbitrario respecto del clock. Llamando `φ` al
desplazamiento entre el máximo verdadero y la muestra más cercana:

    φ ~ Uniforme(−Ts/2, +Ts/2)        σ_φ = Ts/√12 = 2.31 ns

Esto no es ruido del clock: con un clock perfecto pasa igual. Es el efecto que
[`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) §5 llama *jitter de
muestreo* y es la razón de fondo por la que existe `cfg_amp_src`.

### Lo que se puede afirmar sin saber nada del ADC

La fase de muestreo **no depende del conversor**. Es geometría entre dos
relojes que no se hablan: el del pulso (el detector, o el pulser) y el de la
placa. Todo lo que sigue vale para cualquier ADC de 125 MSPS, y lo único que
cambiaría con otro conversor es `Ts`.

1. **Es una variable por evento, no por muestra.** Todas las muestras de un
   pulso comparten el mismo `φ`. No es ruido que promedie con `1/√N`: es un
   corrimiento rígido de la grilla. Por eso la integral no lo ve (sumar sobre
   una grilla corrida da lo mismo) y la muestra de pico lo ve completo (una
   sola muestra, una sola posición).
2. **Es uniforme, y eso es verificable.** Dos relojes libres con frecuencias
   inconmensurables barren todas las fases con la misma probabilidad. El
   estimador de fase de un evento sale de los propios datos, sin hardware
   extra: interpolar el cruce de umbral entre las dos muestras que lo encierran
   da `φ` con resolución sub-`Ts`. El histograma de ese `φ` sobre miles de
   eventos tiene que ser **plano** entre 0 y 8 ns. Si tiene estructura, o el
   interpolador está sesgado, o los relojes están acoplados.
3. **La trampa del acoplamiento.** Si el pulser y la placa compartieran
   referencia (el Rigol tiene entrada de 10 MHz; la Pitaya no la usa), `φ` sería
   una *constante* por configuración, no una variable: el histograma de fase
   sería un pico, el fotopico se afinaría artificialmente y el "jitter de
   muestreo" desaparecería de la medición sin haber desaparecido del sistema.
   Con un detector real nunca hay acoplamiento; con pulser hay que
   asegurarse de que tampoco. Hoy no lo hay: los relojes son independientes y la
   fase barre.
4. **La distribución del error de amplitud no es gaussiana.** Con `φ` uniforme
   y `δ ∝ φ²` (pico redondeado), el error tiene una densidad que se acumula en
   `δ = 0` y cae hacia el máximo: asimétrica, con sesgo hacia subestimar.
   Ensancha el fotopico *y* lo corre hacia abajo en `E[δ]`. El desplazamiento se
   calibra; el ancho no. Con `δ ∝ |φ|` (cúspide) el error es uniforme en
   `[0, A·Ts/2t_r]`, FWHM igual al ancho completo, sin cola.
5. **Se elimina por software, no por hardware.** Un clock mejor no cambia
   nada. Las opciones son: integrar (`cfg_amp_src = 1`), conformar para
   redondear el pico (`τ_c` grande), o interpolar el máximo con un ajuste
   parabólico sobre tres muestras — que recupera el pico verdadero a segundo
   orden y deja la muestra de pico casi tan buena como la integral para picos
   redondeados. Esta última no está en el RTL, pero es barata (una división
   por dos muestras y un cuadrado) y es la primera cosa a probar si hay que
   quedarse con el estimador de pico.

Lo que sí requiere hoja de datos es el jitter de apertura de §2 — y ése ya
quedó dos órdenes de magnitud por debajo de todo lo demás.

### Efecto sobre la muestra de pico

La muestra de pico subestima el máximo verdadero en una cantidad que depende de
`φ` y de la **forma del pico**. Dos casos límite:

**Pico redondeado** (parábola, `V(t) ≈ A·(1 − t²/2τ_c²)`, con `τ_c` el radio de
curvatura; para un pulso gaussiano `τ_c = σ_pulso`):

    δ(φ) = A·φ² / (2τ_c²)
    E[δ]  = A·Ts² / (24·τ_c²)               ← sesgo, no ensancha
    σ_δ   = A·Ts² / (2·√180·τ_c²) ≈ A·Ts² / (27·τ_c²)

**Pico en punta** (cúspide, pendientes `±A/t_r` a cada lado):

    δ(φ) = A·|φ| / t_r
    E[δ]  = A·Ts / (4·t_r)
    σ_δ   = A·Ts / (√48·t_r) ≈ A·Ts / (6.9·t_r)

Los números para `A = 1920` cuentas (el nivel del pulser en la campaña):

| Pulso | Parábola (τ_c) | σ_δ parábola | Cúspide (t_r) | σ_δ cúspide |
|---|---|---|---|---|
| 4 µs FWHM | 1.7 µs | 0.002 cuentas | 400 ns | 5.6 cuentas |
| 2 µs FWHM | 850 ns | 0.006 cuentas | 200 ns | 11 cuentas |
| 0.5 µs FWHM | 212 ns | 0.10 cuentas | 100 ns | 22 cuentas |

Lo medido al acortar el pulso de 4 µs a 0.5 µs fue FWHM 0.33 % → 0.44 %, o sea
σ 2.7 → 3.6 cuentas: **2.4 cuentas extra en cuadratura**. La parábola lo
subestima por 20×, la cúspide lo sobreestima por 10×.

> **Y ninguna de las dos es la explicación.** El Monte Carlo de §5 reproduce ese
> ensanchamiento —predice 0.30 % → 0.42 % contra 0.33 % → 0.44 % medidos— con el
> término de fase en **cero** en los dos extremos. Lo que cambia al angostar el
> pulso no es la fase: es cuántas muestras quedan sobre el ápice compitiendo por
> ser el máximo (§5.3). Las dos filas de la tabla de arriba siguen valiendo como
> cotas analíticas, y la de cúspide es la que manda para pulsos de detector sin
> conformar (§8); para el rango que da el ARB, el mecanismo correcto es el otro.

Regla práctica que sale de la tabla: mientras `Ts² / τ_c²` sea menor que
`σ_w / A` (acá `4.47/1920 ≈ 2.3e-3`), el estimador de pico no paga fase de
muestreo. Eso se cumple hasta `τ_c ≈ 170 ns`, es decir pulsos de ~0.4 µs de
FWHM con pico gaussiano. **Para pulsos más cortos, o con pico en punta (RC-CR
sin conformado), la integral tiene que ganar.**

### Efecto sobre la integral

La integral `Σ V(nTs + φ)` sobre una ventana que cubre todo el pulso es la
regla del rectángulo, y su error con la fase es exponencialmente chico para
señales de banda limitada muestreadas por encima de Nyquist. En la práctica es
cero: la integral **no ve la fase de muestreo**, salvo por dónde cae la ventana
(§4).

### Efecto sobre el timestamp

El timestamp es el ciclo de `adc_clk` en que se detectó el cruce del umbral: se
cuantiza a `Ts`. Error uniforme en un intervalo de `Ts`:

    σ_ts = Ts/√12 = 2.31 ns          FWHM = 8 ns (ancho completo de la uniforme)

Es el piso de resolución temporal **sin interpolar**. Con interpolación lineal
entre las dos muestras que encierran el umbral, el error de fase desaparece y
lo que queda es §4.

---

## 4. Jitter de estimación — ruido de amplitud convertido en tiempo, y vuelta

### Ruido → tiempo (cruce de umbral)

Un umbral `thr` sobre una señal con ruido `σ_v` se cruza en un instante que
fluctúa:

    σ_t = σ_v / |dV/dt|_{V = thr}

Es la fórmula clásica de timing por *leading edge*: el jitter temporal es el
ruido dividido por la pendiente **en el punto de cruce**. Con el ruido blanco
por muestra medido, `σ_w = 4.47` cuentas (**no** los 2.8, que son el ancho del
fotopico ya pasado por el estimador: ver §5.3), y `t_r = 100 ns`:

| Amplitud | Pendiente en el flanco | σ_t | vs σ_ts = 2.31 ns |
|---|---|---|---|
| 8192 (1 Vpp) | 65 cuentas/ns | 69 ps | despreciable |
| 1920 | 15 cuentas/ns | 0.30 ns | despreciable |
| 800 (0.1 Vpp) | 6.4 cuentas/ns | 0.70 ns | 9 % del total en cuadratura |
| 200 (cerca del umbral) | 1.6 cuentas/ns | 2.8 ns | **domina** |

Conclusión: **la resolución temporal del sistema está limitada por la
cuantización a `Ts`, no por el ruido**, en todo el rango dinámico salvo la
última década sobre el umbral. Interpolar entre muestras la mejora hasta
`σ_v/pendiente`, o sea a sub-ns para pulsos grandes, sin tocar el hardware.

Dos cosas que **no son jitter** pero aparecen en la misma distribución:

- **Walk de amplitud**: el instante de cruce de un umbral fijo depende de la
  amplitud (`t_cruce ≈ t_r · thr / (0.8·A)`). Es sistemático y se corrige
  conociendo `A`, o se elimina con un discriminador de fracción constante. El
  RTL actual no tiene CFD; el walk está en el timestamp y hay que corregirlo en
  software si importa. Además entra en la integral cerca del umbral y, en modo
  histéresis, en el **largo de la ventana**:
  [`ventana_de_medicion.md`](ventana_de_medicion.md) §5.
- **Latencia del pipeline**: el detector de cruce, el registro de timestamp y
  el CDC al bus agregan ciclos, pero **un número fijo** de ciclos. La lógica es
  síncrona con `adc_clk`; no agrega jitter. El único cruce de dominio
  (`sys_bus_cdc` hacia `clk_fpga_0`) está en el camino del bus, no del dato.

### Tiempo → amplitud (cierre de ventana)

La otra dirección de la misma fórmula. En modo histéresis (`cfg_gate_mode = 0`)
la ventana de integración cierra donde la cola cruza `thr − hyst`. La cola de
un pulso es la parte más chata, así que ahí `dV/dt` es mínima y `σ_t` máxima:

    σ_t,cierre = σ_v / |dV/dt|_{cola}

Con cola exponencial de constante `τ_d` y cierre a nivel `V_c = thr − hyst`, la
pendiente es `V_c / τ_d`. Para la cola real (`τ_d = 186` muestras = 1.49 µs) y
`V_c = 60` cuentas: `0.040 cuentas/ns` → `σ_t,cierre = 111 ns = 14 muestras`. La
integral suma o resta esas 14 muestras a nivel `~V_c`: `±840` cuentas de
`Q_total`, que para `Q_total = A·Σf ≈ 5.7e5` son **0.15 %** de la amplitud.

El Monte Carlo de §5 lo confirma y lo pone en su lugar: el término blanco de la
integral por histéresis es **0.085 %** contra 0.026 % de la compuerta fija, así
que el cierre que tiembla vale `√(0.085² − 0.026²) = 0.081 %` — la mitad de la
estimación de arriba, porque la fórmula ignora que el cierre tardío agrega
muestras que *también* traen señal. Y sobre todo: **no es el término que manda**.
El que manda es el error de línea de base multiplicado por un largo de ventana
que es el doble (§5.3).

Ese mecanismo es el "jitter del cierre de la ventana" de
[`resultados_validacion_hw.md`](../resultados_validacion_hw.md) §0.3, y es por lo
que existe `cfg_gate_mode = 1`: con compuertas de largo fijo desde el disparo,
la ventana hereda sólo la incertidumbre del cruce de **apertura** (`σ_t` del
flanco de subida, sub-ns) más la fase de muestreo (`±Ts/2`), y sus bordes caen
en zonas de pendiente ≈ 0 (línea de base antes, cola extinguida después), así
que el desplazamiento no cambia la suma.

---

## 5. Varianza de cada estimador, familia por familia

> **Las tablas de §5.1 a §5.6 son del MCA1**, con su ventana por histéresis y su
> disparo por nivel. Lo que cambia en el MCA2 (no hay histéresis, hay trapecio, y el
> disparo es por pendiente) está en §5.7.

Las secciones anteriores van fuente por fuente. Ésta cruza los dos ejes que
importan para elegir configuración: las **seis familias de forma** del catálogo
([`formas_de_pulso.md`](formas_de_pulso.md)) contra los **cuatro estimadores**
de amplitud, todos con el mismo ruido medido y la misma fase de muestreo. Los
números los calcula
[`varianza_estimadores.py`](../../software/monte-carlo/varianza_estimadores.py)
—48 000 eventos por familia, segmentados con las réplicas del RTL de
`pileup.py`— y las figuras son
[`12_varianza_estimadores.png`](figuras/12_varianza_estimadores.png) y
[`13_estimadores_vs_ancho.png`](figuras/13_estimadores_vs_ancho.png).

**Qué se inyecta.** El ruido no se postula: es el de
[`../ruido_del_sistema.md`](../ruido_del_sistema.md) §3, medido sobre el canal
que estaba en vacío, y entra en sus **dos** partes por separado —

    blanco          sigma_w = 4.47 cuentas por muestra, descorrelacionado a 8 ns
    correlacionado  sigma_c = 0.87 cuentas, tau = 12 us (proceso, no constante)

— más la fase de muestreo, barrida en una grilla uniforme de 32 sub-muestras.
En las tablas que siguen el término correlacionado aparece como columna
**«base»**, porque dentro de una ventana se comporta exactamente como un error
de línea de base por evento: es el mismo número sumado a todas las muestras.
Que el término correlacionado se simule como **proceso** y no como un offset
por evento no es cosmético: en 384 muestras promedia de 0.87 a 0.84 (−4 %) y en
las 1030 de la ventana por histéresis de la CR, a 0.78 (−10 %). Con un offset
constante ese término quedaría sobreestimado justo en las familias de cola
larga, que son las que se quieren comparar. Lo que el modelo **no** tiene es el
seguidor de línea de base del RTL, que baja el correlacionado a ~0.76 cuentas
(`ruido_del_sistema.md` §5): el término de base de acá es el de *antes* del
seguidor, pesimista por un 15 % conocido.

### 5.1 La geometría que decide cada estimador

Tres números por forma, todos con el mismo FWHM (250 muestras) y la misma
altura de pico (1920 cuentas):

| familia | Σf [muestras] | Σf/FWHM | Σf²/FWHM | `M_ef` | caída máx. [cuentas] | ventana histéresis |
|---|---|---|---|---|---|---|
| CR | 336 | 1.343 | 0.746 | 9 | 0.05 | 1029 ± 11 |
| CR-RC | 278 | 1.111 | 0.755 | 14 | 0.02 | 634 ± 5 |
| CR-RC⁴ | 269 | 1.076 | 0.753 | 14 | 0.02 | 569 ± 4 |
| triangular | 250 | 1.000 | 0.667 | **1** | **3.84** | 479 ± 1 |
| trapezoidal | 250 | 1.000 | 0.833 | **126** | 0.00 | 365 ± 1 |
| bipolar | 245 | 0.979 | 0.747 | 15 | 0.02 | 404 ± 1 |
| referencia (ARB real) | 298 | 1.192 | 0.759 | 13 | 0.02 | 771 ± 7 |

- **`Σf` = área/pico** es lo que multiplica a la amplitud en cualquier integral.
  Dividido por el FWHM da exactamente el **factor de forma** que midió la
  campaña (1.343, 1.111, 1.076, 1.000, 1.000, 0.979): la geometría de acá y la
  onda que vio la placa son la misma función.
- **`Σf²` es la única geometría que entra en la cota de Cramér-Rao.** Y acá
  aparece el primer resultado que no es obvio: `Σf²/FWHM` vale **0.75 ± 0.08
  para las seis**. A igual FWHM y igual pico, **ninguna forma del catálogo es
  intrínsecamente más medible que otra** — el mejor estimador posible da lo
  mismo con todas, dentro de un 10 %. Todo lo que las separa en las tablas que
  siguen lo pone el **estimador**, no la forma.
- **`M_ef`** es cuántas muestras caen a menos de un ruido (4.47 cuentas) del
  ápice. Va de **1** (triangular) a **126** (trapezoidal), y es lo que decide el
  estimador de pico: ver §5.3.
- **caída máxima** es cuánto se pierde el pico por la fase de muestreo en el
  peor caso. Salvo la triangular, **no llega a 1/80 del ruido**: a 2 µs y
  125 MSPS la fase de muestreo no existe para ninguna familia redondeada.

### 5.2 El resultado: resolución por familia y estimador

Resolución = FWHM/centroide en %, con `A = 1920` cuentas y pulso de 2 µs:

| familia | pico | pico interp. | Q histéresis | Q fija 384 | cota C-R |
|---|---|---|---|---|---|
| CR | 0.353 | 0.358 | 0.460 | **0.186** | 0.040 |
| CR-RC | 0.330 | 0.338 | 0.310 | **0.169** | 0.040 |
| CR-RC⁴ | 0.331 | 0.335 | 0.267 | **0.203** | 0.040 |
| triangular | 0.472 | 0.476 | **0.209** | 0.262 | 0.042 |
| trapezoidal | 0.264 | 0.269 | **0.161** | 0.163 | 0.038 |
| bipolar | 0.328 | 0.330 | 0.180 | **0.168** | 0.040 |
| referencia (ARB real) | 0.339 | 0.342 | 0.379 | **0.175** | 0.040 |

Tres lecturas inmediatas:

1. **La compuerta fija gana en cinco de las siete**, y donde no gana (triangular
   y trapezoidal) pierde por nada contra la histéresis. Es la misma conclusión
   que el análisis offline sacó para una sola forma, ahora sobre todo el
   catálogo.
2. **El rango entre familias es un factor 1.8 con el mismo estimador** (pico:
   0.264 % el trapecio, 0.472 % la triangular). Elegir la forma importa tanto
   como elegir el estimador.
3. **Todos están entre 4× y 11× de la cota.** El instrumento no está limitado
   por la información que tiene el pulso: está limitado por lo que el estimador
   tira a la basura.

### 5.3 De qué está hecha cada varianza

σ/A en %, separada en sus tres términos por ANOVA sobre la grilla de fases
(dentro de cada bin de fase = ruido; entre bins = fase):

**Muestra de pico** (`cfg_amp_src = 0`)

| familia | blanco | base | fase | **σ total** | sesgo |
|---|---|---|---|---|---|
| CR | 0.141 | 0.046 | 0.001 | **0.148** | +0.28 % |
| CR-RC | 0.132 | 0.044 | 0.000 | **0.139** | +0.34 % |
| CR-RC⁴ | 0.131 | 0.044 | 0.002 | **0.138** | +0.34 % |
| triangular | 0.194 | 0.043 | **0.029** | **0.200** | −0.03 % |
| trapezoidal | 0.098 | 0.044 | 0.001 | **0.108** | +0.60 % |
| bipolar | 0.129 | 0.047 | 0.000 | **0.137** | +0.35 % |
| referencia | 0.132 | 0.048 | 0.002 | **0.141** | +0.33 % |

**Integral, compuerta fija de 384** (`gate_mode = 1`)

| familia | blanco | base | fase | **σ total** | sesgo |
|---|---|---|---|---|---|
| CR | 0.023 | 0.069 | **0.029** | **0.078** | −27.7 % |
| CR-RC | 0.025 | 0.066 | 0.015 | **0.072** | −11.0 % |
| CR-RC⁴ | 0.062 | 0.057 | 0.001 | **0.084** | −9.2 % |
| triangular | 0.098 | 0.056 | 0.000 | **0.113** | −8.6 % |
| trapezoidal | 0.020 | 0.067 | 0.000 | **0.070** | −0.1 % |
| bipolar | 0.019 | 0.069 | 0.002 | **0.071** | −0.6 % |
| referencia | 0.026 | 0.066 | 0.018 | **0.073** | −17.0 % |

**Integral, ventana por histéresis** (`gate_mode = 0`)

| familia | blanco | base | fase | **σ total** | ventana |
|---|---|---|---|---|---|
| CR | 0.110 | 0.163 | 0.004 | **0.197** | 1029 |
| CR-RC | 0.065 | 0.117 | 0.004 | **0.133** | 634 |
| CR-RC⁴ | 0.051 | 0.106 | 0.000 | **0.117** | 569 |
| triangular | 0.026 | 0.086 | 0.001 | **0.089** | 479 |
| trapezoidal | 0.021 | 0.066 | 0.001 | **0.069** | 365 |
| bipolar | 0.022 | 0.074 | 0.004 | **0.078** | 404 |
| referencia | 0.085 | 0.134 | 0.004 | **0.159** | 771 |

#### El término blanco del pico es un máximo de `M_ef` gaussianas

Es el punto donde el documento estaba equivocado antes de esta sección. La
muestra de pico **no** paga `σ_w` de ruido: el RTL se queda con el **máximo**
de las muestras de la ventana, y cerca del ápice hay `M_ef` muestras que
compiten por serlo. El máximo de `M` gaussianas tiene desvío **menor** que una
sola y media **mayor**:

| `M` | sd(max)/σ | E[max]/σ |
|---|---|---|
| 1 | 1.00 | 0.00 |
| 9 | 0.60 | +1.49 |
| 13 | 0.56 | +1.67 |
| 126 | 0.42 | +2.59 |

Eso explica las dos columnas de la tabla del pico de una sola vez, sin ningún
parámetro libre:

| familia | `M_ef` | σ_blanco medida / σ_w | sd(max)/σ esperado | sesgo medido | E[max] esperado |
|---|---|---|---|---|---|
| triangular | 1 | 0.83 | 1.00 | −0.03 % | 0.00 % |
| CR | 9 | 0.61 | 0.60 | +0.28 % | +0.35 % |
| referencia | 13 | 0.57 | 0.56 | +0.33 % | +0.39 % |
| trapezoidal | 126 | 0.42 | 0.42 | +0.60 % | +0.60 % |

El acuerdo es del 5 % donde el ápice es realmente plano y se afloja en la
triangular (0.83 medido contra 1.00): con `M_ef = 1` el modelo de "M muestras
a la misma altura" deja de valer —las vecinas están por debajo del pico, pero
no tanto como para no competir nunca—, así que da una cota de arriba. En las
otras tres el ápice es chato en la escala del ruido y la fórmula es exacta.

**El trapecio no gana por tener techo plano: gana porque el techo plano le da
126 muestras para promediar implícitamente en el máximo.** Y paga ese promedio
con un sesgo de +0.60 % de la amplitud, que es constante en cuentas (2.6 σ_w) y
por lo tanto se va en el *offset* de la calibración, no en la ganancia — ver
§5.4.

> **Corrección a §3.** Lo medido al acortar el pulso de 4 µs a 0.5 µs
> (resolución con pico 0.33 % → 0.44 %) **no es fase de muestreo**: el barrido
> de [`13_estimadores_vs_ancho.png`](figuras/13_estimadores_vs_ancho.png) da
> σ 0.128 % → 0.177 % con el término de fase en **0.000 %** en los dos
> extremos. Lo que cambia es `M_ef`: al angostar el pulso quedan menos muestras
> sobre el ápice y el máximo deja de promediar. La predicción en FWHM es
> 0.30 % → 0.42 % contra 0.33 % → 0.44 % medidos. El mecanismo de §3 (parábola
> contra cúspide) es el correcto para pulsos **mucho** más cortos; en el rango
> que da el ARB, el que manda es éste.

#### El término de base es el largo de la ventana, no el cierre

En los dos estimadores de carga el término correlacionado domina, y su tamaño
es casi exactamente `N·σ_c/(A·Σf)` — el offset de base multiplicado por cuántas
muestras se suman. Para la forma real con compuerta fija: `384 × 0.84 /
(1920 × 298) = 0.056 %` contra **0.066 %** simulado, y el resto lo pone el
borde de la ventana.

Eso reordena la explicación de por qué la ventana por histéresis pierde. Con el
mismo ruido y la misma forma:

| | histéresis | compuerta fija | cociente |
|---|---|---|---|
| largo de ventana | 771 muestras | 384 | 2.0× |
| término blanco (cierre que tiembla) | 0.085 % | 0.026 % | 3.3× |
| término de base (N × σ_c) | 0.134 % | 0.066 % | 2.0× |
| **σ total** | **0.159 %** | **0.073 %** | **2.2×** |

El jitter del cierre de la ventana —el mecanismo de §4— es real y vale 0.081 %
en cuadratura, pero **el término más grande es el otro**: la ventana por
histéresis es el doble de larga, y el ruido correlacionado se suma proporcional
al largo. Las dos cosas van en la misma dirección y por eso la histéresis
pierde el doble, que es el ×2.02 medido en placa.

La familia lo confirma: la CR, con la cola más larga del catálogo, abre una
ventana de **1029** muestras y es la peor de las seis con histéresis (0.197 %);
el trapecio, que cierra en 365, es la mejor (0.069 %). **El largo de la ventana
ordena la tabla.**

#### El término de fase es cero salvo en la triangular

A 2 µs y 125 MSPS, con la única excepción de la triangular (0.029 %, que es el
ápice en punta de `M_ef = 1`), la fase de muestreo **no se mide**: queda por
debajo de 0.005 % de la amplitud en las seis familias y en los dos estimadores
de pico. La predicción analítica de §3 para pico redondeado (0.006 cuentas a
2 µs) es consistente con eso.

Aparece en cambio donde no se la espera: en la **compuerta fija**, 0.029 % para
la CR y 0.018 % para la forma real. No es el ápice — es el **borde** de la
compuerta, que cae en una cola que todavía tiene pendiente, así que medio
sample de corrimiento cambia la carga sumada. Es chico, pero es el único lugar
donde la fase sobrevive a 2 µs.

#### El pico interpolado no sirve acá

Interpolar el máximo con una parábola de tres puntos —la propuesta de §3— da
**exactamente lo mismo** que la muestra cruda en las seis familias (0.138 vs
0.139 %, diferencias dentro del error del Monte Carlo). Es consistente: corrige
el error de fase, y a 2 µs el error de fase ya es cero. Peor todavía, en el
barrido de ancho **empeora** cuando el ápice es asimétrico — CR a 0.1 µs:
0.754 % contra 0.426 % de la muestra cruda — porque tres puntos de un flanco
abrupto no definen ninguna parábola. **No vale la pena ponerlo en el RTL** salvo
que aparezcan pulsos simétricos de menos de 0.2 µs.

### 5.4 Sesgo, déficit balístico y linealidad

Los sesgos de las tablas de §5.3 son grandes —hasta −27.7 %— y hay que leerlos
con cuidado, porque **sesgo no es resolución**:

- **La compuerta fija de 384 no cubre la cola de las familias largas.** La CR
  tiene `Σf = 336` repartidas sobre 3380 muestras: la compuerta se queda con el
  72 % de la carga. Es **déficit balístico**, y es una pérdida de *ganancia*, no
  de resolución (la σ/A de la tabla ya está normalizada al centroide medido).
- **El sesgo del pico es el `E[max]` de §5.3**, constante en cuentas.

Que un sesgo sea constante en cuentas o proporcional a la amplitud es lo que
decide si ensucia la **linealidad**. Corriendo el mismo barrido de 12
amplitudes que la campaña de formas (0.1 → 1.0 Vpp) y midiendo la INL con la
misma definición (residuo máximo del ajuste lineal, en % del rango):

| familia | pico | Q histéresis | Q fija 384 | **INL medida en placa** |
|---|---|---|---|---|
| CR | 0.01 | 0.01 | 0.01 | **1.08** |
| CR-RC | 0.01 | 0.04 | 0.02 | **1.09** |
| CR-RC⁴ | 0.01 | 0.07 | 0.27 | **1.09** |
| triangular | 0.03 | 0.17 | 0.28 | **1.04** |
| trapezoidal | 0.00 | 0.09 | 0.06 | **1.09** |
| bipolar | 0.01 | 0.09 | 0.03 | — |

**El estimador aporta entre 0.00 y 0.28 % FS de INL; lo medido es 1.04–1.09 %.**
Queda confirmado lo que la campaña de formas sospechaba y no podía demostrar:
**la INL que se mide es del generador**, no del MCA. El residuo que deja el
estimador está entre 4 y 100 veces por debajo, y —esto es lo que la vuelve una
predicción falsable— **no depende de la familia**, mientras que la medida sí
tendría que depender si fuera del instrumento.

### 5.5 Validación contra los pulsos reales

La fila `referencia` no es una forma de Knoll: es la forma real del estímulo,
con el FWHM y la cola medidos. Corrida a la amplitud del conjunto real
(2415 cuentas), sus predicciones contra lo medido **sobre esas mismas trazas**:

| estimador | predicho | offline, mismas trazas | cociente | en placa |
|---|---|---|---|---|
| pico | 0.272 % | 0.272 % | **1.00×** | 0.344 % |
| Q histéresis | 0.310 % | — | — | 0.325 % |
| Q fija 384 | 0.148 % | 0.149 % | **0.99×** | 0.161 % |

Los dos que tienen con qué compararse cierran dentro del 1 %, y el tercero
dentro del 5 % contra la placa. No hay parámetros ajustados: el ruido sale de
§3 de [`../ruido_del_sistema.md`](../ruido_del_sistema.md), la forma de la
campaña y los estimadores del RTL. El hueco que queda contra el hardware
(+26 % en el pico, +9 % en la compuerta) es el mismo que el presupuesto de
amplitud ya tiene identificado y acotado.

### 5.6 Qué elegir, con los números en la mano

- **Con el estímulo de hoy (2 µs), compuerta fija.** Es 1.9× mejor que el pico
  en la forma real y gana en cinco de las siete familias. El largo hay que
  ponerlo en función de la **cola**, no del FWHM: 384 muestras alcanzan para el
  trapecio y la bipolar, y se comen el 28 % de la carga de la CR.
- **Si hay que quedarse con el pico, conformar a techo plano.** El trapecio da
  0.264 % contra 0.472 % de la triangular con el mismo FWHM y la misma altura,
  y la diferencia es entera de `M_ef`.
- **No gastar RTL en interpolar el pico.** No mejora nada a 2 µs y empeora en
  ápices asimétricos.
- **La palanca grande no es el estimador: es la base.** Los cuatro estimadores
  están entre 4× y 11× de la cota, y en el mejor de ellos el 80 % de la
  varianza es el término correlacionado de 0.87 cuentas. Seguir la línea de
  base es lo único que lo baja, y eso está en
  [`../ruido_del_sistema.md`](../ruido_del_sistema.md) §5.

Para rehacer cualquiera de estos números:

```bash
cd prj/MCA/software
python3 monte-carlo/varianza_estimadores.py --mapa MCA1   # estas tablas + figuras 12 y 13
python3 monte-carlo/varianza_estimadores.py               # las de §5.7 + figuras *_mca2
python3 monte-carlo/varianza_estimadores.py --amp 480     # otra amplitud
python3 monte-carlo/varianza_estimadores.py --fwhm 5e-7
```

### 5.7 En el MCA2

El mismo estudio sobre [`replica_mca2.py`](../../software/monte-carlo/replica_mca2.py):
una ranura, la compuerta de 384 y el disparo por pendiente L = 8, G = 4, con `pre_dly`
ajustado para que la ventana abra en el pie de un pulso de 1920 cuentas. Son 48 000
eventos por familia, con el mismo ruido. La integral por histéresis ya no existe, y
entra el trapecio, con k = FWHM/4 = 62, m = FWHM = 250 y el polo-cero de la cola de cada
forma, si la tiene.

Resolución = FWHM/centroide en %, con `A = 1920` cuentas y pulso de 2 µs:

| familia | pico | pico interp. | Q fija 384 | trapecio | cota C-R |
|---|---|---|---|---|---|
| CR | 0.353 | 0.358 | **0.193** | 0.200 | 0.040 |
| CR-RC | 0.330 | 0.338 | 0.184 | **0.141** | 0.040 |
| CR-RC⁴ | **0.331** | 0.335 | 0.605 | — | 0.040 |
| triangular | 0.472 | 0.476 | **0.319** | — | 0.042 |
| trapezoidal | 0.264 | 0.269 | 0.162 | **0.147** | 0.038 |
| bipolar | 0.328 | 0.330 | 0.172 | **0.149** | 0.040 |
| referencia (ARB real) | 0.339 | 0.342 | 0.180 | **0.149** | 0.040 |

Lo que dice:

1. **El pico no cambió.** La columna es la de §5.2, número por número: el máximo de la
   ventana no depende de quién la abre. Sirve de control de que el modelo de ruido y
   las formas son los mismos.
2. **Donde cabe, el trapecio es el mejor estimador**: 0.149 % contra 0.180 % de la
   integral en la forma real. Mejora el término de base (0.055 contra 0.067), que es el
   dominante, y no tiene término de fase. Es una predicción: falta medirlo con un
   espectro en la placa.
3. **En la CR-RC⁴ y la triangular no cabe.** Con estos k y m la meseta no entra en una
   compuerta de 384. La forma necesitaría una compuerta más larga.
4. **La integral empeora en las formas de pie lento, por el disparo.** En la CR-RC⁴ pasa
   de 0.203 % a 0.605 %, y en la triangular de 0.262 % a 0.319 %. El disparo por pendiente
   baila 1.4 muestras en la CR-RC⁴, y la compuerta cierra en pleno flanco, donde la carga
   cambia 810 cuentas por muestra: eso da 0.26 % de σ, contra 0.27 % medido sobre el mismo
   lote. Con las formas de pie rápido, y con el pulso de la campaña, la integral queda
   como estaba (0.180 % contra 0.175 %).

Sobre los pulsos reales (2415 cuentas), el predicho contra lo medido con el MCA1:

| estimador | predicho | offline, mismas trazas | cociente | en placa, MCA1 |
|---|---|---|---|---|
| pico | 0.272 % | 0.272 % | **1.00×** | 0.344 % |
| Q fija 384 | 0.158 % | 0.149 % | **1.06×** | 0.161 % |
| trapecio | 0.119 % | — | — | — |

La INL que pone el estimador sigue siendo despreciable contra el ~1.08 % medido: a lo sumo
0.04 %, salvo la integral de la CR-RC⁴, que llega a 0.20 %.

Figuras: [`12_varianza_estimadores_mca2.png`](figuras/12_varianza_estimadores_mca2.png) y
[`13_estimadores_vs_ancho_mca2.png`](figuras/13_estimadores_vs_ancho_mca2.png).

---

## 6. Lo que no es jitter pero entra en la misma cuadratura

| Fuente | Distribución | σ | Comentario |
|---|---|---|---|
| Cuantización del ADC | uniforme, 1 LSB | 0.29 cuentas | Un 1 % del ruido total en cuadratura. No es el piso |
| Ruido del ADC + front-end | gaussiano, **blanco** | 4.47 cuentas **por muestra** (los 2.8 son el ancho del fotopico, ya pasado por el estimador) | **El piso del estimador de pico.** El generador no aporta: [`../ruido_del_sistema.md`](../ruido_del_sistema.md) §3 |
| Ruido correlacionado del front-end | τ ≈ 12 µs | 0.87 cuentas | **No promedia en la ventana**, así que es el piso del estimador de *integral*: [`../ruido_del_sistema.md`](../ruido_del_sistema.md) §5 |
| Error de línea de base | lento, correlacionado | depende de `cfg_bl_*` | Sistemático por evento; en la integral se multiplica por N |
| Deriva del centroide | determinista, horas | — | No ensancha una adquisición corta; domina las largas: [`limites_resolucion_y_deriva.md`](limites_resolucion_y_deriva.md) |
| Binning del histograma | uniforme, 1 canal | 0.29 canales | Corrección de Sheppard, ya tratada en el mismo documento |

---

## 7. Presupuesto y cómo medir cada término

Resumen para `A = 1920` cuentas, `t_r = 100 ns`, pulso de 2 µs, `σ_t,clk = 1 ps`:

| Fuente | Afecta a | σ (amplitud) | σ (tiempo) | Se mide con |
|---|---|---|---|---|
| Ruido blanco del front-end | todo | **4.47 cuentas por muestra**; 2.5 en el pico (máximo de `M_ef`), 0.5 en la compuerta fija (÷√384) | 0.30 ns | Autocovarianza de la base, canal en vacío ([`../ruido_del_sistema.md`](../ruido_del_sistema.md) §3) — el RMS solo no alcanza |
| Ruido correlacionado (τ = 12 µs) | sobre todo la integral | 0.87 cuentas; **no promedia**: 1.3 cuentas en la compuerta fija (§5.3) | — | La misma autocovarianza: es la meseta que no baja |
| Fase de muestreo, pico | `cfg_amp_src = 0` | < 0.02 cuentas en 5 de 6 familias; **0.56 cuentas en la triangular** (§5.3) | — | Barrido de ancho de pulso (§5, figura 13); forma del ápice con el osciloscopio |
| Fase de muestreo, compuerta | `gate_mode = 1` | 0.35 cuentas (borde de la ventana, CR) | — | Lo mismo, columna «fase» de §5.3 |
| Fase de muestreo, timestamp | timestamp | — | 2.31 ns | Histograma de `φ` interpolado del cruce de umbral: tiene que ser plano entre 0 y 8 ns (`ts` solo no la ve, está cuantizado) |
| Apertura + clock | flanco, integral | 0.07 cuentas | 1 ps | No vale la pena; sólo si aparecen `t_r < 20 ns` |
| Cierre de ventana (histéresis) | `cfg_amp_src = 1`, `gate_mode = 0` | 0.081 % de A (1.6 cuentas) | 111 ns | Barrido `gate_mode` 0 vs 1 sobre el mismo estímulo (hecho: ×2.02 en placa) |
| Largo de la ventana × base | `cfg_amp_src = 1`, `gate_mode = 0` | **0.134 % de A** — el término más grande de la histéresis (§5.3) | — | Mismo barrido; se separa simulando con `σ_c = 0` |
| Walk de amplitud | timestamp | — | sistemático, hasta `t_r·thr/A` | `ts` vs amplitud con el pulser barrido |

Suma en cuadratura, para la forma real: **2.7 cuentas con la muestra de pico**
(0.339 % FWHM) y **1.5 con la compuerta fija** (0.175 %), contra 0.344 % y
0.161 % medidos. El presupuesto cierra dentro del 10 % y el desglose completo,
familia por familia, está en §5. Eso quiere decir dos cosas:

1. **No hay nada que ganar mejorando el clock.** Ni oscilador externo, ni PLL de
   bajo jitter, ni CDC más prolijo cambian el fotopico.
2. ~~**Sí hay algo que ganar separando el ruido del ADC del ruido del pulser**,
   porque hoy los 2.8 son la suma de los dos y no sabemos cuál domina.~~
   **Hecho, y con datos que ya estaban tomados**: el canal 2 de la campaña
   estaba en vacío, y da el mismo ruido que el canal con el Rigol colgado. **El
   generador no aporta nada medible.** De paso, el RMS solo no alcanzaba: lo que
   decide el presupuesto es la **autocovarianza**, porque el ruido no es blanco.
   Ver [`../ruido_del_sistema.md`](../ruido_del_sistema.md) §3.

### Medir el jitter temporal sin que el generador contamine

Con un solo canal, el histograma de timestamps contra un pulser periódico mezcla
el jitter del sistema con el del generador. La forma de sacarlo: **partir la
misma señal a las dos entradas** (`IN1`, `IN2`) y mirar la distribución de
`ts₁ − ts₂`. El jitter del generador es común y se cancela; lo que queda es
`√2·σ_t,sistema` más la fase de muestreo — que también es común si ambos canales
comparten `adc_clk`, en cuyo caso sólo queda el término de ruido de §4 y la
diferencia tiene que salir **casi siempre 0 ciclos**, con un ±1 en la fracción
de eventos que la fórmula de `σ_t` predice. Es una verificación falsable de toda
la sección 4 con hardware que ya está.

---

## 8. Qué cambia si aparecen pulsos de detector reales

Todo lo anterior está calibrado con `t_r = 100 ns` y picos redondeados de 2 µs,
que es lo que da el ARB. Un preamplificador de carga sin conformar entrega
`t_r` de 10–50 ns y **pico en punta** (subida rápida, decaimiento exponencial):
justo el caso donde la fila "cúspide" de §3 manda. Ahí:

- la muestra de pico paga `A·Ts/(6.9·t_r)`: con `t_r = 20 ns`, **6 % de A**.
  Inaceptable; hay que ir a integral o conformar antes;
- el jitter de apertura sube a `0.8·A/t_r · σ_t`: con 10 ps y `t_r = 20 ns`,
  3.3 cuentas a fondo de escala. Empieza a asomar sobre el ruido, y ahí sí
  conviene saber qué oscilador hay en la placa;
- el timing mejora: `σ_v/pendiente` baja a decenas de ps, y la cuantización a
  `Ts` pasa a ser la única barrera. Interpolar el cruce vale la pena.

El conformado digital ([`formas_de_pulso.md`](formas_de_pulso.md)) mueve el
sistema de vuelta al régimen "pico redondeado" a costa de tiempo muerto, y es la
palanca que arbitra entre las tres filas.
