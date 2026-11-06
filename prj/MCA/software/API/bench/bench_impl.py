#!/usr/bin/env python3
"""Microbench de la API de hardware: la misma operación en cada implementación.

Mide, operación por operación, cuánto cuesta cada llamada en:

    py      la implementación Python congelada (API/ref_py/). Es la base: el
            mismo código siempre, para que una corrida de hoy y una de dentro de
            seis meses se puedan comparar.
    c       libmca por ctypes, que es lo que ve quien usa la API desde Python.
    c_puro  libmca sin intérprete (libmca/build/<arch>/bench_libmca, de
            libmca/tests/bench_libmca.c). La diferencia con `c` es lo que
            cuesta ctypes por llamada.

Las operaciones van en dos niveles, y el nombre dice cuál es cuál:

    bus.*   nivel 2: r32, w32 y la lectura en bloque de una apertura. Existen en
            `c` desde la fase 0 (sólo hace falta el Bus de libmca).
    api.*   nivel 4: las funciones públicas mca_*. En `c` aparecen cuando el
            binding del MCA está en C (fase 1); antes figuran como no
            disponibles, con el motivo.

Qué deja, en `--out` (por defecto datos/bench_impl_<fecha>/):

    resumen.json    el entorno (commit, libmca, bitstream, CPU...), y por
                    operación e implementación: mediana, p5, p95, máximo y
                    repeticiones, en µs. Más la igualdad bit a bit de las
                    lecturas en bloque entre implementaciones.
    resultados.npz  los tiempos crudos, clave "<impl>/<op>", en µs.

`API/bench/comparar_bench.py` lee uno o dos de estos directorios.

Lo que NO hace sin `--destructivo`: borrar el histograma, adquirir ni
reconfigurar. Las operaciones de escritura que sí corre (w32, set_campo)
escriben el valor que el registro ya tenía. Con `--destructivo` se miden
además clear, configure y acquire(0), y al final se restauran los registros
de configuración tal como estaban; el histograma no se recupera.

Con `--remoto HOST[:PUERTO]` corre en la PC contra `mca_server.py`: la columna
`remoto` es lo que cuesta cada función por la op `call` (una ida y vuelta, más
lo que tarde la placa), y `bus.*` las ops `r32`/`w32`. Es lo que ve la GUI.

Con `--shm` no toca la PL: el MCA es un fichero del tamaño del slot en
/dev/shm, con el magic, CAPS y WIDTHS de un MCA1 y cuentas en las aperturas.
`py` lo lee por un mmap, como a /dev/mem; `c` usa el mismo backend devmem de
libmca que en la placa (`Bus.archivo`). Lo que queda es el costo de cada
implementación sin el del bus, que es lo que hay que mirar al tocar el
binding: se puede correr con cualquier bitstream cargado, o con ninguno. Mide
también las operaciones destructivas (no hay nada que borrar) y no corre
`c_puro`, que abre /dev/mem.

    sudo python3 API/bench/bench_impl.py                 # en la placa
    python3 API/bench/bench_impl.py --fake               # en la PC: prueba el script
    python3 API/bench/bench_impl.py --shm                # el binding, sin PL
    python3 API/bench/bench_impl.py --remoto 10.73.28.30 # desde la PC, por red
    make bench-api-remoto                                # desde la PC, trae los datos
    make bench-api-shm-remoto                            # --shm en la placa
"""

import argparse
import gc
import hashlib
import json
import mmap
import os
import platform
import struct
import subprocess
import tempfile
import sys
import time

import numpy as np

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

# La referencia Python del mapa que tenga la placa: la del MCA2 por defecto;
# con el bitstream MCA1, `main` la cambia por la congelada (y `c` queda fuera,
# porque libmca habla sólo MCA2).
import API.ref_py.mca2 as ref                                      # noqa: E402
import API.ref_py.mca as ref_mca1                                  # noqa: E402
from API import _libmca                                            # noqa: E402

FORMATO = 1             # versión del esquema de resumen.json
BITSTREAM_DEFAULT = '/root/mca_red_pitaya.bit.bin'

# El MCA de --shm: la geometría del MCA1 medido en la placa (8192 canales,
# mapa de 128 x 64, espectro 1D y 2D).
SHM_CAPS = ref.CAP_HIST_H | ref.CAP_HIST_H_PSD
SHM_AW = (13, 7, 6)                     # h_aw, h2_aw, psd_aw


# =============================================================================
# Medición
# =============================================================================

