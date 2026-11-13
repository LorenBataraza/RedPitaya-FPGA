"""Los generadores de prueba de la PL: el handle de libmca del generador de pulsos y
las cuentas del motor de disparos que comparte con el del ring.

    from API.generadores import GenPulsos, tabla_cdf, umbral_para

    with GenPulsos.open() as g:                  # 0x4021_0000, y la página de HK
        g.configurar(aleatorio=True, tasa=200e3, n=100_000, tau=250.0,
                     amp_aleat=True, ruido=True, ruido_sh=6)
        g.cargar_tabla(tabla_cdf([1500, 4000], [0.6, 0.4]))
        g.lazo = True                            # adc_dat <- el generador
        ... el MCA corriendo, con trap_mq = mq_de(g.leer_config()['decae']) ...
        g.arrancar()
        g.esperar(timeout_s=5)
        g.parar()
        g.lazo = False

**La lógica está en C** (`libmca/include/gen_pulsos.h` y `gen_disparos.h`), como
el resto de los bloques: acá quedan los tipos de ctypes y la traducción de nombres
y errores. El generador del ring (`gen_eventos`) se maneja desde `OsciloscopeRing`
(`gen_configurar`, `gen_estado`), porque vive en la página del ring y corre sólo con
el ring en RUNNING; comparte con éste `disparos()` y `predecir()`.

Los nombres de la configuración son los de `CFG` del modelo
(`modulos/gen_eventos/modelos/python_model/gen_pulsos_model.py`): un dict de un
bloque de `tb_pulsos_mca` se pasa tal cual a `configurar`. Además:

- `tasa` (Hz) en lugar de `umbral` (aleatorio) o `periodo` (periódico);
- `tau` (muestras) en lugar de `decae`;
- `salidas`: a qué canal del DAC va la salida (`SAL_OUT1` para el lazo del canal 0).

Docs: `docs/gen_eventos/generador_pulsos.md` y `docs/event_ring/generador.md`.
"""

import ctypes
import operator
import time

import numpy as np

from API import _libmca

# --- registros de gen_pulsos (0x4021_0000) ----------------------------------
PHYS = 0x4021_0000
SIZE = 0x2000                     # los registros y la tabla
MAGIC = 0x5055_4C31               # "PUL1"

R_CTRL, R_PERIODO, R_UMBRAL, R_DT_MIN = 0x0000, 0x0004, 0x0008, 0x000C
R_N, R_SEMILLA, R_GEN_CNT, R_ESTADO = 0x0010, 0x0014, 0x0018, 0x001C
R_MAGIC, R_DECAE, R_SUBIDA, R_AMP_N = 0x0020, 0x0024, 0x0028, 0x002C
R_BASE, R_RUIDO, R_TABLA = 0x0030, 0x0034, 0x1000

CTRL_EN, CTRL_ALEATORIO, CTRL_AMP_ALEAT = 1 << 0, 1 << 1, 1 << 2
CTRL_OUT1, CTRL_OUT2 = 1 << 3, 1 << 4
RUIDO_EN = 1 << 8
SAL_OUT1, SAL_OUT2 = 1 << 0, 1 << 1
ST_GENERANDO, ST_TERMINADO, ST_DESBORDE = 1 << 0, 1 << 1, 1 << 2

N_TABLA = 1024
AMP_MIN, AMP_MAX = -8192, 8191
DECAE_RESET = 65280
LAT_TRIG = 1                      # de la decisión a trig_o
LAT_DAT = 5                       # de trig_o a la primera muestra (SUBIDA = 0)

# El lazo digital: housekeeping de Red Pitaya (slot 0).
HK_PHYS, HK_SIZE, HK_LAZO = 0x4000_0000, 0x1000, 0x00C

FS_HZ = 125e6
SEMILLA_0 = 0x2545_F491

# Los nombres de la configuración, en el orden del struct de C.
CLAVES_DISPAROS = ('aleatorio', 'periodo', 'umbral', 'dt_min', 'n', 'semilla')
CLAVES_PULSOS = ('amp_aleat', 'salidas', 'decae', 'subida', 'amp_n', 'base', 'ruido',
                 'ruido_sh')


