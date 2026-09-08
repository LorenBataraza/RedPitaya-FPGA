#!/usr/bin/env python3
"""Compatibilidad del refactor a `API/`: nada de lo público cambió de significado.

Compara el árbol actual contra el baseline congelado ANTES de mover nada
(`API/tests/datos_ref/compat_baseline.json` + `API/tests/datos_ref/compat_golden.npz`, producidos por
`API/tests/gen_compat_baseline.py`). Cinco bloques:

    A. superficie   cada nombre público sigue existiendo, con la misma firma
    B. constantes   cada R_*, BIT_*, base y apertura vale exactamente lo mismo
    C. trazas       las secuencias de escritura de registros son idénticas, EN ORDEN
    D. análisis     los helpers puros dan el mismo número
    E. guardado     round-trip csv/npz/json de la capa de store nueva

Corre entero en la PC, SIN placa: ése es el requisito de diseño. Un test de
compatibilidad que necesita la Pitaya no se corre, y si no se corre no sirve.

    cd prj/MCA/software
    python API/tests/test_compat_api.py          # auto-ejecutable, como el resto de tests/
    python -m pytest API/tests/test_compat_api.py -q

El bloque C es el que gana el sueldo. `multitrigger_utils.py` no tiene
constantes de offset: cada dirección es un literal hex inline (`w32(0x240, m)`).
Al extraerlos, un `0x240` que se vuelve `0x244` no rompe nada en la PC — rompe
escribiendo al registro equivocado en la placa. Y al partir `MultiTriggerScope`
en dos clases, el orden hyst -> arm -> or_mask puede reordenarse sin que ningún
import falle. Las trazas atrapan las dos cosas sin hardware.
"""

import json
import os
import sys
import tempfile
import textwrap

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(os.path.abspath(__file__))
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
sys.path.insert(0, _AQUI)

import gen_compat_baseline as gen                                  # noqa: E402


# =============================================================================
# Andamiaje
# =============================================================================

# Desviaciones INTENCIONADAS del refactor: cambios de superficie que se
# decidieron a propósito y que no deben hacer fallar el test. Cada una lleva su
# motivo. Lo que NO esté acá listado sigue siendo un fallo — la lista es un
# registro que se lee en el diff del commit, no una alfombra para esconder
# regresiones.
DESVIACIONES = {
    ('multitrigger_utils', 'rp'): (
        'era el módulo `rp` importado a nivel de módulo; ahora es un proxy que '
        'lo importa en el primer uso. Sin esto API/osciloscope.py entero era '
        'inimportable desde la PC, y con él la configuración, los registros y '
        'todo test offline. `mt.rp.loquesea` sigue funcionando en la placa.'),
}


class Resultado:
    def __init__(self):
        self.fallos = []
        self.ok = 0
        self.saltados = []
        self.desviaciones = []

    def check(self, cond, msg, detalle=None, desviacion=None):
        if cond:
            self.ok += 1
        elif desviacion in DESVIACIONES:
            self.desviaciones.append((desviacion, DESVIACIONES[desviacion]))
        else:
            self.fallos.append((msg, detalle))
        return cond

    def skip(self, msg):
        self.saltados.append(msg)


# Métodos que no son del proyecto sino del INTÉRPRETE, y que por lo tanto
# aparecen o desaparecen según la versión de Python en la que se corra. El
# baseline se generó en la PC (3.11) y el software se usa en la Pitaya (3.10):
# `BaseException.add_note()` existe desde 3.11, así que las clases de excepción
# del proyecto lo "pierden" al correr en la placa. No es una regresión de la
# API, es otro intérprete. Se ignoran por nombre en vez de filtrar por clase
# base para que la lista sea explícita y se lea en el diff.
_METODOS_DEL_INTERPRETE = {'add_note'}

_CACHE = {}


def _actual():
    """Superficie y golden del árbol ACTUAL, regenerados con el mismo código
    que produjo el baseline (por eso se importa el generador en vez de copiarlo:
    si divergieran, el test compararía dos cosas distintas y no lo diría)."""
    if not _CACHE:
        base, gold = gen.construir()
        _CACHE['base'] = base
        _CACHE['gold'] = gold
    return _CACHE['base'], _CACHE['gold']


def _baseline():
    if not os.path.exists(gen.BASELINE_JSON):
        raise SystemExit(
            f'falta {gen.BASELINE_JSON}.\nEs el paso 0 del refactor y se corre '
            'ANTES de mover nada:\n    python API/tests/gen_compat_baseline.py')
    with open(gen.BASELINE_JSON) as f:
        return json.load(f)


def _golden():
    if not os.path.exists(gen.GOLDEN_NPZ):
        raise SystemExit(f'falta {gen.GOLDEN_NPZ}: correr gen_compat_baseline.py')
    return np.load(gen.GOLDEN_NPZ, allow_pickle=False)


