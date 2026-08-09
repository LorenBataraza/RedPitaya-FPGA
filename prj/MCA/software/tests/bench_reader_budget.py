#!/usr/bin/env python3
"""Fase 0 — presupuesto del hilo lector: medir antes de construir el pipeline.

El diseno del pipeline de adquisicion (mca/) se apoyaba en UNA sola medicion real
(0.35 us/transaccion, de bench_read_vs_length.py) y en estimaciones. Este script
reemplaza las estimaciones por numeros y zanja los riesgos abiertos del esquema.

Que mide (cada bloque imprime su tabla y deja sus arrays en el .npz):

  1. poll_floor    piso del lazo de polling (1 lectura de registro por mmap)
  2. read_window   costo de leer una ventana vs S (muestras) y vs n_ch
  3. raw_vs_v      existen variantes Raw? son mas rapidas que las *V?
  4. wrap          PosV con start>end en UNA llamada vs partirlo en DOS
  5. writer        savez vs savez_compressed sobre un chunk tipico (tiempo + ratio)
  6. gil           latencia por evento del lazo lector CON y SIN escritor de fondo
  7. footprint     bytes/evento y RAM del pool; tiempos de init/arm

NO necesita el Rigol: congela el buffer con un SW trigger, asi que mide el COSTO
DEL TRABAJO del lector (poll + lectura de ventana), que es lo que determina el
techo de eventos/s. La tasa de triggers real es otra medicion (sweep_periods).

Uso (en la Pitaya, con el bitstream multitrigger cargado):
    python3 bench_reader_budget.py [REPS]

ATENCION: no correr con el kernel de Jupyter activo (pelea por /dev/mem -> SIGBUS).
Ver tests/README.md.
"""
import sys, os, time, threading, queue, struct, tempfile, shutil

import numpy as np

sys.path.insert(0, '/opt/redpitaya/lib/python')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import rp
from multitrigger_utils import MultiTriggerScope, N_BUF

REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
HERE = os.path.dirname(os.path.abspath(__file__))

# Config de referencia del pipeline (la del plan): 2 canales, ventana de 32.
S_LIST      = [8, 16, 32, 64, 128]
S_REF       = 32
NCH_REF     = 2
CAPACITY    = 4096          # eventos por chunk
WP_TRIG_OFF = 0x1C          # registro que polea el lector
_U32        = struct.Struct('<I')

CHS = (rp.RP_CH_1, rp.RP_CH_2)


def stats_us(ts_ns):
    """mediana / p99 / max en us de un array de duraciones en ns."""
    a = np.asarray(ts_ns, dtype=np.float64) / 1e3
    return float(np.median(a)), float(np.percentile(a, 99)), float(a.max())


def timeit_ns(fn, reps):
    """Devuelve el array de duraciones (ns) de `reps` corridas de `fn`."""
    out = np.empty(reps, dtype=np.int64)
    pc  = time.perf_counter_ns
    for k in range(reps):
        t0 = pc(); fn(); out[k] = pc() - t0
    return out


# ---------------------------------------------------------------- 1. poll floor

def bench_poll_floor(sc, res):
    """Costo de UNA lectura de registro por mmap = el piso del lazo de polling.

    Es el termino 'overhead de Python' del presupuesto: lo que cuesta detectar
    que llego un evento, antes de leer un solo sample.
    """
    print('\n[1] piso del lazo de polling (lectura de 0x1C por mmap)')
    mem, unpack_from = sc._mmap, _U32.unpack_from

    def one():
        unpack_from(mem, WP_TRIG_OFF)

    # Lote grande: una sola lectura dura menos que la resolucion del reloj.
    BATCH = 1000

    def batch():
        for _ in range(BATCH):
            unpack_from(mem, WP_TRIG_OFF)

    ts = timeit_ns(batch, REPS) / BATCH
    med, p99, mx = stats_us(ts)
    print(f'    mediana={med*1e3:7.0f} ns   p99={p99*1e3:7.0f} ns   max={mx*1e3:8.0f} ns')
    res['poll_ns'] = ts
    return med * 1e3       # ns


# --------------------------------------------------- 2/3. lectura de la ventana

