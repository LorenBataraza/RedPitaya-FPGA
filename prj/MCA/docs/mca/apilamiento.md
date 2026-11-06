# Apilamiento: cuánto deforma el espectro y cuánto lo corrige un corte por forma

Monte-Carlo del apilamiento sobre el MCA. Responde dos preguntas que en la placa
no se pueden contestar, porque no existe el espectro "sin apilamiento" contra el
cual comparar:

1. **¿Cuánto deforma el apilamiento el histograma medido**, contra el que
   deberíamos medir?
2. **¿Cuánto de esa distorsión saca un corte por factor de forma** (cociente
   carga/pico), y **¿hace falta hardware nuevo o alcanza con el eje de forma que
   el RTL ya calcula?**

El documento tiene dos partes. **La primera es la vigente**: el barrido sobre el
MCA2 (las ranuras, el disparo del multitrigger, el trapecio y su banco). **La
segunda es histórica**: el mismo estudio sobre el MCA1, con las dos reglas de
ventana que ese mapa tenía; se conserva porque de ahí salió el diseño, y se
reproduce con `--mapa MCA1`.

**Corre en la PC, sin placa y sin datos medidos.** Son predicciones, no mediciones:
nada de esto se probó todavía en la placa.

```bash
python3 montecarlo.py                # el barrido sobre el MCA2 (~20 min)
python3 graficar.py                  # las figuras, sin re-simular
python3 pico_vs_carga.py             # pico contra carga, con 1 y 4 ranuras (CR-RC^4)
python3 -m pytest test_replica_mca2.py   # la réplica contra el RTL
python3 montecarlo.py --mapa MCA1    # el barrido viejo
```

## El barrido sobre el MCA2

**En corto:**

- **Más ranuras dan más eventos, no más eventos buenos.** Con la integral, a
  100 kcps, pasar de 1 a 4 ranuras lleva la pérdida de 19 % a 0, y los eventos
  buenos se quedan en 34.6 kcps. Lo que se recupera son eventos contaminados.
- **`F_SOLAPE` ve lo que `cnt_pileup` no veía:** marca el 37.6 % de los eventos,
  cuando el 42 % tiene más de un pulso. Pero cortar por él cuesta la mitad del
  fotopico.
- **Lo que corrige es el trapecio:** en la misma semi-gaussiana, 63.5 kcps buenos
  a 100 kcps, contra 34.6 de la integral.
- **El banco con el disparo con polo-cero cambia de escala.** Con el pulso del
  preamplificador, a 1 Mcps da **747 kcps buenos**; un trapecio solo con la
  pendiente, 224. A 100 kcps el continuo es 0.5 % contra 9.8 %.

### Qué se compara

Dos pulsos, porque el banco no tiene sentido con el primero:

- **La semi-gaussiana de la campaña**: FWHM de 2 µs, sube en ~100 muestras, cola
  τ = 186. Es la de las mediciones que hay.
- **El pulso del preamplificador**: sube en ~1 muestra, cola τ = 250. Es para el que
  está pensado el banco ([`pruebas_banco_trapecios.md`](pruebas_banco_trapecios.md)):
  con la semi-gaussiana no hay meseta para k = 8.

| configuración | pulso | ranuras | disparo | estimador | compuerta |
|---|---|---|---|---|---|
| `r1`, `r2`, `r4` | semi-gaussiana | 1, 2, 4 | pendiente | integral | 384 |
| `r4t` | semi-gaussiana | 4 | pendiente | trapecio k = 64, m = 256 | 384 |
| `p4t` | preamplificador | 4 | pendiente | trapecio k = 64, m = 48 | 128 |
| `banco` | preamplificador | 4 | polo-cero | banco 64/48, 32/24, 16/12, 8/8 | 112 |

El disparo y el trapecio se ajustan a cada pulso con las mismas cuentas que en la
placa; el banco sale de `mca_banco_config`. Ruido blanco de σ = 2.8 cuentas, base
fija, 50 000 eventos por punto, nueve tasas de 1 kcps a 1 Mcps y los dos espectros
fuente. Los números de abajo son del espectro de una línea (1920 cuentas). El
realista cuenta lo mismo: a 1 Mcps, `banco` da 761 kcps y `p4t`, 219.

