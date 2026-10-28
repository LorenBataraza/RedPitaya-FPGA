# Figuras: las dos fórmulas de Knoll

El modelo **corto**, el del capítulo 4 de Knoll, para la sección "Las dos
fórmulas de Knoll" de [`../../tiempo_muerto.md`](../../tiempo_muerto.md). Un
solo parámetro τ, arribos de Poisson, y una sola idea —`m = n ·` fracción
viva— de la que salen los dos modelos. Las genera
[`figuras_knoll.py`](figuras_knoll.py).

```bash
cd prj/MCA/docs/mca/figuras/tiempo_muerto
python3 figuras_knoll.py             # además imprime las tablas que cita el doc
```

| Figura | Qué muestra | Datos |
|---|---|---|
| [`knoll_01_tasa_registrada.png`](knoll_01_tasa_registrada.png) | `mτ` contra `nτ` para los dos modelos: el no paralizable satura en `1/τ`, el paralizable tiene **máximo** en `nτ=1` y se desploma. Al lado, la **fracción viva** `1 − mτ` contra `e^{−nτ}` de la que salen las dos fórmulas | teórico |
| [`knoll_02_correccion.png`](knoll_02_correccion.png) | El problema **inverso**: de `m` sacar `n`. El no paralizable se invierte exacto; el paralizable tiene **dos ramas** y un techo en `1/(eτ)` arriba del cual no hay solución. Y por qué a `nτ < 0.15` da igual cuál se use | teórico |
| [`knoll_03_pileup.png`](knoll_03_pileup.png) | La **figura 17.34 de Knoll**: además de `m`, la tasa libre de apilamiento `r_pf = m·e^{−nτ}`, que tiene **máximo en los dos modelos** — subir la actividad más allá de ahí baja los eventos útiles por segundo | teórico |

Lo que este modelo **no** tiene —estímulo periódico, cola de `K` lugares,
distribución del largo del período muerto, dispersión de τ— es lo que agregan
las figuras de abajo.

---

# Figuras: tiempo muerto, el modelo

Figuras para la sección "El modelo, en unidades de τ" de
[`../../tiempo_muerto.md`](../../tiempo_muerto.md). Las genera
[`figuras_tiempo_muerto.py`](figuras_tiempo_muerto.py), con la misma convención
que el resto de [`figuras/`](../): sin texto adentro, paleta y rcParams de
[`figuras_resolucion.py`](../figuras_resolucion.py). Son **teóricas**: no
entra ningún `.npz`, y los ejes van en unidades de τ para que la misma curva
sirva al lector de Python (τ ≈ 250 µs) y al MCA (τ ≈ 2.9 µs).

```bash
cd prj/MCA/docs/mca/figuras/tiempo_muerto
python3 figuras_tiempo_muerto.py     # además imprime las tablas que cita el doc
```

| Figura | Qué muestra | Datos |
|---|---|---|
| [`01_tasas_adimensionales.png`](01_tasas_adimensionales.png) | `m·τ` contra `n·τ` para los tres modelos K=1 —periódico (dientes de sierra), Poisson no paralizable, paralizable— y la fracción perdida contra ρ en log. Donde los modelos se separan es a ρ chico | teórico |
| [`02a_tren_poisson.png`](02a_tren_poisson.png) | **Los arribos en el tiempo**, una fila por ρ: se agrupan, y el que cae en la ventana del anterior se pierde. Es el mecanismo, antes de cualquier curva | teórico |
| [`02b_integral_exponencial.png`](02b_integral_exponencial.png) | La densidad exponencial de `Δt` con el **área entre 0 y τ** sombreada, y lo que da esa área: `1 − e^{−ρ}` contra `ρ/(1+ρ)` y `ρ`. El paralizable es exactamente el área; el no paralizable coincide a primer orden | teórico |
| [`02c_tren_rho05.png`](02c_tren_rho05.png) | **El mismo tren con las dos reglas** a ρ = 0,5: el no paralizable recorta ventanas de largo τ siempre, el paralizable las encadena. Cada período muerto lleva su largo acotado arriba | teórico |
| [`02d_tren_rho15.png`](02d_tren_rho15.png) | Lo mismo a ρ = 1,5, donde aparecen períodos de 5,3 τ. Va en su propia imagen para que la comparación sea entre las dos **reglas** y no entre los dos ρ | teórico |
| [`02e_largo_ventana_muerta.png`](02e_largo_ventana_muerta.png) | **El largo del período muerto es una variable aleatoria**: delta en τ si no paraliza, y átomo en τ + cola si paraliza | teórico |
| [`02f_largo_vs_tasa.png`](02f_largo_vs_tasa.png) | Cómo crece ese largo con la tasa, con el eje en kcps del MCA, y **por qué los cuantiles arrancan planos y la media no** | teórico |
| [`03_cola_K.png`](03_cola_K.png) | Poisson con `K` lugares en el sistema (`K=1` = sin cola): la fracción perdida cae un orden en ρ por cada lugar de cola, y la fracción de tiempo ocupado **sube** con `K`. Cadena embebida de M/D/1/K, no simulación | teórico |
| [`04a_trenes_periodicos.png`](04a_trenes_periodicos.png) | **Los cuatro trenes periódicos en el tiempo**, con `T_prod/T_cons` = 2, 1.25, 0.8, 0.4 y cuáles arribos se pierden. Es la figura que se compara con [`02a`](02a_tren_poisson.png): mismos ejes, arribos sin agrupar | teórico |
| [`04b_periodico.png`](04b_periodico.png) | La escalera `m·τ = ρ/⌈ρ⌉` con τ fijo y con dispersión σ/τ = 3 % y 10 %, junto a Poisson, y la fracción perdida de las mismas curvas | teórico |

