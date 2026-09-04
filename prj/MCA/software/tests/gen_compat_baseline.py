#!/usr/bin/env python3
"""Congela la superficie pública y el comportamiento del software PRE-refactor.

Se corre UNA vez, sobre el árbol ANTES de mover nada a `API/` (paso 0 del
refactor). Produce dos ficheros que `test_compat_api.py` usa como referencia:

    tests/compat_baseline.json   superficie: nombres, tipos, firmas, y el VALOR
                                 de cada constante de los tres módulos públicos
    tests/compat_golden.npz      salidas numéricas de los helpers de análisis +
                                 trazas ordenadas de escritura de registros

Corre entero en la PC, sin placa: el acceso a hardware se sustituye por un
`FakeMmap` y el módulo `rp` (que sólo existe en la Pitaya) por un stub.

Uso:

    cd prj/MCA/software
    python tests/gen_compat_baseline.py           # escribe los dos ficheros
    python tests/gen_compat_baseline.py --check   # regenera y compara, sin escribir

Regenerar el baseline DESPUÉS del refactor anula el sentido del test. Si un
cambio de API es deliberado, se regenera a propósito y se revisa el diff del
JSON en el commit — que es exactamente el registro que se quiere.
"""

import argparse
import ast
import inspect
import json
import os
import struct
import sys
import types

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_SOFT = os.path.join(_AQUI, '..')
sys.path.insert(0, _SOFT)

BASELINE_JSON = os.path.join(_AQUI, 'compat_baseline.json')
GOLDEN_NPZ    = os.path.join(_AQUI, 'compat_golden.npz')

_U32 = struct.Struct('<I')

# Módulos cuya superficie se congela: los puntos de entrada públicos que el
# refactor convierte en shims sobre API/. `rigol_dg4162` se movió entero sin
# partirlo, pero entra igual — mover un fichero sin dejar shim rompe a todo el
# que hacía `import rigol_dg4162 as rg`, y eso pasó de verdad durante el
# refactor: lo cazó la suite offline, no este test, porque faltaba de la lista.
MODULOS = ('mca_utils', 'multitrigger_utils', 'mca', 'rigol_dg4162')


# =============================================================================
# Stubs: correr sin placa
# =============================================================================

def stub_rp():
    """Instala un `rp` falso si el de verdad no está (o sea, en la PC).

    `multitrigger_utils` hace `import rp` a nivel de módulo, así que sin esto
    ni siquiera se puede inspeccionar su superficie fuera de la Pitaya. El stub
    sólo necesita existir: nada de lo que se congela acá llama a la librería.
    """
    try:
        import rp                                              # noqa: F401
        return False
    except ImportError:
        pass

    mod = types.ModuleType('rp')
    mod.__doc__ = 'stub de gen_compat_baseline.py (no es la librería real)'

    def _falta(nombre):
        def _f(*a, **k):
            raise RuntimeError(
                f'rp.{nombre}() llamado en la PC: el stub de compatibilidad no '
                'implementa la librería de RedPitaya. Este camino necesita placa.')
        return _f

    # Sólo los nombres que el árbol referencia a nivel de módulo.
    for n in ('rp_Init', 'rp_Release', 'rp_AcqReset', 'rp_AcqStart',
              'rp_AcqGetDataPosV', 'rp_AcqGetTriggerState', 'fBuffer'):
        setattr(mod, n, _falta(n))
    sys.modules['rp'] = mod
    return True


class FakeMmap(bytearray):
    """mmap de mentira que REGISTRA cada escritura de 32 bits, en orden.

    Los drivers acceden a los registros exactamente de dos formas:

        escribir:  self._mmap[off:off+4] = _U32.pack(v)
        leer:      _U32.unpack_from(self._mmap, off)

    `bytearray` cubre las dos (la lectura por el protocolo de buffer, que la
    subclase conserva) y permite interceptar la escritura. Como los drivers
    reciben el mmap en `__init__`, no hace falta parchear `open()`: se
    construye el objeto con esta instancia y listo.

    El `assert` de tamaño no es decorativo: asignar por slice a un bytearray
    fuera de rango lo REDIMENSIONA en silencio, cosa que un mmap real nunca
    hace. Sin el assert, un offset equivocado pasaría el test en vez de fallar.
    """

    def __init__(self, size):
        super().__init__(size)
        self.writes = []

    def __setitem__(self, k, v):
        if isinstance(k, slice):
            n = k.stop - k.start
            assert n == len(v) and k.stop <= len(self), (
                f'escritura fuera de rango [{k.start:#x}:{k.stop:#x}) sobre un '
                f'buffer de {len(self):#x}: un mmap real abortaría, no crecería')
            self.writes.append((k.start, _U32.unpack(bytes(v))[0]))
        super().__setitem__(k, v)

    def poke(self, off, val):
        """Escribe SIN registrar: para precargar magic/caps/widths."""
        super().__setitem__(slice(off, off + 4), _U32.pack(val & 0xFFFFFFFF))

    def trace(self):
        """La traza como lista plana [off0, val0, off1, val1, ...] (para npz)."""
        return np.array([x for par in self.writes for x in par], dtype=np.int64)


