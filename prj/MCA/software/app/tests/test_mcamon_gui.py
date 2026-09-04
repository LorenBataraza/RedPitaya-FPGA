#!/usr/bin/env python3
"""La GUI (`app/mcamon.py`) de punta a punta contra el servidor en --fake.

Corre sin pantalla (QT_QPA_PLATFORM=offscreen), así que sirve en CI y por ssh.
No prueba estética: prueba que el hilo del socket, las señales entre hilos y el
guardado hacen lo que dicen, que es donde una GUI se rompe de verdad.

Se salta sola si no hay PyQt5.

    python app/tests/test_mcamon_gui.py
    python -m pytest app/tests/test_mcamon_gui.py -q
"""

import os
import sys
import tempfile
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
_SOFTWARE = _RAIZ
sys.path.insert(0, _SOFTWARE)
sys.path.insert(0, _AQUI)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLBACKEND', 'Qt5Agg')

import numpy as np                                                 # noqa: E402

from test_mca_remote import ServidorDePrueba                       # noqa: E402

try:
    from PyQt5.QtWidgets import QApplication
except ImportError:                                                # pragma: no cover
    QApplication = None


def _esperar(app, condicion, timeout=15.0, paso=0.02):
    """Corre el lazo de eventos hasta que se cumpla `condicion`."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if condicion():
            return True
        time.sleep(paso)
    return False


def _con_gui(fn):
    """Levanta servidor + ventana conectada y se lo pasa a `fn`."""
    if QApplication is None:
        print('    (sin PyQt5: salteada)')
        return
    from app.mcamon import Mcamon

    app = QApplication.instance() or QApplication([])
    with ServidorDePrueba() as s:
        v = Mcamon('127.0.0.1', s.port)
        try:
            v.sig_conectar.emit('127.0.0.1', s.port)
            assert _esperar(app, lambda: v.info.get('presente')), \
                'la ventana nunca llegó a conectarse'
            fn(app, v)
        finally:
            v.close()
            app.processEvents()


# =============================================================================
# Pruebas
# =============================================================================

def test_conecta_y_toma_la_geometria_del_hardware():
    def cuerpo(app, v):
        assert v.info['n_channels'] == 16384
        assert v.panel_espectro.n_canales == 16384
        assert 'MCA1' in v.lbl_estado.text()
        assert v.btn_conectar.text() == 'Desconectar'
    _con_gui(cuerpo)


def test_la_pestana_2d_aparece_porque_el_bitstream_la_trae():
    def cuerpo(app, v):
        assert v.info['has_2d'] is True
        assert v.panel_mapa is not None
        titulos = [v.tabs.tabText(i) for i in range(v.tabs.count())]
        assert titulos == ['Mensajes', 'Espectro', 'Mapa 2D (PSD)']
    _con_gui(cuerpo)


def test_el_espectro_llega_y_crece():
    def cuerpo(app, v):
        v.sig_start.emit(0.0, True)          # sin límite, borrando antes
        assert _esperar(app, lambda: v.panel_espectro.hist is not None
                        and v.panel_espectro.hist.sum() > 0), 'no llegó espectro'
        primero = int(v.panel_espectro.hist.sum())
        assert _esperar(app, lambda: int(v.panel_espectro.hist.sum()) > primero), \
            'el espectro no creció'
        v.sig_parar.emit()
        assert _esperar(app, lambda: v.btn_conectar.isEnabled()
                        and not v.panel_espectro.btn_stop.isEnabled())
    _con_gui(cuerpo)


def test_los_contadores_y_las_tasas_se_llenan():
    def cuerpo(app, v):
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda:
                        v.panel_espectro.contadores.get('livetime_s', 0) > 0.2)
        assert _esperar(app, lambda:
                        float(v.panel_espectro.lbl_rate_avg.text()) > 0)
        assert v.panel_espectro.contadores['accepted'] > 0
        assert v.panel_espectro.baseline is not None
        assert 'aceptados' in v.panel_espectro.lbl_contadores.text()
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_la_exposicion_para_sola():
    def cuerpo(app, v):
        v.sig_start.emit(0.5, True)
        assert _esperar(app, lambda: 'restan' in v.panel_espectro.lbl_restante.text())
        assert _esperar(app, lambda:
                        v.panel_espectro.lbl_restante.text() == 'detenido',
                        timeout=10.0), 'la exposición no paró sola'
    _con_gui(cuerpo)


def test_el_umbral_de_la_gui_llega_al_hardware():
    def cuerpo(app, v):
        v.sig_campo.emit('thr', 317)
        assert _esperar(app, lambda: v.panel_espectro.spn_thr.value() == 317), \
            'el valor releído del hardware no volvió al spinbox'
    _con_gui(cuerpo)


def test_la_ventana_de_amplitud_recorta_y_se_dibuja():
    def cuerpo(app, v):
        pe = v.panel_espectro
        v.sig_campo.emit('amp_min', 12000)   # el pico simulado está en ~8000
        assert _esperar(app, lambda: pe.spn_amp_min.value() == 12000)
        v.sig_borrar.emit()
        v.sig_start.emit(0.0, False)
        assert _esperar(app, lambda:
                        pe.contadores.get('rej_amp', 0) > 0), 'no rechazó nada'
        assert pe.contadores['accepted'] == 0
        assert pe.chk_ventana.isChecked()
        assert len(pe._lineas_ventana) > 0, 'no se dibujaron los límites'
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_rebin_y_escala_log_no_rompen_el_dibujo():
    def cuerpo(app, v):
        pe = v.panel_espectro
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: pe.hist is not None and pe.hist.sum() > 0)
        total = int(pe.hist.sum())
        for i in range(pe.cmb_rebin.count()):
            pe.cmb_rebin.setCurrentIndex(i)
            app.processEvents()
            x, y = pe._agrupado()
            assert y.sum() == total, 'el rebin perdió cuentas'
            assert x.size == y.size
        pe.chk_log.setChecked(True)
        app.processEvents()
        assert pe.ax.get_yscale() == 'log'
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_roi_ajusta_el_pico_simulado():
    def cuerpo(app, v):
        pe = v.panel_espectro
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: pe.hist is not None and pe.hist.sum() > 500)
        pe.spn_roi_lo.setValue(7500)
        pe.spn_roi_hi.setValue(8500)
        pe._ajustar_roi()
        texto = pe.lbl_roi.text()
        assert 'centroide' in texto and 'resolución' in texto
        centroide = float(texto.split('centroide')[1].split('·')[0])
        assert 7800 < centroide < 8200, f'centroide fuera de lugar: {centroide}'
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_guardar_y_recargar_desde_la_gui():
    def cuerpo(app, v):
        pe = v.panel_espectro
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: pe.hist is not None and pe.hist.sum() > 0)
        v.sig_parar.emit()
        app.processEvents()
        original = pe.hist.copy()

        # Se llama al guardado directo, sin el diálogo de fichero: es el mismo
        # que usa el botón, con los mismos (hist, meta) que hay en pantalla.
        from API.mca import (mca_load_file, mca_save_file_binary,
                             mca_save_file_json, mca_write_file_histogram)

        with tempfile.TemporaryDirectory() as d:
            for nombre in ('e.csv', 'e.npz', 'e.json'):
                ruta = os.path.join(d, nombre)
                guardar = {'.csv': mca_write_file_histogram,
                           '.npz': mca_save_file_binary,
                           '.json': mca_save_file_json}[os.path.splitext(ruta)[1]]
                guardar(pe.hist, ruta, meta=pe.meta)
                hist2, meta2 = mca_load_file(ruta)
                assert np.array_equal(hist2, original), nombre
                assert meta2['n_channels'] == 16384, nombre

            # y la recarga desde el panel deja el mismo espectro en pantalla
            pe.configurar_geometria(hist2.size)
            pe.actualizar_espectro(hist2, meta2)
            assert np.array_equal(pe.hist, original)

            png = os.path.join(d, 'espectro.png')
            pe.fig.savefig(png, dpi=80)
            assert os.path.getsize(png) > 1000
    _con_gui(cuerpo)


def test_mapa_2d_solo_se_lee_cuando_se_ve():
    def cuerpo(app, v):
        v.tabs.setCurrentWidget(v.panel_mapa)
        app.processEvents()
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: v.panel_mapa.mapa.sum() > 0), \
            'no llegó el mapa 2D con la pestaña visible'
        v.sig_parar.emit()

        v.tabs.setCurrentWidget(v.panel_espectro)
        app.processEvents()
        assert _esperar(app, lambda: not v.trabajador._mapa_visible)
    _con_gui(cuerpo)


def test_desconectar_y_volver_a_conectar():
    def cuerpo(app, v):
        v.sig_desconectar.emit()
        assert _esperar(app, lambda: v.btn_conectar.text() == 'Conectar')
        assert not v.panel_espectro.btn_start.isEnabled()
        v.info = {}
        v.sig_conectar.emit('127.0.0.1', v.spn_port.value())
        assert _esperar(app, lambda: v.info.get('presente')), \
            'el servidor no aceptó al cliente de vuelta'
    _con_gui(cuerpo)


def main():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f'  ok    {fn.__name__}')
        except Exception as e:
            fallos += 1
            print(f'  FALLO {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\n{len(pruebas) - fallos}/{len(pruebas)} pruebas OK')
    return 1 if fallos else 0


if __name__ == '__main__':
    raise SystemExit(main())
