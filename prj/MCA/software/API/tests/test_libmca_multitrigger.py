#!/usr/bin/env python3
"""El multitrigger en libmca hace lo mismo que la implementación Python.

La referencia es `API/ref_py/multitrigger2.py`, congelada. Cada caso corre la misma
operación sobre dos modelos de registros idénticos —uno detrás de la referencia, otro
detrás de libmca por el backend de callbacks— y exige, como
`test_libmca_equivalencia.py` con el MCA:

  1. **las mismas escrituras, en el mismo orden y con el mismo valor**, también en los
     casos de error. Acá el orden es parte del contrato: una escritura a la máscara
     recarga la fuente activa, y el umbral va antes que el habilitado;
  2. **el mismo resultado**, con las mismas claves en el mismo orden y los mismos tipos;
  3. **la misma excepción**: el mismo tipo y, salvo los casos marcados, el mismo mensaje.

Las diferencias deliberadas con la referencia son pocas, y cada una tiene su test bajo
"Lo que difiere a propósito". Además se prueba lo que una equivalencia no ve: que las
tablas de C son las de Python y que el mapa es el que decodifica `mt_cfg.sv`.

Las secuencias que cruzan con el osciloscopio (`multitrigger_arm`, `armar_mca`, ...) se
comparan acá lado a lado, y `test_disparo_mca.py` las fija contra la secuencia validada
en la placa.

    python -m pytest API/tests/test_libmca_multitrigger.py -q
"""

import ctypes
import inspect
import mmap
import os
import re
import struct

import numpy as np
import pytest

from API import _libmca

if not _libmca.disponible():
    pytest.skip(f'libmca no está compilada ({_libmca.motivo()}): make -C libmca',
                allow_module_level=True)

import API.multitrigger as A                                        # noqa: E402
import API.ref_py.multitrigger2 as R                                # noqa: E402

LIB = A._cargar()

SOFT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEADER = os.path.join(SOFT, 'libmca', 'include', 'multitrigger.h')
RTL = os.path.join(os.path.dirname(SOFT), 'modulos', 'mt', 'rtl', 'mt_cfg.sv')

SEMILLAS = range(8)
CANALES = range(4)
CAPS_TODO = R.CAPS_HAS_SLOPE | R.CAPS_HAS_PZ

# Las familias por canal, y lo que retiene cada registro según mt_cfg.sv.
FAMILIAS = {R.R3_SLOPE_CFG: 0x80001F1F, R.R3_SLOPE_THR: 0x3FFFF, R.R3_SLOPE_HYST: 0x3FFFF,
            R.R3_PZ_CFG: 0xBF001F1F, R.R3_PZ_MQ: 0xFFFFF, R.R3_PZ_THR: 0x3FFFF,
            R.R3_PZ_HYST: 0x3FFFF, R.R3_OR_MASK: 0xFFFFFFFF}
RETIENE = {R.R_SHIELD_CFG: 0xFFFF1F7F}
RETIENE.update({base + 4 * ch: m for base, m in FAMILIAS.items() for ch in CANALES})


# =============================================================================
# El modelo y los dos handles
# =============================================================================

class Modelo:
    """Registros con la retención del RTL, que graban cada acceso.

    `no_retiene` son offsets cuyas escrituras se pierden. Con `osc`, FLAGS sale del
    0x000 del scope, como en el RTL (`we_keep` vive en el slot 1).
    """

    def __init__(self, semilla=1, no_retiene=(), caps=CAPS_TODO, osc=None, **fijos):
        rng = np.random.default_rng(semilla)
        self.reg = rng.integers(0, 2 ** 32, R.MTRG_SIZE // 4,
                                dtype=np.uint64).astype(np.uint32)
        for off, retiene in RETIENE.items():    # lo demás, el RTL lo lee en cero
            self.reg[off >> 2] &= retiene
        self.reg[0] = R.MTRG_MAGIC
        self.reg[R.R3_CAPS >> 2] = caps
        for off, v in fijos.items():
            self.reg[int(off) >> 2] = v
        self.no_retiene = set(no_retiene)
        self.osc = osc
        self.escrituras = []

    def r32(self, off):
        if self.osc is not None and off == R.R3_FLAGS:
            arm = self.osc.reg.get(0x000, 0)
            return sum(1 << (4 + c) for c in range(2) if (arm >> (8 * c + 3)) & 1)
        return int(self.reg[off >> 2])

    def w32(self, off, v):
        v = int(v & 0xFFFFFFFF)                 # como el w32 real: un float no pasa
        self.escrituras.append((off, v))
        if off in self.no_retiene or off not in RETIENE:
            return
        self.reg[off >> 2] = v & RETIENE[off]


def handle(M, clase, m):
    class H(getattr(M, clase)):
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


def comparar(caso, op, clase='MtRegion', preparar=None, mensaje=True, **modelo):
    """Corre `op(módulo, h)` de los dos lados y compara. Devuelve lo que dio."""
    mr, mc = Modelo(**modelo), Modelo(**modelo)
    hr, hc = handle(R, clase, mr), handle(A, clase, mc)
    if preparar:
        preparar(hr)
        preparar(hc)
        mr.escrituras.clear()
        mc.escrituras.clear()
    rr = correr(lambda: op(R, hr))
    rc = correr(lambda: op(A, hc))
    assert mc.escrituras == mr.escrituras, (
        f'{caso}: escrituras distintas\n  py: {mr.escrituras}\n  c:  {mc.escrituras}')
    _igual_resultado(caso, rr, rc, mensaje)
    hc.close()
    return rr, mr.escrituras


# =============================================================================
# Las tablas
# =============================================================================

def _regs_de_c():
    return {LIB.multitrigger_reg_info(i).contents.nombre.decode():
            LIB.multitrigger_reg_info(i).contents.offset
            for i in range(LIB.multitrigger_reg_count())}


def test_mapa_de_registros_es_el_de_python():
    assert _regs_de_c() == {
        'R_MAGIC': 0x000, 'R_CAPS': A.R3_CAPS, 'R_SHIELD_CFG': A.R_SHIELD_CFG,
        'R_SHIELD_RUN': A.R_SHIELD_RUN, 'R_TRIG_SNAP': A.R_TRIG_SNAP, 'R_FLAGS': A.R_FLAGS,
        'R_OR_MASK_CH0': A.R_OR_MASK_CH0, 'R_OR_MASK_CH1': A.R_OR_MASK_CH1,
        'R_OR_MASK_CH2': A.R_OR_MASK_CH2, 'R_OR_MASK_CH3': A.R_OR_MASK_CH3,
        'R_SLOPE_CFG': A.R3_SLOPE_CFG, 'R_SLOPE_THR': A.R3_SLOPE_THR,
        'R_SLOPE_HYST': A.R3_SLOPE_HYST, 'R_PZ_CFG': A.R3_PZ_CFG, 'R_PZ_MQ': A.R3_PZ_MQ,
        'R_PZ_THR': A.R3_PZ_THR, 'R_PZ_HYST': A.R3_PZ_HYST}
    assert not LIB.multitrigger_reg_info(LIB.multitrigger_reg_count())
    assert not LIB.multitrigger_reg_info(-1)


def test_las_dos_fachadas_nombran_los_mismos_registros():
    assert (A.R_SHIELD_CFG, A.R_TRIG_SNAP, A.R_FLAGS, A.R_OR_MASK_CH0) == (
        A.R3_SHIELD, A.R3_SNAPSHOT, A.R3_FLAGS, A.R3_OR_MASK)


