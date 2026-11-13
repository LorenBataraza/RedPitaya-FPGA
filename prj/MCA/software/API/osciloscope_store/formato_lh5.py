"""LH5: los eventos del osciloscopio en el formato HDF5 de LEGEND.

Un archivo por lote, `evt_%06d.lh5`:

    /raw            table{t_ns,wp,snap,gap,<annotators>,waveform_in1[,waveform_in2]}
      waveform_inN  table{t0,dt,values}
        t0, dt      float32, en ns. t0 = -pre*dt: el disparo es el tiempo 0
        values      array_of_equalsized_arrays<1,1>{real}: las cuentas, como `wave`
    /meta           string, JSON (en el .npz es un pickle)

El lector oficial (`pip install legend-lh5io`) lo abre sin saber nada de este proyecto:

    import lh5
    t = lh5.read('raw', archivos)       # varios a la vez, como una sola tabla
    t['waveform_in1']['values'].nda     # (eventos, muestras)

La placa no lo necesita: `leer` usa sólo `h5py`, igual que `escribir`. `h5py` se importa
adentro para que el resto del pipeline siga funcionando donde no esté.

**Por qué directo al archivo, y no armado en RAM y volcado de una.** `h5py` suelta el
GIL durante el I/O de HDF5: con cada escritura frenada 50 ms, el hilo lector no se
frenó más de 5.5 ms (h5py 3.16, PC). Armarlo en RAM no ahorra tiempo, y usa más memoria.
Comprobarlo en la placa: `API/bench/bench_escritura.py`.
"""

import json
import re

import numpy as np

_TIPO_COLUMNA = 'array<1>{real}'
_TIPO_ONDA = 'array_of_equalsized_arrays<1,1>{real}'
_PREFIJO_ONDA = 'waveform_in'


def exigir_h5py():
    """El módulo, o un error que dice qué hacer. Lo llama quien crea la sesión: un
    `ImportError` en el hilo escritor recién se vería con la corrida empezada."""
    try:
        import h5py
    except ImportError as e:
        raise ImportError(
            "formato='lh5' necesita h5py y no está. Instalarlo con "
            "'pip3 install h5py' o 'apt install python3-h5py'. Mientras tanto, "
            "formato='npz' funciona sin él.") from e
    return h5py


def _a_json(v):
    """Lo que `json` no conoce. La metadata no puede tirar abajo al hilo escritor en
    medio de una corrida, así que lo que no se sabe convertir queda como texto."""
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.ndarray):
        return v.tolist()
    return str(v)


def escribir(path, payload, meta, pre, dt_ns, comprimir=False):
    """`payload` es el de `EventBatch.payload()`: `wave` y una columna por campo.

    Datasets contiguos y sin comprimir por defecto: es lo más rápido de escribir. Con
    `comprimir`, gzip, que el lector resuelve solo.
    """
    h5py = exigir_h5py()
    opciones = {'compression': 'gzip'} if comprimir else {}

    def columna(grupo, nombre, datos, tipo=_TIPO_COLUMNA, units=None):
        d = grupo.create_dataset(nombre, data=datos, **opciones)
        d.attrs['datatype'] = tipo
        if units:
            d.attrs['units'] = units

    wave = payload['wave']
    n, n_ch, _ = wave.shape
    canales = meta.get('channels') or range(1, n_ch + 1)
    escalares = [k for k in payload if k != 'wave']
    ondas = [f'{_PREFIJO_ONDA}{ch}' for ch in canales]

    with h5py.File(path, 'w') as f:
        raw = f.create_group('raw')
        raw.attrs['datatype'] = 'table{' + ','.join(escalares + ondas) + '}'
        for k in escalares:
            columna(raw, k, payload[k], units='ns' if k.endswith('_ns') else None)
        for i, nombre in enumerate(ondas):
            g = raw.create_group(nombre)
            g.attrs['datatype'] = 'table{t0,dt,values}'
            columna(g, 't0', np.full(n, -pre * dt_ns, dtype=np.float32), units='ns')
            columna(g, 'dt', np.full(n, dt_ns, dtype=np.float32), units='ns')
            columna(g, 'values', wave[:, i, :], tipo=_TIPO_ONDA)
        d = f.create_dataset('meta', data=json.dumps(meta, default=_a_json))
        d.attrs['datatype'] = 'string'


def _texto(v):
    return v.decode() if isinstance(v, bytes) else str(v)


def leer(path):
    """(columnas, meta), con `wave` armada como en el `.npz`: (eventos, canal, muestra)."""
    h5py = exigir_h5py()
    with h5py.File(path, 'r') as f:
        meta = json.loads(_texto(f['meta'][()]))
        raw = f['raw']
        m = re.fullmatch(r'table\{(.*)\}', _texto(raw.attrs['datatype']))
        if m is None:
            raise ValueError(f'{path}: /raw no es una tabla LH5')
        out, ondas = {}, []
        for nombre in m[1].split(','):
            if nombre.startswith(_PREFIJO_ONDA):
                ondas.append(raw[nombre]['values'][()])
            else:
                out[nombre] = raw[nombre][()]
    if not ondas:
        raise ValueError(f'{path}: /raw no tiene ninguna {_PREFIJO_ONDA}N')
    out['wave'] = np.stack(ondas, axis=1)
    return out, meta
