"""Pipeline de adquisicion y guardado del MCA (lado servidor, en la Pitaya).

Cubre los bloques 1 y 3 del diseno del servidor: **lectura de evento** y
**rutina de guardado**. El dashboard y el handler de configuracion son hilos
aparte que se enganchan mas adelante (`AcquisitionSession.stats` es el punto de
enganche del primero; el directorio de chunks completos, el del segundo).

Arquitectura y numeros medidos: ../../docs/arquitectura_adquisicion_software.md

Uso tipico en la placa:

    from multitrigger_utils import MultiTriggerScope
    from mca import BramSource, AcquisitionSession

    sc  = MultiTriggerScope.open()
    src = BramSource(sc, pre=8, post=24, thr=0.5)
    with AcquisitionSession(src, '/home/jupyter/DATOS/corrida_01') as s:
        s.wait(duration_s=30)
    print(s.summary())

Offline, en la PC (sin placa ni modulo `rp`):

    from mca import FakeSource, AcquisitionSession
"""

from .annotators import (Annotator, CachedAnnotator, ConstantAnnotator,
                         DeadTimeAnnotator)
from .events import EventBatch, SCHEMA_VERSION, bytes_per_event
from .reader import ReaderThread
from .session import AcquisitionSession, scope_regs
from .sources import BramSource, FakeSource
from .storage import ChunkWriter, load_chunk

__all__ = [
    'Annotator', 'CachedAnnotator', 'ConstantAnnotator', 'DeadTimeAnnotator',
    'EventBatch', 'SCHEMA_VERSION', 'bytes_per_event',
    'ReaderThread', 'ChunkWriter', 'load_chunk',
    'AcquisitionSession', 'scope_regs',
    'BramSource', 'FakeSource',
]
