"""El canal analógico: lo que la parte analógica (el DAC, el cable, la carga, el
front-end y el ADC) le hace a la señal, medido con la BRAM del osciloscopio.

Lo usan la pestaña «Calibration» de la app (por `canal.medir` del servidor) y las
campañas en modo analógico (`campanas/canal_analogico.py` reexporta todo esto, y
`run_fidelidad_osc.py` toma de acá `casos_canal` y `capturar_canal`).

**Cómo se mide sin el modelo del generador.** Se captura dos veces el mismo estímulo con
la BRAM, disparada por la fuente ASG en el primer pulso: una con el lazo digital (`x`, la
señal del generador tal cual) y otra sin él (`y`, lo que vuelve por IN1, y por IN2 la
diafonía). El generador es determinista (`arrancar` reinicia todo) y el disparo es
digital, así que `x[n]` e `y[n]` son el mismo instante, y el canal es un FIR que se ajusta
por cuadrados mínimos, más unos pocos polos lentos:

    y[n] = b + Σ_j c_j · x[n − j] + Σ_i d_i · (p_i * x)[n] + ruido,   j = LAGS[0] … LAGS[1] − 1

con p_i un pasabajos de un polo de constante LENTOS[i] (en muestras, ganancia 1 en
continua). El FIR es la respuesta rápida (344 ns); los polos, la caída lenta que tiene la
salida cargada con 50 Ω (7 % entre 3 y 13 µs, medida en la placa el 2026-11-14), que el
FIR no alcanza y que con el apilamiento corre la base con la tasa.

Hay tres mediciones:

  rápida   (`capturar_canal` + `caracterizar`) a ritmo pleno, con la ruta del OSC en
           TAP_ADC (las cuentas crudas que ve el MCA): el piso, un estímulo de banda
           ancha y el FIR de 48 taps con los polos lentos. Una captura dura 65 µs, 1.3
           veces el polo más lento: la caída lenta sale poco determinada.
  lenta    (`capturar_lentos` + `caracterizar_lento`) con diezmado (`DEC_LENTO`) y
           promedio, así la BRAM cubre ~0.5 ms: cuasi-escalones del generador
           (τ = 524 µs, el DECAE máximo) capturados con el lazo una vez y sin él
           `promedios` veces. Va por la ruta NATIVA del OSC, porque TAP_ADC saltea el
           diezmado; la calibración del RTL escala x e y por igual, así que la caída
           relativa (Σd/Σc) no cambia. El diezmado no tiene la misma fase en dos
           capturas, así que los flancos quedan fuera del ajuste (`_mascara_flancos`):
           lo que se ajusta es la ganancia de corto plazo y la caída lenta.
  externa  (`capturar_externo` + `caracterizar_externo`) sin el generador: una
           cuadrada de afuera (el Rigol) en IN1, con disparo por software. El escalón
           ideal sale de la propia captura (`escalon_ideal`), así que no hace falta
           saber la amplitud ni la frecuencia. Da la caída lenta de IN1 SOLA: si con la
           cuadrada externa la caída no está, es de la salida OUT1 cargada.

Lo que sale de `caracterizar`:

  offset, ruido        media y desvío de IN1 sin pulsos: la base que ve el MCA y el piso
  densidad, espurias   la densidad de ruido (mediana, cuentas/√Hz) y las líneas que pasan
                       20 veces la mediana
  ganancia             Σ c: la de corto plazo (la que ve un pulso), cuentas de IN1 por
                       cuenta del generador
  ganancia_dc          Σ c + Σ d: la de continua de verdad
  caida_lenta          Σ d / Σ c: cuánto cambia la ganancia de corto plazo a la larga
  latencia             Σ j·c_j / Σ c: el retardo de grupo del FIR, en muestras
  lat_asg              cuántas muestras más tarde que en el lazo digital cruza el escalón
                       el 50 %: lo que hay que correr la ventana del MCA con el disparo del
                       ASG, que no mira la señal
  subida, sobrepico    10-90 % y sobrepico de la respuesta al escalón (Σ acumulada de c)
  bw_3db_mhz           donde |H(f)| cae 3 dB respecto de continua (None: no cae antes de
                       Nyquist)
  residuo_rms          el desvío de y − ajuste: si pasa del piso, el canal no es lineal o
                       no es estacionario
  diafonia_db          el mismo ajuste sobre IN2, relativo a IN1 (rms de la parte coherente)

`CapturaBram` es el procedimiento en la placa, sobre los handles abiertos del servidor:
arma la BRAM con el disparo del ASG (o por software), corre el generador y lee los dos
canales. Antes guarda, y al final restaura, todo lo que toca (`guardar`/`restaurar`).
"""
import math
import time

import numpy as np

FS_HZ = 125e6
AMP_MIN, AMP_MAX = -8192, 8191
LAGS = (-4, 44)          # 48 taps: de −4 (tienen que dar 0) a 43 muestras (344 ns)
LENTOS = (400, 1600, 6400)   # los polos lentos, en muestras (3.2, 12.8 y 51 µs)
MARGEN_SAT = 64          # cuentas de los rieles que no entran en el ajuste
RECUPERA = 8             # muestras a cada lado de un recorte que el residuo no mira
TOL_ALINEAL = 0.03       # el residuo tolera esta fracción de la señal (la alinealidad)
SEG_PSD = 1024           # muestras por segmento de la densidad de ruido (122 kHz)
ESPURIA_X = 20.0         # una espuria pasa esto por la mediana de la densidad
GANANCIA_NULA = 0.02     # por debajo, a IN1 no le llega OUT1
GANANCIA_MIN = 0.3       # por debajo, el canal no es el de la campaña (LV; ~0.5 con IN1
                         # terminado en 50 Ω sí sirve, ~0.05 es el jumper en HV)

