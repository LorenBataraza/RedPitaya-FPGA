#!/usr/bin/env python3
"""Monte-Carlo de apilamiento: barre la tasa y guarda todo para graficar aparte.

Corre en la PC, sin placa. Para cada combinación de espectro fuente, configuración
del MCA y tasa produce CUATRO espectros sobre el mismo eje calibrado:

  verdad     las amplitudes sorteadas. Se conocen exactas, y es lo único que la
             placa no puede darnos: sin esto no hay contra qué comparar.
  referencia el MISMO MCA con los pulsos aislados —mismo ruido, mismo umbral,
             mismo estimador, cero apilamiento—. Aísla la distorsión por
             apilamiento de todo lo demás. Sin esta curva, lo que se mida
             incluiría el ensanchamiento por ruido y el sesgo del estimador.
  medido     el MCA a la tasa del barrido, con el rechazo que el RTL YA hace.
             Es la línea de base contra la que se juzga cualquier corte nuevo.
  con corte  lo anterior más el corte por factor de forma, para cada
             discriminador y cada ancho de banda k.

EL MAPA. Por defecto es el MCA2, con la réplica de `replica_mca2.py` (validada
evento por evento contra el RTL): ver CONFIGS_MCA2. `--mapa MCA1` corre el barrido
viejo, los modos 0 (histéresis) y 1 (compuertas) de `pileup.py`, que reproduce lo
documentado en docs/mca/apilamiento.md §MCA1.

Con el MCA2 se agrega, por tasa: la pérdida por ranuras contra Erlang B, el
espectro sin lo que el propio RTL marca como solapado (`F_SOLAPE`), y los eventos
BUENOS por segundo. Bueno es lo que sólo el Monte-Carlo puede saber: el evento mide
la amplitud verdadera del pulso que lo disparó con error < 1 %.

    python3 montecarlo.py                          # el barrido completo (~20 min)
    python3 montecarlo.py --n-eventos 5000         # una corrida rápida
    python3 montecarlo.py --espectro linea --modo r1,banco
    python3 montecarlo.py --mapa MCA1 --modo 0     # el barrido viejo
"""
import argparse
import json
import os
import sys
import time

import numpy as np

_AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AQUI)

_RAIZ = _AQUI
while _RAIZ != '/' and not os.path.isfile(os.path.join(_RAIZ, 'API', 'mca.py')):
    _RAIZ = os.path.dirname(_RAIZ)          # sube hasta software/

import pileup as pu                                          # noqa: E402
import replica_mca2 as r2                                    # noqa: E402

N_CANALES = 16384        # H_AW = 14, como el RTL; 1 canal = 1 cuenta verdadera
RAZONES   = ('q_pico', 'psd')
KS        = (1.5, 2.0, 2.5, 3.0, 4.0, 6.0)
TASAS     = (1e3, 5e3, 2e4, 5e4, 1e5, 2e5, 3e5, 5e5)
TASAS_MCA2 = TASAS + (1e6,)      # donde el banco tiene algo que mostrar

# Regiones de interés por espectro. `tope` es el punto final de la fuente: por
# encima de eso la fuente NO PUEDE poner nada, así que toda cuenta ahí arriba es
# apilamiento puro y no hay que ajustar nada para verla.
ESPECTROS = {
    'linea':    dict(picos=(1920,), semi_ancho=150, tope=2300),
    'realista': dict(picos=(1250, 2620), semi_ancho=350, tope=3400),
}


# =============================================================================
# Las configuraciones del MCA2
# =============================================================================
#
# El disparo y el trapecio se ajustan a la forma con las funciones de la réplica,
# igual que en la placa se ajustan al pulso: nada de lo que sigue es un número
# mágico de otra corrida.
#
# Son dos pulsos. La semi-gaussiana de la campaña (FWHM 2 µs, sube en ~100
# muestras) es la de las mediciones que hay; ahí se barre `n_acc`. El pulso del
# preamplificador (sube en ~1 muestra) es para el que está pensado el banco, que
# con la otra no tiene meseta para k = 8; ahí se compara el banco y su disparo
# contra un trapecio solo con la pendiente, sobre el mismo pulso.

