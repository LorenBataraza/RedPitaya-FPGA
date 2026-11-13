#!/usr/bin/env python3
"""El osciloscopio en libmca hace lo mismo que la implementación Python.

La referencia es `API/ref_py/osciloscope2.py`, congelada. Cada caso corre la misma
operación sobre dos modelos de registros idénticos —uno detrás de la referencia, otro
detrás de libmca por el backend de callbacks— y exige, como
`test_libmca_multitrigger.py`:

  1. **las mismas escrituras, en el mismo orden y con el mismo valor**, también en los
     casos de error;
  2. **el mismo resultado**, con las mismas claves en el mismo orden y los mismos tipos;
  3. **la misma excepción**: el mismo tipo y, salvo los casos marcados, el mismo mensaje.

Las diferencias deliberadas son pocas, y cada una tiene su test bajo "Lo que difiere a
propósito". La lectura de la BRAM no tiene referencia: se compara contra un modelo de la
apertura con el alias del RTL, y contra la cuenta de `bench_reader_budget.py`.

La captura dejó de pasar por `rp` en la Parte 6 (`read_buffers`, `capture_window_np`,
`wait_*`, `capture_n_events`): eso tampoco tiene referencia en la PC, y se compara contra
la cuenta de librp (`datos_ref/calib_rp.npy`) y los bits de 0x000 que leía librp, en
"La captura, en C". El lazo por evento lo cubre `test_bram_source.py`.

    python -m pytest API/tests/test_libmca_osciloscope.py -q
"""

import ctypes
import inspect
import math
import os
import re
import struct
import sys
import threading
import time

import numpy as np
import pytest

from API import _libmca

if not _libmca.disponible():
    pytest.skip(f'libmca no está compilada ({_libmca.motivo()}): make -C libmca',
                allow_module_level=True)

import API.multitrigger as AM                                       # noqa: E402
import API.osciloscope as A                                         # noqa: E402
import API.ref_py.multitrigger2 as RM                               # noqa: E402
import API.ref_py.osciloscope2 as R                                 # noqa: E402

LIB = A._cargar()

SOFT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEADER = os.path.join(SOFT, 'libmca', 'include', 'osciloscope.h')
RTL = os.path.join(os.path.dirname(SOFT), 'modulos', 'osc', 'rtl', 'osc_cfg.sv')

SEMILLAS = range(8)
CANALES = (0, 1, False, True)
CUAL = (None, 0, 1, False, True)

# Lo que retiene cada registro según osc_cfg.sv. avg_en es un bit por byte.
RETIENE = {R.R_THR_CH0: 0x3FFF, R.R_THR_CH1: 0x3FFF, R.R_HYST_CH0: 0x3FFF,
           R.R_HYST_CH1: 0x3FFF, R.R_DLY_CH0: 0xFFFFFFFF, R.R_DLY_CH1: 0xFFFFFFFF,
           R.R_DEC_CH0: 0x1FFFF, R.R_DEC_CH1: 0x1FFFF, R.R_AVG_EN: 0x01010101,
           R.R_DEB_LEN: 0xFFFFF, R.R_FILT_BYPASS: 0xF, R.R_CALIB_OFF_CH0: 0x3FFF,
           R.R_CALIB_GAIN_CH0: 0xFFFF, R.R_CALIB_OFF_CH1: 0x3FFF,
           R.R_CALIB_GAIN_CH1: 0xFFFF}

# Los que cambian solos: el modelo no retiene lo que se les escribe.
SOLO_LECTURA = (R.R_CMD, R.R_SW_TRIG, R.R_WP_CUR_CH0, R.R_WP_CUR_CH1, R.R_WP_TRIG_CH0,
                R.R_WP_TRIG_CH1, R.R_WE_CNT_CH0, R.R_WE_CNT_CH1)


# =============================================================================
# El modelo y los dos handles
# =============================================================================

