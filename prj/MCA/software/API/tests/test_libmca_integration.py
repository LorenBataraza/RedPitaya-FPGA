#!/usr/bin/env python3
"""La región de TOP en libmca hace lo mismo que la implementación Python.

La referencia es `API/ref_py/integration.py`, congelada. Cada caso corre la misma
operación sobre dos modelos de registros idénticos —uno detrás de la referencia,
otro detrás de libmca por el backend de callbacks— y exige, como
`test_libmca_equivalencia.py` con el MCA:

  1. **las mismas escrituras, en el mismo orden y con el mismo valor**, también
     en los casos de error;
  2. **el mismo resultado**: dicts con las mismas claves EN EL MISMO ORDEN, y los
     mismos tipos;
  3. **la misma excepción**: el mismo tipo y, salvo los casos marcados, el mismo
     mensaje.

Las lecturas no tienen que coincidir una a una: en esta región no tienen efecto
sobre la PL. Además se prueba lo que una equivalencia no ve: que las tablas de C
son las de Python y que el mapa es el que decodifica el RTL, que el despacho va a
donde dice, y que nada de esto se puede llamar por la op `call`.

    python -m pytest API/tests/test_libmca_integration.py -q
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

import API.integration as A                                         # noqa: E402
import API.ref_py.integration as R                                  # noqa: E402

LIB = A._cargar()

SOFT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEADER = os.path.join(SOFT, 'libmca', 'include', 'integration.h')
RTL = os.path.join(os.path.dirname(SOFT), 'modulos', 'comun', 'rtl',
                   'integration_cfg.sv')

CONSUMIDORES = ('osc', 'mtrg', 'mca', 'ring')
MODULOS_SLOT = ('osc', 'ring', 'mtrg', 'top', 'mca', 'pulsos')
ROUTES = {R.R_ROUTE_OSC, R.R_ROUTE_MTRG, R.R_ROUTE_MCA, R.R_ROUTE_RING}
SEMILLAS = range(8)


# =============================================================================
# El modelo y los dos handles
# =============================================================================

class Modelo:
    """Registros con la retención del RTL, que graban cada acceso.

    `no_retiene` son offsets cuyas escrituras se pierden: así se simula una
    relectura que no coincide.
    """

    def __init__(self, semilla=1, no_retiene=(), **fijos):
        rng = np.random.default_rng(semilla)
        self.reg = rng.integers(0, 2 ** 32, R.INTEGRATION_SIZE // 4,
                                dtype=np.uint64).astype(np.uint32)
        self.reg[R.R_MAGIC >> 2] = R.MAGIC
        for off, v in fijos.items():
            self.reg[int(off) >> 2] = v
        self.no_retiene = set(no_retiene)
        self.escrituras = []
        self.lecturas = []

    def r32(self, off):
        self.lecturas.append(off)
        return int(self.reg[off >> 2])

    def w32(self, off, v):
        v = int(v) & 0xFFFFFFFF
        self.escrituras.append((off, v))
        if off in self.no_retiene:
            return
        if off in ROUTES:
            v &= 0x103                          # {en[8], tap[1:0]}
        if off == R.R_CTRL:
            v &= R.CTRL_RUN                     # clear y srst son autolimpiantes
        self.reg[off >> 2] = v


def handle_ref(m):
    class H(R.Integration):
        def r32(self, off):
            return m.r32(off)

        def w32(self, off, v):
            m.w32(off, v)
    return H(None, -1)


def handle_c(m):
    class H(A.Integration):
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


def comparar(caso, op, preparar=None, mensaje=True, **modelo):
    """Corre `op(módulo, h)` de los dos lados y compara. Devuelve lo que dio."""
    mr, mc = Modelo(**modelo), Modelo(**modelo)
    hr, hc = handle_ref(mr), handle_c(mc)
    if preparar:
        preparar(R, hr)
        preparar(A, hc)
        mr.escrituras.clear()
        mc.escrituras.clear()
    rr = correr(lambda: op(R, hr))
    rc = correr(lambda: op(A, hc))
    assert mc.escrituras == mr.escrituras, (
        f'{caso}: escrituras distintas\n  py: {mr.escrituras}\n  c:  {mc.escrituras}')
    assert rr[0] == rc[0], f'{caso}: py dio {rr}, c dio {rc}'
    if rr[0] == 'ok':
        assert iguales(rr[1], rc[1]), (
            f'{caso}: resultado distinto\n  py: {rr[1]!r}\n  c:  {rc[1]!r}')
    else:
        assert issubclass(rc[1], rr[1]), f'{caso}: excepción {rc[1]} en vez de {rr[1]}'
        if mensaje:
            assert rc[2] == rr[2], f'{caso}: mensaje distinto\n  py: {rr[2]}\n  c:  {rc[2]}'
    hc.close()
    return rr, mr.escrituras


# =============================================================================
# Las tablas
# =============================================================================

def test_mapa_de_registros_es_el_de_python():
    regs = {LIB.integration_reg_info(i).contents.nombre.decode():
            LIB.integration_reg_info(i).contents.offset
            for i in range(LIB.integration_reg_count())}
    py = {n: getattr(A, n) for n in dir(A)
          if n.startswith('R_') and isinstance(getattr(A, n), int)}
    assert regs == py
    assert not LIB.integration_reg_info(LIB.integration_reg_count())
    assert not LIB.integration_reg_info(-1)


def test_el_mapa_es_el_que_decodifica_el_rtl():
    """C y Python pueden coincidir y estar los dos mal: el RTL es el que manda."""
    if not os.path.exists(RTL):
        pytest.skip(f'no está {RTL}: en un paquete de release no va el RTL')
    with open(RTL) as f:
        rtl = f.read()
    lectura = rtl[rtl.index('casez (sys_addr[19:0])'):]
    decodificados = {int(h, 16) for h in re.findall(r"20'h([0-9A-Fa-f]+)\s*:", lectura)}
    regs = {LIB.integration_reg_info(i).contents.offset
            for i in range(LIB.integration_reg_count())}
    assert regs == decodificados
    escritura = rtl[rtl.index('case (sys_addr[19:0])'):rtl.index('casez (sys_addr[19:0])')]
    assert ({int(h, 16) for h in re.findall(r"20'h([0-9A-Fa-f]+)\s*:", escritura)}
            == ROUTES | {R.R_CTRL})


def test_constantes_del_header_son_las_de_python():
    with open(HEADER) as f:
        h = f.read()

    def define(nombre):
        m = re.search(rf'#define {nombre}\s+(\(1u << \d+\)|0x[0-9A-Fa-f]+)', h)
        assert m, nombre
        return eval(m.group(1).replace('u', ''))                # noqa: S307

    assert define('INTEGRATION_PHYS') == A.INTEGRATION_PHYS
    assert define('INTEGRATION_SIZE') == A.INTEGRATION_SIZE
    assert define('INTEGRATION_MAGIC') == A.MAGIC
    assert define('INTEGRATION_BUS_BASE') == A.SYS_BUS_BASE
    assert define('INTEGRATION_BUS_SLOT') == A.SYS_BUS_SLOT
    assert define('INTEGRATION_PULSOS_OFFSET') == A.PULSOS_OFFSET
    for n in ('MOD_OSC', 'MOD_MTRG', 'MOD_MCA', 'MOD_RING', 'MOD_ASG', 'MOD_PID', 'MOD_PULSOS',
              'CTRL_RUN', 'CTRL_CLEAR', 'CTRL_SRST', 'ST_PLL_LOCKED', 'ST_ADC_RSTN'):
        assert define(f'INTEGRATION_{n}') == getattr(A, n), n


def test_las_constantes_publicas_son_las_de_la_referencia():
    def publicas(m):
        return {n for n in dir(m) if n.isupper() and not n.startswith('_')}

    assert publicas(A) == publicas(R)
    for n in publicas(R):
        assert getattr(A, n) == getattr(R, n), n
    for n in ('TAP_NATIVE', 'TAP_ADC', 'TAP_DEC_IN', 'TAP_BRAM_IN'):
        assert getattr(A, n) == A.TAP_NATIVE + ('TAP_NATIVE', 'TAP_ADC', 'TAP_DEC_IN',
                                                'TAP_BRAM_IN').index(n)


def test_nombres_de_las_tablas():
    assert tuple(LIB.integration_consumidor_name(i).decode()
                 for i in range(4)) == CONSUMIDORES == tuple(A._I_CONSUMIDOR)
    assert LIB.integration_consumidor_name(4) is None
    assert LIB.integration_consumidor_name(-1) is None
    assert tuple(LIB.integration_slot_name(i).decode()
                 for i in range(6)) == MODULOS_SLOT == tuple(A._I_SLOT)
    assert LIB.integration_slot_name(6) is None


def test_structs_del_mismo_tamanio():
    for tipo, py in (('integration_info_t', A._Info), ('integration_modules_t', A._Modules),
                     ('integration_slots_t', A._Slots), ('integration_caps_t', A._Caps),
                     ('integration_route_t', A._Route), ('integration_status_t', A._Status)):
        assert LIB.integration_sizeof(tipo.encode()) == ctypes.sizeof(py), tipo
    assert LIB.integration_sizeof(b'no_existe') == 0
    assert LIB.integration_sizeof(None) == 0


def test_un_so_viejo_lo_dice_y_no_da_un_attributeerror(monkeypatch):
    class Vieja:
        """Una libmca anterior a este bloque."""

    monkeypatch.setattr(A, '_lib', None)
    monkeypatch.setattr(A._libmca, 'cargar', lambda: Vieja())
    with pytest.raises(OSError, match='otra versión'):
        A._cargar()


def test_un_struct_de_otro_tamanio_lo_dice(monkeypatch):
    # Sin esto ctypes leería corrido, sin ningún error.
    class ConOtroStruct:
        def __getattr__(self, nombre):
            if nombre == 'integration_sizeof':
                def falso(tipo):
                    return 1
                return falso
            return getattr(LIB, nombre)

    monkeypatch.setattr(A, '_lib', None)
    monkeypatch.setattr(A._libmca, 'cargar', ConOtroStruct)
    with pytest.raises(OSError, match='no coinciden en integration_info_t'):
        A._cargar()


def test_misma_superficie_que_la_referencia():
    fr = {n: f for n, f in vars(R).items()
          if n.startswith('integration_') and callable(f)}
    fa = {n: f for n, f in vars(A).items()
          if n.startswith('integration_') and callable(f)}
    assert set(fa) == set(fr)
    for n, f in fr.items():
        pr = list(inspect.signature(f).parameters.values())
        pa = list(inspect.signature(fa[n]).parameters.values())
        # `impl` es lo único agregado: lo tiene también mca_open.
        if n == 'integration_open':
            assert pa[-1].name == 'impl' and pa[-1].default is None
            pa = pa[:-1]
        assert [(p.name, p.default) for p in pa] == [(p.name, p.default) for p in pr], n
    mr = {n for n in vars(R.Integration) if not n.startswith('_')}
    ma = {n for n in vars(A.Integration) if not n.startswith('_')}
    assert mr <= ma and ma - mr == {'impl'}


# =============================================================================
# Lecturas
# =============================================================================

LECTORES = ('integration_get_modules', 'integration_get_slots', 'integration_get_caps',
            'integration_get_routes', 'integration_get_route_osc',
            'integration_get_route_mtrg', 'integration_get_route_mca',
            'integration_get_route_ring', 'integration_get_run',
            'integration_get_status')


@pytest.mark.parametrize('nombre', LECTORES)
@pytest.mark.parametrize('semilla', SEMILLAS)
def test_lecturas(nombre, semilla):
    comparar(f'{nombre}[{semilla}]', lambda M, h: getattr(M, nombre)(h), semilla=semilla)


@pytest.mark.parametrize('semilla', SEMILLAS)
def test_identify(semilla, capsys):
    (_, info), _ = comparar('identify', lambda M, h: M.integration_identify(h, False),
                            semilla=semilla)
    assert info['magic'] == R.MAGIC and len(info['gith']) == 40
    assert capsys.readouterr().out == ''


def test_cada_campo_se_lee_de_su_bit():
    """Con todo en cero salvo un bit, para que un campo corrido no se esconda en
    el azar de un modelo que coincide de los dos lados."""
    for off in (R.R_MODULES, R.R_SLOTS, R.R_CAPS_0, R.R_CAPS_1, R.R_STATUS, R.R_VERSION,
                R.R_GITH_0, R.R_GITH_4):
        for bit in range(32):
            fijos = {str(o): 0 for o in (R.R_MODULES, R.R_SLOTS, R.R_CAPS_0, R.R_CAPS_1,
                                         R.R_STATUS, R.R_VERSION, R.R_GITH_0, R.R_GITH_4)}
            fijos[str(off)] = 1 << bit
            for nombre in ('integration_get_modules', 'integration_get_slots',
                           'integration_get_caps', 'integration_get_status'):
                comparar(f'{nombre} {off:#x} bit {bit}',
                         lambda M, h: getattr(M, nombre)(h), **fijos)
            comparar(f'identify {off:#x} bit {bit}',
                     lambda M, h: M.integration_identify(h, False), **fijos)


@pytest.mark.parametrize('modulo', MODULOS_SLOT)
@pytest.mark.parametrize('semilla', SEMILLAS)
def test_get_base(modulo, semilla):
    comparar(f'base {modulo}', lambda M, h: M.integration_get_base(h, modulo),
             semilla=semilla)
    comparar(f'.base {modulo}', lambda M, h: h.base(modulo), semilla=semilla)


def test_base_real_del_top_del_mca():
    h = handle_c(Modelo(**{str(R.R_SLOTS): 0x76321}))
    assert h.slots() == {'osc': 1, 'ring': 2, 'mtrg': 3, 'top': 6, 'mca': 7, 'pulsos': 0}
    assert h.base('mtrg') == 0x4030_0000 and h.base('mca') == 0x4070_0000
    h.close()


def test_base_del_generador_de_pulsos():
    """El de los bitstreams del 2026-11-09: el slot 2 partido con el ring, y el
    generador 64 KB arriba (SLOTS[23:20] = 2, MODULES bit 6)."""
    for impl in ('c', 'py'):
        h = (handle_c if impl == 'c' else handle_ref)(
            Modelo(**{str(R.R_SLOTS): 0x276321, str(R.R_MODULES): 0x4F}))
        assert h.slots()['pulsos'] == 2 and h.modules()['pulsos'], impl
        assert h.base('pulsos') == 0x4021_0000 and h.base('ring') == 0x4020_0000, impl
        if impl == 'c':
            h.close()


@pytest.mark.parametrize('malo', ['nope', '', 'asg', 3, None])
def test_get_base_de_lo_que_no_tiene_slot(malo):
    r, _ = comparar(f'base {malo!r}', lambda M, h: M.integration_get_base(h, malo))
    assert r[1] is KeyError


@pytest.mark.parametrize('c', CONSUMIDORES)
@pytest.mark.parametrize('w', [0x000, 0x100, 0x001, 0x101, 0x002, 0x102, 0x003, 0x103,
                               0xFFFFFEFC, 0xFFFFFFFF])
def test_get_route_cada_tap(c, w):
    off = {'osc': R.R_ROUTE_OSC, 'mtrg': R.R_ROUTE_MTRG,
           'mca': R.R_ROUTE_MCA, 'ring': R.R_ROUTE_RING}[c]
    comparar(f'get_route {c} {w:#x}', lambda M, h: h.get_route(c), **{str(off): w})
    comparar(f'get_routes {c} {w:#x}', lambda M, h: M.integration_get_routes(h),
             **{str(off): w})


def test_el_nativo_de_cada_consumidor_se_nombra():
    for c, off, nombre in (('osc', R.R_ROUTE_OSC, 'adc_bram_in (nativo)'),
                           ('mtrg', R.R_ROUTE_MTRG, 'adc_dly_in (nativo)'),
                           ('mca', R.R_ROUTE_MCA, 'adc_dec_in (nativo)'),
                           ('ring', R.R_ROUTE_RING, 'adc_dec_in (nativo)')):
        h = handle_c(Modelo(**{str(off): 0x100}))
        assert h.get_route(c) == {'tap': 0, 'nombre': nombre, 'enable': True}
        h.close()


@pytest.mark.parametrize('malo', ['nope', '', 'top', 1, None])
def test_get_route_de_lo_que_no_consume(malo):
    r, _ = comparar(f'get_route {malo!r}', lambda M, h: h.get_route(malo))
    assert r[1] is KeyError


# =============================================================================
# Escrituras
# =============================================================================

SET_ROUTE = ('integration_set_route_osc', 'integration_set_route_mtrg',
             'integration_set_route_mca', 'integration_set_route_ring')


@pytest.mark.parametrize('nombre', SET_ROUTE)
@pytest.mark.parametrize('tap', [0, 1, 2, 3, True, False, np.int64(2)])
@pytest.mark.parametrize('enable', [True, False, 0, 1, 2, '', 'x', None])
def test_set_route(nombre, tap, enable):
    comparar(f'{nombre}({tap!r}, {enable!r})',
             lambda M, h: getattr(M, nombre)(h, tap, enable))


@pytest.mark.parametrize('nombre', SET_ROUTE)
def test_set_route_por_defecto_vuelve_al_nativo_habilitado(nombre):
    r, w = comparar(nombre, lambda M, h: getattr(M, nombre)(h))
    assert r == ('ok', None) and len(w) == 1 and w[0][1] == 0x100


@pytest.mark.parametrize('c', CONSUMIDORES)
@pytest.mark.parametrize('tap', [4, 99, -1, 2 ** 40, -2 ** 40, np.int64(7)])
def test_tap_invalido_mismo_mensaje_y_no_escribe(c, tap):
    r, w = comparar(f'set_route({c}, {tap!r})', lambda M, h: h.set_route(c, tap))
    assert r[1] is ValueError and 'inválido' in r[2] and w == []


@pytest.mark.parametrize('tap', [None, 'x', 1.5])
def test_tap_que_no_es_entero(tap):
    # El valor no cruza a C (viaja como un centinela): mismo tipo, sin repetirlo.
    r, w = comparar(f'set_route(mca, {tap!r})', lambda M, h: h.set_route('mca', tap),
                    mensaje=False)
    assert r[1] is ValueError and w == []
    h = handle_c(Modelo())
    with pytest.raises(ValueError, match='^tap inválido; usar TAP_NATIVE'):
        h.set_route('mca', tap)
    h.close()


@pytest.mark.parametrize('tap', [1.0, []])
def test_tap_con_otro_tipo_de_excepcion_se_rechaza_igual(tap):
    # La única diferencia deliberada de tipo. La referencia da TypeError: `1.0`
    # pasa la validación y revienta en `tap & 3`, y `[]` no se puede buscar en el
    # dict. Las dos rechazan sin escribir; C da el error de un tap inválido.
    m = Modelo()
    h = handle_c(m)
    with pytest.raises(ValueError, match='inválido'):
        h.set_route('mca', tap)
    assert m.escrituras == []
    h.close()
    mr = Modelo()
    with pytest.raises(TypeError):
        handle_ref(mr).set_route('mca', tap)
    assert mr.escrituras == []


@pytest.mark.parametrize('malo', ['nope', '', 7, None])
def test_consumidor_invalido_no_escribe(malo):
    r, w = comparar(f'set_route({malo!r})', lambda M, h: h.set_route(malo, R.TAP_ADC))
    assert r[1] is KeyError and w == []


def test_primero_se_valida_el_tap_y_despues_el_consumidor():
    r, w = comparar('los dos mal', lambda M, h: h.set_route('nope', 99))
    assert r[1] is ValueError and w == []


@pytest.mark.parametrize('c, off', [('osc', R.R_ROUTE_OSC), ('mtrg', R.R_ROUTE_MTRG),
                                    ('mca', R.R_ROUTE_MCA), ('ring', R.R_ROUTE_RING)])
def test_relectura_que_no_coincide(c, off):
    # Mismo tipo (LibMCAError es un RuntimeError) y mismo mensaje, y la escritura
    # se hizo: lo que falló es lo que volvió.
    fijos = {str(off): 0x000}
    r, w = comparar(f'no latchea {c}', lambda M, h: h.set_route(c, R.TAP_BRAM_IN),
                    no_retiene=[off], **fijos)
    assert r[1] is RuntimeError and 'no latche' in r[2] and w == [(off, 0x103)]
    r, w = comparar(f'sin verify {c}',
                    lambda M, h: h.set_route(c, R.TAP_BRAM_IN, verify=False),
                    no_retiene=[off], **fijos)
    assert r == ('ok', None) and w == [(off, 0x103)]


@pytest.mark.parametrize('nombre, off', [('integration_set_route_osc', R.R_ROUTE_OSC),
                                         ('integration_set_route_mtrg', R.R_ROUTE_MTRG),
                                         ('integration_set_route_mca', R.R_ROUTE_MCA),
                                         ('integration_set_route_ring', R.R_ROUTE_RING)])
def test_las_funciones_siempre_verifican(nombre, off):
    r, w = comparar(nombre, lambda M, h: getattr(M, nombre)(h, R.TAP_ADC),
                    no_retiene=[off], **{str(off): 0})
    assert r[1] is RuntimeError and w == [(off, 0x101)]


def test_relectura_ignora_los_bits_que_no_son_del_campo():
    off = R.R_ROUTE_MCA
    r, _ = comparar('bits altos', lambda M, h: h.set_route('mca', R.TAP_ADC),
                    no_retiene=[off], **{str(off): 0xFFFF0101})
    assert r == ('ok', None)
    r, _ = comparar('enable distinto', lambda M, h: h.set_route('mca', R.TAP_ADC),
                    no_retiene=[off], **{str(off): 0x001})
    assert r[1] is RuntimeError


def test_reset_routes():
    r, w = comparar('reset_routes', lambda M, h: M.integration_reset_routes(h))
    assert r == ('ok', None)
    assert w == [(off, 0x100) for off in (R.R_ROUTE_OSC, R.R_ROUTE_MTRG,
                                          R.R_ROUTE_MCA, R.R_ROUTE_RING)]


def test_reset_routes_se_corta_donde_falla():
    off = R.R_ROUTE_MCA
    r, w = comparar('reset_routes corta', lambda M, h: h.reset_routes(),
                    no_retiene=[off], **{str(off): 0})
    assert r[1] is RuntimeError and 'ROUTE_MCA' in r[2]
    assert w == [(R.R_ROUTE_OSC, 0x100), (R.R_ROUTE_MTRG, 0x100), (off, 0x100)]


@pytest.mark.parametrize('on', [True, False, 0, 1, 2, '', 'x', None])
def test_set_run(on):
    comparar(f'set_run({on!r})', lambda M, h: M.integration_set_run(h, on))


def test_set_run_por_defecto():
    r, w = comparar('set_run()', lambda M, h: M.integration_set_run(h))
    assert w == [(R.R_CTRL, R.CTRL_RUN)]


@pytest.mark.parametrize('nombre, bit', [('integration_clear', R.CTRL_CLEAR),
                                         ('integration_soft_reset', R.CTRL_SRST)])
@pytest.mark.parametrize('run', [True, False])
def test_pulso_conserva_el_run(nombre, bit, run):
    r, w = comparar(f'{nombre} run={run}', lambda M, h: getattr(M, nombre)(h),
                    preparar=lambda M, h: M.integration_set_run(h, run))
    assert w == [(R.R_CTRL, bit | (R.CTRL_RUN if run else 0))]


def test_pulso_ignora_la_basura_de_los_otros_bits():
    # El RTL devuelve {31'h0, run}, pero la máscara es parte del contrato.
    r, w = comparar('clear', lambda M, h: M.integration_clear(h),
                    **{str(R.R_CTRL): 0xFFFFFFFE})
    assert w == [(R.R_CTRL, R.CTRL_CLEAR)]


# =============================================================================
# Los métodos, y lo que es composición
# =============================================================================

METODOS = [('modules', ()), ('slots', ()), ('caps', ()), ('routes', ()), ('status', ()),
           ('get_run', ()), ('reset_routes', ()), ('set_run', (True,)), ('set_run', (False,)),
           ('clear', ()), ('soft_reset', ()), ('get_route', ('mtrg',)),
           ('set_route', ('ring', R.TAP_DEC_IN, False)), ('base', ('top',)),
           ('identify', (False,)), ('r32', (R.R_SLOTS,)), ('w32', (R.R_ROUTE_OSC, 0x102))]


@pytest.mark.parametrize('nombre, args', METODOS,
                         ids=[f'{n}{a}' for n, a in METODOS])
def test_los_metodos(nombre, args):
    comparar(f'.{nombre}{args}', lambda M, h: getattr(h, nombre)(*args))


class _MCA:
    h_aw, h2_aw, psd_aw = 13, 7, 6


@pytest.mark.parametrize('caps1, ok', [((6 << 16) | (7 << 8) | 13, True),
                                       ((6 << 16) | (7 << 8) | 14, False)])
def test_geometria_coincide(caps1, ok):
    r, _ = comparar('geometria', lambda M, h: h.geometria_coincide(_MCA()),
                    **{str(R.R_CAPS_1): caps1})
    assert r[1][0] is ok


@pytest.mark.parametrize('semilla', SEMILLAS)
def test_dump_mismo_texto(semilla, capsys):
    def texto(M, h, volcar):
        volcar(M, h)
        return capsys.readouterr().out

    mr, mc = Modelo(semilla), Modelo(semilla)
    hr, hc = handle_ref(mr), handle_c(mc)
    esperado = texto(R, hr, lambda M, h: h.dump())
    assert 'región de TOP' in esperado and 'route ring' in esperado
    assert texto(A, hc, lambda M, h: h.dump()) == esperado
    assert texto(A, hc, lambda M, h: M.integration_dump(h)) == esperado
    assert mc.escrituras == [] and mr.escrituras == []
    hc.close()


@pytest.mark.parametrize('semilla', SEMILLAS)
def test_identify_verbose_mismo_texto(semilla, capsys):
    R.integration_identify(handle_ref(Modelo(semilla)))
    esperado = capsys.readouterr().out
    h = handle_c(Modelo(semilla))
    A.integration_identify(h)
    assert capsys.readouterr().out == esperado and esperado.startswith('región de TOP')
    h.close()


# =============================================================================
# Abrir y cerrar
# =============================================================================

def _fichero(tmp_path, magic=R.MAGIC, **regs):
    """Un fichero del tamaño de la región, como el MCA de `bench_impl.py --shm`."""
    ruta = tmp_path / 'top.bin'
    ruta.write_bytes(bytes(R.INTEGRATION_SIZE))
    with open(ruta, 'r+b') as f:
        m = mmap.mmap(f.fileno(), R.INTEGRATION_SIZE)
        struct.pack_into('<I', m, R.R_MAGIC, magic)
        for off, v in regs.items():
            struct.pack_into('<I', m, int(off), v)
        m.close()
    return str(ruta)


def _abrir_ref_sobre(ruta, monkeypatch, **kw):
    """La referencia abre /dev/mem: se le da el fichero, sin tocar su código."""
    real = os.open
    monkeypatch.setattr(R.os, 'open',
                        lambda p, fl: real(ruta, os.O_RDWR) if p == '/dev/mem' else real(p, fl))
    return R.Integration.open(0, R.INTEGRATION_SIZE, **kw)


def test_magic_malo_mismo_tipo_y_mismo_mensaje(tmp_path, monkeypatch):
    ruta = _fichero(tmp_path, magic=0xDEADBEEF)
    with pytest.raises(A.IntegrationNotPresent) as py:
        _abrir_ref_sobre(ruta, monkeypatch)
    bus = _libmca.Bus.archivo(ruta, 0, R.INTEGRATION_SIZE)
    with pytest.raises(A.IntegrationNotPresent) as c:
        A.Integration._sobre_bus(bus)
    # Sobre un bus suelto C no conoce la base; integration_open dice la dirección.
    assert str(c.value) == str(py.value).replace('0x00000000', 'el bus')
    assert 'MAGIC 0xdeadbeef' in str(c.value) and '"INTG"' in str(c.value)
    # El bus sigue siendo de quien lo abrió.
    assert bus.r32(R.R_MAGIC) == 0xDEADBEEF
    bus.close()


def test_el_detalle_de_una_apertura_no_queda_pegado(tmp_path):
    ruta = _fichero(tmp_path, magic=1)
    bus = _libmca.Bus.archivo(ruta, 0, R.INTEGRATION_SIZE)
    with pytest.raises(A.IntegrationNotPresent):
        A.Integration._sobre_bus(bus)
    assert LIB.integration_last_error(None)
    h = A.Integration._sobre_bus(bus, check_magic=False)
    assert LIB.integration_last_error(None) == b''
    h.close()


def test_sin_check_magic_no_lee_nada():
    m = Modelo(**{str(R.R_MAGIC): 0})
    h = handle_c(m)                     # el constructor no valida ni lee
    assert m.lecturas == [] and m.escrituras == []
    h.close()
    bus = _libmca.Bus.callbacks(m.r32, m.w32)
    p = A.Integration._sobre_bus(bus, check_magic=False)
    assert m.lecturas == []
    p.close()


def test_sin_permiso_es_un_oserror():
    if os.geteuid() == 0:
        pytest.skip('como root /dev/mem se abre')
    with pytest.raises(OSError) as e:
        A.Integration.open()
    assert e.value.errno is not None and '/dev/mem' in str(e.value)
    # Mismo tipo que la referencia.
    with pytest.raises(type(e.value)):
        R.Integration.open()


def test_excepcion_del_modelo_sale_intacta():
    class Roto(A.Integration):
        def r32(self, off):
            raise ZeroDivisionError('el modelo se rompió')

        def w32(self, off, v):
            raise ZeroDivisionError('el modelo se rompió')

    h = Roto(None, -1)
    for fn in (h.status, h.slots, h.routes, lambda: h.identify(False), h.clear,
               lambda: h.set_run(True), lambda: h.get_route('mca'),
               lambda: h.set_route('mca', 1), h.reset_routes, lambda: h.base('mca')):
        with pytest.raises(ZeroDivisionError, match='se rompió'):
            fn()
    h.close()


def test_sin_subclase_es_error_y_no_una_recursion():
    with pytest.raises(TypeError, match='redefina'):
        A.Integration(None, -1)


def test_sobre_un_buffer():
    m = bytearray(R.INTEGRATION_SIZE)
    struct.pack_into('<I', m, R.R_SLOTS, 0x76321)
    h = A.Integration(m, -1)
    assert h.base('mca') == 0x4070_0000
    h.set_route('mca', R.TAP_ADC)
    assert struct.unpack_from('<I', m, R.R_ROUTE_MCA)[0] == 0x101
    # C valida rango y alineación antes de llegar al buffer.
    with pytest.raises(ValueError):
        h.r32(R.INTEGRATION_SIZE)
    with pytest.raises(ValueError, match='alineado'):
        h.w32(2, 0)
    h.close()
    h.close()                           # idempotente


@pytest.mark.parametrize('v', [1.5, None, 'x'])
def test_w32_no_trunca_lo_que_no_es_entero(v):
    mem = bytearray(R.INTEGRATION_SIZE)
    h = A.Integration(mem, -1)
    with pytest.raises(TypeError):
        h.w32(R.R_ROUTE_MCA, v)
    assert not any(mem)
    h.close()


def test_handle_cerrado_no_rompe():
    h = A.Integration(bytearray(R.INTEGRATION_SIZE), -1)
    h.close()
    for fn in (h.status, h.slots, h.clear, lambda: h.r32(0), lambda: h.get_route('mca'),
               lambda: h.set_route('mca', 1), lambda: h.base('mca')):
        with pytest.raises(ValueError):
            fn()


def test_el_handle_es_un_context_manager(tmp_path):
    ruta = _fichero(tmp_path)
    bus = _libmca.Bus.archivo(ruta, 0, R.INTEGRATION_SIZE)
    with A.Integration._sobre_bus(bus) as h:
        assert h.identify(False)['magic'] == R.MAGIC
    assert h._c is None and bus._p is None


def test_el_bus_propio_se_cierra_con_el_handle(tmp_path):
    """Es lo que hace integration_open con el /dev/mem que mapeó: un handle
    cerrado no puede dejarlo mapeado (reprogramar la PL traba el puerto GP0)."""
    ruta = _fichero(tmp_path)

    def mapeado():
        with open('/proc/self/maps') as f:
            return ruta in f.read()

    bus = _libmca.Bus.archivo(ruta, 0, R.INTEGRATION_SIZE)
    assert mapeado()
    p = ctypes.c_void_p()
    assert LIB.integration_open_bus(ctypes.byref(p), bus.ptr, 0, 1) == _libmca.MCA_OK
    LIB.integration_close(p)
    assert mapeado(), 'el bus no era suyo'
    assert LIB.integration_open_bus(ctypes.byref(p), bus.ptr, 1, 1) == _libmca.MCA_OK
    bus._p = None                       # ahora es del handle
    LIB.integration_close(p)
    assert not mapeado()


def test_contrato_de_c_con_punteros_nulos():
    EINVAL = _libmca.MCA_EINVAL
    p = ctypes.c_void_p()
    v = ctypes.c_uint32()
    assert LIB.integration_open(None, 0, 0, 0) == EINVAL
    assert LIB.integration_open_bus(None, None, 0, 0) == EINVAL
    assert LIB.integration_open_bus(ctypes.byref(p), None, 0, 0) == EINVAL
    LIB.integration_close(None)
    assert LIB.integration_r32(None, 0, ctypes.byref(v)) == EINVAL
    assert LIB.integration_clear(None) == EINVAL
    assert LIB.integration_reset_routes(None) == EINVAL
    h = A.Integration(bytearray(R.INTEGRATION_SIZE), -1)
    for fn, args in ((LIB.integration_identify, ()), (LIB.integration_get_modules, ()),
                     (LIB.integration_get_slots, ()), (LIB.integration_get_caps, ()),
                     (LIB.integration_get_status, ()), (LIB.integration_get_run, ()),
                     (LIB.integration_get_base, (0,)), (LIB.integration_get_route, (0,))):
        assert fn(h._c, *args, None) == EINVAL
    assert LIB.integration_get_routes(h._c, None, 4) == EINVAL
    r = (A._Route * 4)()
    assert LIB.integration_get_routes(h._c, r, 3) == EINVAL
    assert LIB.integration_get_routes(h._c, r, 4) == _libmca.MCA_OK
    assert LIB.integration_get_base(h._c, 6, ctypes.byref(v)) == _libmca.MCA_ENOKEY
    assert LIB.integration_get_route(h._c, -1, r) == _libmca.MCA_ENOKEY
    assert LIB.integration_set_route(h._c, 4, 0, 1, 1) == _libmca.MCA_ENOKEY
    assert LIB.integration_set_route(h._c, -1, 9, 1, 1) == EINVAL
    h.close()


def test_el_codigo_nuevo_tiene_texto_y_su_excepcion():
    assert b'tabla' in LIB.mca_strerror(_libmca.MCA_ENOKEY)
    with pytest.raises(KeyError):
        _libmca.check(_libmca.MCA_ENOKEY)


# =============================================================================
# El backend real, sobre un fichero
# =============================================================================

def test_el_backend_devmem_ve_lo_mismo_que_el_mmap(tmp_path, monkeypatch):
    """`py` por un mmap como a /dev/mem, `c` por el backend devmem de libmca: los
    mismos bytes en el mismo fichero, y lo que escribe uno lo lee el otro."""
    regs = {str(R.R_VERSION): 0x01020304, str(R.R_GITH_0): 0xAAAAAAA0,
            str(R.R_GITH_4): 0xBBBBBBB4, str(R.R_MODULES): 0b001111,
            str(R.R_SLOTS): 0x76321, str(R.R_CAPS_0): (1 << 24) | (14 << 16) | (14 << 8) | 2,
            str(R.R_CAPS_1): (6 << 16) | (7 << 8) | 13, str(R.R_STATUS): 3}
    ruta = _fichero(tmp_path, **regs)
    hr = _abrir_ref_sobre(ruta, monkeypatch)
    bus = _libmca.Bus.archivo(ruta, 0, R.INTEGRATION_SIZE)
    hc = A.Integration._sobre_bus(bus)
    assert hc.identify(False) == hr.identify(False)
    assert hc.identify(False)['version'] == (1, 2, 3, 4)
    assert hc.identify(False)['gith'].startswith('bbbbbbb4')
    assert hc.identify(False)['gith'].endswith('aaaaaaa0')
    assert hc.modules() == hr.modules()
    assert hc.slots() == hr.slots()
    assert hc.caps() == hr.caps()
    assert hc.caps()['n_ch'] == 2 and hc.caps()['en_filt'] is True
    assert hc.status() == hr.status()
    hc.set_route('mca', R.TAP_ADC)
    assert hr.get_route('mca') == hc.get_route('mca') == {
        'tap': 1, 'nombre': 'adc_dat', 'enable': True}
    hr.set_route('osc', R.TAP_DEC_IN, enable=False)
    assert hc.get_route('osc') == hr.get_route('osc')
    hc.close()
    hr.close()


def test_la_prueba_de_placa_corre_contra_un_fichero(tmp_path, monkeypatch, capsys):
    """`placa/test_integration_hw.py` no se estrena en la placa: acá corre contra un
    fichero con el contenido del top del MCA, sólo sin los autolimpiantes del RTL."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'test_integration_hw', os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            'placa', 'test_integration_hw.py'))
    prueba = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prueba)
    regs = {str(R.R_MODULES): 0b000111, str(R.R_SLOTS): 0x76321, str(R.R_STATUS): 3,
            str(R.R_ROUTE_OSC): 0x100, str(R.R_ROUTE_MTRG): 0x100,
            str(R.R_ROUTE_MCA): 0x101, str(R.R_ROUTE_RING): 0x100}
    ruta = _fichero(tmp_path, **regs)
    hr = _abrir_ref_sobre(ruta, monkeypatch)
    hc = A.Integration._sobre_bus(_libmca.Bus.archivo(ruta, 0, R.INTEGRATION_SIZE))
    # Un fichero no autolimpia: el pulso queda escrito. Se lo saca como haría el RTL.
    clear, srst = hc.clear, hc.soft_reset

    def autolimpia(pulso):
        def f():
            pulso()
            hc.w32(R.R_CTRL, hc.r32(R.R_CTRL) & R.CTRL_RUN)
        return f

    hc.clear, hc.soft_reset = autolimpia(clear), autolimpia(srst)
    prueba.probar(hc, hr)
    salida = capsys.readouterr().out
    assert prueba._fail == 0, salida
    assert prueba._pass > 20 and 'FAIL' not in salida
    # Dejó el ruteo como estaba.
    assert hc.get_route('mca')['tap'] == R.TAP_ADC
    hc.close()
    hr.close()


