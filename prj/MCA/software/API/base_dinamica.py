"""La base dinámica del MCA: la base fija corrida con la tasa, para compensar la caída
lenta del canal analógico.

**Por qué.** El canal tiene polos lentos (`API/canal.py`): la respuesta a un escalón cae
una fracción `caída` = Σd/Σc en algunos µs. Cada pulso deja una cola negativa, las colas
se apilan, y la base bajo cada pulso queda corrida en promedio

    Δb = caída · (λ / f_s) · ⟨A⟩ · τ

con λ la tasa, ⟨A⟩ la amplitud media en la entrada (ADU) y τ la caída de los pulsos (en
muestras): λ·⟨A⟩·τ/f_s es el nivel medio del tren. El MCA resta una base fija, la de
tasa cero, y el trapecio con polo-cero pasa el error a la amplitud como (l/τ)·Δb
(docs/resultados_meritos_gen_pulsos.md §2.5): unos 9 canales a 400 k/s con el canal
OUT1 → T 50 Ω → IN1. El seguidor de base no lo arregla, porque no ve la base entre
pulsos a esas tasas.

**La ley.** `BaseDinamica.paso` estima cada vez lo que hace falta y lo escribe en la base
fija (registro 0x01C, vale al ciclo siguiente sin parar el MCA):

    base = b0 + clamp(κ · caída · (λ̂ / f_s) · ⟨A⟩ · τ, ±tope)

- λ̂: los disparos sin veto sobre el tiempo que pudieron llegar (`arribos_y_tiempo`,
  la misma λ̂ del `status`), entre un paso y el siguiente. Cuenta también los que no
  encontraron ranura: llegaron y dejaron su cola.
- ⟨A⟩: la feature media de lo que entró al histograma entre pasos (sin el primer ni el
  último canal, que juntan lo de afuera) sobre `ganancia_mca`, las cuentas de la feature
  por ADU de entrada (se mide con `mca.ganancia`, con el lazo digital). Supone que los
  pulsos perdidos tienen el mismo espectro que los medidos.
- τ: la del polo-cero del trapecio, `trap_mq/16 + 1/2` (M = 1/(e^{1/τ} − 1) ≈ τ − 1/2).
- κ: un factor de ajuste, 1 por defecto. La réplica con el canal medido se corre 1.34
  veces lo que la placa, así que la ley tiene que poder escalarse (`base.verificar`).

λ̂ y ⟨A⟩ se suavizan con un promedio exponencial (`suavizado_s`, en tiempo del MCA).
Corrige el corrimiento MEDIO de la base, no su fluctuación entre eventos. Un Clear (el
histograma o los contadores que bajan) reinicia la referencia sin mover la base.
"""
import math

import numpy as np

FS_HZ = 125e6
AMP_W = 16               # bits de la feature del eje 1D
TOPE_ADU = 1000          # |Δb| máximo
SUAVIZADO_S = 1.0        # constante del promedio de λ̂ y ⟨A⟩, en tiempo del MCA
EVENTOS_MIN = 20         # eventos nuevos en el histograma para tomar un ⟨A⟩ nuevo
BASE_MIN, BASE_MAX = -8192, 8191   # la base fija es de 14 bits con signo


def arribos_y_tiempo(cnt):
    """(arribos, segundos) de la tasa de entrada: λ̂ = arribos / segundos.

    Arribos: los disparos que llegaron sin veto, `cross − lost_veto`. Incluye los
    que se perdieron por no haber ranura (`lost_active`) o por esperar al
    publicador (lost_busy): llegaron, aunque no se midieran.

    Segundos: `realtime − vetotime − t_rearm`. El veto sale porque sus disparos no
    se cuentan, y `t_rearm` porque un pulso que llega con el disparo sin re-armar
    no genera flanco y nunca llega a `cross`: no se puede contar, sólo descontar
    su tiempo.

    No es `accepted / livetime`: `accepted` deja afuera los rechazados por la
    ventana de amplitud y la forma, y `livetime` deja afuera el tiempo en que las
    ranuras estaban ocupadas, durante el cual también llegan pulsos.
    """
    arribos = cnt.get('cross', 0) - cnt.get('lost_veto', 0)
    segundos = (cnt.get('realtime_s', 0.0) - cnt.get('vetotime_s', 0.0)
                - cnt.get('t_rearm_s', 0.0))
    return arribos, segundos


def tau_de_mq(trap_mq):
    """La caída de los pulsos, en muestras, desde la Mq del polo-cero (M·16)."""
    return float(trap_mq) / 16.0 + 0.5


def valores_de_canales(n_canales, h_aw, z=0, k=0, amp_w=AMP_W):
    """La feature en el centro de cada canal del eje 1D, con el zoom (z, k)."""
    from API.mca import mca_amplitud_de_canal
    h_aw = int(h_aw)
    lo = np.array([mca_amplitud_de_canal(c, h_aw, z, k, amp_w) for c in (0, 1)], float)
    ancho = lo[1] - lo[0]
    return lo[0] + ancho * (np.arange(int(n_canales)) + 0.5)


def media_feature(h, valores):
    """(feature media, eventos) de un histograma, sin el primer ni el último canal."""
    h = np.asarray(h, float)
    w = h[1:-1]
    n = float(w.sum())
    if n <= 0:
        return None, 0
    return float((w * valores[1:-1]).sum() / n), int(n)


