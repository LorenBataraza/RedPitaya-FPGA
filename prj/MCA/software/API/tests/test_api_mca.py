#!/usr/bin/env python3
"""API nueva de `API/mca.py`: accesores por campo y capa de guardado.

`test_compat_api.py` cubre que la superficie VIEJA no cambió; esto cubre lo que
el refactor AÑADIÓ, que no tiene baseline contra el que compararse:

    - los `mca_get_*` / `mca_set_*` por campo, y en particular el
      read-modify-write de los registros que empaquetan varios campos
    - `mca_get_metadata()`
    - el round-trip de los tres formatos de guardado

Corre en la PC, sin placa: usa el `FakeMmap` de `gen_compat_baseline`.

    python API/tests/test_api_mca.py
    python -m pytest API/tests/test_api_mca.py -q
"""

import os
import sys
import tempfile

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, _AQUI)

from gen_compat_baseline import FakeMmap                           # noqa: E402
import API.mca as A                                                # noqa: E402

import struct as _struct
_U32 = _struct.Struct('<I')


def _leer(m, off):
    """Lee un registro de 32 b del mmap falso, igual que lo hace el driver."""
    return _U32.unpack_from(m, off)[0]


def _handle():
    """Un MCA sobre memoria falsa, con magic/caps/widths precargados."""
    m = FakeMmap(A.MCA_SIZE)
    m.poke(A.R_MAGIC, A.MAGIC)
    m.poke(A.R_CAPS, A.CAP_HIST_H | A.CAP_HIST_H_PSD)
    m.poke(A.R_WIDTHS, (8 << 16) | (8 << 8) | 14)      # psd_aw, h2_aw, h_aw
    return m, A.MCA(m, -1, A.CAP_HIST_H | A.CAP_HIST_H_PSD, 14, 8, 8)


# Registros que empaquetan varios campos, con el layout que publica el RTL
# (mca_top.sv:340,346,351). Es el caso que el read-modify-write tiene que
# respetar: escribir `bl_k` sin borrar `bl_holdoff`.
EMPAQUETADOS = [
    ('R_BL_CTRL',  [('bl_holdoff', 0xBEEF), ('bl_k', 13), ('bl_auto', 1)]),
    ('R_AMP_SRC',  [('q_shift', 0x15), ('amp_src', 1)]),
    ('R_GATE_LEN', [('gate_long', 0x1234), ('gate_short', 0x5678)]),
]


def test_rmw_no_pisa_campos_vecinos():
    """Poner un campo de un registro compartido no debe borrar los otros.

    Sin read-modify-write, `mca_set_bl_k(h, 13)` escribiría la palabra entera y
    dejaría `bl_holdoff` en cero — en la placa eso cambia el comportamiento del
    seguidor de línea de base sin que nada falle ni avise.
    """
    for nombre, campos in EMPAQUETADOS:
        _, h = _handle()
        for campo, valor in campos:            # cada uno por separado, en orden
            getattr(A, f'mca_set_{campo}')(h, valor)
        for campo, valor in campos:            # y todos siguen en pie
            got = int(getattr(A, f'mca_get_{campo}')(h))
            assert got == valor, (
                f'{nombre}: tras escribir los {len(campos)} campos, {campo} '
                f'vale {got} y debería valer {valor} — el RMW pisó un vecino')


def test_set_channel_preserva_run():
    """`channel` es el bit 8 de R_CTRL y `run` el bit 0: comparten registro."""
    _, h = _handle()
    A.mca_start(h)
    assert A.mca_get_running(h)
    A.mca_set_channel(h, 1)
    assert A.mca_get_running(h), 'set_channel apagó la acumulación'
    assert A.mca_get_channel(h) == 1


def test_start_stop_clear():
    _, h = _handle()
    assert not A.mca_get_running(h)
    A.mca_start(h)
    assert A.mca_get_running(h)
    A.mca_stop(h)
    assert not A.mca_get_running(h)
    A.mca_clear(h)                    # con STATUS=0 el clear_busy sale enseguida


