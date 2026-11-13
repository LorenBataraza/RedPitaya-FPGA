#!/usr/bin/env python3
"""El estímulo de tb_pulsos_mca: el generador de pulsos manejando el MCA.

Es el mismo circuito que `volcado_mca2.py`, con una diferencia: el estímulo no
es una traza sino la configuración del generador de pulsos (gen_pulsos, el que
va en el lugar del ASG), que el TB corre en RTL. El test arma la traza con el
modelo del generador y le pasa la réplica del MCA:

    python3 monte-carlo/volcado_pulsos.py             # escribe el estímulo
    make -C ../sim tb_pulsos_mca                      # QuestaSim: el volcado
    python3 -m pytest monte-carlo/test_pulsos_mca.py

Las dos cosas quedan en `monte-carlo/datos_ref/`. Cada bloque termina FLUSH
muestras después del último pulso (el generador tiene N), para que todas las
ventanas cierren antes de que el TB pare el MCA.

FORMATO DEL ESTÍMULO
    B <la línea B de volcado_mca2.py, sin el largo>
    G asg aleatorio periodo umbral dt_min n semilla amp_aleat amp_n decae subida
      base ruido ruido_sh n_tabla n_muestras
    <n_tabla líneas: la amplitud en hex, 14 bits en complemento a dos>
    ...
    FIN

FORMATO DEL VOLCADO: el de volcado_mca2.py, más
    P <GEN_CNT>               los pulsos que salieron, al final del bloque
y con `i` el índice de la muestra del generador (0 = el ciclo después del
arranque, como en gen_pulsos_model.py).
"""

import argparse
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
_MODELO_GEN = os.path.join(_AQUI, '..', '..', 'modulos', 'gen_eventos', 'modelos', 'python_model')
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.dirname(_AQUI))                  # software/, por la API
sys.path.insert(0, os.path.abspath(_MODELO_GEN))

import gen_eventos_model as ge                               # noqa: E402
import gen_pulsos_model as gp                                # noqa: E402
import replica_mca2 as r2                                    # noqa: E402
import volcado_mca2 as vd                                    # noqa: E402

DATOS_REF = os.path.join(_AQUI, 'datos_ref')
ESTIMULO = os.path.join(DATOS_REF, 'pulsos_estimulo.txt')
VOLCADO = os.path.join(DATOS_REF, 'pulsos_volcado.txt')

FLUSH = 4000          # muestras después del último pulso
PAD = 2000            # ceros antes de la traza en la réplica: el MCA ya venía corriendo

# Del pulso del generador (trig_o) al flanco de trig_i del MCA, por la fuente ASG: los
# dos registros de sincronismo y el de flanco de rp_ext_trig, y el registro de
# mt_trig_src. Es la del TB (tb_pulsos_mca).
LAT_ASG = 4
# En el top el dato del lazo digital pasa además por el registro de adc_dat, que el TB
# no tiene: el dato llega un ciclo más tarde y el disparo del ASG, relativo a él, uno
# antes. Medido en la placa el 2026-11-09 (docs/gen_eventos/generador_pulsos.md §8).
LAT_ASG_TOP = LAT_ASG - 1
# Tras un disparo, mt_trig_src no acepta otro hasta que el shield lo re-arma
# (DUR = 0): un pulso del ASG a menos de 3 ciclos del último aceptado se pierde.
REARME = 3

# Lo que tiene que dar la placa en cada bloque: la réplica con LAT_ASG_TOP. La lee
# API/tests/placa/test_generadores_placa.py, que corre allá sin los modelos.
REF_PLACA = os.path.join(DATOS_REF, 'pulsos_placa_ref.json')
# Los dos espectros 1D que mide el test de placa: (feature, zoom). Con zoom 3 el
# canal es el valor (F_TRISE); con 0, los 13 bits altos de la feature.
ESPECTROS_PLACA = (('F_PEAK', 0), ('F_TRISE', 3))
AW_1D = 13            # 8192 canales
_CLAVES_G = ('aleatorio', 'periodo', 'umbral', 'dt_min', 'n', 'semilla', 'amp_aleat',
             'amp_n', 'decae', 'subida', 'base', 'ruido', 'ruido_sh')


def mq_de(decae):
    """La Mq del trapecio y del polo-cero que cancela la caída del generador."""
    return int(round(16.0 * gp.m_polo_cero(decae)))


def forma_de(gen_kw):
    """El pulso del generador, normalizado al pico: para ajustar los disparos."""
    kw = {k: gen_kw[k] for k in ('decae', 'subida') if k in gen_kw}
    t = gp.traza(2600, [8000], periodo=100, n=1, amp_n=1, **kw)
    x = t['dat'][int(t['trig'][0]):].astype(float)
    return x / x.max()