def test_el_mapa_es_el_que_decodifica_el_rtl():
    """C y Python pueden coincidir y estar los dos mal: el RTL es el que manda."""
    if not os.path.exists(RTL):
        pytest.skip(f'no está {RTL}: en un paquete de release no va el RTL')
    with open(RTL) as f:
        rtl = f.read()
    regs = _regs_de_c()
    leidos = {int(h, 16) for h in re.findall(r"20'h([0-9A-Fa-f]+)\s*:",
                                             rtl[rtl.index('casez (sys_addr[19:0])'):])}
    familias = {regs[n] + 4 * ch for n in ('R_SLOPE_CFG', 'R_SLOPE_THR', 'R_SLOPE_HYST',
                                           'R_PZ_CFG', 'R_PZ_MQ', 'R_PZ_THR', 'R_PZ_HYST')
                for ch in CANALES}
    sueltos = {v for n, v in regs.items() if 'SLOPE' not in n and 'PZ' not in n}
    # 0x020, 0x024 y 0x028 existen y la API los usa por el puente legacy del slot 1.
    assert leidos - (familias | sueltos) == {0x020, 0x024, 0x028}
    assert (familias | sueltos) <= leidos

    escritos = {int(h, 16) for h in re.findall(r"sys_addr\[19:0\] == \(?20'h([0-9A-Fa-f]+)", rtl)}
    assert {v for n, v in regs.items() if n in (
        'R_SHIELD_CFG', 'R_OR_MASK_CH0', 'R_SLOPE_CFG', 'R_SLOPE_THR', 'R_SLOPE_HYST',
        'R_PZ_CFG', 'R_PZ_MQ', 'R_PZ_THR', 'R_PZ_HYST')} <= escritos
    assert 'CAPS[16] = 1' in rtl and 'CAPS[17] = 1' in rtl


def test_lo_que_retiene_el_modelo_es_lo_que_retiene_el_rtl():
    """El modelo de estos tests también sale del RTL: si no, probaría contra sí mismo."""
    if not os.path.exists(RTL):
        pytest.skip(f'no está {RTL}: en un paquete de release no va el RTL')
    with open(RTL) as f:
        rtl = f.read()
    assert 'parameter integer SLOPE_LW   = 5' in rtl and 'parameter integer SLOPE_GW   = 5' in rtl
    assert 'parameter integer SLOPE_TW   = 18' in rtl and 'parameter integer PZ_TW      = 18' in rtl
    assert 'parameter integer PZ_KW      = 5' in rtl and 'parameter integer PZ_MW      = 20' in rtl
    assert 'pz_sh[GZ*6 +: 6]         <= sys_wdata[29:24]' in rtl
    assert 'pz_en[GZ]                <= sys_wdata[31]' in rtl


def test_tabla_de_campos_es_campos():
    n = LIB.multitrigger_field_count()
    c = [LIB.multitrigger_field_info(i).contents for i in range(n)]
    assert [f.nombre.decode() for f in c] == list(A._CAMPOS)
    for f in c:
        assert (f.offset, f.shift, f.mascara) == A._CAMPOS[f.nombre.decode()]
        assert not f.bandera
    assert not LIB.multitrigger_field_info(n)
    assert not LIB.multitrigger_field_info(-1)
    assert A._CAMPOS == R._CAMPOS


def test_constantes_del_header_son_las_de_python():
    with open(HEADER) as f:
        h = f.read()

    def define(nombre):
        m = re.search(rf'#define {nombre}\s+(\(1u << \d+\)|0x[0-9A-Fa-f]+|\d+)', h)
        assert m, nombre
        return eval(m.group(1).replace('u', ''))                # noqa: S307

    for c, py in (('PHYS', A.MTRG_PHYS), ('SIZE', A.MTRG_SIZE), ('MAGIC', A.MTRG_MAGIC),
                  ('CAPS_HAS_SLOPE', A.CAPS_HAS_SLOPE), ('CAPS_HAS_PZ', A.CAPS_HAS_PZ),
                  ('SLOPE_LMAX', A.SLOPE_LMAX), ('SLOPE_GMAX', A.SLOPE_GMAX),
                  ('SLOPE_TMAX', A.SLOPE_TMAX), ('PZ_LMAX', A.PZ_LMAX),
                  ('PZ_MQMAX', A.PZ_MQMAX), ('PZ_TMAX', A.PZ_TMAX), ('N_CH', 4),
                  ('PZ_SHMAX', 63)):
        assert define(f'MULTITRIGGER_{c}') == py, c


def test_las_constantes_publicas_son_las_de_la_referencia():
    def publicas(m):
        return {n for n in dir(m) if n.isupper() and not n.startswith('_')}

    assert publicas(A) == publicas(R)
    for n in publicas(R):
        assert getattr(A, n) == getattr(R, n), n


def test_structs_del_mismo_tamanio():
    for tipo, py in (('multitrigger_shield_t', A._Shield), ('multitrigger_slope_t', A._Slope),
                     ('multitrigger_pz_t', A._Pz), ('multitrigger_status_t', A._Status)):
        assert LIB.multitrigger_sizeof(tipo.encode()) == ctypes.sizeof(py), tipo
    assert LIB.multitrigger_sizeof(b'no_existe') == 0
    assert LIB.multitrigger_sizeof(None) == 0


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


def test_otra_tabla_de_campos_lo_dice(monkeypatch):
    def cuenta():
        return 99
    monkeypatch.setattr(A, '_lib', None)
    monkeypatch.setattr(A._libmca, 'cargar', lambda: _Libreria(multitrigger_field_count=cuenta))
    with pytest.raises(OSError, match='99 campos'):
        A._cargar()


def test_un_struct_de_otro_tamanio_lo_dice(monkeypatch):
    def falso(tipo):
        return 1
    monkeypatch.setattr(A, '_lib', None)
    monkeypatch.setattr(A._libmca, 'cargar', lambda: _Libreria(multitrigger_sizeof=falso))
    with pytest.raises(OSError, match='no coinciden en multitrigger_shield_t'):
        A._cargar()


def test_misma_superficie_que_la_referencia():
    def funciones(m):
        return {n: f for n, f in vars(m).items() if n.startswith('multitrigger_') and callable(f)}

    fr, fa = funciones(R), funciones(A)
    assert set(fa) == set(fr)
    for n, f in fr.items():
        assert (str(inspect.signature(f)) == str(inspect.signature(fa[n]))), n
    for clase in ('MultiTrigger', 'MtRegion'):
        cr, ca = getattr(R, clase), getattr(A, clase)
        mr = {n for n in dir(cr) if not n.startswith('_')}
        ma = {n for n in dir(ca) if not n.startswith('_')}
        assert mr <= ma and ma - mr == {'impl'}, (clase, ma - mr)
        for n in mr - {'open'}:
            assert (str(inspect.signature(getattr(cr, n)))
                    == str(inspect.signature(getattr(ca, n)))), f'{clase}.{n}'
        pr = str(inspect.signature(cr.open))
        pa = str(inspect.signature(ca.open))
        assert pa == pr[:-1] + ', impl=None)', clase


def test_las_recetas_puras_son_las_mismas():
    for s in (0, 1, 0x1FFFFFFF, R.BIT_SLOPE_N1, R.BIT_PZ_P3):
        assert A.decode_snap(s) == R.decode_snap(s)
    assert A.pz_ganancia() == R.pz_ganancia()
    assert A.slope_pico(8, 4, escalon=100) == R.slope_pico(8, 4, escalon=100)
    assert A.BITS_OR_MASK == R.BITS_OR_MASK and A.BITS_SHIELD_SRC == R.BITS_SHIELD_SRC
    assert A.BITS_SHIELD_DST == R.BITS_SHIELD_DST


# =============================================================================
# MultiTrigger: máscaras, shield y snapshot
# =============================================================================

@pytest.mark.parametrize('m0, m1', [(0, None), (R.BIT_ADC_P0, R.BIT_ADC_N1), (0xFFFFFFFF, 0),
                                    (1, 2), (True, False), (np.int64(5), np.uint32(7))])
def test_set_or_mask_dos_canales(m0, m1):
    r, w = comparar(f'set_or_mask({m0!r}, {m1!r})',
                    lambda M, h: h.set_or_mask(m0, m1), clase='MultiTrigger')
    assert r == ('ok', None) and [o for o, _ in w] == [R.R_OR_MASK_CH0, R.R_OR_MASK_CH1]


