"""Tests offline de los generadores en libmca (`API/generadores.py`). NO necesitan la
placa.

El handle de `gen_pulsos` llega por `Bus.callbacks` a un modelo de sus registros que
sigue a `gen_pulsos.sv`: el ancho de cada campo, BASE y la tabla releídos con el signo
extendido, GEN_CNT, ESTADO y MAGIC de sólo lectura, y el estado que se reinicia en el
flanco de `en`. El lazo digital, a un modelo del `digital_loop` de HK (2 bits).

Las cuentas, contra los modelos de Python de los dos generadores
(`modulos/gen_eventos/modelos/python_model/`): el umbral por tasa, el DECAE por τ, la
Mq, el sigma del ruido, la tabla por CDF inversa y los disparos, ciclo por ciclo.

Y una contra lo que ya pasó en la placa: configurar los bloques de `tb_pulsos_mca`
con la API deja los registros como las escrituras crudas del TB, que en la placa dieron
lo mismo que la simulación (`docs/gen_eventos/generador_pulsos.md` §8).

Correr:  python3 -m pytest API/tests/test_libmca_generadores.py -v
"""

import ctypes
import os
import re
import sys
import time

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
_PRJ = os.path.dirname(_RAIZ)
_MODELOS = os.path.join(_PRJ, 'modulos', 'gen_eventos', 'modelos', 'python_model')
sys.path.insert(0, _MODELOS)

import API.generadores as G                                          # noqa: E402
from API import _libmca                                              # noqa: E402
from API._libmca import Bus, LibMCAError                             # noqa: E402

try:
    import gen_eventos_model as ge                                   # noqa: E402
    import gen_pulsos_model as gp                                    # noqa: E402
except ImportError:                 # en la placa: `make placa-sync` no copia modulos/
    ge = gp = None
sin_modelo = pytest.mark.skipif(ge is None, reason='sin los modelos de modulos/gen_eventos')

M32 = 0xFFFFFFFF
_RTL = os.path.join(_PRJ, 'modulos', 'gen_eventos', 'rtl', 'gen_pulsos.sv')
_HDR = os.path.join(_RAIZ, 'libmca', 'include', 'gen_pulsos.h')


# =============================================================================
# El modelo de los registros
# =============================================================================

class PulsosFalso:
    """Los registros de gen_pulsos.sv, con sus anchos. `avanza` pulsos por cada
    lectura de ESTADO con `en` prendido, hasta N. `no_retiene`: offsets cuyas
    escrituras se pierden."""

    ANCHO = {G.R_CTRL: 0x1F, G.R_DT_MIN: 0xFFFF, G.R_DECAE: 0xFFFF, G.R_SUBIDA: 0x7,
             G.R_AMP_N: 0x3FF, G.R_RUIDO: 0x10F}
    RESET = {G.R_CTRL: 0, G.R_PERIODO: 1000, G.R_UMBRAL: 0, G.R_DT_MIN: 2, G.R_N: 0,
             G.R_SEMILLA: 0, G.R_DECAE: 65280, G.R_SUBIDA: 0, G.R_AMP_N: 0, G.R_BASE: 0,
             G.R_RUIDO: 0}

    def __init__(self, magic=G.MAGIC, avanza=1, no_retiene=()):
        self.reg = dict(self.RESET)
        self.tabla = [0] * G.N_TABLA
        self.magic = magic
        self.gen_cnt = 0
        self.desborde = False
        self.avanza = avanza
        self.no_retiene = set(no_retiene)
        self.hk = 0
        self.log = []
        self.arranques = 0

    @staticmethod
    def s14(v):
        v &= 0x3FFF
        return v - 0x4000 if v & 0x2000 else v

    def hecho(self):
        n = self.reg[G.R_N]
        return n != 0 and self.gen_cnt >= n

    def r32(self, off):
        if off >= G.R_TABLA:
            return self.s14(self.tabla[(off - G.R_TABLA) >> 2]) & M32
        if off == G.R_GEN_CNT:
            return self.gen_cnt
        if off == G.R_ESTADO:
            en = self.reg[G.R_CTRL] & G.CTRL_EN
            if en and not self.hecho():
                self.gen_cnt += self.avanza
                if self.reg[G.R_N]:
                    self.gen_cnt = min(self.gen_cnt, self.reg[G.R_N])
            activo = bool(en) and not self.hecho()
            return int(activo) | (int(self.hecho()) << 1) | (int(self.desborde) << 2)
        if off == G.R_MAGIC:
            return self.magic
        if off == G.R_BASE:
            return self.s14(self.reg[G.R_BASE]) & M32
        return self.reg.get(off, 0)

    def w32(self, off, v):
        self.log.append((off, v))
        if off in self.no_retiene:
            return
        if off >= G.R_TABLA:
            self.tabla[(off - G.R_TABLA) >> 2] = v & 0x3FFF
            return
        if off not in self.reg:
            return                      # GEN_CNT, ESTADO, MAGIC: sólo lectura
        v &= self.ANCHO.get(off, M32)
        if off == G.R_BASE:
            v &= 0x3FFF
        if off == G.R_CTRL and (v & G.CTRL_EN) and not (self.reg[off] & G.CTRL_EN):
            self.gen_cnt, self.desborde = 0, False      # el arranque
            self.arranques += 1
        self.reg[off] = v

    def hk_r32(self, off):
        return self.hk if off == G.HK_LAZO else 0

    def hk_w32(self, off, v):
        self.log.append(('hk', off, v))
        if off == G.HK_LAZO:
            self.hk = v & 0x3

    def handle(self, hk=True, check_magic=True):
        bus = Bus.callbacks(self.r32, self.w32, size=G.SIZE)
        hkb = Bus.callbacks(self.hk_r32, self.hk_w32, size=G.HK_SIZE) if hk else None
        return G.GenPulsos.sobre(bus, hkb, check_magic=check_magic)

    def escrituras(self, off):
        return [v for o, v in self.log if o == off]