def _mk_readers(n):
    """Devuelve {nombre: callable(ch, start, end) -> np.ndarray} para ventana de n.

    Cubre los caminos disponibles en el `rp` instalado. Ojo: en RP OS 2.x NO
    existen las variantes *NP (capture_window_np ya cae al fallback fBuffer).
    """
    readers = {}

    fb = rp.fBuffer(n)
    def read_v(ch, start, end, _fb=fb, _n=n):
        rp.rp_AcqGetDataPosV(ch, start, end, _fb, _n)
        return _fb
    readers['PosV(float)'] = read_v

    if hasattr(rp, 'rp_AcqGetDataPosVNP'):
        buf = np.empty(n, dtype=np.float32)
        def read_vnp(ch, start, end, _b=buf):
            rp.rp_AcqGetDataPosVNP(ch, start, end, _b)
            return _b
        readers['PosVNP(float)'] = read_vnp

    if hasattr(rp, 'rp_AcqGetDataPosRaw'):
        ib   = rp.i16Buffer(n)
        cand = [('5 args', lambda ch, s, e: rp.rp_AcqGetDataPosRaw(ch, s, e, ib, n)),
                ('4 args', lambda ch, s, e: rp.rp_AcqGetDataPosRaw(ch, s, e, ib))]
        for label, fn in cand:                 # la firma cambia segun la version
            try:
                fn(rp.RP_CH_1, 0, n - 1)
            except Exception as exc:
                last = f'{label}: {exc!r}'
                continue
            readers['PosRaw(int16)'] = lambda ch, s, e, _f=fn, _ib=ib: (_f(ch, s, e), _ib)[1]
            break
        else:
            print(f'    (PosRaw no usable -> {last[:70]})')

    return readers