class GenPulsosNotPresent(RuntimeError):
    """El bitstream cargado no tiene el generador de pulsos en 0x4021_0000."""


# =============================================================================
# Los tipos de C
# =============================================================================

_U, _I32, _I64, _D = ctypes.c_uint32, ctypes.c_int32, ctypes.c_int64, ctypes.c_double
_P, _PP, _PU = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)


class _Disparos(ctypes.Structure):
    _fields_ = [(k, _U) for k in CLAVES_DISPAROS]


class _Pulsos(ctypes.Structure):
    _fields_ = [('disparos', _Disparos), ('amp_aleat', _U), ('salidas', _U),
                ('decae', _U), ('subida', _U), ('amp_n', _U), ('base', _I32),
                ('ruido', _U), ('ruido_sh', _U)]


class _Estado(ctypes.Structure):
    _fields_ = [('gen_cnt', _U), ('estado', _U), ('generando', _I32),
                ('terminado', _I32), ('desborde', _I32)]


class _Reg(ctypes.Structure):
    _fields_ = [('nombre', ctypes.c_char_p), ('offset', _U)]


_lib = None


def _cargar():
    """libmca con las firmas de los generadores declaradas. OSError si no está o es
    vieja."""
    global _lib
    if _lib is not None:
        return _lib
    lib = _libmca.cargar()
    if not hasattr(lib, 'gen_pulsos_open_bus'):
        raise OSError('libmca no tiene gen_pulsos_*: el .so es de otra versión. '
                      'Recompilarla: `make -C libmca`.')

    def f(nombre, res, *args):
        fn = getattr(lib, nombre)
        fn.restype = res
        fn.argtypes = list(args)

    c = ctypes.c_int
    pd, pp, pe = (ctypes.POINTER(_Disparos), ctypes.POINTER(_Pulsos),
                  ctypes.POINTER(_Estado))
    pdbl, pi16 = ctypes.POINTER(_D), ctypes.POINTER(ctypes.c_int16)
    # gen_disparos.h
    f('gen_disparos_default', None, pd)
    f('gen_disparos_validar', c, pd)
    f('gen_disparos_last_error', ctypes.c_char_p)
    f('gen_disparos_umbral_para', c, _D, _U, _PU)
    f('gen_disparos_periodo_para', c, _D, _PU)
    f('gen_disparos_tasa', c, pd, pdbl)
    f('gen_disparos_predecir', c, pd, ctypes.c_uint64, _U,
      ctypes.POINTER(ctypes.c_uint64), _U, _PU)
    f('gen_disparos_sizeof', ctypes.c_size_t, ctypes.c_char_p)
    # gen_pulsos.h
    f('gen_pulsos_open', c, _PP, _U, _U, c)
    f('gen_pulsos_open_bus', c, _PP, _P, c, _P, c, c)
    f('gen_pulsos_close', None, _P)
    f('gen_pulsos_last_error', ctypes.c_char_p, _P)
    f('gen_pulsos_reg_count', _I32)
    f('gen_pulsos_reg_info', ctypes.POINTER(_Reg), _I32)
    f('gen_pulsos_sizeof', ctypes.c_size_t, ctypes.c_char_p)
    f('gen_pulsos_r32', c, _P, _U, _PU)
    f('gen_pulsos_w32', c, _P, _U, _U)
    f('gen_pulsos_config_default', None, pp)
    f('gen_pulsos_validar', c, pp)
    f('gen_pulsos_configurar', c, _P, pp)
    f('gen_pulsos_leer_config', c, _P, pp)
    f('gen_pulsos_cargar_tabla', c, _P, pi16, _U)
    f('gen_pulsos_leer_tabla', c, _P, pi16, _U)
    f('gen_pulsos_arrancar', c, _P)
    f('gen_pulsos_parar', c, _P)
    f('gen_pulsos_estado', c, _P, pe)
    f('gen_pulsos_esperar', c, _P, _I64, pe)
    f('gen_pulsos_set_lazo', c, _P, _I32)
    f('gen_pulsos_get_lazo', c, _P, ctypes.POINTER(_I32))
    f('gen_pulsos_decae_para', c, _D, _PU)
    f('gen_pulsos_tau', c, _U, pdbl)
    f('gen_pulsos_mq', c, _U, _PU)
    f('gen_pulsos_sigma_ruido', c, _U, pdbl)
    f('gen_pulsos_tabla_cdf', c, pdbl, pdbl, _U, pi16, _U)
    for tipo, py in (('gen_disparos_cfg_t', _Disparos), ('gen_estado_t', _Estado),
                     ('gen_pulsos_cfg_t', _Pulsos)):
        if lib.gen_pulsos_sizeof(tipo.encode()) != ctypes.sizeof(py):
            raise OSError(f'libmca y API/generadores.py no coinciden en {tipo}: '
                          f'{lib.gen_pulsos_sizeof(tipo.encode())} contra '
                          f'{ctypes.sizeof(py)} bytes. Recompilar libmca o actualizar el '
                          'struct del binding.')
    _lib = lib
    return lib


