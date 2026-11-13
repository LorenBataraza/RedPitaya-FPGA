"""ANSI N42.42-2011: el espectro del MCA en el formato de intercambio estándar.

Es un XML que abren otros programas de espectroscopía. Se guarda sólo el espectro
1D: el mapa 2D no entra en el formato. La API pública es `mca_save_file_n42` y la
rama `.n42` de `mca_load_file`, en `API/mca.py`; este módulo no toca hardware.

Lo que el MCA no sabe, se dice en vez de inventarlo:

  - **Energía.** El MCA cuenta canales. Sin `calibracion`, el archivo lleva
    `CoefficientValues = 0 1 0` y un `Remark` que aclara que son canales, no keV.
  - **Detector.** Sin `detector`, va `Other`/`Other` con su descripción, porque el
    MCA no sabe qué hay a la entrada. La Schematron de NIST exige la descripción
    cuando alguno de los dos códigos es `Other`.

La metadata completa viaja en un `Remark`, como JSON con el prefijo `mca-meta:`: es
lo que hace exacta la ida y vuelta. Las `*Extension` del formato son abstractas y
pedirían un esquema propio; un `Remark` valida sin nada más.

Validez, comprobada en `API/tests/test_n42.py`: contra el XSD 0.0.54 de NIST, que
está en `API/tests/datos_ref/n42/`, igual que las reglas (`n42.sch`). Las reglas
están en XSLT 2 y `lxml` no las corre: se comprobaron una vez a mano, con Saxon.
"""

import datetime
import json
import math
import os
import re
import time
import uuid
import warnings
import xml.etree.ElementTree as ET

import numpy as np

NS = 'http://physics.nist.gov/N42/2011/N42'

# Los códigos del XSD. `test_n42.py` exige que coincidan con el esquema: uno mal
# escrito da un archivo que abre acá y otro programa rechaza.
CLASES_MEDICION = ('Foreground', 'Background', 'Calibration', 'IntrinsicActivity',
                   'NotSpecified')
CATEGORIAS_DETECTOR = ('Gamma', 'Neutron', 'Alpha', 'Beta', 'X-ray', 'Other')
TIPOS_DETECTOR = ('HPGe', 'HPXe', 'NaI', 'LaBr3', 'LaCl3', 'BGO', 'CZT', 'CdTe',
                  'CsI', 'GMT', 'GMTW', 'LiFiber', 'PVT', 'PS', 'He3', 'He4',
                  'LiGlass', 'LiI', 'SrI2', 'CLYC', 'CdWO4', 'BF3', 'HgI2',
                  'CeBr4', 'LiCAF', 'LiZnS', 'Other')

INSTRUMENTO_DEFECTO = {'fabricante': 'Red Pitaya, con la PL de este proyecto',
                       'modelo': 'Analizador multicanal en FPGA'}

_PREFIJO_META = 'mca-meta:'
_SIN_DETECTOR = ('No declarado: el MCA no sabe qué detector hay a la entrada. '
                 'Pasar detector= al guardar.')
_SIN_CALIBRAR = ('Sin calibrar: E = C, con C el índice de canal desde 0. Son '
                 'canales, no keV.')

_CANALES_POR_LINEA = 16
_CANALES_MAX = 1 << 24      # tope al descomprimir: un archivo roto no agota la RAM


def _q(etiqueta):
    return f'{{{NS}}}{etiqueta}'


def _sub(padre, etiqueta, texto=None, **attrs):
    e = ET.SubElement(padre, _q(etiqueta), attrs)
    if texto is not None:
        e.text = texto
    return e


# =============================================================================
# Escritura
# =============================================================================

def _duracion(s):
    return f'PT{s:.6f}S'


