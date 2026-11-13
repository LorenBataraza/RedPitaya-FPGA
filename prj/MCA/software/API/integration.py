#!/usr/bin/env python3
"""Región de TOP (integración): identificación, descubrimiento y ruteo.

Slot 6 del bus de sistema (0x4060_0000). Es la región que el refactor de
registros añadió por encima de los módulos: dice **qué** bitstream está
cargado, **qué** módulos trae, **en qué slot** vive cada uno, y **de dónde**
toma sus muestras cada consumidor de la cadena DSP.

    from API.integration import (Integration, integration_open,
                                 integration_set_route_mca, TAP_ADC)

    ig = integration_open()
    ig.identify()                              # magic, versión, hash de git
    integration_set_route_mca(ig, TAP_ADC)     # el MCA pasa a la muestra cruda

No es housekeeping: `red_pitaya_hk` (slot 0) es un módulo de RedPitaya (LEDs,
E1/E2, DNA) y sigue donde estaba. Ver `docs/TOP/register_map_top.md`.

**La lógica está en C.** Cada función de hardware de este módulo es una llamada
a la función del mismo nombre de `libmca` (`libmca/include/integration.h`), por
ctypes, con el despacho de `@_api` (`API/_despacho.py`):

    integration_open()            -> handle de C (libmca)     h._via == 'c'
    integration_open(impl='py')   -> la implementación Python h._via == 'py'
                                     de referencia (API/ref_py/integration.py)

Acá quedan las constantes, la traducción de tipos y lo que es composición:
`dump`, `geometria_coincide`, `slot_base`.

**Por qué existe el descubrimiento.** El multitrigger vive en el slot 3 de
`mca_red_pitaya_top` y `event_ring_red_pitaya_top`, pero en el `red_pitaya_top`
clásico está en el **7**, porque ahí los slots 2 y 3 los ocupan el ASG y el PID.
Un driver que hardcodea la base funciona en un bitstream y escribe a la nada en
el otro — sin excepción, porque el esclavo hace ack igual. `slot_base()` lee el
mapa real en vez de suponerlo.
"""

import ctypes
import numbers
import operator
import os
import sys

from API import _libmca
from API._despacho import api as _api, elegir_impl as _elegir_impl
from API.ref_py import integration as _ref

INTEGRATION_PHYS = 0x4060_0000          # slot 6 del sys bus
INTEGRATION_SIZE = 0x1000               # la región entera son 64 registros

MAGIC = 0x494E5447                      # "INTG"

SYS_BUS_BASE = 0x4000_0000              # base del bus; slot n = BASE + n*0x100000
SYS_BUS_SLOT = 0x0010_0000

# --- identificación ---
R_MAGIC   = 0x000
R_VERSION = 0x004                       # {mayor[31:24], menor, parche, variante}
R_GITH_0  = 0x008                       # hash de git, 160 b en cinco palabras
R_GITH_1  = 0x00C
R_GITH_2  = 0x010
R_GITH_3  = 0x014
R_GITH_4  = 0x018
# --- descripción del sistema ---
R_MODULES = 0x020                       # bit por módulo presente
R_SLOTS   = 0x024                       # nibble por módulo
R_CAPS_0  = 0x028                       # {EN_FILT[24], RSZ[21:16], DW[13:8], N_CH[3:0]}
R_CAPS_1  = 0x02C                       # {PSD_AW[23:16], H2_AW[15:8], H_AW[7:0]}
# --- ruteo del datapath ---
R_ROUTE_OSC  = 0x030                    # los cuatro: {en[8], tap[1:0]}
R_ROUTE_MTRG = 0x034
R_ROUTE_MCA  = 0x038
R_ROUTE_RING = 0x03C
# --- control y estado global ---
R_CTRL   = 0x040                        # bit0 run, bit1 clear*, bit2 soft_reset*
R_STATUS = 0x044                        # bit0 pll_locked, bit1 adc_rstn

# --- bits de MODULES ---
MOD_OSC  = 1 << 0
MOD_MTRG = 1 << 1
MOD_MCA  = 1 << 2
MOD_RING = 1 << 3
MOD_ASG  = 1 << 4
MOD_PID  = 1 << 5
MOD_PULSOS = 1 << 6                     # gen_pulsos, en el lugar del ASG

