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
from API.mca import mca_amplitud_de_canal                          # noqa: E402

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
            assert 'MCA2' in v.lbl_estado.text()
            assert v.btn_conectar.text() == 'Disconnect'
        _con_gui(cuerpo, h_aw=h_aw)


def test_la_ventana_de_amplitud_cae_en_el_canal_correcto():
    """El bug que motivó todo esto, y el segundo, el de las unidades.

    El eje está en canales, los h_aw bits altos de la feature de AMP_W=16 bits.
    El código usaba `>> h_shift`, un registro que el bitstream nuevo dejó
    DEPRECADO y que lee 0: la línea caía 8 veces más a la derecha con 8192
    canales, y los límites altos no se dibujaban porque se salían del eje.

    Y en modo pico `amp_min`/`amp_max` no están en las unidades del eje: la
    ventana compara el pico CRUDO de 14 bits (mca_slot.sv:251) y el eje muestra
    `pico << 2` (mca_publish.sv:342). Con h_aw=13, amp_min=1000 es el canal
    500; tratarlo como feature de 16 b daba 125. Con la integral sí coinciden.
    Y si el eje muestra otra feature, no hay líneas.
    """
    from API.mca import F_INT, F_TRAP, mca_canal_de_amplitud

    for h_aw in (14, 13):
        def cuerpo(app, v, h_aw=h_aw):
            p = v.panel_espectro
            # `_cargando` PRIMERO: marcar la casilla escribe amp_min/amp_max en
            # el hardware, y la config que vuelve la desmarca sola porque la
            # ventana sigue abierta (amp_min=0, amp_max=0xFFFF). Acá se está
            # probando el dibujo, no el ida y vuelta.
            def dibujar(amp_src, sel_1d, lo, hi):
                p._cargando = True
                p._amp_src, p._sel_1d = amp_src, sel_1d
                p.chk_ventana.setChecked(True)
                p.spn_amp_min.setValue(lo)
                p.spn_amp_max.setValue(hi)
                p._cargando = False
                p._redibujar()
                app.processEvents()
                return sorted(int(round(ln.get_xdata()[0]))
                              for ln in p._lineas_ventana)

            # Pico: el crudo de 14 b, el eje lo lleva << 2.
            dibujados = dibujar(0, 0, 1000, 8000)
            esperados = sorted(mca_canal_de_amplitud(x << 2, h_aw)
                               for x in (1000, 8000))
            assert dibujados == esperados, (
                f'h_aw={h_aw}: líneas en {dibujados}, esperadas {esperados}')
            if h_aw == 13:
                assert dibujados[0] == 500
            # Y ninguna se cae del eje: antes, las altas no se dibujaban.
            assert len(dibujados) == 2, f'h_aw={h_aw}: se perdió una línea'
            assert all(0 <= c < (1 << h_aw) for c in dibujados)
            # La aclaración dice las unidades, no los canales (pedido del usuario).
            texto = p.lbl_ventana.text()
            assert 'ADC counts of the peak' in texto and 'not channels' in texto
            assert 'dashed red lines' in texto and 'channels ' + str(esperados[0]) not in texto

            # Integral: la ventana y el eje miden lo mismo.
            dibujados = dibujar(1, F_INT, 1000, 60000)
            assert dibujados == sorted(mca_canal_de_amplitud(x, h_aw)
                                       for x in (1000, 60000))

            # Otra feature en el eje: no hay dónde ponerlas.
            assert dibujar(0, F_TRAP, 1000, 8000) == []
            assert 'another feature' in p.lbl_ventana.text()
        _con_gui(cuerpo, h_aw=h_aw)


def test_la_pestana_2d_aparece_porque_el_bitstream_la_trae():
    def cuerpo(app, v):
        assert v.info['has_2d'] is True
        assert v.panel_mapa is not None
        titulos = [v.tabs.tabText(i) for i in range(v.tabs.count())]
        assert titulos == ['Messages', 'Spectrum', 'MCA settings',
                           '2D map (PSD)', 'Pulses', 'OSC settings',
                           'Multitrigger', 'Generator', 'Calibration']
        # La de Integración NO está: el MCA falso no simula el slot 6, y la
        # pestaña se crea sólo si el bitstream lo trae. Las del osciloscopio, el
        # Multitrigger y el generador SÍ: el simulador incluye los bloques, que es
        # lo que permite desarrollarlas sin placa. El ring no tiene pestaña: va
        # dentro de «OSC settings».
        assert v.panel_integracion is None
        assert v.info.get('has_integracion') is False
        assert v.info.get('has_osc') is True
        assert v.info.get('has_mtrg') is True
        assert v.info.get('has_pulsos') is True
        assert v.info.get('has_ring') is True
        assert v.panel_ring is v.panel_config_osc.ring is not None
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
                        v.panel_espectro.tasa_media_hz > 0)
        # Con prefijo, no en notación científica: el falso da ~1000 /s.
        from app.franja import _tasa
        texto = v.panel_espectro.lbl_rate_avg.text()
        assert texto.endswith('/s') and 'e+' not in texto
        assert texto == _tasa(v.panel_espectro.tasa_media_hz)
        assert v.panel_espectro.contadores['accepted'] > 0
        assert v.panel_espectro.baseline is not None
        assert 'accepted' in v.panel_espectro.lbl_contadores.text()
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_el_tiempo_muerto_va_en_total_y_se_desglosa_a_pedido():
    """Por defecto un solo `muerto` (deadtime_real_s, no la ocupación); con
    «detail», una fila por etapa con su tiempo y sus disparos."""
    def cuerpo(app, v):
        p = v.panel_espectro
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: p.contadores.get('livetime_s', 0) > 0.2)
        v.sig_parar.emit()
        assert _esperar(app, lambda: not p.btn_stop.isEnabled())
        texto = p.lbl_contadores.text()
        assert 'dead' in texto and 'no slot' not in texto
        assert f"{p.contadores['deadtime_real_s']:7.3f}" in texto

        p.chk_detalle.setChecked(True)
        texto = p.lbl_contadores.text()
        for etapa in ('veto', 'no slot', 'publisher', 're-arm', 'live',
                      'total'):
            assert etapa in texto, etapa
        # La fila del total trae realtime y cross.
        total = [l for l in texto.splitlines() if l.startswith('total')][0]
        assert str(p.contadores['cross']) in total

        p.chk_detalle.setChecked(False)
        assert 'no slot' not in p.lbl_contadores.text()
    _con_gui(cuerpo)


def test_el_maximo_de_ranuras_lo_dice_la_placa():
    """El tope de `n_acc` sale de `n_acc_max` del identify, no del 4 del
    constructor: la placa tiene 3."""
    def cuerpo(app, v):
        spn = v.panel_config._controles['n_acc'][0]
        assert spn.maximum() == v.info['n_acc_max']
        v.panel_config.configurar_mca({'n_acc_max': 3})
        assert spn.maximum() == 3
    _con_gui(cuerpo)


def test_la_exposicion_para_sola():
    def cuerpo(app, v):
        v.sig_start.emit(0.5, True)
        assert _esperar(app, lambda: 'left' in v.panel_espectro.lbl_restante.text())
        assert _esperar(app, lambda:
                        v.panel_espectro.lbl_restante.text() == 'stopped',
                        timeout=10.0), 'la exposición no paró sola'
    _con_gui(cuerpo)


