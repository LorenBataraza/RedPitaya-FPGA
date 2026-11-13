"""Pérdidas con arribos POISSON en el LECTOR DE PYTHON (multitrigger + BRAM).

Por qué existe aparte de `testbench_mca.sweep_rate_poisson`: las dos
arquitecturas se miden distinto.

  - El MCA cuenta por hardware los eventos que llegaron con el extractor
    ocupado (`cnt_dropped`), así que la pérdida sale directo del propio equipo.
  - **Este lector no tiene ese contador.** Su `stats['n_dropped']`
    (mca/reader.py:96) cuenta sólo *backpressure* — que no hubiera un batch
    libre —, no los eventos perdidos mientras leía: `wp_trig` avanza dos veces
    entre dos polls y nadie se entera. Acá la verdad de referencia la tiene que
    dar el estímulo, y por eso se usa el ARB: sabemos exactamente cuántos pulsos
    emitió.

        P_loss = 1 − n_leidos / (n_events × freq_hz × T)

El punto de la medición: con el tren PERIÓDICO este lector daba 99.1 % de
eficiencia a 2 kHz (arquitectura_adquisicion_software.md), porque con arribos
deterministas y K=1 no se pierde nada mientras el período supere el servicio.
Con Poisson y τ = 252.7 µs el modelo dice ~33 % de pérdida a esa misma tasa.

**Desde la Parte 6 el lazo es de C**, y τ bajó a ~20 µs (medido en la placa el
2026-11-08: la pérdida sigue a Poisson con τ = 20 µs a menos de 2.3 pp entre 5 y
100 kHz). Para esas tasas, `--tau-us 20`; el default de 252.7 repite las del lector de
Python, para comparar.

**Con `--fuente ring`** lee el event_ring en vez de la BRAM (necesita su bitstream). El
ring cuenta su propia pérdida, y la tabla la suma: `DROP_BUSY` (un disparo con una
ventana en vuelo) y `DROP_FULL` (el PS no vació el ring). El lector ya no está en el
camino del disparo, así que lo que se espera es el apilamiento del estímulo hasta que
el escritor no dé abasto. Para medir el ring sin el estímulo analógico (sin el
apilamiento ni el Rigol), `run_etapas_ring.py`, con el generador de eventos de la FPGA.

Uso:
    python3 campanas/run_poisson_loss.py <outdir> [--rhos 0.05,0.1,0.2,0.5,0.9]
                                [--tau-us 252.7] [--sub-s 4] [--semillas 5]
                                [--fuente bram|ring]
"""
import argparse
import json
import os
import shutil
import sys
import time

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import rigol_dg4162 as rg


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('outdir')
    p.add_argument('--rhos', default=None,
                   help='ocupaciones a medir (rho = lambda*tau). Por default, '
                        '16 puntos log-espaciados de 0.02 a 2: la comparacion '
                        'contra el modelo periodico (cero hasta rho=1) se juega '
                        'en esa decada y con pocos puntos no se ve la forma')
    p.add_argument('--tau-us', type=float, default=252.7,
                   help='tiempo de servicio del lector, para elegir las tasas')
    p.add_argument('--sub-s', type=float, default=4.0,
                   help='segundos por realizacion (semilla)')
    p.add_argument('--semillas', type=int, default=5,
                   help='realizaciones distintas por punto')
    p.add_argument('--width-us', type=float, default=None,
                   help='ancho del pulso; por default el minimo que entre')
    p.add_argument('--n-events', type=int, default=64,
                   help='eventos medios por ciclo del ARB')
    p.add_argument('--amp-vpp', type=float, default=0.5)
    p.add_argument('--ch', type=int, default=1)
    p.add_argument('--pre', type=int, default=8)
    p.add_argument('--post', type=int, default=24)
    p.add_argument('--channels', type=int, default=2)
    p.add_argument('--thr', type=float, default=0.25)
    p.add_argument('--hyst', type=float, default=0.02)
    p.add_argument('--reload-bitstream', action='store_true')
    p.add_argument('--formato', choices=('npz', 'lh5'), default='npz',
                   help='con qué escribe el pipeline: para comparar los descartes')
    p.add_argument('--fuente', choices=('bram', 'ring'), default='bram',
                   help='de dónde lee: la BRAM del osciloscopio o el event_ring')
    return p.parse_args(argv)


