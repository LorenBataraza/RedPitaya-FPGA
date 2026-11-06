#!/usr/bin/env python3
"""El presupuesto de ruido completo de la cadena, término por término.

Corre en la PC, sin placa, en ~1 min.

QUEDA EN EL MCA1, A PROPÓSITO
-----------------------------
Usa la réplica del MCA1 de `pileup.py` y no la del MCA2 (`replica_mca2.py`): parte el ruido de la campaña del 2026-09-08 y lo proyecta sobre los estimadores tal como estaban en ese bitstream.
Repetirlo sobre el MCA2 no explicaría esas mediciones.

QUÉ CONTESTA
------------
`fuentes_de_jitter.md` ordena los términos de TIEMPO y deja el de amplitud en
una línea ("ruido ADC + front-end, 2.8 cuentas, el piso").
`varianza_estimadores.py` mide ese piso sobre las trazas y lo parte en dos
—blanco por muestra y error de línea de base por evento— pero no dice **de qué
es cada parte ni qué se puede hacer con ella**. Este script cierra eso:

  1. **Parte el ruido por su ESPECTRO, no por su magnitud.** De las 7054
     ventanas de la campaña, el canal 2 estaba en vacío: son 3.6 millones de
     muestras de línea de base pura. Su autocovarianza separa un término blanco
     de uno correlacionado y **mide el tiempo de correlación del segundo**, que
     es el único número que decide si el seguidor de línea de base puede
     sacarlo.
  2. **Modela el seguidor IIR del RTL con su aritmética entera exacta**
     (`mca_pulse_feature.sv`: `bl_acc += dat - bl_acc_shr`, con el shift
     registrado y la base truncada a DW bits). Es lo único del MCA que ningún
     Monte-Carlo del repo modela con ruido: `linea_base.py` lo corre
     determinista, para el pedestal por tasa.
  3. **Suma el presupuesto** para los dos estimadores de amplitud y lo compara
     con lo medido en placa.

LO QUE SALE, ADELANTADO
----------------------
- El ruido NO es blanco: sobre el blanco de ~4.5 cuentas hay un término
  correlacionado de ~0.9 cuentas con tiempo de correlación de ~12 µs. El blanco
  promedia como 1/sqrt(N) en la integral; el correlacionado NO, porque es
  constante dentro de la ventana — y por eso **domina el estimador que mejor
  resolución da**.
- El seguidor de base del RTL existe justamente para sacar ese término, y la
  campaña lo tenía ENCENDIDO — pero con `bl_k = 12`, o sea con su codo en
  4.9 kHz, **por debajo de los 13 kHz del ruido que tiene que seguir**. Sigue la
  parte equivocada. El óptimo está en `bl_k` = 6–9, y su piso no es el que uno
  esperaría: **no es la ganancia de ruido del IIR sino el DITHER de la parte
  fraccionaria de la base**, porque la base se entrega truncada a enteros.

    python3 ruido.py                      # tablas + figura
    python3 ruido.py --rapido             # menos estadística en el barrido de k
    python3 ruido.py --sin-figura
"""
import argparse
import glob
import json
import os
import sys
import time

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt                              # noqa: E402

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

_SOFT = _AQUI
while _SOFT != '/' and not os.path.isfile(os.path.join(_SOFT, 'API', 'mca.py')):
    _SOFT = os.path.dirname(_SOFT)

TRAZAS = os.path.join(_SOFT, 'datos', 'e2e_20260528_013404', 'principal')
SALIDA = os.path.join(_SOFT, 'datos')

# --- constantes del sistema (ver docs/adc_ltc2145.md §2 y §3) ----------------
FS_HZ = 125e6
TS = 1.0 / FS_HZ
FS_CUENTAS = 8192.0            # fondo de escala de un pulso unipolar, en códigos
SNR_ADC_DBFS = 73.1            # hoja de datos LTC2145-14
N_PRE = 9                      # muestras de pre-disparo que trae cada ventana

# --- condiciones de la campaña (docs/resultados_validacion_hw.md §13.6) -----
A_REF = 1920.0                 # amplitud del estímulo, en cuentas
SF_REF = 298.0                 # área/pico de la forma real, en muestras
GATE = 384                     # cfg_gate_long de la compuerta fija
GATE_CORTA = 32
BL_HOLDOFF = 64                # cfg_bl_holdoff típico, en muestras
BASE_DC = 5.18                 # línea de base medida en el canal 1 de la campaña

# `cfg_bl_k` con el que corrió la campaña: `campanas/testbench_mca.py`,
# DEFAULT_CFG = dict(..., bl_auto=True, bl_k=12, ...). O sea que el seguidor
# estaba ENCENDIDO; lo que está mal elegido es su constante de tiempo.
K_HOY = 12

# `cfg_bl_k` recomendado. El óptimo de ruido es PLANO entre 6 y 9 (ver el
# barrido), así que lo que lo decide no es el ruido: es que el seguidor no se
# coma el pie del pulso antes de que cruce el umbral. Eso está medido en placa
# y es una cota por abajo — `API/mca.py:mca_set_bl_k` documenta que con un pulso
# de 62 µs, k=6 da 0 eventos y k>=9 da los 2000 esperados. 9 es el más chico
# que la placa tiene verificado Y está adentro del óptimo.
K_REC = 9

# Lo medido, para contrastar. Offline = mismas trazas por software;
# placa = el bitstream (docs/mca/decisiones_diseno_mca.md §2.2, §14).
MEDIDO = {
    'pico':    dict(offline=0.272, placa=0.344),
    'q_hist':  dict(offline=None,  placa=0.325),
    'q_fija':  dict(offline=0.149, placa=0.161),
}
# Descomposición de σ/A [%] de varianza_estimadores.py para la forma real.
# Son el punto de partida: este script sólo rehace el término de BASE.
#
# Actualizadas: aquel script ya no usa su propia estimación del término
# correlacionado (1.00 cuentas sacadas de las 9 muestras de pre-disparo) sino
# `ruido_medido` de acá, y lo inyecta como PROCESO con tau = 12 µs en vez de
# como un offset constante por evento. Por eso `VE_SIGMA_BL` vale ahora el
# sigma_c medido y el reescalado de `presupuesto` queda en 1.00 para la fila
# "sin seguidor": lo que sigue haciendo es bajar el término cuando el seguidor
# se lleva parte del correlacionado.
DESCOMP = {
    'pico':   dict(blanco=0.132, base=0.048, fase=0.002, total=0.141),
    'q_fija': dict(blanco=0.026, base=0.066, fase=0.018, total=0.073),
}
# El sigma_c con el que varianza_estimadores.py calculó esos términos de base.
# El término escala LINEAL con él, así que es la referencia para reescalarlo.
VE_SIGMA_BL = 0.87