def test_el_disparo_de_la_gui_se_arma_y_vuelve():
    """El disparo del MCA se configura en el Multitrigger (Sources → MCA trigger) y
    el atajo de Spectrum arma con esos parámetros (op `mca.disparo`); el estado
    releído vuelve a las dos etiquetas. El polo-cero se arma desde el Multitrigger,
    con el umbral en cuentas, y vuelve en cuentas."""
    def cuerpo(app, v):
        p, m = v.panel_espectro, v.panel_mtrg
        assert _esperar(app, lambda: 'NO TRIGGER' in p.lbl_disparo.text()), \
            'al conectar no se leyó el estado del disparo'
        m.spn_thr.setValue(900)
        m.spn_hyst.setValue(200)
        p.btn_armar.click()
        assert _esperar(app, lambda: p.lbl_disparo.text().startswith('armed')
                        and 'thr 900' in p.lbl_disparo.text()), \
            'el disparo armado no volvió del servidor'
        assert m.lbl_disparo.text() == p.lbl_disparo.text()
        p.btn_desarmar.click()
        assert _esperar(app, lambda: 'NO TRIGGER' in p.lbl_disparo.text())

        m.cmb_fuente.setCurrentIndex(m.cmb_fuente.findData('pz'))
        m.spn_thr_pz.setValue(40.0)
        m.btn_armar_mca.click()
        assert _esperar(app, lambda: 'pole-zero IN1' in p.lbl_disparo.text())
        assert abs(m.spn_thr_pz.value() - 40.0) < 0.5
        m.btn_desarmar_mca.click()
        assert _esperar(app, lambda: 'NO TRIGGER' in m.lbl_disparo.text())
    _con_gui(cuerpo)


def test_el_disparo_con_polo_cero_vuelve_como_polo_cero():
    """Si lo armó un script con polo-cero, las etiquetas lo dicen y el Multitrigger
    pasa a esa fuente con sus parámetros (el umbral, de vuelta en cuentas)."""
    from API.multitrigger import pz_ganancia

    def cuerpo(app, v):
        est = {'armado': True, 'fuente': 'pz', 'we_keep': True, 'ch': 0,
               'pendiente': {'L': 8, 'G': 4, 'thr': 600, 'hyst': 300},
               'polo_cero': {'k': 2, 'm': 1, 'sh': 10, 'thr': 353, 'hyst': 177,
                             'mq': 3885}}
        p, m = v.panel_espectro, v.panel_mtrg
        p.actualizar_disparo(est)
        texto = p.lbl_disparo.text()
        assert 'pole-zero' in texto and 'Mq 3885' in texto and 'thr 353' in texto
        assert 'L 8' not in texto
        m.actualizar_disparo(est)
        assert m.cmb_fuente.currentData() == 'pz' and m.spn_mq.value() == 3885
        assert abs(m.spn_thr_pz.value() - 353 / pz_ganancia(2, 1, 3885, 10)) < 0.1
        assert m._w_pz.isVisibleTo(m) is not m._w_pend.isVisibleTo(m)
    _con_gui(cuerpo)


def test_cambiar_pre_dly_avisa_si_se_mira_el_trapecio():
    from API import mca as A
    from API.mca_remote import FakeMCA
    from app.mcamon import Trabajador

    class Quieto:                     # sólo lo que usa escribir_campo
        aviso = type('S', (), {'emit': lambda self, t: mensajes.append(t)})()
        fallo = type('S', (), {'emit': lambda self, t: mensajes.append('FALLO ' + t)})()
        _leer_config = staticmethod(lambda: None)
        _aviso_pre_dly = Trabajador._aviso_pre_dly

    mensajes = []
    t = Quieto()
    t.h = FakeMCA(trap=True)
    A.mca_configure(t.h)
    Trabajador.escribir_campo(t, 'pre_dly', 20)
    assert mensajes == ['pre_dly = 20']
    A.mca_configure(t.h, sel_1d='trapecio')
    mensajes.clear()
    Trabajador.escribir_campo(t, 'pre_dly', 24)
    assert len(mensajes) == 2 and 'trapezoid windows' in mensajes[1]
    t.h.close()


def test_un_campo_del_mca2_llega_al_hardware():
    def cuerpo(app, v):
        v.sig_campo.emit('n_acc', 3)
        assert _esperar(app, lambda:
                        v.panel_config._controles['n_acc'][1]() == 3), \
            'el valor releído del hardware no volvió al spinbox'
    _con_gui(cuerpo)


def test_la_ventana_de_amplitud_recorta_y_se_dibuja():
    def cuerpo(app, v):
        pe = v.panel_espectro
        # La ventana es sobre el pico crudo de 14 b, que el eje lleva << 2: el
        # pico simulado está en el canal ~8000 de 16384, y el corte va en el
        # 12000 (= 48000 en el eje, 12000 en la ventana).
        corte = mca_amplitud_de_canal(12000, 14) >> 2
        v.sig_campo.emit('amp_min', corte)
        assert _esperar(app, lambda: pe.spn_amp_min.value() == corte)
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


def test_la_lista_de_picos_se_llena_sola():
    """Reemplaza al ajuste sobre una región marcada a mano.

    La diferencia que importa no es de presentación: antes había que saber
    DÓNDE estaba el pico para poder medirlo, y en un espectro desconocido eso
    es justamente lo que no se sabe. Acá no se le pide nada al usuario.

    El simulador pone su fotopico en el canal 8000 con sigma 45, así que el
    FWHM verdadero es 2.3548 x 45 = 106 canales.
    """
    def cuerpo(app, v):
        pe = v.panel_espectro
        # Los controles de la ROI ya no existen: si alguien los reintroduce,
        # esta prueba lo dice en vez de dejar dos caminos para lo mismo.
        assert not hasattr(pe, 'spn_roi_lo')
        assert not hasattr(pe, 'btn_ajustar')

        v.sig_start.emit(0.0, True)
        # Hay que dejar que se acumule estadística ANTES de exigirle el ancho.
        # Con 900 cuentas el pico ya se encuentra y su centroide es correcto,
        # pero el FWHM todavía vale 17 en vez de 106: con esa población el
        # histograma son cuatro canales sueltos. Desde ~5000 cuentas queda
        # dentro del 10 %.
        assert _esperar(app, lambda: pe.hist is not None
                        and pe.hist.sum() > 8000, timeout=40.0), \
            'no se acumularon cuentas suficientes'
        assert _esperar(app, lambda: len(pe.picos) > 0), \
            'la lista no encontró ningún pico'

        assert pe.tabla_picos.rowCount() == len(pe.picos)
        p = max(pe.picos, key=lambda d: d['area'])
        assert 7900 < p['canal'] < 8100, f"centroide fuera de lugar: {p['canal']}"
        teorico = 2.3548 * 45
        assert abs(p['fwhm'] - teorico) / teorico < 0.20, \
            f"FWHM {p['fwhm']:.1f} contra {teorico:.1f}"

        # Y lo que se ve en la tabla es lo que hay en la lista.
        fila = pe.picos.index(p)
        assert float(pe.tabla_picos.item(fila, 0).text()) == round(p['canal'], 1)
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_los_picos_se_marcan_en_el_grafico_y_se_pueden_apagar():
    def cuerpo(app, v):
        pe = v.panel_espectro
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: len(pe.picos) > 0)

        pe.chk_marcar.setChecked(True)
        pe._redibujar()
        assert len(pe._marcas_picos) > 0, 'no se dibujó ninguna marca'

        pe.chk_marcar.setChecked(False)
        pe._redibujar()
        assert len(pe._marcas_picos) == 0, 'apagar las marcas no las borró'
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_elegir_un_pico_centra_el_eje_en_el():
    """Es cómo se va de la lista al espectro sin buscar el canal con el zoom."""
    def cuerpo(app, v):
        pe = v.panel_espectro
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: len(pe.picos) > 0)

        fila = pe.picos.index(max(pe.picos, key=lambda d: d['area']))
        pe.tabla_picos.selectRow(fila)
        app.processEvents()

        lo, hi = pe.ax.get_xlim()
        canal = pe.picos[fila]['canal']
        assert lo < canal < hi, f'{canal} fuera de [{lo}, {hi}]'
        assert (hi - lo) < pe.n_canales / 2, 'no se acercó al pico'
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_subir_la_prominencia_no_pierde_el_pico_principal():
    def cuerpo(app, v):
        pe = v.panel_espectro
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: len(pe.picos) > 0)

        pe.spn_prominencia.setValue(50.0)
        pe._recalcular_picos()
        assert len(pe.picos) >= 1, 'se perdió hasta el pico principal'
        assert 7900 < max(pe.picos, key=lambda d: d['area'])['canal'] < 8100
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


