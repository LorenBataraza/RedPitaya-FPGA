# Apilamiento: cuánto deforma el espectro y cuánto lo corrige un corte por forma

Monte-Carlo del apilamiento sobre el MCA. Responde dos preguntas que en la placa
no se pueden contestar, porque no existe el espectro "sin apilamiento" contra el
cual comparar:

1. **¿Cuánto deforma el apilamiento el histograma medido**, contra el que
   deberíamos medir?
2. **¿Cuánto de esa distorsión saca un corte por factor de forma** (cociente
   carga/pico), y **¿hace falta hardware nuevo o alcanza con el eje de forma que
   el RTL ya calcula?**

**Corre en la PC, sin placa y sin datos medidos.** El estímulo es la misma forma
semi-gaussiana de la campaña de referencia: `detector_pulse` con FWHM de 2 µs y
cola τ = 186 muestras, la medida sobre 7054 pulsos reales.

```bash
python3 test_pileup.py      # valida la réplica del RTL (~2 min)
python3 montecarlo.py       # el barrido completo (~2 min)
python3 graficar.py         # las cinco figuras, sin re-simular
```

## Resultado

A **100 kcps**, con el espectro de una línea, y con la banda del corte en k = 3σ:

| modo | discriminador | continuo sobre el tope | L1 al espectro de referencia | eficiencia | apilados rechazados |
|---|---|---|---|---|---|
| 0 (histéresis) | *sin corte* | 32.4 % | 0.894 | — | — |
| 0 | **Q/pico** | **0.8 %** | **0.135** | **100.0 %** | **99.1 %** |
| 0 | Q_cola/Q_tot *(ya en HW)* | 28.9 % | 0.764 | 100.0 % | 29.6 % |
| 1 (compuertas fijas) | *sin corte* | 22.7 % | 0.525 | — | — |
| 1 | Q/pico | 7.2 % | 0.227 | 100.0 % | 45.6 % |
| 1 | Q_cola/Q_tot *(ya en HW)* | 22.7 % | 0.525 | 100.0 % | **0.0 %** |

Con el espectro realista (dos líneas + continuo Compton) la conclusión es la
misma: modo 0 con Q/pico saca el continuo de 10.4 % a **0.4 %** rechazando el
**97.9 %** de los apilados sin perder un solo evento limpio.

Tres conclusiones, en orden de importancia:

### 1. El rechazo de apilamiento que el RTL ya tiene no hace nada

A 100 kcps entre el **40 %** y el **47 %** de los eventos contiene más de un
pulso, y `cnt_pileup` marca entre el **0.00 %** y el **0.45 %**. Los dos
mecanismos fallan por razones
distintas y las dos son medibles:

- **Modo 0**: cierra por `cfg_maxlen`, que vale 4096 muestras. La ventana de un
  pulso de la línea mide 779. Nunca llega.
- **Modo 1**: `gate_2nd` exige que la señal **baje de `thr_lo` y vuelva a cruzar
  `thr_hi`** dentro de la compuerta. Con el pulso de la campaña la cola tarda
  **788 muestras** en bajar de `thr_lo = 60`, y la compuerta mide **384**: la
  señal no puede volver a cruzar desde abajo porque nunca llegó abajo. La
  bandera sólo se dispara cuando el PRIMER pulso es chico —con A = 200 la cola
  baja en la muestra 367 y ahí sí funciona—. Está en `test_pileup.py [3]`.

### 2. El eje de forma que ya está en el hardware NO alcanza

`Q_cola/Q_total` rechaza el 29.6 % de los apilados en modo 0 y **exactamente
nada** en modo 1. El motivo se ve en `mapa_forma.png`: con `gate_short = 32`
medido desde el disparo, la cola se lleva el 94 % de la carga, el cociente vive
en 60/64 y **le quedan tres valores útiles de los 64 del eje**. No hay rango
dinámico para discriminar.

**Q/pico necesita un divisor nuevo en el RTL.** Es el mismo bloque
`mca_div_restore.sv` que ya existe, instanciado con otro numerador y otro
denominador: `floor(pico · 2^AW / Q_total)` —conviene invertirlo respecto de
Q/pico para que el cociente caiga en [0,1) y el divisor restaurador sirva sin
cambios—. Cuesta un segundo divisor y 6 ciclos más de latencia, sobre un evento
que ya dura cientos de muestras.

### 3. Para trabajar a tasa alta conviene la ventana por histéresis, no las compuertas fijas

Esto **corrige la conclusión de la campaña anterior**, que se tomó a una sola
tasa. Sin corregir, el modo 1 deforma menos (continuo 22.7 % contra 32.4 %),
simplemente porque su ventana es más corta (384 contra 779 muestras) y junta
menos apilamiento. Pero es **mucho más difícil de corregir**:

| | modo 0 | modo 1 |
|---|---|---|
| continuo sin corte | 32.4 % | 22.7 % |
| continuo con corte Q/pico | **0.8 %** | 7.2 % |

La razón está en `mapa_forma.png` y es geométrica. En el modo 0 la ventana se
**estira** cuando llega un segundo pulso, así que la carga crece mucho más que
el pico y los apilados se van a Q/pico de 400–1200 contra 250–290 de los
limpios: **poblaciones separadas**. En el modo 1 la compuerta se cierra a las
384 muestras pase lo que pase, así que buena parte de la carga del segundo pulso
queda **afuera**, el cociente apenas se mueve y las dos poblaciones se cruzan.

O sea: lo que hace bueno al modo 1 para la resolución —que el largo no dependa
de la señal— es exactamente lo que lo deja ciego al apilamiento. La combinación
que gana es **modo 0 + corte Q/pico**.

## El corte hay que calibrarlo contra la amplitud