# =============================================================================
# Bloques A y B: superficie pública y valores de las constantes
# =============================================================================

def _firma(obj):
    try:
        return str(inspect.signature(obj))
    except (ValueError, TypeError):
        return '<sin firma>'


def _es_const(v):
    return isinstance(v, (int, float, str, bool, type(None)))


def _valor_const(v):
    if isinstance(v, (tuple, list)):
        return [_valor_const(x) for x in v]
    if isinstance(v, float) and (v != v or v in (float('inf'), float('-inf'))):
        return repr(v)
    return v


def describir(obj):
    """Clasifica un objeto público en una entrada serializable del baseline."""
    if isinstance(obj, types.ModuleType):
        return {'kind': 'module', 'name': obj.__name__}

    if inspect.isclass(obj):
        # Se recorre el MRO (dir + getattr), no vars(): lo que importa para
        # compatibilidad es lo que hace un call site, y un call site escribe
        # `sc.acq_base(...)` sin saber ni importarle si el método está en la
        # clase o en una base. Con vars() un shim que hereda daría 16 falsos
        # positivos de "método desaparecido" por métodos que sí funcionan.
        metodos = {}
        for mn in sorted(dir(obj)):
            if mn.startswith('_') and mn not in ('__init__', '__enter__', '__exit__'):
                continue
            mv = inspect.getattr_static(obj, mn, None)
            if mv is None:
                continue
            if isinstance(mv, (staticmethod, classmethod)):
                metodos[mn] = {'kind': type(mv).__name__, 'sig': _firma(mv.__func__)}
            elif isinstance(mv, property):
                metodos[mn] = {'kind': 'property'}
            elif callable(mv):
                metodos[mn] = {'kind': 'method', 'sig': _firma(mv)}
        return {'kind': 'class', 'methods': metodos}

    if inspect.isroutine(obj):
        return {'kind': 'function', 'sig': _firma(obj)}

    if _es_const(obj):
        return {'kind': 'const', 'value': _valor_const(obj)}

    if isinstance(obj, (tuple, list)) and all(_es_const(x) for x in obj):
        return {'kind': 'const', 'value': _valor_const(obj)}

    return {'kind': 'other', 'type': type(obj).__name__}


def privados_usados_fuera(nombre_mod):
    """Nombres PRIVADOS del módulo que el resto del árbol referencia igual.

    `from X import *` no exporta nombres con guion bajo, así que un shim que
    sólo haga star-import los pierde en silencio. Y sí hay código que los usa:
    `tests/pile-up/pileup.py` importa `_fwhm_pts` de rigol_dg4162, y tres tests
    más lo llaman como `rg._fwhm_pts`. Eso rompió de verdad durante el refactor
    y el test no lo vio, porque sólo miraba nombres públicos.

    Se resuelve el alias con ast (`import rigol_dg4162 as rg` -> `rg._x`) en vez
    de con grep, que no sabría a qué módulo pertenece cada prefijo.
    """
    encontrados = set()
    for raiz, _, ficheros in os.walk(_SOFT):
        if '__pycache__' in raiz or os.sep + 'API' in raiz:
            continue
        for f in ficheros:
            if not f.endswith('.py'):
                continue
            ruta = os.path.join(raiz, f)
            if os.path.basename(ruta) == nombre_mod + '.py':
                continue                      # el módulo no se cuenta a sí mismo
            try:
                arbol = ast.parse(open(ruta, encoding='utf-8').read())
            except (SyntaxError, UnicodeDecodeError):
                continue

            alias = set()
            for n in ast.walk(arbol):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name == nombre_mod:
                            alias.add(a.asname or a.name)
                elif isinstance(n, ast.ImportFrom) and n.module == nombre_mod:
                    encontrados |= {a.name for a in n.names
                                    if a.name.startswith('_')}
            for n in ast.walk(arbol):
                if (isinstance(n, ast.Attribute)
                        and isinstance(n.value, ast.Name)
                        and n.value.id in alias
                        and n.attr.startswith('_')):
                    encontrados.add(n.attr)
    return sorted(encontrados)