def ancho_minimo(rate_hz, n_events, t_rise_frac=0.25,
                 min_rise_pts=2, n_pts=rg.ARB_MAX_POINTS):
    """Ancho de pulso mínimo que el ARB puede dibujar a esa tasa.

    `dt = n_events/(rate*n_pts)` y el flanco necesita `min_rise_pts`, así que
    `width >= min_rise_pts*dt/t_rise_frac`. A 400 ev/s con 64 eventos por ciclo
    son ~79 us: **a tasas bajas el pulso tiene que ser ancho**, y no hay forma
    de esquivarlo con 16384 puntos de memoria.

    `min_rise_pts=2` (contra los 4 del default de `pulse_train_wave`) porque
    este test sólo necesita un flanco limpio que cruce el umbral: el lector
    dispara por flanco y no integra la forma. Para el MCA, que sí integra, hay
    que dejar los 4.
    """
    dt = n_events / (rate_hz * n_pts)
    return min_rise_pts * dt / t_rise_frac


def elegir_n_events(rate_hz, tau_s, n_max=64, n_min=8, frac_tau=0.1, **kw):
    """Eventos por ciclo que dejan el pulso despreciable frente a `tau_s`.

    El compromiso del ARB es `dt = n_events/(rate*n_pts)`: más eventos por ciclo
    (mejor estadística por realización) cuestan resolución temporal, y a tasas
    bajas eso obliga a un pulso ancho. Acá se elige el mayor `n_events` que
    mantenga `width_min <= frac_tau*tau`, para que el ancho del pulso no
    contamine la medición de pérdidas. Devuelve (n_events, width_min).
    """
    n = int(n_max)
    while n > n_min and ancho_minimo(rate_hz, n, **kw) > frac_tau * tau_s:
        n //= 2
    return n, ancho_minimo(rate_hz, n, **kw)


