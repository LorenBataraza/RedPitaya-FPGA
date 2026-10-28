# Apéndice. El catálogo de formas de conformado, en detalle

Apéndice de [§13.11 — INL vs forma del pulso](../resultados_validacion_hw.md).
Ahí se reporta el resultado; acá va de dónde salen las seis formas, qué significa
cada parámetro geométrico, y por qué esa geometría **predice** el orden de los
fotopicos medidos sin tocar un solo dato.

Todo lo numérico de este apéndice lo recalculan las mismas funciones puras que
usó la campaña: [`rigol_dg4162.py:1062-1163`](../../software/API/rigol_dg4162.py)
(las formas) y [`graficar_formas.py`](../../software/campanas/graficar_formas.py)
(la verificación contra el factor de forma medido en placa).

## A.1 Qué es el catálogo, y qué se mantiene fijo

Las seis familias son las salidas clásicas de un amplificador de conformado
(Knoll cap. 16), escritas como funciones de una sola variable adimensional

$$u = \frac{t}{\tau}$$

y normalizadas al pico, de manera que

$$\hat y(u) = \frac{f(u)}{f(u_p)}, \qquad \hat y(u_p) = 1 \ \text{ para las seis.}$$

La campaña las carga al ARB del DG4162 con **el mismo FWHM** ($W = 2\ \mu\text{s}$)
y **la misma altura de pico** ($V_{pp}/2$, vía `load_arb(normalize=True)`). Entre
familias cambia *sólo la forma*: cualquier diferencia en la amplitud reportada es
entonces de la cadena de medición y no del estímulo.

No son trazas capturadas ni un dibujo: son el mismo array que se le cargó al
generador. Tampoco son la respuesta de la cadena a una delta — en el sentido
físico cada una *es* la respuesta impulsiva de un conformador distinto al pulso
de carga cuasi-delta del preamplificador, pero acá el conformador se saltea y la
forma ya conformada se sintetiza directamente en el ARB.

## A.2 Las seis familias

| familia       | $f(u)$                                                         | qué es físicamente                                                          | carácter                                           |
| ------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------- | -------------------------------------------------- |
| `cr`          | $\left(1 - e^{-u/r}\right)e^{-u}$, $r = 0.05$                  | una sola diferenciación: el pulso de cola del preamplificador, sin integrar | la más asimétrica; el FWHM lo fija la cola         |
| `cr_rc`       | $u\,e^{-u}$                                                    | una diferenciación y una integración, constantes iguales                    | semi-gaussiana clásica; **referencia** del barrido |
| `cr_rc4`      | $\dfrac{u^{n}e^{-u}}{n!}$, $n = 4$                             | una diferenciación y $n$ integraciones                                      | la más simétrica y la de mayor soporte             |
| `triangular`  | $u$ en $[0,1]$, $2-u$ en $(1,2]$                               | el caso límite del filtro trapezoidal digital con meseta nula               | ápice en quiebre: el único caso de primer orden    |
| `trapezoidal` | $u$ en $[0,1]$, $1$ en $(1,1{+}p]$, $2{+}p-u$ después; $p = 1$ | el filtro trapezoidal digital (Jordanov-Knoll 1994)                         | meseta de 125 muestras: mejor caso del pico        |
| `bipolar`     | $\left(1-\dfrac{u}{2}\right)u\,e^{-u}$                         | CR-RC-CR: doble diferenciación, con cruce por cero en $u = 2$               | lóbulo negativo; **no pasó el pre-vuelo**          |

El parámetro $r$ de la `cr` y el $p$ de la trapezoidal son los únicos dos
parámetros de forma del catálogo; todo lo demás no tiene perillas.

## A.3 Por qué está cada una en el catálogo

La columna `carácter` resume; acá va por qué cada familia se eligió y qué parte
de la cadena pone a prueba.

- **`cr` — el extremo asimétrico.** Flanco casi vertical y cola exponencial
  larga, así que el FWHM lo fija la cola y no el ápice. Es el peor caso del
  estimador de pico en cuanto a *duración* del ápice, y la que más estresa al
  seguidor de línea de base. El $r$ es el flanco en unidades de escala: con
  $r \to 0$ queda el escalón diferenciado ideal $e^{-u}$, que en un ARB no es
  realizable porque el flanco se cuantiza.