class Modelo:
    """Registros con la retención del RTL, que graban cada acceso, y la BRAM con su
    alias: `sys_addr[19:16]` elige el canal y los bits de abajo de RSZ se ignoran."""

    def __init__(self, semilla=1, rsz=14, n_ch=2, dw=14, magic=R.MAGIC_OSC, bram=None,
                 no_retiene=(), **fijos):
        rng = np.random.default_rng(semilla)
        self.reg = np.zeros(0x2000 // 4, dtype=np.uint32)
        for off, retiene in RETIENE.items():
            self.reg[off >> 2] = int(rng.integers(0, 2 ** 32)) & retiene
        for off in SOLO_LECTURA:
            self.reg[off >> 2] = int(rng.integers(0, 2 ** 32))
        self.reg[R.R_CANON_MAGIC >> 2] = magic
        self.reg[R.R_CANON_CAPS >> 2] = (rsz << 16) | (dw << 8) | n_ch
        for off, v in fijos.items():
            self.reg[int(off) >> 2] = v
        self.n_buf = 1 << rsz
        self.bram = bram
        self.no_retiene = set(no_retiene)
        self.escrituras = []
        self.lecturas = []

    def r32(self, off):
        self.lecturas.append(off)
        if off >= 0x10000:
            ch = (off >> 16) - 1
            return int(self.bram[ch][(off >> 2) & (self.n_buf - 1)])
        return int(self.reg[off >> 2])

    def w32(self, off, v):
        v = int(v & 0xFFFFFFFF)                 # como el w32 real: un float no pasa
        self.escrituras.append((off, v))
        if off in RETIENE and off not in self.no_retiene:
            self.reg[off >> 2] = v & RETIENE[off]


def handle(M, m):
    class H(M.Osciloscope):
        def r32(self, off):
            return m.r32(off)

        def w32(self, off, v):
            m.w32(off, v)
    return H(None, -1)


def correr(fn):
    try:
        return ('ok', fn())
    except Exception as e:                                     # noqa: BLE001
        return ('exc', type(e), str(e))


def iguales(a, b):
    if isinstance(a, dict):
        return (isinstance(b, dict) and list(a) == list(b)
                and all(iguales(a[k], b[k]) for k in a))
    if isinstance(a, (tuple, list)):
        return (type(a) is type(b) and len(a) == len(b)
                and all(iguales(x, y) for x, y in zip(a, b)))
    return type(a) is type(b) and a == b


def _igual_resultado(caso, rr, rc, mensaje):
    assert rr[0] == rc[0], f'{caso}: py dio {rr}, c dio {rc}'
    if rr[0] == 'ok':
        assert iguales(rr[1], rc[1]), (
            f'{caso}: resultado distinto\n  py: {rr[1]!r}\n  c:  {rc[1]!r}')
    else:
        assert issubclass(rc[1], rr[1]), f'{caso}: excepción {rc[1]} en vez de {rr[1]}'
        if mensaje:
            assert rc[2] == rr[2], f'{caso}: mensaje distinto\n  py: {rr[2]}\n  c:  {rc[2]}'


def comparar(caso, op, mensaje=True, **modelo):
    """Corre `op(módulo, h)` de los dos lados y compara. Devuelve lo que dio."""
    mr, mc = Modelo(**modelo), Modelo(**modelo)
    hr, hc = handle(R, mr), handle(A, mc)
    rr = correr(lambda: op(R, hr))
    rc = correr(lambda: op(A, hc))
    assert mc.escrituras == mr.escrituras, (
        f'{caso}: escrituras distintas\n  py: {mr.escrituras}\n  c:  {mc.escrituras}')
    _igual_resultado(caso, rr, rc, mensaje)
    assert (mc.reg == mr.reg).all(), f'{caso}: los registros quedaron distintos'
    hc.close()
    return rr, mr.escrituras


# =============================================================================
# Las tablas
# =============================================================================

def _regs_de_c():
    return {LIB.osciloscope_reg_info(i).contents.nombre.decode():
            LIB.osciloscope_reg_info(i).contents.offset
            for i in range(LIB.osciloscope_reg_count())}


def _r_de(modulo):
    # R_TRIG_SNAP y compañía se importan del multitrigger: no son de este bloque.
    ajenos = {n for n in dir(RM) if n.startswith('R_')} - {'R_CMD', 'R_TRIG_DIS_CLR'}
    return {n: getattr(modulo, n) for n in dir(modulo)
            if n.startswith('R_') and n not in ajenos and not n.startswith('RESET')}


def test_mapa_de_registros_es_el_de_python():
    assert _regs_de_c() == _r_de(A) == _r_de(R)
    assert not LIB.osciloscope_reg_info(LIB.osciloscope_reg_count())
    assert not LIB.osciloscope_reg_info(-1)


def _rtl():
    if not os.path.exists(RTL):
        pytest.skip(f'no está {RTL}: en un paquete de release no va el RTL')
    with open(RTL) as f:
        return f.read()


def test_el_mapa_es_el_que_decodifica_el_rtl():
    """C y Python pueden coincidir y estar los dos mal: el RTL es el que manda."""
    rtl = _rtl()
    leidos = {int(h, 16) for h in re.findall(r"20'h([0-9A-Fa-f]+)\s*:\s*rd_legacy", rtl)}
    regs = _regs_de_c()
    legacy = {v for n, v in regs.items() if not n.startswith('R_CANON')}
    # 0x094 es sólo de escritura: es un pulso.
    assert legacy - leidos == {R.R_TRIG_DIS_CLR}
    assert "(CANON_BASE+20'h000) : rd_canon = MAGIC" in rtl
    assert "(CANON_BASE+20'h004) : rd_canon = {10'h0, RSZ[5:0], 2'h0, DW[5:0], 4'h0, N_CH[3:0]}" in rtl
    assert "localparam [19:0] CANON_BASE = 20'h01000" in rtl
    assert f"parameter [31:0]  MAGIC          = 32'h{R.MAGIC_OSC:08X}" in rtl
    assert "sys_addr[19:0]==20'h094" in rtl


@pytest.mark.parametrize('off, ancho, nombre', [
    (R.R_THR_CH0, 'DW', 'set_tresh'), (R.R_THR_CH1, 'DW', 'set_tresh'),
    (R.R_DLY_CH0, '32', 'set_dly'), (R.R_DLY_CH1, '32', 'set_dly'),
    (R.R_DEC_CH0, '17', 'set_dec'), (R.R_DEC_CH1, '17', 'set_dec'),
    (R.R_HYST_CH0, 'DW', 'set_hyst'), (R.R_HYST_CH1, 'DW', 'set_hyst'),
    (R.R_CALIB_OFF_CH0, 'DW', 'set_calib_offset'), (R.R_CALIB_OFF_CH1, 'DW', 'set_calib_offset'),
    (R.R_CALIB_GAIN_CH0, '16', 'set_calib_gain'), (R.R_CALIB_GAIN_CH1, '16', 'set_calib_gain'),
])
def test_lo_que_retiene_el_modelo_es_lo_que_retiene_el_rtl(off, ancho, nombre):
    """El modelo de estos tests también sale del RTL: si no, probaría contra sí mismo."""
    rtl = _rtl()
    m = re.search(rf"sys_addr\[19:0\]==20'h{off:03X}\) {nombre}\[[^\]]*\]\s*<= sys_wdata\[{ancho}-1:0\]",
                  rtl)
    assert m, f'{off:#x} {nombre}'
    bits = 14 if ancho == 'DW' else int(ancho)
    assert RETIENE[off] == (1 << bits) - 1


def test_lo_que_retienen_los_globales_es_lo_del_rtl():
    rtl = _rtl()
    assert "sys_addr[19:0]==20'h090) set_deb_len                <= sys_wdata[20-1:0]" in rtl
    assert "sys_addr[19:0]==20'h098) set_filt_byp               <= sys_wdata[4-1:0]" in rtl
    assert "sys_addr[19:0]==20'h028) set_avg_en[c] <= sys_dats_all[c*8 + 0]" in rtl
    assert RETIENE[R.R_DEB_LEN] == 0xFFFFF and RETIENE[R.R_FILT_BYPASS] == 0xF
    assert RETIENE[R.R_AVG_EN] == 0x01010101


def test_la_apertura_del_rtl_es_la_del_modelo():
    rtl = _rtl()
    for i in range(1, 5):
        assert f"4'h{i}    : rd_bram = {{{{32-DW{{1'b0}}}}, bram_rd_dat_i[DW*{i}-1:DW*{i - 1}]}}" in rtl


def test_tabla_de_campos_es_campos():
    n = LIB.osciloscope_field_count()
    c = [LIB.osciloscope_field_info(i).contents for i in range(n)]
    assert [f.nombre.decode() for f in c] == list(A._CAMPOS)
    for f in c:
        nombre = f.nombre.decode()
        assert (f.offset, f.shift, f.mascara) == A._CAMPOS[nombre]
        assert bool(f.bandera) == (nombre in A._CON_SIGNO)
    assert not LIB.osciloscope_field_info(n)
    assert not LIB.osciloscope_field_info(-1)
    assert A._CAMPOS == R._CAMPOS and A._CON_SIGNO == R._CON_SIGNO


def test_constantes_del_header_son_las_de_python():
    with open(HEADER) as f:
        h = f.read()

    def define(nombre):
        m = re.search(rf'#define {nombre}\s+(0x[0-9A-Fa-f]+|\d+)', h)
        assert m, nombre
        return int(m.group(1), 0)

    for c, py in (('PHYS', A.SCOPE_PHYS), ('MAGIC', A.MAGIC_OSC),
                  ('CNT_PER_V', A.ADC_CNT_PER_V), ('RSZ_DEFECTO', A.RSZ_DEFECTO),
                  ('N_CH_DEFECTO', A.N_CH_DEFECTO), ('APERTURA_0', A.APERTURA_BRAM_0),
                  ('APERTURA_PASO', A.APERTURA_BRAM_PASO),
                  ('N_APERTURAS', A.APERTURAS_DECODIFICADAS)):
        assert define(f'OSCILOSCOPE_{c}') == py, c
    assert 'OSCILOSCOPE_AMBOS INT64_MIN' in h and A._AMBOS == -2 ** 63


def test_las_constantes_publicas_son_las_de_la_referencia():
    def publicas(m):
        return {n for n in dir(m) if n.isupper() and not n.startswith('_')}

    assert publicas(A) == publicas(R)
    for n in publicas(R):
        assert getattr(A, n) == getattr(R, n), n


def test_structs_del_mismo_tamanio():
    for tipo, py in (('osciloscope_geometria_t', A._Geometria),
                     ('osciloscope_calib_t', A._Calib), ('osciloscope_status_t', A._Status)):
        assert LIB.osciloscope_sizeof(tipo.encode()) == ctypes.sizeof(py), tipo
    assert LIB.osciloscope_sizeof(b'no_existe') == 0
    assert LIB.osciloscope_sizeof(None) == 0


class _Libreria:
    """La libmca de verdad, con lo que se le pise."""

    def __init__(self, **pisado):
        self._pisado = pisado

    def __getattr__(self, nombre):
        if nombre in self._pisado:
            return self._pisado[nombre]
        return getattr(LIB, nombre)


def test_un_so_viejo_lo_dice_y_no_da_un_attributeerror(monkeypatch):
    class Vieja:
        """Una libmca anterior a este bloque."""

    monkeypatch.setattr(A, '_lib', None)
    monkeypatch.setattr(A._libmca, 'cargar', Vieja)
    with pytest.raises(OSError, match='otra versión'):
        A._cargar()


def test_un_so_con_otra_tabla_lo_dice(monkeypatch):
    monkeypatch.setattr(A, '_lib', None)
    falsa = _Libreria(osciloscope_field_count=lambda: 3)
    monkeypatch.setattr(A._libmca, 'cargar', lambda: falsa)
    with pytest.raises(OSError, match='3 campos'):
        A._cargar()


@pytest.mark.parametrize('tipo', ['osciloscope_geometria_t', 'osciloscope_calib_t',
                                  'osciloscope_status_t'])
def test_un_struct_de_otro_tamanio_lo_dice(monkeypatch, tipo):
    def tamanio(t):
        return 1 if t == tipo.encode() else LIB.osciloscope_sizeof(t)

    monkeypatch.setattr(A, '_lib', None)
    falsa = _Libreria(osciloscope_sizeof=tamanio)
    monkeypatch.setattr(A._libmca, 'cargar', lambda: falsa)
    with pytest.raises(OSError, match=tipo):
        A._cargar()


# =============================================================================
# La superficie
# =============================================================================

def _firma_sin_impl(f):
    return [p for n, p in inspect.signature(f).parameters.items() if n != 'impl']


SOLO_EN_C = {'osciloscope_read_bram', 'osciloscope_read_cal', 'osciloscope_calibrar'}

# La captura dejó `rp` (Parte 6): lo que antes era estático lee por el handle.
CON_EL_HANDLE = {'osciloscope_wait_fill': '(osc, timeout_ms=2000)',
                 'osciloscope_wait_triggered': '(osc, timeout_ms=2000)'}
METODOS_NUEVOS = {
    'capture_window_np': '(self, channels=None, pre=0, post=None, at_trigger=True, '
                         'n_buf=None)',
    'read_buffers': '(self, n_buf=None)',
    'wait_fill': '(self, timeout_ms=2000)',
    'wait_triggered': '(self, timeout_ms=2000)'}


def test_las_funciones_son_las_mismas_con_las_mismas_firmas():
    def funciones(m):
        return {n for n in dir(m) if n.startswith('osciloscope_')} - SOLO_EN_C

    assert funciones(A) == funciones(R)
    for n in funciones(R) - set(CON_EL_HANDLE):
        assert _firma_sin_impl(getattr(A, n)) == _firma_sin_impl(getattr(R, n)), n
    for n, firma in CON_EL_HANDLE.items():
        assert str(inspect.signature(getattr(A, n))) == firma, n
    for n in ('open', 'acq_base', 'set_raw_delay', 'verify_bitstream', 'capture_n_events',
              'acq_capture_sw', 'reload_bitstream'):
        assert _firma_sin_impl(getattr(A.Osciloscope, n)) == _firma_sin_impl(getattr(R.Osciloscope, n)), n
    for n, firma in METODOS_NUEVOS.items():
        assert str(inspect.signature(getattr(A.Osciloscope, n))) == firma, n


def test_los_metodos_son_los_mismos():
    def metodos(c):
        return {n for n in dir(c) if not n.startswith('_')}

    assert metodos(R.Osciloscope) <= metodos(A.Osciloscope)
    # `impl` lo tienen los handles en C; lo demás es la calibración de librp.
    assert metodos(A.Osciloscope) - metodos(R.Osciloscope) == {
        'impl', 'calibracion', 'set_calibracion', 'read_cal'}


def test_las_funciones_de_hardware_estan_registradas_en_su_modulo():
    from API._despacho import API_REGISTRADA
    nombres = {n for n, e in API_REGISTRADA.items() if e.modulo == 'API.osciloscope'}
    assert nombres == {n for n in dir(A) if n.startswith('osciloscope_')} - {
        'osciloscope_open', 'osciloscope_close', 'osciloscope_wait_triggered',
        'osciloscope_wait_fill', 'osciloscope_read_buffers', 'osciloscope_read_window',
        'osciloscope_read_events', 'osciloscope_read_capture_sw', 'osciloscope_calibrar'}


# =============================================================================
# Lecturas
# =============================================================================

GETTERS = ('thr', 'decim', 'delay', 'hysteresis', 'calibration', 'wp_cur', 'wp_trig', 'we_cnt')
GLOBALES = ('avg', 'deb_len', 'filter_bypass', 'adc_state', 'trg_state', 'config', 'status')


@pytest.mark.parametrize('semilla', SEMILLAS)
@pytest.mark.parametrize('que', GETTERS)
@pytest.mark.parametrize('ch', CANALES)
def test_lecturas_por_canal(semilla, que, ch):
    nombre = f'osciloscope_get_{que}'
    comparar(nombre, lambda M, h: getattr(M, nombre)(h, ch), semilla=semilla)
    comparar(nombre, lambda M, h: getattr(M, nombre)(h, ch=ch), semilla=semilla)


@pytest.mark.parametrize('que', GETTERS)
def test_el_canal_por_defecto_es_el_0(que):
    nombre = f'osciloscope_get_{que}'
    comparar(nombre, lambda M, h: getattr(M, nombre)(h))


@pytest.mark.parametrize('semilla', SEMILLAS)
@pytest.mark.parametrize('que', GLOBALES)
def test_lecturas_globales(semilla, que):
    nombre = f'osciloscope_get_{que}'
    comparar(nombre, lambda M, h: getattr(M, nombre)(h), semilla=semilla)


@pytest.mark.parametrize('crudo', [0, 1, 0x1FFF, 0x2000, 0x3FFF, 0x4000, 0xFFFFFFFF])
def test_el_umbral_extiende_el_signo(crudo):
    r, _ = comparar('get_thr', lambda M, h: M.osciloscope_get_thr(h),
                    **{str(R.R_THR_CH0): crudo})
    assert -1.0 <= r[1] < 1.0


@pytest.mark.parametrize('crudo', [0x4000, 0xFFFFFFFF, 0x80000000])
def test_la_histeresis_no_recorta_lo_que_lee(crudo):
    comparar('get_hysteresis', lambda M, h: M.osciloscope_get_hysteresis(h),
             **{str(R.R_HYST_CH0): crudo})


def test_los_get_no_escriben_y_config_lee_cada_campo():
    m = Modelo()
    h = handle(A, m)
    c = A.osciloscope_get_config(h)
    assert m.escrituras == []
    assert list(c) == list(A._CAMPOS)
    assert set(m.lecturas) == {off for off, _, _ in A._CAMPOS.values()}
    h.close()


# =============================================================================
# Escrituras
# =============================================================================

VOLTS = [0, 0.0, -0.0, 0.5, -0.5, 1.0, -1.0, 1, -1, True, False, 2.0, -2.0, 3.7, -3.7,
         1 / 8192, -1 / 8192, 1e-12, -1e-12, 1e-300, 1e6, -1e6, 1e15, -1e15,
         1e19, -1e19, 2.0 ** 52, 2.0 ** 53, -2.0 ** 53, 2.0 ** 63, -2.0 ** 63,
         2.0 ** 66, -2.0 ** 66, 1e300, -1e300, 2 ** 60, -2 ** 60,
         # Desde 2^63 cuentas no entran en un int64, y todavía quedan bits bajos.
         2.0 ** 50 + 0.25, -(2.0 ** 50 + 0.25), 2.0 ** 51 + 0.5, 2.0 ** 52 + 1,
         # El bit 31 de las cuentas, que es de la histéresis.
         2.0 ** 18 + 0.125, -(2.0 ** 18 + 0.125), 2.0 ** 19 - 0.25, 2.0 ** 30 + 0.25,
         np.float64(0.25), np.float32(0.25), np.int32(1), float('nan')]
# Exactamente a mitad de camino entre dos cuentas: Python redondea al par.
EMPATES = [(k + 0.5) / 8192 for k in range(-6, 6)] + [8191.5 / 8192, -8192.5 / 8192]
VOLTS_AZAR = [float(v) for v in np.random.default_rng(3).uniform(-3, 3, 40)]


@pytest.mark.parametrize('v', VOLTS + EMPATES + VOLTS_AZAR)
@pytest.mark.parametrize('ch', (None, 0, 1))
def test_set_thr(v, ch):
    comparar('set_thr', lambda M, h: M.osciloscope_set_thr(h, v, ch))


@pytest.mark.parametrize('v', VOLTS + EMPATES + VOLTS_AZAR)
@pytest.mark.parametrize('ch', (None, 0, 1))
def test_set_hysteresis(v, ch):
    comparar('set_hysteresis', lambda M, h: M.osciloscope_set_hysteresis(h, v, ch))


@pytest.mark.parametrize('v', [0, 1 / 8192 / 2, 1 / 8192, 0.99 / 8192, 1.99 / 8192, -1.5 / 8192])
def test_la_histeresis_nunca_es_cero(v):
    _, esc = comparar('set_hysteresis', lambda M, h: M.osciloscope_set_hysteresis(h, v, 0))
    assert esc[0][1] >= 1


def test_la_histeresis_trunca_antes_de_los_bits_bajos():
    # 2^32 cuentas: `max(1, c)` deja c, y w32 se queda con los 32 bits bajos, que son 0.
    _, esc = comparar('set_hysteresis', lambda M, h: M.osciloscope_set_hysteresis(h, 2.0 ** 19, 0))
    assert esc == [(R.R_HYST_CH0, 0)]


@pytest.mark.parametrize('malo', [None, 'x', [], {}, b'x', (1,)])
@pytest.mark.parametrize('fn', ['osciloscope_set_thr', 'osciloscope_set_hysteresis'])
def test_un_volts_que_no_es_numero(fn, malo):
    # El mensaje de la referencia es el de `v * 8192` o de `round`: da igual cuál.
    comparar(fn, lambda M, h: getattr(M, fn)(h, malo), mensaje=False)


def test_el_string_de_un_numero_no_pasa():
    # `float('0.5')` lo aceptaría; `'0.5' * 8192` y `round` no.
    comparar('set_thr', lambda M, h: M.osciloscope_set_thr(h, '0.5'), mensaje=False)


@pytest.mark.parametrize('v', list(R.DEC_LEGAL) + [True, np.int64(8), 0, 2, 7, -1, 9, 65535,
                                                   65537, 2 ** 40, 7.5, None, 'x'])
@pytest.mark.parametrize('ch', (None, 0, 1))
def test_set_decim(v, ch):
    comparar('set_decim', lambda M, h: M.osciloscope_set_decim(h, v, ch))


@pytest.mark.parametrize('v', [0, 1, 1000, 0xFFFFFFFF, 0x1FFFFFFFF, -1, -2 ** 40, 2 ** 70,
                               True, np.uint32(5), np.int64(-1), 1.5, None, 'x'])
@pytest.mark.parametrize('ch', (None, 0, 1))
def test_set_delay(v, ch):
    comparar('set_delay', lambda M, h: M.osciloscope_set_delay(h, v, ch), mensaje=False)


@pytest.mark.parametrize('v', [0, 1, 2, -1, True, False, None, 'x', '', [], [0], 0.0, 0.5])
def test_set_avg_toma_la_verdad(v):
    _, esc = comparar('set_avg', lambda M, h: M.osciloscope_set_avg(h, v))
    assert esc == [(R.R_AVG_EN, 1 if v else 0)]


def test_set_avg_de_c_toma_la_verdad():
    # El binding ya le pasa 0 o 1: esto es lo que ve quien llama desde C.
    m = Modelo()
    h = handle(A, m)
    for en, esperado in ((5, 1), (-1, 1), (0, 0), (2, 1)):
        assert LIB.osciloscope_set_avg(h._c, en) == 0
        assert m.escrituras[-1] == (R.R_AVG_EN, esperado)
    h.close()


@pytest.mark.parametrize('fn', ['osciloscope_set_deb_len', 'osciloscope_set_filter_bypass'])
@pytest.mark.parametrize('v', [0, 1, 0xFFFFF, 0xFFFFFFFF, -1, 2 ** 40, True, 1.5, None, 'x'])
def test_set_crudos(fn, v):
    comparar(fn, lambda M, h: getattr(M, fn)(h, v), mensaje=False)


@pytest.mark.parametrize('kw', [
    {}, dict(offset=5), dict(gain=0x8000), dict(offset=5, gain=7), dict(offset=-1),
    dict(offset=0, gain=0), dict(gain=2 ** 40), dict(ch=1), dict(offset=5, ch=1),
    dict(gain=7, ch=1), dict(offset=5, gain=7, ch=1), dict(offset=5, gain=7, ch=True),
    dict(offset=5, gain=None), dict(offset=None, gain=7),
    # El offset ya está escrito cuando la ganancia falla, en las dos.
    dict(offset=5, gain=1.5), dict(offset=1.5, gain=7), dict(offset='x'),
])
def test_set_calibration(kw):
    comparar('set_calibration', lambda M, h: M.osciloscope_set_calibration(h, **kw),
             mensaje=False)


def test_sin_ch_escribe_los_dos_el_0_primero():
    for fn, v, regs in (('set_thr', 0.5, (R.R_THR_CH0, R.R_THR_CH1)),
                        ('set_decim', 8, (R.R_DEC_CH0, R.R_DEC_CH1)),
                        ('set_delay', 3, (R.R_DLY_CH0, R.R_DLY_CH1)),
                        ('set_hysteresis', 0.5, (R.R_HYST_CH0, R.R_HYST_CH1))):
        _, esc = comparar(fn, lambda M, h: getattr(M, f'osciloscope_{fn}')(h, v))
        assert [o for o, _ in esc] == list(regs), fn


# =============================================================================
# Configuración en bloque, comandos y secuencias
# =============================================================================

@pytest.mark.parametrize('semilla', SEMILLAS)
def test_configure_de_a_un_campo(semilla):
    for campo in A._CAMPOS:
        for v in (0, 1, -1, 0x7F, 0xFFFFFFFF, 2 ** 40, -500, True, 3.9, '12'):
            comparar(campo, lambda M, h: M.osciloscope_configure(h, **{campo: v}),
                     semilla=semilla)


@pytest.mark.parametrize('semilla', SEMILLAS)
def test_configure_de_varios_en_cualquier_orden(semilla):
    rng = np.random.default_rng(semilla)
    nombres = list(A._CAMPOS)
    for _ in range(30):
        elegidos = list(rng.choice(nombres, size=int(rng.integers(1, len(nombres) + 1)),
                                   replace=False))
        campos = {str(c): int(rng.integers(-2 ** 33, 2 ** 33)) for c in elegidos}
        comparar('configure', lambda M, h: M.osciloscope_configure(h, **campos),
                 semilla=semilla)


def test_configure_no_exige_que_el_registro_retenga():
    # A diferencia de multitrigger_configure: la referencia nunca releyó acá.
    comparar('configure', lambda M, h: M.osciloscope_configure(h, thr_ch0=5),
             no_retiene=(R.R_THR_CH0,))


def test_los_que_comparten_palabra_se_escriben_una_vez():
    _, esc = comparar('configure', lambda M, h: M.osciloscope_configure(
        h, avg_en_ch1=1, thr_ch0=2, avg_en_ch0=1))
    assert [o for o, _ in esc] == [R.R_AVG_EN, R.R_THR_CH0], 'en el orden en que aparecen'


def test_configure_vacio_ni_lee_ni_escribe():
    m = Modelo()
    h = handle(A, m)
    A.osciloscope_configure(h)
    assert m.escrituras == [] and m.lecturas == []
    h.close()


@pytest.mark.parametrize('kw', [dict(umbral=1), dict(thr_ch0=1, umbral=1), dict(b=1, a=2),
                                dict(thr_ch0=None), dict(thr_ch0='x'), dict(thr_ch0=1, dec_ch0=[]),
                                dict(thr_ch0=float('nan'))])
def test_configure_lo_que_no_vale_no_escribe_nada(kw):
    _, esc = comparar('configure', lambda M, h: M.osciloscope_configure(h, **kw))
    assert esc == []


def test_configure_rechaza_un_indice_fuera_de_tabla_sin_escribir():
    m = Modelo()
    h = handle(A, m)
    ind, val = (ctypes.c_int32 * 2)(0, len(A._CAMPOS)), (ctypes.c_uint32 * 2)(1, 2)
    assert LIB.osciloscope_configure(h._c, ind, val, 2) == _libmca.MCA_EINVAL
    assert LIB.osciloscope_configure(h._c, ind, None, 2) == _libmca.MCA_EINVAL
    assert LIB.osciloscope_configure(h._c, ind, val, -1) == _libmca.MCA_EINVAL
    assert m.escrituras == []
    h.close()


def test_get_config_con_otro_largo_es_un_error():
    h = handle(A, Modelo())
    v = (ctypes.c_int64 * 3)()
    assert LIB.osciloscope_get_config(h._c, v, 3) == _libmca.MCA_EINVAL
    h.close()


def test_reset_y_sw_trigger():
    _, esc = comparar('reset', lambda M, h: M.osciloscope_reset(h))
    assert esc == [(R.R_CMD, 0x202), (R.R_TRIG_DIS_CLR, 0x101)]
    _, esc = comparar('sw', lambda M, h: M.osciloscope_sw_trigger(h))
    assert esc == [(R.R_SW_TRIG, 1)]


@pytest.mark.parametrize('thr', [0, 0.5, -0.5, 3.7, 0.5 / 8192, 1.5 / 8192, 1e19, 1e300])
@pytest.mark.parametrize('delay', [0, 1, 12, 0xFFFFFFFF, -1])
@pytest.mark.parametrize('decim', R.DEC_LEGAL)
def test_acq_base(thr, delay, decim):
    comparar('acq_base', lambda M, h: h.acq_base(thr=thr, delay=delay, decim=decim))


def test_acq_base_por_defecto():
    _, esc = comparar('acq_base', lambda M, h: h.acq_base())
    assert esc == [(0x000, 0x202), (0x094, 0x101), (0x014, 1), (0x114, 1), (0x008, 4096),
                   (0x00C, 4096), (0x010, 0), (0x110, 0)]


@pytest.mark.parametrize('decim', [0, 7, -1, 2 ** 40, 7.5, None, 'x'])
def test_acq_base_con_decim_ilegal_no_escribe(decim):
    _, esc = comparar('acq_base', lambda M, h: h.acq_base(decim=decim))
    assert esc == []


@pytest.mark.parametrize('delay', [1, 0, 9, 0xFFFFFFFF, -1, True, 1.5, None])
def test_set_raw_delay(delay):
    comparar('set_raw_delay', lambda M, h: h.set_raw_delay(delay), mensaje=False)


def test_set_raw_delay_por_defecto():
    _, esc = comparar('set_raw_delay', lambda M, h: h.set_raw_delay())
    assert esc == [(R.R_DLY_CH0, 1), (R.R_DLY_CH1, 1)]


@pytest.mark.parametrize('off, v', [(0x10, 3), (0x10, -1), (0x10, 2 ** 40), (0x10, True),
                                    (0x10, 1.5), (0x10, None)])
def test_w32(off, v):
    """Un float no pasa: `v & 0xFFFFFFFF` tampoco lo dejaba, y truncarlo escribiría otro
    valor sin avisar."""
    comparar('w32', lambda M, h: h.w32(off, v), mensaje=False)


# =============================================================================
# La geometría
# =============================================================================

@pytest.mark.parametrize('rsz', [1, 2, 10, 13, 14, 20, 24])
@pytest.mark.parametrize('n_ch', [1, 2, 3, 4])
@pytest.mark.parametrize('dw', [10, 14, 16])
def test_geometria_descubierta(rsz, n_ch, dw):
    comparar('geometria', lambda M, h: h.geometria(), rsz=rsz, n_ch=n_ch, dw=dw)
    comparar('n_buf', lambda M, h: h.n_buf, rsz=rsz, n_ch=n_ch, dw=dw)


def test_geometria_por_defecto_sin_el_magic():
    r, _ = comparar('geometria', lambda M, h: h.geometria(), magic=0)
    assert r[1]['descubierta'] is False and r[1]['n_buf'] == 16384


@pytest.mark.parametrize('rsz, n_ch', [(0, 2), (25, 2), (63, 2), (14, 0), (14, 5), (14, 15),
                                       (0, 0)])
def test_geometria_imposible_mismo_error(rsz, n_ch):
    comparar('geometria', lambda M, h: h.geometria(), rsz=rsz, n_ch=n_ch)


def test_la_cuenta_de_c_es_geometria_scope():
    """Los dos lados la necesitan: Python para las constantes de módulo, que existen sin
    libmca, y C para abrir. Se comparan todas."""
    for rsz in range(-1, 27):
        for n_ch in range(-1, 7):
            g = A._Geometria()
            rc = LIB.osciloscope_geometria_de(rsz, n_ch, ctypes.byref(g))
            py = correr(lambda: A.geometria_scope(rsz, n_ch))
            if py[0] == 'exc':
                assert rc == _libmca.MCA_EINVAL
                assert LIB.osciloscope_last_error(None).decode() == py[2]
                continue
            assert rc == 0
            e = py[1]
            assert (g.rsz, g.n_ch, g.n_buf, g.size) == (e['rsz'], e['n_ch'], e['n_buf'], e['size'])
            assert tuple(g.aperturas[:g.n_ch]) == e['aperturas']
            assert not any(g.aperturas[g.n_ch:])
    assert LIB.osciloscope_geometria_de(14, 2, None) == _libmca.MCA_EINVAL


def test_la_geometria_se_lee_una_sola_vez_y_la_guarda_c():
    m = Modelo()
    h = handle(A, m)
    h.geometria()
    h.geometria()
    g = A._Geometria()
    assert LIB.osciloscope_get_geometria(h._c, ctypes.byref(g)) == 0
    assert m.lecturas == [R.R_CANON_MAGIC, R.R_CANON_CAPS]
    h.close()


@pytest.mark.parametrize('off, v', [(0x10, 3), (0x10, -1), (0x10, 2 ** 40), (0x10, True),
                                    (0x10, 1.5), (0x10, None), (0x10, np.int64(7))])
def test_w32_de_verdad(off, v):
    """Sobre un buffer los accesos son los del handle, no los de una subclase."""
    mr, mc = bytearray(R.SCOPE_SIZE), bytearray(R.SCOPE_SIZE)
    hr, hc = R.Osciloscope(mr, -1), A.Osciloscope(mc, -1)
    _igual_resultado('w32', correr(lambda: hr.w32(off, v)), correr(lambda: hc.w32(off, v)), False)
    assert mc == mr
    hc.close()


def test_el_constructor_no_lee_nada():
    m = Modelo()
    h = handle(A, m)
    assert m.lecturas == [] and m.escrituras == []
    h.close()


# =============================================================================
# La BRAM
# =============================================================================

def _bram(rsz=14, n_ch=2, dw=14, semilla=5):
    """Lo que devuelve la apertura: dw bits sin extender, en la palabra de 32."""
    rng = np.random.default_rng(semilla)
    return [rng.integers(0, 1 << dw, 1 << rsz, dtype=np.uint32) for _ in range(n_ch)]


def _con_signo(raw, dw=14):
    """La cuenta de `read_bram_view`, en API/bench/bench_reader_budget.py."""
    s = (raw & ((1 << dw) - 1)).astype(np.int32)
    s -= (s & (1 << (dw - 1))) << 1
    return s.astype(np.int16)


def _esperado(bram, ch, start, n, n_buf, dw=14):
    idx = (np.arange(n, dtype=np.int64) + start) % n_buf
    return _con_signo(bram[ch][idx], dw)


@pytest.mark.parametrize('rsz', [10, 13, 14])
@pytest.mark.parametrize('ch', [0, 1])
@pytest.mark.parametrize('start, n', [(0, 32), (100, 300), (-8, 32), (-1, 2), (0, 0), (5, 1)])
def test_read_bram_es_la_ventana_del_anillo(rsz, ch, start, n):
    bram = _bram(rsz)
    n_buf = 1 << rsz
    h = handle(A, Modelo(rsz=rsz, bram=bram))
    d = A.osciloscope_read_bram(h, ch, start, n)
    assert d.dtype == np.int16 and len(d) == n
    assert (d == _esperado(bram, ch, start, n, n_buf)).all()
    h.close()


@pytest.mark.parametrize('n_buf_menos', [1, 8, 100, 255, 256, 257, 1000])
def test_read_bram_da_la_vuelta_en_el_final(n_buf_menos):
    bram = _bram()
    h = handle(A, Modelo(bram=bram))
    start = (1 << 14) - n_buf_menos
    d = A.osciloscope_read_bram(h, 0, start, 2000)
    assert (d == _esperado(bram, 0, start, 2000, 1 << 14)).all()
    h.close()


def test_read_bram_lee_el_anillo_entero():
    bram = _bram(13)
    h = handle(A, Modelo(rsz=13, bram=bram))
    for start in (0, 1, 4096, 8191):
        d = A.osciloscope_read_bram(h, 1, start, 8192)
        assert (d == _esperado(bram, 1, start, 8192, 8192)).all()
    h.close()


def test_read_bram_con_start_grande_o_negativo_es_modulo():
    bram = _bram()
    h = handle(A, Modelo(bram=bram))
    ref = A.osciloscope_read_bram(h, 0, 7, 16)
    for start in (7 + (1 << 14), 7 - (1 << 14), 7 + (5 << 14), 7 - (5 << 14), 7 + 2 ** 40):
        assert (A.osciloscope_read_bram(h, 0, start, 16) == ref).all(), start
    h.close()


def test_read_bram_extiende_el_signo_de_todas_las_cuentas():
    cuentas = np.arange(1 << 14, dtype=np.uint32)
    h = handle(A, Modelo(bram=[cuentas, cuentas]))
    d = A.osciloscope_read_bram(h, 0, 0, 1 << 14)
    assert d[0] == 0 and d[8191] == 8191 and d[8192] == -8192 and d[16383] == -1
    assert (d == _con_signo(cuentas)).all()
    h.close()


def test_read_bram_ignora_los_bits_de_arriba_de_la_palabra():
    h = handle(A, Modelo(bram=[np.array([0xFFFFC001] * (1 << 14), dtype=np.uint32)] * 2))
    assert A.osciloscope_read_bram(h, 0, 0, 1)[0] == 1
    h.close()


@pytest.mark.parametrize('dw', [1, 8, 10, 12, 14, 15, 16])
def test_read_bram_usa_el_dw_del_bitstream(dw):
    bram = _bram(dw=dw)
    h = handle(A, Modelo(dw=dw, bram=bram))
    d = A.osciloscope_read_bram(h, 0, 0, 1000)
    assert (d == _esperado(bram, 0, 0, 1000, 1 << 14, dw)).all()
    h.close()


@pytest.mark.parametrize('dw', [0, 17, 32, 63])
def test_read_bram_con_un_dw_que_no_entra_es_un_error(dw):
    h = handle(A, Modelo(dw=dw, bram=_bram()))
    with pytest.raises(_libmca.LibMCAError, match='bits'):
        A.osciloscope_read_bram(h, 0, 0, 4)
    h.close()


def test_read_bram_lee_de_a_una_palabra_en_orden():
    m = Modelo(bram=_bram())
    h = handle(A, m)
    h.geometria()
    m.lecturas.clear()
    A.osciloscope_read_bram(h, 1, (1 << 14) - 2, 5)
    a = A.APERTURA_BRAM_0 + A.APERTURA_BRAM_PASO
    assert m.lecturas == [a + 4 * 16382, a + 4 * 16383, a, a + 4, a + 8]
    assert m.escrituras == []
    h.close()


@pytest.mark.parametrize('n_ch, ch', [(2, 2), (2, 3), (2, -1), (1, 1), (4, 4)])
def test_read_bram_rechaza_un_canal_que_no_construyo_el_bitstream(n_ch, ch):
    m = Modelo(n_ch=n_ch, bram=_bram(n_ch=4))
    h = handle(A, m)
    h.geometria()
    m.lecturas.clear()
    with pytest.raises(ValueError, match=rf'canal {ch} fuera de 0\.\.{n_ch - 1}'):
        A.osciloscope_read_bram(h, ch, 0, 4)
    assert m.lecturas == []
    h.close()


@pytest.mark.parametrize('ch', [2, 3])
def test_read_bram_con_cuatro_canales(ch):
    bram = _bram(n_ch=4)
    h = handle(A, Modelo(n_ch=4, bram=bram))
    assert (A.osciloscope_read_bram(h, ch, 3, 40) == _esperado(bram, ch, 3, 40, 1 << 14)).all()
    h.close()


@pytest.mark.parametrize('rsz', [10, 13, 14])
def test_read_bram_rechaza_mas_que_el_anillo_y_no_lo_repite(rsz):
    """Por el alias, el hardware devolvería el buffer repetido sin avisar."""
    m = Modelo(rsz=rsz, bram=_bram(rsz))
    h = handle(A, m)
    h.geometria()
    m.lecturas.clear()
    with pytest.raises(ValueError, match=f'ventana de {(1 << rsz) + 1} muestras sobre un '
                                         f'anillo de {1 << rsz}.*repetido'):
        A.osciloscope_read_bram(h, 0, 0, (1 << rsz) + 1)
    with pytest.raises(ValueError, match='repetido'):
        A.osciloscope_read_bram(h, 0, 0, -1)
    assert m.lecturas == []
    h.close()


def test_el_mensaje_de_mas_que_el_anillo_es_el_de_capture_window_np():
    h = handle(A, Modelo(rsz=13, bram=_bram(13)))
    with pytest.raises(ValueError) as c:
        A.osciloscope_read_bram(h, 0, 0, 12288)
    with pytest.raises(ValueError) as py:
        R.Osciloscope.capture_window_np(pre=4096, post=8192, n_buf=8192)
    assert str(c.value) == str(py.value)
    h.close()


def test_read_bram_con_un_pedido_enorme_no_reserva_memoria():
    h = handle(A, Modelo(bram=_bram()))
    with pytest.raises(ValueError, match='repetido'):
        A.osciloscope_read_bram(h, 0, 0, 2 ** 60)
    h.close()


def test_read_bram_sin_destino_es_un_error():
    h = handle(A, Modelo(bram=_bram()))
    assert LIB.osciloscope_read_bram(h._c, 0, 0, 4, None) == _libmca.MCA_EINVAL
    assert LIB.osciloscope_read_bram(h._c, 0, 0, 0, None) == 0
    h.close()


def test_read_bram_no_pisa_mas_alla_de_la_ventana():
    bram = _bram()
    h = handle(A, Modelo(bram=bram))
    dst = np.full(1000, 12345, dtype=np.int16)
    p = dst[10:].ctypes.data_as(A._PS)
    assert LIB.osciloscope_read_bram(h._c, 0, 16380, 900, p) == 0
    assert (dst[:10] == 12345).all() and (dst[910:] == 12345).all()
    assert (dst[10:910] == _esperado(bram, 0, 16380, 900, 1 << 14)).all()
    h.close()


def test_read_bram_sin_el_mapa_canonico_usa_la_geometria_por_defecto():
    bram = _bram()
    h = handle(A, Modelo(magic=0, rsz=10, bram=bram))
    d = A.osciloscope_read_bram(h, 0, 16380, 8)      # rsz=14 por defecto, n_buf=16384
    assert len(d) == 8
    h.close()


def test_read_bram_propaga_el_error_del_callback():
    class Rota(Modelo):
        def r32(self, off):
            if off >= 0x10000:
                raise OSError('el bus se cayó')
            return super().r32(off)

    h = handle(A, Rota())
    with pytest.raises(OSError, match='el bus se cayó'):
        A.osciloscope_read_bram(h, 0, 0, 4)
    h.close()


def test_read_bram_no_existe_en_la_referencia():
    assert not hasattr(R, 'osciloscope_read_bram')
    h = R.Osciloscope(bytearray(R.SCOPE_SIZE), -1)
    h._via = 'py'
    with pytest.raises(NotImplementedError, match='sólo en libmca'):
        A.osciloscope_read_bram(h, 0, 0, 4)


# =============================================================================
# Lo que difiere a propósito
# =============================================================================

@pytest.mark.parametrize('ch', [2, 3, -1, -2, 2 ** 40])
@pytest.mark.parametrize('que', GETTERS)
def test_un_canal_invalido_al_leer_es_un_error(que, ch):
    """La referencia usa `off1 if ch else off0`: el canal 2 lee el 1, sin avisar."""
    h = handle(A, Modelo())
    with pytest.raises(ValueError, match=f'canal {ch} fuera de 0..1'):
        getattr(A, f'osciloscope_get_{que}')(h, ch)
    h.close()


@pytest.mark.parametrize('ch', [2, 3, -1, -2, 2 ** 40])
@pytest.mark.parametrize('op', [
    lambda h, ch: A.osciloscope_set_thr(h, 0.5, ch),
    lambda h, ch: A.osciloscope_set_decim(h, 8, ch),
    lambda h, ch: A.osciloscope_set_delay(h, 3, ch),
    lambda h, ch: A.osciloscope_set_hysteresis(h, 0.5, ch),
    lambda h, ch: A.osciloscope_set_calibration(h, offset=1, ch=ch),
    lambda h, ch: A.osciloscope_set_calibration(h, gain=1, ch=ch),
])
def test_un_canal_invalido_al_escribir_no_escribe(op, ch):
    m = Modelo()
    h = handle(A, m)
    with pytest.raises(ValueError, match=f'canal {ch} fuera de 0..1'):
        op(h, ch)
    assert m.escrituras == []
    h.close()


def test_sin_argumentos_la_calibracion_no_mira_el_canal():
    # No hay nada que escribir: como en la referencia, ni se valida.
    m = Modelo()
    h = handle(A, m)
    A.osciloscope_set_calibration(h, ch=5)
    assert m.escrituras == []
    h.close()


@pytest.mark.parametrize('ch', [1.0, None, 'x', 0.0])
def test_un_canal_que_no_es_entero_al_leer_es_un_typeerror(ch):
    """La referencia mira la verdad: `ch=1.0` es el 1, y `None` el 0."""
    h = handle(A, Modelo())
    with pytest.raises(TypeError):
        A.osciloscope_get_thr(h, ch)
    h.close()


@pytest.mark.parametrize('v', [float('inf'), float('-inf'), 1e308 * 10])
def test_el_infinito_es_valueerror_en_vez_de_overflowerror(v):
    """No se escribe en ninguna; sólo cambia el tipo: a C no le llega un OverflowError."""
    for fn in (A.osciloscope_set_thr, A.osciloscope_set_hysteresis):
        mr, mc = Modelo(), Modelo()
        with pytest.raises(OverflowError):
            getattr(R, fn.__name__)(handle(R, mr), v)
        h = handle(A, mc)
        with pytest.raises(ValueError, match='infinity'):
            fn(h, v)
        assert mr.escrituras == mc.escrituras == []
        h.close()


def test_un_volts_finito_que_desborda_al_escalar_tambien():
    h = handle(A, Modelo())
    with pytest.raises(ValueError, match='infinity'):
        A.osciloscope_set_thr(h, 1e308)
    h.close()


def test_decim_con_un_float_legal_es_valueerror():
    """`8.0 in DEC_LEGAL` es True, y la referencia cae con TypeError en el w32. No
    escribe ninguna."""
    mr, mc = Modelo(), Modelo()
    with pytest.raises(TypeError):
        R.osciloscope_set_decim(handle(R, mr), 8.0)
    h = handle(A, mc)
    with pytest.raises(ValueError, match='decim 8.0 no legal'):
        A.osciloscope_set_decim(h, 8.0)
    assert mr.escrituras == mc.escrituras == []
    h.close()


@pytest.mark.parametrize('kw, ya_escritas', [
    (dict(thr=None), 4), (dict(thr='x'), 4), (dict(thr=float('nan')), 4),
    (dict(delay=1.5), 6), (dict(delay=None), 6)])
def test_acq_base_con_un_argumento_malo_no_deja_nada_a_medias(kw, ya_escritas):
    """La referencia ya reseteó la FSM y cambió la decimación cuando cae."""
    mr, mc = Modelo(), Modelo()
    with pytest.raises(Exception) as py:                        # noqa: PT011
        handle(R, mr).acq_base(**kw)
    h = handle(A, mc)
    with pytest.raises(py.type):
        h.acq_base(**kw)
    assert len(mr.escrituras) == ya_escritas and mc.escrituras == []
    h.close()


def test_un_volts_entero_enorme_se_pasa_por_double():
    """Desde 2^53 un double ya no representa cada entero, y un `int` de Python sí. No es
    un umbral: son 10^12 V."""
    v = 2 ** 60 + 1
    mr, mc = Modelo(), Modelo()
    R.osciloscope_set_thr(handle(R, mr), v, 0)
    h = handle(A, mc)
    A.osciloscope_set_thr(h, v, 0)
    assert mr.escrituras == [(R.R_THR_CH0, 8192)] and mc.escrituras == [(R.R_THR_CH0, 0)]
    h.close()


# =============================================================================
# Lo que queda compuesto en Python, lado a lado
# =============================================================================

def _dos_bloques(M, MM, escrituras, **fijos):
    """Un osciloscopio y un multitrigger con una sola traza, para ver el orden."""
    class Mt(MM.MultiTrigger):
        def __init__(self):
            self.reg = {RM.R_OR_MASK_CH0: 0, RM.R_OR_MASK_CH1: 0, RM.R_SHIELD_CFG: 0,
                        RM.R_TRIG_SNAP: 0b101, RM.R_FLAGS: 0x33, RM.R_SHIELD_RUN: 7}
            super().__init__(None, -1)

        def r32(self, off):
            return self.reg.get(off, 0)

        def w32(self, off, v):
            v = v & 0xFFFFFFFF
            escrituras.append(('mt', off, v))
            self.reg[off] = v & (0xFFFF1F7F if off == RM.R_SHIELD_CFG else 0xFFFFFFFF)

    class Osc(M.Osciloscope):
        reg = {}

        def __init__(self):
            self.modelo = Modelo(**fijos)
            super().__init__(None, -1)

        def r32(self, off):
            return self.modelo.r32(off)

        def w32(self, off, v):
            v = v & 0xFFFFFFFF
            escrituras.append(('osc', off, v))
            self.modelo.w32(off, v)

        @staticmethod
        def wait_fill(timeout_ms=2000):
            return True

        @staticmethod
        def read_buffers(n_buf=None):
            return ('d1', n_buf)

    o = Osc()
    o._mt = Mt()
    return o


@pytest.mark.parametrize('kw', [{}, dict(thr=0.25), dict(thr=0.25, delay=100),
                                dict(timeout_ms=1)])
def test_acq_capture_sw(kw):
    er, ec = [], []
    hr, hc = _dos_bloques(R, RM, er), _dos_bloques(A, AM, ec)
    _igual_resultado('acq_capture_sw', correr(lambda: hr.acq_capture_sw(**kw)),
                     correr(lambda: hc.acq_capture_sw(**kw)), True)
    assert ec == er
    assert ('osc', 0x004, 0x101) in ec
    assert ec.index(('osc', 0x000, 0x101)) < ec.index(('osc', 0x004, 0x101)), 'arma antes'
    hc.close()


@pytest.mark.parametrize('kw', [dict(thr=0.25), dict(thr=0.25, delay=100)])
def test_osciloscope_read_capture_sw(kw):
    er, ec = [], []
    hr, hc = _dos_bloques(R, RM, er), _dos_bloques(A, AM, ec)
    _igual_resultado('read_capture_sw',
                     correr(lambda: R.osciloscope_read_capture_sw(hr, **kw)),
                     correr(lambda: A.osciloscope_read_capture_sw(hc, **kw)), True)
    assert ec == er
    hc.close()


def _fijos_validos():
    return {str(R.R_DEC_CH0): R.RESET_SET_DEC, str(R.R_DEC_CH1): R.RESET_SET_DEC,
            str(R.R_CALIB_GAIN_CH0): R.RESET_CALIB_GAIN}


@pytest.mark.parametrize('fijos, ok', [(_fijos_validos(), True), ({str(R.R_DEC_CH0): 7}, False)])
def test_verify_bitstream(fijos, ok, capsys):
    er, ec = [], []
    hr, hc = _dos_bloques(R, RM, er, **fijos), _dos_bloques(A, AM, ec, **fijos)
    a, b = hr.verify_bitstream(verbose=True), hc.verify_bitstream(verbose=True)
    salida = capsys.readouterr().out
    assert a == b and a['ok'] is ok and ec == er
    mitad = len(salida) // 2
    assert salida[:mitad] == salida[mitad:]
    hc.close()


def test_verify_bitstream_raise_on_fail():
    er, ec = [], []
    hr, hc = _dos_bloques(R, RM, er, **{str(R.R_DEC_CH0): 7}), _dos_bloques(A, AM, ec, **{str(R.R_DEC_CH0): 7})
    with pytest.raises(RuntimeError) as py:
        hr.verify_bitstream(verbose=False, raise_on_fail=True)
    with pytest.raises(RuntimeError) as c:
        hc.verify_bitstream(verbose=False, raise_on_fail=True)
    assert str(c.value) == str(py.value)
    hc.close()


def test_verify_bitstream_sin_la_region_del_multitrigger_no_levanta(capsys):
    class SinMt(A.Osciloscope):
        @property
        def mt(self):
            raise RuntimeError('no es la región')

        def r32(self, off):
            return 1

        def w32(self, off, v):
            pass

    h = SinMt(None, -1)
    r = h.verify_bitstream()
    assert not r['fingerprint_ok'] and 'no es la región' in capsys.readouterr().out
    h.close()


@pytest.mark.parametrize('metodo', ['debug_trigger', 'debug_dump'])
def test_los_volcados_dicen_lo_mismo(metodo, capsys):
    hr, hc = _dos_bloques(R, RM, []), _dos_bloques(A, AM, [])
    getattr(hr, metodo)()
    py = capsys.readouterr().out
    getattr(hc, metodo)()
    assert capsys.readouterr().out == py and py
    hc.close()


def test_probe_rw_restaura_siempre():
    comparar('probe', lambda M, h: h._probe_rw(R.R_THR_CH0, (0x1234, 0), 0x3FFF))
    comparar('probe', lambda M, h: h._probe_rw(R.R_THR_CH0, (0xFFFFFFFF,), 0xFFFFFFFF))
    comparar('probe', lambda M, h: h._probe_rw(R.R_CMD, (5,)))


def test_capture_n_events_sobre_el_mismo_buffer():
    """El lazo es el de C, en modo continuo: ve los cambios de wp_trig que escribe
    otro hilo en el buffer."""
    mem = bytearray(R.SCOPE_SIZE)
    h = A.Osciloscope(mem, -1)
    fin = threading.Event()

    def pulsar():
        wp = 0
        while not fin.is_set():
            wp = (wp + 1) & 0x3FFF
            struct.pack_into('<I', mem, R.R_WP_TRIG_CH0, wp)
            time.sleep(0.0005)

    t = threading.Thread(target=pulsar, daemon=True)
    t.start()
    try:
        ev, dur = A.osciloscope_read_events(h, n=5, timeout_ms=2000)
    finally:
        fin.set()
        t.join()
    assert len(ev) == 5 and dur < 2.0 and all(e['snap'] == 0 for e in ev)
    wps = [e['wp'] for e in ev]
    assert len(set(wps)) == 5 and all(0 < e['t_ns'] < dur * 1e9 for e in ev)
    assert [e['t_ns'] for e in ev] == sorted(e['t_ns'] for e in ev)
    assert struct.unpack_from('<I', mem, R.R_TRIG_DIS_CLR)[0] == 0x101, 'el pulso inicial'
    h.close()


def test_capture_n_events_con_snapshot_lo_lee_del_multitrigger():
    mem = bytearray(R.SCOPE_SIZE)
    h = A.Osciloscope(mem, -1)
    mt_mem = bytearray(0x1000)
    struct.pack_into('<I', mt_mem, 0, RM.MTRG_MAGIC)
    struct.pack_into('<I', mt_mem, RM.R_TRIG_SNAP, 0x22)
    h._mt = AM.MultiTrigger(mt_mem, -1)
    fin = threading.Event()

    def pulsar():
        wp = 0
        while not fin.is_set():
            wp = (wp + 3) & 0x3FFF
            struct.pack_into('<I', mem, R.R_WP_TRIG_CH1, wp)
            time.sleep(0.0005)

    t = threading.Thread(target=pulsar, daemon=True)
    t.start()
    try:
        ev, _ = h.capture_n_events(n=3, wp_addr=R.R_WP_TRIG_CH1, read_snap=True)
    finally:
        fin.set()
        t.join()
    assert [e['snap'] for e in ev] == [0x22] * 3
    assert all(e['wp'] % 3 == 0 for e in ev)
    h.close()


def test_capture_n_events_sin_eventos_vence_el_plazo():
    hc = A.Osciloscope(bytearray(R.SCOPE_SIZE), -1)
    ev, dur = hc.capture_n_events(n=3, timeout_ms=1, deadline_every=16)
    assert ev == [] and dur >= 0.001
    hc.close()


# =============================================================================
# Abrir y cerrar
# =============================================================================

def _fichero(tmp_path, rsz=14, n_ch=2, dw=14, magic=R.MAGIC_OSC, largo=None, **regs):
    g = R.geometria_scope(rsz, n_ch) if 1 <= n_ch <= 4 and 1 <= rsz <= 24 else {'size': 0x2000}
    ruta = tmp_path / 'osc.bin'
    b = bytearray(largo if largo is not None else g['size'])
    struct.pack_into('<I', b, R.R_CANON_MAGIC, magic)
    struct.pack_into('<I', b, R.R_CANON_CAPS, (rsz << 16) | (dw << 8) | n_ch)
    for off, v in regs.items():
        struct.pack_into('<I', b, int(off), v)
    ruta.write_bytes(bytes(b))
    return str(ruta)


def _redirigir_devmem(monkeypatch, ruta):
    real = os.open
    monkeypatch.setattr(os, 'open',
                        lambda p, fl, *a: real(ruta, os.O_RDWR) if p == '/dev/mem' else real(p, fl, *a))


@pytest.mark.parametrize('n_ch, size', [(1, 0x20000), (2, 0x30000), (4, 0x50000)])
def test_la_sonda_mapea_lo_que_hace_falta(tmp_path, n_ch, size):
    ruta = _fichero(tmp_path, n_ch=n_ch)
    h = A.Osciloscope._de_fichero(ruta)
    g = h.geometria()
    assert g['descubierta'] and g['size'] == size and g['n_ch'] == n_ch
    # Llega a la última palabra de la última apertura, y no más allá.
    ult = A.APERTURA_BRAM_0 + (n_ch - 1) * A.APERTURA_BRAM_PASO + 4 * ((1 << 14) - 1)
    assert h.r32(ult) == 0
    with pytest.raises(ValueError):
        h.r32(ult + 4)
    assert len(A.osciloscope_read_bram(h, n_ch - 1, 0, 1 << 14)) == 1 << 14
    h.close()


def test_abrir_y_cerrar_no_deja_nada_abierto(tmp_path):
    """Ni la sonda ni el mapeo: reprogramar la PL con un mapeo abierto traba el puerto
    GP0 (API/fpga.py)."""
    ruta = _fichero(tmp_path)

    def abierto():
        with open('/proc/self/maps') as f:
            return ruta in f.read()

    fds = len(os.listdir('/proc/self/fd'))
    for size in (None, R.SCOPE_SIZE):
        h = A.Osciloscope._de_fichero(ruta, size=size)
        assert abierto()
        h.close()
        assert not abierto(), f'size={size}'
    assert len(os.listdir('/proc/self/fd')) == fds


def test_la_sonda_que_falla_no_deja_nada_abierto(tmp_path):
    ruta = _fichero(tmp_path, n_ch=9, largo=0x2000)
    fds = len(os.listdir('/proc/self/fd'))
    with pytest.raises(ValueError):
        A.Osciloscope._de_fichero(ruta)
    assert len(os.listdir('/proc/self/fd')) == fds
    with open('/proc/self/maps') as f:
        assert ruta not in f.read()


def test_el_valor_historico_deja_afuera_dos_aperturas_con_cuatro_canales(tmp_path):
    ruta = _fichero(tmp_path, n_ch=4)
    h = A.Osciloscope._de_fichero(ruta, size=R.SCOPE_SIZE)
    assert h.geometria()['size'] == 0x50000
    with pytest.raises(ValueError):
        A.osciloscope_read_bram(h, 2, 0, 4)
    assert len(A.osciloscope_read_bram(h, 1, 0, 4)) == 4
    h.close()


def test_la_sonda_no_relee_la_geometria(tmp_path):
    ruta = _fichero(tmp_path, n_ch=4)
    h = A.Osciloscope._de_fichero(ruta)
    # Se pisa el fichero: lo que dice el handle es lo que leyó la sonda.
    with open(ruta, 'r+b') as f:
        f.seek(R.R_CANON_CAPS)
        f.write(struct.pack('<I', (10 << 16) | (14 << 8) | 1))
    assert h.geometria()['n_ch'] == 4
    h.close()


def test_la_sonda_sobre_un_bitstream_viejo_usa_la_geometria_por_defecto(tmp_path):
    ruta = _fichero(tmp_path, magic=0)
    h = A.Osciloscope._de_fichero(ruta)
    g = h.geometria()
    assert not g['descubierta'] and g['size'] == R.SCOPE_SIZE
    h.close()


def test_la_sonda_con_una_geometria_imposible_da_el_error_de_geometria(tmp_path):
    ruta = _fichero(tmp_path, n_ch=9, largo=0x2000)
    with pytest.raises(ValueError, match='n_ch=9 fuera de 1..4'):
        A.Osciloscope._de_fichero(ruta)


def test_un_fichero_que_no_esta_es_un_oserror(tmp_path):
    with pytest.raises(FileNotFoundError):
        A.Osciloscope._de_fichero(str(tmp_path / 'no_esta.bin'))


def test_open_file_sin_ruta_es_un_error():
    p = ctypes.c_void_p()
    assert LIB.osciloscope_open_file(ctypes.byref(p), None, 0, 0) == _libmca.MCA_EINVAL


def test_open_bus_con_null_es_un_error():
    p = ctypes.c_void_p()
    assert LIB.osciloscope_open_bus(ctypes.byref(p), None, 0) == _libmca.MCA_EINVAL
    assert LIB.osciloscope_open_bus(None, None, 0) == _libmca.MCA_EINVAL


@pytest.mark.parametrize('size_py, size_c', [(R.SCOPE_SIZE, R.SCOPE_SIZE), (0x50000, 0x50000),
                                             (None, 0)])
def test_open_pasa_los_argumentos_y_recuerda_la_region(tmp_path, monkeypatch, size_py, size_c):
    """El camino que sólo corre en la placa: `osciloscope_open` se reemplaza por el mismo
    backend sobre un fichero, y el resto es el de verdad."""
    ruta = _fichero(tmp_path, n_ch=4, **{str(R.R_WP_TRIG_CH0): 77})
    _redirigir_devmem(monkeypatch, ruta)
    pedidos = []

    def abrir(pp, phys, size):
        pedidos.append((phys, size))
        return LIB.osciloscope_open_file(pp, os.fsencode(ruta), phys, size)

    monkeypatch.delenv('MCA_IMPL', raising=False)
    monkeypatch.setattr(A, '_cargar', lambda: _Libreria(osciloscope_open=abrir))
    monkeypatch.setattr(A, 'fpga_state', lambda: None)
    h = A.Osciloscope.open(phys=0, size=size_py)
    assert pedidos == [(0, size_c)] and isinstance(h, A.Osciloscope) and h._via == 'c'
    esperado = 0x50000 if size_py is None else size_py
    assert h._region == (0, esperado)
    assert h.r32(R.R_WP_TRIG_CH0) == 77
    h.w32(R.R_CMD, 0x101)
    assert A.osciloscope_get_adc_state(h) == 0x101
    h.close()


def test_osciloscope_open_descubre_por_defecto(monkeypatch, tmp_path):
    """A diferencia de `Osciloscope.open`, que conserva el 0x30000 histórico."""
    pedidos = []

    def abrir(cls, phys, size, check_pl, impl):
        pedidos.append((phys, size, check_pl, impl))
    monkeypatch.setattr(A.Osciloscope, 'open', classmethod(abrir))
    A.osciloscope_open()
    A.osciloscope_open(phys=1, size=2, check_pl=False, impl='py')
    assert pedidos == [(A.SCOPE_PHYS, None, True, None), (1, 2, False, 'py')]


def test_la_pl_sin_programar_no_llega_a_mapear(monkeypatch):
    monkeypatch.delenv('MCA_IMPL', raising=False)
    monkeypatch.setattr(A, 'fpga_state', lambda: 'unknown')
    monkeypatch.setattr(R, 'fpga_state', lambda: 'unknown')
    with pytest.raises(RuntimeError) as c:
        A.Osciloscope.open(impl='c')
    with pytest.raises(RuntimeError) as py:
        R.Osciloscope.open()
    assert str(c.value) == str(py.value) and 'SIGBUS' in str(c.value)


def test_check_pl_false_no_mira_el_estado(monkeypatch):
    monkeypatch.setattr(A, 'fpga_state', lambda: pytest.fail('miró'))
    monkeypatch.setattr(A, '_cargar', lambda: _Libreria(
        osciloscope_open=lambda pp, phys, size: _libmca.MCA_EINVAL))
    with pytest.raises(ValueError):
        A.Osciloscope.open(check_pl=False, impl='c')


def test_abrir_devmem_sin_permiso_es_un_oserror(monkeypatch):
    if os.access('/dev/mem', os.R_OK | os.W_OK):
        pytest.skip('con root /dev/mem abre')
    monkeypatch.setattr(A, 'fpga_state', lambda: None)
    with pytest.raises(OSError):
        A.Osciloscope.open(impl='c')


def test_cerrar_dos_veces_no_es_un_error():
    h = handle(A, Modelo())
    h.close()
    h.close()


def test_usar_un_handle_cerrado_es_un_error_no_un_segfault():
    h = A.Osciloscope(bytearray(R.SCOPE_SIZE), -1)
    h.close()
    with pytest.raises(ValueError):
        h.r32(0)
    with pytest.raises(ValueError):
        h.w32(0, 1)
    with pytest.raises(ValueError):
        A.osciloscope_get_status(h)
    with pytest.raises(ValueError):
        A.osciloscope_set_thr(h, 0.5)


def test_with_cierra():
    with A.Osciloscope(bytearray(R.SCOPE_SIZE), -1) as h:
        h.w32(0x10, 3)
    assert h._c is None


def test_un_mmap_prestado_no_se_cierra_y_uno_propio_si(tmp_path):
    ruta = _fichero(tmp_path)
    import mmap
    fd = os.open(ruta, os.O_RDWR)
    m = mmap.mmap(fd, R.SCOPE_SIZE)
    h = A.Osciloscope(m, -1)
    h.close()
    assert not m.closed
    h = A.Osciloscope(m, fd)
    h.close()
    assert m.closed
    with pytest.raises(OSError):
        os.fstat(fd)


def test_close_cierra_el_multitrigger():
    h = A.Osciloscope(bytearray(R.SCOPE_SIZE), -1)
    mt = AM.MultiTrigger(bytearray(AM.MTRG_SIZE), -1)
    h._mt = mt
    h.close()
    assert mt._c is None and h._mt is None


def test_un_handle_olvidado_se_cierra_solo():
    h = handle(A, Modelo())
    c = h._c
    assert c
    h.__del__()
    assert h._c is None


def test_del_de_un_handle_a_medio_construir_no_falla(monkeypatch):
    monkeypatch.setattr(A, '_cargar', lambda: (_ for _ in ()).throw(OSError('no carga')))
    with pytest.raises(OSError):
        A.Osciloscope(None, -1)
    h = A.Osciloscope.__new__(A.Osciloscope)
    h.__del__()


def test_el_bus_prestado_lo_cierra_el_handle(tmp_path):
    ruta = _fichero(tmp_path, **{str(R.R_DEC_CH0): 8})
    bus = _libmca.Bus.archivo(ruta, 0, R.SCOPE_SIZE)
    h = A.Osciloscope._sobre_bus(bus)
    assert A.osciloscope_get_decim(h) == 8
    h.close()
    with pytest.raises(ValueError, match='bus cerrado'):
        bus.ptr                                                 # noqa: B018


def test_el_backend_devmem_y_el_python_ven_lo_mismo(tmp_path, monkeypatch):
    ruta = _fichero(tmp_path, **{str(R.R_THR_CH0): 0x3000, str(R.R_DEC_CH1): 8})
    _redirigir_devmem(monkeypatch, ruta)
    monkeypatch.setattr(R, 'fpga_state', lambda: None)
    hr = R.Osciloscope.open(phys=0, size=R.SCOPE_SIZE)
    hc = A.Osciloscope._de_fichero(ruta, size=R.SCOPE_SIZE)
    assert A.osciloscope_get_config(hc) == R.osciloscope_get_config(hr)
    assert A.osciloscope_get_status(hc) == R.osciloscope_get_status(hr)
    assert hc.geometria() == hr.geometria()
    A.osciloscope_set_thr(hc, -0.25, 1)
    assert R.osciloscope_get_thr(hr, 1) == -0.25
    A.osciloscope_configure(hc, avg_en_ch0=1, avg_en_ch1=1)
    assert hr.r32(R.R_AVG_EN) == 0x101
    R.osciloscope_set_delay(hr, 99)
    assert A.osciloscope_get_delay(hc, 1) == 99
    hc.acq_base(thr=0.1, delay=2, decim=8)
    assert R.osciloscope_get_config(hr) == A.osciloscope_get_config(hc)
    hc.close()
    hr.close()


# =============================================================================
# El despacho
# =============================================================================

@pytest.fixture
def ref_sobre_modelo(monkeypatch):
    m = Modelo()

    def abrir(c, *a, **k):
        return handle(R, m)
    monkeypatch.setattr(R.Osciloscope, 'open', classmethod(abrir))
    return m


def test_impl_py_va_a_la_referencia(ref_sobre_modelo):
    h = A.Osciloscope.open(impl='py')
    assert h._via == 'py' and h.impl == 'py' and isinstance(h, R.Osciloscope)
    A.osciloscope_configure(h, thr_ch0=3)
    assert ref_sobre_modelo.escrituras == [(R.R_THR_CH0, 3)]
    assert A.osciloscope_get_config(h)['thr_ch0'] == 3
    assert A.osciloscope_get_thr(h) == 3 / 8192
    assert list(A.osciloscope_get_status(h))[0] == 'adc_state'


def test_impl_py_pasa_los_argumentos(monkeypatch):
    pedidos = []

    def abrir(c, *a):
        pedidos.append(a)
        return handle(R, Modelo())
    monkeypatch.setattr(R.Osciloscope, 'open', classmethod(abrir))
    A.Osciloscope.open(phys=1, size=2, check_pl=False, impl='py')
    A.Osciloscope.open(impl='py')
    assert pedidos == [(1, 2, False), (R.SCOPE_PHYS, R.SCOPE_SIZE, True)]


def test_mca_impl_elige(ref_sobre_modelo, monkeypatch):
    monkeypatch.setenv('MCA_IMPL', 'py')
    assert A.Osciloscope.open()._via == 'py'
    monkeypatch.setenv('MCA_IMPL', 'nope')
    with pytest.raises(ValueError, match='nope'):
        A.Osciloscope.open()


def test_sin_libmca_cae_a_python_y_lo_dice(ref_sobre_modelo, monkeypatch, capsys):
    monkeypatch.delenv('MCA_IMPL', raising=False)
    monkeypatch.setattr(_libmca, 'disponible', lambda: False)
    assert A.Osciloscope.open()._via == 'py'
    assert 'libmca no está disponible' in capsys.readouterr().err


def test_el_multitriggerscope_abre_con_las_dos_implementaciones(monkeypatch, tmp_path):
    """Sin `_CLASE_REF` propia, `open(impl='py')` daría un Osciloscope pelado y `BramSource`
    moriría en `arm_for_adc_trigger`."""
    import multitrigger_utils as mu
    ruta = _fichero(tmp_path)
    _redirigir_devmem(monkeypatch, ruta)
    monkeypatch.setattr(R, 'fpga_state', lambda: None)
    h = mu.MultiTriggerScope.open(phys=0, impl='py')
    assert h._via == 'py' and isinstance(h, R.Osciloscope)
    for m in ('arm_for_adc_trigger', 'disarm', 'set_or_mask', 'configure_shield_autorearm',
              'disable_shield'):
        assert callable(getattr(h, m)), m
    h.close()

    monkeypatch.setattr(A, 'fpga_state', lambda: None)
    monkeypatch.setattr(A, '_cargar', lambda: _Libreria(
        osciloscope_open=lambda pp, phys, size: LIB.osciloscope_open_file(
            pp, os.fsencode(ruta), phys, size)))
    h = mu.MultiTriggerScope.open(phys=0, impl='c')
    assert h._via == 'c' and isinstance(h, mu.MultiTriggerScope) and isinstance(h, A.Osciloscope)
    h.close()


def test_mt_abre_con_la_implementacion_del_scope(monkeypatch):
    pedidos = []

    class Falso:
        close = staticmethod(lambda: None)

    def abrir(impl=None):
        pedidos.append(impl)
        return Falso()
    monkeypatch.setattr(A.MultiTrigger, 'open', abrir)
    h = A.Osciloscope(bytearray(R.SCOPE_SIZE), -1)
    assert h.mt is h.mt, 'se abre una vez'
    assert pedidos == ['c']
    h.close()


def test_reload_bitstream_cierra_y_reabre_con_la_misma_implementacion(monkeypatch):
    class RpFalso:
        rp_Release = rp_Init = staticmethod(lambda: None)

    pedidos, abiertos = [], []

    class Nuevo:
        mt = AM.MultiTrigger(bytearray(AM.MTRG_SIZE), -1)

    def abrir(phys, size, impl=None):
        pedidos.append((phys, size, impl))
        return Nuevo()

    monkeypatch.setattr(A, 'rp', RpFalso)
    monkeypatch.setattr(A, 'load_bitstream', lambda p: abiertos.append(p) or {'path': p, 'state': 'operating'})
    monkeypatch.setattr(A.Osciloscope, 'open', abrir)
    viejo = A.Osciloscope(bytearray(R.SCOPE_SIZE), -1)
    viejo.impl = 'py'
    assert isinstance(A.Osciloscope.reload_bitstream(path='x.bin', scope=viejo, verbose=False), Nuevo)
    assert viejo._c is None, 'el mapeo viejo se cierra antes de reprogramar'
    assert abiertos == ['x.bin'] and pedidos == [(R.SCOPE_PHYS, R.SCOPE_SIZE, 'py')]
    A.Osciloscope.reload_bitstream(path='x.bin', verbose=False)
    assert pedidos[-1][2] is None


def test_remoto_viaja_por_call():
    class Remoto:
        _via = 'remoto'

        def call(self, nombre, *a, **k):
            return (nombre, a, k)

    assert A.osciloscope_get_thr(Remoto(), 1) == ('osciloscope_get_thr', (1,), {})
    assert A.osciloscope_configure(Remoto(), thr_ch0=1) == ('osciloscope_configure', (), {'thr_ch0': 1})


# =============================================================================
# Lo que corre sobre el handle
# =============================================================================

def test_el_osc_simulado_corre_la_logica_de_c():
    from API.mca_remote import FakeOsc
    h = FakeOsc(n_buf=4096)
    assert isinstance(h, A.Osciloscope) and h._c
    assert h.n_buf == 4096 and h.geometria()['descubierta'] and h.geometria()['n_ch'] == 2
    A.osciloscope_set_thr(h, -0.5, 1)
    assert A.osciloscope_get_thr(h, 1) == -0.5
    A.osciloscope_configure(h, dec_ch0=8)
    assert A.osciloscope_get_config(h)['dec_ch0'] == 8
    st = A.osciloscope_get_status(h)
    assert st['adc_state'] == 1 and st['wp_cur_ch0'] < 4096
    assert h.capturar(pre=10, post=20).shape == (2, 30)
    h.close()
    h.close()


@pytest.mark.parametrize('n_buf', [1000, 3, 16383])
def test_el_osc_simulado_exige_una_potencia_de_2(n_buf):
    from API.mca_remote import FakeOsc
    with pytest.raises(ValueError, match='potencia de 2'):
        FakeOsc(n_buf=n_buf)


def test_multitriggerscope_sobre_un_buffer_arma_en_el_orden_de_siempre():
    import multitrigger_utils as mu
    escrituras = []

    class Mem(bytearray):
        def __setitem__(self, k, v):
            escrituras.append(('osc', k.start, struct.unpack('<I', bytes(v))[0]))
            super().__setitem__(k, v)

    class MemMt(bytearray):
        def __setitem__(self, k, v):
            escrituras.append(('mt', k.start, struct.unpack('<I', bytes(v))[0]))
            super().__setitem__(k, v)

    h = mu.MultiTriggerScope(Mem(R.SCOPE_SIZE), -1)
    h._mt = AM.MultiTrigger(MemMt(AM.MTRG_SIZE), -1)
    h.arm_for_adc_trigger(mask_ch0=AM.BIT_ADC_P0, mask_ch1=AM.BIT_ADC_P0, thr=0.25, hyst=0.02,
                          delay=3, we_keep_both=False, auto_rearm=True)
    osc_arm = [i for i, e in enumerate(escrituras) if e[0] == 'osc' and e[1] == 0]
    mascaras = [i for i, e in enumerate(escrituras) if e[0] == 'mt' and e[1] == AM.R_OR_MASK_CH0]
    assert osc_arm and mascaras and max(osc_arm) < min(i for i in mascaras if escrituras[i][2]), (
        'ORDEN CRÍTICO: arma antes de habilitar la máscara')
    h.close()


def test_el_servidor_abre_el_osciloscopio_con_su_impl():
    with open(os.path.join(SOFT, 'app', 'mca_server.py'), encoding='utf-8') as f:
        assert 'osciloscope_open(phys=base, impl=self.impl)' in f.read()


def test_las_cuentas_de_c_son_de_python_en_todo_el_rango():
    """Barrido de la conversión a 14 bits, con todas las cuentas y sus medios."""
    mr, mc = Modelo(), Modelo()
    hr, hc = handle(R, mr), handle(A, mc)
    for k in range(-8192, 8192, 37):
        for frac in (0, 0.25, 0.5, 0.75):
            v = (k + frac) / 8192
            R.osciloscope_set_thr(hr, v, 0)
            A.osciloscope_set_thr(hc, v, 0)
            assert mr.escrituras[-1] == mc.escrituras[-1], v
            assert math.isclose(R.osciloscope_get_thr(hr, 0), A.osciloscope_get_thr(hc, 0))
    hc.close()


# =============================================================================
# La prueba de placa, antes de la placa
# =============================================================================

def test_la_prueba_de_placa_corre_contra_un_fichero(tmp_path, monkeypatch, capsys):
    """`placa/test_osciloscope_hw.py` no se estrena en la placa: acá corre contra un
    fichero. Sin la captura por software, que necesita la FSM del RTL."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'test_osciloscope_hw', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            'placa', 'test_osciloscope_hw.py'))
    prueba = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prueba)
    ruta = _fichero(tmp_path, **{str(R.R_DEC_CH0): 1, str(R.R_DEC_CH1): 1,
                                 str(R.R_CALIB_GAIN_CH0): 0x8000, str(R.R_THR_CH0): 77,
                                 str(R.R_DEB_LEN): 1234})
    with open(ruta, 'r+b') as f:                # algo que leer en la BRAM
        for ch in (0, 1):
            f.seek(A.APERTURA_BRAM_0 + ch * A.APERTURA_BRAM_PASO)
            f.write(np.random.default_rng(ch).integers(0, 1 << 14, 1 << 14,
                                                       dtype='<u4').tobytes())
    _redirigir_devmem(monkeypatch, ruta)
    monkeypatch.setattr(R, 'fpga_state', lambda: None)
    hr = R.Osciloscope.open(phys=0, size=R.SCOPE_SIZE)
    hc = A.Osciloscope._de_fichero(ruta, size=R.SCOPE_SIZE)
    prueba.probar(hc, hr)
    prueba.probar_bram(hc, hr)
    salida = capsys.readouterr().out
    assert prueba._fail == 0, salida
    assert prueba._pass > 15 and 'FAIL' not in salida
    # Dejó todo como estaba.
    assert A.osciloscope_get_config(hc)['thr_ch0'] == 77
    assert A.osciloscope_get_deb_len(hc) == 1234
    hc.close()
    hr.close()



# =============================================================================
# La captura, en C
# =============================================================================
#
# Sin referencia en la PC: la de Python era `rp`. Lo que se compara es la cuenta de
# librp (cmn_CalibCntsSigned de rp-api 2.00-35, compilada una vez:
# datos_ref/generar_calib_rp.py) y los bits de 0x000 que miraba librp.

TABLA = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'datos_ref',
                             'calib_rp.npy'))
CODIGOS = np.arange(1 << 14, dtype=np.uint32)


def _cal(fila):
    return {'gain': int(fila['gain']), 'base': int(fila['base']),
            'offset': int(fila['offset'])}


@pytest.mark.parametrize('fila', range(len(TABLA)))
def test_la_calibracion_es_la_de_librp_en_todas_las_cuentas(fila):
    """La mutación obligatoria del plan: un desplazamiento que redondee hacia abajo
    (`m >> k` con m negativo) tiene que hacer fallar a esto, y lo hace en la fila de
    gain 32112: la cuenta 0 da -36 truncando y -37 redondeando hacia abajo."""
    t = TABLA[fila]
    np.testing.assert_array_equal(A.osciloscope_calibrar(_cal(t), CODIGOS), t['m'])


def test_la_tabla_cubre_lo_que_tiene_que_cubrir():
    bases = {int(b) for b in TABLA['base']}
    assert 32768 in bases and any(b & (b - 1) for b in bases), 'desplazamiento y división'
    assert (TABLA['m'] == 8192).any() and (TABLA['m'] == -8192).any(), 'los dos recortes'
    t = TABLA[[int(g) == 32112 for g in TABLA['gain']]][0]
    assert t['m'][0] == -36, 'el redondeo hacia cero de un negativo'


@pytest.mark.parametrize('cal, msg', [
    ((0, 32768, 0), 'gain=0'), ((32768, 0, 0), 'base=0'),
    ((2 ** 31, 32768, 0), 'gain=2147483648'),
    ((300000, 32768, 0), 'desbordan'), ((32768, 32768, -2 ** 31), 'desbordan')])
def test_una_calibracion_imposible_es_un_error(cal, msg):
    with pytest.raises(ValueError, match=msg):
        A.osciloscope_calibrar(cal, CODIGOS[:4])


def test_calibrar_fuera_de_los_tipos_no_llega_a_c():
    with pytest.raises(ValueError, match='offset'):
        A.osciloscope_calibrar((1, 1, 2 ** 31), CODIGOS[:1])
    with pytest.raises(ValueError, match='bits'):
        A.osciloscope_calibrar((1, 1, 0), CODIGOS[:1], dw=1)


def _modelo_con_codigos(rsz=14, **fijos):
    n = 1 << rsz
    bram = [np.arange(n, dtype=np.uint32) % (1 << 14),
            (np.arange(n, dtype=np.uint32) * 7 + 3) % (1 << 14)]
    return Modelo(rsz=rsz, bram=bram, **fijos), bram


@pytest.mark.parametrize('ch', [0, 1])
@pytest.mark.parametrize('start, n', [(0, 16384), (16000, 1000), (-5, 32)])
def test_read_cal_es_la_cuenta_de_librp_por_el_bus(ch, start, n):
    m, bram = _modelo_con_codigos()
    h = handle(A, m)
    t = TABLA[1]
    got = A.osciloscope_read_cal(h, ch, start, n, _cal(t))
    pos = (start + np.arange(n)) % 16384
    np.testing.assert_array_equal(got, t['m'][bram[ch][pos]])
    assert m.escrituras == []
    h.close()


def test_read_cal_valida_como_read_bram():
    m, _ = _modelo_con_codigos(rsz=13)
    h = handle(A, m)
    for args in ((2, 0, 4), (0, 0, 8193)):
        with pytest.raises(ValueError) as c:
            A.osciloscope_read_bram(h, *args)
        with pytest.raises(ValueError) as k:
            A.osciloscope_read_cal(h, *args, _cal(TABLA[0]))
        assert str(k.value) == str(c.value)
    with pytest.raises(ValueError, match='gain=0'):
        A.osciloscope_read_cal(h, 0, 0, 4, (0, 1, 0))
    h.close()


def test_read_cal_no_existe_en_la_referencia():
    m, _ = _modelo_con_codigos()
    hr = handle(R, m)
    hr._via = 'py'
    with pytest.raises(NotImplementedError, match='sólo en libmca'):
        A.osciloscope_read_cal(hr, 0, 0, 4, _cal(TABLA[0]))


def _con_cal(h, filas=(1, 2)):
    h.set_calibracion([_cal(TABLA[f]) for f in filas])
    return h


@pytest.mark.parametrize('at_trigger, off', [(True, R.R_WP_TRIG_CH0),
                                             (False, R.R_WP_CUR_CH0)])
@pytest.mark.parametrize('wp', [5000, 3])
def test_capture_window_np_es_la_ventana_calibrada_en_volts(at_trigger, off, wp):
    otro = R.R_WP_CUR_CH0 if off == R.R_WP_TRIG_CH0 else R.R_WP_TRIG_CH0
    m, bram = _modelo_con_codigos(**{str(off): wp, str(otro): 9999})
    h = _con_cal(handle(A, m))
    data, ref = h.capture_window_np(pre=8, post=24, at_trigger=at_trigger)
    assert ref == wp and list(data) == [0, 1]
    pos = (wp - 8 + np.arange(32)) % 16384
    for ch, f in zip((0, 1), (1, 2)):
        esperado = (TABLA[f]['m'][bram[ch][pos]].astype(np.float32) / np.float32(8192))
        assert data[ch].dtype == np.float32
        np.testing.assert_array_equal(data[ch], esperado)
        # Lo que se guardaba: rint(V·8192), con la V de librp, es la cuenta.
        np.testing.assert_array_equal(np.rint(data[ch] * 8192), TABLA[f]['m'][bram[ch][pos]])
    assert m.escrituras == []
    h.close()


def test_capture_window_np_por_defecto_es_el_anillo_del_bitstream():
    m, _ = _modelo_con_codigos(rsz=13, **{str(R.R_WP_TRIG_CH0): 10})
    h = _con_cal(handle(A, m))
    data, _ = h.capture_window_np(channels=(1,))
    assert list(data) == [1] and len(data[1]) == 8192
    with pytest.raises(ValueError) as c:
        h.capture_window_np(pre=4096, post=8192)
    with pytest.raises(ValueError) as py:
        R.Osciloscope.capture_window_np(pre=4096, post=8192, n_buf=8192)
    assert str(c.value) == str(py.value)
    h.close()


def test_read_buffers_es_lo_que_daba_oldest():
    """`rp_AcqGetOldestDataV`: desde wp_cur + 1 del canal 0, los dos canales."""
    m, bram = _modelo_con_codigos(rsz=13, **{str(R.R_WP_CUR_CH0): 8191,
                                             str(R.R_WP_CUR_CH1): 17})
    h = _con_cal(handle(A, m))
    d1, d2 = h.read_buffers()
    pos = np.arange(8192)                          # 8191 + 1 da la vuelta a 0
    for d, ch, f in ((d1, 0, 1), (d2, 1, 2)):
        np.testing.assert_array_equal(np.rint(d * 8192), TABLA[f]['m'][bram[ch][pos]])
    assert len(A.osciloscope_read_buffers(h, 100)[0]) == 100
    h.close()


@pytest.mark.parametrize('estado, disparo, lleno', [(0x04, True, False),
                                                    (0x10, False, True),
                                                    (0x1404, True, False), (0, False, False)])
def test_las_esperas_miran_los_bits_de_librp(estado, disparo, lleno):
    """adc_trg_rd (bit 2) y adc_dly_end (bit 4) del canal 0: lo que leían
    rp_AcqGetTriggerState y rp_AcqGetBufferFillState."""
    h = handle(A, Modelo(**{str(R.R_CMD): estado}))
    assert h.wait_triggered(timeout_ms=3) is disparo
    assert A.osciloscope_wait_fill(h, timeout_ms=3) is lleno
    h.close()


class _HwCalib:
    """`rp_hw_calib` de mentira: lo que devuelve la EEPROM por canal."""
    RP_DC_CALIB = 0

    def __init__(self, cals, rc_init=0, rc=0):
        self.cals, self.rc_init, self.rc = cals, rc_init, rc
        self.pedidos = []

    class uint_gain_calib_t:                                    # noqa: N801
        gain = base = offset = 0

    def rp_CalibInit(self):                                     # noqa: N802
        return self.rc_init

    def rp_CalibGetFastADCCalibValueI(self, ch, modo, c):       # noqa: N802
        self.pedidos.append((ch, modo))
        c.gain, c.base, c.offset = self.cals[ch]
        return self.rc


@pytest.fixture
def eeprom(monkeypatch):
    def poner(*a, **kw):
        hc = _HwCalib(*a, **kw)
        monkeypatch.setitem(sys.modules, 'rp_hw_calib', hc)
        return hc
    monkeypatch.delitem(sys.modules, 'rp', raising=False)
    return poner


def test_la_calibracion_se_lee_de_la_eeprom_una_vez_por_canal(eeprom):
    hc = eeprom({0: (33423, 32768, -64), 1: (32112, 32768, 37)})
    h = handle(A, Modelo())
    assert h.calibracion(1) == {'gain': 32112, 'base': 32768, 'offset': 37}
    assert h.calibracion(1) == h.calibracion(1)
    assert h.calibracion(0)['offset'] == -64
    assert hc.pedidos == [(1, 0), (0, 0)], 'DC, y una vez por canal'
    assert A.calibracion_adc() == [{'gain': 33423, 'base': 32768, 'offset': -64},
                                   {'gain': 32112, 'base': 32768, 'offset': 37}]
    h.close()


@pytest.mark.parametrize('kw, msg', [(dict(rc_init=3), 'rp_CalibInit'),
                                     (dict(rc=2), 'canal 0')])
def test_una_calibracion_que_no_se_lee_es_un_error(eeprom, kw, msg):
    eeprom({0: (1, 1, 0)}, **kw)
    with pytest.raises(RuntimeError, match=msg):
        A.calibracion_adc([0])


def test_sin_rp_hw_calib_es_un_error_que_lo_dice(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, 'rp_hw_calib', None)      # el import falla
    monkeypatch.setattr(A, '_RP_PYTHON', str(tmp_path / 'no_existe'))
    with pytest.raises(RuntimeError, match='rp_hw_calib'):
        A.calibracion_adc([0])


def test_redpitaya_agrega_su_camino_si_falta(monkeypatch, tmp_path):
    """Lo que no veía el servidor lanzado por ssh sin login."""
    (tmp_path / 'rp_de_prueba_lote.py').write_text('X = 7\n')
    monkeypatch.setattr(A, '_RP_PYTHON', str(tmp_path))
    monkeypatch.setattr(sys, 'path', [p for p in sys.path if p != str(tmp_path)])
    monkeypatch.delitem(sys.modules, 'rp_de_prueba_lote', raising=False)
    assert A._redpitaya('rp_de_prueba_lote').X == 7
    assert sys.path[-1] == str(tmp_path)


def test_hv_pedido_a_librp_se_rechaza(eeprom, monkeypatch):
    import types
    eeprom({0: (32768, 32768, 0)})
    rp = types.ModuleType('rp')
    rp.RP_LOW, rp.RP_HIGH = 0, 1
    rp.rp_AcqGetGain = lambda ch: [0, rp.RP_HIGH]
    monkeypatch.setitem(sys.modules, 'rp', rp)
    with pytest.raises(ValueError, match='HV'):
        A.calibracion_adc([0])
    rp.rp_AcqGetGain = lambda ch: [0, rp.RP_LOW]
    assert A.calibracion_adc([0])[0]['gain'] == 32768


def test_set_calibracion_valida_al_fijarla():
    h = handle(A, Modelo())
    with pytest.raises(ValueError, match='gain=0'):
        h.set_calibracion({0: (0, 1, 0)})
    h.set_calibracion([(5, 4, 1)])
    assert h.calibracion(0) == {'gain': 5, 'base': 4, 'offset': 1}
    h.close()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
