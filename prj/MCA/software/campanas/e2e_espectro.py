#!/usr/bin/env python3
"""Pulsos de la cadena e2e + comparacion del espectro HW contra el de SW.

Dos cosas en un solo experimento, sobre el MISMO estimulo y al MISMO tiempo:

  - el **pipeline de adquisicion** (`mca/`, slot 1 del bus) guarda las formas de
    onda completas, y de ahi se calcula un histograma de alturas por software;
  - el **MCA en la FPGA** (`mca_top`, slot 7) histogramea en tiempo real.

Los dos miran la misma entrada del ADC, asi que sus espectros tienen que dar la
misma FORMA. Lo que NO tiene que coincidir son las cuentas: el pipeline arrastra
~683 us de tiempo muerto por evento (leer 1024 muestras por el bus) mientras que
el MCA vive en el regimen de los microsegundos, asi que ve muchos mas eventos.
Comparar centroide y ancho -- no areas.

Es la validacion cruzada que cierra el circulo: si el histograma del HW coincide
con el que sale de analizar las formas crudas, el camino de datos del MCA esta
bien de punta a punta.

Uso:

    # en la Pitaya: adquirir (bitstream mca_red_pitaya, Rigol en IN1)
    python3 campanas/e2e_espectro.py --acquire --duration 20

    # donde sea: graficar lo adquirido
    python3 campanas/e2e_espectro.py datos/e2e_espectro_<stamp>.npz
"""
import argparse
import glob
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, '/opt/redpitaya/lib/python')
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

ADC_CNT_PER_V = 8192
FS            = 125e6
N_TRAZAS      = 300           # formas crudas que se guardan para graficar


# ============================================================== adquisicion