MQ_CAMPANA = int(round(16.0 / np.expm1(1.0 / pu.TAU_COLA)))
TAU_PREAMP = 250.0
MQ_PREAMP = int(round(16.0 / np.expm1(1.0 / TAU_PREAMP)))


def _forma_campana():
    return pu.forma_referencia()[0]


def _forma_preamp():
    return r2.forma_preamp(tau=TAU_PREAMP, n=2600)


def _integral(n_acc):
    def armar(forma):
        return r2.cfg(n_acc=n_acc, **r2.disparo_para(forma))
    return armar


def _trapecio_campana(forma):
    c = r2.cfg(n_acc=4, **r2.disparo_para(forma), trap_k=64, trap_m=256, trap_mq=MQ_CAMPANA)
    return {**c, **r2.trap_para(forma, c)}


def _trapecio_preamp(forma):
    # La forma larga del banco, sola, con la pendiente: lo que había antes.
    c = r2.cfg(n_acc=4, gate_long=128, **r2.disparo_para(forma), trap_k=64, trap_m=48,
               trap_mq=MQ_PREAMP)
    return {**c, **r2.trap_para(forma, c)}


def _banco(forma):
    if _RAIZ not in sys.path:
        sys.path.insert(0, _RAIZ)
    from API.mca import mca_banco_config
    kw = mca_banco_config(MQ_PREAMP)         # la misma receta que en la placa
    kw.update(r2.disparo_pz_para(forma, MQ_PREAMP, pre_dly=kw['pre_dly']))
    return r2.cfg(n_acc=4, **kw)


# nombre -> (etiqueta, pulso, estimador, armar)
CONFIGS_MCA2 = {
    'r1':    ('1 ranura, integral', _forma_campana, 'integral', _integral(1)),
    'r2':    ('2 ranuras, integral', _forma_campana, 'integral', _integral(2)),
    'r4':    ('4 ranuras, integral', _forma_campana, 'integral', _integral(4)),
    'r4t':   ('4 ranuras, trapecio', _forma_campana, 'trapecio', _trapecio_campana),
    'p4t':   ('preamp: 4 ranuras, un trapecio, pendiente', _forma_preamp, 'trapecio',
              _trapecio_preamp),
    'banco': ('preamp: 4 ranuras, banco, polo-cero', _forma_preamp, 'trapecio', _banco),
}
_MCA2 = {}                  # nombre -> la configuración armada, ver `_armar`


def _armar(nombre):
    if nombre not in _MCA2:
        etiqueta, forma, estimador, armar = CONFIGS_MCA2[nombre]
        f = forma()
        _MCA2[nombre] = dict(etiqueta=etiqueta, forma=f, estimador=estimador, cfg=armar(f))
    return _MCA2[nombre]


def _es_mca2(modo):
    return isinstance(modo, str)


def _eventos(dat, modo):
    """(eventos, contadores); en el MCA1 no hay contadores: `medir` no corre."""
    if _es_mca2(modo):
        return r2.eventos_mc(dat, _armar(modo)['cfg'])
    return (pu.segmentar_rapido(dat, **pu.CFG_MODO0) if modo == 0
            else pu.compuertas_rapido(dat, **pu.CFG_MODO1)), None


def _amplitud(ev, modo):
    if not _es_mca2(modo):
        return pu.amplitud(ev, modo)
    if _armar(modo)['estimador'] == 'trapecio':
        return np.minimum(ev['trap'], 0xFFFF).astype(np.int64)
    return pu.amplitud(ev, 1)                # la integral, q_tot >> Q_SHIFT


def _clave_de_apareo(modo):
    """La ventana del MCA2 abre ANTES del pulso (`pre_dly`); su disparo, después."""
    return 'i_par' if _es_mca2(modo) else 'i0'