def _fecha(t):
    d = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    return d.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _canales(hist):
    """El espectro validado, como lista de enteros de Python."""
    h = np.asarray(hist)
    if h.ndim != 1 or h.size == 0:
        raise ValueError(f'N42.42 guarda un espectro 1D, y esto tiene forma {h.shape}')
    if not np.issubdtype(h.dtype, np.integer) and not np.all(h == np.rint(h)):
        raise ValueError('N42.42 guarda cuentas enteras, y el espectro no lo es')
    if np.any(h < 0):
        raise ValueError('N42.42 no admite cuentas negativas')
    return h.astype(np.int64).tolist()


def _tiempos(meta):
    """(inicio, real, vivo) en segundos, o ValueError si el formato no se puede
    cumplir. No se inventa ninguno: un tiempo de mentira da un espectro que parece
    bueno y no lo es."""
    def numero(clave):
        v = meta.get(clave)
        if v is None:
            raise ValueError(f'N42.42 exige {clave} en la metadata: pasar '
                             'meta=mca_get_metadata(h)')
        return float(v)

    real = numero('realtime_s')
    vivo = numero('livetime_s')
    t_wall = numero('t_wall')
    if not (math.isfinite(real) and real > 0):
        raise ValueError(f'N42.42 exige un tiempo real mayor que cero, y realtime_s '
                         f'= {real}: el MCA todavía no midió')
    if not (math.isfinite(vivo) and vivo >= 0):
        raise ValueError(f'livetime_s = {vivo}: tiene que ser finito y no negativo')
    if not math.isfinite(t_wall):
        raise ValueError(f't_wall = {t_wall}: tiene que ser finito')
    # Los dos relojes no se leen en el mismo instante: leídos en caliente, el vivo
    # puede pasarse del real, y el estándar lo exige menor o igual.
    return t_wall - real, real, min(vivo, real)


def _detector(detector):
    """{categoria, tipo, descripcion, nombre}, validado. Sin dato, `Other`."""
    if detector is None:
        return {'categoria': 'Other', 'tipo': 'Other', 'descripcion': _SIN_DETECTOR}
    desconocidas = set(detector) - {'categoria', 'tipo', 'descripcion', 'nombre'}
    if desconocidas:
        raise ValueError(f'detector: claves desconocidas {sorted(desconocidas)}')
    d = dict(detector)
    d.setdefault('categoria', 'Other')
    d.setdefault('tipo', 'Other')
    if d['categoria'] not in CATEGORIAS_DETECTOR:
        raise ValueError(f"detector categoria={d['categoria']!r}: tiene que ser una "
                         f'de {CATEGORIAS_DETECTOR}')
    if d['tipo'] not in TIPOS_DETECTOR:
        raise ValueError(f"detector tipo={d['tipo']!r}: tiene que ser uno de "
                         f'{TIPOS_DETECTOR}')
    if 'Other' in (d['categoria'], d['tipo']) and not d.get('descripcion'):
        raise ValueError("N42.42 exige detector descripcion cuando categoria o tipo "
                         "es 'Other'")
    return d


def _instrumento(instrumento):
    desconocidas = set(instrumento or ()) - set(INSTRUMENTO_DEFECTO)
    if desconocidas:
        raise ValueError(f'instrumento: claves desconocidas {sorted(desconocidas)}')
    return {k: (instrumento or {}).get(k) or v for k, v in INSTRUMENTO_DEFECTO.items()}


def _coeficientes(calibracion):
    """(T0, T1, T2) para E = T0 + T1·C + T2·C², en keV. T2 se puede omitir: el
    estándar pide los tres, con T2 = 0 si la calibración es lineal."""
    c = [float(x) for x in calibracion]
    if len(c) not in (2, 3):
        raise ValueError(f'calibracion: se esperaba (T0, T1) o (T0, T1, T2), y son '
                         f'{len(c)} valores')
    if not all(math.isfinite(x) for x in c):
        raise ValueError(f'calibracion: valores no finitos en {c}')
    return (c + [0.0])[:3]


