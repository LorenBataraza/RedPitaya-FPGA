#!/usr/bin/env python3
"""`sweep_rate_poisson` contra un MCA SIMULADO, sin hardware.

Dos cosas a la vez:

  1. Smoke test del barrido entero (estimulo -> adquisicion por trozos con
     recarga de semilla -> contadores -> analisis -> .npz), que es donde se
     rompen las campañas: un ValueError a mitad del barrido cuesta una sesion
     de laboratorio.
  2. Validacion de la MATEMATICA. El MCA simulado son `n_acc` ranuras sin cola
     con tiempo de ocupación `tau` fijo, alimentadas por LA MISMA realizacion
     Poisson que arma el generador. Si el barrido esta bien escrito, tiene que
     recuperar Erlang B (`rho/(1+rho)` con una ranura) y sacar el tau de
     `t_ocup_s`; si diera la curva de escalones (`1-1/ceil(rho)`) seria señal
     de que el estimulo perdio su aleatoriedad en algun paso.

Uso:
    python3 test_poisson_sweep_sim.py
"""
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.dirname(_AQUI))   # campanas/, donde vive testbench_mca

import testbench_mca as tb        # noqa: E402
import rigol_dg4162 as rg         # noqa: E402

FS_HZ = 125e6
FALLAS = []


def check(nombre, ok, detalle=''):
    print(f'  [{"PASS" if ok else "FAIL"}] {nombre}' + (f'  {detalle}' if detalle else ''))
    if not ok:
        FALLAS.append(nombre)
    return ok


class GenFalso:
    """Registra lo que se le pide y re-deriva los arribos de la realizacion."""

    def __init__(self):
        self.info = None
        self.n_cargas = 0

    def load_arb(self, wave, ch=1, normalize=True, check_errors=False):
        self.wave = wave
        self.n_cargas += 1

    def set_arb(self, ch=1, freq_hz=1e3, amp_vpp=1.0, offset_v=0.0, **kw):
        self.freq_hz = freq_hz

    def output(self, ch, on, **kw):
        pass

    def disable_burst(self, ch=1, **kw):
        pass

    def arribos_s(self):
        """Instantes de arribo de la realizacion actual, dentro de un ciclo."""
        i = self.info
        rng = np.random.default_rng(i['seed'])
        n = i['n_events'] if i['fixed_n'] else int(rng.poisson(i['rate_hz'] * i['T_ciclo_s']))
        return np.sort(rng.uniform(0.0, i['n_pts'], n)) * i['dt_s']


def _apply_espia(gen_falso):
    """Envuelve apply_poisson_train para quedarse con el `info`."""
    orig = rg.apply_poisson_train

    def wrapper(gen, *a, **kw):
        info = orig(gen, *a, **kw)
        gen.info = info
        return info
    return wrapper, orig


class McaFalso:
    """`n_acc` ranuras sin cola, cada una ocupada `tau_s` por ventana: Erlang B.

    Es el modelo que se quiere contrastar, con los contadores del MCA2: cada
    disparo cuenta en `cross`; si encuentra ranura libre la ocupa `tau_s`
    (`open`), si no se pierde (`lost_active`: sin publicador, todas están
    midiendo). `t_ocup_s[j]` es el tiempo con j ranuras ocupadas, como lo mide
    el RTL, que es de donde el barrido saca el tau sin asumirlo.
    """

    N_ACC = 4

    def __init__(self, gen, tau_s=3.2e-6):
        self.gen = gen
        self.tau = tau_s
        self.n = 1

    def configure(self, **cfg):
        self.n = int(cfg.get('n_acc', 1))

    def _servir(self, t_arr):
        """Las ranuras: devuelve (abiertos, perdidos, intervalos ocupados)."""
        libre = [-np.inf] * self.n
        abiertos, ocupado = 0, []
        for t in t_arr:
            k = int(np.argmin(libre))
            if libre[k] <= t:
                libre[k] = t + self.tau
                abiertos += 1
                ocupado.append((t, t + self.tau))
        return abiertos, t_arr.size - abiertos, ocupado

    def _ocupacion(self, ocupado, t0, t1):
        ev = sorted([(max(a, t0), 1) for a, b in ocupado if b > t0]
                    + [(min(b, t1), -1) for a, b in ocupado if b > t0])
        occ = np.zeros(self.N_ACC + 1)
        j, tp = 0, t0
        for x, d in ev:
            occ[j] += x - tp
            j, tp = j + d, x
        occ[j] += t1 - tp
        return occ

    def acquire_chunks(self, seconds, chunk_s, on_chunk=None):
        cnt = dict(total=0, accepted=0, dropped=0, pileup=0, rej_amp=0,
                   rej_psd=0, cross=0, open=0, lost_active=0, lost_veto=0,
                   realtime_s=0.0, livetime_s=0.0, deadtime_s=0.0)
        t_ocup = np.zeros(self.N_ACC + 1)
        n = max(1, int(round(seconds / max(chunk_s, 1e-3))))
        for k in range(n):
            info = self.gen.info
            base = self.gen.arribos_s()
            T = info['T_ciclo_s']
            n_ciclos = max(1, int(chunk_s / T))
            # el patron se REPITE: los arribos del trozo son el ciclo tileado
            t = (np.tile(base, n_ciclos)
                 + np.repeat(np.arange(n_ciclos) * T, base.size))
            acc, perd, ocupado = self._servir(t)
            occ = self._ocupacion(ocupado, 0.0, n_ciclos * T)
            t_ocup += occ
            cnt['cross'] += int(t.size)
            cnt['open'] += acc
            cnt['lost_active'] += perd
            cnt['total'] += acc
            cnt['accepted'] += acc
            cnt['realtime_s'] += n_ciclos * T
            cnt['deadtime_s'] += float(occ[1:].sum())
            cnt['livetime_s'] += float(occ[:self.n].sum())
            if on_chunk is not None and k < n - 1:
                on_chunk(k)
        cnt['t_ocup_s'] = t_ocup.tolist()
        return np.zeros(4096, dtype=np.int64), None, cnt


