#!/usr/bin/env python3
"""El generador de pulsos como estímulo del MCA: el RTL contra los dos modelos.

El RTL es gen_pulsos + `mt_top` + `mca_top`, cableados como en el top con
digital_loop[0] = 1, corriendo en QuestaSim con la configuración de
`datos_ref/pulsos_estimulo.txt`; su volcado está en `datos_ref/pulsos_volcado.txt`
(ver `volcado_pulsos.py` y `prj/MCA/sim/tb_pulsos_mca.sv`). El test arma la
traza con el modelo del generador (gen_pulsos_model.py) y le pasa la réplica del
MCA. En cada bloque tienen que coincidir:

  - GEN_CNT con los pulsos del modelo;
  - los flancos de `trig_i`, muestra por muestra. Con el disparo sobre el dato
    (pendiente o polo-cero), los de la réplica; con el disparo del ASG, cada
    pulso LAT_ASG ciclos después, salvo los que llegan antes de que el
    multitrigger se re-arme (REARME ciclos desde el último aceptado);
  - los eventos publicados, campo por campo;
  - el ciclo de cada publicación, a menos de un corrimiento fijo;
  - los contadores y la ocupación por ranuras.

Si falta el volcado el test se saltea: `make -C prj/MCA/sim tb_pulsos_mca`.

    python3 -m pytest monte-carlo/test_pulsos_mca.py -q
"""

import os
import sys

import numpy as np
import pytest

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

import replica_mca2 as r2                                    # noqa: E402
import volcado_pulsos as vp                                  # noqa: E402

# La latencia del ASG del TB y el re-armado del multitrigger: ver volcado_pulsos.py.
# Por pendiente el re-armado no se nota (el Schmitt no dispara tan seguido).
LAT_ASG = vp.LAT_ASG
REARME = vp.REARME
disparos_asg = vp.disparos_asg

pytestmark = pytest.mark.skipif(
    not (os.path.isfile(vp.ESTIMULO) and os.path.isfile(vp.VOLCADO)),
    reason='falta el volcado: python3 monte-carlo/volcado_pulsos.py y '
           '`make -C prj/MCA/sim tb_pulsos_mca`')


@pytest.fixture(scope='module')
def bloques():
    est = vp.leer_estimulo()
    vol = vp.leer_volcado()
    assert len(est) == len(vol), f'{len(est)} bloques de estímulo, {len(vol)} volcados'
    out = []
    for (c, gkw, tabla, asg, n), v in zip(est, vol):
        x, t = vp.entrada_replica(gkw, tabla, n)
        trig = disparos_asg(t['trig']) + LAT_ASG + vp.PAD if asg else None
        m = r2.medir(x, c, trig=trig)
        out.append(dict(c=c, asg=asg, t=t, v=v, m=m))
    return out


def _nombre(b):
    return f"n_acc={b['c']['n_acc']} {'ASG' if b['asg'] else b['c']['fuente']}"


def test_gen_cnt_es_el_modelo(bloques):
    for b in bloques:
        assert b['v']['gen_cnt'] == b['t']['trig'].size, _nombre(b)


def test_los_flancos_de_trig(bloques):
    for b in bloques:
        np.testing.assert_array_equal(b['m']['trig'] - vp.PAD, b['v']['trig'],
                                      err_msg=_nombre(b))


def test_el_asg_dispara_en_cada_pulso(bloques):
    """El modelo del camino del ASG (la latencia y el re-armado) es exacto, y el
    estímulo lo ejercita: hay pulsos a 2 ciclos (se pierden) y a 3 (no)."""
    hay_2 = hay_3 = False
    for b in [b for b in bloques if b['asg']]:
        p = b['t']['trig']
        np.testing.assert_array_equal(b['v']['trig'], disparos_asg(p) + LAT_ASG,
                                      err_msg=_nombre(b))
        d = np.diff(p)
        hay_2 |= bool((d == 2).any())
        hay_3 |= bool((d == 3).any())
    assert hay_2 and hay_3, 'ningún bloque ASG tiene pulsos a 2 y a 3 ciclos'


