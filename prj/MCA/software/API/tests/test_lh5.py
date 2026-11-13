#!/usr/bin/env python3
"""Los eventos del osciloscopio en LH5. NO necesita la placa.

Sin `h5py` se saltean, salvo el mensaje de error que dice cómo instalarlo. Los que usan
el lector oficial, que es lo que prueba que el archivo es LH5 de verdad, necesitan
además `legend-lh5io` (`import lh5`).

Correr:  python3 -m pytest API/tests/test_lh5.py -v
"""

import json
import os
import subprocess
import sys
import threading

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API.osciloscope_store import (AcquisitionSession, ChunkWriter,  # noqa: E402
                                   ConstantAnnotator, EventBatch, FakeSource,
                                   archivos_de_corrida, load_chunk)
from API.osciloscope_store import formato_lh5                        # noqa: E402
from API.osciloscope_store.events import BASE_FIELDS                 # noqa: E402

PRE, POST = 8, 24
S = PRE + POST
DT_NS = 8.0
SCALE = 8192


def _h5py():
    return pytest.importorskip('h5py')


def _lector():
    _h5py()
    return pytest.importorskip('lh5')


def _batch(n=16, n_ch=2, capacidad=32, campos=BASE_FIELDS):
    """Un lote con datos que se distinguen por evento, canal y muestra."""
    b = EventBatch(capacidad, n_ch, S, campos)
    for i in range(n):
        for k in range(n_ch):
            b.wave[i, k] = (i + 1) * 0.01 * (1 if k == 0 else -1) + np.arange(S) * 1e-3
        b.t_ns[i] = 1_000_000 + i * 90_000
        b.wp[i] = i * 137
        b.snap[i] = 2
        b.gap[i] = i % 3
    b.n = n
    return b


def _escritor(tmp_path, formato, n_ch=2, compress=False, **meta):
    base = dict(channels=list(range(1, n_ch + 1)),
                source=dict(pre=PRE, post=POST, dt_ns=DT_NS, samples=S, n_ch=n_ch),
                **meta)
    return ChunkWriter(tmp_path, None, None,
                       dict(n_read=0, n_dropped=0, n_timeouts=0, n_written=0, chunks=0),
                       meta_base=base, formato=formato, wave_scale=SCALE,
                       compress=compress)


def _un_archivo(tmp_path, formato='lh5', batch=None, n_ch=2, **kw):
    w = _escritor(tmp_path, formato, n_ch=n_ch, **kw)
    w._write(batch if batch is not None else _batch(n_ch=n_ch))
    return archivos_de_corrida(tmp_path)[-1]


def _corrida(tmp_path, n_ch=2, n_eventos=200, capacidad=64, annotators=(), **kw):
    src = FakeSource(pre=PRE, post=POST, n_ch=n_ch, rate_hz=20000.0,
                     n_events=n_eventos)
    with AcquisitionSession(src, tmp_path, capacity=capacidad, ram_budget_mb=1,
                            annotators=annotators, verbose=False, formato='lh5',
                            **kw) as s:
        s.wait(duration_s=30, poll_s=0.01)
    return s


# -----------------------------------------------------------------------------
# Sin h5py: lo dice antes de empezar
# -----------------------------------------------------------------------------

def test_sin_h5py_la_sesion_falla_al_crearse_y_dice_como_instalarlo(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'h5py', None)
    src = FakeSource(pre=PRE, post=POST, n_events=10)
    with pytest.raises(ImportError, match='pip3 install h5py'):
        AcquisitionSession(src, tmp_path, capacity=16, ram_budget_mb=1, verbose=False,
                           formato='lh5')
    assert not archivos_de_corrida(tmp_path)


def test_sin_h5py_el_npz_sigue_andando(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'h5py', None)
    src = FakeSource(pre=PRE, post=POST, rate_hz=20000.0, n_events=20)
    with AcquisitionSession(src, tmp_path, capacity=16, ram_budget_mb=1,
                            verbose=False) as s:
        s.wait(duration_s=10, poll_s=0.01)
    assert s.stats['n_written'] == 20
    assert all(f.endswith('.npz') for f in archivos_de_corrida(tmp_path))


def test_formato_desconocido():
    with pytest.raises(ValueError, match='hdf5'):
        ChunkWriter('/tmp', None, None, {}, formato='hdf5')