@pytest.fixture
def pf():
    return PulsosFalso()


@pytest.fixture
def g(pf):
    h = pf.handle()
    yield h
    h.close()


# =============================================================================
# El mapa
# =============================================================================

def test_registros_coinciden_con_libmca():
    nombres = {n[2:]: getattr(G, n) for n in dir(G) if n.startswith('R_')}
    assert G.registros() == nombres


@sin_modelo
def test_el_mapa_es_el_del_rtl():
    """Los offsets del comentario de registros de gen_pulsos.sv."""
    if not os.path.exists(_RTL):
        pytest.skip(f'no está {_RTL}: en un paquete de release no va el RTL')
    rtl = open(_RTL).read()
    del_rtl = {m.group(2): int(m.group(1), 16)
               for m in re.finditer(r'^//\s+0x([0-9A-Fa-f]{4}) R[W ]? +([A-Z_]+)', rtl, re.M)}
    assert del_rtl == G.registros()


@sin_modelo
def test_las_constantes_del_header():
    h = open(_HDR).read()

    def define(nombre):
        m = re.search(rf'#define {nombre}\s+(\(1u << \d+\)|0x[0-9A-Fa-f]+u?|-?\(?-?\d+\)?u?)', h)
        assert m, nombre
        return eval(m.group(1).replace('u', ''))                # noqa: S307

    for c, py in (('PHYS', G.PHYS), ('SIZE', G.SIZE), ('MAGIC', G.MAGIC),
                  ('N_TABLA', G.N_TABLA), ('AMP_MIN', G.AMP_MIN), ('AMP_MAX', G.AMP_MAX),
                  ('DECAE_RESET', G.DECAE_RESET), ('LAT_TRIG', G.LAT_TRIG),
                  ('LAT_DAT', G.LAT_DAT), ('CTRL_EN', G.CTRL_EN),
                  ('CTRL_ALEATORIO', G.CTRL_ALEATORIO), ('CTRL_AMP_ALEAT', G.CTRL_AMP_ALEAT),
                  ('CTRL_OUT1', G.CTRL_OUT1), ('CTRL_OUT2', G.CTRL_OUT2),
                  ('RUIDO_EN', G.RUIDO_EN), ('SAL_OUT1', G.SAL_OUT1), ('SAL_OUT2', G.SAL_OUT2),
                  ('HK_PHYS', G.HK_PHYS), ('HK_SIZE', G.HK_SIZE), ('HK_LAZO', G.HK_LAZO)):
        assert define(f'GEN_PULSOS_{c}') == py, c
    assert G.LAT_DAT == gp.LAT_DAT and G.N_TABLA == gp.N_TABLA
    assert G.DECAE_RESET == gp.CFG['decae'] and G.SEMILLA_0 == ge.SEMILLA_0


