#!/usr/bin/env python3
"""libmca hace lo mismo que la implementación Python, función por función.

La referencia es `API/ref_py/mca2.py`, la implementación Python del mapa
"MCA2". Cada caso corre la misma operación sobre dos modelos de registros
idénticos —uno detrás de la referencia, otro detrás de libmca por el backend
de callbacks— y exige:

  1. **las mismas escrituras, en el mismo orden y con el mismo valor.** Es lo
     que ve la PL. Incluye los casos de error: un argumento inválido se
     rechaza en el mismo punto, así que lo que quedó escrito antes es igual
     (en `configure`, nada: valida todo antes de escribir).
  2. **el mismo resultado**: arreglos bit a bit, dicts con las mismas claves EN
     EL MISMO ORDEN (es el orden de la metadata guardada) y floats exactos.
  3. **la misma excepción**: el mismo tipo y, salvo los casos marcados, el
     mismo mensaje.
  4. en los relojes de 64 b, **la palabra baja antes que la alta**: leerla
     congela la alta en el RTL, y al revés la lectura se parte.

Las lecturas NO tienen que coincidir una a una: no tienen efecto sobre la PL
(salvo la del punto 4), y C lee una sola vez registros que Python leía dos.

Los registros arrancan con contenido aleatorio (misma semilla en los dos
lados), así contadores, último evento y espectros no son ceros que coinciden
por casualidad.

    python -m pytest API/tests/test_libmca_equivalencia.py -q
"""

import numpy as np
import pytest

from API import _libmca

if not _libmca.disponible():
    pytest.skip(f'libmca no está compilada ({_libmca.motivo()}): make -C libmca',
                allow_module_level=True)

import API.mca as A                                                 # noqa: E402
import API.ref_py.mca2 as R                                         # noqa: E402

CAPS = R.CAP_HIST_H | R.CAP_HIST_H_PSD
CAPS_TRAP = CAPS | R.CAP_TRAP
H_AW, H2_AW, PSD_AW = 14, 7, 6
N_ACC_MAX = 4
N_FORMAS = 4

# Pares (LO, HI) de los relojes de 64 b, con los t_ocup[j] de todas las j.
PARES_64 = ([(R.R_REALTIME_LO, R.R_REALTIME_HI), (R.R_LIVETIME_LO, R.R_LIVETIME_HI),
             (R.R_DEADTIME_LO, R.R_DEADTIME_HI), (R.R_VETOTIME_LO, R.R_VETOTIME_HI),
             (R.R_T_WIN_LO, R.R_T_WIN_HI), (R.R_T_DIV_LO, R.R_T_DIV_HI),
             (R.R_T_CLEAR_LO, R.R_T_CLEAR_HI)]
            + [(R.R_T_OCUP + 8 * j, R.R_T_OCUP + 8 * j + 4)
               for j in range(R.N_ACC_TOPE + 1)])
HI_A_LO = {hi: lo for lo, hi in PARES_64}


# =============================================================================
# El modelo y los dos handles
# =============================================================================

class Modelo:
    """Registros que retienen lo escrito y graban cada acceso.

    `no_retiene` son offsets cuyas escrituras se pierden: así se simula una
    relectura de configuración que no coincide.
    """

    def __init__(self, semilla=1, no_retiene=(), **fijos):
        rng = np.random.default_rng(semilla)
        self.reg = rng.integers(0, 2 ** 32, R.MCA_SIZE // 4,
                                dtype=np.uint64).astype(np.uint32)
        self.reg[R.R_MAGIC >> 2] = R.MAGIC
        self.reg[R.R_CAPS >> 2] = CAPS
        self.reg[R.R_WIDTHS >> 2] = (PSD_AW << 16) | (H2_AW << 8) | H_AW
        self.reg[R.R_N_ACC_MAX >> 2] = N_ACC_MAX
        # N_FORMAS de sólo lectura, y la compuerta larga: con basura al azar el
        # banco cambiaría de forma entre corridas.
        self.reg[R.R_N_FORMAS >> 2] = (N_FORMAS << 8) | 1
        # clear_busy y busy abajo: el clear termina y las ranuras se vacían.
        self.reg[R.R_STATUS >> 2] &= ~0x3
        # Relojes de 64 b en rango físico: la palabra alta < 2^19 son menos de
        # 2^51 ciclos (~7 meses a 125 MHz). Con eso las sumas entran exactas en
        # un double y la división es la misma de los dos lados; los valores
        # enormes van aparte, en test_counters_relojes_enormes.
        for _, hi in PARES_64:
            self.reg[hi >> 2] &= (1 << 19) - 1
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
        if off == R.R_CTRL:
            v &= ~(1 << 1)                       # clear autolimpiante
        if off == R.R_N_FORMAS:                  # sólo n_formas se escribe
            v = (int(self.reg[off >> 2]) & ~0x7) | (v & 0x7)
        self.reg[off >> 2] = v


