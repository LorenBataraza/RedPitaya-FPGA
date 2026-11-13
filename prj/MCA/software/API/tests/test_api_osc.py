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


def _mt(regs=None):
    """El handle del multitrigger sobre esos registros: la lógica es la de libmca,
    que llega acá por el backend de callbacks. `.m` son los registros."""
    regs = Registros() if regs is None else regs

    class H(MT.MultiTrigger):
        m = regs.m

        def r32(self, off):
            return regs.r32(off)

        def w32(self, off, v):
            regs.w32(off, v)
    return H(None, -1)


def _osc(regs=None):
    """El handle del osciloscopio sobre esos registros, como `_mt`."""
    regs = Registros() if regs is None else regs

    class H(O.Osciloscope):
        m = regs.m

        def r32(self, off):
            return regs.r32(off)

        def w32(self, off, v):
            regs.w32(off, v)
    return H(None, -1)


# =============================================================================
# Osciloscopio
# =============================================================================

def test_ida_y_vuelta_de_todos_los_campos():
    """Lo escrito se relee igual. Es de lo que depende el anti-eco de la GUI:
    si el readback no coincide, el panel reescribe en un lazo."""
    r = _osc()
    valores = {campo: 1 for campo in O._CAMPOS}
    O.osciloscope_configure(r, **valores)
    leidos = O.osciloscope_get_config(r)
    for campo in O._CAMPOS:
        assert leidos[campo] == 1, campo


def test_el_umbral_conserva_el_signo():
    """14 bits en complemento a dos. Sin extender el signo, -500 se lee como
    +15884 y el control de la GUI salta al tope."""
    r = _osc()
    O.osciloscope_configure(r, thr_ch0=-500, thr_ch1=-8192)
    c = O.osciloscope_get_config(r)
    assert c['thr_ch0'] == -500
    assert c['thr_ch1'] == -8192          # el más negativo representable
    # Y en el registro está el patrón de 14 bits, no un entero negativo de 32.
    assert r.m[O.R_THR_CH0] == (-500 & 0x3FFF)


def test_los_campos_del_mismo_registro_no_se_pisan():
    """`avg_en_ch0` y `avg_en_ch1` comparten palabra: escribirlos de a uno haría
    que el segundo leyera lo que el primero acaba de cambiar."""
    r = _osc()
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
    r = _osc()
    O.osciloscope_configure(r, deb_len=0xFFFFFFFF, filt_bypass=0xFF)
    c = O.osciloscope_get_config(r)
    assert c['deb_len'] == 0xFFFFF        # 20 bits
    assert c['filt_bypass'] == 0xF        # 4 bits, uno por canal


def test_un_campo_inventado_falla_al_escribir():
    r = _osc()
    with pytest.raises(ValueError, match='campos desconocidos'):
        O.osciloscope_configure(r, umbral=100)


def test_la_decimacion_solo_acepta_los_valores_legales():
    """El validador está en el setter suelto, no en la tabla: la tabla escribe
    lo que le den. La GUI usa un combo con estos seis y por eso no puede
    mandar otro."""
    r = _osc()
    with pytest.raises(ValueError, match='no legal'):
        O.osciloscope_set_decim(r, 7)
    for d in O.DEC_LEGAL:
        O.osciloscope_set_decim(r, d)


# =============================================================================
# Multitrigger
# =============================================================================

def test_los_tres_campos_del_shield_comparten_palabra():
    """Layout: {dur[31:16], 3'h0, dst[12:8], 1'b0, src[6:0]}."""
    r = _mt()
    MT.multitrigger_configure(r, shield_src=3, shield_dst=3, shield_dur=7)
    assert r.m[MT.R_SHIELD_CFG] == 0x0007_0303
    c = MT.multitrigger_get_config(r)
    assert (c['shield_src'], c['shield_dst'], c['shield_dur']) == (3, 3, 7)


def test_el_veto_al_mca_va_en_los_bits_nuevos_del_shield():
    """Los campos crecieron EN SITIO sobre bits que estaban en cero: src[6:4] son
    la entrada externa (flancos y nivel) y dst[12] es el MCA. Un software viejo
    que escribe sólo los 4 bits bajos deja el veto apagado."""
    r = _mt()
    MT.multitrigger_configure(r, shield_src=MT.SRC_EXT_LVL, shield_dst=MT.DST_MCA,
                              shield_dur=0)
    assert r.m[MT.R_SHIELD_CFG] == (0x10 << 8) | 0x40
    c = MT.multitrigger_get_config(r)
    assert c['shield_src'] == 0x40 and c['shield_dst'] == 0x10
    # y los bits de canal siguen donde estaban
    MT.multitrigger_configure(r, shield_src=MT.SRC_CH0 | MT.SRC_EXT_P,
                              shield_dst=MT.DST_CH1 | MT.DST_MCA)
    assert r.m[MT.R_SHIELD_CFG] & 0xFF == 0x11
    assert (r.m[MT.R_SHIELD_CFG] >> 8) & 0xFF == 0x12


