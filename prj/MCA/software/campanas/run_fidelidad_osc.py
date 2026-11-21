#!/usr/bin/env python3
"""La fidelidad de la captura del osciloscopio: cada muestra capturada contra la que
generó `gen_pulsos`, bit a bit.

Es generación interna (docs/etapas_de_validacion.md). El generador va por el lazo
digital, así que lo que entra a la captura es exactamente la traza del modelo
(`gen_pulsos_model.py`, bit-exacto contra el RTL): cualquier muestra distinta es de
la captura (el tap, la BRAM o la DDR, el bus, la lectura), no de la señal. Las dos
rutas del osciloscopio:

  ring   el event_ring (necesita su bitstream, c1875919 o posterior): una ventana
         `pre + post` por disparo, con el disparo de la fuente ASG del multitrigger
         (uno por pulso, sin mirar la señal). Arribos de Poisson con dos signos, apilados
         y con saturación. Además de las muestras:
           - la marca de tiempo de cada ventana contra el instante del pulso: tiene
             que estar a una distancia CONSTANTE (sin jitter) y ser la de un pulso;
           - los descartes por captura ocupada (DROP_BUSY) contra el tiempo muerto de
             la captura, 2·(pre + post) + 3 ciclos (campanas/run_etapas_ring.py);
           - EV_CNT + DROP_BUSY + DROP_FULL = los disparos del ASG.
  bram   el osciloscopio de Red Pitaya (cualquier bitstream con el generador): unos
         pocos buffers enteros, uno por caso (periódico con signos, saturación,
         Poisson rápido, pulsos negativos lentos sobre una base). El disparo es el
         primer pulso; el pre-trigger tiene que ser ceros (el generador apagado) y
         después el arranque del generador, muestra por muestra. La posición del
         disparo en el buffer tiene que ser la misma en todos los casos.

La placa y la PC hacen cada una su parte, porque el modelo del generador vive en
`modulos/`, que no se sincroniza a la placa:

  medir     en la placa: captura y guarda `fidelidad.json`, `ring.npz` y `bram_<k>.npz`.
            Con la calibración identidad: las cuentas son las crudas del tap ADC.
  analizar  en la PC: regenera la traza, alinea y compara. Deja `analisis.json`.

`medir --simulada` arma, en la PC, las capturas ideales desde el modelo (con desfases
cualesquiera y el tiempo muerto de la captura): sirve para recorrer `analizar` sin
placa, que tiene que dar cero muestras distintas.

**El modo analógico** (`medir --modo analogico`, con un coaxial de OUT1 a IN1 y el jumper
de IN1 en LV): el lazo digital apagado, así que lo capturado es lo que vuelve por IN1.
Ya no se puede comparar bit a bit; se compara contra el canal medido
(`canal_analogico.py`):

  canal  dos capturas de la BRAM sin pulsos (el piso de IN1 y de IN2) y un estímulo de
         banda ancha (Poisson con escalones y ruido) capturado dos veces, con el lazo y
         sin él. De ahí el offset, el ruido, la respuesta (FIR: ganancia, latencia,
         subida, ancho de banda) y la diafonía a IN2.
  bram   cada caso, con el lazo (bit a bit contra el modelo, como en el modo digital) y
         sin él: lo de IN1 contra el FIR aplicado a lo del lazo. El residuo tiene que
         ser el piso, sin muestras que pasen el umbral de un error de captura.
  ring   las marcas y la cuenta igual que en el digital (el disparo del ASG es digital);
         las muestras contra el FIR aplicado al modelo.

Uso:
    python3 campanas/run_fidelidad_osc.py medir <outdir> [--rutas ring,bram]
        [--modo analogico]
    python3 campanas/run_fidelidad_osc.py analizar <outdir>
o, desde la PC, `make campana-fidelidad-osc-remoto OUT=datos/fidelidad_<fecha>`, que
captura en la placa, trae los archivos y analiza.
"""
import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, os.path.join(_RAIZ, 'campanas'))

import API.generadores as G                                          # noqa: E402
import canal_analogico as CA                                         # noqa: E402
# Las capturas del canal viven en la API (las usa también la pestaña «Calibration»).
from API.canal import PRE_CANAL, casos_canal, capturar_canal        # noqa: E402,F401

FS_HZ = 125e6
IDENTIDAD = {'gain': 32768, 'base': 32768, 'offset': 0}
DEB_LEN_RESET = 62500
REARME_ASG = 3            # el ASG no acepta otro disparo a menos de 3 ciclos
BUSQUEDA = 128            # ± ciclos en que se busca la alineación
RUTAS = ('ring', 'bram')
MODOS = ('digital', 'analogico')


# =============================================================================
# El estímulo
# =============================================================================