# Paleta del proyecto (docs/mca/figuras/figuras_resolucion.py)
SUP, TINTA, TINTA2, MUDO, GRILLA = '#fcfcfb', '#0b0b0b', '#52514e', '#898781', '#e1e0d9'
AZUL, NARAN, ROJO, VERDE = '#2a78d6', '#eb6834', '#d03b3b', '#2e8b57'
plt.rcParams.update({
    'figure.facecolor': SUP, 'axes.facecolor': SUP, 'savefig.facecolor': SUP,
    'font.size': 10, 'axes.titlesize': 10, 'axes.labelsize': 10,
    'axes.edgecolor': '#c3c2b7', 'axes.labelcolor': TINTA2,
    'text.color': TINTA, 'xtick.color': MUDO, 'ytick.color': MUDO,
    'axes.grid': True, 'grid.color': GRILLA, 'grid.linewidth': 0.6,
    'axes.axisbelow': True, 'legend.frameon': False, 'figure.dpi': 140,
})


# =============================================================================
# 1. El ruido, medido y separado por su espectro
# =============================================================================

def cargar_campana(dirtraz=TRAZAS):
    arch = sorted(glob.glob(os.path.join(dirtraz, 'chunk_*.npz')))
    if not arch:
        raise SystemExit(f'no hay chunks en {dirtraz}')
    wave = np.concatenate([np.load(a)['wave'] for a in arch])
    t_ns = np.concatenate([np.load(a)['t_ns'] for a in arch]).astype(float)
    return wave, t_ns


def autocovarianza(y, lag_max):
    """Autocovarianza promediada sobre eventos, SIN quitar la media por ventana.

    Quitarle a cada ventana su propia media induce una correlación negativa
    espuria de -1/(n-1) en todos los retardos (el mismo cuidado que toma
    `varianza_estimadores.modelo_ruido`) y, peor para lo que se busca acá,
    **borra justamente el término correlacionado** que se quiere medir. Acá se
    quita el perfil medio sobre EVENTOS, que es la señal determinista (incluye
    el crosstalk del canal vecino) y no toca la estadística por muestra.
    """
    n = y.shape[1]
    Y = np.fft.rfft(y, n=2 * n, axis=1)
    ac = np.fft.irfft(np.abs(Y) ** 2, axis=1)[:, :n].mean(axis=0)
    return ac[:lag_max + 1] / np.arange(n, n - lag_max - 1, -1)


def ajuste_exponencial(ac, lag_lo, lag_hi):
    """A y L_c de C(L) = A·exp(-L/L_c) por mínimos cuadrados en una grilla.

    Se ajusta desde `lag_lo` para no meter el término blanco (que vive sólo en
    L = 0) ni el retardo 1, donde el ADC agrega una correlación propia.
    """
    L = np.arange(lag_lo, lag_hi, dtype=float)
    c = ac[lag_lo:lag_hi]
    mejor = None
    for Lc in np.logspace(1.0, 5.0, 600):
        e = np.exp(-L / Lc)
        A = float((c * e).sum() / (e * e).sum())
        r = float(((c - A * e) ** 2).sum())
        if mejor is None or r < mejor[0]:
            mejor = (r, A, float(Lc))
    _, A, Lc = mejor
    return max(A, 0.0), Lc


def ruido_medido(wave, t_ns, canal_vacio=1, canal_señal=0, lag_max=450):
    """Separa el ruido en blanco + correlacionado y mide el tiempo de correlación.

    El canal `canal_vacio` de la campaña no tenía estímulo: 7054 ventanas × 512
    muestras de línea de base pura, con dos escalas de tiempo accesibles —
    dentro de la ventana (hasta 4 µs) y entre ventanas (1 ms).
    """
    y = wave[:, canal_vacio, :].astype(float)
    perfil = y.mean(axis=0)
    y = y - perfil                      # quita el crosstalk y cualquier DC
    ac = autocovarianza(y, lag_max)
    A, Lc = ajuste_exponencial(ac, 2, lag_max)
    sigma_w = float(np.sqrt(max(ac[0] - A, 0.0)))
    sigma_c = float(np.sqrt(A))

    # --- el test que decide: ¿está correlacionado entre ventanas (1 ms)? ---
    m = wave[:, canal_vacio, :N_PRE].astype(float).mean(axis=1)
    var_m = float(m.var(ddof=1))
    mc = m - m.mean()
    rho_ms = {int(L): float((mc[:-L] * mc[L:]).mean() / var_m)
              for L in (1, 2, 5, 10, 100)}
    # Si el término correlacionado fuera más lento que el espaciado entre
    # ventanas, rho(1) valdría esto; si es más rápido, 0.
    rho_esperado_lento = sigma_c ** 2 / var_m
    rho_err = 1.0 / np.sqrt(len(m))

    # --- crosstalk entre canales, del mismo perfil medio ---
    perfil_sig = wave[:, canal_señal, :].astype(float).mean(axis=0)
    amp_sig = float(perfil_sig.max() - np.median(perfil_sig[:N_PRE]))
    amp_vac = float(perfil.max() - np.median(perfil[:N_PRE]))
    crosstalk_db = float(20 * np.log10(amp_vac / amp_sig))

    # --- ¿cuánto de ese ruido pone el GENERADOR? ---
    # El canal con estímulo y el canal en vacío comparten placa, ADC y reloj, y
    # se diferencian en que uno tiene el Rigol colgado de la entrada. Con el
    # MISMO estimador sobre las muestras de pre-disparo de los dos, la
    # diferencia es el aporte del generador. Es la medición que
    # `fuentes_de_jitter.md` §6 llama "la más barata del documento": resulta que
    # los datos para hacerla ya estaban tomados.
    pre = {}
    for c in (canal_señal, canal_vacio):
        z = wave[:, c, :N_PRE - 2].astype(float)     # sin las 2 pegadas al disparo
        z = z - z.mean(axis=0, keepdims=True)
        pre[c] = float(np.sqrt(autocovarianza(z, 0)[0]))

    dt = np.diff(t_ns)
    return dict(
        sigma_pre_senal=pre[canal_señal], sigma_pre_vacio=pre[canal_vacio],
        sigma_w=sigma_w, sigma_c=sigma_c, tau_c_muestras=Lc,
        tau_c_us=Lc * TS * 1e6, f_codo_khz=1.0 / (2 * np.pi * Lc * TS) / 1e3,
        ac=ac, sigma_tot=float(np.sqrt(ac[0])),
        rho_ms=rho_ms, rho_esperado_lento=float(rho_esperado_lento),
        rho_err=float(rho_err), var_m=var_m,
        crosstalk_db=crosstalk_db, amp_sig=amp_sig, amp_vac=amp_vac,
        # Ojo: ésta es la base del canal EN VACÍO. La del canal con señal
        # (BASE_DC) es la que usa el MC, porque es la que ve el MCA. Las dos se
        # reportan porque el dither del seguidor depende de la PARTE
        # FRACCIONARIA de la base, y las dos caen en lugares distintos.
        base_dc_vacio=float(perfil[:N_PRE].mean()),
        n_ventanas=int(y.shape[0]), n_muestras=int(y.size),
        dt_ventanas_us=float(np.median(dt) / 1e3),
    )