_EXCEPCIONES = {_libmca.MCA_ENOTPRESENT: GenPulsosNotPresent}


def _detalle_pulsos(c=None):
    return _cargar().gen_pulsos_last_error(c).decode('utf-8', 'replace') or None


def _detalle_disparos():
    return _cargar().gen_disparos_last_error().decode('utf-8', 'replace') or None


def _check(rc, que, detalle):
    if rc:
        _libmca.check(rc, que, _EXCEPCIONES, detalle())


def _u32(v, nombre='valor'):
    if isinstance(v, bool):
        v = int(v)
    v = operator.index(v)
    if not 0 <= v < 2 ** 32:
        raise ValueError(f'{nombre} = {v}: fuera de 0..2^32 - 1')
    return v


def registros():
    """{nombre: offset} del mapa de gen_pulsos, como lo exporta libmca."""
    lib = _cargar()
    out = {}
    for i in range(lib.gen_pulsos_reg_count()):
        r = lib.gen_pulsos_reg_info(i).contents
        out[r.nombre.decode()] = r.offset
    return out


# =============================================================================
# El motor de disparos: la configuración y las cuentas
# =============================================================================

def _a_dict(s):
    return {k: getattr(s, k) for k, _ in s._fields_}


def disparos(tasa=None, aleatorio=False, periodo=None, umbral=None, dt_min=2, n=0,
             semilla=0):
    """La configuración del motor como dict, con los nombres del modelo. `tasa` (Hz)
    da el `umbral` (aleatorio) o el `periodo` (periódico); no se pasa con ellos. Lo
    que no se da queda en el reset del RTL (periódico de 1000 ciclos). No valida:
    eso lo hace C al configurar (o `validar`)."""
    d = _Disparos()
    _cargar().gen_disparos_default(ctypes.byref(d))
    out = _a_dict(d)
    out.update(aleatorio=int(aleatorio) if isinstance(aleatorio, bool) else aleatorio,
               dt_min=dt_min, n=n, semilla=semilla)
    if tasa is not None:
        if (umbral if aleatorio else periodo) is not None:
            raise ValueError(f'tasa y {"umbral" if aleatorio else "periodo"}: uno de los dos')
        if aleatorio:
            umbral = umbral_para(tasa, dt_min)
        else:
            periodo = periodo_para(tasa)
    if periodo is not None:
        out['periodo'] = periodo
    if umbral is not None:
        out['umbral'] = umbral
    return out


def _struct_disparos(cfg):
    d = _Disparos()
    for k in CLAVES_DISPAROS:
        setattr(d, k, _u32(cfg[k], k))
    return d


def umbral_para(tasa_hz, dt_min=2):
    """El UMBRAL que da `tasa_hz` disparos por segundo en el modo aleatorio. Es
    `umbral_para` del modelo; ValueError si no se alcanza con ese `dt_min`."""
    v = _U()
    _check(_cargar().gen_disparos_umbral_para(float(tasa_hz), _u32(dt_min, 'dt_min'),
                                              ctypes.byref(v)),
           'umbral_para', _detalle_disparos)
    return v.value


