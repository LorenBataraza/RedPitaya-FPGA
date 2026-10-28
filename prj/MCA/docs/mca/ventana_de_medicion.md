# La ventana de medición: las dos metodologías, y el walk que las corre

Todo lo que el MCA mide de un evento —el pico, la integral, el largo, el
cociente de forma— sale de un intervalo de muestras que el hardware decide solo:
la **ventana**. Nada se promedia entre eventos, nada se recorta después. Si la
ventana empieza o termina en el lugar equivocado, el número que llega al
histograma ya está mal y no hay análisis posterior que lo arregle.

[`mca_pulse_feature.sv`](../../modulos/mca/rtl/mca_pulse_feature.sv) implementa
**dos reglas distintas de cierre**, seleccionables en caliente con un bit
(`cfg_gate_mode`, registro `0x048`). La apertura es la misma en las dos; lo que
cambia es qué decide el final. Este documento explica las dos, por qué dan
resultados distintos sobre el **mismo** estímulo, y por qué el *amplitude walk*
—un sesgo que casi siempre se discute como un problema de *timing*— acá además
mueve el largo de la ventana y deforma el eje de forma.

Las figuras están en [`figuras/ventana/`](figuras/ventana/), con sus epígrafes
en [`figuras/ventana/README.md`](figuras/ventana/README.md). Son esquemas: la
forma del pulso es el modelo de subida y cola exponenciales, ajustado para
reproducir el largo de ventana medido en la placa.

```bash
cd prj/MCA/docs/mca/figuras/ventana
python3 figuras_ventana.py
```

---

## 1. La apertura es común: un Schmitt, no un comparador

Las dos metodologías abren igual, y conviene decirlo primero porque es la parte
que **ninguna de las dos arregla**.

La ventana abre en la primera muestra que cumple tres cosas a la vez: el
extractor está en `S_IDLE`, la señal (con la línea de base ya restada) cruza
`cfg_thr` hacia arriba, y el biestable `armed` está en 1. `armed` se pone cuando
la señal estuvo por debajo de `cfg_thr − cfg_hyst`, y se limpia al abrir. Es
exactamente la misma estructura que el trigger del osciloscopio
(`rp_adc_trig.v`), y eso es deliberado: hace que los umbrales del MCA y del
scope sean comparables entre sí.

La histéresis cumple acá un solo papel —evitar que el ruido sobre el umbral
abra decenas de ventanas por pulso— y es un papel que **las dos metodologías
necesitan**. La diferencia entre ellas aparece recién en el cierre.

Dos consecuencias de abrir por umbral que valen para los dos modos:

- **La carga por debajo del umbral se pierde siempre.** La integral arranca en
  el cruce, no en el arribo. Con el pulso del modelo eso es el 0.003 % de
  `Q_total` para un pulso de 1920 cuentas, pero el **1.3 %** para uno de 150:
  no es un offset, es una no linealidad que se concentra cerca del umbral.
- **El instante de apertura depende de la amplitud.** Es el walk, y es la
  sección 5.

---

## 2. Metodología A — ventana por histéresis (`cfg_gate_mode = 0`)

![ventana por histéresis](figuras/ventana/01_ventana_histeresis.png)

La ventana cierra cuando la señal vuelve a caer por debajo de
`cfg_thr − cfg_hyst`. Es la regla por default y el comportamiento histórico del
módulo.

| Qué | Cómo se decide |
|---|---|
| Apertura | cruce de `cfg_thr` hacia arriba, con `armed` |
| Cierre | primera muestra con `x < cfg_thr − cfg_hyst` |
| Cierre forzado | `len ≥ cfg_maxlen` → **cuenta como apilamiento** |
| Arranque de la cola | `cfg_tail_dly` muestras **después del pico** |

El rasgo que define la metodología es que **el largo lo decide la señal**:
`F_LEN` es una medición, no una constante. Eso tiene dos caras.

A favor: la ventana **se estira** cuando llega un segundo pulso, así que la
carga crece mucho más que el pico y las poblaciones limpia y apilada se separan
en el eje `Pico/Q_total`. Es lo que hace que el corte de forma funcione —continuo
sobre el fotopico de 32.4 % a 0.8 %— y es la razón por la que, a tasa alta, el
modo 0 **gana** ([`apilamiento.md`](apilamiento.md) §3).

> Que la ventana se estire en vez de reiniciarse es, en el lenguaje de tiempo
> muerto, **paralizable**: el largo del período muerto deja de ser un número y
> pasa a ser una distribución que se ensancha con la tasa. A 100 kcps el
> período muerto medio del MCA es 1.36 veces la ventana de un pulso solo. Las
> curvas están en [`tiempo_muerto.md`](tiempo_muerto.md) §"El largo de la
> ventana muerta".

