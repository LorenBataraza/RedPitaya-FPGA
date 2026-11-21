"""El canal analógico del servidor `--fake`: la BRAM con el generador y un canal de
juguete, para que la pestaña «Calibration» y sus pruebas anden sin placa.

`CapturaFalsa` es `canal.CapturaBram` entera (los registros del OSC, del multitrigger y
del generador son los de los fakes de `mca_remote`, por el backend de callbacks, así
que guardar y restaurar se prueban de verdad); sólo cambia lo que la BRAM tendría
adentro, que sale de acá:

- `traza_generador`: lo que pone el generador, con los instantes de disparo de libmca
  (`generadores.predecir`, los mismos xorshift que el RTL), las alturas de la tabla, la
  caída de DECAE, la base y el ruido. El mismo estímulo da la misma traza: la captura
  con el lazo y la sin él son el mismo instante, como en la placa.
- `CanalFalso`: y = offset + g·(h * x) + Σ d_i (p_i * x) + ruido, con h dos polos
  rápidos y un retardo, y dos polos lentos CONOCIDOS (`caida`), que el ajuste tiene que
  recuperar.
- el diezmado con promedio arranca en una fase al azar, como el de la placa, que corre
  libre respecto del arranque del generador.

No es un modelo de la placa: sus números no se comparan con nada.
"""
import numpy as np

from API import canal as C

FS_HZ = C.FS_HZ


class CanalFalso:
    """El canal de juguete. `caida` es Σd/g, lo que la medición lenta tiene que dar."""

    DEFECTO = dict(ganancia=0.95, offset=-12.0, lat=9, polo=0.45,
                   d=(-0.025, -0.045), lentos=(400.0, 1600.0), ruido=4.0,
                   diafonia=0.002, offset2=-20.0, ruido2=4.0)

    def __init__(self, semilla=0, **kw):
        malos = set(kw) - set(self.DEFECTO)
        if malos:
            raise ValueError(f'canal falso: {sorted(malos)} no existen ({sorted(self.DEFECTO)})')
        self.p = dict(self.DEFECTO, **kw)
        self._rng = np.random.default_rng(semilla)
        a = float(self.p['polo'])
        h1 = (1.0 - a) * a ** np.arange(64)
        self.h = np.convolve(h1, h1)[:96]
        self.h /= self.h.sum()

    @property
    def caida(self):
        return float(sum(self.p['d'])) / float(self.p['ganancia'])

    def limpio(self, x):
        """La parte determinista de IN1: g·(h * x) retardado más los polos lentos."""
        x = np.asarray(x, float)
        p = self.p
        v = np.convolve(x, self.h)[:x.size]
        lat = int(p['lat'])
        if lat:
            v = np.concatenate([np.zeros(lat), v[:x.size - lat]])
        y = p['ganancia'] * v
        for di, tau in zip(p['d'], p['lentos']):
            y = y + float(di) * C.pasabajos(np.concatenate([np.zeros(lat), x[:x.size - lat]])
                                            if lat else x, tau)
        return y

    def aplicar(self, x, canal=0):
        """IN1 (canal 0) o IN2 (canal 1), a ritmo pleno, en cuentas (float)."""
        p = self.p
        n = np.asarray(x).size
        if canal == 0:
            return p['offset'] + self.limpio(x) + p['ruido'] * self._rng.standard_normal(n)
        return (p['offset2'] + p['diafonia'] * self.limpio(x)
                + p['ruido2'] * self._rng.standard_normal(n))

    def ruido(self, n, canal=0):
        """Una entrada sin señal (con el lazo, IN2; o el piso)."""
        p = self.p
        off, s = (p['offset'], p['ruido']) if canal == 0 else (p['offset2'], p['ruido2'])
        return off + s * self._rng.standard_normal(int(n))