class BaseDinamica:
    """El estado de la ley entre pasos. Ver el docstring del módulo."""

    def __init__(self, caida, ganancia_mca, b0, kappa=1.0, fs=FS_HZ,
                 suavizado_s=SUAVIZADO_S, tope=TOPE_ADU):
        if not ganancia_mca or ganancia_mca <= 0:
            raise ValueError(f'ganancia_mca = {ganancia_mca}: hace falta la ganancia del '
                             'MCA en cuentas de la feature por ADU (medirla con el lazo '
                             'digital)')
        self.caida = float(caida)
        self.ganancia_mca = float(ganancia_mca)
        self.b0 = int(b0)
        self.kappa = float(kappa)
        self.fs = float(fs)
        self.suavizado_s = float(suavizado_s)
        self.tope = float(tope)
        self.lam = None              # λ̂ suavizada (Hz)
        self.a = None                # ⟨A⟩ suavizada (ADU)
        self.delta_b = 0.0
        self.pasos = 0
        self.reinicios = 0
        self.fijar_a = False         # True: ⟨A⟩ no se toma del histograma (cebado)
        self._prev = None            # (arribos, segundos, histograma)

    def reiniciar(self):
        """Se olvida de la referencia (los contadores y el histograma del paso anterior)
        pero no de la base: después de un Clear la base sigue donde estaba."""
        self._prev = None
        self.reinicios += 1

    def _ley(self, tau):
        d = self.kappa * self.caida * (self.lam / self.fs) * self.a * float(tau)
        self.delta_b = float(min(max(d, -self.tope), self.tope))

    def cebar(self, lam, a, tau):
        """Arranca la ley en λ y ⟨A⟩ conocidos (los del estímulo, en una campaña), así
        el espectro no junta el transitorio del promedio. Los pasos siguientes la
        llevan a lo medido."""
        self.lam, self.a = float(lam), float(a)
        self._ley(tau)
        return self.estado()

    def base(self):
        b = round(self.b0 + self.delta_b)
        return int(min(max(b, BASE_MIN), BASE_MAX))

    def estado(self):
        return dict(b0=self.b0, delta_b=self.delta_b, base=self.base(), kappa=self.kappa,
                    caida=self.caida, ganancia_mca=self.ganancia_mca,
                    lam_hz=self.lam, a_adu=self.a, pasos=self.pasos,
                    reinicios=self.reinicios)

    def paso(self, cnt, hist, valores, tau):
        """Un paso con los contadores (`mca_read_counters`), el histograma 1D y la
        feature de cada canal (`valores_de_canales`). Devuelve `estado()`."""
        arr, seg = arribos_y_tiempo(cnt)
        h = np.asarray(hist, np.int64)
        prev, self._prev = self._prev, (arr, seg, h.copy())
        if prev is None:
            return self.estado()
        darr, dseg, dh = arr - prev[0], seg - prev[1], h - prev[2]
        if darr < 0 or dseg < 0 or (dh < 0).any():
            self.reiniciar()
            self._prev = (arr, seg, h.copy())
            return self.estado()
        if dseg <= 0:                # el MCA parado: nada nuevo
            return self.estado()
        alfa = 1.0 - math.exp(-dseg / self.suavizado_s) if self.suavizado_s > 0 else 1.0
        lam = darr / dseg
        self.lam = lam if self.lam is None else self.lam + alfa * (lam - self.lam)
        f, n = media_feature(dh, valores)
        if f is not None and n >= EVENTOS_MIN and not self.fijar_a:
            a = f / self.ganancia_mca
            self.a = a if self.a is None else self.a + alfa * (a - self.a)
        if self.a is not None:
            self._ley(tau)
        self.pasos += 1
        return self.estado()


# =============================================================================
# Los centroides de `mca.ganancia` y `base.verificar`
# =============================================================================

def centroides_lineas(hist, n=2, hueco=3):
    """Las n líneas de un espectro de pulsos aislados, sin continuo, de menor a mayor:
    cada una es el tramo ocupado alrededor de un máximo (huecos de hasta `hueco` canales
    vacíos adentro), sin el primer ni el último canal (con zoom, ahí se junta lo de
    afuera). Por línea: centroide (canales fraccionarios), su error y las cuentas. Es
    el de `campanas/run_meritos_pulsos.py`."""
    h = np.asarray(hist, float).copy()
    h[0] = h[-1] = 0
    out = []
    for _ in range(int(n)):
        i = int(np.argmax(h))
        if h[i] <= 0:
            break
        lo = hi = i
        while lo > 0 and h[max(lo - hueco - 1, 0):lo].any():
            lo -= 1
        while hi < h.size - 1 and h[hi + 1:hi + hueco + 2].any():
            hi += 1
        c = np.arange(lo, hi + 1)
        w = h[lo:hi + 1]
        mu = float((c * w).sum() / w.sum())
        var = float(((c - mu) ** 2 * w).sum() / w.sum())
        out.append(dict(centroide=mu, error=math.sqrt((var + 1 / 12) / w.sum()),
                        n=int(w.sum())))
        h[lo:hi + 1] = 0
    return sorted(out, key=lambda d: d['centroide'])


def centroide_en(hist, c, ancho=0.10):
    """El centroide a ±`ancho` (fracción) del canal c: el de una línea de referencia en
    un espectro con continuo (el apilamiento a tasa alta)."""
    lo = max(1, int(math.floor(c * (1 - ancho))))
    hi = min(len(hist) - 2, int(math.ceil(c * (1 + ancho))))
    w = np.asarray(hist[lo:hi + 1], float)
    if w.sum() == 0:
        return None
    return float((np.arange(lo, hi + 1) * w).sum() / w.sum())


def kappa_optimo(s_fija, s_dinamica, kappa):
    """El κ que anula el corrimiento, con el corrimiento lineal en κ: s(κ) = s_f + κ·u,
    y la corrida con la dinámica en `kappa` da u. None si no hay corrimiento que medir."""
    if s_fija is None or s_dinamica is None:
        return None
    u = (s_dinamica - s_fija) / float(kappa) if kappa else 0.0
    if abs(u) < 1e-9:
        return None
    return float(-s_fija / u)