def test_guardar_y_cargar_n42_desde_los_dialogos():
    """Por el mismo camino que los botones, con el diálogo de archivos falso."""
    def cuerpo(app, v):
        import unittest.mock as mock
        from app import panel_espectro as P

        pe = v.panel_espectro
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: pe.hist is not None and pe.hist.sum() > 0)
        v.sig_parar.emit()
        app.processEvents()
        original = pe.hist.copy()

        with tempfile.TemporaryDirectory() as d:
            # Sin extensión: manda el filtro elegido.
            ruta = os.path.join(d, 'sin_extension')
            with mock.patch.object(P.QFileDialog, 'getSaveFileName',
                                   return_value=(ruta, 'N42.42 (*.n42)')) as dlg:
                pe._guardar_archivo()
            assert 'N42.42 (*.n42)' in dlg.call_args[0][3]
            assert os.path.exists(ruta + '.n42')

            pe.hist = None
            with mock.patch.object(P.QFileDialog, 'getOpenFileName',
                                   return_value=(ruta + '.n42', '')) as dlg:
                pe._cargar_archivo()
            assert '*.n42' in dlg.call_args[0][3]
            assert np.array_equal(pe.hist, original)

            # Con una extensión conocida, manda ésa aunque el filtro diga otra cosa.
            ruta = os.path.join(d, 'e.n42')
            with mock.patch.object(P.QFileDialog, 'getSaveFileName',
                                   return_value=(ruta, 'CSV con metadata (*.csv)')):
                pe._guardar_archivo()
            assert open(ruta, encoding='utf-8').read().startswith('<?xml')

            # Sin extensión ni filtro reconocible, como antes: csv.
            ruta = os.path.join(d, 'otro')
            with mock.patch.object(P.QFileDialog, 'getSaveFileName',
                                   return_value=(ruta, '')):
                pe._guardar_archivo()
            assert os.path.exists(ruta + '.csv')

        # Un archivo de otro programa: no trae la geometría del MCA.
        ejemplo = os.path.join(_SOFTWARE, 'API', 'tests', 'datos_ref', 'n42',
                               'annexb.n42')
        with mock.patch.object(P.QFileDialog, 'getOpenFileName',
                               return_value=(ejemplo, '')):
            pe._cargar_archivo()
        assert pe.hist.size == pe.n_canales == 256
        app.processEvents()
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
        assert _esperar(app, lambda: v.btn_conectar.text() == 'Connect')
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
        for campo, valor in (('pre_dly', 27), ('bl_k', 11), ('gate_long', 300),
                             ('zoom_1d_z', 2), ('zoom_1d_k', 1),
                             ('discr_min', 1234), ('sel_1d', 1)):
            w, leer, escribir = pc._controles[campo]
            escribir(valor)                      # como si lo tipeara el usuario
            pc._emitir(campo, valor)             # sin esperar el antirrebote
            assert _esperar(app, lambda c=campo, x=valor: leer() == x), (
                f'{campo}: no volvio del hardware')
        # y la config releida coincide con lo que muestran los controles
        assert _esperar(app, lambda: pc._controles['pre_dly'][1]() == 27)
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
        assert '8192 channels' in pc.lbl_rango.text()

        pc.actualizar_config({'h_aw': 13, 'zoom_1d_z': 2, 'zoom_1d_k': 1})
        texto = pc.lbl_rango.text()
        assert texto.startswith('16384'), texto      # ventana [16384, 32768)
        # y el zoom no puede pasar de AMP_W - h_aw = 3
        assert pc._controles['zoom_1d_z'][0].maximum() == 3
    _con_gui(cuerpo)


def test_flujo_mca_cierra_las_cuentas():
    """La cuenta de la franja, con números a mano: cada tramo, cada pérdida y el
    total perdido sobre los pulsos estimados."""
    from app.diagrama_mca import flujo_mca

    cnt = dict(realtime_s=10.5, vetotime_s=0.5, cross=1000, lost_veto=10, open=950,
               lost_active=25, dropped=20, total=940, accepted=900, rej_amp=40,
               rej_discr=10, full_supp=5)
    fl = flujo_mca(cnt, tasa_entrada_hz=104.0)      # N̂ = 104 · 10 s = 1040
    c = fl['cuentas']
    assert fl['T'] == 10.0
    assert c['pulsos'] == 1040.0 and c['disparos'] == 990
    assert c['rearmado'] == 50.0                    # 1040 − 990
    assert c['publicador'] == 15                    # 1000 − 950 − 25 − 10
    assert c['colisiones'] == 5                     # dropped − lost_busy
    assert c['al_histograma'] == 880                # 900 − 10 − 5 − 5
    assert fl['perdidos'] == 50 + 25 + 15
    assert abs(fl['frac_perdidos'] - 90 / 1040) < 1e-12
    assert fl['tasas']['ventanas'] == 95.0
    # sin tiempo medido ni tasa: ceros, no divisiones por cero
    vacio = flujo_mca({}, 0.0)
    assert vacio['frac_perdidos'] == 0.0 and vacio['tasas']['ventanas'] == 0.0


def _panel_mca():
    from app.panel_config_mca import PanelConfigMCA

    app = QApplication.instance() or QApplication([])
    p = PanelConfigMCA()
    p.configurar_mca({'n_acc_max': 3, 'trap': True})
    p.set_conectado(True)
    return app, p


def _estado(real, total):
    return {'counters': {'realtime_s': real, 'total': total, 'accepted': total,
                         'cross': total, 'open': total},
            'tasa_entrada_hz': 100.0}


def test_la_pestana_mca_avisa_cuando_el_histograma_mezcla_configuraciones():
    """Nada del MCA pide pararlo; lo que se rompe es lo acumulado. Un cambio con
    cuentas marca su etapa y muestra el aviso; las ranuras no (no cambian lo que
    se mide), sin cuentas tampoco, y el aviso se va al borrar, lo borre quien
    sea (el reloj real vuelve atrás)."""
    if QApplication is None:
        print('    (sin PyQt5: salteada)')
        return
    _app, p = _panel_mca()
    borrados = []
    p.pedir_clear.connect(lambda: borrados.append(1))

    p.actualizar_estado(_estado(5.0, 0))            # recién borrado: nada que mezclar
    p._emitir('pre_dly', 20)
    assert p.mezcla == {} and p.frm_mezcla.isHidden()

    p.actualizar_estado(_estado(6.0, 500))
    p._emitir('n_acc', 2)                           # CALIENTE: no marca
    assert p.mezcla == {}
    p._emitir('pre_dly', 21)
    p._emitir('sel_1d', 1)
    assert p.mezcla == {'entrada': {'pre_dly'}, 'publicacion': {'sel_1d'}}
    assert not p.frm_mezcla.isHidden()
    assert 'pre_dly' in p.lbl_mezcla.text() and 'sel_1d' in p.lbl_mezcla.text()
    assert p.diagrama.marcadas == {'entrada', 'publicacion'}

    p.actualizar_estado(_estado(7.0, 900))          # sigue midiendo: sigue el aviso
    assert p.mezcla
    p.actualizar_estado(_estado(0.2, 3))            # alguien borró (Espectro)
    assert p.mezcla == {} and p.frm_mezcla.isHidden() and not p.diagrama.marcadas

    p.actualizar_estado(_estado(1.0, 50))
    p._emitir('gate_long', 300)
    assert p.mezcla == {'estadisticos': {'gate_long'}}
    p.btn_borrar.click()                            # y desde acá
    assert borrados == [1] and p.mezcla == {}