# gen_pulsos comparte el slot 2 con el event_ring (sys_bus_split): vive 64 KB
# arriba de la base del slot.
PULSOS_OFFSET = 0x0001_0000

# --- bits de CTRL ---
CTRL_RUN   = 1 << 0
CTRL_CLEAR = 1 << 1                     # autolimpiante en HW (dura 1 ciclo)
CTRL_SRST  = 1 << 2                     # autolimpiante en HW (dura 1 ciclo)

# --- bits de STATUS ---
ST_PLL_LOCKED = 1 << 0
ST_ADC_RSTN   = 1 << 1


# =============================================================================
# Taps de la cadena DSP
# =============================================================================
#
# La lista canónica vive en integration_cfg.sv; ésta es su espejo. La cadena:
#
#   adc_dat -> calib -> osc_filter -> [byp] -> adc_dec_in ------------- TAP 2
#      |                                          |                       `-> MCA (nativo)
#    TAP 1                                    rp_decim -> adc_dly_in
#                                                 |           `-> multitrigger (nativo)
#                                             rp_delay -> adc_bram_in --- TAP 3
#                                                               `-> OSC (nativo)

TAP_NATIVE  = 0     # como estaba cableado antes del refactor. Es el RESET.
TAP_ADC     = 1     # muestra cruda, ANTES de calibración y ecualizador
TAP_DEC_IN  = 2     # post-calib/ecualizador, PRE-decimación (125 MSPS)
TAP_BRAM_IN = 3     # después de todo el DSP (decimación + delay)

TAP_NAMES = {TAP_NATIVE: 'nativo', TAP_ADC: 'adc_dat',
             TAP_DEC_IN: 'adc_dec_in', TAP_BRAM_IN: 'adc_bram_in'}

# El nativo de cada consumidor, para poder informarlo sin adivinar. El del
# multitrigger NO es ninguno de los tres taps: es adc_dly_in, post-decimación
# pero PRE-delay. Por eso TAP_NATIVE existe como valor aparte.
TAP_NATIVO_DE = {'osc': 'adc_bram_in', 'mtrg': 'adc_dly_in',
                 'mca': 'adc_dec_in',  'ring': 'adc_dec_in'}

_R_ROUTE = {'osc': R_ROUTE_OSC, 'mtrg': R_ROUTE_MTRG,
            'mca': R_ROUTE_MCA, 'ring': R_ROUTE_RING}


class IntegrationNotPresent(RuntimeError):
    """El bitstream cargado no tiene la región de TOP en el slot 6.

    Pasa con cualquier bitstream anterior al refactor de registros. No es
    fatal: los drivers siguen andando con sus bases por defecto, sólo se
    pierden el descubrimiento y el ruteo.
    """


# La referencia lanza su propia IntegrationNotPresent: se la reemplaza por ésta,
# así un `except` atrapa el error venga de C o de Python. Es un alias en memoria;
# el fichero de referencia no se toca.
_ref.IntegrationNotPresent = IntegrationNotPresent


# =============================================================================
# libmca: carga, firmas y tipos
# =============================================================================
#
# Los structs replican los de include/integration.h campo por campo. `_cargar()`
# compara su tamaño con el que informa C: con un campo agregado de un solo lado,
# ctypes leería corrido sin ningún error.

_I32, _U = ctypes.c_int32, ctypes.c_uint32
_P, _PU = ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)
_PP = ctypes.POINTER(ctypes.c_void_p)


class _Info(ctypes.Structure):
    _fields_ = [('magic', _U), ('version', _U * 4), ('gith', ctypes.c_char * 41)]


class _Modules(ctypes.Structure):
    _fields_ = [(k, _I32) for k in ('osc', 'mtrg', 'mca', 'ring', 'asg', 'pid', 'pulsos')]


class _Slots(ctypes.Structure):
    _fields_ = [(k, _U) for k in ('osc', 'ring', 'mtrg', 'top', 'mca', 'pulsos')]


class _Caps(ctypes.Structure):
    _fields_ = [('n_ch', _U), ('dw', _U), ('rsz', _U), ('en_filt', _I32),
                ('h_aw', _U), ('h2_aw', _U), ('psd_aw', _U)]


class _Route(ctypes.Structure):
    _fields_ = [('tap', _U), ('nombre', ctypes.c_char_p), ('enable', _I32)]