# Rango del pulser de calibración. Arriba se queda por debajo de la saturación
# del ADC (8191) para que el pico no se recorte, y alcanza para cubrir donde
# caen los apilados: el pico suma de la línea está en 3840 y el de la línea alta
# del espectro realista en 5240.
A_PULSER = (110.0, 7000.0)


N_TANDA = 2000           # pulsos por traza aislada; ver `corrida_aislada`


def corrida_aislada(amps, forma, modo, rng, n_tanda=N_TANDA):
    """El MCA a tasa cero: pulsos aislados, apareados 1:1 con su amplitud.

    Devuelve (ev, amp_est, a_verdadera). El apareo es por posición: cada pulso
    está solo en su tramo, así que la ventana que abre después del arribo `k`
    (el disparo, en el MCA2) es la del pulso `k`. Los pulsos bajo umbral no abren
    ninguna y quedan afuera del apareo.

    Se procesa POR TANDAS porque los pulsos aislados ocupan `forma.size + trail`
    muestras cada uno: 50 000 pulsos en una sola traza son 1.2e8 muestras, o sea
    ~1 GB en float64 más las copias. Con tandas de 2000 la traza queda en ~35 MB
    y el resultado es idéntico: las tandas son independientes por construcción,
    justamente porque los pulsos no se tocan.
    """
    amps = np.asarray(amps)
    trozos = []
    for a in range(0, amps.size, int(n_tanda)):
        sub = amps[a:a + int(n_tanda)]
        dat, loc = pu.render_aislados(sub, forma, rng=rng)
        ev, _ = _eventos(dat, modo)
        slot = np.searchsorted(loc, ev[_clave_de_apareo(modo)], side='right') - 1
        m = ev['cerrado'] & (slot >= 0)
        ev = {k: v[m] for k, v in ev.items()}
        trozos.append((ev, _amplitud(ev, modo), sub[slot[m]]))

    ev = {k: np.concatenate([t[0][k] for t in trozos]) for k in trozos[0][0]}
    return (ev, np.concatenate([t[1] for t in trozos]),
            np.concatenate([t[2] for t in trozos]))


def calibracion_pulser(forma, modo, rng, n=12_000, rango=A_PULSER):
    """Calibra ganancia y lugar geométrico con un PULSER DESLIZANTE.

    HACE FALTA que sea un barrido uniforme y no el propio espectro fuente, y
    esto es lo que decide si el corte mide algo: el lugar geométrico hay que
    conocerlo en TODO el rango de amplitudes donde caen los eventos, y los
    apilados caen justo donde la fuente no pone nada —entre la línea y el pico
    suma—. Calibrando con una línea monoenergética el lugar geométrico quedaría
    definido en un puñado de canales y `np.interp` extrapolaría plano hacia
    arriba: el corte rechazaría los eventos apilados por estar fuera del rango
    calibrado y no por tener la forma mal. Sería un corte en amplitud disfrazado
    de corte en forma, y daría un resultado espectacular y falso.

    El barrido uniforme de amplitud es además el estímulo canónico del
    laboratorio (es el mismo que `sliding_pulser_wave` usa para la DNL), así que
    esta calibración es reproducible en la placa.
    """
    amps = rng.uniform(rango[0], rango[1], int(n))
    ev, amp_est, a_ver = corrida_aislada(amps, forma, modo, rng)
    cal = pu.calibrar(amp_est, a_ver)
    locus = {r: pu.locus_forma(amp_est, pu.razon_forma(ev, r)) for r in RAZONES}
    return cal, locus, ev, amp_est