def test_barrido_recupera_el_modelo():
    print('\n== barrido completo contra 1, 2 y 4 ranuras simuladas ==')
    n0 = len(FALLAS)
    tau = 3.2e-6
    gen = GenFalso()
    wrapper, orig = _apply_espia(gen)
    rg.apply_poisson_train = wrapper
    try:
        mca = McaFalso(gen, tau_s=tau)
        out = os.path.join(_AQUI, '_out_poisson_sim')
        res = tb.sweep_rate_poisson(mca, gen, ch=1,
                                    rhos=(0.02, 0.05, 0.1, 0.2, 0.5, 0.9),
                                    tau_s=tau, seconds=2.0, chunk_s=0.25,
                                    width_s=2e-6, n_events=64, outdir=out)
    finally:
        rg.apply_poisson_train = orig

    filas = res['filas']
    check('el barrido no se rompio y midio todos los puntos',
          len(filas) == 6 * 3, f'{len(filas)} puntos')
    check('recargo una realizacion por trozo',
          gen.n_cargas >= 6 * 3 * 8, f'{gen.n_cargas} cargas de ARB')

    print(f'    n   rho     medido   Erlang    periodico')
    for f in filas:
        print(f'    {f["n_acc"]}   {f["rho"]:5.3f}   {100*f["p_loss"]:6.2f}%  '
              f'{100*f["p_loss_poisson"]:6.2f}%   {100*f["p_loss_periodico"]:6.2f}%')
    check('el tau medido de t_ocup es el del servicio',
          all(abs(f['tau_med_s'] - tau) < 0.02 * tau for f in filas),
          f"{[round(f['tau_med_s'] * 1e6, 3) for f in filas[:3]]} us")
    for n in (1, 2, 4):
        fs = [f for f in filas if f['n_acc'] == n]
        rho = np.array([f['rho'] for f in fs])
        pl = np.array([f['p_loss'] for f in fs])
        e_erl = np.abs(pl - np.array([f['p_loss_poisson'] for f in fs])).mean()
        check(f'n_acc={n}: las pérdidas siguen a Erlang B', e_erl < 0.02,
              f'|error| medio = {100*e_erl:.2f} pp')
        if n == 1:
            e_per = np.abs(pl - (1 - 1 / np.maximum(np.ceil(rho), 1))).mean()
            check('y con una ranura NO a los arribos periódicos', e_per > 2 * e_erl,
                  f'|error| periódico = {100*e_per:.2f} pp')
            check('se pierde algo incluso a rho chico (lo que el tren periódico oculta)',
                  pl[0] > 0.5 * rho[0], f'a rho={rho[0]:.3f} se perdió {100*pl[0]:.2f}%')
    p1 = max(f['p_loss'] for f in filas if f['n_acc'] == 1)
    p4 = max(f['p_loss'] for f in filas if f['n_acc'] == 4)
    check('cuatro ranuras pierden mucho menos que una', p4 < 0.2 * p1,
          f'{100*p4:.2f} % contra {100*p1:.2f} %')

    npz = os.path.join(_AQUI, '_out_poisson_sim', 'sweep_rate_poisson.npz')
    check('guardo el .npz', os.path.exists(npz))
    if os.path.exists(npz):
        z = np.load(npz)
        check('el .npz trae las columnas del grafico',
              all(k in z.files for k in ('rho', 'p_loss', 'p_loss_poisson',
                                         'p_loss_periodico', 'valido')),
              str(sorted(z.files)[:6]) + '...')
        tb.plot_all(os.path.dirname(npz))
        png = os.path.join(os.path.dirname(npz), 'poisson_loss.png')
        check('plot_all dibujo la curva', os.path.exists(png)
              and os.path.getsize(png) > 5000)
    assert len(FALLAS) == n0, FALLAS[n0:]


def test_saltea_lo_imposible():
    print('\n== a tasa baja el punto se saltea, no revienta ==')
    n0 = len(FALLAS)
    gen = GenFalso()
    wrapper, orig = _apply_espia(gen)
    rg.apply_poisson_train = wrapper
    try:
        mca = McaFalso(gen, tau_s=3.2e-6)
        # 200 Hz con pulsos de 2 us: el ARB no puede dibujarlo (dt = 19 us)
        res = tb.sweep_rate_poisson(mca, gen, rates=(200.0, 5e4), tau_s=3.2e-6,
                                    seconds=1.0, chunk_s=0.25, width_s=2e-6,
                                    n_events=64, n_accs=(1,), outdir=None)
    finally:
        rg.apply_poisson_train = orig
    check('salteo el punto imposible y midio el otro',
          len(res['filas']) == 1 and abs(res['filas'][0]['rate_hz'] - 5e4) < 1,
          f'{[f["rate_hz"] for f in res["filas"]]}')
    assert len(FALLAS) == n0, FALLAS[n0:]


if __name__ == '__main__':
    print('smoke test de sweep_rate_poisson (MCA simulado)')
    test_barrido_recupera_el_modelo()
    test_saltea_lo_imposible()
    print('\nRESULT:', 'PASS' if not FALLAS else f'FAIL ({len(FALLAS)}): {FALLAS}')
    sys.exit(1 if FALLAS else 0)
