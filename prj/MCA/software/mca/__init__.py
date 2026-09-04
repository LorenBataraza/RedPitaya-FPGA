"""SHIM de compatibilidad — el pipeline vive en `API/osciloscope_store/`.

Este paquete se llamaba `mca` pero NO es el analizador multicanal: es el
pipeline de adquisición y guardado del flujo de eventos del osciloscopio
(`ReaderThread`, `ChunkWriter`, `AcquisitionSession`). El refactor lo movió a
`API/osciloscope_store/`, que dice lo que hace.

Se mantiene este shim para no tocar los ~40 importadores, los notebooks ni los
scripts que ya corren en la placa. Código nuevo: importar de `API`::

    from API.osciloscope_store import AcquisitionSession, BramSource

Retirar el shim y migrar los call sites es un paso posterior.
"""

from API.osciloscope_store import (                                # noqa: F401
    Annotator, CachedAnnotator, ConstantAnnotator,
    EventBatch, SCHEMA_VERSION, bytes_per_event,
    ReaderThread, ChunkWriter, load_chunk,
    AcquisitionSession, scope_regs,
    BramSource, FakeSource,
)

__all__ = [
    'Annotator', 'CachedAnnotator', 'ConstantAnnotator',
    'EventBatch', 'SCHEMA_VERSION', 'bytes_per_event',
    'ReaderThread', 'ChunkWriter', 'load_chunk',
    'AcquisitionSession', 'scope_regs',
    'BramSource', 'FakeSource',
]