def test_el_default_sigue_siendo_npz():
    src = FakeSource(pre=PRE, post=POST)
    import inspect
    assert inspect.signature(AcquisitionSession).parameters['formato'].default == 'npz'
    assert src.meta()['dt_ns'] == DT_NS


def test_la_fuente_tiene_que_declarar_pre_y_dt(tmp_path):
    _h5py()
    with pytest.raises(ValueError, match='dt_ns'):
        ChunkWriter(tmp_path, None, None, {}, formato='lh5',
                    meta_base={'source': {'pre': 8}})


# -----------------------------------------------------------------------------
# archivos_de_corrida
# -----------------------------------------------------------------------------

def test_archivos_de_corrida_encuentra_los_dos_formatos_y_no_los_tmp(tmp_path):
    for n in ('evt_000001.lh5', 'evt_000000.lh5', 'evt_000002.lh5.tmp',
              'chunk_000000.npz', 'chunk_000001.npz.tmp', 'run_summary.json',
              'otro.npz'):
        (tmp_path / n).write_bytes(b'')
    assert [os.path.basename(f) for f in archivos_de_corrida(tmp_path)] == [
        'chunk_000000.npz', 'evt_000000.lh5', 'evt_000001.lh5']


# -----------------------------------------------------------------------------
# load_chunk da lo mismo con los dos formatos
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('n_ch', [1, 2, 4])
def test_load_chunk_da_lo_mismo_que_el_npz(tmp_path, n_ch):
    _h5py()
    a, b = tmp_path / 'npz', tmp_path / 'lh5'
    os.makedirs(a)
    os.makedirs(b)
    batch = _batch(n_ch=n_ch)
    arr_n, meta_n = load_chunk(_un_archivo(a, 'npz', batch=batch, n_ch=n_ch))
    arr_l, meta_l = load_chunk(_un_archivo(b, 'lh5', batch=batch, n_ch=n_ch))

    assert set(arr_l) == set(arr_n)
    for k in arr_n:
        assert arr_l[k].dtype == arr_n[k].dtype, k
        assert np.array_equal(arr_l[k], arr_n[k]), k
    distintos = {'t_wall'}          # el reloj del momento de escribir
    assert ({k: v for k, v in meta_l.items() if k not in distintos}
            == {k: v for k, v in meta_n.items() if k not in distintos})
    assert meta_l['schema_version'] == 2
    assert arr_l['wave'].dtype == np.int16


def test_la_onda_vuelve_en_cuentas_y_en_volts(tmp_path):
    _h5py()
    batch = _batch()
    arr, _ = load_chunk(_un_archivo(tmp_path, batch=batch))
    esperado = np.rint(batch.wave[:batch.n] * SCALE).astype(np.int16)
    assert np.array_equal(arr['wave'], esperado)
    np.testing.assert_allclose(arr['wave_V'], esperado / SCALE)
    assert np.array_equal(arr['d1'], arr['wave_V'][:, 0, :])
    assert np.array_equal(arr['d2'], arr['wave_V'][:, 1, :])


# -----------------------------------------------------------------------------
# El archivo, mirado con h5py
# -----------------------------------------------------------------------------

def test_la_estructura_es_la_del_formato(tmp_path):
    """Es lo que protege el formato donde no está el lector oficial: la placa."""
    h5py = _h5py()
    with h5py.File(_un_archivo(tmp_path), 'r') as f:
        raw = f['raw']
        assert raw.attrs['datatype'] == 'table{t_ns,wp,snap,gap,waveform_in1,waveform_in2}'
        assert f['meta'].attrs['datatype'] == 'string'
        assert raw['t_ns'].attrs['datatype'] == 'array<1>{real}'
        assert raw['t_ns'].attrs['units'] == 'ns'
        assert 'units' not in raw['wp'].attrs
        assert raw['gap'].dtype == np.uint8
        for nombre in ('waveform_in1', 'waveform_in2'):
            w = raw[nombre]
            assert w.attrs['datatype'] == 'table{t0,dt,values}'
            assert w['values'].attrs['datatype'] == 'array_of_equalsized_arrays<1,1>{real}'
            assert w['values'].shape == (16, S)
            assert w['values'].dtype == np.int16
            assert w['t0'].dtype == w['dt'].dtype == np.float32
            assert w['t0'].attrs['units'] == w['dt'].attrs['units'] == 'ns'
            assert (w['t0'][()] == -PRE * DT_NS).all()
            assert (w['dt'][()] == DT_NS).all()


