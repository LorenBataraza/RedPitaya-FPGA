"""Hace que pytest FALLE cuando falla un `check()` de estos tests.

Los tests de esta carpeta están escritos para correr de dos formas: sueltos
(`python3 test_x.py`, que imprime todas las comprobaciones y sale con código 1
si alguna falló) y bajo pytest (`make test-campanas`). El estilo suelto usa un
`check(nombre, cond)` que **registra** la falla en la lista `FALLAS` del módulo
en vez de lanzar, para poder imprimir el cuadro completo en vez de cortar en la
primera.

Eso deja un agujero bajo pytest: una función `test_*` que sólo llama a `check`
nunca lanza, y **una función que no lanza es un PASS**. Verificado rompiendo una
comprobación a propósito: pytest seguía reportando 4 passed. O sea que los tests
podían pudrirse sin que nadie se enterara, que es peor que no tenerlos — sobre
todo estos, que son la red que evita medir una sesión entera contra el bitstream
equivocado.

La solución es cambiar `check` por una versión que LANCE, sólo mientras corre
pytest. Se probaron dos caminos peores antes de éste, y conviene dejarlos
anotados para no repetirlos:

  - un fixture `autouse` que revise `FALLAS` al final: la excepción cae en el
    teardown y pytest lo reporta como ERROR, que se lee como "el test explotó"
    en vez de "el test falló";
  - un hookwrapper sobre `pytest_runtest_call` con `force_exception`: ese método
    no existe en el `_Result` de pytest 7.2.1 (el de esta máquina), así que el
    test fallaba igual pero con un `AttributeError` del conftest en vez del
    motivo real. Un mensaje de falla que miente es peor que no tenerlo.

Cambiar `check` no depende de ninguna API interna de pytest. La contra es que
bajo pytest se corta en la primera comprobación fallada en vez de imprimir el
cuadro entero; corriendo el fichero suelto se sigue viendo completo, que es
cuando uno quiere el cuadro.
"""
import pytest


@pytest.fixture(autouse=True)
def check_que_lanza(request, monkeypatch):
    mod = getattr(request, 'module', None)
    original = getattr(mod, 'check', None)
    fallas = getattr(mod, 'FALLAS', None)
    if original is None or fallas is None:
        return                          # módulo con otro estilo: no se toca

    def check(nombre, ok, detalle=''):
        original(nombre, ok, detalle)   # imprime y registra, como siempre
        if not ok:
            raise AssertionError(
                f'{nombre}' + (f' — {detalle}' if detalle else ''))
        return ok

    monkeypatch.setattr(mod, 'check', check)