def test_set_or_mask_por_defecto():
    r, w = comparar('set_or_mask()', lambda M, h: h.set_or_mask(), clase='MultiTrigger')
    assert w == [(R.R_OR_MASK_CH0, 0xFFFFFFFF), (R.R_OR_MASK_CH1, 0xFFFFFFFF)]


@pytest.mark.parametrize('off, ch', [(R.R_OR_MASK_CH0, 0), (R.R_OR_MASK_CH1, 1)])
def test_set_or_mask_que_no_latchea(off, ch):
    r, w = comparar(f'no latchea ch{ch}', lambda M, h: h.set_or_mask(0x12, 0x34),
                    clase='MultiTrigger', no_retiene=[off], **{str(off): 0})
    assert r[1] is AssertionError and f'OR_MASK ch{ch} no latcheada' in r[2]
    assert len(w) == 2, 'las dos se escriben antes de releer'


@pytest.mark.parametrize('v', [-1, 2 ** 32, 2 ** 33 + 5])
def test_set_or_mask_que_no_entra_en_32_bits(v):
    # Se escribe recortado y la relectura no coincide con lo pedido. El texto es otro
    # sólo en cómo se imprime el número.
    r, w = comparar(f'set_or_mask({v})', lambda M, h: h.set_or_mask(v, 0),
                    clase='MultiTrigger', mensaje=False)
    assert r[1] is AssertionError and w[0] == (R.R_OR_MASK_CH0, v & 0xFFFFFFFF)


@pytest.mark.parametrize('v', [1.5, 'x'])
def test_set_or_mask_que_no_es_entero(v):
    r, w = comparar(f'set_or_mask({v!r})', lambda M, h: h.set_or_mask(v, 0),
                    clase='MultiTrigger', mensaje=False)
    assert r[1] is TypeError and w == []


@pytest.mark.parametrize('channels, dur', [(3, 0), (1, 5), (0xF, 0xFFFF), (0x13, 0x12345),
                                           (0xFF, 7), (-1, -1), (True, False), (0, 0)])
def test_shield_autorearm(channels, dur):
    comparar(f'autorearm({channels}, {dur})',
             lambda M, h: h.configure_shield_autorearm(channels, dur), clase='MultiTrigger')


def test_shield_autorearm_por_defecto_y_no_prende_el_veto():
    r, w = comparar('autorearm()', lambda M, h: h.configure_shield_autorearm(),
                    clase='MultiTrigger')
    assert w == [(R.R_SHIELD_CFG, 0x0303)]
    r, w = comparar('autorearm con DST_MCA', lambda M, h: h.configure_shield_autorearm(0xFF),
                    clase='MultiTrigger')
    assert w == [(R.R_SHIELD_CFG, 0x0F0F)]


def test_disable_shield():
    r, w = comparar('disable_shield', lambda M, h: h.disable_shield(), clase='MultiTrigger')
    assert w == [(R.R_SHIELD_CFG, 0)]


@pytest.mark.parametrize('semilla', SEMILLAS)
@pytest.mark.parametrize('metodo', ['get_shield', 'read_snapshot', 'read_snapshot_raw',
                                    'get_flags'])
def test_multitrigger_lecturas(metodo, semilla):
    comparar(f'{metodo}[{semilla}]', lambda M, h: getattr(h, metodo)(),
             clase='MultiTrigger', semilla=semilla)


@pytest.mark.parametrize('ch', CANALES)
def test_multitrigger_get_or_mask(ch):
    comparar(f'get_or_mask({ch})', lambda M, h: h.get_or_mask(ch), clase='MultiTrigger')
    r, _ = comparar('get_or_mask()', lambda M, h: h.get_or_mask(), clase='MultiTrigger')
    assert r[0] == 'ok'


# =============================================================================
# MtRegion: los disparos propios
# =============================================================================

@pytest.mark.parametrize('caps', [0, R.CAPS_HAS_SLOPE, R.CAPS_HAS_PZ, CAPS_TODO, 0xFFFCFFFF])
@pytest.mark.parametrize('metodo', ['has_slope', 'has_pz'])
def test_capacidades(metodo, caps):
    comparar(f'{metodo} caps={caps:#x}', lambda M, h: getattr(h, metodo)(), caps=caps)


@pytest.mark.parametrize('ch', CANALES)
@pytest.mark.parametrize('kw', [dict(L=8, G=4, thr=600, hyst=300), dict(L=1, G=0, thr=1, hyst=0),
                                dict(L=16, G=31, thr=0x3FFFF, hyst=0x3FFFE),
                                dict(L=4, G=7, thr=10, hyst=10, en=False),
                                dict(L=4, G=7, thr=5, hyst=9, en=0),
                                dict(L=np.int64(4), G=np.uint8(2), thr=np.int32(9), hyst=1),
                                dict(L=4, G=7, thr=800, hyst=200, en='si')])
def test_set_slope(ch, kw):
    r, w = comparar(f'set_slope({ch}, {kw})', lambda M, h: h.set_slope(ch, **kw))
    assert r == ('ok', None)
    assert [o for o, _ in w] == [R.R3_SLOPE_THR + 4 * ch, R.R3_SLOPE_HYST + 4 * ch,
                                 R.R3_SLOPE_CFG + 4 * ch], 'umbrales antes que el habilitado'


@pytest.mark.parametrize('args', [(4, 8, 4, 600, 300), (-1, 8, 4, 600, 300), (0, 0, 4, 600, 300),
                                  (0, 17, 4, 600, 300), (0, -3, 4, 600, 300), (0, 8, -1, 600, 300),
                                  (0, 8, 32, 600, 300), (0, 8, 4, -1, 300), (0, 8, 4, 600, -1),
                                  (0, 8, 4, 0x40000, 1), (0, 8, 4, 600, 0x40000),
                                  (0, 8, 4, 300, 300), (0, 8, 4, 100, 300),
                                  (0, 2 ** 70, 4, 600, 300), (0, 8, 4, 2 ** 70, 300)])
def test_set_slope_rechaza_igual_y_sin_escribir(args):
    r, w = comparar(f'set_slope{args}', lambda M, h: h.set_slope(*args), mensaje=2 ** 70 not in args)
    assert r[1] is ValueError and w == []


@pytest.mark.parametrize('kw', [dict(L=1.0), dict(G=1.0), dict(thr=600.0), dict(L=None)])
def test_set_slope_que_no_es_entero(kw):
    args = {**dict(L=8, G=4, thr=600, hyst=300), **kw}
    r, w = comparar(f'set_slope({kw})', lambda M, h: h.set_slope(0, **args), mensaje=False)
    assert r[1] is TypeError and w == []


def test_set_slope_sin_capacidad():
    r, w = comparar('sin CAPS[16]', lambda M, h: h.set_slope(0, 8, 4, 600, 300), caps=R.CAPS_HAS_PZ)
    assert r[1] is RuntimeError and 'CAPS[16]' in r[2] and w == []


@pytest.mark.parametrize('base, n', [(R.R3_SLOPE_THR, 1), (R.R3_SLOPE_HYST, 2), (R.R3_SLOPE_CFG, 3)])
@pytest.mark.parametrize('ch', [0, 3])
def test_set_slope_se_corta_en_el_registro_que_no_retiene(base, n, ch):
    off = base + 4 * ch
    r, w = comparar(f'set_slope no retiene {off:#x}', lambda M, h: h.set_slope(ch, 8, 4, 600, 300),
                    no_retiene=[off], **{str(off): 0})
    assert r[1] is RuntimeError and 'no retuvo' in r[2] and len(w) == n


@pytest.mark.parametrize('ch', CANALES)
@pytest.mark.parametrize('semilla', SEMILLAS)
def test_get_slope_y_get_pz(ch, semilla):
    comparar(f'get_slope({ch})', lambda M, h: h.get_slope(ch), semilla=semilla)
    comparar(f'get_pz({ch})', lambda M, h: h.get_pz(ch), semilla=semilla)