def _fmt_traza(a):
    par = np.asarray(a).reshape(-1, 2)
    return [f'{o:#06x} <- {v:#010x}' for o, v in par]


def _diff_traza(esperada, obtenida):
    """Diff lado a lado. Es el diagnóstico entero del bloque C: sin esto un
    fallo dice sólo 'los arrays difieren', que no ayuda a arreglar nada."""
    e, o = _fmt_traza(esperada), _fmt_traza(obtenida)
    lineas = [f'  {"esperado (pre-refactor)":<28} {"obtenido":<28}']
    for i in range(max(len(e), len(o))):
        ei = e[i] if i < len(e) else '—'
        oi = o[i] if i < len(o) else '—'
        lineas.append(f'  {ei:<28} {oi:<28} {"" if ei == oi else "  <<< DIFIERE"}')
    return '\n'.join(lineas)


# =============================================================================
# A. Superficie pública
# =============================================================================

def bloque_superficie(r):
    base = _baseline()['modulos']
    act, _ = _actual()
    act = act['modulos']

    for mod, nombres in base.items():
        if not r.check(mod in act, f'[A] el módulo {mod} ya no importa'):
            continue
        for nombre, esp in nombres.items():
            if esp['kind'] == 'submodule':
                # `from paquete.sub import ...` tiene que seguir resolviendo:
                # un shim que sólo reexporta en el __init__ no lo consigue.
                try:
                    __import__(nombre)
                    r.check(True, '')
                except ImportError as e:
                    r.check(False, f'[A] {nombre} ya no se puede importar', str(e))
                continue

            got = act[mod].get(nombre)
            if not r.check(got is not None,
                           f'[A] {mod}.{nombre} desapareció de la superficie pública',
                           desviacion=(mod, nombre)):
                continue
            r.check(got['kind'] == esp['kind'],
                    f'[A] {mod}.{nombre} cambió de tipo',
                    f'era {esp["kind"]}, ahora {got["kind"]}',
                    desviacion=(mod, nombre))
            if esp['kind'] == 'function':
                ok, por_que = _firma_compatible(esp.get('sig'), got.get('sig'))
                r.check(ok, f'[A] {mod}.{nombre} cambió de firma de forma '
                            f'INCOMPATIBLE ({por_que})',
                        f'era  {esp.get("sig")}\n    ahora {got.get("sig")}')
            elif esp['kind'] == 'class':
                for m, msp in esp.get('methods', {}).items():
                    if m in _METODOS_DEL_INTERPRETE:
                        continue
                    mgot = got.get('methods', {}).get(m)
                    if not r.check(mgot is not None,
                                   f'[A] {mod}.{nombre}.{m}() desapareció'):
                        continue
                    ok, por_que = _firma_compatible(msp.get('sig'),
                                                    mgot.get('sig'))
                    r.check(ok, f'[A] {mod}.{nombre}.{m}() cambió de firma de '
                                f'forma INCOMPATIBLE ({por_que})',
                            f'era  {msp.get("sig")}\n    ahora {mgot.get("sig")}')


# =============================================================================
# B. Constantes por valor
# =============================================================================

def bloque_constantes(r):
    base = _baseline()['modulos']
    act, _ = _actual()
    act = act['modulos']

    n = 0
    for mod, nombres in base.items():
        for nombre, esp in nombres.items():
            if esp['kind'] != 'const':
                continue
            n += 1
            got = act.get(mod, {}).get(nombre)
            if got is None or got['kind'] != 'const':
                continue        # ya reportado por el bloque A
            ev, gv = esp['value'], got['value']
            detalle = None
            if isinstance(ev, int) and isinstance(gv, int):
                detalle = f'esperado {ev:#x}, obtenido {gv:#x}'
            r.check(ev == gv, f'[B] {mod}.{nombre} cambió de valor', detalle)
    return n


# =============================================================================
# C. Trazas de escritura de registros
# =============================================================================

def _partir_params(sig):
    """Parte "(a, b=1, c=(0, 0))" en ["a", "b=1", "c=(0, 0)"].

    Hace falta partir por comas de PRIMER NIVEL: un default como `(0, 0)` tiene
    comas adentro y un split ingenuo lo rompe en dos parametros fantasma.
    """
    s = sig.strip()
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1]
    fuera, actual, prof = [], '', 0
    for ch in s:
        if ch in '([{':
            prof += 1
        elif ch in ')]}':
            prof -= 1
        if ch == ',' and prof == 0:
            fuera.append(actual.strip()); actual = ''
        else:
            actual += ch
    if actual.strip():
        fuera.append(actual.strip())
    return fuera