### Eventos buenos por segundo

**Bueno** es lo que sólo el Monte Carlo puede saber: el evento mide la amplitud
verdadera del pulso que lo disparó con error menor que 1 %, con un piso de 4 cuentas
para que el ruido de la forma corta no cuente como contaminación. Los marcados no
cuentan como buenos. Es la cifra que importa, porque tiene en cuenta a la vez lo que
se pierde y lo que se publica mal.

| kcps incidentes | `r1` | `r2` | `r4` | `r4t` | `p4t` | `banco` |
|---|---|---|---|---|---|---|
| 20 | 16.3 | 16.3 | 16.2 | 18.3 | 19.5 | **20.0** |
| 100 | 34.6 | 34.1 | 34.6 | 63.5 | 86.6 | **97.5** |
| 200 | 22.8 | 23.3 | 23.2 | 80.6 | 149 | **191** |
| 500 | 2.1 | 2.0 | 1.9 | 49.5 | 241 | **449** |
| 1000 | 0.0 | 0.1 | 0.1 | 9.9 | 224 | **747** |

![Pérdida por ranuras y eventos buenos](figuras/apilamiento/perdida_y_buenos.png)

### A 100 kcps, espectro de una línea

| | `r1` | `r4` | `r4t` | `p4t` | `banco` |
|---|---|---|---|---|---|
| disparos perdidos | 19.1 % | 0 | 0 | 0 | 0 |
| eventos publicados | 37 664 | 46 686 | 46 681 | 49 210 | 49 742 |
| con un solo pulso cerca (la verdad) | 71.3 % | 58.0 % | 58.3 % | 83.1 % | 85.1 % |
| que el RTL marca (`F_SOLAPE ≠ 0`) | 20.8 % | 37.6 % | 37.3 % | 15.6 % | 14.5 % |
| marcados por el banco | — | — | — | — | 1.2 % |
| fotopico sobre la referencia | 0.477 | 0.480 | 0.695 | 0.878 | 0.978 |
| continuo sobre el tope | 26.1 % | 39.5 % | 21.9 % | 9.8 % | 0.5 % |
| L1 al espectro de referencia | 0.905 | 1.108 | 0.569 | 0.228 | 0.012 |
| continuo cortando por `F_SOLAPE` | 12.3 % | 9.2 % | 7.1 % | 1.6 % | 0.5 % |
| fotopico cortando por `F_SOLAPE` | 0.457 | 0.460 | 0.544 | 0.818 | 0.836 |

Lo que hay que leer:

**1. Las ranuras no corrigen, marcan.** De `r1` a `r4` la pérdida desaparece, se
publican un 24 % más de eventos, y el espectro **empeora** (el continuo pasa de 26 %
a 39.5 %). Es lo esperable: una ventana abierta sigue sumando la carga de lo que
llegue, tenga o no otra ranura midiendo ese pulso. Los eventos buenos no cambian.

**2. `F_SOLAPE` reemplaza al rechazo que no andaba.** En el MCA1, `cnt_pileup`
marcaba menos del 0.45 % cuando el 40–47 % de los eventos tenía más de un pulso.
Ahora marca el 37.6 % de un 42 %. Cortar por él baja el continuo de 39.5 % a 9.2 %,
pero se lleva lo mismo que ya estaba perdido: el fotopico queda en 0.46. No puede
ser mejor: lo que marca es que hubo otro disparo, y ese evento ya está contaminado.

Lo que le queda abajo tiene dos orígenes: los pares a menos de ~90 muestras, que con
esta forma la pendiente funde en un solo disparo (medido con dos pulsos de 1920: a 80
muestras nunca da dos disparos, a 100 siempre), y la cola del pulso anterior, que no
abre nada.

