#!/usr/bin/env python3
"""Capturas de las pestañas de mcamon, contra el servidor simulado y sin pantalla.

Levanta `mca_server.py --fake` en local, conecta la GUI, corre una adquisición
unos segundos para que haya espectro, mapa 2D, tasa y trazas, y guarda una PNG
por pestaña en `capturas/`. No toca la placa.

    cd prj/MCA/docs/APP/figuras
    python3 capturas_gui.py                 # 1500x950, en capturas/
    python3 capturas_gui.py --tam 1280x800 --segundos 15

Dos cosas del servidor simulado que se fijan acá, no en `FakeMCA`:

- la geometría es la del bitstream actual (8192 canales, `--fake-h-aw 13`);
- el fotopico va en el medio del eje: el default de `FakeMCA` (canal 8000) está
  pensado para los 16384 canales del bitstream viejo y con 8192 cae en el borde.
"""

import argparse
import os
import subprocess
import sys
import threading
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
SOFT = os.path.normpath(os.path.join(AQUI, '..', '..', '..', 'software'))
sys.path.insert(0, SOFT)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLBACKEND', 'Qt5Agg')

# El servidor simulado, con el pico en el medio del eje de 8192 canales.
_SERVIDOR = r"""
import os, sys, runpy
sys.path.insert(0, {soft!r})
import API.mca_remote as r
_init = r.FakeMCA.__init__
def _init_centrado(self, *a, **k):
    k.setdefault('centro', {centro!r})
    k.setdefault('sigma', {sigma!r})
    _init(self, *a, **k)
r.FakeMCA.__init__ = _init_centrado
sys.argv = ['mca_server.py', '--fake', '--host', '127.0.0.1', '--port', {port!r},
            '--fake-h-aw', '13']
runpy.run_path(os.path.join({soft!r}, 'app', 'mca_server.py'), run_name='__main__')
"""


def _puerto_libre():
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Servidor:
    """El servidor simulado en un subproceso; espera la línea «escuchando»."""

    def __init__(self, centro=4000.0, sigma=60.0):
        self.centro, self.sigma = centro, sigma

    def __enter__(self):
        self.port = _puerto_libre()
        codigo = _SERVIDOR.format(soft=SOFT, centro=self.centro, sigma=self.sigma,
                                  port=str(self.port))
        self.proc = subprocess.Popen([sys.executable, '-c', codigo], cwd=SOFT,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True)
        self._listo = threading.Event()
        self.salida = []
        threading.Thread(target=self._drenar, daemon=True).start()
        if not self._listo.wait(15.0):
            self.proc.kill()
            raise TimeoutError('el servidor no llegó a escuchar:\n' + ''.join(self.salida))
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
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        return False


def _correr(app, segundos):
    t0 = time.time()
    while time.time() - t0 < segundos:
        app.processEvents()
        time.sleep(0.02)


def _esperar(app, cond, timeout=15.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def _nombre(texto):
    limpio = ''.join(c if c.isalnum() else '_' for c in texto.lower())
    while '__' in limpio:
        limpio = limpio.replace('__', '_')
    return 'mcamon_' + limpio.strip('_') + '.png'


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--salida', default=os.path.join(AQUI, 'capturas'))
    p.add_argument('--tam', default='1500x950', help='ancho x alto de la ventana')
    p.add_argument('--segundos', type=float, default=10.0,
                   help='cuánto acumula antes de capturar')
    a = p.parse_args()
    ancho, alto = (int(x) for x in a.tam.split('x'))

    from PyQt5.QtWidgets import QApplication
    from app.mcamon import Mcamon

    app = QApplication.instance() or QApplication([])
    os.makedirs(a.salida, exist_ok=True)
    with Servidor() as s:
        v = Mcamon('127.0.0.1', s.port)
        v.resize(ancho, alto)
        v.show()
        v.sig_conectar.emit('127.0.0.1', s.port)
        if not _esperar(app, lambda: v.info.get('presente')):
            raise SystemExit('la GUI no llegó a conectarse')
        _correr(app, 1.5)
        v.sig_start.emit(0.0, True)
        _correr(app, a.segundos)

        pulsos = getattr(v, 'panel_pulsos', None)
        if pulsos is not None:                 # unas trazas para «Pulses»
            v.tabs.setCurrentWidget(pulsos)
            for _ in range(4):
                pulsos._capturar()
                _correr(app, 0.6)

        for i in range(v.tabs.count()):
            v.tabs.setCurrentIndex(i)
            cal = getattr(v, 'panel_cal', None)
            if cal is not None and v.tabs.widget(i) is cal:
                # «Calibration» mide con el MCA parado (el estímulo iría al espectro).
                v.sig_parar.emit()
                _correr(app, 0.5)
                cal.btn_medir.click()
                _esperar(app, lambda: cal._filas, timeout=30)
            _correr(app, 1.5)
            ruta = os.path.join(a.salida, _nombre(v.tabs.tabText(i)))
            v.grab().save(ruta)
            print(f'{v.tabs.tabText(i):16s} -> {os.path.relpath(ruta, AQUI)}')

        v.sig_parar.emit()
        _correr(app, 0.5)
        v.close()
        app.processEvents()


if __name__ == '__main__':
    main()