def caso_ring(a):
    """Poisson con dos signos y cuatro líneas: apila y, con 6000 + cola, satura."""
    gen = G.config(aleatorio=True, tasa=a.tasa_ring, dt_min=2, n=a.n_ring,
                   semilla=a.semilla, amp_aleat=True, tau=250.0, subida=2, base=0,
                   ruido=True, ruido_sh=5, salidas=G.SAL_OUT1)
    tabla = G.tabla_cdf([-3000, 800, 2500, 6000], [0.2, 0.3, 0.3, 0.2])
    return gen, tabla


def casos_bram(semilla=1):
    """(nombre, generador, tabla) de cada buffer. Sin fin (N = 0): el generador corre
    hasta que se lee el buffer."""
    sal = dict(salidas=G.SAL_OUT1, n=0, semilla=semilla)
    return [
        ('periodico', G.config(periodo=700, amp_n=4, tau=250.0, subida=0, base=0,
                               ruido=True, ruido_sh=6, **sal),
         np.array([1500, -1200, 4000, 300], np.int16)),
        ('saturacion', G.config(periodo=250, amp_n=1, tau=250.0, subida=3, base=1000,
                                ruido=False, **sal),
         np.array([5000], np.int16)),
        ('poisson', G.config(aleatorio=True, tasa=1e6, dt_min=2, amp_aleat=True, tau=250.0,
                             subida=1, base=-500, ruido=True, ruido_sh=4, **sal),
         G.tabla_cdf([200, 900, 2600], [0.5, 0.3, 0.2])),
        ('negativos', G.config(periodo=1100, amp_n=3, tau=400.0, subida=7, base=2000,
                               ruido=True, ruido_sh=6, **sal),
         np.array([-6000, -2000, -7000], np.int16)),
    ]


def texto_canal(c):
    """Una línea por aspecto del canal, para la consola."""
    p = c['piso']
    esp = ', '.join(f'{e["f_mhz"]:.2f} MHz ({e["rms"]:.2f})' for e in p['espurias'][:3])
    bw = 'no cae antes de Nyquist' if c['bw_3db_mhz'] is None else f'{c["bw_3db_mhz"]:.1f} MHz'
    return '\n'.join([
        f'  piso IN1: offset {c["offset"]:+.2f}, ruido {c["ruido"]:.2f} cuentas rms '
        f'({p["densidad"] * 1e3:.3f} cuentas/√kHz, blanco equivalente {p["sigma_blanco"]:.2f})'
        + (f'; espurias {esp}' if esp else ''),
        f'  respuesta: ganancia {c["ganancia"]:.4f}, latencia {c["latencia"]:.2f} muestras '
        f'(el ASG corre la ventana {c["lat_asg"]}), subida 10-90 '
        + ('?' if c['subida_ns'] is None else f'{c["subida_ns"]:.1f} ns')
        + f', sobrepico {100 * c["sobrepico"]:.1f} %, -3 dB {bw}; residuo '
        f'{c["residuo_rms"]:.2f} cuentas rms (taps no causales {100 * c["no_causal"]:.2f} %)',
        f'  caída lenta: {100 * c.get("caida_lenta", 0.0):+.2f} % (ganancia en continua '
        f'{c.get("ganancia_dc", c["ganancia"]):.4f}; sin los polos lentos el residuo sería '
        f'{c.get("residuo_rms_fir", c["residuo_rms"]):.2f})',
        f'  IN2: offset {c["offset_in2"]:+.2f}, ruido {c["ruido_in2"]:.2f}; diafonía '
        f'{c["diafonia_db"]:.1f} dB',
    ])


def disparos_asg(t):
    """Los pulsos que la fuente ASG acepta: a REARME_ASG ciclos o más del último
    aceptado (volcado_pulsos.disparos_asg)."""
    out, ult = [], None
    for x in np.asarray(t, np.int64):
        if ult is None or x - ult >= REARME_ASG:
            out.append(int(x))
            ult = x
    return np.array(out, np.int64)


def aceptados_captura(marcas, muerto):
    """Las marcas que la captura del ring acepta: las demás caen con la captura
    ocupada, un tiempo muerto no paralizable de `muerto` ciclos (el de
    run_etapas_ring.descartes_captura, devolviendo cuáles en vez de cuántos)."""
    out, libre = [], None
    for m in np.asarray(marcas, np.int64):
        if libre is None or m >= libre:
            out.append(int(m))
            libre = m + muerto
    return np.array(out, np.int64)


def muerto_ring(pre, post):
    from run_etapas_ring import muerto_captura
    return muerto_captura(pre, post)


# =============================================================================
# medir: la placa, o capturas ideales desde el modelo
# =============================================================================

