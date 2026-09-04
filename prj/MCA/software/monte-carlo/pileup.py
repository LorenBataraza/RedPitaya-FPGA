"""Apilamiento en el MCA: generación, réplica vectorizada del RTL y métricas.

Corre en la PC, sin placa y sin datos medidos. Es el motor del Monte-Carlo:
`montecarlo.py` lo usa para barrer tasas y `graficar.py` para rehacer las
figuras. Todo son funciones puras sobre arrays, así que se testea entero con
`test_pileup.py`.

POR QUÉ EXISTE
--------------
El MCA mide un evento por ventana. Dos pulsos más cercanos que el largo de esa
ventana se suman en un solo evento y entran al histograma como si fueran uno de
mayor energía: se pierden cuentas del fotopico, aparece un continuo entre E y 2E
y un pico suma en 2E. En la placa no hay forma de medir esa distorsión, porque
no existe el espectro "sin apilamiento" contra el cual comparar. En un
Monte-Carlo sí: las amplitudes se sortean, así que la verdad se conoce exacta.

QUÉ HAY ACÁ
-----------
  1. GENERACIÓN: la forma semi-gaussiana de la campaña de referencia
     (`rigol_dg4162.detector_pulse`), los espectros fuente, arribos de Poisson y
     el renderizado POR GRUPOS, que es lo que hace viable el barrido.
  2. RÉPLICA VECTORIZADA del RTL, en los dos modos de ventana. Da los mismos
     eventos que `estimadores.segmentar_rtl` / `integral_gates` —eso es lo que
     verifica `test_pileup.py`— pero ~50x más rápido, porque el barrido completo
     son ~1.6e6 eventos y la réplica de referencia es un lazo muestra a muestra.
  3. CORTE POR FACTOR DE FORMA: calibración del lugar geométrico y la banda.
  4. MÉTRICAS de distorsión contra la verdad conocida.

LO QUE NO SE MODELA, Y POR QUÉ
------------------------------
  - Los 6 ciclos de S_DIV (el divisor de forma) durante los cuales un pulso
    nuevo se pierde y se cuenta en `cnt_lost_busy`. Son 48 ns contra ventanas de
    ~700 muestras: a 500 kcps afecta al 2.4e-5 de los eventos.
  - (Ya no.) El seguidor IIR de línea de base está modelado en
    `segmentar_base`, fiel al RTL. Lo que sigue con base fija es el barrido de
    `montecarlo.py`, por costo: `segmentar_rapido` es vectorizado y
    `segmentar_base` es un lazo muestra a muestra. El estudio del seguidor está
    en `linea_base.py`.
  - Una diferencia de orden entre `estimadores.segmentar_rtl` y el RTL, que se
    hereda a propósito para que la equivalencia sea exacta: si en la MISMA
    muestra se cumplen `len >= maxlen` y `x < thr_lo`, el RTL lo cuenta como
    apilamiento (`close_maxl` gana en la línea 343) y la réplica lo cierra por
    histéresis. Es un caso de medida nula.
"""

import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))

_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import rigol_dg4162 as rg                                     # noqa: E402
from rigol_dg4162 import detector_pulse, _fwhm_pts            # noqa: E402


# =============================================================================
# Constantes: todo lo que sale de una medición se marca con su fuente
# =============================================================================

FS_HZ         = 125e6    # reloj del ADC, 8 ns por muestra
ADC_CNT_PER_V = 8192     # cuentas por volt (jumper LV, +-1 V)

FWHM_S        = 2e-6     # ancho del pulso de la campaña (testbench_mca.PULSE_WIDTH_S)
TAU_COLA      = 186.0    # muestras; cola medida sobre 7054 pulsos reales
SIGMA_RUIDO   = 2.8      # cuentas; ruido medido de la cadena

# Configuración del MCA. Los dos modos de ventana que existen en el RTL.
CFG_MODO0 = dict(thr=100, hyst=40, maxlen=4096, tail_dly=8)
CFG_MODO1 = dict(thr=100, hyst=40, corta=32, larga=384)

# Estimador de amplitud por modo, como en el RTL (`cfg_amp_src`):
#   modo 0 -> muestra de PICO      (0.272 % offline, 0.344 % en placa)
#   modo 1 -> INTEGRAL de carga    (0.149 % offline, el mejor medido)
# q_tot >> Q_SHIFT tiene que entrar en los 16 bits de `amp_sel` en TODO el rango
# donde se calibra, no sólo donde vive la fuente: la compuerta de 384 muestras
# acumula ~244 veces la amplitud, así que con q_shift=4 un pulso de 4300 cuentas
# ya satura. El pulser de calibración barre hasta 7000 y la saturación le
# arruinaría el ajuste de ganancia (se midió: daba 8.3 en vez de 15.5).
Q_SHIFT = 5              # 244 * 8500 / 32 = 64 800 < 65 535

MOTIVOS = ('hyst', 'maxlen', 'fin_ventana', 'gate')
M_HYST, M_MAXLEN, M_FIN, M_GATE = 0, 1, 2, 3


# =============================================================================
# 1. Generación
# =============================================================================