**3. El eje de forma sigue sin alcanzar, y Q/pico ahora ve otra cosa.** `Q_cola/Q_tot`
no rechaza nada con la integral (0 %). `Q/pico` con k = 3 baja el continuo de `r4` a
10.5 % y el L1 a 0.280, rechazando el 85 % de los apilados, pero se lleva el 30 % de
los "limpios". No son rechazos en falso: esos eventos tienen la cola del pulso
anterior adentro. Medido con `r4` a 100 kcps, con el pulso anterior a 384–600 muestras
el corte conserva el 0 %, a 900–1300 el 93 %, y de ahí en adelante el 100 %. El cociente
está definido al 0.08 %, y la cola lo mueve más que eso aunque no haya otro pulso en
la ventana. Es una definición de "limpio" más estricta que la del estudio del MCA1, y
por eso esta tabla no es comparable con su columna de eficiencia.

**4. El trapecio corrige lo que la ranura marca.** Con la misma semi-gaussiana y las
mismas ranuras, `r4t` conserva 0.695 del fotopico contra 0.480, y casi duplica los
eventos buenos. Sigue limitado por la forma: subir en ~100 muestras exige k + m = 320,
y dos pulsos dentro de eso se funden.

**5. Con un pulso rápido, el banco resuelve casi todo.** `banco` deja el fotopico en
0.978 a 100 kcps y 0.764 a 1 Mcps, con un continuo de 5.3 %. Contra `p4t`, sobre el
mismo pulso, la mejora es de las dos piezas juntas: el banco elige la forma que el
vecino deja medir, y el polo-cero separa pares desde ~8 muestras y no se ciega en la
cola. Lo que queda en el espectro es el pico suma: pares más cercanos que el disparo.
A 1 Mcps queda marcado el 9.7 %, y del resto el 89.7 % mide bien.

El otro estudio del banco, con otro modelo y otra señal, da 744 kcps a 1 Mcps con la
saturación del ADC
([`pruebas_banco_trapecios.md`](pruebas_banco_trapecios.md)). Allá las amplitudes son
uniformes y el criterio es sobre la señal sin ruido, así que la coincidencia es de
orden de magnitud, no una validación.

**6. La pérdida por ranuras es la del modelo mientras la tasa es baja.** Con una
ranura, Erlang B con la tasa de disparos da 0.3 % a 1 kcps (medido 0.3 %) y 1.6 % a
5 kcps (medido 1.3 %). A 100 kcps sobreestima (23.2 % contra 19.1 %): el disparo funde
los pulsos cercanos, y los que quedan no llegan como un proceso de Poisson. Para
predecir la pérdida exacta hace falta simular sobre los disparos:
`analisis.perdida_ranuras` coincide con la réplica dentro de 1 punto.

### Por qué creerle a la réplica

[`replica_mca2.py`](../../software/monte-carlo/replica_mca2.py) corre sobre el mismo
estímulo que el RTL entero (`mt_top` + `mca_top`, como en el top), con
[`sim/tb_mca2_volcado.sv`](../../sim/tb_mca2_volcado.sv).
[`test_replica_mca2.py`](../../software/monte-carlo/test_replica_mca2.py) exige que dé,
**bit a bit**, en 10 configuraciones y 2170 eventos:

- los mismos flancos de `trig_i`, por pendiente y con polo-cero;
- los mismos eventos, con las once features, incluidas `F_TRAP` y `F_FORMA`;
- los mismos contadores y la misma ocupación por ranuras.

Doce mutaciones a propósito en la réplica (la latencia del disparo, la comparación de
los umbrales, qué forma gana, el recorte de `n_formas`, la ventana de una forma, su
escala…) hacen fallar el test. Hay que volver a correr el volcado si cambia el RTL:
`make -C prj/MCA/sim tb_mca2_volcado`.

### Lo que no se modela

- **El seguidor de línea de base**: la base es fija, como en el estudio del MCA1. El
  corrimiento de la base a tasa alta no está.
- **El ruido real**: blanco, de σ = 2.8. El correlacionado de
  [`../ruido_del_sistema.md`](../ruido_del_sistema.md) no está.
