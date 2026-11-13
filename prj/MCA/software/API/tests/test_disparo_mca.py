#!/usr/bin/env python3
"""El disparo del MCA2 que arma la API es el que se validó en la placa.

`multitrigger_armar_mca` / `multitrigger_desarmar_mca` (API/multitrigger.py)
tienen que escribir lo mismo, en el mismo orden, que `Pendiente.armar` /
`Pendiente.desarmar` de `API/tests/placa/test_mca2_placa.py`, que es la
secuencia con la que el MCA2 dio 349 PASS en la placa. El orden importa: el
arm (y `we_keep`) del scope va ANTES de habilitar la máscara.

Corre en la PC: los dos lados escriben sobre registros simulados que graban
cada acceso, en un solo registro de (bloque, offset, valor).

    python -m pytest API/tests/test_disparo_mca.py -q
"""

import importlib.util
import os

import pytest

from API.multitrigger import (BIT_PZ_P0, BIT_SLOPE_P0, CAPS_HAS_PZ, CAPS_HAS_SLOPE,
                              MtRegion, R3_FLAGS, pz_ganancia,
                              multitrigger_armar_mca, multitrigger_desarmar_mca,
                              multitrigger_disparo_mca)
from API.mca_remote import FakeMtRegion, FakeOsc

_PLACA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'placa',
                      'test_mca2_placa.py')


