#!/usr/bin/env python3
"""El decorador `@api` de `API/_despacho.py`: a dónde va cada llamada.

No necesita libmca ni la placa: el "cuerpo de C" de las funciones de prueba es
Python, y lo que se verifica es sólo el ruteo según `h._via`.

    python -m pytest API/tests/test_despacho.py -q
"""

import pytest

from API import _despacho as D


@D.api()
def _prueba_leer(h, x=1):
    return ('c', x)


@D.api(remoto=False)
def _prueba_bloquea(h):
    return 'c'


class Handle:
    def __init__(self, via=None):
        if via is not None:
            self._via = via
        self.llamadas = []

    def call(self, nombre, *a, **k):
        self.llamadas.append((nombre, a, k))
        return ('remoto', nombre)


def test_sin_via_es_c():
    assert _prueba_leer(Handle(), x=3) == ('c', 3)
    assert _prueba_leer(Handle('c')) == ('c', 1)


def test_remoto_va_entero_por_call():
    # La envoltura tiene la firma de la función: lo que sale por `call` va ya
    # ligado, posicional y con los defaults puestos.
    h = Handle('remoto')
    assert _prueba_leer(h, 5) == ('remoto', '_prueba_leer')
    assert _prueba_leer(h, x=2) == ('remoto', '_prueba_leer')
    assert _prueba_leer(h) == ('remoto', '_prueba_leer')
    assert h.llamadas == [('_prueba_leer', (5,), {}), ('_prueba_leer', (2,), {}),
                          ('_prueba_leer', (1,), {})]


def test_una_llamada_mal_formada_falla_antes_de_despachar():
    h = Handle('remoto')
    with pytest.raises(TypeError):
        _prueba_leer(h, 5, x=2)
    assert h.llamadas == []


def test_la_envoltura_conserva_nombre_firma_y_doc():
    import inspect
    from API import mca as A
    assert A.mca_set_n_acc.__name__ == 'mca_set_n_acc'
    assert str(inspect.signature(A.mca_set_n_acc)) == '(h, v)'
    assert A.mca_clear.__defaults__ == (1.0,)
    assert A.mca_clear.__doc__ and 'Borra' in A.mca_clear.__doc__


def test_las_que_bloquean_no_van_por_red():
    with pytest.raises(D.NoRemota):
        _prueba_bloquea(Handle('remoto'))
    assert _prueba_bloquea(Handle('c')) == 'c'


def test_py_sin_referencia_lo_dice():
    # Este módulo de test no tiene referencia en API/ref_py/.
    with pytest.raises(NotImplementedError, match='referencia'):
        _prueba_leer(Handle('py'))


def _correr_py(monkeypatch, modulo_ref, h):
    """Decora un mca_start de mentira y lo corre con `h`: devuelve a qué
    referencia fue (la que tiene el monkeypatch)."""
    import importlib
    ref = importlib.import_module(modulo_ref)
    llamado = []
    monkeypatch.setattr(ref, 'mca_start', lambda h: llamado.append(h) or True)

    def mca_start(h):
        raise AssertionError('no tenía que correr el cuerpo de C')
    mca_start.__module__ = 'API.mca'          # el decorador lo lee al decorar

    previa = D.API_REGISTRADA.get('mca_start')
    try:
        envuelta = D.api()(mca_start)
        assert envuelta(h) is True and llamado == [h]
    finally:
        if previa is None:
            D.API_REGISTRADA.pop('mca_start', None)
        else:
            D.API_REGISTRADA['mca_start'] = previa


def test_py_usa_la_referencia_del_mca2(monkeypatch):
    # Una función de API.mca con h._via == 'py' corre la de API.ref_py.mca2.
    _correr_py(monkeypatch, 'API.ref_py.mca2', Handle('py'))


def test_un_handle_mca1_usa_su_referencia(monkeypatch):
    # El handle MCA1 que abre mca_open(impl='py') trae `_referencia`.
    h = Handle('py')
    h._referencia = 'API.ref_py.mca'
    _correr_py(monkeypatch, 'API.ref_py.mca', h)


def test_lo_que_no_esta_en_la_referencia_lo_dice():
    h = Handle('py')
    h._referencia = 'API.ref_py.mca'                # el MCA1 no tiene ranuras
    from API import mca as A
    with pytest.raises(NotImplementedError, match='mca_get_n_acc'):
        A.mca_get_n_acc(h)


def test_registro_y_lista_blanca():
    assert D.API_REGISTRADA['_prueba_leer'].remoto is True
    assert D.API_REGISTRADA['_prueba_bloquea'].remoto is False
    assert D.API_REGISTRADA['_prueba_leer'].cuerpo(None) == ('c', 1)


def test_via_desconocida():
    with pytest.raises(ValueError, match='_via'):
        _prueba_leer(Handle('gpu'))


def test_elegir_impl(monkeypatch):
    monkeypatch.delenv('MCA_IMPL', raising=False)
    assert D.elegir_impl('py') == ('py', None)
    assert D.elegir_impl(None, c_disponible=True) == ('c', None)
    impl, aviso = D.elegir_impl(None, c_disponible=False)
    assert impl == 'py' and 'libmca' in aviso
    monkeypatch.setenv('MCA_IMPL', 'py')
    assert D.elegir_impl(None, c_disponible=True) == ('py', None)
    with pytest.raises(ValueError):
        D.elegir_impl('fortran')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
