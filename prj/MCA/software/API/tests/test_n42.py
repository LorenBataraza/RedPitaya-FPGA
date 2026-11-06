#!/usr/bin/env python3
"""El espectro del MCA en ANSI N42.42-2011. NO necesita la placa.

Lo que importa es que otro programa lo abra, así que la referencia es el esquema de
NIST y no este código: `datos_ref/n42/` tiene el XSD 0.0.54, las reglas (`n42.sch`) y
el ejemplo del Anexo B, bajados de https://www.nist.gov/pml/radiation-physics/n42-2011.

Las reglas están en XSLT 2 y `lxml` no las corre. Las que afectan a estos archivos se
comprueban acá una por una, y el conjunto entero se corrió una vez a mano con Saxon:
0 fallas en estos archivos.

Correr:  python3 -m pytest API/tests/test_n42.py -v
"""

import datetime
import os
import sys
import time
import warnings
import xml.etree.ElementTree as ET

import numpy as np
import pytest

_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)

from API import mca as A                                           # noqa: E402
from API import n42                                                # noqa: E402

_DATOS = os.path.join(_RAIZ, 'API', 'tests', 'datos_ref', 'n42')
_NS = {'n': n42.NS}

META = dict(gate_long=112, n_acc=4, realtime_s=60.0, livetime_s=59.61,
            t_wall=1_780_000_000.25, api_impl='c', mapa='MCA2', sel_1d=0,
            libmca_version='0.3.0', n_channels=16384, t_ocup_s=[59.0, 1.0],
            nota='acentos: ñandú <&> "comillas"')


@pytest.fixture
def hist():
    h = np.zeros(16384, dtype=np.uint32)
    h[4000:4100] = 37
    h[0] = 5
    h[-1] = 0xFFFFFFFF          # el mayor valor de 32 b tiene que volver exacto
    return h


@pytest.fixture(scope='module')
def xsd():
    etree = pytest.importorskip('lxml.etree')
    return etree.XMLSchema(etree.parse(os.path.join(_DATOS, 'n42.xsd')))


def _valida(xsd, ruta):
    import lxml.etree as etree
    ok = xsd.validate(etree.parse(str(ruta)))
    assert ok, [e.message[:200] for e in xsd.error_log][:5]


def _raiz(ruta):
    return ET.parse(str(ruta)).getroot()


def _texto(raiz, camino):
    return raiz.find(camino, _NS).text


# -----------------------------------------------------------------------------
# El esquema de NIST
# -----------------------------------------------------------------------------

def test_el_validador_rechaza_un_archivo_roto(xsd, hist, tmp_path):
    """Sin esto, los demás no prueban nada: un XSD mal cargado valida cualquier cosa."""
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=META)
    texto = ruta.read_text(encoding='utf-8')
    roto = tmp_path / 'roto.n42'
    roto.write_text(texto.replace('<MeasurementClassCode>NotSpecified',
                                  '<MeasurementClassCode>Inventado'), encoding='utf-8')
    import lxml.etree as etree
    assert not xsd.validate(etree.parse(str(roto)))


def test_el_ejemplo_de_nist_valida(xsd):
    _valida(xsd, os.path.join(_DATOS, 'annexb.n42'))


@pytest.mark.parametrize('kw', [
    {},
    {'calibracion': (-21.8, 12.1, 6.55e-3)},
    {'calibracion': (0.0, 2.5)},
    {'clase': 'Foreground'},
    {'clase': 'Background'},
    {'detector': {'categoria': 'Gamma', 'tipo': 'NaI'}},
    {'detector': {'categoria': 'Gamma', 'tipo': 'Other', 'descripcion': 'plástico',
                  'nombre': 'IN1'}},
    {'instrumento': {'fabricante': 'otro', 'modelo': 'x'}},
], ids=lambda k: next(iter(k), 'defaults'))
def test_valida_contra_el_xsd(xsd, hist, tmp_path, kw):
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=META, **kw)
    _valida(xsd, ruta)


def test_valida_con_la_metadata_real_del_mca(xsd, tmp_path):
    from API.mca_remote import FakeMCA
    h = FakeMCA()
    A.mca_set_n_acc(h, 2)
    A.mca_start(h)
    time.sleep(0.05)
    A.mca_stop(h)
    meta = A.mca_get_metadata(h)
    assert meta['realtime_s'] > 0
    ruta = tmp_path / 'e.n42'
    hist = A.mca_read_histogram(h)
    A.mca_save_file_n42(hist, ruta, meta=meta)
    _valida(xsd, ruta)
    h2, m2 = A.mca_load_file(str(ruta))
    assert np.array_equal(h2, hist)
    assert m2['n_acc'] == 2
    assert m2['t_ocup_s'] == [float(x) for x in meta['t_ocup_s']]