def handle_ref(m, caps=CAPS):
    class H(R.MCA):
        def r32(self, off):
            return m.r32(off)

        def w32(self, off, v):
            m.w32(off, v)
    # `_read_words` de la referencia lee el mmap directo: se le da una vista
    # de los mismos registros (esas lecturas no se graban, los valores sí).
    return H(m.reg.view(np.uint8), -1, caps, H_AW, H2_AW, PSD_AW)


def handle_c(m, caps=CAPS):
    class H(A.MCA):
        def r32(self, off):
            return m.r32(off)

        def w32(self, off, v):
            m.w32(off, v)

        def _leer_bloque(self, off, n):
            m.lecturas.extend(off + 4 * i for i in range(n))
            return m.reg[off >> 2:(off >> 2) + n]
    return H(None, -1, caps, H_AW, H2_AW, PSD_AW)


# =============================================================================
# Comparación
# =============================================================================

def correr(fn):
    try:
        return ('ok', fn())
    except Exception as e:                                     # noqa: BLE001
        return ('exc', type(e), str(e))


def iguales(a, b):
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        return (isinstance(a, np.ndarray) and isinstance(b, np.ndarray)
                and a.dtype == b.dtype and a.shape == b.shape
                and np.array_equal(a, b))
    if isinstance(a, dict):
        return (isinstance(b, dict) and list(a) == list(b)
                and all(iguales(a[k], b[k]) for k in a))
    if isinstance(a, (tuple, list)):
        return (type(a) is type(b) and len(a) == len(b)
                and all(iguales(x, y) for x, y in zip(a, b)))
    return type(a) is type(b) and a == b


def lo_antes_que_hi(lecturas):
    for i, off in enumerate(lecturas):
        if off in HI_A_LO and (i == 0 or lecturas[i - 1] != HI_A_LO[off]):
            return False
    return True


def comparar(caso, op, preparar=None, caps=CAPS, mensaje=True, **modelo):
    """Corre `op(modulo, h)` de los dos lados y compara. `op` recibe el módulo
    (R o A) para llamar a la función del mismo nombre de cada uno."""
    mr, mc = Modelo(**modelo), Modelo(**modelo)
    hr, hc = handle_ref(mr, caps), handle_c(mc, caps)
    if preparar:
        preparar(R, hr)
        preparar(A, hc)
        mr.escrituras.clear(); mc.escrituras.clear()
        mr.lecturas.clear(); mc.lecturas.clear()
    rr = correr(lambda: op(R, hr))
    rc = correr(lambda: op(A, hc))

    assert mc.escrituras == mr.escrituras, (
        f'{caso}: escrituras distintas\n  py: {mr.escrituras}\n  c:  {mc.escrituras}')
    assert rr[0] == rc[0], f'{caso}: py dio {rr}, c dio {rc}'
    if rr[0] == 'ok':
        assert iguales(rr[1], rc[1]), f'{caso}: resultado distinto\n  py: {rr[1]!r}\n  c:  {rc[1]!r}'
    else:
        assert issubclass(rc[1], rr[1]), f'{caso}: excepción {rc[1]} en vez de {rr[1]}'
        if mensaje:
            assert rc[2] == rr[2], f'{caso}: mensaje distinto\n  py: {rr[2]}\n  c:  {rc[2]}'
    assert lo_antes_que_hi(mc.lecturas), f'{caso}: un reloj de 64 b se leyó HI antes que LO'
    hc.close()
    return rr


# =============================================================================
# Casos
# =============================================================================

# Los get/set por campo, sacados de la superficie de la referencia: si alguien
# agrega uno de un lado y no del otro, este test lo nota.
GETTERS = sorted(n for n in dir(R) if n.startswith('mca_get_'))
SETTERS = sorted(n for n in dir(R) if n.startswith('mca_set_'))

