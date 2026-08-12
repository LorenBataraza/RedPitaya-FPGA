#!/usr/bin/env python3
"""Test end-to-end del software de adquisicion con DATOS REALES.

Corre EN LA PITAYA, con el bitstream multitrigger (o el combinado
`mca_red_pitaya.bit.bin`, que trae el scope en el slot 1) y el Rigol DG4162
por USB alimentando IN1.

A diferencia de `test_mca_pipeline.py` (que valida la mecanica con FakeSource,
en la PC), esto ejercita el unico camino que nunca se probo end-to-end:
**`BramSource` contra el hardware**, y deja los archivos medidos en disco.

El estimulo NO se arma a mano: se reusa `rigol_dg4162.pulse_train_wave()`, la
misma que usa `testbench_mca.py`. Da pulsos con forma de detector (subida +
cola exponencial) y **FWHM controlado en segundos**, con la geometria ARB
despejada -- un pulso cuadrado de `set_pulse_periodic` no se parece a lo que va
a ver el sistema en uso.

Consecuencia de usar pulsos realistas: la ventana tiene que cubrirlos. Con
FWHM = 2 us (el valor calibrado de testbench_mca.PULSE_WIDTH_S) hacen falta
~500 muestras a 125 MSa/s, no las 32 del ejemplo de juguete. Eso sube el costo
de lectura por evento y baja el techo -- lo cual es el numero honesto para la
aplicacion real.

Que verifica, en orden de importancia:

  1. ALTURA   la ventana cae SOBRE el pulso y su altura sigue a la programada.
              Es el chequeo que atrapa el bug que motivo el modo single-shot
              (con we_keep=1 el buffer daba la vuelta antes de que el lector
              llegara y se leia ruido).
  2. TASA     eficiencia n_read/(f*t) contra la tasa conocida del generador.
  3. FORMATO  los .npz se abren, la contabilidad cierra, no quedan .tmp, la
              meta trae scope_regs.
  4. TIEMPOS  Delta-t contra el periodo programado.

Los datos quedan en `--out`, asi que la corrida sirve como medicion.

Uso:
    python3 test_mca_e2e.py                    # 1 kHz, 10 s
    python3 test_mca_e2e.py --sweep            # + barrido de tasa
    python3 test_mca_e2e.py --rate 2000 --duration 20
"""
import argparse
import glob
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import rigol_dg4162 as rgmod
from mca import AcquisitionSession, BramSource, load_chunk, scope_regs

FAILS = []
N_BUF = 16384
FS    = 125e6

# El FWHM calibrado de la suite del MCA (testbench_mca.PULSE_WIDTH_S). Se usa el
# mismo para que las dos mediciones sean comparables.
PULSE_WIDTH_S = 2e-6


def check(name, cond, extra=''):
    print(f'  [{"PASS" if cond else "FAIL"}] {name}{("  " + extra) if extra else ""}')
    if not cond:
        FAILS.append(name)
    return cond


# ----------------------------------------------------------------- hardware

def open_scope():
    from multitrigger_utils import MultiTriggerScope
    import rp

    sc = MultiTriggerScope.open()
    if not sc.verify_bitstream(verbose=False)['ok']:
        sc.close()
        raise SystemExit('no se lee un scope multitrigger valido: cargar el '
                         'bitstream (multitrigger o mca_red_pitaya).')
    rp.rp_Init()
    return sc


def open_gen():
    gen = rgmod.RigolDG4162.usb()
    print(f'  generador: {gen.id.strip()}')
    gen.reset()
    return gen


def pulse_height(amp_vpp):
    """Altura REAL del pulso en la entrada, para una `amp_vpp` dada.

    `pulse_train_wave` normaliza la forma a [0, 1], pero el DG4000 interpreta
    los datos ARB como si abarcaran [-1, +1]: el valor 0 de la forma cae en el
    OFFSET (el punto medio), no en el minimo. Asi que la excursion util es la
    mitad de `amp_vpp`. Medido en la placa: amp_vpp=0.6 -> pulso de 0.295 V.
    """
    return amp_vpp / 2.0


