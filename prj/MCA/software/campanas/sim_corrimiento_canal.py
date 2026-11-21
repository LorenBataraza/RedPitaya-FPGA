#!/usr/bin/env python3
"""El corrimiento de la línea con la tasa en el canal analógico, en la placa simulada con
el canal medido: de dónde sale (docs/resultados_meritos_gen_pulsos.md §2.5).

Corre la etapa tasa de `run_meritos_pulsos.py` (Poisson, ASG, 3 ranuras, trapecio, base
fija) en la placa simulada dos veces:

  con_lentos   el canal de la placa (`canal_analogico.CanalMedido`): el FIR y los tres
               polos lentos ajustados a las capturas de la BRAM, con el ruido del piso;
  sin_lentos   el mismo canal ajustado sin los polos lentos: sin la caída lenta.

En la corrida con los polos, cada punto se mide además sobre la misma traza sin la
parte lenta, x − Σ d_i (p_i * x). La diferencia de F_TRAP, evento por evento, es lo que
la caída lenta le hace a cada amplitud; contra la base lenta en el disparo da cuánto
pasa de la base a la amplitud con cada forma del banco, que el trapecio con polo-cero
predice como (k + m)/τ.

    python3 campanas/sim_corrimiento_canal.py datos/sim_corrimiento_canal \\
        [--canal datos/fidelidad_2026-11-14_analogico/canal.npz]

Deja `con_lentos/meritos.json` y `sin_lentos/meritos.json` (los de la campaña) y
`formas.json`: por punto, la base lenta media en los disparos y, por forma, la fracción
de los eventos de las dos líneas que la usan, la pendiente de la diferencia contra la
base y la diferencia media. La figura es `meritos_corrimiento_canal`
(docs/figuras/meritos/figuras_meritos.py).
"""
import argparse
import json
import os
import sys
import time

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)                                   # software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.join(_RAIZ, 'monte-carlo'))

import canal_analogico as CA                                     # noqa: E402
import replica_mca2 as r2                                        # noqa: E402
import run_meritos_pulsos as R                                   # noqa: E402

CANAL = os.path.join(_RAIZ, 'datos', 'fidelidad_2026-11-14_analogico', 'canal.npz')
VENTANA = 0.15        # ±15 % de la línea: los eventos de la línea (el centroide de la figura)
N_MIN_AJUSTE = 30     # eventos mínimos de una forma para ajustar su pendiente


