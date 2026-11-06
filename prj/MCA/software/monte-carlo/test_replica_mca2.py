#!/usr/bin/env python3
"""La réplica del MCA2 contra el RTL entero, evento por evento.

El RTL es `mt_top` + `mca_top` cableados como en el top, corriendo en QuestaSim
sobre el estímulo de `datos_ref/mca2_estimulo.txt`; su volcado está en
`datos_ref/mca2_volcado.txt` (ver `volcado_mca2.py` y
`prj/MCA/sim/tb_mca2_volcado.sv`). Sobre el MISMO estímulo, la réplica tiene que
dar, en cada bloque:

  - los mismos flancos de `trig_i`, muestra por muestra (el disparo por
    pendiente y su latencia);
  - los mismos eventos publicados, en el mismo orden, con la misma amplitud,
    el mismo psd y las once features iguales bit a bit: entre ellas `F_TRAP` y
    `F_FORMA`, la forma del banco que eligió cada ranura;
  - el ciclo de cada publicación, a menos de un corrimiento que es el mismo
    para todos (el registro de salida, que la réplica no cuenta);
  - los mismos contadores y la misma ocupación por ranuras.

Si falta el volcado el test se saltea: `make -C prj/MCA/sim tb_mca2_volcado`.

    python3 -m pytest monte-carlo/test_replica_mca2.py -q
"""

import os
import sys

import numpy as np
import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.dirname(_AQUI))           # software/, por la API

import replica_mca2 as r2                                    # noqa: E402
import volcado_mca2 as vd                                    # noqa: E402

pytestmark = pytest.mark.skipif(
    not (os.path.isfile(vd.ESTIMULO) and os.path.isfile(vd.VOLCADO)),
    reason='falta el volcado: python3 monte-carlo/volcado_mca2.py y '
           '`make -C prj/MCA/sim tb_mca2_volcado`')


@pytest.fixture(scope='module')
def pares():
    est = vd.leer_estimulo()
    vol = vd.leer_volcado()
    assert len(est) == len(vol), f'{len(est)} bloques de estímulo, {len(vol)} volcados'
    return [(c, x, v, r2.medir(x, c)) for (c, x), v in zip(est, vol)]


def _nombre(c):
    return f"n_acc={c['n_acc']} gl={c['gate_long']} L={c['L']}"


def test_los_flancos_de_trig(pares):
    for c, _, v, m in pares:
        np.testing.assert_array_equal(m['trig'], v['trig'], err_msg=_nombre(c))


def test_los_eventos_campo_por_campo(pares):
    for c, _, v, m in pares:
        er, ev = m['eventos'], v['eventos']
        assert er['amp'].size == ev['amp'].size, (
            f"{_nombre(c)}: {er['amp'].size} eventos en la réplica, {ev['amp'].size} en el RTL")
        np.testing.assert_array_equal(er['amp'], ev['amp'], err_msg=f'{_nombre(c)}: amp')
        np.testing.assert_array_equal(er['psd_ok'], ev['psd_ok'], err_msg=f'{_nombre(c)}: psd_ok')
        np.testing.assert_array_equal(er['psd'], ev['psd'], err_msg=f'{_nombre(c)}: psd')
        for k in range(r2.N_FEAT):
            np.testing.assert_array_equal(er['feat'][:, k], ev['feat'][:, k],
                                          err_msg=f'{_nombre(c)}: feature {k}')


def test_el_ciclo_de_cada_publicacion(pares):
    corr = set()
    for c, _, v, m in pares:
        d = v['eventos']['emite'] - m['eventos']['emite']
        assert d.size and np.all(d == d[0]), f'{_nombre(c)}: corrimientos {np.unique(d)}'
        corr.add(int(d[0]))
    assert len(corr) == 1, f'el corrimiento cambia entre bloques: {corr}'


def test_los_contadores(pares):
    for c, _, v, m in pares:
        for k, val in v['cnt'].items():
            assert m['cnt'][k] == val, f'{_nombre(c)}: {k} réplica {m["cnt"][k]}, RTL {val}'


