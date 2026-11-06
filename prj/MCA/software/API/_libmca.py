"""Carga de `libmca` (la API en C) y traducción de sus códigos de error.

Es el único módulo de Python que sabe que hay una biblioteca de C abajo: los
bindings de cada bloque (`API/mca.py`, …) llaman a `cargar()` y a `check()`,
y nada más. La biblioteca se arma con `make -C libmca` (ver su Makefile).

Dónde se la busca, en orden:

  1. `$MCA_LIB`, si está definida. Si apunta a algo que no carga, es un error:
     no se cae en silencio a otra copia, porque quien la definió quería ésa.
  2. `software/libmca/build/<platform.machine()>/libmca.so`, relativo a este
     fichero: en la PC (`x86_64`), en la placa tras `make placa-sync`
     (`armv7l`) y en una instalación, porque el paquete de `make release`
     lleva el árbol entero con el .so de ARM ya compilado y chequeado.

El acceso al bus está envuelto en `Bus`, que es un `mca_bus*` con sus dos
backends: `Bus.devmem()` (la PL) y `Bus.callbacks()` (un modelo en Python,
como `FakeMCA`, enchufado a la lógica de C por punteros a función).
"""

import ctypes
import os
import platform

import numpy as np

_SOFT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Los códigos de include/mca_api.h.
MCA_OK          = 0
MCA_EINVAL      = -1
MCA_ENOTPRESENT = -2
MCA_ETIMEOUT    = -3
MCA_ENOSYS      = -4
MCA_EALIGN      = -5
MCA_ERANGE      = -6
MCA_EOPEN       = -7
MCA_ENOMEM      = -8
MCA_EBACKEND    = -9
MCA_EVERIFY     = -10


class LibMCAError(RuntimeError):
    """Un error de libmca sin una excepción de Python más específica."""

    def __init__(self, msg, rc):
        super().__init__(msg)
        self.rc = rc


# Cada código, a la excepción que la API de Python ya lanzaba en el mismo caso.
# MCA_ENOTPRESENT no está: depende del bloque (MCANotPresent,
# IntegrationNotPresent) y lo pasa quien llama. MCA_EOPEN tampoco: se arma
# un OSError con el errno real, así un "sin root" sale como PermissionError.
_EXCEPCIONES = {
    MCA_EINVAL:   ValueError,
    MCA_EALIGN:   ValueError,
    MCA_ERANGE:   ValueError,
    MCA_ETIMEOUT: TimeoutError,
    MCA_ENOMEM:   MemoryError,
}


# =============================================================================
# Carga
# =============================================================================

_lib = None
_motivo = None          # por qué no cargó, para el aviso de quien cae a Python


def candidatos():
    """Las rutas donde se busca el .so, en el orden en que se prueban."""
    env = os.environ.get('MCA_LIB')
    if env:
        return [env]
    return [os.path.join(_SOFT, 'libmca', 'build', platform.machine(),
                         'libmca.so')]


def cargar():
    """La biblioteca, cargada y con sus firmas declaradas. OSError si no está."""
    global _lib, _motivo
    if _lib is not None:
        return _lib
    errores = []
    for ruta in candidatos():
        if not os.path.exists(ruta):
            errores.append(f'{ruta}: no existe')
            continue
        try:
            # use_errno: mca_bus_open_* devuelve MCA_EOPEN y deja el errno de
            # open()/mmap(); sin esto no se distingue "sin root" de "no hay".
            lib = ctypes.CDLL(ruta, use_errno=True)
        except OSError as e:
            errores.append(f'{ruta}: {e}')
            continue
        _declarar(lib)
        _lib = lib
        _motivo = None
        return lib
    _motivo = '; '.join(errores)
    raise OSError(f'no se pudo cargar libmca ({_motivo}). '
                  'Compilarla con: make -C libmca')


def disponible():
    try:
        cargar()
        return True
    except OSError:
        return False


def motivo():
    """Por qué no cargó la última vez, o None."""
    return _motivo


def version():
    return cargar().mca_lib_version().decode()


def build():
    return cargar().mca_lib_build().decode()


# =============================================================================
# Firmas
# =============================================================================

_R32 = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                        ctypes.POINTER(ctypes.c_uint32))
_W32 = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                        ctypes.c_uint32)
_RW  = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                        ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32))