def medir(fn, presupuesto_s, min_reps=5, max_reps=5000):
    """Tiempos de `fn()` en µs: al menos `min_reps`, hasta agotar el presupuesto.

    La primera llamada no se cuenta: paga imports perezosos, fallos de página
    del mmap y el arranque de cachés, y no es lo que se quiere comparar. El
    recolector de basura va apagado durante la medición: una pasada del GC en
    medio de una operación de 2 µs la multiplica por diez, y eso es ruido del
    proceso, no costo de la operación.
    """
    fn()
    gc.collect()
    gc.disable()
    try:
        ts = []
        fin = time.perf_counter() + presupuesto_s
        while len(ts) < max_reps and (len(ts) < min_reps
                                      or time.perf_counter() < fin):
            t0 = time.perf_counter_ns()
            fn()
            ts.append(time.perf_counter_ns() - t0)
    finally:
        gc.enable()
    return np.asarray(ts, dtype=np.float64) / 1e3


def estadistica(us):
    return {'mediana_us': float(np.median(us)),
            'p5_us':      float(np.percentile(us, 5)),
            'p95_us':     float(np.percentile(us, 95)),
            'max_us':     float(us.max()),
            'reps':       int(us.size)}


# =============================================================================
# Las implementaciones
# =============================================================================
#
# Cada una arma un dict nombre -> callable sin argumentos. Los valores que se
# escriben (w32, set_campo, sobre amp_max, que existe en los dos mapas) se
# leen UNA vez antes, así la escritura no cambia
# nada y la operación medida es sólo la escritura.

def _ops_py(h, destructivo):
    n_h = 1 << h.h_aw
    w_campo = h.r32(ref.R_AMP_MAX)
    campo0 = ref.mca_get_amp_max(h)
    leer_bloque = getattr(h, '_read_words', None)
    if leer_bloque is None or getattr(h, '_mmap', 1) is None:
        # FakeMCA no tiene mmap: el bloque es el mismo lazo, sobre su r32.
        def leer_bloque(off, n):
            return np.array([h.r32(off + 4 * i) for i in range(n)],
                            dtype=np.uint32)
    ops = {
        'bus.r32':          lambda: h.r32(ref.R_MAGIC),
        'bus.w32':          lambda: h.w32(ref.R_AMP_MAX, w_campo),
        'bus.read_words_h': lambda: leer_bloque(ref.APERTURE_H, n_h),
        'api.get_campo':    lambda: ref.mca_get_amp_max(h),
        'api.set_campo':    lambda: ref.mca_set_amp_max(h, campo0),
        'api.get_config':   lambda: ref.mca_get_config(h),
        'api.counters':     lambda: ref.mca_read_counters(h),
        'api.last_event':   lambda: ref.mca_read_last_event(h),
        'api.identify':     lambda: ref.mca_identify(h, verbose=False),
        'api.spectrum':     lambda: ref.mca_read_histogram(h),
    }
    if h.caps & ref.CAP_HIST_H_PSD:
        n_2d = 1 << (h.h2_aw + h.psd_aw)
        ops['bus.read_words_2d'] = lambda: leer_bloque(ref.APERTURE_2D, n_2d)
        ops['api.map2d'] = lambda: ref.mca_read_map2d(h)
    if destructivo:
        ops['api.clear'] = lambda: ref.mca_clear(h)
        ops['api.configure'] = lambda: ref.mca_configure(h)
        ops['api.acquire0'] = lambda: ref.mca_read_acquire(h, 0)
    return ops, leer_bloque


def _ops_c_bus(bus, h_py):
    """Fase 0: el nivel 2 en C, sobre el mismo slot que mide `py`."""
    n_h = 1 << h_py.h_aw
    w_campo = bus.r32(ref.R_AMP_MAX)
    ops = {
        'bus.r32':          lambda: bus.r32(ref.R_MAGIC),
        'bus.w32':          lambda: bus.w32(ref.R_AMP_MAX, w_campo),
        'bus.read_words_h': lambda: bus.read_words(ref.APERTURE_H, n_h),
    }
    if h_py.caps & ref.CAP_HIST_H_PSD:
        n_2d = 1 << (h_py.h2_aw + h_py.psd_aw)
        ops['bus.read_words_2d'] = lambda: bus.read_words(ref.APERTURE_2D, n_2d)
    return ops


