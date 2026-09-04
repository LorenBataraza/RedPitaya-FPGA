"""SHIM de compatibilidad — este módulo vive en `API/osciloscope_store/annotators.py`.

El paquete `mca/` se llamaba así pero NO es el analizador multicanal: es el
pipeline de guardado del flujo del osciloscopio. El refactor lo renombró a
`API/osciloscope_store/`.

Hay código que importa este submódulo POR NOMBRE (`from mca.annotators import ...`),
así que el shim del paquete no alcanza: hace falta también el módulo.

Código nuevo: `from API.osciloscope_store.annotators import ...`
"""

from API.osciloscope_store.annotators import *          # noqa: F401,F403