VALORES = [0, 1, 2, 5, 0x3FFF, 0x12345, 0xFFFFFFFF, -1, True, False]
ESPECIALES = {
    'mca_set_dec':       [1, 4, 0x10000, 0, -1],
    'mca_set_n_acc':     [1, 2, 4, 0, 5, 8, -1, True],
    'mca_set_pre_dly':   [0, 16, 127, 128, -1],
    'mca_set_trap_k':    [1, 64, 1023, 0, 1024, -5],
    'mca_set_trap_mq':   [0, 3885, 0xFFFFF, 0x100000, -1],
    'mca_set_n_formas':  [1, 2, 4, 0, 5, 8, -1, True],
    'mca_set_forma1_k':  [1, 32, 1023, 0, 1024, -5],
    'mca_set_forma2_k':  [1, 16, 1023, 0, 1024, -5],
    'mca_set_forma3_k':  [1, 8, 1023, 0, 1024, -5],
    'mca_set_zoom_1d_z': [0, 1, 2, 3, 30, -3],
    'mca_set_zoom_2dx_z': [0, 9, 30],
    'mca_set_zoom_2dy_z': [0, 10, 30],
    'mca_set_sel_1d':    [None, 'pico', 'psd', 't_subida', 3, 2.0, 6, 9, 10, -1],
    'mca_set_sel_2dx':   [None, 'integral', 4, 15, 'dt_anterior'],
    'mca_set_sel_2dy':   [None, 'ancho_inv', 0, 'solape'],
    'mca_set_discr_sel': [None, 'largo', 5, 99, 'trapecio', 'dt_siguiente'],
}
# Nombres de feature inexistentes: C no recibe el nombre (viaja como un
# centinela), así que el mensaje no lo repite. Mismo tipo, distinto texto.
NOMBRES_MALOS = {'mca_set_sel_1d': ['nope'], 'mca_set_discr_sel': ['']}


def test_hay_los_mismos_get_y_set():
    for n in GETTERS + SETTERS:
        assert hasattr(A, n), f'{n} está en la referencia y no en el binding'
    propios = sorted(n for n in dir(A) if (n.startswith('mca_get_')
                     or n.startswith('mca_set_')) and n != 'mca_get_metadata')
    assert propios == sorted(GETTERS + SETTERS), \
        set(propios) ^ set(GETTERS + SETTERS)


@pytest.mark.parametrize('nombre', GETTERS)
def test_getters(nombre):
    comparar(nombre, lambda M, h: getattr(M, nombre)(h))


@pytest.mark.parametrize('nombre', SETTERS)
def test_setters(nombre):
    for v in ESPECIALES.get(nombre, VALORES):
        comparar(f'{nombre}({v!r})', lambda M, h: getattr(M, nombre)(h, v))
    for v in NOMBRES_MALOS.get(nombre, []):
        comparar(f'{nombre}({v!r})', lambda M, h: getattr(M, nombre)(h, v),
                 mensaje=False)


def test_selector_trapecio_con_el_trapecio():
    for nombre in ('mca_set_sel_1d', 'mca_set_discr_sel'):
        comparar(f'{nombre}(trapecio) con CAPS bit 2',
                 lambda M, h: getattr(M, nombre)(h, 'trapecio'), caps=CAPS_TRAP)


SIN_BANCO = {str(R.R_N_FORMAS): 0}       # un bitstream con trapecio y sin banco


def test_selector_forma_necesita_el_banco():
    for nombre in ('mca_set_sel_1d', 'mca_set_sel_2dx', 'mca_set_discr_sel'):
        comparar(f'{nombre}(forma) con el banco',
                 lambda M, h: getattr(M, nombre)(h, 'forma'), caps=CAPS_TRAP)
        r = comparar(f'{nombre}(forma) sin el banco',
                     lambda M, h: getattr(M, nombre)(h, 'forma'), caps=CAPS_TRAP,
                     **SIN_BANCO)
        assert r[0] == 'exc' and 'banco de trapecios' in r[2]
        # el trapecio sigue valiendo: es lo que tiene ese bitstream
        r = comparar(f'{nombre}(trapecio) sin el banco',
                     lambda M, h: getattr(M, nombre)(h, 'trapecio'), caps=CAPS_TRAP,
                     **SIN_BANCO)
        assert r[0] == 'ok'