- **Que M esté bien ajustado**: el Monte Carlo usa el M exacto. Con 0.5 % de error el
  banco deja de recuperar pulsos chicos sobre la cola de uno grande
  ([`pruebas_banco_trapecios.md`](pruebas_banco_trapecios.md)).
- **Cada grupo arranca con las ranuras libres**: el barrido renderiza por grupos
  separados por un hueco, como el del MCA1. Afecta a ~1 evento por corte.

## El barrido sobre el MCA1 (histórico)

> Es del mapa anterior, con ventana por histéresis o por compuertas, y con `cnt_pileup`.
> `python3 montecarlo.py --mapa MCA1` lo reproduce. El estímulo es la semi-gaussiana de
> la campaña. Las dos reglas de ventana están en
> [`ventana_de_medicion.md`](ventana_de_medicion.md). Lo que sigue sobre todo sirve para
> entender por qué el MCA2 es como es.

### Resultado

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

#### 1. El rechazo de apilamiento que el RTL ya tiene no hace nada

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

#### 2. El eje de forma que ya está en el hardware NO alcanza

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

#### 3. Para trabajar a tasa alta conviene la ventana por histéresis, no las compuertas fijas

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

### El corte hay que calibrarlo contra la amplitud

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

### El límite irreducible

Ningún corte por forma puede sacar las **coincidencias exactas**: la suma de dos
pulsos idénticos que llegan juntos **es** un pulso de la misma forma y el doble
de amplitud, y el lugar geométrico —que depende de la amplitud— predice
correctamente su Q/pico. El corte no tiene de qué agarrarse.

Medido contra el lugar geométrico calibrado, con dos pulsos de la línea
(`familias_evento.png`):

| Δt | amplitud medida | Q/pico | esperado | desvío | veredicto |
|---|---|---|---|---|---|
| 0–4 muestras (0–32 ns) | 469 mV (200 %) | 294.6 | 294.7 | **−0.9 σ** | **indistinguible** |
| 8 muestras (64 ns) | 469 mV | 295.0 | 294.7 | +1.6 σ | indistinguible |
| 20 muestras (160 ns) | 466 mV | 296.2 | 294.7 | +8.8 σ | rechaza |
| 150 muestras (1.2 µs) | 381 mV | 363.3 | 293.9 | +324 σ | rechaza |
| 600 muestras (4.8 µs) | 247 mV | 559.5 | 291.6 | +626 σ | rechaza |

La ventana ciega es **Δt ≲ 10 muestras, o sea ~80 ns** — mucho más angosta de lo
que sugiere el ancho del pulso (2 µs), porque basta que el segundo pulso llegue
un poco tarde para que deforme el flanco de subida y estire la ventana. Esos
eventos entran al pico suma y ahí se quedan: son el residuo en 3840 que se ve en
`corte.png` después del corte, y el 0.9 % de apilados que sobrevive.

La única forma de atacarlos es acortar el pulso, que es un problema de
conformado y no de discriminación.

### Qué valida el simulador, y qué no

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
- El barrido de tasa de arriba corre con **base fija** (`cfg_bl_auto = 0`). El
  seguidor IIR **sí está modelado** —fiel al RTL, con los dos ciclos de retardo
  de registro y el congelamiento— pero vive en `linea_base.py`, que es el
  estudio dedicado; ver la sección del seguidor más abajo.
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
| `replica_mca2.py` | la réplica del MCA2: los dos disparos, las ranuras, el publicador y el banco |
| `test_replica_mca2.py` | la réplica contra el RTL, evento por evento. Necesita el volcado de `datos_ref/` |
| `volcado_mca2.py` | el estímulo del volcado, y cómo leer lo que devuelve el RTL |
| `pileup.py` | funciones puras: forma, espectros fuente, arribos, render por grupos, calibración del corte, métricas, y la réplica vectorizada del MCA1 en sus dos modos |
| `test_pileup.py` | 10 bloques de validación de la réplica del MCA1. Sin placa, sin datos |
| `montecarlo.py` | el barrido (MCA2, o `--mapa MCA1`); guarda `.npz` + `resumen.json` en `software/datos/pileup_<fecha>/` |
| `graficar.py` | las figuras del barrido, desde los `.npz` |
| `pico_vs_carga.py` | Monte-Carlo pico-vs-carga de dobles y triples con las formas de Knoll, con 1 y 4 ranuras |
| `linea_base.py` | el seguidor IIR: qué compra contra el pedestal de tasa y la deriva |
| `graficar_base.py` | las cuatro figuras del seguidor |