def submodulos(nombre_mod):
    """Submódulos importables como `<mod>.<sub>`, si el módulo es un paquete.

    Un shim de paquete que sólo reexporta en su `__init__` NO hace importable
    `paquete.submodulo`, y hay código que lo importa así: `run_acquire.py` hace
    `from mca.storage import ...`, `tests/tiempo-muerto/run_poisson_loss.py`
    hace `from mca.session import ...`. Eso también rompió durante el refactor.
    """
    mod = sys.modules.get(nombre_mod) or __import__(nombre_mod)
    if not hasattr(mod, '__path__'):
        return []
    d = list(mod.__path__)[0]
    return sorted(f[:-3] for f in os.listdir(d)
                  if f.endswith('.py') and not f.startswith('_'))


def superficie(nombre_mod):
    """Superficie pública del módulo, más los privados que otros sí usan."""
    mod = __import__(nombre_mod)
    nombres = getattr(mod, '__all__', None)
    if nombres is None:
        nombres = [n for n in dir(mod) if not n.startswith('_')]
    nombres = list(nombres) + [n for n in privados_usados_fuera(nombre_mod)
                               if hasattr(mod, n)]
    sup = {n: describir(getattr(mod, n)) for n in sorted(set(nombres))}
    for sub in submodulos(nombre_mod):
        sup[f'{nombre_mod}.{sub}'] = {'kind': 'submodule'}
    return sup


# =============================================================================
# Bloque C: trazas de escritura de registros
# =============================================================================

def _capturar(out, clave, mem, fn, *a, **k):
    """Corre una secuencia y guarda su traza, o el error si reventó.

    Capturar la excepción en vez de dejarla propagar no es cosmético: durante el
    refactor una secuencia a medio migrar tiraría abajo la corrida entera y se
    perderían los otros cientos de chequeos. Además el error ES parte del
    contrato — los drivers verifican por relectura (`set_or_mask` asierta que la
    máscara latcheó), así que "seguía fallando igual" y "seguía andando igual"
    se comprueban con el mismo mecanismo.
    """
    try:
        fn(*a, **k)
        out[f'{clave}.__exc__'] = np.asarray('')
    except Exception as e:
        out[f'{clave}.__exc__'] = np.asarray(f'{type(e).__name__}: {e}')
    out[clave] = mem.trace()


def traza_mca():
    """Secuencias del MCA sobre un FakeMmap, con la traza ordenada de writes."""
    import mca_utils as mu

    out = {}

    def nuevo():
        # 0x30000 = registros + las dos aperturas, igual que MCA_SIZE.
        m = FakeMmap(mu.MCA_SIZE)
        m.poke(mu.R_MAGIC, mu.MAGIC)
        m.poke(mu.R_CAPS, mu.CAP_HIST_H | mu.CAP_HIST_H_PSD)
        m.poke(mu.R_WIDTHS, (8 << 16) | (8 << 8) | 14)   # psd_aw, h2_aw, h_aw
        # fd=-1: nadie va a cerrar este handle en el test.
        return m, mu.MCA(m, -1, mu.CAP_HIST_H | mu.CAP_HIST_H_PSD, 14, 8, 8)

    # configure(): valores DISTINTOS del default en cada campo, para que un
    # offset intercambiado con otro cambie la traza en vez de pasar inadvertido.
    m, dev = nuevo()
    _capturar(out, 'mca_configure', m, dev.configure,
              thr=317, hyst=91, baseline=123, bl_auto=True, bl_k=13,
              bl_holdoff=7, maxlen=777, tail_dly=9, amp_min=11, amp_max=0xABCD,
              amp_src=1, q_shift=5, h_shift=3, h2_shift=6, dec=4, channel=1,
              gate_mode=1, gate_short=48, gate_long=400, verify=True)

    for metodo in ('clear', 'start', 'stop'):
        m, dev = nuevo()
        _capturar(out, f'mca_{metodo}', m, getattr(dev, metodo))

    return out