def main(argv=None):
    args = parse_args(argv)
    os.makedirs(args.outdir, exist_ok=True)
    tau = args.tau_us * 1e-6
    rhos = (np.logspace(np.log10(0.02), np.log10(2.0), 16) if not args.rhos
            else np.array([float(x) for x in args.rhos.split(',')], dtype=float))
    rates = rhos / tau

    from multitrigger_utils import BIT_ADC_P0, MultiTriggerScope
    from mca import AcquisitionSession, BramSource
    from API.osciloscope_ring import RingSource

    if args.reload_bitstream:
        sc = MultiTriggerScope.reload_bitstream(verbose=True)
    else:
        sc = MultiTriggerScope.open()
    if not sc.verify_bitstream(verbose=False)['ok']:
        sc.close()
        raise SystemExit('no se lee un scope multitrigger valido '
                         '(probar --reload-bitstream)')

    import rp
    # rp_Init() no hace falta para leer (el lazo es de libmca) y no cambia ninguna
    # muestra: el ecualizador que configura no está en el bitstream (EN_FILT = 0).
    # Queda para que la API siga siendo compatible con la de Red Pitaya.
    rp.rp_Init()
    gen = rg.RigolDG4162.usb()
    print(f'generador: {gen.id}')
    gen.reset()

    Fuente = RingSource if args.fuente == 'ring' else BramSource
    src = Fuente(sc, pre=args.pre, post=args.post, n_ch=args.channels,
                 thr=args.thr, hyst=args.hyst, mask=BIT_ADC_P0)
    # El run_dir es descartable: acá interesa el conteo del lector, no los
    # datos. Se borra al final para no dejar GB de ventanas por ahí.
    run_dir = os.path.join(args.outdir, '_scratch_run')
    ses = AcquisitionSession(src, run_dir, verbose=False, formato=args.formato,
                             meta={'test': 'poisson_loss', 'tau_us': args.tau_us,
                                   'fuente': args.fuente})

    def perdida_hw():
        """EV_CNT, DROP_BUSY y DROP_FULL del ring; con la BRAM no hay. EV_CNT contra
        lo leído dice si un evento que falta no disparó o no se leyó."""
        if args.fuente != 'ring':
            return 0, 0, 0
        k = src.hw_counters()
        return k['hw_ev_cnt'], k['hw_drop_busy'], k['hw_drop_full']

    def error_hilos():
        """El error del lector o del escritor, si alguno se cayó: los cuentan en
        `stats['error']` y siguen sin avisar, y el barrido mediría ceros."""
        errs = [f'{n}: {h.error!r}' for n, h in (('lector', ses.reader),
                                                  ('escritor', ses.writer))
                if h.error is not None]
        return '; '.join(errs) or None

    t_est = len(rhos) * args.semillas * (args.sub_s + 0.4)
    print(f'{len(rhos)} puntos x {args.semillas} semillas x {args.sub_s:g} s '
          f'-> ~{t_est/60:.1f} min de barrido')
    filas = []
    try:
        ses.start()
        time.sleep(0.5)
        for rho_pedido, r in zip(rhos, rates):
            n_ev, w_min = elegir_n_events(r, tau, n_max=args.n_events)
            w = (args.width_us * 1e-6 if args.width_us
                 else max(1.2 * w_min, 2e-6))
            if w > 0.25 * tau:
                print(f'  {r:8.0f} Hz: SALTEADO — ni con {n_ev} eventos por '
                      f'ciclo el pulso baja de {w*1e6:.0f} us, que no es '
                      f'despreciable frente a tau ({args.tau_us:.0f} us).')
                continue

            det = emi = ev = busy = full = 0
            infos = []
            for k in range(args.semillas):
                info = rg.apply_poisson_train(
                    gen, rate_hz=r, width_s=w, ch=args.ch,
                    amp_vpp=args.amp_vpp, n_events=n_ev, min_rise_pts=2,
                    seed=1000 * k + int(r) % 997)
                gen.output(args.ch, True)
                infos.append(info)
                time.sleep(0.4)                       # transitorio de la recarga
                n0 = ses.stats['n_read']
                e0, b0, f0 = perdida_hw()
                t0 = time.perf_counter()
                time.sleep(args.sub_s)
                dt_s = time.perf_counter() - t0
                det += ses.stats['n_read'] - n0
                e1, b1, f1 = perdida_hw()
                ev += e1 - e0
                busy += b1 - b0
                full += f1 - f0
                # emitidos = pulsos por ciclo x ciclos por segundo x segundos
                emi += info['n_events'] * info['freq_hz'] * dt_s

            p_loss = 1.0 - det / max(emi, 1e-9)
            rho = r * tau
            filas.append(dict(
                rate_hz=float(r), rho_pedido=float(rho_pedido), rho=float(rho),
                width_s=float(w), n_events_cfg=int(n_ev),
                n_events=int(np.mean([i['n_events'] for i in infos])),
                detectados=int(det), emitidos=float(emi),
                p_loss=float(p_loss),
                p_loss_poisson=float(rho / (1 + rho)),
                p_loss_periodico=float(1 - 1 / max(np.ceil(rho), 1.0)),
                frac_pileup=float(np.mean([i['frac_pileup'] for i in infos])),
                n_dropped_bp=int(ses.stats['n_dropped']),
                hw_ev_cnt=int(ev), hw_drop_busy=int(busy), hw_drop_full=int(full),
                dt_s=float(infos[0]['dt_s']), error=error_hilos(),
            ))
            f = filas[-1]
            print(f'  {r:8.0f} Hz  rho={rho:5.3f}  w={w*1e6:5.1f} us  '
                  f'det={det:6d}/{emi:8.0f}  P_loss={100*p_loss:5.1f}%  '
                  f'(Poisson {100*f["p_loss_poisson"]:5.1f}%, '
                  f'periodico {100*f["p_loss_periodico"]:5.1f}%)  '
                  f'pileup={100*f["frac_pileup"]:4.1f}%'
                  + (f'  ring: ev={ev} busy={busy} full={full}'
                     if args.fuente == 'ring' else ''))
            if f['error']:
                print(f'  CORTADO: se cayó un hilo de la sesión, los puntos siguientes '
                      f'no valen.\n    {f["error"]}')
                break
    finally:
        try:
            gen.output(args.ch, False); gen.close()
        except Exception as e:
            print('warn generador:', e)
        try:
            ses.stop()
        except Exception as e:
            # Sin esto, una parada que falla se lleva lo medido. Con el ring lleno,
            # parar no termina (DRAINING espera créditos): CTRL <- 0x2 lo destraba.
            print(f'warn: la sesión no paró bien: {e!r}')
        sc.close()
        shutil.rmtree(run_dir, ignore_errors=True)

    if filas:
        col = lambda k: np.array([f[k] for f in filas], dtype=float)
        np.savez_compressed(os.path.join(args.outdir, 'poisson_loss_lector.npz'),
                            **{k: col(k) for k in
                               ('rate_hz', 'rho', 'p_loss', 'p_loss_poisson',
                                'p_loss_periodico', 'width_s', 'detectados',
                                'emitidos', 'frac_pileup', 'dt_s')})
        with open(os.path.join(args.outdir, 'poisson_loss_lector.json'), 'w') as fh:
            json.dump(filas, fh, indent=2)
        pl, rho = col('p_loss'), col('rho')
        e_p = np.abs(pl - rho / (1 + rho)).mean()
        e_d = np.abs(pl - (1 - 1 / np.maximum(np.ceil(rho), 1))).mean()
        print(f'\n  |medido - Poisson|   medio = {100*e_p:.2f} pp')
        print(f'  |medido - periodico| medio = {100*e_d:.2f} pp')
        print(f'  => los datos se parecen mas al modelo '
              f'{"POISSON" if e_p < e_d else "PERIODICO"}')
        print(f'\n=== {args.outdir}/poisson_loss_lector.npz ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