def test_los_campos_se_leen_de_su_bit():
    """Con todo en cero salvo un bit, para que un campo corrido no se esconda en el azar
    de un modelo que coincide de los dos lados."""
    for base, op in ((R.R3_SLOPE_CFG, lambda h: h.get_slope(1)), (R.R3_PZ_CFG, lambda h: h.get_pz(1)),
                     (R.R3_FLAGS, lambda h: h.get_flags()), (R.R3_SHIELD, lambda h: h.get_shield())):
        off = base + (4 if base in (R.R3_SLOPE_CFG, R.R3_PZ_CFG) else 0)
        for bit in range(32):
            comparar(f'{off:#x} bit {bit}', lambda M, h: op(h),
                     **{str(off): 1 << bit})
    for bit in range(32):
        comparar(f'status bit {bit}', lambda M, h: M.multitrigger_get_status(h),
                 clase='MultiTrigger', **{str(R.R_SHIELD_RUN): 1 << bit})


@pytest.mark.parametrize('ch', CANALES)
@pytest.mark.parametrize('metodo, base', [('disable_slope', R.R3_SLOPE_CFG),
                                          ('disable_pz', R.R3_PZ_CFG)])
def test_disable(metodo, base, ch):
    r, w = comparar(f'{metodo}({ch})', lambda M, h: getattr(h, metodo)(ch))
    assert w == [(base + 4 * ch, 0)]


@pytest.mark.parametrize('ch', CANALES)
@pytest.mark.parametrize('kw', [dict(k=2, m=1, mq=3992, sh=10, thr=353, hyst=177),
                                dict(k=1, m=0, mq=0, sh=0, thr=1, hyst=0),
                                dict(k=31, m=0, mq=0xFFFFF, sh=63, thr=0x3FFFF, hyst=0x3FFFE),
                                dict(k=16, m=15, mq=1, sh=1, thr=2, hyst=1),
                                dict(k=2, m=1, mq=3992, sh=10, thr=5, hyst=9, en=False),
                                dict(k=2, m=1, mq=3992, sh=10, thr=9, hyst=5, en='si'),
                                dict(k=2, m=1, mq=3992, sh=10, thr=9, hyst=5, en=0),
                                dict(k=np.int64(2), m=np.uint8(1), mq=3992, sh=10, thr=2, hyst=1)])
def test_set_pz(ch, kw):
    r, w = comparar(f'set_pz({ch}, {kw})', lambda M, h: h.set_pz(ch, **kw))
    assert r == ('ok', None)
    assert [o for o, _ in w] == [R.R3_PZ_THR + 4 * ch, R.R3_PZ_HYST + 4 * ch,
                                 R.R3_PZ_MQ + 4 * ch, R.R3_PZ_CFG + 4 * ch]


@pytest.mark.parametrize('args', [(4, 2, 1, 3992, 10, 353, 177), (-1, 2, 1, 3992, 10, 353, 177),
                                  (0, 0, 1, 3992, 10, 353, 177), (0, -1, 1, 3992, 10, 353, 177),
                                  (0, 2, -1, 3992, 10, 353, 177), (0, 20, 12, 3992, 10, 353, 177),
                                  (0, 32, 0, 3992, 10, 353, 177), (0, 2, 1, -1, 10, 353, 177),
                                  (0, 2, 1, 0x100000, 10, 353, 177), (0, 2, 1, 3992, -1, 353, 177),
                                  (0, 2, 1, 3992, 64, 353, 177), (0, 2, 1, 3992, 10, -1, 177),
                                  (0, 2, 1, 3992, 10, 353, -1), (0, 2, 1, 3992, 10, 0x40000, 1),
                                  (0, 2, 1, 3992, 10, 100, 100), (0, 2, 1, 3992, 10, 100, 200)])
def test_set_pz_rechaza_igual_y_sin_escribir(args):
    r, w = comparar(f'set_pz{args}', lambda M, h: h.set_pz(*args))
    assert r[1] is ValueError and w == []


def test_set_pz_k_y_m_enormes_no_desbordan():
    # k + m se compara sin sumar en C: los dos pueden venir saturados a int64.
    h = handle(A, 'MtRegion', Modelo())
    for k, m in ((2 ** 63 - 1, 2 ** 63 - 1), (2 ** 70, 2 ** 70), (1, 2 ** 63 - 1)):
        with pytest.raises(ValueError, match='k \\+ m'):
            h.set_pz(0, k, m, 3992, 10, 353, 177)
    h.close()


def test_set_pz_sin_capacidad():
    r, w = comparar('sin CAPS[17]', lambda M, h: h.set_pz(0, 2, 1, 3992, 10, 353, 177),
                    caps=R.CAPS_HAS_SLOPE)
    assert r[1] is RuntimeError and 'CAPS[17]' in r[2] and w == []


@pytest.mark.parametrize('base, n', [(R.R3_PZ_THR, 1), (R.R3_PZ_HYST, 2), (R.R3_PZ_MQ, 3),
                                     (R.R3_PZ_CFG, 4)])
def test_set_pz_se_corta_en_el_registro_que_no_retiene(base, n):
    r, w = comparar(f'set_pz no retiene {base:#x}',
                    lambda M, h: h.set_pz(0, 2, 1, 3992, 10, 353, 177),
                    no_retiene=[base], **{str(base): 0})
    assert r[1] is RuntimeError and 'no retuvo' in r[2] and len(w) == n


@pytest.mark.parametrize('ch', CANALES)
@pytest.mark.parametrize('v', [0, 1, R.BIT_SLOPE_P0, 0xFFFFFFFF, -1, 2 ** 32 + 3, True])
def test_region_set_or_mask(ch, v):
    r, w = comparar(f'set_or_mask({ch}, {v})', lambda M, h: h.set_or_mask(ch, v))
    assert w == [(R.R3_OR_MASK + 4 * ch, int(v) & 0xFFFFFFFF)], 'sin relectura'


@pytest.mark.parametrize('ch', CANALES)
def test_region_get_or_mask(ch):
    comparar(f'get_or_mask({ch})', lambda M, h: h.get_or_mask(ch))


@pytest.mark.parametrize('src, dst, dur', [(1, 1, 0), (0x7F, 0x1F, 0xFFFF), (0xFF, 0x3F, 0x12345),
                                           (-1, -1, -1), (True, False, 3), (0, 0, 0)])
def test_set_shield(src, dst, dur):
    comparar(f'set_shield({src}, {dst}, {dur})', lambda M, h: h.set_shield(src, dst, dur))


def test_set_shield_dur_por_defecto():
    r, w = comparar('set_shield(1, 2)', lambda M, h: h.set_shield(1, 2))
    assert w == [(R.R3_SHIELD, 0x0201)]


@pytest.mark.parametrize('semilla', SEMILLAS)
@pytest.mark.parametrize('metodo', ['get_shield', 'get_flags', 'read_snapshot'])
def test_region_lecturas(metodo, semilla):
    comparar(f'{metodo}[{semilla}]', lambda M, h: getattr(h, metodo)(), semilla=semilla)


# =============================================================================
# Configuración en bloque
# =============================================================================

@pytest.mark.parametrize('semilla', SEMILLAS)
@pytest.mark.parametrize('nombre', ['multitrigger_get_config', 'multitrigger_get_status'])
def test_lecturas_en_bloque(nombre, semilla):
    comparar(f'{nombre}[{semilla}]', lambda M, h: getattr(M, nombre)(h),
             clase='MultiTrigger', semilla=semilla)


@pytest.mark.parametrize('campos', [
    dict(shield_src=3, shield_dst=3, shield_dur=7), dict(shield_dur=7, shield_src=3),
    dict(or_mask_ch0=0xFF), dict(or_mask_ch1=0xFF, or_mask_ch0=0xAA),
    dict(shield_dur=1, or_mask_ch1=2, shield_src=3, or_mask_ch0=4),
    dict(shield_src=0xFFF, shield_dst=0xFF, shield_dur=0x12345),
    dict(or_mask_ch0=-1), dict(shield_src=-1), dict(shield_src='7'), dict(shield_src=1.5),
    dict(shield_src=True), {}])