En contra: el cruce de bajada cae en la parte más chata del pulso, así que el
largo lo termina decidiendo el ruido. Es la sección 4.

**Sobre `cfg_tail_dly`.** La cola se mide desde el **pico**, que es un instante
determinado por la señal y por lo tanto también ruidoso. Tiene que ser ≥ 1: con
0 queda `Q_cola == Q_total`, el RTL rechaza el evento y lo cuenta en
`cnt_rej_psd`. Con el default de 4, la cola se lleva casi toda la carga y al
cociente `Q_cola/Q_total` le quedan pocos valores útiles del eje — por eso
existe `F_INVW` (`Pico/Q_total`), que no tiene ese problema.

**Sobre `cfg_maxlen`.** Es un tope de seguridad, no un método de medición: si la
ventana llega ahí, el evento se cierra y se marca apilado. Con el default de
1024 y una ventana real de 779 **nunca llega**, que es exactamente por qué el
rechazo de apilamiento por `maxlen` no detecta nada.

---

## 3. Metodología B — compuertas de largo fijo (`cfg_gate_mode = 1`)

![compuertas fijas](figuras/ventana/02_ventana_fija.png)

La ventana cierra a `cfg_gate_long` muestras del disparo, pase lo que pase, y la
cola arranca en `cfg_gate_short` — las dos medidas **desde el disparo**, no
desde el pico. Es el método clásico de **comparación de carga** (Brooks 1959;
Knoll cap. 17), el mismo que usan los discriminadores n/γ de centelleo.

| Qué | Cómo se decide |
|---|---|
| Apertura | igual que el modo 0 |
| Cierre | `len ≥ cfg_gate_long`, siempre |
| `cfg_maxlen` | **no actúa**: el largo ya está acotado |
| Arranque de la cola | `len ≥ cfg_gate_short`, desde el **disparo** |

Medir la cola desde el disparo y no desde el pico es la mitad del punto: el
instante de pico es ruidoso (la señal es chata ahí), el del disparo no.

### El apilamiento en modo 1 necesita otra regla, y la obvia es incorrecta

La regla intuitiva —"si al cerrar la señal sigue alta, hubo un segundo pulso"—
**no funciona**, y se descubrió midiendo en la placa. Con el pulso de la línea,
al llegar a la muestra 384 la señal todavía está ~289 cuentas por encima de
`thr_lo` y le faltan 394 muestras para bajar: la regla marcaría como apilado el
**100 %** de los eventos con cualquier compuerta más corta que la cola, o sea
justo el rango útil. Peor, el cruce cae en la parte más chata del pulso, así que
el punto se corre cientos de muestras con cualquier deriva de línea de base y el
resultado no es reproducible entre corridas.

Lo que el RTL implementa es un **segundo disparo dentro de la compuerta**: la
señal tiene que bajar de `thr_lo` (`gate_rearm`) y recién después volver a
cruzar `cfg_thr` (`gate_2nd`). Es correcto, pero tiene un límite que conviene
tener presente —paneles (b) y (c) de la figura 2—: **sólo ve el apilamiento
cuando el primer pulso alcanzó a extinguirse dentro de la compuerta**. Con
A = 200 la cola baja en la muestra 309 y la bandera funciona; con A = 1920 la
cola necesita 778 muestras, el segundo pulso monta sobre ella sin pasar nunca
por debajo de `thr_lo`, y el evento se histogramea como limpio. Es el mecanismo
por el que `cnt_pileup` marca entre 0.00 % y 0.45 % donde el 40-47 % de los
eventos tiene más de un pulso ([`apilamiento.md`](apilamiento.md) §1).

---

## 4. Quién decide el cierre: la misma σ_v, dos σ_t muy distintos

![quién decide el cierre](figuras/ventana/03_quien_decide_el_cierre.png)

Ésta es la comparación que justifica que existan los dos modos, y se reduce a
una sola cuenta:

    σ_t = σ_v / |dV/dt|   evaluado donde cae el cruce

- En la **apertura**, el cruce cae en el flanco: `|dV/dt| ≈ 46 cuentas/ns`, y los
  2.8 cuentas rms del ADC dan **σ_t = 0.06 ns**. Despreciable frente a los 8 ns
  del muestreo.
- En el **cierre por histéresis**, el cruce cae en la cola, que es la parte más
  chata: `|dV/dt| ≈ 0.03 cuentas/ns` y **σ_t = 92 ns ≈ 11 muestras**. Tres
  órdenes de magnitud peor, por la sola razón de dónde cae el cruce.

Y esas muestras no son gratis: cada una entra en la integral con el valor que la
señal tiene ahí, que es ≈ `thr_lo`. Un temblor de ±11 muestras a nivel 50 son
±550 cuentas de `Q_total`.

