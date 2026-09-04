#!/usr/bin/env python3
"""Helpers de análisis del MCA: funciones PURAS, sin hardware.

Se pueden correr contra ficheros .npz guardados, sin la placa — que es lo que
permite probar el análisis en la PC y regenerar las figuras de la memoria sin
tener que enchufar nada.

Excepción deliberada a la nomenclatura de `API/`: estas funciones NO llevan
prefijo de módulo. No son cfg/read/store ni pegan a ningún bloque del bus, y ya
se usan como `mu.gauss_fit_peak` en una quincena de sitios, incluidas las
figuras de `docs/mca/figuras/`. Las tres capas gobiernan la API de *hardware*.

Contenido:

    gauss_fit_peak          ajuste del fotopico -> centroide, fwhm, resolución
    energy_calibration      recta canal(E) + INL como % de fondo de escala
    dnl                     no-linealidad diferencial desde un pulser deslizante
    fom                     figura de mérito de discriminación por forma
    deadtime_fit            modelos paralizable / no paralizable
    tau_poisson             tau y TASA INCIDENTE de los Δt (fuente real)
    tau_periodico           tau acotado y pérdida exacta de los Δt (Rigol PULSE)
    error_cuantizacion      verifica que el estímulo sea el que se dice
    cv_residuo              diagnóstico de la forma de los Δt
    counts_to_volts         canal -> volts de amplitud de pico
    axis_calibration        mapa directo del eje de amplitud, con invertibilidad
    apply_calibration       corrige números de canal sueltos
    linearize_spectrum      corrige un espectro entero rebineando por bordes
    inl_residual_vs_knots   INL residual según el tamaño de la LUT del RTL
    propagar_calibracion_muestra
                            replica pulsos reales por una corrección por muestra
"""

import numpy as np

# La escala del ADC es una propiedad del front-end, no del análisis. Se importa
# del driver en vez de redefinirla acá: ya hay tres copias del literal 8192 en
# el árbol (mca, osciloscope, osciloscope_ring) y una cuarta que se desincronice
# en silencio cambiaría todos los ejes en volts sin que nada falle.
from .mca import ADC_CNT_PER_V                                     # noqa: F401


def gauss_fit_peak(spec, lo=None, hi=None):
    """Ajuste gaussiano a un pico del espectro.

    Devuelve dict con centroide, sigma, fwhm, area y resolucion_pct.

    El FWHM del pico de un PULSER (amplitud fija) ES la contribución de ruido
    electrónico de la cadena: se resta en cuadratura del FWHM total para
    separar detector de electrónica.
    """
    spec = np.asarray(spec, dtype=float)
    lo = 0 if lo is None else int(lo)
    hi = len(spec) if hi is None else int(hi)
    x = np.arange(lo, hi, dtype=float)
    y = spec[lo:hi]
    if y.sum() <= 0:
        # Ventana vacía: es un resultado posible (todo rechazado, umbral mal
        # puesto, generador apagado). Se devuelve NaN en vez de romper, para que
        # una campaña de varios puntos no se caiga por uno malo.
        return {'centroid': float('nan'), 'sigma': float('nan'),
                'fwhm': float('nan'), 'area': 0.0,
                'resolution_pct': float('nan'), 'empty': True}

    # Semilla por momentos, después refinamiento gaussiano por mínimos
    # cuadrados sobre log(y) (sólo con los bins de estadística suficiente).
    c0 = float((x * y).sum() / y.sum())
    s0 = float(np.sqrt(max((y * (x - c0) ** 2).sum() / y.sum(), 1e-9)))

    m = y > max(3.0, 0.05 * y.max())
    if m.sum() >= 4:
        # log(A) - (x-c)^2/(2 s^2)  ->  polinomio de grado 2 en x
        p = np.polyfit(x[m], np.log(y[m]), 2, w=np.sqrt(y[m]))
        if p[0] < 0:
            s0 = float(np.sqrt(-1.0 / (2.0 * p[0])))
            c0 = float(-p[1] / (2.0 * p[0]))

    # Un pico que cae en UN solo canal es un resultado legítimo, no un error:
    # pasa cuando el estimador es tan reproducible que no hay dispersión (es el
    # caso de la integral de carga con un pulser sintético). El ancho se acota
    # entonces por el propio bin, que es el límite de lo que se puede resolver.
    n_pobl = int((y > 0).sum())
    if n_pobl <= 1 or not np.isfinite(s0) or s0 <= 0:
        s0 = 1.0 / np.sqrt(12.0)        # desvío de una distribución uniforme de 1 bin

    fwhm = 2.0 * np.sqrt(2.0 * np.log(2.0)) * s0
    return {
        'centroid': c0,
        'sigma':    s0,
        'fwhm':     fwhm,
        'area':     float(y.sum()),
        'resolution_pct': 100.0 * fwhm / c0 if c0 else float('nan'),
        'bins_poblados': n_pobl,
        'empty': False,
    }