- **`cr_rc` — la referencia.** La semi-gaussiana unipolar clásica, y la forma más
  parecida a la que usó la campaña publicada. Todas las ganancias relativas se
  reportan contra ella, y es la que se re-mide al final como réplica de cierre
  (de ahí sale el piso de 0.43 mV). Su cordura cierra el lazo con §13.4:
  3927.4 ch/Vpp contra 3927.50.

- **`cr_rc4` — el extremo simétrico.** Cuanto mayor $n$, más parecida a una
  gaussiana (de ahí "semi-gaussiana"), a costa de un pulso **más largo** para el
  mismo FWHM: pica en $u_p = 4$ y decae hasta $u \approx 14$. Es la de flanco más
  suave del catálogo, un factor 10 por debajo de la `cr`. $n = 4$ es el valor
  habitual en espectroscopía.

- **`triangular` — el ápice en quiebre.** Soporte finito y simetría exacta, pero
  derivada *discontinua* en el máximo. Es el único caso del catálogo donde el
  jitter de muestreo del ápice entra a primer orden (§A.6), y por eso la que peor
  resuelve: 7.37 ch de FWHM espectral.

- **`trapezoidal` — el control de la triangular.** El ápice dura $p\,\tau$ en vez
  de un instante, así que el muestreo cae sobre el máximo verdadero muchas veces
  y el jitter desaparece: mejor caso del estimador de pico, 5.55 ch. El detalle
  geométrico que la vuelve el par de control ideal: todo trapecio simétrico
  cumple $\text{área} = \hat y\,W$ **exactamente** —la recta de media altura
  bisecta las dos rampas, así que lo que se recorta en las esquinas es lo mismo
  que se agrega en los flancos—, y la triangular es el caso límite $p = 0$. Las
  dos tienen entonces el **mismo factor de forma, 1.000, para cualquier $p$**, y
  caen sobre la misma recta de pico-vs-carga. Cualquier diferencia entre ellas es
  del ápice y de nada más.

- **`bipolar` — el que rompe la segmentación.** El RTL recorta a cero
  ($x_c = \max(x,0)$), así que pierde el 50 % del área y el seguidor de base
  queda congelado durante el pulso. **No pasó el pre-vuelo**: 4004 eventos contra
  2002 esperados (200 %) y 50 % de apilamiento — el MCA cuenta dos eventos por
  pulso emitido. Quedó fuera de los resultados, y eso en sí *es* un resultado
  sobre robustez.

## A.4 Los parámetros geométricos: qué mide cada uno

La propiedad que hace posible la campaña es que **todas** las formas son de la
forma $f(t/\tau)$. Eso vuelve el FWHM lineal en la escala,

$$\mathrm{FWHM}(\tau) = w_u\,\tau \quad\Longrightarrow\quad \tau = \frac{W}{w_u},$$

y por lo tanto permite despejar la escala con un solo sondeo
(`_escala_para_fwhm`) en vez de iterar.