class CapturaPlaca:
    """El generador por el lazo digital (o, en modo analógico, por OUT1 → IN1), y la
    captura de cada ruta con el tap ADC."""

    nombre = 'placa'

    def __init__(self, rutas, modo='digital'):
        if modo not in MODOS:
            raise ValueError(f'modo {modo!r}: uno de {MODOS}')
        self.modo = modo
        from API import integration as I
        from API import multitrigger as MT
        from API import osciloscope as O
        self.I, self.MT, self.O = I, MT, O
        self.g = G.GenPulsos.open()
        self.osc = O.osciloscope_open()
        self.mt = MT.MultiTrigger.open()
        self.ig = I.integration_open()
        self.ring = None
        if 'ring' in rutas:
            import API.osciloscope_ring as OR
            self.OR = OR
            self.ring = OR.OsciloscopeRing.open()          # RingNotPresent sin el ring
            if self.ring.gen_presente():
                self.ring.gen_apagar()       # que el disparo del ring sea el multitrigger
            I.integration_set_route_ring(self.ig, I.TAP_ADC)
        I.integration_set_route_osc(self.ig, I.TAP_ADC)
        I.integration_set_route_mtrg(self.ig, I.TAP_ADC)
        self.osc.set_calibracion([IDENTIDAD, IDENTIDAD])
        self.n_buf = int(self.osc.n_buf)
        self.g.lazo = modo == 'digital'

    def _armar_asg(self, delay, continuo):
        """El disparo de la fuente ASG en el canal 0 (y nada en el 1). Con `continuo`,
        we_keep y el re-armado por el shield (el ring); si no, single-shot (la BRAM)."""
        self.MT.multitrigger_arm(self.osc, self.mt, mask_ch0=self.MT.BIT_ASG_P, mask_ch1=0,
                                 thr=0.0, hyst=0.01, delay=delay, we_keep_both=continuo,
                                 auto_rearm=continuo)
        if not continuo:
            # multitrigger_arm escribe el retardo crudo sólo con el re-armado automático.
            self.osc.set_raw_delay(delay)
        self.osc.w32(self.O.R_DEB_LEN, 0)        # rp_ext_trig filtra también el ASG

    def _desarmar(self):
        self.MT.multitrigger_disarm(self.osc, self.mt)
        self.osc.w32(self.O.R_DEB_LEN, DEB_LEN_RESET)

    def ring_capturar(self, gen, tabla, pre, post, plazo_s):
        OR, ring, g = self.OR, self.ring, self.g
        g.lazo = self.modo == 'digital'
        g.configurar(**gen)
        g.cargar_tabla(tabla)
        n = int(gen['n'])
        s = pre + post
        lector = OR.LectorRing(ring, pre, post, 2, [IDENTIDAD] * 2)
        lector.configurar()                      # parado: geometría, contadores, footers
        cols = dict(wave=np.zeros((n, 2, s), np.int16), ts_hw=np.zeros(n, np.int64),
                    snap=np.zeros(n, np.uint32), seq=np.zeros(n, np.uint32))
        leidos, quietos = 0, 0
        self._armar_asg(delay=1, continuo=True)
        ring.correr()
        try:
            g.arrancar()
            fin = time.time() + plazo_s
            while time.time() < fin and leidos < n:
                got, _, _ = lector.leer(cols, leidos, n - leidos,
                                        time.perf_counter_ns() + 50_000_000)
                leidos += got
                e, k = g.estado(), ring.contadores()
                quietos = quietos + 1 if (e['terminado'] and leidos == k['ev_cnt']) else 0
                if quietos >= 2:                 # dos veces: una ventana puede estar saliendo
                    break
        finally:
            ring.parar()
            k = ring.contadores()
            e = g.estado()
            g.parar()
            self._desarmar()
        return dict(wave=cols['wave'][:leidos, 0, :], ts_hw=cols['ts_hw'][:leidos],
                    seq=cols['seq'][:leidos],
                    contadores={c: int(v) for c, v in k.items()},
                    gen_estado={c: e[c] for c in ('gen_cnt', 'terminado', 'desborde')})

    def bram_capturar(self, gen, tabla, pre, post, lazo=None):
        """Un buffer de los dos canales. `lazo` None es el del modo; True o False lo
        fija para esta captura (las del canal analógico van de a pares)."""
        osc, g = self.osc, self.g
        if pre + post > self.n_buf:
            raise ValueError(f'{pre} + {post} muestras: el buffer tiene {self.n_buf}')
        g.lazo = (self.modo == 'digital') if lazo is None else bool(lazo)
        g.configurar(**gen)                      # apagado: el lazo da ceros
        g.cargar_tabla(tabla)
        self._armar_asg(delay=post, continuo=False)
        try:
            time.sleep(0.005)                    # el pre-trigger se llena de ceros
            g.arrancar()
            if not osc.wait_fill(timeout_ms=2000):
                raise TimeoutError('la BRAM no completó el post-trigger: ¿disparó el ASG?')
            wp = int(self.O.osciloscope_get_wp_trig(osc, 0))
            buf = np.asarray(osc.read_cal(0, wp - pre, pre + post), np.int16)
            buf1 = np.asarray(osc.read_cal(1, wp - pre, pre + post), np.int16)
        finally:
            g.parar()
            self._desarmar()
        return dict(buf=buf, buf1=buf1, wp_trig=wp)

    def close(self):
        for paso in (self.g.parar, lambda: setattr(self.g, 'lazo', False), self._desarmar,
                     lambda: self.I.integration_reset_routes(self.ig)):
            try:
                paso()
            except Exception as e:                              # noqa: BLE001
                print(f'  (al cerrar: {type(e).__name__}: {e})')
        if self.ring is not None:
            self.ring.close()
        self.I.integration_close(self.ig)
        self.mt.close()
        self.O.osciloscope_close(self.osc)
        self.g.close()


