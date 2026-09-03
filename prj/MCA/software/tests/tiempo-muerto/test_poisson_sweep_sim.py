#!/usr/bin/env python3
"""`sweep_rate_poisson` contra un MCA SIMULADO, sin hardware.

Dos cosas a la vez:

  1. Smoke test del barrido entero (estimulo -> adquisicion por trozos con
     recarga de semilla -> contadores -> analisis -> .npz), que es donde se
     rompen las campañas: un ValueError a mitad del barrido cuesta una sesion
     de laboratorio.
  2. Validacion de la MATEMATICA. El MCA simulado es un servidor K=1 con tiempo
     muerto `tau` fijo alimentado por LA MISMA realizacion Poisson que arma el
     generador. Si el barrido esta bien escrito, tiene que recuperar
     `P_loss = rho/(1+rho)`; si diera la curva de escalones (`1-1/ceil(rho)`)
     seria señal de que el estimulo perdio su aleatoriedad en algun paso.

Uso:
    python3 test_poisson_sweep_sim.py
"""
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_AQUI, '..', '..'))   # -> software/

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
    """Servidor K=1 con tiempo muerto fijo `tau_s`, no paralizable.

    Es el modelo que se quiere contrastar: cada evento aceptado ocupa el
    extractor `tau_s`; lo que llegue mientras tanto se cuenta en `dropped` y se
    descarta (no extiende el tiempo muerto).
    """

    def __init__(self, gen, tau_s=2.3e-6):
        self.gen = gen
        self.tau = tau_s
        self.cnt = dict(total=0, accepted=0, dropped=0, pileup=0,
                        rej_amp=0, rej_psd=0,
                        realtime_s=0.0, livetime_s=0.0, deadtime_s=0.0)

    def configure(self, **cfg):
        pass

    def _servir(self, t_arr):
        """Filtro de tiempo muerto: devuelve (aceptados, perdidos)."""
        libre_en = -np.inf
        acc = 0
        for t in t_arr:
            if t >= libre_en:
                acc += 1
                libre_en = t + self.tau
        return acc, t_arr.size - acc

    def acquire_chunks(self, seconds, chunk_s, on_chunk=None):
        self.cnt = {k: (0 if isinstance(v, int) else 0.0)
                    for k, v in self.cnt.items()}
        n = max(1, int(round(seconds / max(chunk_s, 1e-3))))
        for k in range(n):
            info = self.gen.info
            base = self.gen.arribos_s()
            T = info['T_ciclo_s']
            n_ciclos = max(1, int(chunk_s / T))
            # el patron se REPITE: los arribos del trozo son el ciclo tileado
            t = (np.tile(base, n_ciclos)
                 + np.repeat(np.arange(n_ciclos) * T, base.size))
            acc, drop = self._servir(t)
            self.cnt['total']    += acc
            self.cnt['accepted'] += acc
            self.cnt['dropped']  += drop
            self.cnt['realtime_s'] += n_ciclos * T
            self.cnt['deadtime_s'] += acc * self.tau
            self.cnt['livetime_s'] += n_ciclos * T - acc * self.tau
            if on_chunk is not None and k < n - 1:
                on_chunk(k)
        return np.zeros(4096, dtype=np.int64), None, dict(self.cnt)


def test_barrido_recupera_el_modelo():
    print('\n== barrido completo contra un servidor K=1 simulado ==')
    tau = 2.3e-6
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
          len(filas) == 6, f'{len(filas)} puntos')
    check('recargo una realizacion por trozo',
          gen.n_cargas >= 6 * 8, f'{gen.n_cargas} cargas de ARB')

    rho = np.array([f['rho'] for f in filas])
    pl  = np.array([f['p_loss'] for f in filas])
    e_poisson  = np.abs(pl - rho / (1 + rho)).mean()
    e_periodico = np.abs(pl - (1 - 1 / np.maximum(np.ceil(rho), 1))).mean()
    print(f'    rho     medido   Poisson   periodico')
    for f in filas:
        print(f'    {f["rho"]:5.3f}   {100*f["p_loss"]:6.2f}%  '
              f'{100*f["p_loss_poisson"]:6.2f}%   {100*f["p_loss_periodico"]:6.2f}%')
    check('las perdidas siguen al modelo de POISSON', e_poisson < 0.02,
          f'|error| medio = {100*e_poisson:.2f} pp')
    check('y NO al de arribos periodicos', e_periodico > 2 * e_poisson,
          f'|error| periodico = {100*e_periodico:.2f} pp')
    check('se pierde algo incluso a rho chico (lo que el tren periodico oculta)',
          pl[0] > 0.5 * rho[0], f'a rho={rho[0]:.3f} se perdio {100*pl[0]:.2f}%')

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


def test_saltea_lo_imposible():
    print('\n== a tasa baja el punto se saltea, no revienta ==')
    gen = GenFalso()
    wrapper, orig = _apply_espia(gen)
    rg.apply_poisson_train = wrapper
    try:
        mca = McaFalso(gen, tau_s=2.3e-6)
        # 200 Hz con pulsos de 2 us: el ARB no puede dibujarlo (dt = 19 us)
        res = tb.sweep_rate_poisson(mca, gen, rates=(200.0, 5e4), tau_s=2.3e-6,
                                    seconds=1.0, chunk_s=0.25, width_s=2e-6,
                                    n_events=64, outdir=None)
    finally:
        rg.apply_poisson_train = orig
    check('salteo el punto imposible y midio el otro',
          len(res['filas']) == 1 and abs(res['filas'][0]['rate_hz'] - 5e4) < 1,
          f'{[f["rate_hz"] for f in res["filas"]]}')


if __name__ == '__main__':
    print('smoke test de sweep_rate_poisson (MCA simulado)')
    test_barrido_recupera_el_modelo()
    test_saltea_lo_imposible()
    print('\nRESULT:', 'PASS' if not FALLAS else f'FAIL ({len(FALLAS)}): {FALLAS}')
    sys.exit(1 if FALLAS else 0)
