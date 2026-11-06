#!/usr/bin/env python3
"""(P,R) Prueba en placa del MCA con ranuras ("MCA2"). Corre EN LA PITAYA.

Es AUTÓNOMA a propósito: `API/mca.py` y `libmca` todavía hablan el mapa
"MCA1" (umbral, histéresis, re-armado, modo de publicación), así que esta
prueba lleva su propia tabla de registros —la de docs/mca/register_map_mca.md—
y escribe el multitrigger a mano, igual que `sim/tb_mca_mt_latencia.sv`. Del
resto del árbol usa sólo el driver del Rigol (`campanas/estimulo.py`).

    python3 API/tests/placa/test_mca2_placa.py                  # todo
    python3 API/tests/placa/test_mca2_placa.py --etapas regs    # sin generador
    python3 API/tests/placa/test_mca2_placa.py --etapas poisson --tasas 30e3 1e5

Las etapas:

  regs       sin señal: identificación, registros, reservados en cero,
             barrido del bus, borrado y las invariantes de los relojes.
  periodico  tren del Rigol a 2 kHz: cuenta de disparos sin pérdidas,
             espectro con 1 ranura contra 4 (tienen que coincidir), la ley de
             Little sobre t_ocup (cada ventana ocupa gate_larga + 19 ciclos),
             F_TRISE contra cfg_pre_dly (corre exactamente lo que se retarda) y
             F_DTPREV contra el período del generador.
  par        pares de pulsos a 1.6 us: con 1 ranura el segundo se pierde
             (lost_active) y con 2 o más se miden los dos; F_DTPREV, F_DTNEXT y
             F_SOLAPE tienen que marcar exactamente el par.
  poisson    arribos de Poisson a varias tasas y 1..4 ranuras: la pérdida
             medida contra una simulación M/D/N/N sobre EL MISMO patrón de
             arribos (se reconstruye de la semilla del generador), y contra
             Erlang B como referencia.
  trapecio   (bitstream con mca_trap, CAPS bit 2) pulsos de preamplificador
             (subida rápida, cola de 2 us) y polo-cero exacto: F_TRAP de un
             pulso que monta sobre la cola de otro a dt >= k+m coincide con el
             del pulso aislado, y F_PEAK no; a dt < k+m se contamina.
  banco      (bitstream con mca_trap) cada forma del banco de trapecios
             (docs/mca/pruebas_banco_trapecios.md) con el trapecio unico:
             barre el offset de la ventana, mide la linealidad de un pulso
             chico contra 64/48 y el error de A y de B en pares a varios dt
             alrededor de sus umbrales. Usa el M de la etapa trapecio si corre
             antes, o --trap-mq.
  disparo    cuantos disparos da el multitrigger para dos pulsos a dt, y para
             un pulso chico sobre la cola de uno grande (la simulacion del RTL
             da ~20 muestras y ~150-190).

Todo lo medido queda en un JSON (--out).
"""

import argparse
import json
import math
import mmap
import os
import struct
import sys
import time

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

FS = 125e6

# =============================================================================
# El mapa "MCA2" (docs/mca/register_map_mca.md)
# =============================================================================
MCA_PHYS, MCA_SIZE = 0x4070_0000, 0x30000
MAGIC_MCA2 = 0x4D434132

R_MAGIC, R_CAPS, R_WIDTHS = 0x000, 0x004, 0x008
R_CTRL, R_STATUS = 0x00C, 0x010
R_BASELINE, R_BL_CTRL, R_BASELINE_NOW = 0x01C, 0x020, 0x024
R_AMP_MIN, R_AMP_MAX, R_AMP_SRC = 0x030, 0x034, 0x038
R_H_SHIFT, R_H2_SHIFT, R_DEC, R_GATE_LEN = 0x03C, 0x040, 0x044, 0x04C
R_HIST_SEL, R_ZOOM_1D, R_ZOOM_2DX, R_ZOOM_2DY = 0x090, 0x094, 0x0B8, 0x0BC
R_DISCR_CTRL, R_DISCR_MIN, R_DISCR_MAX = 0x098, 0x09C, 0x0A0
R_HIST_CTRL, R_HIST_STATUS = 0x0A4, 0x0A8
R_N_ACC_CFG, R_PRE_DLY, R_N_ACC = 0x120, 0x124, 0x11C
R_TRAP_KM, R_TRAP_MQ, R_TRAP_MED = 0x128, 0x12C, 0x130
# El banco de trapecios: {umbr_ok[31], N_FORMAS[10:8], n_formas[2:0]} y un
# bloque por forma desde 0x180: +0 {m, k}, +4 {ok, sh, lw, off}, +8 {despues, antes}
R_N_FORMAS, R_FORMA = 0x134, 0x180
CAP_TRAP = 1 << 2
R_PUB_STATE = 0x10C
R_T_OCUP = 0x140                    # + 8*j, j = 0..N_ACC
APERTURE_H = 0x10000

# Contadores de 32 b, por nombre
CONTADORES = {
    'total': 0x050, 'accepted': 0x054, 'rej_amp': 0x058, 'rej_psd': 0x05C,
    'pileup': 0x060, 'dropped': 0x064, 'rej_discr': 0x0AC, 'full_supp': 0x0B0,
    'open': 0x0B4, 'dead_periods': 0x0E0, 'dead_len_max': 0x0E4,
    'dead_ext': 0x0E8, 'cross': 0x0EC, 'lost_active': 0x0F4,
    'lost_veto': 0x0F8, 'win': 0x110, 'trig': 0x118,
}
# Relojes de 64 b: leer la palabra baja congela la alta
RELOJES = {
    'realtime': 0x068, 'livetime': 0x070, 'deadtime': 0x078,
    'vetotime': 0x0C0, 't_win': 0x0C8, 't_div': 0x0D0, 't_clear': 0x0FC,
}
# Los que dejaron libres el Schmitt, la histéresis, el re-armado y la FIFO
RESERVADOS = (0x014, 0x018, 0x028, 0x02C, 0x048, 0x0D8, 0x0DC, 0x0F0,
              0x104, 0x108, 0x114)

F_PEAK, F_INT, F_PSD, F_INVW, F_LEN, F_TRISE = 0, 1, 2, 3, 4, 5
F_DTPREV, F_DTNEXT, F_SOLAPE, F_TRAP = 6, 7, 8, 9
F_FORMA = 10                        # la forma del banco, 0xFFFF = marcado
SOL_PERDIDO, SOL_ADENTRO = 1 << 5, 1 << 4

# =============================================================================
# El multitrigger: slot 1 (we_keep, compartido con el scope) y slot 3 (mt_cfg)
# =============================================================================
OSC_PHYS, MTRG_PHYS = 0x4010_0000, 0x4030_0000
MTRG_MAGIC = 0x4D54_5247            # "MTRG"
M_SHIELD, M_FLAGS, M_OR_MASK = 0x010, 0x01C, 0x040
M_SLOPE_CFG, M_SLOPE_THR, M_SLOPE_HYST = 0x060, 0x070, 0x080
BIT_SLOPE_P0 = 1 << 17
# El disparo con polo-cero (mt_pz_trig), bits 25..28 de la máscara
M_PZ_CFG, M_PZ_MQ, M_PZ_THR, M_PZ_HYST = 0x090, 0x0A0, 0x0B0, 0x0C0
BIT_PZ_P0 = 1 << 25

_U32 = struct.Struct('<I')


class Mem:
    """Un mapeo de /dev/mem. Escritura por slice y lectura de a una palabra:
    cualquier otra cosa termina en accesos anchos o en ráfaga, que el esclavo
    AXI rechaza y que en esta placa REINICIAN el sistema (ver
    API/ref_py/mca.py, `_read_words`)."""

    def __init__(self, phys, size):
        self._fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        self._m = mmap.mmap(self._fd, size, mmap.MAP_SHARED,
                            mmap.PROT_READ | mmap.PROT_WRITE, offset=phys)

    def close(self):
        self._m.close()
        os.close(self._fd)

    def w32(self, off, v):
        self._m[off:off + 4] = _U32.pack(v & 0xFFFFFFFF)

    def r32(self, off):
        return _U32.unpack_from(self._m, off)[0]

    def words(self, off, n):
        u, m = _U32.unpack_from, self._m
        return np.array([u(m, off + 4 * i)[0] for i in range(n)], dtype=np.uint32)


class MCA2:
    def __init__(self):
        self.mem = Mem(MCA_PHYS, MCA_SIZE)
        magic = self.mem.r32(R_MAGIC)
        if magic != MAGIC_MCA2:
            self.mem.close()
            raise RuntimeError(f'magic {magic:#010x}: no es el bitstream "MCA2"')
        w = self.mem.r32(R_WIDTHS)
        self.h_aw, self.h2_aw, self.psd_aw = w & 0xFF, (w >> 8) & 0xFF, (w >> 16) & 0xFF
        self.n_acc_max = self.mem.r32(R_N_ACC)
        self.chan = 0

    def close(self):
        self.mem.close()

    r32 = property(lambda s: s.mem.r32)
    w32 = property(lambda s: s.mem.w32)

    def r64(self, lo):
        a = self.mem.r32(lo)
        return (self.mem.r32(lo + 4) << 32) | a

    def stop(self):
        self.w32(R_CTRL, self.chan << 8)

    def start(self):
        self.w32(R_CTRL, (self.chan << 8) | 1)

    def clear(self, timeout_s=1.0):
        self.w32(R_CTRL, (self.chan << 8) | 2)
        t0 = time.time()
        while self.r32(R_STATUS) & 1:
            if time.time() - t0 > timeout_s:
                raise RuntimeError('clear_busy no bajó')
            time.sleep(0.001)

    base_fija = None             # --base: sin seguidor, con esta base en las etapas
    bl_holdoff = 0               # --bl-holdoff: del seguidor, en ciclos despues de cada ventana

    def configurar(self, gate_long=384, gate_short=32, n_acc=1, pre_dly=11,
                   sel_1d=F_PEAK, z_1d=0, bl_k=12, amp_src=0, q_shift=0):
        self.stop()
        if self.base_fija is None:
            self.w32(R_BL_CTRL, (self.bl_holdoff << 16) | (bl_k << 4) | 1)
        else:
            self.w32(R_BL_CTRL, bl_k << 4)
            self.w32(R_BASELINE, self.base_fija & 0x3FFF)
        self.w32(R_AMP_MIN, 0)
        self.w32(R_AMP_MAX, 0xFFFF)
        # amp_src mueve sel_1d/sel_2dx: va ANTES que cfg_hist_sel
        self.w32(R_AMP_SRC, ((q_shift & 0x1F) << 8) | (amp_src & 1))
        self.w32(R_HIST_SEL, (F_PSD << 8) | (F_PEAK << 4) | (sel_1d & 0xF))
        self.w32(R_ZOOM_1D, z_1d & 0xF)
        self.w32(R_ZOOM_2DX, 0)
        self.w32(R_ZOOM_2DY, 0)
        self.w32(R_DEC, 1)
        self.w32(R_GATE_LEN, (gate_long << 16) | gate_short)
        self.w32(R_DISCR_CTRL, 0)
        self.w32(R_HIST_CTRL, 1)
        self.w32(R_N_ACC_CFG, n_acc)
        self.w32(R_PRE_DLY, pre_dly)
        # El banco en reset (una forma, sin umbrales): si no, lo que dejo la etapa
        # banco_rtl sigue eligiendo formas, y con los umbrales marca pulsos.
        self.w32(R_N_FORMAS, 1)
        self.w32(R_FORMA + 8, 0)

    def sel_1d(self, f, z):
        self.w32(R_HIST_SEL, (self.r32(R_HIST_SEL) & ~0xF) | f)
        self.w32(R_ZOOM_1D, z)

    def leer(self):
        d = {k: self.r32(o) for k, o in CONTADORES.items()}
        d.update({k: self.r64(o) for k, o in RELOJES.items()})
        d['t_ocup'] = [self.r64(R_T_OCUP + 8 * j) for j in range(self.n_acc_max + 1)]
        d['n_acc'] = self.r32(R_N_ACC_CFG)
        d['pub_state'] = self.r32(R_PUB_STATE)
        return d

    def espectro(self):
        return self.mem.words(APERTURE_H, 1 << self.h_aw)

    def medir(self, segundos, histograma=True):
        """clear, run, stop y foto coherente. Espera a que se vacíen las
        ranuras: con run = 0 las abiertas igual cierran y publican."""
        self.stop()
        self.clear()
        self.start()
        time.sleep(segundos)
        self.stop()
        time.sleep(0.01)
        d = self.leer()
        if histograma:
            d['_h'] = self.espectro()
        return d