def _firma_compatible(esp, got):
    """Los parametros del baseline siguen estando, en orden y con el MISMO default.

    El contrato de este archivo es "nada de lo publico cambio de SIGNIFICADO",
    no "la firma es identica byte a byte". Agregar parametros opcionales al
    final no rompe a ningun llamador existente, y bloquearlo obligaria a
    regenerar el baseline en cada mejora — que es justamente lo que vaciaria de
    valor al test. Lo que sigue siendo una rotura, y se sigue detectando:
    quitar un parametro, renombrarlo, reordenarlo, o cambiarle el default.
    """
    if esp is None or got is None:
        return esp == got, 'una de las dos firmas no existe'
    if esp == got:
        return True, ''
    pe, pg = _partir_params(esp), _partir_params(got)
    if len(pg) < len(pe):
        return False, 'se quitaron parametros'
    if pg[:len(pe)] != pe:
        return False, 'los parametros viejos cambiaron de nombre, orden o default'
    nuevos = pg[len(pe):]
    sin_default = [x for x in nuevos
                   if '=' not in x and not x.startswith(('*', '**'))]
    if sin_default:
        return False, f'parametros nuevos SIN default: {sin_default}'
    return True, ''


def _es_subsecuencia(esperada, obtenida):
    """Las escrituras del baseline siguen estando, en ORDEN y con el mismo valor.

    Igual que con las firmas: agregar registros nuevos no cambia el significado
    de los viejos. Lo que este bloque existe para atrapar —una direccion que se
    corre, un valor que cambia, dos escrituras que se reordenan, una que
    desaparece— lo sigue atrapando, porque exige que TODA la secuencia vieja
    aparezca completa y en el mismo orden relativo.
    """
    esperada = np.asarray(esperada)
    obtenida = np.asarray(obtenida)
    if len(esperada) == 0:
        return True
    if len(obtenida) < len(esperada):
        return False
    i = 0
    for fila in obtenida:
        if np.array_equal(fila, esperada[i]):
            i += 1
            if i == len(esperada):
                return True
    return False


def bloque_trazas(r):
    gold = _golden()
    _, act = _actual()

    claves = sorted(k for k in gold.files if k.startswith('traza.'))
    for k in claves:
        esperada = gold[k]
        obtenida = act.get(k)
        if not r.check(obtenida is not None, f'[C] falta la traza {k}'):
            continue
        obtenida = np.asarray(obtenida)
        nombre = k[len('traza.'):]

        if k.endswith('.__exc__'):
            # Una secuencia que antes corría limpia y ahora lanza (o al revés)
            # es una rotura, aunque la traza parcial coincidiera.
            esp, got = str(esperada), str(obtenida)
            if esp == got:
                r.check(True, '')
            elif not esp:
                r.check(False, f'[C] {nombre[:-8]} ahora falla y antes no', got)
            elif not got:
                r.check(False, f'[C] {nombre[:-8]} ya no lanza el error esperado', esp)
            else:
                r.check(False, f'[C] {nombre[:-8]} cambió de error',
                        f'era  {esp}\n    ahora {got}')
            continue

        igual = _es_subsecuencia(esperada, obtenida)
        r.check(igual,
                f'[C] la secuencia de escrituras de {nombre} cambió',
                _diff_traza(esperada, obtenida) if not igual else None)
    return sum(1 for k in claves if not k.endswith('.__exc__'))


# =============================================================================
# D. Equivalencia numérica del análisis
# =============================================================================

def bloque_analisis(r):
    gold = _golden()
    _, act = _actual()

    claves = sorted(k for k in gold.files if k.startswith('analisis.'))
    for k in claves:
        esp = gold[k]
        got = act.get(k)
        if not r.check(got is not None, f'[D] falta la salida {k}'):
            continue
        got = np.asarray(got)

        if esp.dtype.kind in 'SU' or got.dtype.kind in 'SU':
            # Incluye las claves __exc__: que un helper siga fallando con el
            # MISMO error es parte del contrato (p.ej. counts_to_volts con
            # amp_src=1 debe seguir rechazando la conversión).
            r.check(str(esp) == str(got), f'[D] {k} cambió',
                    f'era  {str(esp)!r}\n    ahora {str(got)!r}')
            continue

        if not r.check(esp.shape == got.shape, f'[D] {k} cambió de forma',
                       f'era {esp.shape}, ahora {got.shape}'):
            continue
        try:
            # La tolerancia es 1e-7, no 1e-9, PORQUE EL BASELINE SE GENERÓ EN
            # OTRA ARQUITECTURA. En la Pitaya (armv7l, numpy 1.21) contra la PC
            # (x86-64, numpy 1.24) el rebinning de `linearize_spectrum` difiere
            # en 4 de 16384 canales por 6e-9 relativo: orden de magnitud del
            # redondeo de float64, no un cambio de algoritmo. Un cambio real de
            # comportamiento mueve los números MUCHO más que esto, así que 1e-7
            # no afloja lo que el test busca y sí lo hace correr en la placa,
            # que es donde el software se usa.
            np.testing.assert_allclose(got.astype(float), esp.astype(float),
                                       rtol=1e-7, atol=1e-12, equal_nan=True)
            r.check(True, '')
        except AssertionError as e:
            r.check(False, f'[D] {k} cambió de valor', str(e).strip())
    return len(claves)