def traza_scope():
    """Secuencias del scope/multitrigger. Incluye el orden crítico de armado."""
    import multitrigger_utils as mt

    out = {}

    def nuevo():
        m = FakeMmap(mt.SCOPE_SIZE)
        return m, mt.MultiTriggerScope(m, -1)

    m, sc = nuevo()
    _capturar(out, 'scope_acq_base', m, sc.acq_base, thr=0.35, delay=12, decim=64)

    m, sc = nuevo()
    _capturar(out, 'scope_set_or_mask', m, sc.set_or_mask,
              mask_ch0=mt.BIT_ADC_P0, mask_ch1=mt.BIT_ADC_N1)

    m, sc = nuevo()
    _capturar(out, 'scope_shield', m, sc.configure_shield_autorearm,
              channels=0x3, dur=5)

    m, sc = nuevo()
    _capturar(out, 'scope_set_raw_delay', m, sc.set_raw_delay, delay=9)

    m, sc = nuevo()
    _capturar(out, 'scope_disarm', m, sc.disarm)

    # LA traza importante: cruza los registros del osciloscopio (hyst 0x20/0x24,
    # arm 0x00) y los del multitrigger (or_mask 0x240/0x244), y el orden
    # arm-ANTES-de-máscara es load-bearing. Al partir MultiTriggerScope en dos
    # clases esta secuencia es lo primero que se puede reordenar sin querer.
    for etiqueta, kw in (('autorearm', dict(auto_rearm=True)),
                         ('legacy',    dict(auto_rearm=False))):
        m, sc = nuevo()
        _capturar(out, f'scope_arm_{etiqueta}', m, sc.arm_for_adc_trigger,
                  mask_ch0=mt.BIT_ADC_P0, mask_ch1=mt.BIT_ADC_N1,
                  thr=0.25, hyst=0.02, delay=3, we_keep_both=True, **kw)

    return out


# =============================================================================
# Bloque D: equivalencia numérica de los helpers de análisis
# =============================================================================

def _espectro_sintetico(rng, n=16384, centro=8000.0, sigma=60.0, area=200000.0):
    ch = np.arange(n)
    pico = area / (sigma * np.sqrt(2 * np.pi)) * np.exp(-0.5 * ((ch - centro) / sigma) ** 2)
    fondo = 40.0 * np.exp(-ch / 6000.0)
    return rng.poisson(pico + fondo).astype(np.uint32)


def _mapa_sintetico(rng, n_amp=256, n_psd=256):
    """Dos poblaciones separadas en factor de forma: entrada natural de fom()."""
    m = np.zeros((n_amp, n_psd), dtype=np.uint32)
    for centro_psd, n_ev in ((90.0, 40000), (150.0, 30000)):
        a = rng.normal(140.0, 25.0, n_ev)
        p = rng.normal(centro_psd, 12.0, n_ev)
        ok = (a >= 0) & (a < n_amp) & (p >= 0) & (p < n_psd)
        np.add.at(m, (a[ok].astype(int), p[ok].astype(int)), 1)
    return m