class Pendiente:
    """El disparo por pendiente del multitrigger en MODO CONTINUO: we_keep para
    que la máscara sobreviva al disparo, y el shield con fuente y destino en el
    canal (dur = 0) para que lo re-arme solo. Sin DST_MCA: no veta al MCA."""

    def __init__(self, ch=0):
        self.ch = ch
        self.osc = Mem(OSC_PHYS, 0x1000)
        self.mt = Mem(MTRG_PHYS, 0x1000)
        if self.mt.r32(0x000) != MTRG_MAGIC:
            raise RuntimeError(f'slot 3 sin multitrigger: {self.mt.r32(0):#010x}')
        if not (self.mt.r32(0x004) >> 16) & 1:
            raise RuntimeError('el multitrigger no tiene disparo por pendiente')

    def armar(self, L=8, G=4, thr=600, hyst=300):
        c = self.ch
        self.mt.w32(M_OR_MASK + 4 * c, 0)
        self.mt.w32(M_SLOPE_CFG + 4 * c, 0)
        self.mt.w32(M_SLOPE_THR + 4 * c, thr)
        self.mt.w32(M_SLOPE_HYST + 4 * c, hyst)
        self.mt.w32(M_SLOPE_CFG + 4 * c, (1 << 31) | (G << 8) | L)
        self.mt.w32(M_SHIELD, ((1 << c) << 8) | (1 << c))
        self.osc.w32(0x094, 0x0101)                 # limpia adc_trg_dis
        # arm + we_keep en los dos canales, y DESPUÉS la máscara
        # (multitrigger_arm, docs/osc/orden_arm_trigger_captura.md)
        self.osc.w32(0x000, 0x0909)
        self.mt.w32(M_OR_MASK + 4 * c, BIT_SLOPE_P0 << c)
        flags = self.mt.r32(M_FLAGS)
        if not (flags >> (4 + c)) & 1:
            raise RuntimeError(f'we_keep no quedó puesto: flags {flags:#x}')

    def desarmar(self):
        c = self.ch
        self.mt.w32(M_OR_MASK + 4 * c, 0)
        self.mt.w32(M_SLOPE_CFG + 4 * c, 0)
        self.mt.w32(M_SHIELD, 0)
        self.osc.w32(0x000, 0)
        self.osc.w32(0x094, 0x0101)
        self.osc.w32(0x000, 0x0202)

    def tiene_pz(self):
        return bool((self.mt.r32(0x004) >> 17) & 1)

    def armar_pz(self, k=2, m=1, mq=3992, sh=10, thr=353, hyst=177):
        """El disparo con polo-cero en modo continuo: la misma secuencia que
        multitrigger_armar_mca(fuente='pz') (test_disparo_mca.py lo exige)."""
        if not self.tiene_pz():
            raise RuntimeError('el multitrigger no tiene disparo con polo-cero (CAPS[17])')
        c = self.ch
        self.mt.w32(M_OR_MASK + 4 * c, 0)
        self.mt.w32(M_PZ_CFG + 4 * c, 0)
        self.mt.w32(M_PZ_THR + 4 * c, thr)
        self.mt.w32(M_PZ_HYST + 4 * c, hyst)
        self.mt.w32(M_PZ_MQ + 4 * c, mq)
        self.mt.w32(M_PZ_CFG + 4 * c, (1 << 31) | (sh << 24) | (m << 8) | k)
        self.mt.w32(M_SHIELD, ((1 << c) << 8) | (1 << c))
        self.osc.w32(0x094, 0x0101)
        self.osc.w32(0x000, 0x0909)
        self.mt.w32(M_OR_MASK + 4 * c, BIT_PZ_P0 << c)
        flags = self.mt.r32(M_FLAGS)
        if not (flags >> (4 + c)) & 1:
            raise RuntimeError(f'we_keep no quedó puesto: flags {flags:#x}')

    def desarmar_pz(self):
        if self.tiene_pz():
            self.mt.w32(M_PZ_CFG + 4 * self.ch, 0)

    def close(self):
        self.osc.close()
        self.mt.close()


# =============================================================================
# Resultados
# =============================================================================
_res = {'pass': 0, 'fail': 0, 'checks': []}


def check(nombre, ok, detalle=''):
    ok = bool(ok)
    _res['pass' if ok else 'fail'] += 1
    _res['checks'].append({'nombre': nombre, 'ok': ok, 'detalle': str(detalle)})
    print(f'  {"PASS" if ok else "FAIL"}  {nombre}' + (f'   [{detalle}]' if detalle else ''))


def stats_h(h, lo=1, hi=None):
    """Media y sigma de un histograma, sin los canales de desborde."""
    hi = len(h) - 1 if hi is None else hi
    c = np.arange(len(h))[lo:hi]
    w = h[lo:hi].astype(float)
    n = w.sum()
    if n == 0:
        return 0, 0.0, 0.0
    mu = (c * w).sum() / n
    return int(n), float(mu), float(math.sqrt(((c - mu) ** 2 * w).sum() / n))


def invariantes(d, n_acc, etq):
    """Las identidades del teselado y de la atribución, sobre una foto."""
    to = d['t_ocup']
    check(f'{etq}: realtime = veto + t_win + t_div + livetime',
          d['realtime'] == d['vetotime'] + d['t_win'] + d['t_div'] + d['livetime'],
          f"{d['realtime']} vs {d['vetotime'] + d['t_win'] + d['t_div'] + d['livetime']}")
    check(f'{etq}: suma de t_ocup = realtime - vetotime',
          sum(to) == d['realtime'] - d['vetotime'], f'{sum(to)}')
    check(f'{etq}: t_win + t_div = t_ocup[n_acc]',
          d['t_win'] + d['t_div'] == to[n_acc], f"{d['t_win'] + d['t_div']} vs {to[n_acc]}")
    check(f'{etq}: livetime = suma de t_ocup[j < n_acc]',
          d['livetime'] == sum(to[:n_acc]), f"{d['livetime']} vs {sum(to[:n_acc])}")
    check(f'{etq}: deadtime = suma de t_ocup[j >= 1]',
          d['deadtime'] == sum(to[1:]), f"{d['deadtime']} vs {sum(to[1:])}")
    check(f'{etq}: cross = open + lost_active + dropped + lost_veto',
          d['cross'] == d['open'] + d['lost_active'] + d['dropped'] + d['lost_veto'],
          f"{d['cross']} vs {d['open']}+{d['lost_active']}+{d['dropped']}+{d['lost_veto']}")
    check(f'{etq}: total = open (las ranuras se vaciaron)', d['total'] == d['open'],
          f"{d['total']} vs {d['open']}")
    check(f'{etq}: ninguna ranura por encima de n_acc', all(x == 0 for x in to[n_acc + 1:]),
          str(to))


def sin_h(d):
    return {k: v for k, v in d.items() if not k.startswith('_')}


# =============================================================================
# Etapa regs
# =============================================================================
ESCRIBIBLES = [
    ('cfg_baseline', R_BASELINE, 0x00003FFF),
    ('cfg_bl_ctrl', R_BL_CTRL, 0xFFFF00F1),
    ('cfg_amp_min', R_AMP_MIN, 0x0000FFFF),
    ('cfg_amp_max', R_AMP_MAX, 0x0000FFFF),
    ('cfg_amp_src', R_AMP_SRC, 0x00001F01),
    ('cfg_dec', R_DEC, 0x0000FFFF),
    ('cfg_gate_len', R_GATE_LEN, 0xFFFFFFFF),
    ('cfg_hist_sel', R_HIST_SEL, 0x00000FFF),
    ('cfg_zoom_1d', R_ZOOM_1D, 0x0000FF0F),
    ('cfg_zoom_2dx', R_ZOOM_2DX, 0x0000FF0F),
    ('cfg_zoom_2dy', R_ZOOM_2DY, 0x0000FF0F),
    ('cfg_discr_ctrl', R_DISCR_CTRL, 0x000000F3),
    ('cfg_discr_min', R_DISCR_MIN, 0x0000FFFF),
    ('cfg_discr_max', R_DISCR_MAX, 0x0000FFFF),
    ('cfg_hist_ctrl', R_HIST_CTRL, 0x00000001),
    ('cfg_n_acc', R_N_ACC_CFG, 0x00000007),
    ('cfg_pre_dly', R_PRE_DLY, 0x0000007F),
]


