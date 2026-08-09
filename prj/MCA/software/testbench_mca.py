#!/usr/bin/env python3
"""Suite de caracterización del Analizador Multicanal (MCA).

Se corre EN LA PITAYA, con el bitstream `mca_red_pitaya.bit` cargado y el Rigol
DG4162 conectado por USB alimentando IN1 (o IN2).

Cada función cierra una fila de la tabla de parámetros a caracterizar de un MCA:

    eje de amplitud   ganancia de conversión, INL, DNL, offset de cero
    resolución        contribución de ruido electrónico, jitter de muestreo
    tasa              tiempo muerto y su modelo, throughput, live time,
                      corrimiento del centroide con la tasa
    umbral            LLD / piso de ruido, curva S de eficiencia
    forma             FOM y su dependencia con la energía

División de responsabilidades: el driver y los helpers de análisis puros están
en mca_utils.py; acá va sólo lo que necesita hardware. Todas las funciones
devuelven los datos CRUDOS además del resultado, para poder re-graficar y
re-analizar sin volver a medir.

Uso:
    python3 testbench_mca.py --list
    python3 testbench_mca.py single_peak
    python3 testbench_mca.py all --outdir datos/mca_2026-08-08
"""

import argparse
import os
import sys
import time

import numpy as np

import mca_utils as mu
from mca_utils import MCA
import rigol_dg4162 as rg


# =============================================================================
# Infraestructura
# =============================================================================

DEFAULT_CFG = dict(thr=200, hyst=80, baseline=0, bl_auto=False,
                   maxlen=1024, tail_dly=8, amp_src=0, q_shift=0,
                   h_shift=0, h2_shift=7, dec=1, channel=0)


def connect(channel=0):
    """Abre el MCA y el generador. Falla temprano y con mensaje claro."""
    mca = MCA.open()
    info = mca.identify()
    gen = rg.RigolDG4162.usb()
    print(f'generador: {gen.id}')
    gen.reset()
    return mca, gen, info


def _save(outdir, name, **arrays):
    if not outdir:
        return None
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f'{name}.npz')
    np.savez_compressed(path, **arrays)
    print(f'  guardado en {path}')
    return path


def _apply_arb(gen, wave, ch, freq_hz, amp_vpp, offset_v, settle_s=0.3):
    gen.load_arb(wave, ch=ch)
    gen.set_arb(ch=ch, freq_hz=freq_hz, amp_vpp=amp_vpp, offset_v=offset_v)
    gen.output(ch, True)
    time.sleep(settle_s)


def _acquire(mca, seconds):
    spec, m2d, cnt = mca.acquire(seconds)
    if cnt['dropped']:
        frac = cnt['dropped'] / max(cnt['total'], 1)
        if frac > 0.01:
            print(f"  AVISO: {cnt['dropped']} eventos descartados "
                  f"({100*frac:.1f}% del total)")
    return spec, m2d, cnt


# =============================================================================
# 1. Pico único — contribución de ruido electrónico
# =============================================================================