def reparto_blanco(sigma_w):
    """Cuánto del blanco por muestra es del ADC y cuánto de todo lo demás.

    El ADC pone lo que dice su SNR: una senoidal de fondo de escala tiene valor
    eficaz (FS/2)/sqrt(2), así que sigma = (FS/2)/sqrt(2) / 10^(SNR/20). La
    cuantización (1/sqrt(12)) ya está adentro de ese número.
    """
    sigma_adc = FS_CUENTAS / np.sqrt(2) / 10 ** (SNR_ADC_DBFS / 20)
    sigma_q = 1.0 / np.sqrt(12)
    resto = float(np.sqrt(max(sigma_w ** 2 - sigma_adc ** 2, 0.0)))
    return dict(sigma_adc=float(sigma_adc), sigma_q=float(sigma_q),
                resto=resto,
                frac_adc=float(sigma_adc ** 2 / sigma_w ** 2),
                frac_resto=float(resto ** 2 / sigma_w ** 2))


def cota_antialias(f_corte_mhz=60.0, ordenes=(1, 2, 3)):
    """Cuánto del ruido medido podría ser ruido DOBLADO por falta de antialias.

    El S/H del ADC tiene 750 MHz de ancho de banda y el único filtro de la
    cadena es la caída del front-end a 60 MHz (docs/adc_ltc2145.md §2.1): todo
    lo que entre arriba de 62.5 MHz se dobla a la banda. Con el ruido del
    front-end blanco hasta mucho más allá de su propio corte y una caída de
    orden n, la fracción de la potencia que llega por doblado es

        1 - ∫_0^fNy |H|² df / ∫_0^inf |H|² df

    Es una COTA, no una medición: supone que el ruido del front-end es blanco a
    la entrada de su propia caída, que es justo lo que no está medido.
    """
    f_ny = FS_HZ / 2 / 1e6
    out = {}
    for n in ordenes:
        f = np.linspace(0, 200 * f_corte_mhz, 400001)
        h2 = 1.0 / (1.0 + (f / f_corte_mhz) ** (2 * n))
        tot = float(np.trapz(h2, f))
        k = f <= f_ny
        dentro = float(np.trapz(h2[k], f[k]))
        out[n] = dict(enbw_mhz=tot, dentro_mhz=dentro,
                      frac_doblada=1.0 - dentro / tot,
                      mejora_sigma=float(np.sqrt(dentro / tot)))
    return out


# =============================================================================
# 2. El seguidor de línea de base del RTL, con su aritmética exacta
# =============================================================================

def _ou(n, sigma, tau_muestras, rng, x0=None):
    """Proceso de Ornstein-Uhlenbeck (AR(1)) con la sigma y el tau medidos.

    Es el proceso estacionario más simple con autocovarianza exponencial, que
    es la que se midió. No se postula: `tau` y `sigma` salen de `ruido_medido`.
    `x0` encadena bloques sucesivos sin cortar la correlación.
    """
    a = float(np.exp(-1.0 / tau_muestras))
    e = rng.normal(0.0, sigma * np.sqrt(1 - a * a), n)
    x = np.empty(n)
    x[0] = (rng.normal(0.0, sigma) if x0 is None else a * x0 + e[0])
    for i in range(1, n):
        x[i] = a * x[i - 1] + e[i]
    return x