def _meta_json(meta):
    """La metadata, sin lo que ya está en los elementos del estándar."""
    propia = {k: v for k, v in meta.items() if not k.startswith('n42_')}
    return _PREFIJO_META + json.dumps(propia)


def escribir(hist, path, meta, detector=None, calibracion=None, clase=None,
             instrumento=None, avisos=()):
    """Escribe el archivo. Valida antes de abrirlo: si algo no se puede cumplir,
    falla sin dejar nada en disco.

    Lo que venga en `None` se toma de `meta['n42_*']`, si está: es lo que hace que
    guardar un `.n42` releído no pierda la calibración ni el detector.

    `avisos` son `Remark` del espectro: lo que hay que saber para leer sus canales.
    """
    meta = dict(meta or {})
    canales = _canales(hist)
    inicio, real, vivo = _tiempos(meta)

    if detector is None:
        detector = meta.get('n42_detector')
    if calibracion is None:
        calibracion = meta.get('n42_calibracion')
    if instrumento is None:
        instrumento = meta.get('n42_instrumento')
    if clase is None:
        clase = meta.get('n42_clase') or 'NotSpecified'
    if clase not in CLASES_MEDICION:
        raise ValueError(f'clase={clase!r}: tiene que ser una de {CLASES_MEDICION}')
    det = _detector(detector)
    coef = None if calibracion is None else _coeficientes(calibracion)
    instr = _instrumento(instrumento)

    ET.register_namespace('', NS)
    raiz = ET.Element(_q('RadInstrumentData'),
                      {'n42DocUUID': str(uuid.uuid4()),
                       'n42DocDateTime': _fecha(time.time())})
    _sub(raiz, 'RadInstrumentDataCreatorName', 'API/mca.py')

    i = _sub(raiz, 'RadInstrumentInformation', id='instrumento')
    _sub(i, 'RadInstrumentManufacturerName', instr['fabricante'])
    _sub(i, 'RadInstrumentModelName', instr['modelo'])
    _sub(i, 'RadInstrumentClassCode', 'Other')
    versiones = [('Mapa de registros', meta.get('mapa') or 'desconocido')]
    if meta.get('libmca_version'):
        versiones.append(('libmca', meta['libmca_version']))
    for nombre, version in versiones:
        v = _sub(i, 'RadInstrumentVersion')
        _sub(v, 'RadInstrumentComponentName', nombre)
        _sub(v, 'RadInstrumentComponentVersion', str(version))

    d = _sub(raiz, 'RadDetectorInformation', id='detector')
    if det.get('nombre'):
        _sub(d, 'RadDetectorName', det['nombre'])
    _sub(d, 'RadDetectorCategoryCode', det['categoria'])
    _sub(d, 'RadDetectorKindCode', det['tipo'])
    if det.get('descripcion'):
        _sub(d, 'RadDetectorDescription', det['descripcion'])

    c = _sub(raiz, 'EnergyCalibration', id='calibracion')
    if coef is None:
        _sub(c, 'Remark', _SIN_CALIBRAR)
    _sub(c, 'CoefficientValues',
         '0 1 0' if coef is None else ' '.join(repr(x) for x in coef))

    m = _sub(raiz, 'RadMeasurement', id='medicion')
    _sub(m, 'Remark', _meta_json(meta))
    _sub(m, 'MeasurementClassCode', clase)
    _sub(m, 'StartDateTime', _fecha(inicio))
    _sub(m, 'RealTimeDuration', _duracion(real))

    e = _sub(m, 'Spectrum', id='espectro', radDetectorInformationReference='detector',
             energyCalibrationReference='calibracion')
    for aviso in avisos:
        _sub(e, 'Remark', aviso)
    _sub(e, 'LiveTimeDuration', _duracion(vivo))
    lineas = (' '.join(map(str, canales[k:k + _CANALES_POR_LINEA]))
              for k in range(0, len(canales), _CANALES_POR_LINEA))
    _sub(e, 'ChannelData', '\n' + '\n'.join(lineas) + '\n', compressionCode='None')

    texto = ET.tostring(raiz, encoding='utf-8', xml_declaration=True)
    with open(os.fspath(path), 'wb') as f:
        f.write(texto)