def test_configure(campos):
    r, w = comparar(f'configure({campos})', lambda M, h: M.multitrigger_configure(h, **campos),
                    clase='MultiTrigger')
    assert r == ('ok', None)


def test_configure_agrupa_y_respeta_el_orden_de_los_registros():
    r, w = comparar('orden', lambda M, h: M.multitrigger_configure(
        h, shield_dur=1, or_mask_ch1=2, shield_src=3, or_mask_ch0=4), clase='MultiTrigger',
        **{str(R.R_SHIELD_CFG): 0})
    assert w == [(R.R_SHIELD_CFG, (1 << 16) | 3), (R.R_OR_MASK_CH1, 2), (R.R_OR_MASK_CH0, 4)]


def test_configure_conserva_los_otros_campos_del_registro():
    r, w = comparar('rmw', lambda M, h: M.multitrigger_configure(h, shield_dst=2),
                    clase='MultiTrigger', **{str(R.R_SHIELD_CFG): 0x00050001})
    assert w == [(R.R_SHIELD_CFG, 0x00050201)]


@pytest.mark.parametrize('campos', [dict(nope=1), dict(shield_src=1, nope=2), dict(a=1, b=2)])
def test_configure_campo_desconocido_no_escribe(campos):
    r, w = comparar(f'configure({campos})', lambda M, h: M.multitrigger_configure(h, **campos),
                    clase='MultiTrigger')
    assert r[1] is ValueError and 'campos desconocidos' in r[2] and w == []


@pytest.mark.parametrize('v', ['x', None, [1]])
def test_configure_valor_que_no_convierte_no_escribe(v):
    r, w = comparar(f'configure(shield_src={v!r})',
                    lambda M, h: M.multitrigger_configure(h, or_mask_ch0=1, shield_src=v),
                    clase='MultiTrigger')
    assert r[0] == 'exc' and w == []


def test_configure_que_no_retiene_se_corta_ahi():
    off = R.R_SHIELD_CFG
    r, w = comparar('no retiene', lambda M, h: M.multitrigger_configure(
        h, or_mask_ch0=1, shield_src=2, or_mask_ch1=3), clase='MultiTrigger', no_retiene=[off],
        **{str(off): 0})
    assert r[1] is RuntimeError and 'no retuvo' in r[2] and 'bitstream correcto' in r[2]
    assert [o for o, _ in w] == [R.R_OR_MASK_CH0, off]


def test_configure_positional_es_un_typeerror():
    r, _ = comparar('positional', lambda M, h: M.multitrigger_configure(h, 1), clase='MultiTrigger',
                    mensaje=False)
    assert r[1] is TypeError


@pytest.mark.parametrize('metodo, args', [('w32', (R.R_OR_MASK_CH0, 0x102)), ('r32', (R.R3_FLAGS,)),
                                          ('w32', (R.R_SHIELD_CFG, -1))])
@pytest.mark.parametrize('clase', ['MultiTrigger', 'MtRegion'])
def test_acceso_crudo(clase, metodo, args):
    # Sin r32/w32 propios: entran a C, y C llega al buffer por el bus.
    m = Modelo()

    h = getattr(A, clase)(bytearray(m.reg.tobytes()), -1)
    hr = getattr(R, clase)(bytearray(m.reg.tobytes()), -1)
    assert getattr(h, metodo)(*args) == getattr(hr, metodo)(*args)
    assert bytes(h._mmap) == bytes(hr._mmap)
    h.close()


# =============================================================================
# Las secuencias que cruzan con el osciloscopio
# =============================================================================

class OscFalso:
    """Lo que las secuencias usan del osciloscopio, sobre un log común."""

    def __init__(self, log):
        self.log, self.reg = log, {}

    def w32(self, off, v):
        self.log.append(('osc', off, v & 0xFFFFFFFF))
        self.reg[off] = v & 0xFFFFFFFF

    def r32(self, off):
        return self.reg.get(off, 0)

    def acq_base(self, thr=0.0, delay=0, decim=1):
        self.log.append(('acq_base', thr, delay, decim))

    def set_raw_delay(self, delay):
        self.log.append(('raw_delay', delay))


def _secuencia(M, clase, op, **modelo):
    log = []
    osc = OscFalso(log)
    m = Modelo(osc=osc, **modelo)

    class H(getattr(M, clase)):
        def r32(self, off):
            return m.r32(off)

        def w32(self, off, v):
            log.append(('mt', off, int(v & 0xFFFFFFFF)))
            m.w32(off, v)

    h = H(None, -1)
    res = correr(lambda: op(M, osc, h))
    if M is A:
        h.close()
    return log, res


def comparar_secuencia(caso, clase, op, mensaje=True, **modelo):
    lr, rr = _secuencia(R, clase, op, **modelo)
    lc, rc = _secuencia(A, clase, op, **modelo)
    assert lc == lr, f'{caso}: secuencia distinta\n  py: {lr}\n  c:  {lc}'
    _igual_resultado(caso, rr, rc, mensaje)
    return lr, rr


@pytest.mark.parametrize('kw', [dict(), dict(auto_rearm=False), dict(delay=7),
                                dict(we_keep_both=False), dict(mask_ch0=R.BIT_ADC_N0, mask_ch1=0),
                                dict(thr=0.25, hyst=0.02)])
def test_multitrigger_arm(kw):
    log, r = comparar_secuencia(f'arm({kw})', 'MultiTrigger',
                                lambda M, o, h: M.multitrigger_arm(o, h, **kw))
    arm = next(i for i, x in enumerate(log) if x[:2] == ('osc', 0x000))
    masc = next(i for i, x in enumerate(log) if x[:2] == ('mt', R.R_OR_MASK_CH0))
    assert arm < masc, 'arm antes que la máscara'


def test_multitrigger_disarm():
    comparar_secuencia('disarm', 'MultiTrigger', lambda M, o, h: M.multitrigger_disarm(o, h))


@pytest.mark.parametrize('ch', [0, 1])
@pytest.mark.parametrize('kw', [dict(), dict(L=4, G=2, thr=1200, hyst=100), dict(fuente='pz'),
                                dict(fuente='pz', mq=3885, k=4, m=2, sh=11, thr_cuentas=30.0,
                                     hyst_cuentas=10.0)])
def test_armar_y_desarmar_mca(ch, kw):
    comparar_secuencia(f'armar_mca({ch}, {kw})', 'MtRegion',
                       lambda M, o, h: M.multitrigger_armar_mca(o, h, ch=ch, **kw))

    def ida_y_vuelta(M, o, h):
        M.multitrigger_armar_mca(o, h, ch=ch, **kw)
        estado = M.multitrigger_disparo_mca(h, ch)
        M.multitrigger_desarmar_mca(o, h, ch=ch)
        return estado, M.multitrigger_disparo_mca(h, ch)

    _, r = comparar_secuencia(f'ida y vuelta({ch}, {kw})', 'MtRegion', ida_y_vuelta)
    assert r[1][0]['armado'] and not r[1][1]['armado']


@pytest.mark.parametrize('ch', [2, 3])
def test_armar_sin_we_keep_lo_dice_igual(ch):
    # El modelo sólo tiene we_keep en los canales 0 y 1, como el 0x0909 de la secuencia.
    log, r = comparar_secuencia(f'sin we_keep {ch}', 'MtRegion',
                                lambda M, o, h: M.multitrigger_armar_mca(o, h, ch=ch))
    assert r[1] is RuntimeError and 'we_keep' in r[2]


@pytest.mark.parametrize('kw', [dict(ch=4), dict(ch=-1), dict(fuente='nivel'), dict(thr=100, hyst=200),
                                dict(L=0), dict(fuente='pz', k=20, m=12)])
def test_armar_rechaza_igual(kw):
    log, r = comparar_secuencia(f'armar({kw})', 'MtRegion',
                                lambda M, o, h: M.multitrigger_armar_mca(o, h, **kw))
    assert r[1] is ValueError