class _Status(ctypes.Structure):
    _fields_ = [('pll_locked', _I32), ('adc_rstn', _I32)]


class _Reg(ctypes.Structure):
    _fields_ = [('nombre', ctypes.c_char_p), ('offset', _U)]


# Los índices de C. Los nombres que no estén se pasan como -1 y C contesta
# MCA_ENOKEY en el mismo punto donde Python hacía el `_R_ROUTE[consumidor]`.
_I_CONSUMIDOR = {c: i for i, c in enumerate(_R_ROUTE)}
_I_SLOT = {k: i for i, (k, _) in enumerate(_Slots._fields_)}

# Un tap que no es un entero no cruza a C: viaja como este centinela
# (INTEGRATION_TAP_NO_ENTERO) y el mensaje no lo repite.
_TAP_NO_ENTERO = -2 ** 63

_lib = None


def _cargar():
    """libmca con las firmas de este bloque declaradas. OSError si no está."""
    global _lib
    if _lib is not None:
        return _lib
    lib = _libmca.cargar()
    # Un .so anterior a este bloque daría un AttributeError sobre una función
    # suelta, y el servidor lo tomaría por "este bitstream no trae el slot 6".
    if not hasattr(lib, 'integration_open'):
        raise OSError('libmca no tiene integration_*: el .so es de otra versión. '
                      'Recompilarla: `make -C libmca arm` en la PC y volver a '
                      'copiarla a la placa, o `make -C libmca placa-lib`.')

    def f(nombre, res, *args):
        fn = getattr(lib, nombre)
        fn.restype = res
        fn.argtypes = list(args)

    c = ctypes.c_int
    f('integration_open', c, _PP, _U, _U, c)
    f('integration_open_bus', c, _PP, _P, c, c)
    f('integration_close', None, _P)
    f('integration_last_error', ctypes.c_char_p, _P)
    f('integration_reg_count', _I32)
    f('integration_reg_info', ctypes.POINTER(_Reg), _I32)
    f('integration_consumidor_name', ctypes.c_char_p, _I32)
    f('integration_slot_name', ctypes.c_char_p, _I32)
    f('integration_sizeof', ctypes.c_size_t, ctypes.c_char_p)
    f('integration_r32', c, _P, _U, _PU)
    f('integration_w32', c, _P, _U, _U)
    f('integration_identify', c, _P, ctypes.POINTER(_Info))
    f('integration_get_modules', c, _P, ctypes.POINTER(_Modules))
    f('integration_get_slots', c, _P, ctypes.POINTER(_Slots))
    f('integration_get_caps', c, _P, ctypes.POINTER(_Caps))
    f('integration_get_base', c, _P, _I32, _PU)
    f('integration_get_route', c, _P, _I32, ctypes.POINTER(_Route))
    f('integration_get_routes', c, _P, ctypes.POINTER(_Route), _I32)
    f('integration_set_route', c, _P, _I32, ctypes.c_int64, _I32, _I32)
    f('integration_reset_routes', c, _P)
    f('integration_set_run', c, _P, _I32)
    f('integration_get_run', c, _P, ctypes.POINTER(_I32))
    f('integration_clear', c, _P)
    f('integration_soft_reset', c, _P)
    f('integration_get_status', c, _P, ctypes.POINTER(_Status))

    for tipo, py in (('integration_info_t', _Info),
                     ('integration_modules_t', _Modules),
                     ('integration_slots_t', _Slots),
                     ('integration_caps_t', _Caps),
                     ('integration_route_t', _Route),
                     ('integration_status_t', _Status)):
        if lib.integration_sizeof(tipo.encode()) != ctypes.sizeof(py):
            raise OSError(f'libmca y API/integration.py no coinciden en {tipo}: '
                          f'{lib.integration_sizeof(tipo.encode())} contra '
                          f'{ctypes.sizeof(py)} bytes. Recompilar libmca o '
                          'actualizar el struct del binding.')
    _lib = lib
    return lib


_EXCEPCIONES = {_libmca.MCA_ENOTPRESENT: IntegrationNotPresent}