@sin_modelo
def test_la_configuracion_por_defecto_es_el_reset_del_modelo():
    c = G.config()
    assert {k: c[k] for k in gp.CFG} == {k: int(v) for k, v in gp.CFG.items()}
    assert c['salidas'] == G.SAL_OUT1


# =============================================================================
# El ciclo de vida
# =============================================================================

def test_sin_el_generador_en_el_slot():
    with pytest.raises(G.GenPulsosNotPresent, match='PUL1'):
        PulsosFalso(magic=0).handle()


def test_sin_check_magic_no_lee_nada():
    pf = PulsosFalso(magic=0)
    h = pf.handle(check_magic=False)
    assert pf.log == []
    h.close()


def test_r32_w32_crudos(g, pf):
    g.w32(G.R_PERIODO, 1234)
    assert pf.reg[G.R_PERIODO] == 1234 and g.r32(G.R_PERIODO) == 1234
    with pytest.raises(TypeError):
        g.w32(G.R_PERIODO, 1.5)
    with pytest.raises(ValueError):
        g.r32(0x2000)                    # fuera de la región


def test_cerrado():
    h = PulsosFalso().handle()
    h.close()
    with pytest.raises(ValueError, match='cerrado'):
        h.estado()
    h.close()                            # dos veces no rompe


# =============================================================================
# Configurar
# =============================================================================

@sin_modelo
def test_configurar_apaga_escribe_todo_y_relee(g, pf):
    pf.reg[G.R_CTRL] = G.CTRL_EN | G.CTRL_OUT1
    cfg = g.configurar(aleatorio=True, tasa=600e3, dt_min=3, n=300, semilla=44,
                       amp_aleat=True, tau=250.0, subida=5, amp_n=200, base=-100,
                       ruido=True, ruido_sh=4, salidas=G.SAL_OUT1 | G.SAL_OUT2)
    # CTRL: primero apagado, al final la configuración sin `en`
    assert pf.escrituras(G.R_CTRL) == [0, G.CTRL_ALEATORIO | G.CTRL_AMP_ALEAT
                                       | G.CTRL_OUT1 | G.CTRL_OUT2]
    assert pf.log[0] == (G.R_CTRL, 0)
    r = pf.reg
    assert r[G.R_UMBRAL] == ge.umbral_para(600e3, dt_min=3) == cfg['umbral']
    assert (r[G.R_DT_MIN], r[G.R_N], r[G.R_SEMILLA]) == (3, 300, 44)
    assert r[G.R_DECAE] == gp.decae_para(250.0) == cfg['decae']
    assert (r[G.R_SUBIDA], r[G.R_AMP_N]) == (5, 200)
    assert PulsosFalso.s14(r[G.R_BASE]) == -100
    assert r[G.R_RUIDO] == G.RUIDO_EN | 4
    assert g.leer_config() == cfg


def test_amp_n_1024_se_escribe_0_y_se_lee_1024(g, pf):
    g.configurar(amp_n=1024)
    assert pf.reg[G.R_AMP_N] == 0
    assert g.leer_config()['amp_n'] == 1024
    g.configurar()
    assert g.leer_config()['amp_n'] == 1024          # 0 también es la tabla entera


def test_periodico_por_tasa(g, pf):
    g.configurar(tasa=125e3)
    assert pf.reg[G.R_PERIODO] == 1000
    assert pf.reg[G.R_CTRL] & G.CTRL_ALEATORIO == 0