def pulse_train(gen, rate_hz, amp_vpp, width_s=PULSE_WIDTH_S, ch=1,
                offset_v=0.0, settle_s=0.4, verbose=True):
    """Mismo estimulo que testbench_mca._pulse_train: forma de detector con
    FWHM en segundos y la frecuencia de repeticion despejada.

    Diferencia deliberada con `_pulse_train`, que usa `offset_v = amp_vpp/2`:
    aca el offset va en **0**, para que el baseline quede en 0 V. Con el offset
    a amp_vpp/2 los pulsos viajan sobre un pedestal de DC de ese valor (medido:
    baseline +0.280 V con amp_vpp=0.6), y entonces el umbral de disparo por
    flanco tiene que estar POR ENCIMA del pedestal o no hay cruce que detectar.
    Fue exactamente lo que hizo que la primera corrida diera 0 eventos.
    """
    wave, freq, info = rgmod.pulse_train_wave(width_s, rate_hz)
    if verbose:
        print(f'  estimulo: {info["n_pulses"]} pulso(s)/forma de '
              f'{width_s*1e6:g} us FWHM a {rate_hz:g} Hz '
              f'(forma a {freq:.1f} Hz, {info["srate_sa_s"]/1e6:.0f} MSa/s, '
              f'{info["fwhm_pts"]:.0f} pts/pulso)')
        print(f'  amplitud: amp_vpp={amp_vpp} V -> pulso de '
              f'{pulse_height(amp_vpp)*1000:.0f} mV sobre baseline {offset_v} V')
    gen.load_arb(wave, ch=ch)
    gen.set_arb(ch=ch, freq_hz=freq, amp_vpp=amp_vpp, offset_v=offset_v)
    gen.output(ch, True)
    time.sleep(settle_s)
    return info


# ------------------------------------------------------------------ corrida

def acquire(sc, out_dir, duration_s, args):
    src = BramSource(sc, pre=args.pre, post=args.post, n_ch=args.channels,
                     thr=args.thr, hyst=args.hyst)
    s = AcquisitionSession(src, out_dir, capacity=args.chunk,
                           ram_budget_mb=args.ram_mb, verbose=False,
                           meta=dict(test='e2e', thr_V=args.thr,
                                     pulse_width_s=PULSE_WIDTH_S))
    s.writer.meta_base['scope_regs'] = scope_regs(sc)
    with s:
        s.wait(duration_s=duration_s, poll_s=0.1)
    return s


def read_all(run_dir):
    files = sorted(glob.glob(os.path.join(run_dir, 'chunk_*.npz')))
    if not files:
        return None, None, files
    arrs, metas = [], []
    for f in files:
        a, m = load_chunk(f)
        arrs.append(a); metas.append(m)
    cat = {k: np.concatenate([a[k] for a in arrs])
           for k in ('t_ns', 'wp', 'snap', 'gap', 'wave_V')}
    return cat, metas, files


# ------------------------------------------------------------------ chequeos

def check_formato(stats, cat, metas, files, run_dir):
    print('\n  -- formato y contabilidad --')
    check('no quedan .tmp huerfanos',
          not glob.glob(os.path.join(run_dir, '*.tmp')))
    check('se escribieron chunks', len(files) > 0, f'({len(files)})')
    total = len(cat['t_ns'])
    check('eventos en disco == leidos', total == stats['n_read'],
          f'({total} vs {stats["n_read"]})')
    exact = sum(m['chunk_dropped'] for m in metas)
    summ_path = os.path.join(run_dir, 'run_summary.json')
    if check('hay run_summary.json', os.path.exists(summ_path)):
        with open(summ_path) as fh:
            summ = json.load(fh)
        tail = summ.get('trailing_dropped', 0)
        check('contabilidad cerrada (chunk_dropped + trailing == n_dropped)',
              exact + tail == stats['n_dropped'],
              f'({exact} + {tail} vs {stats["n_dropped"]})')
    check('meta trae scope_regs', 'scope_regs' in metas[0])
    check('int16 en disco', np.load(files[0])['wave'].dtype == np.int16)
    snaps = sorted(set(int(x) for x in cat['snap']))
    check('snapshot no nulo (sabemos que fuente disparo)', snaps != [0],
          f'(valores: {[hex(s) for s in snaps[:4]]})')


