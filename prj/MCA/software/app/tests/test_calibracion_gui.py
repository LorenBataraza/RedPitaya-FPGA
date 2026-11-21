"""La pestaña «Calibration» de punta a punta contra el servidor en --fake, sin pantalla.

El servidor falso mide el canal con `API/canal_falso.py` (caída lenta conocida) y su
MCA cuenta la tasa del generador con el lazo, así que la pestaña recorre lo mismo que
en la placa: medir, la repetibilidad, Origin, guardar y cargar, G_F y la base
dinámica, con «MCA settings» de sólo lectura mientras está prendida.

    python -m pytest app/tests/test_calibracion_gui.py -q
"""

import os
import sys

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)
sys.path.insert(0, _AQUI)

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLBACKEND', 'Qt5Agg')

import pytest                                                      # noqa: E402

from API.canal_falso import CanalFalso                             # noqa: E402
from test_mcamon_gui import _con_gui, _esperar                     # noqa: E402

pytest.importorskip('PyQt5')
CAIDA = CanalFalso().caida


def _medir(app, p, filas_antes):
    p.btn_medir.click()
    assert _esperar(app, lambda: len(p._filas) > filas_antes, timeout=30), \
        f'no llegó la medición: {p.lbl_error.text()} {p.lbl_estado.text()}'


def test_la_pestana_mide_y_guarda(tmp_path):
    def cuerpo(app, v):
        v.resize(1240, 860)
        v.show()
        p = v.panel_cal
        assert p is not None
        assert 'Calibration' in [v.tabs.tabText(i) for i in range(v.tabs.count())]
        v.tabs.setCurrentWidget(p)
        app.processEvents()
        # Entra sin agrandar la ventana.
        assert v.width() == 1240 and v.height() == 860
        assert p.minimumSizeHint().height() <= p.height()

        _medir(app, p, 0)
        r = p._res
        assert r['caida_lenta_usar'] == pytest.approx(CAIDA, rel=0.1)
        assert 'restored' in p.lbl_estado.text()
        assert '%' in p._lbl['caida'].text() and 'slow fit' in p._lbl['caida'].text()
        assert p._lbl['piso'].text() != '—'
        assert p.tabla.rowCount() == 1 and p.tabla.item(0, 0).text() == 'OUT1→T50→IN1'
        lineas = p.diagrama.lineas()
        assert 'slow drop' in lineas['modelo'][0][0]
        assert p.btn_b0.isEnabled()

        # La repetibilidad: dos rápidas, y el falso es estable.
        p.btn_repetir.click()
        assert _esperar(app, lambda: 'noise' in p.lbl_repet.text(), timeout=30), \
            p.lbl_error.text()
        assert 'stable' in p.lbl_repet.text() and 'NOT' not in p.lbl_repet.text()

        # La externa agrega su fila, y el veredicto cambia.
        p.cmb_ref.setCurrentIndex(1)
        assert p.ed_rotulo.text() == 'external→T50→IN1'
        _medir(app, p, len(p._filas))
        assert p._filas[-1]['referencia'] == 'externa'
        assert 'front-end' in p.lbl_veredicto.text() or 'both' in p.lbl_veredicto.text()

        # Guardar y cargar en un panel nuevo da lo mismo.
        ruta = p.guardar(tmp_path / 'cal.json')
        assert os.path.exists(ruta) and os.path.exists(str(tmp_path / 'cal.npz'))
        from app.panel_calibracion import PanelCalibracion
        q = PanelCalibracion()
        q.cargar(ruta)
        assert [f['rotulo'] for f in q._filas] == [f['rotulo'] for f in p._filas]
        assert q._lbl['caida'].text() == p._lbl['caida'].text()
        assert set(q._caps) == set(p._caps)
        q.deleteLater()
    _con_gui(cuerpo, h_aw=13)


def test_la_base_dinamica_desde_la_pestana():
    def cuerpo(app, v):
        p = v.panel_cal
        v.tabs.setCurrentWidget(p)
        _medir(app, p, 0)
        # Sin G_F no se prende, y lo dice.
        p.chk_din.setChecked(True)
        assert not p.chk_din.isChecked() and 'G_F' in p.lbl_aviso.text()

        p.btn_gf.click()
        assert _esperar(app, lambda: '/ADU' in p.lbl_gf.text(), timeout=20), \
            p.lbl_error.text()
        assert p.btn_check.isEnabled()

        p.chk_din.setChecked(True)
        assert _esperar(app, lambda: (p._base or {}).get('on'), timeout=10)
        assert _esperar(app, lambda: v.panel_config.base_dinamica, timeout=5)
        w = v.panel_config._controles['baseline'][0]
        assert w.isReadOnly() and v.panel_config.lbl_base_dinamica.isVisibleTo(
            v.panel_config)
        assert p.diagrama.lineas()['base'][0][0].startswith('Δb')

        # κ nuevo va al servidor con la dinámica prendida.
        p.spn_kappa.setValue(0.5)
        assert _esperar(app, lambda: (p._base or {}).get('kappa') == 0.5, timeout=10)

        p.chk_din.setChecked(False)
        assert _esperar(app, lambda: not v.panel_config.base_dinamica, timeout=10)
        assert not w.isReadOnly()
        assert p.diagrama.lineas()['base'][0][0] == 'fixed: dynamic off'
    _con_gui(cuerpo, h_aw=13)


def test_un_fallo_va_a_la_etiqueta():
    """Medir con el MCA corriendo: el servidor lo rechaza (en castellano, como todo lo
    que viene de la API) y la pestaña lo muestra en rojo, sin un diálogo (que colgaría
    la prueba)."""
    def cuerpo(app, v):
        p = v.panel_cal
        v.sig_start.emit(0.0, False)
        assert _esperar(app, lambda: v.panel_espectro._corriendo
                        if hasattr(v.panel_espectro, '_corriendo') else True, timeout=5)
        _esperar(app, lambda: False, timeout=0.5)
        p.btn_medir.click()
        assert _esperar(app, lambda: 'corriendo' in p.lbl_error.text(), timeout=15), \
            p.lbl_error.text()
        assert p.lbl_estado.text() == 'failed' and p.btn_medir.isEnabled()
        v.sig_parar.emit()
    _con_gui(cuerpo, h_aw=13)


def test_el_veredicto():
    from app.panel_calibracion import veredicto
    gen = dict(referencia='generador', caida=-0.073)
    assert 'Measure' in veredicto([gen])
    assert 'loaded output' in veredicto([gen, dict(referencia='externa', caida=-0.002)])
    assert 'front-end' in veredicto([gen, dict(referencia='externa', caida=-0.07)])
    assert 'both' in veredicto([gen, dict(referencia='externa', caida=-0.03)])