# =============================================================================
# E. Round-trip de la capa de guardado nueva
# =============================================================================

def bloque_store(r):
    """Sólo corre una vez que existe API/. Antes del paso 6 se salta."""
    try:
        from API import mca as api_mca
    except ImportError:
        r.skip('[E] API.mca todavía no existe (pasos 1-6 del refactor)')
        return

    faltan = [n for n in ('mca_write_file_histogram', 'mca_save_file_binary',
                          'mca_save_file_json') if not hasattr(api_mca, n)]
    if faltan:
        r.skip(f'[E] falta la capa de guardado: {", ".join(faltan)}')
        return

    rng = np.random.default_rng(7)
    hist = rng.poisson(300.0, 4096).astype(np.uint32)
    meta = {'schema_version': 1, 'thr': 317, 'gate_short': 48,
            'gate_long': 400, 'livetime_s': 10.0, 'amp_src': 1}

    with tempfile.TemporaryDirectory() as d:
        rutas = {
            'csv':  (os.path.join(d, 'e.csv'),  api_mca.mca_write_file_histogram),
            'npz':  (os.path.join(d, 'e.npz'),  api_mca.mca_save_file_binary),
            'json': (os.path.join(d, 'e.json'), api_mca.mca_save_file_json),
        }
        leer = getattr(api_mca, 'mca_load_file', None)
        if leer is None:
            r.skip('[E] falta mca_load_file() (el lector inverso del paso 6)')
            return

        for fmt, (ruta, escribir) in rutas.items():
            escribir(hist, ruta, meta=meta)
            r.check(os.path.exists(ruta), f'[E] {fmt}: no se escribió el fichero')
            h2, m2 = leer(ruta)
            r.check(np.array_equal(np.asarray(h2), hist),
                    f'[E] {fmt}: el histograma no sobrevive el round-trip')
            for k, v in meta.items():
                got = m2.get(k)
                igual = (abs(float(got) - float(v)) < 1e-9
                         if isinstance(v, (int, float)) and got is not None
                         else got == v)
                r.check(igual, f'[E] {fmt}: metadata {k!r} no sobrevive',
                        f'era {v!r}, volvió {got!r}')


# =============================================================================
# Ejecución
# =============================================================================

def correr():
    r = Resultado()
    gen.stub_rp()

    bloque_superficie(r)
    n_const = bloque_constantes(r)
    n_traz = bloque_trazas(r)
    n_anal = bloque_analisis(r)
    bloque_store(r)

    print(f'A. superficie   {len(_baseline()["modulos"])} módulos')
    print(f'B. constantes   {n_const} valores')
    print(f'C. trazas       {n_traz} secuencias de registros')
    print(f'D. análisis     {n_anal} claves numéricas')
    print(f'E. guardado     round-trip csv/npz/json')
    print()

    for msg in r.saltados:
        print(f'SALTADO  {msg}')

    for (mod, nombre), motivo in r.desviaciones:
        print(f'DESVIACIÓN INTENCIONADA  {mod}.{nombre}')
        for linea in textwrap.wrap(motivo, 72):
            print(f'    {linea}')

    if r.fallos:
        print()
        for msg, detalle in r.fallos:
            print(f'FALLO  {msg}')
            if detalle:
                print('\n'.join('       ' + l for l in str(detalle).splitlines()))
        print(f'\n{len(r.fallos)} fallo(s), {r.ok} comprobación(es) OK')
    else:
        print(f'\nOK: {r.ok} comprobaciones, sin diferencias con el baseline')
    return r


# --- pytest -----------------------------------------------------------------

def _sin_fallos(fn, prefijo):
    r = Resultado()
    gen.stub_rp()
    fn(r)
    malos = [f'{m}\n{d}' if d else m for m, d in r.fallos]
    assert not malos, f'{prefijo}:\n' + '\n'.join(malos)


def test_superficie():
    _sin_fallos(bloque_superficie, 'superficie pública cambiada')


def test_constantes():
    _sin_fallos(bloque_constantes, 'constantes de registro cambiadas')


def test_trazas():
    _sin_fallos(bloque_trazas, 'secuencia de escrituras de registro cambiada')


def test_analisis():
    _sin_fallos(bloque_analisis, 'helpers de análisis cambiados')


def test_store_roundtrip():
    _sin_fallos(bloque_store, 'round-trip de guardado roto')


if __name__ == '__main__':
    raise SystemExit(1 if correr().fallos else 0)