`Q/pico` **no es constante**: en el modo 0 la ventana cierra cuando la cola cruza
`thr − hyst`, o sea que su largo crece con el logaritmo de la amplitud, y el
cociente deriva **+21 %** entre 110 y 7000 cuentas. Un umbral fijo cortaría los
pulsos limpios chicos y dejaría pasar los apilados grandes.

La calibración se hace con un **pulser deslizante** —amplitud uniforme sobre todo
el rango, el mismo estímulo canónico que `sliding_pulser_wave` usa para la DNL—
y no con el propio espectro fuente. **No es un detalle**: con una línea
monoenergética el lugar geométrico quedaría definido en un puñado de canales y
la interpolación extrapolaría plano hacia arriba, así que el corte rechazaría los
apilados por caer fuera del rango calibrado y no por tener la forma mal. Sería un
corte en amplitud disfrazado de corte en forma, y daría un resultado
espectacular y falso.

Con el lugar geométrico bien calibrado, `k` casi no importa: entre k = 1.5 y
k = 6 el L1 se mueve de 0.134 a 0.138 y el continuo residual de 0.53 % a 1.12 %.
La separación es tan limpia que el corte no es sensible a dónde se ponga; k = 2
ya da el 99.98 % de eficiencia.

## El límite irreducible

Ningún corte por forma puede sacar las **coincidencias cercanas**. Con Δt ≲ 60
muestras (480 ns) la suma de dos pulsos idénticos **es** un pulso de la misma
forma y el doble de amplitud: Q/pico da 290 contra 286 de un pulso limpio. Esos
eventos entran al pico suma y ahí se quedan — es el residuo en 3840 que se ve en
`corte.png` después del corte, y es el 0.9 % de apilados que sobrevive.

La única forma de atacarlos es acortar el pulso, que es un problema de
conformado y no de discriminación.

## Qué valida el simulador, y qué no

La réplica vectorizada del RTL da **los mismos eventos, cuenta por cuenta**, que
`estimadores.segmentar_rtl` e `integral_gates` —que a su vez ya están validadas
contra `tb_mca_pulse_feature.sv` y contra la placa—. Eso es el test [1] y [2], y
es lo que hace creíble todo lo demás. La réplica de referencia es un lazo muestra
a muestra a 3.8 Mmuestras/s; la vectorizada corre el barrido de 1.6e6 eventos en
2 minutos.

Además, sin que se lo haya puesto a mano, el simulador reproduce el **modelo de
tiempo muerto paralizable** `m = n·exp(−n·L₀)` con L₀ = la ventana de un pulso
aislado, dentro del 2.1 % —contra 14.8 % del no paralizable— (test [10]). Es
consistente: un arribo dentro de la ventana no la reinicia, la **estira**.

**Lo que el simulador NO reproduce**, y conviene tenerlo presente al leer los
números absolutos:

- **Sólo hay ruido blanco.** Los pulsos reales traen además jitter de forma y de
  amplitud del generador, que es irreducible. Por eso las resoluciones salen
  optimistas: el pico da σ = 1.69 cuentas contra 2.81 medidas en placa. Para las
  conclusiones sobre apilamiento no mueve la aguja, porque el ancho de la línea
  lo fija el `res_pct` de la fuente (3 % = 24 cuentas sobre 1920), diez veces
  mayor.
- **No está el seguidor IIR de línea de base**; se usa base fija (`cfg_bl_auto = 0`).
- **No están los 6 ciclos de `S_DIV`** durante los cuales un pulso nuevo se
  pierde. Son 48 ns contra ventanas de ~780 muestras: a 500 kcps afecta al
  2.4e-5 de los eventos.
- Una **diferencia de orden** que se hereda a propósito de `segmentar_rtl` para
  que la equivalencia sea exacta: si en la misma muestra se cumplen
  `len >= maxlen` y `x < thr_lo`, el RTL lo cuenta como apilamiento y la réplica
  lo cierra por histéresis. Es un caso de medida nula.

## Archivos

| Archivo | Qué es |
|---|---|
| `pileup.py` | funciones puras: forma, espectros fuente, arribos, render por grupos, réplica vectorizada del RTL en los dos modos, calibración del corte, métricas |
| `test_pileup.py` | 10 bloques de validación. Sin placa, sin datos |
| `montecarlo.py` | el barrido; guarda `.npz` + `resumen.json` en `software/datos/pileup_<fecha>/` |
| `graficar.py` | las cinco figuras, desde los `.npz` |

Las figuras: `espectros.png` (verdad / referencia / medido), `distorsion_vs_tasa.png`,
`mapa_forma.png` (dónde se separan las poblaciones), `corte.png` (antes y después),
`compromiso.png` (eficiencia contra rechazo).

### Cómo se hace viable el barrido

A 125 MSPS un segundo son 1.25e8 muestras y 50 000 eventos a 1 kcps serían 6e9.
Entre pulsos separados por más que el template no pasa nada, así que los arribos
se **agrupan** y cada grupo se renderiza en su propio array: el costo escala con
la cantidad de eventos y no con el tiempo transcurrido, y 1 kcps y 500 kcps
cuestan lo mismo. Los grupos además se cortan de a 1500 arribos, porque a tasa
alta se funden todos en uno solo y la traza se va a varios GB.

## Bibliografía

- **G. F. Knoll**, *Radiation Detection and Measurement*, 4ª ed., Wiley, 2010 —
  cap. 4 (tiempo muerto, paralizable y no paralizable), cap. 17 (discriminación
  por forma de pulso).
- **F. D. Brooks**, *A scintillation counter with neutron and gamma-ray
  discriminators*, Nucl. Instrum. Methods **4** (1959) 151 — el método de
  comparación de carga, que es el modo 1.
