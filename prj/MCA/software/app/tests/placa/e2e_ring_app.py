#!/usr/bin/env python3
"""(P) El ring de mcamon contra la placa, sin pantalla. Corre EN LA PC, contra el
`mca_server` de la placa con el bitstream del ring.

    mcamon («OSC settings», el ring) --TCP--> mca_server --> AdquisicionRing
                                                                   --> event_ring

Maneja el ring de la pestaña como un usuario (los mismos widgets, las mismas ops
`ring.*`) en tres corridas:

  A. el generador de eventos, periódico, N = 200 000 a 100 k/s: sin pérdidas, y
     EV_CNT + DROP_BUSY + DROP_FULL = N exacto;
  B. el generador Poisson a 500 k/s, sin fin: la placa lee unos 190 k/s, así que el
     ring está lleno cuando se para;
  C. el disparo del ADC, con `gen_pulsos` por el lazo digital a 10 k/s: un disparo
     por pulso, sin pérdidas. El umbral es el de la etapa Disparo de la pestaña.

En las tres, la franja de la pestaña tiene que mostrar las cuentas finales.

En las tres, lo de parar (`AcquisitionSession.stop`): el estímulo se corta con el ring
corriendo y el lector se lleva lo que quedó, así que al final leídos = EV_CNT exacto,
nada sin leer, sin error y sin destrabar el ring (con B, que está lleno, también).

Deja la placa como estaba: la corrida parada, el generador parado, el lazo apagado,
y las corridas borradas de la placa (con --guardar, quedan).

    make verificar-placa-ring-app

Requiere el bitstream del ring con los dos generadores (c1875919 o posterior):
`campanas/preparar_placa.py --cargar --bitstream /root/event_ring_red_pitaya_Z10_2CH.bit.bin`
en la placa, con el servidor parado antes y levantado después.
"""

import argparse
import os
import subprocess
import sys
import time

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

from API.mca_net import PORT_DEFAULT                                # noqa: E402

N_A = 200_000
TASA_C = 10_000

_pass = _fail = 0


def check(nombre, cond, detalle=''):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
    print(f"  [{'OK  ' if cond else 'FALLA'}] {nombre}"
          + (f'   {detalle}' if detalle else ''))
    return cond