def test_la_franja_sigue_al_raton_y_lleva_a_los_controles():
    """Cada control pertenece a una etapa; el grupo bajo el ratón se resalta en
    la franja, y un clic en un bloque pide esa etapa."""
    if QApplication is None:
        print('    (sin PyQt5: salteada)')
        return
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtTest import QTest
    from app.diagrama_mca import COLOR

    app, p = _panel_mca()
    assert set(p._etapa_de) == set(p.campos())
    assert set(p._etapa_de.values()) <= set(COLOR)

    g_base = p._grupos['base'][0]
    app.sendEvent(g_base, QEvent(QEvent.Enter))
    assert p.diagrama.resaltada == 'base'
    app.sendEvent(g_base, QEvent(QEvent.Leave))
    assert p.diagrama.resaltada is None

    p.resize(1240, 700)
    p.diagrama.resize(1200, p.diagrama.height())
    p.diagrama._geometria()                         # las cajas, para este ancho
    pedidas = []
    p.diagrama.etapa_elegida.connect(pedidas.append)
    centro = p.diagrama._cajas['publicacion'].center()
    QTest.mouseClick(p.diagrama, Qt.LeftButton, pos=QPoint(int(centro.x()),
                                                            int(centro.y())))
    assert pedidas == ['publicacion']


def test_la_pestana_mca_va_en_tres_columnas_con_la_leyenda_en_la_franja():
    """Una columna por función del panorama: preprocesamiento; disparo y ranuras;
    publicación. La leyenda ya no es un texto abajo: la dibuja la franja."""
    if QApplication is None:
        print('    (sin PyQt5: salteada)')
        return
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QLabel

    app, p = _panel_mca()
    # El alto que le queda a la pestaña en la ventana de 1240 × 860, con el trapecio
    # y con el aviso de mezcla a la vista: el peor caso.
    p.resize(1240, 745)
    p.show()
    p.actualizar_estado(_estado(5.0, 10))
    p._emitir('trap_k', 48)
    for _ in range(5):
        app.processEvents()
    try:
        assert not p.frm_mezcla.isHidden()
        x = {k: {g.mapTo(p, QPoint(0, 0)).x() for g in gs}
             for k, gs in p._grupos.items()}
        assert len(x['entrada'] | x['base'] | x['trapecio']) == 1, x
        assert len(x['segmentacion'] | x['estadisticos']) == 1, x
        assert len(x['publicacion']) == 1, x          # eje, discriminador, histograma
        assert min(x['entrada']) < min(x['segmentacion']) < min(x['publicacion'])
        assert not [w for w in p.findChildren(QLabel) if 'nothing needs the MCA stopped' in w.text()]
        assert p.diagrama.LEYENDA
        # todo a la vista, sin scroll, en la ventana de siempre
        assert p.scroll.verticalScrollBar().maximum() == 0
    finally:
        p.hide()


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


# =============================================================================
# Pestañas de OSC y Multitrigger
# =============================================================================
#
# OJO CON EL ALCANCE, igual que con la de Integración: el simulador NO simula
# el RTL del osciloscopio. No hay FSM de captura, ni disparo real, ni BRAM: hay
# registros que retienen lo escrito y formas sintéticas. Lo que estas pruebas
# demuestran es el CONTRATO —que la captura viaja, que el dibujo la usa, que las
# casillas escriben la máscara que corresponde— y no el driver de la placa.
# Ese lado sólo lo cubre `verificar-placa`.

def test_la_pestana_osc_captura_y_dibuja():
    """Una captura llega por el socket y termina dibujada, en volts y en us."""
    def cuerpo(app, v):
        p = v.panel_pulsos
        assert p is not None, 'no se creó la pestaña Pulsos'
        v.tabs.setCurrentWidget(p)
        app.processEvents()

        p.spn_pre.setValue(128)
        p.spn_post.setValue(512)
        p._capturar()
        assert _esperar(app, lambda: len(p._trazas) > 0), 'no llegó ninguna traza'

        pre, datos = p._trazas[-1]
        assert pre == 128
        assert datos.shape == (2, 640), f'forma inesperada: {datos.shape}'
        assert datos.dtype == np.float32

        # El eje de tiempo tiene el trigger en t=0, y por eso arranca negativo:
        # las `pre` muestras de antes del disparo.
        x = p.lineas_ch[0].get_xdata()
        assert len(x) == 640
        assert x[0] < 0 < x[-1], f'el trigger no quedó en t=0: {x[0]}..{x[-1]}'
        assert abs(x[128]) < 1e-9, 'la muestra `pre` no es t=0'
    _con_gui(cuerpo)


def test_la_persistencia_acumula_y_se_puede_apagar():
    def cuerpo(app, v):
        p = v.panel_pulsos
        v.tabs.setCurrentWidget(p)
        for _ in range(3):
            p._capturar()
            app.processEvents()
            time.sleep(0.05)
        assert _esperar(app, lambda: len(p._trazas) >= 3), 'no se acumularon trazas'

        p.chk_fosforo.setChecked(True)
        p._redibujar_forma()
        con = len(p._fosforo)
        assert con > 0, 'con persistencia no se dibujó ninguna traza vieja'

        p.chk_fosforo.setChecked(False)
        p._redibujar_forma()
        assert len(p._fosforo) == 0, 'apagar la persistencia no la borró'
    _con_gui(cuerpo)


def test_la_curva_de_tasa_sale_del_status_del_mca():
    """La tasa del MCA se dibuja sin ninguna lectura extra.

    Es la propiedad que hace barata la pestaña: `rate_inst_hz` ya viene en cada
    `status`, y hasta ahora se mostraba como texto y se tiraba.
    """
    def cuerpo(app, v):
        p = v.panel_pulsos
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: len(p._serie(1)[0]) >= 2), \
            'la curva de tasa del MCA no acumuló puntos'
        _xs, ys = p._serie(1)
        assert any(y > 0 for y in ys), 'todas las tasas dieron cero'
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_la_marca_de_captura_cae_en_la_curva_de_tasa():
    """Lo que ata los dos gráficos: la forma de arriba y el instante de abajo."""
    def cuerpo(app, v):
        p = v.panel_pulsos
        v.tabs.setCurrentWidget(p)
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: len(p._historia) >= 2)
        p._capturar()
        assert _esperar(app, lambda: len(p._marcas) > 0), 'no se anotó la captura'
        assert len(p._lineas_marca) == len(p._marcas)

        t_marca = p._lineas_marca[-1].get_xdata()[0]
        xs = [fila[0] - p._t0 for fila in p._historia]
        assert min(xs) <= t_marca <= max(xs) + 1.0, \
            'la marca cayó fuera del tramo de tasa dibujado'
        v.sig_parar.emit()
    _con_gui(cuerpo)