def _ops_c_api(destructivo, fake, shm=None):
    """Las funciones mca_* del binding, con h._via == 'c' (libmca por ctypes).

    Devuelve (ops, handle) o lanza NotImplementedError con el motivo. Con
    --fake el handle es FakeMCA, que corre la misma lógica de C contra su
    modelo Python; con --shm (`shm` es la ruta del fichero), el backend devmem
    sobre ese fichero.
    """
    import API.mca as A
    if getattr(A.MCA, 'impl', None) != 'c':
        raise NotImplementedError('el binding del MCA todavía no está en C '
                                  '(fase 1): sólo se miden las bus.*')
    if fake:
        from API.mca_remote import FakeMCA
        h = FakeMCA()
    elif shm:
        h = A.MCA._sobre_bus(_libmca.Bus.archivo(shm, 0, ref.MCA_SIZE))
    else:
        h = A.mca_open(impl='c')
    campo0 = A.mca_get_amp_max(h)
    ops = {
        'api.get_campo':  lambda: A.mca_get_amp_max(h),
        'api.set_campo':  lambda: A.mca_set_amp_max(h, campo0),
        'api.get_config': lambda: A.mca_get_config(h),
        'api.counters':   lambda: A.mca_read_counters(h),
        'api.last_event': lambda: A.mca_read_last_event(h),
        'api.identify':   lambda: A.mca_identify(h, verbose=False),
        'api.spectrum':   lambda: A.mca_read_histogram(h),
    }
    if h.caps & A.CAP_HIST_H_PSD:
        ops['api.map2d'] = lambda: A.mca_read_map2d(h)
    if destructivo:
        ops['api.clear'] = lambda: A.mca_clear(h)
        ops['api.configure'] = lambda: A.mca_configure(h)
        ops['api.acquire0'] = lambda: A.mca_read_acquire(h, 0)
    return ops, h


def _c_puro(presupuesto_s, destructivo):
    """Corre el bench en C sin intérprete y devuelve su JSON, o lanza el motivo."""
    exe = os.path.join(_RAIZ, 'libmca', 'build', platform.machine(),
                       'bench_libmca')
    if not os.path.exists(exe):
        raise NotImplementedError(f'no existe {exe} (make -C libmca bench, '
                                  'fase 1)')
    r = subprocess.run([exe, '--presupuesto', str(presupuesto_s)]
                       + (['--destructivo'] if destructivo else []),
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        pista = ('. Si es la glibc (el cruzado pide GLIBC_2.34), compilarlo en '
                 'la placa: make -C libmca placa-lib'
                 if 'GLIBC' in r.stderr else '')
        raise RuntimeError(f'{exe} falló ({r.returncode}): '
                           f'{r.stderr.strip()}{pista}')
    return json.loads(r.stdout)


def _abrir_placa():
    """El handle de referencia del mapa que tenga la placa: MCA2, o MCA1 con la
    referencia congelada (y entonces libmca no aplica)."""
    global ref
    try:
        return ref.MCA.open()
    except ref.MCANotPresent as e:
        if 'MCA1' not in str(e):
            raise
        ref = ref_mca1
        return ref.MCA.open()


def _abrir_shm():
    """El MCA de --shm: (ruta, handle de referencia sobre su mmap).

    Un fichero de MCA_SIZE bytes con el magic, CAPS y WIDTHS en su lugar y
    cuentas fijas (semilla 0) en las dos aperturas, para que la igualdad bit a
    bit entre implementaciones compare algo distinto de ceros.
    """
    d = '/dev/shm' if os.path.isdir('/dev/shm') else tempfile.gettempdir()
    fd, ruta = tempfile.mkstemp(prefix='bench_impl_mca_', suffix='.bin', dir=d)
    os.ftruncate(fd, ref.MCA_SIZE)
    m = mmap.mmap(fd, ref.MCA_SIZE)
    h_aw, h2_aw, psd_aw = SHM_AW
    # Es memoria común: acá pack_into y los slices grandes no tienen problema.
    struct.pack_into('<III', m, ref.R_MAGIC, ref.MAGIC, SHM_CAPS,
                     h_aw | h2_aw << 8 | psd_aw << 16)
    struct.pack_into('<I', m, ref.R_N_ACC_MAX, 4)
    rng = np.random.default_rng(0)
    for off, n in ((ref.APERTURE_H, 1 << h_aw),
                   (ref.APERTURE_2D, 1 << (h2_aw + psd_aw))):
        m[off:off + 4 * n] = rng.integers(0, 1000, n, dtype='<u4').tobytes()
    return ruta, ref.MCA(m, fd, SHM_CAPS, h_aw, h2_aw, psd_aw)


# =============================================================================
# Entorno
# =============================================================================

def _leer(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _commit():
    """El commit del software medido. En la placa no hay .git: lo pasa make."""
    env = os.environ.get('MCA_COMMIT')
    if env:
        return env
    try:
        sha = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'],
                             cwd=_RAIZ, capture_output=True, text=True,
                             timeout=5).stdout.strip()
        sucio = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', '.'],
                               cwd=_RAIZ, timeout=5).returncode != 0
        return (sha + ('-sucio' if sucio else '')) or None
    except (OSError, subprocess.SubprocessError):
        return None