def test_get_config_cubre_todos_los_campos():
    _, h = _handle()
    cfg = A.mca_get_config(h)
    assert set(cfg) == set(A._CAMPOS), 'mca_get_config no devuelve todos los campos'


def test_metadata_lleva_config_contadores_y_geometria():
    _, h = _handle()
    A.mca_set_thr(h, 317)
    meta = A.mca_get_metadata(h)
    for clave in ('schema_version', 'thr', 'gate_long', 'h_aw', 'total',
                  'livetime_s', 'n_channels', 'adc_cnt_per_V', 't_wall'):
        assert clave in meta, f'falta {clave!r} en la metadata'
    assert meta['thr'] == 317
    assert meta['n_channels'] == 1 << 14


def test_roundtrip_de_los_tres_formatos():
    """El formato es una decisión de almacenamiento: los tres tienen que
    devolver el mismo histograma y la misma metadata."""
    _, h = _handle()
    A.mca_set_thr(h, 317)
    A.mca_set_gate_long(h, 400)
    meta = A.mca_get_metadata(h)
    hist = (np.arange(256, dtype=np.uint32) * 7) % 1000

    with tempfile.TemporaryDirectory() as d:
        escritores = (('csv',  A.mca_write_file_histogram),
                      ('npz',  A.mca_save_file_binary),
                      ('json', A.mca_save_file_json))
        for ext, escribir in escritores:
            ruta = os.path.join(d, 'espectro.' + ext)
            escribir(hist, ruta, meta=meta)
            leido, meta2 = A.mca_load_file(ruta)

            assert np.array_equal(leido, hist), f'{ext}: el histograma no vuelve igual'
            for clave in ('thr', 'gate_long', 'schema_version', 'n_channels'):
                assert int(meta2[clave]) == int(meta[clave]), (
                    f'{ext}: la metadata {clave!r} volvió como {meta2[clave]!r}')


def test_load_file_rechaza_formato_desconocido():
    try:
        A.mca_load_file('/tmp/no_existe.bin')
    except ValueError as e:
        assert '.bin' in str(e)
    else:
        raise AssertionError('mca_load_file aceptó una extensión desconocida')


def main():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f'  ok    {fn.__name__}')
        except Exception as e:
            fallos += 1
            print(f'  FALLO {fn.__name__}: {type(e).__name__}: {e}')
    print(f'\n{len(pruebas) - fallos}/{len(pruebas)} pruebas OK')
    return 1 if fallos else 0


if __name__ == '__main__':
    raise SystemExit(main())


# =============================================================================
# Opciones nuevas de configure(): selector de feature, zoom y discriminador
#
# No tienen baseline contra el que compararse (son de la fase 1-3), así que la
# cobertura tiene que ser explícita. Lo que importa es que los DEFAULTS
# reproduzcan el comportamiento histórico —si no, toda la campaña medida deja de
# ser comparable sin que nadie se entere— y que las configuraciones inválidas
# fallen fuerte en vez de producir un espectro vacío.
# =============================================================================

def test_defaults_reproducen_el_comportamiento_historico():
    m, mca = _handle()
    mca.configure(verify=False)
    # sel_1d y sel_2dx siguen a amp_src (0 = pico), sel_2dy es el factor de forma.
    assert _leer(m, A.R_HIST_SEL) == (A.F_PSD << 8) | (A.F_PEAK << 4) | A.F_PEAK
    # Zoom en cero en los tres ejes = fondo de escala = como siempre.
    for off in (A.R_ZOOM_1D, A.R_ZOOM_2DX, A.R_ZOOM_2DY):
        assert _leer(m, off) == 0
    # Discriminador APAGADO: deja pasar todo.
    assert _leer(m, A.R_DISCR_CTRL) == 0