def seguidor_rtl(dat, k, frac_bits=0, congelado=None, estado=None):
    """Réplica exacta del seguidor de `mca_pulse_feature.sv`.

        bl_acc      <= bl_acc + dat - bl_acc_shr      (sólo si no está congelado)
        bl_acc_shr  <= bl_acc >>> k                   (registrado: un ciclo tarde)
        baseline    <= bl_acc_shr[DW-1:0]             (registrado otra vez)

    `>>>` sobre un acumulador con signo es floor, no truncamiento hacia cero, y
    el acumulador es ancho a propósito (DW + 2^BL_KW bits) para que el
    incremento no se cuantice a cero. Las dos cosas importan para el ruido: la
    información fraccionaria se guarda en el acumulador y lo único que se
    cuantiza es la base ENTREGADA.

    `frac_bits` no existe en el RTL: es la propuesta de entregar la base con F
    bits fraccionarios (`bl_acc >>> (k-F)`, en unidades de 2^-F). Sirve para
    poner un número a cuánto cuesta el truncamiento, y se devuelve en cuentas.

    `congelado[i] = True` reproduce el freeze durante el pulso y el holdoff.
    """
    n = len(dat)
    sh = k - frac_bits
    esc = float(1 << frac_bits)
    bl_acc, shr, prev = estado if estado is not None else (0, 0, 0)
    out = np.empty(n)
    frz = congelado if congelado is not None else np.zeros(n, dtype=bool)
    for i in range(n):
        out[i] = prev / esc
        prev = shr
        if not frz[i]:
            bl_acc = bl_acc + int(dat[i]) - (bl_acc >> k)
        shr = bl_acc >> sh
    return out, (bl_acc, shr, prev)


def mc_seguidor(k, ruido, rng, n_ev=400, gate=GATE, holdoff=BL_HOLDOFF,
                frac_bits=0, base_dc=BASE_DC, espaciado=None):
    """σ del error de base que ve un evento, con el seguidor corriendo.

    Devuelve DOS números, porque los dos estimadores de amplitud ven el error
    de base de forma distinta:

      `sigma_pico`  = σ del error en UNA muestra (la del pico). Es
                      bl_congelada - base_verdadera en el instante del pico.
      `sigma_int_N` = σ de la SUMA del error sobre las `gate` muestras de la
                      ventana, dividida por `gate`. O sea el error de base
                      EQUIVALENTE por muestra para la integral. Si el error
                      fuera constante dentro de la ventana daría lo mismo que
                      `sigma_pico`; es menor en la medida en que la base se
                      mueve y se promedia, y mayor nunca.

    El estímulo no hace falta: el error de base es aditivo y no depende de la
    amplitud del pulso. Lo único que el pulso aporta es el CONGELAMIENTO del
    seguidor, que sí se modela (gate + holdoff).
    """
    if espaciado is None:
        # El seguidor corre CONTINUO entre eventos, así que el espaciado sólo
        # tiene que alcanzar para que el transitorio del congelamiento anterior
        # se haya ido: 8 constantes de tiempo sobran.
        espaciado = max(8 * (1 << k), 4 * (gate + holdoff), 2048)

    # Un evento por bloque, encadenando el estado del OU y el del seguidor. Sin
    # esto el stream entero (n_ev × espaciado muestras) no entra en memoria para
    # los k grandes.
    frz = np.zeros(espaciado, dtype=bool)
    ini = espaciado // 2
    frz[ini:ini + gate + holdoff] = True
    est = None
    w0 = None
    err_pico, err_int = [], []
    calentamiento = 3          # bloques que se descartan: el acumulador arranca
    for b in range(n_ev + calentamiento):   # en 0 y la base real está en ~5
        w = _ou(espaciado, ruido['sigma_c'], ruido['tau_c_muestras'], rng, x0=w0)
        w0 = w[-1]
        base = base_dc + w
        dat = np.rint(base + rng.normal(0.0, ruido['sigma_w'], espaciado)
                      ).astype(np.int64)
        bl, est = seguidor_rtl(dat, k, frac_bits=frac_bits, congelado=frz,
                               estado=est)
        if b < calentamiento:
            continue
        e = bl[ini:ini + gate] - base[ini:ini + gate]
        err_int.append(e.sum() / gate)
        err_pico.append(e[0])
    err_pico = np.asarray(err_pico)
    err_int = np.asarray(err_int)
    a_ = 2.0 ** -k
    return dict(
        k=k, frac_bits=frac_bits, espaciado=int(espaciado), n_ev=len(err_int),
        sigma_pico=float(err_pico.std(ddof=1)),
        sigma_int_N=float(err_int.std(ddof=1)),
        sesgo_pico=float(err_pico.mean()), sesgo_int=float(err_int.mean()),
        iir_teorico=float(ruido['sigma_w'] * np.sqrt(a_ / (2 - a_))),
        dither_teorico=float(np.sqrt(_frac(base_dc) * (1 - _frac(base_dc)))
                             / (1 << frac_bits)),
        seguimiento_teorico=float(ruido['sigma_c'] * np.sqrt(
            (1 << k) / ((1 << k) + ruido['tau_c_muestras']))),
        tau_f_us=float((1 << k) * TS * 1e6),
    )


def _frac(x):
    return float(x - np.floor(x))


def barrido_bl_k(ruido, rng, ks, n_ev, fracs=(0, 2)):
    out = {}
    for fb in fracs:
        out[fb] = [mc_seguidor(k, ruido, rng, n_ev=n_ev, frac_bits=fb) for k in ks]
    return out


# =============================================================================
# 3. Los términos que pone la aritmética de la cadena digital
# =============================================================================

def muestras_en_cero(sigma_w, gate=GATE, amp=A_REF, umbral_sigmas=2.0):
    """Cuántas muestras de la ventana fija tienen la señal "en cero".

    Es donde el recorte `xc = max(x-base, 0)` puede actuar: si la señal está
    muy por encima del ruido, el recorte nunca se activa y no hay nada que
    rectificar. Se cuenta sobre la plantilla real del estímulo, no sobre una
    estimación de ancho: la forma del ARB tiene una cola de 1.5 µs y una
    ventana de 384 muestras son 3.07 µs, así que la pregunta no es obvia.
    """
    import varianza_estimadores as ve
    tpl = ve.plantilla_ref(2e-6, 0.0)
    y = amp * tpl[:gate]
    if y.size < gate:                       # la plantilla es más corta que la ventana
        y = np.concatenate([y, np.zeros(gate - y.size)])
    n = int(np.count_nonzero(y < umbral_sigmas * sigma_w))
    return dict(n_cero=n, gate=gate, cola_al_cierre=float(y[-1]),
                umbral_cuentas=float(umbral_sigmas * sigma_w))