## Las figuras

Salen de `graficar.py` y viven en el directorio de la corrida
(`software/datos/pileup_<fecha>/`). Lo que sigue describe las de la corrida del MCA1,
con la que se escribió esta sección. Las del MCA2 son las mismas, salvo
`perdida_y_buenos.png`, que es nueva y sólo existe ahí, y `familias_evento.png`, que
sigue siendo del MCA1 (con la compuerta fija todas las ventanas miden lo mismo).

### `familias_evento.png` — qué es un evento apilado

Seis trazas en **volts contra microsegundos**: lo que el MCA registra como **un
solo evento**. El sombreado es la ventana del MCA (verde si el corte lo acepta,
rojo si lo rechaza), los punteados son `thr` y `thr − hyst`, y cada panel anota
la amplitud medida, el Q/pico, el Q/pico **esperado a esa amplitud** y el desvío
en sigmas.

Es la figura para empezar, porque hace visible el mecanismo entero. Se ve que la
ventana se **estira** con el apilamiento (779 muestras limpia, 1385 con un
segundo pulso en la cola) mientras el pico casi no sube: eso es exactamente lo
que dispara el cociente Q/pico, de 291 a 559. Y se ve el caso que no tiene
arreglo: con Δt = 4 muestras los dos pulsos se funden en uno de forma idéntica y
doble altura, y el desvío es de −0.9 σ.

### `mapa_forma.png` — dónde se separan las poblaciones

Amplitud contra factor de forma, con los eventos limpios en azul y los apilados
en rojo, más el lugar geométrico calibrado y la banda del corte. Una fila por
combinación de espectro y modo, y una columna por discriminador.

Es la figura que **decide el trabajo**, y hay que leerla comparando las cuatro
filas:

- en **modo 0** (histéresis) los apilados se van a arcos de Q/pico 400–1200
  contra 250–290 de los limpios: poblaciones separadas, y por eso el corte
  rechaza el 99 % sin tocar un evento bueno;
- en **modo 1** los arcos oscilan alrededor del lugar geométrico y lo cruzan:
  no hay dónde poner el corte;
- la columna de `Q_cola/Q_tot` muestra por qué el eje que ya está en el hardware
  no alcanza: las bandas horizontales son la cuantización a 64 bins, y en modo 1
  el cociente vive en 60/64 con **tres valores útiles**.

### `espectros.png` — la distorsión, sin corregir

Los tres espectros superpuestos a 100 kcps, eje y logarítmico: la **verdad**
(gris, las amplitudes sorteadas), la **referencia** (azul, el mismo MCA a tasa
cero) y lo **medido** (naranja). El punteado rojo es el tope de la fuente.

La referencia es la curva importante: sin ella, la diferencia contra la verdad
mezclaría el apilamiento con el ensanchamiento por ruido, el umbral y el sesgo
del estimador. Todo lo que aparece a la derecha del punteado es apilamiento
puro, porque ahí la fuente no puede poner nada. Se ve el continuo entre E y 2E y
el pico suma en 2E.

### `distorsion_vs_tasa.png` — cuánto, en función de la tasa

Tres paneles contra la tasa incidente:

1. **fotopico (línea gruesa) contra throughput (línea fina)**, con el modelo de
   tiempo muerto paralizable `exp(−λL₀)` punteado. Las dos curvas no son lo
   mismo y la diferencia entre ellas **es** el apilamiento: el throughput pierde
   sólo por tiempo muerto —y por eso sigue al modelo—, mientras que el fotopico
   pierde eso **más** los eventos que el apilamiento se llevó fuera del pico.