def check_altura(cat, amp_vpp, pre):
    """La ventana cae sobre el pulso y su altura sigue a la programada."""
    print('\n  -- altura y forma --')
    esperada = pulse_height(amp_vpp)          # amp_vpp/2, ver pulse_height()
    w    = cat['wave_V'][:, 0, :]
    base = np.median(w[:, :max(pre - 4, 1)], axis=1)
    peak = w.max(axis=1)
    alt  = np.median(peak - base)
    print(f'     base={np.median(base):+.4f} V   pico={np.median(peak):+.4f} V   '
          f'altura={alt:.4f} V   (esperada {esperada:.4f} V)')
    check('la ventana cae SOBRE el pulso (altura >> ruido)', alt > 0.05,
          f'({alt*1000:.1f} mV)')
    check('la altura coincide con la programada (+-20%)',
          abs(alt - esperada) < 0.2 * esperada,
          f'(alt/esperada = {alt/esperada:.2f})')
    # El pico tiene que caer DESPUES del trigger, dentro de la ventana.
    imax = np.median(np.argmax(w, axis=1))
    check('el pico cae dentro de la ventana, despues del trigger',
          pre <= imax <= w.shape[1] - 1, f'(argmax mediano={imax:.0f}, pre={pre})')
    print(f'     argmax mediano = {imax:.0f} de {w.shape[1]} muestras')
    return float(alt)


def check_tasa(stats, rate_hz, duration_s):
    print('\n  -- tasa y ciclo --')
    n   = stats['n_read']
    dur = stats.get('duration_s', duration_s)
    esp = rate_hz * dur
    ef  = n / esp if esp else 0.0
    print(f'     leidos={n}  esperados={esp:.0f}  eficiencia={ef*100:.1f} %  '
          f'descartes={stats["n_dropped"]}')
    if n:
        cyc = dur / n * 1e6
        print(f'     ciclo por evento = {cyc:.0f} us -> techo ~{1e6/cyc/1e3:.1f} kev/s')
    check('capturo eventos', n > 0, f'({n})')
    return ef


def check_tiempos(cat, rate_hz):
    print('\n  -- tiempos --')
    if len(cat['t_ns']) < 3:
        return
    dt_sw = np.diff(cat['t_ns']) / 1e3
    per   = 1e6 / rate_hz
    med   = float(np.median(dt_sw))
    print(f'     dt SW mediano = {med:.1f} us   (periodo programado {per:.1f} us)')
    check('el dt sigue al periodo del generador (+-30%)',
          abs(med - per) < 0.3 * per, f'({med:.0f} vs {per:.0f} us)')


# -------------------------------------------------------------------- barrido

def sweep(sc, gen, out_base, rates, duration_s, args):
    print('\n' + '=' * 70)
    print('  BARRIDO DE TASA')
    print('=' * 70)
    print(f'  {"f (Hz)":>8} {"leidos":>8} {"esperados":>10} {"efic %":>8} '
          f'{"ciclo us":>9} {"altura mV":>10}')
    rows = []
    for f in rates:
        # La geometria del ARB acota el rango: con FWHM fijo, a tasas bajas
        # hacen falta mas puntos por periodo de los que tiene el instrumento
        # (16384). pulse_train_wave lo detecta y explica; aca se saltea.
        try:
            pulse_train(gen, f, args.amp, verbose=False)
        except ValueError as exc:
            print(f'  {f:8.0f}   salteado: {str(exc).split(":")[0]}')
            continue
        run = os.path.join(out_base, f'sweep_{int(f)}Hz')
        s = acquire(sc, run, duration_s, args)
        st  = s.stats
        dur = st.get('duration_s', duration_s)
        ef  = st['n_read'] / (f * dur) if f * dur else 0
        cyc = dur / st['n_read'] * 1e6 if st['n_read'] else float('nan')
        cat, _, files = read_all(run)
        alt = float('nan')
        if cat is not None:
            w = cat['wave_V'][:, 0, :]
            alt = float(np.median(w.max(axis=1)
                                  - np.median(w[:, :max(args.pre - 4, 1)], axis=1)))
        print(f'  {f:8.0f} {st["n_read"]:8d} {f*dur:10.0f} {ef*100:8.1f} '
              f'{cyc:9.0f} {alt*1000:10.1f}')
        rows.append((f, st['n_read'], f * dur, ef, cyc, alt))
    arr = np.array(rows)
    np.savez(os.path.join(out_base, 'sweep.npz'),
             rate_hz=arr[:, 0], n_read=arr[:, 1], expected=arr[:, 2],
             efficiency=arr[:, 3], cycle_us=arr[:, 4], height_V=arr[:, 5])
    print(f'\n  ciclo minimo: {np.nanmin(arr[:, 4]):.0f} us '
          f'-> techo {1e6/np.nanmin(arr[:, 4])/1e3:.1f} kev/s')
    return arr