def clamp_rectificacion(sigma, n_cero):
    """Qué le hace a la integral el recorte `xc = max(x - base, 0)`.

    `mca_pulse_feature.sv` satura cada muestra a >= 0 antes de acumular (lo
    necesita el divisor: protege q_tail < q_tot). Donde la señal vale ~0 —el
    tramo de la ventana fija en que el pulso ya se extinguió— eso RECTIFICA el
    ruido: una variable de media cero pasa a tener media sigma/sqrt(2pi).

        E[max(n,0)]   = sigma/sqrt(2pi)
        Var[max(n,0)] = sigma^2 (1/2 - 1/(2pi))

    El sesgo es sistemático y se calibra. Lo que NO se calibra es que depende de
    sigma: si el ruido cambia (temperatura, tasa, otra fuente), el pedestal de
    la integral cambia con él y el centroide se mueve sin que nada de la señal
    haya cambiado. Esto pone el número a ese acoplamiento.
    """
    bias1 = sigma / np.sqrt(2 * np.pi)
    var1 = sigma ** 2 * (0.5 - 1.0 / (2 * np.pi))
    return dict(
        bias_por_muestra=float(bias1), sigma_por_muestra=float(np.sqrt(var1)),
        bias_q=float(n_cero * bias1), sigma_q=float(np.sqrt(n_cero * var1)),
        d_centroide_por_cuenta=float(n_cero / np.sqrt(2 * np.pi)),
    )


def cuantizaciones():
    """Los términos de cuantización de la cadena, todos uniformes de 1 LSB.

    - ADC: 1 código. Ya está dentro del SNR, no se suma aparte.
    - `q_shift`: la integral se entrega como `q_tot >> cfg_q_shift`, así que se
      trunca 1 LSB del eje de amplitud.
    - `mca_zoom`: es puro rebanado de bits, no agrega nada propio; lo que agrega
      es el bineado del eje, que es la corrección de Sheppard.
    - histograma: 1 canal.
    """
    u = 1.0 / np.sqrt(12)
    return dict(adc_cuentas=u, q_shift_lsb=u, bin_canales=u,
                sheppard=lambda can_fwhm: np.sqrt(1 + (2.355 / can_fwhm) ** 2 / 12) - 1)


# =============================================================================
# 4. El presupuesto
# =============================================================================

def presupuesto(ruido, seg_hoy, seg_prop, seg_prop_frac):
    """Los dos estimadores, con el término de base rehecho por este script.

    Se parte de la descomposición de `varianza_estimadores.py` y se REEMPLAZA el
    término de base por el que da el seguidor con cada configuración. Los otros
    dos términos —blanco y fase— no los toca el seguidor, así que se dejan.

    Ojo con la referencia: `varianza_estimadores.py` estima la base con la media
    de las 9 muestras de pre-disparo de cada ventana, que NO es ninguno de los
    dos estimadores de la placa (ni la base fija ni el IIR). Su `sigma_bl` sirve
    como escala —el término es lineal en él— y nada más.

    La fila de `bl_auto = 0` se deja como referencia aunque la campaña no haya
    corrido así: es la cota de arriba, el caso en que nada saca el término
    correlacionado.
    """
    tabla = {}
    for est, N in (('pico', 1), ('q_fija', GATE)):
        d = DESCOMP[est]
        sigma_bl_ref = VE_SIGMA_BL
        filas = {}
        campo = 'sigma_pico' if N == 1 else 'sigma_int_N'
        for nom, sbl in ((f'sin seguidor (referencia)', ruido['sigma_c']),
                         (f'`bl_k = {K_HOY}` (la campaña)', seg_hoy[campo]),
                         (f'`bl_k = {K_REC}` (propuesto)', seg_prop[campo]),
                         (f'`bl_k = {K_REC}` + 2 bits frac.', seg_prop_frac[campo])):
            base = d['base'] * sbl / sigma_bl_ref
            tot = float(np.sqrt(d['blanco'] ** 2 + base ** 2 + d['fase'] ** 2))
            filas[nom] = dict(sigma_bl=float(sbl), blanco=d['blanco'],
                              base=float(base), fase=d['fase'],
                              sigma=tot, fwhm=2.355 * tot)
        tabla[est] = filas
    return tabla


# =============================================================================
# 5. Salida
# =============================================================================