@pytest.mark.parametrize('kw, motivo', [
    (dict(periodo=1), 'periodo = 1'),
    (dict(aleatorio=True, umbral=0), 'umbral = 0'),
    (dict(aleatorio=True, umbral=5, dt_min=1), 'dt_min = 1'),
    (dict(dt_min=70000), 'DT_MIN tiene 16 bits'),
    (dict(aleatorio=2), 'aleatorio = 2'),
    (dict(decae=65536), 'DECAE tiene 16 bits'),
    (dict(subida=8), 'SUBIDA tiene 3 bits'),
    (dict(amp_n=1025), 'amp_n = 1025'),
    (dict(base=8192), 'base = 8192'),
    (dict(base=-8193), 'base = -8193'),
    (dict(ruido_sh=16), 'ruido_sh = 16'),
    (dict(salidas=4), 'salidas = 4'),
    (dict(amp_aleat=2), 'amp_aleat = 2'),
])
def test_lo_que_el_rtl_no_hace_no_se_escribe(g, pf, kw, motivo):
    with pytest.raises(ValueError, match=re.escape(motivo)):
        g.configurar(**kw)
    assert pf.log == []
    with pytest.raises(ValueError, match=re.escape(motivo)):
        G.validar(**kw)


@pytest.mark.parametrize('kw, msg', [
    (dict(tasa=1e3, umbral=5, aleatorio=True), 'tasa y umbral'),
    (dict(tasa=1e3, periodo=5), 'tasa y periodo'),
    (dict(tau=10, decae=5), 'tau y decae'),
])
def test_dos_formas_de_decir_lo_mismo(kw, msg):
    with pytest.raises(ValueError, match=msg):
        G.config(**kw)


def test_una_clave_que_no_es_del_generador():
    with pytest.raises(TypeError, match='trap_mq'):
        G.config(trap_mq=4080)


def test_un_registro_que_no_retiene_es_everify():
    pf = PulsosFalso(no_retiene={G.R_DECAE})
    h = pf.handle()
    with pytest.raises(LibMCAError, match='DECAE') as e:
        h.configurar(decae=1234)
    assert e.value.rc == _libmca.MCA_EVERIFY
    h.close()


# =============================================================================
# La tabla
# =============================================================================

def test_la_tabla_con_signo_y_el_resto_en_cero(g, pf):
    pf.tabla = [123] * G.N_TABLA
    amp = [-8192, -1, 0, 1, 8191, 4000]
    g.cargar_tabla(amp)
    assert [PulsosFalso.s14(v) for v in pf.tabla[:6]] == amp
    assert pf.tabla[6:] == [0] * (G.N_TABLA - 6)
    t = g.leer_tabla()
    assert t.dtype == np.int16 and list(t[:6]) == amp and not t[6:].any()
    assert list(g.leer_tabla(3)) == amp[:3]


def test_la_tabla_entera():
    pf = PulsosFalso()
    g = pf.handle()
    t = G.tabla_cdf([1500, 4000], [0.6, 0.4])
    g.cargar_tabla(t)
    np.testing.assert_array_equal(g.leer_tabla(), t)
    g.close()


@pytest.mark.parametrize('amp, motivo', [
    ([0, 8192], 'amp[1] = 8192'),
    ([-8193], 'amp[0] = -8193'),
    ([0.5], 'enteros'),
    (np.zeros(1025, int), '1025'),
    (np.zeros((2, 3), int), 'forma'),
])
def test_una_tabla_que_no_entra_no_se_escribe(g, pf, amp, motivo):
    with pytest.raises(ValueError, match=re.escape(motivo)):
        g.cargar_tabla(amp)
    assert pf.log == []


def test_una_entrada_que_no_retiene_es_everify():
    pf = PulsosFalso(no_retiene={G.R_TABLA + 4 * 7})
    pf.tabla[7] = 99
    g = pf.handle()
    with pytest.raises(LibMCAError, match=r'TABLA\[7\]') as e:
        g.cargar_tabla([5] * 10)
    assert e.value.rc == _libmca.MCA_EVERIFY
    g.close()


# =============================================================================
# Control, estado y el lazo
# =============================================================================