def _ok(h, rc, que='', clave=None):
    """rc de libmca -> nada, o la excepción con el detalle que dejó C.

    `clave` es el nombre que se buscó en una tabla: MCA_ENOKEY es el KeyError que
    daba el dict. Si el handle corre sobre callbacks, primero se relanza la
    excepción que haya tirado un callback: es la causa real.
    """
    if rc == 0:
        return
    if rc == _libmca.MCA_ENOKEY:
        raise KeyError(clave)
    det = _cargar().integration_last_error(h._c).decode('utf-8', 'replace') or None
    if h._bus is not None:
        h._bus.check(rc, que, _EXCEPCIONES, det)
    _libmca.check(rc, que, _EXCEPCIONES, det)


def _dict(s, conv=lambda v: v):
    """Un struct a dict, en el orden de sus campos."""
    return {k: conv(getattr(s, k)) for k, _ in s._fields_}


def _ruta(r):
    return {'tap': r.tap, 'nombre': r.nombre.decode(), 'enable': bool(r.enable)}


def _get_route(ig, consumidor):
    r = _Route()
    _ok(ig, _cargar().integration_get_route(
        ig._c, _I_CONSUMIDOR.get(consumidor, -1), ctypes.byref(r)),
        'get_route', consumidor)
    return _ruta(r)


def _set_route(ig, consumidor, tap, enable, verify):
    t = (max(_TAP_NO_ENTERO, min(2 ** 63 - 1, int(tap)))
         if isinstance(tap, numbers.Integral) else _TAP_NO_ENTERO)
    _ok(ig, _cargar().integration_set_route(
        ig._c, _I_CONSUMIDOR.get(consumidor, -1), t, 1 if enable else 0,
        1 if verify else 0), 'set_route', consumidor)


# =============================================================================
# Driver
# =============================================================================

