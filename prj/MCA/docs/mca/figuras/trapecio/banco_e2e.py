#!/usr/bin/env python3
"""El disparo con polo-cero y el banco de trapecios del RTL, de punta a punta,
contra el modelo de pruebas_banco.py, sobre el MISMO tren de Poisson.

Arma el estimulo con pruebas_banco.tren() (la misma semilla y el mismo largo que
la tabla del tren de pruebas_banco: 300 kcps con 4 M muestras y 1 Mcps con 2 M,
ruido blanco de 4.57 cuentas), corre tb_banco_e2e.sv en Questa (mt_top con el
polo-cero en la mascara y mca_top con el banco 64/48, 32/24, 16/12 y 8/8, las
ventanas y los umbrales de banco_pruebas.json) y verifica, sobre el volcado:

  1. el disparo: los flancos de trig_i son los de DisparoPZ, muestra por
     muestra, a menos de un corrimiento fijo;
  2. las marcas: F_DTPREV y F_DTNEXT de cada evento son las distancias de su
     disparo al anterior y al siguiente dentro de la compuerta;
  3. la eleccion: F_FORMA es la primera forma con antes <= F_DTPREV y
     despues <= F_DTNEXT, o 0xFFFF si ninguna;
  4. la medicion: F_TRAP es, BIT A BIT, el promedio de la salida entera del
     trapecio elegido sobre su ventana (estimadores en int64, como mca_trap);
     de ahi sale tambien donde abre la ventana respecto del disparo, que es lo
     que fija el off de cada forma (c del modelo + PRE + LAT_TOP);
  5. el resultado: con las decisiones del RTL (que disparos abren ranura, que
     forma elige cada una y donde cae su ventana) se clasifica cada pulso con
     el criterio del modelo (bueno = error < 1 % sobre la senal sin ruido), y
     se compara contra clasificar() del modelo.

    python3 banco_e2e.py [--dir /ruta/de/trabajo] [--tasas 300 1000]

Los archivos del estimulo y del volcado (~25 MB) van a --dir (por defecto un
directorio temporal); el resumen queda en banco_e2e.json, al lado de este
archivo.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import pruebas_banco as pb                      # noqa: E402
from recuperacion_modelo import MQ              # noqa: E402

MCA = os.path.abspath(os.path.join(AQUI, '..', '..', '..', '..'))
REPO = os.path.abspath(os.path.join(MCA, '..', '..'))
FUENTES = (
    [os.path.join(MCA, 'modulos', 'comun', 'rtl', 'mca_trap.sv')]
    + [os.path.join(REPO, 'rtl', 'classic', f) for f in ('rp_adc_trig.v', 'rp_ext_trig.v')]
    + [os.path.join(MCA, 'modulos', 'mt', 'rtl', f) for f in (
        'mt_trig_src.sv', 'mt_slope_trig.sv', 'mt_pz_trig.sv', 'trigger_shield.sv',
        'mt_event_logic.v', 'mt_cfg.sv', 'mt_top.sv')]
    + [os.path.join(MCA, 'modulos', 'mca', 'rtl', f) for f in (
        'mca_div_restore.sv', 'mca_hist.sv', 'mca_zoom.sv', 'mca_discriminator.sv',
        'mca_delay.sv', 'mca_baseline.sv', 'mca_slot.sv', 'mca_window.sv', 'mca_publish.sv',
        'mca_pulse_feature.sv', 'mca_top.sv')]
    + [os.path.join(AQUI, 'tb_banco_e2e.sv')])

PRE = 16          # cfg_pre_dly: el de la placa; con el polo-cero alcanza (latencia <= 14)
LAT_TOP = 2       # el registro de entrada y la salida de la linea de retardo
GATE, GS, N_ACC = 112, 32, 4   # la compuerta tiene que cubrir off + 8 + w de la forma 0
PZ = dict(k=2, m=1, mq=MQ, sh=10, thr=353, hyst=177)
MARCADO = 0xFFFF


def configuracion():
    res = json.load(open(os.path.join(AQUI, 'banco_pruebas.json')))
    b = res['bancos']['pz'][pb.ELEGIDO['pz']]
    banco = pb.BANCOS[pb.ELEGIDO['pz']]
    return banco, b['c'], [tuple(u) for u in b['umbral_real']]


def estimulo(tasa):
    """El tren de la tabla de pruebas_banco.main(), con la misma semilla. La
    muestra que entra al RTL se satura a 14 bits, como el ADC."""
    r2 = np.random.default_rng(23)
    n = int(4e6 if tasa < 1000 else 2e6)
    pies, a, xl = pb.tren(tasa, n, r2)
    x = np.round(xl + r2.normal(0, 4.57, n))
    sat = int(((x > 8191) | (x < -8192)).sum())
    return pies, a, xl, np.clip(x, -8192, 8191).astype(np.int64), sat


def escribir(ruta, x, banco, cs, umbr, k_off):
    with open(ruta, 'w') as fh:
        fh.write(f"CFG {N_ACC} {GS} {GATE} {PRE} {MQ} {len(banco)} {PZ['k']} {PZ['m']} {PZ['mq']} "
                 f"{PZ['sh']} {PZ['thr']} {PZ['hyst']} {len(x)}\n")
        for f, c, (an, de) in zip(banco, cs, umbr):
            fh.write(f"F {f.k} {f.m} {c + k_off} {f.lw} {f.sh} {an} {de}\n")
        np.savetxt(fh, x, fmt='%d')


def compilar(d):
    lib = os.path.join(d, 'work')
    if not os.path.isdir(lib):
        subprocess.run(['vlib', lib], check=True, capture_output=True)
    r = subprocess.run(['vlog', '-sv', '-quiet', '-work', lib] + FUENTES, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(r.stdout + r.stderr)
    return lib


def simular(lib, estim, volcado):
    r = subprocess.run(['vsim', '-c', '-work', lib, 'tb_banco_e2e', f'+ESTIM={estim}',
                        f'+VOLCADO={volcado}', '-do', 'run -all; quit -f'],
                       capture_output=True, text=True)
    if 'RESULT: PASS' not in r.stdout:
        sys.exit(r.stdout[-3000:] + r.stderr)
    print('   ', [l for l in r.stdout.splitlines() if 'tb_banco_e2e:' in l][0].strip('# '))


def leer(volcado):
    T, A, E = [], [], []
    for l in open(volcado):
        p = l.split()
        if p[0] == 'T':
            T.append(int(p[1]))
        elif p[0] == 'A':
            A.append(int(p[1]))
        elif p[0] == 'E':
            E.append([int(v) for v in p[1:]])
    return np.array(T), np.array(A), np.array(E)


def trap_int(x, f, mq=MQ):
    """mca_trap en enteros: d, p, s exactos en int64, s >> sh saturado a 18 bits."""
    def ret(v, j):
        o = np.zeros_like(v)
        o[j:] = v[:len(v) - j]
        return o
    d = x - ret(x, f.k) - ret(x, f.l) + ret(x, f.k + f.l)
    p = np.cumsum(d)
    s = np.cumsum(16 * p + mq * d)
    return np.clip(s >> f.sh, -(1 << 17), (1 << 17) - 1)


def eleccion(dtp, dtn, umbr):
    for i, (an, de) in enumerate(umbr):
        if an <= dtp and de <= dtn:
            return i
    return MARCADO


def analizar(tasa, pies, a, xl, x, T, A, E, banco, cs, umbr, k_off):
    out = {'pulsos': int(len(pies)), 'disparos_rtl': int(len(T)), 'ventanas': int(len(A)),
           'eventos': int(len(E))}

    # 1. el disparo
    tm = pb.DISPARO_PZ.disparos(x.astype(float))
    j = np.clip(np.searchsorted(tm, T), 1, len(tm) - 1)
    cerca = np.where(np.abs(T - tm[j - 1]) <= np.abs(T - tm[j]), tm[j - 1], tm[j])
    vals, cnt = np.unique(T - cerca, return_counts=True)
    delta = int(vals[np.argmax(cnt)])
    solo_rtl = sorted(set((T - delta).tolist()) - set(tm.tolist()))
    solo_mod = sorted(set(tm.tolist()) - set((T - delta).tolist()))
    out['disparo_distintos'] = {'solo_rtl': solo_rtl[:20], 'solo_modelo': solo_mod[:20]}
    out['disparo'] = {'modelo': int(len(tm)), 'rtl': int(len(T)), 'corrimiento': delta,
                      'iguales': float(np.mean(T - cerca == delta)),
                      'mismo_conjunto': bool(len(tm) == len(T) and np.all(T - delta == tm))}

    # las ventanas abren en el ciclo del flanco: A es un subconjunto de T
    ti = np.searchsorted(T, A)
    out['abre_con_su_disparo'] = bool(np.all(T[np.minimum(ti, len(T) - 1)] == A))
    n = min(len(A), len(E))
    A, E, ti = A[:n], E[:n], ti[:n]

    # 2. las marcas
    dtp_esp = np.where(ti > 0, T[ti] - T[np.maximum(ti - 1, 0)], 0xFFFF)
    sig = T[np.minimum(ti + 1, len(T) - 1)] - T[ti]
    dtn_esp = np.where((ti + 1 < len(T)) & (sig <= GATE - 1), sig, 0xFFFF)
    dtp_esp = np.minimum(dtp_esp, 0xFFFF)
    out['dt_prev_iguales'] = float(np.mean(E[:, 7] == dtp_esp))
    out['dt_next_iguales'] = float(np.mean(E[:, 8] == dtn_esp))

    # 3. la eleccion
    fe = E[:, 11]
    out['eleccion_igual'] = float(np.mean([eleccion(p, q, umbr) == f
                                           for p, q, f in zip(E[:, 7], E[:, 8], fe)]))
    out['formas'] = {str(i): int((fe == i).sum()) for i in range(len(banco))}
    out['formas']['marcado'] = int((fe == MARCADO).sum())

    # 4. la medicion, bit a bit, y donde abre la ventana
    ys = [trap_int(x, f) for f in banco]
    mejor = None
    for eps in range(-3, 4):
        ok = tot = 0
        for e, ai in zip(E, A):
            f = int(e[11])
            if f == MARCADO:
                continue
            fo = banco[f]
            ini = ai - PRE - LAT_TOP + eps + cs[f] + k_off
            if ini < 0 or ini + fo.w > len(x):
                continue
            suma = int(ys[f][ini:ini + fo.w].sum())
            prom = suma >> fo.lw
            esp = 0 if prom < 0 else min(prom, 0xFFFF)
            ok += int(esp == e[10]); tot += 1
        if mejor is None or ok > mejor[1]:
            mejor = (eps, ok, tot)
    eps, ok, tot = mejor
    # el F_TRAP exacto de cada evento con ese eps (None si es marcado o no entra)
    exacto = []
    for e, ai in zip(E, A):
        f = int(e[11])
        ini = ai - PRE - LAT_TOP + eps + (cs[f] + k_off if f != MARCADO else 0)
        if f == MARCADO or ini < 0 or ini + banco[f].w > len(x):
            exacto.append(None)
            continue
        prom = int(ys[f][ini:ini + banco[f].w].sum()) >> banco[f].lw
        exacto.append(0 if prom < 0 else min(prom, 0xFFFF))
    distintos = [(int(ai), int(e[11]), int(e[10]), v) for e, ai, v in zip(E, A, exacto)
                 if v is not None and v != e[10]]
    out['f_trap_distintos_por_forma'] = {str(i): sum(1 for d_ in distintos if d_[1] == i)
                                         for i in range(len(banco))}
    # la ventana del RTL arranca en (disparo del modelo) + c + corrimiento
    corr_ventana = delta + eps - PRE - LAT_TOP + k_off
    out['f_trap'] = {'iguales_bit_a_bit': ok, 'comparados': tot, 'eps': eps,
                     'ventana_menos_modelo': corr_ventana}

    # 5. la clasificacion con las decisiones del RTL
    gan = pb.ganancia(banco[0], 1.2)
    salidas = [pb.trap(xl[None], f)[0] for f in banco]
    clase = np.array(['perdido'] * len(pies), dtype=object)
    for e, ai, v_ex in zip(E, A, exacto):
        t = ai - delta                                   # el disparo, en el reloj del modelo
        jj = np.searchsorted(pies, t - pb.DISPARO_PZ.lat_min) - 1
        if jj < 0 or clase[jj] != 'perdido':
            continue
        f = int(e[11])
        if f == MARCADO:
            clase[jj] = 'marcado'
            continue
        if v_ex is not None and v_ex != e[10]:
            clase[jj] = 'error_rtl'        # el RTL no midio lo que dice el modelo entero
            continue
        ini = t + cs[f] + corr_ventana
        v = salidas[f][ini:ini + banco[f].w].mean()
        clase[jj] = 'bueno' if abs(v / (a[jj] * gan) - 1) < pb.CRIT_PAR / 100 else 'malo'
    modelo = pb.clasificar(pies, a, xl, x.astype(float), pb.DISPARO_PZ, banco, cs, umbr, N_ACC, GATE)
    seg = len(x) / 125e6
    for nom, cl in (('rtl', clase), ('modelo', modelo)):
        cnt = {k: int((cl == k).sum()) for k in ('bueno', 'malo', 'marcado', 'perdido', 'error_rtl')}
        out[nom] = {**cnt, 'buenos_kcps': cnt['bueno'] / seg / 1e3}
    out['misma_clase'] = float(np.mean(clase == modelo))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir')
    ap.add_argument('--tasas', type=int, nargs='+', default=[300, 1000])
    ap.add_argument('--gate', type=int, default=GATE)
    ap.add_argument('--pre', type=int, default=PRE)
    args = ap.parse_args()
    globals()['GATE'], globals()['PRE'] = args.gate, args.pre
    d = args.dir or tempfile.mkdtemp(prefix='banco_e2e_')
    os.makedirs(d, exist_ok=True)
    banco, cs, umbr = configuracion()
    k_off = PRE + LAT_TOP
    print(f'banco {[f"{f.k}/{f.m}/{f.w}" for f in banco]}, c = {cs}, umbrales {umbr}, '
          f'off = c + {k_off}; trabajo en {d}')
    lib = compilar(d)
    res = {'pre_dly': PRE, 'gate': GATE, 'n_acc': N_ACC, 'off_menos_c': k_off, 'tasas': {}}
    print(f'pre_dly = {PRE}, compuerta = {GATE}: la ventana de la forma 0 termina en '
          f'{cs[0] + k_off + 8 + banco[0].w} desde la apertura')
    for tasa in args.tasas:
        pies, a, xl, x, sat = estimulo(tasa)
        estim = os.path.join(d, f'estimulo_{tasa}.txt')
        volcado = os.path.join(d, f'volcado_{tasa}.txt')
        escribir(estim, x, banco, cs, umbr, k_off)
        print(f'\n{tasa} kcps: {len(pies)} pulsos, {len(x)} muestras ({sat} saturadas)')
        simular(lib, estim, volcado)
        T, A, E = leer(volcado)
        r = analizar(tasa, pies, a, xl, x, T, A, E, banco, cs, umbr, k_off)
        r['saturadas'] = sat
        res['tasas'][str(tasa)] = r
        dd = r['disparo']
        print(f"  disparo: {dd['rtl']} RTL / {dd['modelo']} modelo, corrimiento {dd['corrimiento']}, "
              f"iguales {100 * dd['iguales']:.2f} %, mismo conjunto: {dd['mismo_conjunto']}")
        print(f"  cada ventana abre con su disparo: {r['abre_con_su_disparo']}; "
              f"F_DTPREV {100 * r['dt_prev_iguales']:.2f} %, F_DTNEXT {100 * r['dt_next_iguales']:.2f} % iguales")
        print(f"  F_FORMA = la regla: {100 * r['eleccion_igual']:.2f} %  ({r['formas']})")
        ft = r['f_trap']
        print(f"  F_TRAP bit a bit: {ft['iguales_bit_a_bit']} de {ft['comparados']} (eps {ft['eps']}); "
              f"la ventana del RTL menos la del modelo: {ft['ventana_menos_modelo']} muestras")
        seg = len(x) / 125e6
        for nom in ('modelo', 'rtl'):
            c = r[nom]
            tot = len(pies)
            print(f"  {nom:6s}: buenos {100 * c['bueno'] / tot:5.1f} % ({c['buenos_kcps']:4.0f} kcps), "
                  f"sin detectar {100 * c['malo'] / tot:5.2f} %, marcados {100 * c['marcado'] / tot:5.1f} %, "
                  f"perdidos {100 * c['perdido'] / tot:5.1f} %"
                  + (f", ERROR DEL RTL {c['error_rtl']}" if c['error_rtl'] else ''))
        print(f"  misma clase pulso a pulso: {100 * r['misma_clase']:.2f} %; disparos distintos "
              f"{r['disparo_distintos']}; F_TRAP distinto por forma {r['f_trap_distintos_por_forma']}")
    with open(os.path.join(AQUI, f'banco_e2e_g{GATE}_p{PRE}.json'), 'w') as fh:
        json.dump(res, fh, indent=1)
    print(f'-> banco_e2e_g{GATE}_p{PRE}.json')


if __name__ == '__main__':
    main()