class PlacaPorEvento(R.PlacaSimulada):
    """La placa simulada que, en cada punto, mide también la traza sin la parte lenta
    del canal y guarda, por evento publicado en las dos, F_TRAP con y sin la parte
    lenta (en canales del espectro), la forma y la base lenta en el disparo."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.puntos = []

    def correr(self, gen, tabla, mca, disparo, espectros, base=False):
        out = super().correr(gen, tabla, mca, disparo, espectros, base)
        u = self.ultima
        t, trig = u['t'], u['medida']['trig']
        xg = np.concatenate([np.zeros(self.vp.PAD), np.asarray(t['dat'], float)])
        w = self.canal_sim.lenta(xg, 0)
        m2 = r2.medir(u['x'] - np.round(w).astype(np.int64), u['cfg'], trig=u['trig'])
        e1, e2 = u['medida']['eventos'], m2['eventos']
        comun, i1, i2 = np.intersect1d(e1['i'], e2['i'], return_indices=True)
        z = dict(espectros).get('trapecio', 0)
        zz, kk = R._zoom(z)
        canal = lambda e, i: self.vp.canal_1d(e['feat'][i, r2.F_TRAP], zz, kk,
                                              aw=self.h_aw).astype(float)
        seg = (int(t['trig'][-1]) + 1) / R.FS_HZ
        self.puntos.append(dict(
            n_in_hz=int(t['trig'].size) / seg,
            base_disparo=float(w[np.clip(trig, 0, w.size - 1)].mean()) if trig.size else 0.0,
            c1=canal(e1, i1), c2=canal(e2, i2),
            forma=e1['feat'][i1, r2.F_FORMA].astype(np.int64),
            w=w[np.clip(trig[comun], 0, w.size - 1)],
            formas=[(int(f[0]), int(f[1])) for f in r2.formas_en_uso(u['cfg'])]))
        return out


def argumentos(a, sub, extra=()):
    return [os.path.join(a.outdir, sub), '--simulada', '--modo', 'analogico',
            '--etapas', 'tasa', '--fuentes', 'asg', '--n-acc', '3',
            '--tasas', ','.join(f'{v:g}' for v in a.tasas), '--n-min', str(a.n_min),
            '--seg', str(a.seg), '--semilla', str(a.semilla), '--tau', f'{a.tau:g}',
            '--canal-medido', a.canal, *extra]


def por_forma(p, lineas, tau):
    """Para un punto: por forma, la fracción de los eventos de las líneas (por F_TRAP
    sin la parte lenta), la pendiente de c1 − c2 contra la base y la diferencia media."""
    en = np.zeros(p['c2'].size, bool)
    for L in lineas:
        en |= np.abs(p['c2'] - L) < VENTANA * L
    dc = p['c1'] - p['c2']
    out = []
    for q, (k, m) in enumerate(p['formas']):
        sel = en & (p['forma'] == q)
        n = int(sel.sum())
        pend = (float(np.polyfit(p['w'][sel], dc[sel], 1)[0])
                if n >= N_MIN_AJUSTE and np.ptp(p['w'][sel]) > 0 else None)
        out.append(dict(forma=q, k=k, m=m, l_tau=(k + m) / tau, n=n,
                        fraccion=n / max(int(en.sum()), 1), pendiente=pend,
                        delta_medio=float(dc[sel].mean()) if n else None,
                        base_media=float(p['w'][sel].mean()) if n else None))
    return dict(n_eventos=int(en.sum()), formas=out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('outdir')
    ap.add_argument('--canal', default=CANAL, help='el canal.npz de run_fidelidad_osc.py')
    ap.add_argument('--tasas', type=lambda s: [float(v) for v in s.split(',')],
                    default=list(R.TASAS))
    ap.add_argument('--n-min', type=int, default=3000)
    ap.add_argument('--seg', type=float, default=0.02)
    ap.add_argument('--tau', type=float, default=250.0)
    ap.add_argument('--semilla', type=int, default=1)
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)
    t0 = time.time()

    # Sin los polos lentos: la campaña tal cual.
    print('== sin los polos lentos', flush=True)
    rc = R.main(argumentos(a, 'sin_lentos', ('--sin-lentos',)))
    if rc:
        return rc

    # Con los polos lentos, y cada punto también sin la parte lenta.
    print('== con los polos lentos', flush=True)
    canal = CA.CanalMedido.desde_capturas(a.canal, semilla=a.semilla)
    placa = PlacaPorEvento(modo='analogico', canal=canal)
    rc = R.main(argumentos(a, 'con_lentos'), placa=placa)
    if rc:
        return rc

    with open(os.path.join(a.outdir, 'con_lentos', 'meritos.json')) as fh:
        mm = json.load(fh)
    lineas = mm['referencias']['tasa/asg']['trapecio']['lineas']
    filas = [r for r in mm['filas'] if r['etapa'] == 'tasa']
    puntos = []
    for r in sorted(filas, key=lambda r: r['tasa']):
        n_in = r['corridas'][0]['meritos']['n_in_hz']
        p = min(placa.puntos, key=lambda q: abs(q['n_in_hz'] / n_in - 1))
        if abs(p['n_in_hz'] / n_in - 1) > 1e-6:
            raise RuntimeError(f'{r["tasa"]:g}/s: sin el punto medido por evento')
        puntos.append(dict(tasa=r['tasa'], n_in_hz=n_in, base_disparo=p['base_disparo'],
                           **por_forma(p, lineas, a.tau)))
    res = dict(canal=canal.describir(), lineas=lineas, ventana=VENTANA, tau=a.tau,
               puntos=puntos)
    with open(os.path.join(a.outdir, 'formas.json'), 'w') as fh:
        json.dump(res, fh, indent=1)

    print('\n== de la base a la amplitud, por forma (con los polos lentos)')
    print('  tasa [k/s]  base [cuentas]  ' + '  '.join(
        f'k={f["k"]}: uso, pendiente' for f in puntos[0]['formas']))
    for p in puntos:
        txt = '  '.join(f'{100 * f["fraccion"]:5.1f} %, '
                        + (f'{f["pendiente"]:5.3f}' if f['pendiente'] is not None else '  —  ')
                        for f in p['formas'])
        print(f'  {p["n_in_hz"] / 1e3:9.0f}  {p["base_disparo"]:14.1f}  {txt}')
    print('  (k + m)/τ: ' + ', '.join(f'{f["l_tau"]:.3f}' for f in puntos[0]['formas']))
    print(f'\n{a.outdir}: sin_lentos/, con_lentos/ y formas.json ({time.time() - t0:.0f} s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
