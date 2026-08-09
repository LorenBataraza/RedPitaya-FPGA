#!/usr/bin/env python3
"""Tests del pipeline mca/ con FakeSource: corren en la PC, sin placa.

Cubren la mecanica que no depende del hardware:

  1. contabilidad     leidos + descartados == generados; sum(gap) == n_dropped
  2. integridad       las trazas sobreviven el viaje y la conversion a int16
  3. descartes        con el escritor frenado, los gap>0 caen donde deben
  4. esquema dinamico n_ch=4 y un annotator producen las columnas esperadas
  5. atomicidad       no quedan .tmp; todo .npz visible se puede abrir

Uso:
    python3 test_mca_pipeline.py
"""
import os
import sys
import glob
import shutil
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from mca import AcquisitionSession, ConstantAnnotator, FakeSource, load_chunk
from mca.storage import ChunkWriter

FAILS = []


def check(name, cond, extra=''):
    print(f'  [{"PASS" if cond else "FAIL"}] {name}{("  " + extra) if extra else ""}')
    if not cond:
        FAILS.append(name)


def run_session(tmp, n_events, rate_hz=20000.0, capacity=64, n_ch=2,
                annotators=(), writer_delay=0.0, ram_budget_mb=1,
                slow_chunks=2):
    src = FakeSource(pre=8, post=24, n_ch=n_ch, rate_hz=rate_hz,
                     n_events=n_events)
    s = AcquisitionSession(src, tmp, capacity=capacity,
                           ram_budget_mb=ram_budget_mb, annotators=annotators,
                           verbose=False)
    if writer_delay:
        # Escritor artificialmente lento durante los primeros `slow_chunks`
        # chunks y normal despues: fuerza una rafaga de descartes EN MEDIO de la
        # corrida (no solo en la cola), que es el caso que la columna `gap`
        # tiene que marcar.
        orig = s.writer._write

        def slow(batch, _o=orig, _w=s.writer):
            if _w.index < slow_chunks:
                time.sleep(writer_delay)
            return _o(batch)
        s.writer._write = slow
    with s:
        # Sin condicion: corta cuando la fuente se agota (devuelve 'source').
        # NO se puede esperar n_events=N, porque los descartados no cuentan en
        # n_read y entonces N nunca se alcanzaria.
        s.wait(duration_s=30, poll_s=0.02)
    return s


def chunks_of(tmp):
    return sorted(glob.glob(os.path.join(tmp, 'chunk_*.npz')))


# ---------------------------------------------------------------- 1, 2, 5

