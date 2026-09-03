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

_AQUI = os.path.dirname(os.path.abspath(__file__))
_SOFT = os.path.abspath(os.path.join(_AQUI, '..', '..'))
sys.path.insert(0, _SOFT)

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
# Carga de mediciones
# ---------------------------------------------------------------------------

def cargar(path):
    """Lee cualquiera de los .npz de barrido y devuelve un dict comun.

    Reconoce los tres formatos que produce la suite:

      sweep_rate.npz          barrido PERIODICO del MCA (testbench_mca.sweep_rate)
      sweep_rate_poisson.npz  barrido POISSON del MCA    (sweep_rate_poisson)
      poisson_loss_lector.npz barrido POISSON del lector (run_poisson_loss.py)

    Devuelve n (tasa incidente), m (registrada), p_loss y de donde sale cada
    cosa. `p_loss` es la clave: en los barridos Poisson viene de los CONTADORES
    del sistema (dropped/(total+dropped) en el MCA, o el ground-truth del
    estimulo en el lector), no de la curva.
    """
    if not path or not os.path.exists(path):
        return None
    z = np.load(path, allow_pickle=True)
    f = z.files
    if 'r_in' in f and 'r_out' in f:                    # barrido periodico
        n, m = z['r_in'].astype(float), z['r_out'].astype(float)
        ok = (n > 0) & (m > 0)
        d = dict(n=n[ok], m=m[ok], p_loss=1.0 - m[ok] / n[ok],
                 estimulo='periodico', origen_loss='1 - registrada/incidente')
        if 'livetime_frac' in f:
            d['live'] = z['livetime_frac'].astype(float)[ok]
        return d
    if 'rate_hz' in f and 'p_loss' in f:                # barridos Poisson
        n = z['rate_hz'].astype(float)
        pl = z['p_loss'].astype(float)
        val = z['valido'].astype(bool) if 'valido' in f else np.ones_like(n, bool)
        m = (z['r_out'].astype(float) if 'r_out' in f
             else n * (1.0 - pl))
        d = dict(n=n[val], m=m[val], p_loss=pl[val], estimulo='poisson',
                 origen_loss=('contadores de HW: dropped/(total+dropped)'
                              if 'dropped' in f else
                              'ground-truth del estimulo: 1 - leidos/emitidos'))
        if 'tau_med_s' in f:
            d['tau_med'] = float(np.median(z['tau_med_s'][val]))
        return d
    return None


def tau_de_livetime(n, m, live):
    """tau desde el TIEMPO MUERTO que exporta el FPGA, sin usar la curva.

    fraccion muerta = tasa_registrada * tau  ->  ajuste por el origen. Es
    independiente de que haya o no saturacion, que es lo que salva la medicion
    cuando el barrido no llego al techo.
    """
    return float(np.sum(m * (1.0 - live)) / np.sum(m * m))


# ---------------------------------------------------------------------------
# Figura comun a las dos arquitecturas
# ---------------------------------------------------------------------------