def test_n_formas_sin_el_banco():
    r = comparar('set n_formas=2 sin banco', lambda M, h: M.mca_set_n_formas(h, 2),
                 caps=CAPS_TRAP, **SIN_BANCO)
    assert r[0] == 'exc' and 'no tiene el banco' in r[2]
    comparar('set n_formas=1 sin banco', lambda M, h: M.mca_set_n_formas(h, 1),
             caps=CAPS_TRAP, **SIN_BANCO)


# El banco de la campaña: lo que da `mca_banco_config(3885, pre_dly=16)`.
BANCO = dict(n_formas=4, gate_long=112, pre_dly=16, trap_mq=3885,
             trap_k=64, trap_m=48, trap_off=87, trap_lw=4, trap_sh=15,
             trap_antes=97, trap_despues=96,
             forma1_k=32, forma1_m=24, forma1_off=47, forma1_lw=3, forma1_sh=14,
             forma1_antes=49, forma1_despues=48,
             forma2_k=16, forma2_m=12, forma2_off=27, forma2_lw=2, forma2_sh=13,
             forma2_antes=26, forma2_despues=24,
             forma3_k=8, forma3_m=8, forma3_off=18, forma3_lw=1, forma3_sh=12,
             forma3_antes=15, forma3_despues=13)

CONFIGS = {
    'defaults': {},
    'banco': BANCO,
    'banco_en_uso_2': {**BANCO, 'n_formas': 2},
    'banco_ventana_justa': {**BANCO, 'gate_long': 111},
    'banco_enmascarado': {**BANCO, 'forma1_off': 0x10000 + 47, 'forma1_lw': 8 + 3},
    # una sola forma: las otras no se miran, y sin ejes en F_TRAP tampoco su ventana
    'una_forma_compuerta_corta': dict(gate_long=64),
    'una_forma_trapecio_en_compuerta': dict(gate_long=96, trap_off=72, trap_lw=4),
    # --- errores del banco: cada uno en su punto, sin escrituras ---
    'n_formas_0': dict(n_formas=0),
    'n_formas_5': dict(n_formas=5),
    'n_formas_negativo': dict(n_formas=-1),
    'forma_k_0': dict(forma2_k=0),
    'forma_k_grande': dict(forma3_k=1024),
    'forma_km_grande': dict(forma1_k=1000, forma1_m=100),
    'banco_compuerta_104': {**BANCO, 'gate_long': 104},
    'banco_despues_afuera': {**BANCO, 'forma2_despues': 200},
    'banco_ganancia_k48': {**BANCO, 'forma1_k': 48},
    'banco_ganancia_sh': {**BANCO, 'forma3_sh': 13},
    'kw_desconocido': dict(forma4_k=8),
    'todos': dict(baseline=123, bl_auto=True, bl_k=13, bl_holdoff=7,
                  amp_min=11, amp_max=0xABCD, amp_src=1, q_shift=5, dec=4,
                  channel=1, gate_short=48, gate_long=400, n_acc=3,
                  pre_dly=20, trap_k=32, trap_m=16, trap_mq=3885,
                  trap_off=40, trap_lw=3, trap_sh=9),
    'features': dict(sel_1d='integral', sel_2dx=3, sel_2dy='dt_anterior',
                     zoom_1d=(2, 1), zoom_2dx=(20, 300), zoom_2dy=(1, 0),
                     discr=('psd', 10, 900), keep_if_full=False),
    'discr_externo': dict(discr=('pico', 500, 100, True)),
    'amp_src_defaults': dict(amp_src=True),
    'enmascarados': dict(baseline=-1, gate_long=0x12345, q_shift=99,
                         trap_lw=9, trap_sh=70, trap_off=0x1FFFF),
    'sin_verify': dict(bl_k=5, verify=False),
    'n_acc_tope': dict(n_acc=N_ACC_MAX, pre_dly=127, trap_k=1000, trap_m=23),
    # --- errores: cada uno en su punto, sin escrituras ---
    'dec_negativo': dict(dec=-5),
    'n_acc_0': dict(n_acc=0),
    'n_acc_de_mas': dict(n_acc=N_ACC_MAX + 1),
    'pre_dly_128': dict(pre_dly=128),
    'trap_k_0': dict(trap_k=0),
    'trap_km_grande': dict(trap_k=1000, trap_m=100),
    'trap_mq_grande': dict(trap_mq=1 << 20),
    'discr_vacio': dict(discr=('pico', 500, 100), verify=False),
    'sel_indice_malo': dict(sel_1d=12),
    'sel_2dy_malo': dict(sel_2dy=12),
    'sel_trapecio_sin_caps': dict(sel_1d='trapecio'),
    'discr_feature_mala': dict(discr=(11, 1, 2)),
}