---

# Figuras: ¿paralizable o no? Lo decide el re-armado

Las tres de abajo las genera [`figuras_trigger.py`](figuras_trigger.py) y
responden una pregunta distinta: **de qué parte de la electrónica depende que
el sistema siga el modelo paralizable o el no paralizable.**

```bash
python3 figuras_trigger.py            # ~20 min; --rapido para iterar el dibujo
```

> ⚠ **Las figuras e imágenes de abajo están generadas con `N_DIV = 6` y hay que
> regenerarlas.** 6 es el *default* del parámetro `Q_W` de `mca_div_restore`, no
> el valor con el que `mca_top` instancia los divisores: `DIV_W = 16`. La
> latencia es `Q_W` ciclos fija
> ([`mca_div_restore.sv:19-21`](../../../../modulos/mca/rtl/mca_div_restore.sv#L19-L21)),
> así que `S_DIV` dura **16** ciclos. El script ya está corregido; los números
> publicados en este README (el «3,12 µs» de las figuras 5 y 7a, y las tablas de
> pérdida) todavía son los de 6 ciclos. El efecto es de 0.08 µs sobre un τ de
> 5.9 µs — **no cambia ninguna conclusión**, pero los valores se corren.

No son teóricas ni medidas: se sintetiza la señal a 125 MS/s sumando pulsos de
detector y se corre sobre ella la **misma máquina de estados del RTL**
([`mca_pulse_feature.sv`](../../../../modulos/mca/rtl/mca_pulse_feature.sv)) —
Schmitt con re-armado por debajo de `thr_lo`, desarme si la señal cruza
`thr_hi` con el módulo ocupado, y los dos modos de cierre. Los **puntos** salen
de ahí; las **líneas** son las fórmulas de Knoll. Parámetros, todos del RTL o
de la campaña: `cfg_thr = 100`, `cfg_hyst = 40` (`thr_lo = 60`),
`cfg_gate_long = 384` muestras = 3.07 µs, `cfg_maxlen = 4096`, `S_DIV` = 16
ciclos. La cola del pulso (τ = 1.14 µs sobre 8192 cuentas) está elegida para
reproducir las **~700 muestras sobre `thr_lo`** que el comentario de
[`:206`](../../../../modulos/mca/rtl/mca_pulse_feature.sv#L206) reporta medido en
placa; la simulación da 737.

## El resultado

**`cfg_gate_mode` no decide nada.** Los dos modos del MCA son **paralizables**
y con el mismo tiempo muerto efectivo. Lo que decide es el **re-armado**
([`:567-577`](../../../../modulos/mca/rtl/mca_pulse_feature.sv#L567-L577)):
`armed` es una condición de **nivel** —la señal tiene que bajar de `thr_lo`— y
no un contador. Mientras la cola del último pulso siga arriba el módulo no
puede abrir, y cualquier pulso que llegue en ese lapso levanta la señal y
**alarga** el bloqueo. Eso es la definición de paralizable.

De ahí sale la regla que las figuras ponen a prueba:

> **τ_efectivo = max(cierre de la ventana, cola sobre `thr_lo`)**, y el modelo
> es **paralizable**, `m = n·e^{−nτ}`.

| configuración | cierra a | τ_efectivo | ¿`deadtime_cnt` honesto? |
|---|---|---|---|
| modo 0, histéresis | la cola, 5.9 µs | **5.9 µs** | **sí**: la ventana dura todo el bloqueo |
| modo 1, `gate_long = 384` (campaña) | 3.07 µs | **5.9 µs** | **no**: cuenta 3.1 de 5.9 µs |
| modo 1, `gate_long = 1024` | 8.19 µs | **8.2 µs** | casi, pero τ creció y se pierde más |
| re-armado por contador (no está en el RTL) | 3.07 µs | 3.1 µs, **no paralizable** | — pero **cuenta de más** |

Pérdida simulada contra el modelo que le toca, estímulo Poisson:

| tasa | modo 1 / 384 | modo 0 | modo 1 / 1024 | `n·e^{−nτ}`, τ=5.9 µs |
|---|---|---|---|---|
| 20 kcps | 11.2 % | 11.3 % | 17.5 % | **11.2 %** |
| 50 kcps | 26.0 % | 26.1 % | 37.5 % | **25.7 %** |
| 100 kcps | 45.9 % | 46.1 % | 57.4 % | **44.8 %** |
| 200 kcps | 70.1 % | 71.1 % | 77.2 % | **69.5 %** |
| 400 kcps | 91.5 % | 94.0 % | 92.8 % | **90.7 %** |

Los dos modos del RTL siguen `n·e^{−nτ}` con el mismo τ dentro de ~1 pp en toda
la década. El **no paralizable con el mismo τ** daría 10.6 / 22.9 / 37.3 /
54.3 / 70.4 %: a 200 kcps son **16 puntos** de diferencia, así que un barrido
Poisson distingue los dos modelos sin ambigüedad.

Y el contador del FPGA, modo 1 con `gate_long = 384`:

| tasa | `deadtime_cnt`/`realtime` | bloqueo real |
|---|---|---|
| 20 kcps | 5.5 % | **11.0 %** |
| 50 kcps | 11.5 % | **25.6 %** |
| 126 kcps | 18.1 % | **52.2 %** |
| 318 kcps | 14.0 % | **85.7 %** |
| 800 kcps | 1.0 % | **99.6 %** |

El contado **no es monótono**: pasa por un máximo cerca de 126 kcps y después
baja, porque a tasa alta casi no se abren ventanas. Un `deadtime_cnt` que
**baja** al subir la tasa es la firma de este efecto, no de un sistema que se
descongestiona.

| Figura | Qué muestra | Datos |
|---|---|---|
| [`05_politicas_trigger.png`](05_politicas_trigger.png) | El mismo tren visto por los dos modos de cierre. El modo 0 es el único **sin rayado**: su ventana termina donde termina el bloqueo. En el modo 1 el rayado es tiempo muerto real que **ningún contador registra**, y los pulsos que caen ahí (marca gris) se pierden sin dejar rastro — y encima alargan el bloqueo | FSM del RTL |
| [`06_paralizable_vs_no.png`](06_paralizable_vs_no.png) | Las tres configuraciones del RTL caen sobre su curva **paralizable**; la referencia no paralizable con el mismo τ queda muy por encima. El barrido **periódico** es el ensayo que las separa sin ambigüedad | FSM del RTL |
| [`07a_cronograma.png`](07a_cronograma.png) | **Cronograma de los dos relojes** sobre un caso concreto: lo que cuenta `feat_busy` contra lo que el sistema estuvo realmente bloqueado | FSM del RTL |
| [`07b_deadtime_oculto.png`](07b_deadtime_oculto.png) | Cuánto difieren esos dos relojes contra la tasa, para `gate_long` = 384 y 1024 | FSM del RTL |

---

# Figura: por qué corregir la medición no alcanza

La genera [`figuras_tiempo_muerto.py`](figuras_tiempo_muerto.py) junto con las
demás teóricas. Responde a la objeción natural —"si conozco τ, invierto el
modelo y listo"— mostrando los dos motivos por los que la inversión falla.

| Figura | Qué muestra | Datos |
|---|---|---|
| [`08_amplificacion_correccion.png`](08_amplificacion_correccion.png) | Cuánto amplifica la corrección un error en la tasa medida **(a)** y un error en τ **(b)** | teórico |

## El término de amplificación de error

Conviene trabajar en las cantidades adimensionales `mτ` y `nτ`, donde la
calibración es una única función sin parámetros libres. Toda la propagación
queda gobernada por **un** número, el **término de amplificación de error**

```
E = dln(nτ)/dln(mτ)
```

que a τ fijo es `dln(n)/dln(m)`, o sea la pendiente de la curva de calibración
en escala log-log. Los dos coeficientes salen de ahí, corridos en una unidad:

```
δn/n = E·δm/m + (E−1)·δτ/τ
```

| | no paralizable | paralizable |
|---|---|---|
| calibración | `nτ = mτ/(1−mτ)` | `nτ = −W(−mτ)` |
| `E` (pesa `δm/m`) | `1/(1−mτ) = 1+ρ` | `1/(1−ρ)` |
| `E−1` (pesa `δτ/τ`) | `ρ` | `ρ/(1−ρ)` |

La diferencia entre columnas es el argumento entero: en el no paralizable `E`
crece **linealmente** con ρ, y en el paralizable **diverge en ρ = 1**, porque
ahí `dm/dn = 0` y la calibración se vuelve horizontal. A ρ = 0.9 un error del
1 % en τ ya son 9 % en la tasa corregida — y ése es **sistemático**, así que no
se achica midiendo más tiempo.

**Cuidado con el signo** en la columna paralizable: para ρ > 1 el término es
**negativo**, porque se está en la rama descendente y subir `mτ` *baja* `nτ`.
La figura grafica `|E|`, así que el cruce por debajo de 1 cerca de ρ = 2 no es
que la corrección mejore: es el signo dado vuelta.

## A dónde va con ρ grande

| | no paralizable | paralizable (ρ > 1) |
|---|---|---|
| `E` | `≈ ρ`, lineal | `1/(ρ−1)`, decrece **y cambia de signo** |
| estadística para 1 % | `T ≈ 10⁴·ρ²·τ`, cuadrático | `T ≈ 10⁴·τ·e^ρ/[(ρ−1)²ρ]`, mínimo en `ρ = 2+√3 ≈ 3.73` y después exponencial |
| piso sistemático | `ρ·δτ/τ`, **irreducible** | ídem, más la ambigüedad de rama |

En el no paralizable siempre se compra precisión midiendo más tiempo; lo que no
se compra es el término en τ, y ése fija la tasa máxima utilizable (con τ al
1 %, mantener la corrección dentro del 10 % pide ρ ≲ 10). En el paralizable la
caída de `|E|` pasado ρ = 1 es un espejismo: la tasa medida se desploma como
`ρ·e^{−ρ}` y aun con estadística suficiente la medición no dice en qué rama se
está. Los números los imprime `tabla()`.

## Y la inversión no es única

Dos lecturas que fallan por motivos distintos, con τ = 5.94 µs (el del MCA en
modo 1). Los intervalos los imprime `tabla()`:

| lectura | tasas incidentes compatibles | banda con ±2 % en `m` |
|---|---|---|
| `m` = 50.5 kcps (`mτ` = 0.30) | **82 kcps o 300 kcps** | ±3.9 % y ±2.6 % |
| `m` = 60.9 kcps (`mτ` = 0.362) | 140 kcps o 200 kcps | **±15 % y ±13 %, y se tocan** |

La primera es ambigüedad pura: las bandas son angostas pero hay **dos**
soluciones separadas por un factor 3.7, y la medición no dice cuál. La segunda
está cerca del máximo (`1/e` = 0.368): ahí `E` infla las bandas hasta que se
**superponen**, y el resultado es "entre 127 y 218 kcps", sin poder siquiera
decir de qué lado del pico se está. El no paralizable, en cambio, es monótono y
se invierte sin ambigüedad.

Esto salía como un tercer panel de la figura 08 y se sacó: el mensaje es
numérico y la tabla lo dice mejor que el gráfico.

## Epígrafes

**Figura 1.** Tasa registrada contra tasa incidente, ambas multiplicadas por el
tiempo muerto τ, para un servidor sin cola (K=1). (a) Escala lineal. Punteado:
sin pérdidas, m = n. Azul: arribos periódicos, m·τ = ρ/⌈ρ⌉, sin pérdida hasta
ρ = 1 y en dientes de sierra después; en cada entero se registra uno de cada k
arribos. Naranja: arribos Poisson con tiempo muerto no paralizable,
m·τ = ρ/(1+ρ), que tiende a 1 sin alcanzarlo. Verde: paralizable, ρ·e^{−ρ},
con máximo 1/e en ρ = 1. La curva de Poisson pasa por el fondo de cada diente
del periódico: en ρ = k ambas valen k/(k+1). (b) La fracción perdida 1 − m/n
de las mismas curvas, con ρ logarítmico: el periódico da cero hasta ρ = 1; los
otros dos dan ≈ ρ desde el origen.

**Figura 2a.** Arribos Poisson en el tiempo, en unidades de τ, una fila por
ρ = 0,2, 0,5 y 1. Cada arribo registrado (azul) abre una ventana muerta de
largo τ (gris); los arribos que caen adentro (rojo) se pierden y no la
extienden. Los arribos se **agrupan** —la exponencial tiene su máximo en
Δt = 0— así que hay pérdida a toda tasa, incluso en la fila de ρ = 0,2 donde
el sistema está libre el 80 % del tiempo. Las pérdidas esperadas son
ρ/(1+ρ) = 17, 33 y 50 %; la realización que se dibuja tiene pocos arribos y se
aparta de esos valores, que es justamente por qué los números salen de la
curva y no de contar rayitas.

**Figura 2b.** De dónde sale esa pérdida. (a) Densidad del intervalo entre
arribos,
τ·n·e^{−n·Δt}, para ρ = 0,2, 0,5 y 1, con el área entre 0 y τ sombreada. Esa
área, 1 − e^{−ρ}, es la probabilidad de que el próximo arribo caiga dentro de
la ventana; es no nula para todo ρ porque la exponencial tiene su máximo en
Δt = 0. (b) Fracción perdida contra ρ: el área (verde, punto-raya) es exacta
para el modelo paralizable; para el no paralizable la pérdida es ρ/(1+ρ)
(naranja), porque los perdidos no reabren la ventana y lo que cuenta es su
número esperado, ∫₀^τ n·dt = ρ. Las dos coinciden con ρ (punteado) a primer
orden.

**Figuras 2c y 2d.** El **mismo** tren de arribos —misma semilla— procesado por
las dos reglas, a ρ = 0,5 y a ρ = 1,5. Arriba, el no paralizable: cada
registrado abre una ventana de largo τ y lo que cae adentro se pierde sin
tocarla, así que **todas** las bandas grises miden lo mismo, y la cota de la
primera dice cuánto. Abajo, el paralizable: cada arribo que cae adentro
**reabre** la ventana, así que las bandas se encadenan y su largo es τ más la
suma de los huecos del racimo. Las cotas rojas miden cada período muerto que se
extendió, en unidades de τ; las que no llevan cota miden τ exacto. A ρ = 1,5
aparecen períodos de 5,3 τ —el sistema queda bloqueado cinco veces más de lo que
dura una ventana— con el mismo tren de arribos que arriba. Son dos imágenes y no
una, para que la comparación que hace el ojo sea entre las dos **reglas** y no
entre los dos ρ.

**Figura 2e.** La distribución del largo del período muerto. (a) Densidad, en
unidades de τ. El no paralizable es una **delta en L = τ**: el largo no es
aleatorio, es un parámetro del equipo. El paralizable conserva una masa de
probabilidad en τ —el disco, de valor e^{−ρ}, los períodos que no se extienden
ni una vez— y le crece una cola continua, con un quiebre en cada múltiplo de τ
porque cada tramo nuevo lo aporta una extensión más. Ojo con el eje: la línea
es una densidad y los discos son masa de probabilidad; conviven porque la
distribución es **mixta**. (b) La cola, P(L > x). Cada ρ decae como una
exponencial cuya pendiente baja con la tasa: a ρ = 2 un período muerto de 8 τ
tiene probabilidad 10⁻³, y a ρ = 0,2 ya es inalcanzable.

**Figura 2f.** Cómo crece con la tasa. (a) La media es exacta,
E[L]/τ = (e^ρ − 1)/ρ, y la banda va de la mediana al p90. El punto rojo es el
MCA en modo 0 a 100 kcps con su τ = 5,9 µs: período muerto medio
**1,36 τ = 8,0 µs**, p90 de 2,1 τ. El eje de arriba convierte ρ a kcps para ese
τ. Lo que hay que leer es la **asimetría**: la mediana vale exactamente τ hasta
ρ = 0,69 mientras la media ya se fue un 36 % arriba. (b) Por qué esos tramos
planos, que es la pregunta que deja (a). La distribución tiene un átomo en
L = τ de masa e^{−ρ}, y **mientras esa masa supere al cuantil pedido, el cuantil
cae adentro del átomo y vale exactamente τ**. El p90 despega cuando
e^{−ρ} = 0,9, o sea ρ = ln(10/9) = 0,11; la mediana cuando e^{−ρ} = 0,5, o sea
ρ = ln 2 = 0,69. La media **no** tiene tramo plano: vale (e^ρ − 1)/ρ ≈ 1 + ρ/2
desde el origen, y lo que parece constante cerca de cero es nada más una
pendiente de 1/2 en un eje que llega a 4.

**Figura 3.** Arribos Poisson, servicio fijo τ y K lugares en el sistema
contando al que se atiende; K = 1 es sin cola. Resuelto con la cadena de Markov
embebida en las partidas de M/D/1/K. (a) Fracción perdida contra ρ para
K = 1, 2, 3, 5, 10 y K = ∞ (discontinua). Con K = 1 basta un arribo dentro de
una ventana para perderlo y la pérdida es ≈ ρ; con K lugares hace falta una
ráfaga de K en un mismo servicio, ≈ ρ^K/K!. Con K = ∞ la pérdida es
exactamente cero hasta ρ = 1. Por encima de ρ = 1 todas convergen a 1 − 1/ρ.
(b) Fracción de tiempo ocupado m·τ para los mismos K: sube con K, porque el
servidor atiende más. La cola no reduce el tiempo ocupado; hace que estar
ocupado deje de implicar perder. Con K = 1 los dos paneles coinciden en
ρ/(1+ρ).

**Figura 4a.** Productor periódico de período T_prod y consumidor que tarda
T_cons = τ por evento, sin cola: cuatro trenes en unidades de τ, con
T_prod/T_cons = 2, 1,25, 0,8 y 0,4 (ρ = 0,5, 0,8, 1,25 y 2,5). Azul: arribos
registrados; gris: ventana muerta; rojo: arribos perdidos. Con T_prod ≥ T_cons
no se pierde ninguno; con 0,8 se pierde uno de cada dos y con 0,4 dos de cada
tres. La anotación de cada fila da la regla exacta —se registra 1 de cada
k = ⌈ρ⌉— y no el conteo de la ventana dibujada, que queda cortada al final.
Mismos ejes que la figura 2a: la diferencia entre las dos imágenes, arribos en
grilla contra arribos agrupados, es todo el asunto del documento.

**Figura 4b.** Las curvas del mismo modelo. (a) m·τ contra n·τ = T_cons/T_prod.
Azul grueso: τ fijo,
m·τ = ρ/⌈ρ⌉; los puntos negros son los cuatro trenes de (a). Azules finos: τ
con dispersión gaussiana σ/τ = 3 % y 10 %, m = n/E[⌈τ/T⌉]; el diente se
redondea sólo cerca de cada entero, con ancho ± (σ/τ)·ρ, así que los dientes
altos se borran antes que los bajos. Naranja: Poisson, para comparar. (b) La
fracción perdida de las mismas curvas.

**Figura 5.** El mismo tren de pulsos procesado por la máquina de estados del
RTL en los dos modos de cierre que implementa. Señal sintetizada a 125 MS/s;
eje vertical logarítmico a partir de `thr_lo`. Gris: la ventana que el módulo
declara ocupada, que es lo que suma `feat_busy` y por lo tanto
`deadtime_cnt`. Rayado rojo:
tiempo en que el módulo está libre pero **no puede abrir**, porque el Schmitt
no se re-arma hasta que la señal baja de `thr_lo`; ese tiempo no entra en
ningún contador. Triángulo azul: el pulso abrió una ventana y fue aceptado.
Marca roja: el pulso llegó con la ventana abierta y quedó contado en
`cnt_lost_busy`. Marca gris: el pulso llegó en la zona rayada — se perdió sin
quedar en ningún contador, y además corrió el bloqueo más adelante.
(a) modo 1 con `cfg_gate_long = 384`, la configuración de la campaña: la
ventana dura 3,12 µs pero el bloqueo se estira hasta 14,4 µs porque dos pulsos caen en
la zona rayada y la extienden. (b) modo 0, histéresis: la ventana cierra
exactamente cuando la señal baja de `thr_lo`, así que coincide con el bloqueo
y no hay rayado — el contador es honesto, y el tiempo muerto es el mismo que
en (a).

**Figura 6.** Tasa registrada y fracción perdida contra tasa incidente, con la
FSM del RTL corrida sobre señal sintetizada (marcadores) y las fórmulas de
Knoll (líneas). (a) y (b): arribos Poisson. Círculos naranjas (modo 1,
`gate_long = 384`) y cuadrados rojos (modo 0) caen uno sobre el otro y sobre
la misma curva **paralizable** `n·e^{−nτ}` con τ = 5,9 µs, que es el tiempo que
el pulso aislado pasa sobre `thr_lo`; los triángulos verdes (modo 1,
`gate_long = 1024`) siguen la paralizable con τ = 8,2 µs, el largo de su
compuerta. La línea punto-raya negra es la **no paralizable con el mismo
τ = 5,9 µs**: queda muy por encima, y la separación —16 puntos porcentuales a
200 kcps— es lo que hace al ensayo concluyente. Los rombos azules son una
variante que **no está en el RTL**, re-armar por contador en vez de por
umbral: no pierde eventos sino que **cuenta de más**, porque trocea el
apilamiento en pedazos del largo de la compuerta y registra cada uno como un
evento (de ahí los valores negativos de 1 − m/n y los puntos por encima de la
diagonal ideal). Es el modo de falla que el comentario de `:569-573` del RTL
da como motivo para no hacerlo. (c) El mismo barrido con estímulo
**periódico**, que separa los modelos sin depender de ninguna curva: las tres
configuraciones paralizables se desploman a cero cuando el período baja del
τ_efectivo —la señal nunca vuelve a cruzar `thr_lo` y el Schmitt no se re-arma
nunca más— mientras que la de re-armado por contador sigue registrando. La
línea vertical marca el período igual a la cola sobre `thr_lo`.

**Figura 7a.** El tiempo muerto que el contador del FPGA no ve, modo 1 con
`cfg_gate_long = 384`. (a) Tres pulsos: el primero y el tercero abren ventana
(triángulo azul), el segundo llega en la zona bloqueada y se pierde sin
contador (marca gris). (b) Los dos relojes: `feat_busy` cuenta 3,12 µs por
evento (la compuerta más los 16 ciclos de `S_DIV`), mientras el sistema estuvo
realmente incapaz de abrir durante 9,4 µs.

**Figura 7b.** La misma comparación contra la tasa, para `gate_long` = 384 (naranja) y
1024 (verde); trazo lleno el bloqueo real, trazo cortado lo que informaría
`deadtime_cnt`, y el área sombreada entre ambos lo que se pierde de contar. Lo
contado **no es monótono**: pasa por un máximo —18 % cerca de 126 kcps con la
compuerta de 384— y después baja hasta el 1 % a 800 kcps, cuando el bloqueo
real es del 99,6 %. Un tiempo muerto informado que baja al subir la tasa es la
firma de este efecto.

**Figura 8.** El término de amplificación de error de la corrección por tiempo
muerto, `E = dln(nτ)/dln(mτ)`, contra `ρ = nτ`. Es la pendiente de la curva de
calibración en escala log-log, y los dos paneles son el mismo número corrido en
una unidad. (a) `E`, el factor que pesa un error relativo en la tasa medida:
`1+ρ` para el modelo no paralizable (naranja) y `1/|1−ρ|` para el paralizable
(verde, punto-raya). La línea punteada horizontal marca la amplificación
unitaria y la vertical, `ρ = 1`. La curva paralizable está cortada en el techo
del eje: diverge en `ρ = 1`, donde `dm/dn = 0` y la calibración se vuelve
horizontal. (b) `E−1`, el factor que pesa un error en el tiempo muerto: `ρ`
contra `ρ/|1−ρ|`. Este término es **sistemático**, así que no se reduce
prolongando la medición. Se grafica el **valor absoluto**: para `ρ > 1` el
término paralizable es negativo, porque ahí se está en la rama descendente
—más actividad da menos cuentas— y subir `mτ` baja `nτ`. Por eso que la curva
verde caiga por debajo de 1 cerca de `ρ = 2` no es un alivio sino el signo dado
vuelta. Pasado `ρ = 1` el problema deja de ser la precisión: la tasa medida se
desploma como `ρ·e^{−ρ}` y la inversión admite **dos** soluciones, de modo que
una estimación formalmente precisa no dice en qué rama está el sistema.