def figura(outdir, nombre, titulo, per, poi, tau, tau_txt,
           mu_sigma=None, extra_modelos=None):
    """Tres paneles: throughput, PERDIDA vs tasa, y residuos de la perdida.

    El panel del medio es el que discrimina. En el de arriba los dos modelos
    convergen a tasa alta y la medicion deja de distinguirlos; la perdida, en
    cambio, los separa desde el primer punto: periodico da CERO hasta rho=1 y
    Poisson da rho/(1+rho). Es el par (tasa, eventos perdidos) que el sistema
    exporta — `cnt_dropped`/`cnt_total` en el MCA, y el tiempo vivo en los dos.
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    ns = [d['n'] for d in (per, poi) if d is not None]
    n_lo = min(x.min() for x in ns) / 2
    n_hi = max(x.max() for x in ns) * 2
    fino = np.logspace(np.log10(n_lo), np.log10(n_hi), 800)

    C_PER, C_POI = 'k', 'tab:orange'          # medido: periodico / Poisson
    M_PER, M_POI = 'tab:blue', 'tab:red'      # modelos

    fig, ax = plt.subplots(3, 1, figsize=(9.5, 11), sharex=True,
                           gridspec_kw={'height_ratios': [2, 1.5, 1.2]})

    # ---- (a) throughput -----------------------------------------------------
    ax[0].loglog(fino, fino, ':', color='gray', lw=1, label='ideal (sin perdidas)')
    if mu_sigma is not None:
        ax[0].loglog(fino, m_periodico(fino, tau), '-', color=M_PER, lw=1,
                     alpha=0.45, label=f'periodico, tau constante')
        ax[0].loglog(fino, m_periodico_disperso(fino, *mu_sigma), '-',
                     color=M_PER, lw=2.2,
                     label=f'periodico + dispersion ({tau_txt})')
    else:
        ax[0].loglog(fino, m_periodico(fino, tau), '-', color=M_PER, lw=2,
                     label=f'periodico D/D/1/1 ({tau_txt})')
    ax[0].loglog(fino, m_poisson(fino, tau), '--', color=M_POI, lw=2,
                 label='Poisson M/G/1/1, mismo tau')
    for nom, fn, kw in (extra_modelos or []):
        ax[0].loglog(fino, fn(fino), label=nom, **kw)
    if per is not None:
        ax[0].loglog(per['n'], per['m'], 'o', color=C_PER, ms=7,
                     label='medido — estimulo PERIODICO')
    if poi is not None:
        ax[0].loglog(poi['n'], poi['m'], 's', color=C_POI, ms=8, mec='k',
                     mew=0.6, label='medido — estimulo POISSON')
    ax[0].set_ylabel('tasa registrada [ev/s]')
    ax[0].set_title(titulo)
    ax[0].grid(True, which='both', alpha=0.3)
    ax[0].legend(fontsize=8, loc='upper left')

    # ---- (b) perdida: el discriminador -------------------------------------
    ax[1].semilogx(fino, 100 * (1 - m_periodico(fino, tau) / fino), '-',
                   color=M_PER, lw=2, label='periodico: CERO hasta rho=1')
    ax[1].semilogx(fino, 100 * (fino * tau) / (1 + fino * tau), '--',
                   color=M_POI, lw=2, label='Poisson: rho/(1+rho)')
    if per is not None:
        ax[1].semilogx(per['n'], 100 * per['p_loss'], 'o', color=C_PER, ms=7,
                       label='medido — PERIODICO')
    if poi is not None:
        ax[1].semilogx(poi['n'], 100 * poi['p_loss'], 's', color=C_POI, ms=8,
                       mec='k', mew=0.6, label='medido — POISSON')
    # El tiempo muerto NO es la perdida: el sistema puede estar ocupado el 29 %
    # del tiempo y no perder un solo evento si los arribos son periodicos.
    # Son dos observables distintos y los dos los exporta el sistema.
    if per is not None and 'live' in per:
        ax[1].semilogx(per['n'], 100 * (1 - per['live']), 'v:', color='tab:purple',
                       ms=6, alpha=0.8,
                       label='tiempo muerto medido (NO es la perdida)')
    if poi is None:
        ax[1].text(0.03, 0.55, 'faltan los puntos con fuente Poisson\n'
                                '(run_poisson_loss.py / sweep_rate_poisson):\n'
                                'irian sobre la curva roja, en naranja',
                   transform=ax[1].transAxes, ha='left', va='center', fontsize=8.5,
                   color=C_POI, style='italic')
    ax[1].axvline(1.0 / tau, color='gray', ls=':', lw=1)
    ax[1].annotate('rho = 1', xy=(1.0 / tau, 5), fontsize=8, color='gray',
                   rotation=90, va='bottom', ha='right')
    ax[1].set_ylabel('eventos perdidos [%]')
    ax[1].set_ylim(-3, 100)
    ax[1].grid(True, which='both', alpha=0.3)
    ax[1].legend(fontsize=8, loc='best')

    # ---- (c) residuos de la perdida ----------------------------------------
    for d, col, mk, lab in ((per, C_PER, 'o', 'PERIODICO'),
                            (poi, C_POI, 's', 'POISSON')):
        if d is None:
            continue
        rho = d['n'] * tau
        ax[2].semilogx(d['n'], 100 * (d['p_loss'] - (1 - m_periodico(d['n'], tau) / d['n'])),
                       mk + '-', color=col, alpha=0.55,
                       label=f'{lab}: medido - modelo periodico')
        ax[2].semilogx(d['n'], 100 * (d['p_loss'] - rho / (1 + rho)),
                       mk + '--', color=col,
                       label=f'{lab}: medido - modelo Poisson')
    ax[2].axhline(0, color='k', lw=0.8)
    ax[2].set_xlabel('tasa incidente [ev/s]')
    ax[2].set_ylabel('residuo de la perdida\n[puntos porcentuales]')
    ax[2].grid(True, which='both', alpha=0.3)
    ax[2].legend(fontsize=8)

    fig.tight_layout()
    p = os.path.join(outdir, nombre)
    fig.savefig(p, dpi=130, bbox_inches='tight'); plt.close(fig)
    print(f'  -> {p}')
    return p


# ---------------------------------------------------------------------------
# Las dos arquitecturas
# ---------------------------------------------------------------------------

def figura_lector(outdir, per_path=None, poi_path=None):
    per = cargar(per_path)
    if per is None:                       # sin .npz: la tabla del documento
        per = dict(n=LECTOR_N, m=LECTOR_M, p_loss=1.0 - LECTOR_M / LECTOR_N,
                   estimulo='periodico', origen_loss='tabla del documento')
    poi = cargar(poi_path)
    n, m = per['n'], per['m']
    print('\n=== lector de Python ===')
    print(f'  periodico: {len(n)} puntos ({per["origen_loss"]})')
    if poi is not None:
        print(f'  Poisson  : {len(poi["n"])} puntos ({poi["origen_loss"]})')
    else:
        print('  Poisson  : SIN MEDIR (el panel del medio queda con los modelos solos)')

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

    figura(outdir, 'modelos_tasa_lector.png',
           'Lector de Python — tasa, perdidas y modelos de tiempo muerto',
           per, poi, mu_d, f'tau = {mu_d*1e6:.0f} $\\pm$ {sg_d*1e6:.0f} us',
           mu_sigma=(mu_d, sg_d),
           extra_modelos=[('paralizable', lambda x: m_paralizable(x, tau_x),
                           dict(ls='-.', color='tab:green', lw=1))])

    print(f'\n  Con el tau ajustado ({mu_d*1e6:.0f} us), una fuente de Poisson daria:')
    for lam in (500, 2000, 5000):
        rho = lam * mu_d
        print(f'    {lam:6d} ev/s: rho={rho:5.3f}  perdida {100*rho/(1+rho):5.1f} %  '
              f'(el tren periodico dio '
              f'{100*(1-m_periodico_disperso(np.array([lam]), mu_d, sg_d)[0]/lam):5.1f} %, '
              f'y la tasa registrada caeria a {lam/(1+rho):.0f} ev/s)')
    return dict(tau_periodico=tau_d, tau_periodico_lo=lo, tau_periodico_hi=hi,
                tau_disperso_mu=mu_d, tau_disperso_sigma=sg_d,
                tau_poisson=tau_p, tau_paralizable=tau_x,
                res_periodico=res_d, res_disperso=res_g, res_poisson=res_p)


def figura_mca(outdir, per_path, poi_path=None):
    per = cargar(per_path)
    if per is None:
        print(f'\n(sin datos del MCA en {per_path})')
        return None
    poi = cargar(poi_path)
    n, m = per['n'], per['m']
    print(f'\n=== MCA ({os.path.basename(os.path.dirname(per_path))}) ===')
    print(f'  periodico: {len(n)} puntos')

    tau = None
    if 'live' in per:
        tau = tau_de_livetime(n, m, per['live'])
        print(f'  tau del TIEMPO MUERTO medido por el FPGA: {tau*1e6:.2f} us')
    if poi is not None:
        print(f'  Poisson  : {len(poi["n"])} puntos ({poi["origen_loss"]})')
        if 'tau_med' in poi:
            print(f'  tau del barrido Poisson (deadtime/total): '
                  f'{poi["tau_med"]*1e6:.2f} us')
            tau = tau or poi['tau_med']
    else:
        print('  Poisson  : SIN MEDIR')
    if tau is None:
        print('  sin tiempo vivo ni barrido Poisson no hay tau: no se grafica')
        return None
    seg = m / n
    print(f'  seguimiento minimo: {100*seg.min():.2f} % a {n[int(np.argmin(seg))]:.0f} ev/s'
          f'  => rho=1 recien a {1/tau:.0f} ev/s, por eso el barrido periodico '
          f'no vio el techo')

    figura(outdir, 'modelos_tasa_mca.png',
           'MCA — tasa, perdidas y modelos de tiempo muerto',
           per, poi, tau, f'tau = {tau*1e6:.2f} us (del tiempo vivo)')

    rho = n * tau
    res_p = per['p_loss'] - rho / (1 + rho)
    print(f'  residuo de la perdida vs Poisson: max {100*np.abs(res_p).max():.1f} pp '
          f'a {n[int(np.argmax(np.abs(res_p)))]:.0f} ev/s')
    return dict(tau_live=tau, res_poisson_pp=100 * res_p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--outdir',
                    default=os.path.join(_SOFT, 'datos', 'modelos_tasa'))
    ap.add_argument('--mca', default=os.path.join(
        _SOFT, 'datos', 'mca_20260811_113136', 'sweep_rate.npz'),
        help='barrido PERIODICO del MCA (sweep_rate.npz)')
    ap.add_argument('--mca-poisson', default=None,
                    help='barrido POISSON del MCA (sweep_rate_poisson.npz)')
    ap.add_argument('--lector', default=None,
                    help='barrido PERIODICO del lector; sin esto se usa la '
                         'tabla de 6 puntos del documento')
    ap.add_argument('--lector-poisson', default=None,
                    help='barrido POISSON del lector (poisson_loss_lector.npz)')
    a = ap.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)

    r1 = figura_lector(a.outdir, a.lector, a.lector_poisson)
    r2 = figura_mca(a.outdir, a.mca, a.mca_poisson)

    np.savez_compressed(os.path.join(a.outdir, 'modelos_tasa.npz'),
                        lector_n=LECTOR_N, lector_m=LECTOR_M,
                        **{f'lector_{k}': v for k, v in (r1 or {}).items()},
                        **{f'mca_{k}': v for k, v in (r2 or {}).items()})
    print(f'\n=== graficos y ajustes en {a.outdir}/ ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