def test_amp_src_sigue_moviendo_el_selector():
    """Compatibilidad: la campaña vieja configura amp_src y nada más."""
    m, mca = _handle()
    mca.configure(amp_src=1, verify=False)
    assert _leer(m, A.R_HIST_SEL) & 0xF == A.F_INT
    assert (_leer(m, A.R_HIST_SEL) >> 4) & 0xF == A.F_INT


def test_sel_explicito_gana_sobre_amp_src():
    m, mca = _handle()
    mca.configure(amp_src=0, sel_1d='ancho_inv', sel_2dy='largo', verify=False)
    v = _leer(m, A.R_HIST_SEL)
    assert v & 0xF == A.F_INVW
    assert (v >> 8) & 0xF == A.F_LEN


def test_zoom_se_empaqueta_bien():
    m, mca = _handle()
    mca.configure(zoom_1d=(3, 5), zoom_2dx=(1, 1), verify=False)
    assert _leer(m, A.R_ZOOM_1D) == (5 << 8) | 3
    assert _leer(m, A.R_ZOOM_2DX) == (1 << 8) | 1


def test_discriminador_interno_y_externo():
    m, mca = _handle()
    mca.configure(discr=('ancho_inv', 100, 200), verify=False)
    assert _leer(m, A.R_DISCR_MIN) == 100
    assert _leer(m, A.R_DISCR_MAX) == 200
    assert _leer(m, A.R_DISCR_CTRL) == (A.F_INVW << 4) | 1        # enable, interno

    m, mca = _handle()
    mca.configure(discr=('psd', 100, 200, True), verify=False)
    assert _leer(m, A.R_DISCR_CTRL) == (A.F_PSD << 4) | 2 | 1     # enable, externo


def test_discr_vacio_falla_en_vez_de_vaciar_el_espectro():
    """min > max con intervalo interno rechaza TODO evento.

    En el RTL es la respuesta correcta a un conjunto vacío, pero como
    configuración es casi siempre un error de tipeo, y el síntoma sería un
    espectro sin una sola cuenta y ningún mensaje. Se levanta acá.
    """
    m, mca = _handle()
    try:
        mca.configure(discr=('pico', 500, 100), verify=False)
        assert False, 'aceptó un intervalo interno vacío'
    except ValueError as e:
        assert 'vacio' in str(e) or 'vacío' in str(e)
    # Pero con intervalo EXTERNO min>max es legítimo: acepta todo.
    mca.configure(discr=('pico', 500, 100, True), verify=False)


def test_feature_invalida_falla():
    m, mca = _handle()
    for mala in ('inexistente', 9, 15):
        try:
            mca.configure(sel_1d=mala, verify=False)
            assert False, f'aceptó la feature inválida {mala!r}'
        except ValueError:
            pass


def test_keep_if_full():
    m, mca = _handle()
    mca.configure(keep_if_full=True, verify=False)
    assert _leer(m, A.R_HIST_CTRL) == 1
    mca.configure(keep_if_full=False, verify=False)
    assert _leer(m, A.R_HIST_CTRL) == 0


# =============================================================================
# amplitud <-> canal: el espejo de mca_zoom.sv
# =============================================================================
#
# Existe porque NO hay otra forma de ubicar en el eje del espectro un valor que
# vive en cuentas de amplitud: los limites de la ventana de aceptacion, los del
# discriminador, o un umbral que se quiera dibujar encima del histograma.
#
# La conversion se hacia con `h_shift`, que el bitstream nuevo dejo DEPRECADO
# ("se sigue leyendo y escribiendo, pero ya no afecta al datapath"). Con
# h_shift=0 el canal salia igual a la amplitud: 2^(AMP_W-h_aw) veces de mas, un
# factor 8 sobre un eje de 8192 canales.

def test_canal_de_amplitud_sin_zoom_es_el_corrimiento_de_los_bits_altos():
    for h_aw in (13, 14):
        corr = A.AMP_W - h_aw
        for v in (0, 1, 1000, 4095, 32768, 65535):
            esperado = min(v >> corr, (1 << h_aw) - 1)
            assert A.mca_canal_de_amplitud(v, h_aw) == esperado, (v, h_aw)


