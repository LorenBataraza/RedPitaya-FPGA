"""El despacho de la API de hardware: a C, a la referencia Python o a la red.

Cada función pública de hardware (`mca_set_thr`, `mca_read_histogram`, …)
lleva el decorador `@api`. Su cuerpo es la llamada a libmca; el decorador
decide, mirando `h._via`, si ese cuerpo corre o si la llamada va a otro lado:

    h._via == 'c'       el cuerpo: libmca por ctypes, sobre devmem o callbacks
    h._via == 'py'      la función de igual nombre en la implementación
                        Python de referencia (API/ref_py/): la del módulo
                        que diga `h._referencia`, o la de _REFERENCIA
    h._via == 'remoto'  h.call(nombre, *args, **kw): la función ENTERA corre en
                        la placa, como un comando SCPI en Red Pitaya

Un handle sin `_via` es 'c'.

El decorador además registra la función en `API_REGISTRADA`. Ese registro es la
lista blanca de la op `call` del servidor: se puede llamar por red lo que esté
acá con `remoto=True`, y nada más. Las que bloquean (`acquire`, los
`autoscale_*`) se registran con `remoto=False`: un `call` de diez segundos
tendría tomado el lock del servidor y congelaría la exposición y el `status`.
"""

import functools
import importlib
import inspect
import os
from collections import namedtuple

# nombre -> Entrada. `fn` es la envoltura que despacha; `cuerpo`, la función de
# C sin despacho (la que corre el servidor cuando atiende un `call`).
Entrada = namedtuple('Entrada', 'fn cuerpo remoto modulo')
API_REGISTRADA = {}

# El módulo del binding -> su referencia congelada.
_REFERENCIA = {
    'API.mca':          'API.ref_py.mca2',      # MCA1: h._referencia
    'API.integration':  'API.ref_py.integration',
    'API.multitrigger': 'API.ref_py.multitrigger',
    'API.osciloscope':  'API.ref_py.osciloscope',
}

IMPLS = ('c', 'py')


class NoRemota(RuntimeError):
    """La función no se puede llamar por red (bloquea el servidor)."""


def _de_referencia(modulo, nombre, h=None):
    # Un handle puede traer su propia referencia: el de MCA1 que abre
    # mca_open(impl='py') va a API/ref_py/mca.py, no al default (mca2).
    destino = getattr(h, '_referencia', None) or _REFERENCIA.get(modulo)
    try:
        if destino is None:
            raise KeyError(modulo)
        ref = importlib.import_module(destino)
    except KeyError:
        raise NotImplementedError(
            f'{modulo} no tiene implementación de referencia en API/ref_py/')
    try:
        return getattr(ref, nombre)
    except AttributeError:
        raise NotImplementedError(
            f'{nombre} existe sólo en libmca: la referencia Python está '
            'congelada y no se le agregan funciones (ver API/ref_py/)')


def _directa(fn, despachar):
    """Una envoltura con la MISMA firma que `fn`, que va directo a C.

    El despacho genérico recibe `*args, **kw` y en la placa eso cuesta ~5 µs
    por llamada, contra ~2 µs de una función con los parámetros con nombre
    (medido en docs/API/diseno_de_clases.md §4.5): más que la llamada a C de un
    get. Por eso, si todos los parámetros de `fn` son posicionales comunes, se
    genera `def f(h, v): return cuerpo(h, v) if <es C> else despachar(h, v)`
    con los mismos defaults. Si no, None, y queda el despacho genérico.
    """
    params = list(inspect.signature(fn).parameters.values())
    if not params or any(p.kind is not p.POSITIONAL_OR_KEYWORD for p in params):
        return None
    ps = ', '.join(p.name for p in params)
    h = params[0].name
    fuente = (f'def {fn.__name__}({ps}):\n'
              f'    if getattr({h}, "_via", "c") == "c":\n'
              f'        return cuerpo({ps})\n'
              f'    return despachar({ps})\n')
    ns = {}
    exec(fuente, {'cuerpo': fn, 'despachar': despachar}, ns)
    f = ns[fn.__name__]
    f.__defaults__ = fn.__defaults__
    return f


def api(remoto=True):
    """Decorador de las funciones públicas de hardware. Ver el módulo."""
    def deco(fn):
        nombre, modulo = fn.__name__, fn.__module__

        def despachar(h, *args, **kw):
            via = getattr(h, '_via', 'c')
            if via == 'c':
                return fn(h, *args, **kw)
            if via == 'py':
                return _de_referencia(modulo, nombre, h)(h, *args, **kw)
            if via == 'remoto':
                if not remoto:
                    # Lo que espera no viaja por `call`; el handle puede
                    # armarlo del lado del cliente (MCARemote.acquire).
                    local = getattr(h, 'en_el_cliente', lambda _n: None)(nombre)
                    if local is not None:
                        return local(*args, **kw)
                    raise NoRemota(
                        f'{nombre} no se llama por red: bloquearía el servidor. '
                        'Usar ctrl.start(seconds=...) y status.')
                return h.call(nombre, *args, **kw)
            raise ValueError(f'h._via desconocido: {via!r}')

        envoltura = functools.update_wrapper(_directa(fn, despachar) or despachar,
                                             fn)
        API_REGISTRADA[nombre] = Entrada(envoltura, fn, remoto, modulo)
        return envoltura
    return deco


def elegir_impl(impl=None, c_disponible=None):
    """'c' o 'py': lo pedido, o `$MCA_IMPL`, o 'c' si libmca carga.

    Devuelve `(impl, aviso)`. `aviso` no es None cuando se cayó a Python sin
    que nadie lo pidiera, para que quien abre lo diga en vez de medir con la
    implementación equivocada sin enterarse.
    """
    pedida = impl or os.environ.get('MCA_IMPL') or None
    if pedida is not None:
        if pedida not in IMPLS:
            raise ValueError(f'impl={pedida!r}: tiene que ser una de {IMPLS}')
        return pedida, None
    if c_disponible is None:
        from API import _libmca
        c_disponible = _libmca.disponible()
    if c_disponible:
        return 'c', None
    from API import _libmca
    return 'py', ('libmca no está disponible, se usa la implementación Python '
                  f'({_libmca.motivo()})')