def etapa_regs(m, mt, recien_cargado):
    mt.desarmar()                       # sin disparos, esté como esté el Rigol
    print('\n[regs] identificación')
    check('magic "MCA2"', m.r32(R_MAGIC) == MAGIC_MCA2, f'{m.r32(R_MAGIC):#010x}')
    check('caps: 1D y 2D', m.r32(R_CAPS) & 3 == 3, f'{m.r32(R_CAPS):#x}')
    check('anchos 13 / 7 / 6', (m.h_aw, m.h2_aw, m.psd_aw) == (13, 7, 6),
          f'{m.h_aw}/{m.h2_aw}/{m.psd_aw}')
    check('N_ACC = 4', m.n_acc_max == 4, m.n_acc_max)
    if recien_cargado:
        check('reset: cfg_n_acc = 1', m.r32(R_N_ACC_CFG) == 1, m.r32(R_N_ACC_CFG))
        check('reset: cfg_pre_dly = 11', m.r32(R_PRE_DLY) == 11, m.r32(R_PRE_DLY))
        check('reset: gate 384/32', m.r32(R_GATE_LEN) == (384 << 16 | 32),
              f'{m.r32(R_GATE_LEN):#010x}')

    print('\n[regs] escritura y relectura')
    m.stop()
    for nombre, off, mask in ESCRIBIBLES:
        previo = m.r32(off)
        ok, det = True, ''
        for patron in (0xA5A5A5A5, 0x5A5A5A5A):
            m.w32(off, patron & mask)
            leido = m.r32(off) & mask
            if leido != patron & mask:
                ok, det = False, f'escribí {patron & mask:#x}, leí {leido:#x}'
                break
        m.w32(off, previo)
        check(f'{nombre} ({off:#05x}) retiene', ok, det)

    print('\n[regs] reservados: se escriben sin efecto y se leen en cero')
    malos = []
    for off in RESERVADOS:
        m.w32(off, 0xFFFFFFFF)
        if m.r32(off) != 0:
            malos.append(f'{off:#05x}={m.r32(off):#x}')
    check(f'{len(RESERVADOS)} offsets reservados en cero', not malos, ', '.join(malos))
    altos = [m.r32(R_T_OCUP + 8 * j + h) for j in range(m.n_acc_max + 1, 8) for h in (0, 4)]
    check('t_ocup[j > N_ACC] lee cero', not any(altos), str(altos))

    print('\n[regs] barrido del bus (ninguna dirección puede colgarlo)')
    t0 = time.time()
    n = 0
    for off in range(0, 0x200, 4):
        m.r32(off); n += 1
    for base in (APERTURE_H, 0x20000):
        for off in range(base, base + 0x400, 4):
            m.r32(off); n += 1
    for off in (0x0FFFC, 0x1FFFC, 0x2FFFC, 0x00300, 0x00800, 0x0F000):
        m.r32(off); n += 1
    check(f'{n} lecturas sin colgarse', True, f'{1e6 * (time.time() - t0) / n:.1f} us/acceso')

    print('\n[regs] borrado')
    m.configurar(n_acc=4)
    m.clear()
    h = m.espectro()
    check('espectro en cero tras el borrado', not h.any(), f'{int((h != 0).sum())} canales')
    d = m.leer()
    check('contadores en cero', all(d[k] == 0 for k in CONTADORES if k != 'trig'),
          {k: d[k] for k in CONTADORES if d[k]})
    check('relojes y t_ocup en cero',
          all(d[k] == 0 for k in RELOJES if k != 't_clear') and not any(d['t_ocup']),
          {k: d[k] for k in RELOJES if d[k]})

    print('\n[regs] relojes sin disparos (máscara del multitrigger apagada)')
    d = m.medir(1.0, histograma=False)
    rt = d['realtime'] / FS
    check('realtime ~ 1 s', 0.95 < rt < 1.2, f'{rt:.4f} s')
    check('sin disparos: cross = 0', d['cross'] == 0, d['cross'])
    check('t_ocup[0] = realtime', d['t_ocup'][0] == d['realtime'], d['t_ocup'])
    invariantes(d, 4, 'reposo')
    t1 = m.leer()['realtime']
    time.sleep(0.2)
    check('con run = 0 el realtime no avanza', m.leer()['realtime'] == t1)
    return {'reposo': sin_h(d)}


# =============================================================================
# Etapas con generador
# =============================================================================
def abrir_generador():
    import API.rigol_dg4162 as rg
    gen = rg.RigolDG4162.usb()
    gen.reset()
    return gen


def forma_pulso(t_s, fwhm_s=2e-6):
    """La forma de `pulse_train_wave`: (1 - e^-t/tr) e^-t/tau con la escala que
    da el FWHM pedido (2.361 us para 2 us), normalizada al pico."""
    s = 2.361e-6 * fwhm_s / 2e-6
    tr, tau = 0.25 * s, 0.6 * s
    t = np.maximum(t_s, 0.0)
    p = (1 - np.exp(-t / tr)) * np.exp(-t / tau)
    tp = tr * math.log(1 + tau / tr)
    return np.where(t_s > 0, p / ((1 - math.exp(-tp / tr)) * math.exp(-tp / tau)), 0.0)


def etapa_periodico(m, mt, gen, args):
    from campanas.estimulo import encender
    print(f'\n[periodico] tren de {args.tasa_per:g} Hz, {args.amp:g} Vpp '
          f'(pulso de ~{args.amp / 2 * 8192:.0f} cuentas)')
    freq, info = encender(gen, args.gen_ch, args.tasa_per, args.amp)
    periodo = FS / args.tasa_per
    m.configurar(n_acc=1, gate_long=args.gate, sel_1d=F_PEAK)
    mt.armar(thr=args.thr, hyst=args.hyst)
    m.medir(0.5, histograma=False)                 # la base converge
    base = m.r32(R_BASELINE_NOW)
    base = base - (1 << 32) if base & 0x80000000 else base
    print(f'        línea de base seguida: {base} cuentas')
    out = {'baseline_now': base, 'freq_gen': freq}
    tau = args.gate + 19

    espectros = {}
    for n in (1, 4):
        m.w32(R_N_ACC_CFG, n)
        d = m.medir(args.segundos)
        rt = d['realtime'] / FS
        tasa = d['cross'] / rt
        etq = f'periódico N={n}'
        check(f'{etq}: tasa de disparos = {args.tasa_per:g} Hz (±1 %)',
              abs(tasa / args.tasa_per - 1) < 0.01, f'{tasa:.1f} Hz')
        check(f'{etq}: ninguna pérdida',
              d['lost_active'] == 0 and d['dropped'] == 0 and d['open'] == d['cross'],
              f"open {d['open']} cross {d['cross']} la {d['lost_active']} dr {d['dropped']}")
        check(f'{etq}: ningún solape marcado', d['pileup'] == 0, d['pileup'])
        invariantes(d, n, etq)
        # Little: cada ventana ocupa su ranura gate+1 midiendo y 18 publicando
        ocup = sum(j * x for j, x in enumerate(d['t_ocup']))
        check(f'{etq}: ocupación por ventana = gate_larga + 19 = {tau}',
              abs(ocup / max(d['open'], 1) - tau) <= 1.0, f'{ocup / max(d["open"], 1):.2f}')
        if n == 1:
            check(f'{etq}: cada período muerto dura {tau}', d['dead_len_max'] in (tau - 1, tau, tau + 1),
                  d['dead_len_max'])
        else:
            check(f'{etq}: nunca dos ranuras ocupadas', not any(d['t_ocup'][2:]), d['t_ocup'])
        h = d.pop('_h')
        espectros[n] = h
        nn, mu, sg = stats_h(h)
        # F_PEAK va alineado a 16 b (peak << 2) y el eje es de 13: canal = cuentas / 2
        print(f'        espectro: {nn} eventos, pico en el canal {mu:.1f} ± {sg:.2f} '
              f'(~{2 * mu:.0f} cuentas)')
        out[f'N{n}'] = dict(sin_h(d), pico=mu, sigma=sg, n_h=nn)
    (_, mu1, s1), (_, mu4, s4) = stats_h(espectros[1]), stats_h(espectros[4])
    check('espectro N=1 contra N=4: mismo pico (±0.2 sigma)', abs(mu1 - mu4) < 0.2 * max(s1, 1),
          f'{mu1:.2f} vs {mu4:.2f}')
    check('espectro N=1 contra N=4: mismo ancho (±10 %)', abs(s4 / max(s1, 1e-9) - 1) < 0.10,
          f'{s1:.2f} vs {s4:.2f}')
    np.savez_compressed(args.out.replace('.json', '_periodico.npz'),
                        h1=espectros[1], h4=espectros[4])

    print('\n[periodico] F_TRISE contra cfg_pre_dly')
    m.w32(R_N_ACC_CFG, 1)
    m.sel_1d(F_TRISE, 3)                     # z = 3: el canal ES la feature
    tr = {}
    for dly in (0, 11, 31, 61):
        m.w32(R_PRE_DLY, dly)
        d = m.medir(1.0)
        _, mu, sg = stats_h(d['_h'], lo=0)
        tr[dly] = (mu, sg)
        print(f'        pre_dly {dly:3d}: t_subida {mu:7.2f} ± {sg:.2f} muestras')
    pend = np.polyfit(list(tr), [v[0] for v in tr.values()], 1)[0]
    check('t_subida corre exactamente lo que se retarda (pendiente 1)', abs(pend - 1) < 0.02,
          f'{pend:.4f}')
    # El pico de la forma cae a 90.3 muestras del pie; la ventana abre en
    # pie + latencia - 2 - pre_dly, así que latencia = 92.3 + pre_dly - t_subida.
    lat = 92.3 + 11 - tr[11][0]
    print(f'        latencia pie -> trig_i estimada: {lat:.1f} ciclos '
          f'(pre_dly sugerido con 4 de margen: {math.ceil(lat - 2 + 4)})')
    out['trise'] = {str(k): v for k, v in tr.items()}
    out['latencia_estimada'] = lat

    print('\n[periodico] F_DTPREV contra el período del generador')
    m.w32(R_PRE_DLY, 11)
    m.sel_1d(F_DTPREV, 0)                    # z = 0: canal = feature >> 3
    d = m.medir(args.segundos)
    h = d['_h']
    c0 = int(round(periodo / 8))
    frac = h[c0 - 1:c0 + 2].sum() / max(h.sum(), 1)
    check(f'F_DTPREV en el período ({periodo:.0f} muestras, canal {c0})', frac > 0.99,
          f'{100 * frac:.2f} % en {c0 - 1}..{c0 + 1}')
    out['dtprev_frac'] = float(frac)
    m.sel_1d(F_PEAK, 0)
    return out