@pytest.mark.parametrize('nombre', sorted(CONFIGS))
def test_configure(nombre):
    kw = CONFIGS[nombre]
    comparar(f'configure {nombre}', lambda M, h: M.mca_configure(h, **kw))
    comparar(f'MCA.configure {nombre}', lambda M, h: h.configure(**kw))


def test_configure_trapecio_con_caps():
    comparar('configure trapecio', lambda M, h: M.mca_configure(
        h, sel_1d='trapecio', discr=('trapecio', 0, 9000)), caps=CAPS_TRAP)


@pytest.mark.parametrize('kw', [dict(sel_1d='trapecio'), dict(sel_2dy='trapecio'),
                                dict(sel_2dx='forma'),
                                dict(discr=('trapecio', 0, 9000)),
                                dict(discr=('forma', 0, 3))])
def test_la_ventana_se_exige_si_se_la_usa(kw):
    # La compuerta de 64 no alcanza para la ventana del reset (72 + 8 + 16): da
    # igual sin nadie mirando F_TRAP, y es un error en cuanto alguien la mira.
    r = comparar(f'configure {kw}', lambda M, h: M.mca_configure(h, gate_long=64, **kw),
                 caps=CAPS_TRAP)
    assert r[0] == 'exc' and 'la ventana termina en 96' in r[2]
    # n_formas = 1 mira sólo la forma 0: las otras pueden no entrar
    r = comparar(f'configure {kw} entra', lambda M, h: M.mca_configure(
        h, gate_long=96, forma1_off=500, **kw), caps=CAPS_TRAP)
    assert r[0] == 'ok'


def test_configure_sin_banco_no_toca_sus_registros():
    registros = {R.R_N_FORMAS, R.R_TRAP_UMBR}
    for f in range(3):
        registros |= {R.R_FORMA1_KM + 16 * f + d for d in (0, 4, 8)}
    for kw in ({}, dict(forma1_k=33)):
        m = Modelo(**SIN_BANCO)
        h = handle_c(m, caps=CAPS_TRAP)
        A.mca_configure(h, **kw)
        assert not registros & {off for off, _ in m.escrituras}
        h.close()
        comparar(f'configure sin banco {kw}', lambda M, h: M.mca_configure(h, **kw),
                 caps=CAPS_TRAP, **SIN_BANCO)
    r = comparar('configure n_formas=2 sin banco',
                 lambda M, h: M.mca_configure(h, n_formas=2), caps=CAPS_TRAP, **SIN_BANCO)
    assert r[0] == 'exc' and 'no tiene el banco' in r[2]


def test_configure_vuelve_al_reset_del_banco():
    # configure es todo el estado: sin pasar el banco no queda nada del anterior.
    def op(M, h):
        M.mca_configure(h, **BANCO)
        M.mca_configure(h)
        return M.mca_get_config(h)
    cfg = comparar('banco y configure', op)[1]
    assert cfg['n_formas'] == 1 and cfg['trap_mq'] == 0
    assert (cfg['trap_antes'], cfg['trap_despues']) == (0, 0)
    assert (cfg['forma1_k'], cfg['forma1_m'], cfg['forma1_antes']) == (32, 16, 0)


def test_configure_invalido_no_escribe_nada():
    for nombre in ('dec_negativo', 'n_acc_0', 'pre_dly_128', 'trap_km_grande',
                   'sel_indice_malo', 'discr_vacio', 'n_formas_5', 'forma_k_0',
                   'forma_km_grande', 'banco_compuerta_104', 'banco_despues_afuera',
                   'banco_ganancia_k48'):
        m = Modelo()
        h = handle_c(m)
        with pytest.raises(ValueError):
            A.mca_configure(h, **CONFIGS[nombre])
        assert m.escrituras == [], nombre
        h.close()


def test_configure_relectura_de_n_formas():
    r = comparar('verify n_formas', lambda M, h: M.mca_configure(h, **BANCO),
                 no_retiene=(R.R_N_FORMAS,))
    assert r[0] == 'exc' and 'n_formas: escribi 4' in r[2]