El Monte Carlo de la figura 3 —4000 eventos, mismo pulso, fase de muestreo
uniforme y **sólo** ruido blanco del ADC— da:

| | largo de la ventana | resolución de `Q_total` |
|---|---|---|
| modo 0, histéresis | 765 ± 6.1 muestras | **0.080 %** |
| modo 1, compuerta fija | 384 ± 0 muestras | **0.024 %** |

Medido offline sobre 7054 pulsos reales, el salto es **0.528 % → 0.149 %**
([`software/API/modelo_rtl/`](../../software/API/modelo_rtl/)). El Monte Carlo
reproduce la *razón* (3.3 contra 3.5) pero no el valor absoluto, y la diferencia
está identificada: le falta el **error de línea de base**, que se multiplica por
el largo —variable— de la ventana y empuja en la misma dirección.

Por qué la compuerta fija inmuniza: sus dos bordes caen en zonas de pendiente
≈ 0 —línea de base antes del disparo, cola ya extinguida después—, así que
desplazarlos no cambia la suma. Hereda sólo la incertidumbre de la **apertura**
(sub-ns) más la fase de muestreo (±Ts/2).

### Cuál usar

No hay un ganador, y conviene decirlo explícito porque la conclusión cambió
entre campañas:

| | modo 0 (histéresis) | modo 1 (compuerta fija) |
|---|---|---|
| Resolución de la integral | 0.528 % | **0.149 %** |
| Largo de la ventana | 779 muestras, variable | **384**, constante |
| Separa apilados en el eje de forma | **sí** (continuo 32.4 % → 0.8 %) | apenas (→ 7.2 %) |
| `cnt_pileup` sirve | no (`maxlen` nunca llega) | sólo si el 1er pulso es chico |
| `Q/pico` constante con la amplitud | **no**, deriva 21 % | sí |

Lo que hace bueno al modo 1 para la resolución —que el largo no dependa de la
señal— es exactamente lo que lo deja ciego al apilamiento. **A tasa baja y con
estímulo limpio, modo 1. A tasa alta, modo 0 con corte por forma**, que es la
combinación que gana en [`apilamiento.md`](apilamiento.md).

---

## 5. El problema del *amplitude walk*

![amplitude walk](figuras/ventana/04_amplitude_walk.png)

### Qué es

![los tres pulsos enteros y el Δt](figuras/ventana/05_walk_tres_pulsos.png)

Un umbral fijo no se cruza en el mismo momento para pulsos de distinta
amplitud. Tres pulsos de la misma forma que llegan **exactamente a la vez**, de
1600, 400 y 150 cuentas, cruzan `cfg_thr = 100` separados por **39.4 ns**, o
4.9 muestras, y el grande cruza primero porque sube más rápido.

La figura muestra las tres ondas enteras y los dos instantes que el sistema
decide sobre cada una. El Δt de **apertura** —el que va al timestamp— es de
nanosegundos y no se ve a la escala del pulso; hay que ampliar el flanco. El de
**cierre** se ve de lejos: **3.91 µs**, 488 muestras, porque ahí el cruce ocurre
sobre una cola exponencial. El mismo efecto, dos órdenes de magnitud de
diferencia según dónde caiga el cruce.

Con una rampa de subida lineal la estimación habitual es

    t_cruce ≈ t_r · thr / (0.8 · A)

Acá la subida es exponencial, más empinada al principio que su pendiente media,
así que esa fórmula es una **cota superior**: el modelo exacto da 2.1 ns para
A = 1920 donde la fórmula estima 6.5. La dependencia en `1/A` es la misma.

### Por qué es un problema distinto del jitter

Ésta es la parte que conviene no mezclar: **el walk no tiene dispersión**. Dos
pulsos de la misma amplitud cruzan en el mismo momento siempre. Es un **sesgo
determinista cuyo valor depende de la variable que se está midiendo**, que es
la peor combinación posible:

- No se promedia: tomar más eventos no lo reduce.
- No aparece como un ensanchamiento en una medición monoenergética, donde todos
  los pulsos tienen la misma amplitud y por lo tanto el mismo walk. **Aparece
  recién cuando el espectro tiene más de una línea**, o cuando se compara contra
  una referencia externa.
- Es corregible, justamente porque es determinista — pero hay que conocer `A`.

Y es grande comparado con todo lo demás —panel (b)—: para amplitudes por debajo
de ~1000 cuentas supera a `Ts/2 = 4 ns`, la cuantización del muestreo, y está
una o dos décadas por encima del σ_t que produce el ruido del ADC en el mismo
cruce. En el presupuesto de [`fuentes_de_jitter.md`](fuentes_de_jitter.md) es el
único término de tiempo que no está dominado por el período de muestreo.