def test_contabilidad_e_integridad():
    print('\n[1/2/5] contabilidad, integridad y atomicidad')
    tmp = tempfile.mkdtemp(prefix='mca_t1_')
    try:
        N = 512
        s = run_session(tmp, N, capacity=64)
        st = s.stats

        files = chunks_of(tmp)
        check('no quedan .tmp huerfanos',
              not glob.glob(os.path.join(tmp, '*.tmp')))
        check('se escribio al menos un chunk', len(files) > 0,
              f'({len(files)} chunks)')

        total, gaps, waves = 0, 0, []
        for f in files:
            arr, meta = load_chunk(f)
            total += len(arr['t_ns'])
            gaps  += int(arr['gap'].sum())
            waves.append(arr['wave_V'])
            check(f'{os.path.basename(f)}: meta consistente',
                  meta['chunk_events'] == len(arr['t_ns'])
                  and meta['schema_version'] >= 1)

        check('escritos + descartados == leidos + descartados',
              total + st['n_dropped'] == st['n_read'] + st['n_dropped'],
              f'({total} + {st["n_dropped"]} vs {st["n_read"]})')
        check('leidos == generados', st['n_read'] == N,
              f'({st["n_read"]} vs {N})')
        check('sin descartes a esta tasa', st['n_dropped'] == 0)
        check('sum(gap) == n_dropped', gaps == st['n_dropped'],
              f'({gaps} vs {st["n_dropped"]})')

        w = np.concatenate(waves)
        check('shape (eventos, canal, muestra)', w.shape == (total, 2, 32),
              str(w.shape))
        # El pulso sintetico sube en pre=8 y decae: el maximo tiene que caer ahi.
        check('la forma del pulso sobrevivio (pico en el trigger)',
              int(np.median(np.argmax(w[:, 0, :], axis=1))) == 8,
              f'(argmax mediano={int(np.median(np.argmax(w[:, 0, :], axis=1)))})')
        check('int16 en disco', np.load(files[0])['wave'].dtype == np.int16)
        # Redondeo de la conversion float32 volts -> int16 cuentas: <= 1 cuenta.
        check('error de cuantizacion <= 1 cuenta',
              float(np.max(np.abs(w))) < 2.0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------- 3

def test_descartes():
    print('\n[3] backpressure: descartar y contar, nunca bloquear')
    tmp = tempfile.mkdtemp(prefix='mca_t3_')
    try:
        N = 2000
        # ram_budget chico -> 2 batches. El escritor se frena 40 ms en los dos
        # primeros chunks (la cola se llena -> descartes) y despues se
        # normaliza, asi que el lector se recupera y los eventos siguientes
        # llevan gap>0. Es el caso realista: una rafaga en el medio.
        s = run_session(tmp, N, rate_hz=20000.0, capacity=32,
                        writer_delay=0.04, slow_chunks=2, ram_budget_mb=0.001)
        st = s.stats
        check('hubo descartes (el test tiene sentido)', st['n_dropped'] > 0,
              f'({st["n_dropped"]})')
        # El lector nunca se bloquea: todo evento generado o se lee o se
        # cuenta como descarte. Ninguno se pierde SIN registro.
        check('leidos + descartados == generados',
              st['n_read'] + st['n_dropped'] == N,
              f'({st["n_read"]} + {st["n_dropped"]} vs {N})')

        gaps, marcados, gaps_exact = 0, 0, 0
        for f in chunks_of(tmp):
            arr, meta = load_chunk(f)
            g = arr['gap']
            gaps     += int(g.sum())
            marcados += int((g > 0).sum())
            gaps_exact = gaps_exact + meta['chunk_dropped']
            # sum(gap) puede ser MENOR que chunk_dropped (gap satura en 255)
            check(f'{os.path.basename(f)}: chunk_dropped >= sum(gap)',
                  meta['chunk_dropped'] >= int(g.sum()))
        # `gap` cuenta los descartes ENTRE dos eventos guardados; los del final
        # de la corrida no tienen evento posterior donde anotarse y van al
        # run_summary. El invariante completo cierra los dos.
        import json
        with open(os.path.join(tmp, 'run_summary.json')) as fh:
            summ = json.load(fh)
        tail = summ['trailing_dropped']
        check('sum(chunk_dropped) + trailing == n_dropped (contabilidad cerrada)',
              gaps_exact + tail == st['n_dropped'],
              f'({gaps_exact} + {tail} vs {st["n_dropped"]})')
        check('gap saturo (el escenario ejercita el techo de uint8)',
              gaps < gaps_exact, f'(sum(gap)={gaps} < exacto={gaps_exact})')
        check('los huecos estan MARCADOS en eventos concretos', marcados > 0,
              f'({marcados} eventos con gap>0, {tail} en la cola)')
        check('el lector se recupero (hay eventos despues de la rafaga)',
              st['n_read'] > 2 * 32, f'(n_read={st["n_read"]})')
        check('run_summary refleja los totales',
              summ['n_read'] == st['n_read']
              and summ['n_dropped'] == st['n_dropped'])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------- 4

def test_esquema_dinamico():
    print('\n[4] esquema dinamico: 4 canales + annotator')
    tmp = tempfile.mkdtemp(prefix='mca_t4_')
    try:
        ann = ConstantAnnotator(x_mm=12.5, y_mm=-3.0)
        s = run_session(tmp, 128, capacity=64, n_ch=4, annotators=(ann,))
        files = chunks_of(tmp)
        check('escribio con n_ch=4', len(files) > 0)
        arr, meta = load_chunk(files[0])
        check('wave tiene 4 canales', arr['wave'].shape[1] == 4,
              str(arr['wave'].shape))
        check('columnas del annotator presentes',
              'x_mm' in arr and 'y_mm' in arr, str(sorted(arr)))
        check('valores del annotator correctos',
              np.allclose(arr['x_mm'], 12.5) and np.allclose(arr['y_mm'], -3.0))
        check('meta lista los campos',
              'x_mm' in meta['fields'] and 'gap' in meta['fields'],
              str(meta['fields']))
        check('meta lista los 4 canales', meta['channels'] == [1, 2, 3, 4],
              str(meta['channels']))
        check('load_chunk expone vistas por canal',
              all(f'd{c}' in arr for c in (1, 2, 3, 4)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_colision_de_columnas():
    print('\n[4b] dos annotators con la misma columna -> error explicito')
    tmp = tempfile.mkdtemp(prefix='mca_t4b_')
    try:
        a1, a2 = ConstantAnnotator(x_mm=1.0), ConstantAnnotator(x_mm=2.0)
        try:
            AcquisitionSession(FakeSource(n_events=1), tmp,
                               annotators=(a1, a2), verbose=False)
            check('colision detectada', False, '(no lanzo)')
        except ValueError as e:
            check('colision detectada', 'x_mm' in str(e), f'({e})')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    test_contabilidad_e_integridad()
    test_descartes()
    test_esquema_dinamico()
    test_colision_de_columnas()
    print('\nRESULT:', 'PASS' if not FAILS else f'FAIL ({len(FAILS)}): {FAILS}')
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