def etapa_par(m, mt, gen, args):
    from campanas.estimulo import _aplicar
    dt_par = args.par_dt
    T = 1.0 / args.tasa_par
    n_pts = 16384
    t = np.arange(n_pts) * T / n_pts
    # headroom 2: un pulso solo llega a la mitad del rango; el segundo arranca
    # sobre la cola del primero
    onda = 0.5 * (forma_pulso(t) + forma_pulso(t - dt_par))
    print(f'\n[par] pares a {dt_par * 1e6:g} us ({dt_par * FS:.0f} muestras), '
          f'{args.tasa_par:g} pares/s, pulso de ~{args.amp_par / 4 * 8192:.0f} cuentas')
    _aplicar(gen, args.gen_ch, onda, 1.0 / T, args.amp_par, normalize=False)
    m.configurar(n_acc=1, gate_long=args.gate)
    mt.armar(thr=args.thr, hyst=args.hyst)
    m.medir(0.5, histograma=False)
    d_mu = dt_par * FS
    out = {}
    for n in (1, 2, 4):
        m.w32(R_N_ACC_CFG, n)
        res = {}
        for f, z in ((F_SOLAPE, 3), (F_DTPREV, 3), (F_DTNEXT, 3), (F_PEAK, 0)):
            m.sel_1d(f, z)
            res[f] = m.medir(args.segundos)
        d = res[F_SOLAPE]
        etq = f'par N={n}'
        rt = d['realtime'] / FS
        check(f'{etq}: dos disparos por par', abs(d['cross'] / rt / (2 * args.tasa_par) - 1) < 0.01,
              f"{d['cross'] / rt:.1f} disparos/s")
        invariantes(d, n, etq)
        hs = d['_h']
        tot = max(hs.sum(), 1)
        if n == 1:
            check(f'{etq}: el segundo se pierde con la ventana abierta',
                  abs(d['lost_active'] / max(d['cross'], 1) - 0.5) < 0.005,
                  f"lost_active {d['lost_active']} de {d['cross']}")
            # "adentro" es que llegó otro disparo dentro de la ventana, haya
            # abierto o no; "perdido", que además no encontró ranura
            sp = SOL_PERDIDO | SOL_ADENTRO
            check(f'{etq}: toda ventana marcada "adentro" y "perdido"', hs[sp] / tot > 0.99,
                  f'{100 * hs[sp] / tot:.2f} %')
        else:
            check(f'{etq}: se miden los dos', d['open'] == d['cross'] and d['lost_active'] == 0,
                  f"open {d['open']} cross {d['cross']}")
            check(f'{etq}: mitad "disparo adentro", mitad "otra abierta"',
                  abs(hs[SOL_ADENTRO] / tot - 0.5) < 0.01 and abs(hs[1] / tot - 0.5) < 0.01,
                  f'adentro {100 * hs[SOL_ADENTRO] / tot:.2f} %, otras=1 {100 * hs[1] / tot:.2f} %')
            hp, hn = res[F_DTPREV]['_h'], res[F_DTNEXT]['_h']
            lo, hi = int(d_mu) - 3, int(d_mu) + 4
            check(f'{etq}: F_DTPREV del segundo = {d_mu:.0f} (±3)',
                  abs(hp[lo:hi].sum() / max(hp.sum(), 1) - 0.5) < 0.01,
                  f'{100 * hp[lo:hi].sum() / max(hp.sum(), 1):.2f} % en {lo}..{hi - 1}')
            check(f'{etq}: F_DTNEXT del primero = {d_mu:.0f} (±3), el segundo sin siguiente',
                  abs(hn[lo:hi].sum() / max(hn.sum(), 1) - 0.5) < 0.01
                  and abs(hn[-1] / max(hn.sum(), 1) - 0.5) < 0.01,
                  f'{100 * hn[lo:hi].sum() / max(hn.sum(), 1):.2f} % en {lo}..{hi - 1}, '
                  f'{100 * hn[-1] / max(hn.sum(), 1):.2f} % en 8191')
        check(f'{etq}: cnt_pileup = todas las ventanas', d['pileup'] == d['total'],
              f"{d['pileup']} de {d['total']}")
        hpk = res[F_PEAK]['_h']
        _, mu, sg = stats_h(hpk)
        print(f'        N={n}: open {d["open"]}, lost_active {d["lost_active"]}, '
              f'pico medio {mu:.0f} ± {sg:.0f}')
        out[f'N{n}'] = {**sin_h(d), 'h_solape': hs[:64].tolist(), 'pico': mu, 'sigma': sg,
                        'h_peak_nz': {int(i): int(v) for i, v in enumerate(hpk) if v}}
    m.sel_1d(F_PEAK, 0)
    return out


# --- el trapecio -----------------------------------------------------------
def pulso_preamp(t_s, tau_s=2e-6, sube_s=10e-9):
    """Salida de un preamplificador de carga: subida rápida y cola exponencial,
    normalizada al pico."""
    t = np.maximum(t_s, 0.0)
    p = (1 - np.exp(-t / sube_s)) * np.exp(-t / tau_s)
    return np.where(t_s > 0, p, 0.0) / p.max()


def picos(h, lo, hi):
    """Centroide y sigma de un histograma entre dos canales."""
    c = np.arange(lo, hi)
    w = h[lo:hi].astype(float)
    if w.sum() == 0:
        return float('nan'), float('nan'), 0
    mu = (c * w).sum() / w.sum()
    return float(mu), float(math.sqrt(((c - mu) ** 2 * w).sum() / w.sum())), int(w.sum())


def etapa_trapecio(m, mt, gen, args):
    """Pulsos de preamplificador (subida de 10 ns, cola de 2 us) en una sola forma
    de 200 us con un PAR (a1 en 0, a2 = 0.6 a1 en dt) y los mismos dos pulsos
    AISLADOS (a1 en 100 us, a2 en 150 us). El discriminador por F_DTPREV separa
    el segundo del par (dt) de los aislados (50 us o mas), asi que el par y su
    referencia se miden con la misma forma cargada, sin depender de que el
    generador repita la amplitud entre dos cargas.

    El polo-cero se AJUSTA en el hardware: la cola que llega al ADC no es
    exactamente la programada (la cadena Rigol -> entrada de la placa la toca),
    asi que se barre M alrededor del nominal y se toma el que deja al segundo
    del par igual al aislado. Es el ajuste de polo-cero de cualquier MCA."""
    from campanas.estimulo import _aplicar
    if not m.r32(R_CAPS) & CAP_TRAP:
        check('el bitstream tiene el trapecio (CAPS bit 2)', False, f'{m.r32(R_CAPS):#x}')
        return {}
    tau_s, T = 2e-6, 200e-6
    tau = tau_s * FS
    k, mm = args.trap_k, args.trap_m
    mq0 = round(16.0 / (math.exp(1.0 / tau) - 1.0))
    # altura 16*A*k*(1+M) -> 8A: los 13 bits de la amplitud a la izquierda
    sh = round(math.log2(16 * k * (1 + mq0 / 16.0) / 8))
    # La ventana abre pre_dly + 2 - latencia muestras antes del pie (la latencia
    # del disparo con un flanco rapido es de ~7 ciclos), y la meseta va de
    # pie + k + subida hasta pie + k + m: la ventana de 16 va en el medio.
    lw = 4
    pie = args.pre_trap + 2 - 7
    off = pie + k + (mm - (1 << lw)) // 2
    n_pts = 16384
    t = np.arange(n_pts) * T / n_pts
    escala = 1.5                                    # el par mas cercano entra
    out = {'k': k, 'm': mm, 'mq0': mq0, 'sh': sh, 'off': off, 'lw': lw}
    print(f'\n[trapecio] k={k} m={mm} M={mq0 / 16:.2f} (tau {tau:.0f} muestras) sh={sh} '
          f'meseta [{off}, {off + (1 << lw)})')

    m.configurar(n_acc=4, gate_long=args.gate, pre_dly=args.pre_trap)
    m.w32(R_TRAP_KM, (mm << 16) | k)
    m.w32(R_TRAP_MED, (sh << 24) | (lw << 16) | off)
    check('trapecio: la ventana de la meseta entra en la compuerta',
          m.r32(R_TRAP_MED) >> 31, f'{m.r32(R_TRAP_MED):#010x}')
    m.sel_1d(F_TRAP, 0)

    def forma(dt_s):
        u = (pulso_preamp(t) + 0.6 * pulso_preamp(t - dt_s)
             + pulso_preamp(t - 100e-6) + 0.6 * pulso_preamp(t - 150e-6)) / escala
        return 2 * u - 1                            # base en 0 V, pico en amp

    def cargar(dt_s):
        """Carga la forma y verifica que llegue: 4 disparos por periodo. La
        primera carga despues del reset del generador a veces no sale (medido:
        ~1 MHz de disparos espurios), asi que se reintenta una vez."""
        for intento in range(2):
            _aplicar(gen, args.gen_ch, forma(dt_s), 1.0 / T, args.amp_trap, normalize=False)
            mt.armar(thr=args.thr, hyst=args.hyst)
            d = m.medir(0.5, histograma=False)
            tasa = d['cross'] / (d['realtime'] / FS)
            if abs(tasa * T / 4 - 1) < 0.01:
                return True, tasa
            print(f'        la forma no llego ({tasa:.0f} disparos/s, se esperaban '
                  f'{4 / T:.0f}): se recarga')
        return False, tasa

    def discr(lo, hi):
        m.w32(R_DISCR_MIN, lo)
        m.w32(R_DISCR_MAX, hi)
        m.w32(R_DISCR_CTRL, (F_DTPREV << 4) | 1)

    def medir_pob(dt_m):
        """(F del segundo del par, F de a1 aislado y primero del par, F de a2 aislado)"""
        discr(dt_m - 8, dt_m + 8)
        h_par = m.medir(1.0)['_h']
        discr(dt_m + 9, 0xFFFF)
        h_ais = m.medir(1.0)['_h']
        m.w32(R_DISCR_CTRL, 0)
        c = np.arange(len(h_ais))
        mu = (c[1:-1] * h_ais[1:-1]).sum() / max(h_ais[1:-1].sum(), 1)
        a1 = picos(h_ais, int(mu), len(h_ais) - 1)
        a2 = picos(h_ais, 1, int(mu))
        p2 = picos(h_par, 1, len(h_par) - 1)
        return p2, a1, a2, h_par, h_ais

    # --- el barrido de M con el par a dt = trap_dt ---------------------------
    dt_s = args.trap_dt * 1e-6
    dt_m = round(dt_s * FS)
    ok, tasa = cargar(dt_s)
    check(f'trapecio: el generador emite la forma (4 disparos por periodo)', ok,
          f'{tasa:.0f} disparos/s')
    if not ok:
        return out
    filas = []
    print(f'        par a dt = {args.trap_dt:g} us ({dt_m} muestras, k+m = {k + mm}):')
    print(f'        {"M":>8s} {"segundo del par":>16s} {"a2 aislado":>12s} {"error":>8s}'
          f' {"a1 aislado":>12s} {"sigma a1":>9s}')
    for dlt in np.arange(-0.04, 0.0401, 0.01):
        mq = round(mq0 * (1 + dlt))
        m.w32(R_TRAP_MQ, mq)
        p2, a1, a2, _, _ = medir_pob(dt_m)
        # la altura escala con 1+M: se compara el cociente, no el valor absoluto
        err = p2[0] / a2[0] - 1
        filas.append({'mq': mq, 'M': mq / 16, 'par2': p2, 'a1': a1, 'a2': a2, 'err': err})
        print(f'        {mq / 16:8.2f} {p2[0]:16.2f} {a2[0]:12.2f} {100 * err:+7.2f}%'
              f' {a1[0]:12.2f} {a1[1]:9.2f}')
    out['barrido'] = filas
    errs = np.array([f['err'] for f in filas])
    ms = np.array([f['M'] for f in filas])
    pend, orden = np.polyfit(ms, errs, 1)
    m_opt = -orden / pend
    tau_ef = 1.0 / math.log(1.0 + 1.0 / m_opt)
    out.update({'M_opt': m_opt, 'tau_efectiva_muestras': tau_ef})
    print(f'        M que cancela la cola: {m_opt:.2f} muestras (nominal {mq0 / 16:.2f}): '
          f'tau efectiva {tau_ef:.1f} muestras = {tau_ef / FS * 1e6:.3f} us')
    check('trapecio: el error cambia de signo en el barrido (M_opt adentro)',
          errs.min() < 0 < errs.max(), ' '.join(f'{100 * e:+.2f}' for e in errs))

    mq_opt = round(m_opt * 16)
    m.w32(R_TRAP_MQ, mq_opt)
    p2, a1, a2, h_par, h_ais = medir_pob(dt_m)
    err = p2[0] / a2[0] - 1
    out['ajustado'] = {'mq': mq_opt, 'par2': p2, 'a1': a1, 'a2': a2, 'err': err}
    print(f'        con M = {mq_opt / 16:.2f}: segundo del par {p2[0]:.2f} ± {p2[1]:.2f}, '
          f'aislado {a2[0]:.2f} ± {a2[1]:.2f} ({100 * err:+.3f} %)')
    check(f'trapecio con M ajustado: el segundo del par = aislado (±0.2 %)',
          abs(err) < 0.002, f'{100 * err:+.3f} %')

    # El pico, sobre la misma forma: el segundo del par arrastra la cola
    m.sel_1d(F_PEAK, 0)
    discr(dt_m - 8, dt_m + 8)
    pk_par = picos(m.medir(1.0)['_h'], 1, (1 << m.h_aw) - 1)
    m.w32(R_DISCR_CTRL, 0)
    # F_PEAK va al canal A/2 (pico << 2 en 16 b, eje de 13) y F_TRAP al ~A: un
    # a2 aislado tiene el pico en ~a2/2
    print(f'        pico del segundo del par: {pk_par[0]:.1f} (canal; un a2 aislado da ~{a2[0] / 2:.1f})')
    check('pico: el segundo del par arrastra la cola (+10 % o más)',
          pk_par[0] > 1.10 * a2[0] / 2, f'{pk_par[0]:.1f} vs {a2[0] / 2:.1f}')
    out['pico_par2'] = pk_par
    m.sel_1d(F_TRAP, 0)

    # --- dt < k + m: con el M ajustado, el par se contamina igual --------------
    dt2 = 0.5e-6
    dt2_m = round(dt2 * FS)
    ok2, tasa2 = cargar(dt2)
    if ok2:
        p2c, a1c, a2c, _, _ = medir_pob(dt2_m)
        errc = p2c[0] / a2c[0] - 1
        print(f'        par a dt = 0.5 us ({dt2_m} muestras < k+m): segundo {p2c[0]:.2f} '
              f'contra aislado {a2c[0]:.2f} ({100 * errc:+.2f} %)')
        check('trapecio dt < k+m: el segundo se contamina (>1 %)', abs(errc) > 0.01,
              f'{100 * errc:+.2f} %')
        out['dt05'] = {'par2': p2c, 'a2': a2c, 'err': errc}
    else:
        check('trapecio: la forma de dt = 0.5 us llega', False, f'{tasa2:.0f} disparos/s')
    np.savez_compressed(args.out.replace('.json', '_trapecio.npz'), h_par=h_par, h_ais=h_ais)
    m.sel_1d(F_PEAK, 0)
    return out