def forma_referencia(fwhm_s=FWHM_S, tau_muestras=TAU_COLA, fs_hz=FS_HZ,
                     n_forma=2048, piso=0.5):
    """La forma semi-gaussiana de la campaña, muestreada a `fs_hz`.

    Es `detector_pulse` —(1 - e^{-t/t_rise}) e^{-t/tau}, normalizada al pico—,
    con DOS consignas simultáneas: el FWHM del estímulo (2 us) y la constante de
    cola medida sobre los pulsos reales (186 muestras). Eso deja un solo grado
    de libertad, `t_rise`, que se despeja numéricamente: la fórmula cerrada del
    FWHM no existe porque la normalización al pico acopla los dos parámetros.

    `n_forma` se recorta donde la cola cae por debajo de `piso` cuentas para la
    amplitud máxima esperada: más allá de eso el pulso no puede ni sostener la
    ventana abierta ni mover una carga. El recorte es lo que fija el hueco
    mínimo entre grupos (ver `agrupar`).

    Devuelve (forma, info).
    """
    fwhm_pts = fwhm_s * fs_hz
    tau = float(tau_muestras)

    # t_rise por bisección sobre el FWHM, que crece monótono con t_rise
    lo, hi = 1e-3, 10.0 * fwhm_pts
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        f = _fwhm_pts(detector_pulse(int(8 * fwhm_pts), t_rise=mid, tau=tau,
                                     amplitude=1.0, t0=0.0))
        if f < fwhm_pts:
            lo = mid
        else:
            hi = mid
    t_rise = 0.5 * (lo + hi)

    forma = detector_pulse(int(n_forma), t_rise=t_rise, tau=tau,
                           amplitude=1.0, t0=0.0)
    info = dict(t_rise=float(t_rise), tau=tau,
                fwhm_pts=float(_fwhm_pts(forma)),
                i_pico=int(np.argmax(forma)),
                area_pico=float(forma.sum()),
                n=int(forma.size), fs_hz=float(fs_hz))
    return forma, info


def forma_knoll(familia, fwhm_s=FWHM_S, fs_hz=FS_HZ, piso=1e-5, **kw):
    """Una familia del catálogo de Knoll, muestreada a la tasa del ADC.

    La contraparte de `forma_referencia` para las formas de amplificador de
    conformado (`rigol_dg4162.FORMAS_KNOLL`): CR, CR-RC, CR-RC^n, triangular,
    trapezoidal, bipolar. Sirve para preguntar cuánto de lo que concluye el
    estudio de apilamiento depende de la forma del pulso.

    Toda forma del catálogo es f(t/escala), así que el FWHM es LINEAL en la
    escala y se despeja con un solo sondeo sobre-muestreado: es exactamente lo
    que hace `_escala_para_fwhm`, y se reusa en vez de reimplementarlo para que
    la forma de acá y la que la campaña le cargó al Rigol sean la misma.

    El template se corta donde la cola cae por debajo de `piso` relativo al
    pico. Ese largo es el que fija el hueco mínimo entre grupos (ver `agrupar`).

    Devuelve (forma, info), con la misma convención que `forma_referencia`.
    """
    f = rg.FORMAS_KNOLL[familia] if isinstance(familia, str) else familia
    fwhm_pts = float(fwhm_s) * float(fs_hz)          # FWHM en muestras del ADC
    escala = rg._escala_para_fwhm(f, fwhm_pts, **kw)

    # Largo del template: se sondea la cola hasta que baja de `piso`. Se hace
    # sobre la forma continua y no sobre la muestreada para no atarlo a la
    # grilla del ADC.
    u = np.arange(0.0, 400.0, 1.0 / 64.0)
    y = np.asarray(f(u, **kw), dtype=float)
    pk = float(np.abs(y).max())
    i_pk = int(np.argmax(np.abs(y)))
    cola = np.flatnonzero(np.abs(y[i_pk:]) < piso * pk)
    u_max = float(u[i_pk + int(cola[0])]) if cola.size else float(u[-1])

    n = int(np.ceil(u_max * escala)) + 1
    forma = np.asarray(f(np.arange(n, dtype=float) / escala, **kw), dtype=float)
    forma = forma / float(forma.max())               # normalizada al PICO

    pos = forma[forma > 0].sum()
    info = dict(familia=familia if isinstance(familia, str) else 'callable',
                escala=float(escala), fwhm_pts=float(_fwhm_pts(forma)),
                i_pico=int(np.argmax(forma)), area_pico=float(pos),
                factor_forma=float(pos / _fwhm_pts(forma)),
                n=int(forma.size), fs_hz=float(fs_hz))
    return forma, info


# Espectro realista: dos líneas gaussianas, un continuo y una cola bajo umbral.
# Son los MISMOS parámetros de docs/mca/figuras/animacion_cadena_mca.py, para
# que el espectro de este trabajo y el de las figuras del informe sean el mismo.
LINEAS   = ((1250, 105, 0.42), (2620, 130, 0.33))   # (centro, sigma, peso)
W_CONT   = 0.15                                      # peso del continuo
CONTINUO = (400, 2900)
SUBUMBRAL = (90, 255)
A_CLIP   = (60, 4000)


def sortear_amplitudes(n, modelo='linea', rng=None, centro=1920.0,
                       res_pct=3.0):
    """Amplitudes verdaderas de los eventos, en cuentas de ADC.

    `modelo='linea'`   : una línea monoenergética de `res_pct` % de FWHM. Deja
                         la física del apilamiento desnuda: todo lo que aparezca
                         entre E y 2E, y el pico suma en 2E, es apilamiento.
    `modelo='realista'`: dos líneas + continuo + una población BAJO EL UMBRAL.
                         Los eventos bajo umbral importan: solos no cuentan,
                         pero apilados sobre uno bueno lo corren igual.
    """
    rng = np.random.default_rng() if rng is None else rng
    n = int(n)
    if modelo == 'linea':
        sigma = centro * (res_pct / 100.0) / (2.0 * np.sqrt(2.0 * np.log(2.0)))
        a = rng.normal(centro, sigma, n)
    elif modelo == 'realista':
        u = rng.random(n)
        a = np.empty(n)
        acc = 0.0
        pend = np.ones(n, dtype=bool)
        for c, s, w in LINEAS:
            m = pend & (u < acc + w)
            a[m] = rng.normal(c, s, int(m.sum()))
            pend &= ~m
            acc += w
        m = pend & (u < acc + W_CONT)
        a[m] = rng.uniform(*CONTINUO, int(m.sum()))
        pend &= ~m
        a[pend] = rng.uniform(*SUBUMBRAL, int(pend.sum()))
    else:
        raise ValueError(f'modelo desconocido: {modelo!r}')
    return np.clip(a, *A_CLIP)


