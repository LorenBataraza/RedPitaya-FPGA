#!/usr/bin/env python3
"""Tests del motor de apilamiento. Corren en la PC, sin placa y sin datos.

El test que importa es el PRIMERO: la réplica vectorizada tiene que dar los
MISMOS eventos, evento por evento y cuenta por cuenta, que
`estimadores.segmentar_rtl` e `integral_gates`, que a su vez ya están validadas
contra el testbench de RTL y contra la placa (sigma del pico 2.78 réplica contra
2.81 medida). Si eso pasa, el Monte-Carlo está midiendo lo mismo que el
hardware. Si no, no, y todo lo demás sobra.

Se prueba justo sobre trazas con apilamiento forzado, que es donde el
segmentador tiene los casos raros: ventanas que se funden, máximos locales que
abren la cola y después son superados, cierres por `maxlen`, y segundos cruces
adentro de la compuerta.

    python3 test_pileup.py
"""
import os
import sys

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)
sys.path.insert(0, os.path.join(_AQUI, '..', 'estimadores'))

import pileup as pu                                          # noqa: E402
import estimadores as es                                     # noqa: E402

FAILS = []


def check(nombre, cond, extra=''):
    print(f'  [{"PASS" if cond else "FAIL"}] {nombre}{("  " + extra) if extra else ""}')
    if not cond:
        FAILS.append(nombre)


def checkv(nombre, got, exp):
    check(nombre, got == exp, f'(obtenido {got}, esperado {exp})')


def cerca(nombre, got, exp, tol):
    ok = np.isfinite(got) and abs(got - exp) <= tol
    check(nombre, ok, f'({got:.4g} contra {exp:.4g}, tol {tol:g})')


# =============================================================================
def _trazas_de_prueba(n_trazas, rng, forma):
    """Trazas cortas con apilamiento forzado: 1 a 4 pulsos muy juntos.

    Las separaciones se sortean chicas a propósito (hasta ~1.5 anchos de pulso):
    ahí es donde las ventanas se funden y donde el segmentador tiene los casos
    que un tren de pulsos separados no ejercita nunca.
    """
    for _ in range(n_trazas):
        n = int(rng.integers(1, 5))
        sep = np.concatenate(([0], rng.integers(5, 400, n - 1)))
        t = np.cumsum(sep) + 40
        a = rng.uniform(80, 3500, n)          # incluye pulsos casi bajo umbral
        y = rng.normal(0.0, pu.SIGMA_RUIDO, int(t[-1]) + forma.size + 700)
        for tk, ak in zip(t, a):
            y[tk:tk + forma.size] += ak * forma
        yield np.rint(y).astype(np.int64)


def test_replica_modo0():
    print('\n[1] modo 0: la réplica vectorizada = estimadores.segmentar_rtl')
    rng = np.random.default_rng(7)
    forma, _ = pu.forma_referencia(n_forma=512)     # corto, para que el test vuele
    cfg = dict(thr=100, hyst=40, maxlen=600, tail_dly=8)   # maxlen chico: fuerza apilamiento

    n_ev = n_dif = n_apil = 0
    for dat in _trazas_de_prueba(250, rng, forma):
        ref = es.segmentar_rtl(dat, baseline=0, **cfg)
        got = pu.segmentar_rapido(dat, baseline=0, **cfg)
        if len(ref) != got['i0'].size:
            n_dif += 1
            continue
        for k, e in enumerate(ref):
            n_ev += 1
            mismo = (e.i0 == got['i0'][k] and e.largo == got['largo'][k]
                     and e.q_tot == got['q_tot'][k] and e.q_tail == got['q_tail'][k]
                     and e.pico == got['pico'][k] and e.t_pico == got['t_pico'][k]
                     and pu.MOTIVOS[got['motivo'][k]] == e.motivo)
            if not mismo:
                n_dif += 1
                if n_dif <= 3:
                    print(f'      ref={e}')
                    print(f'      got=i0={got["i0"][k]} largo={got["largo"][k]} '
                          f'q_tot={got["q_tot"][k]} q_tail={got["q_tail"][k]} '
                          f'pico={got["pico"][k]} t_pico={got["t_pico"][k]} '
                          f'motivo={pu.MOTIVOS[got["motivo"][k]]}')
            n_apil += int(e.motivo == 'maxlen')

    check(f'{n_ev} eventos idénticos en i0/largo/q_tot/q_tail/pico/t_pico/motivo',
          n_dif == 0, f'({n_dif} diferencias)')
    check('el conjunto de prueba ejercita el cierre por maxlen', n_apil > 0,
          f'({n_apil} apilados)')