2. **continuo por encima del tope**, la medida más limpia de apilamiento porque
   no necesita ajustar nada.
3. **distancia L1** al espectro de referencia: la deformación de forma resumida
   en un número, sin el factor de throughput.

### `corte.png` — la distorsión, corregida

El mismo espectro de `espectros.png` con una curva más: lo medido **después** del
corte Q/pico con k = 3. En modo 0 la curva verde se pega a la referencia y el
continuo entre 2000 y 6000 desaparece; lo único que queda es el residuo del pico
suma en 3840, que son las coincidencias exactas. En modo 1 la corrección es
parcial, que es la misma conclusión de `mapa_forma.png` vista sobre el espectro.

### `compromiso.png` — lo que cuesta

Dos paneles a 100 kcps:

1. **limpios conservados contra apilados rechazados** — la curva de compromiso.
   `Q/pico` en modo 0 llega a la esquina (99 % de rechazo, 100 % de eficiencia);
   las curvas de `Q_cola/Q_tot` se quedan a mitad de camino o directamente no se
   mueven del origen.
2. **L1 contra el ancho de la banda `k`**, con el valor sin corte punteado. Es
   plano: entre k = 1.5 y k = 6 el L1 se mueve un 3 %. La separación es tan
   limpia que el corte no es sensible a dónde se ponga, lo cual importa en la
   práctica porque significa que no hay que sintonizar nada con cuidado.

### `pico_vs_carga_cr_rc4.png` — la firma del apilamiento, por espaciamiento

Lo genera un script aparte, `pico_vs_carga.py`, con la familia **CR-RC⁴** del
catálogo de Knoll (la habitual en espectroscopía) en vez de la semi-gaussiana
del resto del estudio.

**En el MCA2**, con la compuerta de 384 y el disparo por pendiente:

| caso | Q/pico, 1 ranura [µs] | pendiente | eventos por realización | Q/pico, 4 ranuras [µs] | pendiente | eventos por realización |
|---|---|---|---|---|---|---|
| limpio | 1.529 | 1.000× | 1.00 | 1.530 | 1.000× | 1.00 |
| doble Δt = 4 | 1.488 | 0.976× | 1.00 | 1.491 | 0.976× | 1.00 |
| doble Δt = 20 | 1.475 | 0.964× | 1.00 | 1.475 | 0.964× | 1.00 |
| doble Δt = 150 | 1.247 | 0.811× | 1.00 | 1.248 | 0.810× | 1.00 |
| doble Δt = 600 | 1.598 | 1.050× | 2.00 | 1.599 | 1.050× | 2.00 |
| triple Δt = 120 y 320 | 1.286 | 0.834× | 1.00 | 2.317 | 1.514× | 1.70 |

- **La recta de limpios es la misma con 1 y con 4 ranuras** (1.51 µs, 70 % del techo):
  un pulso solo no sabe cuántas ranuras hay. Es más baja que en el MCA1 porque
  `pre_dly` hace abrir la ventana antes del pie en los pulsos altos, que disparan
  temprano, y la compuerta cierra antes.
- **El doble a 150 cae debajo de la recta**: con la compuerta fija el pico suma más que
  la carga que entra. Es la firma contraria a la de la ventana por histéresis, que se
  describe abajo. Un corte por forma "sólo por arriba" no lo ve con esta forma.
- **Más ranuras sólo cambian el triple**: con cuatro, el segundo pulso abre su propia
  ventana, que junta al tercero. Es el evento de mayor carga, y por eso se va arriba.

**En el MCA1**, que es lo que describe el resto de esta sección:

El gráfico pico-vs-carga compara **dos estimadores internos del mismo evento**,
así que no depende de la exactitud del generador — por eso la campaña de formas
lo usa para medir el factor de forma. Un pulso limpio los tiene proporcionales y
cae sobre una recta de pendiente `factor_forma · FWHM`; un evento apilado suma
carga sin sumar pico en la misma proporción y **se despega de la recta hacia
arriba**. Cuánto se despega depende del espaciamiento:

