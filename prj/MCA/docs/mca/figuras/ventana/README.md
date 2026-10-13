# Figuras: la ventana de medición

Cinco figuras para [`../../ventana_de_medicion.md`](../../ventana_de_medicion.md):
las dos reglas de cierre que implementa
[`mca_pulse_feature.sv`](../../../../modulos/mca/rtl/mca_pulse_feature.sv)
—histéresis y compuertas fijas—, qué decide el largo en cada una, y el
*amplitude walk*. Las genera [`figuras_ventana.py`](figuras_ventana.py), con la
misma convención que el resto de [`figuras/`](../): sin texto adentro, paleta y
rcParams de [`../figuras_resolucion.py`](../figuras_resolucion.py).

```bash
cd prj/MCA/docs/mca/figuras/ventana
python3 figuras_ventana.py     # además imprime las tablas que cita el doc
```

Son **esquemas**: no entra ningún `.npz`. La forma del pulso es subida y cola
exponenciales (`t_r = 100 ns` 10-90 %, `τ_d = 1650 ns`), con `τ_d` elegido para
que el cierre por histéresis caiga en las **779 muestras** medidas en la placa.
Son 206 muestras de cola contra las 186 medidas sobre 7054 pulsos reales: la
diferencia es que acá `thr_lo` vale 50 —el default— y la campaña midió con 60.
Los registros son los defaults de `mca_top.sv`: `cfg_thr = 100`,
`cfg_hyst = 50`, `cfg_maxlen = 1024`, `cfg_tail_dly = 4`, `cfg_gate_short = 32`,
`cfg_gate_long = 384`. El único número que sale de una simulación y no de una
fórmula es la resolución de `Q_total` de la figura 3, un Monte Carlo de 4000
eventos con **sólo** el ruido blanco del ADC (σ_v = 2.8 cuentas).

| Figura | Qué muestra | Datos |
|---|---|---|
| [`01_ventana_histeresis.png`](01_ventana_histeresis.png) | La ventana del modo 0: abre en el cruce de subida de `cfg_thr`, cierra en el de bajada de `cfg_thr − cfg_hyst`, y el cronograma de la FSM que lo implementa | esquema |
| [`02_ventana_fija.png`](02_ventana_fija.png) | La ventana del modo 1: `cfg_gate_short` y `cfg_gate_long` medidas **desde el disparo**, y los dos casos de apilamiento —el que `gate_2nd` marca y el que no— | esquema |
| [`03_quien_decide_el_cierre.png`](03_quien_decide_el_cierre.png) | Por qué las dos reglas no dan lo mismo: la pendiente en el punto de cierre, la dispersión del largo y la de `Q_total` | esquema + Monte Carlo |
| [`04_amplitude_walk.png`](04_amplitude_walk.png) | El walk del cruce de umbral contra la amplitud, comparado con el ruido y con `Ts/2`, y lo que le hace al largo de la ventana del modo 0 | esquema |
| [`05_walk_tres_pulsos.png`](05_walk_tres_pulsos.png) | Las tres ondas **enteras**, del arribo al cierre, y el Δt entre los instantes en que el sistema declara cada evento: 39.4 ns en el disparo, 3.91 µs en el cierre | esquema |

---

## Epígrafes

**Figura 1.** Determinación de la ventana por **histéresis** (`cfg_gate_mode =
0`), con un pulso de 1920 cuentas. (a) La ventana abre en la muestra donde la
señal cruza `cfg_thr` hacia arriba estando previamente armada —es decir,
habiendo estado por debajo de `cfg_thr − cfg_hyst`— y cierra en la primera
muestra que vuelve a caer por debajo de ese mismo nivel inferior: un Schmitt,
el mismo que usa el trigger del osciloscopio. `Q_total` es la suma de todas las
muestras de la ventana y `Q_cola` la de las que están a `cfg_tail_dly` o más
del pico; con el default `cfg_tail_dly = 4` la cola se lleva casi toda la
carga, que es el problema de rango dinámico del eje de forma. `cfg_maxlen` es
el tope: si la ventana llega ahí, el evento se cierra y se cuenta como
apilamiento. El largo que resulta, 778 muestras, reproduce las 779 medidas en
la placa. (b) El mismo intervalo visto como cronograma de la FSM: los dos
comparadores, `armed`, el estado `S_ACTIVE`, `in_tail` y el pulso de cierre.
`armed` se limpia al abrir y vuelve a ponerse en la misma muestra en que la
señal cae por debajo del nivel inferior, que es la que cierra. Nótese que
`x ≥ thr_hi` cae mucho antes que el cierre: lo que cierra la ventana es el
cruce del nivel **inferior**, no el del umbral.

