"""SHIM de compatibilidad — el event_ring vive en `API/osciloscope_ring.py`.

`API/tests/test_ring_source.py` importa este submódulo por nombre
(`from mca.ring_source import RingSource, R_CTRL, ...`), así que el shim del
paquete no alcanza: hace falta también el módulo.

Código nuevo: `from API.osciloscope_ring import RingSource`.
"""

from API.osciloscope_ring import *                                 # noqa: F401,F403
from API.osciloscope_ring import (                                 # noqa: F401
    RingSource,
    RING_PHYS, RING_SIZE, MAGIC, ADC_CNT_PER_V,
    HDR_BYTES, FOOTER_BYTES, MAX_BATCH_BYTES,
    R_CTRL, R_STATUS, R_SLOT_BASE, R_RING_SZ, R_SLOT_SHIFT,
    R_PRE, R_POST, R_WR_SLOT, R_RD_SLOT, R_SEQ, R_N_SLOTS,
    R_DROP_BUSY, R_DROP_FULL, R_EV_CNT, R_LVL,
    R_TS_LO, R_TS_HI, R_AXI_ADDR, R_MAGIC,
)