def _bloques_def():
    """(nombre, configuración del MCA, del generador, tabla, disparo por ASG)."""
    lineas = gp.tabla_cdf([1500, 4000], [0.6, 0.4])
    continuo = gp.tabla_cdf(np.r_[np.linspace(300, 6000, 200), 3000],
                            np.r_[np.full(200, 0.6 / 200), 0.4])
    tau_campana, tau_pre = 186.0, 250.0

    # A: el disparo por pendiente de la campaña, una ranura, dos líneas
    ga = dict(aleatorio=True, umbral=ge.umbral_para(200e3, dt_min=2), dt_min=2,
              n=150, semilla=11, amp_aleat=True, decae=gp.decae_para(tau_campana),
              subida=3, ruido=True, ruido_sh=6)
    ca = dict(n_acc=1, trap_mq=mq_de(ga['decae']))

    # B: el banco del recorte (3 formas) con el disparo con polo-cero, 3 ranuras,
    # a 1 Mcps: apila y pierde
    from API.mca import BANCO_PZ, mca_banco_config
    gb = dict(aleatorio=True, umbral=ge.umbral_para(1e6, dt_min=5), dt_min=5,
              n=400, semilla=22, amp_aleat=True, decae=gp.decae_para(tau_pre),
              subida=0, ruido=True, ruido_sh=5)
    mq_b = mq_de(gb['decae'])
    # el pre_dly del disparo con polo-cero pisa el del banco (los dos son 16)
    cb = {**mca_banco_config(mq_b, formas=BANCO_PZ),
          **r2.disparo_pz_para(forma_de(gb), mq_b, a_umbral=50.0), 'n_acc': 3}

    # C: el disparo del ASG, periódico, la tabla en orden: un barrido de amplitud
    gc = dict(periodo=1500, n=200, amp_n=200, decae=gp.decae_para(tau_campana),
              subida=2)
    rampa = [int(round(100 + i * (7900 / 199))) for i in range(200)]
    cc = dict(n_acc=2, trap_mq=mq_de(gc['decae']))

    # D: el disparo del ASG con Poisson a 600 kcps, 3 ranuras, el banco: las
    # pérdidas con los disparos exactos
    gd = dict(aleatorio=True, umbral=ge.umbral_para(600e3, dt_min=2), dt_min=2,
              n=300, semilla=44, amp_aleat=True, decae=gp.decae_para(tau_pre),
              subida=0, ruido=True, ruido_sh=4)
    cd = dict(n_acc=3, **mca_banco_config(mq_de(gd['decae']), formas=BANCO_PZ))

    return (('pendiente', ca, ga, lineas, False),
            ('pz_banco', cb, gb, continuo, False),
            ('asg_rampa', cc, gc, rampa, True),
            ('asg_poisson', cd, gd, lineas, True))


def _largo(gen_kw, tabla):
    """Cuántas muestras corre el bloque: hasta FLUSH después del último pulso."""
    n = int(gen_kw['n'])
    if gen_kw.get('aleatorio'):
        media = ge.intervalo_medio(int(gen_kw['umbral']), int(gen_kw.get('dt_min', 2)))
    else:
        media = max(int(gen_kw.get('periodo', 1000)), 2)
    t = gp.traza(int(1.5 * n * media) + 2000, tabla, **gen_kw)
    if t['trig'].size < n:
        raise RuntimeError(f'el bloque no llegó a {n} pulsos')
    return int(t['trig'][-1]) + FLUSH


def bloques():
    """[(nombre, cfg del MCA, kw del generador, tabla, asg, n_muestras)]."""
    out = []
    for nombre, ckw, gkw, tabla, asg in _bloques_def():
        out.append((nombre, r2.cfg(**ckw), gkw, list(tabla), asg, _largo(gkw, tabla)))
    return out


def escribir_estimulo(path=ESTIMULO):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for _, c, gkw, tabla, asg, n in bloques():
            vals = [int(c['fuente'] == 'pz') if k == 'fuente' else int(c[k])
                    for k in vd._CLAVES_B]
            f.write('B ' + ' '.join(str(v) for v in vals) + '\n')
            g = {**gp.CFG, **gkw}
            f.write(f'G {int(asg)} ' + ' '.join(str(int(g[k])) for k in _CLAVES_G)
                    + f' {len(tabla)} {n}\n')
            for v in tabla:
                f.write(f'{int(v) & 0x3FFF:04x}\n')
        f.write('FIN\n')
    return path


def leer_estimulo(path=ESTIMULO):
    """[(cfg, kw del generador, tabla, asg, n_muestras)] tal como los leyó el TB."""
    out = []
    with open(path) as f:
        while True:
            ln = f.readline()
            if not ln or ln.startswith('FIN'):
                break
            kw = dict(zip(vd._CLAVES_B, (int(v) for v in ln.split()[1:])))
            kw['fuente'] = 'pz' if kw['fuente'] else 'pendiente'
            p = f.readline().split()
            asg = bool(int(p[1]))
            vals = [int(v) for v in p[2:]]
            gkw = dict(zip(_CLAVES_G, vals[:len(_CLAVES_G)]))
            n_tab, n = vals[len(_CLAVES_G)], vals[len(_CLAVES_G) + 1]
            tabla = []
            for _ in range(n_tab):
                v = int(f.readline(), 16)
                tabla.append(v - 0x4000 if v >= 0x2000 else v)
            out.append((r2.cfg(**kw), gkw, tabla, asg, n))
    return out