**Figura 2.** Determinación de la ventana por **compuertas fijas**
(`cfg_gate_mode = 1`), el método de comparación de carga (Brooks 1959; Knoll
cap. 17). (a) La apertura es la misma que en la figura 1, pero el cierre está a
`cfg_gate_long = 384` muestras del disparo pase lo que pase, y la cola arranca
en `cfg_gate_short = 32` muestras del **disparo**, no del pico. Al cerrar, el
pulso todavía está 289 cuentas por encima de `cfg_thr − cfg_hyst` y le faltan
394 muestras para bajar: por eso la regla intuitiva de apilamiento —"si al
cerrar la señal sigue alta, hubo un segundo pulso"— marcaría el 100 % de los
eventos limpios con cualquier compuerta más corta que la cola. (b) La regla que
el RTL sí implementa: `gate_rearm` cuando la señal baja de `cfg_thr − cfg_hyst`
dentro de la compuerta, y `gate_2nd` cuando después vuelve a cruzar `cfg_thr`.
Con un primer pulso chico (200 cuentas) la cola baja en la muestra 309, dentro
de la compuerta, y el segundo pulso queda marcado. (c) Con un primer pulso de
la línea (1920 cuentas) la cola necesita 778 muestras para bajar, el segundo
pulso monta sobre ella sin que la señal pase nunca por debajo del nivel
inferior, y `gate_2nd` queda en 0: el evento se histogramea como limpio. Es el
mecanismo por el que `cnt_pileup` marca entre 0.00 % y 0.45 % donde el 40-47 %
de los eventos tiene más de un pulso ([`../../apilamiento.md`](../../apilamiento.md) §1).
(d) Los flags de los dos casos, con la compuerta sombreada.

**Figura 3.** Quién decide el cierre en cada modo. (a) Módulo de la derivada
del pulso contra el tiempo, en ejes logarítmicos. En el cruce de apertura la
pendiente es 46 cuentas/ns y el ruido del ADC (σ_v = 2.8 cuentas) se traduce en
σ_t = 0.06 ns; en el cruce de cierre por histéresis, que cae en la parte más
chata de la cola, la pendiente es 0.03 cuentas/ns y el mismo ruido da
σ_t = 92 ns, unas 11 muestras. Son tres órdenes de magnitud por la sola razón
de dónde cae el cruce. El notch es el pico, donde la derivada pasa por cero.
(b) Monte Carlo de 4000 eventos del mismo pulso, con fase de muestreo uniforme
y ruido blanco: el largo de la ventana del modo 0 tiene σ = 6.1 muestras —el
muestreo a 8 ns recorta algo la estimación continua—, el del modo 1 es
exactamente constante. (c) La distribución de `Q_total` que sale de ahí: 0.080 %
en modo 0 contra 0.024 % en modo 1, un factor 3.3. Medido sobre 7054 pulsos
reales el salto es 0.528 % → 0.149 %, factor 3.5: el Monte Carlo reproduce la
razón pero no el valor absoluto, porque sólo tiene ruido blanco y le falta el
error de línea de base, que se multiplica por el largo —variable— de la
ventana.

**Figura 4.** *Amplitude walk*: el instante en que un umbral fijo se cruza
depende de la amplitud del pulso. (a) Tres pulsos de 150, 400 y 1600 cuentas
con el **mismo** instante de arribo. El de 1600 cruza `cfg_thr` a los 2.6 ns y
el de 150 a los 42 ns: 39 ns de corrimiento, casi cinco períodos de muestreo,
sin que nada haya llegado antes. No es ruido —no tiene dispersión— sino un
sesgo determinista que depende de la variable que se está midiendo. (b) El
corrimiento contra la amplitud, en ejes logarítmicos. Azul: el modelo exacto,
proporcional a 1/A. Naranja: la estimación habitual `t_r·thr/(0.8·A)`, que
supone una rampa lineal y acá es una cota superior, porque la subida
exponencial es más empinada al principio que su propia pendiente media. Rojo
punteado: el σ_t que el ruido del ADC produce en el mismo cruce, una o dos
décadas más abajo. Gris: la cuantización del muestreo, `Ts/2 = 4 ns`, que el
walk supera para toda amplitud por debajo de ~1000 cuentas. (c) Lo que el walk
le hace a la ventana. En modo 0 el cierre es otro cruce de umbral, así que el
largo de la ventana crece con el logaritmo de la amplitud: de 309 muestras a
200 cuentas a 1073 a 8000. Como consecuencia `Q_total/pico` —el eje de forma—
no es constante: deriva 29 % de punta a punta en el esquema, 21 % medido en la
placa, y por eso el corte de forma hay que calibrarlo contra la amplitud. En
modo 1 el largo no depende de la amplitud, y esa es exactamente la propiedad
que lo deja ciego al apilamiento.

**Figura 5.** Las mismas tres ondas de la figura 4, enteras y con los dos
instantes que el sistema decide sobre cada una. (a) Del arribo al cierre, con
los tres pulsos llegando **exactamente a la vez**. Los discos llenos son el
disparo —la muestra en que el evento queda declarado y se graba el timestamp— y
los círculos vacíos el cierre de la ventana por histéresis. A esta escala los
tres disparos son un solo punto: el walk de apertura no se ve. El del cierre sí,
y mucho: **3.91 µs**, o 488 muestras, entre el pulso de 150 cuentas y el de
1600, porque el cierre es un cruce sobre una cola exponencial. La banda roja
marca lo que amplía (b). (b) El flanco, con la grilla de muestreo del ADC de
fondo. El pulso de 1600 cuentas cruza `cfg_thr` a los 2.6 ns del arribo, el de
400 a los 11.4 y el de 150 a los 42.0: **39.4 ns de punta a punta, 4.9
muestras**, sin que ninguno haya llegado antes que otro. Los dos tramos son
8.8 ns entre 1600 y 400, y 30.6 ns entre 400 y 150 — el walk se acelera hacia
abajo porque va como `1/A`, así que casi todo el error se concentra en la
primera década sobre el umbral.