# ----------------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--rate', type=float, default=1000.0, help='Hz (1000)')
    p.add_argument('--duration', type=float, default=10.0, help='segundos (10)')
    p.add_argument('--amp', type=float, default=0.6, help='Vpp del pulso (0.6)')
    p.add_argument('--thr', type=float, default=0.15, help='umbral en V (0.15)')
    p.add_argument('--hyst', type=float, default=0.02, help='histeresis en V')
    # Ventana dimensionada para el pulso: 2 us de FWHM son 250 muestras a
    # 125 MSa/s, asi que 512 lo cubren con cola.
    p.add_argument('--pre', type=int, default=32, help='muestras pre-trigger (32)')
    p.add_argument('--post', type=int, default=480, help='muestras post-trigger (480)')
    p.add_argument('--channels', type=int, default=2, choices=(1, 2))
    p.add_argument('--chunk', type=int, default=512, help='eventos por chunk')
    p.add_argument('--ram-mb', type=float, default=32.0)
    p.add_argument('--sweep', action='store_true')
    p.add_argument('--out', default=None)
    args = p.parse_args()

    stamp = time.strftime('%Y%m%d_%H%M%S')
    out_base = os.path.abspath(args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'datos', f'e2e_{stamp}'))
    os.makedirs(out_base, exist_ok=True)

    print('=' * 70)
    print('  Test end-to-end del software de adquisicion (datos REALES)')
    print('=' * 70)
    print(f'  salida : {out_base}')

    sc  = open_scope()
    gen = None
    try:
        gen = open_gen()
        pulse_train(gen, args.rate, args.amp)
        print(f'  ventana: {args.pre}+{args.post} = {args.pre+args.post} muestras '
              f'({(args.pre+args.post)/FS*1e6:.1f} us) x {args.channels} ch')
        print(f'  umbral : {args.thr} V (hyst {args.hyst} V)')

        run_dir = os.path.join(out_base, 'principal')
        print(f'\n  adquiriendo {args.duration:.0f} s...')
        s = acquire(sc, run_dir, args.duration, args)
        print(s.summary())

        cat, metas, files = read_all(run_dir)
        if cat is None:
            check('se escribio al menos un chunk', False, '(ninguno)')
        else:
            check_formato(s.stats, cat, metas, files, run_dir)
            check_altura(cat, args.amp, args.pre)
            check_tasa(s.stats, args.rate, args.duration)
            check_tiempos(cat, args.rate)

        if args.sweep:
            sweep(sc, gen, out_base, [500, 1000, 2000, 4000, 8000], 5.0, args)
    finally:
        if gen is not None:
            try:
                gen.output(1, False); gen.close()
            except Exception as e:
                print(f'  aviso: no se pudo apagar el generador: {e!r}')
        try:
            sc.disarm()
        finally:
            sc.close()

    print('\n' + '=' * 70)
    print(f'  datos: {out_base}')
    print('  RESULT:', 'PASS' if not FAILS else f'FAIL ({len(FAILS)}): {FAILS}')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
