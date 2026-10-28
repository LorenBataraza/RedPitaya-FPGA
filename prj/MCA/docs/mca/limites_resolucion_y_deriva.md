# Límites de resolución del MCA, y por qué el que ata es la deriva

Este documento junta los límites que acotan lo que el MCA puede distinguir, los
pone **todos en la misma unidad** (fracciones de FWHM) y muestra que están
separados por órdenes de magnitud. La conclusión es que ni el contador, ni el
binning, ni la cantidad de canales son la restricción activa: **es la deriva del
centroide**, por un factor 38 sobre su propia tolerancia.

Los números salen de la campaña de [§14.1b](../resultados_validacion_hw.md) y de
fórmulas recalculadas en
[`figuras/figuras_limites.py`](figuras/figuras_limites.py), que también genera
las tres figuras. Si el documento y una figura no coinciden, es un bug del
script.

![jerarquía de límites](figuras/08_jerarquia_limites.png)

---

## 1. Tres límites que se confunden todo el tiempo

|                                    | Qué es                                                                                             | ¿Las cuentas lo mejoran?                           |
| ---------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Resolución instrumental (FWHM)** | El ancho del pico de un pulser: es el ruido de la cadena                                           | **No.** Nunca                                      |
| **Pérdida por binning**            | El histograma discretiza y eso agrega varianza                                                     | No: se arregla con más canales, no con más cuentas |
| **Poder resolutivo estadístico**   | Sabiendo que hay dos gaussianas de ancho conocido, con qué separación se puede afirmar que son dos | **Sí**, pero lentísimo                             |

Casi todas las discusiones sobre "cuántos canales necesito" mezclan las tres. Van
por separado en las secciones 2, 3 y 4.

---

## 2. Pérdida por binning: la regla de 4–10 canales por FWHM, derivada

Medir una variable continua y guardarla en bins de ancho Δ agrega varianza. La
**corrección de Sheppard** dice cuánta:

    σ_ef² = σ² + Δ²/12

Con Δ = 1 canal, la inflación de σ depende sólo de cuántos canales entran en un
FWHM:

| canales / FWHM | 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| σ inflado | 20.9 % | 5.6 % | **1.4 %** | 0.36 % | 0.09 % |

**De ahí sale la regla de 4–10 canales por FWHM** que se cita siempre sin
justificar: por debajo de 4 la discretización empieza a costar más del 1.4 %, y
por encima de 10 ya no queda nada que recuperar.

Dónde está el MCA, sobre un eje de 8192 canales usado a fondo de escala (modo
compuerta fija, datos de §14.1b reescalados):

| Amplitud | Centroide | FWHM (canales) | σ inflado |
|---|---|---|---|
| 0.10 Vpp | 806 | 6.31 | **0.58 %** |
| 0.51 Vpp | 4093 | 6.62 | 0.53 % |
| 1.00 Vpp | 8191 | 8.64 | **0.31 %** |