class CapturaSimulada:
    """Capturas ideales desde el modelo, con desfases elegidos acá y que `analizar` no
    conoce: lo que una placa sin errores tendría que dar. En modo analógico, lo que
    vuelve por IN1 e IN2 sale del canal de juguete (`canal_analogico.CanalSimulado`)."""

    nombre = 'simulada'
    C0_RING = 123_457        # el reloj del ring arrancó antes que el generador
    D_RING = 4               # la muestra de la marca, respecto del pulso
    D_BRAM = 6               # la muestra de wp_trig, respecto del pulso

    def __init__(self, rutas, n_buf=8192, modo='digital', canal=None):
        if modo not in MODOS:
            raise ValueError(f'modo {modo!r}: uno de {MODOS}')
        self.n_buf, self.modo = n_buf, modo
        self.canal = canal if canal is not None else CA.CanalSimulado()
        self.gp = _modelo()

    def _entradas(self, t, lazo, idx):
        """(IN1, IN2) en los índices `idx` de la traza (negativos: el generador todavía
        apagado). Con el lazo, IN1 es la traza y IN2 el piso; sin él, las dos salen del
        canal, que se aplica a la traza entera con ceros antes (tiene memoria)."""
        idx = np.asarray(idx, np.int64)
        antes = int(max(0, -idx.min())) + 128
        x = np.concatenate([np.zeros(antes, np.int64), np.asarray(t['dat'], np.int64)])
        j = idx + antes
        if j.max() >= x.size:
            raise ValueError('la captura simulada se sale de la traza')
        if lazo:
            return x[j], self.canal.aplicar(np.zeros(x.size), 1)[j]
        return self.canal.aplicar(x, 0)[j], self.canal.aplicar(x, 1)[j]

    def ring_capturar(self, gen, tabla, pre, post, plazo_s):
        t = _traza(self.gp, gen, tabla, extra=post + BUSQUEDA + 10)
        acc = disparos_asg(t['trig'])
        ok = aceptados_captura(acc, muerto_ring(pre, post))
        ts = ok + self.C0_RING
        idx = (ok + self.D_RING - pre)[:, None] + np.arange(pre + post)
        if self.modo == 'digital':
            wave = _extender(t['dat'], idx).astype(np.int16)
        else:
            wave = self._entradas(t, False, idx)[0].astype(np.int16)
        cont = dict(ev_cnt=int(ok.size), drop_busy=int(acc.size - ok.size), drop_full=0)
        return dict(wave=wave, ts_hw=ts, seq=np.arange(ok.size, dtype=np.uint32),
                    contadores=cont,
                    gen_estado=dict(gen_cnt=int(t['trig'].size), terminado=True,
                                    desborde=bool(t['desborde'])))

    def bram_capturar(self, gen, tabla, pre, post, lazo=None):
        t = _traza(self.gp, gen, tabla, extra=post + BUSQUEDA + 10)
        t0 = int(t['trig'][0])
        idx = t0 + self.D_BRAM - pre + np.arange(pre + post)
        lazo = (self.modo == 'digital') if lazo is None else bool(lazo)
        in1, in2 = self._entradas(t, lazo, idx)
        return dict(buf=in1.astype(np.int16), buf1=in2.astype(np.int16), wp_trig=4321)

    def close(self):
        pass