def leer_volcado(path=VOLCADO):
    """Lo de `volcado_mca2.leer_volcado`, con `gen_cnt` (la línea P) por bloque."""
    out = vd.leer_volcado(path)
    p = []
    with open(path) as f:
        for ln in f:
            if ln.startswith('P '):
                p.append(int(ln.split()[1]))
    for b, n in zip(out, p):
        b['gen_cnt'] = n
    return out


def entrada_replica(gkw, tabla, n):
    """La muestra que ve el MCA (con PAD ceros antes) y los pulsos del generador."""
    t = gp.traza(n, tabla, **gkw)
    x = np.concatenate([np.zeros(PAD, np.int64), t['dat']])
    return x, t


def disparos_asg(pulsos):
    """Los pulsos que el multitrigger acepta por la fuente ASG."""
    out, ult = [], None
    for t in pulsos:
        if ult is None or t - ult >= REARME:
            out.append(int(t))
            ult = t
    return np.array(out, np.int64)


def canal_1d(feat, z, k=0, aw=AW_1D):
    """El canal del histograma 1D de una feature de 16 bits con zoom (z, k): la
    ventana [k 2^(16-z), (k+1) 2^(16-z)), que satura en los bordes, y los aw bits
    siguientes (docs/mca/register_map_mca.md, el zoom)."""
    ancho = 1 << (16 - z)
    rel = np.clip(np.asarray(feat, np.int64) - k * ancho, 0, ancho - 1)
    return rel >> (16 - z - aw)


def referencia_placa(lat_asg=LAT_ASG_TOP):
    """Por bloque del estímulo, lo que tiene que medir la placa: GEN_CNT, los
    contadores (con los nombres de los registros del MCA), t_ocup[1:] y los
    espectros de ESPECTROS_PLACA como {canal: cuentas}."""
    out = []
    for nombre, (c, gkw, tabla, asg, n) in zip([b[0] for b in _bloques_def()],
                                               leer_estimulo()):
        x, t = entrada_replica(gkw, tabla, n)
        trig = disparos_asg(t['trig']) + lat_asg + PAD if asg else None
        m = r2.medir(x, c, trig=trig)
        k = m['cnt']
        if k['rej_amp'] or k['rej_psd']:
            raise RuntimeError(f'{nombre}: con rechazos el espectro no son los publicados')
        ev = m['eventos']
        esp = {}
        for f, z in ESPECTROS_PLACA:
            u, cu = np.unique(canal_1d(ev['feat'][:, getattr(r2, f)], z), return_counts=True)
            esp[f'{f}_z{z}'] = {str(int(a)): int(b) for a, b in zip(u, cu)}
        cnt = dict(total=k['total'], accepted=k['accepted'], rej_amp=k['rej_amp'],
                   rej_psd=k['rej_psd'], pileup=k['pileup'], dropped=k['lost_busy'],
                   cross=k['cross'], open=k['open'], lost_active=k['lost_active'],
                   win=k['windows'], trig=k['trig'])
        out.append(dict(nombre=nombre, fuente='ASG' if asg else c['fuente'],
                        n_acc=int(c['n_acc']), gen_cnt=int(t['trig'].size), cnt=cnt,
                        t_ocup=[int(v) for v in m['t_ocup'][1:]], espectros=esp))
    return dict(lat_asg=lat_asg, aw_1d=AW_1D, estimulo=os.path.basename(ESTIMULO),
                bloques=out)


def escribir_referencia_placa(path=REF_PLACA):
    import json
    with open(path, 'w') as f:
        json.dump(referencia_placa(), f, indent=1, sort_keys=True)
        f.write('\n')
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--salida', default=ESTIMULO)
    ap.add_argument('--placa', action='store_true',
                    help=f'escribe sólo la referencia del test de placa ({REF_PLACA})')
    a = ap.parse_args(argv)
    if a.placa:
        p = escribir_referencia_placa()
        print(f'referencia de la placa: {p}')
        return 0
    p = escribir_estimulo(a.salida)
    print(f'estímulo: {p} ({os.path.getsize(p) / 1e3:.0f} kB)')
    for nombre, c, gkw, tabla, asg, n in bloques():
        x, t = entrada_replica(gkw, tabla, n)
        trig = None
        if asg:
            # una latencia cualquiera: sólo para mostrar qué esperar
            trig = t['trig'] + PAD + 8
        m = r2.medir(x, c, trig=trig)
        print(f'  {nombre}: n_acc={c["n_acc"]} {"ASG" if asg else c["fuente"]} {n} muestras, '
              f'{t["trig"].size} pulsos, {m["cnt"]["cross"]} disparos, {m["cnt"]["open"]} abren, '
              f'{m["cnt"]["lost_active"]} lost_active, {m["cnt"]["lost_busy"]} lost_busy, '
              f'{m["cnt"]["accepted"]} publicados, {m["cnt"]["pileup"]} solapados')
    return 0


if __name__ == '__main__':
    sys.exit(main())