def test_armar_pz_sin_capacidad():
    log, r = comparar_secuencia('pz sin caps', 'MtRegion',
                                lambda M, o, h: M.multitrigger_armar_mca(o, h, fuente='pz'),
                                caps=R.CAPS_HAS_SLOPE)
    assert r[1] is RuntimeError and 'polo-cero' in r[2]


def test_desarmar_sin_pz_no_toca_el_pz():
    log, _ = comparar_secuencia('desarmar', 'MtRegion',
                                lambda M, o, h: M.multitrigger_desarmar_mca(o, h),
                                caps=R.CAPS_HAS_SLOPE)
    assert ('mt', R.R3_PZ_CFG, 0) not in log


# =============================================================================
# Lo que difiere a propósito
# =============================================================================
#
# `ch` fuera de 0..3. La referencia calcula `base + 4 * ch` sin mirarlo, y en las
# familias eso es OTRO registro: `disable_slope(4)` pone en cero el umbral del canal 0
# (0x060 + 16 = 0x070), sin ningún error. C lo rechaza y no toca nada.

@pytest.mark.parametrize('ch', [4, -1, 100])
@pytest.mark.parametrize('metodo, args, tocado', [
    ('disable_slope', (), lambda c: R.R3_SLOPE_CFG + 4 * c),
    ('disable_pz', (), lambda c: R.R3_PZ_CFG + 4 * c),
    ('set_or_mask', (7,), lambda c: R.R3_OR_MASK + 4 * c)])
def test_canal_fuera_de_rango_no_escribe_en_otro_registro(metodo, args, tocado, ch):
    mr = Modelo()
    getattr(handle(R, 'MtRegion', mr), metodo)(ch, *args)
    assert [o for o, _ in mr.escrituras] == [tocado(ch)], 'lo que hace la referencia'

    mc = Modelo()
    h = handle(A, 'MtRegion', mc)
    with pytest.raises(ValueError, match=f'canal {ch} fuera de 0..3'):
        getattr(h, metodo)(ch, *args)
    assert mc.escrituras == []
    h.close()


@pytest.mark.parametrize('ch', [4, -1])
@pytest.mark.parametrize('metodo', ['get_slope', 'get_pz', 'get_or_mask'])
def test_canal_fuera_de_rango_no_lee_otro_registro(metodo, ch):
    h = handle(A, 'MtRegion', Modelo())
    with pytest.raises(ValueError, match='fuera de 0..3'):
        getattr(h, metodo)(ch)
    h.close()


def test_get_or_mask_de_multitrigger_con_un_canal_invalido():
    # La referencia indexa una tupla: 4 es un IndexError, y -1 lee el canal 3.
    hr = handle(R, 'MultiTrigger', Modelo())
    with pytest.raises(IndexError):
        hr.get_or_mask(4)
    assert hr.get_or_mask(-1) == hr.get_or_mask(3)
    h = handle(A, 'MultiTrigger', Modelo())
    for ch in (4, -1):
        with pytest.raises(ValueError, match='fuera de 0..3'):
            h.get_or_mask(ch)
    h.close()


def test_desarmar_un_canal_invalido_ya_no_escribe():
    log, r = _secuencia(A, 'MtRegion', lambda M, o, h: M.multitrigger_desarmar_mca(o, h, ch=4))
    assert r[1] is ValueError and log == []


def test_la_relectura_de_set_or_mask_no_desaparece_con_python_o():
    # Es un `assert` en la referencia: con -O se va. En C es siempre.
    assert 'assert rb0 == mask_ch0' in inspect.getsource(R.MultiTrigger.set_or_mask)
    assert 'assert' not in re.sub(r'""".*?"""', '', inspect.getsource(A.MultiTrigger.set_or_mask),
                                  flags=re.S).replace('AssertionError', '')


# =============================================================================
# Abrir y cerrar
# =============================================================================

def _fichero(tmp_path, magic=R.MTRG_MAGIC, **regs):
    ruta = tmp_path / 'mt.bin'
    ruta.write_bytes(bytes(R.MTRG_SIZE))
    with open(ruta, 'r+b') as f:
        m = mmap.mmap(f.fileno(), R.MTRG_SIZE)
        struct.pack_into('<I', m, 0, magic)
        for off, v in regs.items():
            struct.pack_into('<I', m, int(off), v)
        m.close()
    return str(ruta)


def _redirigir_devmem(monkeypatch, ruta):
    real = os.open
    monkeypatch.setattr(os, 'open',
                        lambda p, fl, *a: real(ruta, os.O_RDWR) if p == '/dev/mem' else real(p, fl, *a))


@pytest.mark.parametrize('clase', ['MultiTrigger', 'MtRegion'])
def test_magic_malo_mismo_tipo_y_mismo_mensaje(tmp_path, monkeypatch, clase):
    ruta = _fichero(tmp_path, magic=0xDEADBEEF)
    _redirigir_devmem(monkeypatch, ruta)
    with pytest.raises(RuntimeError) as py:
        getattr(R, clase).open(phys=0, size=R.MTRG_SIZE)
    bus = _libmca.Bus.archivo(ruta, 0, R.MTRG_SIZE)
    with pytest.raises(RuntimeError) as c:
        getattr(A, clase)._sobre_bus(bus)
    # Sobre un bus suelto C no conoce la base; multitrigger_open dice la dirección.
    assert str(c.value) == str(py.value).replace('0x00000000', 'el bus', 1)
    assert 'MAGIC 0xdeadbeef' in str(c.value)
    assert bus.r32(0) == 0xDEADBEEF, 'el bus sigue siendo de quien lo abrió'
    bus.close()


def test_el_detalle_de_una_apertura_no_queda_pegado(tmp_path):
    ruta = _fichero(tmp_path, magic=1)
    bus = _libmca.Bus.archivo(ruta, 0, R.MTRG_SIZE)
    with pytest.raises(RuntimeError):
        A.MtRegion._sobre_bus(bus)
    assert LIB.multitrigger_last_error(None)
    h = A.MtRegion._sobre_bus(bus, check_magic=False)
    assert LIB.multitrigger_last_error(None) == b''
    h.close()


def test_sin_check_magic_no_lee_nada():
    m = Modelo(**{'0': 0})
    leidas = []
    bus = _libmca.Bus.callbacks(lambda off: leidas.append(off) or m.r32(off), m.w32)
    h = A.MultiTrigger._sobre_bus(bus, check_magic=False)
    assert leidas == []
    h.close()


def test_sin_permiso_es_un_oserror(monkeypatch):
    if os.geteuid() == 0:
        pytest.skip('como root /dev/mem se abre')
    monkeypatch.delenv('MCA_IMPL', raising=False)
    for clase in (A.MultiTrigger, A.MtRegion):
        with pytest.raises(OSError) as e:
            clase.open(impl='c')
        assert e.value.errno is not None and '/dev/mem' in str(e.value)


@pytest.mark.parametrize('clase, ops', [
    ('MultiTrigger', [lambda h: h.set_or_mask(1), lambda h: h.get_or_mask(0), lambda h: h.disable_shield(),
                      lambda h: h.get_shield(), lambda h: h.read_snapshot_raw(), lambda h: h.get_flags(),
                      A.multitrigger_get_config, A.multitrigger_get_status,
                      lambda h: A.multitrigger_configure(h, shield_src=1)]),
    ('MtRegion', [lambda h: h.has_slope(), lambda h: h.set_slope(0, 8, 4, 600, 300), lambda h: h.get_slope(0),
                  lambda h: h.disable_slope(0), lambda h: h.has_pz(), lambda h: h.get_pz(0),
                  lambda h: h.set_pz(0, 2, 1, 3992, 10, 353, 177), lambda h: h.set_or_mask(0, 1),
                  lambda h: h.set_shield(1, 1), lambda h: h.get_flags()])])
def test_excepcion_del_modelo_sale_intacta(clase, ops):
    class Roto(getattr(A, clase)):
        def r32(self, off):
            raise ZeroDivisionError('el modelo se rompió')

        def w32(self, off, v):
            raise ZeroDivisionError('el modelo se rompió')

    h = Roto(None, -1)
    for op in ops:
        with pytest.raises(ZeroDivisionError, match='se rompió'):
            op(h)
    h.close()