def test_canal_de_amplitud_satura_no_envuelve():
    """El contrato del RTL: fuera de la ventana el evento va a un extremo.

    Es lo que hace que los bines de los bordes sirvan de indicadores visibles de
    desborde. Si envolviera, un evento por encima de la ventana aparecería en el
    canal 0 y seria indistinguible de uno por debajo.
    """
    h_aw = 13
    # ventana z=1, k=1  ->  [32768, 65536)
    assert A.mca_canal_de_amplitud(0, h_aw, z=1, k=1) == 0
    assert A.mca_canal_de_amplitud(32767, h_aw, z=1, k=1) == 0
    # ventana z=1, k=0  ->  [0, 32768)
    assert A.mca_canal_de_amplitud(65535, h_aw, z=1, k=0) == (1 << h_aw) - 1
    assert A.mca_canal_de_amplitud(32768, h_aw, z=1, k=0) == (1 << h_aw) - 1


def test_canal_de_amplitud_los_bins_anidan_exacto():
    """Un bin de nivel z es la union de DOS de nivel z+1, sin resto.

    Es la propiedad que justifica el zoom alineado a potencias de 2 frente a un
    offset libre: espectros tomados con ventanas distintas se cosen con
    aritmetica entera, sin resamplear y sin agregar DNL.
    """
    h_aw = 13
    for v in range(0, 65536, 97):            # barrido con paso primo
        c0 = A.mca_canal_de_amplitud(v, h_aw, z=0, k=0)
        k1 = v >> (A.AMP_W - 1)              # en que mitad cae
        c1 = A.mca_canal_de_amplitud(v, h_aw, z=1, k=k1)
        # El canal de z=0 se parte en dos al pasar a z=1: el de la mitad que le
        # toca tiene que ser el doble, mas 0 o 1.
        assert c1 >> 1 == c0 - k1 * (1 << (h_aw - 1)) or c0 in (0, (1 << h_aw) - 1)


def test_z_se_satura_igual_que_el_rtl():
    """`z` no puede pasar de AMP_W - h_aw: mas alla no quedan bits que rebanar.

    El RTL lo satura en silencio; el software lo satura ANTES de escribir, para
    que lo que se lee de vuelta sea lo que de verdad quedo configurado.
    """
    m, mca = _handle()
    z_max = A.AMP_W - mca.h_aw
    A.mca_set_zoom_1d_z(mca, z_max + 5)
    assert A.mca_get_zoom_1d_z(mca) == z_max


def test_amplitud_de_canal_es_inversa_por_izquierda():
    for h_aw in (13, 14):
        for z in range(0, 4):
            for k in range(0, 1 << z):
                for canal in (0, 1, 100, (1 << h_aw) - 1):
                    v = A.mca_amplitud_de_canal(canal, h_aw, z, k)
                    assert A.mca_canal_de_amplitud(v, h_aw, z, k) == canal


def test_get_config_relee_los_campos_nuevos():
    """`configure()` los escribia y NADA los leia de vuelta.

    La consecuencia no era cosmetica: `mca_get_metadata` se arma sobre
    `mca_get_config`, asi que un espectro guardado con zoom no registraba el
    zoom y su eje quedaba irreconstruible.
    """
    m, mca = _handle()
    mca.configure(zoom_1d=(2, 1), sel_1d='integral', keep_if_full=False,
                  discr=('pico', 100, 500), verify=False)
    cfg = A.mca_get_config(mca)
    assert cfg['zoom_1d_z'] == 2
    assert cfg['zoom_1d_k'] == 1
    assert cfg['sel_1d'] == A.F_INT
    assert cfg['keep_if_full'] == 0
    assert cfg['discr_en'] == 1
    assert cfg['discr_min'] == 100 and cfg['discr_max'] == 500
