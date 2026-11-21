#!/usr/bin/env python3
"""El techo del camino original del osciloscopio, la BRAM, con `gen_pulsos`.

Es la medición que faltaba para comparar los caminos de datos
(docs/resultados_meritos_gen_pulsos.md §3.3): hasta ahora la BRAM sólo tenía las corridas
con el Rigol (`run_poisson_loss.py`, 8 + 24 muestras) y el bench de su ciclo con 32. Acá
el estímulo es el generador de pulsos de la FPGA por el lazo digital y el disparo es el
del ASG, como en la fidelidad (`run_fidelidad_osc.py`): no depende de la señal.

La BRAM es single-shot: guarda un evento, se congela y el PS lo lee y la re-arma. Se mide
el lector solo, sin el escritor de la sesión, como la etapa B del ring:

  c       el lazo de libmca (`API.osciloscope.Lector`, el de `BramSource`): espera el
          buffer congelado, lee la ventana de los dos canales y re-arma, en C.
  python  el lazo original, el de `BramSource` antes de libmca 0.11.0 (bdf7d56^): poll de
          `adc_state` por mmap, `rp_AcqGetDataPosV` de librp por canal y el re-armado con
          tres escrituras desde Python. Lo único distinto son las direcciones de las
          máscaras y del snapshot, que hoy están en el slot 3 (mt_cfg.sv).

Dos etapas:

  techo   un tren periódico rápido (`--periodo` ciclos), así que al re-armar siempre hay
          un disparo esperando: los eventos leídos por segundo son el techo del lector,
          en cada ventana de `--ventanas`.
  tasa    Poisson a cada tasa de `--tasas-c` / `--tasas-python`, con la ventana de
          8 + 24 muestras: los eventos leídos por segundo contra la tasa de entrada.

Corre en la placa, con un bitstream que tenga la BRAM, el multitrigger y `gen_pulsos`
(el del MCA o el del ring). Escribe `<outdir>/techo_bram.json`.

    python3 campanas/run_techo_bram.py <outdir> [--etapas techo,tasa] [--lectores c,python]
"""
import argparse
import json
import mmap
import os
import platform
import struct
import sys
import time
from datetime import datetime

import numpy as np

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RAIZ)
sys.path.insert(0, '/opt/redpitaya/lib/python')

import API.generadores as G                                          # noqa: E402

FS_HZ = 125e6
IDENTIDAD = {'gain': 32768, 'base': 32768, 'offset': 0}
DEB_LEN_RESET = 62500               # el debounce de rp_ext_trig, que filtra también el ASG
VENTANAS = '8+24,16+112,16+240,16+479,32+992'      # las del ring, sin 16+998
TASAS_C = '1e3,3e3,1e4,3e4,1e5,3e5,1e6,3e6'
TASAS_PY = '300,1e3,3e3,1e4,3e4,1e5'

# las direcciones del lazo original, con las máscaras y el snapshot donde están hoy
SCOPE_PHYS, SCOPE_SIZE = 0x4010_0000, 0x30000
MTRG_PHYS, MTRG_SIZE = 0x4030_0000, 0x1000
R_STATE, R_WP_TRIG_CH0 = 0x000, 0x01C
MT_SNAP, MT_MASK0, MT_MASK1 = 0x018, 0x040, 0x044
N_BUF = 16384


class Placa:
    """El generador por el lazo digital y la BRAM disparada por el ASG en los dos canales."""

    def __init__(self):
        from API import integration as I
        from API import multitrigger as MT
        from API import osciloscope as O
        self.I, self.MT, self.O = I, MT, O
        self.g = G.GenPulsos.open()
        self.osc = O.osciloscope_open()
        self.mt = MT.MultiTrigger.open()
        self.ig = I.integration_open()
        I.integration_set_route_osc(self.ig, I.TAP_ADC)
        I.integration_set_route_mtrg(self.ig, I.TAP_ADC)
        self.osc.set_calibracion([IDENTIDAD, IDENTIDAD])
        self.g.lazo = True
        self.mascara = MT.BIT_ASG_P

    def armar(self, post):
        """Single-shot, con el shield re-armando el disparo, como `BramSource.arm`. El
        retardo es el post-trigger: la BRAM se congela al completarlo."""
        self.MT.multitrigger_arm(self.osc, self.mt, mask_ch0=self.mascara,
                                 mask_ch1=self.mascara, thr=0.0, hyst=0.01,
                                 delay=max(1, post), we_keep_both=False, auto_rearm=True)
        self.osc.w32(self.O.R_DEB_LEN, 0)            # rp_ext_trig filtra también el ASG

    def desarmar(self):
        self.MT.multitrigger_disarm(self.osc, self.mt)
        self.osc.w32(self.O.R_DEB_LEN, DEB_LEN_RESET)

    def generar(self, cfg):
        self.g.parar()
        self.g.configurar(**cfg)
        # La altura no importa (dispara el ASG), pero con un disparo cada 32 ciclos y
        # τ = 250 los pulsos se apilan unas 8 veces: 100 ADU no llegan al fondo de escala.
        self.g.cargar_tabla([100])
        self.g.arrancar()

    def close(self):
        for paso in (self.g.parar, lambda: setattr(self.g, 'lazo', False), self.desarmar,
                     lambda: self.I.integration_reset_routes(self.ig)):
            try:
                paso()
            except Exception as e:                              # noqa: BLE001
                print(f'  (al cerrar: {type(e).__name__}: {e})')
        self.I.integration_close(self.ig)
        self.mt.close()
        self.O.osciloscope_close(self.osc)
        self.g.close()


