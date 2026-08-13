"""Estimadores de amplitud del MCA, en NumPy puro y sin hardware.

Contiene DOS cosas distintas y hay que no confundirlas:

  1. Una REPLICA EXACTA del RTL (`segmentar_rtl`), ciclo a ciclo, con la misma
     semantica de ventana, saturacion y pico que mca_pulse_feature.sv. Sirve
     para reproducir offline lo que el hardware mide.
  2. Las ALTERNATIVAS que todavia no estan en el RTL: compuertas de largo fijo
     y conformado trapezoidal. Sirven para decidir si vale la pena
     implementarlas antes de gastar una sintesis.

Las tres se calculan sobre LOS MISMOS pulsos, que es lo unico que permite
compararlas: separa "la carga realmente varia" de "nuestra definicion de
ventana agrega varianza".

Todo es funcion pura sobre arrays: se testea sin placa (test_estimadores.py).
"""

import numpy as np


# =============================================================================
# 1. Replica del RTL  (mca_pulse_feature.sv)
# =============================================================================

class Evento:
    """Un pulso segmentado, con lo mismo que emite el RTL."""

    __slots__ = ('i0', 'largo', 'q_tot', 'q_tail', 'pico', 't_pico',
                 'motivo', 'cerrado')

    def __init__(self, i0, largo, q_tot, q_tail, pico, t_pico, motivo):
        self.i0      = i0        # indice de la muestra que abrio
        self.largo   = largo     # muestras acumuladas
        self.q_tot   = q_tot
        self.q_tail  = q_tail
        self.pico    = pico
        self.t_pico  = t_pico
        self.motivo  = motivo    # 'hyst' | 'maxlen' | 'fin_ventana'
        self.cerrado = motivo != 'fin_ventana'

    def __repr__(self):
        return (f'Evento(i0={self.i0}, largo={self.largo}, q_tot={self.q_tot}, '
                f'q_tail={self.q_tail}, pico={self.pico}, motivo={self.motivo!r})')


def segmentar_rtl(dat, baseline=0, thr=100, hyst=40, maxlen=4096, tail_dly=8):
    """Segmenta como mca_pulse_feature.sv y devuelve la lista de eventos.

    Semantica copiada del RTL, con los numeros de linea de la fuente:

      x  = dat - baseline                                          (:132)
      xc = max(x, 0)   -- clamp a >=0 ANTES de acumular             (:133)
      thr_lo = thr - hyst                                           (:136)
      armed: se pone cuando x < thr_lo; se limpia al abrir           (:257)
      abre:  armed y x >= thr_hi                                     (:151)
      al abrir: len=1, t_peak=0, peak=xc, q_tot=xc, q_tail=0         (:273-277)
      cierra: x < thr_lo  (la muestra que cierra NO se acumula)      (:152)
              o len >= maxlen -> APILAMIENTO                          (:153)
      en curso: len+=1, q_tot+=xc, si in_tail q_tail+=xc             (:315-317)
      in_tail = len >= t_peak + tail_dly                              (:159)
      pico con comparacion ESTRICTA: gana la primera ocurrencia      (:319)

    `motivo='fin_ventana'` marca los pulsos que no llegaron a cerrar antes de
    que se acabara el array. Son eventos TRUNCADOS y no hay que usarlos: su
    carga esta cortada. El llamador decide si los descarta o si eso le dice
    que la ventana de captura es demasiado corta.
    """
    x  = np.asarray(dat, dtype=np.int64) - int(baseline)
    xc = np.maximum(x, 0)
    thr_hi = int(thr)
    thr_lo = thr_hi - int(hyst)

    eventos = []
    armed = False
    activo = False
    i0 = largo = q_tot = q_tail = pico = t_pico = 0

    for i in range(x.size):
        xi, xci = x[i], xc[i]

        if not activo:
            # re-armado: la senal tiene que bajar de thr_lo antes de poder abrir
            if xi < thr_lo:
                armed = True
            if armed and xi >= thr_hi:
                activo = True
                armed  = False
                i0, largo = i, 1
                q_tot, q_tail = int(xci), 0
                pico, t_pico  = int(xci), 0
            continue

        # --- pulso activo ---
        if xi < thr_lo:                       # cierra por histeresis
            eventos.append(Evento(i0, largo, q_tot, q_tail, pico, t_pico, 'hyst'))
            activo = False
            armed  = True                     # esta muestra ya esta por debajo
            continue
        if largo >= maxlen:                   # cierra por longitud: APILAMIENTO
            eventos.append(Evento(i0, largo, q_tot, q_tail, pico, t_pico, 'maxlen'))
            activo = False
            continue

        # acumula (la cola arranca tail_dly muestras despues del pico)
        if largo >= t_pico + tail_dly:
            q_tail += int(xci)
        q_tot += int(xci)
        if xci > pico:                        # ESTRICTO
            pico, t_pico = int(xci), largo
        largo += 1

    if activo:                                # se acabo el array sin cerrar
        eventos.append(Evento(i0, largo, q_tot, q_tail, pico, t_pico, 'fin_ventana'))
    return eventos


