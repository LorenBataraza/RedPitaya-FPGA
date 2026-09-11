#!/usr/bin/env python3
"""La guarda que impide cargar un bitstream de otro Zynq.

**El incidente que la motivó:** se programó un `.bit.bin` compilado para
`7z010` sobre una placa `z20_125_4ch`, que lleva un `7z020`. El IDCODE no
coincide, el FPGA manager devuelve `-ETIMEDOUT` y —esto es lo grave— **queda
trabado**: toda programación posterior falla, incluida la de fábrica, hasta
reiniciar la placa. No es un error que se pueda reintentar.

Todo lo de acá corre sin placa: son funciones puras sobre ficheros y sobre la
salida de `monitor`, que se simula con un guión.
"""

import os
import stat
import sys

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)
sys.path.insert(0, _RAIZ)

import struct                                                      # noqa: E402

from API import fpga                                               # noqa: E402


def _bit_falso(parte, diseno='mca_red_pitaya_top'):
    """Un `.bit` con la cabecera etiquetada que escribe Vivado.

    Formato: magic, y después campos `a`(diseño) `b`(parte) `c`(fecha)
    `d`(hora), cada uno con su longitud de 16 bits big-endian.
    """
    d = bytearray()
    d += struct.pack('>H', 9) + b'\x0f\xf0' * 4 + b'\x00'
    d += struct.pack('>H', 1)
    for clave, valor in (('a', diseno), ('b', parte),
                         ('c', '2026/09/04'), ('d', '18:32:41')):
        v = valor.encode() + b'\x00'
        d += clave.encode() + struct.pack('>H', len(v)) + v
    d += b'e' + struct.pack('>I', 16) + b'\xff' * 16
    return bytes(d)


# =============================================================================
# Leer la parte del bitstream
# =============================================================================

def test_lee_la_parte_de_la_cabecera(tmp_path):
    f = tmp_path / 'x.bit'
    f.write_bytes(_bit_falso('7z010clg400'))
    assert fpga.parte_del_bitstream(str(f)) == '7z010clg400'


def test_el_bin_no_tiene_cabecera(tmp_path):
    """`bootgen` la quita, y el `.bin` es justo el que se carga. Por eso la
    parte tiene que viajar por otro lado."""
    f = tmp_path / 'x.bit.bin'
    f.write_bytes(b'\xff' * 64 + b'\x66\x55\x99\xaa' + b'\x00' * 64)
    assert fpga.parte_del_bitstream(str(f)) is None


def test_un_fichero_que_no_existe_no_rompe():
    assert fpga.parte_del_bitstream('/no/existe.bit') is None


# =============================================================================
# Encontrarla desde el .bit.bin, que es lo que hay en la placa
# =============================================================================

def test_la_encuentra_en_el_bit_hermano(tmp_path):
    """El caso del árbol de desarrollo: Vivado deja los dos en `out/`."""
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out' / 'm.bit').write_bytes(_bit_falso('7z020clg400'))
    binario = tmp_path / 'out' / 'm.bit.bin'
    binario.write_bytes(b'\xff' * 32)
    assert fpga.parte_declarada(str(binario)) == '7z020clg400'


def test_la_encuentra_en_el_version_del_paquete(tmp_path):
    """El caso de la placa: no hay `.bit`, sólo el paquete instalado."""
    (tmp_path / 'out').mkdir()
    binario = tmp_path / 'out' / 'm.bit.bin'
    binario.write_bytes(b'\xff' * 32)
    (tmp_path / 'VERSION').write_text(
        'paquete    mca-0.1.0\n'
        'bitstream  m.bit.bin\n'
        'parte      7z010clg400\n'
        'eje        13 bits\n')
    assert fpga.parte_declarada(str(binario)) == '7z010clg400'


def test_sin_ninguna_de_las_dos_da_none(tmp_path):
    (tmp_path / 'out').mkdir()
    binario = tmp_path / 'out' / 'm.bit.bin'
    binario.write_bytes(b'\xff' * 32)
    assert fpga.parte_declarada(str(binario)) is None


# =============================================================================
# La decisión
# =============================================================================

def test_acepta_la_parte_correcta():
    ok, motivo = fpga.bitstream_compatible('7z010clg400', 'z10_125')
    assert ok and 'correcto' in motivo


def test_rechaza_el_cruce_que_rompio_la_placa():
    """El caso exacto del incidente."""
    ok, motivo = fpga.bitstream_compatible('7z010clg400', 'z20_125_4ch')
    assert not ok
    assert '7z020' in motivo and 'trabado' in motivo


def test_rechaza_tambien_al_reves():
    ok, _ = fpga.bitstream_compatible('7z020clg400', 'z10_125')
    assert not ok


def test_las_variantes_de_z20_comparten_parte():
    for modelo in ('z20_125', 'z20_125_4ch', 'z20_122'):
        ok, _ = fpga.bitstream_compatible('7z020clg400', modelo)
        assert ok, modelo


def test_ante_la_duda_deja_pasar_y_lo_dice():
    """Falla ABIERTA, no cerrada: si no se puede comprobar, no se bloquea.

    Un falso positivo acá impediría cargar un bitstream perfectamente válido en
    una placa nueva que la tabla todavía no conoce. El riesgo es asimétrico
    porque el caso que importa —dos partes conocidas que no coinciden— sí se
    detecta.
    """
    for parte, modelo in (('7z010clg400', 'z99_futuro'),  # modelo desconocido
                          (None, 'z20_125_4ch'),          # bitstream sin parte
                          ('7z010clg400', None)):         # placa ilegible
        ok, motivo = fpga.bitstream_compatible(parte, modelo)
        assert ok, (parte, modelo)
        assert motivo, 'dejó pasar sin decir por qué'


# =============================================================================
# Leer el modelo de la placa
# =============================================================================

def _monitor_falso(tmp_path, salida, rc=0):
    """Un `monitor` de mentira, para no depender de tener una placa."""
    g = tmp_path / 'monitor'
    g.write_text(f'#!/bin/sh\necho "{salida}"\nexit {rc}\n')
    g.chmod(g.stat().st_mode | stat.S_IEXEC)
    return str(g)


def test_lee_el_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr(fpga, 'MONITOR_PATHS',
                        (_monitor_falso(tmp_path, 'z20_125_4ch'),))
    assert fpga.modelo_de_placa() == 'z20_125_4ch'


def test_undefined_no_es_un_modelo(tmp_path, monkeypatch):
    """Sin root, `monitor -f` no puede abrir la EEPROM y escribe `undefined`
    en stdout **con código de salida 0**. Mirar sólo el returncode haría que
    "undefined" pasara por el nombre de un modelo, y de ahí a comparar la parte
    contra una placa inventada."""
    monkeypatch.setattr(fpga, 'MONITOR_PATHS',
                        (_monitor_falso(tmp_path, 'undefined'),))
    assert fpga.modelo_de_placa() is None


def test_sin_monitor_da_none(monkeypatch):
    monkeypatch.setattr(fpga, 'MONITOR_PATHS', ('/no/existe/monitor',))
    assert fpga.modelo_de_placa() is None


# =============================================================================
# El bitstream real del repo
# =============================================================================

def test_el_bitstream_del_repo_declara_su_parte():
    """Si esto falla, `make release` va a escribir "desconocida" en VERSION y
    la guarda se queda sin con qué comparar."""
    bit = os.path.join(_RAIZ, '..', 'out', 'mca_red_pitaya.bit')
    if not os.path.exists(bit):
        return                          # sin síntesis local, no hay nada que probar
    parte = fpga.parte_del_bitstream(bit)
    assert parte and parte.startswith('7z'), parte
