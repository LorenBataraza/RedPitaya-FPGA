# Límites de resolución del MCA, y por qué el que ata es la deriva

Este documento junta los límites que acotan lo que el MCA puede distinguir, los
pone **todos en la misma unidad** (fracciones de FWHM) y muestra que están
separados por órdenes de magnitud. La conclusión es que ni el contador, ni el
binning, ni la cantidad de canales son la restricción activa: **es la deriva del
centroide**, por un factor 38 sobre su propia tolerancia.

Los números salen de la campaña de [§14.1b](../resultados_validacion_hw.md) y de
fórmulas recalculadas en
[`figuras/figuras_limites.py`](figuras/figuras_limites.py), que también genera la
figura. Si el documento y la figura no coinciden, es un bug del script.

![jerarquía de límites](figuras/08_jerarquia_limites.png)

---

## 1. Tres límites que se confunden todo el tiempo

| | Qué es | ¿Las cuentas lo mejoran? |
|---|---|---|
| **Resolución instrumental (FWHM)** | El ancho del pico de un pulser: es el ruido de la cadena | **No.** Nunca |
| **Pérdida por binning** | El histograma discretiza y eso agrega varianza | No: se arregla con más canales, no con más cuentas |
| **Poder resolutivo estadístico** | Sabiendo que hay dos gaussianas de ancho conocido, con qué separación se puede afirmar que son dos | **Sí**, pero lentísimo |

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
de la regla en todo el rango** y tirando menos del 0.6 %.

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

Cada bin es un `uint32` saturante ([`mca_hist.sv:139`](../../rtl/mine/mca/mca_hist.sv#L139)):
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

## Cómo reproducir

```bash
cd prj/MCA/docs/mca/figuras
python3 figuras_limites.py          # imprime todos los números y regenera la figura
```

Todo se recalcula desde `software/datos/mca_gate_esp_v2/sweep_gate_espectro.npz`
y las fórmulas; no hay constantes copiadas a mano salvo la resolución de
referencia (0.106 %) y la tasa máxima (794 kcps), que están declaradas arriba del
script con el enlace a la sección que las midió.

## Bibliografía

| Ref | Para qué |
|---|---|
| **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010. | Cap. 3, estadística de conteo y propagación de errores; cap. 4, tiempo muerto. |
| **M. A. Mariscotti**, *A method for automatic identification of peaks in the presence of background*, Nucl. Instrum. Methods **50** (1967) 309. | Búsqueda de picos por diferencias segundas y la significancia estadística de un pico sobre el continuo. |
| **L. A. Currie**, *Limits for qualitative detection and quantitative determination*, Anal. Chem. **40** (1968) 586. | Los límites de detección en conteo (L_C, L_D, L_Q), el marco estándar. |
| **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real time…*, Nucl. Instrum. Methods A **345** (1994) 337. | El trapecio y la cancelación polo-cero: la solución al problema de la sección 6. |

La cota de Cramér-Rao de la sección 3 se deriva acá en vez de citarse, porque el
caso concreto (mezcla simétrica de dos gaussianas de ancho conocido) sale en tres
líneas y así queda claro qué se está suponiendo.