def corrida_poisson(amps, t_idx, forma, modo, rng):
    """El MCA a tasa `lambda`: los eventos de todos los grupos, y los contadores.

    `n_arr` es cuántos pulsos verdaderos entró cada evento: 1 es limpio, >1 es
    apilado. Es lo que después permite separar eficiencia de rechazo. En el MCA2,
    `a_ver` es además la amplitud del pulso que disparó cada evento: el último
    arribo antes del disparo.

    Con varias ranuras no hay partición del eje, y cada grupo arranca con las
    ranuras libres. Los grupos se cortan en un hueco más largo que el pulso entero
    (y `max_ev` en el más largo que encuentre), así que esto casi no se nota.
    """
    trozos = []
    cnt = {}
    mca2 = _es_mca2(modo)
    for a, b in pu.agrupar(t_idx, forma.size):
        dat, o = pu.render(t_idx[a:b], amps[a:b], forma, rng=rng)
        ev, c = _eventos(dat, modo)
        m = ev['cerrado']
        ev = {k: v[m] for k, v in ev.items()}
        loc = t_idx[a:b] - o
        if mca2:
            ev['n_arr'] = r2.contar_arribos(ev, loc)
            j = np.searchsorted(loc, ev['i_par'], side='right') - 1
            ev['a_ver'] = np.where(j >= 0, amps[a:b][np.maximum(j, 0)], np.nan)
            for k, v in c.items():
                cnt[k] = cnt.get(k, 0) + v
        else:
            ev['n_arr'] = pu.contar_arribos(ev, loc)
        trozos.append(ev)
    if not trozos:
        return {}, cnt
    return {k: np.concatenate([t[k] for t in trozos]) for k in trozos[0]}, cnt


# Lo que un evento puede errar y seguir siendo bueno: 1 % de la amplitud, como en
# docs/mca/pruebas_banco_trapecios.md, con un piso de cuentas. Allá el error se
# mide sobre la señal sin ruido; acá hay ruido, y sin el piso un pulso chico medido
# por la forma corta (sigma ~ 1.4 cuentas con k = 8) contaría como contaminado.
ERROR_BUENO = 0.01
PISO_BUENO = 4.0


def es_bueno(amp, a_ver, cal):
    """Mide la amplitud verdadera del pulso que lo disparó."""
    a_est = (np.asarray(amp, dtype=float) - cal[1]) / cal[0]
    return np.abs(a_est - a_ver) <= np.maximum(ERROR_BUENO * a_ver, PISO_BUENO)


def _metricas_mca2(ev, cnt, amp, t_idx, cal, modo, h_ref, roi, can):
    """Lo que sólo tiene el MCA2: pérdida por ranuras, solapes, marcados y buenos.

    La carga de Erlang es con la tasa de DISPAROS, no de arribos: el disparo funde
    los pulsos cercanos, así que hay menos disparos que pulsos. `tau_ranura` es lo
    que una ventana ocupa su ranura sin esperar al publicador.
    """
    c = _armar(modo)['cfg']
    rt = max(int(t_idx[-1] - t_idx[0]), 1) / pu.FS_HZ
    tau = r2.tau_ranura(c) / pu.FS_HZ
    rho = cnt.get('cross', 0) / rt * tau
    nh = min(max(int(c['n_acc']), 1), r2.N_ACC_RTL)
    cross = max(cnt.get('cross', 0), 1)
    marcado = ev['forma'] == r2.MARCADO
    bueno = es_bueno(amp, ev['a_ver'], cal) & ~marcado
    out = dict(cross=int(cnt.get('cross', 0)), open=int(cnt.get('open', 0)),
               lost_active=int(cnt.get('lost_active', 0)),
               lost_busy=int(cnt.get('lost_busy', 0)),
               tasa_disparos=cnt.get('cross', 0) / rt,
               frac_perdidos=(cnt.get('cross', 0) - cnt.get('open', 0)) / cross,
               rho=float(rho), erlang=float(r2.erlang_b(nh, rho)),
               frac_solape=float(ev['apilado'].mean()) if ev['apilado'].size else 0.0,
               n_marcados=int(marcado.sum()),
               frac_marcados=float(marcado.mean()) if marcado.size else 0.0,
               n_buenos=int(bueno.sum()), tasa_buenos=float(bueno.sum() / rt),
               frac_buenos=float(bueno.sum() / max(int((~marcado).sum()), 1)))
    h_sol = pu.histograma(can[~ev['apilado'] & ~marcado], N_CANALES)
    for p in roi['picos']:
        out[f'm{p}_solape'] = pu.metricas(h_sol, h_ref, p, roi['semi_ancho'], roi['tope'])
    return out, h_sol


