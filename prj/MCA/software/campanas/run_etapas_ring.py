#!/usr/bin/env python3
"""Las etapas del event_ring: a qué tasa anda, con el generador de eventos de la FPGA.

Es la campaña de docs/event_ring/generador.md §6. El estímulo es el generador del ring
(`gen_eventos`): los disparos salen de un motor conocido y cada slot trae, en lugar del
dato, un patrón que dice qué disparo es. No usa el Rigol ni el multitrigger: la
pérdida que se mide es la del ring y no la del estímulo.

Cada punto es una etapa, una ventana, un modo del motor y una tasa:

  A      el lector sólo devuelve los créditos (`LectorRing.medir('creditos')`): lo que
         se pierde, lo pierden la PL, el AXI o la DDR.
  copia  la copia de cada slot, sin mirarla: separa lo que cuesta copiar de lo que
         cuesta verificar. No está en §6; va si se la pide.
  B      la copia y la verificación de cada slot, en C (`medir('verificar')`): el
         lector.
  C      la sesión entera (`OR.AdquisicionRing`: `RingSource` con el generador y
         `AcquisitionSession`, npz o LH5) escribiendo en `--destino`. Los archivos se
         verifican después, en numpy, con las mismas reglas que B, y se borran (salvo
         `--guardar`). Con `--red HOST` la sesión corre en el servidor de la placa (las
         ops `ring.*`) y este script, en la PC: `--destino` es un directorio de la
         placa dentro de un montaje de red, y `--destino-pc`, el mismo visto desde acá.

El modo periódico da el techo; el aleatorio, la pérdida contra el modelo.

**Contra qué se compara cada punto** (lo que no cierra es una anomalía y el script sale
con 1; un descarte que el modelo predice no lo es):

- **La cuenta.** `EV_CNT + DROP_BUSY + DROP_FULL = GEN_CNT = N`, y el lector consumió
  los EV_CNT.
- **DROP_BUSY contra el tiempo muerto de la captura.** Un disparo que cae a menos de
  `2·(pre + post) + 3` ciclos de la marca del último aceptado se descarta. Con las
  marcas del motor (`predecir`) el número es exacto mientras no haya DROP_FULL (un
  descarte por lleno no abre ventana y cambia la cadena). Es el `2·S + 2` de la
  simulación (logica_de_captura_y_axi.md §2.4) más uno de la marca. Se ajustó en la
  placa: el caso aleatorio a 3 MHz del 2026-11-09 dio 59 762, y `2·S + 3` da 59 762
  exactos (con `2·S + 2`, 59 373).
- **DROP_FULL contra el techo del writer de la simulación**
  (`docs/event_ring/figuras/tiempos/geometrias.txt`, en `TECHO_SIM`). Con trenes
  periódicos el RTL no pierde desde `writer` ciclos entre disparos y sí a `writer − 2`.
  Por defecto el barrido periódico agrega esos dos períodos a cada ventana de la tabla.
- **B y C: cero errores.** La cabecera, la marca `{1, k}`, k y ts que avanzan, la
  marca exacta del motor y cada muestra desde el arranque igual al patrón.

**El criterio de §6** (cero descartes y cero errores en 10⁸ eventos o más, también con
el ARM ocupado) es una corrida aparte, larga, en el punto elegido: `--n 1e8 --seg-max 0`,
con `--carga 2` para ocupar los dos núcleos. Vale para A y B: en C el punto entero queda
en el disco hasta verificarlo, y el que no entra en `--destino` se saltea.

Uso (en la Pitaya, con el bitstream del ring con generador, 78e26188 o posterior):

    python3 campanas/run_etapas_ring.py <outdir> [--etapas A,B] [--modos periodico,aleatorio]
        [--ventanas 8+24,16+479@12] [--tasas 1e4,1e5,1e6] [--n 200000] [--seg-max 2]
        [--formato npz|lh5] [--destino /dev/shm/etapas] [--carga 2]

La etapa C por la red (en la PC, con `mca_server.py` corriendo en la placa con el
bitstream del ring y el directorio de la PC montado en la placa, `make placa-montar-red`):

    python3 campanas/run_etapas_ring.py <outdir> --etapas C --red <ip-placa>
        --destino /mnt/pc/etapas --destino-pc ~/pitaya_red/etapas

Deja `<outdir>/etapas_ring.json` (se reescribe después de cada punto, así una corrida
cortada conserva lo medido) y la tabla del resumen. `make campana-etapas-ring` desde
`software/`.
"""
import argparse
import bisect
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

import API.generadores as G                                          # noqa: E402
import API.osciloscope_ring as OR                                    # noqa: E402
from API import _libmca                                              # noqa: E402
from API.osciloscope_store import (archivos_de_corrida,             # noqa: E402
                                   bytes_per_event, load_chunk)
