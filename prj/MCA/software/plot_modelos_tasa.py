#!/usr/bin/env python3
"""Tasas medidas contra los modelos de tiempo muerto, con residuos.

Corre en la PC, sin hardware: usa lo ya medido.

Los tres modelos, todos con un solo servidor y sin cola (K=1, que es la
arquitectura actual: un evento a la vez, lo que llega mientras se procesa se
pierde). Cambia SOLO el proceso de arribos:

  D/D/1/1   (arribos PERIODICOS, = el Rigol en modo PULSE)
      m = n / ceil(n*tau)
      No pierde NADA mientras el periodo supere el servicio, y despues cae en
      escalones. Es el modelo del ESTIMULO que se uso en toda la campana.

  M/G/1/1   (arribos POISSON, = una fuente radiactiva)
      m = n / (1 + n*tau)          <- "no paralizable"
      Pierde a CUALQUIER tasa: P_loss = rho/(1+rho) -> rho cuando rho -> 0.

  paralizable (Poisson, cada arribo re-extiende el tiempo muerto)
      m = n * exp(-n*tau)

El punto del grafico: los datos medidos siguen al modelo PERIODICO y son
incompatibles con el de Poisson. Eso NO dice que el equipo no pierda eventos con
una fuente real — dice que el estimulo era periodico y que esa medicion de
eficiencia no se puede extrapolar a Poisson. Para eso hay que re-medir con
`poisson_train_wave` (ver run_poisson_loss.py / testbench_mca.sweep_rate_poisson).

Uso:
    python3 plot_modelos_tasa.py [--outdir datos/modelos_tasa]
                                 [--mca datos/mca_20260811_113136/sweep_rate.npz]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Datos medidos del LECTOR DE PYTHON (multitrigger + BRAM).
# Fuente: docs/multitrigger/arquitectura_adquisicion_software.md, "El techo real,
# medido end-to-end". Barrido de 4 s por punto, pulsos 0->1 V, ventana 8+24
# muestras, 2 canales. Estimulo PERIODICO (Rigol en modo PULSE).
# ---------------------------------------------------------------------------
LECTOR_N = np.array([500.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0])
LECTOR_M = np.array([500.0,  999.0, 1983.0, 2473.0,  3259.0,  3684.0])


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------

def m_periodico(n, tau):
    """D/D/1/1: un arribo cada 1/n, servicio tau. Escalones."""
    n = np.asarray(n, dtype=float)
    return n / np.maximum(np.ceil(n * tau), 1.0)


def m_poisson(n, tau):
    """M/G/1/1 = no paralizable. Es la curva de una fuente real."""
    n = np.asarray(n, dtype=float)
    return n / (1.0 + n * tau)


def m_paralizable(n, tau):
    n = np.asarray(n, dtype=float)
    return n * np.exp(-n * tau)


def m_periodico_disperso(n, tau_mu, tau_sigma, n_q=241):
    """D/G/1/1: arribos periodicos y servicio con DISPERSION.

    Con tau constante el modelo predice mesetas discretas, y el punto medido a
    20 kev/s (3684) cae JUSTO ENTRE dos de ellas (4000 con k=5, 3333 con k=6):
    ningun tau constante puede acertarle. Un servicio con dispersion reparte los
    eventos entre los dos escalones y promedia — que es lo que hace el ciclo
    real, donde `read`+`rearm`+`book` no tardan siempre lo mismo.

    Se promedia n/ceil(n*tau) sobre tau ~ Normal(mu, sigma) truncada en > 0.
    """
    n = np.asarray(n, dtype=float)[..., None]
    if tau_sigma <= 0:
        return m_periodico(n[..., 0], tau_mu)
    q = np.linspace(-3.5, 3.5, n_q)
    taus = tau_mu + tau_sigma * q
    w = np.exp(-0.5 * q ** 2)
    ok = taus > 0
    taus, w = taus[ok], w[ok]
    w = w / w.sum()
    return np.sum(w * (n / np.maximum(np.ceil(n * taus), 1.0)), axis=-1)


def ajustar2(modelo, n, m, mus, sigmas):
    """Ajuste en dos parametros por barrido (mismo criterio relativo)."""
    mejor = (np.inf, None, None)
    for mu in mus:
        for s in sigmas:
            e = float(np.sum(((m - modelo(n, mu, s)) / m) ** 2))
            if e < mejor[0]:
                mejor = (e, mu, s)
    return mejor[1], mejor[2], mejor[0]


def intervalo_tau(modelo, n, m, taus=None, tol=1.05):
    """Rango de tau indistinguible del mejor ajuste.

    El modelo de escalones es DISCONTINUO en tau: hay intervalos enteros que dan
    exactamente la misma prediccion, asi que un tau puntual es enganoso.
    """
    taus = np.logspace(-5, -3, 20001) if taus is None else np.asarray(taus)
    err = np.array([np.sum(((m - modelo(n, t)) / m) ** 2) for t in taus])
    dentro = taus[err <= tol * err.min()]
    return float(dentro.min()), float(dentro.max())


def ajustar(modelo, n, m, taus=None):
    """tau que minimiza el error RELATIVO (las tasas cubren decadas).

    Para el modelo periodico no sirve un ajuste analitico: `ceil` lo hace
    discontinuo en tau, asi que se barre.
    """
    taus = np.logspace(-7, -2, 40001) if taus is None else np.asarray(taus)
    err = np.array([np.sum(((m - modelo(n, t)) / m) ** 2) for t in taus])
    i = int(np.argmin(err))
    return float(taus[i]), float(err[i])


def resumen(nombre, modelo, n, m, tau):
    pred = modelo(n, tau)
    res = 100.0 * (m - pred) / m
    print(f'  {nombre:14s} tau = {tau*1e6:8.2f} us   '
          f'residuo |max| = {np.abs(res).max():6.2f} %   '
          f'rms = {np.sqrt((res**2).mean()):6.2f} %')
    return pred, res


# ---------------------------------------------------------------------------

def figura_lector(outdir):
    n, m = LECTOR_N, LECTOR_M
    print('\n=== lector de Python (estimulo PERIODICO) ===')
    tau_d, _ = ajustar(m_periodico, n, m)
    lo, hi = intervalo_tau(m_periodico, n, m)
    tau_p, _ = ajustar(m_poisson, n, m)
    tau_x, _ = ajustar(m_paralizable, n, m)
    mu_d, sg_d, _ = ajustar2(m_periodico_disperso, n, m,
                             np.linspace(150e-6, 400e-6, 126),
                             np.linspace(0.0, 200e-6, 81))
    _, res_d = resumen('periodico', m_periodico, n, m, tau_d)
    _, res_p = resumen('Poisson', m_poisson, n, m, tau_p)
    _, _ = resumen('paralizable', m_paralizable, n, m, tau_x)
    pred_g = m_periodico_disperso(n, mu_d, sg_d)
    res_g = 100.0 * (m - pred_g) / m
    print(f'  {"periodico+disp":14s} tau = {mu_d*1e6:8.2f} us +- {sg_d*1e6:.0f}   '
          f'residuo |max| = {np.abs(res_g).max():6.2f} %   '
          f'rms = {np.sqrt((res_g**2).mean()):6.2f} %')
    print(f'  tau indistinguibles con el modelo de escalones: '
          f'{lo*1e6:.0f} a {hi*1e6:.0f} us (es discontinuo en tau)')
    print(f'\n  {"n [ev/s]":>9} {"medido":>8} {"per+disp":>9} {"res":>7} '
          f'{"Poisson":>9} {"res":>7}   tau/T')
    for k in range(len(n)):
        print(f'  {n[k]:9.0f} {m[k]:8.0f} {pred_g[k]:9.0f} {res_g[k]:6.1f}% '
              f'{m_poisson(n[k], tau_p):9.0f} {res_p[k]:6.1f}%   {n[k]*mu_d:5.2f}')

    # La comparacion que importa: el MISMO tau (el que ajusta los datos) puesto
    # en el modelo de Poisson dice cuanto se perderia con una fuente real.
    pred_p_taud = m_poisson(n, mu_d)

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fino = np.logspace(np.log10(n.min() / 2), np.log10(n.max() * 2), 600)
    fig, ax = plt.subplots(2, 1, figsize=(9, 8), sharex=True,
                           gridspec_kw={'height_ratios': [2.2, 1]})

    ax[0].loglog(fino, fino, 'k:', lw=0.9, label='ideal (sin perdidas)')
    ax[0].loglog(fino, m_periodico(fino, tau_d), '-', color='tab:blue', lw=1,
                 alpha=0.55, label=f'periodico, tau constante = {tau_d*1e6:.0f} us')
    ax[0].loglog(fino, m_periodico_disperso(fino, mu_d, sg_d), '-',
                 color='tab:blue', lw=2.2,
                 label=f'periodico + dispersion: tau = {mu_d*1e6:.0f} $\\pm$ {sg_d*1e6:.0f} us')
    ax[0].loglog(fino, m_poisson(fino, tau_p), '--', color='tab:red',
                 label=f'Poisson M/G/1/1, tau={tau_p*1e6:.0f} us')
    ax[0].loglog(fino, m_paralizable(fino, tau_x), '-.', color='tab:green',
                 lw=1, label=f'paralizable, tau={tau_x*1e6:.0f} us')
    ax[0].loglog(n, m, 'ko', ms=8, label='medido')
    # el punto que ningun tau constante puede acertar
    ax[0].annotate('cae ENTRE dos escalones\n(k=5 -> 4000, k=6 -> 3333)',
                   xy=(n[-1], m[-1]), xytext=(n[-1] * 0.28, m[-1] * 0.35),
                   fontsize=7.5, arrowprops=dict(arrowstyle='->', lw=0.8))
    ax[0].set_ylabel('tasa registrada [ev/s]')
    ax[0].set_title('Lector de Python — tasa medida y modelos de tiempo muerto\n'
                    '(estimulo PERIODICO: es el modelo D/D/1/1 el que aplica)')
    ax[0].grid(True, which='both', alpha=0.3)
    ax[0].legend(fontsize=8, loc='upper left')

    ax[1].semilogx(n, res_d, 'o-', color='tab:blue', alpha=0.5,
                   label='vs periodico (tau constante)')
    ax[1].semilogx(n, res_g, 'o-', color='tab:blue', lw=2,
                   label='vs periodico + dispersion')
    ax[1].semilogx(n, res_p, 's--', color='tab:red', label='vs Poisson')
    ax[1].axhline(0, color='k', lw=0.8)
    ax[1].set_xlabel('tasa incidente [ev/s]')
    ax[1].set_ylabel('residuo  (medido-modelo)/medido  [%]')
    ax[1].grid(True, which='both', alpha=0.3)
    ax[1].legend(fontsize=8)

    fig.tight_layout()
    p = os.path.join(outdir, 'modelos_tasa_lector.png')
    fig.savefig(p, dpi=130, bbox_inches='tight'); plt.close(fig)
    print(f'  -> {p}')

    print(f'\n  Con el tau ajustado ({mu_d*1e6:.0f} us), una fuente de Poisson daria:')
    for lam in (500, 2000, 5000):
        rho = lam * mu_d
        print(f'    {lam:6d} ev/s: rho={rho:5.3f}  perdida {100*rho/(1+rho):5.1f} %  '
              f'(el tren periodico dio '
              f'{100*(1-m_periodico_disperso(np.array([lam]), mu_d, sg_d)[0]/lam):5.1f} %, '
              f'y la tasa registrada caeria de {lam*1.0:.0f} a {pred_p_taud[0]*0+lam/(1+rho):.0f} ev/s)')
    return dict(tau_periodico=tau_d, tau_periodico_lo=lo, tau_periodico_hi=hi,
                tau_disperso_mu=mu_d, tau_disperso_sigma=sg_d,
                tau_poisson=tau_p, tau_paralizable=tau_x,
                res_periodico=res_d, res_disperso=res_g, res_poisson=res_p)


def figura_mca(outdir, npz_path):
    if not os.path.exists(npz_path):
        print(f'\n(sin datos del MCA en {npz_path})')
        return None
    z = np.load(npz_path)
    n, m = z['r_in'], z['r_out']
    ok = (n > 0) & (m > 0)
    n, m = n[ok], m[ok]
    live = z['livetime_frac'][ok] if 'livetime_frac' in z.files else None
    print(f'\n=== MCA ({os.path.basename(os.path.dirname(npz_path))}) ===')

    # El MCA sigue al generador EXACTO: no hay curvatura que ajustar. Pero el
    # FPGA mide el tiempo muerto, y de ahi sale tau sin depender de la curva:
    #   fraccion muerta = m * tau   ->  pendiente de (1-live) contra m
    tau_live = None
    if live is not None:
        muerta = 1.0 - live
        tau_live = float(np.sum(m * muerta) / np.sum(m * m))   # ajuste por el origen
        print(f'  tau del TIEMPO MUERTO medido por el FPGA: {tau_live*1e6:.2f} us')
    seguimiento = m / n
    print(f'  seguimiento minimo: {100*seguimiento.min():.2f} % '
          f'(a {n[int(np.argmin(seguimiento))]:.0f} ev/s)')
    print(f'  => sin saturacion no hay tiempo muerto que ajustar de la curva; '
          f'con arribos periodicos eso es lo ESPERADO hasta rho=1 '
          f'({1/tau_live if tau_live else float("nan"):.0f} ev/s).')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fino = np.logspace(np.log10(n.min()), np.log10(max(n.max(), 1 / tau_live) * 3), 600)
    fig, ax = plt.subplots(3, 1, figsize=(9, 10.5), sharex=True,
                           gridspec_kw={'height_ratios': [2, 1.2, 1.2]})

    ax[0].loglog(fino, fino, 'k:', lw=0.9, label='ideal')
    ax[0].loglog(fino, m_periodico(fino, tau_live), '-', color='tab:blue',
                 label=f'periodico, tau={tau_live*1e6:.2f} us (del live time)')
    ax[0].loglog(fino, m_poisson(fino, tau_live), '--', color='tab:red',
                 label='Poisson con el mismo tau')
    ax[0].loglog(n, m, 'ko', ms=7, label='medido')
    ax[0].set_ylabel('tasa registrada [cps]')
    ax[0].set_title('MCA — el barrido periodico no alcanzo el techo\n'
                    '(tau sale del tiempo muerto que mide el FPGA, no de la curva)')
    ax[0].grid(True, which='both', alpha=0.3); ax[0].legend(fontsize=8, loc='upper left')

    if live is not None:
        ax[1].semilogx(n, 100 * (1 - live), 'o', color='tab:purple',
                       label='fraccion muerta medida')
        # sólo sobre el rango medido: extrapolar el ajuste hasta rho=1 dibujaría
        # una meseta del 100 % que no se midió
        rango = np.logspace(np.log10(n.min()), np.log10(n.max()), 200)
        ax[1].semilogx(rango, 100 * rango * tau_live, '-',
                       color='tab:purple', alpha=0.6,
                       label=f'ajuste  rho = lambda*{tau_live*1e6:.2f} us')
        ax[1].set_ylabel('tiempo muerto [%]')
        ax[1].grid(True, which='both', alpha=0.3); ax[1].legend(fontsize=8)

    res_d = 100 * (m - m_periodico(n, tau_live)) / m
    res_p = 100 * (m - m_poisson(n, tau_live)) / m
    ax[2].semilogx(n, res_d, 'o-', color='tab:blue', label='vs periodico')
    ax[2].semilogx(n, res_p, 's--', color='tab:red', label='vs Poisson')
    ax[2].axhline(0, color='k', lw=0.8)
    ax[2].set_xlabel('tasa incidente [cps]')
    ax[2].set_ylabel('residuo [%]')
    ax[2].grid(True, which='both', alpha=0.3); ax[2].legend(fontsize=8)

    fig.tight_layout()
    p = os.path.join(outdir, 'modelos_tasa_mca.png')
    fig.savefig(p, dpi=130, bbox_inches='tight'); plt.close(fig)
    print(f'  -> {p}')
    print(f'  residuo vs periodico: rms {np.sqrt((res_d**2).mean()):.2f} %   '
          f'vs Poisson: rms {np.sqrt((res_p**2).mean()):.2f} %  '
          f'(max {np.abs(res_p).max():.1f} % a {n[int(np.argmax(np.abs(res_p)))]:.0f} cps)')
    return dict(tau_live=tau_live, res_periodico=res_d, res_poisson=res_p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--outdir', default='datos/modelos_tasa')
    ap.add_argument('--mca', default='datos/mca_20260811_113136/sweep_rate.npz')
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)

    r1 = figura_lector(a.outdir)
    r2 = figura_mca(a.outdir, a.mca)

    np.savez_compressed(os.path.join(a.outdir, 'modelos_tasa.npz'),
                        lector_n=LECTOR_N, lector_m=LECTOR_M,
                        **{f'lector_{k}': v for k, v in (r1 or {}).items()},
                        **{f'mca_{k}': v for k, v in (r2 or {}).items()})
    print(f'\n=== graficos y ajustes en {a.outdir}/ ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
