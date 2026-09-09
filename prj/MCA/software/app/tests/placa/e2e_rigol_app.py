#!/usr/bin/env python3
"""(P,R) La aplicación entera contra pulsos REALES del Rigol. Corre EN LA PITAYA.

Es el único test que cierra el lazo completo:

    Rigol DG4162 --cable--> IN1 --> MCA en la PL --> mca_server --TCP--> MCARemote

Todo lo demás prueba una mitad. `app/tests/test_mca_remote.py` prueba el
protocolo contra un MCA simulado; `API/tests/placa/test_mca_datapath.py` prueba
el camino de datos sin la aplicación. Acá el estímulo es físico y el cliente
habla por socket, así que si el número que sale en pantalla es el que inyectó el
generador, están bien las dos mitades y la costura.

El servidor se levanta como subproceso en 127.0.0.1: no se conecta al del puerto
1001 por si hay una GUI usándolo — el servidor acepta UN cliente a la vez.

    python3 app/tests/placa/e2e_rigol_app.py --outdir datos/e2e_app
    python3 app/tests/placa/e2e_rigol_app.py --rate 5000 --segundos 20

Requiere: bitstream del MCA cargado (`make verificar-placa-bitstream`), Rigol por USB, y
que ningún otro proceso tenga /dev/mem abierto.
"""

import argparse
import os
import socket
import subprocess
import sys
import threading
import time

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import API.rigol_dg4162 as rg                                      # noqa: E402
from API.analisis import gauss_fit_peak                            # noqa: E402
from API.mca import (mca_get_metadata, mca_read_counters,          # noqa: E402
                     mca_read_histogram, mca_read_map2d,
                     mca_save_file_binary, mca_write_file_histogram)
from API.mca_remote import MCARemote                               # noqa: E402

# El estímulo, con los mismos números que la campaña validada
# (campanas/testbench_mca.py: PULSE_WIDTH_S y DEFAULT_CFG).
ANCHO_PULSO_S = 2e-6
CFG_MCA = dict(thr=100, hyst=40, baseline=0, bl_auto=True, bl_k=12,
               bl_holdoff=64, maxlen=4096, tail_dly=8, amp_src=0,
               q_shift=0, h_shift=0, h2_shift=7, dec=1, channel=0)

_pass = _fail = 0


def check(nombre, cond, detalle='', pista=''):
    """`pista` sale SÓLO si falla: es el diagnóstico, no la medida.

    Sin separarlo, un check que pasa imprime igual "¿el cable está en IN1?" y
    el que lee la salida no sabe si eso es un aviso o no.
    """
    global _pass, _fail
    if cond:
        _pass += 1
        print(f'  [OK  ] {nombre}' + (f'   {detalle}' if detalle else ''))
    else:
        _fail += 1
        print(f'  [FALLA] {nombre}' + (f'   {detalle}' if detalle else ''))
        if pista:
            print(f'          {pista}')
    return cond


# =============================================================================
# El servidor, como subproceso
# =============================================================================

class Servidor:
    """`app/mca_server.py` contra el hardware real, en un puerto de loopback.

    La espera al arranque lee la línea "escuchando" de su stdout en vez de
    abrir un socket de sondeo: el servidor acepta un solo cliente y el sondeo
    se gastaría el cupo. Es el mismo patrón que `app/tests/test_mca_remote.py`.
    """

    def __init__(self, puerto=None):
        self.port = puerto or self._puerto_libre()
        self.salida = []

    @staticmethod
    def _puerto_libre():
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def __enter__(self):
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(_RAIZ, 'app', 'mca_server.py'),
             '--host', '127.0.0.1', '--port', str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self._listo = threading.Event()
        threading.Thread(target=self._drenar, daemon=True).start()
        if not self._listo.wait(20.0):
            raise TimeoutError('el servidor no llegó a escuchar:\n'
                               + ''.join(self.salida))
        return self

    def _drenar(self):
        for linea in self.proc.stdout:
            self.salida.append(linea)
            if 'escuchando' in linea:
                self._listo.set()
        self._listo.set()

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def conectar(self):
        return MCARemote.connect('127.0.0.1', self.port, timeout=30.0)


# =============================================================================
# El estímulo
# =============================================================================

def encender_generador(gen, ch, rate_hz, amp_vpp, ancho_s=ANCHO_PULSO_S):
    """Tren de pulsos de detector, ancho fijo en segundos.

    `pulse_train_wave` despeja la frecuencia de repetición de la FORMA a partir
    del ancho pedido y de cuántos pulsos entran en ella: `set_arb` estira la
    forma completa sobre 1/freq, así que pedir "ancho" y "tasa" a la vez sólo
    se puede resolviendo la geometría, no fijando freq=tasa.
    """
    onda, freq, info = rg.pulse_train_wave(ancho_s, rate_hz)
    gen.load_arb(onda, ch=ch)
    # offset = amp/2 deja el tren unipolar positivo: la base queda en amp/2 y
    # el pico en amp, o sea altura de pulso = amp/2. Es la convención de
    # campanas/testbench_mca.py y la que espera el seguidor de línea de base.
    gen.set_arb(ch=ch, freq_hz=freq, amp_vpp=amp_vpp, offset_v=amp_vpp / 2)
    gen.output(ch, True)
    time.sleep(0.3)
    print(f'  estímulo: {info["n_pulses"]} pulso(s)/forma de '
          f'{ancho_s * 1e6:g} us a {rate_hz:g} Hz nominales, '
          f'{amp_vpp:g} Vpp (altura {amp_vpp / 2:g} V)')
    return info