def test_sin_comprimir_es_contiguo_y_comprimido_es_gzip(tmp_path):
    h5py = _h5py()
    a, b = tmp_path / 'a', tmp_path / 'b'
    os.makedirs(a)
    os.makedirs(b)
    batch = _batch(n=32)
    ra, rb = _un_archivo(a, batch=batch), _un_archivo(b, batch=batch, compress=True)
    with h5py.File(ra, 'r') as f:
        d = f['raw/waveform_in1/values']
        assert d.chunks is None and d.compression is None
    with h5py.File(rb, 'r') as f:
        assert f['raw/waveform_in1/values'].compression == 'gzip'
    assert np.array_equal(load_chunk(ra)[0]['wave'], load_chunk(rb)[0]['wave'])


def test_la_metadata_es_json_legible_con_numpy_adentro(tmp_path):
    h5py = _h5py()
    ruta = _un_archivo(tmp_path, entero=np.int32(7), real=np.float32(0.5),
                       arreglo=np.arange(3), raro=object())
    with h5py.File(ruta, 'r') as f:
        v = f['meta'][()]
    m = json.loads(v.decode() if isinstance(v, bytes) else v)
    assert m['entero'] == 7 and m['real'] == 0.5 and m['arreglo'] == [0, 1, 2]
    assert 'object' in m['raro']         # queda como texto: no tira abajo la corrida
    assert m['chunk_events'] == 16 and m['channels'] == [1, 2]


# -----------------------------------------------------------------------------
# De punta a punta, por el lector y el escritor reales
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('n_ch', [1, 2])
def test_corrida_completa(tmp_path, n_ch):
    _h5py()
    s = _corrida(tmp_path, n_ch=n_ch)
    archivos = archivos_de_corrida(tmp_path)
    assert archivos and all(os.path.basename(f).startswith('evt_') for f in archivos)
    assert s.stats['n_read'] + s.stats['n_dropped'] == 200

    n = 0
    for f in archivos:
        arr, meta = load_chunk(f)
        assert arr['wave'].shape[1:] == (n_ch, S)
        assert ('d2' in arr) == (n_ch == 2)
        assert meta['chunk_events'] == len(arr['t_ns'])
        n += len(arr['t_ns'])
    assert n == s.stats['n_written'] == s.stats['n_read']
    with open(tmp_path / 'run_summary.json') as fh:
        assert json.load(fh)['formato'] == 'lh5'


def test_el_annotator_llega_como_columna(tmp_path):
    h5py = _h5py()
    _corrida(tmp_path, n_eventos=40, capacidad=16,
             annotators=(ConstantAnnotator(temp_C=21.5),))
    archivo = archivos_de_corrida(tmp_path)[0]
    with h5py.File(archivo, 'r') as f:
        assert 'temp_C,waveform_in1' in f['raw'].attrs['datatype']
    arr, meta = load_chunk(archivo)
    assert (arr['temp_C'] == 21.5).all()
    assert 'temp_C' in meta['fields']


# -----------------------------------------------------------------------------
# Atomicidad
# -----------------------------------------------------------------------------

def test_un_tmp_nunca_queda_visible(tmp_path):
    """Todo lo que se ve durante la corrida se puede abrir: un file pusher depende de eso."""
    _h5py()
    vistos, errores = set(), []
    fin = threading.Event()

    def mirar():
        while not fin.is_set():
            for f in archivos_de_corrida(tmp_path):
                if f not in vistos:
                    try:
                        load_chunk(f)
                        vistos.add(f)
                    except Exception as e:                     # noqa: BLE001
                        errores.append((f, repr(e)))

    th = threading.Thread(target=mirar)
    th.start()
    try:
        _corrida(tmp_path, n_eventos=400, capacidad=32)
    finally:
        fin.set()
        th.join()
    assert not errores
    assert vistos
    assert not [f for f in os.listdir(tmp_path) if f.endswith('.tmp')]


def test_si_falla_la_escritura_no_queda_nada(tmp_path, monkeypatch):
    _h5py()
    w = _escritor(tmp_path, 'lh5')

    def romper(*a, **k):
        raise OSError('disco lleno')
    monkeypatch.setattr(formato_lh5.np, 'full', romper)     # a mitad del archivo
    with pytest.raises(OSError, match='disco lleno'):
        w._write(_batch())
    assert os.listdir(tmp_path) == []