def _test_mca2_placa():
    spec = importlib.util.spec_from_file_location('test_mca2_placa', _PLACA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Grabador:
    """Los registros de un bloque, que retienen lo escrito y lo anotan en un
    log compartido. FLAGS del multitrigger sale del 0x000 del scope, como en
    el RTL (we_keep vive en el slot 1)."""

    def __init__(self, nombre, log, regs=None, scope=None):
        self.nombre, self.log = nombre, log
        self.reg = dict(regs or {})
        self.scope = scope

    def w32(self, off, v):
        self.log.append((self.nombre, off, v & 0xFFFFFFFF))
        self.reg[off] = v & 0xFFFFFFFF

    def r32(self, off):
        if self.scope is not None and off == R3_FLAGS:
            arm = self.scope.reg.get(0x000, 0)
            return sum(1 << (4 + c) for c in range(2) if (arm >> (8 * c + 3)) & 1)
        return self.reg.get(off, 0)


def _bloques(mod):
    log = []
    osc = Grabador('osc', log)
    mt = Grabador('mt', log, {0x000: mod.MTRG_MAGIC, 0x004: 1 << 16}, scope=osc)
    return log, osc, mt


def _mtregion(grabador):
    """Un MtRegion de la API sobre el grabador."""
    r = MtRegion(None, -1)
    r.w32 = grabador.w32
    r.r32 = grabador.r32
    return r


@pytest.mark.parametrize('ch', [0, 1])
@pytest.mark.parametrize('params', [dict(L=8, G=4, thr=600, hyst=300),
                                    dict(L=4, G=2, thr=1200, hyst=100)])
def test_armar_es_la_secuencia_validada_en_placa(ch, params):
    mod = _test_mca2_placa()

    log_placa, osc_p, mt_p = _bloques(mod)
    p = mod.Pendiente.__new__(mod.Pendiente)
    p.ch, p.osc, p.mt = ch, osc_p, mt_p
    p.armar(**params)

    log_api, osc_a, mt_a = _bloques(mod)
    multitrigger_armar_mca(osc_a, _mtregion(mt_a), ch=ch, **params)

    assert log_api == log_placa
    # y el orden que importa: arm + we_keep antes que la máscara
    i_arm = log_api.index(('osc', 0x000, 0x0909))
    i_mask = log_api.index(('mt', 0x040 + 4 * ch, BIT_SLOPE_P0 << ch))
    assert i_arm < i_mask


@pytest.mark.parametrize('ch', [0, 1])
def test_desarmar_es_la_secuencia_validada_en_placa(ch):
    mod = _test_mca2_placa()
    log_placa, osc_p, mt_p = _bloques(mod)
    p = mod.Pendiente.__new__(mod.Pendiente)
    p.ch, p.osc, p.mt = ch, osc_p, mt_p
    p.desarmar()

    log_api, osc_a, mt_a = _bloques(mod)
    multitrigger_desarmar_mca(osc_a, _mtregion(mt_a), ch=ch)
    assert log_api == log_placa


def test_sin_we_keep_avisa():
    mod = _test_mca2_placa()
    _, osc, mt = _bloques(mod)
    mt.scope = None                       # FLAGS queda en 0: we_keep no se puso
    with pytest.raises(RuntimeError, match='we_keep'):
        multitrigger_armar_mca(osc, _mtregion(mt))


def test_hyst_mayor_que_thr_no_arma():
    mod = _test_mca2_placa()
    log, osc, mt = _bloques(mod)
    with pytest.raises(ValueError, match='re-arma'):
        multitrigger_armar_mca(osc, _mtregion(mt), thr=100, hyst=200)


def test_el_simulado_arma_y_lo_informa():
    osc = FakeOsc()
    mtr = FakeMtRegion(osc=osc)
    assert not multitrigger_disparo_mca(mtr)['armado']
    multitrigger_armar_mca(osc, mtr, ch=0)
    est = multitrigger_disparo_mca(mtr)
    assert est['armado'] and est['we_keep'] and est['pendiente']['en']
    assert est['shield'] == {'dur': 0, 'dst': 1, 'src': 1}
    multitrigger_desarmar_mca(osc, mtr)
    assert not multitrigger_disparo_mca(mtr)['armado']


# ---------------------------------------------------------------- polo-cero
def _bloques_pz():
    log = []
    osc = Grabador('osc', log)
    mt = Grabador('mt', log, {0x000: 0x4D54_5247, 0x004: CAPS_HAS_PZ | CAPS_HAS_SLOPE},
                  scope=osc)
    return log, osc, mt


def test_pz_ganancia_es_la_del_modelo_validado():
    # pruebas_banco.ganancia(Forma(2, 1), 1.2) con el Mq nominal: 7.0698
    assert abs(pz_ganancia() - 7.0698) < 1e-3
    assert round(50 * pz_ganancia()) == 353 and round(25 * pz_ganancia()) == 177


@pytest.mark.parametrize('ch', [0, 1])
def test_armar_pz_escribe_la_fuente_y_la_mascara(ch):
    log, osc, mt = _bloques_pz()
    multitrigger_armar_mca(osc, _mtregion(mt), ch=ch, fuente='pz')
    cfg = (1 << 31) | (10 << 24) | (1 << 8) | 2
    assert log == [
        ('mt', 0x040 + 4 * ch, 0),                       # mascara en cero
        ('mt', 0x090 + 4 * ch, 0),                       # polo-cero apagado
        ('mt', 0x0B0 + 4 * ch, 353), ('mt', 0x0C0 + 4 * ch, 177),
        ('mt', 0x0A0 + 4 * ch, 3992), ('mt', 0x090 + 4 * ch, cfg),
        ('mt', 0x010, (1 << (8 + ch)) | (1 << ch)),      # shield src = dst = ch
        ('osc', 0x094, 0x0101), ('osc', 0x000, 0x0909),  # arm + we_keep...
        ('mt', 0x040 + 4 * ch, BIT_PZ_P0 << ch),         # ...antes que la mascara
    ]


def test_armar_pz_con_el_m_de_la_placa():
    log, osc, mt = _bloques_pz()
    mq = round(242.8 * 16)
    multitrigger_armar_mca(osc, _mtregion(mt), fuente='pz', mq=mq)
    assert ('mt', 0x0A0, mq) in log
    assert ('mt', 0x0B0, round(50 * pz_ganancia(mq=mq))) in log


@pytest.mark.parametrize('ch', [0, 1])
def test_armar_pz_es_la_secuencia_de_la_placa(ch):
    mod = _test_mca2_placa()
    log_placa, osc_p, mt_p = _bloques_pz()
    p = mod.Pendiente.__new__(mod.Pendiente)
    p.ch, p.osc, p.mt = ch, osc_p, mt_p
    g = pz_ganancia()
    p.armar_pz(thr=round(50 * g), hyst=round(25 * g))
    log_api, osc_a, mt_a = _bloques_pz()
    multitrigger_armar_mca(osc_a, _mtregion(mt_a), ch=ch, fuente='pz')
    assert log_api == log_placa


def test_pz_sin_caps_avisa():
    mod = _test_mca2_placa()
    _, osc, mt = _bloques(mod)                # CAPS solo con la pendiente
    with pytest.raises(RuntimeError, match='polo-cero'):
        multitrigger_armar_mca(osc, _mtregion(mt), fuente='pz')


def test_pz_forma_fuera_de_rango():
    _, osc, mt = _bloques_pz()
    with pytest.raises(ValueError, match='k \\+ m'):
        multitrigger_armar_mca(osc, _mtregion(mt), fuente='pz', k=20, m=12)
    with pytest.raises(ValueError, match='fuente'):
        multitrigger_armar_mca(osc, _mtregion(mt), fuente='nivel')


def test_el_simulado_arma_pz_y_lo_informa():
    osc = FakeOsc()
    mtr = FakeMtRegion(osc=osc)
    multitrigger_armar_mca(osc, mtr, ch=0, fuente='pz')
    est = multitrigger_disparo_mca(mtr)
    assert est['armado'] and est['fuente'] == 'pz' and est['polo_cero']['en']
    assert (est['polo_cero']['k'], est['polo_cero']['m'], est['polo_cero']['thr']) == (2, 1, 353)
    assert not est['pendiente']['en']
    multitrigger_desarmar_mca(osc, mtr)                 # sin decirle cuál
    est = multitrigger_disparo_mca(mtr)
    assert not est['armado'] and not est['polo_cero']['en']
    assert not est['pendiente']['en']


def test_desarmar_apaga_la_fuente_aunque_la_mascara_ya_este_en_cero():
    # Un armar que falló a mitad de camino: la fuente quedó encendida, sin máscara.
    osc = FakeOsc()
    mtr = FakeMtRegion(osc=osc)
    mtr.set_pz(0, 2, 1, 3992, 10, 353, 176)
    assert mtr.get_pz(0)['en'] and not mtr.get_or_mask(0)
    multitrigger_desarmar_mca(osc, mtr)
    assert not mtr.get_pz(0)['en']


def test_el_banco_y_su_disparo_usan_el_mismo_mq():
    from API.mca import mca_get_config, mca_get_n_formas, mca_get_umbr_ok, mca_get_formas_ok
    from API.mca_remote import FakeMCA
    from API.multitrigger import multitrigger_armar_banco
    osc = FakeOsc()
    mtr = FakeMtRegion(osc=osc)
    h = FakeMCA(trap=True)
    multitrigger_armar_banco(h, osc, mtr, mq=3885, sel_1d='trapecio')
    cfg = mca_get_config(h)
    assert cfg['trap_mq'] == mtr.get_pz(0)['mq'] == 3885
    assert multitrigger_disparo_mca(mtr)['fuente'] == 'pz'
    assert mca_get_n_formas(h) == 3 and cfg['n_acc'] == 4 and cfg['gate_long'] == 112
    assert mca_get_umbr_ok(h) and mca_get_formas_ok(h) == [True] * 3
    h.close()


def test_el_banco_usa_las_ranuras_del_bitstream():
    """Sin `n_acc`, todas las que tenga la placa: 3 desde el recorte del 2026-11-09.
    Con 4 fijas, libmca rechazaba la configuración en un bitstream de 3."""
    from API.mca import mca_get_config
    from API.mca_remote import FakeMCA
    from API.multitrigger import multitrigger_armar_banco
    osc = FakeOsc()
    mtr = FakeMtRegion(osc=osc)
    h = FakeMCA(trap=True)
    h.N_ACC = 3
    multitrigger_armar_banco(h, osc, mtr, mq=3885, sel_1d='trapecio')
    assert mca_get_config(h)['n_acc'] == 3
    with pytest.raises(ValueError):
        multitrigger_armar_banco(h, osc, mtr, mq=3885, n_acc=4)
    h.close()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))