def traza_generador(cfg, tabla, n):
    """Las `n` muestras que pone el generador desde que arranca, con la config entera
    (`generadores.config`) y la tabla."""
    from scipy.signal import lfilter
    from API import generadores as G
    n = int(n)
    disp = {k: cfg[k] for k in G.CLAVES_DISPAROS}
    tasa = max(G.tasa(**disp), 1.0)
    n_max = int(tasa * n / FS_HZ * 2) + 16
    if disp.get('n'):
        n_max = min(n_max, int(disp['n']))
    t = np.asarray(G.predecir(n, 0, n_max=n_max, **disp), np.int64)
    t = t[(t >= 0) & (t < n)]
    tabla = np.asarray(tabla, np.int64)
    if cfg.get('amp_aleat'):
        rng = np.random.default_rng(int(cfg.get('semilla', 0)) + 7)
        llena = np.zeros(G.N_TABLA, np.int64)
        llena[:min(tabla.size, G.N_TABLA)] = tabla[:G.N_TABLA]
        amp = llena[rng.integers(0, G.N_TABLA, t.size)]
    else:
        k = int(cfg.get('amp_n') or tabla.size) or 1
        amp = tabla[np.arange(t.size) % min(k, tabla.size)]
    imp = np.zeros(n)
    np.add.at(imp, t, amp.astype(float))
    r = float(cfg.get('decae', 0)) / 65536.0
    x = lfilter([1.0], [1.0, -r], imp) if r > 0 else imp
    x = x + float(cfg.get('base', 0))
    if cfg.get('ruido'):
        rng = np.random.default_rng(int(cfg.get('semilla', 0)) + 11)
        x = x + G.sigma_ruido(int(cfg.get('ruido_sh', 0))) * rng.standard_normal(n)
    return np.clip(np.round(x), G.AMP_MIN, G.AMP_MAX)


def diezmar(v, dec, fase):
    """El promedio de `dec` muestras, empezando en `fase`."""
    v = np.asarray(v, float)[int(fase):]
    m = v.size // int(dec)
    return v[:m * int(dec)].reshape(m, int(dec)).mean(axis=1)


class CapturaFalsa(C.CapturaBram):
    """`CapturaBram` sobre los fakes, con lo que la BRAM tendría adentro sintetizado."""

    ESPERA_PRE_S = 0.0
    PERIODO_EXTERNO = 62500      # ciclos: la cuadrada "del Rigol", de 2 kHz
    ALTO_EXTERNO = 2000.0

    def __init__(self, osc, mt, gen=None, ig=None, canal=None, semilla=0):
        super().__init__(osc, mt, gen, ig)
        self.canal = canal if canal is not None else CanalFalso(semilla)
        self._rng = np.random.default_rng(semilla + 1)

    def _esperar_y_leer(self, pre, post, dec, gen=None, tabla=None, lazo=False,
                        externa=False):
        pre, post, dec = int(pre), int(post), int(dec)
        n = pre + post
        fase = int(self._rng.integers(0, dec)) if dec > 1 else 0
        largo = (n + 1) * dec
        if externa:
            t0 = int(self._rng.integers(0, self.PERIODO_EXTERNO))
            t = np.arange(largo) + t0
            x = np.where((t // (self.PERIODO_EXTERNO // 2)) % 2 == 0, self.ALTO_EXTERNO,
                         -self.ALTO_EXTERNO)
            y0, y1 = self.canal.aplicar(x, 0), self.canal.aplicar(x, 1)
        else:
            antes = pre * dec + fase
            x = np.concatenate([np.zeros(antes), traza_generador(gen, tabla, largo - antes)])
            if lazo:
                y0, y1 = x, self.canal.ruido(largo, 1)
            else:
                y0, y1 = self.canal.aplicar(x, 0), self.canal.aplicar(x, 1)
            fase = 0                 # el disparo es el primer pulso: ya está en `antes`
        a = diezmar(y0, dec, fase)[:n] if dec > 1 else np.asarray(y0, float)[:n]
        b = diezmar(y1, dec, fase)[:n] if dec > 1 else np.asarray(y1, float)[:n]
        lim = (C.AMP_MIN, C.AMP_MAX)
        return dict(buf=np.clip(np.round(a), *lim).astype(np.int16),
                    buf1=np.clip(np.round(b), *lim).astype(np.int16), wp_trig=0)
