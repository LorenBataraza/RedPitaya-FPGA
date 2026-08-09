"""Annotators: informacion externa que se adjunta a cada evento.

Un GPS o un sensor de posicion **no es un EventSource**: no define cuando ocurre
un evento, lo *anota*. Y va 3-4 ordenes de magnitud mas lento (un GPS da 1-10 Hz;
los eventos pueden venir a decenas de kHz). Por eso son un concepto aparte.

LA REGLA que hace que esto no rompa el dead-time:

    `sample_into()` corre DENTRO del lazo caliente y no puede hacer I/O.
    Solo copia un valor ya cacheado.

Todo annotator lento corre su propio hilo (leyendo el puerto serie del GPS, por
ejemplo) y actualiza un atributo; `sample_into` lo copia. Son nanosegundos.

Y como el valor cacheado puede estar viejo, todo annotator asincronico declara
ademas un campo `*_age_ns`: sin eso, un GPS que perdio el fix hace diez minutos
escribe coordenadas plausibles y silenciosamente falsas en cada evento.
"""

import threading
import time

import numpy as np


class Annotator:
    """Interfaz. `scalar_fields` se suma al esquema del batch."""

    scalar_fields = ()

    def start(self):
        pass

    def sample_into(self, batch, i):
        raise NotImplementedError

    def stop(self):
        pass

    def meta(self):
        return {}


class ConstantAnnotator(Annotator):
    """Valores fijos por corrida. Sirve de referencia y para los tests."""

    def __init__(self, **values):
        self.values = values
        self.scalar_fields = tuple((k, np.float64) for k in values)

    def sample_into(self, batch, i):
        for k, v in self.values.items():
            batch.scalars[k][i] = v

    def meta(self):
        return dict(kind='constant', **self.values)


class CachedAnnotator(Annotator):
    """Base para fuentes asincronicas lentas (GPS, posicion, temperatura).

    La subclase implementa `poll()` -> dict de valores (o None si no hay dato
    nuevo). La clase base corre el hilo, cachea el ultimo valor con su
    timestamp, y expone `sample_into` como una copia pura.

    Declara automaticamente `<prefijo>_age_ns`: cuanto hace que se actualizo el
    valor que se esta guardando. Es lo que permite descartar offline los eventos
    anotados con datos rancios.
    """

    #: campos que produce `poll()`, como ((nombre, dtype), ...)
    value_fields = ()
    #: cada cuanto llamar a poll(), en segundos
    interval_s = 1.0
    #: nombre corto para el campo de antiguedad
    prefix = 'aux'

    def __init__(self):
        self.scalar_fields = tuple(self.value_fields) + (
            (f'{self.prefix}_age_ns', np.int64),)
        self._names   = [n for n, _ in self.value_fields]
        self._cache   = {n: 0.0 for n in self._names}
        self._t_ns    = 0
        self._lock    = threading.Lock()
        self._stop    = threading.Event()
        self._thread  = None
        self._age_key = f'{self.prefix}_age_ns'

    def poll(self):
        """Devuelve un dict {nombre: valor} o None. Puede bloquear: corre en su
        propio hilo, no en el del lector."""
        raise NotImplementedError

    def _loop(self):
        while not self._stop.is_set():
            try:
                v = self.poll()
            except Exception:
                v = None                      # una lectura fallida no mata el hilo
            if v:
                t = time.perf_counter_ns()
                with self._lock:
                    self._cache.update(v)
                    self._t_ns = t
            self._stop.wait(self.interval_s)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name=f'annot-{self.prefix}')
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2 * self.interval_s + 1)

    def sample_into(self, batch, i):
        # Sin lock a proposito: leer valores ya escritos es benigno bajo el GIL,
        # y tomar un lock por evento seria mas caro que todo lo demas junto.
        # Lo peor que puede pasar es mezclar un valor con la edad del anterior,
        # y ambos difieren en menos de `interval_s`.
        cache = self._cache
        s = batch.scalars
        for n in self._names:
            s[n][i] = cache[n]
        s[self._age_key][i] = (batch.t_ns[i] - self._t_ns) if self._t_ns else -1

    def meta(self):
        return dict(kind=type(self).__name__, interval_s=self.interval_s)


def merge_fields(source, annotators):
    """Esquema final del batch: lo que declara la fuente + cada annotator.

    Falla fuerte ante nombres repetidos: una colision silenciosa haria que dos
    productores se pisen la misma columna.
    """
    fields, seen = list(source.scalar_fields), set()
    for name, _ in fields:
        seen.add(name)
    for a in annotators:
        for name, dt in a.scalar_fields:
            if name in seen:
                raise ValueError(
                    f'columna duplicada {name!r}: {type(a).__name__} choca con '
                    'la fuente u otro annotator')
            seen.add(name)
            fields.append((name, dt))
    return tuple(fields)