def leer_c(placa, pre, post, seg, cap=4096):
    """El lazo de libmca durante `seg` segundos: (eventos, segundos, dead_ns mediano)."""
    lector = placa.O.Lector(placa.osc, placa.mt, pre=pre, post=post, n_ch=2,
                            mascara=placa.mascara, cal=[IDENTIDAD] * 2, single_shot=True,
                            rearmar=True, leer_snap=True)
    cols = dict(wave=np.zeros((cap, 2, pre + post), np.int16),
                t_ns=np.zeros(cap, np.int64), wp=np.zeros(cap, np.int32),
                snap=np.zeros(cap, np.uint32), gap=np.zeros(cap, np.uint8),
                dead_ns=np.zeros(cap, np.int64))
    placa.armar(post)
    lector.iniciar()
    pc = time.perf_counter_ns
    n, muertos = 0, []
    t0 = pc()
    fin = t0 + int(seg * 1e9)
    while pc() < fin:
        k, _, _ = lector.leer(cols, 0, cap, min(fin, pc() + 50_000_000))
        n += k
        muertos.append(cols['dead_ns'][:k].copy())
    t1 = pc()
    placa.desarmar()
    dead = np.concatenate(muertos) if muertos else np.zeros(0)
    return n, (t1 - t0) / 1e9, float(np.median(dead)) if dead.size else None


class LazoOriginal:
    """El lazo de Python con librp, como en `BramSource` antes de libmca 0.11.0
    (wait_event, snapshot, read_into y rearm) y lo que `reader._loop` hace por evento:
    anotar `t_ns`, `wp` y `snap`, leer la ventana y re-armar."""

    def __init__(self, pre, post, mascara, rp):
        self.pre, self.post, self.n = pre, post, pre + post
        self.mascara, self.rp = mascara, rp
        fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        try:
            self.mem = mmap.mmap(fd, SCOPE_SIZE, mmap.MAP_SHARED,
                                 mmap.PROT_READ | mmap.PROT_WRITE, offset=SCOPE_PHYS)
            self.mtm = mmap.mmap(fd, MTRG_SIZE, mmap.MAP_SHARED,
                                 mmap.PROT_READ | mmap.PROT_WRITE, offset=MTRG_PHYS)
        finally:
            os.close(fd)
        self.u32 = struct.Struct('<I')
        import ctypes
        self.chs = (rp.RP_CH_1, rp.RP_CH_2)
        self.fbufs = [rp.fBuffer(self.n) for _ in self.chs]
        self.views = [np.frombuffer((ctypes.c_float * self.n)
                                    .from_address(int(fb.cast().__int__())), dtype=np.float32)
                      for fb in self.fbufs]

    def wait_event(self, deadline_ns):
        mem, unpack, pc = self.mem, self.u32.unpack_from, time.perf_counter_ns
        while True:
            if not (unpack(mem, R_STATE)[0] & 0x1):       # adc_we == 0: congelado
                return unpack(mem, R_WP_TRIG_CH0)[0]
            if pc() > deadline_ns:
                return None

    def snapshot(self):
        return self.u32.unpack_from(self.mtm, MT_SNAP)[0]

    def read_into(self, dst, wp):
        start = (wp - self.pre) % N_BUF
        end = (start + self.n - 1) % N_BUF
        get = self.rp.rp_AcqGetDataPosV
        for k, ch in enumerate(self.chs):
            get(ch, start, end, self.fbufs[k], self.n)
            dst[k] = self.views[k]

    def rearm(self):
        # Asignación por slice, como el w32 de Python de siempre: struct.pack_into sale
        # como stores de a byte, el esclavo AXI no los atiende y da SIGBUS (pasó acá;
        # ver API/tests/placa/test_rw_dev_mem.py).
        pack, mem, mtm = self.u32.pack, self.mem, self.mtm
        mem[R_STATE:R_STATE + 4] = pack(0x0000_0101)      # arm ch0+ch1, single-shot
        mtm[MT_MASK0:MT_MASK0 + 4] = pack(self.mascara)
        mtm[MT_MASK1:MT_MASK1 + 4] = pack(self.mascara)

    def close(self):
        self.mem.close()
        self.mtm.close()