class _BusOps(ctypes.Structure):
    _fields_ = [('r32', _R32), ('w32', _W32), ('read_words', _RW),
                ('ctx', ctypes.c_void_p)]


_P  = ctypes.c_void_p
_U  = ctypes.c_uint32
_PU = ctypes.POINTER(ctypes.c_uint32)
_PP = ctypes.POINTER(ctypes.c_void_p)


def _palabra(t):
    """¿ctypes pasa igual un argumento de este tipo con y sin argtypes?"""
    return (t in (ctypes.c_uint32, ctypes.c_int32) or t is ctypes.c_void_p
            or issubclass(t, ctypes._Pointer))


def version_rapida(lib, nombre):
    """La función ya declarada, o una copia SIN argtypes si eso es seguro.

    En el ARM de la placa ctypes tarda 10.7 µs en convertir (void*, uint32_t*)
    con argtypes y 4.4 µs sin ellos (docs/API/diseno_de_clases.md §4.5). Sin
    argtypes ctypes pasa un int de Python como int de C, y un c_void_p, un
    byref o un arreglo como puntero: es correcto sólo si TODOS los parámetros
    son punteros o enteros de 32 b, y eso se comprueba contra lo declarado. Las
    que reciben int64 o double se devuelven tal cual. Quien llama a una copia
    pasa siempre un c_void_p como puntero, nunca un int (en x86-64 se
    truncaría a 32 b).
    """
    decl = getattr(lib, nombre)
    if not all(_palabra(t) for t in decl.argtypes):
        return decl
    fn = lib[nombre]                          # objeto nuevo, sin argtypes
    fn.restype = decl.restype
    return fn


_R = {}                 # nombre -> version_rapida, para Bus


def _declarar(lib):
    def f(nombre, res, *args):
        fn = getattr(lib, nombre)
        fn.restype = res
        fn.argtypes = list(args)

    f('mca_strerror',          ctypes.c_char_p, ctypes.c_int)
    f('mca_lib_version',       ctypes.c_char_p)
    f('mca_lib_build',         ctypes.c_char_p)
    f('mca_bus_open_devmem',   ctypes.c_int, _PP, _U, _U)
    f('mca_bus_open_file',     ctypes.c_int, _PP, ctypes.c_char_p, _U, _U)
    f('mca_bus_open_callback', ctypes.c_int, _PP, ctypes.POINTER(_BusOps), _U)
    f('mca_bus_close',         None, _P)
    f('mca_bus_r32',           ctypes.c_int, _P, _U, _PU)
    f('mca_bus_w32',           ctypes.c_int, _P, _U, _U)
    f('mca_bus_read_words',    ctypes.c_int, _P, _U, _U, _PU)
    f('mca_bus_size',          _U, _P)
    for nombre in ('mca_bus_r32', 'mca_bus_w32', 'mca_bus_read_words'):
        _R[nombre] = version_rapida(lib, nombre)


# =============================================================================
# Errores
# =============================================================================

def check(rc, contexto='', excepciones=None, detalle=None):
    """rc de libmca -> nada si es MCA_OK, la excepción correspondiente si no.

    `excepciones` agrega o pisa entradas de la tabla, p. ej.
    `{MCA_ENOTPRESENT: MCANotPresent}` desde el binding del MCA. `detalle` es
    el texto de `mca_last_error()`: si C dejó uno, ése ES el mensaje (sin
    prefijo, para que diga exactamente lo que decía la versión de Python).
    """
    if rc == MCA_OK:
        return
    if detalle:
        msg = detalle
    else:
        msg = cargar().mca_strerror(rc).decode()
        if contexto:
            msg = f'{contexto}: {msg}'
    if rc == MCA_EOPEN:
        e = ctypes.get_errno()
        raise OSError(e, f'{msg} ({os.strerror(e)})')
    exc = (excepciones or {}).get(rc) or _EXCEPCIONES.get(rc)
    if exc is None:
        raise LibMCAError(msg, rc)
    raise exc(msg)


# =============================================================================
# Bus
# =============================================================================