def test_los_codigos_son_los_del_esquema():
    etree = pytest.importorskip('lxml.etree')
    raiz = etree.parse(os.path.join(_DATOS, 'n42.xsd')).getroot()
    xs = {'x': 'http://www.w3.org/2001/XMLSchema'}

    def del_esquema(nombre):
        return tuple(e.get('value') for e in raiz.findall(
            f".//x:simpleType[@name='{nombre}']//x:enumeration", xs))

    assert n42.CLASES_MEDICION == del_esquema('MeasurementClassCodeSimpleType')
    assert n42.CATEGORIAS_DETECTOR == del_esquema('RadDetectorCategoryCodeSimpleType')
    assert n42.TIPOS_DETECTOR == del_esquema('RadDetectorKindCodeSimpleType')


# -----------------------------------------------------------------------------
# Las reglas de n42.sch que el XSD no ve
# -----------------------------------------------------------------------------

def test_detector_other_lleva_descripcion(hist, tmp_path):
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=META)
    d = _raiz(ruta).find('n:RadDetectorInformation', _NS)
    assert d.find('n:RadDetectorCategoryCode', _NS).text == 'Other'
    assert d.find('n:RadDetectorKindCode', _NS).text == 'Other'
    assert d.find('n:RadDetectorDescription', _NS).text


@pytest.mark.parametrize('det', [{'categoria': 'Gamma'},           # tipo: Other
                                 {'tipo': 'NaI'},                  # categoria: Other
                                 {'categoria': 'Other', 'tipo': 'Other'}])
def test_detector_other_sin_descripcion_no_se_escribe(hist, tmp_path, det):
    ruta = tmp_path / 'e.n42'
    with pytest.raises(ValueError, match='descripcion'):
        A.mca_save_file_n42(hist, ruta, meta=META, detector=det)
    assert not ruta.exists()


def test_el_inicio_es_t_wall_menos_el_tiempo_real(hist, tmp_path):
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=META)
    inicio = _texto(_raiz(ruta), 'n:RadMeasurement/n:StartDateTime')
    d = datetime.datetime.fromisoformat(inicio.replace('Z', '+00:00'))
    assert d.timestamp() == pytest.approx(META['t_wall'] - META['realtime_s'], abs=1e-5)
    assert d.utcoffset() == datetime.timedelta(0)


def test_el_tiempo_vivo_no_pasa_del_real(hist, tmp_path):
    # Leídos en caliente, los dos relojes no son del mismo instante.
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=dict(META, livetime_s=60.5))
    raiz = _raiz(ruta)
    assert _texto(raiz, './/n:Spectrum/n:LiveTimeDuration') == 'PT60.000000S'
    assert _texto(raiz, 'n:RadMeasurement/n:RealTimeDuration') == 'PT60.000000S'
    # El dato crudo no se pierde: va en la metadata.
    assert A.mca_load_file(str(ruta))[1]['livetime_s'] == 60.5


# -----------------------------------------------------------------------------
# Ida y vuelta
# -----------------------------------------------------------------------------

def test_ida_y_vuelta_exacta(hist, tmp_path):
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=META)
    h2, m2 = A.mca_load_file(str(ruta))
    assert h2.dtype == np.uint32
    assert np.array_equal(h2, hist)
    assert {k: v for k, v in m2.items() if not k.startswith('n42_')} == META
    assert m2['n42_clase'] == 'NotSpecified'
    assert m2['n42_n_espectros'] == 1


def test_sin_calibrar_lo_dice(hist, tmp_path):
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=META)
    cal = _raiz(ruta).find('n:EnergyCalibration', _NS)
    assert cal.find('n:CoefficientValues', _NS).text == '0 1 0'
    assert 'no keV' in cal.find('n:Remark', _NS).text
    _, m2 = A.mca_load_file(str(ruta))
    assert m2['n42_calibracion'] is None    # 0 1 0 no es una calibración


def test_la_calibracion_lineal_lleva_t2_cero(hist, tmp_path):
    # El estándar pide los tres, con T2 = 0 si es lineal.
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=META, calibracion=(1.5, 2.5))
    cal = _raiz(ruta).find('n:EnergyCalibration', _NS)
    assert cal.find('n:CoefficientValues', _NS).text == '1.5 2.5 0.0'
    assert cal.find('n:Remark', _NS) is None
    assert A.mca_load_file(str(ruta))[1]['n42_calibracion'] == [1.5, 2.5, 0.0]