def periodo_para(tasa_hz):
    """El PERIODO más cercano a `tasa_hz` en el modo periódico."""
    v = _U()
    _check(_cargar().gen_disparos_periodo_para(float(tasa_hz), ctypes.byref(v)),
           'periodo_para', _detalle_disparos)
    return v.value


def tasa(**cfg):
    """La tasa media de una configuración del motor, en Hz."""
    v = _D()
    d = _struct_disparos(disparos() | cfg)
    _check(_cargar().gen_disparos_tasa(ctypes.byref(d), ctypes.byref(v)), 'tasa',
           _detalle_disparos)
    return v.value


def predecir(n_ciclos, lat, n_max=None, **cfg):
    """Los ciclos de los primeros disparos (hasta `n_max`, o los `n` de la
    configuración) en `n_ciclos` desde el arranque, como int64. `lat` es `LAT_TRIG`
    para los pulsos (el `trig` de `traza` del modelo) y `GEN_LAT_TS` del ring para
    sus marcas de tiempo (lo que da `disparos` del modelo)."""
    c = disparos() | cfg
    if n_max is None:
        if not c['n']:
            raise ValueError('sin N (sin fin): pasar n_max')
        n_max = c['n']
    n_max = _u32(n_max, 'n_max')
    out = np.empty(n_max, np.uint64)
    n = _U()
    d = _struct_disparos(c)
    _check(_cargar().gen_disparos_predecir(
        ctypes.byref(d), int(n_ciclos), _u32(lat, 'lat'),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)), n_max, ctypes.byref(n)),
        'predecir', _detalle_disparos)
    return out[:n.value].astype(np.int64)


# =============================================================================
# Las cuentas del generador de pulsos
# =============================================================================

def decae_para(tau_muestras):
    """El DECAE de una caída de `tau_muestras` (8 ns cada una)."""
    v = _U()
    _check(_cargar().gen_pulsos_decae_para(float(tau_muestras), ctypes.byref(v)),
           'decae_para', _detalle_pulsos)
    return v.value


def tau_de(decae):
    """La constante de tiempo, en muestras, de un DECAE."""
    v = _D()
    _check(_cargar().gen_pulsos_tau(_u32(decae, 'decae'), ctypes.byref(v)), 'tau_de',
           _detalle_pulsos)
    return v.value


def mq_de(decae):
    """La Mq del polo-cero que cancela la caída: la del trapecio (`trap_mq`) y la del
    disparo con polo-cero."""
    v = _U()
    _check(_cargar().gen_pulsos_mq(_u32(decae, 'decae'), ctypes.byref(v)), 'mq_de',
           _detalle_pulsos)
    return v.value


def sigma_ruido(sh):
    """El sigma del ruido, en cuentas, para un `ruido_sh`."""
    v = _D()
    _check(_cargar().gen_pulsos_sigma_ruido(_u32(sh, 'sh'), ctypes.byref(v)),
           'sigma_ruido', _detalle_pulsos)
    return v.value


def tabla_cdf(valores, pesos):
    """Las 1024 amplitudes (int16) que sortean `valores` con probabilidades `pesos`:
    la tabla del modo `amp_aleat`. Ver `gen_pulsos_tabla_cdf` en el header."""
    v = np.ascontiguousarray(valores, dtype=np.float64)
    w = np.ascontiguousarray(pesos, dtype=np.float64)
    if v.ndim != 1 or v.shape != w.shape:
        raise ValueError(f'valores {v.shape} y pesos {w.shape}: dos listas del mismo largo')
    out = np.empty(N_TABLA, np.int16)
    pd = ctypes.POINTER(_D)
    _check(_cargar().gen_pulsos_tabla_cdf(
        v.ctypes.data_as(pd), w.ctypes.data_as(pd), v.size,
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), N_TABLA),
        'tabla_cdf', _detalle_pulsos)
    return out