PRE_CANAL = 256          # muestras del buffer antes del disparo en las capturas del canal
IDENTIDAD = {'gain': 32768, 'base': 32768, 'offset': 0}

# La medición lenta y la externa.
DEC_LENTO = 8            # diezmado: la BRAM de 8192 muestras cubre 524 µs
TAU_ESCALON = 65535.0    # muestras (524 µs): el DECAE máximo, 10 veces el polo más lento
ALTO_ESCALON = 3000      # cuentas del generador: con el sobrepico del canal no satura
PERIODO_ESCALON = 16384  # ciclos entre escalones (131 µs, 2.6 veces el polo más lento)
PROMEDIOS = 4            # capturas sin el lazo (o externas) que entran al ajuste
LAGS_LENTO = (0, 1)      # un solo tap: la ganancia de corto plazo, sin los flancos
ANTES_FLANCO = 2         # muestras diezmadas antes de un flanco que no entran
DESPUES_FLANCO = 12      # y después (96 ciclos: el FIR rápido y su sobrepico)
ESCALON_X = 1000.0       # la altura del escalón ideal de la referencia externa
ESCALON_MIN = 200.0      # cuentas: por debajo, en IN1 no hay una cuadrada
SUAVIZADO = 4            # muestras del promedio con que se busca el umbral


# =============================================================================
# El ajuste del FIR
# =============================================================================

def _invalidos(x, y, lags, margen=MARGEN_SAT):
    """Las muestras n que no entran en el ajuste: y[n] cerca de un riel, o algún
    x[n − j] del FIR cerca de un riel (el recorte del DAC o del ADC no es lineal)."""
    j0, j1 = lags
    xs = (np.abs(x) >= AMP_MAX - margen).astype(np.int64)
    ys = (y >= AMP_MAX - margen) | (y <= AMP_MIN + margen)
    # Σ_{j=j0}^{j1−1} xs[n − j] = conv(xs, 1_L)[n − j0], con L = j1 − j0.
    c = np.convolve(xs, np.ones(j1 - j0, np.int64))
    n = np.arange(x.size)
    k = n - j0
    malo_x = np.where((k >= 0) & (k < c.size), c[np.clip(k, 0, c.size - 1)], 1) > 0
    return ys | malo_x


def pasabajos(x, tau):
    """(p * x)[n]: un polo de constante `tau` muestras, ganancia 1 en continua, causal
    desde el principio de la traza (antes, el generador apagado: x = 0)."""
    from scipy.signal import lfilter
    a = math.exp(-1.0 / float(tau))
    return lfilter([1.0 - a], [1.0, -a], np.asarray(x, float))