def test_escribir_un_campo_del_osc_va_al_bloque_del_osc():
    """El campo se rutea por `BLOQUE`, no por el nombre.

    El OSC y el MCA tienen campos de nombres parecidos: si el ruteo fuera por
    nombre, un campo del osciloscopio terminaría escrito en el MCA.
    """
    def cuerpo(app, v):
        p = v.panel_config_osc
        assert p.BLOQUE == 'osc'
        pre_mca_antes = v.panel_config._controles['pre_dly'][1]()

        v.sig_campo_osc.emit('thr_ch0', -250)
        assert _esperar(app, lambda:
                        v.panel_mtrg._controles['thr_ch0'][1]() == -250), \
            'el umbral del OSC no volvió releído del hardware'
        assert p._umbral['thr_ch0'] == -250 and '-0.' in p.lbl_thr_v.text()
        # Y el del MCA no se movió.
        assert v.panel_config._controles['pre_dly'][1]() == pre_mca_antes

        # El umbral de nivel se edita en el Multitrigger, pero es un registro del
        # OSC: va a osc.set y vuelve a las dos pestañas.
        v.panel_mtrg._emitir('thr_ch1', -300)
        assert _esperar(app, lambda: p._umbral.get('thr_ch1') == -300
                        and v.panel_mtrg._controles['thr_ch1'][1]() == -300)
    _con_gui(cuerpo)


def test_el_mapa_de_pulsos_cuenta_las_lineas():
    """Cada traza suma uno en las celdas que recorre su línea: el flanco llena la
    columna entera entre las dos muestras. Se agranda el eje V si una traza se sale,
    empieza de nuevo con otra ventana y resta las trazas que salen por el tope."""
    if QApplication is None:
        print('    (sin PyQt5: salteada)')
        return
    from app.panel_pulsos import MapaPulsos

    m = MapaPulsos(ny=100)
    escalon = np.r_[np.zeros(25), np.ones(25)].astype(np.float32)
    m.agregar(escalon, pre=25)
    H, (t0, t1), (lo, hi) = m.matriz()
    assert H.shape == (100, 49) and (t0, t1) == (-25, 24)
    assert lo < 0 < 1 < hi
    assert (H.sum(axis=0) >= 1).all(), 'una columna sin traza'
    f0, f1 = m._filas(np.array([0.0, 1.0], np.float32))
    assert (H[f0:f1 + 1, 24] == 1).all(), 'el flanco no llenó su columna'
    assert H[:, 0].sum() == 1

    m.agregar(escalon, pre=25)
    assert m.matriz()[0].max() == 2
    m.agregar(3 * escalon, pre=25)                    # se sale: se agranda
    H, _t, (_lo, hi) = m.matriz()
    assert hi > 3 and m.n == 3 and H.sum(axis=0).min() >= 3

    m.agregar(np.zeros(80, np.float32), pre=10)       # otra ventana
    assert m.n == 1 and m.matriz()[0].shape[1] == 79 and m.matriz()[1] == (-10, 69)

    m2 = MapaPulsos(ny=20, max_trazas=50)
    for _ in range(60):
        m2.agregar(np.zeros(30, np.float32), pre=0)
    assert m2.n == 50 and m2.agregadas == 60 and m2.matriz()[0].max() == 50


def test_la_vista_de_pulsos_junta_un_mapa_de_calor():
    """Las capturas van al mapa de los dos canales; una que trae el mismo disparo
    que la anterior no se suma (sería el mismo pulso dos veces). Con el mapa, el
    continuo pide más seguido, pero nunca con una captura en vuelo."""
    def cuerpo(app, v):
        p = v.panel_pulsos
        v.tabs.setCurrentWidget(p)
        p.cmb_vista.setCurrentIndex(p.cmb_vista.findData('mapa'))
        assert p.intervalo_continuo_ms() < 500
        for k in range(3):
            p._capturar()
            assert _esperar(app, lambda: p._mapas[0].n > k), 'la captura no llegó al mapa'
            time.sleep(0.01)
        assert p._mapas[0].n == p._mapas[1].n == 3
        assert p._imagen is not None and p._imagen.get_visible()
        assert not p.lineas_ch[0].get_visible()
        assert '3 traces' in p.lbl_mapa.text()

        pre, datos = p._trazas[-1]
        meta = {'pre': pre, 'dec': 1, 'fs_hz': 125e6, 'wp': 1234}
        p.actualizar_traza(meta, datos)
        p.actualizar_traza(meta, datos)               # el mismo disparo
        assert p._mapas[0].n == 4 and p.repetidas == 1
        assert 'without a new trigger' in p.lbl_mapa.text()

        pedidas = []
        p.pedir_captura.connect(lambda a, b: pedidas.append((a, b)))
        p._pedida = time.monotonic()
        p.pedir_una()
        assert pedidas == [], 'pidió otra con una captura en vuelo'

        p.cmb_vista.setCurrentIndex(p.cmb_vista.findData('pulso'))
        assert p.lineas_ch[0].get_visible() and not p._imagen.get_visible()
        p.borrar_mapa()
        assert p._mapas[0].n == 0
    _con_gui(cuerpo)


def test_el_flujo_del_ring_cierra_las_cuentas():
    from app.diagrama_osc import flujo_ring

    assert flujo_ring({'corriendo': False, 'stats': None, 'hw': None}) is None
    f = flujo_ring({'corriendo': True,
                    'stats': {'n_read': 88, 'n_written': 80, 'chunks': 2},
                    'hw': {'hw_ev_cnt': 90, 'hw_drop_busy': 6, 'hw_drop_full': 4,
                           'hw_no_leidos': 0xFFFFFFFE, 'hw_n_slots': 4096}})
    assert f['disparos'] == 100 and f['perdidos'] == 10
    assert abs(f['frac_perdidos'] - 0.1) < 1e-12
    assert f['sin_leer'] == 0, 'la resta sin signo que da la vuelta es cero'
    assert (f['leidos'], f['escritos'], f['archivos']) == (88, 80, 2)


def test_configuracion_osc_lleva_el_ring_en_su_franja():
    """El ring es la fila de abajo de la franja: sus grupos son etapas, el estímulo
    se mueve entre el disparo y el generador, y el disparo del ADC usa el umbral de
    la etapa Disparo (una sola vez en la pestaña)."""
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtTest import QTest

    def cuerpo(app, v):
        c, r = v.panel_config_osc, v.panel_ring
        assert c.diagrama.hay_ring and r is c.ring
        assert {'entrada', 'diezmado', 'disparo', 'bram', 'ventana', 'ddr',
                'archivos'} <= set(c._grupos)

        r.cmb_estimulo.setCurrentIndex(r.cmb_estimulo.findData('generador'))
        assert r.grp_estimulo in c._grupos['generador']
        assert c.diagrama._estimulo == 'generador'
        r.cmb_estimulo.setCurrentIndex(r.cmb_estimulo.findData('disparo'))
        assert r.grp_estimulo in c._grupos['disparo']
        assert r.grp_estimulo not in c._grupos['generador']

        c.fijar_disparo_v(0.125, 0.02)
        kw = r.argumentos()
        assert abs(kw['disparo']['thr'] - 0.125) < 1 / 8192
        assert abs(kw['disparo']['hyst'] - 0.02) < 1 / 8192
        assert r.spn_thr.isHidden() and not r.lbl_disparo.isHidden()
        assert '+0.125 V' in r.lbl_disparo.text()

        app.sendEvent(r.grp_ventana, QEvent(QEvent.Enter))
        assert c.diagrama.resaltada == 'ventana'
        app.sendEvent(r.grp_ventana, QEvent(QEvent.Leave))
        assert c.diagrama.resaltada is None

        c.diagrama.resize(1200, c.diagrama.height())
        pedidas = []
        c.diagrama.etapa_elegida.connect(pedidas.append)
        for clave in ('bram', 'ddr'):
            centro = c.diagrama.caja(clave).center()
            QTest.mouseClick(c.diagrama, Qt.LeftButton,
                             pos=QPoint(int(centro.x()), int(centro.y())))
        assert pedidas == ['bram', 'ddr']
        assert c.diagrama.resaltada == 'ddr'
    _con_gui(cuerpo)