def acquire(args):
    """Corre el pipeline y el MCA a la vez y guarda todo en un .npz."""
    import rigol_dg4162 as rgmod
    import rp
    import mca_utils as mu
    from multitrigger_utils import MultiTriggerScope
    from mca import AcquisitionSession, BramSource, load_chunk, scope_regs

    # -- generador ---------------------------------------------------------
    gen = rgmod.RigolDG4162.usb()
    print(f'  generador : {gen.id.strip()}')
    gen.reset()
    wave, freq, info = rgmod.pulse_train_wave(args.width, args.rate)
    gen.load_arb(wave, ch=1)
    # offset 0: baseline en 0 V. La forma se normaliza a [0,1] pero el DG la
    # interpreta sobre [-1,+1], asi que la excursion util es amp_vpp/2.
    gen.set_arb(ch=1, freq_hz=freq, amp_vpp=args.amp, offset_v=0.0)
    gen.output(1, True)
    time.sleep(0.4)
    alt_esperada = args.amp / 2
    print(f'  estimulo  : {args.width*1e6:g} us FWHM a {args.rate:g} Hz, '
          f'pulso de {alt_esperada*1000:.0f} mV')

    # -- scope + MCA -------------------------------------------------------
    sc = MultiTriggerScope.open()
    if not sc.verify_bitstream(verbose=False)['ok']:
        sc.close()
        raise SystemExit('no se lee un scope multitrigger valido')
    rp.rp_Init()

    mca = mu.MCA.open()
    mca.identify(verbose=False)
    print(f'  MCA       : {1 << mca.h_aw} canales')

    # Umbral COMUN a los dos, para que la poblacion aceptada sea la misma.
    thr_cnt = int(round(args.thr * ADC_CNT_PER_V))
    cfg = dict(thr=thr_cnt, hyst=int(round(args.hyst * ADC_CNT_PER_V)),
               baseline=0, bl_auto=True, bl_k=12, bl_holdoff=64,
               maxlen=4096, tail_dly=8, amp_src=0,   # 0 = muestra de pico
               q_shift=0, h_shift=args.h_shift, h2_shift=7, dec=1, channel=0)
    mca.configure(**cfg)
    print(f'  umbral    : {args.thr} V = {thr_cnt} cuentas (los dos caminos)')

    stamp   = time.strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(_RAIZ, 'datos', f'e2e_espectro_{stamp}')

    src = BramSource(sc, pre=args.pre, post=args.post, n_ch=1,
                     thr=args.thr, hyst=args.hyst)
    ses = AcquisitionSession(src, run_dir, capacity=512, ram_budget_mb=32,
                             verbose=False, meta=dict(test='e2e_espectro'))
    ses.writer.meta_base['scope_regs'] = scope_regs(sc)

    print(f'\n  adquiriendo {args.duration:.0f} s (pipeline + MCA en paralelo)...')
    try:
        mca.stop(); mca.clear(); mca.start()
        t0 = time.perf_counter()
        with ses:
            ses.wait(duration_s=args.duration, poll_s=0.1)
        t_run = time.perf_counter() - t0
        mca.stop()
        spec = mca.spectrum()
        cnt  = mca.counters()
    finally:
        gen.output(1, False); gen.close()
        try:
            sc.disarm()
        finally:
            sc.close()
        mca.close()

    print(ses.summary())
    print(f'  MCA: total={cnt["total"]} aceptados={cnt["accepted"]} '
          f'pileup={cnt["pileup"]} descartados={cnt["dropped"]}')
    print(f'       realtime={cnt["realtime_s"]:.2f} s  '
          f'livetime={cnt["livetime_s"]:.2f} s  '
          f'(dead {100*(1-cnt["livetime_s"]/max(cnt["realtime_s"],1e-9)):.1f} %)')

    # -- formas crudas del pipeline ---------------------------------------
    files = sorted(glob.glob(os.path.join(run_dir, 'chunk_*.npz')))
    if not files:
        raise SystemExit('el pipeline no escribio ningun chunk')
    trazas, t_ns = [], []
    for f in files:
        a, _ = load_chunk(f)
        trazas.append(a['wave_V'][:, 0, :])
        t_ns.append(a['t_ns'])
    W    = np.concatenate(trazas)
    t_ns = np.concatenate(t_ns)
    print(f'  pipeline: {W.shape[0]} formas de {W.shape[1]} muestras')

    out = os.path.join(_RAIZ, 'datos', f'e2e_espectro_{stamp}.npz')
    np.savez_compressed(
        out,
        trazas=W[:N_TRAZAS].astype(np.float32),   # muestra para graficar
        alturas_V=alturas(W, args.pre),           # TODAS, para el histograma
        t_ns=t_ns,
        espectro_hw=spec.astype(np.uint32),
        mca_counters=np.array(cnt, dtype=object),
        mca_cfg=np.array(cfg, dtype=object),
        stats=np.array(dict(ses.stats), dtype=object),
        meta=np.array(dict(
            rate_hz=args.rate, amp_vpp=args.amp, altura_esperada_V=alt_esperada,
            width_s=args.width, thr_V=args.thr, pre=args.pre, post=args.post,
            h_shift=args.h_shift, h_aw=mca.h_aw, duration_s=t_run,
            adc_cnt_per_V=ADC_CNT_PER_V, run_dir=run_dir), dtype=object))
    print(f'\n  guardado: {out}')
    return out


def alturas(W, pre, modo='pre'):
    """Altura de cada pulso, con la base estimada de tres formas distintas.

    NO es un detalle: de que se tome como cero depende TODO el eje de amplitud.

      'pre'  mediana de la region pre-trigger. Es lo natural, pero **solo vale
             si `pre` cubre mas que el flanco de subida**. Medido en la placa:
             con un pulso de 2 us de FWHM la subida 10-90% dura 376 ns, asi que
             con pre=32 muestras (256 ns) la "base" cae DENTRO del flanco, a
             ~30% del pico, y la altura sale 33% baja (197 mV en vez de 295).
      'zero' cero absoluto. Vale cuando el baseline real del sistema es 0 y el
             pulso no vuelve a la base dentro de la ventana (medido lejos del
             pulso: 0.0006 V).
      'min'  minimo de la ventana. Robusto si la ventana contiene base, malo si
             arranca sobre el flanco.
    """
    peak = W.max(axis=1)
    if modo == 'zero':
        base = np.zeros(len(W), dtype=W.dtype)
    elif modo == 'min':
        base = W.min(axis=1)
    else:
        base = np.median(W[:, :max(pre - 4, 1)], axis=1)
    return (peak - base).astype(np.float32)