# --- el banco de trapecios --------------------------------------------------
# (k, m, lw, inicio de la ventana desde el disparo segun el modelo, umbrales
# antes / despues en dt de disparo): docs/mca/pruebas_banco_trapecios.md, con
# el disparo POR PENDIENTE, que es el que hay en la placa (con el de polo-cero
# que se propone, la ultima forma seria 8/8 y los umbrales los de esa tabla)
BANCO = ((64, 48, 4, 71, 100, 93), (32, 24, 3, 31, 52, 45),
         (16, 12, 2, 12, 28, 23), (8, 12, 1, 5, 19, 14))


def etapa_banco(m, mt, gen, args):
    """Cada forma del banco con el trapecio unico del bitstream de prueba.

    Una forma arbitraria de 200 us con cinco pulsos de preamplificador: el par
    (A = 1 en 0, B = 0.6 en dt), a1 = 1 en 70 us, a2 = 0.6 en 120 us y un
    pulso chico de 0.04 en 165 us. Cada uno tiene un F_DTPREV distinto (A
    35 us, B dt, a1 70 us - dt, a2 50 us, el chico 45 us), asi que el
    discriminador por F_DTPREV saca cada poblacion sola, con la misma carga del
    generador: no depende de que repita la amplitud entre cargas.

    Por forma: (1) con el par lejos, barre el offset de la ventana y se queda
    con el medio de la meseta de a1; (2) la linealidad: el cociente chico/a1
    contra el de 64/48 (el walk del disparo corre la ventana de los pulsos
    chicos); (3) el error de A y de B contra los aislados, a dt alrededor de
    los umbrales del modelo. Si el par se funde en un disparo (4 por periodo en
    vez de 5) B no se mide: es la resolucion del disparo."""
    from campanas.estimulo import _aplicar
    if not m.r32(R_CAPS) & CAP_TRAP:
        check('el bitstream tiene el trapecio (CAPS bit 2)', False, f'{m.r32(R_CAPS):#x}')
        return {}
    tau_s, T = 2e-6, 200e-6
    mq0 = round(16.0 / (math.exp(1.0 / (tau_s * FS)) - 1.0))
    mq = args.trap_mq if args.trap_mq else mq0
    print(f'\n[banco] M = {mq / 16:.2f}' + ('' if args.trap_mq else
          '  (el NOMINAL: correr antes la etapa trapecio o pasar --trap-mq)'))
    if args.disparo == 'pz':
        m.bl_holdoff = m.bl_holdoff or HOLDOFF_BANCO
    m.configurar(n_acc=4, gate_long=args.gate, pre_dly=args.pre_trap)
    m.w32(R_TRAP_MQ, mq)
    n_pts = 16384
    t = np.arange(n_pts) * T / n_pts
    escala = 1.7

    def us(x):
        return round(x * FS)
    DT_A, DT_A2, DT_CH, T_A1 = us(35e-6), us(50e-6), us(45e-6), us(70e-6)

    def forma(d):
        dt_s = d / FS
        u = (pulso_preamp(t) + 0.6 * pulso_preamp(t - dt_s) + pulso_preamp(t - 70e-6)
             + 0.6 * pulso_preamp(t - 120e-6) + 0.04 * pulso_preamp(t - 165e-6)) / escala
        return 2 * u - 1

    def cargar(d):
        """Carga y cuenta disparos por periodo: 5, o 4 si el par se fundio."""
        por = float('nan')
        for _ in range(2):
            _aplicar(gen, args.gen_ch, forma(d), 1.0 / T, args.amp_trap, normalize=False)
            armar_disparo(mt, args, mq)
            dd = m.medir(0.5, histograma=False)
            por = dd['cross'] / (dd['realtime'] / FS) * T
            if min(abs(por - 5), abs(por - 4)) < 0.05:
                return round(por)
            print(f'        la forma no llego ({por:.2f} disparos por periodo): se recarga')
        return None

    def pob(dtprev, ancho=24, seg=1.0):
        m.w32(R_DISCR_MIN, max(0, dtprev - ancho))
        m.w32(R_DISCR_MAX, min(0xFFFF, dtprev + ancho))
        m.w32(R_DISCR_CTRL, (F_DTPREV << 4) | 1)
        h = m.medir(seg)['_h']
        m.w32(R_DISCR_CTRL, 0)
        return picos(h, 1, len(h) - 1)

    out = {'mq': mq, 'formas': []}
    ref = None
    # Cada disparo con su banco: la pendiente corre el instante 7 ciclos con la amplitud,
    # asi que su forma corta necesita 12 de meseta, y aun asi el pulso chico sale corrido
    # 2-5 % (medido); el polo-cero corre 1 y le alcanza con 8.
    for k, mm, lw, c, u_ant, u_des in (BANCO_PZ if args.disparo == 'pz' else BANCO):
        sh = round(math.log2(16 * k * (1 + mq0 / 16.0) / 8))
        m.w32(R_TRAP_KM, (mm << 16) | k)
        m.sel_1d(F_TRAP, 0)
        fila = {'k': k, 'm': mm, 'lw': lw, 'sh': sh}
        u = max(u_ant, u_des)
        lejos = u + 60
        print(f'\n  forma {k}/{mm}/{1 << lw} (sh {sh}), umbrales del modelo {u_ant}/{u_des}')
        if cargar(lejos) != 5:
            check(f'banco {k}/{mm}: el generador emite la forma', False)
            continue
        # (1) el offset
        off_nom = c + args.pre_trap + 2
        barrido = []
        for off in range(max(0, off_nom - 4), off_nom + 5):
            m.w32(R_TRAP_MED, (sh << 24) | (lw << 16) | off)
            barrido.append((off, pob(T_A1 - lejos, seg=0.5)[0]))
        mx = max(v for _, v in barrido)
        meseta = [o for o, v in barrido if v >= mx * (1 - 0.001)]
        off = meseta[len(meseta) // 2]
        m.w32(R_TRAP_MED, (sh << 24) | (lw << 16) | off)
        fila.update({'barrido_off': barrido, 'off': off, 'off_nominal': off_nom})
        print(f'        offset: meseta (a1 a 0.1 % del maximo) en {meseta}, se usa {off} '
              f'(el modelo dice {off_nom})')
        check(f'banco {k}/{mm}: la ventana entra en la compuerta', m.r32(R_TRAP_MED) >> 31,
              f'{m.r32(R_TRAP_MED):#010x}')
        check(f'banco {k}/{mm}: el offset del modelo cae en la meseta (+-2)',
              any(abs(o - off_nom) <= 2 for o in meseta), f'{meseta}')
        # (2) la linealidad
        a1, ch = pob(T_A1 - lejos), pob(DT_CH)
        cociente = ch[0] / a1[0]
        ref = cociente if ref is None else ref
        lin = cociente / ref - 1
        fila.update({'a1': a1, 'chico': ch, 'linealidad': lin})
        b_now = m.r32(R_BASELINE_NOW) & 0x3FFF
        b_now = b_now - 0x4000 if b_now >= 0x2000 else b_now
        print(f'        chico/a1 = {cociente:.5f} ({100 * lin:+.3f} % contra 64/48); base {b_now}')
        # 0.5 % de un pulso de ~140 cuentas es 0.7 cuentas. Pide la base bien: sin el
        # holdoff del seguidor, mide adentro de las colas y cada forma queda corrida
        # distinto (la fuga de continua va con k*l). La 8/8 no llega: su
        # ventana de 2 muestras cae en el borde de una meseta corta, y a esta amplitud el
        # disparo se corre. Medido con subida de 2.9 muestras: -3 %, ~4 cuentas.
        tol = 0.04 if k == 8 else 0.005
        check(f'banco {k}/{mm}: el pulso chico (0.04) mide igual que con 64/48 (+-{100 * tol:g} %)',
              abs(lin) < tol, f'{100 * lin:+.3f} %')
        # (3) los pares
        filas = []
        print(f'        {"dt":>5s} {"disp":>4s} {"error A":>9s} {"error B":>9s}')
        for d in sorted({u - 6, u - 3, u, u + 4, u + 10, u + 30}):
            n = cargar(d)
            if n is None:
                filas.append({'dt': d, 'disparos': None})
                continue
            junto = n == 4
            pa, ra = pob(DT_A), pob(T_A1 - (0 if junto else d))
            r2 = pob(DT_A2)
            ea = pa[0] / ra[0] - 1
            eb = float('nan')
            if not junto:
                eb = pob(d, ancho=8)[0] / r2[0] - 1
            filas.append({'dt': d, 'disparos': n, 'err_A': ea, 'err_B': eb})
            print(f'        {d:5d} {n:4d} {100 * ea:+8.3f}% {100 * eb:+8.3f}%')
        fila['pares'] = filas
        # Si el par se fundio en un disparo, A se mide con B adentro y nadie lo
        # marca: es el limite del disparo (pruebas_banco_trapecios.md, sec. 4),
        # no de la forma. Se reporta aparte.
        juntos = [f['dt'] for f in filas if f.get('disparos') == 4]
        if juntos:
            print(f'        el par dio UN disparo en dt = {juntos}: B no se mide y A queda '
                  f'contaminado sin marca')
        fila['dt_fundidos'] = juntos
        ok_b = [f for f in filas if f.get('disparos') == 5 and f['dt'] >= u_ant + 4]
        ok_a = [f for f in filas if f.get('disparos') == 5 and f['dt'] >= u_des + 4]
        check(f'banco {k}/{mm}: B < 1 % desde dt = {u_ant} + 4',
              ok_b and all(abs(f['err_B']) < 0.01 for f in ok_b),
              ' '.join(f"{f['dt']}:{100 * f['err_B']:+.2f}" for f in ok_b))
        check(f'banco {k}/{mm}: A < 1 % desde dt = {u_des} + 4',
              ok_a and all(abs(f['err_A']) < 0.01 for f in ok_a),
              ' '.join(f"{f['dt']}:{100 * f['err_A']:+.2f}" for f in ok_a))
        out['formas'].append(fila)
    m.sel_1d(F_PEAK, 0)
    return out


def armar_disparo(mt, args, mq):
    """El disparo de --disparo: la pendiente (thr, hyst) o el polo-cero con el
    umbral en 50 cuentas de amplitud y el M del MCA."""
    if args.disparo == 'pz':
        from API.multitrigger import pz_ganancia
        g = pz_ganancia(mq=mq)
        mt.armar_pz(mq=mq, thr=int(round(50 * g)), hyst=int(round(25 * g)))
    else:
        mt.armar(thr=args.thr, hyst=args.hyst)


def etapa_disparo(m, mt, gen, args):
    """Cuantos disparos da el multitrigger para dos pulsos a dt: 8 pares por
    periodo de 200 us, disparos por par = 1 o 2. Primero 1 y 0.6, despues uno
    grande y uno de 0.04 en su cola.

    Con la pendiente (--disparo pendiente) la simulacion del RTL da dos
    disparos desde ~20 muestras, y en la cola la pendiente negativa tapa al
    chico hasta ~150-190. Con el polo-cero (--disparo pz) los dos se separan
    desde 7-8 muestras con una subida de 1.2: el trapecio vuelve a cero y la cola
    no tapa nada.

    La separacion depende de la subida de la senal, y lo que da el generador no
    es lo de la simulacion. Medido con la forma arbitraria (2026-11-05): con
    sube_s = 5 ns (1.6 muestras de 10 a 90 %, lo mas rapido sin sobrepaso) separa
    desde 10; con 10 ns (2.9 muestras), desde 13. Por eso con el polo-cero esta
    etapa usa la de 5 ns: un pulso cada 40 us, para que 16384 puntos la resuelvan."""
    from campanas.estimulo import _aplicar
    pz = args.disparo == 'pz'
    T, N, sube = (40e-6, 1, 5e-9) if pz else (200e-6, 8, 10e-9)
    n_pts = 16384
    t = np.arange(n_pts) * T / n_pts
    sep = T / N
    m.configurar(n_acc=4, gate_long=args.gate, pre_dly=args.pre_trap)
    mq = args.trap_mq or round(16.0 / (math.exp(1.0 / (2e-6 * FS)) - 1.0))
    out = {'disparo': args.disparo}
    print(f'\n[disparo] {args.disparo}: disparos por par contra dt (muestras)')
    listas = ((('1 -> 0.6', 0.6, [5, 7, 8, 9, 10, 11, 12, 15, 20]),
               ('1 -> 0.04', 0.04, [5, 7, 8, 9, 10, 11, 12, 15, 20])) if pz else
              (('1 -> 0.6', 0.6, [6, 9, 12, 15, 18, 21, 24, 30, 40]),
               ('1 -> 0.04', 0.04, [20, 50, 100, 140, 170, 200, 250, 400])))
    for nombre, r, dts in listas:
        filas = []
        for d in dts:
            u = sum(pulso_preamp(t - i * sep, sube_s=sube) +
                    r * pulso_preamp(t - i * sep - d / FS, sube_s=sube) for i in range(N)) / 1.7
            _aplicar(gen, args.gen_ch, 2 * u - 1, 1.0 / T, args.amp_trap, normalize=False)
            armar_disparo(mt, args, mq)
            dd = m.medir(1.0, histograma=False)
            filas.append((d, dd['cross'] / (dd['realtime'] / FS) * T / N))
        sep2 = next((d for j, (d, _) in enumerate(filas)
                     if all(abs(q - 2) < 0.02 for _, q in filas[j:])), None)
        print(f'  {nombre}: ' + ' '.join(f'{d}:{q:.2f}' for d, q in filas) +
              f'  -> dos disparos desde dt = {sep2}')
        out[nombre] = {'filas': filas, 'dos_desde': sep2}
    s1, s2 = out['1 -> 0.6']['dos_desde'], out['1 -> 0.04']['dos_desde']
    if pz:
        check('disparo pz: dos pulsos de 1 y 0.6 se separan desde <= 10 muestras (simulacion: 7)',
              s1 is not None and s1 <= 10, s1)
        check('disparo pz: el de 0.04 en la cola de uno de 1 dispara desde <= 10 muestras '
              '(simulacion: 7; la pendiente, > 100)', s2 is not None and s2 <= 10, s2)
        # Aislados: un disparo por pulso, y que el sobrepaso de un flanco abrupto (1 ns:
        # 8 % a la entrada, la salida re-arma y rebota) lo tape el holdoff del shield.
        def por_pulso(sube_s, vpp, dur=0):
            u = pulso_preamp(t - 1e-6, sube_s=sube_s)
            _aplicar(gen, args.gen_ch, 2 * u - 1, 1.0 / T, vpp, normalize=False)
            armar_disparo(mt, args, mq)
            mt.mt.w32(M_SHIELD, (dur << 16) | ((1 << mt.ch) << 8) | (1 << mt.ch))
            d = m.medir(0.5, histograma=False)
            mt.mt.w32(M_SHIELD, ((1 << mt.ch) << 8) | (1 << mt.ch))
            return d['cross'] / (d['realtime'] / FS) * T
        q5 = [(v, por_pulso(5e-9, v)) for v in (0.012, 0.05, 0.2, 0.45, 1.0)]
        out['aislados_5ns'] = q5
        print('  aislados, 5 ns: ' + ' '.join(f'{v:g} Vpp:{q:.3f}' for v, q in q5))
        check('disparo pz: un disparo por pulso con subida de 5 ns, de ~90 a ~7600 cuentas',
              all(abs(q - 1) < 0.002 for _, q in q5), q5)
        q1 = por_pulso(1e-9, 0.45)
        q1h = por_pulso(1e-9, 0.45, dur=6)
        out['flanco_1ns'] = {'dur0': q1, 'dur6': q1h}
        print(f'  aislado, 1 ns y 0.45 Vpp: {q1:.3f} disparos; con holdoff de 6 ciclos: {q1h:.3f}')
        check('disparo pz: el flanco de 1 ns da mas de un disparo (el sobrepaso rebota)', q1 > 1.1, q1)
        check('disparo pz: el holdoff de 6 ciclos deja uno solo', abs(q1h - 1) < 0.002, q1h)
    else:
        check('disparo: dos pulsos de 1 y 0.6 se separan desde 12..30 muestras (simulacion: ~20)',
              s1 is not None and 12 <= s1 <= 30, s1)
        check('disparo: un pulso de 0.04 en la cola de uno de 1 tarda mas de 100 muestras en disparar',
              s2 is None or s2 > 100, s2)
    return out


def etapa_falsos(m, mt, gen, args):
    """El disparo con polo-cero sin senal: la salida del generador apagada.

    Tiene que dar cero con el umbral de trabajo (50 cuentas) y con un margen
    (40). Medido (2026-11-05): ninguno en 37 G muestras con 50 ni en 7.5 G con
    40; con 30 ya aparecen (uno en 7.5 G), y con 20 son miles por segundo."""
    from API.multitrigger import pz_ganancia
    if not mt.tiene_pz():
        check('el multitrigger tiene el disparo con polo-cero (CAPS[17])', False)
        return {}
    gen.output(args.gen_ch, False)
    time.sleep(0.5)
    m.configurar(n_acc=4, gate_long=args.gate_banco, pre_dly=args.pre_banco)
    mq = args.trap_mq or round(16.0 / (math.exp(1.0 / (2e-6 * FS)) - 1.0))
    g = pz_ganancia(mq=mq)
    out = {}
    print('\n[falsos] polo-cero, sin senal')
    for thr, seg in ((50, args.seg_falsos), (40, args.seg_falsos / 2)):
        mt.armar_pz(mq=mq, thr=int(round(thr * g)), hyst=int(round(thr / 2 * g)))
        d = m.medir(seg, histograma=False)
        rt = d['realtime'] / FS
        out[thr] = {'realtime': rt, 'cross': d['cross']}
        check(f'falsos: ninguno con umbral {thr} en {rt * FS / 1e9:.1f} G muestras', d['cross'] == 0, d['cross'])
    mt.desarmar_pz()
    return out


# --- el banco del RTL, con el disparo con polo-cero ------------------------
# (k, m, lw, inicio de la ventana desde el disparo segun el modelo, umbrales
# antes / despues): docs/mca/pruebas_banco_trapecios.md con el polo-cero. En el
# registro, off = c + pre_dly + 2; la compuerta tiene que cubrir la ventana de
# la primera: c + pre_dly + 2 + 8 + 16 = 111 con pre_dly 16 (bit 31 de FORMA_MED).
BANCO_PZ = ((64, 48, 4, 69, 97, 96), (32, 24, 3, 29, 49, 48),
            (16, 12, 2, 9, 26, 24), (8, 8, 1, 0, 15, 13))
HOLDOFF_BANCO = 1500     # del seguidor de base, a la baja tasa de estas etapas


def etapa_banco_rtl(m, mt, gen, args):
    """El banco de trapecios del RTL con el disparo con polo-cero: cada ranura
    elige la forma sola, por F_DTPREV y F_DTNEXT.

    La forma de onda es la de la etapa banco (el par A = 1 en 0 y B = 0.6 en
    dt, a1 = 1 en 70 us, a2 = 0.6 en 120 us y 0.04 en 165 us). Para cada dt:
    (1) la forma que eligio B (el histograma de F_FORMA, discriminado por
    F_DTPREV = dt) es la de la regla; (2) la de A (F_DTPREV = 35 us,
    F_DTNEXT = dt) tambien; (3) F_TRAP de B contra a2 aislado, y de A contra a1,
    a menos de 1 % mientras no esten marcados."""
    import copy
    from campanas.estimulo import _aplicar
    args = copy.copy(args)               # el disparo de esta etapa no queda para las otras
    args.disparo = 'pz'
    if not m.r32(R_CAPS) & CAP_TRAP or ((m.r32(R_N_FORMAS) >> 8) & 7) < len(BANCO_PZ):
        check('el bitstream tiene el banco de 4 formas (0x134)', False, f'{m.r32(R_N_FORMAS):#x}')
        return {}
    if not mt.tiene_pz():
        check('el multitrigger tiene el disparo con polo-cero (CAPS[17])', False)
        return {}
    tau_s, T = 2e-6, 200e-6
    mq0 = round(16.0 / (math.exp(1.0 / (tau_s * FS)) - 1.0))
    mq = args.trap_mq or mq0
    pre, gate = args.pre_banco, args.gate_banco
    # Sin holdoff el seguidor mide dentro de las colas, y cada forma queda corrida
    # distinto: el error máximo da 1.15 % en vez de 0.81 % (medido).
    m.bl_holdoff = m.bl_holdoff or HOLDOFF_BANCO
    m.configurar(n_acc=4, gate_long=gate, pre_dly=pre)
    m.w32(R_TRAP_MQ, mq)
    for f, (k, mm, lw, c, an, de) in enumerate(BANCO_PZ):
        sh = round(math.log2(16 * k * (1 + mq0 / 16.0) / 8))
        m.w32(R_FORMA + 16 * f, (mm << 16) | k)
        m.w32(R_FORMA + 16 * f + 4, (sh << 24) | (lw << 16) | (c + pre + 2))
        m.w32(R_FORMA + 16 * f + 8, (de << 16) | an)
    m.w32(R_N_FORMAS, len(BANCO_PZ))
    time.sleep(0.01)
    oks = [bool(m.r32(R_FORMA + 16 * f + 4) >> 31) for f in range(len(BANCO_PZ))]
    check(f'banco rtl: las 4 ventanas entran en la compuerta de {gate}', all(oks), oks)
    check('banco rtl: los umbrales de despues entran en la compuerta', m.r32(R_N_FORMAS) >> 31,
          f'{m.r32(R_N_FORMAS):#x}')

    n_pts = 16384
    t = np.arange(n_pts) * T / n_pts

    def us(x):
        return round(x * FS)
    DT_A, DT_A2, T_A1 = us(35e-6), us(50e-6), us(70e-6)

    def regla(dtp, dtn):
        for f, (_, _, _, _, an, de) in enumerate(BANCO_PZ):
            if an <= dtp and de <= dtn:
                return f
        return 0xFFFF

    def cargar(d):
        u = (pulso_preamp(t) + 0.6 * pulso_preamp(t - d / FS) + pulso_preamp(t - 70e-6)
             + 0.6 * pulso_preamp(t - 120e-6) + 0.04 * pulso_preamp(t - 165e-6)) / 1.7
        _aplicar(gen, args.gen_ch, 2 * u - 1, 1.0 / T, args.amp_trap, normalize=False)
        armar_disparo(mt, args, mq)
        dd = m.medir(0.5, histograma=False)
        return round(dd['cross'] / (dd['realtime'] / FS) * T)

    def pob(dtprev, feat, ancho=2, seg=1.0):
        # F_FORMA con zoom 3: el bin es el valor (0..3), y 0xFFFF satura arriba
        m.sel_1d(feat, 3 if feat == F_FORMA else 0)
        m.w32(R_DISCR_MIN, max(0, dtprev - ancho))
        m.w32(R_DISCR_MAX, min(0xFFFF, dtprev + ancho))
        m.w32(R_DISCR_CTRL, (F_DTPREV << 4) | 1)
        h = m.medir(seg)['_h']
        m.w32(R_DISCR_CTRL, 0)
        if feat == F_FORMA:
            cuentas = {f: int(h[f]) for f in range(len(BANCO_PZ))}
            cuentas[0xFFFF] = int(h[-1])
            return max(cuentas, key=cuentas.get), cuentas
        return picos(h, 1, len(h) - 1)

    out = {'mq': mq, 'pre': pre, 'gate': gate, 'pares': []}
    cargar(400)
    ref_a1, ref_a2 = pob(T_A1 - 400, F_TRAP, ancho=24), pob(DT_A2, F_TRAP, ancho=24)
    print(f'\n[banco rtl] M = {mq / 16:.2f}; a1 {ref_a1[0]:.2f}, a2 {ref_a2[0]:.2f} (canales)')
    print(f'  {"dt":>4s} {"disp":>4s} {"forma B":>8s} {"forma A":>8s} {"error A":>8s} {"error B":>8s}')
    for d in (5, 10, 14, 16, 20, 26, 30, 45, 50, 60, 100, 150):
        n = cargar(d)
        fb, cb = pob(d, F_FORMA)
        fa, ca = pob(DT_A, F_FORMA)
        eb_esp, ea_esp = regla(d, 0xFFFF), regla(DT_A, d if d < gate else 0xFFFF)
        ea = eb = float('nan')
        if ea_esp != 0xFFFF:
            ea = pob(DT_A, F_TRAP)[0] / ref_a1[0] - 1
        if eb_esp != 0xFFFF and n == 5:
            eb = pob(d, F_TRAP)[0] / ref_a2[0] - 1
        out['pares'].append({'dt': d, 'disparos': n, 'forma_B': fb, 'forma_A': fa,
                             'esperada_B': eb_esp, 'esperada_A': ea_esp, 'err_A': ea, 'err_B': eb,
                             'cuentas_B': cb, 'cuentas_A': ca})
        print(f'  {d:4d} {n:4d} {fb:8d} {fa:8d} {100 * ea:+7.2f}% {100 * eb:+7.2f}%')
    m.sel_1d(F_PEAK, 0)
    pares = out['pares']
    # Con esta forma (sube_s = 10 ns: 2.9 muestras) el par se separa desde 13; con una
    # subida limpia de 1.6, desde 10 (etapa disparo).
    check('banco rtl: el par se separa en dos disparos desde dt = 14', all(p['disparos'] == 5
          for p in pares if p['dt'] >= 14), [p['disparos'] for p in pares])
    check('banco rtl: B elige la forma de la regla', all(p['forma_B'] == p['esperada_B']
          for p in pares if p['disparos'] == 5), [(p['dt'], p['forma_B']) for p in pares])
    # Si el par se fundio, A no tiene vecino: no se le puede pedir la forma del dt.
    check('banco rtl: A elige la forma de la regla', all(p['forma_A'] == p['esperada_A']
          for p in pares if p['disparos'] == 5), [(p['dt'], p['forma_A']) for p in pares])
    errs = [abs(p[e]) for p in pares for e in ('err_A', 'err_B') if p[e] == p[e]]
    check('banco rtl: A y B no marcados miden a menos de 1 % de los aislados',
          errs and max(errs) < 0.01, f'max {100 * max(errs or [0]):.2f} %')
    return out


# --- Poisson ---------------------------------------------------------------
def arribos_poisson(info):
    """Los instantes de arribo de `poisson_train_wave`, reconstruidos de la
    semilla: mismo generador, mismas llamadas en el mismo orden."""
    rng = np.random.default_rng(info['seed'])
    n_pts = info['n_pts']
    n_arr = int(info['n_events']) if info['fixed_n'] else \
        int(rng.poisson(info['rate_hz'] * info['T_ciclo_s']))
    pos = np.sort(rng.uniform(0.0, n_pts, n_arr))
    idx = np.floor(pos).astype(int) % n_pts
    if n_arr != info['n_events']:
        raise RuntimeError(f'reconstrucción: {n_arr} arribos, el generador dice {info["n_events"]}')
    return idx * info['dt_s'] * FS                 # en ciclos del ADC


def disparos(arr, ciclo, d_merge):
    """Un arribo dispara si el anterior quedó a d_merge o más: el Schmitt de la
    pendiente no se re-arma mientras dura la subida del pulso anterior."""
    gap = np.diff(np.concatenate([[arr[-1] - ciclo], arr]))
    return arr[gap >= d_merge]


def simular(trig, ciclo, n, g1, serv=18, n_ciclos=60, desde=20):
    """M/D/N/N con UN publicador compartido: cada disparo toma una ranura libre,
    mide g1 = gate+1 ciclos, espera al publicador y publica `serv`. Devuelve la
    pérdida y la fracción de tiempo con j ranuras ocupadas."""
    libre = [0.0] * n
    pub = 0.0
    abiertos = perdidos = 0
    intervalos = []
    t0, t1 = desde * ciclo, n_ciclos * ciclo
    for k in range(n_ciclos):
        for t in trig + k * ciclo:
            i = min(range(n), key=lambda j: libre[j])
            if libre[i] <= t:
                ini = max(t + g1, pub)
                pub = ini + serv
                libre[i] = pub
                if t >= t0:
                    abiertos += 1
                intervalos.append((t, pub))
            elif t >= t0:
                perdidos += 1
    # ocupación: barrido de eventos sobre [t0, t1)
    ev = []
    for a, b in intervalos:
        a, b = max(a, t0), min(b, t1)
        if b > a:
            ev += [(a, 1), (b, -1)]
    ev.sort()
    occ = np.zeros(n + 1)
    j, tp = 0, t0
    for t, s in ev:
        occ[j] += t - tp
        j, tp = j + s, t
    occ[j] += t1 - tp
    return perdidos / max(abiertos + perdidos, 1), occ / occ.sum()


def erlang_b(n, rho):
    b = 1.0
    for k in range(1, n + 1):
        b = rho * b / (k + rho * b)
    return b


def etapa_poisson(m, mt, gen, args):
    from campanas.estimulo import encender_poisson, eventos_por_ciclo_max
    m.configurar(n_acc=1, gate_long=args.gate, sel_1d=F_SOLAPE, z_1d=3)
    g1 = args.gate + 1
    out = []
    for tasa in args.tasas:
        for semilla in args.semillas:
            n_ev = min(args.eventos, eventos_por_ciclo_max(tasa, 2e-6))
            freq, info = encender_poisson(gen, args.gen_ch, tasa, args.amp, n_eventos=n_ev,
                                          semilla=semilla)
            arr = arribos_poisson(info)
            ciclo = info['T_ciclo_s'] * FS
            mt.armar(thr=args.thr, hyst=args.hyst)
            m.medir(0.3, histograma=False)
            print(f'\n[poisson] {tasa:g} ev/s pedidos, semilla {semilla}: {info["n_events"]} '
                  f'arribos en {info["T_ciclo_s"] * 1e3:.2f} ms ({info["rate_real"]:.0f} ev/s)')
            fila = {'tasa': tasa, 'semilla': semilla, 'info': info, 'runs': {}}
            for n in (1, 2, 3, 4):
                m.w32(R_N_ACC_CFG, n)
                d = m.medir(args.segundos)
                rt = d['realtime'] / FS
                etq = f'poisson {tasa:g}/{semilla} N={n}'
                invariantes(d, n, etq)
                # disparos por ciclo del patrón -> d_merge que los explica
                por_ciclo = d['cross'] / (d['realtime'] / ciclo)
                cand = np.arange(0, 400)
                nd = np.array([len(disparos(arr, ciclo, x)) for x in cand])
                d_merge = int(cand[np.argmin(np.abs(nd - por_ciclo))])
                trig = disparos(arr, ciclo, d_merge)
                l_sim, occ_sim = simular(trig, ciclo, n, g1)
                l_med = 1 - d['open'] / max(d['cross'], 1)
                to = np.array(d['t_ocup'][:n + 1], float)
                occ_med = to / to.sum()
                tau_med = sum(j * x for j, x in enumerate(d['t_ocup'])) / max(d['open'], 1)
                rho = d['cross'] / d['realtime'] * tau_med
                l_erl = erlang_b(n, rho)
                hs = d.pop('_h')
                print(f'        N={n}: {d["cross"] / rt:8.0f} disparos/s (d_merge {d_merge:3d}), '
                      f'pérdida {100 * l_med:6.2f} % · sim {100 * l_sim:6.2f} % · '
                      f'Erlang {100 * l_erl:6.2f} % · tau {tau_med:.1f} · '
                      f'solapes {100 * d["pileup"] / max(d["total"], 1):.1f} %')
                tol = max(0.005, 0.1 * l_sim)
                check(f'{etq}: pérdida = simulación sobre el patrón (±{100 * tol:.1f} pp)',
                      abs(l_med - l_sim) <= tol, f'{100 * l_med:.2f} vs {100 * l_sim:.2f} %')
                check(f'{etq}: ocupación = simulación (±0.01 por casillero)',
                      np.max(np.abs(occ_med - occ_sim)) < 0.01,
                      ' '.join(f'{a:.3f}/{b:.3f}' for a, b in zip(occ_med, occ_sim)))
                fila['runs'][n] = {**sin_h(d), 'd_merge': d_merge, 'l_med': l_med,
                                   'l_sim': l_sim, 'l_erl': l_erl, 'rho': rho,
                                   'tau_med': tau_med, 'occ_med': occ_med.tolist(),
                                   'occ_sim': occ_sim.tolist(), 'h_solape': hs[:64].tolist()}
            out.append(fila)
    return out


# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--etapas', nargs='+', default=['regs', 'periodico', 'par', 'poisson'],
                    choices=['regs', 'periodico', 'par', 'poisson', 'trapecio', 'banco',
                             'disparo', 'banco_rtl', 'falsos'])
    ap.add_argument('--disparo', choices=['pendiente', 'pz'], default='pendiente',
                    help='la fuente de la etapa disparo (banco_rtl usa siempre pz)')
    ap.add_argument('--base', type=int, default=None,
                    help='base fija en cuentas, sin seguidor: la del generador encendido')
    ap.add_argument('--bl-holdoff', type=int, default=0, help='holdoff del seguidor de base, ciclos')
    ap.add_argument('--seg-falsos', type=float, default=60.0, help='segundos sin senal, etapa falsos')
    ap.add_argument('--pre-banco', type=int, default=16, help='cfg_pre_dly para banco_rtl')
    ap.add_argument('--gate-banco', type=int, default=112,
                    help='compuerta para banco_rtl: cubre la ventana de 64/48 (>= 111)')
    ap.add_argument('--recien-cargado', action='store_true',
                    help='verificar también los valores de reset')
    ap.add_argument('--gen-ch', type=int, default=1)
    ap.add_argument('--amp', type=float, default=0.6, help='Vpp del tren y de Poisson')
    ap.add_argument('--amp-par', type=float, default=0.8, help='Vpp de los pares')
    ap.add_argument('--gate', type=int, default=384, help='compuerta larga, en muestras')
    ap.add_argument('--thr', type=int, default=600, help='umbral de la pendiente (L=8, G=4)')
    ap.add_argument('--hyst', type=int, default=300)
    ap.add_argument('--segundos', type=float, default=2.0)
    ap.add_argument('--tasa-per', type=float, default=2000.0)
    ap.add_argument('--tasa-par', type=float, default=5000.0)
    ap.add_argument('--par-dt', type=float, default=1.6e-6)
    ap.add_argument('--tasas', type=float, nargs='+', default=[30e3, 100e3, 250e3])
    ap.add_argument('--semillas', type=int, nargs='+', default=[0, 1])
    ap.add_argument('--eventos', type=int, default=256, help='arribos medios por ciclo de Poisson')
    ap.add_argument('--trap-k', type=int, default=64, help='subida del trapecio, muestras')
    ap.add_argument('--trap-m', type=int, default=48, help='meseta del trapecio, muestras')
    ap.add_argument('--pre-trap', type=int, default=12, help='cfg_pre_dly para la etapa trapecio')
    ap.add_argument('--amp-trap', type=float, default=0.8, help='Vpp de la etapa trapecio')
    ap.add_argument('--trap-dt', type=float, default=1.0, help='separacion del par, us (>= k+m)')
    ap.add_argument('--trap-mq', type=int, default=0,
                    help='Mq para la etapa banco (M*16); 0 = el de la etapa trapecio o el nominal')
    ap.add_argument('--out', default=f'/tmp/mca2_placa_{time.strftime("%Y%m%d_%H%M%S")}.json')
    args = ap.parse_args(argv)

    m = MCA2()
    m.base_fija = args.base
    m.bl_holdoff = args.bl_holdoff
    mt = Pendiente(ch=0)
    resultados = {'args': vars(args)}
    gen = None
    try:
        if 'regs' in args.etapas:
            resultados['regs'] = etapa_regs(m, mt, args.recien_cargado)
        con_gen = [e for e in args.etapas if e != 'regs']
        if con_gen:
            gen = abrir_generador()
            for e in con_gen:
                f = {'periodico': etapa_periodico, 'par': etapa_par, 'poisson': etapa_poisson,
                     'trapecio': etapa_trapecio, 'banco': etapa_banco,
                     'disparo': etapa_disparo, 'banco_rtl': etapa_banco_rtl,
                     'falsos': etapa_falsos}[e]
                hold = m.bl_holdoff
                resultados[e] = f(m, mt, gen, args)
                m.bl_holdoff = hold
                if e == 'trapecio' and resultados[e].get('M_opt') and not args.trap_mq:
                    args.trap_mq = round(resultados[e]['M_opt'] * 16)   # para banco
    finally:
        m.stop()
        mt.desarmar()
        mt.desarmar_pz()
        mt.close()
        if gen is not None:
            try:
                gen.output(args.gen_ch, False)
            finally:
                gen.close()
        m.close()
        resultados['resumen'] = _res
        with open(args.out, 'w') as fh:
            json.dump(resultados, fh, indent=1, default=lambda o: o.tolist()
                      if hasattr(o, 'tolist') else str(o))
        print(f'\nresultados en {args.out}')

    print('\n' + '=' * 62)
    print(f'RESULTADO: {_res["pass"]} PASS, {_res["fail"]} FAIL')
    print('=' * 62)
    return 0 if _res['fail'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