# =============================================================================
# Lectura
# =============================================================================

_RE_DURACION = re.compile(
    r'P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d*)?)S)?)?')
_RE_FECHA = re.compile(
    r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)?')


def _leer_duracion(texto):
    """xsd:duration -> segundos. Sólo días para abajo: un mes no dura fijo."""
    m = _RE_DURACION.fullmatch((texto or '').strip())
    if m is None or not any(m.groups()):
        raise ValueError(f'duración que no se puede convertir a segundos: {texto!r}')
    dias, horas, minutos, seg = (float(g or 0) for g in m.groups())
    return dias * 86400 + horas * 3600 + minutos * 60 + seg


def _leer_fecha(texto):
    """xsd:dateTime -> segundos Unix. XSD deja indeterminada una fecha sin zona
    horaria: se toma como hora local."""
    m = _RE_FECHA.fullmatch((texto or '').strip())
    if m is None:
        raise ValueError(f'fecha que no se puede leer: {texto!r}')
    d = datetime.datetime.strptime(m[1], '%Y-%m-%dT%H:%M:%S')
    zona = m[3]
    if zona == 'Z':
        d = d.replace(tzinfo=datetime.timezone.utc)
    elif zona:
        signo = -1 if zona[0] == '-' else 1
        desvio = datetime.timedelta(hours=int(zona[1:3]), minutes=int(zona[4:6]))
        d = d.replace(tzinfo=datetime.timezone(signo * desvio))
    return d.timestamp() + float(m[2] or 0)


def _descomprimir_ceros(v):
    """`CountedZeroes`: un 0 seguido de cuántos ceros son. `22 0 3 7` -> `22 0 0 0 7`."""
    salida, i = [], 0
    while i < len(v):
        if v[i] != 0:
            salida.append(v[i])
            i += 1
            continue
        if i + 1 >= len(v):
            raise ValueError('CountedZeroes: la lista termina en un cero, sin su cantidad')
        cuantos = v[i + 1]
        if cuantos <= 0 or cuantos != int(cuantos):
            raise ValueError(f'CountedZeroes: la cantidad de ceros es {cuantos}, y '
                             'tiene que ser un entero mayor que cero')
        if len(salida) + cuantos > _CANALES_MAX:
            raise ValueError(f'CountedZeroes: da más de {_CANALES_MAX} canales')
        salida.extend([0.0] * int(cuantos))
        i += 2
    return salida


def _leer_canales(elem):
    try:
        v = [float(x) for x in (elem.text or '').split()]
    except ValueError as e:
        raise ValueError(f'ChannelData: {e}') from None
    codigo = elem.get('compressionCode', 'None')
    if codigo == 'CountedZeroes':
        v = _descomprimir_ceros(v)
    elif codigo != 'None':
        raise ValueError(f'ChannelData: compressionCode={codigo!r} desconocido')
    h = np.asarray(v, dtype=np.float64)
    if h.size == 0:
        raise ValueError('ChannelData vacío')
    if not np.all(h == np.rint(h)) or h.min() < 0 or h.max() > 0xFFFFFFFF:
        raise ValueError('ChannelData trae valores que no son cuentas enteras de 32 b')
    return h.astype(np.uint32)


def _texto(padre, etiqueta):
    e = padre.find(_q(etiqueta))
    return None if e is None or e.text is None else e.text.strip()


def _calibracion_de(raiz, espectro):
    """Los coeficientes de la calibración a la que apunta el espectro, o None si
    está definida de otra forma (`EnergyBoundaryValues`, por ejemplo)."""
    ref = espectro.get('energyCalibrationReference')
    for c in raiz.findall(_q('EnergyCalibration')):
        if c.get('id') == ref:
            texto = _texto(c, 'CoefficientValues')
            return [float(x) for x in texto.split()] if texto else None
    return None


