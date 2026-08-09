#!/usr/bin/env python3
"""Adquisicion continua de pulsos -> chunks .npz. Corre en la Pitaya.

Reemplaza a `guardado_mariana.py` con tres diferencias de fondo:

  - **Guarda por chunks, no todo al final.** Un corte de luz cuesta el ultimo
    chunk, no la corrida entera.
  - **Re-arma por hardware.** `arm_for_adc_trigger(auto_rearm=True)` +
    `trigger_shield` re-arman en ~24 ns, en vez del `rp_AcqStop`/`rp_AcqStart`
    por evento, que pasa por el camino de la API con ~65 us de piso.
  - **Sin `input()`.** Todo por argumentos, para poder correr como servicio.

Mantiene la convencion de nombre de carpeta y la tabla de progreso del script
original.

Ejemplos:
    python3 run_acquire.py --duration 60 --thr 0.2
    python3 run_acquire.py --events 100000 --pre 8 --post 24 --out /mnt/datos
    python3 run_acquire.py --duration 30 --fake     # sin HW, para probar el flujo
"""
import argparse
import os
import signal
import sys
import time
from datetime import datetime

sys.path.insert(0, '/opt/redpitaya/lib/python')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mca import AcquisitionSession, FakeSource
from mca.storage import free_space_mb

DEFAULT_OUT = '/home/jupyter/RedPitaya/DATOS'


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_argument_group('condicion de corte (al menos una)')
    g.add_argument('--duration', type=float, help='segundos de adquisicion')
    g.add_argument('--events', type=int, help='eventos a leer')

    g = p.add_argument_group('trigger y ventana')
    g.add_argument('--thr', type=float, default=0.2, help='umbral en V (0.2)')
    g.add_argument('--hyst', type=float, default=0.02, help='histeresis en V (0.02)')
    g.add_argument('--pre', type=int, default=8, help='muestras pre-trigger (8)')
    g.add_argument('--post', type=int, default=24, help='muestras post-trigger (24)')
    g.add_argument('--channels', type=int, default=2, choices=(1, 2),
                   help='canales a guardar (2)')
    g.add_argument('--edge', choices=('p', 'n'), default='p',
                   help='flanco del ADC ch0: p=subida (default), n=bajada')
    g.add_argument('--no-snap', action='store_true',
                   help='no leer 0x218 por evento (ahorra ~2.3 us/evento)')

    g = p.add_argument_group('salida')
    g.add_argument('--out', default=DEFAULT_OUT, help=f'directorio base ({DEFAULT_OUT})')
    g.add_argument('--label', default='', help='sufijo para el nombre de la corrida')
    g.add_argument('--chunk', type=int, default=4096, help='eventos por chunk (4096)')
    g.add_argument('--ram-mb', type=float, default=64.0,
                   help='presupuesto de RAM del pool en MB (64)')
    g.add_argument('--compress', action='store_true',
                   help='comprimir los .npz. MEDIDO: 7.3x mas lento por 12%% de '
                        'espacio. No usar salvo que el disco sea el problema.')

    g = p.add_argument_group('otros')
    g.add_argument('--fake', action='store_true',
                   help='fuente sintetica (no toca el HW)')
    g.add_argument('--fake-rate', type=float, default=5000.0,
                   help='eventos/s de la fuente sintetica (5000)')
    g.add_argument('--reload-bitstream', action='store_true',
                   help='recargar el bitstream multitrigger antes de arrancar')

    a = p.parse_args(argv)
    if a.duration is None and a.events is None:
        p.error('hace falta --duration o --events')
    return a


def run_dir_for(base, thr, label):
    """Convencion de nombre heredada: Data_<AAAAMMDD_HHMM>_TCH1_TL<mV>."""
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    mv    = int(round(thr * 1000))
    name  = f'Data_{stamp}_TCH1_TL{mv:+05d}mV'
    if label:
        name += f'_{label}'
    return os.path.join(os.path.abspath(base), name)