def bench_read_window(sc, res):
    """Costo de leer una ventana, vs longitud S y vs metodo (V / Raw).

    Responde dos cosas del plan: (2) si la linealidad de 0.35 us/muestra se
    mantiene en el rango CHICO que usa el MCA (el bench viejo arranca en 128),
    y (3) si conviene int16 crudo en vez de float32 en volts.
    """
    print(f'\n[2/3] lectura de ventana vs S y vs metodo   (ref: pos={sc._ref})')
    ref   = sc._ref
    names = None
    table = {}
    for n in S_LIST:
        readers = _mk_readers(n)
        names   = names or list(readers)
        start   = (ref - n // 2) % N_BUF
        end     = (start + n - 1) % N_BUF
        row = {}
        for name, fn in readers.items():
            fn(rp.RP_CH_1, start, end)                    # warm-up
            ts = timeit_ns(lambda f=fn: f(rp.RP_CH_1, start, end), REPS)
            row[name] = float(np.median(ts)) / 1e3        # us
        table[n] = row

    hdr = f'    {"S":>5s} ' + ' '.join(f'{k:>16s}' for k in names) + '   us/muestra'
    print(hdr); print('    ' + '-' * (len(hdr) - 4))
    for n in S_LIST:
        row  = table[n]
        best = min(row.values())
        print(f'    {n:5d} ' + ' '.join(f'{row[k]:16.2f}' for k in names)
              + f'   {best/n:9.3f}')

    res['S_list']       = np.array(S_LIST)
    res['read_methods'] = np.array(names, dtype=object)
    res['read_us']      = np.array([[table[n][k] for k in names] for n in S_LIST])

    # Presupuesto por evento a la config de referencia, con el mejor metodo.
    best_name = min(table[S_REF], key=table[S_REF].get)
    per_ev_us = table[S_REF][best_name] * NCH_REF
    print(f'\n    mejor metodo @S={S_REF}: {best_name}  ->  '
          f'{per_ev_us:.1f} us/evento con {NCH_REF} canales')
    res['best_method'] = best_name
    return per_ev_us, best_name, table


# ------------------------------------- 2b. lectura directa del BRAM por el mmap

# El casez de multitrigger_rp_scope_cfg mapea la BRAM de cada canal a un rango
# propio del espacio del scope: 20'h1???? -> ch0, 20'h2???? -> ch1. La direccion
# del bus ES el indice de muestra (bram_rp_i = sys_addr[RSZ+1:2]), o sea una
# palabra de 32 b por muestra. Y SCOPE_SIZE (0x30000) ya cubre los dos rangos,
# asi que el mmap que MultiTriggerScope abre para los registros TAMBIEN tiene la
# BRAM: se puede leer la ventana con numpy, sin pasar por la API del rp.
BRAM_OFF = (0x10000, 0x20000)
DW_MASK  = 0x3FFF          # 14 bits utiles; el readback los pone zero-extended
DW_SIGN  = 0x2000


def make_bram_views(mem):
    """UNA vista uint32 por canal sobre el mmap, creada una sola vez.

    Crear la vista con np.frombuffer cuesta ~200 us (adquiere el buffer del
    mmap entero), asi que hacerlo por evento arruina todo: hay que hoistearlo
    fuera del lazo y despues solo SLICEAR, que es gratis.
    """
    return [np.frombuffer(mem, dtype='<u4', count=N_BUF, offset=off)
            for off in BRAM_OFF]


def read_bram_view(views, ch_idx, start, n, out=None):
    """Ventana de `n` muestras del canal `ch_idx`, sliceando la vista.

    El readback trae el valor de 14 b en los bits bajos SIN extender el signo,
    asi que hay que re-extenderlo. Escribe en `out` (int16) si se provee.
    """
    v = views[ch_idx]
    if start + n <= N_BUF:
        raw = v[start:start + n]
    else:                                       # wrap: dos tramos
        n1  = N_BUF - start
        raw = np.concatenate((v[start:], v[:n - n1]))
    s = (raw & DW_MASK).astype(np.int16)
    s -= ((s & DW_SIGN) << 1).astype(np.int16)  # sign-extend de 14 -> 16 b
    if out is not None:
        out[:] = s
        return out
    return s


def bench_direct_bram(sc, res):
    """La API vs leer la BRAM directo del mmap.

    Motivo: el bloque [2] muestra que el costo de `rp_AcqGetDataPosV` esta
    dominado por un OVERHEAD FIJO POR LLAMADA (~35 us), no por las muestras. Si
    ese overhead es de la API y no del bus, saltearla deberia dar un salto
    grande justo en el rango de ventanas chicas que usa el MCA.
    """
    print('\n[2b] leer la ventana: API (PosV) vs mmap directo (vista hoisteada)')
    mem   = sc._mmap
    ref   = sc._ref
    views = make_bram_views(mem)

    # --- correctitud contra la API ---
    # La API aplica la calibracion de EEPROM (offset+ganancia) y el camino
    # directo no, asi que se compara la FORMA: se quita la media de cada uno.
    n     = 64
    start = (ref - n // 2) % N_BUF
    fb = rp.fBuffer(n)
    rp.rp_AcqGetDataV(rp.RP_CH_1, start, n, fb)
    w_api = np.fromiter((fb[i] for i in range(n)), dtype=np.float32, count=n)
    w_dir = read_bram_view(views, 0, start, n).astype(np.float32) / 8192.0
    off   = float(np.mean(w_dir - w_api))
    dmax  = float(np.max(np.abs((w_dir - off) - w_api)))
    ok    = dmax < 2e-4            # ~2 cuentas
    print(f'    vs API: offset constante = {off*8192:+.1f} cuentas (calibracion), '
          f'max|diff| residual = {dmax:.3g} V   {"OK" if ok else "<-- REVISAR"}')
    if not ok:
        print(f'      api[:6]={np.round(w_api[:6], 4)}')
        print(f'      dir[:6]={np.round(w_dir[:6], 4)}')

    # --- velocidad, vs S, leyendo los N canales de referencia ---
    print(f'    {"S":>5s} {"API 2ch (us)":>14s} {"mmap 2ch (us)":>15s} {"speedup":>9s}')
    api_us, dir_us = [], []
    for s in S_LIST:
        st = (ref - s // 2) % N_BUF
        en = (st + s - 1) % N_BUF
        f  = rp.fBuffer(s)

        def do_api(_s=s, _st=st, _en=en, _f=f):
            for ch in CHS[:NCH_REF]:
                rp.rp_AcqGetDataPosV(ch, _st, _en, _f, _s)

        def do_dir(_s=s, _st=st):
            for k in range(NCH_REF):
                read_bram_view(views, k, _st, _s)

        do_api(); do_dir()
        a = float(np.median(timeit_ns(do_api, REPS))) / 1e3
        d = float(np.median(timeit_ns(do_dir, REPS))) / 1e3
        api_us.append(a); dir_us.append(d)
        print(f'    {s:5d} {a:14.1f} {d:15.1f} {a/d:8.1f}x')

    res['direct_S']      = np.array(S_LIST)
    res['direct_api_us'] = np.array(api_us)
    res['direct_mmap_us'] = np.array(dir_us)
    res['direct_ok']     = ok
    i = S_LIST.index(S_REF)
    print(f'    @S={S_REF}: API {api_us[i]:.1f} us  ->  mmap {dir_us[i]:.1f} us '
          f'/evento  (techo {1e6/dir_us[i]/1e3:.0f} kev/s vs {1e6/api_us[i]/1e3:.0f})')
    return dir_us[i], ok


# ------------------------------------------------------------------- 4. el wrap

def bench_wrap(sc, res):
    """PosV con start>end: UNA llamada vs partirlo en DOS.

    capture_window_np le pasa start>end directo a la API; guardado_mariana.py lo
    parte a mano. Los dos no pueden estar bien.

    La referencia es `rp_AcqGetDataV(ch, pos, size)`, que es POSICIONAL igual que
    PosV -- NO `OldestDataV`, que devuelve el buffer ROTADO para arrancar en la
    muestra mas vieja y por lo tanto no se indexa por posicion absoluta.
    """
    print('\n[4] ventana con wrap (start > end): 1 llamada vs 2')
    n     = 64
    start = (N_BUF - n // 2) % N_BUF          # fuerza el wrap
    end   = (start + n - 1) % N_BUF
    assert start > end, 'la ventana de prueba deberia envolver'

    # referencia posicional: DataV(pos, size) == PosV(pos, pos+size-1)
    fr = rp.fBuffer(n)
    rp.rp_AcqGetDataV(rp.RP_CH_1, start, n, fr)
    w_ref = np.fromiter((fr[i] for i in range(n)), dtype=np.float32, count=n)

    # A: una sola llamada con start > end
    fb = rp.fBuffer(n)
    rp.rp_AcqGetDataPosV(rp.RP_CH_1, start, end, fb, n)
    w_one = np.fromiter((fb[i] for i in range(n)), dtype=np.float32, count=n)

    # B: partido en dos (lo que hace guardado_mariana.py)
    n1, n2 = N_BUF - start, end + 1
    f1, f2 = rp.fBuffer(n1), rp.fBuffer(n2)
    rp.rp_AcqGetDataPosV(rp.RP_CH_1, start, N_BUF - 1, f1, n1)
    rp.rp_AcqGetDataPosV(rp.RP_CH_1, 0, end, f2, n2)
    w_two = np.concatenate([
        np.fromiter((f1[i] for i in range(n1)), dtype=np.float32, count=n1),
        np.fromiter((f2[i] for i in range(n2)), dtype=np.float32, count=n2)])

    d_one = float(np.max(np.abs(w_one - w_ref)))
    d_two = float(np.max(np.abs(w_two - w_ref)))
    print(f'    start={start} end={end} n={n}')
    print(f'    1 llamada   max|diff| vs referencia = {d_one:.3g}   '
          f'{"OK" if d_one < 1e-6 else "<-- MAL"}')
    print(f'    2 llamadas  max|diff| vs referencia = {d_two:.3g}   '
          f'{"OK" if d_two < 1e-6 else "<-- MAL"}')
    print(f'    veredicto: {"la API resuelve el wrap sola" if d_one < 1e-6 else "HAY QUE PARTIRLO A MANO"}')
    res['wrap_diff_one'] = d_one
    res['wrap_diff_two'] = d_two
    return d_one < 1e-6


# ---------------------------------------------------------------- 5. el escritor

def _mk_chunk(n_ev, n_ch, S, dtype):
    """Chunk representativo: lo que el ChunkWriter va a escribir por archivo."""
    rng = np.random.default_rng(0)
    if dtype == np.int16:
        wave = rng.integers(-8192, 8192, size=(n_ev, n_ch, S), dtype=np.int16)
    else:
        wave = rng.standard_normal((n_ev, n_ch, S)).astype(np.float32)
    return dict(
        wave=wave,
        t_ns=np.arange(n_ev, dtype=np.int64) * 100_000,
        wp=rng.integers(0, N_BUF, n_ev).astype(np.int32),
        snap=np.full(n_ev, 2, dtype=np.uint32),
        gap=np.zeros(n_ev, dtype=np.uint8),
    )


def bench_writer(res, dtype=np.int16):
    """savez vs savez_compressed sobre un chunk tipico: tiempo y ratio.

    Decide el default de compresion con un numero, no a ojo. Importa porque el
    tiempo del escritor es tiempo que compite con el lector (ver bloque 6).
    """
    print(f'\n[5] escritura de un chunk ({CAPACITY} ev x {NCH_REF} ch x {S_REF} '
          f'muestras, {np.dtype(dtype).name})')
    payload = _mk_chunk(CAPACITY, NCH_REF, S_REF, dtype)
    raw_mb  = sum(a.nbytes for a in payload.values()) / 1024**2
    tmp     = tempfile.mkdtemp(prefix='benchw_')
    out     = {}
    try:
        for label, fn in (('savez', np.savez), ('savez_compressed', np.savez_compressed)):
            path = os.path.join(tmp, f'{label}.npz')
            ts = timeit_ns(lambda p=path, f=fn: f(p, **payload), max(5, REPS // 40))
            sz = os.path.getsize(path) / 1024**2
            med_ms = float(np.median(ts)) / 1e6
            out[label] = (med_ms, sz)
            print(f'    {label:18s} {med_ms:7.1f} ms   {sz:5.2f} MB   '
                  f'ratio={raw_mb/sz:4.2f}x   {raw_mb/(med_ms/1e3):6.1f} MB/s')
        res['writer'] = np.array([[v[0], v[1]] for v in out.values()])
        res['writer_labels'] = np.array(list(out), dtype=object)
        res['chunk_raw_mb'] = raw_mb
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out, payload


# ------------------------------------------------------- 6. contencion del GIL

def bench_gil(sc, payload, best_name, res):
    """LA medicion que decide la escalera de mitigaciones.

    Corre el lazo del lector (poll + leer ventana de los 2 canales) y mide la
    latencia POR EVENTO, primero solo y despues con un hilo de fondo escribiendo
    chunks sin parar. Si la distribucion no se mueve, no hay contencion de GIL y
    los escalones 2-4 (afinidad / SCHED_FIFO / proceso aparte) son innecesarios.
    """
    print('\n[6] contencion de GIL: lazo del lector, solo vs con escritor de fondo')
    ref   = sc._ref
    mem, unpack_from = sc._mmap, _U32.unpack_from
    start = (ref - S_REF // 2) % N_BUF
    end   = (start + S_REF - 1) % N_BUF
    N_IT  = max(2000, REPS * 10)

    if best_name == 'mmap directo':                 # el camino que vamos a usar
        views = make_bram_views(mem)
        def read_all():
            for k in range(NCH_REF):
                read_bram_view(views, k, start, S_REF)
    else:
        read = _mk_readers(S_REF)[best_name]
        def read_all():
            for ch in CHS[:NCH_REF]:
                read(ch, start, end)

    def reader_loop():
        """Un 'evento': 1 poll + leer la ventana de los N canales."""
        lat = np.empty(N_IT, dtype=np.int64)
        pc  = time.perf_counter_ns
        for k in range(N_IT):
            t0 = pc()
            unpack_from(mem, WP_TRIG_OFF)
            read_all()
            lat[k] = pc() - t0
        return lat

    lat_solo = reader_loop()

    stop = threading.Event()
    tmp  = tempfile.mkdtemp(prefix='benchg_')
    n_written = [0]

    def writer_loop():
        i = 0
        while not stop.is_set():
            np.savez(os.path.join(tmp, f'c{i % 3}.npz'), **payload)
            i += 1
        n_written[0] = i

    th = threading.Thread(target=writer_loop, daemon=True)
    try:
        th.start()
        time.sleep(0.2)                     # que el escritor entre en regimen
        lat_busy = reader_loop()
    finally:
        stop.set(); th.join(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)

    print(f'    {"":10s} {"mediana":>10s} {"p99":>10s} {"max":>10s}   (us/evento)')
    for label, lat in (('solo', lat_solo), ('con writer', lat_busy)):
        med, p99, mx = stats_us(lat)
        print(f'    {label:10s} {med:10.2f} {p99:10.2f} {mx:10.1f}')
    m_solo = float(np.median(lat_solo)); m_busy = float(np.median(lat_busy))
    p_solo = float(np.percentile(lat_busy, 99)) / float(np.percentile(lat_solo, 99))
    degr   = (m_busy / m_solo - 1) * 100
    stall_us = float(lat_busy.max()) / 1e3
    print(f'    chunks escritos de fondo: {n_written[0]}')
    print(f'    degradacion: mediana {degr:+.1f} %   p99 x{p_solo:.1f}   '
          f'stall maximo {stall_us:.0f} us')
    # La MEDIANA no alcanza para decidir: la firma de la contencion de GIL esta
    # en la COLA. Un stall del orden de sys.getswitchinterval() (5 ms por
    # default) es GIL, no I/O.
    sw_us = sys.getswitchinterval() * 1e6
    print(f'    (sys.getswitchinterval() = {sw_us:.0f} us)')
    if stall_us > 0.5 * sw_us:
        veredicto = (f'CONTENCION DE GIL: stalls de ~{stall_us:.0f} us, del orden '
                     f'del switch interval ({sw_us:.0f} us). La mediana no lo '
                     f'muestra; la cola si.')
    elif degr > 10 or p_solo > 2:
        veredicto = 'hay degradacion apreciable -> evaluar afinidad / SCHED_FIFO'
    else:
        veredicto = 'sin contencion apreciable -> escalones 2-4 innecesarios'
    print(f'    veredicto: {veredicto}')
    res['lat_solo_ns'] = lat_solo
    res['lat_busy_ns'] = lat_busy
    return m_solo / 1e3, m_busy / 1e3


# ---------------------------------------------------------------- 7. footprint

def bench_footprint(per_ev_us, res, dtype=np.int16):
    """Bytes por evento, RAM del pool y techo de eventos/s derivado."""
    print('\n[7] presupuesto de memoria y techo')
    b_wave  = NCH_REF * S_REF * np.dtype(dtype).itemsize
    b_scal  = 8 + 4 + 4 + 1                       # t_ns, wp, snap, gap
    b_ev    = b_wave + b_scal
    for nb in (2, 4, 8):
        mb = nb * CAPACITY * b_ev / 1024**2
        print(f'    n_batches={nb}  ->  {mb:6.2f} MB de pool '
              f'({nb*CAPACITY} eventos en vuelo)')
    techo = 1e6 / per_ev_us if per_ev_us else float('nan')
    print(f'    bytes/evento = {b_ev}  (wave {b_wave} + escalares {b_scal})')
    print(f'    TECHO del lector = {techo/1e3:.1f} kev/s  ({per_ev_us:.1f} us/evento)')
    res['bytes_per_event'] = b_ev
    res['ceiling_ev_s']    = techo
    return b_ev, techo


# ---------------------------------------------------------------------- main

def main():
    print('=' * 78)
    print(f'  Fase 0 - presupuesto del hilo lector   (REPS={REPS})')
    print('=' * 78)
    print(f'  rp: variantes NP {"presentes" if hasattr(rp, "rp_AcqGetDataPosVNP") else "AUSENTES"}'
          f' | Raw {"presente" if hasattr(rp, "rp_AcqGetDataPosRaw") else "ausente"}')

    t0 = time.perf_counter()
    rp.rp_Init()
    t_init = time.perf_counter() - t0

    sc  = MultiTriggerScope.open()
    res = {}
    try:
        t0 = time.perf_counter()
        sc.acq_capture_sw(thr=0.5)               # congela el buffer (sin Rigol)
        t_arm = time.perf_counter() - t0
        sc._ref = rp.rp_AcqGetWritePointerAtTrig()[1]
        print(f'  rp_Init={t_init*1e3:.0f} ms | arm+captura SW={t_arm*1e3:.0f} ms '
              f'| wp_trig={sc._ref}')

        bench_poll_floor(sc, res)
        per_ev_us, best_name, _ = bench_read_window(sc, res)
        dir_us, dir_ok = bench_direct_bram(sc, res)
        wrap_ok = bench_wrap(sc, res)
        # El camino directo se elige solo si ademas de correcto es MAS RAPIDO.
        if dir_ok and dir_us < per_ev_us:
            per_ev_us, best_name, dtype = dir_us, 'mmap directo', np.int16
        else:
            dtype = np.int16 if 'Raw' in best_name else np.float32
            if dir_ok:
                print(f'\n    nota: el mmap directo es correcto pero {dir_us/per_ev_us:.1f}x '
                      f'mas lento a S={S_REF} -> se queda la API')
        _, payload = bench_writer(res, dtype)
        bench_gil(sc, payload, best_name, res)
        bench_footprint(per_ev_us, res, dtype)

        print('\n' + '=' * 78)
        print('  RESUMEN')
        print('=' * 78)
        print(f'  metodo de lectura elegido : {best_name}  -> dtype {np.dtype(dtype).name}')
        print(f'  wrap start>end (API)      : {"lo resuelve la API" if wrap_ok else "PARTIR A MANO"}')
        print(f'  techo del lector          : {res["ceiling_ev_s"]/1e3:.1f} kev/s')

        res['t_init_s'] = t_init
        res['t_arm_s']  = t_arm
        out = os.path.join(HERE, 'bench_reader_budget.npz')
        np.savez(out, **res)
        print(f'\n  datos: {out}')
    finally:
        sc.disarm(); sc.close(); rp.rp_Release()


if __name__ == '__main__':
    main()