# =============================================================================
# El despacho
# =============================================================================

@pytest.fixture
def ref_sobre_modelo(monkeypatch):
    m = Modelo(**{str(R.R_SLOTS): 0x76321})
    monkeypatch.setattr(R.Integration, 'open',
                        classmethod(lambda cls, *a, **k: handle_ref(m)))
    return m


def test_impl_py_va_a_la_referencia(ref_sobre_modelo):
    h = A.integration_open(impl='py')
    assert h._via == 'py' and h.impl == 'py' and isinstance(h, R.Integration)
    assert A.integration_get_slots(h)['mca'] == 7
    assert A.integration_get_base(h, 'mtrg') == 0x4030_0000
    A.integration_set_route_mca(h, R.TAP_ADC)
    assert ref_sobre_modelo.escrituras == [(R.R_ROUTE_MCA, 0x101)]


def test_mca_impl_elige(ref_sobre_modelo, monkeypatch):
    monkeypatch.setenv('MCA_IMPL', 'py')
    assert A.integration_open()._via == 'py'
    monkeypatch.setenv('MCA_IMPL', 'nope')
    with pytest.raises(ValueError, match='nope'):
        A.integration_open()


def test_sin_libmca_cae_a_python_y_lo_dice(ref_sobre_modelo, monkeypatch, capsys):
    monkeypatch.delenv('MCA_IMPL', raising=False)
    monkeypatch.setattr(_libmca, 'disponible', lambda: False)
    h = A.integration_open()
    assert h._via == 'py'
    assert 'libmca no está disponible' in capsys.readouterr().err


