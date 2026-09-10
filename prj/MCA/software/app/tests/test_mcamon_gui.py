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


def _con_gui(fn, h_aw=14):
    """Levanta servidor + ventana conectada y se lo pasa a `fn`.

    `h_aw` es la geometría del MCA simulado. Vale la pena decir por qué es un
    parámetro: hasta que lo fue, TODA la suite corría contra los 16384 canales
    del bitstream viejo, con el número puesto a mano en las aserciones. Eso
    dejaba sin cubrir justamente la clase de defecto que aparece al cambiar la
    geometría, y de hecho había uno vivo (la ventana de aceptación dibujada
    2^(AMP_W-h_aw) canales a la derecha).
    """
    if QApplication is None:
        print('    (sin PyQt5: salteada)')
        return
    from app.mcamon import Mcamon

    app = QApplication.instance() or QApplication([])
    with ServidorDePrueba(h_aw=h_aw) as s:
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
    """El cliente NO hardcodea el eje: lo toma del registro WIDTHS.

    Se corre contra las dos geometrías reales —16384 del bitstream viejo y 8192
    del nuevo— porque el número está publicado por el hardware y el cliente
    tiene que servir para los dos sin recompilarse.
    """
    for h_aw in (14, 13):
        def cuerpo(app, v, h_aw=h_aw):
            n = 1 << h_aw
            assert v.info['n_channels'] == n, f'h_aw={h_aw}'
            assert v.panel_espectro.n_canales == n, f'h_aw={h_aw}'
            assert v.panel_espectro.h_aw == h_aw
            assert 'MCA1' in v.lbl_estado.text()
            assert v.btn_conectar.text() == 'Desconectar'
        _con_gui(cuerpo, h_aw=h_aw)


def test_la_ventana_de_amplitud_cae_en_el_canal_correcto():
    """El bug que motivó todo esto.

    `amp_min`/`amp_max` viven en cuentas de amplitud de AMP_W=16 bits y el eje
    está en canales, así que la línea va en `amp >> (16 - h_aw)`. El código
    usaba `>> h_shift`, un registro que el bitstream nuevo dejó DEPRECADO y que
    lee 0: la línea caía 8 veces más a la derecha con 8192 canales, y los
    límites altos no se dibujaban porque se salían del eje.

    Con h_aw=13, amp_min=1000 tiene que dar el canal 125. Daba 1000.
    """
    from API.mca import mca_canal_de_amplitud

    for h_aw in (14, 13):
        def cuerpo(app, v, h_aw=h_aw):
            p = v.panel_espectro
            # `_cargando` PRIMERO: marcar la casilla escribe amp_min/amp_max en
            # el hardware, y la config que vuelve la desmarca sola porque la
            # ventana sigue abierta (amp_min=0, amp_max=0xFFFF). Acá se está
            # probando el dibujo, no el ida y vuelta.
            p._cargando = True
            p.chk_ventana.setChecked(True)
            p.spn_amp_min.setValue(1000)
            p.spn_amp_max.setValue(60000)
            p._cargando = False
            p._redibujar()
            app.processEvents()

            esperados = sorted(mca_canal_de_amplitud(x, h_aw)
                               for x in (1000, 60000))
            dibujados = sorted(int(round(ln.get_xdata()[0]))
                               for ln in p._lineas_ventana)
            assert dibujados == esperados, (
                f'h_aw={h_aw}: líneas en {dibujados}, esperadas {esperados}')
            # Y ninguna se cae del eje: antes, 60000 no se dibujaba.
            assert len(dibujados) == 2, f'h_aw={h_aw}: se perdió una línea'
            assert all(0 <= c < (1 << h_aw) for c in dibujados)
        _con_gui(cuerpo, h_aw=h_aw)


def test_la_pestana_2d_aparece_porque_el_bitstream_la_trae():
    def cuerpo(app, v):
        assert v.info['has_2d'] is True
        assert v.panel_mapa is not None
        titulos = [v.tabs.tabText(i) for i in range(v.tabs.count())]
        assert titulos == ['Mensajes', 'Espectro', 'MCA', 'Mapa 2D (PSD)']
        # La de Integración NO está: el MCA falso no simula el slot 6, y la
        # pestaña se crea sólo si el bitstream lo trae.
        assert v.panel_integracion is None
        assert v.info.get('has_integracion') is False
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
                assert meta2['n_channels'] == pe.n_canales, nombre
                # El eje tiene que quedar RECONSTRUIBLE: sin el zoom, un
                # espectro dice "8192 canales" sin decir sobre qué ventana de
                # amplitud, y no hay forma de saberlo después.
                for clave in ('h_aw', 'zoom_1d_z', 'zoom_1d_k'):
                    assert clave in meta2, f'{nombre}: falta {clave}'

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