def golden_analisis():
    """Corre cada helper puro con entrada fija y devuelve arrays comparables."""
    import mca_utils as mu

    rng = np.random.default_rng(20260903)
    out = {}

    def guardar(clave, valor):
        """Aplana dicts/tuplas a arrays con clave prefijada."""
        if isinstance(valor, dict):
            for k, v in valor.items():
                guardar(f'{clave}.{k}', v)
        elif isinstance(valor, tuple):
            for i, v in enumerate(valor):
                guardar(f'{clave}.{i}', v)
        else:
            arr = np.asarray(valor)
            if arr.dtype == object or arr.dtype.kind in 'SU':
                arr = np.asarray(str(valor))
            out[clave] = arr

    def correr(clave, fn, *a, **k):
        """Congela también las excepciones: que siga fallando igual es parte
        del contrato de compatibilidad."""
        try:
            guardar(clave, fn(*a, **k))
            out[f'{clave}.__exc__'] = np.asarray('')
        except Exception as e:
            out[f'{clave}.__exc__'] = np.asarray(f'{type(e).__name__}: {e}')

    spec = _espectro_sintetico(rng)
    out['_in.spec'] = spec
    correr('gauss_fit_peak', mu.gauss_fit_peak, spec, 7700, 8300)
    correr('gauss_fit_peak_full', mu.gauss_fit_peak, spec)
    correr('gauss_fit_peak_vacio', mu.gauss_fit_peak, spec, 100, 200)

    # Espectro plano de pulser deslizante: la entrada que espera dnl().
    plano = rng.poisson(500.0, 16384).astype(np.uint32)
    out['_in.plano'] = plano
    correr('dnl', mu.dnl, plano, 1000, 15000, smooth=64)
    correr('dnl_laxo', mu.dnl, plano, 1000, 15000, smooth=32, strict=False)

    energias  = np.array([59.5, 122.1, 356.0, 662.0, 1173.2, 1332.5])
    centroides = 12.05 * energias + 31.0 + np.array([0.0, 1.5, -2.0, 0.8, -1.1, 0.4])
    out['_in.energias'] = energias
    out['_in.centroides'] = centroides
    correr('energy_calibration', mu.energy_calibration, centroides, energias)

    mapa = _mapa_sintetico(rng)
    out['_in.mapa_suma'] = np.asarray(mapa.sum())
    correr('fom', mu.fom, mapa)
    correr('fom_rango', mu.fom, mapa, 100, 200)

    r_in  = np.array([1e2, 1e3, 5e3, 1e4, 5e4, 1e5, 2e5])
    r_out = r_in * np.exp(-r_in * 2e-6)
    correr('deadtime_fit', mu.deadtime_fit, r_in, r_out)

    bins = np.arange(0, 16384, 512)
    correr('counts_to_volts_pico', mu.counts_to_volts, bins, h_shift=3, amp_src=0)
    correr('counts_to_volts_carga', mu.counts_to_volts, bins, h_shift=0,
           amp_src=1, q_shift=5)

    # Eje con no-linealidad suave y monótona: axis_calibration debe invertirlo.
    ref = np.linspace(500.0, 15500.0, 24)
    medidos = ref + 90.0 * np.sin(2 * np.pi * ref / 16384.0) + 25.0
    out['_in.ref'] = ref
    out['_in.medidos'] = medidos
    correr('axis_calibration', mu.axis_calibration, ref, medidos)

    try:
        cal = mu.axis_calibration(ref, medidos)
        correr('apply_calibration', mu.apply_calibration, bins, cal)
        correr('linearize_spectrum', mu.linearize_spectrum, spec, cal)
        correr('inl_residual_vs_knots', mu.inl_residual_vs_knots, cal,
               n_knots=(8, 16, 32, 64))
    except Exception as e:
        out['axis_calibration.__setup_exc__'] = np.asarray(f'{type(e).__name__}: {e}')

    return out


# =============================================================================
# Orquestación
# =============================================================================

def construir():
    usando_stub = stub_rp()

    baseline = {
        'nota': ('superficie PRE-refactor; la compara tests/test_compat_api.py. '
                 'Regenerar sólo si el cambio de API es deliberado.'),
        'python': '%d.%d' % sys.version_info[:2],
        'numpy': np.__version__,
        'rp_stub': usando_stub,
        'modulos': {m: superficie(m) for m in MODULOS},
    }

    golden = {}
    golden.update({f'traza.{k}': v for k, v in traza_mca().items()})
    golden.update({f'traza.{k}': v for k, v in traza_scope().items()})
    golden.update({f'analisis.{k}': v for k, v in golden_analisis().items()})
    return baseline, golden


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--check', action='store_true',
                    help='regenerar y comparar contra lo ya guardado, sin escribir')
    args = ap.parse_args(argv)

    baseline, golden = construir()

    n_const = sum(1 for m in baseline['modulos'].values()
                  for d in m.values() if d['kind'] == 'const')
    n_fn = sum(1 for m in baseline['modulos'].values()
               for d in m.values() if d['kind'] in ('function', 'class'))
    trazas = [k for k in golden if k.startswith('traza.') and not k.endswith('.__exc__')]
    n_writes = sum(len(golden[k]) // 2 for k in trazas)

    if args.check:
        with open(BASELINE_JSON) as f:
            viejo = json.load(f)
        igual = viejo['modulos'] == baseline['modulos']
        print(f'superficie: {"IGUAL" if igual else "CAMBIÓ"}')
        return 0 if igual else 1

    with open(BASELINE_JSON, 'w') as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False, sort_keys=True)
    np.savez_compressed(GOLDEN_NPZ, **golden)

    print(f'{BASELINE_JSON}')
    print(f'  {len(baseline["modulos"])} módulos, {n_fn} funciones/clases, '
          f'{n_const} constantes')
    print(f'{GOLDEN_NPZ}')
    print(f'  {len(trazas)} trazas ({n_writes} escrituras de registro), '
          f'{len([k for k in golden if k.startswith("analisis.")])} claves de análisis')
    if baseline['rp_stub']:
        print('  (rp stubbeado: corriendo en la PC, sin placa)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