def test_guardar_un_archivo_releido_no_pierde_nada(hist, tmp_path):
    a, b = tmp_path / 'a.n42', tmp_path / 'b.n42'
    det = {'categoria': 'Gamma', 'tipo': 'NaI', 'nombre': 'IN1'}
    cal = (-21.8, 12.1, 6.55e-3)
    instr = {'fabricante': 'otro', 'modelo': 'x'}
    A.mca_save_file_n42(hist, a, meta=META, detector=det, calibracion=cal,
                        clase='Foreground', instrumento=instr)
    h1, m1 = A.mca_load_file(str(a))
    A.mca_save_file_n42(h1, b, meta=m1)
    h2, m2 = A.mca_load_file(str(b))
    assert np.array_equal(h2, hist)
    assert m2 == m1
    assert m2['n42_calibracion'] == list(cal)
    assert m2['n42_detector'] == det
    assert m2['n42_clase'] == 'Foreground'
    assert m2['n42_instrumento'] == instr
    # El Remark no repite lo que ya dicen los elementos: si no, podrían contradecirse.
    remark = _texto(_raiz(b), 'n:RadMeasurement/n:Remark')
    assert remark.startswith('mca-meta:') and 'n42_' not in remark


def test_guardar_el_ejemplo_de_nist_lo_conserva(xsd, tmp_path):
    hist, meta = A.mca_load_file(os.path.join(_DATOS, 'annexb.n42'))
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=meta)
    _valida(xsd, ruta)
    h2, m2 = A.mca_load_file(str(ruta))
    assert np.array_equal(h2, hist)
    assert m2 == meta


def test_guardar_sin_calibrar_releido_sigue_sin_calibrar(hist, tmp_path):
    a, b = tmp_path / 'a.n42', tmp_path / 'b.n42'
    A.mca_save_file_n42(hist, a, meta=META)
    h1, m1 = A.mca_load_file(str(a))
    A.mca_save_file_n42(h1, b, meta=m1)
    cal = _raiz(b).find('n:EnergyCalibration', _NS)
    assert 'no keV' in cal.find('n:Remark', _NS).text
    assert m1['n42_detector'] is None


def test_el_trapecio_aclara_el_canal_0(xsd, hist, tmp_path):
    ruta = tmp_path / 'e.n42'
    A.mca_save_file_n42(hist, ruta, meta=dict(META, sel_1d=A.F_TRAP))
    _valida(xsd, ruta)
    assert 'canal 0' in _texto(_raiz(ruta), './/n:Spectrum/n:Remark')
    ruta2 = tmp_path / 'sin.n42'
    A.mca_save_file_n42(hist, ruta2, meta=META)
    assert _raiz(ruta2).find('.//n:Spectrum/n:Remark', _NS) is None


def test_mca_load_file_sigue_rechazando_lo_desconocido():
    with pytest.raises(ValueError, match=r'\.n42'):
        A.mca_load_file('/tmp/no_existe.bin')


# -----------------------------------------------------------------------------
# Lo que no se puede escribir, no se escribe
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('cambio, motivo', [
    ({'realtime_s': 0.0}, 'mayor que cero'),
    ({'realtime_s': float('nan')}, 'mayor que cero'),
    ({'realtime_s': None}, 'realtime_s'),
    ({'livetime_s': None}, 'livetime_s'),
    ({'livetime_s': -1.0}, 'livetime_s'),
    ({'t_wall': None}, 't_wall'),
])
def test_metadata_que_no_alcanza(hist, tmp_path, cambio, motivo):
    ruta = tmp_path / 'e.n42'
    with pytest.raises(ValueError, match=motivo):
        A.mca_save_file_n42(hist, ruta, meta=dict(META, **cambio))
    assert not ruta.exists()


def test_sin_metadata_no_escribe(hist, tmp_path):
    ruta = tmp_path / 'e.n42'
    with pytest.raises(ValueError, match='realtime_s'):
        A.mca_save_file_n42(hist, ruta)
    assert not ruta.exists()


@pytest.mark.parametrize('malo, motivo', [
    (np.zeros((4, 4), dtype=np.uint32), '1D'),
    (np.array([], dtype=np.uint32), '1D'),
    (np.array([1.5, 2.0]), 'enteras'),
    (np.array([1, -1]), 'negativas'),
])
def test_espectro_invalido(tmp_path, malo, motivo):
    ruta = tmp_path / 'e.n42'
    with pytest.raises(ValueError, match=motivo):
        A.mca_save_file_n42(malo, ruta, meta=META)
    assert not ruta.exists()