def test_los_eventos_campo_por_campo(bloques):
    for b in bloques:
        er, ev = b['m']['eventos'], b['v']['eventos']
        assert er['amp'].size == ev['amp'].size, (
            f"{_nombre(b)}: {er['amp'].size} eventos en la réplica, {ev['amp'].size} en el RTL")
        np.testing.assert_array_equal(er['amp'], ev['amp'], err_msg=f'{_nombre(b)}: amp')
        np.testing.assert_array_equal(er['psd_ok'], ev['psd_ok'], err_msg=f'{_nombre(b)}: psd_ok')
        np.testing.assert_array_equal(er['psd'], ev['psd'], err_msg=f'{_nombre(b)}: psd')
        for k in range(r2.N_FEAT):
            np.testing.assert_array_equal(er['feat'][:, k], ev['feat'][:, k],
                                          err_msg=f'{_nombre(b)}: feature {k}')


def test_el_ciclo_de_cada_publicacion(bloques):
    corr = set()
    for b in bloques:
        d = b['v']['eventos']['emite'] - (b['m']['eventos']['emite'] - vp.PAD)
        assert d.size and np.all(d == d[0]), f'{_nombre(b)}: corrimientos {np.unique(d)}'
        corr.add(int(d[0]))
    assert len(corr) == 1, f'el corrimiento cambia entre bloques: {corr}'


def test_los_contadores(bloques):
    for b in bloques:
        for k, val in b['v']['cnt'].items():
            assert b['m']['cnt'][k] == val, f'{_nombre(b)}: {k} réplica {b["m"]["cnt"][k]}, RTL {val}'


def test_la_ocupacion(bloques):
    """t_ocup[0] depende de cuándo arrancó `run`; los demás son las ventanas."""
    for b in bloques:
        np.testing.assert_array_equal(b['m']['t_ocup'][1:], b['v']['t_ocup'][1:],
                                      err_msg=_nombre(b))


def test_cada_pulso_es_un_evento_con_su_amplitud(bloques):
    """Con el ASG y los pulsos separados (el barrido de amplitud), cada pulso abre
    una ventana y se publica, en orden: el MCA mide lo que el generador puso."""
    b = [b for b in bloques if b['asg'] and b['c']['n_acc'] == 2][0]
    ev = b['v']['eventos']
    assert ev['amp'].size == b['t']['trig'].size
    a_gen = b['t']['amp']
    # la amplitud medida crece con la del generador, pulso por pulso
    assert np.all(np.diff(ev['amp'][np.argsort(a_gen)]) >= 0)


def test_el_estimulo_ejercita_lo_que_importa(bloques):
    tot = {k: sum(b['m']['cnt'][k] for b in bloques)
           for k in ('lost_active', 'lost_busy', 'pileup', 'accepted')}
    for k, n in tot.items():
        assert n > 0, f'ningún bloque ejercita {k}'
    assert any(b['asg'] for b in bloques) and any(not b['asg'] for b in bloques)
    assert any(b['c']['fuente'] == 'pz' and not b['asg'] for b in bloques)
    assert any(b['c']['n_formas'] == 3 for b in bloques), 'falta el banco del recorte'


def test_la_referencia_de_la_placa_es_la_replica():
    """`datos_ref/pulsos_placa_ref.json`, contra lo que mide el test de placa, es la
    réplica con la latencia del ASG del top. Si cambia el modelo o el estímulo, se
    regenera: `python3 monte-carlo/volcado_pulsos.py --placa`."""
    import json
    assert vp.LAT_ASG_TOP == LAT_ASG - 1
    assert os.path.isfile(vp.REF_PLACA), 'falta: python3 monte-carlo/volcado_pulsos.py --placa'
    with open(vp.REF_PLACA) as f:
        guardada = json.load(f)
    assert guardada == json.loads(json.dumps(vp.referencia_placa()))


def test_la_referencia_de_la_placa_coincide_con_el_rtl_salvo_la_latencia(bloques):
    """Por pendiente y polo-cero la referencia es el volcado del RTL; con el ASG
    sólo cambia lo que depende de la latencia (el instante de cada ventana)."""
    import json
    with open(vp.REF_PLACA) as f:
        ref = json.load(f)['bloques']
    for r, b in zip(ref, bloques):
        assert r['gen_cnt'] == b['v']['gen_cnt'] and r['n_acc'] == b['c']['n_acc']
        k = b['v']['cnt']
        assert r['cnt']['dropped'] == k['lost_busy'] and r['cnt']['win'] == k['windows']
        pico = np.unique(vp.canal_1d(b['v']['eventos']['feat'][:, r2.F_PEAK], 0),
                         return_counts=True)
        assert r['espectros']['F_PEAK_z0'] == {str(int(a)): int(n) for a, n in zip(*pico)}
        if not b['asg']:
            assert r['t_ocup'] == [int(v) for v in b['v']['t_ocup'][1:]]


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))