def energy_calibration(centroids, energies):
    """Ajuste lineal canal = a*E + b. Devuelve (a, b, residuos, inl_pct_fs)."""
    c = np.asarray(centroids, dtype=float)
    e = np.asarray(energies, dtype=float)
    a, b = np.polyfit(e, c, 1)
    resid = c - (a * e + b)
    fs = c.max() - c.min()
    inl = 100.0 * np.abs(resid).max() / fs if fs else float('nan')
    return a, b, resid, inl


def dnl(spec, lo=None, hi=None, smooth=64, strict=True, max_empty_frac=0.01):
    """No linealidad diferencial a partir de un espectro de *sliding pulser*.

    Con amplitud uniformemente aleatoria todos los canales deberían recibir la
    misma cuenta; la desviación relativa es la DNL. Spec típica: <±1%.

    Ojo: mide el ADC y el estimador de amplitud, no el binning. La DNL del
    binning digital es exactamente cero por construcción (el bin es un
    desplazamiento a la derecha de un entero, todos los canales igual de anchos).

    `smooth`: ancho (en canales) del promedio móvil contra el que se compara
    cada canal. La media GLOBAL sólo sirve si el estímulo llena la ventana de
    forma perfectamente plana; con cualquier estímulo suave pero no plano —el
    ruido de una modulación AM es gaussiano, no uniforme— la pendiente de la
    envolvente se cuenta como DNL y el número sale inflado. Comparar contra la
    envolvente local separa las dos cosas, que es lo que interesa. `smooth=None`
    vuelve al comportamiento viejo (media global).

    `strict` / `max_empty_frac`: si más de `max_empty_frac` de los canales de la
    ventana están SIN cuentas, levanta ValueError en vez de devolver un número.
    Un canal vacío no es DNL: es que el estímulo no lo excitó nunca (el caso de
    una forma arbitraria cíclica, que produce líneas discretas), y devolver un
    porcentaje ahí es peor que fallar. El umbral es una FRACCIÓN y no cero
    porque con un número finito de amplitudes distintas siempre queda algún
    canal sin visitar por pura estadística: con N amplitudes sobre M canales la
    probabilidad de que un canal quede vacío es exp(-N/M). Unos pocos vacíos son
    muestreo; el 19 % que dio la campaña anterior era el estímulo.
    """
    spec = np.asarray(spec, dtype=float)
    lo = 0 if lo is None else int(lo)
    hi = len(spec) if hi is None else int(hi)
    y = spec[lo:hi]
    if y.size == 0:
        raise ValueError('la ventana está vacía')
    mean = y.mean()
    if mean <= 0:
        raise ValueError('la ventana no tiene cuentas')

    n_vacios = int((y <= 0).sum())
    frac_vacios = n_vacios / y.size
    if strict and frac_vacios > max_empty_frac:
        raise ValueError(
            f'{n_vacios} de {y.size} canales de la ventana ({100*frac_vacios:.1f}%) '
            f'no tienen NINGUNA cuenta: el estímulo no barre la amplitud de '
            f'forma continua (una forma arbitraria cíclica produce líneas '
            f'discretas). La DNL que saldría de acá no significa nada. Subí el '
            f'número de amplitudes distintas (más recargas del ARB) o usá '
            f'modulación de ruido.')

    if smooth:
        k = int(smooth)
        if k % 2 == 0:
            k += 1                       # impar: el promedio queda centrado
        if k >= y.size:
            k = max(3, (y.size // 2) | 1)
        # Promedio móvil con bordes reflejados, para no hundir los extremos.
        pad = k // 2
        yp  = np.pad(y, pad, mode='reflect')
        env = np.convolve(yp, np.ones(k) / k, mode='valid')
    else:
        env = np.full_like(y, mean)

    env = np.where(env > 0, env, np.nan)
    d = (y - env) / env
    return {'dnl': d, 'dnl_max_pct': 100.0 * float(np.nanmax(np.abs(d))),
            'dnl_rms_pct': 100.0 * float(np.sqrt(np.nanmean(d ** 2))),
            'mean_counts': mean, 'n_empty': n_vacios,
            'empty_frac': frac_vacios, 'smooth': smooth, 'envelope': env}


def fom(map2d, amp_lo=None, amp_hi=None):
    """Figure of Merit de la separación por forma de pulso.

    FOM = |c1 - c2| / (FWHM1 + FWHM2) sobre la proyección del eje de forma.
    FOM > 1.27 se considera buena separación.

    `amp_lo`/`amp_hi` permiten calcularla por rebanadas de amplitud, que es
    como se ve que la separación se degrada a baja energía.
    """
    m = np.asarray(map2d, dtype=float)
    lo = 0 if amp_lo is None else int(amp_lo)
    hi = m.shape[0] if amp_hi is None else int(amp_hi)
    proj = m[lo:hi, :].sum(axis=0)
    if proj.sum() <= 0:
        raise ValueError('la rebanada de amplitud no tiene cuentas')

    # Separar las dos poblaciones por el mínimo entre los dos máximos.
    i1 = int(np.argmax(proj))
    # el segundo pico: el máximo fuera de un entorno del primero
    mask = np.ones_like(proj, dtype=bool)
    w = max(2, len(proj) // 16)
    mask[max(0, i1 - w):i1 + w + 1] = False
    if not mask.any() or proj[mask].max() <= 0:
        return {'fom': float('nan'), 'reason': 'no se detectaron dos poblaciones'}
    i2 = int(np.arange(len(proj))[mask][np.argmax(proj[mask])])
    a, b = sorted((i1, i2))
    valley = a + int(np.argmin(proj[a:b + 1]))

    g1 = gauss_fit_peak(proj, 0, valley + 1)
    g2 = gauss_fit_peak(proj, valley, len(proj))
    denom = g1['fwhm'] + g2['fwhm']
    return {
        'fom': abs(g2['centroid'] - g1['centroid']) / denom if denom else float('nan'),
        'peak1': g1, 'peak2': g2, 'valley': valley,
    }


def deadtime_fit(rate_in, rate_out):
    """Ajusta los modelos de tiempo muerto paralizable y no paralizable.

    No paralizable: m = n/(1+n*tau)   Paralizable: m = n*exp(-n*tau)
    Devuelve el tau de cada uno y cuál ajusta mejor. Cuál de los dos describe
    al sistema determina la corrección a aplicar a las cuentas.
    """
    n = np.asarray(rate_in, dtype=float)
    m = np.asarray(rate_out, dtype=float)
    ok = (n > 0) & (m > 0)
    n, m = n[ok], m[ok]
    if len(n) < 3:
        raise ValueError('hacen falta al menos 3 puntos')

    # no paralizable: 1/m = 1/n + tau  ->  tau = media(1/m - 1/n)
    tau_np = float(np.mean(1.0 / m - 1.0 / n))
    # paralizable: ln(m/n) = -n*tau  ->  ajuste por el origen
    tau_p = float(-np.sum(n * np.log(m / n)) / np.sum(n * n))

    def _sse(pred):
        return float(np.sum((m - pred) ** 2))
    sse_np = _sse(n / (1.0 + n * tau_np))
    sse_p = _sse(n * np.exp(-n * tau_p))
    return {
        'tau_nonparalyzable_s': tau_np, 'sse_nonparalyzable': sse_np,
        'tau_paralyzable_s':    tau_p,  'sse_paralyzable':    sse_p,
        'best': 'no paralizable' if sse_np <= sse_p else 'paralizable',
    }


# =============================================================================
# Tiempo muerto inferido de los intervalos entre eventos
# =============================================================================
#
# `deadtime_fit` (arriba) necesita un BARRIDO de tasas: ajusta m(n) sobre varios
# puntos. Lo que sigue saca tau de UNA SOLA corrida, de la distribución de los
# Δt, y es lo que permite estimarlo en tiempo de corrida.
#
# Es el complemento del `DeadTimeAnnotator` (API/osciloscope_store/annotators.py),
# que cronometra el período ocupado directamente. Los dos hacen falta: el
# cronómetro mide tau sin suponer nada sobre los arribos, pero NO puede dar la
# tasa incidente; la inferencia por intervalos sí, y sirve de contraste.
#
# EL PROCESO DE ARRIBOS CAMBIA LA MATEMÁTICA, no es un parámetro del mismo
# ajuste. Por eso hay dos funciones y no una con un flag:
#
#   Poisson (fuente real)      Δt = tau + Exp(n)   exponencial DESPLAZADA
#   periódico (Rigol PULSE)    Δt = k·T            CUANTIZADA, k = ⌈tau/T⌉
#
# La primera determina tau y además `n`; la segunda sólo ACOTA tau, y a cambio
# da la pérdida exacta sin pasar por ningún modelo. Ver
# `../docs/mca/tiempo_muerto.md` para por qué el estímulo periódico engaña.


def _intervalos_limpios(t_ns, gap):
    """Δt utilizables: los pares SIN descartes de backpressure en el medio.

    `gap` cuenta SÓLO los descartes por backpressure (la rama `queue.Empty` del
    lector). Los eventos perdidos por tiempo muerto **no dejan rastro**: el
    scope no estaba armado, así que no hubo trigger que detectar y el lector
    nunca se enteró.

    Esa asimetría es justo lo que hace válido el método. Los Δt tienen que
    incluir las pérdidas por tiempo muerto —son la señal que se está midiendo—
    y NO las de backpressure, que son un artefacto del pipeline de software.
    Filtrar por `gap == 0` deja exactamente eso.

    Medido en simulación con 20 % de backpressure encima: sin filtrar, la tasa
    incidente sale sesgada un 24 %.
    """
    t_ns = np.asarray(t_ns, dtype=np.int64)
    gap  = np.asarray(gap)
    if t_ns.ndim != 1 or gap.shape != t_ns.shape:
        raise ValueError('t_ns y gap tienen que ser 1-D y del mismo largo')
    dt = np.diff(t_ns) / 1e9
    return dt[gap[1:] == 0]          # el gap del evento que CIERRA el par


def tau_poisson(t_ns, gap, q=0.001):
    """tau y TASA INCIDENTE, para arribos de Poisson (una fuente real).

    Con un sistema K=1 no paralizable el intervalo entre eventos REGISTRADOS es
    una exponencial DESPLAZADA::

        Δt = tau + Exp(n)

    El corrimiento da `tau` y la pendiente da `n`, la tasa que realmente entró
    — que es lo que no se puede obtener de ninguna otra forma sin una fuente
    calibrada ni un pulser de referencia.

    `q` es un cuantil bajo en lugar del mínimo estricto: el MLE del corrimiento
    es `min(Δt)`, pero un solo outlier por debajo (jitter del reloj de software)
    lo arruina. Se paga algo de sesgo y se gana robustez.

    Validado por Monte-Carlo contra un K=1 de tau conocido
    (`API/tests/test_deadtime_estimadores.py`): tau dentro de ±3 % y
    `n` dentro de ±5 % en el rango rho = 0.05 … 2.

    **Requiere arribos de Poisson.** Con el Rigol en PULSE no aplica: un tren
    periódico no tiene esta distribución. Usar `tau_periodico`.
    """
    dt = _intervalos_limpios(t_ns, gap)
    if dt.size < 100:
        raise ValueError(f'muy pocos intervalos limpios ({dt.size}): hacen '
                         'falta al menos 100')
    tau = float(np.quantile(dt, q))
    med = float(dt.mean())
    if med <= tau:
        raise ValueError('la media de los Δt no supera al corrimiento: los '
                         'datos no son una exponencial desplazada')
    n   = 1.0 / (med - tau)
    rho = n * tau
    return {
        'modelo': 'poisson', 'tau_s': tau,
        'n_incidente': n, 'm_registrada': 1.0 / med,
        'rho': rho, 'perdida': rho / (1.0 + rho),
        'n_intervalos': int(dt.size),
    }


def error_cuantizacion(t_ns, gap, T_s):
    """Mediana de |Δt/T − entero más cercano|, en unidades de período.

    Es LA propiedad que define a un tren periódico visto por un sistema K=1:
    los intervalos registrados son múltiplos enteros de T.

        periódico -> ~0     (los Δt SON múltiplos de T)
        Poisson   -> ~0.25  (la parte fraccionaria queda uniforme en [−0.5, 0.5])

    Sirve para VERIFICAR que el estímulo es el que se dice, no como selector
    automático: hace falta `T_s`, que se conoce porque se programa el generador.
    """
    dt = _intervalos_limpios(t_ns, gap) / float(T_s)
    if dt.size == 0:
        raise ValueError('no quedaron intervalos limpios')
    return float(np.median(np.abs(dt - np.round(dt))))


def tau_periodico(t_ns, gap, T_s, tol=0.15):
    """tau (ACOTADO) y pérdida EXACTA, para un tren periódico (Rigol en PULSE).

    Un D/D/1/1 acepta un arribo cada `k = ⌈tau/T⌉` períodos, así que los Δt
    quedan cuantizados en múltiplos de T. De ahí salen tres cosas:

    - `k`, redondeando `Δt/T`;
    - la **pérdida exacta**, `1 − 1/⟨k⟩`, sin pasar por ningún modelo;
    - y tau **acotado**, no determinado:  `(k−1)·T < tau <= k·T`.

    Ese bracket no es debilidad del estimador: el modelo es **discontinuo en
    tau** y con un solo `k` poblado la información no está en los datos. Es el
    mismo "cualquier tau entre 200 y 250 µs da la misma predicción" que ya
    reporta `../docs/mca/tiempo_muerto.md`. Lo que lo aprieta es barrer T e
    **intersecar los brackets**.

    Caso especial útil: cuando `tau/T` cae cerca de un entero se pueblan DOS `k`
    adyacentes, y entonces el borde entre ellos localiza tau directamente. Es lo
    que pasa en el punto de 20 kev/s del barrido del lector (`tau/T = 5.00`).

    `T_s` es obligatorio: con un único `k` poblado, `Δt = k·T` es indistinguible
    de un tren de período `k·T`. Se conoce, se programa el generador.

    `tol` es el error de cuantización admitido, EN UNIDADES DE PERÍODO, y no es
    arbitrario: el jitter del reloj de software ensancha cada Δt, así que el
    error escala como `jitter/T` — con 3 µs de jitter da 0.01 períodos a
    T = 1 ms pero 0.06 a T = 50 µs. El contraste es contra Poisson, que da 0.25,
    y el default va en el medio. De ahí sale el límite de validez: la prueba
    pierde poder cuando T se acerca al jitter del timestamp (~30 µs, o sea
    33 kev/s, bastante por encima del techo de ~11 kev/s del lector).
    """
    T_s = float(T_s)
    if T_s <= 0:
        raise ValueError('T_s tiene que ser positivo')
    dt = _intervalos_limpios(t_ns, gap)
    if dt.size < 100:
        raise ValueError(f'muy pocos intervalos limpios ({dt.size}): hacen '
                         'falta al menos 100')

    # El test de cuantización va PRIMERO: es el discriminante de verdad, y da
    # el diagnóstico útil. Si fuera después del chequeo de k, un estímulo
    # Poisson con Δt cortos fallaría con "T_s incompatible", que manda a
    # revisar el T en vez de a cambiar de función.
    k   = np.round(dt / T_s).astype(int)
    err = float(np.median(np.abs(dt / T_s - k)))
    if err > tol:
        raise ValueError(
            f'los Δt no son múltiplos de T_s={T_s:g} s (error de cuantización '
            f'mediano {err:.3f} períodos, tolerancia {tol}): el estímulo no es '
            'periódico — usar tau_poisson')
    if (k < 1).any():
        raise ValueError(f'T_s={T_s:g} s incompatible con los datos: hay Δt '
                         'menores a T/2 aunque estén cuantizados. Suele ser un '
                         'T_s mal pasado (¿factor de 10? ¿Hz en vez de s?)')

    ks, cuentas = np.unique(k, return_counts=True)
    frac    = cuentas / cuentas.sum()
    orden   = np.argsort(-cuentas)
    k_moda  = int(ks[orden[0]])
    k_medio = float((ks * frac).sum())

    salida = {
        'modelo': 'periodico', 'T_s': T_s, 'err_cuantizacion': err,
        'k_moda': k_moda, 'k_medio': k_medio,
        'k_frac': {int(a): float(b) for a, b in zip(ks, frac)},
        'tau_lo': (k_moda - 1) * T_s, 'tau_hi': k_moda * T_s,
        'n_incidente': 1.0 / T_s, 'm_registrada': 1.0 / float(dt.mean()),
        'perdida': 1.0 - 1.0 / k_medio,
        'n_intervalos': int(dt.size),
    }

    # Dos k adyacentes poblados: es LA condición que localiza tau dentro del
    # bracket, porque el borde entre ellos está a un pelo de tau.
    if len(ks) >= 2 and abs(int(ks[orden[1]]) - k_moda) == 1:
        k_bajo = min(k_moda, int(ks[orden[1]]))
        salida['tau_est'] = k_bajo * T_s
        salida['frac_bajo_borde'] = float(frac[ks <= k_bajo].sum())
    return salida


def cv_residuo(t_ns, gap, q=0.001):
    """CV del residuo de los Δt. **Diagnóstico, NO selector automático.**

    Anclajes: exponencial da 1.00, jitter gaussiano da ~0.33, y ninguno de los
    dos depende de rho ni de la amplitud del jitter. Tienta usarlo para elegir
    modelo solo, y por eso conviene decir por qué no se hace:

    cuando `tau/T` cae cerca de un entero, el periódico reparte los eventos
    entre `k` y `k+1`, los Δt se vuelven bimodales y el CV sube hasta ~0.91 —
    indistinguible de Poisson. Medido en el Monte-Carlo: se equivoca en 3 de 5
    casos periódicos, incluido `tau/T = 5.00`, que es el punto de 20 kev/s del
    barrido del lector. El modelo se declara; para verificarlo está
    `error_cuantizacion`, que sí acierta en los cinco.
    """
    dt = _intervalos_limpios(t_ns, gap)
    if dt.size == 0:
        raise ValueError('no quedaron intervalos limpios')
    resid = dt - np.quantile(dt, q)
    m = float(resid.mean())
    return float(resid.std() / m) if m > 0 else 0.0


def counts_to_volts(bins, h_shift=0, amp_src=0, q_shift=0):
    """Convierte índice de canal a volts de amplitud de pico.

    Sólo tiene sentido con amp_src=0 (muestra de pico). Con la integral el eje
    es carga, no amplitud, y la escala depende del ancho del pulso.
    """
    if amp_src:
        raise ValueError('con amp_src=1 el eje es carga: calibrá contra el '
                         'generador en vez de convertir')
    return np.asarray(bins, dtype=float) * (1 << h_shift) / ADC_CNT_PER_V


# =============================================================================
# Linealización del eje de amplitud
#
# Modelo:   Ahat = G*A + INL(A)      A = amplitud de referencia (lo que entra)
#                                    Ahat = centroide medido, en canales
#
# Para poder recuperar A a partir de Ahat el mapa tiene que ser estrictamente
# creciente:
#
#       d(Ahat)/dA = G + d(INL)/dA > 0     <=>     min d(INL)/dA > -G
#
# OJO con la dirección de la derivada: la condición es sobre dINL/dA, no sobre
# dA/dINL. Acá se calcula el MARGEN  G + min(dINL/dA)  y no un booleano, porque
# un margen chico dice que la inversión existe pero es numéricamente frágil.
#
# DOS PATOLOGÍAS DISTINTAS, que conviene no mezclar:
#
#   (a) PLEGADO. Si el margen es <= 0 el mapa se pliega y dos regiones no
#       conexas de energía caen en el mismo canal. NINGUNA corrección lo
#       deshace: la información se perdió en el hardware.
#   (b) PEINE DE DNL. Aparece aunque el mapa sea perfectamente monótono, sólo
#       por estirar y comprimir bins: unos canales terminan recibiendo un rango
#       de entrada más ancho que otros. Se mitiga corrigiendo con más bits de
#       los que tiene el eje (es el caso: ev_amp son 16 b y el eje 14), pero hay
#       que MEDIRLO con dnl(), no suponerlo.
#
# UNA CALIBRACIÓN NO SIGNIFICA LO MISMO PARA CADA FEATURE. Una corrección en el
# dominio de MUESTRA (x -> f(x), un filtro sin memoria) se propaga distinto
# según qué se estime después:
#
#   pico     P = max(x)   -> con f monótona el máximo CONMUTA: P' = f(P).
#                           Warp exacto del eje, no depende de la forma.
#   integral Q = sum(x)   -> sum(f(x)) != f(sum(x)). Con f lineal queda
#                           Q' = g*Q + o*N, o sea que el offset entra
#                           multiplicado por el LARGO DE LA VENTANA. Con f no
#                           lineal NO EXISTE ningún mapa escalar Q -> Q': es un
#                           funcional de la forma entera.
#   cocientes             -> una ganancia se cancela; un offset no.
#
# O sea que el pico es la única feature donde calibrar la muestra y calibrar la
# feature son la misma cosa. Para la integral no hay fórmula cerrada y hay que
# replayar pulsos reales: eso es propagar_calibracion_muestra().
# =============================================================================

def _interp_lineal_extrap(x, xp, fp):
    """np.interp pero extrapolando linealmente en vez de saturar.

    np.interp CLAVA el valor de los extremos fuera del rango. Para un eje de
    calibración eso es un modo de falla silencioso: todo lo que caiga fuera del
    rango calibrado se apilaría en el último canal en vez de correrse. Acá se
    extrapola con la pendiente del tramo extremo, y el llamador decide qué
    hacer con lo que quedó afuera (linearize_spectrum lo cuenta y lo reporta).
    """
    x  = np.asarray(x, dtype=float)
    xp = np.asarray(xp, dtype=float)
    fp = np.asarray(fp, dtype=float)
    y  = np.interp(x, xp, fp)

    izq = x < xp[0]
    if izq.any():
        m = (fp[1] - fp[0]) / (xp[1] - xp[0])
        y[izq] = fp[0] + m * (x[izq] - xp[0])
    der = x > xp[-1]
    if der.any():
        m = (fp[-1] - fp[-2]) / (xp[-1] - xp[-2])
        y[der] = fp[-1] + m * (x[der] - xp[-1])
    return y


def axis_calibration(ref, centroids, inl_model='knots', deg=3, n_grid=1024):
    """Construye el mapa directo g: A -> Ahat desde una campaña de amplitud.

    `ref`       amplitudes de referencia (lo que se le pidió al generador, o la
                energía de las líneas de una fuente).
    `centroids` centroide medido de cada una, en canales (de gauss_fit_peak).

    `inl_model`:
      'knots' (default) — la INL es la interpolación lineal de los residuos
          medidos. No inventa estructura entre puntos y representa cualquier
          curva monótona.
      'poly' — ajuste polinómico de grado `deg` al residuo. Es opción y NO
          default: un polinomio puede salir NO MONÓTONO entre los puntos
          medidos sin que se note, y ahí el eje se pliega (patología (a)).

    Devuelve un dict que consumen apply_calibration() y linearize_spectrum().
    Las claves que importan:

      gain, offset   el ajuste lineal global
      inl_pct_fs     INL como residuo máximo en % de fondo de escala
      margen         G + min(dINL/dA). > 0 => invertible. Es EL número.
      invertible     bool, pero mirá el margen

    ADVERTENCIA DE INTERPRETACIÓN: si la referencia es un generador, la INL que
    sale de acá es la del CONJUNTO (MCA + generador + INL estática del ADC), no
    la del MCA. Corregir con ella mete la calibración del generador adentro del
    instrumento. Ver run_formas.py, que separa lo común de lo diferencial.
    """
    a = np.asarray(ref, dtype=float)
    c = np.asarray(centroids, dtype=float)
    ok = np.isfinite(a) & np.isfinite(c)
    a, c = a[ok], c[ok]
    if a.size < 3:
        raise ValueError(f'hacen falta al menos 3 puntos válidos, hay {a.size}')

    o = np.argsort(a)
    a, c = a[o], c[o]
    if np.any(np.diff(a) <= 0):
        raise ValueError('hay amplitudes de referencia repetidas: el mapa '
                         'A -> Ahat no queda definido')

    # El ajuste lineal y el residuo ya los hace energy_calibration.
    G, b, resid, inl_pct = energy_calibration(c, a)
    if G <= 0:
        raise ValueError(f'la ganancia salió {G:.4g} <= 0. Todo el modelo '
                         f'supone un eje creciente; con ganancia negativa hay '
                         f'que revisar el signo del estímulo, no calibrar')

    ag = np.linspace(a[0], a[-1], int(n_grid))
    if inl_model == 'knots':
        p  = None
        ig = np.interp(ag, a, resid)
    elif inl_model == 'poly':
        p  = np.polyfit(a, resid, int(deg))
        ig = np.polyval(p, ag)
    else:
        raise ValueError(f"inl_model tiene que ser 'knots' o 'poly', no {inl_model!r}")

    cg = G * ag + b + ig                      # Ahat sobre la malla densa

    dinl     = np.gradient(ig, ag)
    dinl_min = float(dinl.min())
    margen   = G + dinl_min
    # El chequeo sobre la malla es el mismo criterio, pero directo: si algún
    # tramo no crece, el mapa se pliega ahí.
    monotona = bool(np.all(np.diff(cg) > 0))

    fs = float(c.max() - c.min())
    return {
        'ref': a, 'centroids': c,
        'gain': float(G), 'offset': float(b),
        'resid': resid, 'inl_pct_fs': float(inl_pct),
        'a_grid': ag, 'chat_grid': cg, 'inl_grid': ig,
        'inl_model': inl_model, 'poly': p,
        'dinl_min': dinl_min,
        'margen': float(margen),
        'invertible': bool(margen > 0 and monotona),
        'monotona': monotona,
        'fs_canales': fs,
    }


def _exigir_invertible(cal):
    if not cal['invertible']:
        raise ValueError(
            f"el eje NO es invertible: margen G + min(dINL/dA) = "
            f"{cal['margen']:.4g} (G = {cal['gain']:.4g}). El mapa A -> Ahat se "
            f"pliega, o sea que dos regiones no conexas de energía caen en el "
            f"mismo canal. Eso NO se corrige con ningún rebinning: la "
            f"información se perdió en el hardware. Revisá el estímulo, o usá "
            f"inl_model='knots' si venías con 'poly' (un polinomio puede "
            f"perder la monotonía entre los puntos medidos).")


def apply_calibration(bins, cal):
    """Mapea números de canal MEDIDOS a canales CORREGIDOS. No rebinnea.

    Es para corregir escalares ya ajustados (centroides de gauss_fit_peak). El
    mapa compuesto es  T(chat) = G * g^-1(chat) + b,  o sea: se vuelve a la
    amplitud de entrada y se la re-proyecta con la recta ideal. Así el eje
    corregido queda en las MISMAS unidades de canal que el crudo y los dos
    espectros se superponen.

    Con INL == 0 esto es la identidad, por construcción.
    """
    _exigir_invertible(cal)
    A = _interp_lineal_extrap(bins, cal['chat_grid'], cal['a_grid'])
    return cal['gain'] * A + cal['offset']


def linearize_spectrum(spec, cal):
    """Corrige un espectro entero conservando las cuentas.

    El punto que hace falta entender: linealizar el eje NO es renombrar los
    canales. Si el mapa estira una zona y comprime otra, las ALTURAS del
    histograma también cambian — si no, el pico corregido queda en el lugar
    correcto pero con el área equivocada, y aparece una DNL falsa.

    El método es rebinning por BORDES:

      1. los bordes enteros 0..N del espectro medido se pasan por T,
      2. la cuenta acumulada se interpola en la grilla destino,
      3. np.diff de eso son las cuentas corregidas.

    Conserva las cuentas EXACTAMENTE y absorbe el jacobiano sin derivar nada.
    Es a propósito: la fórmula puntual N(A) = N(g(A)) * g'(A) obliga a derivar
    un interpolante construido sobre datos ruidosos, que es justo lo que no
    conviene hacer, y encima no conserva las cuentas sobre una grilla discreta.

    Convención de bordes: el canal i cubre [i, i+1). Es la del RTL, donde el
    bin es una truncación (amp >> shift). La misma convención se usa para ir y
    para volver, así que cualquier medio bin de sesgo se cancela.

    Devuelve dict con:
      spec              el espectro corregido, mismo largo que el de entrada
      edges_ref         los bordes del eje corregido en unidades de REFERENCIA
      counts_out        cuentas que cayeron fuera del eje y se perdieron
      frac_out          esas cuentas como fracción del total
    """
    _exigir_invertible(cal)
    y = np.asarray(spec, dtype=float)
    n = y.size

    bordes_src = apply_calibration(np.arange(n + 1, dtype=float), cal)
    if np.any(np.diff(bordes_src) <= 0):
        # No debería pasar si el margen es positivo; si pasa es que la malla
        # densa no resolvió una ondulación fina del modelo.
        raise ValueError('los bordes corregidos no quedaron crecientes: subí '
                         'n_grid en axis_calibration, o pasá a inl_model="knots"')

    bordes_dst = np.arange(n + 1, dtype=float)
    cum = np.concatenate(([0.0], np.cumsum(y)))
    # np.interp SATURA fuera de rango, que acá es exactamente lo que se quiere:
    # lo que quedó fuera del eje destino no se reparte en ningún bin, y la
    # diferencia contra el total es la pérdida, que se reporta.
    out = np.diff(np.interp(bordes_dst, bordes_src, cum))

    total = float(y.sum())
    fuera = total - float(out.sum())
    return {
        'spec': out,
        'edges_ref': (bordes_dst - cal['offset']) / cal['gain'],
        'counts_out': fuera,
        'frac_out': fuera / total if total else 0.0,
    }


def inl_residual_vs_knots(cal, n_knots=(8, 16, 32, 64, 128, 256)):
    """INL que QUEDARÍA después de corregir con una LUT de N nodos.

    Sirve para dimensionar la tabla del RTL ANTES de sintetizar nada: para cada
    N se muestrea la curva de INL en N nodos equiespaciados, se interpola
    linealmente entre ellos (que es lo que hace la LUT en hardware) y el residuo
    INL - INL_interpolada es el error que la tabla NO puede corregir.

    Devuelve dict con `n_knots`, `inl_pct_fs` (residual por cada N) y
    `inl_pct_fs_original`, para poder decidir con la curva en la mano en vez de
    elegir 64 o 128 nodos a ojo.
    """
    ag, ig = cal['a_grid'], cal['inl_grid']
    fs = cal['fs_canales']
    res = []
    for n in n_knots:
        n = int(n)
        if n < 2:
            raise ValueError('una LUT necesita al menos 2 nodos')
        nodos = np.linspace(ag[0], ag[-1], n)
        recon = np.interp(ag, nodos, np.interp(nodos, ag, ig))
        res.append(100.0 * float(np.abs(ig - recon).max()) / fs if fs else float('nan'))
    return {
        'n_knots': np.asarray(n_knots, dtype=int),
        'inl_pct_fs': np.asarray(res, dtype=float),
        'inl_pct_fs_original': cal['inl_pct_fs'],
    }


def propagar_calibracion_muestra(ondas, f, estimadores, baseline=0.0):
    """Cómo cambia cada feature al aplicar una corrección x -> f(x) por MUESTRA.

    Para el pico hay respuesta analítica (el máximo conmuta con f monótona), y
    para la integral NO EXISTE ningún mapa escalar: depende de la forma entera
    del pulso. Así que se calcula replayando pulsos reales.

    `ondas`       (n_eventos, n_muestras) en cuentas de ADC.
    `f`           callable sobre un array de muestras. Tiene que ser monótona
                  creciente; se verifica sobre el rango que realmente aparece.
    `estimadores` dict nombre -> callable(ondas_2d, baseline) -> array de un
                  valor por evento. Acá se pasan las réplicas bit-exactas del
                  RTL de API/modelo_rtl/estimadores.py; se inyectan en vez de
                  importarse para que este módulo no dependa de los tests.

    Devuelve dict nombre -> {'crudo', 'calibrado', 'ratio_medio'}.
    """
    w = np.asarray(ondas)
    if w.ndim != 2:
        raise ValueError(f'ondas tiene que ser (n_eventos, n_muestras), es {w.shape}')

    # La monotonía de f no se asume: se verifica sobre el rango que de verdad
    # aparece en los datos. Si f no es monótona, ni siquiera el pico conmuta y
    # todo lo que salga de acá es basura.
    prueba = np.arange(int(w.min()), int(w.max()) + 1, dtype=float)
    if prueba.size >= 2 and np.any(np.diff(np.asarray(f(prueba), dtype=float)) < 0):
        raise ValueError('f no es monótona creciente sobre el rango de muestras '
                         'presente en los datos: la propagación no está definida')

    wc = np.asarray(f(w.astype(float)))
    salida = {}
    for nombre, est in estimadores.items():
        crudo = np.asarray(est(w, baseline), dtype=float)
        calib = np.asarray(est(wc, float(f(np.array([baseline]))[0])), dtype=float)
        m = np.isfinite(crudo) & np.isfinite(calib) & (crudo != 0)
        salida[nombre] = {
            'crudo': crudo, 'calibrado': calib,
            'ratio_medio': float(np.mean(calib[m] / crudo[m])) if m.any() else float('nan'),
        }
    return salida