def test_las_casillas_del_multitrigger_arman_la_mascara():
    def cuerpo(app, v):
        p = v.panel_mtrg
        assert p is not None, 'no se creó la pestaña de Multitrigger'
        assert _esperar(app, lambda: len(p._casillas) > 0), \
            'no llegaron los nombres de los bits desde el servidor'

        # Los nombres los manda el SERVIDOR: el cliente no tiene su propia copia
        # de la lista de bits, que es como se desincroniza de un RTL que cambió.
        nombres = [n for n, _v, _a in p._bits]
        assert 'sw' in nombres and 'adc_p0' in nombres

        from API.multitrigger import BIT_ADC_P0
        p._mascaras[0] = 0
        p._cambio(0, BIT_ADC_P0, True)
        assert _esperar(app, lambda:
                        p._casillas[(0, BIT_ADC_P0)].isChecked()
                        and p._mascaras[0] & BIT_ADC_P0), \
            'marcar la casilla no encendió el bit'

        p._cambio(0, BIT_ADC_P0, False)
        assert _esperar(app, lambda: not (p._mascaras[0] & BIT_ADC_P0)), \
            'desmarcar la casilla no apagó el bit'
    _con_gui(cuerpo)


def test_la_franja_del_multitrigger_lee_las_fuentes_y_el_shield():
    """Las cuentas de la franja del Multitrigger, sin Qt: los bits del servidor en
    filas por fuente (sin los canales que el bitstream no trae), la máscara que usa
    cada canal con y sin indep_mode, el shield en palabras, lo mal puesto, y lo que
    el MCA ve del disparo."""
    from API.multitrigger import (BIT_ADC_P0, BIT_SLOPE_P0, BITS_OR_MASK,
                                  BITS_SHIELD_DST, BITS_SHIELD_SRC)
    from app.diagrama_mt import (describir_escudo, diagnostico, filas_mascara,
                                 flujo_mt, mascaras_efectivas)
    bits = [[n, int(v), a] for n, v, a in BITS_OR_MASK]
    b_src = [[n, int(v), a] for n, v, a in BITS_SHIELD_SRC]
    b_dst = [[n, int(v), a] for n, v, a in BITS_SHIELD_DST]

    filas, ocultos = filas_mascara(bits, n_ch=2)
    assert [r for _f, r, _p in filas] == [
        'software', 'level IN1', 'slope IN1', 'pole-zero IN1', 'level IN2',
        'slope IN2', 'pole-zero IN2', 'external DIO0', 'generator (ASG)']
    # Los canales 2 y 3 y la cadena de otro scope no están en este bitstream.
    fuera = {n for n, v, _a in bits if ocultos & v}
    assert {'adc_p2', 'slope_n3', 'pz_p3', 'trig_ch0'} <= fuera
    assert not fuera & {'sw', 'adc_p0', 'slope_n1', 'pz_p1', 'ext_p', 'asg_n'}

    cfg = {'or_mask_ch0': BIT_SLOPE_P0, 'or_mask_ch1': BIT_ADC_P0}
    assert mascaras_efectivas(cfg, 2, indep=0) == [BIT_SLOPE_P0, BIT_SLOPE_P0]
    assert mascaras_efectivas(cfg, 2, indep=0b10) == [BIT_SLOPE_P0, BIT_ADC_P0]
    assert mascaras_efectivas(cfg, 2, indep=None) == [BIT_SLOPE_P0, BIT_ADC_P0]

    assert 'IN1 at once: hardware re-arm' in describir_escudo(1, 1, 0, b_src, b_dst)
    assert '125 cycles (1 µs) later' in describir_escudo(1, 1, 125, b_src, b_dst)
    veto = describir_escudo(0x40, 0x10, 0, b_src, b_dst)
    assert 'while DIO0 is high' in veto and 're-arms no channel' in veto
    assert describir_escudo(0, 0, 0, b_src, b_dst).startswith('Off')

    # El disparo del MCA como lo deja multitrigger_armar_mca: IN2 repite la máscara
    # de IN1 (sin indep_mode) y no se re-arma, pero el evento no pierde nada.
    pend = {'en': True, 'L': 8, 'G': 4, 'thr': 600, 'hyst': 300}
    info = {'bits': bits, 'bits_shield_dst': b_dst, 'n_ch': 2, 'indep': 0,
            'config': {'or_mask_ch0': BIT_SLOPE_P0, 'or_mask_ch1': 0,
                       'shield_src': 1, 'shield_dst': 1, 'shield_dur': 0},
            'status': {'flags': 0x30},
            'canales': [{'pendiente': pend, 'polo_cero': None},
                        {'pendiente': dict(pend, en=False), 'polo_cero': None}]}
    d = diagnostico(info)
    assert not [t for avisos in d.values() for t, grave in avisos if grave], d
    assert ('IN2 uses the mask of IN1', False) in d['mascara']
    # El veto por nivel de DIO0 deja de re-armar IN1: se para tras el primero.
    info['config'].update(shield_src=0x40, shield_dst=0x10)
    assert diagnostico(info)['escudo'] == [('IN1 stops after its first trigger', True)]
    # La pendiente en la máscara pero apagada; la máscara vacía.
    info['canales'][0]['pendiente'] = dict(pend, en=False)
    assert diagnostico(info)['fuentes'] == [('slope IN1 is in a mask but off', True)]
    info['config'].update(or_mask_ch0=0)
    assert ('no source in any mask: nothing triggers', True) in \
        diagnostico(info)['mascara']

    f = flujo_mt({'realtime_s': 2.0, 'cross': 1000, 'lost_veto': 10,
                  'vetotime_s': 0.5, 't_rearm_s': 0.1})
    assert f['tasa'] == 500 and f['vetados'] == 10
    assert abs(f['frac_veto'] - 0.25) < 1e-12
    assert abs(f['frac_rearmado'] - 0.05) < 1e-12