def test_formas_ok_sólo_de_las_que_se_usan():
    def op(M, h):
        h.w32(R.R_TRAP_MED, 1 << 31)
        h.w32(R.R_FORMA1_MED, 0)
        h.w32(R.R_FORMA2_MED, 1 << 31)
        h.w32(R.R_FORMA3_MED, 1 << 31)
        res = []
        for n in (0, 1, 2, 3, 4, 7):
            h.w32(R.R_N_FORMAS, n)
            res.append(M.mca_get_formas_ok(h))
        return res
    r = comparar('formas_ok', op)
    assert r[1] == [[True], [True], [True, False], [True, False, True],
                    [True, False, True, True], [True, False, True, True]]


def test_configure_nombre_de_feature_malo():
    comparar('configure sel_1d=nope',
             lambda M, h: M.mca_configure(h, sel_1d='nope'), mensaje=False)


def test_configure_relectura_que_no_coincide():
    r = comparar('verify falla', lambda M, h: M.mca_configure(h, n_acc=3),
                 no_retiene=(R.R_N_ACC, R.R_DEC))
    assert r[0] == 'exc' and 'n_acc: escribi 3' in r[2]


def test_configure_sin_trapecio_no_relee_el_trapecio():
    # Un MCA2 sin el trapecio (el de la placa de la fase A) no tiene sus
    # registros: leen cero. configure no puede fallar por eso...
    sin = (R.R_TRAP_KM, R.R_TRAP_MQ, R.R_TRAP_MED)
    r = comparar('verify sin trapecio', lambda M, h: M.mca_configure(h),
                 no_retiene=sin)
    assert r[0] == 'ok'
    # ...y con el trapecio sí: ahí un registro que no retiene es un error.
    r = comparar('verify con trapecio', lambda M, h: M.mca_configure(h),
                 caps=CAPS_TRAP, no_retiene=sin)
    assert r[0] == 'exc' and 'trap_k: escribi 64' in r[2]


@pytest.mark.parametrize('nombre', ['mca_start', 'mca_stop', 'mca_clear'])
def test_control(nombre):
    comparar(nombre, lambda M, h: getattr(M, nombre)(h))
    comparar(f'MCA.{nombre[4:]}', lambda M, h: getattr(h, nombre[4:])())


def test_clear_timeout():
    # clear_busy pegado en 1: los dos se rinden con TimeoutError.
    comparar('clear timeout', lambda M, h: M.mca_clear(h, timeout_s=0.01),
             **{str(R.R_STATUS): 1})


@pytest.mark.parametrize('nombre', ['mca_read_histogram', 'mca_read_map2d',
                                    'mca_read_counters', 'mca_read_last_event'])
def test_lecturas(nombre):
    comparar(nombre, lambda M, h: getattr(M, nombre)(h))


@pytest.mark.parametrize('n_max', [0, 1, 4, 7, 12])
def test_counters_segun_las_ranuras(n_max):
    # t_ocup tiene N_ACC + 1 casilleros, con el tope de los 3 bits de n_acc.
    comparar(f'counters n_max={n_max}', lambda M, h: M.mca_read_counters(h),
             **{str(R.R_N_ACC_MAX): n_max})


def test_counters_sin_periodos():
    comparar('counters 0', lambda M, h: M.mca_read_counters(h),
             **{str(R.R_DEAD_PERIODS): 0})


def test_counters_relojes_enormes():
    # 2^64 ciclos son 4675 años: no pasa en la placa, pero la suma de los dos
    # relojes del tiempo muerto no puede dar la vuelta. Con sumas de más de 53
    # bits `deadtime_real_s` sigue siendo exacto (la conversión correctamente
    # redondeada de la suma, en los dos lados); la media divide por los
    # períodos y ahí C redondea dos veces y Python una: se admite 1 ulp.
    mr, mc = Modelo(), Modelo()
    for m in (mr, mc):
        for lo, hi in PARES_64[4:6]:                     # t_win, t_div
            m.reg[lo >> 2] = 0xFFFFFFFF
            m.reg[hi >> 2] = 0xFFFFFFF0
    a = R.mca_read_counters(handle_ref(mr))
    b = A.mca_read_counters(handle_c(mc))
    assert a['deadtime_real_s'] == b['deadtime_real_s']
    assert b['deadtime_real_s'] > 2 * 2 ** 63 / R.FS_HZ * 0.99      # no dio la vuelta
    assert b['dead_len_mean_s'] == pytest.approx(a['dead_len_mean_s'], rel=1e-15)
    a.pop('dead_len_mean_s'), b.pop('dead_len_mean_s')
    assert iguales(a, b)