def make_source(args):
    if args.fake:
        return FakeSource(pre=args.pre, post=args.post, n_ch=args.channels,
                          rate_hz=args.fake_rate), None

    from multitrigger_utils import BIT_ADC_N0, BIT_ADC_P0, MultiTriggerScope
    from mca import BramSource

    if args.reload_bitstream:
        sc = MultiTriggerScope.reload_bitstream(verbose=True)
    else:
        sc = MultiTriggerScope.open()
    res = sc.verify_bitstream(verbose=False)
    if not res['ok']:
        sc.close()
        raise SystemExit('no se lee un scope multitrigger valido. '
                         'Probar con --reload-bitstream.')

    import rp
    rp.rp_Init()
    src = BramSource(sc, pre=args.pre, post=args.post, n_ch=args.channels,
                     thr=args.thr, hyst=args.hyst,
                     mask=BIT_ADC_P0 if args.edge == 'p' else BIT_ADC_N0,
                     read_snap=not args.no_snap)
    return src, sc


class Progress:
    """Tabla cada 0.5 s, como la del script original (+ descartados)."""

    HEADER = (f'{"Evento":>10} | {"Tasa (ev/s)":>12} | {"Descartes":>10} | '
              f'{"Chunks":>7} | {"Cola libre":>10}')

    def __init__(self, session, every_s=0.5):
        self.s = session
        self.every = every_s
        self.t0 = self.last = time.perf_counter()
        self.prev_n = 0
        print('=' * len(self.HEADER))
        print(self.HEADER)
        print('=' * len(self.HEADER))

    def __call__(self, stats):
        now = time.perf_counter()
        if now - self.last < self.every:
            return
        n    = stats['n_read']
        rate = (n - self.prev_n) / (now - self.last)
        print(f'{n:10d} | {rate:12.0f} | {stats["n_dropped"]:10d} | '
              f'{stats["chunks"]:7d} | {self.s.free_q.qsize():10d}', flush=True)
        self.prev_n, self.last = n, now


def main(argv=None):
    args = parse_args(argv)

    out_dir = run_dir_for(args.out, args.thr, args.label)
    os.makedirs(os.path.dirname(out_dir), exist_ok=True)
    free = free_space_mb(os.path.dirname(out_dir))

    src, scope = make_source(args)
    session = AcquisitionSession(
        src, out_dir, capacity=args.chunk, ram_budget_mb=args.ram_mb,
        compress=args.compress, verbose=False,
        meta=dict(cli=' '.join(sys.argv[1:]), edge=args.edge))

    if scope is not None:
        from mca import scope_regs
        session.writer.meta_base['scope_regs'] = scope_regs(scope)

    print('=' * 70)
    print('  Adquisicion de pulsos - pipeline mca/')
    print('=' * 70)
    print(f'  fuente     : {src.meta()["kind"]}  '
          f'{args.channels} ch x {args.pre}+{args.post} muestras')
    if not args.fake:
        print(f'  trigger    : flanco {args.edge} @ {args.thr} V (hyst {args.hyst} V)')
    print(f'  salida     : {out_dir}')
    print(f'  disco libre: {free:.0f} MB')
    print(session.describe(rate_hz=args.fake_rate if args.fake else None))
    print(f'  corte      : ' + (f'{args.duration} s' if args.duration
                                else f'{args.events} eventos'))
    print()

    stop = {'flag': False}

    def on_signal(signum, frame):
        if not stop['flag']:
            stop['flag'] = True
            print('\n[señal] cerrando limpio (Ctrl-C otra vez para forzar)...')
            raise KeyboardInterrupt
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    reason = 'interrupt'
    try:
        with session:
            prog = Progress(session)
            reason = session.wait(duration_s=args.duration,
                                  n_events=args.events, poll_s=0.05,
                                  on_tick=prog)
    except KeyboardInterrupt:
        pass
    finally:
        if scope is not None:
            try:
                scope.close()
            except Exception:
                pass

    print('\n' + '=' * 70)
    print(f'  fin ({reason})')
    print(session.summary())
    print(f'  datos: {out_dir}')
    return 0 if not session.stats.get('error') else 1


if __name__ == '__main__':
    sys.exit(main())