# =============================================================================
# La corrida
# =============================================================================

def correr(args):
    print('=== 1. generador ===')
    gen = rg.RigolDG4162.usb()
    print(f'  {gen.id}')
    gen.reset()
    info_gen = encender_generador(gen, args.gen_ch, args.rate, args.amp)

    try:
        with Servidor(args.puerto) as srv:
            print(f'\n=== 2. servidor en 127.0.0.1:{srv.port} ===')
            h = srv.conectar()
            try:
                return _sesion(h, args, info_gen)
            finally:
                h.close()
    finally:
        gen.output(args.gen_ch, False)
        gen.close()
        print('\ngenerador apagado')


def _sesion(h, args, info_gen):
    # --- identificación, como la que hace la GUI al conectarse ---------------
    info = h.info
    print(f"  MCA presente: {info.get('presente')}, "
          f"{info.get('n_channels')} canales, "
          f"mapa 2D {'si' if info.get('has_2d') else 'no'}, "
          f"PL {info.get('fpga_state')}")
    if not check('el servidor encuentra el MCA', bool(info.get('presente')),
                 str(info.get('error', ''))):
        return 1
    n_canales = info['n_channels']
    check('geometría publicada por el hardware', n_canales in (8192, 16384),
          f'{n_canales} canales (h_aw={info["h_aw"]})')

    # --- configuración -------------------------------------------------------
    print('\n=== 3. configuración ===')
    cfg = dict(CFG_MCA, channel=args.channel)
    h.configure(**cfg)
    leido = h.config()
    malos = [k for k, v in cfg.items() if leido.get(k) != v]
    check('la config releída coincide con la escrita', not malos,
          'difieren: ' + ', '.join(malos) if malos else
          f"thr={leido['thr']} hyst={leido['hyst']} bl_k={leido['bl_k']} "
          f"canal={leido['channel']}")

    # --- adquisición temporizada, con poleo como el de la GUI ----------------
    print(f'\n=== 4. adquisición de {args.segundos} s (tiempo vivo) ===')
    h.clear()
    vacio = mca_read_histogram(h)
    check('clear deja el espectro en cero', int(vacio.sum()) == 0,
          f'{int(vacio.sum())} cuentas')

    h._pedir('ctrl.start', seconds=float(args.segundos), clear_first=False)
    muestras = []
    t0 = time.time()
    while time.time() - t0 < args.segundos + 15:
        est = h.status()
        muestras.append((time.time() - t0, est['counters']['livetime_s'],
                         est['counters']['accepted'], est['rate_inst_hz']))
        if not est['running']:
            break
        time.sleep(0.5)
    else:
        check('la exposición terminó sola', False, 'se pasó del timeout')
        h.stop()

    est = h.status()
    check('la exposición paró sola', not est['running'])
    check('la exposición marcada como completa',
          bool(est['exposure'].get('done')))

    cnt = mca_read_counters(h)
    lt = cnt['livetime_s']
    check('el tiempo vivo es el pedido', abs(lt - args.segundos) < 0.5,
          f'{lt:.3f} s pedidos {args.segundos:g} s')

    # --- el espectro ---------------------------------------------------------
    print('\n=== 5. espectro ===')
    hist = mca_read_histogram(h)
    meta = h.metadata()
    total = int(hist.sum())
    print(f"  {total} cuentas, contadores: total={cnt['total']} "
          f"aceptados={cnt['accepted']} rech_amp={cnt['rej_amp']} "
          f"apilados={cnt['pileup']} perdidos={cnt['dropped']}")
    print(f"  real={cnt['realtime_s']:.3f} s vivo={lt:.3f} s "
          f"muerto={cnt['deadtime_s']:.3f} s")

    if not check('llegaron eventos', total > 0, f'{total} cuentas',
                 pista='CERO cuentas: ¿el cable del Rigol está en IN1? '
                       '¿el umbral es más alto que el pulso?'):
        return 1
    check('el espectro coincide con el contador de aceptados',
          total == cnt['accepted'], f'{total} vs {cnt["accepted"]}')

    # La tasa medida contra la inyectada. El generador repite una forma con
    # n_pulses pulsos a freq Hz, así que la tasa real es n_pulses*freq.
    tasa_med = cnt['accepted'] / lt if lt > 0 else 0
    error_pct = 100 * abs(tasa_med - args.rate) / args.rate
    check('la tasa medida es la inyectada', error_pct < 5.0,
          f'{tasa_med:.1f} Hz medidos vs {args.rate:g} Hz inyectados '
          f'({error_pct:.2f} %)')

    # --- el pico -------------------------------------------------------------
    pico_bin = int(np.argmax(hist))
    ancho = max(64, n_canales // 64)
    lo, hi = max(0, pico_bin - ancho), min(n_canales, pico_bin + ancho)
    aj = gauss_fit_peak(hist, lo, hi)
    print(f"  pico en el canal {pico_bin}: centroide {aj['centroid']:.1f}, "
          f"FWHM {aj['fwhm']:.2f}, resolución {aj['resolution_pct']:.3f} %")
    check('hay un fotopico y no ruido plano', not aj.get('empty'))
    check('el pico está dentro de la escala', 0 < pico_bin < n_canales - 1,
          f'canal {pico_bin} de {n_canales}')
    check('el area del pico es la mayoría de las cuentas',
          aj['area'] > 0.5 * total,
          f"{aj['area']:.0f} de {total}")
    check('la resolución es razonable para un pulser',
          aj['resolution_pct'] < 15.0, f"{aj['resolution_pct']:.3f} %")

    # La amplitud esperada: altura de pulso = amp/2 volts, y el eje son cuentas
    # de ADC (ADC_CNT_PER_V = 8192 en LV) desplazadas por h_shift.
    esperado = (args.amp / 2) * 8192 / (1 << cfg['h_shift'])
    check('el centroide cae donde lo pone el generador',
          abs(aj['centroid'] - esperado) < 0.35 * esperado,
          f"centroide {aj['centroid']:.0f}, esperado ~{esperado:.0f} "
          f"para {args.amp / 2:g} V")

    # --- estabilidad durante la corrida --------------------------------------
    tasas = [r for _, _, _, r in muestras[2:] if r > 0]
    if tasas:
        disp = 100 * np.std(tasas) / np.mean(tasas)
        check('la tasa instantánea es estable', disp < 25.0,
              f'{np.mean(tasas):.0f} Hz +- {disp:.1f} %')

    # --- lo que la GUI hace además -------------------------------------------
    print('\n=== 6. lo que ofrece la aplicación ===')
    check('metadata completa para el fichero', len(meta) >= 30,
          f'{len(meta)} claves, thr={meta.get("thr")} '
          f'livetime={meta.get("livetime_s"):.3f}')
    if info.get('has_2d'):
        m2d = mca_read_map2d(h)
        check('el mapa 2D tiene cuentas', int(m2d.sum()) > 0,
              f'{int(m2d.sum())} eventos en {m2d.shape}')
    else:
        m2d = None

    ultimo = h._pedir('read.last_event')[0]['result']
    check('el registro de último evento responde', 'amp' in ultimo,
          f"amp={ultimo.get('amp')} q_tot={ultimo.get('q_tot')}")

    # --- guardado, con las mismas funciones que usa el botón de la GUI -------
    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)
        csv = os.path.join(args.outdir, 'espectro.csv')
        npz = os.path.join(args.outdir, 'espectro.npz')
        mca_write_file_histogram(hist, csv, meta=meta)
        mca_save_file_binary(hist, npz, meta=meta)
        np.savez_compressed(os.path.join(args.outdir, 'corrida.npz'),
                            hist=hist, muestras=np.array(muestras),
                            map2d=m2d if m2d is not None else np.zeros(1),
                            esperado=esperado, rate_nominal=args.rate,
                            n_pulses_por_forma=info_gen['n_pulses'])
        check('los ficheros quedaron escritos',
              os.path.getsize(csv) > 0 and os.path.getsize(npz) > 0,
              args.outdir)

    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--rate', type=float, default=2000.0,
                    help='tasa de pulsos inyectada, Hz')
    ap.add_argument('--amp', type=float, default=0.6,
                    help='amplitud pico a pico del generador, V')
    ap.add_argument('--segundos', type=float, default=10.0,
                    help='tiempo VIVO de exposición')
    ap.add_argument('--channel', type=int, default=0, help='0 = IN1, 1 = IN2')
    ap.add_argument('--gen-ch', type=int, default=1, help='canal del Rigol')
    ap.add_argument('--puerto', type=int, default=None)
    ap.add_argument('--outdir', default=None)
    args = ap.parse_args(argv)

    print(f'e2e de la aplicación con pulsos reales — {time.strftime("%H:%M:%S")}\n')
    try:
        rc = correr(args)
    except Exception as e:                                        # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f'\nABORTADO: {type(e).__name__}: {e}')
        return 2

    print(f'\nRESULTADO: {_pass} PASS, {_fail} FALLA')
    return 1 if (_fail or rc) else 0


if __name__ == '__main__':
    sys.exit(main())