def test_la_pestana_del_multitrigger_va_por_etapas_y_sigue_al_disparo_del_mca():
    """Armar el disparo del MCA desde Spectrum se ve en el Multitrigger: la pendiente
    de IN1 en la máscara y en las fuentes, el shield re-armando IN1; y en «OSC
    settings», que sólo muestra las fuentes. El shield se escribe con casillas con
    nombre y se describe en palabras; la franja marca lo mal puesto, sigue al ratón y
    lleva a los controles; «OSC settings» y «Spectrum» llevan al Multitrigger, y todo
    entra sin scroll en la ventana de siempre."""
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtTest import QTest
    from API.multitrigger import BIT_SLOPE_P0

    def graves(p):
        return [t for avisos in p.diagrama.diagnostico().values()
                for t, grave in avisos if grave]

    def cuerpo(app, v):
        v.resize(1240, 860)
        v.show()
        p = v.panel_mtrg
        v.tabs.setCurrentWidget(p)
        assert _esperar(app, lambda: p._casillas_escudo['shield_src'])
        v.panel_espectro.btn_armar.click()
        assert _esperar(app, lambda: p._casillas[(0, BIT_SLOPE_P0)].isChecked()), \
            'el disparo del MCA no se ve en la máscara'
        assert p.spn_l.value() == 8 and 'slope IN1' in p.lbl_disparo.text()
        assert _esperar(app, lambda: 'slope IN1' in v.panel_config_osc.lbl_fuentes.text())
        assert 'hardware re-arm' in p.lbl_escudo.text()
        assert graves(p) == []
        # Sin los canales 2 y 3: ni columnas en la máscara ni casillas en el shield.
        assert {ch for ch, _v in p._casillas} == {0, 1}
        assert [c.text() for _v, c in p._casillas_escudo['shield_src']] == \
            ['IN1', 'IN2', 'DIO0 ↑', 'DIO0 ↓', 'DIO0 level']

        # El veto por nivel con las casillas: el shield deja de re-armar IN1.
        src = {c.text(): c for _v, c in p._casillas_escudo['shield_src']}
        dst = {c.text(): c for _v, c in p._casillas_escudo['shield_dst']}
        src['DIO0 level'].setChecked(True)
        src['IN1'].setChecked(False)
        dst['veto the MCA'].setChecked(True)
        dst['re-arm IN1'].setChecked(False)
        assert _esperar(app, lambda: p._info['config']['shield_src'] == 0x40
                        and p._info['config']['shield_dst'] == 0x10)
        assert graves(p) == ['IN1 stops after its first trigger']
        assert 're-arms no channel' in p.lbl_escudo.text()
        p.aplicar_escudo(1, 1, 0)
        assert _esperar(app, lambda: p._info['config']['shield_src'] == 1
                        and p._info['config']['shield_dst'] == 1 and not graves(p))

        app.sendEvent(p._grupos['escudo'][0], QEvent(QEvent.Enter))
        assert p.diagrama.resaltada == 'escudo'
        app.sendEvent(p._grupos['escudo'][0], QEvent(QEvent.Leave))
        centro = p.diagrama.caja('mascara').center()
        QTest.mouseClick(p.diagrama, Qt.LeftButton,
                         pos=QPoint(int(centro.x()), int(centro.y())))
        assert p.diagrama.resaltada == 'mascara'

        assert p.scroll.verticalScrollBar().maximum() == 0
        assert p.scroll.horizontalScrollBar().maximum() == 0
        assert v.width() == 1240

        v.tabs.setCurrentWidget(v.panel_config_osc)
        v.panel_config_osc.btn_ir_mtrg.click()
        assert v.tabs.currentWidget() is p
        v.tabs.setCurrentWidget(v.panel_espectro)
        v.panel_espectro.btn_ir_mtrg.click()
        assert v.tabs.currentWidget() is p and p.diagrama.resaltada == 'fuentes'
        v.sig_disparo.emit({'ch': 0, 'armar': False})
    _con_gui(cuerpo)


def test_los_campos_de_los_paneles_existen_en_su_bloque():
    """Un nombre mal escrito sólo se notaría al tocar el control.

    El panel emite `(campo, valor)` y el servidor lo busca en la tabla del
    bloque; sin esto, el error sale como una línea en el log la primera vez que
    alguien mueve ese control, meses después.
    """
    def cuerpo(app, v):
        from app.widgets_config import campos_desconocidos
        for panel in (v.panel_config, v.panel_config_osc, v.panel_mtrg):
            for bloque, campos in panel.campos_por_bloque().items():
                malos = campos_desconocidos(campos, bloque)
                assert not malos, f'{type(panel).__name__} ({bloque}): {malos}'
        # El Multitrigger escribe en dos bloques: el nivel es del OSC.
        assert set(v.panel_mtrg.campos_por_bloque()['osc']) == {
            'thr_ch0', 'thr_ch1', 'hyst_ch0', 'hyst_ch1', 'deb_len'}
    _con_gui(cuerpo)


# =============================================================================
# La pestaña del generador de pulsos
# =============================================================================

def test_las_amplitudes_del_generador_se_leen_del_texto():
    from app.panel_generador import leer_lineas
    assert leer_lineas('1500, 4000', '0.6 0.4') == [[1500, 0.6], [4000, 0.4]]
    assert leer_lineas('-200', '') == [[-200, 1.0]]
    for amp, pesos in (('', ''), ('1500, 4000', '1'), ('9000', ''),
                       ('1.5', ''), ('abc', ''), ('10, 20', '0 0')):
        try:
            leer_lineas(amp, pesos)
        except ValueError:
            pass
        else:
            raise AssertionError(f'aceptó {amp!r} / {pesos!r}')


def test_la_pestana_del_generador_configura_y_relee():
    def cuerpo(app, v):
        assert v.panel_gen is not None, 'sin pestaña del generador'
        assert v.tabs.indexOf(v.panel_gen) >= 0
        p = v.panel_gen
        assert _esperar(app, lambda: p.lbl_mq.text() != '—')
        p.cmb_modo.setCurrentIndex(1)
        p.spn_tasa.setValue(20000)
        p.ed_amplitudes.setText('1500, 4000')
        p.ed_pesos.setText('3, 1')
        p.spn_tau.setValue(3.0)
        p.btn_aplicar.click()
        assert _esperar(app, lambda: 'drawn' in p.lbl_amp_modo.text())
        # Lo que vuelve es lo releído de la placa: los pesos, en fracción de tabla.
        assert p.ed_amplitudes.text() == '1500, 4000'
        assert p.ed_pesos.text().startswith('0.75')
        assert abs(float(p.lbl_tau.text()) - 3.0) < 0.02
        assert abs(float(p.lbl_tasa.text()) / 20000 - 1) < 1e-3
        # Un error se avisa en la pestaña, sin diálogo modal, y no escribe nada.
        p.ed_amplitudes.setText('1500, 99999')
        p.btn_aplicar.click()
        assert 'not applied' in p.lbl_error.text()
        p.btn_releer.click()
        assert _esperar(app, lambda: p.ed_amplitudes.text() == '1500, 4000')
    _con_gui(cuerpo)


def test_el_lazo_se_ve_en_la_barra_y_lleva_la_tasa_al_espectro():
    """Prender el lazo desde la pestaña: aparece el aviso arriba y, con el
    generador andando, la tasa de entrada del espectro es la del generador."""
    def cuerpo(app, v):
        p = v.panel_gen
        assert _esperar(app, lambda: p.lbl_mq.text() != '—')
        p.cmb_modo.setCurrentIndex(1)
        p.spn_tasa.setValue(5000)
        p.ed_amplitudes.setText('2000')
        p.btn_aplicar.click()
        assert _esperar(app, lambda: p.lbl_amp_modo.text() == 'one fixed amplitude')
        assert not v.lbl_lazo.isVisibleTo(v)
        p.chk_lazo.setChecked(True)
        assert _esperar(app, lambda: v.lbl_lazo.isVisibleTo(v))
        p.btn_arrancar.click()
        assert _esperar(app, lambda: p.lbl_estado.text() == 'generating')
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: v.panel_espectro.contadores.get(
            'realtime_s', 0) > 1.5)
        tasa = v.panel_espectro.tasa_media_hz
        assert abs(tasa / 5000 - 1) < 0.15, tasa
        v.sig_parar.emit()
        p.btn_parar.click()
        p.chk_lazo.setChecked(False)
        assert _esperar(app, lambda: not v.lbl_lazo.isVisibleTo(v))
    _con_gui(cuerpo)


def test_la_franja_del_generador_compara_tasas():
    from app.diagrama_gen import comparar_tasas
    assert abs(comparar_tasas(1000.0, 990.0) + 0.01) < 1e-12
    for gen, lam in ((0, 990.0), (None, 990.0), (1000.0, None), (1000.0, 0.0)):
        assert comparar_tasas(gen, lam) is None