def test_replica_modo1():
    print('\n[2] modo 1: la réplica vectorizada = estimadores.integral_gates')
    rng = np.random.default_rng(11)
    forma, _ = pu.forma_referencia(n_forma=512)
    cfg = dict(thr=100, hyst=40, corta=32, larga=384)

    n_ev = n_dif = 0
    for dat in _trazas_de_prueba(250, rng, forma):
        ref = es.integral_gates(dat, baseline=0, **cfg)
        got = pu.compuertas_rapido(dat, baseline=0, **cfg)
        if len(ref) != got['i0'].size:
            n_dif += 1
            continue
        for k, g in enumerate(ref):
            n_ev += 1
            # integral_gates recorta la compuerta al fin del array; la réplica
            # también, así que q_tot y pico tienen que coincidir igual.
            mismo = (g['i0'] == got['i0'][k] and g['q_tot'] == got['q_tot'][k]
                     and g['q_tail'] == got['q_tail'][k]
                     and g['pico'] == got['pico'][k]
                     and bool(g['truncado']) == bool(got['truncado'][k]))
            if not mismo:
                n_dif += 1
                if n_dif <= 3:
                    print(f'      ref={g}')
                    print(f'      got=i0={got["i0"][k]} q_tot={got["q_tot"][k]} '
                          f'q_tail={got["q_tail"][k]} pico={got["pico"][k]} '
                          f'trunc={got["truncado"][k]}')
    check(f'{n_ev} compuertas idénticas en i0/q_tot/q_tail/pico/truncado',
          n_dif == 0, f'({n_dif} diferencias)')


def test_gate_2nd():
    print('\n[3] modo 1: la bandera de apilamiento (gate_2nd) del RTL')
    forma, info = pu.forma_referencia(n_forma=2048)
    cfg = dict(thr=100, hyst=40, corta=32, larga=384)
    thr_lo = cfg['thr'] - cfg['hyst']

    def apilado(dt, a1=1920.0, a2=1920.0):
        y = np.zeros(6000)
        y[100:100 + forma.size] += a1 * forma
        if dt is not None:
            y[100 + dt:100 + dt + forma.size] += a2 * forma
        ev = pu.compuertas_rapido(np.rint(y).astype(np.int64), **cfg)
        return bool(ev['apilado'][0])

    def baja_en(a):
        """Muestra en que la cola de un pulso de amplitud `a` cruza thr_lo."""
        v = a * forma
        i = np.flatnonzero(v[info['i_pico']:] < thr_lo)
        return info['i_pico'] + int(i[0]) if i.size else 10 ** 9

    check('un pulso solo NO se marca apilado', not apilado(None))

    # El RTL exige DOS pasos: la señal tiene que bajar de thr_lo y recién
    # después volver a cruzar thr_hi, todo dentro de la compuerta. Con un primer
    # pulso chico la cola baja a tiempo y la bandera funciona.
    print(f'      la cola de un pulso baja de thr_lo={thr_lo} en la muestra '
          f'{baja_en(200)} (A=200) y {baja_en(1920)} (A=1920); compuerta = 384')
    check('primer pulso chico (A=200), dt=380: la cola bajó a tiempo -> SE MARCA',
          apilado(380, a1=200.0))

    # LÍMITE MEDIDO DEL RTL, y es el resultado que justifica buscar otra cosa:
    # con el pulso de la campaña (2 us, A=1920) la cola tarda ~788 muestras en
    # bajar de thr_lo, o sea el DOBLE de la compuerta. La señal nunca vuelve a
    # cruzar desde abajo, así que gate_2nd NO puede dispararse por más apilado
    # que esté el evento. La bandera está viva sólo para primeros pulsos chicos.
    for dt in (100, 200, 300, 380):
        check(f'A=1920, dt={dt}: la cola no baja dentro de la compuerta '
              f'-> NO se marca (límite del RTL)', not apilado(dt))
    check('dt=600: segundo pulso FUERA de la compuerta -> no se marca',
          not apilado(600))