def test_arrancar_baja_y_sube_en_conservando_la_configuracion(g, pf):
    g.configurar(aleatorio=True, umbral=10, amp_aleat=True)
    cfg = pf.reg[G.R_CTRL]
    pf.log.clear()
    g.arrancar()
    assert pf.escrituras(G.R_CTRL) == [cfg, cfg | G.CTRL_EN]
    g.arrancar()                                     # prendido: vuelve a arrancar
    assert pf.escrituras(G.R_CTRL)[-2:] == [cfg, cfg | G.CTRL_EN]
    assert pf.arranques == 2
    g.parar()
    assert pf.reg[G.R_CTRL] == cfg


def test_estado(g, pf):
    pf.gen_cnt, pf.desborde = 17, True
    e = g.estado()
    assert e == dict(gen_cnt=17, estado=0b100, generando=False, terminado=False,
                     desborde=True)


def test_esperar_hasta_n():
    pf = PulsosFalso(avanza=7)
    g = pf.handle()
    g.configurar(n=50)
    g.arrancar()
    e = g.esperar(timeout_s=1.0)
    assert e['terminado'] and e['gen_cnt'] == 50 and not e['generando']
    g.close()


def test_esperar_sin_n_o_apagado(g, pf):
    g.configurar(n=0)
    g.arrancar()
    with pytest.raises(ValueError, match='N = 0'):
        g.esperar(0.1)
    g.configurar(n=10)
    with pytest.raises(ValueError, match='apagado'):
        g.esperar(0.1)


def test_esperar_vence():
    pf = PulsosFalso(avanza=0)
    g = pf.handle()
    g.configurar(n=10)
    g.arrancar()
    t0 = time.perf_counter()
    with pytest.raises(TimeoutError, match='GEN_CNT = 0'):
        g.esperar(timeout_s=0.05)
    assert time.perf_counter() - t0 < 1.0
    g.close()


def test_el_lazo_toca_solo_el_bit_0(g, pf):
    pf.hk = 0b10
    assert g.lazo is False
    g.lazo = True
    assert pf.hk == 0b11 and g.lazo is True
    g.lazo = False
    assert pf.hk == 0b10


def test_sin_hk_no_hay_lazo():
    pf = PulsosFalso()
    g = pf.handle(hk=False)
    with pytest.raises(LibMCAError, match='housekeeping') as e:
        g.lazo = True
    assert e.value.rc == _libmca.MCA_ENOSYS
    g.close()


def test_null_y_fuera_de_rango_en_c():
    lib = G._cargar()
    p = ctypes.c_void_p()
    assert lib.gen_pulsos_open_bus(None, None, 0, None, 0, 0) == _libmca.MCA_EINVAL
    assert lib.gen_pulsos_open_bus(ctypes.byref(p), None, 0, None, 0, 0) == _libmca.MCA_EINVAL
    lib.gen_pulsos_close(None)
    for fn in (lib.gen_pulsos_arrancar, lib.gen_pulsos_parar):
        assert fn(None) == _libmca.MCA_EINVAL
    assert lib.gen_pulsos_estado(None, None) == _libmca.MCA_EINVAL
    assert lib.gen_pulsos_reg_info(-1) is not None and not lib.gen_pulsos_reg_info(-1)
    assert not lib.gen_pulsos_reg_info(lib.gen_pulsos_reg_count())
    assert lib.gen_pulsos_sizeof(b'no_existe') == 0 and lib.gen_pulsos_sizeof(None) == 0
    h = PulsosFalso().handle()
    assert lib.gen_pulsos_estado(h.c, None) == _libmca.MCA_EINVAL
    assert lib.gen_pulsos_leer_config(h.c, None) == _libmca.MCA_EINVAL
    assert lib.gen_pulsos_cargar_tabla(h.c, None, 3) == _libmca.MCA_EINVAL
    assert lib.gen_pulsos_cargar_tabla(h.c, None, 0) == _libmca.MCA_OK
    h.close()


# =============================================================================
# Las cuentas, contra los modelos
# =============================================================================

@sin_modelo
@pytest.mark.parametrize('dt_min', [0, 2, 3, 5, 100])
def test_umbral_para_es_el_del_modelo(dt_min):
    for tasa in np.geomspace(1.0, 125e6 / max(dt_min, 2), 400):
        try:
            esperado = ge.umbral_para(float(tasa), dt_min=dt_min)
        except ValueError:
            with pytest.raises(ValueError, match='el máximo'):
                G.umbral_para(float(tasa), dt_min)
            continue
        assert G.umbral_para(float(tasa), dt_min) == esperado, (tasa, dt_min)