def diagnostico_ventana(W, pre, thr):
    """La region pre-trigger, ¿contiene linea de base o es parte del flanco?

    Criterio: si la pre-region tiene PENDIENTE apreciable o su nivel esta lejos
    de cero comparado con el ruido, entonces la ventana arranca sobre la subida
    y la altura estimada con 'pre' esta sesgada hacia abajo.
    """
    n = max(pre - 4, 4)
    pre_reg = W[:, :n]
    nivel  = float(np.median(pre_reg))
    # pendiente media en la pre-region, en V por muestra
    pend   = float(np.median(np.diff(pre_reg, axis=1).mean(axis=1)))
    ruido  = float(np.median(np.std(pre_reg[:, :max(n // 3, 2)], axis=1)))
    sesgo  = nivel > 5 * max(ruido, 1e-6)
    return dict(nivel_V=nivel, pendiente_V_muestra=pend, ruido_V=ruido,
                pre_contaminada=bool(sesgo),
                frac_del_umbral=nivel / thr if thr else float('nan'))


# ================================================================ analisis

def consistencia_periodo(t_ns, periodo_us, tol=0.05):
    """Fraccion de Delta-t que son multiplos enteros de `periodo_us`.

    Con tiempo muerto mayor que el periodo, el lector se saltea pulsos y los
    Delta-t observados son MULTIPLOS ENTEROS del periodo real, no el periodo.
    Por eso "el dt mediano coincide con el periodo pedido" puede dar bien por
    pura coincidencia: con tiempo muerto de ~1 ms y periodo real de 250 us el dt
    mediano da exactamente 1000 us y parece confirmar 1 kHz cuando el estimulo
    corre a 4 kHz.

    OJO: la cuantizacion sola NO determina el periodo, porque cualquier DIVISOR
    del periodo real tambien explica los datos. Sirve para FALSAR un candidato
    (si la fraccion es baja, ese periodo esta mal), no para inferirlo. El
    periodo se toma de la tasa del MCA, que cuenta los pulsos con ~1.6 % de
    tiempo muerto.
    """
    dt = np.diff(np.asarray(t_ns, dtype=np.float64)) / 1e3       # us
    dt = dt[dt > 0]
    if len(dt) < 20 or not np.isfinite(periodo_us) or periodo_us <= 0:
        return 0.0
    r = dt / periodo_us
    return float(np.mean(np.abs(r - np.round(r)) < tol))


def gauss_stats(x, w=None):
    """Centroide y FWHM de una distribucion (por momentos, sin ajuste)."""
    if w is None:
        mu_ = float(np.mean(x)); sd = float(np.std(x))
    else:
        w = np.asarray(w, dtype=float)
        tot = w.sum()
        if tot <= 0:
            return float('nan'), float('nan'), float('nan')
        mu_ = float((x * w).sum() / tot)
        sd  = float(np.sqrt(((x - mu_) ** 2 * w).sum() / tot))
    fwhm = 2.3548 * sd
    res  = 100 * fwhm / mu_ if mu_ else float('nan')
    return mu_, fwhm, res


def plot(path, out_png=None):
    import matplotlib
    if not os.environ.get('DISPLAY'):
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    z    = np.load(path, allow_pickle=True)
    meta = z['meta'].item()
    cnt  = z['mca_counters'].item()
    st   = z['stats'].item()
    W    = z['trazas']
    h_pre = z['alturas_V']            # como se guardaron: base = mediana(pre)
    spec = z['espectro_hw']
    pre  = meta['pre']
    thr  = meta['thr_V']
    esperada = meta['altura_esperada_V']

    t_us = (np.arange(W.shape[1]) - pre) / FS * 1e6

    # -- correccion de la linea de base -----------------------------------
    diag = diagnostico_ventana(W, pre, thr)
    base_med = diag['nivel_V']
    # Con la pre-region contaminada, el cero correcto es el baseline absoluto
    # del sistema (medido lejos del pulso: 0.0006 V). Como `base` es
    # practicamente constante (sigma de 0.5 mV sobre las trazas guardadas), las
    # alturas completas se corrigen sumandole ese offset.
    h = (h_pre + base_med) if diag['pre_contaminada'] else h_pre
    etiqueta_sw = ('pico absoluto (pre corregida +%.0f mV)' % (base_med * 1000)
                   if diag['pre_contaminada'] else 'pico - base pre-trigger')

    mu_s, fw_s, res_s = gauss_stats(h)
    ch   = np.arange(len(spec))
    nz   = np.nonzero(spec)[0]
    # El eje ya NO es `amp >> h_shift`: la feature se normaliza y el canal toma
    # los h_aw bits altos, asi que la escala depende de h_aw y no de h_shift.
    # Se pasa por counts_to_volts para tener una sola definicion del eje.
    v_hw = mu.counts_to_volts(ch, h_aw=meta.get('h_aw', 13)) \
           * (ADC_CNT_PER_V / meta['adc_cnt_per_V'])
    mu_h, fw_h, res_h = gauss_stats(ch, spec)
    mu_hw_v, _, _     = gauss_stats(v_hw, spec)
    dif = 100 * (mu_hw_v - mu_s) / mu_s if mu_s else float('nan')

    fig, ax = plt.subplots(2, 3, figsize=(16.5, 9))
    fig.suptitle(f'Cadena e2e: pulsos, estadisticas y espectro HW vs SW   |   '
                 f'{meta["rate_hz"]:.0f} Hz, {meta["width_s"]*1e6:g} us FWHM, '
                 f'pulso programado {esperada*1000:.0f} mV', fontsize=13)

    # -- 1. pulsos superpuestos -------------------------------------------
    a = ax[0, 0]
    for k in range(min(40, len(W))):
        a.plot(t_us, W[k], lw=0.5, alpha=0.25, color='C0')
    a.plot(t_us, W.mean(axis=0), lw=2, color='C3', label='promedio')
    a.axvline(0, color='k', ls=':', lw=1.2, label='trigger')
    a.axhline(thr, color='C2', ls='--', lw=1, label=f'umbral {thr*1000:.0f} mV')
    a.axhline(0, color='gray', lw=0.8)
    a.set_xlabel('t desde el trigger (us)'); a.set_ylabel('V')
    a.set_title(f'{min(40, len(W))} pulsos superpuestos')
    a.legend(fontsize=8); a.grid(alpha=0.3)

    # -- 2. zoom del flanco: por que `pre` no alcanza ----------------------
    a = ax[0, 1]
    p = np.percentile(W, [5, 50, 95], axis=0)
    a.fill_between(t_us, p[0], p[2], alpha=0.25, color='C0', label='5-95 %')
    a.plot(t_us, p[1], color='C0', lw=1.5, label='mediana')
    a.axvspan(t_us[0], 0, color='C1', alpha=0.15,
              label=f'pre = {pre} muestras ({pre/FS*1e6:.2f} us)')
    a.axhline(base_med, color='C1', ls='-.', lw=1.2,
              label=f'base medida {base_med*1000:.0f} mV')
    a.axhline(thr, color='C2', ls='--', lw=1)
    a.axhline(0, color='gray', lw=0.8, label='cero real (0.6 mV)')
    a.set_xlim(t_us[0], min(3.0, t_us[-1]))
    a.set_xlabel('t desde el trigger (us)'); a.set_ylabel('V')
    a.set_title('zoom del flanco: la pre-region cae DENTRO de la subida\n'
                f'(subida 10-90% = 376 ns > pre = {pre/FS*1e9:.0f} ns)')
    a.legend(fontsize=7.5, loc='lower right'); a.grid(alpha=0.3)

    # -- 3. alturas por SW, los dos estimadores ---------------------------
    a = ax[0, 2]
    a.hist(h_pre * 1000, bins=100, color='C7', alpha=0.6,
           label=f'base pre-trigger: {np.median(h_pre)*1000:.1f} mV (SESGADO)')
    a.hist(h * 1000, bins=100, color='C0', alpha=0.8,
           label=f'corregido: {mu_s*1000:.1f} mV')
    a.axvline(esperada * 1000, color='C3', ls='--', lw=1.5,
              label=f'programado {esperada*1000:.0f} mV')
    a.set_xlabel('altura (mV)'); a.set_ylabel('cuentas')
    a.set_title(f'alturas por SW (n={len(h)})\n'
                f'FWHM={fw_s*1000:.2f} mV  ->  {res_s:.2f} %')
    a.legend(fontsize=7.5); a.grid(alpha=0.3)

    # -- 4. espectro del HW -----------------------------------------------
    a = ax[1, 0]
    a.plot(ch, spec, lw=1.0, color='C4')
    if len(nz):
        a.set_xlim(max(0, nz.min() - 30), min(len(spec), nz.max() + 30))
    a.axvline(mu_h, color='C1', lw=1.5,
              label=f'centroide {mu_h:.0f} = {mu_hw_v*1000:.1f} mV')
    a.set_xlabel('canal del MCA'); a.set_ylabel('cuentas')
    a.set_title(f'espectro del MCA en HW (aceptados={cnt["accepted"]})\n'
                f'FWHM={fw_h:.1f} canales  ->  {res_h:.2f} %')
    a.legend(fontsize=8); a.grid(alpha=0.3)

    # -- 5. LA COMPARACION -------------------------------------------------
    a = ax[1, 1]
    lo = min(h.min(), v_hw[nz].min() if len(nz) else h.min())
    hi = max(h.max(), v_hw[nz].max() if len(nz) else h.max())
    edges = np.linspace(lo * 0.97, hi * 1.03, 220)
    n_sw, _ = np.histogram(h, bins=edges)
    n_hw, _ = np.histogram(v_hw, bins=edges, weights=spec.astype(float))
    ctr = 0.5 * (edges[1:] + edges[:-1]) * 1000
    # Normalizados: las AREAS no son comparables (tiempos muertos distintos de
    # dos ordenes de magnitud); la FORMA y el CENTROIDE si.
    a.step(ctr, n_sw / max(n_sw.max(), 1), where='mid', color='C0', lw=1.5,
           label=f'SW, formas crudas (n={len(h)})')
    a.step(ctr, n_hw / max(n_hw.max(), 1), where='mid', color='C4', lw=1.5,
           label=f'HW, MCA (n={cnt["accepted"]})')
    a.axvline(esperada * 1000, color='C3', ls='--', lw=1.2, label='programado')
    a.set_xlabel('amplitud (mV)'); a.set_ylabel('normalizado al maximo')
    a.set_title(f'MISMO estimulo, dos caminos independientes\n'
                f'centroides {mu_s*1000:.1f} vs {mu_hw_v*1000:.1f} mV  ({dif:+.2f} %)')
    a.legend(fontsize=8); a.grid(alpha=0.3)

    # -- 6. estadisticas ---------------------------------------------------
    a = ax[1, 2]
    a.axis('off')
    dur     = meta['duration_s']
    esp     = meta['rate_hz'] * dur
    dead_hw = 100 * (1 - cnt['livetime_s'] / max(cnt['realtime_s'], 1e-9))
    # Tasa real del estimulo: la del MCA, que con 1.65 % de tiempo muerto ve
    # practicamente todo. Se contrasta con la cuantizacion de los Delta-t.
    r_mca    = cnt['accepted'] / max(cnt['realtime_s'], 1e-9)
    frac_mca = consistencia_periodo(z['t_ns'], 1e6 / r_mca)
    frac_ped = consistencia_periodo(z['t_ns'], 1e6 / meta['rate_hz'])
    filas = [
        ('ESTIMULO', f'pedido {meta["rate_hz"]:.0f} Hz'),
        ('  tasa real (MCA)', f'{r_mca:.0f} Hz   <-- x{r_mca/meta["rate_hz"]:.1f}'),
        ('  dt multiplos de 1/f_real', f'{frac_mca*100:.1f} %'),
        ('  dt multiplos de 1/f_pedida', f'{frac_ped*100:.1f} %'),
        ('', ''),
        ('PIPELINE (formas de onda)', ''),
        ('  guardados', f'{st["n_read"]}'),
        ('  descartes de SW', f'{st["n_dropped"]}'),
        ('  ciclo por evento', f'{dur/max(st["n_read"],1)*1e6:.0f} us'),
        ('  eficiencia vs tasa real', f'{100*st["n_read"]/max(r_mca*dur,1):.1f} %'),
        ('', ''),
        ('MCA EN HARDWARE', ''),
        ('  total / aceptados', f'{cnt["total"]} / {cnt["accepted"]}'),
        ('  pileup / descartados', f'{cnt["pileup"]} / {cnt["dropped"]}'),
        ('  tiempo muerto', f'{dead_hw:.2f} %'),
        ('  x mas eventos que el SW', f'{cnt["accepted"]/max(st["n_read"],1):.1f}x'),
        ('', ''),
        ('AMPLITUD', ''),
        ('  programada', f'{esperada*1000:.1f} mV'),
        ('  SW (pico absoluto)', f'{mu_s*1000:.1f} mV'),
        ('  HW (MCA)', f'{mu_hw_v*1000:.1f} mV'),
        ('  SW - HW', f'{dif:+.2f} %'),
        ('', ''),
        ('RESOLUCION (FWHM)', ''),
        ('  SW', f'{res_s:.2f} %'),
        ('  HW', f'{res_h:.2f} %'),
    ]
    y = 1.0
    for k, v in filas:
        bold = k and not k.startswith('  ') and not v
        a.text(0.0, y, k, fontsize=9, va='top', family='monospace',
               weight='bold' if bold else 'normal')
        a.text(0.60, y, v, fontsize=9, va='top', family='monospace')
        y -= 0.044

    fig.tight_layout(rect=[0, 0, 1, 0.955])
    out_png = out_png or os.path.splitext(path)[0] + '.png'
    fig.savefig(out_png, dpi=120)

    # -- reporte por consola ----------------------------------------------
    print('\n  -- diagnostico de la ventana --')
    print(f'     nivel de la pre-region : {base_med*1000:.1f} mV '
          f'({diag["frac_del_umbral"]*100:.0f} % del umbral)')
    print(f'     ruido de la pre-region : {diag["ruido_V"]*1000:.2f} mV')
    if diag['pre_contaminada']:
        print(f'     *** pre CONTAMINADA: la ventana arranca sobre el flanco.')
        print(f'         `pre` deberia cubrir mas que la subida (376 ns = '
              f'{int(376e-9*FS)} muestras); tiene {pre}.')
    print('\n  -- cadencia del estimulo --')
    r_mca2 = cnt['accepted'] / max(cnt['realtime_s'], 1e-9)
    f_ped  = meta['rate_hz']
    fm = consistencia_periodo(z['t_ns'], 1e6 / r_mca2)
    fp = consistencia_periodo(z['t_ns'], 1e6 / f_ped)
    print(f'     tasa pedida     : {f_ped:.0f} Hz  -> {fp*100:5.1f} % de los dt '
          f'son multiplos de {1e6/f_ped:.0f} us')
    print(f'     tasa real (MCA) : {r_mca2:.0f} Hz  -> {fm*100:5.1f} % de los dt '
          f'son multiplos de {1e6/r_mca2:.0f} us')
    if abs(r_mca2 - f_ped) > 0.1 * f_ped:
        print(f'     *** el estimulo corre a {r_mca2/f_ped:.1f}x la tasa pedida.')
        print(f'         Toda eficiencia calculada contra la tasa PEDIDA esta '
              f'sobreestimada por ese factor.')
        print(f'         Eficiencia real del pipeline: '
              f'{100*st["n_read"]/(r_mca2*meta["duration_s"]):.1f} %')
    print('\n  -- amplitud --')
    print(f'     programada  = {esperada*1000:8.2f} mV')
    print(f'     SW (sesgado)= {np.median(h_pre)*1000:8.2f} mV')
    print(f'     SW (pico)   = {mu_s*1000:8.2f} mV   FWHM {res_s:5.2f} %')
    print(f'     HW (MCA)    = {mu_hw_v*1000:8.2f} mV   FWHM {res_h:5.2f} %'
          f'   [canal {mu_h:.0f}]')
    print(f'     SW - HW     = {dif:+.2f} %')
    print(f'\n  grafico: {out_png}')
    return out_png


# ==================================================================== main

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('npz', nargs='?', help='archivo a graficar')
    p.add_argument('--acquire', action='store_true', help='adquirir (en la Pitaya)')
    p.add_argument('--duration', type=float, default=20.0)
    p.add_argument('--rate', type=float, default=1000.0)
    p.add_argument('--amp', type=float, default=0.6, help='Vpp (pulso = amp/2)')
    p.add_argument('--width', type=float, default=2e-6, help='FWHM (2 us)')
    p.add_argument('--thr', type=float, default=0.15)
    p.add_argument('--hyst', type=float, default=0.02)
    p.add_argument('--pre', type=int, default=32)
    p.add_argument('--post', type=int, default=480)
    p.add_argument('--h-shift', type=int, default=0,
                   help='canal = cuentas de ADC >> h_shift (0)')
    args = p.parse_args()

    if args.acquire:
        path = acquire(args)
    elif args.npz:
        path = args.npz
    else:
        cands = sorted(glob.glob(os.path.join(_RAIZ, 'datos', 'e2e_espectro_*.npz')))
        if not cands:
            p.error('no hay archivos; correr con --acquire en la Pitaya')
        path = cands[-1]
        print(f'  usando el mas reciente: {path}')

    try:
        plot(path)
    except ImportError:
        print('  (sin matplotlib: copiar el .npz y graficar en la PC)')


if __name__ == '__main__':
    main()
