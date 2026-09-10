#!/usr/bin/env python3
"""Las tablas de campos del osciloscopio y del multitrigger.

Corre sin placa: los dos bloques se acceden por `r32`/`w32`, así que un modelo
de registros de tres líneas alcanza para probar la aritmética de bits, que es
donde estas tablas se equivocan.

Lo que NO cubre, y conviene tenerlo dicho: que las MÁSCARAS coincidan con el
RTL. Están copiadas de `modulos/osc/rtl/osc_cfg.sv` —`set_tresh` es DW=14,
`set_dec` 17, `set_deb_len` 20, `set_filt_byp` 4— pero acá no hay nada que lo
verifique contra el hardware. Eso lo comprueba `verificar-placa-mca`, que
escribe y relee cada registro en la placa.
"""

import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import pytest                                                      # noqa: E402

from API import multitrigger as MT                                 # noqa: E402
from API import osciloscope as O                                   # noqa: E402


class Registros:
    """Un bloque que retiene lo que se le escribe. Nada más."""

    def __init__(self, inicial=None):
        self.m = dict(inicial or {})

    def r32(self, off):
        return self.m.get(off, 0)

    def w32(self, off, v):
        self.m[off] = int(v) & 0xFFFFFFFF


# =============================================================================
# Osciloscopio
# =============================================================================

def test_ida_y_vuelta_de_todos_los_campos():
    """Lo escrito se relee igual. Es de lo que depende el anti-eco de la GUI:
    si el readback no coincide, el panel reescribe en un lazo."""
    r = Registros()
    valores = {campo: 1 for campo in O._CAMPOS}
    O.osciloscope_configure(r, **valores)
    leidos = O.osciloscope_get_config(r)
    for campo in O._CAMPOS:
        assert leidos[campo] == 1, campo


def test_el_umbral_conserva_el_signo():
    """14 bits en complemento a dos. Sin extender el signo, -500 se lee como
    +15884 y el control de la GUI salta al tope."""
    r = Registros()
    O.osciloscope_configure(r, thr_ch0=-500, thr_ch1=-8192)
    c = O.osciloscope_get_config(r)
    assert c['thr_ch0'] == -500
    assert c['thr_ch1'] == -8192          # el más negativo representable
    # Y en el registro está el patrón de 14 bits, no un entero negativo de 32.
    assert r.m[O.R_THR_CH0] == (-500 & 0x3FFF)


def test_los_campos_del_mismo_registro_no_se_pisan():
    """`avg_en_ch0` y `avg_en_ch1` comparten palabra: escribirlos de a uno haría
    que el segundo leyera lo que el primero acaba de cambiar."""
    r = Registros()
    O.osciloscope_configure(r, avg_en_ch0=1, avg_en_ch1=1)
    c = O.osciloscope_get_config(r)
    assert (c['avg_en_ch0'], c['avg_en_ch1']) == (1, 1)
    # El layout del RTL es un BYTE por canal, no bits contiguos: 0x101, no 0x3.
    assert r.m[O.R_AVG_EN] == 0x101

    # Y tocar uno solo deja al otro donde estaba.
    O.osciloscope_configure(r, avg_en_ch0=0)
    c = O.osciloscope_get_config(r)
    assert (c['avg_en_ch0'], c['avg_en_ch1']) == (0, 1)


def test_las_mascaras_recortan_como_el_rtl():
    """Escribir de más no rompe —el RTL trunca— pero leer de más devolvería
    bits que no existen y el readback dejaría de coincidir."""
    r = Registros()
    O.osciloscope_configure(r, deb_len=0xFFFFFFFF, filt_bypass=0xFF)
    c = O.osciloscope_get_config(r)
    assert c['deb_len'] == 0xFFFFF        # 20 bits
    assert c['filt_bypass'] == 0xF        # 4 bits, uno por canal


def test_un_campo_inventado_falla_al_escribir():
    r = Registros()
    with pytest.raises(ValueError, match='campos desconocidos'):
        O.osciloscope_configure(r, umbral=100)


def test_la_decimacion_solo_acepta_los_valores_legales():
    """El validador está en el setter suelto, no en la tabla: la tabla escribe
    lo que le den. La GUI usa un combo con estos seis y por eso no puede
    mandar otro."""
    r = Registros()
    with pytest.raises(ValueError, match='no legal'):
        O.osciloscope_set_decim(r, 7)
    for d in O.DEC_LEGAL:
        O.osciloscope_set_decim(r, d)


# =============================================================================
# Multitrigger
# =============================================================================

def test_los_tres_campos_del_shield_comparten_palabra():
    """Layout de 0x210: {dur[31:16], 4'h0, dst[11:8], 4'h0, src[3:0]}."""
    r = Registros()
    MT.multitrigger_configure(r, shield_src=3, shield_dst=3, shield_dur=7)
    assert r.m[MT.R_SHIELD_CFG] == 0x0007_0303
    c = MT.multitrigger_get_config(r)
    assert (c['shield_src'], c['shield_dst'], c['shield_dur']) == (3, 3, 7)


def test_un_registro_que_no_retiene_se_denuncia():
    """Con `assert` esto desaparecía bajo `python -O`, y una máscara que no
    latchea deja el scope sin disparar sin más síntoma que 'no llegan eventos'."""
    class Sordo(Registros):
        def w32(self, off, v):
            pass                          # acepta y no guarda

    with pytest.raises(RuntimeError, match='no retuvo lo escrito'):
        MT.multitrigger_configure(Sordo(), or_mask_ch0=0xFF)


def test_los_bits_de_la_mascara_son_los_del_snapshot():
    """Las casillas de la GUI y las fuentes del snapshot tienen que
    corresponderse posicionalmente: son la misma lista del RTL."""
    nombres_mascara = [n for n, _v, _a in MT.BITS_OR_MASK]
    assert len(nombres_mascara) == len(MT._SNAP_NAMES)
    # Los valores son bits sucesivos desde el 0, sin huecos ni repetidos.
    valores = [v for _n, v, _a in MT.BITS_OR_MASK]
    assert valores == [1 << i for i in range(len(valores))]


def test_decode_snap_nombra_las_fuentes_activas():
    assert MT.decode_snap(0) == []
    assert MT.decode_snap(0b11) == ['sw_any', 'adc_p0']


# =============================================================================
# Los simulados
# =============================================================================

def test_el_osc_simulado_devuelve_la_ventana_pedida():
    from API.mca_remote import FakeOsc
    o = FakeOsc(semilla=1)
    datos = o.capturar(pre=100, post=400, n_ch=2)
    assert datos.shape == (2, 500)
    assert datos.dtype.name == 'float32'
    # Hay un pulso en el trigger: el máximo de la ventana está cerca de `pre`.
    assert abs(int(datos[0].argmax()) - 100) < 5 * 40      # 5 sigmas del ancho


def test_el_osc_simulado_retiene_la_configuracion():
    from API.mca_remote import FakeOsc
    o = FakeOsc()
    O.osciloscope_configure(o, thr_ch0=-250, dec_ch0=8)
    c = O.osciloscope_get_config(o)
    assert c['thr_ch0'] == -250
    assert c['dec_ch0'] == 8