from API.osciloscope_store.storage import MIN_FREE_MB, free_space_mb  # noqa: E402

FS_HZ = 125e6
IDENTIDAD = {'gain': 32768, 'base': 32768, 'offset': 0}

# El tiempo muerto de la captura, desde la marca del disparo aceptado: 2·S + 2 ciclos
# en la simulación, más 1 (ajustado en la placa, ver la cabecera).
MUERTO_EXTRA = 3

# La simulación del RTL (docs/event_ring/figuras/tiempos/geometrias.txt): por ventana
# (pre, post), el slot_shift y los ciclos por evento de la captura y del writer.
TECHO_SIM = {
    (8, 24): (8, 66, 88),
    (16, 112): (10, 258, 328),
    (16, 240): (11, 514, 648),
    (16, 479): (12, 992, 1264),
    (16, 998): (12, 2030, 2041),
    (32, 992): (13, 2050, 2568),
}

# Etapa -> modo de LectorRing.medir (None: la sesión entera).
ETAPAS = {'A': 'creditos', 'copia': 'copia', 'B': 'verificar', 'C': None}
MODOS = ('periodico', 'aleatorio')
ERRORES = ('err_cabecera', 'err_marca', 'err_k', 'err_ts', 'err_patron')
ERRORES_ARCHIVO = ('err_seq', 'err_marca', 'err_k', 'err_ts', 'err_patron')


# =============================================================================
# El modelo
# =============================================================================

def muerto_captura(pre, post):
    """Ciclos desde la marca de un disparo aceptado hasta que la captura acepta otro."""
    return OR.N_CH_HW * (pre + post) + MUERTO_EXTRA


def descartes_captura(ts, muerto):
    """Los disparos de `ts` (marcas en orden) que caen con la captura ocupada: el
    tiempo muerto no paralizable de `muerto` ciclos (uno que se descarta no lo
    extiende)."""
    ts = [int(t) for t in ts]
    n, i, aceptados = len(ts), 0, 0
    while i < n:
        aceptados += 1
        i = bisect.bisect_left(ts, ts[i] + muerto, i + 1)
    return n - aceptados


def marcas_periodico(k, periodo):
    """La marca del disparo k en el modo periódico."""
    return (np.asarray(k, np.int64) + 1) * max(int(periodo), 2) - 1 + OR.GEN_LAT_TS


