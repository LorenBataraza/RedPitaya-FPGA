# Las familias de forma de pulso, en volts contra tiempo

Gráficas del catálogo de formas de amplificador de conformado (Knoll, cap. 16)
que usa la campaña de INL vs forma, [`run_formas.py`](../../run_formas.py).

**Corre en la PC, sin placa y sin Rigol.**

```bash
python3 graficar_formas.py                 # a datos/formas_<la más reciente>
python3 graficar_formas.py --fwhm 4e-6     # otra consigna de ancho
python3 graficar_formas.py --vpp 1.0 --out /tmp
```

## Qué se grafica, exactamente

La **onda que se le cargó al generador**, reconstruida con las mismas funciones
puras que usó la campaña
([`shaped_train_wave`](../../rigol_dg4162.py) con `n_pulses=1`). No es un dibujo
ni una aproximación: es el mismo array.

Lo que **no** es: las ondas capturadas por el ADC. La campaña guardó centroides,
ganancias, INL y factores de forma, pero no guardó trazas, así que los pulsos
capturados de estas seis familias no existen en disco. Lo que sí se hace es
anotar sobre cada forma **los números medidos en la placa**, leídos de
`formas_inl.npz`.

Para que eso no sea un acto de fe, el script **recalcula el factor de forma
sobre la traza que grafica y lo contrasta contra el medido**, con la misma
definición del RTL (área positiva / (pico · FWHM)). Las seis cierran a 0.00 %:

```
  familia       FWHM [µs]   ff calc  ff medido      dif
  cr                2.001    1.3433     1.3434    0.00 %
  cr_rc             2.000    1.1110     1.1110    0.00 %
  cr_rc4            2.000    1.0764     1.0764    0.00 %
  triangular        2.014    1.0071     1.0071    0.00 %
  trapezoidal       2.000    0.9999     0.9999    0.00 %
  bipolar           2.000    0.9789     0.9789    0.00 %
```

Si eso cierra, lo que se ve en las figuras es lo que se midió.

## El catálogo

Todas con el **mismo FWHM** (2 µs) y la **misma altura de pico** (0.25 V con la
consigna de 0.5 Vpp). Ese es el diseño de la campaña: si la amplitud reportada
cambia al cambiar la forma, el error es de la cadena de medición y no del
estímulo.

| familia | qué es | factor de forma | INL de pico | por qué está |
|---|---|---|---|---|
| `cr` | una diferenciación, `(1−e^{−u/r})·e^{−u}` | **1.343** | 1.08 % FS | la más asimétrica: ápice de pocas muestras, el **peor caso** para el estimador de pico |
| `cr_rc` | `u·e^{−u}`, pico en u=1 | 1.111 | 1.09 % FS | la semi-gaussiana clásica, la más parecida a la campaña publicada. Es la **referencia** |
| `cr_rc4` | `u⁴e^{−u}/4!`, pico en u=4 | 1.076 | 1.09 % FS | cuatro integraciones: más simétrica y más parecida a una gaussiana, a costa de un pulso más largo |
| `triangular` | rampa y rampa | 1.007 | 1.04 % FS | ápice puntiagudo con soporte finito |
| `trapezoidal` | rampa, techo plano, rampa | **1.000** | 1.09 % FS | el **mejor caso** para el pico: el ápice dura y el ADC cae sobre el máximo muchas veces |
| `bipolar` | CR-RC-CR, cruce por cero en u=2 | 0.979 | **no medible** | doble diferenciación; el lóbulo negativo es lo que más estresa la segmentación |

Dos detalles que hacen al par triangular/trapezoidal el control ideal: **todo
trapecio simétrico tiene área = pico·FWHM exactamente**, y la triangular es su
caso límite, así que las dos tienen el mismo factor de forma 1.000 y caen sobre
la misma recta de pico-vs-carga. Cualquier diferencia entre ellas es del ápice y
de nada más.

**La bipolar no se pudo medir**, y eso también es un resultado: el 50 % de sus
eventos cerró por `maxlen` y no entró al histograma. El RTL recorta a cero
(`xc = max(x,0)` en `mca_pulse_feature.sv:149`) y el seguidor de línea de base
queda congelado durante el pulso, así que el lóbulo negativo —la mitad del área—
se pierde y la segmentación se descontrola.

## Las figuras

### `familias.png` — una familia por panel

Cada una en volts contra microsegundos, con la marca del FWHM, la línea del
umbral del MCA (12.2 mV = 100 cuentas) y, anotados, el factor de forma, la INL y
la ganancia **medidos en placa**.

Los ejes x **no** están compartidos, a propósito: las familias difieren en largo
por un factor 8 —la cola de la CR llega a 25 µs y el trapecio termina en 3— así
que un eje común aplasta a las compactas contra el margen izquierdo y no se ve
la forma, que es lo único que esta figura tiene que mostrar.

Lo que hay que mirar: **todas tienen el mismo FWHM y la misma altura**, y aun así
son pulsos completamente distintos. La CR gasta casi toda su carga en una cola
que dura diez anchos; el trapecio no tiene cola. Esa es la variable que la
campaña barre.

### `familias_superpuestas.png` — las seis juntas

Dos paneles:

**(a) el estímulo.** Las seis sobre el mismo eje, mismo FWHM y misma altura, así
que lo único que cambia es la forma. La leyenda lleva el factor de forma de cada
una, y se ve que ordena exactamente por cuánta cola tiene el pulso:
`cr` (1.343) > `cr_rc` (1.111) > `cr_rc4` (1.076) > `triangular` (1.007) >
`trapezoidal` (1.000). Sombreado, el lóbulo negativo de la bipolar.

**(b) lo que integra el RTL**, con el recorte `xc = max(x, 0)`. Es el panel que
explica de un vistazo por qué la bipolar quedó afuera: lo que en (a) era la mitad
negativa del pulso, acá simplemente no está.

## La conexión con el estudio de apilamiento

El **factor de forma** de esta campaña, `área/(pico·FWHM)`, **es exactamente el
cociente Q/pico** que [`tests/pile-up/`](../pile-up/) usa para discriminar
eventos apilados. Las dos campañas miden la misma cantidad por motivos
distintos: acá para preguntar cuánto depende la amplitud reportada de la forma,
allá para preguntar si un evento contiene más de un pulso.

[`pico_vs_carga.py`](../pile-up/pico_vs_carga.py) lleva esto al plano donde la
campaña lo mide: hace un Monte-Carlo de eventos **dobles y triples** con la
CR-RC⁴ y grafica pico contra carga. La recta de eventos limpios sale con
pendiente 2.121 µs contra el techo teórico `factor_forma × FWHM = 1.0764 × 2 µs
= 2.153 µs` (la ventana por histéresis corta la cola), y los apilados abren
rectas propias de pendiente 1.27× y 1.77×.

De ahí sale una consecuencia práctica que conviene tener presente: **el corte por
factor de forma hay que recalibrarlo si se cambia la forma del pulso**. El lugar
geométrico de una `cr` está en 1.343 y el de un trapecio en 1.000 — un 34 % de
diferencia, contra los ~0.1 % de dispersión que tiene el cociente dentro de una
misma familia. Un corte calibrado con una forma y aplicado a otra rechazaría
todo.

## Bibliografía

- **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010 —
  cap. 16 (amplificadores de conformado y sus formas de salida).