def test_forma():
    print('\n[4] la forma generada es la de la campaña de referencia')
    forma, info = pu.forma_referencia()
    cerca('FWHM = 2 us = 250 muestras', info['fwhm_pts'], 250.0, 2.5)
    cerca('cola tau = 186 muestras', info['tau'], 186.0, 1e-9)
    check('normalizada al pico', abs(forma.max() - 1.0) < 1e-12)
    check('empieza en cero', forma[0] == 0.0)
    # la cola tiene que estar apagada al final del template, si no el corte
    # introduce un escalón que el segmentador vería como señal
    check('la cola cae por debajo de 1e-3 al final del template',
          forma[-1] < 1e-3, f'({forma[-1]:.2e})')
    # tau se recupera del propio array
    i = info['i_pico']
    t = np.arange(i + 200, forma.size)
    tau_med = -1.0 / np.polyfit(t, np.log(forma[i + 200:]), 1)[0]
    cerca('tau recuperada del array', tau_med, 186.0, 2.0)


def test_arribos():
    print('\n[5] los arribos son un proceso de Poisson')
    rng = np.random.default_rng(3)
    tasa, n = 1e5, 200_000
    t = pu.arribos_poisson(n, tasa, rng=rng)
    dt = np.diff(t) / pu.FS_HZ
    med_esp = 1.0 / tasa
    cerca('media de los intervalos', dt.mean(), med_esp, 0.02 * med_esp)
    # de una exponencial, sigma == media
    cerca('sigma/media = 1 (exponencial)', dt.std() / dt.mean(), 1.0, 0.02)
    check('monótonos', bool(np.all(np.diff(t) >= 0)))

    # Kolmogorov-Smirnov contra la exponencial teórica
    x = np.sort(dt)
    F = 1.0 - np.exp(-tasa * x)
    m = x.size
    d = max(np.abs(F - np.arange(1, m + 1) / m).max(),
            np.abs(F - np.arange(0, m) / m).max())
    check(f'KS contra la exponencial: D={d:.4f} < 1.63/sqrt(n)={1.63/np.sqrt(m):.4f}',
          d < 1.63 / np.sqrt(m))


def test_agrupar():
    print('\n[6] el agrupado no puede perder ni duplicar eventos')
    rng = np.random.default_rng(5)
    for tasa in (1e3, 1e5, 5e5):
        t = pu.arribos_poisson(20_000, tasa, rng=rng)

        # sin tope: el criterio físico, un grupo por región de actividad
        gr = pu.agrupar(t, 2048, max_ev=None)
        cubre = sum(int(b - a) for a, b in gr)
        checkv(f'tasa {tasa:.0e}: todos los arribos en algún grupo', cubre, t.size)
        ok = all(t[gr[k + 1][0]] - t[gr[k][1] - 1] > 2048 for k in range(len(gr) - 1))
        check(f'tasa {tasa:.0e}: los huecos entre grupos superan el template', ok)

        # con tope: se subdivide para acotar la memoria, pero la partición tiene
        # que seguir siendo exacta (ni se pierde ni se duplica ningún arribo)
        gc = pu.agrupar(t, 2048, max_ev=1500)
        checkv(f'tasa {tasa:.0e}: con tope, la partición sigue siendo exacta',
               sum(int(b - a) for a, b in gc), t.size)
        contigua = all(gc[k][1] == gc[k + 1][0] for k in range(len(gc) - 1))
        check(f'tasa {tasa:.0e}: con tope, los trozos son contiguos', contigua)
        mx = max(int(b - a) for a, b in gc)
        # el tope es blando: el corte se corre al hueco más grande del entorno,
        # así que un trozo puede pasarse, pero no puede quedar sin acotar
        check(f'tasa {tasa:.0e}: el trozo más grande queda acotado '
              f'({mx} arribos)', mx <= 3000)