### Dónde entra en este MCA — tres lugares, no uno

**1. En el timestamp.** El obvio: `ts` es la muestra de apertura, así que
arrastra el walk completo. Si se usan los timestamps para coincidencias o para
medir Δt entre canales, dos eventos simultáneos de distinta energía van a
aparecer separados por decenas de ns. El RTL **no tiene CFD**; la corrección hay
que hacerla en software, que es posible porque la amplitud del mismo evento está
disponible.

**2. En la integral, cerca del umbral.** Como la ventana abre en el cruce, la
carga anterior se pierde, y cuanto más tarde cruza —o sea, cuanto más chico es
el pulso— más se pierde. Con el modelo: 0.003 % de `Q_total` a 1920 cuentas,
0.53 % a 200 y 1.3 % a 150. Es una **no linealidad integral** concentrada en la
primera década sobre el umbral, en la misma dirección que todo lo demás (mide de
menos).

**3. En el largo de la ventana, y sólo en el modo 0.** Éste es el que suele
pasarse por alto. El cierre por histéresis es *otro* cruce de umbral, así que
también camina con la amplitud — y mucho más, porque la cola es exponencial:

    F_LEN(A) ≈ τ_d · ln(A / thr_lo)

En el panel (c) de la figura 4: 309 muestras para un pulso de 200 cuentas y 1073
para uno de 8000. La ventana de un evento grande dura **tres veces y media** la
de uno chico, y en la figura 5 eso son los 3.91 µs que separan los tres cierres.
De ahí sale la consecuencia práctica más importante del documento:

> **`Q_total/pico` no es constante.** El eje de forma deriva 29 % de punta a
> punta en el modelo, 21 % medido en la placa. Un corte de forma con umbral
> fijo cortaría los pulsos limpios chicos y dejaría pasar los apilados grandes.
> Por eso el corte se calibra como un **lugar geométrico contra la amplitud**, y
> con un **pulser deslizante**, no con el espectro fuente: con una línea
> monoenergética el lugar geométrico queda definido en un puñado de canales y el
> corte terminaría rechazando por caer fuera del rango calibrado y no por tener
> la forma mal — un corte en amplitud disfrazado de corte en forma, que da un
> resultado espectacular y falso.

El modo 1 elimina el tercer efecto por construcción —su largo no depende de
nada— pero **no toca los otros dos**: la apertura sigue siendo un umbral fijo.
Cambiar de modo de ventana no es una corrección de walk.

### Cómo se corrige, en orden de costo

1. **En software, conociendo `A`.** El evento ya trae pico e integral, así que
   `t_corregido = ts − k/A` con `k` ajustado contra un pulser deslizante. Cuesta
   cero en hardware y sirve para el 95 % de los usos.
2. **Interpolando el cruce.** Con dos muestras alrededor del umbral y la
   pendiente local se recupera el cruce con precisión `σ_v/pendiente`, sub-ns
   para pulsos grandes. Mejora la cuantización a `Ts` además del walk.
3. **CFD, discriminador de fracción constante.** Dispara cuando la señal llega a
   una fracción fija de su propia amplitud, así que el instante es independiente
   de `A` por construcción. Es la solución correcta y la que no existe hoy en el
   RTL; cuesta una línea de retardo y un comparador de cruce por cero. Cuánto
   gana, y por qué en el event ring se puede hacer en software sobre las
   muestras ya capturadas: [`timestamp_cfd.md`](timestamp_cfd.md).

### Cómo se mide

Barrido de amplitud con el **pulser deslizante** —el mismo estímulo canónico que
se usa para la DNL—, graficando `ts` contra la amplitud del mismo evento. La
curva tiene que ser una `1/A`; su coeficiente es el `k` de la corrección 1. Es
la entrada "Walk de amplitud" del presupuesto de
[`fuentes_de_jitter.md`](fuentes_de_jitter.md) §6, la única que sigue sin medir.

---

## Dónde está cada cosa

| Qué | Dónde |
|---|---|
| La implementación | [`mca_pulse_feature.sv`](../../modulos/mca/rtl/mca_pulse_feature.sv) |
| Los registros | [`register_map_mca.md`](register_map_mca.md) |
| El presupuesto de jitter y el walk en el timestamp | [`fuentes_de_jitter.md`](fuentes_de_jitter.md) |
| Qué modo conviene a cada tasa, y el corte de forma | [`apilamiento.md`](apilamiento.md) |
| La réplica offline de las dos reglas | [`software/API/modelo_rtl/`](../../software/API/modelo_rtl/) |
| Las figuras y sus epígrafes | [`figuras/ventana/`](figuras/ventana/) |