def leer_python(placa, rp, pre, post, seg, cap=4096):
    """El lazo original durante `seg` segundos: (eventos, segundos, None)."""
    lazo = LazoOriginal(pre, post, placa.mascara, rp)
    wave = np.zeros((cap, 2, pre + post), np.float32)
    t_ns = np.zeros(cap, np.int64)
    wps = np.zeros(cap, np.int32)
    snaps = np.zeros(cap, np.uint32)
    wait_event, snapshot, read_into, rearm = (lazo.wait_event, lazo.snapshot,
                                              lazo.read_into, lazo.rearm)
    pc = time.perf_counter_ns
    placa.armar(post)
    n = 0
    t0 = pc()
    fin = t0 + int(seg * 1e9)
    try:
        while True:
            wp = wait_event(min(fin, pc() + 50_000_000))
            if wp is None:
                if pc() >= fin:
                    break
                continue
            i = n % cap
            t_ns[i] = pc()
            wps[i] = wp
            snaps[i] = snapshot()
            read_into(wave[i], wp)
            rearm()
            n += 1
            if t_ns[i] >= fin:
                break
    finally:
        t1 = pc()
        placa.desarmar()
        lazo.close()
    return n, (t1 - t0) / 1e9, None


def parse_ventanas(txt):
    out = []
    for v in txt.split(','):
        pre, post = (int(x) for x in v.split('+'))
        out.append((pre, post))
    return out


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    p.add_argument('outdir')
    p.add_argument('--etapas', default='techo,tasa')
    p.add_argument('--lectores', default='c,python')
    p.add_argument('--ventanas', default=VENTANAS, help='pre+post,... (techo)')
    p.add_argument('--periodo', type=int, default=32,
                   help='ciclos entre disparos en el techo (32: 3.9 M/s)')
    p.add_argument('--tasas-c', default=TASAS_C)
    p.add_argument('--tasas-python', default=TASAS_PY)
    p.add_argument('--seg', type=float, default=2.0, help='segundos por punto')
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)
    lectores = [x for x in a.lectores.split(',') if x]
    etapas = [x for x in a.etapas.split(',') if x]
    rp = None
    if 'python' in lectores:
        import rp as _rp
        _rp.rp_Init()           # librp lee la BRAM: el lazo original lo necesita
        rp = _rp
    placa = Placa()
    puntos = []

    def medir(etapa, lector, pre, post, cfg):
        placa.generar(cfg)
        time.sleep(0.01)
        if lector == 'c':
            n, s, dead = leer_c(placa, pre, post, a.seg)
        else:
            n, s, dead = leer_python(placa, rp, pre, post, a.seg)
        e = placa.g.estado()
        placa.g.parar()
        f = dict(etapa=etapa, lector=lector, pre=pre, post=post, muestras=pre + post,
                 tasa_in=G.tasa(**cfg), leidos=n, seg=s, tasa_out=n / s,
                 ciclo_us=s / n * 1e6 if n else None, dead_ns_mediana=dead,
                 gen_cnt=int(e['gen_cnt']), desborde=bool(e['desborde']))
        print(f'  {etapa:5} {lector:6} {pre:>3}+{post:<4} entrada {f["tasa_in"] / 1e3:9.1f} k/s'
              f'  lee {f["tasa_out"] / 1e3:8.2f} k/s'
              + (f'  ({f["ciclo_us"]:.1f} µs por evento)' if 'techo' == etapa and n else '')
              + (f'  dead {dead / 1e3:.1f} µs' if dead else ''), flush=True)
        puntos.append(f)

    try:
        if 'techo' in etapas:
            cfg = G.config(periodo=a.periodo, n=0, amp_n=1, tau=250.0)
            for lector in lectores:
                for pre, post in parse_ventanas(a.ventanas):
                    medir('techo', lector, pre, post, cfg)
        if 'tasa' in etapas:
            for lector in lectores:
                txt = a.tasas_c if lector == 'c' else a.tasas_python
                for k, t in enumerate(float(x) for x in txt.split(',')):
                    cfg = G.config(aleatorio=True, tasa=t, dt_min=2, n=0, semilla=2 * k + 1,
                                   amp_n=1, tau=250.0)
                    medir('tasa', lector, 8, 24, cfg)
    finally:
        placa.close()
        meta = dict(test='techo_bram', fecha=datetime.now().isoformat(timespec='seconds'),
                    cli=sys.argv[1:], maquina=platform.node(), periodo=a.periodo,
                    seg=a.seg, estimulo='gen_pulsos por el lazo digital, disparo del ASG',
                    lectores={'c': 'libmca, osciloscope_leer_lote',
                              'python': 'el lazo de BramSource antes de libmca 0.11.0 '
                                        '(bdf7d56^), con librp'})
        with open(os.path.join(a.outdir, 'techo_bram.json'), 'w') as fh:
            json.dump(dict(meta=meta, puntos=puntos), fh, indent=1)
        print(f'escrito {os.path.join(a.outdir, "techo_bram.json")}')


if __name__ == '__main__':
    main()