def test_la_ocupacion(pares):
    """t_ocup[0] depende de cuándo arrancó `run` respecto del estímulo, que la
    réplica no ve; los demás casilleros son las ventanas y tienen que coincidir."""
    for c, _, v, m in pares:
        np.testing.assert_array_equal(m['t_ocup'][1:], v['t_ocup'][1:], err_msg=_nombre(c))


def test_el_estimulo_ejercita_el_banco(pares):
    """Si ninguna forma gana, o nada queda marcado, la igualdad no prueba la
    elección; y el disparo con polo-cero tiene que estar entre los comparados."""
    assert any(c['fuente'] == 'pz' for c, *_ in pares)
    con_banco = [(c, v) for c, _, v, _ in pares if c['n_formas'] > 1]
    formas = np.concatenate([v['eventos']['feat'][:, r2.F_FORMA] for _, v in con_banco])
    for f in range(r2.N_FORMAS_RTL):
        assert (formas == f).any(), f'ninguna ranura eligió la forma {f}'
    assert (formas == r2.MARCADO).any(), 'ningún pulso quedó marcado'
    # El recorte de n_formas: se pidieron 7, y hay un bloque que los usa.
    assert any(c['n_formas'] > r2.N_FORMAS_RTL for c, _ in con_banco)
    # Una forma sola con umbrales marca, y da F_TRAP = 0.
    sola = [v for c, _, v, _ in pares if c['n_formas'] == 1 and c['trap_antes']]
    assert sola and (sola[0]['eventos']['feat'][:, r2.F_FORMA] == r2.MARCADO).any()
    # Una forma que no entra en la compuerta gana igual, y da cero sin marcar.
    fuera = [(k, v) for c, _, v, _ in pares
             for k, (_, _, off, lw, *_ ) in enumerate(r2.formas_en_uso(c))
             if off + r2.TLAT + (1 << lw) > c['gate_long']]
    assert fuera, 'ningún bloque tiene una forma que no entra'
    k, v = fuera[0]
    feat = v['eventos']['feat']
    assert (feat[feat[:, r2.F_FORMA] == k, r2.F_TRAP] == 0).all()
    assert (feat[:, r2.F_FORMA] == k).any(), 'la forma que no entra nunca ganó'


def test_la_receta_de_la_api_es_el_banco_del_volcado():
    """Lo que el RTL corrió con el banco es lo que `mca_banco_config` escribe en la
    placa, así que este test también le da la razón a la API."""
    from API.mca import mca_banco_config
    kw = mca_banco_config(vd._MQ_PRE)
    for k, v in kw.items():
        assert vd._BANCO[k] == v, k
    assert set(kw) == set(vd._BANCO)


def test_la_perdida_es_la_del_modelo_de_la_api():
    """`analisis.perdida_ranuras` simula las ranuras sobre los disparos: tiene que
    dar lo mismo que la réplica, que es la que coincide con el RTL."""
    import API.analisis as an
    for c, x in vd.leer_estimulo():
        if c['amp_min'] != 0 or c['amp_max'] != r2.SAT16:
            continue                     # el modelo publica todo: sin ventana de amplitud
        m = r2.medir(x, c)
        n = min(max(int(c['n_acc']), 1), r2.N_ACC_RTL)
        cnt = m['cnt']
        real = (cnt['lost_active'] + cnt['lost_busy']) / max(cnt['cross'], 1)
        modelo, _ = an.perdida_ranuras(m['trig'], n, int(c['gate_long']) + 1)
        assert abs(modelo - real) <= 0.01, f'{_nombre(c)}: modelo {modelo}, réplica {real}'


def test_el_estimulo_ejercita_lo_que_importa(pares):
    """Si el estímulo no tiene pérdidas, solapes y rechazos, la igualdad de
    arriba no prueba el asignador."""
    tot = {k: sum(m['cnt'][k] for *_, m in pares)
           for k in ('lost_active', 'lost_busy', 'pileup', 'rej_amp', 'accepted')}
    for k, n in tot.items():
        assert n > 0, f'ningún bloque ejercita {k}'


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