@pytest.mark.parametrize('clase', [A.MultiTrigger, A.MtRegion])
def test_sin_accesos_es_un_typeerror_y_no_una_recursion(clase):
    h = clase(None, -1)                 # se pueden asignar después: test_disparo_mca
    with pytest.raises(TypeError, match='redefina'):
        h.get_flags()
    h.close()


def test_los_accesos_se_pueden_asignar_a_la_instancia():
    m = Modelo()
    h = A.MtRegion(None, -1)
    h.r32, h.w32 = m.r32, m.w32
    h.set_or_mask(1, 0x12)
    assert m.escrituras == [(R.R3_OR_MASK + 4, 0x12)]
    assert h.get_or_mask(1) == 0x12
    h.close()


def test_sobre_un_buffer_las_dos_fachadas_ven_lo_mismo():
    mem = bytearray(R.MTRG_SIZE)
    struct.pack_into('<II', mem, 0, R.MTRG_MAGIC, CAPS_TODO)
    mt, mr = A.MultiTrigger(mem, -1), A.MtRegion(mem, -1)
    mt.set_or_mask(0x12, 0x34)
    assert (mr.get_or_mask(0), mr.get_or_mask(1)) == (0x12, 0x34)
    mr.set_shield(src=3, dst=3, dur=6)
    assert mt.get_shield()['dur'] == 6 and mt.get_shield()['runtime'] == 0
    assert 'runtime' not in mr.get_shield()
    assert struct.unpack_from('<I', mem, R.R_SHIELD_CFG)[0] == (6 << 16) | 0x0303
    with pytest.raises(ValueError):
        mt.r32(R.MTRG_SIZE)
    with pytest.raises(ValueError, match='alineado'):
        mr.w32(2, 0)
    mt.close()
    mr.close()
    mt.close()                          # idempotente


class _Prestado(bytearray):
    cerrados = 0

    def close(self):
        type(self).cerrados += 1


@pytest.mark.parametrize('clase', [A.MultiTrigger, A.MtRegion])
def test_un_buffer_prestado_no_se_cierra(clase):
    _Prestado.cerrados = 0
    h = clase(_Prestado(R.MTRG_SIZE), -1)
    h.close()
    assert _Prestado.cerrados == 0, 'con fd = -1 el mmap es de otro'


@pytest.mark.parametrize('clase', [A.MultiTrigger, A.MtRegion])
def test_lo_propio_se_cierra(clase):
    _Prestado.cerrados = 0
    fd = os.open('/dev/null', os.O_RDONLY)
    h = clase(_Prestado(R.MTRG_SIZE), fd)
    h.close()
    assert _Prestado.cerrados == 1
    with pytest.raises(OSError):
        os.fstat(fd)
    h.close()
    assert _Prestado.cerrados == 1


def test_handle_cerrado_no_rompe():
    h = A.MtRegion(bytearray(R.MTRG_SIZE), -1)
    h.close()
    for op in (lambda: h.get_flags(), lambda: h.r32(0), lambda: h.get_slope(0), lambda: h.disable_pz(0),
               lambda: h.set_or_mask(0, 1), lambda: h.has_pz()):
        with pytest.raises(ValueError):
            op()


def test_el_handle_es_un_context_manager(tmp_path):
    ruta = _fichero(tmp_path)
    bus = _libmca.Bus.archivo(ruta, 0, R.MTRG_SIZE)
    with A.MultiTrigger._sobre_bus(bus) as h:
        assert h.r32(0) == R.MTRG_MAGIC
    assert h._c is None and bus._p is None


def test_el_bus_propio_se_cierra_con_el_handle(tmp_path):
    ruta = _fichero(tmp_path)

    def mapeado():
        with open('/proc/self/maps') as f:
            return ruta in f.read()

    bus = _libmca.Bus.archivo(ruta, 0, R.MTRG_SIZE)
    assert mapeado()
    p = ctypes.c_void_p()
    assert LIB.multitrigger_open_bus(ctypes.byref(p), bus.ptr, 0, 1) == _libmca.MCA_OK
    LIB.multitrigger_close(p)
    assert mapeado(), 'el bus no era suyo'
    assert LIB.multitrigger_open_bus(ctypes.byref(p), bus.ptr, 1, 1) == _libmca.MCA_OK
    bus._p = None                       # ahora es del handle
    LIB.multitrigger_close(p)
    assert not mapeado()


def test_contrato_de_c_con_punteros_nulos():
    EINVAL = _libmca.MCA_EINVAL
    p = ctypes.c_void_p()
    v = ctypes.c_uint32()
    assert LIB.multitrigger_open(None, 0, 0, 0) == EINVAL
    assert LIB.multitrigger_open_bus(None, None, 0, 0) == EINVAL
    assert LIB.multitrigger_open_bus(ctypes.byref(p), None, 0, 0) == EINVAL
    LIB.multitrigger_close(None)
    assert LIB.multitrigger_r32(None, 0, ctypes.byref(v)) == EINVAL
    assert LIB.multitrigger_disable_shield(None) == EINVAL
    h = A.MtRegion(bytearray(R.MTRG_SIZE), -1)
    for fn in (LIB.multitrigger_get_caps, LIB.multitrigger_has_slope, LIB.multitrigger_has_pz,
               LIB.multitrigger_get_shield, LIB.multitrigger_get_snapshot, LIB.multitrigger_get_flags,
               LIB.multitrigger_get_status):
        assert fn(h._c, None) == EINVAL
    for fn in (LIB.multitrigger_get_or_mask, LIB.multitrigger_get_slope, LIB.multitrigger_get_pz):
        assert fn(h._c, 0, None) == EINVAL
    vals = (ctypes.c_uint32 * 5)()
    assert LIB.multitrigger_get_config(h._c, None, 5) == EINVAL
    assert LIB.multitrigger_get_config(h._c, vals, 4) == EINVAL
    assert LIB.multitrigger_get_config(h._c, vals, 5) == _libmca.MCA_OK
    idx = (ctypes.c_int32 * 1)(99)
    assert LIB.multitrigger_configure(h._c, idx, vals, 1) == EINVAL, 'índice fuera de la tabla'
    assert LIB.multitrigger_configure(h._c, idx, vals, -1) == EINVAL
    assert LIB.multitrigger_configure(h._c, None, None, 1) == EINVAL
    assert LIB.multitrigger_configure(h._c, None, None, 0) == _libmca.MCA_OK
    h.close()


# =============================================================================
# El backend real, sobre un fichero
# =============================================================================

@pytest.mark.parametrize('clase', ['MultiTrigger', 'MtRegion'])
def test_el_backend_devmem_ve_lo_mismo_que_el_mmap(tmp_path, monkeypatch, clase):
    regs = {str(R.R3_CAPS): CAPS_TODO, str(R.R_SHIELD_RUN): 0x30005, str(R.R_TRIG_SNAP): 0b11,
            str(R.R_FLAGS): 0x33}
    ruta = _fichero(tmp_path, **regs)
    _redirigir_devmem(monkeypatch, ruta)
    hr = getattr(R, clase).open(phys=0, size=R.MTRG_SIZE)
    hc = getattr(A, clase)._sobre_bus(_libmca.Bus.archivo(ruta, 0, R.MTRG_SIZE))
    assert hc.get_flags() == hr.get_flags()
    assert hc.read_snapshot() == hr.read_snapshot() == ['sw_any', 'adc_p0']
    assert hc.get_shield() == hr.get_shield()
    if clase == 'MtRegion':
        hc.set_slope(1, 8, 4, 600, 300)
        assert hr.get_slope(1) == hc.get_slope(1) == {'en': True, 'L': 8, 'G': 4, 'thr': 600, 'hyst': 300}
        hr.set_pz(2, 2, 1, 3992, 10, 353, 177)
        assert hc.get_pz(2) == hr.get_pz(2)
        hc.set_or_mask(3, 0xABCD)
        assert hr.get_or_mask(3) == 0xABCD
    else:
        hc.set_or_mask(0x12, 0x34)
        assert (hr.get_or_mask(0), hr.get_or_mask(1)) == (0x12, 0x34)
        A.multitrigger_configure(hc, shield_src=3, shield_dst=2)
        assert R.multitrigger_get_config(hr) == A.multitrigger_get_config(hc)
        assert R.multitrigger_get_status(hr) == A.multitrigger_get_status(hc)
    hc.close()
    hr.close()