def _filas(x, y, lags, margen, lentos, fuera=None):
    """Las filas del ajuste de un par (x, y): los taps y los polos lentos (sin la
    constante), los y y los índices n usados. `fuera` son muestras que no entran."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    if x.shape != y.shape:
        raise ValueError(f'x {x.shape} e y {y.shape}: las dos capturas, del mismo largo')
    j0, j1 = int(lags[0]), int(lags[1])
    js = np.arange(j0, j1)
    n = np.arange(max(j1 - 1, 0), x.size + min(j0, 0))
    malo = _invalidos(x, y, (j0, j1), margen)
    if fuera is not None:
        malo = malo | fuera
    n = n[~malo[n]]
    A = np.empty((n.size, js.size + len(lentos)))
    A[:, :js.size] = x[n[:, None] - js[None, :]]
    for i, tau in enumerate(lentos):
        A[:, js.size + i] = pasabajos(x, tau)[n]
    return A, y[n], n


def ajustar_fir(x, y, lags=LAGS, margen=MARGEN_SAT, lentos=LENTOS):
    """y ≈ b + c * x + Σ d_i (p_i * x) por cuadrados mínimos, sobre las muestras donde
    existen todos los taps y nada está cerca de un riel. Devuelve c (de lags[0] a
    lags[1] − 1), d (uno por polo de `lentos`), b, el residuo en las muestras usadas y su
    rms. Con `lentos` vacío es el FIR solo."""
    lentos = tuple(lentos)
    j0, j1 = int(lags[0]), int(lags[1])
    A0, yv, n = _filas(x, y, (j0, j1), margen, lentos)
    if n.size < 4 * (j1 - j0 + len(lentos)):
        raise ValueError(f'{n.size} muestras para {j1 - j0} taps: el estímulo satura')
    A = np.empty((n.size, 1 + A0.shape[1]))
    A[:, 0] = 1.0
    A[:, 1:] = A0
    sol, *_ = np.linalg.lstsq(A, yv, rcond=None)
    res = yv - A @ sol
    nt = j1 - j0
    return dict(c=sol[1:1 + nt], d=sol[1 + nt:], lentos=lentos, b=float(sol[0]),
                lags=(j0, j1), n=n, residuo=res, rms=float(res.std()))


def ajustar_pares(pares, lags=LAGS, margen=MARGEN_SAT, lentos=LENTOS, fueras=None,
                  inicial=False):
    """`ajustar_fir` sobre varios pares (x, y) a la vez: el mismo FIR y los mismos polos,
    con una constante por par (la base puede moverse entre capturas). `fueras`, una
    máscara por par de las muestras que no entran. `b` es la media de las constantes.

    Con `inicial`, además una columna e^{−n/τ_i} por polo y por par: el estado con que
    cada polo lento entra a la captura. Hace falta cuando la señal venía de antes (una
    cuadrada externa que corre desde siempre); con el generador, que arranca adentro de
    la captura, ese estado es cero."""
    lentos = tuple(lentos)
    j0, j1 = int(lags[0]), int(lags[1])
    if fueras is None:
        fueras = [None] * len(pares)
    bloques = [_filas(x, y, (j0, j1), margen, lentos, f)
               for (x, y), f in zip(pares, fueras)]
    m, nt, nl = len(bloques), j1 - j0, len(lentos)
    ni = nl if inicial else 0
    filas = sum(b[1].size for b in bloques)
    cols = m + nt + nl + m * ni
    if filas < 4 * cols:
        raise ValueError(f'{filas} muestras para {nt} taps y {nl} polos: el '
                         'estímulo satura o no hay escalones')
    A = np.zeros((filas, cols))
    Y = np.empty(filas)
    i = 0
    for k, (Ak, yk, nk) in enumerate(bloques):
        A[i:i + yk.size, k] = 1.0
        A[i:i + yk.size, m:m + nt + nl] = Ak
        for q, tau in enumerate(lentos[:ni]):
            A[i:i + yk.size, m + nt + nl + k * ni + q] = np.exp(-nk / float(tau))
        Y[i:i + yk.size] = yk
        i += yk.size
    sol, *_ = np.linalg.lstsq(A, Y, rcond=None)
    res = Y - A @ sol
    return dict(c=sol[m:m + nt], d=sol[m + nt:m + nt + nl], lentos=lentos,
                b=float(sol[:m].mean()), bs=[float(v) for v in sol[:m]], lags=(j0, j1),
                muestras=int(filas), residuo=res, rms=float(res.std()))


def predecir(x, c, b, lags=LAGS, d=(), lentos=()):
    """b + Σ_j c_j x[n − j] + Σ_i d_i (p_i * x)[n] para todo n, con x = 0 fuera de la
    traza (el generador apagado). Del mismo largo que x. Sin `d` es el FIR solo."""
    x = np.asarray(x, float)
    j0 = int(lags[0])
    full = np.convolve(x, np.asarray(c, float))
    k = np.arange(x.size) - j0
    out = np.full(x.size, float(b))
    ok = (k >= 0) & (k < full.size)
    out[ok] += full[k[ok]]
    for di, tau in zip(d, lentos):
        out += float(di) * pasabajos(x, tau)
    return out


def predecir_canal(x, canal):
    """`predecir` con el modelo guardado en el dict de `caracterizar` (los análisis
    viejos no traen polos lentos: queda el FIR solo)."""
    return predecir(x, canal['fir'], canal['fir_b'], canal['fir_lags'],
                    canal.get('fir_lentos', ()), canal.get('lentos', ()))


def _cruce(t, s, nivel):
    """El primer t (interpolado) donde s sube a `nivel`."""
    for i in range(1, len(s)):
        if s[i - 1] < nivel <= s[i]:
            return float(t[i - 1] + (nivel - s[i - 1]) / (s[i] - s[i - 1]) * (t[i] - t[i - 1]))
    return None


def respuesta(c, lags=LAGS):
    """Las cuentas de la respuesta del canal desde los taps del FIR."""
    c = np.asarray(c, float)
    js = np.arange(int(lags[0]), int(lags[1]))
    g = float(c.sum())
    if g == 0:
        raise ValueError('el FIR suma 0: no vuelve nada por IN1 (¿el cable?)')
    s = np.cumsum(c) / g                      # la respuesta al escalón, normalizada
    t10, t50, t90 = (_cruce(js, s, v) for v in (0.1, 0.5, 0.9))
    f = np.linspace(0.0, 0.5, 4097)           # ciclos por muestra, hasta Nyquist
    H = np.abs(np.exp(-2j * np.pi * f[:, None] * js[None, :]) @ c) / abs(g)
    abajo = np.flatnonzero(H < 1.0 / math.sqrt(2.0))
    bw = None if abajo.size == 0 else float(f[abajo[0]] * FS_HZ / 1e6)
    # En el lazo digital el escalón vale 0 en j = −1 y 1 en j = 0: t50 = −0.5.
    lat_asg = None if t50 is None else int(round(t50 + 0.5))
    return dict(ganancia=g, latencia=float((js * c).sum() / g), t50=t50, lat_asg=lat_asg,
                subida=None if None in (t10, t90) else t90 - t10,
                subida_ns=None if None in (t10, t90) else (t90 - t10) * 1e9 / FS_HZ,
                sobrepico=float(max(0.0, s.max() - 1.0)), bw_3db_mhz=bw,
                no_causal=float((c[js < 0] ** 2).sum() / max((c ** 2).sum(), 1e-30)),
                escalon=s.tolist())


def respuesta_lenta(d, lentos, ganancia, t):
    """La respuesta al escalón normalizada a la ganancia de corto plazo, en los
    instantes `t` (muestras a ritmo pleno) después del flanco: 1 + Σ (d_i/g)(1 − e^{−t/τ_i}).
    Es la caída lenta, la que el FIR no ve."""
    t = np.asarray(t, float)
    s = np.ones_like(t)
    for di, tau in zip(d, lentos):
        s += float(di) / float(ganancia) * (1.0 - np.exp(-t / float(tau)))
    return s


def modulo_h(c, n=512):
    """|H(f)| / |H(0)| del FIR, de 0 a Nyquist: (f en MHz, |H|)."""
    c = np.asarray(c, float)
    js = np.arange(LAGS[0], LAGS[0] + c.size)
    f = np.linspace(0.0, 0.5, int(n))
    g = abs(float(c.sum())) or 1e-30
    H = np.abs(np.exp(-2j * np.pi * f[:, None] * js[None, :]) @ c) / g
    return f * FS_HZ / 1e6, H


# =============================================================================
# El piso
# =============================================================================

def densidad(y, seg=SEG_PSD):
    """La densidad de Welch con ventana de Hann (unilateral, cuentas²/Hz) y sus
    frecuencias, de una captura sin pulsos."""
    y = np.asarray(y, float)
    seg = int(min(seg, y.size))
    w = np.hanning(seg)
    k = y.size // seg
    z = (y[:k * seg] - y.mean()).reshape(k, seg) * w
    P = 2.0 * (np.abs(np.fft.rfft(z, axis=1)) ** 2).mean(axis=0) / (FS_HZ * (w ** 2).sum())
    return np.fft.rfftfreq(seg, 1.0 / FS_HZ), P


def piso(y, seg=SEG_PSD):
    """Media, desvío y densidad de ruido de una captura sin pulsos. La densidad es la de
    Welch con ventana de Hann (unilateral, cuentas²/Hz); la `densidad` es su mediana
    entre 1 MHz y Nyquist, en cuentas/√Hz, y `sigma_blanco` el desvío de un ruido blanco
    con esa densidad: si es mucho menor que `sigma`, el piso no es blanco."""
    y = np.asarray(y, float)
    mu, sd = float(y.mean()), float(y.std())
    f, P = densidad(y, seg)
    df = f[1] - f[0]
    banda = f >= 1e6
    med = float(np.median(P[banda]))
    esp = []
    alto = np.flatnonzero((P > ESPURIA_X * med) & (f > 3 * df))
    if alto.size:
        grupos = np.split(alto, np.flatnonzero(np.diff(alto) > 1) + 1)
        for gr in grupos:
            lo, hi = max(gr[0] - 1, 0), min(gr[-1] + 2, P.size)   # el lóbulo de Hann
            i = gr[np.argmax(P[gr])]
            # La densidad integra a la varianza (Parseval con Σw²): la potencia de la
            # línea es lo que el lóbulo pasa del piso.
            esp.append(dict(f_mhz=float(f[i] / 1e6),
                            rms=float(math.sqrt(max(P[lo:hi].sum() - med * (hi - lo), 0.0)
                                                * df))))
        esp.sort(key=lambda e: -e['rms'])
    return dict(media=mu, sigma=sd, densidad=math.sqrt(med),
                sigma_blanco=math.sqrt(med * FS_HZ / 2.0), espurias=esp[:5], n=int(y.size))


# =============================================================================
# Todo junto
# =============================================================================

def caracterizar(x, y0, y1, piso0, piso1, lags=LAGS):
    """El canal desde las cinco capturas de `capturar_canal`: el estímulo por el lazo
    (`x`), lo que vuelve por IN1 (`y0`) e IN2 (`y1`), y las dos entradas sin pulsos. Lo
    que devuelve va al JSON (sin los arreglos largos)."""
    p0, p1 = piso(piso0), piso(piso1)
    f0 = ajustar_fir(x, y0, lags)
    r = respuesta(f0['c'], lags)
    lento = float(np.sum(f0['d']))
    out = dict(offset=p0['media'], ruido=p0['sigma'], piso=p0, piso_in2=p1,
               offset_in2=p1['media'], ruido_in2=p1['sigma'],
               residuo_rms=f0['rms'], muestras_ajuste=int(f0['n'].size),
               residuo_rms_fir=ajustar_fir(x, y0, lags, lentos=())['rms'],
               fir=[float(v) for v in f0['c']], fir_b=f0['b'], fir_lags=list(f0['lags']),
               fir_lentos=[float(v) for v in f0['d']], lentos=list(f0['lentos']),
               **{k: v for k, v in r.items()})
    out.update(ganancia_dc=r['ganancia'] + lento,
               caida_lenta=lento / r['ganancia'] if r['ganancia'] else 0.0)
    f1 = ajustar_fir(x, y1, lags)
    xa = np.asarray(x, float)
    coh0 = predecir(xa, f0['c'], 0.0, lags, f0['d'], f0['lentos'])[f0['n']].std()
    coh1 = predecir(xa, f1['c'], 0.0, lags, f1['d'], f1['lentos'])[f1['n']].std()
    out.update(diafonia_dc=float(f1['c'].sum() / (r['ganancia'] or 1e-30)),
               diafonia_db=float(20.0 * math.log10(max(coh1 / max(coh0, 1e-30), 1e-12))),
               fir_in2=[float(v) for v in f1['c']])
    return out


def problema(c):
    """None si el canal medido sirve; si no, qué le pasa. Sin el coaxial el FIR da
    ganancia ~0, el residuo es el piso y todo "cierra": hay que decirlo antes. Con el
    jumper de IN1 en HV (±20 V) la ganancia cae a ~1/20."""
    g = c['ganancia']
    if abs(g) < GANANCIA_NULA:
        return (f'la ganancia del canal es {g:.4f}: OUT1 no llega a IN1 '
                '(¿falta el coaxial OUT1 → IN1?)')
    if g < GANANCIA_MIN:
        return (f'la ganancia del canal es {g:.4f}, lejos de 1 (~0.05 es el jumper de IN1 '
                'en HV: hace falta LV)')
    return None


def residuo(y, pred, sigma_piso, margen=MARGEN_SAT, x=None, mascara=False):
    """y − predicción en las muestras lejos de los rieles: rms, máximo y cuántas pasan
    el umbral de un error de captura (8 desvíos robustos y al menos 6 del piso). Un
    error de la captura (una muestra corrida, una palabra mal leída) da cientos de
    cuentas; la alinealidad del canal, unas pocas y suaves."""
    y = np.asarray(y, float)
    pred = np.asarray(pred, float)
    # Fuera: lo que el ADC recorta (medido, o predicho por el canal: con sobrepico el
    # recorte llega antes que el riel del generador), más RECUPERA muestras a cada lado.
    riel = ((y >= AMP_MAX - margen) | (y <= AMP_MIN + margen)
            | (pred >= AMP_MAX - margen) | (pred <= AMP_MIN + margen))
    if x is not None:
        riel |= np.abs(np.asarray(x, float)) >= AMP_MAX - margen
    riel = np.convolve(riel.astype(int), np.ones(2 * RECUPERA + 1, int), 'same') > 0
    ok = ~riel & np.isfinite(pred) & np.isfinite(y)
    r = (y - pred)[ok]
    if r.size == 0:
        return dict(muestras=0)
    med = float(np.median(r))
    robusto = 1.4826 * float(np.median(np.abs(r - med)))
    umbral = max(8.0 * robusto, 6.0 * float(sigma_piso), 8.0)
    # Más una tolerancia proporcional a la señal: cerca del fondo de escala el front-end
    # comprime ~1 % (medido en la placa), y eso no es un error de captura.
    fuera = np.abs(r - med) > umbral + TOL_ALINEAL * np.abs(pred[ok])
    out = dict(muestras=int(r.size), rms=float(r.std()), media=float(r.mean()),
               max=float(np.abs(r).max()), robusto=robusto, umbral=umbral,
               fuera=int(fuera.sum()))
    if mascara:                  # qué muestras de y pasan el umbral (no va al JSON)
        m = np.zeros(y.size, bool)
        m[np.flatnonzero(ok)[fuera]] = True
        out['_mascara'] = m
    return out


# =============================================================================
# La medición rápida: el piso y un estímulo de banda ancha, a ritmo pleno
# =============================================================================

def casos_canal(semilla=1):
    """Las capturas del canal analógico: el piso (pulsos de altura 0, para que el ASG
    dispare) y un estímulo de banda ancha para el FIR (escalones de subida 0 de los dos
    signos, Poisson a 200 k/s, más el ruido del generador, que es blanco y conocido: va
    en lo capturado por el lazo). Sin saturar: el apilamiento llega a ±1000 cuentas de
    desvío."""
    from API import generadores as G
    sal = dict(salidas=G.SAL_OUT1, n=0, semilla=semilla)
    return [
        ('piso', G.config(periodo=1000, amp_n=1, tau=250.0, subida=0, base=0, ruido=False,
                          **sal),
         np.array([0], np.int16)),
        ('excitacion', G.config(aleatorio=True, tasa=200e3, dt_min=2, amp_aleat=True,
                                tau=250.0, subida=0, base=0, ruido=True, ruido_sh=2, **sal),
         G.tabla_cdf([-2500, 700, 1800, 3200], [0.25, 0.25, 0.25, 0.25])),
    ]


def capturar_canal(cap, semilla=1, pre=PRE_CANAL):
    """Las cinco capturas de `caracterizar`, con una captura (`CapturaBram`, o las
    `CapturaPlaca` y `CapturaSimulada` de las campañas) en cualquier modo: el lazo se
    elige en cada una."""
    post = int(cap.n_buf) - int(pre)
    out = {}
    for nombre, gen, tabla in casos_canal(semilla):
        ana = cap.bram_capturar(gen, tabla, pre, post, lazo=False)
        if nombre == 'piso':
            out['piso0'], out['piso1'] = ana['buf'], ana['buf1']
            continue
        dig = cap.bram_capturar(gen, tabla, pre, post, lazo=True)
        out['x'], out['y0'], out['y1'] = dig['buf'], ana['buf'], ana['buf1']
    return out


# =============================================================================
# La medición lenta: cuasi-escalones con diezmado
# =============================================================================

def lentos_diezmados(dec, lentos=LENTOS):
    """Los polos lentos en muestras diezmadas."""
    return tuple(float(t) / float(dec) for t in lentos)


def caso_lento(semilla=1):
    """(generador, tabla): escalones alternados de ±ALTO_ESCALON cada PERIODO_ESCALON
    ciclos, con τ = 524 µs (cuasi-escalones: en 131 µs caen un 22 %, y x se captura)."""
    from API import generadores as G
    gen = G.config(periodo=PERIODO_ESCALON, amp_n=2, tau=TAU_ESCALON, subida=0, base=0,
                   ruido=False, salidas=G.SAL_OUT1, n=0, semilla=semilla)
    return gen, np.array([ALTO_ESCALON, -ALTO_ESCALON], np.int16)


def capturar_lentos(cap, semilla=1, promedios=PROMEDIOS, dec=DEC_LENTO, pre=PRE_CANAL):
    """{'x': el estímulo por el lazo, 'ys': [IN1 sin el lazo] × promedios}, diezmados."""
    post = int(cap.n_buf) - int(pre)
    gen, tabla = caso_lento(semilla)
    x = cap.bram_capturar(gen, tabla, pre, post, lazo=True, dec=dec)['buf']
    ys = [cap.bram_capturar(gen, tabla, pre, post, lazo=False, dec=dec)['buf']
          for _ in range(int(promedios))]
    return dict(x=x, ys=ys)


def _mascara_flancos(x, antes=ANTES_FLANCO, despues=DESPUES_FLANCO):
    """Las muestras cerca de un flanco de x: ahí la fase del diezmado (distinta en cada
    captura) y la respuesta rápida mandan, y el ajuste lento no las mira."""
    x = np.asarray(x, float)
    dx = np.abs(np.diff(x))
    if dx.size == 0 or dx.max() == 0:
        return np.zeros(x.size, bool)
    flancos = np.flatnonzero(dx > 0.1 * dx.max()) + 1
    m = np.zeros(x.size, bool)
    for e in flancos:
        m[max(0, e - antes):min(x.size, e + despues + 1)] = True
    return m


def ajustar_lentos(pares, dec, lentos=LENTOS, inicial=False):
    """La ganancia de corto plazo y la caída lenta desde pares (x, y) diezmados, sin los
    flancos. Devuelve el ajuste con y sin los polos lentos."""
    fueras = [_mascara_flancos(x) for x, _y in pares]
    f = ajustar_pares(pares, LAGS_LENTO, lentos=lentos_diezmados(dec, lentos),
                      fueras=fueras, inicial=inicial)
    f0 = ajustar_pares(pares, LAGS_LENTO, lentos=(), fueras=fueras)
    return f, f0


def caracterizar_lento(pares, dec=DEC_LENTO, lentos=LENTOS, referencia='generador'):
    """Lo que va al JSON de la medición lenta: los dᵢ (con sus τᵢ a ritmo pleno), la
    ganancia de corto plazo y la caída lenta Σd/Σc. Con la referencia externa la señal
    venía de antes de la captura, y el estado inicial de cada polo entra al ajuste."""
    f, f0 = ajustar_lentos(pares, dec, lentos, inicial=referencia == 'externa')
    g = float(np.sum(f['c']))
    d = [float(v) for v in f['d']]
    return dict(referencia=referencia, dec=int(dec), n_capturas=len(pares),
                lentos=[float(t) for t in lentos], lentos_us=[t / FS_HZ * 1e6 for t in lentos],
                d=d, ganancia=g, ganancia_dc=g + sum(d),
                caida_lenta=sum(d) / g if g else 0.0,
                caida_por_polo=[v / g if g else 0.0 for v in d],
                residuo_rms=f['rms'], residuo_rms_sin_lentos=f0['rms'],
                muestras=f['muestras'], b=f['b'])


# =============================================================================
# La referencia externa: una cuadrada en IN1, sin el generador
# =============================================================================

def escalon_ideal(y, suavizado=SUAVIZADO):
    """El escalón ideal (0 o ESCALON_X) de una cuadrada capturada: arriba donde la señal
    suavizada pasa la media altura entre sus percentiles 5 y 95. ValueError si no hay
    una cuadrada."""
    y = np.asarray(y, float)
    k = max(1, int(suavizado))
    ys = np.convolve(y, np.ones(k) / k, 'same')
    lo, hi = np.percentile(ys, 5), np.percentile(ys, 95)
    if hi - lo < ESCALON_MIN:
        raise ValueError(f'la señal de IN1 va de {lo:.0f} a {hi:.0f} cuentas: no hay una '
                         'cuadrada (¿está conectado el generador externo?)')
    x = np.where(ys > 0.5 * (lo + hi), ESCALON_X, 0.0)
    if np.count_nonzero(np.diff(x)) < 2:
        raise ValueError('la captura no tiene dos flancos: con el diezmado cubre ~0.5 ms, '
                         'así que la cuadrada tiene que ser de ~2 kHz (medio período de '
                         '250 µs, 5 veces el polo más lento)')
    return x


def capturar_externo(cap, promedios=PROMEDIOS, dec=DEC_LENTO, pre=PRE_CANAL):
    """[IN1] × promedios, diezmados, con disparo por software."""
    post = int(cap.n_buf) - int(pre)
    return [cap.capturar_sw(pre, post, dec=dec)['buf'] for _ in range(int(promedios))]


def caracterizar_externo(ys, dec=DEC_LENTO, lentos=LENTOS):
    """La caída lenta de IN1 sola: cada captura contra su escalón ideal."""
    pares = [(escalon_ideal(y), np.asarray(y, float)) for y in ys]
    out = caracterizar_lento(pares, dec, lentos, referencia='externa')
    alto = [float(np.ptp(np.percentile(y, [5, 95]))) for _x, y in pares]
    out['escalon_cuentas'] = float(np.median(alto))
    return out


# =============================================================================
# La medición entera (lo que corre `canal.medir`)
# =============================================================================

QUE = ('todo', 'rapido', 'lento')
REFERENCIAS = ('generador', 'externa')


def medir(cap, referencia='generador', que='todo', semilla=1, promedios=PROMEDIOS):
    """(resultado, capturas). `resultado` es el dict de `caracterizar` (la medición
    rápida) con `lento` (la lenta o la externa) adentro; `capturas`, nombre -> int16.
    `caida_lenta_usar` es la de la lenta si se midió (más larga, mejor determinada) y si
    no la de la rápida."""
    if referencia not in REFERENCIAS:
        raise ValueError(f'referencia {referencia!r}: una de {REFERENCIAS}')
    if que not in QUE:
        raise ValueError(f'que {que!r}: uno de {QUE}')
    caps = {}
    if referencia == 'externa':
        ys = capturar_externo(cap, promedios)
        lento = caracterizar_externo(ys)
        caps['externa_y'] = np.stack(ys)
        res = dict(referencia='externa', lento=lento,
                   caida_lenta_usar=lento['caida_lenta'], fuente_caida='externa')
        return res, caps
    res = {}
    if que in ('todo', 'rapido'):
        d = capturar_canal(cap, semilla)
        res = caracterizar(**d)
        caps.update(d)
        res['problema'] = problema(res)
    if que in ('todo', 'lento') and not res.get('problema'):
        dl = capturar_lentos(cap, semilla, promedios)
        res['lento'] = caracterizar_lento([(dl['x'], y) for y in dl['ys']])
        caps['lento_x'] = dl['x']
        caps['lento_y'] = np.stack(dl['ys'])
        if 'ganancia' not in res:
            res['problema'] = problema(res['lento'])
    res['referencia'] = 'generador'
    if 'lento' in res:
        res.update(caida_lenta_usar=res['lento']['caida_lenta'], fuente_caida='lenta')
    else:
        res.update(caida_lenta_usar=res.get('caida_lenta', 0.0), fuente_caida='rapida')
    return res, caps


def repetibilidad(y_a, y_b, sigma_piso):
    """Dos capturas de IN1 del mismo estímulo: el rms de su diferencia contra el que
    darían dos ruidos independientes (√2 σ). Una conexión floja da cientos de cuentas."""
    r = np.asarray(y_a, float) - np.asarray(y_b, float)
    rms = float(r.std())
    esperado = math.sqrt(2.0) * float(sigma_piso)
    return dict(rms=rms, esperado=esperado, razon=rms / esperado if esperado else None,
                estable=bool(rms <= 2.0 * esperado))


# =============================================================================
# El procedimiento en la placa
# =============================================================================

class CapturaBram:
    """La BRAM del osciloscopio con el generador de pulsos, sobre handles abiertos (los
    del servidor): `osc` (Osciloscope), `mt` (MultiTrigger), `gen` (GenPulsos, o None
    para sólo la referencia externa) e `ig` (la integración, o None: entonces la ruta del
    OSC no se toca y el diezmado depende de cómo esté).

    Usarla con `with`: al entrar guarda lo que toca y al salir lo restaura, aunque algo
    falle en el medio."""

    ESPERA_PRE_S = 0.005     # el pre-trigger se llena antes de arrancar el generador

    def __init__(self, osc, mt, gen=None, ig=None):
        self.osc, self.mt, self.gen, self.ig = osc, mt, gen, ig
        self._guardado = None
        self.restaurado = None

    @property
    def n_buf(self):
        return int(self.osc.n_buf)

    def __enter__(self):
        self._guardado = self.guardar()
        return self

    def __exit__(self, *exc):
        if self._guardado is not None:
            self.restaurar(self._guardado)
            self._guardado = None
        return False

    # ---------- guardar y restaurar ----------

    def _regs_osc(self):
        from API import osciloscope as O
        return (O.R_THR_CH0, O.R_THR_CH1, O.R_DLY_CH0, O.R_DLY_CH1, O.R_DEC_CH0,
                O.R_DEC_CH1, O.R_HYST_CH0, O.R_HYST_CH1, O.R_AVG_EN, O.R_DEB_LEN)

    def _regs_mt(self):
        from API import multitrigger as MT
        return (MT.R_SHIELD_CFG,)

    def _mascaras(self):
        from API import multitrigger as MT
        return (MT.R_OR_MASK_CH0, MT.R_OR_MASK_CH1, MT.R_OR_MASK_CH2, MT.R_OR_MASK_CH3)

    def guardar(self):
        """Lo que la medición toca: registros del OSC y del MT, las máscaras, qué
        canales tenían `we_keep` (el disparo continuo del MCA), la config y la tabla del
        generador, el lazo y la ruta del OSC. RuntimeError si el generador está
        generando: no se puede devolver a ese estado."""
        from API import multitrigger as MT
        s = {'osc': {r: self.osc.r32(r) for r in self._regs_osc()},
             'mt': {r: self.mt.r32(r) for r in self._regs_mt()},
             'mascaras': {r: self.mt.r32(r) for r in self._mascaras()},
             'we_keep': (self.mt.r32(MT.R_FLAGS) >> 4) & 0xF}
        if self.gen is not None:
            est = self.gen.estado()
            if est.get('generando'):
                raise RuntimeError('el generador está generando: pararlo antes de medir '
                                   'el canal (la medición usa el generador)')
            from API import generadores as G
            s['gen'] = dict(cfg=self.gen.leer_config(),
                            tabla=np.asarray(self.gen.leer_tabla(G.N_TABLA), np.int16),
                            lazo=bool(self.gen.lazo))
        if self.ig is not None:
            r = self.ig.routes()['osc']
            s['ruta_osc'] = (int(r['tap']), bool(r['enable']))
        return s

    def restaurar(self, s):
        """Todo como estaba: el generador parado con su config, la tabla y el lazo; los
        registros del OSC y del MT; si había `we_keep` en algún canal, la captura
        re-armada en continuo (arm antes que la máscara, como `multitrigger_armar_mca`);
        y la ruta del OSC. Devuelve qué hizo, y lo deja en `self.restaurado`."""
        from API import osciloscope as O
        hecho = []
        if 'gen' in s and self.gen is not None:
            g = s['gen']
            self.gen.parar()
            self.gen.configurar(**g['cfg'])
            self.gen.cargar_tabla(g['tabla'])
            self.gen.lazo = g['lazo']
            hecho.append('generador')
        osc, mt = self.osc, self.mt
        osc.w32(O.R_CMD, 0)                      # desarmar
        for r, v in s['mascaras'].items():
            mt.w32(r, 0)                         # sin fuentes mientras se restaura
        osc.w32(O.R_CMD, 0x0000_0202)            # reset de la FSM
        for r, v in s['osc'].items():
            osc.w32(r, v)
        for r, v in s['mt'].items():
            mt.w32(r, v)
        osc.w32(O.R_TRIG_DIS_CLR, 0x0000_0101)
        wk = int(s['we_keep'])
        if wk & 0x3:
            osc.w32(O.R_CMD, sum(0x09 << (8 * ch) for ch in range(2) if (wk >> ch) & 1))
            hecho.append('captura re-armada (we_keep)')
        for r, v in s['mascaras'].items():
            mt.w32(r, v)
        hecho.append('OSC y multitrigger')
        if 'ruta_osc' in s and self.ig is not None:
            tap, en = s['ruta_osc']
            self.ig.set_route('osc', tap, en)
            hecho.append('ruta del OSC')
        self.restaurado = hecho
        return hecho

    # ---------- una captura ----------

    def _ruta(self, dec):
        """TAP_ADC (crudo, lo que ve el MCA) a ritmo pleno; la nativa con diezmado,
        porque TAP_ADC lo saltea."""
        if self.ig is None:
            return
        from API import integration as I
        self.ig.set_route('osc', I.TAP_ADC if int(dec) == 1 else I.TAP_NATIVE, True)

    def _armar(self, post, dec, mascara):
        """La BRAM en single-shot, con `mascara` en el canal 0 y nada en el 1, el retardo
        de post-trigger, el diezmado (con promedio si dec > 1) y sin el filtro de
        `deb_len` (rp_ext_trig filtra también el ASG). Arm antes que la máscara."""
        from API import osciloscope as O
        osc, mt = self.osc, self.mt
        mt.set_or_mask(0, 0)
        osc.acq_base(thr=0.0, delay=int(post), decim=int(dec))
        O.osciloscope_configure(osc, avg_en_ch0=int(dec > 1), avg_en_ch1=int(dec > 1))
        mt.disable_shield()
        osc.set_raw_delay(int(post))
        osc.w32(O.R_DEB_LEN, 0)
        osc.w32(O.R_TRIG_DIS_CLR, 0x0000_0101)
        osc.w32(O.R_CMD, 0x0000_0101)            # arm, single-shot
        mt.set_or_mask(mascara, 0)

    def _desarmar(self):
        from API import osciloscope as O
        self.mt.set_or_mask(0, 0)
        self.osc.w32(O.R_CMD, 0)
        self.osc.w32(O.R_TRIG_DIS_CLR, 0x0000_0101)

    def _esperar_y_leer(self, pre, post, dec, **_kw):
        """Espera el post-trigger y lee los dos canales en cuentas crudas de la BRAM.
        `_kw` es lo que la captura falsa necesita para sintetizar."""
        from API import osciloscope as O
        plazo = int(2000 + (pre + post) * dec * 8e-6)
        if not self.osc.wait_fill(timeout_ms=plazo):
            raise TimeoutError('la BRAM no completó el post-trigger: ¿no hubo disparo?')
        wp = int(O.osciloscope_get_wp_trig(self.osc, 0))
        n = int(pre) + int(post)
        buf = np.asarray(O.osciloscope_read_cal(self.osc, 0, wp - pre, n, IDENTIDAD), np.int16)
        buf1 = np.asarray(O.osciloscope_read_cal(self.osc, 1, wp - pre, n, IDENTIDAD),
                          np.int16)
        return dict(buf=buf, buf1=buf1, wp_trig=wp)

    def bram_capturar(self, gen, tabla, pre, post, lazo=False, dec=1):
        """Un buffer de los dos canales con el generador: disparo del ASG en el primer
        pulso, `lazo` prendido o no. La misma firma que `CapturaPlaca.bram_capturar`."""
        from API import multitrigger as MT
        if self.gen is None:
            raise RuntimeError('este bitstream no trae el generador de pulsos')
        if pre + post > self.n_buf:
            raise ValueError(f'{pre} + {post} muestras: el buffer tiene {self.n_buf}')
        g = self.gen
        g.lazo = bool(lazo)
        g.configurar(**gen)                      # apagado: el lazo da ceros
        g.cargar_tabla(tabla)
        self._ruta(dec)
        self._armar(post, dec, MT.BIT_ASG_P)
        try:
            time.sleep(self.ESPERA_PRE_S + (pre * dec) / FS_HZ)
            g.arrancar()
            return self._esperar_y_leer(pre, post, dec, gen=gen, tabla=tabla,
                                        lazo=bool(lazo))
        finally:
            g.parar()
            self._desarmar()

    def capturar_sw(self, pre, post, dec=1):
        """Un buffer con disparo por software, sin el generador (la referencia externa)."""
        from API import multitrigger as MT
        from API import osciloscope as O
        if pre + post > self.n_buf:
            raise ValueError(f'{pre} + {post} muestras: el buffer tiene {self.n_buf}')
        if self.gen is not None:
            self.gen.parar()
            self.gen.lazo = False
        self._ruta(dec)
        self._armar(post, dec, MT.BIT_SW)
        try:
            time.sleep(self.ESPERA_PRE_S + (pre * dec) / FS_HZ)
            O.osciloscope_sw_trigger(self.osc)
            return self._esperar_y_leer(pre, post, dec, externa=True)
        finally:
            self._desarmar()