def medir(a):
    os.makedirs(a.outdir, exist_ok=True)
    if a.simulada:
        cap = CapturaSimulada(a.rutas, modo=a.modo,
                              canal=CA.CanalSimulado.desde_texto(a.canal_sim, a.semilla))
    else:
        cap = CapturaPlaca(a.rutas, modo=a.modo)
    meta = dict(fecha=datetime.now().isoformat(timespec='seconds'), placa=cap.nombre,
                host=platform.node(), rutas=a.rutas, modo=a.modo, identidad=IDENTIDAD,
                args={k: v for k, v in vars(a).items() if k != 'func'})
    if a.simulada and a.modo == 'analogico':
        meta['canal_simulado'] = cap.canal.describir()
    analogico = a.modo == 'analogico'
    try:
        if analogico:
            d = capturar_canal(cap, a.semilla)
            np.savez_compressed(os.path.join(a.outdir, 'canal.npz'), **d)
            meta['canal'] = dict(casos=[(n, g, [int(v) for v in t])
                                        for n, g, t in casos_canal(a.semilla)],
                                 pre=PRE_CANAL, n=int(d['x'].size))
            print(f'[canal] piso y estímulo, con y sin el lazo: {d["x"].size} muestras',
                  flush=True)
        if 'ring' in a.rutas:
            gen, tabla = caso_ring(a)
            print(f'[ring] {a.n_ring} pulsos Poisson a {a.tasa_ring / 1e3:g} k/s, ventanas '
                  f'{a.pre_ring}+{a.post_ring}', flush=True)
            r = cap.ring_capturar(gen, tabla, a.pre_ring, a.post_ring,
                                  plazo_s=2.0 * a.n_ring / a.tasa_ring + 5.0)
            np.savez_compressed(os.path.join(a.outdir, 'ring.npz'), wave=r['wave'],
                                ts_hw=r['ts_hw'], seq=r['seq'])
            meta['ring'] = dict(gen=gen, tabla=[int(v) for v in tabla], pre=a.pre_ring,
                                post=a.post_ring, contadores=r['contadores'],
                                gen_estado=r['gen_estado'], leidos=int(r['ts_hw'].size))
            k = r['contadores']
            print(f'  {r["ts_hw"].size} ventanas; EV {k["ev_cnt"]}, DROP_BUSY '
                  f'{k["drop_busy"]}, DROP_FULL {k["drop_full"]}; GEN_CNT '
                  f'{r["gen_estado"]["gen_cnt"]}', flush=True)
        if 'bram' in a.rutas:
            meta['bram'] = []
            for i, (nombre, gen, tabla) in enumerate(casos_bram(a.semilla)):
                # En el analógico, cada caso dos veces: `buf` por el lazo (bit a bit
                # contra el modelo) e `y0`, `y1` sin él (IN1 e IN2).
                b = cap.bram_capturar(gen, tabla, a.pre_bram, a.post_bram,
                                      lazo=True if analogico else None)
                extra = {}
                if analogico:
                    y = cap.bram_capturar(gen, tabla, a.pre_bram, a.post_bram, lazo=False)
                    extra = dict(y0=y['buf'], y1=y['buf1'])
                np.savez_compressed(os.path.join(a.outdir, f'bram_{i}.npz'), buf=b['buf'],
                                    **extra)
                meta['bram'].append(dict(nombre=nombre, gen=gen,
                                         tabla=[int(v) for v in tabla], pre=a.pre_bram,
                                         post=a.post_bram, wp_trig=b['wp_trig']))
                print(f'[bram] {nombre}: {b["buf"].size} muestras, wp_trig {b["wp_trig"]}',
                      flush=True)
    finally:
        cap.close()
        with open(os.path.join(a.outdir, 'fidelidad.json'), 'w') as f:
            json.dump(meta, f, indent=1,
                      default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    print(f'  -> {a.outdir}/fidelidad.json')
    return 0


# =============================================================================
# analizar: contra el modelo, en la PC
# =============================================================================

def _modelo():
    mod = os.path.join(_RAIZ, '..', 'modulos', 'gen_eventos', 'modelos', 'python_model')
    sys.path.insert(0, os.path.abspath(mod))
    import gen_pulsos_model as gp
    return gp


def _traza(gp, gen, tabla, extra):
    """La traza del modelo hasta `extra` ciclos después del último pulso (con N) o del
    primero (sin fin, como en la BRAM)."""
    d = {k: int(gen[k]) for k in G.CLAVES_DISPAROS}
    n = d['n'] or 1
    tasa = G.tasa(**d)
    t_k = G.predecir(int(1.5 * n * FS_HZ / tasa) + 100_000, G.LAT_TRIG, n_max=n, **d)
    kw = {k: int(v) for k, v in gen.items() if k != 'salidas'}
    return gp.traza(int(t_k[-1]) + int(extra), [int(v) for v in tabla], **kw)


def _extender(x, idx):
    """x[idx], con 0 antes del arranque (el generador apagado da ceros por el lazo)
    y -1 de relleno después del final de la traza (no se compara: ver `_comparar`)."""
    x = np.asarray(x, np.int64)
    idx = np.asarray(idx, np.int64)
    out = np.where(idx < 0, 0, -(1 << 20))
    dentro = (idx >= 0) & (idx < x.size)
    out[dentro] = x[idx[dentro]]
    return out


def _alinear(capt, x, base, pre, busqueda=BUSQUEDA):
    """El desfase d en [−busqueda, busqueda] que hace capt[j] == x[base + d − pre + j]
    en más muestras. Devuelve (d, coincidencias)."""
    s = capt.shape[-1]
    mejor = (None, -1)
    for d in range(-busqueda, busqueda + 1):
        ref = _extender(x, base + d - pre + np.arange(s))
        n = int((np.asarray(capt, np.int64) == ref).sum())
        if n > mejor[1]:
            mejor = (d, n)
    return mejor


def _muestras_ring_analogico(wave, g, x, pre, canal, k_alinear=50):
    """Las ventanas de IN1 contra el FIR del canal aplicado al modelo: la alineación d
    es la que minimiza el residuo en las primeras `k_alinear` ventanas."""
    s = wave.shape[1]
    antes = BUSQUEDA + pre + 64
    p = CA.predecir_canal(np.concatenate([np.zeros(antes), np.asarray(x, float)]), canal)
    w = wave.astype(float)

    def tomar(gs, d):
        j = (gs + d - pre)[:, None] + np.arange(s) + antes
        ok = (j >= 0) & (j < p.size)
        return np.where(ok, p[np.clip(j, 0, p.size - 1)], np.nan)

    k = min(k_alinear, g.size)
    err = []
    for d in range(-BUSQUEDA, BUSQUEDA + 1):
        r = np.abs(w[:k] - tomar(g[:k], d))
        err.append(np.nanmean(r) if np.isfinite(r).any() else np.inf)
    d = int(np.argmin(err)) - BUSQUEDA
    pred = tomar(g, d)
    res = CA.residuo(w.ravel(), pred.ravel(), canal['ruido'], mascara=True)
    m = res.pop('_mascara', np.zeros(w.size, bool)).reshape(w.shape)
    return dict(d=d, muestras=int(np.isfinite(pred).sum()), residuo=res,
                ventanas_con_error=int(m.any(axis=1).sum()))


def analizar_ring(outdir, m, gp, canal=None):
    pre, post = m['pre'], m['post']
    s = pre + post
    z = np.load(os.path.join(outdir, 'ring.npz'))
    wave, ts = z['wave'].astype(np.int64), z['ts_hw'].astype(np.int64)
    t = _traza(gp, m['gen'], m['tabla'], extra=post + BUSQUEDA + 10)
    x, trig = t['dat'], t['trig'].astype(np.int64)
    acc = disparos_asg(trig)
    out = dict(ventanas=int(ts.size), pulsos=int(trig.size), disparos_asg=int(acc.size),
               perdidos_rearme_asg=int(trig.size - acc.size))
    k, e = m['contadores'], m['gen_estado']
    out['gen_cnt_ok'] = e['gen_cnt'] == m['gen']['n'] and bool(e['terminado'])
    out['cuenta_cierra'] = k['ev_cnt'] + k['drop_busy'] + k['drop_full'] == acc.size
    out['leidos_todos'] = ts.size == k['ev_cnt']
    if ts.size == 0:
        out['veredicto'] = 'sin ventanas'
        return out
    # La primera ventana es el primer disparo: el ring estaba vacío.
    c0 = int(ts[0] - acc[0])
    g = ts - c0
    pos = np.searchsorted(acc, g)
    es = (pos < acc.size) & (acc[np.minimum(pos, acc.size - 1)] == g)
    out.update(c0=c0, marcas_de_un_pulso=int(es.sum()), marcas_fuera=int((~es).sum()))
    # Descartes por captura ocupada, contra el modelo (exacto sin DROP_FULL).
    ok = aceptados_captura(acc, muerto_ring(pre, post))
    out['drop_busy_modelo'] = int(acc.size - ok.size)
    out['drop_busy_igual'] = (k['drop_full'] != 0 or
                              out['drop_busy_modelo'] == k['drop_busy'])
    out['marcas_iguales_al_modelo'] = (k['drop_full'] == 0 and np.array_equal(g, ok))
    if canal is not None:
        out.update(_muestras_ring_analogico(wave, g, x, pre, canal))
        out['veredicto'] = ('fiel' if out['residuo'].get('fuera', 1) == 0
                            and out['marcas_fuera'] == 0 and out['cuenta_cierra']
                            and out['drop_busy_igual'] else 'NO FIEL')
        return out
    # La alineación de las muestras con la primera ventana, y después todas.
    d, _ = _alinear(wave[0], x, int(g[0]), pre)
    idx = (g + d - pre)[:, None] + np.arange(s)
    ref = _extender(x, idx)
    valido = ref > -(1 << 20)
    dist = (wave != ref) & valido
    out.update(d=int(d), muestras=int(valido.sum()), muestras_distintas=int(dist.sum()),
               ventanas_con_error=int(dist.any(axis=1).sum()),
               dif_max=int(np.abs(np.where(valido, wave - ref, 0)).max()),
               saturadas=int(((ref == G.AMP_MAX) | (ref == G.AMP_MIN)).sum()),
               negativas=int((ref < 0).sum()))
    if dist.any():
        i, j = np.argwhere(dist)[0]
        out['primer_error'] = dict(ventana=int(i), muestra=int(j), capturada=int(wave[i, j]),
                                   modelo=int(ref[i, j]))
    out['veredicto'] = ('fiel' if out['muestras_distintas'] == 0 and out['marcas_fuera'] == 0
                        and out['cuenta_cierra'] and out['drop_busy_igual'] else 'NO FIEL')
    return out


def analizar_bram(outdir, casos, gp, canal=None):
    out = []
    for i, c in enumerate(casos):
        pre, post = c['pre'], c['post']
        z = np.load(os.path.join(outdir, f'bram_{i}.npz'))
        buf = z['buf'].astype(np.int64)
        t = _traza(gp, c['gen'], c['tabla'], extra=post + BUSQUEDA + 10)
        x, t0 = t['dat'], int(t['trig'][0])
        d, _ = _alinear(buf, x, t0, pre)
        ref = _extender(x, t0 + d - pre + np.arange(buf.size))
        valido = ref > -(1 << 20)
        dist = (buf != ref) & valido
        antes = t0 + d - pre + np.arange(buf.size) < 0
        r = dict(nombre=c['nombre'], d=int(d), muestras=int(valido.sum()),
                 muestras_distintas=int(dist.sum()),
                 ceros_antes_del_arranque=int(antes.sum()),
                 saturadas=int(((ref == G.AMP_MAX) | (ref == G.AMP_MIN)).sum()),
                 dif_max=int(np.abs(np.where(valido, buf - ref, 0)).max()))
        if dist.any():
            j = int(np.flatnonzero(dist)[0])
            r['primer_error'] = dict(muestra=j, capturada=int(buf[j]), modelo=int(ref[j]))
        if canal is not None and 'y0' in z:
            # IN1 contra el FIR aplicado a lo del lazo: el mismo instante en las dos (el
            # disparo es digital), y antes del arranque el lazo da ceros, así que al FIR
            # no le falta historia.
            pred = CA.predecir_canal(buf, canal)
            r['analogico'] = CA.residuo(z['y0'], pred, canal['ruido'])
        out.append(r)
    return out


def analizar(a):
    with open(os.path.join(a.outdir, 'fidelidad.json')) as f:
        m = json.load(f)
    gp = _modelo()
    modo = m.get('modo', 'digital')
    res = dict(captura=m.get('placa'), fecha_captura=m.get('fecha'), modo=modo,
               fecha=datetime.now().isoformat(timespec='seconds'))
    canal = None
    if modo == 'analogico':
        z = np.load(os.path.join(a.outdir, 'canal.npz'))
        canal = res['canal'] = CA.caracterizar(z['x'], z['y0'], z['y1'], z['piso0'],
                                               z['piso1'])
        print('[canal]\n' + texto_canal(canal))
        p = res['canal_problema'] = CA.problema(canal)
        if p:
            print(f'  SIN CANAL: {p}')
        elif canal['no_causal'] > 0.01:
            print('  OJO: el FIR tiene energía antes del pulso: las capturas con y sin el '
                  'lazo no estaban alineadas')
    if 'ring' in m and canal is not None:
        r = res['ring'] = analizar_ring(a.outdir, m['ring'], gp, canal)
        q = r.get('residuo', {})
        print(f'[ring] {r["veredicto"]}: {r["ventanas"]} ventanas, {r.get("muestras", 0)} '
              f'muestras contra el FIR del canal: residuo {q.get("rms", 0):.2f} cuentas rms '
              f'(máx {q.get("max", 0):.1f}), {q.get("fuera", "?")} pasan {q.get("umbral", 0):.1f}'
              f' ({r.get("ventanas_con_error", 0)} ventanas); la muestra a d = {r.get("d")}')
        print(f'  marcas: {r.get("marcas_de_un_pulso", 0)} a distancia constante de su '
              f'pulso, {r.get("marcas_fuera", 0)} que no; DROP_BUSY '
              f'{m["ring"]["contadores"]["drop_busy"]} contra {r.get("drop_busy_modelo")} del '
              f'modelo; la cuenta {"cierra" if r["cuenta_cierra"] else "NO cierra"}')
    elif 'ring' in m:
        r = res['ring'] = analizar_ring(a.outdir, m['ring'], gp)
        print(f'[ring] {r["veredicto"]}: {r["ventanas"]} ventanas, '
              f'{r.get("muestras", 0)} muestras, {r.get("muestras_distintas", 0)} distintas '
              f'({r.get("ventanas_con_error", 0)} ventanas con error, dif. máx '
              f'{r.get("dif_max", 0)}); {r.get("saturadas", 0)} saturadas y '
              f'{r.get("negativas", 0)} negativas en el modelo')
        print(f'  marcas: {r.get("marcas_de_un_pulso", 0)} a distancia constante de su '
              f'pulso (c0 = {r.get("c0")}, la muestra a d = {r.get("d")}), '
              f'{r.get("marcas_fuera", 0)} que no; DROP_BUSY {m["ring"]["contadores"]["drop_busy"]}'
              f' contra {r.get("drop_busy_modelo")} del modelo; la cuenta '
              f'{"cierra" if r["cuenta_cierra"] else "NO cierra"} con los '
              f'{r["disparos_asg"]} disparos del ASG ({r["perdidos_rearme_asg"]} pulsos a '
              f'menos de 3 ciclos)')
    if 'bram' in m:
        res['bram'] = analizar_bram(a.outdir, m['bram'], gp, canal)
        ds = {b['d'] for b in res['bram']}
        for b in res['bram']:
            print(f'[bram] {b["nombre"]:10s}: {b["muestras_distintas"]} de {b["muestras"]} '
                  f'distintas (dif. máx {b["dif_max"]}), disparo a d = {b["d"]}, '
                  f'{b["ceros_antes_del_arranque"]} ceros antes del arranque, '
                  f'{b["saturadas"]} saturadas' + (' (por el lazo)' if canal else ''))
            q = b.get('analogico')
            if q:
                print(f'  {"":10s}  IN1 contra el FIR: residuo {q["rms"]:.2f} cuentas rms '
                      f'(media {q["media"]:+.2f}, máx {q["max"]:.1f}), {q["fuera"]} de '
                      f'{q["muestras"]} pasan {q["umbral"]:.1f}')
        res['bram_d_constante'] = len(ds) == 1
        print(f'  la posición del disparo en el buffer es '
              f'{"la misma" if len(ds) == 1 else "DISTINTA"} en los {len(res["bram"])} casos')
    fiel = (not res.get('canal_problema')
            and res.get('ring', {}).get('veredicto', 'fiel') == 'fiel'
            and all(b['muestras_distintas'] == 0 for b in res.get('bram', []))
            and all(b.get('analogico', {}).get('fuera', 0) == 0 for b in res.get('bram', []))
            and res.get('bram_d_constante', True))
    res['veredicto'] = 'fiel' if fiel else 'NO FIEL'
    with open(os.path.join(a.outdir, 'analisis.json'), 'w') as f:
        json.dump(res, f, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    print(f'\n{res["veredicto"].upper()}  -> {a.outdir}/analisis.json')
    return 0 if fiel else 1


# =============================================================================

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='paso', required=True)
    m = sub.add_parser('medir', help='captura (en la placa, o --simulada)')
    m.add_argument('outdir')
    m.add_argument('--rutas', default='ring,bram',
                   type=lambda s: [x for x in s.split(',') if x])
    m.add_argument('--simulada', action='store_true',
                   help='capturas ideales desde el modelo, en la PC')
    m.add_argument('--modo', default='digital', choices=MODOS,
                   help='digital: el lazo; analogico: OUT1 → coaxial → IN1')
    m.add_argument('--canal-sim', default='',
                   help="el canal de juguete de --simulada --modo analogico, p. ej. "
                        "'ganancia=0.97,offset=-12,lat=9,polo=0.45,ruido=1.3'")
    m.add_argument('--tasa-ring', type=float, default=50e3)
    m.add_argument('--n-ring', type=int, default=4000)
    m.add_argument('--pre-ring', type=int, default=32)
    m.add_argument('--post-ring', type=int, default=480)
    m.add_argument('--pre-bram', type=int, default=4000)
    m.add_argument('--post-bram', type=int, default=4000)
    m.add_argument('--semilla', type=int, default=1)
    z = sub.add_parser('analizar', help='compara contra el modelo (en la PC)')
    z.add_argument('outdir')
    a = ap.parse_args(argv)
    if a.paso == 'medir':
        for r in a.rutas:
            if r not in RUTAS:
                ap.error(f'ruta {r!r}: una de {RUTAS}')
    return a


def main(argv=None):
    a = parse_args(argv)
    return medir(a) if a.paso == 'medir' else analizar(a)


if __name__ == '__main__':
    sys.exit(main())