# -----------------------------------------------------------------------------
# El bench de la placa corre
# -----------------------------------------------------------------------------

def test_el_bench_de_escritura_corre(tmp_path):
    programa = os.path.join(_RAIZ, 'API', 'bench', 'bench_escritura.py')
    r = subprocess.run([sys.executable, programa, '--dir', str(tmp_path), '--reps', '2',
                        '--capacidad', '64'], capture_output=True, text=True, timeout=120)
    try:
        import h5py                                                # noqa: F401
    except ImportError:
        assert r.returncode == 1 and 'FALTA h5py' in r.stdout, r.stdout + r.stderr
    else:
        assert r.returncode == 0 and 'lh5 ' in r.stdout, r.stdout + r.stderr
    assert 'npz ' in r.stdout
    assert os.listdir(tmp_path) == []         # no deja nada: corre sobre la microSD


# -----------------------------------------------------------------------------
# El lector oficial: esto es lo que prueba que es LH5
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('n_ch', [1, 2])
def test_el_lector_oficial_lo_abre(tmp_path, n_ch):
    lh5 = _lector()
    batch = _batch(n_ch=n_ch)
    ruta = _un_archivo(tmp_path, batch=batch, n_ch=n_ch)
    t = lh5.read('raw', ruta)
    assert type(t).__name__ == 'Table' and len(t) == 16

    esperado = np.rint(batch.wave[:16] * SCALE).astype(np.int16)
    for k in range(n_ch):
        w = t[f'waveform_in{k + 1}']
        assert type(w).__name__ == 'WaveformTable'
        assert np.array_equal(w['values'].nda, esperado[:, k, :])
        assert (w['t0'].nda == -PRE * DT_NS).all()
        assert (w['dt'].nda == DT_NS).all()
    assert (f'waveform_in{n_ch + 1}' in t) is False
    assert np.array_equal(t['t_ns'].nda, batch.t_ns[:16])
    assert np.array_equal(t['gap'].nda, batch.gap[:16])

    meta = json.loads(lh5.read('meta', ruta).value)
    assert meta['chunk_events'] == 16 and meta['channels'] == list(range(1, n_ch + 1))


def test_el_lector_oficial_junta_varios_archivos(tmp_path):
    lh5 = _lector()
    _corrida(tmp_path, n_eventos=200, capacidad=64)
    archivos = archivos_de_corrida(tmp_path)
    assert len(archivos) > 1
    t = lh5.read('raw', archivos)
    uno_por_uno = [load_chunk(f)[0] for f in archivos]
    assert len(t) == sum(len(a['t_ns']) for a in uno_por_uno)
    assert np.array_equal(t['waveform_in2']['values'].nda,
                          np.concatenate([a['wave'][:, 1, :] for a in uno_por_uno]))


def test_el_lector_oficial_abre_el_comprimido_y_los_annotators(tmp_path):
    lh5 = _lector()
    _corrida(tmp_path, n_eventos=40, capacidad=64, compress=True,
             annotators=(ConstantAnnotator(temp_C=21.5),))
    t = lh5.read('raw', archivos_de_corrida(tmp_path)[0])
    assert (t['temp_C'].nda == 21.5).all()
    assert t['waveform_in1']['values'].nda.shape[1] == S


def test_lh5concat_los_une(tmp_path):
    lh5 = _lector()
    programa = os.path.join(os.path.dirname(sys.executable), 'lh5concat')
    if not os.path.exists(programa):
        pytest.skip('lh5concat no está junto a este python')
    _corrida(tmp_path, n_eventos=200, capacidad=64)
    archivos = archivos_de_corrida(tmp_path)
    salida = tmp_path / 'junto.lh5'
    subprocess.run([programa, '-o', str(salida), '--include', 'raw*', *archivos],
                   check=True, capture_output=True)
    t = lh5.read('raw', str(salida))
    uno_por_uno = [load_chunk(f)[0] for f in archivos]
    assert np.array_equal(t['t_ns'].nda,
                          np.concatenate([a['t_ns'] for a in uno_por_uno]))
    assert np.array_equal(t['waveform_in1']['values'].nda,
                          np.concatenate([a['wave'][:, 0, :] for a in uno_por_uno]))
