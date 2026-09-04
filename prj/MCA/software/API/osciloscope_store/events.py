"""Esquema del evento y el lote (batch) preasignado.

El pipeline no mueve eventos sueltos: mueve `EventBatch`, bloques de arrays
preasignados. Eso cumple tres cosas a la vez:

- **RAM acotada y conocida de antemano.** El pool de batches se asigna al
  arrancar y no crece con la duracion de la corrida (el problema de
  `guardado_mariana.py`, donde la lista de eventos crece hasta el final y un
  corte se lleva todo).
- **Sin allocations en el lazo caliente.** El lector escribe adentro de arrays
  que ya existen; no hay basura para el GC entre evento y evento.
- **Migracion barata a multiprocessing.** Al ser arrays de tamano fijo, el pool
  pasa a `multiprocessing.shared_memory` sin tocar el resto (escalon 5 de las
  mitigaciones de GIL, ver docs/arquitectura_adquisicion_software.md).

El esquema NO esta hardcodeado: se arma en runtime a partir de lo que declaren
la fuente y los annotators, asi que agregar columnas (features del MCA en HW,
posicion, GPS) no toca ni al lector ni al escritor ni al formato de archivo.
"""

import numpy as np

SCHEMA_VERSION = 1

# Columnas que existen siempre, independientemente de la fuente.
#   t_ns : reloj de SW (perf_counter_ns), monotono, jitter de us
#   wp   : wp_trig del HW (0x1C), 8 ns de resolucion pero envuelve cada 16384
#   snap : trig_snapshot (0x218), que fuente disparo el evento
#   gap  : eventos descartados JUSTO ANTES de este  <- lo escribe el lector
#
# Se guardan los dos relojes crudos a proposito: los Delta-t son un np.diff
# offline, no se calculan en el lazo.
BASE_FIELDS = (
    ('t_ns', np.int64),
    ('wp',   np.int32),
    ('snap', np.uint32),
    ('gap',  np.uint8),
)

GAP_MAX = 255          # `gap` es uint8 y satura: ver nota en EventBatch.gap


class EventBatch:
    """Bloque de `capacity` eventos con todos sus arrays preasignados.

    `n` marca cuantos eventos son validos (el lector puede entregar un batch
    parcial al cerrar la corrida).

    Cada campo escalar queda accesible como atributo (`batch.t_ns`) ademas de
    en `batch.scalars`: en el lazo caliente el atributo evita un lookup de dict
    por evento.
    """

    # Sin __slots__ a proposito: los nombres de las columnas se deciden en
    # runtime (fuente + annotators), asi que no se pueden declarar por
    # adelantado. Son unos pocos objetos por corrida; el __dict__ no pesa.

    def __init__(self, capacity, n_ch, samples, scalar_fields=BASE_FIELDS,
                 wave_dtype=np.float32):
        self.capacity = capacity
        self.n_ch     = n_ch
        self.samples  = samples
        self.n        = 0
        # Total EXACTO de descartes atribuidos a este chunk. Va aparte de la
        # columna `gap` justamente porque `gap` es uint8 y satura: una rafaga de
        # 838 descartes deja gap=255 en el evento que la sigue, pero el total
        # tiene que seguir cerrando. `gap` responde "hay un hueco aca?"; esto
        # responde "cuantos".
        self.dropped  = 0

        # (eventos, canal, muestra). El canal es un EJE, no un nombre de
        # variable: el mismo codigo sirve para 2 o 4 canales (la RTL ya es
        # parametrica en N_CH).
        self.wave = np.zeros((capacity, n_ch, samples), dtype=wave_dtype)

        self.scalars = {}
        for name, dt in scalar_fields:
            arr = np.zeros(capacity, dtype=dt)
            self.scalars[name] = arr
            setattr(self, name, arr)
        self.field_names = tuple(self.scalars)

    def reset(self):
        """Deja el batch listo para volver a llenarse (no borra los arrays: los
        datos viejos quedan pisados por los nuevos, y `n` acota lo valido)."""
        self.n = 0
        self.dropped = 0

    @property
    def nbytes(self):
        return self.wave.nbytes + sum(a.nbytes for a in self.scalars.values())

    def payload(self, wave_dtype=None, wave_scale=None):
        """Arrays recortados a `n`, listos para `np.savez`.

        `wave_dtype`/`wave_scale`: conversion opcional de la onda al escribir
        (tipicamente float32 en volts -> int16 en cuentas). Se hace ACA, en el
        hilo escritor, no en el lector: es trabajo que no pertenece al camino
        critico.
        """
        w = self.wave[:self.n]
        if wave_dtype is not None and w.dtype != wave_dtype:
            if wave_scale:
                w = np.rint(w * wave_scale)
            w = w.astype(wave_dtype)
        out = {'wave': w}
        for name, arr in self.scalars.items():
            out[name] = arr[:self.n]
        return out


def bytes_per_event(n_ch, samples, scalar_fields=BASE_FIELDS,
                    wave_dtype=np.float32):
    """Bytes de RAM por evento. Se usa para derivar `n_batches` del presupuesto."""
    return (n_ch * samples * np.dtype(wave_dtype).itemsize
            + sum(np.dtype(dt).itemsize for _, dt in scalar_fields))


def make_pool(n_batches, capacity, n_ch, samples, scalar_fields=BASE_FIELDS,
              wave_dtype=np.float32):
    """Pool de batches preasignados (lo que va a la cola de libres)."""
    return [EventBatch(capacity, n_ch, samples, scalar_fields, wave_dtype)
            for _ in range(n_batches)]


def batches_for_budget(budget_mb, capacity, n_ch, samples,
                       scalar_fields=BASE_FIELDS, wave_dtype=np.float32,
                       minimum=2, maximum=8):
    """Cuantos batches entran en `budget_mb`, acotado a [minimum, maximum].

    El usuario da un presupuesto de RAM y el sistema deriva la profundidad de
    cola, en vez de pedirle que elija un numero de batches a ciegas.

    - `minimum=2`: con uno solo el lector se queda sin destino apenas el
      escritor toma el batch.
    - `maximum=8`: el presupuesto es un TECHO, no un objetivo. Lo que la cola
      tiene que cubrir es el tiempo de un chunk (86 ms medidos) mas los stalls
      de GIL (5.3 ms); 8 batches dan segundos de margen. Mas profundidad no
      compra nada y solo retrasa el momento en que los datos llegan al disco.
    """
    per = capacity * bytes_per_event(n_ch, samples, scalar_fields, wave_dtype)
    return max(minimum, min(maximum, int(budget_mb * 1024**2 // per)))