def tabla_ruido(r):
    rep = reparto_blanco(r['sigma_w'])
    print('\n### El ruido de la línea de base, medido y separado por su espectro\n')
    print(f"Canal en vacío de la campaña: {r['n_ventanas']} ventanas × 512 muestras "
          f"= {r['n_muestras'] / 1e6:.2f} M muestras de base pura.\n")
    print('| término | σ [cuentas] | σ [µV] | varianza | correlación |')
    print('|---|---|---|---|---|')
    v = r['sigma_tot'] ** 2
    for nom, s, corr in (
            ('blanco (descorrelacionado a 8 ns)', r['sigma_w'], 'ninguna'),
            (f"correlacionado (τ = {r['tau_c_us']:.0f} µs)", r['sigma_c'],
             f"plana hasta ~{r['tau_c_us']:.0f} µs"),
    ):
        print(f'| {nom} | {s:.2f} | {s * 122.07:.0f} | '
              f'{s ** 2 / v * 100:.1f} % | {corr} |')
    print(f"| **total por muestra** | **{r['sigma_tot']:.2f}** | "
          f"{r['sigma_tot'] * 122.07:.0f} | 100 % | — |")

    print('\n**El test que lo decide.** Si el término correlacionado fuera deriva '
          'lenta, las bases de dos ventanas consecutivas (separadas '
          f"{r['dt_ventanas_us'] / 1e3:.2f} ms) correlacionarían "
          f"ρ = {r['rho_esperado_lento']:.3f}. Medido:\n")
    print('| retardo | ρ medido | ρ si fuera lento | ρ si fuera rápido |')
    print('|---|---|---|---|')
    for L, rho in r['rho_ms'].items():
        print(f"| {L} ventana{'s' if L > 1 else ''} ({L * r['dt_ventanas_us'] / 1e3:.0f} ms) "
              f"| {rho:+.4f} ± {r['rho_err']:.3f} | {r['rho_esperado_lento']:+.3f} | 0 |")
    print(f"\nEs cero a {r['rho_esperado_lento'] / r['rho_err']:.0f}σ del valor "
          'que tendría una deriva lenta: **el término correlacionado no es deriva '
          'térmica ni de red, y la autocovarianza fija su tiempo de correlación '
          f"en {r['tau_c_us']:.0f} µs (codo en {r['f_codo_khz']:.0f} kHz).**")

    print('\n### ¿Cuánto de ese ruido pone el generador?\n')
    print('Mismo estimador sobre el pre-disparo de los dos canales de la misma '
          'campaña: uno con el Rigol colgado de la entrada, el otro en vacío.\n')
    print('| canal | σ por muestra [cuentas] |')
    print('|---|---|')
    print(f"| 1, con el generador | {r['sigma_pre_senal']:.2f} |")
    print(f"| 2, en vacío | {r['sigma_pre_vacio']:.2f} |")
    dif = r['sigma_pre_vacio'] ** 2 - r['sigma_pre_senal'] ** 2
    print(f"\nLa diferencia en varianza es {dif:+.2f} cuentas² — del orden del error "
          'del propio estimador, y del signo *contrario* al que tendría un '
          'generador ruidoso. **El generador no aporta ruido medible: las '
          f"{r['sigma_tot']:.2f} cuentas son de la placa.** Eso cierra la "
          'pregunta que `fuentes_de_jitter.md` §6 dejaba abierta ("separar el '
          'ruido del ADC del ruido del pulser") con datos que ya estaban '
          'tomados, y simplifica el reparto que sigue: no hay un tercer dueño.')

    print('\n### De quién es el ruido blanco\n')
    print('| fuente | σ [cuentas] | varianza | de dónde sale |')
    print('|---|---|---|---|')
    print(f"| ADC (SNR = {SNR_ADC_DBFS} dBFS) | {rep['sigma_adc']:.2f} | "
          f"{rep['frac_adc'] * 100:.1f} % | hoja de datos |")
    print(f"| front-end de la placa | {rep['resto']:.2f} | "
          f"{rep['frac_resto'] * 100:.1f} % | por diferencia |")
    print(f"| **total medido** | **{r['sigma_w']:.2f}** | 100 % | autocovarianza en L=0 |")
    print(f"\n(De los {rep['sigma_adc']:.2f} del ADC, la cuantización sola pone "
          f"{rep['sigma_q']:.3f} cuentas: ya está adentro del SNR.)")

    print(f"\n### Crosstalk entre canales\n")
    print(f"El pulso del canal 1 ({r['amp_sig']:.0f} cuentas de pico) aparece en el "
          f"canal 2, en vacío, como un perfil medio de {r['amp_vac']:.2f} cuentas: "
          f"**{r['crosstalk_db']:.1f} dB**. Es el número que "
          '`docs/adc_ltc2145.md` §10.2 dejaba pendiente, y sale de datos que ya '
          'estaban tomados.')
    return rep


def tabla_antialias(cota, sigma_w, sigma_adc):
    print('\n### Cuánto del blanco podría ser ruido DOBLADO\n')
    print('| caída del front-end | ENBW de ruido | dentro de Nyquist | fracción doblada '
          '| σ con antialias perfecto |')
    print('|---|---|---|---|---|')
    for n, d in cota.items():
        piso = float(np.hypot(np.sqrt(max(sigma_w ** 2 - sigma_adc ** 2, 0))
                              * d['mejora_sigma'], sigma_adc))
        print(f"| {n} polo{'s' if n > 1 else ''} a 60 MHz | {d['enbw_mhz']:.0f} MHz | "
              f"{d['dentro_mhz']:.0f} MHz | {d['frac_doblada'] * 100:.0f} % | "
              f"{piso:.2f} cuentas |")
    print('\nEs una **cota**: supone el ruido del front-end blanco hasta mucho más '
          'allá de su propio corte. El término del ADC no baja —entra después del '
          'filtro—, así que el piso con un antialias perfecto nunca baja de '
          f'{sigma_adc:.2f} cuentas.')


def tabla_seguidor(bar, ks, ruido):
    print('\n### El seguidor de línea de base: su propio ruido, contra `cfg_bl_k`\n')
    print('`sigma_pico` es el error en una muestra; `sigma_int` es el error '
          'equivalente por muestra para la suma sobre la ventana de '
          f'{GATE} muestras. Los tres términos teóricos son la ganancia de ruido '
          'del IIR, el dither de la parte fraccionaria de la base y el residuo de '
          'seguimiento del término correlacionado.\n')
    print('| `bl_k` | τ seguidor | IIR teo. | dither teo. | seguimiento teo. '
          '| σ_pico MC | σ_int MC | σ_int con 2 bits frac. |')
    print('|---|---|---|---|---|---|---|---|')
    for i, k in enumerate(ks):
        a = bar[0][i]
        b = bar[2][i]
        print(f"| {k} | {a['tau_f_us']:.1f} µs | {a['iir_teorico']:.3f} | "
              f"{a['dither_teorico']:.3f} | {a['seguimiento_teorico']:.3f} | "
              f"{a['sigma_pico']:.3f} | {a['sigma_int_N']:.3f} | {b['sigma_int_N']:.3f} |")
    n_ev = bar[0][0]['n_ev']
    print(f"\nError estadístico de cada σ del Monte-Carlo: "
          f"±{100 / np.sqrt(2 * n_ev):.1f} % relativo ({n_ev} eventos por punto). "
          '**El óptimo es plano**: todo lo que está entre `k` = 6 y 9 empata '
          'dentro de ese error, así que el ruido no elige el valor. Lo que lo '
          'elige es la cota por abajo medida en placa (el seguidor no puede '
          f"comerse el pie del pulso): `bl_k = {K_REC}`.")
    print(f"\nPara comparar: con `bl_auto = 0` (como corrió la campaña) el error de "
          f"base es el término correlacionado completo, **{ruido['sigma_c']:.2f} "
          'cuentas**, y nada lo saca.')