| caso | Q/pico modo 0 | pendiente | ventana | Q/pico modo 1 |
|---|---|---|---|---|
| limpio | 2.112 µs | 1.000× | 540 | 1.955 µs |
| doble Δt = 4 (32 ns) | 2.134 µs | **1.008×** | 606 | 1.943 µs |
| doble Δt = 20 (160 ns) | 2.144 µs | **1.013×** | 611 | 1.945 µs |
| doble Δt = 150 (1.2 µs) | 2.690 µs | 1.271× | 699 | 2.090 µs |
| doble Δt = 600 (4.8 µs) | — | 1.646× | 549 | 1.953 µs |
| triple Δt = 120 y 320 | 3.745 µs | **1.768×** | 869 | 2.132 µs |

Tres cosas para leer en la figura:

- **Δt = 4 y 20 caen sobre la recta de limpios.** Es el límite irreducible visto
  en este plano: un doble muy junto es indistinguible de un pulso limpio del
  doble de amplitud, y de hecho su nube **extiende** la recta hasta el doble de
  pico. Las separaciones grandes, en cambio, abren rectas propias de pendiente
  1.27× y 1.77×.
- **Δt = 600 tiene dos poblaciones**, y por eso no tiene un Q/pico único: la
  ventana por histéresis **crece con la amplitud**, así que los pulsos chicos se
  separan en dos eventos limpios (el 68 % de las realizaciones) y los grandes se
  funden en uno. Es el mismo mecanismo que obliga a calibrar el corte contra la
  amplitud.
- **El panel del modo 1 está casi degenerado**: todas las rectas se superponen,
  porque la compuerta de 384 muestras deja afuera la carga del segundo pulso.
  Es la misma conclusión de `mapa_forma.png` en el plano donde la campaña de
  formas la mediría.

El script verifica además que la pendiente de los limpios queda por debajo del
techo teórico `factor_forma × FWHM = 1.0764 × 2 µs = 2.153 µs` —la ventana por
histéresis corta la cola por debajo de `thr − hyst`— y que la compuerta fija
queda todavía más abajo: **1.951 µs (90.6 %) < 2.121 µs (98.5 %) ≤ 2.153 µs**.

```bash
python3 pico_vs_carga.py                      # CR-RC⁴, 2500 realizaciones/caso
python3 pico_vs_carga.py --familia cr_rc      # otra familia del catálogo
```

## El seguidor de línea de base: qué compra, y qué no

`linea_base.py` + `graficar_base.py`. El Monte-Carlo de arriba corre con **base
fija en 0** (`cfg_bl_auto = 0`): el seguidor IIR era lo único del MCA que no
estaba modelado. Ahora sí lo está, fiel al RTL, y eso permite contestar dos
cosas.

### Lo que compra

| tasa | base fija | seguidor | base seguida | IIR congelado |
|---|---|---|---|---|
| 1 995 | +0.00 % | +0.00 % | 0.65 cuentas | 38 % |
| 20 000 | +0.06 % | +0.01 % | 1.71 | 42 % |
| 72 444 | **+0.21 %** | **+0.10 %** | 4.88 | 54 % |
| 150 000 | +0.55 % | +0.07 % | 15.7 | 68 % |
| 300 000 | +0.78 % | **−2.93 %** | 147 | 80 % |

- **Contra el pedestal de tasa**: hasta ~150 kcps el seguidor corta la deriva de
  centroide **a la mitad o mejor** (+0.55 % → +0.07 % a 150 kcps). El mecanismo
  se ve en `mecanismo_base.png` y en `trazas_base.png`: la base sólo se mueve en
  los huecos entre pulsos y sube con la tasa siguiendo al pedestal que dejan las
  colas.
- **Contra la deriva térmica**: la elimina. Con la rampa medida (0.43 mV = 3.48
  cuentas) la base fija corre el centroide **+1.90 canales** y el seguidor
  **+0.04 canales**, o sea 47× menos. Era esperable —la rampa es ~10⁴ veces más
  lenta que τ— pero deja el número puesto.