def test_counters_cola_saturada():
    comparar('counters sat', lambda M, h: M.mca_read_counters(h),
             **{str(R.R_PUB_STATE): (7 << 16) | (4 << 8) | 2,
                str(R.R_N_ACC_MAX): 4})


def test_map2d_sin_motor_2d():
    comparar('map2d sin 2D', lambda M, h: M.mca_read_map2d(h),
             caps=R.CAP_HIST_H)


def test_baseline_now_negativo():
    comparar('baseline_now', lambda M, h: M.mca_get_baseline_now(h),
             **{str(R.R_BASELINE_NOW): 0x2005})


@pytest.mark.parametrize('variante', ['mca2', 'mca1'])
def test_features_e_identify(variante):
    modelo = {'mca2': {}, 'mca1': {str(R.R_MAGIC): R.MAGIC_MCA1}}[variante]
    comparar(f'tiene_features {variante}', lambda M, h: h.tiene_features(), **modelo)
    comparar(f'exigir_features {variante}', lambda M, h: h.exigir_features(), **modelo)
    comparar(f'identify {variante}',
             lambda M, h: M.mca_identify(h, verbose=False), **modelo)
    comparar(f'identify {variante} con trapecio',
             lambda M, h: M.mca_identify(h, verbose=False), caps=CAPS_TRAP,
             **modelo)


def test_acceso_crudo():
    comparar('r32', lambda M, h: h.r32(R.R_AMP_MAX))
    comparar('w32', lambda M, h: h.w32(R.R_AMP_MAX, 0x1234))
    comparar('_r64', lambda M, h: h._r64(R.R_REALTIME_LO, R.R_REALTIME_HI))
    comparar('_read_words', lambda M, h: h._read_words(R.APERTURE_H, 300))
    comparar('channel', lambda M, h: h.channel)
    comparar('running', lambda M, h: h.running)


@pytest.mark.parametrize('clear_first', [True, False])
def test_acquire(clear_first):
    comparar(f'acquire {clear_first}',
             lambda M, h: M.mca_read_acquire(h, 0, clear_first=clear_first))


def test_acquire_con_ranuras_que_no_se_vacian():
    # busy pegado en 1: los dos esperan 10 ms y siguen sin error.
    comparar('acquire busy', lambda M, h: M.mca_read_acquire(h, 0),
             **{str(R.R_STATUS): 2})


def test_acquire_segundos_negativos():
    comparar('acquire -1', lambda M, h: M.mca_read_acquire(h, -1))


def test_acquire_chunks_llama_on_chunk_en_orden():
    llamadas = {R: [], A: []}

    def op(M, h):
        out = M.mca_read_acquire_chunks(h, 0.003, 0.001,
                                        on_chunk=llamadas[M].append)
        return out, list(llamadas[M])
    comparar('acquire_chunks', op)
    assert llamadas[R] == llamadas[A] == [0, 1]


def test_acquire_chunks_excepcion_en_on_chunk():
    class Corte(Exception):
        pass

    def on_chunk(k):
        raise Corte(f'corte en {k}')
    comparar('acquire_chunks corte',
             lambda M, h: M.mca_read_acquire_chunks(h, 0.003, 0.001,
                                                    on_chunk=on_chunk))


@pytest.mark.parametrize('q_tot', [0, 1, 7999, 8000, 123456, 0xFFFFFFFF])
def test_autoscale_q_shift(q_tot):
    comparar(f'autoscale_q {q_tot}', lambda M, h: h.autoscale_q_shift(seconds=0),
             **{str(R.R_LAST_QTOT): q_tot})
    comparar(f'autoscale_q cfg {q_tot}',
             lambda M, h: h.autoscale_q_shift(target_channel=300, seconds=0,
                                              gate_long=200),
             **{str(R.R_LAST_QTOT): q_tot})


def test_metadata_salvo_el_reloj_de_pared():
    def op(M, h):
        # La metadata es del binding: sobre la referencia corre despachada.
        if M is R:
            h._via = 'py'
        meta = A.mca_get_metadata(h)
        meta.pop('t_wall')
        meta.pop('api_impl', None)
        meta.pop('libmca_version', None)
        return meta
    comparar('metadata', op)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