@pytest.mark.parametrize('kw, motivo', [
    ({'clase': 'Inventada'}, 'clase'),
    ({'detector': {'categoria': 'Inventada', 'descripcion': 'x'}}, 'categoria'),
    ({'detector': {'tipo': 'Inventado', 'descripcion': 'x'}}, 'tipo'),
    ({'detector': {'categoría': 'Gamma'}}, 'desconocidas'),
    ({'instrumento': {'marca': 'x'}}, 'desconocidas'),
    ({'calibracion': (1.0,)}, 'calibracion'),
    ({'calibracion': (1.0, 2.0, 3.0, 4.0)}, 'calibracion'),
    ({'calibracion': (0.0, float('inf'))}, 'calibracion'),
])
def test_argumento_invalido(hist, tmp_path, kw, motivo):
    ruta = tmp_path / 'e.n42'
    with pytest.raises(ValueError, match=motivo):
        A.mca_save_file_n42(hist, ruta, meta=META, **kw)
    assert not ruta.exists()


def test_una_metadata_que_no_es_json_no_deja_medio_archivo(hist, tmp_path):
    ruta = tmp_path / 'e.n42'
    with pytest.raises(TypeError):
        A.mca_save_file_n42(hist, ruta, meta=dict(META, raro=object()))
    assert not ruta.exists()


# -----------------------------------------------------------------------------
# Archivos ajenos
# -----------------------------------------------------------------------------

def test_lee_el_ejemplo_de_nist():
    hist, meta = A.mca_load_file(os.path.join(_DATOS, 'annexb.n42'))
    assert hist.dtype == np.uint32
    assert hist.size == meta['n_channels'] == 256
    assert hist[:6].tolist() == [0, 0, 0, 22, 421, 847]
    assert meta['realtime_s'] == 60.0
    assert meta['livetime_s'] == 59.61
    assert meta['n42_clase'] == 'Foreground'
    assert meta['n42_calibracion'] == [-21.8, 12.1, 6.55e-03]
    assert meta['n42_detector'] == {'categoria': 'Gamma', 'tipo': 'NaI'}
    assert meta['n42_instrumento']['modelo'] == 'iRIID'
    fin = datetime.datetime(2003, 11, 22, 23, 46, 19,
                            tzinfo=datetime.timezone(datetime.timedelta(hours=-7)))
    assert meta['t_wall'] == fin.timestamp()


_AJENO = """<?xml version="1.0"?>
<RadInstrumentData xmlns="http://physics.nist.gov/N42/2011/N42">
  <RadInstrumentInformation id="i"><RadInstrumentManufacturerName>m</RadInstrumentManufacturerName>
    <RadInstrumentModelName>x</RadInstrumentModelName><RadInstrumentClassCode>Other</RadInstrumentClassCode>
    <RadInstrumentVersion><RadInstrumentComponentName>c</RadInstrumentComponentName>
    <RadInstrumentComponentVersion>1</RadInstrumentComponentVersion></RadInstrumentVersion>
  </RadInstrumentInformation>
  <RadDetectorInformation id="d"><RadDetectorCategoryCode>Gamma</RadDetectorCategoryCode>
    <RadDetectorKindCode>NaI</RadDetectorKindCode></RadDetectorInformation>
  <EnergyCalibration id="e"><EnergyBoundaryValues>0 1 2 3</EnergyBoundaryValues></EnergyCalibration>
  <RadMeasurement id="m"><MeasurementClassCode>Background</MeasurementClassCode>
    <StartDateTime>{inicio}</StartDateTime><RealTimeDuration>{real}</RealTimeDuration>
    <Spectrum id="s" radDetectorInformationReference="d" energyCalibrationReference="e">
      <LiveTimeDuration>PT1M</LiveTimeDuration>
      <ChannelData {compresion}>{datos}</ChannelData>
    </Spectrum>{mas}
  </RadMeasurement>
</RadInstrumentData>
"""


def _ajeno(tmp_path, inicio='2020-01-02T03:04:05Z', real='PT2M', compresion='',
           datos='1 2 3', mas=''):
    ruta = tmp_path / 'ajeno.n42'
    ruta.write_text(_AJENO.format(inicio=inicio, real=real, compresion=compresion,
                                  datos=datos, mas=mas), encoding='utf-8')
    return str(ruta)


def test_counted_zeroes_con_el_ejemplo_del_estandar(tmp_path):
    ruta = _ajeno(tmp_path, compresion='compressionCode="CountedZeroes"',
                  datos='22 5 0 1 2 1 0 2 3 4 0 8 1')
    hist, meta = A.mca_load_file(ruta)
    assert hist.tolist() == [22, 5, 0, 2, 1, 0, 0, 3, 4] + [0] * 8 + [1]
    assert meta['n_channels'] == 18