# =============================================================================
# El despacho
# =============================================================================

@pytest.fixture
def ref_sobre_modelo(monkeypatch):
    m = Modelo(**{str(R.R_SHIELD_CFG): 0})
    for clase in ('MultiTrigger', 'MtRegion'):
        cls = getattr(R, clase)

        def abrir(c, *a, _clase=clase, **k):
            return handle(R, _clase, m)
        monkeypatch.setattr(cls, 'open', classmethod(abrir))
    return m


def test_impl_py_va_a_la_referencia(ref_sobre_modelo):
    h = A.MultiTrigger.open(impl='py')
    assert h._via == 'py' and h.impl == 'py' and isinstance(h, R.MultiTrigger)
    A.multitrigger_configure(h, shield_src=3)
    assert ref_sobre_modelo.escrituras == [(R.R_SHIELD_CFG, 3)]
    assert A.multitrigger_get_config(h)['shield_src'] == 3
    assert A.multitrigger_get_status(h)['fuentes'] == R.decode_snap(h.read_snapshot_raw())
    r = A.MtRegion.open(impl='py')
    assert r._via == 'py' and isinstance(r, R.MtRegion)


def test_mca_impl_elige(ref_sobre_modelo, monkeypatch):
    monkeypatch.setenv('MCA_IMPL', 'py')
    assert A.MtRegion.open()._via == 'py'
    monkeypatch.setenv('MCA_IMPL', 'nope')
    with pytest.raises(ValueError, match='nope'):
        A.MtRegion.open()


def test_sin_libmca_cae_a_python_y_lo_dice(ref_sobre_modelo, monkeypatch, capsys):
    monkeypatch.delenv('MCA_IMPL', raising=False)
    monkeypatch.setattr(_libmca, 'disponible', lambda: False)
    assert A.MultiTrigger.open()._via == 'py'
    assert 'libmca no está disponible' in capsys.readouterr().err


def test_la_firma_de_open_sigue_con_osc_primero(ref_sobre_modelo):
    # `MultiTrigger.open(osc=osc)` está en los docstrings de los dos módulos.
    assert A.MultiTrigger.open(object(), impl='py')._via == 'py'
    assert A.MultiTrigger.open(osc=object(), impl='py')._via == 'py'


def test_las_funciones_de_hardware_estan_registradas_en_su_modulo():
    from API._despacho import API_REGISTRADA
    nombres = {n for n, e in API_REGISTRADA.items() if e.modulo == 'API.multitrigger'}
    assert nombres == {'multitrigger_get_config', 'multitrigger_configure',
                       'multitrigger_get_status'}


# =============================================================================
# Abrir, y los sustitutos
# =============================================================================

def test_no_queda_acceso_a_la_pl_desde_python():
    """`region_mapeada` y `mapeo()` eran el lazo por evento en Python. Con el lazo en
    C (Parte 6) no queda quien los use."""
    import API.osciloscope as O
    assert not hasattr(A, 'region_mapeada') and not hasattr(A, '_mapear')
    assert not hasattr(A.MultiTrigger, 'mapeo') and not hasattr(O.Osciloscope, 'mapeo')


def test_open_con_exito_pasa_los_argumentos_y_recuerda_la_geometria(tmp_path, monkeypatch):
    """El camino que sólo corre en la placa: `multitrigger_open` se reemplaza por el
    mismo backend sobre un fichero, y el resto es el de verdad."""
    ruta = _fichero(tmp_path)
    _redirigir_devmem(monkeypatch, ruta)
    pedidos = []

    def abrir(pp, phys, size, check):
        pedidos.append((phys, size, check))
        bus = _libmca.Bus.archivo(ruta, 0, R.MTRG_SIZE)
        rc = LIB.multitrigger_open_bus(pp, bus.ptr, 1, check)
        bus._p = None                   # como en multitrigger_open: es del handle
        return rc

    monkeypatch.delenv('MCA_IMPL', raising=False)
    monkeypatch.setattr(A, '_cargar', lambda: _Libreria(multitrigger_open=abrir))
    h = A.MultiTrigger.open(phys=0, size=R.MTRG_SIZE, check_magic=False)
    assert pedidos == [(0, R.MTRG_SIZE, 0)] and isinstance(h, A.MultiTrigger)
    assert h._geo == (0, R.MTRG_SIZE)
    assert h.r32(0) == R.MTRG_MAGIC
    h.close()
    r = A.MtRegion.open(phys=0, size=R.MTRG_SIZE)
    assert pedidos[-1] == (0, R.MTRG_SIZE, 1) and isinstance(r, A.MtRegion)
    assert r.r32(0) == R.MTRG_MAGIC
    r.close()


@pytest.mark.parametrize('clase', ['MultiTrigger', 'MtRegion'])
@pytest.mark.parametrize('v', [1.5, None, 'x'])
def test_w32_no_trunca_lo_que_no_es_entero(clase, v):
    mem = bytearray(R.MTRG_SIZE)
    h = getattr(A, clase)(mem, -1)
    with pytest.raises(TypeError):
        h.w32(R.R_OR_MASK_CH0, v)
    assert not any(mem)
    h.close()


def test_el_multitrigger_simulado_corre_la_logica_de_c():
    from API.mca_remote import FakeMultiTrigger
    h = FakeMultiTrigger()
    assert isinstance(h, A.MultiTrigger) and h._c
    assert h.read_snapshot_raw() == 0b11 and h.read_snapshot() == ['sw_any', 'adc_p0']
    h.set_or_mask(0x12, 0x34)
    assert A.multitrigger_get_config(h)['or_mask_ch1'] == 0x34
    A.multitrigger_configure(h, shield_dur=9)
    assert h.get_shield()['dur'] == 9
    assert A.multitrigger_get_status(h)['fuentes'] == ['sw_any', 'adc_p0']
    h.close()
    h.close()


def test_la_prueba_de_placa_corre_contra_un_fichero(tmp_path, monkeypatch, capsys):
    """`placa/test_multitrigger_hw.py` no se estrena en la placa: acá corre contra un
    fichero. Sin el armado con el osciloscopio, que necesita el `we_keep` del RTL."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'test_multitrigger_hw', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             'placa', 'test_multitrigger_hw.py'))
    prueba = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prueba)
    ruta = _fichero(tmp_path, **{str(R.R3_CAPS): CAPS_TODO, str(R.R_FLAGS): 0x03,
                                 str(R.R_OR_MASK_CH0): 0x55, str(R.R_SHIELD_CFG): 0x0301,
                                 str(R.R3_SLOPE_THR): 77})
    _redirigir_devmem(monkeypatch, ruta)
    hr_mt = R.MultiTrigger.open(phys=0, size=R.MTRG_SIZE)
    hr_r = R.MtRegion.open(phys=0, size=R.MTRG_SIZE)
    hc_mt = A.MultiTrigger._sobre_bus(_libmca.Bus.archivo(ruta, 0, R.MTRG_SIZE))
    hc_r = A.MtRegion._sobre_bus(_libmca.Bus.archivo(ruta, 0, R.MTRG_SIZE))
    prueba.probar(hc_mt, hc_r, hr_mt, hr_r)
    salida = capsys.readouterr().out
    assert prueba._fail == 0, salida
    assert prueba._pass > 15 and 'FAIL' not in salida
    # Dejó todo como estaba.
    assert hc_r.get_or_mask(0) == 0x55 and hc_r.get_shield() == {'dur': 0, 'dst': 3, 'src': 1}
    assert hc_r.get_slope(0)['thr'] == 77
    for h in (hc_mt, hc_r, hr_mt, hr_r):
        h.close()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