class Integration:
    """Handle de la región de TOP sobre libmca.

    Los métodos son la API de siempre y cada uno es una llamada a la función de
    C del mismo nombre.
    """

    # La implementación que hay abajo.
    impl = 'c'
    _via = 'c'

    def __init__(self, mem, fd):
        """Un handle sobre un buffer ya mapeado, o sobre el `r32`/`w32` de una
        subclase con `mem=None`, sin leer nada. Ver `_libmca.Bus.de_handle`."""
        self._mmap = mem
        self._fd   = fd
        self._c    = None
        self._bus  = None
        lib = _cargar()
        self._bus = _libmca.Bus.de_handle(self, Integration, mem)
        p = ctypes.c_void_p()
        _libmca.check(lib.integration_open_bus(ctypes.byref(p), self._bus.ptr, 0, 0),
                      'integration_open_bus')
        self._c = p

    @classmethod
    def open(cls, phys=INTEGRATION_PHYS, size=INTEGRATION_SIZE, check_magic=True):
        """Mapear la región de TOP (en C, `integration_open`).

        Igual que el resto de los drivers: si la PL no está programada la
        PRIMERA lectura mata el proceso con SIGBUS sin traceback.
        `API.fpga.fpga_state()` permite chequearlo antes.
        """
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.integration_open(ctypes.byref(p), phys, size,
                                  1 if check_magic else 0)
        if rc:
            det = lib.integration_last_error(None).decode('utf-8', 'replace') or None
            _libmca.check(rc, f'/dev/mem @ {phys:#x}', _EXCEPCIONES, det)
        return cls._envolver(p, None)

    @classmethod
    def _sobre_bus(cls, bus, check_magic=True):
        """Un handle sobre un `_libmca.Bus` ya abierto, que pasa a ser suyo: lo
        cierra `close()`. Lo usan los tests y `bench_impl.py --shm`, con el
        backend devmem apuntando a un fichero."""
        lib = _cargar()
        p = ctypes.c_void_p()
        rc = lib.integration_open_bus(ctypes.byref(p), bus.ptr, 0,
                                      1 if check_magic else 0)
        if rc:
            det = lib.integration_last_error(None).decode('utf-8', 'replace') or None
            bus.check(rc, 'integration_open_bus', _EXCEPCIONES, det)
        return cls._envolver(p, bus)

    @classmethod
    def _envolver(cls, p, bus):
        h = cls.__new__(cls)
        h._mmap, h._fd, h._bus, h._c = None, -1, bus, p
        return h

    def close(self):
        c, self._c = getattr(self, '_c', None), None
        if c:
            _cargar().integration_close(c)
        bus, self._bus = getattr(self, '_bus', None), None
        if bus is not None:
            bus.close()
        # Lo que el constructor recibió ya abierto se cierra como antes.
        mem, self._mmap = getattr(self, '_mmap', None), None
        if mem is not None and hasattr(mem, 'close'):
            mem.close()
        fd, self._fd = getattr(self, '_fd', -1), -1
        if fd is not None and fd >= 0:
            os.close(fd)

    def __del__(self):
        # Un handle olvidado no deja /dev/mem mapeado: reprogramar la PL con un
        # mapeo abierto traba el puerto GP0 (API/fpga.py).
        try:
            self.close()
        except Exception:                                      # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def w32(self, off, v):
        # En C: un store de 32 b alineado, validado antes de llegar al bus.
        rc = _cargar().integration_w32(self._c, off, operator.index(v) & 0xFFFFFFFF)
        if rc:
            _ok(self, rc, f'w32 {off:#x}')

    def r32(self, off):
        v = ctypes.c_uint32()
        rc = _cargar().integration_r32(self._c, off, ctypes.byref(v))
        if rc:
            _ok(self, rc, f'r32 {off:#x}')
        return v.value

    # ---------- identificación ----------

    def identify(self, verbose=True):
        """Magic, versión y hash de git del bitstream cargado."""
        return integration_identify(self, verbose)

    # ---------- descripción del sistema ----------

    def modules(self):
        """Qué módulos trae este bitstream, como dict de bool."""
        return integration_get_modules(self)

    def slots(self):
        """En qué slot vive cada módulo EN ESTE bitstream.

        No es decorativo: el multitrigger está en el slot 3 del top del MCA y
        en el 7 del `red_pitaya_top` clásico.
        """
        return integration_get_slots(self)

    def base(self, modulo):
        """Dirección física de la base de un módulo, según el mapa real."""
        return integration_get_base(self, modulo)

    def caps(self):
        """Parámetros de síntesis: anchos, número de canales, profundidades.

        **`h_aw`, `h2_aw` y `psd_aw` son INFORMATIVOS y pueden mentir.** Son una
        segunda copia de la geometría del MCA, que el propio MCA publica en su
        registro `WIDTHS` (`0x008`) — y las dos copias ya divergieron: el
        bitstream que bajó el eje de 16384 a 8192 canales actualizó el MCA y no
        esta región, así que contra ese `.bit.bin` esto devuelve 14 mientras el
        hardware histogramea con 13.

        **La fuente de verdad es `MCA.h_aw`**, que sale de `WIDTHS`. No usar
        estos tres campos para dimensionar una lectura ni para convertir
        amplitudes a canales: para eso está `mca_canal_de_amplitud()`.

        Los otros cuatro (`n_ch`, `dw`, `rsz`, `en_filt`) sí son del sistema y
        ningún bloque suelto los conoce, así que acá es donde corresponde
        leerlos.
        """
        return integration_get_caps(self)

    def geometria_coincide(self, mca):
        """¿La geometría publicada acá coincide con la que dice el MCA?

        Devuelve `(bool, mensaje)`. Sirve para que quien tenga los dos handles
        abiertos pueda detectar la divergencia en vez de que quede latente hasta
        que alguien confíe en el campo equivocado.
        """
        c = self.caps()
        iguales = (c['h_aw'] == mca.h_aw and c['h2_aw'] == mca.h2_aw
                   and c['psd_aw'] == mca.psd_aw)
        if iguales:
            return True, f'geometría coherente: h_aw={mca.h_aw}'
        return False, (
            f'integration_cfg publica h_aw={c["h_aw"]} h2_aw={c["h2_aw"]} '
            f'psd_aw={c["psd_aw"]}, pero el MCA dice h_aw={mca.h_aw} '
            f'h2_aw={mca.h2_aw} psd_aw={mca.psd_aw}. Vale la del MCA (WIDTHS). '
            f'El top tiene que re-sintetizarse con los parámetros atados.')

    # ---------- ruteo del datapath ----------

    def get_route(self, consumidor):
        """`{'tap': int, 'nombre': str, 'enable': bool}` de un consumidor.

        `consumidor` es 'osc', 'mtrg', 'mca' o 'ring'.
        """
        return _get_route(self, consumidor)

    def set_route(self, consumidor, tap=TAP_NATIVE, enable=True, verify=True):
        """Elegir de qué punto de la cadena DSP toma sus muestras un consumidor.

        Con `enable=False` el `val` del consumidor se fuerza a 0: deja de
        recibir muestras sin tocar el resto del sistema.

        OJO, cambiar de tap CORRE LA LATENCIA: `rp_bram_sm` cuenta el delay en
        muestras decimadas, así que un OSC en TAP_ADC y un multitrigger en
        nativo desalinean el pre-trigger. Es legítimo, no es gratis.

        OJO 2, el camino a DDR por AXI NO se rutea: `rp_axi_sm` sigue siempre en
        su nodo nativo, así que esto afecta la captura en BRAM pero no las
        capturas `rp_AcqAxi*`.
        """
        _set_route(self, consumidor, tap, enable, verify)

    def routes(self):
        """Los cuatro ruteos de una, para imprimir."""
        return integration_get_routes(self)

    def reset_routes(self):
        """Devolver los cuatro consumidores a NATIVO habilitado.

        Es el estado de reset del hardware, o sea el comportamiento
        pre-refactor. Sirve para volver a terreno conocido sin recargar el
        bitstream.
        """
        integration_reset_routes(self)

    # ---------- control y estado global ----------

    def set_run(self, on=True):
        integration_set_run(self, on)

    def get_run(self):
        return integration_get_run(self)

    def clear(self):
        """Pulso global de clear (el HW lo autolimpia en un ciclo)."""
        integration_clear(self)

    def soft_reset(self):
        """Pulso global de soft reset (autolimpiante)."""
        integration_soft_reset(self)

    def status(self):
        return integration_get_status(self)

    # ---------- volcado ----------

    def dump(self):
        """Volcado legible de la región entera."""
        integration_dump(self)