- **Dónde se rompe**: a **300 kcps el seguidor se da vuelta y corre el centroide
  −2.93 %**, peor que la base fija. Ahí está congelado el 80 % del tiempo y las
  pocas muestras que ve son todas cola, así que engancha una base de 147 cuentas
  —7.7 % de la línea— y se la resta a pulsos que no la tienen. **Es un modo de
  falla nuevo, no documentado**, y aparece justo donde el instrumento ya está
  perdiendo el 87 % de los eventos por tiempo muerto.

### Lo que NO explica: la hipótesis del repo queda descartada

[`limites_resolucion_y_deriva.md`](limites_resolucion_y_deriva.md)
dejó anotado que el seguidor era el sospechoso del 4× de deriva que el
apilamiento no explicaba. **No lo es.** Sobre la ventana de la campaña
(1995 → 72 444 Hz, ×36):

| | corrimiento de centroide |
|---|---|
| medido en placa | **+1.28 %** |
| MC, base fija (sólo apilamiento) | +0.21 % |
| MC, con seguidor (`bl_k = 12`, como la campaña) | **+0.10 %** |

El seguidor **no agrega deriva: la resta**. La campaña se midió con
`bl_auto = True`, así que la columna comparable es la última, y deja **+1.18 %
sin explicar** — más que antes, no menos. El sospechoso hay que buscarlo en otro
lado: el candidato natural es el acoplamiento de la cadena analógica (un
acoplamiento AC corre el nivel de DC con el ciclo de trabajo, que sube con la
tasa), pero **eso no está medido y queda como hipótesis**.

### El barrido de `bl_k`

A 72 kcps, `bl_k` de 6 a 15 sale plano (centroide 1923–1925). Sólo `k = 3`
(τ = 0.1 µs) se aparta, a 1915: ahí el seguidor empieza a perseguir el pulso.
Concuerda con la regla del repo (`τ ≥ 100×` la duración del pulso → `k ≥ 14.6`
para 2 µs) en el sentido de que la falla aparece por abajo, y con lo medido en
placa, donde el barrido de 3 a 18 salió plano **con pulsos de 2 µs**.

El modelo reproduce además el otro régimen sin que se lo pida: con pulsos de
**62 µs**, `k = 3` y `k = 6` dan **cero eventos** y `k ≥ 9` funciona — que es
exactamente la tabla que midió la placa en
[`resultados_validacion_hw.md §4`](../resultados_validacion_hw.md).
Está como test [15].

### Figuras

- `deriva_centroide.png` — la figura que dirime la hipótesis. Dos paneles: el
  rango completo (donde se ve el derrumbe a 300 kcps) y el zoom a la ventana de
  la campaña, con el +1.28 % medido marcado y la distancia que **ninguna** de
  las dos configuraciones cubre.
- `mecanismo_base.png` — la base seguida y la fracción de tiempo congelado
  contra la tasa. Las dos suben juntas, y ahí está el mecanismo: cuanto más alta
  la tasa, más pedestal hay que seguir y menos tiempo tiene el IIR para seguirlo.
- `trazas_base.png` — la misma traza a 72 kcps en dos escalas. Abajo, con el eje
  en la escala de la base, se ve que la línea **sólo se mueve en los huecos** y
  queda escalonada; sombreado, el IIR congelado.
- `barrido_bl_k.png` — centroide, eventos y base seguida contra `bl_k`, con la
  cota `τ = 100×` el pulso marcada.

```bash
python3 linea_base.py        # ~2.5 min
python3 graficar_base.py
```

### Ver también

[`campanas/`](../../software/campanas/) grafica en volts contra tiempo las **seis familias
de forma de pulso** que midió `run_formas.py` (CR, CR-RC, CR-RC⁴, triangular,
trapezoidal, bipolar). El **factor de forma** de esa campaña, `área/(pico·FWHM)`,
es exactamente el cociente Q/pico que usa el discriminador de acá: sus valores
medidos —de 1.343 para la CR a 0.979 para la bipolar— son el lugar geométrico
que el corte tendría que calibrar para cada forma.

## Cómo se hace viable el barrido

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