def _md5(path):
    try:
        with open(path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except OSError:
        return None


def _ultimo_programado():
    """El nombre del último bitstream que programó el kernel, según dmesg.

    La PL no dice qué tiene cargado, pero el FPGA manager deja una línea
    "writing <nombre> to Xilinx Zynq FPGA Manager" cada vez. Sólo el nombre:
    el md5 se toma del fichero con ese nombre junto al de por defecto, si está.
    """
    try:
        r = subprocess.run(['dmesg'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None, None
    nombres = [ln.split('writing ', 1)[1].split(' to ', 1)[0]
               for ln in r.stdout.splitlines()
               if 'fpga_manager' in ln and 'writing ' in ln]
    if not nombres:
        return None, None
    ruta = os.path.join(os.path.dirname(BITSTREAM_DEFAULT), nombres[-1])
    return nombres[-1], _md5(ruta)


def entorno(h, fake, shm=False):
    from API import fpga
    cpu = '/sys/devices/system/cpu/cpu0/cpufreq'
    sin_pl = fake or shm
    programado, programado_md5 = (None, None) if sin_pl else _ultimo_programado()
    e = {
        'formato':        FORMATO,
        't_wall':         time.time(),
        'fecha':          time.strftime('%Y-%m-%d %H:%M:%S'),
        'commit':         _commit(),
        'fake':           fake,
        # dónde está "el MCA": la PL, un fichero en memoria o FakeMCA
        'medio':          'fake' if fake else 'shm' if shm else 'pl',
        'host':           platform.node(),
        'machine':        platform.machine(),
        'python':         platform.python_version(),
        'numpy':          np.__version__,
        'libmca_version': _libmca.version() if _libmca.disponible() else None,
        'libmca_build':   _libmca.build() if _libmca.disponible() else None,
        'libmca_motivo':  None if _libmca.disponible() else _libmca.motivo(),
        'cpu_governor':   _leer(f'{cpu}/scaling_governor'),
        'cpu_khz':        _leer(f'{cpu}/scaling_cur_freq'),
        'loadavg':        _leer('/proc/loadavg'),
        'gc':             'apagado durante cada medición',
        'placa':          None if fake else fpga.modelo_de_placa(),
        'fpga_state':     None if sin_pl else fpga.fpga_state(),
        # El fichero por defecto, NO necesariamente el cargado: la PL no dice
        # qué bitstream tiene. El último programado sale de dmesg (sólo el
        # nombre). Lo que identifica al MCA cargado son el magic, CAPS y
        # WIDTHS, que van abajo.
        'bitstream_default':     BITSTREAM_DEFAULT,
        'bitstream_default_md5': None if sin_pl else _md5(BITSTREAM_DEFAULT),
        'bitstream_programado':     programado,
        'bitstream_programado_md5': programado_md5,
        'mca_magic':  None if sin_pl else int(h.r32(ref.R_MAGIC)),
        'mapa':       'MCA1' if ref is ref_mca1 else 'MCA2',
        'mca_caps':   int(h.caps),
        'mca_widths': {'h_aw': h.h_aw, 'h2_aw': h.h2_aw, 'psd_aw': h.psd_aw},
        'mca_running': bool(ref.mca_get_running(h)),
    }
    return e


# =============================================================================
# Configuración: foto y restauración (para --destructivo)
# =============================================================================

def foto_config(h):
    """Las palabras crudas de los registros de configuración, menos R_CTRL.

    R_CTRL lleva el bit de run y el de clear, que no son configuración: se
    restaura sólo su campo `channel`, por read-modify-write.
    """
    offs = sorted({off for off, _, _ in ref._CAMPOS.values()} - {ref.R_CTRL})
    return ({off: h.r32(off) for off in offs}, ref.mca_get_channel(h))


def restaurar_config(h, foto):
    palabras, canal = foto
    for off, v in palabras.items():
        h.w32(off, v)
    ref.mca_set_channel(h, canal)


# =============================================================================
# Main
# =============================================================================

def _correr_remoto(args, out):
    """La columna `remoto`: las funciones de la API desde la PC, por `call`."""
    import API.mca as A
    from API.mca_net import PORT_DEFAULT
    from API.mca_remote import MCARemote
    host, _, puerto = args.remoto.partition(':')
    h = MCARemote.connect(host, int(puerto) if puerto else PORT_DEFAULT)
    info = h.info
    campo0 = A.mca_get_amp_max(h)
    w_campo = h.r32(A.R_AMP_MAX)
    ops = {
        'bus.r32':        lambda: h.r32(A.R_MAGIC),
        'bus.w32':        lambda: h.w32(A.R_AMP_MAX, w_campo),
        'api.get_campo':  lambda: A.mca_get_amp_max(h),
        'api.set_campo':  lambda: A.mca_set_amp_max(h, campo0),
        'api.get_config': lambda: A.mca_get_config(h),
        'api.counters':   lambda: A.mca_read_counters(h),
        'api.last_event': lambda: A.mca_read_last_event(h),
        'api.identify':   lambda: A.mca_identify(h, verbose=False),
        'api.spectrum':   lambda: A.mca_read_histogram(h),
    }
    if h._has_2d:
        ops['api.map2d'] = lambda: A.mca_read_map2d(h)
    if args.destructivo:
        ops['api.clear'] = lambda: A.mca_clear(h)
        ops['api.configure'] = lambda: A.mca_configure(h)
    resumen = {'entorno': {
        'formato': FORMATO, 't_wall': time.time(),
        'fecha': time.strftime('%Y-%m-%d %H:%M:%S'), 'commit': _commit(),
        'fake': bool(info.get('fake')), 'medio': 'remoto', 'host': args.remoto,
        'machine': platform.machine(), 'python': platform.python_version(),
        'numpy': np.__version__, 'protocolo': info.get('protocol'),
        'impl_placa': info.get('impl'), 'libmca_version': info.get('libmca_version'),
        'mca_caps': int(h.caps),
        'mca_widths': {'h_aw': h.h_aw, 'h2_aw': h.h2_aw, 'psd_aw': h.psd_aw},
        'mca_magic': int(info.get('magic', 0))}, 'ops': {},
        'no_disponible': {}, 'igualdad': {}}
    crudos = {}
    try:
        for nombre, fn in ops.items():
            us = medir(fn, args.presupuesto)
            crudos[f'remoto/{nombre}'] = us
            resumen['ops'].setdefault(nombre, {})['remoto'] = estadistica(us)
            print(f'  remoto  {nombre:20s} {np.median(us):12.2f} µs  '
                  f'(n={us.size})', flush=True)
    finally:
        h.close()
    with open(os.path.join(out, 'resumen.json'), 'w') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    np.savez(os.path.join(out, 'resultados.npz'), **crudos)
    print(f'datos en {out}/')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', default=None,
                    help='directorio de salida (default datos/bench_impl_<fecha>)')
    ap.add_argument('--impl', default='py,c,c_puro',
                    help='implementaciones, separadas por coma')
    ap.add_argument('--presupuesto', type=float, default=1.0,
                    help='segundos por operación e implementación (default 1)')
    ap.add_argument('--destructivo', action='store_true',
                    help='mide también clear, configure y acquire(0): BORRA el '
                         'histograma')
    ap.add_argument('--fake', action='store_true',
                    help='contra FakeMCA, sin placa: prueba el script, los '
                         'números no significan nada')
    ap.add_argument('--shm', action='store_true',
                    help='sin PL: el MCA es un fichero en /dev/shm. Mide el '
                         'costo de cada implementación sin el del bus; '
                         'incluye las destructivas')
    ap.add_argument('--remoto', metavar='HOST[:PUERTO]', default=None,
                    help='desde la PC, contra mca_server.py: la columna remoto')
    args = ap.parse_args(argv)
    impls = [i.strip() for i in args.impl.split(',') if i.strip()]
    if sum(bool(x) for x in (args.fake, args.shm, args.remoto)) > 1:
        ap.error('--fake, --shm y --remoto son excluyentes')

    out = args.out or os.path.join(
        'datos', ('bench_shm_' if args.shm else 'bench_remoto_' if args.remoto
                  else 'bench_impl_') + time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(out, exist_ok=True)
    if args.remoto:
        return _correr_remoto(args, out)

    shm = None
    if args.fake:
        from API.mca_remote import FakeMCA
        h = FakeMCA()
    elif args.shm:
        shm, h = _abrir_shm()
        args.destructivo = True             # no hay nada que borrar
    else:
        h = _abrir_placa()

    if args.destructivo and ref.mca_get_running(h):
        print('el MCA está corriendo: --destructivo borraría una adquisición '
              'en curso. Pararlo antes (mca_stop).', file=sys.stderr)
        return 2

    resumen = {'entorno': entorno(h, args.fake, bool(shm)), 'ops': {},
               'no_disponible': {}, 'igualdad': {}}
    crudos = {}
    foto = foto_config(h) if args.destructivo else None

    def registrar(impl, ops):
        for nombre, fn in ops.items():
            us = medir(fn, args.presupuesto)
            crudos[f'{impl}/{nombre}'] = us
            resumen['ops'].setdefault(nombre, {})[impl] = estadistica(us)
            print(f'  {impl:7s} {nombre:20s} {np.median(us):12.2f} µs  '
                  f'(n={us.size})', flush=True)

    bus = None
    h_c = None
    try:
        ops_py, leer_bloque = _ops_py(h, args.destructivo)
        if 'py' in impls:
            registrar('py', ops_py)

        if 'c' in impls and ref is ref_mca1:
            resumen['no_disponible']['c'] = ('la placa tiene el MCA1 y libmca '
                                             'habla MCA2')
        elif 'c' in impls:
            if not _libmca.disponible():
                resumen['no_disponible']['c'] = _libmca.motivo()
            else:
                if args.fake:
                    bus = _libmca.Bus.callbacks(h.r32, h.w32)
                elif shm:
                    bus = _libmca.Bus.archivo(shm, 0, ref.MCA_SIZE)
                else:
                    bus = _libmca.Bus.devmem(ref.MCA_PHYS, ref.MCA_SIZE)
                registrar('c', _ops_c_bus(bus, h))
                try:
                    ops_c, h_c = _ops_c_api(args.destructivo, args.fake, shm)
                    registrar('c', ops_c)
                except NotImplementedError as e:
                    resumen['no_disponible']['c.api'] = str(e)

                # Igualdad bit a bit de los bloques: sólo vale con el MCA
                # parado, si no los dos lados leen histogramas distintos.
                if ref.mca_get_running(h):
                    resumen['igualdad']['nota'] = ('MCA corriendo: no se '
                                                   'compara')
                else:
                    pares = [('bus.read_words_h', ref.APERTURE_H,
                              1 << h.h_aw)]
                    if h.caps & ref.CAP_HIST_H_PSD:
                        pares.append(('bus.read_words_2d', ref.APERTURE_2D,
                                      1 << (h.h2_aw + h.psd_aw)))
                    for nombre, off, n in pares:
                        a = leer_bloque(off, n)
                        b = bus.read_words(off, n)
                        resumen['igualdad'][nombre] = {
                            'iguales': bool(np.array_equal(a, b)),
                            'n': int(n), 'suma': int(a.sum(dtype=np.uint64))}

        if 'c_puro' in impls and ref is ref_mca1:
            resumen['no_disponible']['c_puro'] = ('la placa tiene el MCA1 y '
                                                  'libmca habla MCA2')
        elif 'c_puro' in impls and shm:
            resumen['no_disponible']['c_puro'] = ('abre /dev/mem: con --shm '
                                                  'no se mide')
        elif 'c_puro' in impls:
            try:
                puro = _c_puro(args.presupuesto, args.destructivo)
                for nombre, st in puro.get('ops', {}).items():
                    resumen['ops'].setdefault(nombre, {})['c_puro'] = st
            except (NotImplementedError, RuntimeError) as e:
                resumen['no_disponible']['c_puro'] = str(e)
    finally:
        if foto is not None:
            restaurar_config(h, foto)
        if bus is not None:
            bus.close()
        if h_c is not None:
            h_c.close()
        h.close()
        if shm:
            os.unlink(shm)

    with open(os.path.join(out, 'resumen.json'), 'w') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    np.savez(os.path.join(out, 'resultados.npz'), **crudos)
    for k, v in resumen['no_disponible'].items():
        print(f'  no disponible: {k}: {v}')
    print(f'datos en {out}/')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