# =============================================================================
# Descubrimiento de bases — lo usan los otros drivers
# =============================================================================

def slot_base(modulo, default=None):
    """Base física de un módulo leída del bitstream, o `default` si no se puede.

    Devuelve `default` —sin lanzar— cuando no hay región de TOP, no hay
    /dev/mem o la PL no está programada: un driver que hardcodeaba su base
    tiene que poder seguir hardcodeándola. Lo que se gana es que, cuando la
    información ESTÁ, se usa.

    Se abre y se cierra el mapeo en cada llamada a propósito: se llama una vez
    por `open()` de driver, no en ningún camino caliente.
    """
    try:
        with integration_open() as ig:
            return ig.base(modulo)
    except (IntegrationNotPresent, OSError, ValueError, KeyError):
        return default


# =============================================================================
# API por nombre — nomenclatura <módulo>_<capa>_<campo> (ver API/README.md)
# =============================================================================

def integration_open(phys=INTEGRATION_PHYS, size=INTEGRATION_SIZE,
                     check_magic=True, impl=None):
    """Abre la región de TOP. Devuelve el handle que usan las demás.

    `impl` elige la implementación: 'c' (libmca) o 'py' (la referencia Python,
    para benchmarks). Sin pedir ninguna se usa `$MCA_IMPL`, y si tampoco está,
    C; si libmca no carga se cae a Python **y se avisa**.
    """
    impl, aviso = _elegir_impl(impl)
    if aviso:
        print(f'warn: {aviso}', file=sys.stderr)
    if impl == 'py':
        h = _ref.Integration.open(phys, size, check_magic)
        h._via = 'py'
        h.impl = 'py'
        return h
    return Integration.open(phys, size, check_magic)


def integration_close(ig):
    ig.close()


@_api()
def integration_identify(ig, verbose=True):
    i = _Info()
    _ok(ig, _cargar().integration_identify(ig._c, ctypes.byref(i)), 'identify')
    info = {'magic':   i.magic,
            'version': tuple(i.version),
            'gith':    i.gith.decode()}
    if verbose:
        may, men, par, var = info['version']
        print(f'región de TOP: magic {info["magic"]:#010x} '
              f'v{may}.{men}.{par} (variante {var})')
        print(f'  git {info["gith"]}')
    return info