def una_combinacion(espectro, modo, tasas, n_ev, semilla, forma, verbose=True):
    """Todo el barrido de tasas para un espectro y una configuración."""
    roi = ESPECTROS[espectro]
    mca2 = _es_mca2(modo)
    rng = np.random.default_rng(semilla)

    # --- 1. calibración con pulser deslizante (ganancia + lugar geométrico) --
    cal, locus, ev_cal, amp_cal = calibracion_pulser(forma, modo, rng)
    razon_cal = {r: pu.razon_forma(ev_cal, r) for r in RAZONES}

    # --- 2. referencia: el MISMO espectro fuente, con los pulsos aislados ----
    amps_ref = pu.sortear_amplitudes(n_ev, espectro, rng)
    ev_ref, amp_ref, _ = corrida_aislada(amps_ref, forma, modo, rng)
    L0 = float(ev_ref['largo'].mean())

    h_ver = pu.histograma(pu.a_canal(amps_ref, (1.0, 0.0), n_canales=N_CANALES),
                          N_CANALES)
    h_ref = pu.histograma(pu.a_canal(amp_ref, cal, n_canales=N_CANALES), N_CANALES)

    if verbose:
        d = 100 * (locus['q_pico'][1][-1] / locus['q_pico'][1][0] - 1)
        print(f'  pulser: {amp_cal.size} eventos entre {A_PULSER[0]:.0f} y '
              f'{A_PULSER[1]:.0f} cuentas, ganancia {cal[0]:.3f}')
        print(f'  deriva de Q/pico en todo el rango: {d:+.1f} %')
        print(f'  referencia: {amp_ref.size} eventos de {n_ev}, ventana '
              f'{L0:.0f} muestras ({L0/pu.FS_HZ*1e6:.2f} us)')

    # --- barrido ------------------------------------------------------------
    filas, hists, mapas = [], {}, {}
    for tasa in tasas:
        t0 = time.perf_counter()
        amps = pu.sortear_amplitudes(n_ev, espectro, rng)
        t_idx = pu.arribos_poisson(n_ev, tasa, rng=rng)
        ev, cnt = corrida_poisson(amps, t_idx, forma, modo, rng)
        extra, h_sol = {}, None
        if mca2:
            # Los marcados caen en el canal 0: el espectro se lee sin ellos.
            amp = _amplitud(ev, modo)
            can = pu.a_canal(amp, cal, n_canales=N_CANALES)
            extra, h_sol = _metricas_mca2(ev, cnt, amp, t_idx, cal, modo, h_ref, roi, can)
            n_det = int(amp.size)
            s = ev['forma'] != r2.MARCADO
            ev = {k: v[s] for k, v in ev.items()}
            amp, can = amp[s], can[s]
        else:
            amp = pu.amplitud(ev, modo)
            can = pu.a_canal(amp, cal, n_canales=N_CANALES)
            n_det = int(amp.size)
        h_med = pu.histograma(can, N_CANALES)

        limpio = ev['n_arr'] <= 1
        base = dict(tasa=float(tasa), n_gen=int(n_ev), n_det=n_det,
                    frac_limpios=float(limpio.mean()),
                    frac_rtl_apilado=float(ev['apilado'].mean()),
                    largo_medio=float(ev['largo'].mean()), **extra)
        for p in roi['picos']:
            base[f'm{p}'] = pu.metricas(h_med, h_ref, p, roi['semi_ancho'],
                                        roi['tope'])

        # --- cortes por factor de forma ------------------------------------
        h_cortes = np.zeros((len(RAZONES), len(KS), N_CANALES), dtype=np.int64)
        cortes = []
        for ir, r in enumerate(RAZONES):
            razon = pu.razon_forma(ev, r)
            for ik, k in enumerate(KS):
                ok = pu.aplicar_corte(amp, razon, locus[r], k=k)
                h_cortes[ir, ik] = pu.histograma(can[ok], N_CANALES)
                fila = dict(razon=r, k=float(k),
                            eficiencia=float(ok[limpio].mean()),
                            rechazo=float(1.0 - ok[~limpio].mean())
                                    if (~limpio).any() else float('nan'),
                            n=int(ok.sum()))
                for p in roi['picos']:
                    fila[f'm{p}'] = pu.metricas(h_cortes[ir, ik], h_ref, p,
                                                roi['semi_ancho'], roi['tope'])
                cortes.append(fila)
        base['cortes'] = cortes
        filas.append(base)

        clave = f'{espectro}_modo{modo}_{tasa:.0f}'
        hists[clave] = dict(h_med=h_med, h_cortes=h_cortes)
        if h_sol is not None:
            hists[clave]['h_solape'] = h_sol
        # Muestra de eventos para el mapa 2D. Se guarda la tasa más cercana a
        # 100 kcps: suficientemente alta para que la población apilada se vea,
        # suficientemente baja para que la limpia siga siendo mayoría.
        if tasa == min(tasas, key=lambda t: abs(t - 1e5)):
            s = slice(None, 60_000)
            mapas[clave] = dict(amp=amp[s], n_arr=ev['n_arr'][s],
                                **{f'r_{r}': pu.razon_forma(ev, r)[s]
                                   for r in RAZONES})
        if verbose:
            p0 = roi['picos'][0]
            m = base[f'm{p0}']
            print(f'  {tasa:8.0f} cps: {amp.size:6d} ev, limpios '
                  f'{100*base["frac_limpios"]:5.1f} %, área {m["area_rel"]:.3f}, '
                  f'corrim {m["corrimiento"]:+6.1f} can, continuo '
                  f'{100*m["continuo"]:5.2f} %, L1 {m["l1"]:.3f}'
                  + (f', perdidos {100*base["frac_perdidos"]:5.1f} % (Erlang '
                     f'{100*base["erlang"]:5.1f} %), buenos '
                     f'{base["tasa_buenos"]/1e3:6.1f} kcps' if mca2 else '')
                  + f'   [{time.perf_counter()-t0:.1f} s]')

    return dict(h_ver=h_ver, h_ref=h_ref, hists=hists, mapas=mapas,
                filas=filas, cal=cal, L0=L0, locus=locus,
                amp_cal=amp_cal, razon_cal=razon_cal)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--espectro', default='ambos',
                    choices=['linea', 'realista', 'ambos'])
    ap.add_argument('--mapa', default='MCA2', choices=['MCA2', 'MCA1'])
    ap.add_argument('--modo', default=None,
                    help='MCA2: configuraciones separadas por comas '
                         f'({",".join(CONFIGS_MCA2)}); MCA1: 0 o 1. Por defecto, todas')
    ap.add_argument('--tasas', default=None)
    ap.add_argument('--n-eventos', type=int, default=50_000)
    ap.add_argument('--semilla', type=int, default=0)
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    espectros = ['linea', 'realista'] if a.espectro == 'ambos' else [a.espectro]
    if a.mapa == 'MCA1':
        modos = [0, 1] if a.modo in (None, 'ambos') else [int(x) for x in a.modo.split(',')]
    else:
        modos = list(CONFIGS_MCA2) if a.modo is None else a.modo.split(',')
        malos = set(modos) - set(CONFIGS_MCA2)
        if malos:
            ap.error(f'configuraciones desconocidas: {sorted(malos)}')
    defecto = TASAS_MCA2 if a.mapa == 'MCA2' else TASAS
    tasas = [float(x) for x in a.tasas.split(',')] if a.tasas else list(defecto)

    out = a.out or os.path.join(_RAIZ, 'datos',
                                time.strftime('pileup_%Y%m%d_%H%M%S'))
    os.makedirs(out, exist_ok=True)

    forma_campana, info = pu.forma_referencia()
    print(f'forma: FWHM {info["fwhm_pts"]:.0f} muestras '
          f'({info["fwhm_pts"]/pu.FS_HZ*1e6:.2f} us), cola tau {info["tau"]:.0f}, '
          f'pico en {info["i_pico"]}, template {info["n"]}')
    print(f'salida: {out}\n')

    resumen = dict(mapa=a.mapa, forma=info, n_eventos=a.n_eventos, semilla=a.semilla,
                   tasas=tasas, razones=list(RAZONES), ks=list(KS),
                   n_canales=N_CANALES, cfg_modo0=pu.CFG_MODO0,
                   cfg_modo1=pu.CFG_MODO1, q_shift=pu.Q_SHIFT,
                   sigma_ruido=pu.SIGMA_RUIDO, espectros={}, combinaciones=[])
    if a.mapa == 'MCA2':
        resumen['configs'] = {
            m: dict(etiqueta=_armar(m)['etiqueta'], estimador=_armar(m)['estimador'],
                    cfg=_armar(m)['cfg'], tau_ranura=r2.tau_ranura(_armar(m)['cfg']))
            for m in modos}

    t_ini = time.perf_counter()
    for esp in espectros:
        resumen['espectros'][esp] = ESPECTROS[esp]
        for im, modo in enumerate(modos):
            if a.mapa == 'MCA2':
                print(f'=== espectro {esp}, {modo}: {_armar(modo)["etiqueta"]} ===')
                forma = _armar(modo)['forma']
                semilla = a.semilla + 100 * im
            else:
                print(f'=== espectro {esp}, modo {modo} '
                      f'({"histéresis" if modo == 0 else "compuertas fijas"}) ===')
                forma = forma_campana
                semilla = a.semilla + 100 * modo
            r = una_combinacion(esp, modo, tasas, a.n_eventos, semilla, forma)
            base = f'{esp}_modo{modo}'
            guardar = dict(h_ver=r['h_ver'], h_ref=r['h_ref'],
                           tasas=np.array(tasas), ks=np.array(KS),
                           cal=np.array(r['cal']), L0=np.array(r['L0']),
                           amp_cal=r['amp_cal'])
            for rz in RAZONES:
                guardar[f'locus_{rz}'] = np.stack(r['locus'][rz])
                guardar[f'razon_cal_{rz}'] = r['razon_cal'][rz]
            guardar['h_med'] = np.stack([r['hists'][f'{base}_{t:.0f}']['h_med']
                                         for t in tasas])
            guardar['h_cortes'] = np.stack(
                [r['hists'][f'{base}_{t:.0f}']['h_cortes'] for t in tasas])
            if a.mapa == 'MCA2':
                guardar['h_solape'] = np.stack(
                    [r['hists'][f'{base}_{t:.0f}']['h_solape'] for t in tasas])
            for clave, mp in r['mapas'].items():
                for kk, vv in mp.items():
                    guardar[f'mapa_{kk}'] = vv
                guardar['mapa_tasa'] = np.array(float(clave.rsplit('_', 1)[1]))
            np.savez_compressed(os.path.join(out, f'{base}.npz'), **guardar)
            print(f'  guardado en {base}.npz\n')

            resumen['combinaciones'].append(
                dict(espectro=esp, modo=modo, cal=list(r['cal']), L0=r['L0'],
                     filas=r['filas']))

    with open(os.path.join(out, 'resumen.json'), 'w') as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False, default=float)
    print(f'listo en {time.perf_counter()-t_ini:.0f} s -> {out}')
    print(f'ahora: make montecarlo-figuras DIR={out}')
    return out


if __name__ == '__main__':
    main()