@pytest.mark.parametrize('tasa', [0, -1, float('nan'), float('inf')])
def test_una_tasa_que_no_es(tasa):
    with pytest.raises(ValueError):
        G.umbral_para(tasa)
    with pytest.raises(ValueError):
        G.periodo_para(tasa)


@sin_modelo
def test_periodo_para_y_la_tasa():
    assert G.periodo_para(125e3) == 1000 and G.periodo_para(62.5e6) == 2
    with pytest.raises(ValueError, match='el máximo'):
        G.periodo_para(100e6)
    assert G.tasa(periodo=1000) == 125e3
    for t, dt in ((200e3, 2), (1e6, 5), (600e3, 2)):
        u = G.umbral_para(t, dt)
        assert G.tasa(aleatorio=True, umbral=u, dt_min=dt) == pytest.approx(
            125e6 / ge.intervalo_medio(u, dt), rel=1e-15)
        assert G.tasa(aleatorio=True, umbral=u, dt_min=dt) == pytest.approx(t, rel=1e-6)


@sin_modelo
def test_decae_tau_y_sigma_son_los_del_modelo():
    for tau in np.r_[np.geomspace(0.05, 1e7, 3000), 186.0, 250.0, np.inf]:
        assert G.decae_para(float(tau)) == gp.decae_para(float(tau)), tau
    for d in range(1, 65536, 7):
        assert G.tau_de(d) == pytest.approx(gp.tau_de(d), rel=1e-14), d
    assert G.tau_de(0) == 0.0
    for sh in range(16):
        assert G.sigma_ruido(sh) == gp.sigma_ruido(sh)
    for malo in (0.0, -3.0, float('nan')):
        with pytest.raises(ValueError, match='tau'):
            G.decae_para(malo)
    with pytest.raises(ValueError):
        G.sigma_ruido(16)


@sin_modelo
def test_mq_es_la_de_la_cuenta_en_double_para_todo_decae():
    lib = G._cargar()
    v = ctypes.c_uint32()
    for d in range(65536):
        assert lib.gen_pulsos_mq(d, ctypes.byref(v)) == 0
        assert v.value == int(round(16.0 * gp.m_polo_cero(d))), d
    with pytest.raises(ValueError):
        G.mq_de(65536)


@sin_modelo
def test_tabla_cdf_es_la_del_modelo():
    casos = [([1500, 4000], [0.6, 0.4]),
             (np.r_[np.linspace(300, 6000, 200), 3000], np.r_[np.full(200, 0.6 / 200), 0.4]),
             ([100], [1.0]), ([-8192, 8191], [1, 1]), ([1, 2, 3], [0, 1, 0]),
             ([2.5, 3.5], [1, 1])]                   # el redondeo al par
    rng = np.random.default_rng(3)
    for _ in range(200):
        n = int(rng.integers(1, 300))
        casos.append((rng.uniform(-8000, 8000, n), rng.exponential(1.0, n)))
    for v, w in casos:
        np.testing.assert_array_equal(G.tabla_cdf(v, w), gp.tabla_cdf(v, w))


@pytest.mark.parametrize('v, w, motivo', [
    ([1, 2], [1, -1], 'pesos[1]'), ([1, 2], [0, 0], 'suman 0'), ([9000], [1], '9000'),
    ([], [], 'sin valores'), ([1, 2], [1], 'mismo largo'), ([1], [float('nan')], 'pesos[0]'),
])
def test_tabla_cdf_que_no_es(v, w, motivo):
    with pytest.raises(ValueError, match=re.escape(motivo)):
        G.tabla_cdf(v, w)