def test_multitrigger_y_mtregion_ven_los_mismos_registros():
    """Son dos handles de la misma región. Si las constantes se separan, lo que
    escribe el panel de la GUI (MultiTrigger) no es lo que lee el disparo del MCA
    (MtRegion): así quedó muerto el camino del slot 1, sin ningún error."""
    from API.multitrigger import (MTRG_MAGIC, MultiTrigger, MtRegion, R3_FLAGS, R3_OR_MASK,
                                  R3_SHIELD, R3_SNAPSHOT, R_FLAGS, R_OR_MASK_CH0,
                                  R_SHIELD_CFG, R_TRIG_SNAP)
    assert (R_SHIELD_CFG, R_TRIG_SNAP, R_FLAGS, R_OR_MASK_CH0) == (R3_SHIELD, R3_SNAPSHOT,
                                                                  R3_FLAGS, R3_OR_MASK)
    mem = bytearray(0x1000)
    mem[0:4] = MTRG_MAGIC.to_bytes(4, 'little')
    mt, mr = MultiTrigger(mem, -1), MtRegion(mem, -1)
    mt.set_or_mask(0x12, 0x34)
    assert (mr.get_or_mask(0), mr.get_or_mask(1)) == (0x12, 0x34)
    mr.set_shield(src=0x3, dst=0x3, dur=6)
    assert mt.get_shield()['dur'] == 6 and (mt.get_shield()['dst'], mt.get_shield()['src']) == (3, 3)
    mt.disable_shield()
    assert mr.get_shield() == {'dur': 0, 'dst': 0, 'src': 0}


def test_multitrigger_rechaza_un_bitstream_sin_la_region(monkeypatch, tmp_path):
    """Sin el MAGIC falla al abrir: escribir igual sería perder las máscaras en silencio."""
    import mmap as _mmap
    import os as _os
    from API import _libmca
    from API import multitrigger as M
    # C abre /dev/mem por su cuenta: se le da el mismo backend sobre un fichero.
    ruta = tmp_path / 'vacio.bin'
    ruta.write_bytes(bytes(0x1000))
    bus = _libmca.Bus.archivo(str(ruta), 0, 0x1000)
    with pytest.raises(RuntimeError, match='no es la región del multitrigger'):
        M.MultiTrigger._sobre_bus(bus)
    bus.close()

    # La referencia, que es lo que se abre si libmca no carga, lo abre en Python.
    monkeypatch.setattr(_os, 'open', lambda *a, **k: -7)
    monkeypatch.setattr(_os, 'close', lambda fd: None)

    class Vacio(bytearray):
        def close(self):
            pass
    monkeypatch.setattr(_mmap, 'mmap', lambda *a, **k: Vacio(0x1000))
    with pytest.raises(RuntimeError, match='no es la región del multitrigger'):
        M.MultiTrigger.open(impl='py')