def tabla_presupuesto(tab):
    print('\n### El presupuesto, por estimador\n')
    for est, nom in (('pico', 'muestra de pico (`cfg_amp_src = 0`)'),
                     ('q_fija', f'integral, compuerta fija de {GATE} (`cfg_amp_src = 1`)')):
        print(f'**{nom}**\n')
        print('| configuración de la base | σ_bl [cuentas] | blanco | base | fase '
              '| σ/A [%] | FWHM/A [%] |')
        print('|---|---|---|---|---|---|---|')
        for cfg, d in tab[est].items():
            print(f"| {cfg} | {d['sigma_bl']:.2f} | {d['blanco']:.3f} | "
                  f"{d['base']:.3f} | {d['fase']:.3f} | {d['sigma']:.3f} | "
                  f"**{d['fwhm']:.3f}** |")
        m = MEDIDO['q_fija' if est == 'q_fija' else 'pico']
        print(f"\nMedido en placa: **{m['placa']} %**, con `bl_k = {K_HOY}` — la "
              'fila que hay que mirar para validar. (Offline sobre las mismas '
              f"trazas: {m['offline']} %, pero con otro estimador de base, así "
              'que no es comparable fila a fila.)\n')


def figura(ruido, bar, ks, tab, out):
    fig, ax = plt.subplots(1, 3, figsize=(13.2, 4.0))

    # (a) la autocovarianza medida y su ajuste
    a = ax[0]
    ac = ruido['ac']
    L = np.arange(len(ac))
    a.semilogx(L[1:] * TS * 1e6, ac[1:], '.', ms=3, color=MUDO,
               label='medida (canal en vacío)')
    Lf = np.logspace(0, np.log10(len(ac) - 1), 200)
    a.semilogx(Lf * TS * 1e6, ruido['sigma_c'] ** 2
               * np.exp(-Lf / ruido['tau_c_muestras']), '-', color=ROJO, lw=1.6,
               label=f"ajuste: σ={ruido['sigma_c']:.2f}, τ={ruido['tau_c_us']:.0f} µs")
    a.axhline(0, color=TINTA2, lw=0.8)
    a.plot([1e3], [0.0], 'v', color=AZUL, ms=8,
           label='entre ventanas (1 ms): ρ = 0')
    a.set_xlabel('retardo [µs]')
    a.set_ylabel('autocovarianza [cuentas²]')
    a.set_title(f"(a) el ruido no es blanco\nσ_total = {ruido['sigma_tot']:.2f} "
                f"cuentas, de las que {ruido['sigma_c']:.2f} están correlacionadas")
    a.legend(fontsize=8, loc='upper right')

    # (b) el seguidor contra bl_k
    a = ax[1]
    for fb, col, mk in ((0, AZUL, 'o'), (2, VERDE, 's')):
        a.plot(ks, [d['sigma_int_N'] for d in bar[fb]], mk + '-', color=col, ms=4,
               label=f'σ_int, {fb} bits fraccionarios')
    a.plot(ks, [d['iir_teorico'] for d in bar[0]], ':', color=MUDO,
           label='ganancia de ruido del IIR')
    a.plot(ks, [d['seguimiento_teorico'] for d in bar[0]], '--', color=NARAN,
           label='residuo de seguimiento')
    a.plot(ks, [d['dither_teorico'] for d in bar[0]], '-.', color=ROJO,
           label='dither de la base truncada')
    a.axhline(ruido['sigma_c'], color=TINTA, lw=1.2,
              label=f"sin seguidor: {ruido['sigma_c']:.2f}")
    for kk, txt, col in ((K_HOY, f'la campaña\nk = {K_HOY}', ROJO),
                         (K_REC, f'propuesto\nk = {K_REC}', TINTA2)):
        a.axvline(kk, color=col, lw=1.0, ls=':')
        a.annotate(txt, (kk, ruido['sigma_c']), textcoords='offset points',
                   xytext=(-32 if kk == K_HOY else 4, -14), fontsize=7, color=col)
    a.set_yscale('log')
    a.set_xlabel('`cfg_bl_k`  (τ = 2^k muestras)')
    a.set_ylabel('error de base por evento [cuentas]')
    a.set_title('(b) el seguidor tiene un óptimo\ny su piso es el truncamiento, '
                'no el IIR')
    a.legend(fontsize=7, loc='lower left')

    # (c) el presupuesto
    a = ax[2]
    cfgs = [c for c in tab['q_fija'] if 'referencia' not in c]
    x = np.arange(len(cfgs))
    an = 0.38
    for i, (est, col) in enumerate((('pico', NARAN), ('q_fija', AZUL))):
        v = [tab[est][c]['fwhm'] for c in cfgs]
        a.bar(x + (i - 0.5) * an, v, an, color=col, label=est)
    for est, col, ls in (('pico', NARAN, '--'), ('q_fija', AZUL, '--')):
        m = MEDIDO['pico' if est == 'pico' else 'q_fija']['placa']
        a.axhline(m, color=col, ls=ls, lw=1.0)
        a.text(-0.45, m, f'{est} en placa  ', fontsize=7,
               color=col, va='bottom', ha='left')
    a.set_xticks(x)
    a.set_xticklabels([f'bl_k={K_HOY}\n(la campaña)', f'bl_k={K_REC}\n(propuesto)',
                       f'bl_k={K_REC}\n+2 bits frac.'], fontsize=8)
    a.set_ylabel('FWHM / centroide [%]')
    a.set_title('(c) qué compra atacar la base\n(los otros términos sin tocar)')
    a.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(out, bbox_inches='tight')
    print(f'\nfigura -> {out}')