def integration_dump(ig):
    """Volcado legible de la región entera. Es composición: no toca registros."""
    integration_identify(ig)
    mods = integration_get_modules(ig)
    slots = integration_get_slots(ig)
    print('  módulos:', ' '.join(k for k, v in mods.items() if v) or '(ninguno)')
    print('  slots:  ', ' '.join(f'{k}={v}' for k, v in sorted(
        slots.items(), key=lambda kv: kv[1])))
    c = integration_get_caps(ig)
    print(f'  caps:    n_ch={c["n_ch"]} dw={c["dw"]} rsz={c["rsz"]} '
          f'en_filt={c["en_filt"]} h_aw={c["h_aw"]} h2_aw={c["h2_aw"]} '
          f'psd_aw={c["psd_aw"]}')
    for nombre, r in integration_get_routes(ig).items():
        marca = '' if r['enable'] else '   [DESHABILITADO]'
        print(f'  route {nombre:<5} tap={r["tap"]} {r["nombre"]}{marca}')
    st = integration_get_status(ig)
    print(f'  status:  pll_locked={st["pll_locked"]} adc_rstn={st["adc_rstn"]} '
          f'run={integration_get_run(ig)}')


# --- descripción del sistema ---

@_api()
def integration_get_modules(ig):
    m = _Modules()
    _ok(ig, _cargar().integration_get_modules(ig._c, ctypes.byref(m)), 'get_modules')
    return _dict(m, bool)


@_api()
def integration_get_slots(ig):
    s = _Slots()
    _ok(ig, _cargar().integration_get_slots(ig._c, ctypes.byref(s)), 'get_slots')
    return _dict(s)


@_api()
def integration_get_base(ig, m):
    v = ctypes.c_uint32()
    _ok(ig, _cargar().integration_get_base(ig._c, _I_SLOT.get(m, -1), ctypes.byref(v)),
        'get_base', m)
    return v.value


@_api()
def integration_get_caps(ig):
    c = _Caps()
    _ok(ig, _cargar().integration_get_caps(ig._c, ctypes.byref(c)), 'get_caps')
    d = _dict(c)
    d['en_filt'] = bool(d['en_filt'])
    return d


# --- ruteo ---

@_api()
def integration_get_routes(ig):
    r = (_Route * len(_I_CONSUMIDOR))()
    _ok(ig, _cargar().integration_get_routes(ig._c, r, len(r)), 'get_routes')
    return {c: _ruta(x) for c, x in zip(_I_CONSUMIDOR, r)}


@_api()
def integration_reset_routes(ig):
    _ok(ig, _cargar().integration_reset_routes(ig._c), 'reset_routes')


@_api()
def integration_get_route_osc(ig):
    return _get_route(ig, 'osc')


@_api()
def integration_get_route_mtrg(ig):
    return _get_route(ig, 'mtrg')


@_api()
def integration_get_route_mca(ig):
    return _get_route(ig, 'mca')


@_api()
def integration_get_route_ring(ig):
    return _get_route(ig, 'ring')


@_api()
def integration_set_route_osc(ig, tap=TAP_NATIVE, enable=True):
    _set_route(ig, 'osc', tap, enable, True)


@_api()
def integration_set_route_mtrg(ig, tap=TAP_NATIVE, enable=True):
    _set_route(ig, 'mtrg', tap, enable, True)


@_api()
def integration_set_route_mca(ig, tap=TAP_NATIVE, enable=True):
    _set_route(ig, 'mca', tap, enable, True)


@_api()
def integration_set_route_ring(ig, tap=TAP_NATIVE, enable=True):
    _set_route(ig, 'ring', tap, enable, True)


# --- control global ---

@_api()
def integration_get_run(ig):
    v = _I32()
    _ok(ig, _cargar().integration_get_run(ig._c, ctypes.byref(v)), 'get_run')
    return bool(v.value)


@_api()
def integration_set_run(ig, on=True):
    _ok(ig, _cargar().integration_set_run(ig._c, 1 if on else 0), 'set_run')


@_api()
def integration_clear(ig):
    _ok(ig, _cargar().integration_clear(ig._c), 'clear')


@_api()
def integration_soft_reset(ig):
    _ok(ig, _cargar().integration_soft_reset(ig._c), 'soft_reset')


@_api()
def integration_get_status(ig):
    s = _Status()
    _ok(ig, _cargar().integration_get_status(ig._c, ctypes.byref(s)), 'get_status')
    return _dict(s, bool)


if __name__ == '__main__':
    with integration_open() as _ig:
        integration_dump(_ig)