def config(tasa=None, tau=None, **kw):
    """La configuración entera del generador como dict: el reset del RTL con
    `salidas = SAL_OUT1`, y lo que se pase. `tasa` y `tau` como en `disparos` y
    `decae_para`."""
    p = _Pulsos()
    _cargar().gen_pulsos_config_default(ctypes.byref(p))
    out = {k: getattr(p, k) for k in CLAVES_PULSOS}
    dk = {k: kw.pop(k) for k in list(kw) if k in CLAVES_DISPAROS}
    out.update(disparos(tasa=tasa, **dk))
    if tau is not None:
        if 'decae' in kw:
            raise ValueError('tau y decae: uno de los dos')
        kw['decae'] = decae_para(tau)
    malos = set(kw) - set(CLAVES_PULSOS)
    if malos:
        raise TypeError(f'claves que no son del generador: {sorted(malos)}')
    out.update(kw)
    return out


def _struct_pulsos(cfg):
    p = _Pulsos()
    p.disparos = _struct_disparos(cfg)
    for k in CLAVES_PULSOS:
        v = cfg[k]
        if k == 'base':
            v = operator.index(v)
            if not -2 ** 31 <= v < 2 ** 31:
                raise ValueError(f'base = {v}: fuera de int32')
            p.base = v
        else:
            setattr(p, k, _u32(v, k))
    return p


def validar(tasa=None, tau=None, **kw):
    """La configuración que quedaría, o ValueError con el motivo, sin tocar el
    hardware."""
    cfg = config(tasa=tasa, tau=tau, **kw)
    p = _struct_pulsos(cfg)
    _check(_cargar().gen_pulsos_validar(ctypes.byref(p)), 'validar', _detalle_pulsos)
    return cfg


def _estado_dict(e):
    d = _a_dict(e)
    for k in ('generando', 'terminado', 'desborde'):
        d[k] = bool(d[k])
    return d


# =============================================================================
# El handle
# =============================================================================

