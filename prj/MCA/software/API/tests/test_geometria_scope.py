#!/usr/bin/env python3
"""La geometría del scope: profundidad del anillo, aperturas y mapeo.

**El fallo que esto cubre no tira una excepción.** Las aperturas de BRAM están
decodificadas por `sys_addr[19:16]` (osc_cfg.sv:432), o sea que el canal `i` vive
en 0x10000*(i+1) sea cual sea `RSZ`. Con `RSZ` menor que 14 la mitad alta de cada
apertura es un ALIAS de la baja: pedirle 16384 muestras a un bitstream de RSZ=13
devuelve el anillo DOS VECES, sin código de error y sin nada que se queje.

Y como 2^14 = 2·2^13, el `% 16384` de la aritmética de ventanas tampoco se rompe
—el alias cancela exactamente el módulo de más—, así que la única señal de que
la ventana se cortó a la mitad es que los datos están repetidos. Por eso los
límites tienen que venir del hardware: no hay excepción que los reemplace.

Todo corre sin placa: `geometria_scope` es una función pura y el resto habla por
`r32`/`w32` contra un diccionario.
"""

import os
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import pytest                                                      # noqa: E402

from API import osciloscope as O                                   # noqa: E402


class Registros:
    """Un bloque que retiene lo que se le escribe."""

    def __init__(self, inicial=None):
        self.m = dict(inicial or {})

    def r32(self, off):
        return self.m.get(off, 0)

    def w32(self, off, v):
        self.m[off] = int(v) & 0xFFFFFFFF


def _osc(rsz=None, n_ch=None, dw=14):
    """Un `Osciloscope` sobre registros de mentira.

    Sin argumentos no publica el magic, que es el caso del bitstream viejo.
    """
    r = Registros()
    if rsz is not None:
        r.m[O.R_CANON_MAGIC] = O.MAGIC_OSC
        r.m[O.R_CANON_CAPS]  = (rsz << 16) | (dw << 8) | n_ch
    o = O.Osciloscope.__new__(O.Osciloscope)
    o._mmap, o._fd, o._geo = None, None, None
    o.r32 = r.r32
    o.w32 = r.w32
    return o


# =============================================================================
# La cuenta
# =============================================================================

def test_el_default_reproduce_las_constantes_historicas():
    """El ancla: 2 canales y RSZ=14 tienen que dar exactamente lo de siempre.

    Si esto se mueve, la geometría dejó de ser una refactorización y pasó a ser
    un cambio de comportamiento — y `compat_baseline.json` congela los dos
    valores, así que se enteraría igual, pero acá se lee el porqué.
    """
    g = O.geometria_scope()
    assert g['n_buf'] == 16384 == O.N_BUF
    assert g['size']  == 0x30000 == O.SCOPE_SIZE


def test_con_cuatro_canales_el_mapeo_viejo_se_queda_corto():
    """El bug que motivó todo esto.

    Con 4 canales la última apertura arranca en 0x40000, o sea DESPUÉS del final
    del mapeo de 0x30000. Nada de la API leía esas aperturas por el mmap, así
    que estaba latente; el bench sí lo hace (`bench_reader_budget.make_bram_views`)
    y ahí `np.frombuffer` habría fallado al pedir la vista.
    """
    g = O.geometria_scope(rsz=14, n_ch=4)
    assert g['size'] == 0x50000
    assert g['size'] > O.SCOPE_SIZE, 'el valor fijo cubriría las 4 aperturas'


def test_el_stride_no_depende_de_rsz():
    """Lo decide el decodificador de direcciones, no la profundidad."""
    for rsz in (12, 13, 14):
        g = O.geometria_scope(rsz=rsz, n_ch=4)
        assert g['aperturas'] == (0x10000, 0x20000, 0x30000, 0x40000)


def test_bajar_rsz_achica_el_mapeo_pero_no_mueve_las_aperturas():
    """RSZ=13 con 4 canales: mismas bases, la mitad de palabras en cada una."""
    g = O.geometria_scope(rsz=13, n_ch=4)
    assert g['n_buf'] == 8192
    assert g['size'] == 0x40000 + 4 * 8192 == 0x48000


@pytest.mark.parametrize('rsz', (12, 13, 14))
@pytest.mark.parametrize('n_ch', (1, 2, 3, 4))
def test_el_buffer_de_cada_canal_entra_entero_en_el_mapeo(rsz, n_ch):
    """La propiedad que el tamaño tiene que cumplir, calculada y no afirmada."""
    g = O.geometria_scope(rsz=rsz, n_ch=n_ch)
    assert len(g['aperturas']) == n_ch
    for base in g['aperturas']:
        assert base + 4 * g['n_buf'] <= g['size']


def test_rechaza_geometrias_imposibles():
    """5 canales no existen: el casez decodifica cuatro aperturas y punto."""
    with pytest.raises(ValueError):
        O.geometria_scope(n_ch=5)
    with pytest.raises(ValueError):
        O.geometria_scope(n_ch=0)
    with pytest.raises(ValueError):
        O.geometria_scope(rsz=0)


# =============================================================================
# Leerla del bitstream cargado
# =============================================================================

def test_la_lee_del_mapa_canonico():
    o = _osc(rsz=13, n_ch=4, dw=16)
    g = o.geometria()
    assert (g['rsz'], g['n_ch'], g['dw']) == (13, 4, 16)
    assert g['n_buf'] == 8192
    assert g['descubierta']


def test_sin_magic_cae_al_default_y_lo_dice():
    """Un bitstream anterior al refactor no tiene el mapa canónico.

    Falla ABIERTA, igual que la guarda de variante: negarse a operar contra un
    bitstream viejo sería peor que operar con la geometría que ese bitstream
    justamente tiene. `descubierta=False` es lo que permite distinguir el dato
    leído de la suposición.
    """
    g = _osc().geometria()
    assert g['n_buf'] == O.N_BUF
    assert not g['descubierta']


def test_n_buf_es_el_del_bitstream():
    assert _osc(rsz=13, n_ch=2).n_buf == 8192
    assert _osc(rsz=14, n_ch=2).n_buf == 16384


def test_la_geometria_se_lee_una_sola_vez():
    """Va en el camino de cada captura; releer el bus por muestra no."""
    o = _osc(rsz=13, n_ch=2)
    leidas = []
    original = o.r32
    o.r32 = lambda off: (leidas.append(off), original(off))[1]
    o.geometria(); o.geometria(); o.n_buf
    assert leidas == [O.R_CANON_MAGIC, O.R_CANON_CAPS]


# =============================================================================
# El límite que reemplaza al alias silencioso
# =============================================================================

def test_una_ventana_mas_grande_que_el_anillo_se_rechaza():
    """Sin esto el hardware devuelve el anillo repetido y nadie se entera."""
    with pytest.raises(ValueError, match='repetido'):
        O.Osciloscope.capture_window_np(pre=4096, post=8192, n_buf=8192)


def test_la_ventana_justa_pasa():
    """Que el límite sea `>` y no `>=`: pedir el anillo entero es legítimo.

    Llega hasta el acceso a `rp`, que en la PC no existe; que el error sea de
    importación y no el ValueError de arriba es la prueba de que pasó el
    chequeo.
    """
    with pytest.raises(Exception) as e:
        O.Osciloscope.capture_window_np(pre=0, post=8192, n_buf=8192)
    assert 'repetido' not in str(e.value)