_U = (lambda t, dt_min=2: ge.umbral_para(t, dt_min=dt_min)) if ge else (lambda *a, **k: 1)
CFG_DISPAROS = [
    dict(aleatorio=False, periodo=7, n=200), dict(aleatorio=False, periodo=2, n=50),
    dict(aleatorio=False, periodo=1000),
    dict(aleatorio=True, umbral=_U(5e6, dt_min=3), dt_min=3, n=500, semilla=9),
    dict(aleatorio=True, umbral=_U(200e3), dt_min=2, n=150, semilla=11),
    dict(aleatorio=True, umbral=M32, dt_min=2, n=100),          # dispara cada 2
    dict(aleatorio=True, umbral=_U(1e6, dt_min=5), dt_min=5),
]


@sin_modelo
@pytest.mark.parametrize('cfg', CFG_DISPAROS)
def test_predecir_es_disparos_del_modelo(cfg):
    n_ciclos = 300_000
    esperado = ge.disparos(n_ciclos, **cfg)
    got = G.predecir(n_ciclos, ge.TS_DEL_DISPARO, n_max=len(esperado) + 10, **cfg)
    np.testing.assert_array_equal(got, esperado)
    if cfg.get('n'):
        assert len(got) == min(cfg['n'], len(got))
        np.testing.assert_array_equal(G.predecir(n_ciclos, 2, **cfg), esperado)


@sin_modelo
@pytest.mark.parametrize('cfg', CFG_DISPAROS[:5])
def test_predecir_es_el_trig_de_la_traza(cfg):
    t = gp.traza(20_000, [100], **cfg)
    p = G.predecir(20_000, G.LAT_TRIG, n_max=20_000, **cfg)
    np.testing.assert_array_equal(p[p < 20_000], t['trig'])


def test_predecir_sin_n_pide_n_max():
    with pytest.raises(ValueError, match='n_max'):
        G.predecir(1000, 1, periodo=10)
    assert list(G.predecir(1000, 0, n_max=3, periodo=10)) == [9, 19, 29]


# =============================================================================
# Los bloques de tb_pulsos_mca, por la API
# =============================================================================

_ESTIMULO = os.path.join(_RAIZ, 'monte-carlo', 'datos_ref', 'pulsos_estimulo.txt')


def _bloques_tb():
    """(kw del generador, tabla) de cada bloque, como los lee el script de placa."""
    tok = open(_ESTIMULO).read().split()
    i, out = 0, []
    claves = ('aleatorio', 'periodo', 'umbral', 'dt_min', 'n', 'semilla', 'amp_aleat',
              'amp_n', 'decae', 'subida', 'base', 'ruido', 'ruido_sh')
    while tok[i] != 'FIN':
        i += 50                                              # la línea B
        gg = [int(x) for x in tok[i + 1:i + 17]]
        i += 17
        n_tab = gg[14]
        tab = [int(x, 16) for x in tok[i:i + n_tab]]
        i += n_tab
        out.append((dict(zip(claves, gg[1:14])), [t - 0x4000 if t >= 0x2000 else t
                                                  for t in tab]))
    return out


@pytest.mark.skipif(not os.path.isfile(_ESTIMULO), reason='falta pulsos_estimulo.txt')
def test_los_bloques_del_tb_dejan_los_registros_como_las_escrituras_crudas():
    """Lo que en la placa dio igual a la simulación (2026-11-09) se escribió a mano,
    registro por registro, como el TB. Con la API tienen que quedar los mismos."""
    for gkw, tab in _bloques_tb():
        crudo = PulsosFalso()
        for o, v in ((0x04, gkw['periodo']), (0x08, gkw['umbral']), (0x0C, gkw['dt_min']),
                     (0x10, gkw['n']), (0x14, gkw['semilla']), (0x24, gkw['decae']),
                     (0x28, gkw['subida']), (0x2C, gkw['amp_n']), (0x30, gkw['base']),
                     (0x34, (gkw['ruido'] << 8) | gkw['ruido_sh'])):
            crudo.w32(o, v)
        for k in range(1024):
            crudo.w32(0x1000 + 4 * k, tab[k] if k < len(tab) else 0)
        crudo.w32(0x00, (gkw['aleatorio'] << 1) | (gkw['amp_aleat'] << 2) | (1 << 3))

        api = PulsosFalso()
        g = api.handle()
        g.configurar(**gkw)
        g.cargar_tabla(tab)
        g.close()
        assert api.reg == crudo.reg and api.tabla == crudo.tabla, gkw