def test_single_peak(mca, gen, ch=1, seconds=10.0, amp_vpp=0.5, rate_hz=2e3,
                     outdir=None, **cfg):
    """FWHM del pico de un pulser de amplitud fija.

    Ese ancho ES la contribución de la cadena electrónica: se resta en
    cuadratura del FWHM total para separar detector de electrónica. Es la
    medición de referencia contra la que se comparan todas las demás.
    """
    print('\n=== pico único (ruido electrónico) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)

    pts = 128
    wave = rg.detector_pulse(pts, t_rise=4, tau=16, amplitude=1.0)
    _apply_arb(gen, wave, ch, rate_hz, amp_vpp, amp_vpp / 2)

    spec, _, cnt = _acquire(mca, seconds)
    gen.output(ch, False)

    peak = np.argmax(spec)
    w = max(8, int(0.15 * peak))
    fit = mu.gauss_fit_peak(spec, max(0, peak - w), min(len(spec), peak + w))
    print(f"  centroide {fit['centroid']:.1f} canales   FWHM {fit['fwhm']:.2f}   "
          f"resolución {fit['resolution_pct']:.2f}%")
    print(f"  cuentas: total {cnt['total']}, aceptadas {cnt['accepted']}, "
          f"tasa {cnt['total']/max(cnt['realtime_s'],1e-9):.0f} cps")
    _save(outdir, 'single_peak', spec=spec, **{f'cnt_{k}': v for k, v in cnt.items()})
    return {'fit': fit, 'counters': cnt, 'spectrum': spec}


# =============================================================================
# 2. Barrido de amplitud — ganancia, INL, offset de cero
# =============================================================================

def sweep_amplitude(mca, gen, ch=1, amps=None, seconds=4.0, rate_hz=2e3,
                    outdir=None, **cfg):
    """Centroide vs amplitud del generador: ganancia de conversión e INL.

    La INL es el residuo del ajuste lineal en % de fondo de escala. Un MCA
    decente está por debajo de ±0.05% FS.
    """
    print('\n=== barrido de amplitud (ganancia / INL) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    amps = np.linspace(0.1, 1.0, 20) if amps is None else np.asarray(amps)

    pts = 128
    wave = rg.detector_pulse(pts, t_rise=4, tau=16, amplitude=1.0)
    gen.load_arb(wave, ch=ch)

    centroids, fwhms = [], []
    for a in amps:
        gen.set_arb(ch=ch, freq_hz=rate_hz, amp_vpp=float(a), offset_v=float(a) / 2)
        gen.output(ch, True)
        time.sleep(0.3)
        spec, _, _ = _acquire(mca, seconds)
        pk = int(np.argmax(spec))
        w = max(8, int(0.15 * pk))
        f = mu.gauss_fit_peak(spec, max(0, pk - w), min(len(spec), pk + w))
        centroids.append(f['centroid'])
        fwhms.append(f['fwhm'])
        print(f'  {a:.3f} Vpp -> canal {f["centroid"]:8.1f}  FWHM {f["fwhm"]:.2f}')
    gen.output(ch, False)

    centroids = np.array(centroids)
    a_fit, b_fit, resid, inl = mu.energy_calibration(centroids, amps)
    print(f'  ganancia {a_fit:.1f} canales/Vpp   offset de cero {b_fit:.1f} canales')
    print(f'  INL {inl:.3f}% FS')
    _save(outdir, 'sweep_amplitude', amps=amps, centroids=centroids,
          fwhms=np.array(fwhms), resid=resid)
    return {'amps': amps, 'centroids': centroids, 'fwhms': np.array(fwhms),
            'gain': a_fit, 'offset': b_fit, 'inl_pct_fs': inl, 'resid': resid}


# =============================================================================
# 3. Sliding pulser — DNL
# =============================================================================

def test_dnl(mca, gen, ch=1, seconds=60.0, amp_vpp=1.0, outdir=None, **cfg):
    """DNL con amplitud uniformemente aleatoria: el espectro debe salir plano.

    Necesita estadística: con pocas cuentas por canal la fluctuación de Poisson
    domina sobre la DNL real. Con N cuentas/canal el piso de ruido es 1/sqrt(N),
    así que para medir 1% hacen falta >=10000 cuentas por canal.
    """
    print('\n=== sliding pulser (DNL) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)

    wave = rg.sliding_pulser_wave(n_pulses=128, pts_per_pulse=128,
                                  amp_min=0.15, amp_max=0.95)
    _apply_arb(gen, wave, ch, 200.0, amp_vpp, amp_vpp / 2)
    spec, _, cnt = _acquire(mca, seconds)
    gen.output(ch, False)

    nz = np.nonzero(spec)[0]
    if len(nz) < 16:
        print('  no hay suficientes canales poblados; subí el tiempo o el rango')
        return {'spectrum': spec, 'counters': cnt}
    lo, hi = int(nz[0] + 0.05 * len(nz)), int(nz[-1] - 0.05 * len(nz))
    d = mu.dnl(spec, lo, hi)
    print(f"  ventana [{lo}, {hi}]   media {d['mean_counts']:.0f} cuentas/canal")
    print(f"  DNL max {d['dnl_max_pct']:.2f}%   rms {d['dnl_rms_pct']:.2f}%")
    if d['mean_counts'] < 1e4:
        print(f"  AVISO: con {d['mean_counts']:.0f} cuentas/canal el piso de Poisson "
              f"es {100/np.sqrt(d['mean_counts']):.1f}%: la DNL medida está dominada "
              "por estadística, subí el tiempo de adquisición")
    _save(outdir, 'dnl', spec=spec, dnl=d['dnl'], lo=lo, hi=hi)
    return {'spectrum': spec, 'dnl': d, 'window': (lo, hi)}


# =============================================================================
# 4. Pico vs integral — jitter de muestreo
# =============================================================================

def compare_estimators(mca, gen, ch=1, seconds=10.0, amp_vpp=0.5, rate_hz=2e3,
                       t_rises=(2, 4, 8, 16), q_shift=5, outdir=None, **cfg):
    """FWHM con estimador de PICO vs de INTEGRAL, para varios tiempos de subida.

    Es EL experimento que justifica (o no) un eje de 16384 canales. Con la
    muestra de pico la amplitud sale de una sola muestra y el muestreo casi
    nunca cae en el máximo verdadero; ese error crece cuando el pulso es rápido
    (pocas muestras en el flanco). La integral promedia el ruido como sigma/√N
    y es inmune a ese jitter, así que la diferencia entre las dos curvas mide
    directamente la contribución instrumental.
    """
    print('\n=== pico vs integral (jitter de muestreo) ===')
    out = {'t_rise': [], 'fwhm_peak': [], 'fwhm_int': [],
           'res_peak': [], 'res_int': []}

    for tr in t_rises:
        wave = rg.detector_pulse(128, t_rise=tr, tau=16, amplitude=1.0)
        gen.load_arb(wave, ch=ch)
        gen.set_arb(ch=ch, freq_hz=rate_hz, amp_vpp=amp_vpp, offset_v=amp_vpp / 2)
        gen.output(ch, True)
        time.sleep(0.3)

        res = {}
        for label, src, qs in (('peak', 0, 0), ('int', 1, q_shift)):
            mca.configure(**{**DEFAULT_CFG, **cfg, 'amp_src': src, 'q_shift': qs})
            spec, _, _ = _acquire(mca, seconds)
            pk = int(np.argmax(spec))
            w = max(8, int(0.15 * pk))
            res[label] = mu.gauss_fit_peak(spec, max(0, pk - w),
                                           min(len(spec), pk + w))
        out['t_rise'].append(tr)
        out['fwhm_peak'].append(res['peak']['fwhm'])
        out['fwhm_int'].append(res['int']['fwhm'])
        out['res_peak'].append(res['peak']['resolution_pct'])
        out['res_int'].append(res['int']['resolution_pct'])
        print(f'  t_rise {tr:3d} muestras   resolución pico {res["peak"]["resolution_pct"]:6.2f}%'
              f'   integral {res["int"]["resolution_pct"]:6.2f}%')
    gen.output(ch, False)

    out = {k: np.asarray(v) for k, v in out.items()}
    mejora = out['res_peak'] / np.maximum(out['res_int'], 1e-9)
    print(f'  mejora de la integral: x{mejora.min():.2f} a x{mejora.max():.2f}')
    _save(outdir, 'compare_estimators', **out)
    return out


# =============================================================================
# 5. Barrido de tasa — tiempo muerto, throughput, live time
# =============================================================================

def sweep_rate(mca, gen, ch=1, rates=None, seconds=5.0, amp_vpp=0.5,
               outdir=None, **cfg):
    """Tasa registrada vs incidente: throughput, modelo de tiempo muerto,
    exactitud del live time y corrimiento del centroide con la tasa."""
    print('\n=== barrido de tasa (tiempo muerto / throughput) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    rates = np.logspace(2, 5.5, 12) if rates is None else np.asarray(rates)

    pts = 128
    wave = rg.detector_pulse(pts, t_rise=4, tau=16, amplitude=1.0)
    gen.load_arb(wave, ch=ch)

    r_in, r_out, centroids, lt_frac = [], [], [], []
    for r in rates:
        gen.set_arb(ch=ch, freq_hz=float(r), amp_vpp=amp_vpp, offset_v=amp_vpp / 2)
        gen.output(ch, True)
        time.sleep(0.3)
        spec, _, cnt = _acquire(mca, seconds)
        rt = max(cnt['realtime_s'], 1e-9)
        r_in.append(r)
        r_out.append(cnt['accepted'] / rt)
        lt_frac.append(cnt['livetime_s'] / rt)
        pk = int(np.argmax(spec))
        w = max(8, int(0.15 * pk))
        try:
            centroids.append(mu.gauss_fit_peak(spec, max(0, pk - w),
                                               min(len(spec), pk + w))['centroid'])
        except ValueError:
            centroids.append(np.nan)
        print(f'  {r:9.0f} Hz in -> {r_out[-1]:9.0f} cps out   '
              f'live {100*lt_frac[-1]:5.1f}%   centroide {centroids[-1]:.1f}')
    gen.output(ch, False)

    r_in = np.array(r_in); r_out = np.array(r_out)
    try:
        dt = mu.deadtime_fit(r_in, r_out)
        print(f"  tau no paralizable {dt['tau_nonparalyzable_s']*1e6:.2f} us")
        print(f"  tau paralizable    {dt['tau_paralyzable_s']*1e6:.2f} us")
        print(f"  mejor ajuste: {dt['best']}")
    except ValueError as e:
        dt = None
        print(f'  no se pudo ajustar el tiempo muerto: {e}')

    cen = np.array(centroids)
    ok = ~np.isnan(cen)
    if ok.sum() >= 2:
        shift = 100.0 * (cen[ok][-1] - cen[ok][0]) / cen[ok][0]
        print(f'  corrimiento del centroide de la tasa mínima a la máxima: {shift:+.2f}%')
    _save(outdir, 'sweep_rate', r_in=r_in, r_out=r_out, centroids=cen,
          livetime_frac=np.array(lt_frac))
    return {'r_in': r_in, 'r_out': r_out, 'centroids': cen,
            'livetime_frac': np.array(lt_frac), 'deadtime': dt}


# =============================================================================
# 6. Par de pulsos — resolución par-pulso
# =============================================================================

def test_pulse_pair(mca, gen, ch=1, gaps_s=None, seconds=4.0, amp_vpp=0.5,
                    outdir=None, **cfg):
    """Dos pulsos separados por `gap`: mínimo para contarlos como dos.

    Reutiliza set_pulse_pair_burst, que ya existía para el scope.
    """
    print('\n=== par de pulsos (resolución par-pulso) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    gaps_s = np.logspace(-7, -4, 12) if gaps_s is None else np.asarray(gaps_s)

    gaps, ratio, pileup = [], [], []
    for g in gaps_s:
        gen.set_pulse_pair_burst(ch=ch, gap_s=float(g), width_s=float(g) / 4,
                                 amp_vpp=amp_vpp, offset_v=amp_vpp / 2,
                                 burst_period_s=max(10 * g, 1e-3))
        gen.output(ch, True)
        time.sleep(0.3)
        _, _, cnt = _acquire(mca, seconds)
        n_burst = cnt['realtime_s'] / max(10 * g, 1e-3)
        gaps.append(g)
        ratio.append(cnt['total'] / max(n_burst, 1e-9) / 2.0)   # 1.0 = los dos
        pileup.append(cnt['pileup'])
        print(f'  gap {g*1e6:8.3f} us -> fracción detectada {ratio[-1]:.2f}   '
              f'apilamientos {cnt["pileup"]}')
    gen.output(ch, False)
    gen.disable_burst(ch)

    gaps = np.array(gaps); ratio = np.array(ratio)
    ok = np.where(ratio > 0.5)[0]
    tau_pp = gaps[ok[0]] if len(ok) else np.nan
    print(f'  resolución par-pulso (50%): {tau_pp*1e6:.2f} us')
    _save(outdir, 'pulse_pair', gaps=gaps, ratio=ratio, pileup=np.array(pileup))
    return {'gaps': gaps, 'ratio': ratio, 'pileup': np.array(pileup),
            'tau_pair_s': tau_pp}


# =============================================================================
# 7. Barrido de umbral — curva S y LLD
# =============================================================================

def sweep_threshold(mca, gen, ch=1, thrs=None, seconds=3.0, amp_vpp=0.2,
                    rate_hz=2e3, outdir=None, **cfg):
    """Fracción de pulsos detectados vs umbral (curva S). El 50% define el LLD
    efectivo. Con la entrada terminada da además el piso de ruido."""
    print('\n=== barrido de umbral (curva S / LLD) ===')
    thrs = np.arange(20, 600, 20) if thrs is None else np.asarray(thrs)

    wave = rg.detector_pulse(128, t_rise=4, tau=16, amplitude=1.0)
    _apply_arb(gen, wave, ch, rate_hz, amp_vpp, amp_vpp / 2)

    det = []
    for t in thrs:
        mca.configure(**{**DEFAULT_CFG, **cfg, 'thr': int(t),
                         'hyst': max(4, int(t) // 3)})
        _, _, cnt = _acquire(mca, seconds)
        det.append(cnt['total'] / max(cnt['realtime_s'], 1e-9))
        print(f'  umbral {t:5d} -> {det[-1]:9.0f} cps')
    gen.output(ch, False)

    det = np.array(det, dtype=float)
    ref = det.max() if det.size else 0.0
    lld = np.nan
    if ref > 0:
        below = np.where(det < 0.5 * ref)[0]
        if len(below):
            lld = thrs[below[0]]
    print(f'  LLD efectivo (50%): {lld}')

    print('  midiendo el piso de ruido: DESCONECTÁ o terminá la entrada...')
    gen.output(ch, False)
    time.sleep(1.0)
    noise = []
    for t in thrs:
        mca.configure(**{**DEFAULT_CFG, **cfg, 'thr': int(t),
                         'hyst': max(4, int(t) // 3)})
        _, _, cnt = _acquire(mca, 1.0)
        noise.append(cnt['total'] / max(cnt['realtime_s'], 1e-9))
    noise = np.array(noise, dtype=float)
    quiet = np.where(noise < 1.0)[0]
    print(f'  umbral mínimo sin disparos de ruido: '
          f'{thrs[quiet[0]] if len(quiet) else "ninguno del barrido"}')
    _save(outdir, 'sweep_threshold', thrs=thrs, detected=det, noise=noise)
    return {'thrs': thrs, 'detected': det, 'noise': noise, 'lld': lld}


# =============================================================================
# 8. Dos poblaciones — FOM
# =============================================================================

def test_psd_fom(mca, gen, ch=1, seconds=30.0, amp_vpp=0.5, rate_hz=500.0,
                 tau_a=12.0, tau_b=40.0, outdir=None, **cfg):
    """Dos poblaciones con la MISMA amplitud y colas distintas.

    Al no moverse en el eje de amplitud, cualquier separación que aparezca es
    del eje de forma: es el caso limpio para medir la FOM. FOM > 1.27 se
    considera buena separación.
    """
    print('\n=== dos poblaciones (FOM de PSD) ===')
    if not mca.caps & mu.CAP_HIST_H_PSD:
        print('  este bitstream no trae el motor 2D; salteando')
        return None
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)

    wave = rg.two_population_wave(n_pulses=64, pts_per_pulse=128,
                                  tau_a=tau_a, tau_b=tau_b, frac_b=0.5)
    _apply_arb(gen, wave, ch, rate_hz, amp_vpp, amp_vpp / 2)
    spec, m2d, cnt = _acquire(mca, seconds)
    gen.output(ch, False)

    res = mu.fom(m2d)
    print(f"  FOM global: {res.get('fom', float('nan')):.3f}")
    if cnt['rej_psd']:
        print(f"  {cnt['rej_psd']} eventos sin factor de forma válido "
              "(Q_total=0 o Q_cola>=Q_total): revisá cfg_tail_dly y el umbral")

    # Dependencia con la energía: la separación se degrada a baja amplitud.
    n_amp = m2d.shape[0]
    per_slice = []
    for lo in range(0, n_amp, max(1, n_amp // 4)):
        hi = min(lo + max(1, n_amp // 4), n_amp)
        try:
            f = mu.fom(m2d, lo, hi)['fom']
        except (ValueError, KeyError):
            f = np.nan
        per_slice.append((lo, hi, f))
        print(f'  amplitud [{lo:3d},{hi:3d}) -> FOM {f:.3f}')
    _save(outdir, 'psd_fom', spec=spec, map2d=m2d)
    return {'fom': res, 'map2d': m2d, 'per_slice': per_slice, 'counters': cnt}


# =============================================================================
# 9. Verificación cruzada contra el scope
# =============================================================================

def cross_check_counts(mca, gen, ch=1, seconds=5.0, amp_vpp=0.5, rate_hz=1e3,
                       outdir=None, **cfg):
    """`cnt_total` del MCA contra la tasa conocida del generador.

    La comparación directa con capture_n_events() del scope no es posible en el
    bitstream del MCA (los dos coexisten en el diseño, pero el scope necesita su
    propia configuración de armado); acá se contrasta contra el generador, que
    es una referencia independiente y suficiente.
    """
    print('\n=== verificación cruzada de conteo ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    wave = rg.detector_pulse(128, t_rise=4, tau=16, amplitude=1.0)
    _apply_arb(gen, wave, ch, rate_hz, amp_vpp, amp_vpp / 2)
    _, _, cnt = _acquire(mca, seconds)
    gen.output(ch, False)

    esperado = rate_hz * cnt['realtime_s']
    err = 100.0 * (cnt['total'] - esperado) / max(esperado, 1e-9)
    print(f"  esperado {esperado:.0f}, contado {cnt['total']} ({err:+.2f}%)")
    print(f"  descartados {cnt['dropped']}, apilamientos {cnt['pileup']}, "
          f"rechazados por amplitud {cnt['rej_amp']}")
    return {'expected': esperado, 'counters': cnt, 'error_pct': err}


# =============================================================================
# Graficado
# =============================================================================

def plot_all(outdir):
    """Grafica los .npz de una campaña. Se puede correr en la PC, sin hardware."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    def _load(name):
        p = os.path.join(outdir, f'{name}.npz')
        return np.load(p) if os.path.exists(p) else None

    d = _load('single_peak')
    if d is not None:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.semilogy(d['spec'] if 'spec' in d else d['spectrum'])
        ax.set_xlabel('canal'); ax.set_ylabel('cuentas')
        ax.set_title('Espectro — pulser de amplitud fija')
        fig.savefig(os.path.join(outdir, 'single_peak.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('sweep_amplitude')
    if d is not None:
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
        a1.plot(d['amps'], d['centroids'], 'o-'); a1.set_ylabel('centroide')
        a1.set_title('Linealidad')
        a2.plot(d['amps'], d['resid'], 'o-'); a2.axhline(0, color='k', lw=.5)
        a2.set_xlabel('amplitud [Vpp]'); a2.set_ylabel('residuo (INL)')
        fig.savefig(os.path.join(outdir, 'linealidad.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('sweep_rate')
    if d is not None:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.loglog(d['r_in'], d['r_out'], 'o-', label='medido')
        ax.loglog(d['r_in'], d['r_in'], 'k--', lw=.8, label='ideal')
        ax.set_xlabel('tasa incidente [Hz]'); ax.set_ylabel('tasa registrada [cps]')
        ax.legend(); ax.set_title('Throughput')
        fig.savefig(os.path.join(outdir, 'throughput.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('psd_fom')
    if d is not None:
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.imshow(d['map2d'], origin='lower', aspect='auto')
        ax.set_xlabel('factor de forma'); ax.set_ylabel('amplitud')
        ax.set_title('Mapa amplitud x forma')
        fig.savefig(os.path.join(outdir, 'psd_map.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)
    print(f'gráficos en {outdir}')


# =============================================================================
# CLI
# =============================================================================

TESTS = {
    'single_peak':        test_single_peak,
    'sweep_amplitude':    sweep_amplitude,
    'dnl':                test_dnl,
    'compare_estimators': compare_estimators,
    'sweep_rate':         sweep_rate,
    'pulse_pair':         test_pulse_pair,
    'sweep_threshold':    sweep_threshold,
    'psd_fom':            test_psd_fom,
    'cross_check':        cross_check_counts,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('test', nargs='?', help="nombre del test, o 'all'")
    ap.add_argument('--list', action='store_true', help='listar los tests')
    ap.add_argument('--outdir', default=None, help='dónde guardar los .npz')
    ap.add_argument('--channel', type=int, default=0, help='0=IN1, 1=IN2')
    ap.add_argument('--gen-ch', type=int, default=1, help='canal del Rigol')
    ap.add_argument('--plot-only', action='store_true',
                    help='sólo graficar un --outdir ya medido (no usa hardware)')
    args = ap.parse_args(argv)

    if args.list or not args.test and not args.plot_only:
        print('tests disponibles:')
        for k in TESTS:
            print(f'  {k}')
        print("  all   (corre todos en orden)")
        return 0

    if args.plot_only:
        if not args.outdir:
            ap.error('--plot-only necesita --outdir')
        plot_all(args.outdir)
        return 0

    mca, gen, _ = connect(args.channel)
    try:
        names = list(TESTS) if args.test == 'all' else [args.test]
        for n in names:
            if n not in TESTS:
                print(f'test desconocido: {n}', file=sys.stderr)
                return 2
            TESTS[n](mca, gen, ch=args.gen_ch, outdir=args.outdir,
                     channel=args.channel)
    finally:
        try:
            gen.output(args.gen_ch, False)
        finally:
            gen.close()
            mca.close()
    if args.outdir:
        plot_all(args.outdir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