def test_la_pestana_del_generador_marca_lo_editado_y_compara_con_el_mca():
    """Lo editado sin aplicar marca su etapa en la franja y se avisa al lado de
    «Apply»; aplicar (o releer) lo limpia. El ratón sobre un grupo resalta su
    bloque. Con el lazo y el generador andando, la franja compara la λ̂ del MCA
    con la tasa del generador."""
    from PyQt5.QtCore import QEvent

    def cuerpo(app, v):
        p = v.panel_gen
        assert _esperar(app, lambda: p.lbl_mq.text() != '—')
        assert p.editadas == set()
        p.spn_tau.setValue(p.spn_tau.value() + 0.5)
        p.ed_amplitudes.textEdited.emit(p.ed_amplitudes.text())
        assert p.editadas == {'forma', 'amplitud'}
        assert p.diagrama.marcadas == {'forma', 'amplitud'}
        assert 'Amplitude, Pulse shape' in p.lbl_pendiente.text()
        p.btn_aplicar.click()
        assert _esperar(app, lambda: not p.editadas and not p.diagrama.marcadas)
        assert p.lbl_pendiente.text() == ''

        g = p._grupos['disparos'][0]
        app.sendEvent(g, QEvent(QEvent.Enter))
        assert p.diagrama.resaltada == 'disparos'
        app.sendEvent(g, QEvent(QEvent.Leave))

        p.cmb_modo.setCurrentIndex(1)
        p.spn_tasa.setValue(5000)
        p.btn_aplicar.click()
        assert _esperar(app, lambda: not p.editadas)
        p.chk_lazo.setChecked(True)
        assert _esperar(app, lambda: p.diagrama.lazo)
        p.btn_arrancar.click()
        v.sig_start.emit(0.0, True)
        assert _esperar(app, lambda: p.diagrama.diferencia() is not None)
        assert _esperar(app, lambda: v.panel_espectro.contadores.get(
            'realtime_s', 0) > 1.5)
        assert abs(p.diagrama.diferencia()) < 0.15, p.diagrama.diferencia()
        v.sig_parar.emit()
        p.btn_parar.click()
        p.chk_lazo.setChecked(False)
        assert _esperar(app, lambda: p.diagrama.diferencia() is None)
    _con_gui(cuerpo)


def test_la_mq_del_generador_va_al_trapecio():
    def cuerpo(app, v):
        p = v.panel_gen
        assert _esperar(app, lambda: p.lbl_mq.text() != '—')
        mq = int(p.lbl_mq.text())
        p.btn_mq.click()
        assert _esperar(app, lambda:
                        v.panel_config._controles['trap_mq'][1]() == mq)
    _con_gui(cuerpo)


# =============================================================================
# La pestaña del event_ring
# =============================================================================

def _ring_visible(app, v, carpeta):
    p = v.panel_ring
    assert p is not None, 'sin el ring en «OSC settings»'
    v.tabs.setCurrentWidget(v.panel_config_osc)
    p.ed_carpeta.setText(carpeta)
    return p


def test_la_pestana_del_ring_corre_con_el_generador_y_cierra_las_cuentas():
    """Una corrida con N disparos del generador de eventos: la sesión los lee todos,
    EV_CNT + DROP_BUSY + DROP_FULL = N, y quedan archivos en la carpeta nueva."""
    from API.osciloscope_store import archivos_de_corrida

    def cuerpo(app, v):
        with tempfile.TemporaryDirectory() as tmp:
            p = _ring_visible(app, v, tmp)
            p.cmb_estimulo.setCurrentIndex(p.cmb_estimulo.findData('generador'))
            p.spn_tasa.setValue(1e5)
            p.spn_n.setValue(2000)
            p.btn_iniciar.click()
            assert _esperar(app, lambda: p.ultimo.get('corriendo')), p.lbl_error.text()
            assert _esperar(app, lambda: (p.ultimo.get('stats') or {}).get(
                'n_read', 0) >= 2000 and (p.ultimo.get('hw') or {}).get(
                'hw_gen_terminado'))
            assert p.btn_parar.isEnabled() and not p.btn_iniciar.isEnabled()
            p.btn_parar.click()
            assert _esperar(app, lambda: not p.ultimo.get('corriendo'))
            hw = p.ultimo['hw_final']
            assert hw['hw_ev_cnt'] + hw['hw_drop_busy'] + hw['hw_drop_full'] == 2000
            assert p.ultimo['stats']['n_written'] == hw['hw_ev_cnt']
            run_dir = p.ultimo['run_dir']
            assert run_dir.startswith(tmp) and archivos_de_corrida(run_dir)
            assert p.lbl_estado.text().startswith('stopped')
            assert p.btn_iniciar.isEnabled()
            fl = v.panel_config_osc.diagrama.flujo
            assert fl['disparos'] == 2000 and fl['capturados'] == hw['hw_ev_cnt']
            assert fl['escritos'] == p.ultimo['stats']['n_written']
    _con_gui(cuerpo)


def test_el_ring_sin_fin_corre_hasta_parar():
    def cuerpo(app, v):
        with tempfile.TemporaryDirectory() as tmp:
            p = _ring_visible(app, v, tmp)
            p.cmb_estimulo.setCurrentIndex(p.cmb_estimulo.findData('generador'))
            p.cmb_modo.setCurrentIndex(1)
            p.spn_tasa.setValue(5e4)
            p.spn_n.setValue(0)
            p.btn_iniciar.click()
            assert _esperar(app, lambda: (p.ultimo.get('stats') or {}).get(
                'n_read', 0) > 5000)
            assert p.ultimo['corriendo'] and p.lbl_tasa.text() not in ('', '—')
            p.btn_parar.click()
            assert _esperar(app, lambda: not p.ultimo.get('corriendo'))
    _con_gui(cuerpo)


def test_el_ring_avisa_en_la_pestana_lo_que_no_puede_iniciar():
    """Una carpeta relativa no sale del cliente; una que no existe la rechaza el
    servidor, y el motivo llega a la pestaña. Ninguna de las dos con un diálogo."""
    def cuerpo(app, v):
        p = _ring_visible(app, v, 'datos')
        p.btn_iniciar.click()
        assert 'absolute' in p.lbl_error.text()
        p.ed_carpeta.setText('/no/existe/esta/carpeta')
        p.btn_iniciar.click()
        assert _esperar(app, lambda: 'no existe' in p.lbl_error.text())
        assert not p.ultimo.get('corriendo')
    _con_gui(cuerpo)


def test_la_ocupacion_del_ring_no_se_llena_por_una_resta_negativa():
    """`hw_no_leidos` sin signo: si el lector avanzó entre las dos lecturas, la resta
    da la vuelta. Eso es cero sin leer, no el ring lleno."""
    if QApplication is None:
        return
    app = QApplication.instance() or QApplication([])           # noqa: F841 (vive)
    from app.panel_ring import PanelRing
    p = PanelRing()
    base = {'corriendo': True, 'stats': {'n_read': 10, 'n_written': 0, 'chunks': 0},
            'run_dir': '/dev/shm/ring_x', 'fs': 'tmpfs'}
    for crudo, esperado in ((5, 5), (0xFFFFFFFE, 0), (99999, 4096)):
        p.actualizar_ring(dict(base, hw={'hw_ev_cnt': 10, 'hw_drop_busy': 0,
                                         'hw_drop_full': 0, 'hw_n_slots': 4096,
                                         'hw_no_leidos': crudo}))
        assert p.bar_ring.value() == esperado, (crudo, p.bar_ring.value())