class Bus:
    """Un `mca_bus*` de libmca: el nivel 2, con alineación y rango verificados
    en C antes de llegar al backend.

    Con `callbacks()`, una excepción que se lance adentro de r32/w32 no puede
    cruzar la frontera de C (ctypes la imprimiría y devolvería 0, o sea un
    acceso "exitoso" con basura). Se guarda, el callback devuelve
    MCA_EBACKEND, y `check()` la vuelve a lanzar acá, intacta, cuando C
    termina.
    """

    def __init__(self, ptr, guardas=None):
        self._p = ptr
        # Los CFUNCTYPE tienen que vivir lo mismo que el bus: si el recolector
        # se los lleva mientras C guarda sus punteros, el próximo acceso salta
        # a memoria liberada (segfault, sin traceback).
        self._guardas = guardas
        self._pendiente = None

    # ---------- apertura ----------

    @classmethod
    def devmem(cls, phys, size):
        lib = cargar()
        p = ctypes.c_void_p()
        check(lib.mca_bus_open_devmem(ctypes.byref(p), phys, size),
              f'/dev/mem @ {phys:#x}')
        return cls(p)

    @classmethod
    def archivo(cls, path, phys, size):
        """El backend devmem sobre un fichero común: para tests sin placa."""
        lib = cargar()
        p = ctypes.c_void_p()
        check(lib.mca_bus_open_file(ctypes.byref(p), os.fsencode(path), phys,
                                    size), str(path))
        return cls(p)

    @classmethod
    def callbacks(cls, r32, w32, read_words=None, size=0):
        """Un bus cuyos accesos son funciones de Python.

        `r32(off) -> int`, `w32(off, val)` y, opcional, `read_words(off, n)
        -> secuencia de n enteros`. Sin `read_words`, C hace n llamadas a r32.
        """
        bus = cls(None)

        def envolver(fn):
            # Cierra sobre `bus` para dejar la excepción donde check() la ve.
            def cb(*args):
                try:
                    return fn(*args)
                except BaseException as e:              # noqa: BLE001
                    bus._pendiente = e
                    return MCA_EBACKEND
            return cb

        def _r(_ctx, off, val):
            val[0] = int(r32(off)) & 0xFFFFFFFF
            return MCA_OK

        def _w(_ctx, off, val):
            w32(off, val)
            return MCA_OK

        def _rw(_ctx, off, n, dst):
            np.ctypeslib.as_array(dst, shape=(n,))[:] = read_words(off, n)
            return MCA_OK

        ops = _BusOps(_R32(envolver(_r)), _W32(envolver(_w)),
                      _RW(envolver(_rw)) if read_words is not None else _RW(),
                      None)
        lib = cargar()
        p = ctypes.c_void_p()
        check(lib.mca_bus_open_callback(ctypes.byref(p), ctypes.byref(ops),
                                        size), 'bus por callbacks')
        bus._p = p
        bus._guardas = ops
        return bus

    # ---------- errores ----------

    def check(self, rc, contexto='', excepciones=None, detalle=None):
        """Como `check()`, pero primero relanza la excepción de un callback."""
        if self._pendiente is not None:
            e, self._pendiente = self._pendiente, None
            raise e
        check(rc, contexto, excepciones, detalle)

    # ---------- acceso ----------

    @property
    def ptr(self):
        """El `mca_bus*`, para pasárselo a las funciones de cada bloque."""
        if self._p is None:
            raise ValueError('bus cerrado')
        return self._p

    # Sin `cargar()` ni el contexto del error en el camino que sale bien: cada
    # llamada de Python cuesta ~1 µs en la placa. Un Bus existe sólo si la
    # biblioteca cargó, así que _R ya está lleno.

    def r32(self, off):
        v = ctypes.c_uint32()
        rc = _R['mca_bus_r32'](self.ptr, off, ctypes.byref(v))
        if rc or self._pendiente is not None:
            self.check(rc, f'r32 {off:#x}')
        return v.value

    def w32(self, off, val):
        rc = _R['mca_bus_w32'](self.ptr, off, int(val) & 0xFFFFFFFF)
        if rc or self._pendiente is not None:
            self.check(rc, f'w32 {off:#x}')

    def read_words(self, off, n):
        """n palabras desde `off`, de a una, en un np.ndarray uint32."""
        dst = np.empty(n, dtype=np.uint32)
        rc = _R['mca_bus_read_words'](self.ptr, off, n, dst.ctypes.data_as(_PU))
        if rc or self._pendiente is not None:
            self.check(rc, f'read_words {off:#x} x{n}')
        return dst

    @property
    def size(self):
        return cargar().mca_bus_size(self.ptr)

    def close(self):
        if self._p is not None:
            cargar().mca_bus_close(self._p)
            self._p = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