def esperar(app, condicion, timeout=15.0, paso=0.02):
    """Corre el lazo de eventos de Qt hasta que se cumpla `condicion`."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if condicion():
            return True
        time.sleep(paso)
    return False


class Placa:
    """Lo que no pasa por la app: mirar y borrar los archivos de una corrida."""

    def __init__(self, ssh):
        self.ssh = ssh
        self.corridas = []

    def correr(self, cmd):
        return subprocess.run(['ssh', self.ssh, cmd], capture_output=True, text=True,
                              timeout=60).stdout

    def archivos(self, run_dir):
        """(cuántos archivos, kB) del directorio de la corrida."""
        self.corridas.append(run_dir)
        n, kb = self.correr(f'ls {run_dir} | wc -l; du -sk {run_dir} | cut -f1').split()
        return int(n), int(kb)

    def borrar(self):
        for d in self.corridas:
            # Sólo lo que creó la pestaña: <carpeta>/ring_<fecha>.
            if os.path.basename(d).startswith('ring_'):
                self.correr(f'rm -rf {d}')
        self.corridas = []


def corrida(app, v, placa, nombre, preparar, dur_s=None, hasta=None, captura=None):
    """Una corrida desde la pestaña: preparar, Iniciar, esperar, Parar. Verifica lo que
    vale para todas y devuelve (lo final, los disparos)."""
    p = v.panel_ring
    v.tabs.setCurrentWidget(v.panel_config_osc)
    preparar(p)
    p.btn_iniciar.click()
    if not esperar(app, lambda: p.ultimo.get('corriendo'), timeout=20):
        raise AssertionError(f'{nombre}: no arrancó: {p.lbl_error.text()}')
    if hasta is not None:
        if not esperar(app, lambda: hasta(p.ultimo), timeout=60):
            raise AssertionError(f'{nombre}: no llegó al final: {p.ultimo}')
    else:
        t0 = time.time()
        esperar(app, lambda: time.time() - t0 > dur_s, timeout=dur_s + 5)
    if captura:
        for _ in range(30):
            app.processEvents()
            time.sleep(0.02)
        v.grab().save(captura)
    p.btn_parar.click()
    if not esperar(app, lambda: not p.ultimo.get('corriendo'), timeout=60):
        raise AssertionError(f'{nombre}: no paró')
    fin = p.ultimo
    hw, st = fin['hw_final'], fin['stats']
    disp = hw['hw_ev_cnt'] + hw['hw_drop_busy'] + hw['hw_drop_full']
    print(f"\n=== {nombre}: {fin['run_dir']} ({fin.get('fs')})")
    print(f"  disparos {disp} = EV {hw['hw_ev_cnt']} + BUSY {hw['hw_drop_busy']} + FULL "
          f"{hw['hw_drop_full']}; leídos {st['n_read']}, escritos {st['n_written']} en "
          f"{st['chunks']} archivos, {st.get('rate_ev_s', 0):.0f} ev/s")
    check(f'{nombre}: sin error', fin['error'] is None and fin['motivo'] in (None, 'source'),
          f"motivo {fin['motivo']}, error {fin['error']}")
    check(f'{nombre}: se vació antes de parar, sin destrabar',
          st.get('vaciado') is True and hw.get('hw_destrabe') is None,
          f"vaciado {st.get('vaciado')}, destrabe {hw.get('hw_destrabe')}")
    check(f'{nombre}: leídos = EV_CNT, nada sin leer',
          st['n_read'] == hw['hw_ev_cnt'] and hw.get('hw_no_leidos') == 0,
          f"{st['n_read']} contra {hw['hw_ev_cnt']}, sin leer {hw.get('hw_no_leidos')}")
    check(f'{nombre}: se escribió todo lo leído', st['n_written'] == st['n_read'])
    fl = v.panel_config_osc.diagrama.flujo or {}
    check(f'{nombre}: la franja muestra las cuentas finales',
          fl.get('disparos') == disp and fl.get('leidos') == st['n_read'],
          f'{fl}')
    n, kb = placa.archivos(fin['run_dir'])
    check(f'{nombre}: los archivos están en la placa', n >= st['chunks'] > 0,
          f'{n} archivos, {kb} kB')
    return fin, disp


def sesion(app, v, placa, args):
    if not check('el servidor tiene el ring y su generador',
                 v.panel_ring is not None and bool(v.info.get('has_gen')),
                 f"has_ring={v.info.get('has_ring')} has_gen={v.info.get('has_gen')}"):
        print('  ¿está cargado el bitstream del ring? (ver el docstring)')
        return
    cmb = v.panel_ring.cmb_estimulo
    check('el generador de eventos está disponible en la pestaña',
          cmb.model().item(cmb.findData('generador')).isEnabled())

    def captura(nombre):
        return os.path.join(args.capturas, nombre) if args.capturas else None

    # --- A: N fijo: las cuentas cierran exacto --------------------------------
    def prep_a(p):
        p.ed_carpeta.setText(args.carpeta)
        p.cmb_estimulo.setCurrentIndex(p.cmb_estimulo.findData('generador'))
        p.cmb_modo.setCurrentIndex(0)                  # periódico
        p.spn_tasa.setValue(1e5)
        p.spn_n.setValue(N_A)
        p.spn_pre.setValue(8)
        p.spn_post.setValue(24)
    fin, disp = corrida(app, v, placa, f'A periódico, N = {N_A}', prep_a,
                        hasta=lambda e: (e.get('hw') or {}).get('hw_gen_terminado')
                        and (e.get('stats') or {}).get('n_read', 0)
                        >= (e.get('hw') or {}).get('hw_ev_cnt', 1))
    hw = fin['hw_final']
    check('A: EV + BUSY + FULL = N', disp == N_A, f'{disp}')
    check('A: el generador dio N y terminó, sin cortarlo',
          hw.get('hw_gen_cnt') == N_A and hw.get('hw_gen_terminado')
          and not hw.get('hw_gen_cortado'))
    check('A: a 100 k/s no pierde', hw['hw_drop_busy'] == 0 and hw['hw_drop_full'] == 0)

    # --- B: Poisson sin fin, el ring lleno al parar ----------------------------
    def prep_b(p):
        p.cmb_modo.setCurrentIndex(1)                  # Poisson
        p.spn_tasa.setValue(5e5)
        p.spn_dt_min.setValue(2)
        p.spn_n.setValue(0)                            # sin fin
    fin, disp = corrida(app, v, placa, 'B Poisson 500 k/s, sin fin', prep_b,
                        dur_s=args.segundos, captura=captura('ring_generador.png'))
    hw = fin['hw_final']
    check('B: EV + BUSY + FULL = lo generado', disp == hw.get('hw_gen_cnt'),
          f"{disp} contra {hw.get('hw_gen_cnt')}")
    check('B: el ring se llenó (el vaciado con el ring lleno)', hw['hw_drop_full'] > 0,
          f"DROP_FULL {hw['hw_drop_full']}")
    check('B: el generador quedó cortado, no terminado',
          hw.get('hw_gen_cortado') and not hw.get('hw_gen_terminado'))

    # --- C: el disparo del ADC, con gen_pulsos por el lazo --------------------
    g = v.panel_gen
    g.cmb_modo.setCurrentIndex(0)                      # periódico
    g.spn_tasa.setValue(TASA_C)
    g.spn_n.setValue(0)
    g.ed_amplitudes.setText('2000')
    g.ed_pesos.setText('')
    g.spn_tau.setValue(2.0)
    g.btn_aplicar.click()
    if not esperar(app, lambda: g.lbl_amp_modo.text() == 'one fixed amplitude'
                   and g.spn_n.value() == 0, timeout=10):
        raise AssertionError(f'C: el generador no se configuró: {g.lbl_error.text()}')
    g.chk_lazo.setChecked(True)
    if not esperar(app, lambda: v.lbl_lazo.isVisibleTo(v), timeout=10):
        raise AssertionError('C: el lazo no se prendió')
    g.btn_arrancar.click()
    if not esperar(app, lambda: g.lbl_estado.text() == 'generating', timeout=10):
        raise AssertionError('C: el generador no arrancó')

    def prep_c(p):
        p.cmb_estimulo.setCurrentIndex(p.cmb_estimulo.findData('disparo'))
        v.panel_config_osc.fijar_disparo_v(0.1, 0.02)
        p.spn_pre.setValue(16)
        p.spn_post.setValue(240)
    fin, disp = corrida(app, v, placa, f'C disparo del ADC, pulsos a {TASA_C} /s por el lazo',
                        prep_c, dur_s=args.segundos, captura=captura('ring_disparo.png'))
    hw = fin['hw_final']
    dur = fin['stats'].get('duration_s') or args.segundos
    check('C: un disparo por pulso (±10 %)', abs(disp / (TASA_C * dur) - 1) < 0.1,
          f'{disp} en {dur:.2f} s = {disp / dur:.0f}/s')
    check(f'C: a {TASA_C} /s no pierde', hw['hw_drop_busy'] == 0 and hw['hw_drop_full'] == 0)


def limpiar(app, v, placa, guardar):
    """La placa como estaba, pase lo que pase."""
    p, g = v.panel_ring, v.panel_gen
    if p is not None and p.ultimo.get('corriendo'):
        p.btn_parar.click()
        esperar(app, lambda: not p.ultimo.get('corriendo'), timeout=60)
    if g is not None:
        g.btn_parar.click()
        g.chk_lazo.setChecked(False)
        check('al final, el lazo apagado',
              esperar(app, lambda: not v.lbl_lazo.isVisibleTo(v), timeout=10))
    if guardar:
        print('  las corridas quedan en la placa: ' + ', '.join(placa.corridas))
    else:
        placa.borrar()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--host', default='10.73.28.30')
    ap.add_argument('--port', type=int, default=PORT_DEFAULT)
    ap.add_argument('--ssh', default='pitaya', help='el alias de ssh de la placa')
    ap.add_argument('--carpeta', default='/dev/shm',
                    help='dónde escribe la pestaña, en la placa')
    ap.add_argument('--segundos', type=float, default=4.0,
                    help='cuánto corren B y C antes de pararlas')
    ap.add_argument('--capturas', default=None,
                    help='un directorio de la PC para guardar las capturas de B y C')
    ap.add_argument('--guardar', action='store_true',
                    help='no borrar las corridas de la placa')
    ap.add_argument('--ver', action='store_true', help='con la ventana a la vista')
    args = ap.parse_args(argv)
    if not args.ver:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    if args.capturas:
        os.makedirs(args.capturas, exist_ok=True)

    from PyQt5.QtWidgets import QApplication
    from app.mcamon import Mcamon

    app = QApplication.instance() or QApplication([])
    v = Mcamon(args.host, args.port)
    v.resize(1300, 850)
    v.show()
    placa = Placa(args.ssh)
    try:
        v.sig_conectar.emit(args.host, args.port)
        if check('la app se conecta', esperar(app, lambda: v.info.get('presente'),
                                              timeout=20)):
            try:
                sesion(app, v, placa, args)
            except AssertionError as e:
                check('la sesión llegó al final', False, str(e))
            finally:
                limpiar(app, v, placa, args.guardar)
    finally:
        v.close()
        app.processEvents()
    print(f'\n{_pass} OK, {_fail} FALLA')
    return 1 if _fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