def test_locus_plano():
    print('\n[7] el lugar geométrico: plano en modo 1, con deriva en modo 0')
    rng = np.random.default_rng(13)
    forma, _ = pu.forma_referencia()
    amps = rng.uniform(400, 3400, 3000)
    dat, _ = pu.render_aislados(amps, forma, rng=rng)

    ev0 = pu.segmentar_rapido(dat, **pu.CFG_MODO0)
    ev1 = pu.compuertas_rapido(dat, **pu.CFG_MODO1)
    checkv('modo 0 detecta un evento por pulso', ev0['i0'].size, amps.size)
    checkv('modo 1 detecta un evento por pulso', ev1['i0'].size, amps.size)

    r0 = pu.razon_forma(ev0, 'q_pico')
    r1 = pu.razon_forma(ev1, 'q_pico')
    a0, a1 = pu.amplitud(ev0, 0), pu.amplitud(ev1, 1)

    l0 = pu.locus_forma(a0, r0)
    l1 = pu.locus_forma(a1, r1)
    d0 = 100 * (l0[1][-1] / l0[1][0] - 1)
    d1 = 100 * (l1[1][-1] / l1[1][0] - 1)
    print(f'      deriva de Q/pico entre el bin más bajo y el más alto: '
          f'modo 0 {d0:+.1f} %, modo 1 {d1:+.1f} %')
    check('modo 0: Q/pico deriva con la amplitud (>5 %)', d0 > 5.0)
    check('modo 1: Q/pico es plano (<1 %)', abs(d1) < 1.0)

    # a tasa cero el corte casi no puede rechazar: si rechaza, está mal calibrado
    for nombre, a, r, l in (('modo 0', a0, r0, l0), ('modo 1', a1, r1, l1)):
        ef = float(pu.aplicar_corte(a, r, l, k=3.0).mean())
        check(f'{nombre}: el corte k=3 deja pasar >99 % de los pulsos limpios',
              ef > 0.99, f'({100*ef:.2f} %)')


def test_resolucion_conocida():
    print('\n[8] el simulador contra las resoluciones ya medidas')
    rng = np.random.default_rng(17)
    forma, _ = pu.forma_referencia()
    # línea sin ancho intrínseco: lo que quede ES la contribución de la cadena
    amps = np.full(4000, 2410.0)            # la amplitud del conjunto de estimadores
    dat, _ = pu.render_aislados(amps, forma, rng=rng)

    ev0 = pu.segmentar_rapido(dat, **pu.CFG_MODO0)
    ev1 = pu.compuertas_rapido(dat, **pu.CFG_MODO1)
    r_pico = es.resolucion(ev0['pico'])
    r_gate = es.resolucion(ev1['q_tot'])
    print(f'      pico: sigma {r_pico["sigma"]:.2f} cuentas, '
          f'resolución {r_pico["res_pct"]:.3f} %  (placa: 2.81 cuentas, 0.272 %)')
    print(f'      compuerta 384: resolución {r_gate["res_pct"]:.3f} %  '
          f'(offline sobre pulsos reales: 0.149 %)')

    # LO QUE SE VALIDA, Y LO QUE NO. El simulador tiene ruido blanco y NADA MÁS:
    # los pulsos reales traen además el jitter de forma y de amplitud del
    # generador, que es irreducible y que acá no existe. Así que las
    # resoluciones absolutas salen OPTIMISTAS —el pico da ~1.7 cuentas contra
    # 2.81 medidas— y no tiene sentido exigir que coincidan. Lo que sí tiene que
    # reproducirse es el ORDEN DE MAGNITUD y, sobre todo, el ORDENAMIENTO entre
    # estimadores, que es lo que decidió el modo 1.
    #
    # Para las conclusiones sobre apilamiento esto no mueve la aguja: el ancho
    # de la línea lo fija `res_pct` del espectro fuente (3 % = 24 cuentas sobre
    # 1920), diez veces mayor que cualquiera de estas sigmas.
    check('la sigma del pico es del orden de la medida en placa (dentro de 2x)',
          0.5 * 2.81 <= r_pico['sigma'] <= 2.0 * 2.81,
          f'({r_pico["sigma"]:.2f} contra 2.81)')
    check('la sigma del pico es MENOR que el ruido por muestra '
          '(el máximo de una meseta promedia)',
          r_pico['sigma'] < pu.SIGMA_RUIDO,
          f'({r_pico["sigma"]:.2f} contra {pu.SIGMA_RUIDO})')
    check('la compuerta fija resuelve mejor que el pico, como se midió offline',
          r_gate['res_pct'] < r_pico['res_pct'],
          f'({r_gate["res_pct"]:.3f} % contra {r_pico["res_pct"]:.3f} %)')