| parámetro | definición | qué representa | unidades |
|---|---|---|---|
| $u_p$ | $\arg\max_u f(u)$ | **Dónde cae el ápice dentro del pulso.** Es propiedad intrínseca de la fórmula, sin parámetros libres: $u_p = r\ln(1+1/r)$ para la `cr`, $u_p = n$ para CR-RC$^n$, $u_p = 2-\sqrt2$ para la bipolar. Un $u_p$ chico frente al soporte total significa pulso asimétrico (ápice temprano + cola larga). La trapezoidal no tiene un $u_p$ sino un **intervalo** $[1,\,1{+}p]$: eso *es* la meseta. | adimensional |
| $w_u$ | $u_2 - u_1$ con $\hat y(u_1) = \hat y(u_2) = \tfrac12$, $u_1 < u_p < u_2$ | **El FWHM medido en la variable adimensional**, antes de elegir escala. Es un número fijo de cada forma (1.000 exacto para la triangular, 2.000 exacto para la trapezoidal con $p=1$; las demás se resuelven numéricamente, p. ej. $u\,e^{1-u} = \tfrac12$ para la `cr_rc`). Es el número que convierte la consigna de ancho en una sola división. | adimensional |
| $\tau$ | $W / w_u$ | **La única perilla por familia**: la escala temporal que efectivamente se le carga al ARB para cumplir la consigna. Varía un factor 5.5 entre familias, y es el motivo por el que los pulsos difieren en **largo total** hasta un factor 8 a igual FWHM — y por el que `familias.png` no comparte eje $x$. | s |
| $\lvert\hat y'\rvert W$ | $W\cdot\max_{t<t_p}\lvert \mathrm{d}\hat y/\mathrm{d}t\rvert$ | **La pendiente máxima del flanco de subida**, en fracciones de la altura de pico por FWHM. Vale 1.00 para la triangular por definición (sube de 0 a 1 en exactamente un FWHM), lo que la vuelve la unidad natural de la columna. Gobierna el *timing walk* del disparo por umbral, no el error de amplitud. Para pasar a V/s: $(V_{pp}/2)\cdot\lvert\hat y'\rvert W / W$. | adimensional |
| $K = -\hat y''W^2$ | curvatura en el ápice, $\hat y(t_p{+}\Delta) \approx 1 - \tfrac{K}{2}(\Delta/W)^2$ | **Qué tan cerrado es el ápice.** Tiene valor cerrado: $\hat y''(u_p) = -1/n$ para CR-RC$^n$ y $-(2+\sqrt2)$ para la bipolar, escalado después por $w_u^2$. Las dos entradas con $K = 0$ **no significan lo mismo**: en la trapezoidal $\hat y'' = 0$ de verdad sobre toda la meseta, mientras que en la triangular $\hat y''$ *no existe* en $u_p$ (es una delta: el ápice es un quiebre). A esas dos las gobierna el término de primer orden. | adimensional |
| $N_{\mathrm{1\,LSB}}$ | $T_s^{-1}\,\mathrm{med}\{t : \hat y(t) \ge 1-\epsilon\}$, con $\epsilon = \mathrm{LSB}/(V_{pp}/2) = 2.44\times10^{-4}$ | **El ancho útil del ápice, en muestras del ADC**: cuántas muestras a 125 MSa/s caen donde el pulso es *indistinguible* del máximo para el cuantizador. Traduce $K$ a algo operativo, y es la columna que anticipa el resultado del estimador de pico. (1 LSB = 1/8192 V: 14 bits sobre ±1 V con el jumper LV.) | muestras |
| FF | $\dfrac{\int_{A^+} f\,\mathrm{d}t}{f_{\max}\,W} = \dfrac{Q}{\hat y\,W}$ | **El factor de forma**, con área **positiva** y no neta, porque el RTL acumula $x_c = \max(x,0)$. Es exactamente el cociente $Q/\text{pico}$ que el estudio de apilamiento usa para discriminar eventos apilados, y la pendiente de `pico_vs_carga.png`. El de la tabla es el **medido en placa**, leído de `formas_inl.npz`. | adimensional |

## A.5 La tabla detallada

$W = 2\ \mu\text{s}$, $T_s = 8\ \text{ns}$ (125 MSa/s, `dec=1`), $V_{pp} = 1\ \text{V}$,
$1\ \text{ch} = 0.255\ \text{mV}_{pp}$ a la ganancia medida de 3927 ch/Vpp.
El déficit es el promedio sobre fase de muestreo uniforme.

| familia | $f(u)$ | $u_p$ | $w_u$ | $\tau$ [µs] | $\lvert\hat y'\rvert W$ | $K$ | $N_{\mathrm{1\,LSB}}$ | FF | déficit de pico [ch] |
|---|---|---|---|---|---|---|---|---|---|
| `cr` | $(1-e^{-u/0.05})e^{-u}$ | 0.152 | 0.867 | 2.31 | **21.20** | **15.78** | 2.8 | 1.343 | 0.041 |
| `cr_rc` | $u\,e^{-u}$ | 1.000 | 2.446 | 0.82 | 6.65 | 5.99 | 4.5 | 1.111 | 0.016 |
| `cr_rc4` | $u^4e^{-u}/24$ | 4.000 | 4.755 | 0.42 | **2.20** | 5.65 | 4.6 | 1.076 | 0.015 |
| `triangular` | rampa / rampa | 1.000 | 1.000 | 2.00 | 1.00 | $0$ (quiebre) | **0.1** | 1.007 | **3.91** |
| `trapezoidal` | rampa / meseta / rampa | $[1,2]$ | 2.000 | 1.00 | 2.00 | $0$ (meseta) | **125.1** | 1.000 | **0.00** |
| `bipolar` | $(1-u/2)\,u\,e^{-u}$ | 0.586 | 1.199 | 1.67 | 5.20 | 4.91 | 5.0 | 0.979 | 0.013 |