def test_por_defecto_es_c(monkeypatch):
    monkeypatch.delenv('MCA_IMPL', raising=False)
    abierto = []

    def falso(cls, *a):
        abierto.append(a)
        return 'el handle de C'

    monkeypatch.setattr(A.Integration, 'open', classmethod(falso))
    assert A.integration_open(0x1000, 0x2000, False) == 'el handle de C'
    assert abierto == [(0x1000, 0x2000, False)]


def test_las_excepciones_de_las_dos_son_la_misma():
    assert R.IntegrationNotPresent is A.IntegrationNotPresent


def test_sin_implementacion_conocida_es_un_error():
    h = handle_c(Modelo())
    h._via = 'marte'
    with pytest.raises(ValueError, match='marte'):
        A.integration_get_status(h)
    h._via = 'c'
    h.close()


def test_registradas_en_su_modulo():
    from API._despacho import API_REGISTRADA
    nombres = {n for n in API_REGISTRADA if n.startswith('integration_')}
    assert nombres == {n for n in vars(R) if n.startswith('integration_')
                       and n not in ('integration_open', 'integration_close',
                                     'integration_dump')}
    assert {API_REGISTRADA[n].modulo for n in nombres} == {'API.integration'}


# =============================================================================
# slot_base
# =============================================================================