def test_calibracion_y_metricas():
    print('\n[9] calibración del estimador y métricas contra la verdad')
    rng = np.random.default_rng(19)
    forma, _ = pu.forma_referencia()
    amps = pu.sortear_amplitudes(6000, 'linea', rng)
    dat, _ = pu.render_aislados(amps, forma, rng=rng)

    for modo, ev in ((0, pu.segmentar_rapido(dat, **pu.CFG_MODO0)),
                     (1, pu.compuertas_rapido(dat, **pu.CFG_MODO1))):
        a = pu.amplitud(ev, modo)
        cal = pu.calibrar(a, amps)
        can = pu.a_canal(a, cal)
        h_med = pu.histograma(can)
        h_ver = pu.histograma(pu.a_canal(amps, (1.0, 0.0)))
        m = pu.metricas(h_med, h_ver, canal_pico=1920, semi_ancho=200, tope=3000)
        print(f'      modo {modo}: ganancia {cal[0]:.3f}, '
              f'área {m["area_rel"]:.4f}, corrimiento {m["corrimiento"]:+.2f} can, '
              f'L1 {m["l1"]:.4f}')
        check(f'modo {modo}: a tasa cero se conservan las cuentas del pico',
              abs(m['area_rel'] - 1.0) < 0.02)
        check(f'modo {modo}: a tasa cero el centroide no se corre',
              abs(m['corrimiento']) < 3.0)
        check(f'modo {modo}: a tasa cero no hay continuo sobre el tope',
              m['continuo'] < 1e-3, f'({m["continuo"]:.2e})')


def test_apilamiento_aparece():
    print('\n[10] la pérdida por tiempo muerto sigue el modelo PARALIZABLE')
    rng = np.random.default_rng(23)
    forma, _ = pu.forma_referencia()

    # Largo de la ventana de un pulso AISLADO: es el tiempo muerto del modo 0.
    # No es un parámetro libre — sale de thr, hyst y la cola: la ventana cierra
    # cuando la cola cruza thr-hyst, o sea en i_pico + tau*ln(A/thr_lo).
    d0, _ = pu.render_aislados(pu.sortear_amplitudes(500, 'linea', rng), forma,
                               rng=rng)
    L0 = float(pu.segmentar_rapido(d0, **pu.CFG_MODO0)['largo'].mean())
    print(f'      ventana de un pulso aislado: {L0:.0f} muestras = '
          f'{L0/pu.FS_HZ*1e6:.2f} us')
    print(f'      {"tasa":>8} {"m/n":>8} {"paraliz.":>9} {"no-paraliz.":>12}')

    n = 15_000
    peor_par = peor_npar = 0.0
    for tasa in (2e4, 5e4, 1e5):
        amps = pu.sortear_amplitudes(n, 'linea', rng)
        t = pu.arribos_poisson(n, tasa, rng=rng)
        m = 0
        picos = []
        for a, b in pu.agrupar(t, forma.size):
            dat, _ = pu.render(t[a:b], amps[a:b], forma, rng=rng)
            ev = pu.segmentar_rapido(dat, **pu.CFG_MODO0)
            m += int(ev['cerrado'].sum())
            picos.append(ev['pico'][ev['cerrado']])
        picos = np.concatenate(picos)
        r = m / n
        # Un arribo DENTRO de la ventana no la reinicia: la ESTIRA, porque el
        # pulso nuevo mantiene la señal arriba del umbral. Ese es exactamente el
        # tiempo muerto extendible del modelo paralizable, m = n*exp(-n*tau).
        par  = float(np.exp(-tasa * L0 / pu.FS_HZ))
        npar = float(pu.tasa_no_paralizable(tasa, L0 / pu.FS_HZ) / tasa)
        print(f'      {tasa:8.0e} {r:8.4f} {par:9.4f} {npar:12.4f}')
        peor_par  = max(peor_par,  abs(r - par) / par)
        peor_npar = max(peor_npar, abs(r - npar) / npar)
        if tasa == 5e4:
            check('a 50 kcps aparecen eventos muy por encima de la línea '
                  '(pico suma)', float((picos > 1.5 * 1920).mean()) > 0.02)

    check(f'el modelo paralizable ajusta dentro del 10 % relativo',
          peor_par < 0.10, f'(peor desvío {100*peor_par:.1f} %)')
    check('...y ajusta MEJOR que el no paralizable',
          peor_par < peor_npar,
          f'({100*peor_par:.1f} % contra {100*peor_npar:.1f} %)')


def main():
    for t in (test_replica_modo0, test_replica_modo1, test_gate_2nd, test_forma,
              test_arribos, test_agrupar, test_locus_plano,
              test_resolucion_conocida, test_calibracion_y_metricas,
              test_apilamiento_aparece):
        t()
    print(f'\nRESULT: {"PASS" if not FAILS else "FAIL"}')
    if FAILS:
        for f in FAILS:
            print(f'  - {f}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