Entre 6.3 y 8.6 canales por FWHM en toda una década de amplitud, o sea **dentro
de la regla en todo el rango** y tirando menos del 0.6 %. La
[figura de la sección 5](#el-zoom-no-mejora-el-poder-resolutivo) muestra lo mismo
medido como información de Fisher en vez de como inflación de σ, y da la misma
respuesta: en esa banda ya sobrevive el 98–99 %.

> **Corolario que conviene tener escrito:** más canales no es una decisión de
> diseño, es una **consecuencia** de mejor resolución. Con la resolución medida
> (0.106 % de FWHM/centroide) el rango justificado es `FS/FWHM × (4..10)` =
> **3800 a 9500 canales**. Para justificar 14 bits harían falta 0.06 % de
> resolución, el doble de lo que hay. Eso lo da el conformado trapezoidal o un
> frente de menos ruido, no más bins.

---

## 3. Poder resolutivo estadístico: información de Fisher

La pregunta precisa es: dadas N cuentas de una mezcla de dos gaussianas iguales
de ancho σ separadas `2d`, ¿con qué `d` mínimo se puede afirmar que son dos y no
una sola más ancha?

![qué compran las cuentas](figuras/14_cuentas_vs_separacion.png)

**(a)** Un doblete separado 1.2 FWHM, histogramado con 6 canales/FWHM —el
bineado del MCA— con N creciente. Con 100 cuentas no hay nada que afirmar; con
10³ asoma el valle; de 10⁴ en adelante son dos picos y no se discute. Es lo que
uno espera que compren las cuentas.
**(b)** La misma secuencia con el doblete separado **0.13 FWHM**. En ninguna N se
ve nada: la mezcla verdadera y la gaussiana única de los mismos momentos se
superponen en los cinco paneles. Éste es el caso que gobierna el límite, y el
ojo nunca lo resuelve.
**(c)** Por qué (b) no es un callejón sin salida: la significancia con que un
estimador óptimo detecta la separación crece como `√N`, así que el doblete
invisible de (b) cruza los 3σ en **N ≈ 9.3 × 10³**. Lo que crece con las cuentas
no es el valle: es la evidencia.

Dos lecturas que conviene no saltear:

- **De dónde sale el exponente ¼, leído en (c).** A `d` fijo la significancia
  sube como `√N` —pendiente ½ en el log-log—, pero la significancia es
  proporcional a `d²`. Pedir que cruce un umbral fijo deja `d² ∝ N^(−1/2)`, o
  sea `d ∝ N^(−1/4)`. El ¼ es el ½ de siempre, dividido por el 2 del exponente
  con que `d` entra.
- **(c) es un techo, no una predicción de lo que verías.** Es la cota de
  Cramér-Rao con σ y posición conocidos: lo mejor que puede hacer cualquier
  método. El ojo, que además tiene que estimar ancho y posición, llega mucho más
  tarde — a N = 10² la cota ya marca 13σ para el doblete ancho y el panel de (a)
  correspondiente es puro ruido. La brecha entre (a) y (c) **es** la diferencia
  entre el óptimo y lo ingenuo que se cuantifica más abajo.

### La derivación

La densidad es `p(x) = ½[φ(x−d) + φ(x+d)]` (con σ = 1). Desarrollando para `d`
chico, `φ(x∓d) ≈ φ(x) ∓ dφ'(x) + (d²/2)φ''(x)`, así que los términos impares se
cancelan y queda

    p(x) ≈ φ(x) + (d²/2)·φ''(x)          ∂p/∂d ≈ d·φ''(x)

La información de Fisher por muestra, usando `φ'' = (x²−1)φ`:

    I(d) = ∫ (∂p/∂d)²/p dx ≈ d² ∫ (x²−1)² φ dx = d²·E[(x²−1)²] = 2d²

Cramér-Rao da entonces `σ_d ≥ 1/(d√(2N))`. Pidiendo detección a 3σ (`d > 3σ_d`):

    d_min = √3 / (2N)^(1/4) = 1.73 / (2N)^(1/4)     ∝  N^(-1/4)

**La separación detectable mejora como la raíz CUARTA de las cuentas.** Para
duplicar el poder resolutivo hacen falta **16×** más cuentas.

El desarrollo completo —qué objeto es la información de Fisher, por qué este
problema en particular da raíz cuarta y no la raíz cuadrada de siempre, y qué
supone cada paso— está en el
[apéndice A](#apéndice-a-información-de-fisher-en-detalle).

### Y en la práctica se hace peor

La cota supone el estimador óptimo. Un estimador basado en momentos —mirar el
exceso de curtosis, que para esta mezcla vale `−2(d/σ)⁴`— sólo alcanza `N^(-1/8)`.
Verificado por Monte-Carlo:

| N | `d_min` medida con curtosis | Cota óptima (Cramér-Rao) |
|---|---|---|
| 10⁴ | 0.580 σ | 0.146 σ |
| 10⁵ | 0.403 σ | 0.082 σ |
| 10⁶ | 0.302 σ | 0.046 σ |

Por 100× más cuentas, el óptimo gana **3.16×** y el ingenuo **1.93×**. La
conclusión práctica es la misma en los dos casos: **acumular cuentas es una forma
carísima de comprar separación.**

---

## 4. El límite del contador de 32 bits

Cada bin es un `uint32` saturante ([`mca_hist.sv:160`](../../modulos/mca/rtl/mca_hist.sv#L160)):
al llegar a `0xFFFFFFFF` se queda ahí, no envuelve.

Con FWHM = 8.64 canales, σ = 3.67, el bin del pico se lleva `1/(σ√2π)` = **10.9 %**
del total. O sea que el contador satura cuando el pico acumuló

    N = 2³² / 0.109 = 3.95 × 10¹⁰ cuentas  =  13.8 horas a 794 kcps

y eso **con toda la actividad en un solo pico**. El piso estadístico de la
sección 3 con esa N es

    d_min = 1.73/(2·3.95e10)^(1/4) = 0.0033 σ   →  separación 0.0028 FWHM

**Ése es el límite duro que impone el ancho del contador.** Es real, pero está a
cuatro órdenes de magnitud de cualquier cosa que importe — ver sección 6.

---

## 5. Qué cambia con el zoom (y no es lo que uno espera)

El eje del MCA admite **zoom alineado a potencias de 2**: la ventana se restringe
a `[k·2^(16−z), (k+1)·2^(16−z))`, con `z` el nivel de zoom y `k` el índice de
ventana. Sobre una feature normalizada a uint16 eso es puro rebanado de bits — un
comparador y una rebanada, ni restador ni multiplicador.

La alineación no es un capricho: hace que **los bins de cada nivel sean
subdivisiones exactamente anidadas de los del nivel anterior**, así que un bin de
nivel `z` es la suma *entera* de dos de nivel `z+1`. Espectros tomados con
ventanas distintas se combinan con aritmética entera, sin resampleo, sin
interpolación y sin la DNL que introduce el rebinning de
[§15.2](../resultados_validacion_hw.md).

### El zoom NO mejora el poder resolutivo

Es la conclusión importante y va en contra de la intuición. Aumentar
canales/FWHM sólo recupera la pérdida por binning de la sección 2 — y esa pérdida
**ya es menor al 0.6 %**. Hacer zoom 8× la llevaría a ~0.01 %: no hay nada que
recuperar. Y no toca ninguno de los otros dos límites: la FWHM instrumental es
del ruido, y el poder resolutivo estadístico depende de N, no del binning.

Dicho con números en vez de con un argumento, a **N fija**:

![el bineado contra la detección](figuras/15_bineado_vs_deteccion.png)

**(a)** La misma muestra de 10⁵ cuentas histogramada con 1, 2, 4 y 16 canales por
FWHM. Con 1 el valle desaparece; con 2 ya está; de 4 en adelante las curvas son
indistinguibles entre sí y de la densidad real.
**(b)** El mismo efecto medido como **información**: la fracción de la
información de Fisher sobre la separación que sobrevive al bineado (eje
izquierdo) y lo que eso cuesta en `d_min` (eje derecho).

| canales/FWHM | 1 | 2 | 4 | **6.31** | **8.64** | 16 | 64 |
|---|---|---|---|---|---|---|---|
| información retenida | 0.51 | 0.81 | 0.95 | **0.978** | **0.988** | 0.997 | 1.000 |
| `d_min` relativo | 1.18 | 1.05 | 1.014 | **1.006** | **1.003** | 1.001 | 1.000 |

**El MCA trabaja en la banda sombreada, 6.3–8.6 canales/FWHM, donde ya conserva
el 98–99 % de la información.** Llevarlo a 64 canales/FWHM mejora `d_min` un
**0.30 %** y cuesta **7.4× la BRAM**. Ésa es la cuenta que respalda el párrafo
de arriba, y es la misma conclusión por otro camino que la regla de 4–10 de la
sección 2.

> **Un detalle que vale la pena, porque la corrección de Sheppard se cita de
> más:** la curva punteada de (b) es `1/(1+Δ²/12)`, y queda **por encima** de las
> dos curvas reales — a 4 canales/FWHM predice 0.97 y lo que sobrevive es 0.95.
> Sheppard describe la **inflación del ancho**, no la pérdida de información
> sobre la **separación**, y subestima la segunda. Para decidir bineado da lo
> mismo (las dos saturan en el mismo lugar); para citar un número, no.

Y la asimetría entre las dos curvas de (b) no es casual: el doblete fino pierde
**más** información que el ancho con el mismo bineado. Su firma vive en la
curvatura de la distribución (`φ''`, sección 3), que es justo lo primero que un
bin ancho promedia.

**Para qué sirve entonces**: permite usar un histograma más chico (8192 en vez de
16384 canales) sin ceder nada, y encuadrar el eje sobre dos picos juntos. Es un
dispositivo de **ahorro de BRAM y de encuadre**, no de resolución.

### Y la deriva sí aparece con zoom — peor

En unidades de FWHM la deriva es invariante bajo zoom, porque el FWHM y el
corrimiento escalan juntos. Pero **como fracción de la ventana empeora 2^z**, y
eso es lo que importa operativamente:

| Deriva | z=0 (100 % de FS) | z=1 (50 %) | z=2 (25 %) | z=3 (12.5 %) |
|---|---|---|---|---|
| 1.28 % (×36 de tasa) | 1.0 % de la ventana | 2.0 % | 4.1 % | 8.2 % |
| 6.45 % (barrido completo) | 5.2 % | 10.3 % | 20.6 % | **41.3 %** |

Con `z=3`, una deriva del 6.45 % marcha el pico por el **41 % del ancho de la
ventana** y puede empujarlo fuera de la aceptación, perdiendo cuentas **en
silencio**. En un espectro a fondo de escala el mismo corrimiento se ve como un
desplazamiento modesto; con zoom es una fuga.

> **Hacer zoom sin control de deriva es una trampa.**

**Consecuencia aprovechable:** como el discriminador es lo que define la ventana
de zoom, `cnt_rej_discr` funciona como **alarma de deriva** — si empieza a subir
sin que cambie la fuente, el pico se está yendo de la ventana. Es un uso previsto
del contador, no un efecto colateral.

---

## 6. La deriva como pérdida de resolución, y la especificación que falta

Éste es el punto que ordena todo lo demás.

La deriva a lo largo de una corrida convoluciona el pico consigo mismo desplazado,
así que se suma en cuadratura con el ancho intrínseco:

    FWHM_medido² = FWHM_intrínseco² + deriva²

| Deriva | 0.10 FWHM | **0.32 FWHM** | 0.50 FWHM | 1.0 FWHM |
|---|---|---|---|---|
| FWHM medido | +0.5 % | **+5.0 %** | +11.8 % | +41.4 % |

Para que la resolución no se degrade más del 5 %, la deriva tiene que quedar
**por debajo de 0.32 FWHM**. Con FWHM/centroide = 0.106 %, eso es una
**estabilidad de centroide del 0.034 %**.

**Ésa es la especificación que el sistema no cumple.** El corrimiento medido es
1.28 % con un cambio de tasa de ×36, o sea **38× la tolerancia**; con el barrido
completo de tasa, 190×.

### Por qué la LUT de linealización NO corrige la deriva

Es la pregunta natural, porque §15 muestra que una INL sí se puede invertir y
compensar. Pero **son dos objetos matemáticamente distintos**:

| | INL | Deriva |
|---|---|---|
| De qué depende | de la **amplitud**: `Â = G·A + INL(A)` | de la **tasa y del tiempo**, con la amplitud FIJA |
| ¿Reproducible? | sí — la misma entrada da el mismo canal siempre | no — el mismo pulso da canales distintos según la actividad |
| ¿Invertible con un mapa `h(F)`? | **sí**, es exactamente lo que hace §15 | **no** |

La imposibilidad es casi tautológica: **una LUT indexada por el valor de la
feature sólo puede corregir lo que dependa del valor de la feature.** La deriva
depende de una variable que el mapeo no ve, así que cualquier tabla queda bien a
una tasa y mal a todas las demás.

Y el orden de magnitud lo empeora: la INL entera mide **0.563 % FS** y la deriva
con la tasa mide **1.28 %**. **La deriva es 2.3× más grande que la corrección
completa que la LUT intentaría aplicar.**

**Dónde la calibración sí sirve**: §2.3 de
[`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) lista *calibrar a la tasa
de trabajo* como compensación válida. La LUT **fija el punto de operación**; lo
que no puede es rastrear su variación. Alcanza si se mide siempre a la misma
actividad, y no alcanza para una fuente que decae ni para comparar una muestra
intensa con una débil.

### ¿De dónde viene la deriva, y alcanza con un corte por forma?

Son **dos mecanismos** y conviene separarlos porque responden a cosas distintas:

- **(a) Contaminación por pulsos vecinos.** La integral incluye carga del pulso de
  al lado. Es a nivel de evento. A 100 kcps sólo el **53–59 %** de los eventos
  están limpios y `cnt_pileup` marca entre **0.00 % y 0.45 %**: casi todo el
  apilamiento entra al espectro. Ver
  [`monte-carlo/`](../../software/monte-carlo/).
- **(b) Pedestal de línea de base.** El nivel medio sube porque las colas se
  solapan, y eso afecta también a los eventos **limpios**. Rechazar no lo toca:
  sacar un evento no cambia el nivel sobre el que están parados los demás.

El Monte-Carlo de apilamiento tiene la línea de base **fija en 0** —no modela
ningún seguidor—, así que toda la deriva que muestra es mecanismo (a) puro. Con
el corte por `Q/pico` calibrado, sobre el espectro de una línea en modo 0:

| Tasa | Limpios | Corrimiento sin corte | Con corte `Q/pico` |
|---|---|---|---|
| 20 kcps | 88.2 % | +0.10 % | +0.07 % |
| 50 kcps | 73.2 % | +0.29 % | **+0.14 %** |
| 100 kcps | 53.4 % | +0.48 % | **+0.25 %** |
| 200 kcps | 27.6 % | +0.79 % | +0.50 % |

**El corte saca alrededor de la mitad.** Lo que queda es el límite irreducible:
dos pulsos idénticos separados 0–64 ns suman un pulso *de la misma forma* y el
doble de amplitud, y el lugar geométrico predice correctamente su `Q/pico`
(medido a −0.9σ y +1.6σ: indistinguible).

**Y el número que cierra la discusión:** el apilamiento solo produce **+0.21 %**
entre las dos tasas de la campaña, mientras que la placa midió **+1.28 %**. La
deriva medida es varias veces más grande que lo que el apilamiento explica, así
que hay un segundo mecanismo llevándose la mayor parte.

### El seguidor de línea de base era el sospechoso — y quedó exonerado

Ésta era la hipótesis obvia, porque el seguidor IIR es lo único del MCA que el
Monte-Carlo no modelaba. [`monte-carlo/linea_base.py`](../../software/monte-carlo/linea_base.py)
lo modela y corre el **mismo estímulo** con base fija y con seguidor. El
resultado es el contrario del esperado:

| Tasa | Base fija (apilamiento solo) | Con seguidor | Base media seguida | Fracción congelada |
|---|---|---|---|---|
| 1 995 Hz | 0.000 % | 0.000 % | 0.65 | 38.1 % |
| 20 000 Hz | +0.063 % | +0.015 % | 1.71 | 42.1 % |
| 72 444 Hz | **+0.208 %** | **+0.096 %** | 4.88 | 53.4 % |
| 150 000 Hz | +0.551 % | +0.074 % | 15.69 | 67.7 % |

**El seguidor MEJORA el corrimiento, no lo empeora**: a la tasa alta de la
campaña lo baja de +0.21 % a +0.10 %. Está haciendo exactamente su trabajo —
sigue el pedestal (la base media sube de 0.65 a 4.88 cuentas) y lo resta.

| | Corrimiento |
|---|---|
| Placa (medido, ×36 de tasa) | **+1.28 %** |
| MC, apilamiento solo | +0.21 % |
| MC, apilamiento + seguidor | +0.10 % |
| **Sin explicar** | **+1.18 %** |

**Con la cadena digital del MCA entera modelada, queda el 92 % del efecto sin
explicar.** Eso mueve la sospecha *afuera* del MCA digital.

> **Y una advertencia para tasa alta**: a 300 kcps el seguidor se rompe
> (−2.93 %, base media 147 cuentas, 79.5 % del tiempo congelado). No afecta a la
> campaña, pero es un modo de falla real que hay que respetar al subir la tasa.

### Qué queda por descartar, en orden de costo

1. **Que no sea una deriva con la TASA sino con el TIEMPO.** `sweep_rate` recorre
   las tasas de menor a mayor y **no tiene pasada de vuelta**, así que tasa y
   tiempo están confundidos — el mismo tipo de error que ya invalidó el +6.45 %
   (confundido con el ancho de pulso). El arreglo es trivial: agregar la pasada
   de vuelta que `sweep_amplitude` ya tiene. Si el corrimiento se repite al
   volver, es de la tasa; si no, es del tiempo. **Es la medición más barata y más
   decisiva que queda.**
2. **Que sea del generador.** El DG4162 a 2 kHz y a 72 kHz trabaja con ciclos de
   trabajo muy distintos. Se dirime con el **pulser de referencia digital**: si
   su pico se queda quieto mientras el pico real se mueve, la deriva es anterior
   a la inyección, o sea del generador o del frente analógico.
3. **Que sea del frente analógico** del Red Pitaya (térmica, asentamiento).

**Un candidato ya descartado con número.** El recorte `xc >= 0` de
`mca_pulse_feature` rectifica el ruido donde la señal vale ~0, así que le mete a
`q_tot` un pedestal que **depende de σ**: un cambio del ruido correría el
centroide sin que la señal cambie. No alcanza ni de lejos — con el estímulo de
la campaña ni siquiera se activa (la cola del ARB todavía vale 528 cuentas
cuando la compuerta cierra), y en el caso general harían falta ~3200 muestras en
cero para que un cambio del 10 % en σ corriera el centroide 0.1 %. Ver
[`../ruido_del_sistema.md`](../ruido_del_sistema.md) §6.

> **Consecuencia para el conformado trapezoidal.** §5 de
> [`decisiones_diseno_mca.md`](decisiones_diseno_mca.md) da el corrimiento con la
> tasa como *el argumento principal* de la cancelación polo-cero. Si el
> corrimiento no está en la cadena digital, la PZ no lo va a arreglar. **El
> trapecio sigue justificándose por resolución, pero su justificación por deriva
> queda en suspenso hasta cerrar los tres puntos de arriba.**

> **Conclusión: el corte por forma NO reemplaza a la cancelación polo-cero.**
> Ataca el mecanismo (a), que es ~1/4 de la deriva medida, y de eso saca la mitad.

**Pero el corte vale la pena igual, por otra métrica.** Sobre la *deformación del
espectro* —no la posición del pico— es espectacular: en modo 0 baja el continuo
sobre el fotopico de **32.4 % a 0.8 %**, rechazando el 99.1 % de los apilados sin
perder un evento limpio. Tres condiciones para poder contar con él:

1. **El eje de forma que ya está en el hardware no sirve para esto.**
   `Q_cola/Q_total` rechaza el 29.6 % en modo 0 y **0 %** en modo 1: con
   `gate_short = 32` la cola se lleva el 94 % de la carga y al cociente le quedan
   3 valores útiles de 64. El que funciona es **`Q/pico`**, que necesita un
   segundo divisor.
2. **Obliga a modo 0 (histéresis), no a compuertas fijas** — y ahí hay un
   conflicto real con §14.1b, donde las compuertas fijas dieron ×1.91 mejor
   resolución. Lo que las hace buenas (largo independiente de la señal) es lo que
   las deja ciegas al apilamiento.
3. **El corte se calibra con un pulser deslizante**, no con el espectro fuente, o
   queda un corte en amplitud disfrazado de corte en forma.

Lo que sí ataca la deriva, en orden de preferencia:

1. **Cancelación polo-cero** — elimina la cola exponencial, así que no hay colas
   que se apilen. Ataca la causa, no el síntoma.
2. **Pulser de referencia** inyectado junto con la señal: su pico está a amplitud
   fija, así que el corrimiento *de ese pico* **es** la deriva, medida en vivo.
   Práctica estándar en espectroscopía gamma.
3. **Rebanadas + realineado** por centroide antes de sumar (sección 8).

> **Predicción comprobable:** el error *leave-one-out* de §15.3 (0.24 % FS que
> **no** se reproduce) puede ser en parte deriva térmica **durante el propio
> barrido de calibración**. Se dirime repitiendo la campaña y correlacionando los
> residuos de las dos pasadas: si correlacionan, es INL real; si no, es deriva.
> `sweep_amplitude` ya hace esa pasada de ida y vuelta.

---

## 7. La jerarquía completa

Todo en unidades de FWHM, que es lo que permite compararlos:

| Límite | En FWHM | Comentario |
|---|---|---|
| Saturación del contador de 32 b | **0.0028** | 13.8 h a tasa máxima con todo en un pico |
| Pérdida por binning a 8.6 can/FWHM | **0.0031** | Sheppard, Δ = 1 canal |
| *Tolerancia de deriva (<5 % de degradación)* | *0.32* | el umbral, no un efecto |
| Deriva medida, ×36 de tasa | **12** | **38× la tolerancia** |
| Deriva medida, barrido completo de tasa | **61** | 190× la tolerancia |

La deriva medida es **4353×** el límite del contador. Cualquier esfuerzo puesto en
ampliar contadores, agregar canales o afinar el binning está atacando el problema
equivocado por cuatro órdenes de magnitud.

**El trabajo que corresponde es la cancelación polo-cero** del conformado
trapezoidal (Jordanov-Knoll), que es lo que elimina el corrimiento de línea de
base a alta tasa en el origen en vez de esconderse de él con `cfg_bl_holdoff`.
Ver §5 de [`decisiones_diseno_mca.md`](decisiones_diseno_mca.md).

---

## 8. Adquisición por rebanadas: qué corrige y qué no

Un esquema natural es *acumular, guardar el histograma, borrar y seguir*. Sumar K
espectros de M cuentas es estadísticamente idéntico a uno de K·M — **pero sólo si
nada derivó en el medio**, que es justo lo que no se cumple.

Entonces la motivación correcta **no es el contador** (sección 4: no ata). Es que
partir la adquisición permite **medir el corrimiento del centroide entre
rebanadas** y corregirlo o descartar las malas. Es la práctica estándar en
corridas largas.

- **Doble buffer en RTL**, para que la adquisición no pare durante la lectura:
  cuesta **2× BRAM**. No se justifica — el presupuesto de BRAM es el recurso
  escaso del 7010 (40 de 60 usados).
- **Rebanadas de tiempo fijo en software**: da lo mismo con costo cero.
  [`MCA.acquire_chunks()`](../../software/API/mca.py) ya existe pero *acumula*
  en el mismo histograma; falta una variante que lea-y-borre por rebanada y
  devuelva la serie temporal de espectros.

El flag `full` del histograma sirve como **disparador de rebanada** y como seguro
contra la saturación silenciosa, no como mecanismo principal.

---

## Apéndice A. Información de Fisher, en detalle

La sección 3 usa la cota de Cramér-Rao en tres líneas y sigue de largo. Acá va el
desarrollo: qué mide la información de Fisher, por qué este problema **no es
regular** —que es de donde sale el exponente ¼—, qué tan buena es la aproximación
que se usa, y en qué dirección se rompe cada supuesto.

Todo lo numérico de este apéndice lo recalcula
[`figuras/figuras_limites.py`](figuras/figuras_limites.py), incluidas las
integrales de Fisher que acá aparecen resueltas.

### A.1 Qué mide

Para una densidad `p(x; θ)` la información de Fisher por muestra es

    I(θ) = E[(∂/∂θ · log p)²] = −E[∂²/∂θ² · log p]

o sea **la curvatura esperada de la log-verosimilitud** en el valor verdadero. Si
mover `θ` casi no cambia la distribución de los datos, la log-verosimilitud es
plana, `I` es chica y ningún estimador puede distinguir valores vecinos. Las dos
propiedades que se usan abajo:

- **Es aditiva**: `N` muestras independientes dan `N·I(θ)`.
- **Cota de Cramér-Rao**: para cualquier estimador insesgado, `Var(θ̂) ≥ 1/(N·I)`.

Lo importante de la cota es que es un **piso sobre los estimadores, no sobre un
estimador**: no hay ajuste más astuto, deconvolución ni algoritmo que la baje.
Sólo se mueve agregando información —más cuentas, menos σ, menos pérdida por
bineado—. Las condiciones de regularidad (soporte independiente de `θ`,
derivabilidad, intercambio de derivada e integral) se cumplen sin drama acá: una
mezcla de gaussianas es analítica y de soporte completo.

### A.2 El caso regular de referencia: el centroide de un pico

Conviene tener a mano el problema fácil, porque es el que todo el mundo
extrapola. Un solo pico gaussiano de σ conocido y centroide `μ` desconocido:

    log p = −(x−μ)²/(2σ²) + cte    →    ∂²/∂μ² log p = −1/σ²    →    I(μ) = 1/σ²

`I` **no depende de `μ`**: el problema es regular y la cota se evalúa sin más,
`σ_μ = σ/√N`.

| N | `σ_μ` en σ | `σ_μ` en FWHM |
|---|---|---|
| 10⁴ | 0.0100 | 0.0042 |
| 10⁶ | 0.0010 | 0.00042 |

Raíz cuadrada de las cuentas: para duplicar la precisión, 4× más cuentas. **Éste
es el comportamiento que uno espera, y no es el que rige separar dos picos.**

### A.3 Por qué separar dos picos NO es un problema regular

Con `p(x; d) = ½[φ(x−d) + φ(x+d)]` la densidad es **par en `d`**, así que
`∂p/∂d` se anula idénticamente en `d = 0`: a separación nula, mover `d` no cambia
la distribución a primer orden, sólo la ensancha a segundo. De ahí sale toda la
sección 3:

    p(x; d) = φ(x) + (d²/2)·φ''(x) + O(d⁴)        ∂p/∂d = d·φ''(x) + O(d³)
    I(d)    = ∫ (∂p/∂d)²/p dx ≈ d² ∫ φ''²/φ dx = d²·E[(X²−1)²] = 2d²

usando `φ'' = (x²−1)φ` y `E[(X²−1)²] = E[X⁴] − 2E[X²] + 1 = 3 − 2 + 1 = 2`.

**La información se anula cuando `d → 0`, y se anula como `d²`.** En `d = 0` el
parámetro es localmente **no identificable**: no es que cueste medirlo, es que no
hay nada que medir. Dos consecuencias:

1. **La cota depende del valor desconocido**: `σ_d ≥ 1/(d√(2N))` empeora justo
   cuando lo que se quiere medir es chico, que es siempre el caso de interés.
2. **Por eso el criterio de detección es una condición de punto fijo**, no una
   evaluación: hay que pedir `d > 3·σ_d(d)`, y recién al resolverla aparece el
   exponente.

```
d > 3/(d√(2N))   →   d² > 3/√(2N)   →   d_min = √3/(2N)^(1/4)
```

| N | `d_min` (Cramér-Rao) | separación `2d` en FWHM |
|---|---|---|
| 10⁴ | 0.1457 σ | 0.124 |
| 10⁵ | 0.0819 σ | 0.070 |
| 10⁶ | 0.0461 σ | 0.039 |
| 3.95 × 10¹⁰ (saturación, §4) | 0.00327 σ | 0.0028 |

**El ¼ es una raíz cuadrada aplicada dos veces**: una por la estadística de
siempre, y otra porque el parámetro entra en la información al cuadrado. Es la
firma de un problema degenerado, y vale para cualquier parámetro que sólo se
manifieste a segundo orden. El panel (c) de la
[figura de la sección 3](#3-poder-resolutivo-estadístico-información-de-fisher)
es esta misma cuenta dibujada: la significancia sube con pendiente ½ y el `d`
detectable baja con ¼.

### A.4 Qué tan buena es la aproximación `I ≈ 2d²`

Es el límite `d → 0`, y el documento la usa en `d` finito. La información exacta,
integrada numéricamente:

| `d` (σ) | 0.0033 | 0.046 | 0.082 | 0.146 | 0.20 | 0.30 |
|---|---|---|---|---|---|---|
| `I_exacta / 2d²` | 1.0000 | 0.9958 | 0.9868 | 0.9596 | 0.9275 | 0.8533 |

La exacta queda **por debajo** de la cuadrática, así que la fórmula cerrada es
algo optimista. Resolviendo el punto fijo con la `I` exacta:

| N | fórmula | exacta | desvío |
|---|---|---|---|
| 10⁴ | 0.1457 | 0.1472 | +1.1 % |
| 10⁵ | 0.0819 | 0.0822 | +0.3 % |
| 10⁶ | 0.0461 | 0.0461 | +0.1 % |
| 3.95 × 10¹⁰ | 0.00327 | 0.00327 | 0.00 % |

El error se amortigua con exponente ¼ (`d_min ∝ I^(−1/4)` a `d` fijo), así que un
4 % de error en la información es 1 % en `d_min`. **La aproximación no es el punto
débil del argumento**, y en la N que de verdad importa —la de la saturación del
contador— no se nota en las cifras publicadas.

### A.5 De dónde sale el 3, y por qué el exponente no se negocia

El criterio de `k` sigmas da `d_min = √k/(2N)^(1/4)`: la convención sólo mueve el
prefactor.

| criterio | prefactor | `d_min` a N = 10⁶ |
|---|---|---|
| 1σ | 1.00 | 0.0266 σ |
| 2σ | 1.41 | 0.0376 σ |
| **3σ** (el del texto) | **1.73** | **0.0461 σ** |
| 5σ | 2.24 | 0.0595 σ |

Pasar de 3σ a 2σ mejora `d_min` un 18 %, que es lo mismo que comprar **2.25× más
cuentas**: la convención de reporte vale casi tanto como una campaña, y conviene
decir siempre con qué `k` se está hablando. El exponente, en cambio, no depende de
nada de esto.

### A.6 Los supuestos, uno por uno

| Supuesto | Qué pasa si no vale |
|---|---|
| σ conocido e **igual** en los dos picos | hay que estimarlo junto con `d`; parte de la información se va al ancho y `d_min` empeora |
| **intensidades iguales** (50/50) | sobrevive con una N efectiva — ver abajo |
| posición global del doblete conocida | en la práctica **no** lo es, y resulta que eso es lo que *sostiene* el exponente — ver abajo |
| sin continuo de fondo | lo que entra en la cota es la N **del pico**, no la del espectro: un fondo bajo el doblete diluye la información |
| cuentas sin bineado | el bineado destruye información, y es irrecuperable; con 6.3–8.6 canales/FWHM sobrevive el 98–99 % (§5), despreciable frente a todo lo demás |

**Intensidades desiguales y el parámetro de molestia.** Con pesos `w` y `1−w` la
densidad ya no es par en `d`: mover `d` corre la media de la mezcla, que es un
efecto de **primer** orden. Eso volvería el problema regular y daría `N^(−1/2)`…
pero sólo si se supiera de antemano dónde tiene que estar el centro. En un
espectro real la posición global es un parámetro de molestia que se ajusta junto
con todo lo demás, y al perfilarlo se absorbe exactamente la dirección de primer
orden. La información que le queda a `d` vuelve a anularse como `d²`:

    I_perfilada(d) = I_dd − I_dμ²/I_μμ = 2·[4w(1−w)]²·d²

(verificada numéricamente a 4 cifras para `w` = 0.05 … 0.5). O sea que **todo el
apéndice sobrevive cambiando N por una N efectiva**:

    N_ef = [4w(1−w)]² · N

| `w` | 0.5 | 0.4 | 0.3 | 0.2 | 0.1 |
|---|---|---|---|---|---|
| `N_ef/N` | 1.00 | 0.92 | 0.71 | 0.41 | 0.13 |
| `d_min` relativo | 1.00 | 1.02 | 1.09 | 1.25 | **1.67** |

Y el resultado es tranquilizador: un doblete 10:1 —bastante asimétrico— cuesta
1.67× en separación detectable, no un orden de magnitud. **El exponente ¼ es lo
robusto del asunto; los supuestos mueven el prefactor.**

### A.7 El estimador ingenuo, con el término exacto

La tabla de §3 compara la cota con un estimador por momentos, y vale hacer la
cuenta completa porque **acá la aproximación de `d` chico sí se rompe**. Para
`X = εd + Z` con `ε = ±1` equiprobable y `Z ~ N(0,1)`:

    m₂ = 1 + d²        m₄ = 3 + 6d² + d⁴
    γ₂ = m₄/m₂² − 3 = −2d⁴/(1+d²)²        →    −2d⁴   sólo si d ≪ 1

El exceso de curtosis muestral de una muestra casi normal tiene
`SE ≈ √(24/N)`, así que la detección a 3σ pide `2d⁴/(1+d²)² = 3√(24/N)`:

| N | con `γ₂` exacta | con la aproximación `−2d⁴` | Monte-Carlo (§3) |
|---|---|---|---|
| 10⁴ | 0.610 σ | 0.521 σ | 0.580 σ |
| 10⁵ | 0.424 σ | 0.390 σ | 0.403 σ |
| 10⁶ | 0.306 σ | 0.293 σ | 0.302 σ |

El estimador por momentos opera en `d ≈ 0.3–0.6`, donde el denominador `(1+d²)²`
ya se come un 25 % de la curtosis: usar `−2d⁴` subestima `d_min` un 15 % a
N = 10⁴. **Es el contraste exacto con A.4**: en la cota de Cramér-Rao la
aproximación de `d` chico es inocua porque el óptimo trabaja en `d ≈ 0.05–0.15`;
en el estimador ingenuo no lo es, porque trabaja diez veces más lejos. La forma
cerrada acota al Monte-Carlo por arriba y converge a él (+5 % a 10⁴, +1.3 % a 10⁶).

De la relación `d⁴ ∝ N^(−1/2)` sale el `N^(−1/8)` de §3. Y la lectura conceptual
es que la caída no es un defecto del método de momentos en abstracto: **la
curtosis mira un solo número de la muestra, mientras que la verosimilitud mira la
forma entera.** La distancia entre ⅛ y ¼ es el precio de resumir.

### A.8 Lo que el apéndice le aporta a la tesis del documento

El poder resolutivo es el único de los tres límites de §1 que las cuentas
mejoran, y mejora como la raíz cuarta. Puesto al lado de la deriva:

| | En FWHM |
|---|---|
| Incertidumbre estadística del centroide a N = 10⁶ (A.2) | 0.00042 |
| Deriva medida, ×36 de tasa (§7) | **12** |

**La deriva es 2.8 × 10⁴ veces la incertidumbre estadística del propio
centroide.** Es el resultado de la sección 7 visto desde la teoría de estimación:
la varianza no es el límite por cuatro órdenes de magnitud, **el MCA está limitado
por un sesgo** — y ninguna cantidad de cuentas corrige un sesgo. Ésa es la razón
de fondo por la que la sección 6 es la que importa.

---

## Cómo reproducir

```bash
cd prj/MCA/docs/mca/figuras
python3 figuras_limites.py          # imprime todos los números y regenera las tres figuras
```

| Figura | Qué muestra |
|---|---|
| `08_jerarquia_limites.png` | Los cuatro límites en un eje logarítmico común, contra la tolerancia (sección 7) |
| `14_cuentas_vs_separacion.png` | Qué compran las cuentas: el valle que emerge, el que nunca se ve, y la significancia que explica a los dos (sección 3) |
| `15_bineado_vs_deteccion.png` | Qué compran los canales a N fija: nada por encima de 4 por FWHM (sección 5) |

Todo se recalcula desde `software/datos/mca_gate_esp_v2/sweep_gate_espectro.npz`
y las fórmulas; no hay constantes copiadas a mano salvo la resolución de
referencia (0.106 %) y la tasa máxima (794 kcps), que están declaradas arriba del
script con el enlace a la sección que las midió. Las tablas del apéndice A las
imprime el mismo script: las integrales de Fisher se resuelven por cuadratura,
así que las aproximaciones analíticas de A.4, A.6 y A.7 quedan verificadas y no
afirmadas.

## Bibliografía

| Ref | Para qué |
|---|---|
| **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010. | Cap. 3, estadística de conteo y propagación de errores; cap. 4, tiempo muerto. |
| **M. A. Mariscotti**, *A method for automatic identification of peaks in the presence of background*, Nucl. Instrum. Methods **50** (1967) 309. | Búsqueda de picos por diferencias segundas y la significancia estadística de un pico sobre el continuo. |
| **L. A. Currie**, *Limits for qualitative detection and quantitative determination*, Anal. Chem. **40** (1968) 586. | Los límites de detección en conteo (L_C, L_D, L_Q), el marco estándar. |
| **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real time…*, Nucl. Instrum. Methods A **345** (1994) 337. | El trapecio y la cancelación polo-cero: la solución al problema de la sección 6. |
| **C. R. Rao**, *Information and the accuracy attainable in the estimation of statistical parameters*, Bull. Calcutta Math. Soc. **37** (1945) 81. | La cota original. El apéndice A es un caso particular suyo. |
| **E. L. Lehmann, G. Casella**, *Theory of Point Estimation*, 2ª ed., Springer, 1998. | Cap. 2: información de Fisher y condiciones de regularidad. Cap. 6: el perfilado de parámetros de molestia que usa A.6. |

La cota de Cramér-Rao de la sección 3 se deriva acá en vez de citarse, porque el
caso concreto (mezcla simétrica de dos gaussianas de ancho conocido) sale en tres
líneas y así queda claro qué se está suponiendo. El
[apéndice A](#apéndice-a-información-de-fisher-en-detalle) hace el desarrollo
completo, con los supuestos y su sensibilidad.
