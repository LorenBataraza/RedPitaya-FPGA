"""Ancla del árbol de software: hace importable `API`, `app` y los shims.

Redundante con `pythonpath = ["."]` de pyproject.toml cuando pytest se invoca
desde `software/`, que es el caso normal. Existe para el otro caso: correrlo
desde la raíz del repo (`pytest prj/MCA/software`), donde el rootdir de pytest
no coincide con esta carpeta y `pythonpath` se resuelve contra el rootdir.

NO agregar `__init__.py` a los directorios de tests, ni más `conftest.py` en
los subdirectorios. Los paquetes sacan a pytest del modo rootdir-prepend, y de
ese modo dependen tres imports test-a-test que hoy funcionan:

    app/tests/test_mcamon_gui.py   -> from test_mca_remote import ServidorDePrueba
    API/tests/test_compat_api.py   -> import gen_compat_baseline
    API/tests/placa/hw_ring_swtrig.py -> from hw_ring_plumbing import ...
"""

import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))

if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