## A.6 La pendiente en la altura máxima es lo que discrimina

El estimador de pico (`amp_src=0`) toma **una** muestra: la mayor del pulso. El
muestreo casi nunca cae en el máximo verdadero, así que siempre subestima. Si la
mejor muestra queda a distancia $d$ del ápice, con $d \sim \mathcal U[0,\,T_s/2]$,
el déficit sale del desarrollo alrededor de $t_p$:

$$\hat y(t_p + d) = 1 + \hat y'(t_p)\,d + \tfrac12\hat y''(t_p)\,d^2 + \mathcal O(d^3)$$

**Para cinco de las seis familias $\hat y'(t_p) = 0$.** El término lineal se anula
y el déficit es de segundo orden:

$$\delta_2 = \frac{K}{2}\left(\frac{d}{W}\right)^2 \;\le\; \frac{K}{8}\left(\frac{T_s}{W}\right)^2 = 2\times10^{-6}\,K$$

Con $K \approx 6$ eso da $\sim$12 ppm, o **0.016 ch $\approx$ 4 µV**: tres órdenes
por debajo del piso de 0.43 mV de la campaña. Y es contraintuitivo — la `cr`,
con el ápice casi tres veces más cerrado, sigue dando 0.041 ch. Su problema no es
el ápice, es la cola y la línea de base.

La **triangular** es la única con derivada discontinua en el máximo,
$\hat y'(t_p^{\mp}) = \pm1/W$. El término lineal sobrevive y el déficit pasa a
primer orden:

$$\delta_1 = m\,\frac{d}{W}, \quad m = \lvert\hat y'\rvert W = 1 \quad\Longrightarrow\quad \overline{\delta_1} = \frac{m\,T_s}{4W} = 1.0\times10^{-3}, \quad \delta_1^{\max} = \frac{m\,T_s}{2W} = 2.0\times10^{-3}$$

O sea 3.9 ch de sesgo medio, 7.9 ch de recorrido y 2.3 ch de rms: un factor
$\sim$250 sobre las demás. Dos consecuencias, las dos medidas:

- **Sesgo de ganancia.** El déficit es proporcional a la amplitud, así que es
  error de ganancia puro y no de INL. La triangular es la de ganancia relativa
  más baja de las cinco, **0.9957** (−0.43 %), y la trapezoidal la más alta,
  **1.0007**. El ADC predice sólo −0.10 %; el resto lo aporta el **propio ARB**,
  que muestrea el vértice a 32.8 MSa/s: $m\,T_{\mathrm{arb}}/(4W) = 0.38\ \%$.
  Suma $\approx 0.48\ \%$ contra 0.43 % medido — cierra dentro de la deriva de la
  campaña. **El supuesto fuerte es que el filtro de reconstrucción del DAC no
  suaviza el vértice más que esto**, así que es coincidencia dentro del piso y no
  medición. Falsable barato: repetir sólo la triangular con `--width 8e-6` debe
  bajar el déficit un factor 4 exacto.
- **Ensanchamiento del fotopico.** El déficit es aleatorio pulso a pulso (la fase
  de muestreo no está correlacionada con el disparo), así que ensancha. La
  triangular da el FWHM espectral más grande, **7.37 ch**, y la trapezoidal el más
  chico, **5.55 ch**, contra 6.31 ch de la `cr_rc` de referencia.

Como triangular y trapezoidal comparten factor de forma exacto (§A.3), los
1.8 ch que las separan en el fotopico son **jitter de muestreo del ápice y nada
más**. El estimador de carga es inmune a todo esto ($\sigma/\sqrt N$, sin
dependencia de la fase), y por eso tener los dos conmutables en el mismo
bitstream *es* el experimento
([`mca_pulse_feature.sv:36-43`](../../modulos/mca/rtl/mca_pulse_feature.sv)).

## A.7 Cómo reproducir la tabla

```bash
# sin placa y sin generador: reconstruye las formas y verifica contra el
# factor de forma medido en formas_inl.npz
python3 campanas/graficar_formas.py --out datos/formas_20260814_203920
```

## Bibliografía

- **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010 —
  cap. 16 (conformado de pulsos y restauración de línea de base).
- **V. T. Jordanov, G. F. Knoll**, *Digital synthesis of pulse shapes in real
  time for high resolution radiation spectroscopy*, Nucl. Instrum. Methods A
  **345** (1994) 337 — el trapezoidal digital.