def _detector_de(raiz, espectro):
    ref = espectro.get('radDetectorInformationReference')
    detectores = raiz.findall(_q('RadDetectorInformation'))
    elegido = next((d for d in detectores if d.get('id') == ref),
                   detectores[0] if detectores else None)
    if elegido is None:
        return None
    d = {'categoria': _texto(elegido, 'RadDetectorCategoryCode'),
         'tipo': _texto(elegido, 'RadDetectorKindCode'),
         'descripcion': _texto(elegido, 'RadDetectorDescription'),
         'nombre': _texto(elegido, 'RadDetectorName')}
    return {k: v for k, v in d.items() if v is not None}


def leer(path):
    """(histograma uint32, metadata), de un archivo propio o ajeno.

    Si el archivo es de este proyecto, la metadata es la que se guardó. Si es ajeno,
    se arma lo que hace falta para mirar el espectro: `realtime_s`, `livetime_s`,
    `t_wall` y `n_channels`.

    Además, siempre, lo que dice el estándar: `n42_clase`, `n42_detector`,
    `n42_calibracion` (`[T0, T1, T2]`, o None si está definida de otra forma),
    `n42_instrumento` y `n42_n_espectros`. Con más de un `Spectrum` se devuelve el
    primero, y se avisa.
    """
    raiz = ET.parse(os.fspath(path)).getroot()
    if raiz.tag != _q('RadInstrumentData'):
        raise ValueError(f'{path}: no es N42.42-2011, la raíz es {raiz.tag!r}')

    pares = [(m, e) for m in raiz.findall(_q('RadMeasurement'))
             for e in m.findall(_q('Spectrum'))]
    if not pares:
        raise ValueError(f'{path}: no tiene ningún Spectrum')
    med, esp = pares[0]
    if len(pares) > 1:
        warnings.warn(f'{path}: tiene {len(pares)} espectros, y se devuelve el primero')

    datos = esp.find(_q('ChannelData'))
    if datos is None:
        raise ValueError(f'{path}: el Spectrum no tiene ChannelData')
    hist = _leer_canales(datos)

    meta = {}
    for r in med.findall(_q('Remark')):
        if (r.text or '').startswith(_PREFIJO_META):
            meta = json.loads(r.text[len(_PREFIJO_META):])
            break

    real = _leer_duracion(_texto(med, 'RealTimeDuration'))
    meta.setdefault('realtime_s', real)
    meta.setdefault('livetime_s', _leer_duracion(_texto(esp, 'LiveTimeDuration')))
    meta.setdefault('t_wall', _leer_fecha(_texto(med, 'StartDateTime')) + real)
    meta.setdefault('n_channels', int(hist.size))

    meta['n42_clase'] = _texto(med, 'MeasurementClassCode')
    meta['n42_calibracion'] = _calibracion_de(raiz, esp)
    meta['n42_detector'] = _detector_de(raiz, esp)
    instr = raiz.find(_q('RadInstrumentInformation'))
    if instr is not None:
        meta['n42_instrumento'] = {
            'fabricante': _texto(instr, 'RadInstrumentManufacturerName'),
            'modelo': _texto(instr, 'RadInstrumentModelName')}
    meta['n42_n_espectros'] = len(pares)

    # Un archivo propio sin calibrar dice `0 1 0` con su Remark: eso no es una
    # calibración, y guardarlo de vuelta tiene que seguir diciendo lo mismo.
    cal = raiz.find(_q('EnergyCalibration'))
    if cal is not None and _texto(cal, 'Remark') == _SIN_CALIBRAR:
        meta['n42_calibracion'] = None
    # Lo mismo para el detector: "no declarado" no es un dato que se conserve.
    if (meta['n42_detector'] or {}).get('descripcion') == _SIN_DETECTOR:
        meta['n42_detector'] = None
    return hist, meta