def modelo(d, pre, post, n_max=2_000_000, ciclos_max=1e9):
    """`(busy, marcas)`: los DROP_BUSY que predice el tiempo muerto de la captura y las
    marcas del motor (None en el periódico, que tiene la fórmula, o si predecirlas
    cuesta más que `n_max` disparos o `ciclos_max` ciclos: entonces busy es None en
    el aleatorio)."""
    muerto, n = muerto_captura(pre, post), int(d['n'])
    if not d['aleatorio']:
        per = max(int(d['periodo']), 2)
        paso = -(-muerto // per)                  # de cuántos en cuántos acepta
        return n - -(-n // paso), None
    ciclos = n * FS_HZ / G.tasa(**d)
    if n > n_max or ciclos > ciclos_max:
        return None, None
    for f in (1.3, 3.0):
        marcas = G.predecir(int(f * ciclos) + 10_000, OR.GEN_LAT_TS, n_max=n, **d)
        if marcas.size == n:
            return descartes_captura(marcas, muerto), marcas
    raise RuntimeError(f'predecir dio {marcas.size} disparos de {n}')


# =============================================================================
# La verificación de los archivos (etapa C)
# =============================================================================

def _cero_verif():
    return dict(eventos=0, err_seq=0, err_marca=0, err_k=0, err_ts=0, err_patron=0,
                muestras_malas=0, k_saltos=0, k_ultimo=-1, primer_error_seq=None)


def verificar_eventos(v, cols, d, pre, post, marcas=None, bloque=256):
    """Verifica en numpy un lote de eventos del generador leídos en orden, como
    `medir('verificar')` en C, y acumula en `v` (de `_cero_verif`). `cols`: `ts_hw`,
    `snap`, `seq` y `wave` (eventos, canal, muestra) en cuentas con la calibración
    identidad. `marcas`, las del motor en el modo aleatorio (de `modelo`); sin
    ellas, se exige sólo que k avance y que haya `dt_min` ciclos por cada k."""
    ts = np.asarray(cols['ts_hw'], np.int64)
    m = ts.size
    if m == 0:
        return v
    s = pre + post
    snap = np.asarray(cols['snap'], np.int64)
    seq = np.asarray(cols['seq'], np.int64)
    k16 = snap & 0xFFFF
    k_prev = v['k_ultimo']
    ts_prev = v.get('_ts_ultimo', -1)
    tsp = np.concatenate(([ts_prev], ts[:-1]))

    e_seq = seq != ((v['eventos'] + np.arange(m)) & 0xFFFFFFFF)
    e_marca = (snap & OR.GEN_SNAP_MARCA) == 0
    e_ts = ts <= tsp
    if not d['aleatorio']:
        per = max(int(d['periodo']), 2)
        q, r = np.divmod(ts + 1 - OR.GEN_LAT_TS, per)
        k = q - 1
        e_ts |= (r != 0) | (k < 0)
    elif marcas is not None:
        k = np.searchsorted(marcas, ts)
        e_ts |= marcas[np.minimum(k, marcas.size - 1)] != ts
    else:
        # La vuelta de 16 bits, como en C: k avanza lo mínimo que da su k16.
        prev16 = np.concatenate(([k_prev], k16[:-1]))
        k = k_prev + np.cumsum((k16 - prev16) & 0xFFFF)
    kp = np.concatenate(([k_prev], k[:-1]))
    e_k = ((k & 0xFFFF) != k16) | (k <= kp)
    if d['n']:
        e_k |= k >= int(d['n'])
    if d['aleatorio'] and marcas is None:
        dt = max(int(d['dt_min']) & 0xFFFF, 2)
        hay = kp >= 0
        e_ts |= hay & (ts - tsp < dt * (k - kp))
        e_ts |= ts < OR.GEN_LAT_TS + dt * k

    # El patrón, de a bloques: con ventanas de 1024 muestras un chunk entero en int64
    # no entra en la RAM de la placa. Las muestras de antes del arranque no se miran.
    j = np.arange(s)
    malas = np.zeros(m, np.int64)
    w = cols['wave']
    for i in range(0, m, bloque):
        t = ts[i:i + bloque]
        dif = w[i:i + bloque] != OR.patron_gen(t, pre, s)
        dif &= ((t[:, None] - pre + j) >= 0)[:, None, :]
        malas[i:i + bloque] = dif.sum(axis=(1, 2))
    e_pat = malas > 0

    v['eventos'] += m
    for nombre, e in (('err_seq', e_seq), ('err_marca', e_marca), ('err_k', e_k),
                      ('err_ts', e_ts), ('err_patron', e_pat)):
        v[nombre] += int(e.sum())
    v['muestras_malas'] += int(malas.sum())
    malo = e_seq | e_marca | e_k | e_ts | e_pat
    if v['primer_error_seq'] is None and malo.any():
        v['primer_error_seq'] = int(seq[np.argmax(malo)])
    v['k_saltos'] += int(np.clip(k - kp - 1, 0, None).sum())
    v['k_ultimo'] = int(k[-1])
    v['_ts_ultimo'] = int(ts[-1])
    return v


def verificar_archivos(run_dir, d, pre, post, marcas=None):
    """`verificar_eventos` sobre los archivos de una corrida, en orden."""
    v = _cero_verif()
    for path in archivos_de_corrida(run_dir):
        a, _ = load_chunk(path)
        verificar_eventos(v, a, d, pre, post, marcas)
    v.pop('_ts_ultimo', None)
    v['errores'] = sum(v[c] for c in ERRORES_ARCHIVO)
    return v


# =============================================================================
# Las corridas
# =============================================================================

# Para un ring que `parar` no pudo parar (lleno, sin créditos): vive en la API, porque
# también lo necesitan `RingSource.close()` y el servidor.
destrabar = OR.destrabar


def correr_medida(ring, d, pre, post, modo, plazo_s, slot_shift=None, sondeo_s=0.05):
    """Etapas A, copia y B: el generador con `d`, el lector en `modo`, hasta que el
    motor termina y se consumió todo lo escrito (o `plazo_s`). Devuelve la medida, el
    estado del generador y los contadores del ring, leídos con el ring parado, y si
    venció el plazo."""
    lector = OR.LectorRing(ring, pre, post, OR.N_CH_HW, [IDENTIDAD] * OR.N_CH_HW,
                           slot_shift=slot_shift)
    lector.configurar()
    n_slots = lector.estado['n_slots']
    ring.gen_configurar(d, patron=True)
    ring.correr()
    vencido, fin_visto = False, False
    t_fin = time.monotonic() + plazo_s
    try:
        while True:
            m = lector.medir(modo, time.perf_counter_ns() + int(sondeo_s * 1e9),
                             disparos=d)
            e, k = ring.gen_estado(), ring.contadores()
            # Una vuelta más después de ver el fin: la última ventana puede estar
            # todavía en vuelo cuando el motor dice que terminó.
            if fin_visto and m['eventos'] == k['ev_cnt']:
                break
            fin_visto = e['terminado']
            if time.monotonic() > t_fin:
                vencido = True
                break
    finally:
        try:
            ring.parar()             # WR_SLOT vuelve a 0; los contadores quedan
        except TimeoutError:
            destrabar(ring, lector)
            vencido = True
        e, k = ring.gen_estado(), ring.contadores()
        ring.gen_apagar()
    return lector.medida, e, k, n_slots, vencido


class AdqRemota:
    """Una adquisición del ring por el servidor (las ops `ring.*`): lo mismo que
    `OR.AdquisicionRing`, del otro lado del socket. `h` es un `MCARemote`."""

    def __init__(self, h, **kw):
        self.h, self.kw = h, kw

    def iniciar(self):
        return self.h.ring_iniciar(**self.kw)

    def estado(self):
        return self.h.ring_estado()

    def parar(self):
        return self.h.ring_parar()


def _juntar(*errores):
    """Los errores, una vez cada uno: `parar` repite los que ya vio el sondeo."""
    vistos = []
    for e in errores:
        for parte in (e or '').split('; '):
            if parte and parte not in vistos:
                vistos.append(parte)
    return '; '.join(vistos) or None


def correr_sesion(adq, plazo_s, sondeo_s=0.05):
    """Etapa C: la sesión entera con el generador, hasta que el motor termina y la
    sesión leyó todo lo que el ring escribió (o `plazo_s`). `adq` tiene `iniciar`,
    `estado` y `parar`: una `OR.AdquisicionRing` en esta máquina, o una `AdqRemota`
    por el servidor; el criterio de fin es el mismo. Devuelve las estadísticas de la
    sesión, los contadores finales (con el ring parado), los slots del ring, si venció
    el plazo, el error y el sistema de archivos donde escribió."""
    vencido, error, fin_visto = False, None, False
    t_fin = time.monotonic() + plazo_s
    info = adq.iniciar()
    try:
        while True:
            time.sleep(sondeo_s)
            e = adq.estado()
            if e['motivo'] is not None:      # se cayó un hilo, disco lleno, o terminó
                error = e['error'] or f'la sesión terminó sola ({e["motivo"]})'
                break
            if fin_visto and e['stats']['n_read'] >= e['hw']['hw_ev_cnt']:
                break
            fin_visto = e['hw']['hw_gen_terminado']
            if time.monotonic() > t_fin:
                vencido = True
                break
    finally:
        f = adq.parar()
    return (f['stats'], f['hw_final'], f['n_slots'], vencido, _juntar(error, f['error']),
            info.get('fs'))


def ocupar_cpu(n):
    """`n` procesos que ocupan un núcleo cada uno, para medir con el ARM ocupado."""
    return [subprocess.Popen([sys.executable, '-c', 'while True: pass'])
            for _ in range(n)]


def soltar_cpu(procs):
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


# =============================================================================
# Un punto
# =============================================================================

def disparos_punto(modo, tasa, n, dt_min=5, semilla=7):
    if modo == 'periodico':
        return G.disparos(tasa=tasa, n=n)
    return G.disparos(aleatorio=True, tasa=tasa, dt_min=dt_min, n=n, semilla=semilla)


def medir_punto(ring, etapa, pre, post, slot_shift, modo, tasa, a, destino):
    """Corre un punto y devuelve su fila: lo medido, el modelo y las anomalías."""
    n = a.n if a.seg_max <= 0 else min(a.n, max(a.n_min, int(tasa * a.seg_max)))
    d = disparos_punto(modo, tasa, n, a.dt_min, a.semilla)
    tasa_real = G.tasa(**d)
    busy_pred, marcas = modelo(d, pre, post, a.n_modelo_max)
    plazo = 1.5 * n / tasa_real + a.plazo_extra
    fila = dict(etapa=etapa, pre=pre, post=post, muestras=pre + post,
                slot_shift=slot_shift,
                slot_bytes=OR.geometria(pre, post, slot_shift=slot_shift)['slot_bytes'],
                modo=modo, tasa_pedida=float(tasa), tasa=float(tasa_real), n=int(n),
                disparos={c: int(v) for c, v in d.items()}, carga=a.carga,
                muerto_captura=muerto_captura(pre, post),
                techo_captura_hz=FS_HZ / muerto_captura(pre, post))
    sim = TECHO_SIM.get((pre, post))
    fila['techo_writer_sim_hz'] = (FS_HZ / sim[2] if sim and sim[0] == slot_shift
                                   else None)

    t0 = time.monotonic()
    if ETAPAS[etapa] is not None:
        m, e, k, n_slots, vencido = correr_medida(ring, d, pre, post, ETAPAS[etapa],
                                                  plazo, slot_shift)
        dur = max(m['t1_ns'] - m['t0_ns'], 1) * 1e-9
        fila.update(consumidos=m['eventos'], bytes=m['bytes'], dur_s=dur,
                    tasa_consumo=m['eventos'] / dur,
                    trabajo=m['trabajo_ns'] * 1e-9 / dur,
                    ocupacion_max=m['ocupacion_max'], sondeos=m['sondeos'],
                    bloques=m['bloques'], descartados_leidos=m['descartados'])
        if etapa == 'B':
            fila.update({c: m[c] for c in ERRORES + ('muestras_malas', 'k_saltos',
                                                     'k_ultimo', 'primer_error_seq')})
            fila['errores'] = m['errores']
        gen_cnt, terminado = e['gen_cnt'], e['terminado']
        ev, busy, full = k['ev_cnt'], k['drop_busy'], k['drop_full']
    else:
        # Todo el punto queda en el disco hasta verificarlo: 10⁸ ventanas de 32
        # muestras son unos 15 GB, más de lo que entra en la SD o en tmpfs.
        # Lo que se escribe como mucho: los N menos los que la captura descarta seguro.
        escritos = n - busy_pred if busy_pred is not None else n
        mb = escritos * bytes_per_event(OR.N_CH_HW, pre + post,
                                        OR.RingSource.scalar_fields, np.int16) / 2 ** 20
        # `destino` es donde escribe la sesión; `local`, el mismo directorio visto desde
        # acá. Por la red son dos caminos, el de la placa y el de la PC: el lugar libre
        # se mide, los archivos se verifican y se borran en el de la PC.
        local = a.destino_pc if a.red else destino
        os.makedirs(local, exist_ok=True)
        libre = free_space_mb(local)
        if mb > libre - a.margen_mb:
            raise ValueError(f'la etapa C escribiría hasta {mb:.0f} MB y en {local} '
                             f'hay {libre:.0f} MB libres, con {a.margen_mb:.0f} de margen: '
                             'bajar --n o --margen-mb, o cambiar --destino')
        nombre = f'c_{pre}_{post}_{modo}_{int(tasa)}'
        run_dir = os.path.join(local, nombre)
        shutil.rmtree(run_dir, ignore_errors=True)
        kw = dict(run_dir=os.path.join(destino if a.red else os.path.abspath(destino),
                                       nombre),
                  pre=pre, post=post, n_ch=OR.N_CH_HW, slot_shift=slot_shift,
                  generador=d, calib=[IDENTIDAD] * OR.N_CH_HW, formato=a.formato,
                  capacity=a.chunk, ram_mb=a.ram_mb, margen_mb=a.margen_mb,
                  meta={'test': 'etapas_ring', 'etapa': 'C'})
        adq = AdqRemota(ring, **kw) if a.red else OR.AdquisicionRing(ring, **kw)
        st, fin, n_slots, vencido, error, fs = correr_sesion(adq, plazo)
        fin = fin or {}
        dur = st.get('duration_s') or 0.0
        fila.update(consumidos=st['n_read'], escritos=st['n_written'],
                    chunks=st['chunks'], dur_s=dur,
                    tasa_consumo=st['n_read'] / dur if dur else None,
                    formato=a.formato, destino=destino, fs=fs, error_sesion=error)
        gen_cnt, terminado = fin.get('hw_gen_cnt', 0), fin.get('hw_gen_terminado', False)
        ev, busy, full = (fin.get('hw_ev_cnt', 0), fin.get('hw_drop_busy', 0),
                          fin.get('hw_drop_full', 0))
        if a.verificar_archivos:
            # Sin err_cabecera: el archivo no guarda la cabecera del slot.
            v = verificar_archivos(run_dir, d, pre, post, marcas)
            fila.update({c: v[c] for c in ERRORES_ARCHIVO + ('muestras_malas', 'k_saltos',
                                                             'k_ultimo',
                                                             'primer_error_seq')})
            fila['errores'] = v['errores']
            fila['eventos_en_archivos'] = v['eventos']
        if not a.guardar:
            shutil.rmtree(run_dir, ignore_errors=True)
    fila.update(n_slots=n_slots, vencido=vencido, t_punto_s=time.monotonic() - t0,
                gen_cnt=int(gen_cnt), terminado=bool(terminado), ev_cnt=int(ev),
                drop_busy=int(busy), drop_full=int(full), busy_predicho=busy_pred)
    fila['anomalias'] = anomalias(fila)
    fila['pasa'] = not fila['anomalias']
    fila['sin_perdidas'] = fila['pasa'] and busy + full == 0
    return fila


def anomalias(f):
    """Lo que no cierra en un punto. Un DROP_FULL no es anomalía: es lo que se mide
    (dónde se satura cada etapa)."""
    out = []
    perd = f['drop_busy'] + f['drop_full']
    if f['vencido']:
        out.append('venció el plazo')
    if not f['terminado'] or f['gen_cnt'] != f['n']:
        out.append('el generador no llegó a N')
    if f['ev_cnt'] + perd != f['gen_cnt']:
        out.append('EV_CNT + descartes != GEN_CNT')
    if f['consumidos'] != f['ev_cnt']:
        out.append('no se consumió todo lo escrito')
    if f.get('escritos') is not None and f['escritos'] != f['ev_cnt']:
        out.append('el escritor no guardó todo lo escrito')
    if f.get('eventos_en_archivos') is not None and f['eventos_en_archivos'] != f['ev_cnt']:
        out.append('los archivos no tienen todo lo escrito')
    if f.get('errores'):
        out.append('errores en los slots')
    if f.get('error_sesion'):
        out.append('se cayó un hilo de la sesión')
    if (f['busy_predicho'] is not None and f['drop_full'] == 0
            and f['drop_busy'] != f['busy_predicho']):
        out.append('DROP_BUSY distinto del tiempo muerto de la captura')
    if f.get('k_ultimo') is not None and f.get('errores') == 0 and f['k_ultimo'] >= 0:
        if f['k_saltos'] + (f['gen_cnt'] - 1 - f['k_ultimo']) != perd:
            out.append('los k que faltan no son los descartados')
    return out


# =============================================================================
# El barrido
# =============================================================================

def parse_ventanas(txt):
    """'8+24,16+479@12' -> [(8, 24, None), (16, 479, 12)]."""
    out = []
    for v in txt.split(','):
        v, _, sh = v.strip().partition('@')
        pre, post = (int(x) for x in v.split('+'))
        out.append((pre, post, int(sh) if sh else None))
    return out


VENTANAS_SIM = ','.join(f'{p}+{q}@{sh}' for (p, q), (sh, _, _) in TECHO_SIM.items())


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('outdir')
    p.add_argument('--etapas', default='A,B',
                   help='A, copia, B y C, separadas por coma (A,B)')
    p.add_argument('--modos', default='periodico,aleatorio')
    p.add_argument('--ventanas', default=VENTANAS_SIM,
                   help='pre+post[@slot_shift], separadas por coma (las de la simulación)')
    p.add_argument('--tasas', default='1e4,3e4,1e5,3e5,1e6,3e6', help='en Hz')
    p.add_argument('--sin-techo', dest='techo', action='store_false',
                   help='no agregar al periódico los dos períodos del techo del writer')
    p.add_argument('--n', type=float, default=200_000, help='disparos por punto, como mucho')
    p.add_argument('--n-min', type=float, default=10_000)
    p.add_argument('--seg-max', type=float, default=2.0,
                   help='segundos de estímulo por punto (0: siempre --n)')
    p.add_argument('--dt-min', type=int, default=5, help='del modo aleatorio')
    p.add_argument('--semilla', type=int, default=7)
    p.add_argument('--n-modelo-max', type=float, default=2_000_000,
                   help='hasta cuántos disparos se predicen las marcas del aleatorio')
    p.add_argument('--plazo-extra', type=float, default=5.0,
                   help='segundos de más sobre 1.5·N/tasa antes de cortar un punto')
    p.add_argument('--carga', type=int, default=0,
                   help='procesos que ocupan un núcleo cada uno durante la medición')
    p.add_argument('--resumen', action='store_true',
                   help='no mide: reimprime el resumen de <outdir>/etapas_ring.json')
    g = p.add_argument_group('etapa C')
    g.add_argument('--formato', choices=('npz', 'lh5'), default='npz')
    g.add_argument('--destino', default=None,
                   help='dónde escribe la sesión: la SD, /dev/shm o un montaje de red '
                        '(<outdir>/_etapa_c)')
    g.add_argument('--chunk', type=int, default=4096)
    g.add_argument('--ram-mb', type=float, default=64.0)
    g.add_argument('--margen-mb', type=float, default=MIN_FREE_MB,
                   help='lo que el escritor deja libre en el disco: se para solo por '
                        f'debajo ({MIN_FREE_MB:.0f}, como la sesión; en /dev/shm, que '
                        'tiene 231 MB en la placa, conviene ~16)')
    g.add_argument('--red', default=None, metavar='HOST[:PUERTO]',
                   help='la etapa C por el servidor de la placa (mca_server.py), desde '
                        'esta máquina: la sesión corre en la placa y escribe en --destino '
                        '(un camino absoluto de la placa, dentro de un montaje de red); '
                        'acá se verifica en --destino-pc')
    g.add_argument('--destino-pc', default=None,
                   help='con --red: el --destino de la placa, visto desde esta máquina')
    g.add_argument('--guardar', action='store_true', help='no borrar los archivos')
    g.add_argument('--sin-verificar', dest='verificar_archivos', action='store_false',
                   help='no leer de vuelta los archivos')
    a = p.parse_args(argv)
    a.etapas = [e.strip() for e in a.etapas.split(',') if e.strip()]
    for e in a.etapas:
        if e not in ETAPAS:
            p.error(f'etapa {e!r}: es una de {", ".join(ETAPAS)}')
    a.modos = [m.strip() for m in a.modos.split(',') if m.strip()]
    for m in a.modos:
        if m not in MODOS:
            p.error(f'modo {m!r}: es uno de {", ".join(MODOS)}')
    a.ventanas = parse_ventanas(a.ventanas)
    a.tasas = [float(x) for x in a.tasas.split(',') if x.strip()]
    a.n, a.n_min, a.n_modelo_max = int(a.n), int(a.n_min), int(a.n_modelo_max)
    if a.red:
        if a.etapas != ['C']:
            p.error('--red corre sólo la etapa C: --etapas C')
        if a.carga:
            p.error('--carga ocupa los núcleos de esta máquina, no los de la placa: no '
                    'va con --red')
        if not a.destino or not a.destino_pc:
            p.error('--red necesita --destino (en la placa, dentro del montaje) y '
                    '--destino-pc (el mismo directorio, acá)')
        if not os.path.isabs(a.destino):
            p.error(f'--destino {a.destino}: con --red es un camino absoluto de la placa')
        a.destino_pc = os.path.expanduser(a.destino_pc)
    elif a.destino_pc:
        p.error('--destino-pc va con --red')
    return a


def puntos(a):
    """(pre, post, slot_shift, modo, tasa, etapa), con las etapas de un mismo estímulo
    seguidas."""
    for pre, post, sh in a.ventanas:
        if sh is None:
            sh = OR.geometria(pre, post)['slot_shift']
        for modo in a.modos:
            tasas = list(a.tasas)
            sim = TECHO_SIM.get((pre, post))
            if modo == 'periodico' and a.techo and sim and sim[0] == sh:
                tasas += [FS_HZ / (sim[2] - 2), FS_HZ / sim[2]]
            for tasa in sorted(set(tasas)):
                for etapa in a.etapas:
                    yield pre, post, sh, modo, tasa, etapa


def linea(f):
    perd = f['drop_busy'] + f['drop_full']
    txt = (f'  {f["etapa"]:>5} {f["pre"]:>3}+{f["post"]:<4} {f["modo"]:<9} '
           f'{f["tasa"] / 1e3:9.1f} k/s  N={f["n"]:<8d} ev={f["ev_cnt"]:<8d} '
           f'busy={f["drop_busy"]:<7d}')
    txt += (f'(mod {f["busy_predicho"]:<7d}) ' if f['busy_predicho'] is not None
            else '(mod   -    ) ')
    txt += f'full={f["drop_full"]:<7d} pérdida={100 * perd / max(f["gen_cnt"], 1):5.1f} %'
    if f.get('tasa_consumo'):
        txt += f'  lee {f["tasa_consumo"] / 1e3:7.1f} k/s'
    if f.get('trabajo') is not None:
        txt += f' trabajo {100 * f["trabajo"]:3.0f} %'
    if f.get('ocupacion_max') is not None:
        txt += f' ocup {f["ocupacion_max"]}/{f["n_slots"]}'
    if f.get('errores') is not None:
        txt += f' errores {f["errores"]}'
    if f['anomalias']:
        txt += '  ANOMALÍA: ' + '; '.join(f['anomalias'])
    return txt


def saturado(f):
    """¿El lector se atrasó? Un punto corto puede no tener descartes sólo porque el ring
    (131 072 slots de 256 B) absorbió el atraso: en la placa, B a 1 M/s con 32
    muestras llegó a 124 992 slots ocupados sin perder. Cuenta como saturado si la
    ocupación pasó de 1/16 del ring o, en un punto más largo que el ring, de 1/16 del
    punto (el atraso de un lector lento crece con N; el de un lector al día que el
    sistema demoró, no: A a 1.4 M/s con 10⁸ y el ARM ocupado llegó a 42 191 slots, 30
    ms, leyendo a la tasa del estímulo), o si el lector trabajó el 95 % del tiempo.
    En C, que no los mide, si la sesión leyó a menos del 90 % de la tasa a la que se
    escribieron los aceptados (`ev_cnt` en lo que duró el estímulo). Y siempre que
    haya DROP_FULL: la etapa no dio abasto (en A, el writer de la PL)."""
    if f.get('drop_full', 0) > 0:
        return True
    if f.get('ocupacion_max') is not None:
        return (f['ocupacion_max'] >= max(f['n_slots'], f['n']) / 16
                or (f.get('trabajo') or 0) >= 0.95)
    escritos_por_s = f['ev_cnt'] * f['tasa'] / f['n']
    return (f.get('tasa_consumo') or 0.0) < 0.9 * escritos_por_s


def resumen(filas):
    """Por etapa y ventana: la tasa periódica más alta sin descartes con el lector al
    día, la más baja con DROP_FULL, lo que lee el lector saturado y los techos de la
    simulación."""
    lineas = ['', '  por etapa y ventana: el periódico más alto sin descartes con el lector '
              'al día / el más bajo con DROP_FULL;',
              '  lo que pasa por la etapa saturada (en A, el writer de la PL; en B, el '
              'lector; en C, el lector de la sesión);',
              '  los techos de la simulación (captura, writer)']
    claves = sorted({(f['etapa'], f['pre'], f['post']) for f in filas},
                    key=lambda c: (list(ETAPAS).index(c[0]), c[1] + c[2]))
    for etapa, pre, post in claves:
        fs = [f for f in filas if (f['etapa'], f['pre'], f['post']) == (etapa, pre, post)]
        per = [f for f in fs if f['modo'] == 'periodico']
        ok = [f['tasa'] for f in per if f['sin_perdidas'] and not saturado(f)]
        llenas = [f['tasa'] for f in per if f['drop_full'] > 0]
        lee = [f['tasa_consumo'] for f in fs if saturado(f) and f.get('tasa_consumo')]
        f0 = fs[0]
        sim = (f'{f0["techo_captura_hz"] / 1e3:.0f}, '
               + (f'{f0["techo_writer_sim_hz"] / 1e3:.0f}' if f0['techo_writer_sim_hz']
                  else '-'))
        lineas.append(f'  {etapa:>5} {pre:>3}+{post:<4}  '
                      + (f'{max(ok) / 1e3:8.1f}' if ok else '       -') + ' / '
                      + (f'{min(llenas) / 1e3:8.1f}' if llenas else '       -')
                      + ' k/s   pasa ' + (f'{max(lee) / 1e3:7.1f} k/s' if lee else '      -    ')
                      + f'   (sim {sim} k/s)')
    malas = [f for f in filas if f['anomalias']]
    lineas.append(f'\n  {len(filas)} puntos, {len(malas)} con anomalías')
    return '\n'.join(lineas)


def guardar(path, meta, filas):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(dict(meta=meta, puntos=filas), fh, indent=1,
                  default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    os.replace(tmp, path)


def main(argv=None, abrir_ring=None):
    a = parse_args(argv)
    salida = os.path.join(a.outdir, 'etapas_ring.json')
    if a.resumen:
        with open(salida) as fh:
            print(resumen(json.load(fh)['puntos']))
        return 0
    os.makedirs(a.outdir, exist_ok=True)
    destino = a.destino or os.path.join(a.outdir, '_etapa_c')
    if 'C' in a.etapas and not a.red:
        os.makedirs(destino, exist_ok=True)
    if a.red:
        # La sesión corre en el servidor; `ring` es el handle remoto (las ops ring.*).
        from API.mca_net import PORT_DEFAULT
        from API.mca_remote import MCARemote
        host, _, puerto = a.red.partition(':')
        ring = MCARemote.connect(host, int(puerto) if puerto else PORT_DEFAULT)
    else:
        ring = (abrir_ring or OR.OsciloscopeRing.open)()
    meta = dict(test='etapas_ring', fecha=datetime.now().isoformat(timespec='seconds'),
                cli=' '.join(sys.argv[1:] if argv is None else argv),
                libmca=_libmca.version(), maquina=platform.node(),
                muerto_extra=MUERTO_EXTRA, techo_sim={f'{p}+{q}': v for (p, q), v
                                                      in TECHO_SIM.items()})
    if a.red:
        meta.update(servidor=a.red, libmca_placa=ring.libmca_version)
    filas = []
    procs = ocupar_cpu(a.carga) if a.carga else []
    try:
        if a.red:
            if not (ring.has_ring and ring.has_gen):
                raise SystemExit(f'el servidor de {a.red} no tiene el ring con el '
                                 'generador: cargar el bitstream del ring con generadores '
                                 '(78e26188 o posterior) y levantar el servidor')
        elif not ring.gen_presente():
            raise SystemExit('el ring de este bitstream no tiene el generador ("GEN1"): '
                             'cargar el del ring con generadores (78e26188 o posterior)')
        todos = list(puntos(a))
        print(f'{len(todos)} puntos: etapas {",".join(a.etapas)}, '
              f'{len(a.ventanas)} ventanas, modos {",".join(a.modos)}'
              + (f', con {a.carga} núcleo(s) ocupado(s)' if a.carga else ''))
        for pre, post, sh, modo, tasa, etapa in todos:
            try:
                f = medir_punto(ring, etapa, pre, post, sh, modo, tasa, a, destino)
            except ValueError as e:          # una tasa que el motor no hace
                print(f'  {etapa:>5} {pre:>3}+{post:<4} {modo:<9} {tasa:9.0f} Hz: '
                      f'SALTEADO ({e})')
                continue
            filas.append(f)
            print(linea(f), flush=True)
            guardar(salida, meta, filas)
    finally:
        soltar_cpu(procs)
        ring.close()
        if not a.guardar and 'C' in a.etapas and not a.destino:
            shutil.rmtree(destino, ignore_errors=True)
    print(resumen(filas))
    print(f'\n=== {salida} ===')
    return 1 if any(f['anomalias'] for f in filas) else 0


if __name__ == '__main__':
    sys.exit(main())