class GenPulsos:
    """El generador de pulsos de libmca: sus registros (0x4021_0000) y el lazo
    digital de HK.

        g = GenPulsos.open()                              # la placa
        g = GenPulsos.sobre(Bus.callbacks(...), hk=...)   # tests
    """

    def __init__(self, c, bus=None, hk=None):
        self._c = c
        self._bus = bus           # los de Python, si se abrió sobre ellos: viven con él
        self._hk = hk

    @classmethod
    def open(cls, phys=PHYS, size=SIZE, check_magic=True):
        """Mapea el generador y la página de HK. GenPulsosNotPresent si el slot 2 no
        lo tiene (el bitstream del MCA de antes del 2026-11-09, por ejemplo)."""
        p = ctypes.c_void_p()
        rc = _cargar().gen_pulsos_open(ctypes.byref(p), _u32(phys), _u32(size),
                                       int(bool(check_magic)))
        if rc:
            _libmca.check(rc, 'gen_pulsos_open', _EXCEPCIONES, _detalle_pulsos())
        return cls(p)

    @classmethod
    def sobre(cls, bus, hk=None, check_magic=True):
        """Sobre `Bus` de `API._libmca` (el del generador y, si está, el de HK), que
        quedan a cargo de este handle."""
        p = ctypes.c_void_p()
        rc = _cargar().gen_pulsos_open_bus(ctypes.byref(p), bus.ptr, 0,
                                           hk.ptr if hk is not None else None, 0,
                                           int(bool(check_magic)))
        if rc:
            bus.check(rc, 'gen_pulsos_open_bus', _EXCEPCIONES, _detalle_pulsos())
        return cls(p, bus, hk)

    def _ok(self, rc, que=''):
        if rc == 0:
            return
        det = _detalle_pulsos(self._c)
        for r in (self._bus, self._hk):
            if r is not None and r._pendiente is not None:
                r.check(rc, que, None, det)
        _libmca.check(rc, que, _EXCEPCIONES, det)

    @property
    def c(self):
        if self._c is None:
            raise ValueError('generador cerrado')
        return self._c

    def r32(self, off):
        v = _U()
        self._ok(_cargar().gen_pulsos_r32(self.c, _u32(off), ctypes.byref(v)),
                 f'r32 {off:#x}')
        return v.value

    def w32(self, off, val):
        self._ok(_cargar().gen_pulsos_w32(self.c, _u32(off), operator.index(val)
                                          & 0xFFFFFFFF), f'w32 {off:#x}')

    # -- configuración --

    def configurar(self, tasa=None, tau=None, **kw):
        """Apaga el generador, escribe toda la configuración y la relee (`config` dice
        qué queda con lo que no se pasa). No lo arranca. Devuelve lo escrito."""
        cfg = config(tasa=tasa, tau=tau, **kw)
        p = _struct_pulsos(cfg)
        self._ok(_cargar().gen_pulsos_configurar(self.c, ctypes.byref(p)), 'configurar')
        return cfg

    def leer_config(self):
        p = _Pulsos()
        self._ok(_cargar().gen_pulsos_leer_config(self.c, ctypes.byref(p)), 'leer_config')
        out = _a_dict(p.disparos)
        out.update({k: getattr(p, k) for k in CLAVES_PULSOS})
        return out

    def cargar_tabla(self, amp):
        """Hasta 1024 amplitudes (14 bits con signo); el resto de la tabla en 0. La
        relee entera."""
        a = np.asarray(amp)
        if a.ndim != 1:
            raise ValueError(f'la tabla es una lista, y tiene forma {a.shape}')
        if a.size and not np.issubdtype(a.dtype, np.integer):
            if not np.array_equal(a, np.round(a)):
                raise ValueError('la tabla son enteros (cuentas)')
        a64 = a.astype(np.int64)
        if a64.size and (a64.min() < AMP_MIN or a64.max() > AMP_MAX):
            i = int(np.flatnonzero((a64 < AMP_MIN) | (a64 > AMP_MAX))[0])
            raise ValueError(f'amp[{i}] = {a64[i]}: no entra en 14 bits con signo '
                             f'({AMP_MIN}..{AMP_MAX})')
        t = np.ascontiguousarray(a64, dtype=np.int16)
        self._ok(_cargar().gen_pulsos_cargar_tabla(
            self.c, t.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), t.size),
            'cargar_tabla')

    def leer_tabla(self, n=N_TABLA):
        out = np.empty(_u32(n, 'n'), np.int16)
        self._ok(_cargar().gen_pulsos_leer_tabla(
            self.c, out.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)), out.size),
            'leer_tabla')
        return out

    # -- control y estado --

    def arrancar(self):
        """Reinicia todo el estado y empieza a generar."""
        self._ok(_cargar().gen_pulsos_arrancar(self.c), 'arrancar')

    def parar(self):
        """La salida y el disparo en cero; GEN_CNT y ESTADO quedan."""
        self._ok(_cargar().gen_pulsos_parar(self.c), 'parar')

    def estado(self):
        """`gen_cnt`, `estado` (crudo), `generando`, `terminado` y `desborde`."""
        e = _Estado()
        self._ok(_cargar().gen_pulsos_estado(self.c, ctypes.byref(e)), 'estado')
        return _estado_dict(e)

    def esperar(self, timeout_s=5.0):
        """Hasta que llegue a N. TimeoutError si no; ValueError si N es 0 o está
        apagado. Devuelve el estado."""
        e = _Estado()
        plazo = time.perf_counter_ns() + int(timeout_s * 1e9)
        self._ok(_cargar().gen_pulsos_esperar(self.c, plazo, ctypes.byref(e)), 'esperar')
        return _estado_dict(e)

    @property
    def lazo(self):
        """digital_loop[0] de HK: True si adc_dat toma el generador en vez del ADC."""
        v = _I32()
        self._ok(_cargar().gen_pulsos_get_lazo(self.c, ctypes.byref(v)), 'lazo')
        return bool(v.value)

    @lazo.setter
    def lazo(self, on):
        self._ok(_cargar().gen_pulsos_set_lazo(self.c, int(bool(on))), 'lazo')

    def close(self):
        if self._c is not None:
            _cargar().gen_pulsos_close(self._c)
            self._c = None
        for r in (self._bus, self._hk):
            if r is not None:
                r.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