def arribos_poisson(n_ev, tasa_hz, fs_hz=FS_HZ, rng=None):
    """Instantes de llegada, en MUESTRAS, de un proceso de Poisson de tasa `tasa_hz`.

    Intervalos exponenciales acumulados. Se redondea a la grilla del ADC al
    final y no antes, para no sesgar los intervalos cortos —que son justo los
    que producen el apilamiento.
    """
    rng = np.random.default_rng() if rng is None else rng
    dt = rng.exponential(fs_hz / float(tasa_hz), int(n_ev))
    return np.round(np.cumsum(dt)).astype(np.int64)


MAX_EV_GRUPO = 1500      # tope de arribos por llamada a `render` (ver abajo)


def agrupar(t_idx, hueco, max_ev=MAX_EV_GRUPO):
    """Corta la lista de arribos donde el hueco supera `hueco` muestras.

    Es lo que hace viable el barrido. A 125 MSPS un segundo son 1.25e8 muestras,
    y 50 000 eventos a 1 kcps serían 6e9: imposible. Pero entre pulsos separados
    por más que el largo del template no pasa NADA, así que cada grupo se
    renderiza en su propio array chico. El costo pasa a escalar con la cantidad
    de EVENTOS y no con el tiempo transcurrido: 1 kcps y 500 kcps cuestan lo
    mismo, y a tasa alta los grupos se funden —que es, precisamente, apilarse—.

    `max_ev` ACOTA LA MEMORIA, y no es opcional. A tasa alta el hueco medio cae
    por debajo del template y los 50 000 arribos terminan en UN SOLO grupo: la
    traza son ~1.25e7 muestras y, entre el ruido en float64 y las copias del
    redondeo, se va a varios GB. (Pasó: la primera corrida del barrido completo
    se llevó puesta la sesión entera.) Cortando de a `max_ev` la traza queda
    acotada por `max_ev * hueco` y el pico de memoria en decenas de MB.

    El corte se pone en el hueco MÁS GRANDE cerca del límite nominal, que es
    donde menos señal hay que partir. El evento que quede a caballo del corte no
    llega a cerrar su ventana y sale marcado `fin_ventana`, así que el llamador
    lo descarta por `cerrado`: se pierde ~1 evento por corte, del orden del
    0.02 % con los valores de acá.

    Devuelve un array de (n_grupos, 2) con los índices [a, b) de cada grupo.
    """
    t_idx = np.asarray(t_idx)
    if t_idx.size == 0:
        return np.zeros((0, 2), dtype=np.int64)
    corte = np.flatnonzero(np.diff(t_idx) > int(hueco)) + 1
    bordes = np.concatenate(([0], corte, [t_idx.size]))

    if max_ev:
        finos = [0]
        for a, b in zip(bordes[:-1], bordes[1:]):
            n = int(b - a)
            if n <= int(max_ev):
                finos.append(int(b))
                continue
            p = int(np.ceil(n / float(max_ev)))          # piezas
            for k in range(1, p):
                nom = a + int(round(k * n / p))
                lo = max(a + 1, nom - n // (4 * p))
                hi = min(b - 1, nom + n // (4 * p))
                if hi <= lo:
                    finos.append(int(nom))
                    continue
                g = np.diff(t_idx[lo - 1:hi])            # huecos del entorno
                finos.append(int(lo + int(np.argmax(g))))
            finos.append(int(b))
        bordes = np.unique(np.array(finos, dtype=np.int64))

    return np.stack([bordes[:-1], bordes[1:]], axis=1).astype(np.int64)


SAT_ADC = (1 << 13) - 1          # ADC de 14 bits con signo: +8191 cuentas


def render(t_idx, amps, forma, sigma_ruido=SIGMA_RUIDO, lead=64, trail=None,
           rng=None, sat=SAT_ADC):
    """Traza de un grupo de arribos: ruido de base + las formas superpuestas.

    Devuelve (traza int64 redondeada y saturada como el ADC, offset global del
    índice 0). `trail` tiene que alcanzar para que la última ventana pueda
    CERRAR; por defecto el largo del template, que es donde la cola ya no
    sostiene el umbral.

    La saturación a 14 bits con signo no es un detalle: cuando dos pulsos de la
    línea se suman, el resultado se va a 3840 cuentas y todavía entra, pero con
    tres o con amplitudes altas el ADC recorta, y un evento recortado pierde
    pico sin perder carga. Sin este clamp el Monte-Carlo sería optimista
    justamente en la cola del espectro que estamos midiendo.
    """
    rng = np.random.default_rng() if rng is None else rng
    trail = forma.size if trail is None else int(trail)
    t_idx = np.asarray(t_idx, dtype=np.int64)
    o = int(t_idx[0]) - int(lead)
    n = int(t_idx[-1]) - o + forma.size + trail
    y = rng.normal(0.0, float(sigma_ruido), n)
    for tk, ak in zip(t_idx, amps):
        i = int(tk) - o
        y[i:i + forma.size] += float(ak) * forma
    # in-place: `np.clip(np.rint(y), ...)` deja dos float64 del largo de la
    # traza vivos a la vez, y con trazas largas eso es lo que hace la diferencia
    np.rint(y, out=y)
    np.clip(y, -int(sat) - 1, int(sat), out=y)
    return y.astype(np.int64), o


def render_aislados(amps, forma, sigma_ruido=SIGMA_RUIDO, lead=64, trail=256,
                    rng=None):
    """Traza con los pulsos separados lo suficiente para que NO se apilen nunca.

    Es el MCA a tasa cero: mismo ruido, mismo umbral, mismo estimador, cero
    apilamiento. Sirve para dos cosas a la vez, y por eso vale la pena tenerla
    aparte del render de Poisson:

      - es el espectro de REFERENCIA, el que aísla la distorsión por apilamiento
        de todo lo demás (ruido, umbral, sesgo del estimador);
      - da el apareo 1:1 entre evento medido y amplitud verdadera, que es lo que
        permite calibrar la ganancia del estimador y el lugar geométrico del
        factor de forma sin tener que adivinar qué evento vino de qué pulso.

    La separación es `forma.size + trail`, o sea más que el template entero: dos
    pulsos consecutivos no se tocan ni por la cola. `trail` sólo tiene que
    alcanzar para que la ÚLTIMA ventana cierre, y la ventana de un pulso de la
    línea se cierra en ~780 muestras, muy adentro del template.

    OJO con el largo: son `len(amps) * (forma.size + trail)` muestras en UN
    array. Con 50 000 pulsos eso es 1.2e8 muestras y no entra en memoria; el
    llamador tiene que procesar por tandas (`montecarlo.corrida_aislada` lo hace).

    Devuelve (traza, t_idx) con un arribo cada `forma.size + trail` muestras.
    """
    trail = forma.size if trail is None else int(trail)
    paso = forma.size + trail
    t_idx = int(lead) + paso * np.arange(len(amps), dtype=np.int64)
    y, o = render(t_idx, amps, forma, sigma_ruido, lead=lead, trail=trail,
                  rng=rng)
    return y, t_idx - o


# =============================================================================
# 2. Réplica vectorizada del RTL
#
# La semántica es la de mca_pulse_feature.sv y la referencia es
# estimadores.segmentar_rtl / integral_gates. Acá NO se decide nada nuevo: se
# reproduce lo mismo con índices de cruce en vez de un lazo muestra a muestra.
# =============================================================================

def _ventanas_modo0(x, thr, hyst, maxlen):
    """Bordes de ventana del modo histéresis. Lazo sobre CRUCES, no sobre muestras.

    El Schmitt es secuencial, pero sus transiciones sólo dependen de dónde están
    los cruces de `thr_hi` y `thr_lo`, y esos son O(eventos), no O(muestras).
    Cada transición es un `searchsorted`.
    """
    thr_hi, thr_lo = int(thr), int(thr) - int(hyst)
    idx_hi = np.flatnonzero(x >= thr_hi)
    idx_lo = np.flatnonzero(x < thr_lo)
    n = x.size

    i0s, largos, motivos = [], [], []
    armed = False
    pos = 0
    while True:
        if not armed:
            k = np.searchsorted(idx_lo, pos)
            if k >= idx_lo.size:
                break
            pos = int(idx_lo[k]) + 1      # esa muestra arma; no puede abrir
            armed = True
        j = np.searchsorted(idx_hi, pos)
        if j >= idx_hi.size:
            break
        i0 = int(idx_hi[j])
        armed = False

        m = np.searchsorted(idx_lo, i0 + 1)
        ic = int(idx_lo[m]) if m < idx_lo.size else n     # cierre por histéresis
        lim = i0 + int(maxlen)                            # cierre por maxlen

        if ic <= lim:
            if ic < n:
                largos.append(ic - i0); motivos.append(M_HYST)
                pos, armed = ic + 1, True
            else:
                largos.append(n - i0); motivos.append(M_FIN)
                pos = n
        elif lim < n:
            largos.append(int(maxlen)); motivos.append(M_MAXLEN)
            pos, armed = lim + 1, False
        else:
            largos.append(n - i0); motivos.append(M_FIN)
            pos = n
        i0s.append(i0)
        if pos >= n:
            break

    return (np.array(i0s, dtype=np.int64), np.array(largos, dtype=np.int64),
            np.array(motivos, dtype=np.int8))


def _rangos(i0s, largos):
    """Índices planos de todas las ventanas concatenadas, sin lazo Python."""
    tot = int(largos.sum())
    ini = np.concatenate(([0], np.cumsum(largos)[:-1])).astype(np.int64)
    idx = np.repeat(i0s - ini, largos) + np.arange(tot, dtype=np.int64)
    return idx, ini


def _rasgos(xc, i0s, largos, tail_dly=None, corta=None):
    """q_tot, q_tail, pico y t_pico de cada ventana, todo vectorizado.

    El único punto fino es `q_tail` en el modo 0: el RTL compara contra el pico
    CORRIENTE (`len >= t_peak + tail_dly` con `t_peak` acumulado hasta la muestra
    anterior), no contra el pico final. Con ruido eso no es lo mismo —un máximo
    local puede abrir la cola y después ser superado— así que hay que reproducir
    el máximo corriente POR VENTANA. Se hace con un truco: se le suma a cada
    ventana un desplazamiento creciente mayor que cualquier valor, así un
    `np.maximum.accumulate` global no puede filtrar de una ventana a la
    siguiente, y después se resta.
    """
    if i0s.size == 0:
        z = np.zeros(0, dtype=np.int64)
        return z, z, z, z
    idx, ini = _rangos(i0s, largos)
    xg = xc[idx]
    off = np.repeat(np.arange(i0s.size, dtype=np.int64), largos)   # id de ventana
    local = np.arange(xg.size, dtype=np.int64) - np.repeat(ini, largos)

    q_tot = np.add.reduceat(xg, ini)
    pico  = np.maximum.reduceat(xg, ini)

    # t_pico: PRIMERA ocurrencia del máximo (el RTL compara con `>` estricto)
    es_max = xg == np.repeat(pico, largos)
    t_pico = np.minimum.reduceat(np.where(es_max, local, np.int64(1) << 40),
                                 ini)

    if corta is not None:                      # modo 1: cola desde el DISPARO
        cola = local >= int(corta)
    else:                                      # modo 0: cola desde el pico CORRIENTE
        gr = int(xg.max()) + 1
        run = np.maximum.accumulate(xg + off * gr) - off * gr      # máx corriente
        prev = np.concatenate(([-1], run[:-1]))
        prev[ini] = -1                                             # arranque de ventana
        rec = xg > prev                                            # nuevo récord estricto
        gl = int(largos.max()) + 1
        pos_rec = np.where(rec, local, np.int64(-1))
        t_run = np.maximum.accumulate(pos_rec + off * gl) - off * gl
        t_prev = np.concatenate(([0], t_run[:-1]))
        t_prev[ini] = 0
        cola = (local >= t_prev + int(tail_dly)) & (local > 0)

    q_tail = np.add.reduceat(np.where(cola, xg, 0), ini)
    return q_tot, q_tail, pico, t_pico


def segmentar_rapido(dat, baseline=0, thr=100, hyst=40, maxlen=4096,
                     tail_dly=8):
    """Modo 0 (ventana por histéresis). Equivale a `estimadores.segmentar_rtl`.

    Devuelve un dict de arrays paralelos, uno por evento.
    """
    x  = np.asarray(dat, dtype=np.int64) - int(baseline)
    xc = np.maximum(x, 0)
    i0s, largos, motivos = _ventanas_modo0(x, thr, hyst, maxlen)
    q_tot, q_tail, pico, t_pico = _rasgos(xc, i0s, largos, tail_dly=tail_dly)
    return dict(i0=i0s, largo=largos, motivo=motivos, q_tot=q_tot,
                q_tail=q_tail, pico=pico, t_pico=t_pico,
                cerrado=motivos != M_FIN,
                apilado=motivos == M_MAXLEN)


def compuertas_rapido(dat, baseline=0, thr=100, hyst=40, corta=32, larga=384):
    """Modo 1 (compuertas de largo fijo). Equivale a `estimadores.integral_gates`.

    Agrega lo que `integral_gates` no calcula: la bandera de APILAMIENTO del
    RTL (`gate_2nd`, mca_pulse_feature.sv:200-202). Un segundo pulso adentro de
    la compuerta se detecta en dos pasos —la señal tiene que BAJAR de thr_lo y
    recién después volver a cruzar thr_hi—, porque sin el paso intermedio la
    propia subida del pulso en curso la dispararía. La regla ingenua ("si al
    cerrar sigue alta, hay apilamiento") se probó en la placa y descartaba el
    100 % de los eventos: la cola del propio pulso tarda ~700 muestras en bajar.
    """
    x  = np.asarray(dat, dtype=np.int64) - int(baseline)
    xc = np.maximum(x, 0)
    thr_hi, thr_lo = int(thr), int(thr) - int(hyst)
    idx_hi = np.flatnonzero(x >= thr_hi)
    idx_lo = np.flatnonzero(x < thr_lo)
    n, larga = x.size, int(larga)

    i0s = []
    armed, pos = False, 0
    while True:
        if not armed:
            k = np.searchsorted(idx_lo, pos)
            if k >= idx_lo.size:
                break
            pos = int(idx_lo[k]) + 1
            armed = True
        j = np.searchsorted(idx_hi, pos)
        if j >= idx_hi.size:
            break
        i0 = int(idx_hi[j])
        i0s.append(i0)
        pos, armed = min(i0 + larga, n), False
        if pos >= n:
            break

    i0s = np.array(i0s, dtype=np.int64)
    truncado = (i0s + larga) > n
    largos = np.minimum(larga, n - i0s)
    q_tot, q_tail, pico, t_pico = _rasgos(xc, i0s, largos, corta=corta)

    # gate_2nd: primer cruce de thr_hi POSTERIOR al primer descenso bajo thr_lo,
    # los dos dentro de las muestras i0+1 .. i0+largo-1 (la que cierra no cuenta:
    # el RTL las evalúa en la rama que NO cierra).
    apilado = np.zeros(i0s.size, dtype=bool)
    if i0s.size:
        fin = i0s + largos - 1
        k = np.searchsorted(idx_lo, i0s + 1)
        hay_lo = k < idx_lo.size
        i_lo = np.where(hay_lo, idx_lo[np.minimum(k, idx_lo.size - 1)], n)
        hay_lo &= i_lo <= fin
        j = np.searchsorted(idx_hi, i_lo + 1)
        hay_hi = j < idx_hi.size
        i_hi = np.where(hay_hi, idx_hi[np.minimum(j, idx_hi.size - 1)], n)
        apilado = hay_lo & hay_hi & (i_hi <= fin)

    return dict(i0=i0s, largo=largos, q_tot=q_tot, q_tail=q_tail, pico=pico,
                t_pico=t_pico, truncado=truncado, apilado=apilado,
                cerrado=~truncado,
                motivo=np.where(truncado, M_FIN, M_GATE).astype(np.int8))


def contar_arribos(ev, loc):
    """Cuántos pulsos VERDADEROS entró cada evento. Sólo existe en el Monte-Carlo.

    Es la definición operativa de apilamiento y la única forma de medir la
    eficiencia de un corte: `contar == 1` es un evento limpio, `> 1` es uno
    apilado. En la placa este número no se puede conocer, que es exactamente por
    lo que hace falta simular.

    Se reparte el eje: al evento k le tocan los arribos entre el final de la
    ventana anterior y el final de la suya. Así todo arribo cae en exactamente
    un evento —incluido el que lo disparó, que ocurre ANTES de `i0` porque el
    pulso tarda en llegar al umbral—, y ninguno se cuenta dos veces.
    """
    fin = np.asarray(ev['i0'], dtype=np.int64) + np.asarray(ev['largo'],
                                                            dtype=np.int64)
    bordes = np.concatenate(([0], fin))
    return np.diff(np.searchsorted(np.asarray(loc, dtype=np.int64), bordes))


def avanzar_base(bl_acc, dc, n, k):
    """Adelanta el acumulador del IIR `n` muestras de señal quieta en `dc`.

    HACE FALTA porque el renderizado por grupos NO materializa el tiempo muerto
    entre pulsos —ese es justamente el truco que hace viable el barrido— pero el
    seguidor sí corre durante ese tiempo y converge. Saltearlo dejaría la base
    enganchada al último grupo.

    En reposo el IIR es lineal, así que el salto tiene forma cerrada:

        bl_acc(n) = (1 - 2^-k)^n * (bl_acc(0) - dc*2^k) + dc*2^k

    Es exacto en valor esperado; lo que se pierde es el ruido de la base, que
    promedia a cero sobre las miles de muestras de un hueco. Y donde la
    aproximación sería peor —tasa alta— los huecos directamente no existen,
    porque los grupos se funden.
    """
    n = int(n)
    if n <= 0:
        return int(bl_acc)
    objetivo = float(dc) * (1 << int(k))
    decae = (1.0 - 2.0 ** -int(k)) ** n
    return int(round(decae * (float(bl_acc) - objetivo) + objetivo))


def segmentar_base(dat, bl_auto=True, baseline=0, bl_k=12, bl_holdoff=64,
                   thr=100, hyst=40, maxlen=4096, tail_dly=8, bl_acc0=None,
                   traza_base=False):
    """Modo 0 CON el seguidor IIR de línea de base. Lazo muestra a muestra.

    NO se puede vectorizar como `segmentar_rapido`, y no es por falta de ganas:
    la base depende del estado de la segmentación (se congela durante el pulso)
    y el estado depende de la base (`x = dat - baseline` decide los cruces). El
    lazo corre a ~3.8 Mmuestras/s, que alcanza para el estudio.

    Con `bl_auto=False` tiene que dar EXACTAMENTE los mismos eventos que
    `segmentar_rapido(dat, baseline=...)`. Eso es lo que la ancla a la cadena ya
    validada contra `tb_mca_pulse_feature.sv` y contra la placa, y es un test.

    Temporización de registros, copiada de mca_pulse_feature.sv:110-138 y
    :285-301. Los tres detalles no son cosméticos:

      - el shift va UN ciclo atrasado (`:119-127`): se lo sacó del lazo del IIR
        para dejarlo en una sola suma, así que
        `bl_acc(n) = bl_acc(n-1) + dat(n) - (bl_acc(n-2) >> k)`;
      - `baseline` TAMBIÉN está registrada (`:128-138`), o sea dos ciclos detrás
        de `bl_acc`. Se hizo porque el camino combinacional era el peor de todo
        el MCA (-0.674 ns a 125 MHz);
      - la condición de actualización lleva `!open_pulse` (`:288-292`): en el
        flanco en que abre el pulso `st` todavía vale S_IDLE, y sin esa guarda
        el IIR se come la primera muestra del flanco de subida de CADA pulso y
        arrastra la base hacia arriba de forma sistemática. Ese bug ya apareció
        una vez en la placa; acá se modela la versión corregida.

    Devuelve el mismo dict que `segmentar_rapido`, más:
        bl_acc_fin  : el acumulador al terminar, para encadenar grupos
        frac_congelada : fracción de muestras en que el IIR no actualizó. Es la
                         variable explicativa del estudio: a tasa alta el
                         seguidor está congelado casi siempre y deja de seguir.
        base        : la traza de la base (sólo si `traza_base=True`)
        congelada   : máscara de las muestras en que el IIR no actualizó
    """
    dat = np.asarray(dat, dtype=np.int64)
    k = int(bl_k)
    thr_hi, thr_lo = int(thr), int(thr) - int(hyst)

    # --- registros del seguidor -------------------------------------------
    if bl_acc0 is None:
        bl_acc0 = int(baseline) << k          # arranca convergido, no en cero
    bl_acc = int(bl_acc0)
    bl_shr = bl_acc >> k                      # bl_acc_shr
    base_r = int(baseline) if not bl_auto else bl_shr   # baseline registrada
    bl_hold = 0

    # --- registros de la FSM ----------------------------------------------
    armed = False
    activo = False
    i0 = largo = q_tot = q_tail = pico = t_pico = 0

    i0s, largos, motivos = [], [], []
    q_tots, q_tails, picos, t_picos = [], [], [], []
    n_congeladas = 0
    base_tr = np.empty(dat.size, dtype=np.int64) if traza_base else None
    cong_tr = np.zeros(dat.size, dtype=bool) if traza_base else None

    for i in range(dat.size):
        d = int(dat[i])
        x = d - base_r
        xc = x if x > 0 else 0
        if traza_base:
            base_tr[i] = base_r

        # `st` ANTES del flanco: es lo que mira la condición del seguidor, y no
        # es lo mismo que `activo` después de correr la FSM de este ciclo.
        en_reposo = not activo
        carga_hold = False

        # ---- FSM (idéntica a segmentar_rapido / mca_pulse_feature) --------
        abre = False
        if not activo:
            if x < thr_lo:
                armed = True
            if armed and x >= thr_hi:
                abre = True
                activo, armed = True, False
                i0, largo = i, 1
                q_tot, q_tail = xc, 0
                pico, t_pico = xc, 0
        else:
            if x < thr_lo:                    # cierra por histéresis
                i0s.append(i0); largos.append(largo); motivos.append(M_HYST)
                q_tots.append(q_tot); q_tails.append(q_tail)
                picos.append(pico); t_picos.append(t_pico)
                activo, armed = False, True
                carga_hold = True
            elif largo >= int(maxlen):        # cierra por longitud: apilamiento
                i0s.append(i0); largos.append(largo); motivos.append(M_MAXLEN)
                q_tots.append(q_tot); q_tails.append(q_tail)
                picos.append(pico); t_picos.append(t_pico)
                activo = False
                carga_hold = True
            else:
                if largo >= t_pico + int(tail_dly):
                    q_tail += xc
                q_tot += xc
                if xc > pico:
                    pico, t_pico = xc, largo
                largo += 1

        # ---- seguidor: sólo en reposo, sin abrir y fuera del holdoff ------
        if en_reposo and not abre and bl_hold == 0:
            bl_acc_n = bl_acc + d - bl_shr    # bl_shr va un ciclo atrasado
        else:
            bl_acc_n = bl_acc
            n_congeladas += 1
            if traza_base:
                cong_tr[i] = True
            if bl_hold:
                bl_hold -= 1

        # El `bl_hold <= cfg_bl_holdoff` de la FSM está DESPUÉS en el archivo
        # que el `bl_hold <= bl_hold - 1` del seguidor, así que en Verilog gana
        # la carga: en el ciclo que cierra el pulso el holdoff se carga entero,
        # no se carga y se decrementa. Por eso va acá y no en la rama de arriba.
        if carga_hold:
            bl_hold = int(bl_holdoff)

        # los tres registros avanzan juntos, cada uno con el valor pre-flanco
        base_r = bl_shr if bl_auto else int(baseline)
        bl_shr = bl_acc >> k
        bl_acc = bl_acc_n

    if activo:                                 # se acabó el array sin cerrar
        i0s.append(i0); largos.append(largo); motivos.append(M_FIN)
        q_tots.append(q_tot); q_tails.append(q_tail)
        picos.append(pico); t_picos.append(t_pico)

    mot = np.array(motivos, dtype=np.int8)
    out = dict(i0=np.array(i0s, dtype=np.int64),
               largo=np.array(largos, dtype=np.int64),
               motivo=mot,
               q_tot=np.array(q_tots, dtype=np.int64),
               q_tail=np.array(q_tails, dtype=np.int64),
               pico=np.array(picos, dtype=np.int64),
               t_pico=np.array(t_picos, dtype=np.int64),
               cerrado=mot != M_FIN,
               apilado=mot == M_MAXLEN,
               bl_acc_fin=int(bl_acc),
               frac_congelada=float(n_congeladas / max(dat.size, 1)))
    if traza_base:
        out['base'] = base_tr
        out['congelada'] = cong_tr
    return out


def psd(q_tail, q_tot, psd_aw=6):
    """Eje de forma del hardware, vectorizado y con las mismas guardas.

    `floor(q_tail * 2^PSD_AW / q_tot)`, con el divisor bloqueado cuando
    `q_tot == 0` o `q_tail >= q_tot` (mca_pulse_feature.sv:227). Devuelve
    (psd, ok); con ok=False el evento entra al espectro 1D pero no al mapa 2D.
    """
    q_tail = np.asarray(q_tail, dtype=np.int64)
    q_tot  = np.asarray(q_tot,  dtype=np.int64)
    ok = (q_tot != 0) & (q_tail < q_tot)
    den = np.where(ok, q_tot, 1)                  # evita la división por cero
    v = np.where(ok, (q_tail << int(psd_aw)) // den, 0)
    return v.astype(np.int64), ok


def amplitud(ev, modo, q_shift=Q_SHIFT):
    """Amplitud del evento como la calcula el RTL, según el modo.

    modo 0 -> muestra de PICO (`cfg_amp_src = 0`): es el mejor estimador con
              ventana por histéresis, 0.272 % offline contra 0.528 % de la
              integral, porque el largo de la ventana lo decide el ruido.
    modo 1 -> INTEGRAL `q_tot >> cfg_q_shift`: con la compuerta fija el largo ya
              no tiembla y la integral promedia el ruido, 0.149 %.
    Los dos saturan a 16 bits como `amp_sel`.
    """
    v = ev['pico'] if modo == 0 else (ev['q_tot'] >> int(q_shift))
    return np.minimum(v, (1 << 16) - 1).astype(np.int64)


# =============================================================================
# 3. Corte por factor de forma
# =============================================================================

def razon_forma(ev, cual, q_shift=Q_SHIFT):
    """El cociente que se usa para discriminar.

    'q_pico' : Q_total / pico. Es el que pide la física —el área sobre la altura
               es una constante de la FORMA, así que un pulso apilado, que suma
               carga sin subir el pico en la misma proporción, se sale—. El RTL
               NO lo calcula hoy: haría falta un divisor nuevo.
    'psd'    : Q_cola / Q_total, el eje que el RTL YA calcula y YA histograma en
               el mapa 2D. Evaluarlo es gratis y es lo que decide si hace falta
               hardware nuevo o alcanza con lo que hay.
    """
    if cual == 'q_pico':
        pico = np.maximum(ev['pico'], 1)
        return ev['q_tot'] / pico
    if cual == 'psd':
        v, ok = psd(ev['q_tail'], ev['q_tot'])
        return np.where(ok, v, np.nan).astype(float)
    raise ValueError(f'razón desconocida: {cual!r}')


def locus_forma(amp, razon, n_bins=24, min_por_bin=20):
    """Lugar geométrico del cociente contra la amplitud, medido a tasa cero.

    HACE FALTA porque el cociente NO es constante en el modo 0: la ventana por
    histéresis cierra cuando la cola cruza `thr - hyst`, o sea que su largo
    crece con el logaritmo de la amplitud, y Q/pico deriva ~+11 % entre 400 y
    3200 cuentas. Un umbral fijo cortaría los pulsos limpios chicos y dejaría
    pasar los apilados grandes. En el modo 1 el largo es fijo por construcción y
    el lugar geométrico sale plano —que se recupere plano es uno de los tests—.

    Devuelve (centros, mediana, sigma) interpolables. Se usa mediana y MAD y no
    media y desvío porque la muestra de calibración puede tener contaminación
    residual, y una cola larga inflaría el sigma justo donde importa.
    """
    amp = np.asarray(amp, dtype=float)
    razon = np.asarray(razon, dtype=float)
    ok = np.isfinite(amp) & np.isfinite(razon)
    amp, razon = amp[ok], razon[ok]
    if amp.size < min_por_bin:
        raise ValueError('muy pocos eventos para calibrar el lugar geométrico')

    bordes = np.quantile(amp, np.linspace(0, 1, int(n_bins) + 1))
    bordes = np.unique(bordes)
    j = np.clip(np.digitize(amp, bordes[1:-1]), 0, len(bordes) - 2)

    centros, med, sig = [], [], []
    for b in range(len(bordes) - 1):
        m = j == b
        if m.sum() < min_por_bin:
            continue
        r = razon[m]
        mu = float(np.median(r))
        centros.append(float(np.median(amp[m])))
        med.append(mu)
        sig.append(1.4826 * float(np.median(np.abs(r - mu))))   # MAD -> sigma
    if len(centros) < 2:
        raise ValueError('no quedaron bins con estadística suficiente')

    sig = np.array(sig)
    sig[sig <= 0] = np.median(sig[sig > 0]) if np.any(sig > 0) else 1e-9
    return np.array(centros), np.array(med), sig


def aplicar_corte(amp, razon, locus, k=3.0, solo_arriba=True):
    """Máscara de eventos ACEPTADOS: |razón - mediana(amp)| <= k*sigma(amp).

    `solo_arriba=True` corta únicamente por exceso del cociente, que es hacia
    donde mueve el apilamiento (más carga para el mismo pico). Cortar también
    por debajo sólo agrega pérdida de eficiencia sin sacar apilamiento.
    """
    centros, med, sig = locus
    amp = np.asarray(amp, dtype=float)
    razon = np.asarray(razon, dtype=float)
    mu = np.interp(amp, centros, med)
    s  = np.interp(amp, centros, sig)
    d = razon - mu
    ok = d <= k * s if solo_arriba else np.abs(d) <= k * s
    return ok & np.isfinite(razon)


# =============================================================================
# 4. Histogramas y métricas
# =============================================================================

def calibrar(amp_ref, a_verdadera):
    """Ganancia y offset del estimador, por cuadrados mínimos sobre pares 1:1.

    Los dos modos usan estimadores distintos (pico contra integral >> q_shift),
    así que sus amplitudes viven en escalas distintas. Calibrando contra la
    amplitud verdadera los tres espectros —verdad, referencia y medido— caen
    sobre EL MISMO eje y se pueden restar. Sin esto la comparación sería entre
    ejes incompatibles.
    """
    amp_ref = np.asarray(amp_ref, dtype=float)
    a_verdadera = np.asarray(a_verdadera, dtype=float)
    # Los eventos que tocaron el techo de 16 bits de `amp_sel` no informan sobre
    # la ganancia: su amplitud ya no depende de la del pulso. Incluirlos aplana
    # el ajuste. Lo mismo con los que tocaron la saturación del ADC.
    m = (np.isfinite(amp_ref) & np.isfinite(a_verdadera)
         & (amp_ref < (1 << 16) - 1) & (a_verdadera < SAT_ADC))
    if m.sum() < 2:
        raise ValueError('no quedaron eventos sin saturar para calibrar')
    a, b = np.polyfit(a_verdadera[m], amp_ref[m], 1)
    return float(a), float(b)


def a_canal(amp, cal, h_shift=0, n_canales=8192):
    """Amplitud del estimador -> canal, en unidades de amplitud VERDADERA.

    El binado es el del RTL: un corrimiento a la derecha del entero, con
    saturación en el bin superior (nunca envuelve, mca_top.sv:163-167).
    """
    a, b = cal
    v = np.rint((np.asarray(amp, dtype=float) - b) / a).astype(np.int64)
    v = np.maximum(v, 0) >> int(h_shift)
    return np.minimum(v, int(n_canales) - 1)


def histograma(canales, n_canales=8192):
    return np.bincount(np.asarray(canales, dtype=np.int64),
                       minlength=int(n_canales))[:int(n_canales)]


def rebin(h, factor):
    """Agrupa canales de a `factor`. Descarta la cola que no completa un bin."""
    h = np.asarray(h)
    n = (h.size // int(factor)) * int(factor)
    return h[:n].reshape(-1, int(factor)).sum(axis=1)


def metricas(h_med, h_ref, canal_pico, semi_ancho, tope, rebin_l1=64):
    """Distorsión de un espectro medido contra el de referencia (tasa cero).

    - `area_rel`   : cuentas en el fotopico sobre las de la referencia. Es la
                     SUPERVIVENCIA del fotopico e incluye la pérdida por tiempo
                     muerto, que a tasa alta es el término dominante.
    - `corrimiento`: desplazamiento del centroide, en canales.
    - `fwhm_rel`   : ensanchamiento del pico.
    - `continuo`   : cuentas por encima de `tope` —el punto final de la fuente—
                     sobre el total. Es apilamiento PURO y no necesita ningún
                     ajuste para verse: ahí la fuente no puede poner nada.
    - `l1`         : distancia L1 entre los dos espectros NORMALIZADOS. Resume
                     la deformación de forma en un número, sin el factor de
                     throughput, e incluye lo que no cae ni en el pico ni por
                     encima del tope.

    El L1 se calcula sobre el espectro REAGRUPADO de a `rebin_l1` canales. Con
    16384 canales y decenas de miles de eventos la mayoría de los canales tiene
    una o ninguna cuenta, y el L1 crudo mide el ruido de Poisson del binado en
    vez de la deformación: con 4000 eventos da ~0.2 incluso comparando un
    espectro contra sí mismo. El reagrupado baja ese piso un orden de magnitud y
    deja pasar la forma, que es lo que se quiere medir.
    """
    sys.path.insert(0, _RAIZ)
    import mca_utils as mu

    lo, hi = int(canal_pico - semi_ancho), int(canal_pico + semi_ancho)
    f_med = mu.gauss_fit_peak(h_med, lo, hi)
    f_ref = mu.gauss_fit_peak(h_ref, lo, hi)

    n_med, n_ref = h_med.sum(), h_ref.sum()
    g_med, g_ref = rebin(h_med, rebin_l1), rebin(h_ref, rebin_l1)
    p_med = g_med / n_med if n_med else g_med.astype(float)
    p_ref = g_ref / n_ref if n_ref else g_ref.astype(float)

    return dict(
        area_rel=float(f_med['area'] / f_ref['area']) if f_ref['area'] else np.nan,
        corrimiento=float(f_med['centroid'] - f_ref['centroid']),
        fwhm_rel=float(f_med['fwhm'] / f_ref['fwhm']) if f_ref['fwhm'] else np.nan,
        continuo=float(h_med[int(tope):].sum() / n_med) if n_med else np.nan,
        l1=float(np.abs(p_med - p_ref).sum()),
        n=int(n_med),
        centroide=float(f_med['centroid']),
        fwhm=float(f_med['fwhm']),
    )


def frac_apilamiento_teo(tasa_hz, ancho_s):
    """1 - exp(-2*lambda*w): la fracción de eventos con un vecino a menos de w.

    Es la misma fórmula que ya reporta `poisson_train_wave` en su `info`, y sirve
    de contraste independiente para el Monte-Carlo.
    """
    return 1.0 - np.exp(-2.0 * np.asarray(tasa_hz, dtype=float) * float(ancho_s))


def tasa_no_paralizable(n, tau_s):
    """m = n / (1 + n*tau): el modelo de tiempo muerto no paralizable.

    Es el que ajustó la placa (tau = 0.37 us). Está en plot_modelos_tasa.py.
    """
    n = np.asarray(n, dtype=float)
    return n / (1.0 + n * float(tau_s))