@pytest.mark.parametrize('datos', ['1 2 0', '1 0 0 2', '1 0 -3 2', '1 0 1.5 2',
                                   f'0 {(1 << 24) + 1} 1'])
def test_counted_zeroes_incoherente(tmp_path, datos):
    ruta = _ajeno(tmp_path, compresion='compressionCode="CountedZeroes"', datos=datos)
    with pytest.raises(ValueError, match='CountedZeroes'):
        A.mca_load_file(ruta)


@pytest.mark.parametrize('datos', ['', '1 2.5', '1 -2', '1 x', str(1 << 32)])
def test_channel_data_que_no_son_cuentas(tmp_path, datos):
    with pytest.raises(ValueError, match='ChannelData'):
        A.mca_load_file(_ajeno(tmp_path, datos=datos))


def test_compresion_desconocida(tmp_path):
    ruta = _ajeno(tmp_path, compresion='compressionCode="Otra"')
    with pytest.raises(ValueError, match='Otra'):
        A.mca_load_file(ruta)


def test_acepta_notacion_cientifica_y_varias_lineas(tmp_path):
    hist, _ = A.mca_load_file(_ajeno(tmp_path, datos='\n1.0E3\n  2e0\t3\n'))
    assert hist.tolist() == [1000, 2, 3]


def test_la_calibracion_de_otra_forma_da_none(tmp_path):
    _, meta = A.mca_load_file(_ajeno(tmp_path))
    assert meta['n42_calibracion'] is None
    assert meta['n42_clase'] == 'Background'
    assert meta['livetime_s'] == 60.0


@pytest.mark.parametrize('texto, segundos', [
    ('PT60S', 60.0), ('PT59.61S', 59.61), ('PT1M', 60.0), ('PT1H2M3.5S', 3723.5),
    ('P1DT1S', 86401.0), ('PT0S', 0.0),
])
def test_duraciones(texto, segundos):
    assert n42._leer_duracion(texto) == segundos


@pytest.mark.parametrize('texto', ['', 'P', 'PT', 'P1M', 'P1Y', '-PT1S', '60', None])
def test_duraciones_que_no_se_pueden_convertir(texto):
    with pytest.raises(ValueError, match='duración'):
        n42._leer_duracion(texto)


@pytest.mark.parametrize('texto, esperado', [
    ('2020-01-02T03:04:05Z', 1577934245.0),
    ('2020-01-02T03:04:05+00:00', 1577934245.0),
    ('2020-01-02T00:04:05-03:00', 1577934245.0),
    ('2020-01-02T03:04:05.25Z', 1577934245.25),
    ('2020-01-02T03:04:05.123456789Z', 1577934245.123456789),
])
def test_fechas(texto, esperado):
    assert n42._leer_fecha(texto) == pytest.approx(esperado, abs=1e-6)


def test_fecha_ilegible(tmp_path):
    with pytest.raises(ValueError, match='fecha'):
        A.mca_load_file(_ajeno(tmp_path, inicio='ayer'))


def test_con_varios_espectros_devuelve_el_primero_y_avisa(tmp_path):
    otro = ('<Spectrum id="s2" radDetectorInformationReference="d" '
            'energyCalibrationReference="e"><LiveTimeDuration>PT1S</LiveTimeDuration>'
            '<ChannelData>9 9</ChannelData></Spectrum>')
    ruta = _ajeno(tmp_path, mas=otro)
    with pytest.warns(UserWarning, match='2 espectros'):
        hist, meta = A.mca_load_file(ruta)
    assert hist.tolist() == [1, 2, 3]
    assert meta['n42_n_espectros'] == 2


def test_con_un_espectro_no_avisa(tmp_path):
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        A.mca_load_file(_ajeno(tmp_path))


def test_no_es_n42(tmp_path):
    ruta = tmp_path / 'viejo.n42'
    ruta.write_text('<N42InstrumentData xmlns="http://physics.nist.gov/Divisions/'
                    'Div846/Gp4/ANSIN4242/2005/ANSIN4242"/>')
    with pytest.raises(ValueError, match='no es N42.42-2011'):
        A.mca_load_file(str(ruta))


def test_sin_espectro(tmp_path):
    ruta = tmp_path / 'vacio.n42'
    ruta.write_text(f'<RadInstrumentData xmlns="{n42.NS}"/>')
    with pytest.raises(ValueError, match='ningún Spectrum'):
        A.mca_load_file(str(ruta))