def psd_rtl(q_tail, q_tot, psd_aw=6):
    """Cociente del eje de forma, con las MISMAS guardas que el hardware.

    El divisor restaurador calcula floor(num * 2^Q_W / den), y
    mca_pulse_feature.sv:176 exige `q_tot != 0 and q_tail < q_tot` antes de
    arrancarlo. Devuelve (psd, ok); con ok=False el evento entra al espectro
    1D pero NO al mapa 2D.
    """
    if q_tot == 0 or q_tail >= q_tot:
        return 0, False
    return int((int(q_tail) << psd_aw) // int(q_tot)), True


# =============================================================================
# 2. Alternativa A: compuertas de largo FIJO  (metodo de comparacion de carga)
# =============================================================================

def integral_gates(dat, baseline=0, thr=100, hyst=40, corta=64, larga=384,
                   pre=0):
    """Carga sobre compuertas de largo FIJO desde el disparo.

    Es el metodo de comparacion de carga (Brooks 1959; Knoll cap. 17): dos
    compuertas de largo fijo, una corta que toma el grueso de la componente
    rapida y una larga que toma todo. A diferencia de la ventana por
    histeresis del RTL, el largo NO lo decide el ruido sobre la cola.

    `pre` extiende la compuerta hacia ATRAS del disparo (necesita muestras
    previas en el array; si no las hay se recorta).

    Devuelve una lista de dicts con q_tot, q_tail y pico, uno por disparo.
    """
    x  = np.asarray(dat, dtype=np.int64) - int(baseline)
    xc = np.maximum(x, 0)
    thr_hi = int(thr)
    thr_lo = thr_hi - int(hyst)

    fuera = []
    armed = False
    i = 0
    while i < x.size:
        if x[i] < thr_lo:
            armed = True
        elif armed and x[i] >= thr_hi:
            a = max(0, i - int(pre))
            b_corta = a + int(pre) + int(corta)
            b_larga = a + int(pre) + int(larga)
            truncado = b_larga > x.size
            b_larga_r = min(b_larga, x.size)
            b_corta_r = min(b_corta, x.size)
            q_tot  = int(xc[a:b_larga_r].sum())
            q_corta = int(xc[a:b_corta_r].sum())
            fuera.append(dict(i0=i, q_tot=q_tot, q_corta=q_corta,
                              q_tail=q_tot - q_corta,
                              pico=int(xc[a:b_larga_r].max()) if b_larga_r > a else 0,
                              truncado=truncado))
            # saltar hasta el final de la compuerta larga: dos disparos dentro
            # de la misma compuerta serian el mismo evento (apilamiento)
            i = b_larga_r
            armed = False
            continue
        i += 1
    return fuera


# =============================================================================
# 3. Alternativa B: conformado trapezoidal  (Jordanov-Knoll 1994)
# =============================================================================

def trapecio(dat, k, m, M, baseline=0):
    """Conformado trapezoidal recursivo de Jordanov & Knoll (NIM A 345, 1994).

        d[n] = v[n] - v[n-k] - v[n-l] + v[n-k-l]      con l = k + m
        p[n] = p[n-1] + d[n]
        r[n] = p[n] + M*d[n]
        s[n] = s[n-1] + r[n]

    `k` es el tiempo de subida y `m` la meseta, en MUESTRAS. `M` es la
    constante de decaimiento de la senal de entrada, tambien en muestras: es
    el termino que cancela el polo (deconvoluciona la cola exponencial). Con
    M correcto la salida vuelve a cero sin undershoot; con M mal, no.

    La altura de la meseta vale k*M*A para una entrada exponencial de
    amplitud A, asi que la salida NO esta normalizada: para comparar
    resoluciones da igual (se usa sigma/media), pero para calibrar hay que
    dividir por k*M.

    Devuelve el array conformado, del mismo largo que la entrada.
    """
    v = np.asarray(dat, dtype=np.float64) - float(baseline)
    k, l = int(k), int(k) + int(m)
    n = v.size

    # d[n] = v[n] - v[n-k] - v[n-l] + v[n-k-l], con v[<0] = 0
    def desp(a, d):
        out = np.zeros_like(a)
        if d < a.size:
            out[d:] = a[:a.size - d]
        return out

    d = v - desp(v, k) - desp(v, l) + desp(v, k + l)
    p = np.cumsum(d)
    r = p + float(M) * d
    return np.cumsum(r)


def meseta_ventana(i_disparo, i_pico, k, m):
    """Donde esta REALMENTE la meseta del trapecio. Devuelve (a, b) o None.

    Para un ESCALON ideal en T la meseta va de T+k a T+k+m. Pero la entrada
    real no es un escalon: la carga se colecta entre `i_disparo` y `i_pico`.
    Como el trapecio es un filtro lineal, la salida sube desde i_disparo+k
    hasta i_pico+k, y recien ahi es plana, hasta i_disparo+k+m:

        meseta = [ i_pico + k , i_disparo + k + m ]

    De donde sale la condicion que es facil pasar por alto:

        m > (i_pico - i_disparo)     o sea  m > el tiempo de coleccion

    Si no se cumple **no hay meseta**: la ventana queda vacia y lo que se
    muestrea es el flanco del trapecio, que depende del tiempo de subida de
    cada pulso. Es un error silencioso — da un numero, y es malo.
    """
    a = int(i_pico) + int(k)
    b = int(i_disparo) + int(k) + int(m)
    return (a, b) if b > a else None


def altura_meseta(s, i_disparo, k, m, i_pico=None, frac=0.6):
    """Altura de la meseta del trapecio, promediando su parte central.

    `i_pico` es el fin de la coleccion de carga; si no se pasa se asume un
    escalon ideal (i_pico == i_disparo). Se promedia el `frac` central para no
    tocar los codos, donde el conformado tiene su transitorio.
    """
    i_pico = i_disparo if i_pico is None else i_pico
    v = meseta_ventana(i_disparo, i_pico, k, m)
    if v is None:
        return np.nan                      # m <= tiempo de coleccion: sin meseta
    a, b = v
    margen = int((b - a) * (1 - frac) / 2)
    a, b = a + margen, b - margen
    a, b = max(0, a), min(len(s), max(a + 1, b))
    if a >= len(s):
        return np.nan
    return float(np.mean(s[a:b]))


# =============================================================================
# 4. Metricas
# =============================================================================

def resolucion(valores):
    """Resolucion en % (FWHM/centroide) de un conjunto de estimaciones.

    Se usa sigma/media * 2.355 y no un ajuste gaussiano a proposito: sobre los
    valores crudos (sin binear) no hay binado que sesgue el ancho, que es
    justamente el artefacto que arruino la comparacion pico/integral en la
    campana (un q_shift grande comprimia el pico en pocos canales y el FWHM se
    cuantizaba).
    """
    v = np.asarray(valores, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < 2 or v.mean() == 0:
        return dict(n=v.size, media=np.nan, sigma=np.nan, res_pct=np.nan)
    return dict(n=int(v.size), media=float(v.mean()), sigma=float(v.std(ddof=1)),
                res_pct=float(100.0 * 2.355 * v.std(ddof=1) / v.mean()))
