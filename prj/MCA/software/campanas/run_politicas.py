"""Validación EN PLACA de las fases 1 y 2: el teselado, y qué compra cada política.

Las fases 1 y 2 se verificaron en simulación con assertions (17 propiedades,
`modulos/mca/sim/VERIFICACION.md`). Esto es lo que la simulación no puede dar:

  1. que las identidades valgan en el SILICIO, leídas por el bus de verdad;
  2. qué valen las dos palancas con pulsos reales, no con estímulo sintetizado;
  3. el número que los propios documentos tienen en disputa: tau.

Qué se mide y por qué, en orden de valor
----------------------------------------

**`invariantes`** — las dos identidades del teselado, leídas por AXI con el MCA
parado. Es la contraparte en placa de `ap_teselado` y `ap_atribucion_arribos`.
Hay que parar antes de leer: la identidad vale ciclo a ciclo en el hardware,
pero cada acceso al bus se lleva ~6 ciclos y los contadores avanzan entre uno y
otro (`MCA.counters` lo documenta). Con `run=1` la suma NO cierra, y eso no es
un bug.

**`barrido`** — el síntoma que motivó toda la fase 1: `deadtime_cnt` no es
monótono en la tasa. Baja cuando la tasa sube, porque a tasa alta casi no se
abren ventanas y lo que cuenta son ventanas. Un tiempo muerto informado que baja
cuando la tasa sube no corrige nada. `deadtime_real_s = t_win + t_div + t_rearm`
tiene que ser monótono. Las dos curvas salen de la MISMA corrida, así que la
comparación no depende de que el estímulo se repita.

OJO CON LA COMPARACIÓN CONTRA LA TABLA DE `figuras_trigger.py`
(`docs/mca/figuras/tiempo_muerto/README.md`: 11.0 / 25.6 / 52.2 / 85.7 % de
bloqueo real a 20 / 50 / 126 / 318 kcps). Esa tabla sale de correr la FSM del
RTL sobre señal sintetizada con cola de 5.9 us sobre `thr_lo`. El Rigol entrega
pulsos de ~2 us de FWHM: la cola es otra, así que **tau es otra y los
porcentajes no tienen por qué coincidir**. Lo que sí se contrasta es la forma —
`deadtime_real` monótono, `deadtime_cnt` no — y el valor de tau medido contra
el que predice la configuración. Decir que esto "reproduce la tabla" sería
comparar dos estímulos distintos.

**`politicas`** — las cuatro combinaciones de `rearm_mode` x `pub_mode` sobre el
MISMO estímulo, que es la única forma de comparar políticas sin que el
generador se meta en el resultado. Es el mismo truco que `cfg_amp_src` usa para
comparar pico contra integral en un solo bitstream.

Con `gate_mode=1` a proposito. Con compuerta por nivel (`gate_mode=0`) la
ventana se queda abierta hasta que la señal baja de `thr_lo`, así que la cola
cae dentro de `t_win` y `t_rearm` sale ~0: la palanca del re-armado no tendría
nada que mostrar. El término que la fase 1 descubrió vive justamente en la
configuración de la campaña: compuerta fija más corta que la cola.

**`rearm_dly`** — el compromiso que el RTL advierte y que hay que medir, no
suponer: el re-armado por contador baja el tiempo muerto pero SOBRE-CUENTA,
porque trocea un apilamiento en pedazos del largo de la compuerta y registra
cada pedazo como evento. `rearm_dly` chico = más eventos y más falsos; grande =
se parece al nivel pero determinista. Se barre para ver dónde está el codo.

**`distribucion`** — lo que los escalares del período muerto compran:

  (a) `dead_ext / dead_periods` estima `P(L > tau) = 1 - e^-rho`, o sea la
      FRACCIÓN APILADA, que es lo que `cnt_pileup` no logra medir (marca
      0.00-0.45 % donde el 40-47 % de los eventos tiene más de un pulso).
  (b) `E[L] / tau` contra `(e^rho - 1)/rho` separa paralizable de no
      paralizable SIN barrido: con `rearm_mode=0` tiene que crecer con rho, con
      `rearm_mode=1` tiene que quedarse en 1. Hoy eso exige un barrido Poisson
      con fuente de actividad variable, que es el ensayo caro.

Uso:
    python3 campanas/run_politicas.py <outdir> [--solo invariantes,barrido,...]
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/
sys.path.insert(0, _RAIZ)
# `testbench_mca` vive acá al lado. Corriendo el script directo Python ya pone
# su directorio en el path, pero importándolo como módulo (un test, otra
# campaña) no, y el fallo aparece recién al importar.
sys.path.insert(0, _AQUI)

import testbench_mca as tb                                  # noqa: E402
import rigol_dg4162 as rg                                   # noqa: E402
from API import mca as mca_mod                              # noqa: E402

FS_HZ = mca_mod.FS_HZ

# La configuración de la campaña, y la única en que la fase 1 tiene algo que
# mostrar: compuerta FIJA de 384 muestras (3.07 us), más corta que la cola.
CFG = dict(tb.DEFAULT_CFG, gate_mode=1, gate_short=32, gate_long=384)

# Las cuatro tasas de la tabla de figuras_trigger.py. Se usan las mismas no
# para comparar porcentajes (ver el encabezado) sino para que las dos
# mediciones queden en la misma grilla y se puedan poner una al lado de la otra.
TASAS = (20e3, 50e3, 126e3, 318e3)


# --------------------------------------------------------------------------
# lectura cruda: la identidad se verifica en CICLOS, no en segundos
# --------------------------------------------------------------------------
def ciclos(mca):
    """Los cinco relojes del teselado en ciclos de adc_clk, crudos del bus.

    `counters()` los devuelve en segundos, que es lo útil para medir pero no
    para probar una identidad: dividir por 125e6 y volver a multiplicar mete
    redondeo donde se busca igualdad exacta.
    """
    r = mca._r64
    return {
        'realtime': r(mca_mod.R_REALTIME_LO, mca_mod.R_REALTIME_HI),
        'livetime': r(mca_mod.R_LIVETIME_LO, mca_mod.R_LIVETIME_HI),
        'deadtime': r(mca_mod.R_DEADTIME_LO, mca_mod.R_DEADTIME_HI),
        'vetotime': r(mca_mod.R_VETOTIME_LO, mca_mod.R_VETOTIME_HI),
        't_win':    r(mca_mod.R_T_WIN_LO,    mca_mod.R_T_WIN_HI),
        't_div':    r(mca_mod.R_T_DIV_LO,    mca_mod.R_T_DIV_HI),
        't_rearm':  r(mca_mod.R_T_REARM_LO,  mca_mod.R_T_REARM_HI),
        't_clear':  r(mca_mod.R_T_CLEAR_LO,  mca_mod.R_T_CLEAR_HI),
    }


def _chequeo(nombre, ok, detalle):
    print(f"  {'OK  ' if ok else 'FALLA'} {nombre}: {detalle}")
    return {'nombre': nombre, 'ok': bool(ok), 'detalle': detalle}


def estimulo(gen, rate_hz, ch=1, amp_vpp=0.5, n_events=64, seed=0,
             settle_s=0.3):
    """Carga un tren Poisson Y ENCIENDE LA SALIDA. Una sola puerta de entrada.

    `rg.apply_poisson_train` sube la forma y la aplica pero **no enciende la
    salida**: eso lo hace el llamador (`sweep_rate_poisson` lo hace aparte, con
    un `gen.output(ch, True)` suelto). Y `tb.connect()` arranca con un
    `gen.reset()`, que deja las dos salidas en OFF. Sin este envoltorio la
    campaña corre entera contra una entrada muerta: los contadores dan todos
    cero, las identidades CIERRAN (0 == 0) y el resultado parece bueno.
    Costó una corrida descubrirlo; de ahí que haya una sola función que
    enciende, y que `invariantes` exija que el estímulo haya llegado.
    """
    n_ev = tb._n_events_factible(rate_hz, tb.PULSE_WIDTH_S, n_events)
    if n_ev < 4:
        return None, n_ev
    info = rg.apply_poisson_train(gen, rate_hz=rate_hz,
                                  width_s=tb.PULSE_WIDTH_S, ch=ch,
                                  amp_vpp=amp_vpp, n_events=n_ev, seed=seed)
    gen.output(ch, True)
    time.sleep(settle_s)
    return info, n_ev


def invariantes(mca, gen, rate_hz=50e3, seconds=3.0, **cfg):
    """Las identidades del teselado y de la atribución, leídas por el bus.

    Con un estímulo que ejercite TODOS los casilleros: a 50 kcps con compuerta
    fija hay ventanas, publicación, bloqueo por re-armado y cruces perdidos en
    cada una de esas condiciones. Un estímulo manso dejaría casilleros en cero y
    la identidad cerraría por vacío.
    """
    print('\n=== invariantes del teselado, leídas por AXI ===')
    c = {**CFG, **cfg}
    mca.configure(**c)
    estimulo(gen, rate_hz)
    _, _, cnt = mca.acquire(seconds)          # acquire() para ANTES de leer
    cy = ciclos(mca)
    pub_k = cnt.get('pub_k', 0)

    suma = (cy['vetotime'] + cy['t_win'] + cy['t_div'] + cy['t_rearm']
            + cy['livetime'])
    chequeos = [
        # ESTE CHEQUEO VA PRIMERO Y NO ES CEREMONIA. Las cinco identidades de
        # abajo son todas de la forma `a == b + c`, y con la entrada muerta
        # cierran las cinco con 0 == 0: la corrida informa SEIS OK y no probó
        # nada. Pasó de verdad -- la primera corrida en placa dio todo OK con
        # `cross = 0`, porque el generador tenía la salida apagada. Un teselado
        # sólo queda probado si los casilleros tuvieron algo que repartir.
        _chequeo('el estímulo llegó: hubo cruces, ventanas y bloqueo',
                 cnt['cross'] > 0 and cnt['windows'] > 0 and cy['t_win'] > 0
                 and cy['t_rearm'] > 0,
                 f"cruces {cnt['cross']}, ventanas {cnt['windows']}, "
                 f"t_win {cy['t_win']} ciclos, t_rearm {cy['t_rearm']} ciclos"
                 + ('' if cnt['cross'] else
                    '  <-- SIN CRUCES: revisá que la salida del generador esté '
                    'encendida y el cable en IN1. Las identidades de abajo '
                    'cierran por vacío y no significan nada.')),
        _chequeo('teselado  realtime == veto+win+div+rearm+live',
                 suma == cy['realtime'],
                 f"realtime {cy['realtime']} vs suma {suma} "
                 f"(diferencia {cy['realtime'] - suma})"),
        # Seis casilleros: el sexto (`lost_notrig`) es el que el plan de la
        # fase 2 no había previsto. Un cruce puede encontrar el módulo LIBRE y
        # no abrir, si la apertura la manda el trigger externo.
        _chequeo('atribución  cross == open+rearm+active+busy+veto+notrig',
                 (cnt['open'] + cnt['lost_rearm'] + cnt['lost_active']
                  + cnt['dropped'] + cnt['lost_veto']
                  + cnt['lost_notrig']) == cnt['cross'],
                 f"cross {cnt['cross']} vs suma "
                 f"{cnt['open'] + cnt['lost_rearm'] + cnt['lost_active'] + cnt['dropped'] + cnt['lost_veto'] + cnt['lost_notrig']}"),
        # `windows` cuenta ventanas abiertas, `open` cruces que abrieron. Con
        # Schmitt interno y re-armado por nivel son lo mismo; la desigualdad es
        # lo que vale en general.
        _chequeo('windows >= open', cnt['windows'] >= cnt['open'],
                 f"windows {cnt['windows']}, open {cnt['open']}"),
        # El registro histórico 0x078 queda BIT-IDÉNTICO al de antes: vale
        # win+div y nada más. Es deliberado, hay campañas guardadas que lo usan.
        _chequeo('compat  deadtime == t_win + t_div (pub_mode=0)',
                 cy['deadtime'] == cy['t_win'] + cy['t_div'],
                 f"deadtime {cy['deadtime']} vs win+div "
                 f"{cy['t_win'] + cy['t_div']}"),
        # Un período muerto dura al menos un ciclo, así que no puede haber más
        # períodos que ciclos muertos.
        _chequeo('períodos  t_muerto >= dead_periods',
                 (cy['t_win'] + cy['t_div'] + cy['t_rearm'])
                 >= cnt['dead_periods'],
                 f"muerto {cy['t_win'] + cy['t_div'] + cy['t_rearm']} ciclos, "
                 f"{cnt['dead_periods']} períodos"),
        _chequeo('FIFO  pub_occ_max <= pub_k',
                 cnt['pub_occ_max'] <= max(pub_k, 1),
                 f"marca de agua {cnt['pub_occ_max']} de {pub_k} lugares"),
    ]
    print(f"\n  reparto: win {100*cnt['t_win_s']/max(cnt['realtime_s'],1e-9):.1f}% "
          f"div {100*cnt['t_div_s']/max(cnt['realtime_s'],1e-9):.2f}% "
          f"rearm {100*cnt['t_rearm_s']/max(cnt['realtime_s'],1e-9):.1f}% "
          f"live {100*cnt['livetime_s']/max(cnt['realtime_s'],1e-9):.1f}%")
    return {'chequeos': chequeos, 'ciclos': cy,
            'counters': {k: float(v) for k, v in cnt.items()},
            'rate_hz': rate_hz, 'seconds': seconds,
            'todas_ok': all(ch['ok'] for ch in chequeos)}


def barrido(mca, gen, tasas=TASAS, seconds=3.0, **cfg):
    """`deadtime_real` monótono en la tasa; `deadtime_cnt` no. Misma corrida."""
    print('\n=== barrido de tasa: el contador honesto contra el viejo ===')
    c = {**CFG, **cfg}
    filas = []
    for r in tasas:
        mca.configure(**c)
        info, n_ev = estimulo(gen, r)
        if info is None:
            print(f'  {r/1e3:6.0f} kcps: SALTEADO (entran {n_ev} eventos/ciclo '
                  f'en el ARB)')
            continue
        _, _, cnt = mca.acquire(seconds)
        rt = max(cnt['realtime_s'], 1e-12)
        f = {
            'rate_hz': float(r),
            'viejo_frac': cnt['deadtime_s'] / rt,
            'real_frac': cnt['deadtime_real_s'] / rt,
            'rearm_frac': cnt['t_rearm_s'] / rt,
            # tau por ventana: el tiempo muerto honesto dividido por las
            # ventanas que lo generaron. Es tau MEDIDO, sin suponer el modelo.
            'tau_us': (1e6 * cnt['deadtime_real_s'] / cnt['windows']
                       if cnt['windows'] else float('nan')),
            'windows': int(cnt['windows']),
            'total': int(cnt['total']),
            'cross': int(cnt['cross']),
            'counters': {k: float(v) for k, v in cnt.items()},
        }
        filas.append(f)
        print(f"  {r/1e3:6.0f} kcps:  viejo {100*f['viejo_frac']:5.1f}%   "
              f"real {100*f['real_frac']:5.1f}%   "
              f"(rearm {100*f['rearm_frac']:5.1f}%)   "
              f"tau {f['tau_us']:5.2f} us   ventanas {f['windows']}")

    if len(filas) >= 2:
        reales = [f['real_frac'] for f in filas]
        viejos = [f['viejo_frac'] for f in filas]
        mono_real = all(b >= a - 1e-9 for a, b in zip(reales, reales[1:]))
        mono_viejo = all(b >= a - 1e-9 for a, b in zip(viejos, viejos[1:]))
        print(f"\n  deadtime_real monótono: {'SÍ' if mono_real else 'NO'}  "
              f"(es lo que la fase 1 tenía que arreglar)")
        print(f"  deadtime_cnt  monótono: {'SÍ' if mono_viejo else 'NO'}  "
              f"(el síntoma del bug; si sale SÍ es que el estímulo no llegó "
              f"a la zona donde se cae)")
    else:
        mono_real = mono_viejo = None
    return {'filas': filas, 'mono_real': mono_real, 'mono_viejo': mono_viejo}


def politicas(mca, gen, rate_hz=126e3, seconds=3.0, rearm_dly=16, **cfg):
    """Las cuatro combinaciones rearm_mode x pub_mode sobre el MISMO estímulo.

    El estímulo se carga UNA vez y no se vuelve a tocar: lo único que cambia
    entre los cuatro puntos son dos bits de registro. Recargar el ARB entre
    medición y medición metería una realización distinta de Poisson en la
    comparación, y la diferencia entre políticas es del orden de la varianza
    entre realizaciones.
    """
    print('\n=== las cuatro políticas, mismo estímulo ===')
    c = {**CFG, **cfg}
    estimulo(gen, rate_hz)

    filas = []
    for rm in (0, 1):
        for pm in (0, 1):
            mca.configure(**c, rearm_mode=rm, pub_mode=pm,
                          rearm_dly=(rearm_dly if rm else 0))
            _, _, cnt = mca.acquire(seconds)
            rt = max(cnt['realtime_s'], 1e-12)
            f = {
                'rearm_mode': rm, 'pub_mode': pm,
                'windows': int(cnt['windows']),
                'total': int(cnt['total']),
                'tasa_ventanas': cnt['windows'] / rt,
                'real_frac': cnt['deadtime_real_s'] / rt,
                'rearm_frac': cnt['t_rearm_s'] / rt,
                'div_frac': cnt['t_div_s'] / rt,
                'tau_us': (1e6 * cnt['deadtime_real_s'] / cnt['windows']
                           if cnt['windows'] else float('nan')),
                'pub_occ_max': int(cnt['pub_occ_max']),
                'pub_saturada': bool(cnt['pub_saturada']),
                'counters': {k: float(v) for k, v in cnt.items()},
            }
            filas.append(f)
            print(f"  rearm={'cont' if rm else 'niv '} pub={'FIFO' if pm else 'bloq'}:  "
                  f"ventanas {f['windows']:7d}  "
                  f"({f['tasa_ventanas']/1e3:6.1f} k/s)  "
                  f"muerto {100*f['real_frac']:5.1f}%  "
                  f"rearm {100*f['rearm_frac']:5.1f}%  "
                  f"div {100*f['div_frac']:5.2f}%  "
                  f"tau {f['tau_us']:5.2f} us  "
                  f"agua {f['pub_occ_max']}")

    base = filas[0]
    for f in filas[1:]:
        if base['windows']:
            f['ganancia'] = f['windows'] / base['windows']
    print('\n  ganancia de ventanas contra nivel+bloqueante:')
    for f in filas[1:]:
        print(f"    rearm={'cont' if f['rearm_mode'] else 'niv '} "
              f"pub={'FIFO' if f['pub_mode'] else 'bloq'}: "
              f"x{f.get('ganancia', float('nan')):.2f}")
    return {'filas': filas, 'rate_hz': float(rate_hz),
            'rearm_dly': int(rearm_dly)}


def barrer_rearm_dly(mca, gen, rate_hz=126e3, dlys=(16, 64, 128, 384, 738),
                     seconds=3.0, **cfg):
    """El compromiso del re-armado por contador: rendimiento contra sobre-conteo.

    El RTL advierte que el contador SOBRE-CUENTA: trocea un apilamiento en
    pedazos del largo de la compuerta y registra cada pedazo como evento. Acá se
    ve dónde está el codo. El indicador de sobre-conteo es `windows/cross`: con
    re-armado por nivel cada cruce abre a lo sumo una ventana, así que
    `windows/cross <= 1`. Con contador, un solo cruce puede abrir varias y la
    razón se va arriba de 1 -- eventos que el equipo informa y no existieron
    como pulsos separados.
    """
    print('\n=== rearm_dly: rendimiento contra sobre-conteo ===')
    c = {**CFG, **cfg}
    estimulo(gen, rate_hz)

    filas = []
    for d in (0,) + tuple(dlys):              # 0 = la referencia por NIVEL
        mca.configure(**c, rearm_mode=(1 if d else 0),
                      rearm_dly=(d if d else 0))
        _, _, cnt = mca.acquire(seconds)
        rt = max(cnt['realtime_s'], 1e-12)
        f = {
            'rearm_dly': int(d),
            'rearm_dly_us': 1e6 * d / FS_HZ,
            'modo': 'contador' if d else 'nivel',
            'windows': int(cnt['windows']),
            'cross': int(cnt['cross']),
            'sobreconteo': (cnt['windows'] / cnt['cross']
                            if cnt['cross'] else float('nan')),
            'real_frac': cnt['deadtime_real_s'] / rt,
            'tau_us': (1e6 * cnt['deadtime_real_s'] / cnt['windows']
                       if cnt['windows'] else float('nan')),
            'pileup': int(cnt['pileup']),
            'counters': {k: float(v) for k, v in cnt.items()},
        }
        filas.append(f)
        print(f"  {f['modo']:8s} dly {f['rearm_dly_us']:5.2f} us:  "
              f"ventanas {f['windows']:7d}  cruces {f['cross']:7d}  "
              f"ventanas/cruce {f['sobreconteo']:5.2f}  "
              f"muerto {100*f['real_frac']:5.1f}%  tau {f['tau_us']:5.2f} us")
    return {'filas': filas, 'rate_hz': float(rate_hz)}


def distribucion(mca, gen, tasas=TASAS, seconds=3.0, **cfg):
    """E[L] y el estimador de apilamiento, en los dos modos de re-armado.

    Lo que se pone a prueba es la discriminación de la figura 2e SIN barrido de
    actividad: paralizable tiene átomo en tau más cola continua, así que
    `E[L]/tau` crece con rho como `(e^rho - 1)/rho`; no paralizable tiene
    `L = delta(tau)` y la razón se queda en 1. `tau` se toma del punto de tasa
    más baja, donde rho -> 0 y `E[L] -> tau` por construcción.
    """
    print('\n=== distribución del período muerto ===')
    c = {**CFG, **cfg}
    out = {}
    for rm, dly in ((0, 0), (1, 16)):
        filas = []
        print(f"  --- re-armado por {'contador' if rm else 'nivel'} ---")
        for r in tasas:
            mca.configure(**c, rearm_mode=rm, rearm_dly=dly)
            info, _ = estimulo(gen, r)
            if info is None:
                continue
            _, _, cnt = mca.acquire(seconds)
            filas.append({
                'rate_hz': float(r),
                'E_L_us': 1e6 * cnt['dead_len_mean_s'],
                'L_max_us': 1e6 * cnt['dead_len_max_s'],
                'dead_periods': int(cnt['dead_periods']),
                'dead_ext_frac': cnt['dead_ext_frac'],
                'pileup_frac': cnt['pileup'] / max(cnt['total'], 1),
                'counters': {k: float(v) for k, v in cnt.items()},
            })
        if not filas:
            continue
        # tau del punto de tasa mas baja (rho -> 0): E[L] -> tau.
        tau_us = filas[0]['E_L_us']
        for f in filas:
            f['tau_us'] = tau_us
            f['rho'] = f['rate_hz'] * tau_us * 1e-6
            f['E_L_sobre_tau'] = f['E_L_us'] / tau_us if tau_us else float('nan')
            # paralizable: E[L]/tau = (e^rho - 1)/rho.  no paralizable: 1.
            rho = f['rho']
            f['modelo_paralizable'] = ((math.exp(rho) - 1) / rho
                                       if rho > 1e-9 else 1.0)
            f['apilada_esperada'] = 1 - math.exp(-rho)
            print(f"    {f['rate_hz']/1e3:6.0f} kcps:  rho {rho:5.2f}  "
                  f"E[L] {f['E_L_us']:6.2f} us  E[L]/tau {f['E_L_sobre_tau']:5.2f} "
                  f"(paralizable predice {f['modelo_paralizable']:5.2f})  "
                  f"apilada medida {100*f['dead_ext_frac']:5.1f}% "
                  f"(esperada {100*f['apilada_esperada']:5.1f}%, "
                  f"cnt_pileup dice {100*f['pileup_frac']:5.2f}%)")
        out['contador' if rm else 'nivel'] = filas
    return out


SECCIONES = {
    'invariantes': invariantes,
    'barrido': barrido,
    'politicas': politicas,
    'rearm_dly': barrer_rearm_dly,
    'distribucion': distribucion,
}


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('outdir')
    p.add_argument('--solo', default=None,
                   help='secciones separadas por coma: '
                        + ','.join(SECCIONES))
    p.add_argument('--seconds', type=float, default=3.0)
    a = p.parse_args(argv)
    os.makedirs(a.outdir, exist_ok=True)

    quiero = (list(SECCIONES) if not a.solo
              else [s.strip() for s in a.solo.split(',')])
    for s in quiero:
        if s not in SECCIONES:
            p.error(f'sección desconocida: {s}. Hay: {", ".join(SECCIONES)}')

    mca, gen, info = tb.connect()
    res = {'info': {k: (list(v) if isinstance(v, tuple) else v)
                    for k, v in info.items()}}
    # Un bitstream sin los registros de la fase 1/2 devuelve 0 en todos (las
    # direcciones no mapeadas se ignoran en silencio), así que la campaña
    # entera saldría plausible y vacía. Hay que cortar acá.
    mca.exigir_features()
    res['pub_k'] = int(mca.counters().get('pub_k', 0))
    print(f"  FIFO de publicación: {res['pub_k']} lugares")
    try:
        for s in quiero:
            res[s] = SECCIONES[s](mca, gen, seconds=a.seconds)
    finally:
        try:
            gen.output(1, False)
        except Exception:
            pass
        mca.stop()
        path = os.path.join(a.outdir, 'politicas.json')
        with open(path, 'w') as fh:
            json.dump(res, fh, indent=1, default=float)
        print(f'\nguardado en {path}')

    inv = res.get('invariantes')
    if inv and not inv['todas_ok']:
        print('\nHAY INVARIANTES QUE NO CIERRAN — ver arriba')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