def test_los_bits_del_shield_son_sucesivos_y_con_nombre():
    for tabla in (MT.BITS_SHIELD_SRC, MT.BITS_SHIELD_DST):
        valores = [v for _n, v, _a in tabla]
        assert valores == [1 << i for i in range(len(valores))]
    assert MT.BITS_SHIELD_SRC[-1][0] == 'ext_lvl'
    assert MT.BITS_SHIELD_DST[-1][0] == 'mca'


def test_el_estado_publica_el_veto():
    """Bit 17 del runtime del shield: lo que el shield le manda al MCA AHORA."""
    r = _mt(Registros({MT.R_SHIELD_RUN: (1 << 17) | (1 << 16) | 5}))
    est = MT.multitrigger_get_status(r)
    assert est['mca_veto'] and est['shield_active']
    assert est['shield_runtime'] & 0xFFFF == 5
    est = MT.multitrigger_get_status(_mt(Registros({MT.R_SHIELD_RUN: 1 << 16})))
    assert est['shield_active'] and not est['mca_veto']


def test_un_registro_que_no_retiene_se_denuncia():
    """Con `assert` esto desaparecía bajo `python -O`, y una máscara que no
    latchea deja el scope sin disparar sin más síntoma que 'no llegan eventos'."""
    class Sordo(Registros):
        def w32(self, off, v):
            pass                          # acepta y no guarda

    with pytest.raises(RuntimeError, match='no retuvo lo escrito'):
        MT.multitrigger_configure(_mt(Sordo()), or_mask_ch0=0xFF)


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
# Disparo por pendiente (región propia, slot 3)
# =============================================================================

def _region(caps=MT.CAPS_HAS_SLOPE):
    """Una MtRegion sobre memoria común: retiene lo escrito, como un registro."""
    mem = bytearray(MT.MTRG_SIZE)
    mem[MT.R3_CAPS:MT.R3_CAPS + 4] = caps.to_bytes(4, 'little')
    return MT.MtRegion(mem, -1)


def test_las_fuentes_de_pendiente_caen_en_el_mismo_bit_de_mascara_y_snapshot():
    assert MT.BIT_SLOPE_P0 == 1 << 17 and MT.BIT_SLOPE_N3 == 1 << 24
    assert MT.decode_snap(MT.BIT_SLOPE_P0) == ['slope_p0']
    assert MT.decode_snap(MT.BIT_SLOPE_N1) == ['slope_n1']


def test_set_slope_escribe_el_layout_de_mt_cfg():
    r = _region()
    r.set_slope(1, L=4, G=7, thr=800, hyst=200)
    assert r.r32(MT.R3_SLOPE_CFG + 4) == (1 << 31) | (7 << 8) | 4
    assert r.r32(MT.R3_SLOPE_THR + 4) == 800
    assert r.r32(MT.R3_SLOPE_HYST + 4) == 200
    assert r.r32(MT.R3_SLOPE_CFG) == 0              # el canal 0 no se tocó
    assert r.get_slope(1) == {'en': True, 'L': 4, 'G': 7, 'thr': 800, 'hyst': 200}
    r.disable_slope(1)
    assert r.get_slope(1)['en'] is False


@pytest.mark.parametrize('kw', [
    dict(L=0, G=0, thr=10, hyst=1),
    dict(L=17, G=0, thr=10, hyst=1),
    dict(L=4, G=32, thr=10, hyst=1),
    dict(L=4, G=0, thr=MT.SLOPE_TMAX + 1, hyst=1),
    dict(L=4, G=0, thr=10, hyst=10),                # no re-arma en s=0
])
def test_set_slope_rechaza_lo_que_el_rtl_saturaria(kw):
    with pytest.raises(ValueError):
        _region().set_slope(0, **kw)


def test_set_slope_exige_el_bitstream_con_pendiente():
    with pytest.raises(RuntimeError, match='CAPS'):
        _region(caps=0).set_slope(0, L=4, G=7, thr=800, hyst=200)


def test_slope_pico_da_la_respuesta_del_trapezoidal():
    assert MT.slope_pico(4, 7, escalon=400) == 1600       # L·A
    assert MT.slope_pico(4, 7, pendiente=4) == 176        # L·(L+G)·m
    with pytest.raises(ValueError):
        MT.slope_pico(4, 7)


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