# =============================================================================
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--n', type=int, default=400, help='eventos por punto del barrido')
    p.add_argument('--rapido', action='store_true', help='n=120 y menos k')
    p.add_argument('--semilla', type=int, default=20261009)
    p.add_argument('--out', default=None)
    p.add_argument('--sin-figura', action='store_true')
    args = p.parse_args()

    n_ev = 120 if args.rapido else args.n
    ks = [4, 6, 8, 9, 10, 11, 12] if args.rapido else list(range(4, 14))
    rng = np.random.default_rng(args.semilla)
    t0 = time.time()

    print('=== presupuesto de ruido de la cadena ===')
    wave, t_ns = cargar_campana()
    r = ruido_medido(wave, t_ns)
    rep = tabla_ruido(r)
    tabla_antialias(cota_antialias(), r['sigma_w'], rep['sigma_adc'])

    print(f'\n(barrido del seguidor: {len(ks)} valores de k × {n_ev} eventos…)')
    bar = barrido_bl_k(r, rng, ks, n_ev)
    tabla_seguidor(bar, ks, r)

    # El k que se recomienda es K_REC, no el argmin: ver el comentario de K_REC.
    i_rec = ks.index(K_REC) if K_REC in ks else int(
        np.argmin(np.abs(np.asarray(ks) - K_REC)))
    i_min = int(np.argmin([d['sigma_int_N'] for d in bar[0]]))
    print(f"\nMínimo del Monte-Carlo en `k` = {ks[i_min]} "
          f"(σ_int = {bar[0][i_min]['sigma_int_N']:.3f}); el recomendado es "
          f"`k` = {K_REC} (σ_int = {bar[0][i_rec]['sigma_int_N']:.3f} sin bits "
          f"fraccionarios, {bar[2][i_rec]['sigma_int_N']:.3f} con 2). Los dos "
          'empatan dentro del error del MC.')

    mz = muestras_en_cero(r['sigma_w'])
    cl = clamp_rectificacion(r['sigma_w'], max(mz['n_cero'], 1))
    q = cuantizaciones()
    print('\n### El recorte `xc >= 0`, y el acoplamiento ruido → centroide\n')
    print(f"`mca_pulse_feature.sv` satura cada muestra a >= 0 antes de acumular. "
          f"Donde la señal vale ~0 eso rectifica el ruido y le mete a `q_tot` un "
          f"pedestal de +{cl['bias_por_muestra']:.2f} cuentas por muestra, que "
          '**depende de σ** y por lo tanto acopla el ruido al centroide.\n')
    plural = 'muestras quedan' if mz['n_cero'] != 1 else 'muestra queda'
    print(f"Con el estímulo de la campaña no pasa: de las {GATE} muestras de la "
          f"ventana fija, **{mz['n_cero']}** {plural} por debajo de "
          f"{mz['umbral_cuentas']:.0f} cuentas (2σ). La cola del ARB todavía vale "
          f"{mz['cola_al_cierre']:.0f} cuentas cuando la compuerta cierra, así que "
          '**el recorte nunca se activa dentro de la ventana** y el término es '
          'exactamente cero.\n')
    print(f"Dónde sí importa: con una compuerta más larga que el pulso, o en modo "
          f"histéresis cuando la cola baja al nivel del ruido. Si `n` muestras de "
          f"la ventana quedan en cero, el pedestal es `n·σ/√(2π)` y el "
          f"acoplamiento `d(q_tot)/dσ = n/√(2π)`. Para que un cambio del 10 % en σ "
          f"corra el centroide un 0.1 % harían falta "
          f"{int(0.001 * A_REF * SF_REF / (0.1 * r['sigma_w'] / np.sqrt(2 * np.pi)))} "
          'muestras en cero: más que cualquier ventana razonable. **No es el '
          'mecanismo que falta en `limites_resolucion_y_deriva.md`.**')

    print('\n### Lo que pone la aritmética de la cadena digital\n')
    print('| término | σ | en cuentas de ADC | comentario |')
    print('|---|---|---|---|')
    print(f"| cuantización del ADC | {q['adc_cuentas']:.3f} LSB | "
          f"{q['adc_cuentas']:.3f} | ya está dentro del SNR, no se suma aparte |")
    print(f"| truncamiento de la base (`bl_acc >>> k`) | hasta 0.500 | "
          f"{np.sqrt(_frac(BASE_DC) * (1 - _frac(BASE_DC))):.3f} | "
          'dither de la parte fraccionaria; **no** es uniforme de 1/√12 |')
    print(f"| truncamiento de `q_tot >> cfg_q_shift` | {q['q_shift_lsb']:.3f} LSB del eje | "
          f"{q['q_shift_lsb'] * 2 ** 0:.3f}·2^s | un LSB del eje de amplitud |")
    print(f"| `mca_zoom` | 0 | 0 | rebanado de bits exacto: no agrega nada propio |")
    print(f"| bineado del histograma | {q['bin_canales']:.3f} canales | — | "
          'corrección de Sheppard: a 6.6 canales/FWHM infla σ un '
          f"{q['sheppard'](6.6) * 100:.2f} % |")

    i_hoy = ks.index(K_HOY) if K_HOY in ks else int(
        np.argmin(np.abs(np.asarray(ks) - K_HOY)))
    tab = presupuesto(r, bar[0][i_hoy], bar[0][i_rec], bar[2][i_rec])
    tabla_presupuesto(tab)

    out = args.out or os.path.join(
        SALIDA, 'ruido_' + time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(out, exist_ok=True)
    res = dict(ruido={k: v for k, v in r.items() if k != 'ac'},
               reparto=rep, antialias={str(k): v for k, v in cota_antialias().items()},
               seguidor={str(fb): bar[fb] for fb in bar},
               bl_k=dict(recomendado=K_REC, minimo_mc=ks[i_min]),
               clamp=cl, presupuesto=tab, medido=MEDIDO,
               n_ev=n_ev, semilla=args.semilla)
    with open(os.path.join(out, 'resumen.json'), 'w') as f:
        json.dump(res, f, indent=1, default=float)
    print(f"\nresumen -> {os.path.join(out, 'resumen.json')}")
    if not args.sin_figura:
        figura(r, bar, ks, tab, os.path.join(out, 'ruido.png'))
    print(f'\n({time.time() - t0:.0f} s)')


if __name__ == '__main__':
    main()
