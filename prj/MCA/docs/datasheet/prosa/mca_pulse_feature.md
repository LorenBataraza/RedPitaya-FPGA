<!-- Prosa a mano del datasheet de `mca_pulse_feature`: la §1.1 «Qué hace».

     Este archivo es la FUENTE. `modulos/mk/datasheet.py` lo copia dentro del
     bloque AUTO:prosa de `../datasheet_mca_pulse_feature.md` en cada corrida, y nunca lo
     reescribe: es el unico lugar donde esta prosa se edita, y por eso vive
     afuera de la pagina generada.  Estos comentarios no se copian.

     Los enlaces y las imagenes se escriben relativos a ESTE archivo, asi
     renderiza bien y el chequeo de enlaces del repo lo puede verificar; al
     copiarlos a la pagina se recalculan solos.                         -->

**Qué hace.** Es **el bloque central del MCA**: recibe el flujo de muestras ya
calibrado y, por cada pulso que detecta, emite **un** registro de evento
coherente con todas sus características —pico, integral, cocientes de forma,
largo, tiempo de subida—. Que salga de un único registro es lo que garantiza
que el espectro 1D y el mapa 2D cuenten **exactamente los mismos pulsos**; si
cada histograma se armara su propio evento, un corte podría afectar a uno y no
al otro y las dos vistas dejarían de ser comparables.

Su vida completa, muestra por muestra y con los números de cada etapa medidos
sobre la simulación, está en
[`mca_pulso_vida.svg`](../../mca/figuras/ondas/mca_pulso_vida.svg).

**Hoy es solo cableado.** El trabajo está en tres submódulos:
[`mca_baseline`](../datasheet_mca_baseline.md) (la línea de base),
[`mca_window`](../datasheet_mca_window.md) (la ventana, los acumuladores y la
contabilidad de tiempo muerto) y [`mca_publish`](../datasheet_mca_publish.md)
(la FIFO, los divisores y el bus de features). Los puertos son los de siempre, y
el comportamiento es bit-idéntico al del módulo único: lo verifica
`tb_mca_pulse_feature_eq` contra la copia congelada `sim/mca_pulse_feature_ref.v`.
Dónde van las fronteras lo decidió el timing; el detalle está en
[`decisiones_diseno_mca.md`](../../mca/decisiones_diseno_mca.md) §6.

**Tres decisiones que explican su forma.**

**1 · Hay dos modos de cerrar la ventana, y la diferencia se mide.** Con
histéresis el largo lo decide dónde la cola cruza el umbral, que es la parte
más chata del pulso: lo decide el ruido. Con compuertas fijas el largo es
`cfg_gate_long` y no depende de la señal. Sobre **7054 pulsos reales**, offline,
la resolución de la integral pasa de **0.528 % a 0.149 %**
(`software/API/modelo_rtl/estimadores.py`). Los dos modos conviven en el mismo
bitstream porque comparar dos políticas sobre los **mismos** pulsos es lo único
que decide entre ellas con datos.

**2 · La amplitud es seleccionable, y eso ES el experimento.** `cfg_amp_src = 0`
toma la muestra de pico —ruido de una sola muestra, y el muestreo casi nunca
cae en el máximo real: ensancha el fotopico—; `= 1` toma la integral de carga,
donde el ruido blanco promedia como σ/√N y el jitter de muestreo no entra.
Poder alternar entre las dos en el mismo bitstream es lo que permite **medir**
la contribución del jitter en vez de estimarla
([`fuentes_de_jitter.md`](../../mca/fuentes_de_jitter.md)).

**3 · El tiempo muerto se mide por casilleros, no por `busy`.** `busy_o` **no**
es la condición de bloqueo del módulo, y usarlo como tal es lo que hacía que el
reloj de tiempo muerto de [`mca_top`](../datasheet_mca_top.md) mintiera: la
condición real exige `armed`, que es de **nivel**, así que mientras la cola del
último pulso siga arriba el módulo está en `S_IDLE` —`busy_o` bajo— pero **no
puede abrir**. Ese tiempo no entraba en ningún contador. Por eso salen los
cuatro casilleros `dt_win` / `dt_div` / `dt_rearm` / `puede_abrir`, mutuamente
excluyentes, más los contadores de atribución que mandan **cada** cruce de
umbral a exactamente un casillero. El desarrollo está en
[`tiempo_muerto.md`](../../mca/tiempo_muerto.md).

**Los detalles que parecen menores y no lo son.** El seguidor de línea de base
usa un acumulador ancho porque con la forma ingenua el incremento se cuantiza a
cero y el seguidor se congela; se descongela `cfg_bl_holdoff` muestras
**después** del pulso para no agarrar el undershoot de la cola. El pico se
compara con `>` estricto, porque con `>=` el instante de pico se correría hasta
el final de una meseta con ruido y el tiempo de subida saldría arbitrariamente
largo. Cada muestra se satura a ≥ 0 antes de acumular, porque si no una cola con
undershoot resta de `q_tot` mientras `q_tail` sigue sumando y se llega a
`q_tail > q_tot`, que rompe la premisa del divisor.

El apilamiento —ventana que llega a `cfg_maxlen`— se **cuenta** en
`cnt_pileup` pero **no se histogramea**: su integral y su pico están
contaminados por el segundo pulso. Se ve cerrarse en
[`mca_apilamiento.svg`](../../mca/figuras/ondas/mca_apilamiento.svg) y el
tratamiento completo está en [`apilamiento.md`](../../mca/apilamiento.md).

> **El bloque que el formal no paga.** Acumuladores anchos sobre ventanas de
> miles de ciclos: la profundidad de BMC mata el intento, y la propiedad
> interesante necesita el modelo de referencia que ya existe. Es el único de la
> lista con veredicto **no** en
> [`verificacion_formal.md`](../../verificacion_formal.md).