@pytest.mark.parametrize('exc', [A.IntegrationNotPresent('no'), OSError('no'),
                                 PermissionError(13, 'no'), ValueError('no'),
                                 KeyError('no')])
def test_slot_base_devuelve_el_default(monkeypatch, exc):
    def abrir():
        raise exc
    monkeypatch.setattr(A, 'integration_open', abrir)
    assert A.slot_base('mca', 0x123) == 0x123
    assert A.slot_base('mca') is None


def test_slot_base_no_se_traga_lo_demas(monkeypatch):
    def abrir():
        raise RuntimeError('otra cosa')
    monkeypatch.setattr(A, 'integration_open', abrir)
    with pytest.raises(RuntimeError):
        A.slot_base('mca', 0x123)


def test_slot_base_lee_el_mapa_y_cierra(tmp_path, monkeypatch):
    ruta = _fichero(tmp_path, **{str(R.R_SLOTS): 0x76721})
    bus = _libmca.Bus.archivo(ruta, 0, R.INTEGRATION_SIZE)
    h = A.Integration._sobre_bus(bus)
    monkeypatch.setattr(A, 'integration_open', lambda: h)
    assert A.slot_base('mtrg', 0) == 0x4070_0000     # el red_pitaya_top clásico
    assert h._c is None


def test_slot_base_de_lo_que_no_tiene_slot_da_el_default(tmp_path, monkeypatch):
    ruta = _fichero(tmp_path)
    bus = _libmca.Bus.archivo(ruta, 0, R.INTEGRATION_SIZE)
    monkeypatch.setattr(A, 'integration_open', lambda: A.Integration._sobre_bus(bus))
    assert A.slot_base('nope', 0x77) == 0x77


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
