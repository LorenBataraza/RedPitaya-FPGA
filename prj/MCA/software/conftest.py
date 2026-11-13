"""Ancla del árbol de software: hace importable `API`, `app` y los shims, y hace
que un `check()` que falla le falle a pytest.

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

## `check()` bajo pytest

Muchos tests están escritos para correr de dos formas: sueltos (`python3
test_x.py`, que imprime todas las comprobaciones y sale con código 1 si alguna
falló) y bajo pytest (`make verificar`). El estilo suelto usa un `check(...)` que
**registra** la falla en una lista del módulo en vez de lanzar, para poder imprimir
el cuadro completo en vez de cortar en la primera.

Eso deja un agujero bajo pytest: una función `test_*` que sólo llama a `check`
nunca lanza, y **una función que no lanza es un PASS**. Verificado rompiendo una
comprobación a propósito: pytest seguía en verde.

La solución es cambiar `check` por una versión que LANCE, sólo mientras corre
pytest. Se probaron dos caminos peores antes de éste, y conviene dejarlos anotados
para no repetirlos:

  - un fixture `autouse` que revise la lista al final: la excepción cae en el
    teardown y pytest lo reporta como ERROR, que se lee como "el test explotó" en
    vez de "el test falló";
  - un hookwrapper sobre `pytest_runtest_call` con `force_exception`: ese método no
    existe en el `_Result` de pytest 7.2.1 (el de esta máquina), así que el test
    fallaba igual pero con un `AttributeError` del conftest en vez del motivo real.
    Un mensaje de falla que miente es peor que no tenerlo.

Cambiar `check` no depende de ninguna API interna de pytest. La contra es que bajo
pytest se corta en la primera comprobación fallada; corriendo el fichero suelto se
sigue viendo completo, que es cuando uno quiere el cuadro.
"""

import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.abspath(__file__))

if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# Cómo se llama la lista de fallas en los distintos tests. Las firmas de `check`
# también varían (`check(nombre, ok, detalle)`, `check(cond, msg)`), así que la falla
# se detecta porque la lista creció, no mirando los argumentos.
_LISTAS_DE_FALLAS = ('FAILS', 'FALLAS', '_fallos')


@pytest.fixture(autouse=True)
def check_que_lanza(request, monkeypatch):
    mod = getattr(request, 'module', None)
    original = getattr(mod, 'check', None)
    fallas = next((getattr(mod, n) for n in _LISTAS_DE_FALLAS if hasattr(mod, n)),
                  None)
    if original is None or fallas is None:
        return                          # módulo con otro estilo: no se toca

    def check(*args, **kw):
        antes = len(fallas)
        resultado = original(*args, **kw)   # imprime y registra, como siempre
        if len(fallas) > antes:
            textos = [a for a in (*args, *kw.values()) if isinstance(a, str) and a]
            raise AssertionError(' — '.join(textos) or repr(fallas[-1]))
        return resultado

    monkeypatch.setattr(mod, 'check', check)