def test_la_pestana_del_mca_escribe_y_relee():
    """Un valor puesto en la pestaña nueva llega al hardware y vuelve.

    Es el mismo ida y vuelta que ya se probaba para el umbral, pero sobre los
    campos que ANTES no se releian: `configure()` los escribia y
    `mca_get_config` no los veia, asi que un control de GUI para ellos habria
    mostrado siempre cero.
    """
    def cuerpo(app, v):
        pc = v.panel_config
        for campo, valor in (('thr', 271), ('bl_k', 11), ('maxlen', 2048),
                             ('zoom_1d_z', 2), ('zoom_1d_k', 1),
                             ('discr_min', 1234), ('sel_1d', 1)):
            w, leer, escribir = pc._controles[campo]
            escribir(valor)                      # como si lo tipeara el usuario
            pc._emitir(campo, valor)             # sin esperar el antirrebote
            assert _esperar(app, lambda c=campo, x=valor: leer() == x), (
                f'{campo}: no volvio del hardware')
        # y la config releida coincide con lo que muestran los controles
        assert _esperar(app, lambda: pc._controles['thr'][1]() == 271)
    _con_gui(cuerpo)


def test_el_rango_del_eje_sigue_al_zoom():
    """La etiqueta traduce (z, k) a cuentas de amplitud.

    Sin eso, z y k son dos numeros sin unidades y no hay forma de saber que
    ventana se esta mirando sin hacer la cuenta a mano.
    """
    def cuerpo(app, v):
        pc = v.panel_config
        pc.configurar_geometria(8192, 13)
        pc.actualizar_config({'h_aw': 13, 'zoom_1d_z': 0, 'zoom_1d_k': 0})
        assert '0 …' in pc.lbl_rango.text()
        assert '8192 canales' in pc.lbl_rango.text()

        pc.actualizar_config({'h_aw': 13, 'zoom_1d_z': 2, 'zoom_1d_k': 1})
        texto = pc.lbl_rango.text()
        assert texto.startswith('16384'), texto      # ventana [16384, 32768)
        # y el zoom no puede pasar de AMP_W - h_aw = 3
        assert pc._controles['zoom_1d_z'][0].maximum() == 3
    _con_gui(cuerpo)


def test_todos_los_campos_de_la_pestana_tienen_setter():
    """El trabajador escribe por `getattr(A, f'mca_set_{campo}')`.

    Un campo mal escrito no falla al importar sino al TOCARLO, y el usuario ve
    un error en el log en vez de un control que no anda. Esto lo convierte en
    algo que falla en CI.
    """
    if QApplication is None:
        print('    (sin PyQt5: salteada)')
        return
    from app.panel_config_mca import PanelConfigMCA
    from app.widgets_config import campos_sin_setter

    QApplication.instance() or QApplication([])
    p = PanelConfigMCA()
    faltan = campos_sin_setter(p.campos())
    assert not faltan, f'sin mca_set_*: {faltan}'
    # y todos son campos de verdad del MCA
    from API.mca import _CAMPOS
    desconocidos = [c for c in p.campos() if c not in _CAMPOS]
    assert not desconocidos, f'no estan en _CAMPOS: {desconocidos}'


def test_el_panel_de_integracion_pinta_ruteo_y_avisa_de_la_divergencia():
    """No pasa por el servidor: el MCA falso no simula el slot 6.

    Se le da directamente lo que devuelve `integracion.get`, que es el contrato
    entre las dos mitades. Lo que se comprueba es lo que la pestaña tiene que
    hacer con eso, incluido el caso que HOY es real: la geometria publicada por
    integration_cfg no coincide con la del MCA.
    """
    if QApplication is None:
        print('    (sin PyQt5: salteada)')
        return
    from app.panel_integracion import PanelIntegracion

    QApplication.instance() or QApplication([])
    p = PanelIntegracion()
    p.set_conectado(True)

    emitido = []
    p.pedir_ruteo.connect(lambda c, t, e: emitido.append((c, t, e)))

    p.actualizar({
        'modules': {'osc': True, 'mtrg': True, 'mca': True, 'ring': False},
        'slots': {'osc': 1, 'mtrg': 3, 'top': 6, 'mca': 7},
        'caps': {'n_ch': 2, 'dw': 14, 'rsz': 14, 'en_filt': False,
                 'h_aw': 14, 'h2_aw': 7, 'psd_aw': 6},
        'routes': {'osc':  {'tap': 0, 'enable': True},
                   'mtrg': {'tap': 1, 'enable': True},
                   'mca':  {'tap': 0, 'enable': True},
                   'ring': {'tap': 0, 'enable': False}},
        'status': {'pll_locked': True, 'adc_rstn': True}, 'run': True,
        'geometria_coincide': False,
        'geometria_motivo': 'h_aw=14 acá, h_aw=13 en el MCA',
    })

    # repoblar NO reescribe al hardware: es el eco que romperia el lazo
    assert emitido == [], f'actualizar() escribió al hardware: {emitido}'
    assert p._combos['mtrg'].currentData() == 1
    assert p.btn_run.isChecked() is True
    assert 'mca=7' in p.lbl_topologia.text()
    assert 'h_aw=13 en el MCA' in p.lbl_geometria.text()

    # y un cambio del usuario SI escribe
    p._combos['mca'].setCurrentIndex(p._combos['mca'].findData(1))
    assert emitido == [('mca', 1, True)], emitido
