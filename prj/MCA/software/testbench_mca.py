#!/usr/bin/env python3
"""Suite de caracterización del Analizador Multicanal (MCA).

Se corre EN LA PITAYA, con el bitstream `mca_red_pitaya.bit` cargado y el Rigol
DG4162 conectado por USB alimentando IN1 (o IN2).

Cada función cierra una fila de la tabla de parámetros a caracterizar de un MCA:

    eje de amplitud   ganancia de conversión, INL, DNL, offset de cero
    resolución        contribución de ruido electrónico, jitter de muestreo
    tasa              tiempo muerto y su modelo, throughput, live time,
                      corrimiento del centroide con la tasa
    umbral            LLD / piso de ruido, curva S de eficiencia
    forma             FOM y su dependencia con la energía

División de responsabilidades: el driver y los helpers de análisis puros están
en mca_utils.py; acá va sólo lo que necesita hardware. Todas las funciones
devuelven los datos CRUDOS además del resultado, para poder re-graficar y
re-analizar sin volver a medir.

Uso:
    python3 testbench_mca.py --list
    python3 testbench_mca.py single_peak
    python3 testbench_mca.py all --outdir datos/mca_2026-08-08
"""

import argparse
import os
import sys
import time

import numpy as np

import mca_utils as mu
from mca_utils import MCA
import rigol_dg4162 as rg


# =============================================================================
# Infraestructura
# =============================================================================

# Ancho de pulso por default de TODOS los estimulos ARB, en segundos.
#
# Antes el ancho no era un parametro: `set_arb` estira la forma completa sobre
# el periodo de repeticion, asi que con 128 puntos a 2 kHz cada punto duraba
# ~3.9 us y el pulso terminaba durando ~336 us = 42000 muestras a 125 MSPS.
# Eso obligaba a maxlen=60000 y contaminaba tiempo muerto, apilamiento y
# par-pulso. `rg.pulse_train_wave()` invierte la relacion: se le pide el ancho
# en segundos y devuelve la frecuencia a la que hay que aplicar la forma.
PULSE_WIDTH_S = 2e-6

# maxlen coherente con PULSE_WIDTH_S: un pulso de 2 us de FWHM ocupa ~1000
# muestras a 125 MSPS contando la cola, asi que 4096 deja margen de sobra sin
# tragarse apilamientos. OJO: si se cambia PULSE_WIDTH_S hay que recalibrar
# esto y `bl_k` (ver sweep_baseline_k).
DEFAULT_CFG = dict(thr=100, hyst=40, baseline=0, bl_auto=True, bl_k=12,
                   bl_holdoff=64, maxlen=4096, tail_dly=8, amp_src=0,
                   q_shift=0, h_shift=0, h2_shift=7, dec=1, channel=0)


def connect(channel=0):
    """Abre el MCA y el generador. Falla temprano y con mensaje claro."""
    mca = MCA.open()
    info = mca.identify()
    gen = rg.RigolDG4162.usb()
    print(f'generador: {gen.id}')
    gen.reset()
    return mca, gen, info


def _save(outdir, name, **arrays):
    if not outdir:
        return None
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f'{name}.npz')
    np.savez_compressed(path, **arrays)
    print(f'  guardado en {path}')
    return path


def _apply_arb(gen, wave, ch, freq_hz, amp_vpp, offset_v, settle_s=0.3):
    gen.load_arb(wave, ch=ch)
    gen.set_arb(ch=ch, freq_hz=freq_hz, amp_vpp=amp_vpp, offset_v=offset_v)
    gen.output(ch, True)
    time.sleep(settle_s)


def _pulse_train(gen, ch, rate_hz, amp_vpp, width_s=None, offset_v=None,
                 settle_s=0.3, verbose=True, **kw):
    """Arma y aplica un tren de pulsos de ancho `width_s` a `rate_hz`.

    Es el reemplazo de `detector_pulse(128, ...) + set_arb(freq=rate)`: acá el
    ancho del pulso está fijado en segundos y la frecuencia de repetición sale
    despejada. `kw` va a `rg.pulse_train_wave` (amp_range, tau_choices, seed...).

    Devuelve el `info` de la geometría, que dice cuántos pulsos distintos entran
    por forma — dato que hace falta para interpretar la DNL y la FOM.
    """
    width_s = PULSE_WIDTH_S if width_s is None else width_s
    wave, freq, info = rg.pulse_train_wave(width_s, rate_hz, **kw)
    if verbose:
        print(f'  estímulo: {info["n_pulses"]} pulso(s)/forma de '
              f'{width_s*1e6:g} us FWHM a {rate_hz:g} Hz '
              f'(forma a {freq:.1f} Hz, {info["srate_sa_s"]/1e6:.0f} MSa/s, '
              f'{info["fwhm_pts"]:.0f} pts/pulso)')
    offset_v = amp_vpp / 2 if offset_v is None else offset_v
    _apply_arb(gen, wave, ch, freq, amp_vpp, offset_v, settle_s=settle_s)
    return info


def _acquire(mca, seconds):
    spec, m2d, cnt = mca.acquire(seconds)
    # OJO con la normalizacion: `dropped` suma los eventos que llegaron con el
    # extractor OCUPADO (que nunca entraron a `total`) mas los descartes del
    # barrido de borrado (que si estan en `total`). Compararlo contra `total` da
    # porcentajes de mas del 100% -- fue lo que invalido el test de par-pulso.
    # El denominador correcto es total + dropped: todo lo que llego a la entrada.
    llegados = max(cnt['total'] + cnt['dropped'], 1)
    if cnt['dropped'] / llegados > 0.01:
        print(f"  AVISO: {cnt['dropped']} de {llegados} eventos perdidos por "
              f"extractor ocupado ({100*cnt['dropped']/llegados:.1f}% de los "
              f"que llegaron)")
    if cnt['pileup'] / max(cnt['total'], 1) > 0.05:
        print(f"  AVISO: {cnt['pileup']} eventos "
              f"({100*cnt['pileup']/max(cnt['total'],1):.0f}% de los contados) "
              f"cerraron por maxlen y NO entraron al histograma. "
              f"Subi cfg_maxlen o usa cfg_dec.")
    return spec, m2d, cnt


def _pico(spec, frac=0.15, min_w=8):
    """Ajusta el pico dominante del espectro: argmax + ventana + gaussiana.

    La ventana es proporcional al canal del pico (`frac`) y no fija, porque el
    ancho del pico crece con la energía; con una ventana fija el ajuste se come
    la cola a canal alto y se queda sin bins a canal bajo. El piso `min_w`
    cubre el caso de un pico cerca del canal 0.

    Devuelve el dict de `mu.gauss_fit_peak` (con NaN y `empty=True` si el
    espectro está vacío, que es un resultado legítimo: umbral mal puesto,
    generador apagado, todo rechazado).
    """
    spec = np.asarray(spec)
    if not spec.any():
        return {'centroid': float('nan'), 'sigma': float('nan'),
                'fwhm': float('nan'), 'area': 0.0,
                'resolution_pct': float('nan'), 'empty': True}
    pk = int(np.argmax(spec))
    w = max(min_w, int(frac * pk))
    return mu.gauss_fit_peak(spec, max(0, pk - w), min(len(spec), pk + w))


# =============================================================================
# 1. Pico único — contribución de ruido electrónico
# =============================================================================

def test_single_peak(mca, gen, ch=1, seconds=10.0, amp_vpp=0.5, rate_hz=2e3,
                     width_s=None, outdir=None, **cfg):
    """FWHM del pico de un pulser de amplitud fija.

    Ese ancho ES la contribución de la cadena electrónica: se resta en
    cuadratura del FWHM total para separar detector de electrónica. Es la
    medición de referencia contra la que se comparan todas las demás.
    """
    print('\n=== pico único (ruido electrónico) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)

    _pulse_train(gen, ch, rate_hz, amp_vpp, width_s)

    spec, _, cnt = _acquire(mca, seconds)
    gen.output(ch, False)

    fit = _pico(spec)
    print(f"  centroide {fit['centroid']:.1f} canales   FWHM {fit['fwhm']:.2f}   "
          f"resolución {fit['resolution_pct']:.2f}%")
    print(f"  cuentas: total {cnt['total']}, aceptadas {cnt['accepted']}, "
          f"tasa {cnt['total']/max(cnt['realtime_s'],1e-9):.0f} cps")
    _save(outdir, 'single_peak', spec=spec, **{f'cnt_{k}': v for k, v in cnt.items()})
    return {'fit': fit, 'counters': cnt, 'spectrum': spec}


# =============================================================================
# 2. Barrido de amplitud — ganancia, INL, offset de cero
# =============================================================================

def sweep_amplitude(mca, gen, ch=1, amps=None, seconds=4.0, rate_hz=2e3,
                    width_s=None, ida_y_vuelta=True, outdir=None, **cfg):
    """Centroide vs amplitud del generador: ganancia de conversión e INL.

    La INL es el residuo del ajuste lineal en % de fondo de escala. Un MCA
    decente está por debajo de ±0.05% FS.

    **La INL medida NO es la del MCA solo**: incluye la exactitud de amplitud
    del DG4162, que en la campaña anterior no se podía separar del 0.501 % FS
    reportado. Con `ida_y_vuelta=True` (default) cada amplitud se mide dos
    veces, subiendo y bajando, y se compara el residuo de las dos pasadas:

      - si los dos residuos COINCIDEN, el desvío es SISTEMÁTICO (o del
        generador, que repite su error para cada consigna, o del ADC). El
        número es real, pero sigue siendo la suma de los dos.
      - si NO coinciden, lo que domina es la ESTADÍSTICA del ajuste del
        centroide, y la "INL" no es más que el ruido de la medición.

    Es la única separación que se puede hacer sin una referencia de amplitud
    externa mejor que el propio generador; distinguir generador de ADC pide un
    patrón de tensión trazable.
    """
    print('\n=== barrido de amplitud (ganancia / INL) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    amps = np.linspace(0.1, 1.0, 20) if amps is None else np.asarray(amps)

    width_s = PULSE_WIDTH_S if width_s is None else width_s
    wave, freq, info = rg.pulse_train_wave(width_s, rate_hz)
    print(f'  estímulo: {width_s*1e6:g} us FWHM a {rate_hz:g} Hz '
          f'({info["n_pulses"]} pulso(s)/forma a {freq:.1f} Hz)')
    gen.load_arb(wave, ch=ch)

    def _medir(a):
        gen.set_arb(ch=ch, freq_hz=freq, amp_vpp=float(a), offset_v=float(a) / 2)
        gen.output(ch, True)
        time.sleep(0.3)
        spec, _, _ = _acquire(mca, seconds)
        f = _pico(spec)
        return f['centroid'], f['fwhm']

    centroids, fwhms = [], []
    for a in amps:
        cen, fw = _medir(a)
        centroids.append(cen)
        fwhms.append(fw)
        print(f'  {a:.3f} Vpp -> canal {cen:8.1f}  FWHM {fw:.2f}')

    centroids = np.array(centroids)
    a_fit, b_fit, resid, inl = mu.energy_calibration(centroids, amps)

    # Segunda pasada, en orden inverso: mismo estímulo, mismo instrumento.
    resid2 = None
    if ida_y_vuelta:
        print('  segunda pasada (bajando) para separar sistemático de ruido...')
        cen2 = []
        for a in amps[::-1]:
            c2, _ = _medir(a)
            cen2.append(c2)
        cen2 = np.array(cen2[::-1])
        _, _, resid2, inl2 = mu.energy_calibration(cen2, amps)
    gen.output(ch, False)

    print(f'  ganancia {a_fit:.1f} canales/Vpp   offset de cero {b_fit:.1f} canales')
    print(f'  INL {inl:.3f}% FS')

    veredicto = None
    if resid2 is not None:
        ok = np.isfinite(resid) & np.isfinite(resid2)
        if ok.sum() >= 3:
            # Correlación de los dos residuos: 1 = perfectamente repetible.
            r = float(np.corrcoef(resid[ok], resid2[ok])[0, 1])
            disp = float(np.std(resid[ok] - resid2[ok]))
            amp_r = float(np.std(resid[ok]))
            print(f'  vuelta: INL {inl2:.3f}% FS   correlación de residuos '
                  f'{r:+.2f}   dispersión entre pasadas {disp:.2f} canales '
                  f'(residuo {amp_r:.2f})')
            if r > 0.7:
                veredicto = ('sistemático: el residuo se repite entre pasadas, '
                             'así que la INL es real — pero es la del conjunto '
                             'generador+ADC, no la del MCA solo')
            elif disp > amp_r:
                veredicto = ('ruido: el residuo NO se repite; la "INL" es la '
                             'estadística del ajuste del centroide. Subí el '
                             'tiempo por punto antes de reportarla')
            else:
                veredicto = 'mezcla de sistemático y estadística; subí el tiempo por punto'
            print(f'  => {veredicto}')

    _save(outdir, 'sweep_amplitude', amps=amps, centroids=centroids,
          fwhms=np.array(fwhms), resid=resid,
          **({'resid_vuelta': resid2} if resid2 is not None else {}))
    return {'amps': amps, 'centroids': centroids, 'fwhms': np.array(fwhms),
            'gain': a_fit, 'offset': b_fit, 'inl_pct_fs': inl, 'resid': resid,
            'resid_vuelta': resid2, 'veredicto': veredicto}


# =============================================================================
# 2b. INL vs familia de forma — robustez de la determinación de amplitud
# =============================================================================

# Orden del barrido: la de REFERENCIA primero. `cr_rc` es la semi-gaussiana
# clásica, la forma más parecida al estímulo con el que se midió la campaña
# publicada, así que su ganancia y su INL son la comparación de cordura de todo
# el barrido. Las demás van de más asimétrica a más simétrica.
FAMILIAS_KNOLL = ('cr_rc', 'cr', 'cr_rc4', 'triangular', 'trapezoidal', 'bipolar')

# amp_src del MCA por estimador (registro cfg_amp_src, bit 0).
_AMP_SRC = {'pico': 0, 'carga': 1}


def sweep_formas_inl(mca, gen, ch=1, familias=None, amps=None, seconds=3.0,
                     rate_hz=2e3, width_s=None, estimadores=('pico', 'carga'),
                     ida_y_vuelta=True, target_channel=8000, outdir=None, **cfg):
    """La curva de INL medida con VARIAS familias de forma de pulso.

    `sweep_amplitude` mide la INL con una sola forma, y su pasada de ida y
    vuelta alcanza para decir que el residuo es SISTEMÁTICO — pero no de quién
    es. Este barrido agrega el eje que falta repitiendo la misma curva con las
    formas de amplificador de conformado de Knoll (ver `rg.FORMAS_KNOLL`), todas
    con el MISMO FWHM y la misma altura de pico, de modo que entre familia y
    familia lo único que cambia es la forma.

    Sirve para dos cosas:

    1. **Robustez.** Si la amplitud que reporta el MCA cambia al cambiar la
       forma a igual altura de pico, ese error es de la cadena de medición y no
       del estímulo. Es la pregunta directa.

    2. **Atribución.** El error de consigna de amplitud del DG4162 es COMÚN a
       todas las formas: `load_arb` normaliza cada forma a pico 1.0 y `set_arb`
       la escala por `amp_vpp`, así que el mismo lazo de amplitud del
       instrumento actúa idéntico sobre todas. Entonces:

           residuo COMÚN a todas las familias  = generador + INL estática del ADC
           residuo DIFERENCIAL entre familias  = cadena de medición, y sólo ella

       Es lo más lejos que se llega sin un patrón de tensión trazable. NO separa
       generador de INL estática del ADC (los dos son común-modo), pero sí acota
       la parte que depende de la forma, que es la que importa acá.

    Se mide con los dos estimadores (`estimadores=('pico','carga')`) porque la
    expectativa es opuesta: el de pico lee el ápice y debería ser casi
    insensible a la forma; el de carga integra, así que su ganancia escala con
    el factor de forma (área/pico) y va a cambiar mucho — de forma PREDECIBLE,
    lo que sirve de verificación cruzada (ver el gráfico pico-vs-carga).

    Devuelve el dict de datos crudos; el análisis es `analizar_formas()`.
    """
    print('\n=== INL vs familia de forma (robustez de la amplitud) ===')
    c = {**DEFAULT_CFG, **cfg}
    familias = FAMILIAS_KNOLL if familias is None else tuple(familias)
    # Validar los nombres ANTES de conectar nada: un typo en --familias o en
    # --estimadores tiene que fallar en el segundo cero, no a los quince
    # minutos de campaña.
    malas = [f for f in familias if f not in rg.FORMAS_KNOLL]
    if malas:
        raise ValueError(f'familias desconocidas: {malas}. '
                         f'Conocidas: {sorted(rg.FORMAS_KNOLL)}')
    malos = [e for e in estimadores if e not in _AMP_SRC]
    if malos:
        raise ValueError(f'estimadores desconocidos: {malos}. '
                         f'Conocidos: {sorted(_AMP_SRC)}')
    amps = np.linspace(0.1, 1.0, 12) if amps is None else np.asarray(amps, dtype=float)
    width_s = PULSE_WIDTH_S if width_s is None else width_s
    a_max = float(amps.max())

    def _set_amp(a):
        # freq_hz = rate_hz porque todas las formas se arman con n_pulses=1.
        gen.set_arb(ch=ch, freq_hz=rate_hz, amp_vpp=float(a), offset_v=float(a) / 2)
        gen.output(ch, True)
        time.sleep(0.3)

    def _centroide(a):
        _set_amp(a)
        spec, _, _ = _acquire(mca, seconds)
        f = _pico(spec)
        return f['centroid'], f['fwhm']

    def _prevuelo(fam):
        """¿Esta familia se mide bien con la configuración actual?

        Es la guarda contra el modo de falla documentado en mca_utils: si la
        constante del seguidor de línea de base no es mucho más larga que el
        pulso, el seguidor se COME el pulso y no se detecta ningún evento. Con
        formas de cola larga (`cr`) o con el lóbulo negativo de la bipolar el
        riesgo es real, y una curva medida sobre un espectro casi vacío sale
        como una INL enorme sin ninguna advertencia.
        """
        mca.configure(**{**c, 'amp_src': 0, 'q_shift': 0})
        _set_amp(a_max)
        spec, _, cnt = _acquire(mca, 1.0)
        esperados = rate_hz * max(cnt['realtime_s'], 1e-9)
        frac = cnt['total'] / max(esperados, 1e-9)
        pileup = cnt['pileup'] / max(cnt['total'], 1)
        ok = bool(spec.any()) and 0.9 <= frac <= 1.1 and pileup < 0.05
        print(f'  pre-vuelo: {cnt["total"]} eventos = {100*frac:.0f}% de los '
              f'esperados, apilamiento {100*pileup:.1f}%'
              f'{"" if ok else "   <-- NO MEDIBLE"}')
        return ok, frac, pileup

    guardar = {'amps': amps, 'familias': np.array(familias),
               'estimadores': np.array(estimadores),
               'h_shift': np.array(c['h_shift']),
               'width_s': np.array(width_s), 'rate_hz': np.array(rate_hz),
               'seconds': np.array(seconds)}
    res = {'amps': amps, 'familias': familias, 'estimadores': estimadores,
           'h_shift': c['h_shift'], 'por_forma': {}}

    for fam in familias:
        print(f'\n--- familia {fam} ---')
        try:
            # n_pulses=1 es lo que fija freq_hz y la tasa de muestreo del ARB
            # iguales para todas las familias: sin eso cambiaría la forma Y la
            # frecuencia a la vez, y la comparación no diría nada.
            wave, freq, info = rg.shaped_train_wave(fam, width_s, rate_hz,
                                                    n_pulses=1)
        except ValueError as e:
            print(f'  no se puede armar el estímulo: {e}')
            guardar[f'ok_{fam}'] = np.array(False)
            continue
        print(f'  estímulo: {width_s*1e6:g} us FWHM a {freq:.0f} Hz, '
              f'{info["srate_sa_s"]/1e6:.1f} MSa/s, factor de forma '
              f'{info["factor_forma"]:.3f}'
              + ('' if info['area_pos_frac'] > 0.99 else
                 f', área positiva {100*info["area_pos_frac"]:.0f}%'))
        gen.load_arb(wave, ch=ch)

        ok, frac, pileup = _prevuelo(fam)
        guardar[f'ok_{fam}'] = np.array(ok)
        guardar[f'prevuelo_{fam}'] = np.array([frac, pileup])
        guardar[f'factor_forma_{fam}'] = np.array(info['factor_forma'])
        guardar[f'area_pos_frac_{fam}'] = np.array(info['area_pos_frac'])
        if not ok:
            print('  se saltea esta familia (el resto de la campaña sigue)')
            continue

        for est in estimadores:
            qs = 0
            if _AMP_SRC[est] == 1:
                # Q_tot escala con el factor de forma, así que el
                # desplazamiento hay que re-elegirlo POR FAMILIA: con uno fijo
                # las familias compactas quedarían comprimidas en pocos canales
                # y su FWHM cuantizado al bin. Se autoescala a la amplitud
                # máxima para que el barrido entero entre en el eje.
                _set_amp(a_max)
                qs = mca.autoscale_q_shift(target_channel=target_channel,
                                           **{**c, 'amp_src': 1, 'q_shift': 0})
                if qs is None:
                    print(f'  [{est}] sin eventos al autoescalar; se saltea')
                    continue
            mca.configure(**{**c, 'amp_src': _AMP_SRC[est], 'q_shift': qs})

            cen, fw = [], []
            for a in amps:
                x, y = _centroide(a)
                cen.append(x)
                fw.append(y)
            cen = np.array(cen)
            gain, off, resid, inl = mu.energy_calibration(cen, amps)

            resid2 = None
            if ida_y_vuelta:
                cen2 = np.array([_centroide(a)[0] for a in amps[::-1]])[::-1]
                _, _, resid2, _ = mu.energy_calibration(cen2, amps)

            piso = (float(np.nanstd(resid - resid2)) if resid2 is not None
                    else float('nan'))
            print(f'  [{est:5s}] q_shift={qs:2d}  ganancia {gain:9.1f} ch/Vpp  '
                  f'offset {off:+7.1f}  INL {inl:5.2f}% FS  '
                  f'({1e3*np.nanmax(np.abs(resid))/abs(gain):.2f} mV)  '
                  f'piso ida/vuelta {piso:.2f} ch')

            guardar[f'cen_{fam}_{est}'] = cen
            guardar[f'fwhm_{fam}_{est}'] = np.array(fw)
            guardar[f'resid_{fam}_{est}'] = resid
            guardar[f'gain_{fam}_{est}'] = np.array(gain)
            guardar[f'offset_{fam}_{est}'] = np.array(off)
            guardar[f'inl_{fam}_{est}'] = np.array(inl)
            guardar[f'qshift_{fam}_{est}'] = np.array(qs)
            if resid2 is not None:
                guardar[f'resid_vuelta_{fam}_{est}'] = resid2
            res['por_forma'][(fam, est)] = {
                'cen': cen, 'fwhm': np.array(fw), 'gain': gain, 'offset': off,
                'resid': resid, 'resid_vuelta': resid2, 'inl_pct_fs': inl,
                'q_shift': qs}

    # Réplica de cierre: la familia de referencia otra vez, al final de la
    # campaña. Acota la deriva sobre los ~20 minutos que dura todo, y es el
    # control nulo del análisis diferencial — dos medidas de la MISMA forma
    # tienen que dar diferencia ~0. Si la réplica se aparta más que el
    # diferencial entre familias, lo que se está midiendo es deriva.
    ref = familias[0]
    if guardar.get(f'ok_{ref}', np.array(False)) and 'pico' in estimadores:
        print(f'\n--- réplica de cierre ({ref}, pico) ---')
        wave, freq, _ = rg.shaped_train_wave(ref, width_s, rate_hz, n_pulses=1)
        gen.load_arb(wave, ch=ch)
        mca.configure(**{**c, 'amp_src': 0, 'q_shift': 0})
        cen_r = np.array([_centroide(a)[0] for a in amps])
        g_r, _, resid_r, inl_r = mu.energy_calibration(cen_r, amps)
        guardar['cen_replica'] = cen_r
        guardar['resid_replica'] = resid_r
        guardar['gain_replica'] = np.array(g_r)
        deriva = 1e3 * float(np.nanmax(np.abs(
            resid_r - guardar[f'resid_{ref}_pico']))) / abs(g_r)
        print(f'  ganancia {g_r:.1f} ch/Vpp (inicial '
              f'{float(guardar[f"gain_{ref}_pico"]):.1f}), INL {inl_r:.2f}% FS')
        print(f'  deriva sobre la campaña: {deriva:.2f} mV de residuo')

    gen.output(ch, False)
    _save(outdir, 'formas_inl', **guardar)
    res['npz'] = guardar
    return res


def analizar_formas(d):
    """Descompone los residuos en parte común (generador) y diferencial (MCA).

    `d` es el .npz de `sweep_formas_inl` (o su ruta). No toca hardware: se puede
    correr en la PC sobre una campaña ya medida.

    Todo se pasa a mV referidos a la consigna del generador (residuo en canales
    dividido por la ganancia de esa misma familia), que es la única unidad en la
    que las familias y los dos estimadores son comparables entre sí — las
    ganancias en canales/Vpp difieren en órdenes de magnitud entre pico y carga.
    """
    if isinstance(d, str):
        d = np.load(d)
    # Acepta tanto el NpzFile como el dict crudo que devuelve sweep_formas_inl,
    # para poder analizar sin pasar por el disco.
    claves = set(d.files) if hasattr(d, 'files') else set(d)
    familias = [str(x) for x in d['familias']]
    estimadores = [str(x) for x in d['estimadores']]
    amps = np.asarray(d['amps'], dtype=float)
    out = {'amps': amps.tolist(), 'por_estimador': {}}

    # Control nulo PRIMERO, porque es un piso del veredicto y no un apéndice: la
    # réplica de cierre re-mide la familia de referencia al final de la campaña,
    # así que su diferencia contra la medición inicial es lo que la deriva
    # produce SIN cambiar la forma. Un diferencial entre familias que no supere
    # esa deriva no se puede atribuir a la forma — y esto ya pasó en la primera
    # campaña medida, donde la deriva (0.43 mV) quedó del orden del diferencial
    # del estimador de pico (0.57 mV).
    ref = familias[0]
    deriva = float('nan')
    if 'resid_replica' in claves and f'resid_{ref}_pico' in claves:
        g = float(d['gain_replica'])
        deriva = 1e3 * float(np.nanmax(np.abs(
            np.asarray(d['resid_replica'])
            - np.asarray(d[f'resid_{ref}_pico'])))) / abs(g)
        out['deriva_replica_mv'] = deriva
        out['ganancia_replica_pct'] = 100.0 * (
            g / float(d[f'gain_{ref}_pico']) - 1.0)

    for est in estimadores:
        fams = [f for f in familias
                if f'resid_{f}_{est}' in claves and bool(d[f'ok_{f}'])]
        if len(fams) < 2:
            out['por_estimador'][est] = {'error': f'sólo {len(fams)} familia(s) '
                                         'medibles: no hay comparación posible'}
            continue

        gain = {f: float(d[f'gain_{f}_{est}']) for f in fams}
        # Ganancia FÍSICA: en canales la ganancia arrastra el desplazamiento de
        # binning, y `q_shift` se autoescala por familia — así que comparar
        # ganancias en canales/Vpp entre familias mide el autoescalado, no la
        # electrónica. Deshacer el desplazamiento deja cuentas de ADC por Vpp
        # (pico) o cuentas·muestra por Vpp (carga), que sí son comparables.
        shift = {f: 2.0 ** float(d[f'qshift_{f}_{est}'] if _AMP_SRC[est] == 1
                                 else d['h_shift']) for f in fams}
        g_fis = {f: gain[f] * shift[f] for f in fams}
        # Residuos en mV: canales / (canales por Vpp). El desplazamiento se
        # cancela solo acá (numerador y denominador están en la misma escala).
        R = np.vstack([1e3 * np.asarray(d[f'resid_{f}_{est}']) / gain[f]
                       for f in fams])

        # Descomposición común / diferencial.
        comun = np.nanmean(R, axis=0)
        dif = R - comun

        # Piso de ruido: dispersión entre la pasada de ida y la de vuelta. Todo
        # diferencial por debajo de esto es estadística del ajuste del
        # centroide, no una diferencia entre formas.
        piso = {}
        for i, f in enumerate(fams):
            k = f'resid_vuelta_{f}_{est}'
            piso[f] = (1e3 * float(np.nanstd(np.asarray(d[f'resid_{f}_{est}'])
                                             - np.asarray(d[k]))) / abs(gain[f])
                       if k in claves else float('nan'))
        piso_tipico = float(np.nanmedian(list(piso.values())))

        ref_e = fams[0]
        max_dif = float(np.nanmax(np.abs(dif)))
        max_comun = float(np.nanmax(np.abs(comun)))
        # El diferencial tiene que superar DOS pisos, no uno: la estadística del
        # ajuste del centroide (ida/vuelta, que es por punto) y la deriva de la
        # campaña (réplica de cierre, que es lenta y no la ve la ida y vuelta).
        piso_efectivo = float(np.nanmax([piso_tipico,
                                         deriva if np.isfinite(deriva) else 0.0]))

        # Correlación entre los residuos de cada par de familias. Si todas
        # correlacionan ~1, el residuo es común-modo: la INL no viene de cómo se
        # determina la amplitud sino del estímulo (o de la INL estática del ADC).
        with np.errstate(invalid='ignore'):
            corr = np.corrcoef(np.nan_to_num(R, nan=0.0))
        fuera = ~np.eye(len(fams), dtype=bool)
        corr_min = float(np.nanmin(corr[fuera])) if len(fams) > 1 else float('nan')

        quien = ('estadística del ajuste' if piso_tipico >= piso_efectivo
                 else 'deriva de la campaña (réplica de cierre)')
        if max_dif < piso_efectivo:
            veredicto = (
                f'la INL NO depende de la forma: el diferencial entre familias '
                f'({max_dif:.2f} mV) está por debajo del piso de {piso_efectivo:.2f} '
                f'mV que impone la {quien}. Los {max_comun:.2f} mV de residuo son '
                f'común-modo, o sea del generador y/o de la INL estática del ADC '
                f'— la determinación de amplitud es robusta frente a la forma.')
        elif max_dif < 3.0 * piso_efectivo:
            # Zona gris: supera el piso pero no por margen suficiente para
            # atribuirlo a la forma. Es el caso que se dio con el estimador de
            # pico en la primera campaña (0.57 mV de diferencial contra 0.43 mV
            # de deriva), y el veredicto anterior lo daba por bueno.
            veredicto = (
                f'la INL es común-modo ({max_comun:.2f} mV) dentro de lo que esta '
                f'campaña puede resolver: el diferencial entre familias '
                f'({max_dif:.2f} mV) supera el piso de {piso_efectivo:.2f} mV '
                f'({quien}) por sólo {max_dif/piso_efectivo:.1f}x, así que es una '
                f'COTA SUPERIOR de la dependencia con la forma, no una medición '
                f'de ella. Para bajar la cota hay que bajar la deriva: campaña '
                f'más corta, o familias intercaladas en vez de en bloque.')
        elif max_dif < 0.3 * max_comun:
            veredicto = (
                f'la INL es mayormente común-modo ({max_comun:.2f} mV) con una '
                f'componente dependiente de la forma de {max_dif:.2f} mV '
                f'({100*max_dif/max_comun:.0f}% del total, {max_dif/piso_efectivo:.1f}x '
                f'el piso de {piso_efectivo:.2f} mV impuesto por la {quien}). Esa '
                f'componente SÍ es de la cadena de medición.')
        else:
            veredicto = (
                f'la determinación de amplitud depende fuertemente de la forma: '
                f'el diferencial ({max_dif:.2f} mV) es comparable al residuo '
                f'total ({max_comun:.2f} mV) y supera {max_dif/piso_efectivo:.0f}x '
                f'el piso de {piso_efectivo:.2f} mV ({quien}). La INL medida con '
                f'una sola forma no es representativa.')

        out['por_estimador'][est] = {
            'familias': fams,
            'ganancia_ch_por_vpp': gain,
            'ganancia_fisica_por_vpp': g_fis,
            'ganancia_relativa': {f: g_fis[f] / g_fis[ref] for f in fams},
            'inl_pct_fs': {f: float(d[f'inl_{f}_{est}']) for f in fams},
            'inl_mv': {f: float(np.nanmax(np.abs(R[i])))
                       for i, f in enumerate(fams)},
            'fwhm_medio_ch': {f: float(np.nanmean(d[f'fwhm_{f}_{est}']))
                              for f in fams},
            'residuo_comun_max_mv': max_comun,
            'residuo_diferencial_max_mv': max_dif,
            'diferencial_por_familia_mv': {f: float(np.nanmax(np.abs(dif[i])))
                                           for i, f in enumerate(fams)},
            'piso_ida_vuelta_mv': piso,
            'piso_efectivo_mv': piso_efectivo,
            'piso_lo_impone': quien,
            'diferencial_sobre_piso': (max_dif / piso_efectivo
                                       if piso_efectivo > 0 else float('inf')),
            'correlacion_min_entre_familias': corr_min,
            'veredicto': veredicto,
        }

    # Pendiente medida del gráfico pico-vs-carga contra la predicha por la
    # geometría de la forma: es la verificación cruzada de que el eje de carga
    # está bien escalado. La comparación es de RELACIONES entre familias, no de
    # valores absolutos, porque el factor de forma es adimensional y la
    # pendiente medida arrastra el ancho del pulso y la ganancia del ADC.
    ff = {f: float(d[f'factor_forma_{f}']) for f in familias
          if f'factor_forma_{f}' in claves}
    pend = {}
    for f in familias:
        kp, kc = f'cen_{f}_pico', f'cen_{f}_carga'
        if kp in claves and kc in claves:
            x = np.asarray(d[kp]) * 2.0 ** float(d['h_shift'])
            y = np.asarray(d[kc]) * 2.0 ** float(d[f'qshift_{f}_carga'])
            m = np.isfinite(x) & np.isfinite(y)
            if m.sum() >= 2:
                pend[f] = float(np.polyfit(x[m], y[m], 1)[0])
    if pend and ff:
        r0 = familias[0] if familias[0] in pend else list(pend)[0]
        out['pico_vs_carga'] = {
            'pendiente_medida': pend,
            'factor_forma': {f: ff[f] for f in pend if f in ff},
            'pendiente_relativa': {f: pend[f] / pend[r0] for f in pend},
            'factor_forma_relativo': {f: ff[f] / ff[r0] for f in pend if f in ff},
        }

    return out


# =============================================================================
# 3. Sliding pulser — DNL
# =============================================================================

def test_dnl(mca, gen, ch=1, seconds=60.0, amp_vpp=1.0, rate_hz=50e3,
             width_s=None, mode='auto', reload_s=1.5, smooth=64,
             outdir=None, **cfg):
    """DNL: el espectro tiene que salir SUAVE, sin canales vacíos ni picos.

    El estímulo tiene que barrer la amplitud de forma CONTINUA. Una forma
    arbitraria cíclica no sirve: repite el mismo puñado de amplitudes para
    siempre y el espectro son líneas discretas — es lo que invalidó la medición
    anterior (467 % de "DNL", con 172 canales poblados y 40 vacíos
    intercalados). Dos vías, en orden de preferencia:

      mode='am'     modulación AM con la fuente de ruido interna del generador.
                    Es lo canónico: la amplitud varía de forma continua y no
                    cuesta tiempo de recarga.
      mode='reload' recarga el ARB con una semilla nueva cada `reload_s`,
                    acumulando en el MISMO histograma. Más lento (~0.6 s por
                    recarga) pero usa sólo comandos ya probados contra este
                    firmware.
      mode='auto'   intenta AM y cae a reload si el instrumento la rechaza
                    (precedente: `:DATA:CATenate` no existe en este firmware).

    Estadística: con N cuentas/canal el piso de Poisson es 1/sqrt(N), así que
    para resolver 1 % hacen falta >=10^4 cuentas por canal. La rutina lo estima
    ANTES de medir y avisa si el tiempo pedido no alcanza.
    """
    print('\n=== sliding pulser (DNL) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    width_s = PULSE_WIDTH_S if width_s is None else width_s

    usado = None
    if mode in ('auto', 'am'):
        # AM sobre un tren de amplitud FIJA: la variación la pone la modulación.
        try:
            _pulse_train(gen, ch, rate_hz, amp_vpp, width_s)
            gen.set_am_noise(ch=ch, depth_pct=90.0)
            usado = 'am'
            print('  modulación AM de ruido aceptada por el instrumento')
        except Exception as e:
            gen.set_mod_off(ch=ch)
            # Vaciar la cola: set_am_noise manda 5 comandos y este firmware los
            # rechaza TODOS, asi que quedan errores viejos que el proximo
            # assert_ok le achacaria a load_arb.
            viejos = gen.clear_errors()
            if mode == 'am':
                raise
            print(f'  el instrumento rechazó la modulación AM ({str(e)[:60]}); '
                  f'se usa la recarga del ARB')
            if viejos:
                print(f'  ({len(viejos)} errores de SCPI descartados de la cola)')
    if usado is None:
        usado = 'reload'

    n_canales = 1 << mca.h_aw
    n_amp_distintas = 0        # 0 = continuo (modulacion analogica)
    if usado == 'am':
        spec, _, cnt = _acquire(mca, seconds)
    else:
        # Semilla nueva por trozo: cada recarga trae otras amplitudes, y el
        # histograma acumula todas. Sin esto son siempre las mismas.
        info = _pulse_train(gen, ch, rate_hz, amp_vpp, width_s,
                            amp_range=(0.15, 0.95), seed=0)
        estado = {'k': 0}

        def _recargar(_k):
            estado['k'] += 1
            wave, freq, _ = rg.pulse_train_wave(width_s, rate_hz,
                                                amp_range=(0.15, 0.95),
                                                seed=estado['k'])
            gen.load_arb(wave, ch=ch, check_errors=False)
            gen.set_arb(ch=ch, freq_hz=freq, amp_vpp=amp_vpp,
                        offset_v=amp_vpp / 2)

        n_recargas = max(1, int(seconds / reload_s))
        n_amp_distintas = n_recargas * info['n_pulses']
        print(f'  {n_recargas} recargas x {info["n_pulses"]} pulsos = '
              f'~{n_amp_distintas} amplitudes distintas')
        spec, _, cnt = mca.acquire_chunks(seconds, reload_s, on_chunk=_recargar)
    gen.output(ch, False)
    gen.set_mod_off(ch=ch)

    nz = np.nonzero(spec)[0]
    if len(nz) < 16:
        print('  no hay suficientes canales poblados; subí el tiempo o el rango')
        return {'spectrum': spec, 'counters': cnt, 'modo': usado}
    # Ventana = la MESETA de la distribución, no los extremos. El estímulo
    # reparte la amplitud sobre un rango, pero en los bordes la densidad cae y
    # aparecen canales vacíos por falta de muestreo, no por DNL. Tomar el tramo
    # continuo más largo con cuentas por encima de la mitad de la mediana deja
    # la zona donde la estadística alcanza. (Mismo criterio que sweep_threshold:
    # la meseta es la referencia, no los extremos.)
    piso = 0.5 * float(np.median(spec[nz]))
    buenos = spec > piso
    mejor_lo, mejor_hi, cur_lo = 0, 0, None
    for i, b in enumerate(buenos):
        if b and cur_lo is None:
            cur_lo = i
        elif not b and cur_lo is not None:
            if i - cur_lo > mejor_hi - mejor_lo:
                mejor_lo, mejor_hi = cur_lo, i
            cur_lo = None
    if cur_lo is not None and len(buenos) - cur_lo > mejor_hi - mejor_lo:
        mejor_lo, mejor_hi = cur_lo, len(buenos)
    lo, hi = mejor_lo, mejor_hi
    if hi - lo < 16:
        print(f'  la meseta tiene sólo {hi-lo} canales; subí el tiempo o '
              f'ensanchá el rango de amplitudes')
        return {'spectrum': spec, 'counters': cnt, 'modo': usado}
    ancho = max(hi - lo, 1)
    media = float(spec[lo:hi].mean())
    vacios = int((spec[lo:hi] <= 0).sum())

    print(f'  ventana [{lo}, {hi}] de {n_canales} canales   '
          f'{media:.0f} cuentas/canal   {vacios} canales vacíos')
    if media > 0:
        tasa = cnt['total'] / max(cnt['realtime_s'], 1e-9)
        t_10k = 1e4 * ancho / max(tasa, 1e-9)
        print(f'  piso de Poisson {100/np.sqrt(media):.2f}%; para 10^4 '
              f'cuentas/canal hacen falta ~{t_10k:.0f} s a {tasa:.0f} cps')

    try:
        d = mu.dnl(spec, lo, hi, smooth=smooth)
    except ValueError as e:
        print(f'  MEDICIÓN INVÁLIDA: {e}')
        _save(outdir, 'dnl', spec=spec, lo=lo, hi=hi)
        return {'spectrum': spec, 'counters': cnt, 'modo': usado,
                'error': str(e), 'window': (lo, hi)}

    print(f"  DNL max {d['dnl_max_pct']:.2f}%   rms {d['dnl_rms_pct']:.2f}%   "
          f"(contra envolvente de {smooth} canales)")
    if media < 1e4:
        print(f"  AVISO: con {media:.0f} cuentas/canal el piso de Poisson es "
              f"{100/np.sqrt(media):.1f}%: la DNL medida está dominada por "
              "estadística, subí el tiempo de adquisición")

    # Piso por DISCRETIZACIÓN DEL ESTÍMULO. Es distinto del de Poisson y suele
    # ser el que manda: con `n_amp` amplitudes distintas repartidas sobre
    # `ancho` canales, cada canal recibe n_amp/ancho amplitudes y ese reparto
    # fluctúa como sqrt(n_amp/ancho). Ninguna cantidad de tiempo lo baja: hay
    # que aumentar el NÚMERO DE AMPLITUDES DISTINTAS.
    piso_est = float('nan')
    if n_amp_distintas:
        por_canal = n_amp_distintas / ancho
        piso_est = 100.0 / np.sqrt(max(por_canal, 1e-9))
        print(f"  piso por discretización del estímulo: {piso_est:.1f}% "
              f"({n_amp_distintas} amplitudes distintas / {ancho} canales = "
              f"{por_canal:.1f} por canal)")
        if d['dnl_rms_pct'] < 2.0 * piso_est:
            print(f"  => la DNL medida ({d['dnl_rms_pct']:.1f}%) NO es del MCA: "
                  f"está en el piso del estímulo. Es una COTA SUPERIOR. Para "
                  f"bajarla hacen falta ~{int(ancho * (100/1.0)**2):d} amplitudes "
                  f"distintas (para resolver 1%), inalcanzable recargando el "
                  f"ARB. Necesita modulación analógica de amplitud.")
    _save(outdir, 'dnl', spec=spec, dnl=d['dnl'], envelope=d['envelope'],
          lo=lo, hi=hi)
    return {'spectrum': spec, 'dnl': d, 'window': (lo, hi), 'modo': usado,
            'counters': cnt, 'n_amp_distintas': n_amp_distintas,
            'piso_estimulo_pct': piso_est}


# =============================================================================
# 4. Pico vs integral — jitter de muestreo
# =============================================================================

def compare_estimators(mca, gen, ch=1, seconds=10.0, amp_vpp=0.5, rate_hz=2e3,
                       widths_s=(0.5e-6, 1e-6, 2e-6, 4e-6), q_shift=None,
                       target_channel=8000, min_fwhm=3.0, outdir=None, **cfg):
    """FWHM con estimador de PICO vs de INTEGRAL, para varios tiempos de subida.

    Es EL experimento que justifica (o no) un eje de 16384 canales. Con la
    muestra de pico la amplitud sale de una sola muestra y el muestreo casi
    nunca cae en el máximo verdadero; ese error crece cuando el pulso es rápido
    (pocas muestras en el flanco). La integral promedia el ruido como sigma/√N
    y es inmune a ese jitter, así que la diferencia entre las dos curvas mide
    directamente la contribución instrumental.

    **El desplazamiento de la integral se auto-escala** (`q_shift=None`): con un
    valor fijo el pico integral queda comprimido en pocos canales, el FWHM se
    cuantiza al canal y el estimador parece mejor de lo que es. Se mide `Q_total`
    de un evento real y se despeja el desplazamiento que lleva el pico a
    `target_channel`, o sea a la MISMA escala que el estimador de pico. Si aun
    así el FWHM queda por debajo de `min_fwhm` canales, el punto se marca como
    no comparable en vez de reportar una mejora que es un artefacto.
    """
    print('\n=== pico vs integral (jitter de muestreo) ===')
    out = {'width_s': [], 'fwhm_peak': [], 'fwhm_int': [],
           'res_peak': [], 'res_int': [], 'q_shift': [], 'comparable': []}

    for wid in widths_s:
        _pulse_train(gen, ch, rate_hz, amp_vpp, wid)

        # Desplazamiento de la integral para este ancho: Q_total escala con el
        # ancho del pulso, asi que hay que re-elegirlo en cada punto.
        qs = q_shift
        if qs is None:
            qs = mca.autoscale_q_shift(target_channel=target_channel,
                                       **{**DEFAULT_CFG, **cfg,
                                          'amp_src': 1, 'q_shift': 0})
            if qs is None:
                print(f'  w={wid*1e6:g} us: no se detectan eventos; se saltea')
                continue

        res = {}
        for label, src, q in (('peak', 0, 0), ('int', 1, qs)):
            mca.configure(**{**DEFAULT_CFG, **cfg, 'amp_src': src, 'q_shift': q})
            spec, _, _ = _acquire(mca, seconds)
            if not spec.any():
                print(f'  w={wid*1e6:g} us: espectro VACIO con amp_src={src}; '
                      'revisá umbral/q_shift. Se saltea el punto.')
                res = None
                break
            res[label] = _pico(spec)
        if res is None:
            continue

        # Guarda: un FWHM de pocos canales esta cuantizado por el binning, no
        # medido. Comparar resoluciones ahi da una "mejora" que es del shift.
        comparable = (res['peak']['fwhm'] >= min_fwhm
                      and res['int']['fwhm'] >= min_fwhm)
        out['width_s'].append(wid)
        out['fwhm_peak'].append(res['peak']['fwhm'])
        out['fwhm_int'].append(res['int']['fwhm'])
        out['res_peak'].append(res['peak']['resolution_pct'])
        out['res_int'].append(res['int']['resolution_pct'])
        out['q_shift'].append(qs)
        out['comparable'].append(comparable)
        aviso = '' if comparable else '   <-- FWHM cuantizado, NO comparable'
        print(f'  w={wid*1e6:5.2f} us  q_shift={qs:2d}   resolución pico '
              f'{res["peak"]["resolution_pct"]:6.2f}% (FWHM {res["peak"]["fwhm"]:.1f})'
              f'   integral {res["int"]["resolution_pct"]:6.2f}% '
              f'(FWHM {res["int"]["fwhm"]:.1f}){aviso}')
    gen.output(ch, False)

    out = {k: np.asarray(v) for k, v in out.items()}
    ok = out['comparable'] if out['comparable'].size else np.zeros(0, bool)
    if ok.any():
        mejora = out['res_peak'][ok] / np.maximum(out['res_int'][ok], 1e-9)
        print(f'  mejora de la integral (sólo puntos comparables): '
              f'x{mejora.min():.2f} a x{mejora.max():.2f}')
    else:
        print('  ningún punto es comparable: bajá q_shift (subí target_channel) '
              'o alargá el pulso. NO se reporta mejora.')
    _save(outdir, 'compare_estimators', **out)
    return out


# =============================================================================
# 5. Barrido de tasa — tiempo muerto, throughput, live time
# =============================================================================

def sweep_rate(mca, gen, ch=1, rates=None, seconds=5.0, amp_vpp=0.5,
               width_s=None, outdir=None, **cfg):
    """Tasa registrada vs incidente: throughput, modelo de tiempo muerto,
    exactitud del live time y corrimiento del centroide con la tasa.

    El barrido llega hasta ~800 kcps a propósito. La campaña anterior cortó en
    100 kcps y el MCA seguía al generador de forma EXACTA, o sea que 100 kcps no
    era el techo sino el final del barrido; con ~2.3 µs de tiempo muerto por
    evento la saturación tiene que aparecer cerca de 435 kcps. Sin saturación no
    hay curvatura, y sin curvatura el ajuste de tiempo muerto no significa nada
    (daba tau = 8971 µs, que es ruido del ajuste).
    """
    print('\n=== barrido de tasa (tiempo muerto / throughput) ===')
    # Estimulo en modo PULSE, NO en ARB. El ARB estira la forma completa sobre
    # el periodo de repeticion, asi que al barrer la tasa el pulso cambia de
    # ANCHO al mismo tiempo y la curva de throughput no significa nada. El modo
    # PULSE da periodo y ancho independientes, que es lo que hace falta: ancho
    # fijo, periodo variable.
    c = {**DEFAULT_CFG, **cfg}
    c['maxlen'] = min(c.get('maxlen', 4096), 4096)     # pulsos cortos de verdad
    width_s = PULSE_WIDTH_S if width_s is None else width_s
    rates = np.logspace(2, 5.9, 16) if rates is None else np.asarray(rates)


    r_in, r_out, centroids, lt_frac, anchos, validos = [], [], [], [], [], []
    for r in rates:
        period = 1.0 / float(r)
        # El ancho tiene que escalar con el periodo: set_pulse_periodic exige
        # width < period/2, y con un ancho fijo de 2 us el barrido reventaba con
        # ValueError apenas el periodo bajaba de 4 us (250 kHz).
        w_s = min(width_s, 0.2 * period)
        gen.set_pulse_periodic(ch=ch, period_s=period, width_s=w_s,
                               amp_vpp=amp_vpp, offset_v=amp_vpp / 2)
        gen.output(ch, True)
        # Reconfigurar DENTRO del lazo. Con una sola configuracion previa el
        # barrido daba 100 cps constantes a cualquier tasa; reconfigurando en
        # cada punto sigue al generador de forma exacta hasta 100 kcps.
        mca.configure(**c)
        time.sleep(0.3)
        # El generador no valida nada: preguntarle que quedo puesto (misma
        # leccion que testbench_multitrigger.rigol_state).
        try:
            f_real = float(gen.query(f':SOURce{ch}:FREQuency?'))
            w_real = float(gen.query(f':SOURce{ch}:PULSe:WIDTh?'))
        except Exception:
            f_real, w_real = float('nan'), float('nan')
        spec, _, cnt = _acquire(mca, seconds)
        rt = max(cnt['realtime_s'], 1e-9)
        r_medida = cnt['total'] / rt

        # GUARDA: si el MCA no perdio NI UN evento, entonces `total/realtime` ES
        # la tasa de entrada verdadera. Que difiera de la pedida sólo puede
        # significar que el generador no está entregando lo que se le pidió, y
        # el punto no mide throughput: mide otra cosa. Sin esta guarda el
        # barrido reporta una tabla entera de valores plausibles pero falsos
        # (la campaña anterior dio 100 cps constantes de 187 Hz a 100 kHz y se
        # leyó como "seguimiento exacto").
        sin_perdidas = (cnt['dropped'] == 0 and cnt['pileup'] == 0)
        coincide = abs(r_medida - r) <= 0.05 * r
        ok = coincide or not sin_perdidas
        r_in.append(r)
        r_out.append(cnt['accepted'] / rt)
        lt_frac.append(cnt['livetime_s'] / rt)
        anchos.append(w_real if np.isfinite(w_real) else w_s)
        validos.append(ok)
        try:
            centroids.append(_pico(spec)['centroid'])
        except ValueError:
            centroids.append(np.nan)
        aviso = ''
        if not ok:
            aviso = (f'   <-- INVÁLIDO: sin pérdidas pero entran {r_medida:.0f} Hz, '
                     f'no {r:.0f} (generador en {f_real:.0f} Hz)')
        print(f'  {r:9.0f} Hz in (w={w_real*1e9:6.0f} ns) -> {r_out[-1]:9.0f} cps '
              f'out   live {100*lt_frac[-1]:5.1f}%   '
              f'centroide {centroids[-1]:.1f}{aviso}')
    gen.output(ch, False)
    gen.disable_burst(ch)

    r_in = np.array(r_in); r_out = np.array(r_out)
    validos = np.array(validos, dtype=bool)
    if not validos.all():
        print(f'  {int((~validos).sum())} de {len(validos)} puntos INVÁLIDOS: el '
              f'generador no entregó la tasa pedida. Se excluyen del análisis.')
        r_in, r_out = r_in[validos], r_out[validos]
        lt_frac = list(np.array(lt_frac)[validos])
        centroids = list(np.array(centroids)[validos])
        anchos = list(np.array(anchos)[validos])
    if r_in.size < 2:
        print('  quedan menos de 2 puntos válidos: no hay curva que analizar.')
        _save(outdir, 'sweep_rate', r_in=r_in, r_out=r_out)
        return {'r_in': r_in, 'r_out': r_out, 'validos': validos,
                'techo_cps': float('nan'), 'rate_techo_hz': float('nan'),
                'saturo': False, 'deadtime': None,
                'centroids': np.array(centroids),
                'livetime_frac': np.array(lt_frac)}

    # El techo: el maximo de la curva de salida, y a que tasa de entrada ocurre.
    i_max = int(np.argmax(r_out))
    techo, r_techo = float(r_out[i_max]), float(r_in[i_max])
    print(f'  TECHO: {techo:.0f} cps de salida, con {r_techo:.0f} Hz de entrada')

    # Sin saturacion no hay nada que ajustar: si la salida sigue a la entrada
    # hasta el ultimo punto, el barrido se quedo corto.
    seguimiento = r_out / np.maximum(r_in, 1e-9)
    saturo = bool(seguimiento.min() < 0.9)
    dt = None
    if not saturo:
        print(f'  el MCA sigue al generador hasta {r_in[-1]:.0f} Hz '
              f'(seguimiento mínimo {100*seguimiento.min():.1f}%): NO se '
              f'alcanzó el techo, extendé `rates`. No se ajusta tiempo muerto.')
    else:
        try:
            dt = mu.deadtime_fit(r_in, r_out)
            print(f"  tau no paralizable {dt['tau_nonparalyzable_s']*1e6:.2f} us")
            print(f"  tau paralizable    {dt['tau_paralyzable_s']*1e6:.2f} us")
            print(f"  mejor ajuste: {dt['best']}")
        except ValueError as e:
            print(f'  no se pudo ajustar el tiempo muerto: {e}')

    # CORRIMIENTO DEL CENTROIDE: sólo sobre los puntos con el MISMO ancho de
    # pulso. Comparar el primer punto contra el último mezcla dos variables,
    # porque `w_s` se achica con el período: la campaña reportó +6.45 % y el
    # salto grande caía exactamente donde cambiaba el ancho (72->132 kHz,
    # 2000->1517 ns, +2.52 % de golpe), no donde cambiaba la tasa. Con ancho
    # constante el corrimiento genuino era +1.28 % sobre x36 de tasa.
    cen = np.array(centroids)
    anc = np.array(anchos)
    shift = float('nan')
    if cen.size:
        w_nom = anc.max()
        mismo = (np.abs(anc - w_nom) < 1e-9) & ~np.isnan(cen)
        if mismo.sum() >= 2:
            c0, c1 = cen[mismo][0], cen[mismo][-1]
            r0, r1 = r_in[mismo][0], r_in[mismo][-1]
            shift = 100.0 * (c1 - c0) / c0
            print(f'  corrimiento del centroide con ancho CONSTANTE '
                  f'({w_nom*1e9:.0f} ns): {shift:+.2f}% '
                  f'entre {r0:.0f} y {r1:.0f} Hz (x{r1/r0:.0f})')
        else:
            print('  no hay 2 puntos con el mismo ancho: el corrimiento del '
                  'centroide no se puede separar del cambio de ancho')
        ok = ~np.isnan(cen)
        if ok.sum() >= 2 and mismo.sum() < ok.sum():
            todo = 100.0 * (cen[ok][-1] - cen[ok][0]) / cen[ok][0]
            print(f'  (sobre TODO el barrido daría {todo:+.2f}%, pero mezcla el '
                  f'cambio de ancho: no citar ese número)')
    _save(outdir, 'sweep_rate', r_in=r_in, r_out=r_out, centroids=cen,
          livetime_frac=np.array(lt_frac), widths=np.array(anchos))
    return {'r_in': r_in, 'r_out': r_out, 'centroids': cen,
            'livetime_frac': np.array(lt_frac), 'deadtime': dt,
            'techo_cps': techo, 'rate_techo_hz': r_techo, 'saturo': saturo,
            'centroid_shift_pct': shift, 'widths': anc}


# =============================================================================
# 5b. Barrido de tasa con arribos POISSON
# =============================================================================

def _n_events_factible(rate_hz, width_s, n_events, t_rise_frac=0.25,
                       min_rise_pts=rg.MIN_RISE_PTS, n_pts=rg.ARB_MAX_POINTS):
    """Eventos por ciclo que entran en la memoria del ARB a esa tasa y ancho.

    El paso de muestreo es `dt = n_events/(rate*n_pts)`, así que a tasas bajas
    pedir muchos eventos por ciclo deja el pulso sin puntos. En vez de reventar
    a mitad del barrido, cada punto usa los que entren.
    """
    n_max = int(np.floor(t_rise_frac * width_s * rate_hz * n_pts / min_rise_pts))
    return max(0, min(int(n_events), n_max))


def sweep_rate_poisson(mca, gen, ch=1, rates=None, rhos=None, tau_s=2.3e-6,
                       seconds=6.0, chunk_s=0.5, amp_vpp=0.5, width_s=None,
                       n_events=64, seed0=0, outdir=None, **cfg):
    """Pérdidas vs ρ con arribos de POISSON — la medición que el tren periódico
    no puede dar.

    `sweep_rate` usa el modo PULSE, que es un tren **periódico**, y eso adula a
    la arquitectura: con arribos deterministas y un solo servidor sin cola (K=1)
    no se pierde NADA mientras el período supere el tiempo de servicio, y recién
    después cae en escalones (`P_loss = 1 − 1/⌈ρ⌉`). Una fuente radiactiva
    entrega Poisson, y ahí `P_loss = ρ/(1+ρ)`: se pierde algo a **cualquier**
    tasa, incluso 9 % con ρ=0.1. Los 99 % de eficiencia medidos a 2 kHz son una
    propiedad del estímulo, no del equipo.

    Cómo se mide, y por qué no depende del generador: el MCA cuenta por HW los
    eventos que llegaron con el extractor ocupado (`cnt_dropped`), así que

        P_loss = dropped / (total + dropped)

    sale directo. Y como el FPGA también mide el tiempo muerto,
    `tau = deadtime_s/total` da el tiempo de servicio **medido**, con lo cual el
    modelo se contrasta sin asumirlo. El `N` emitido que se deriva del estímulo
    se usa sólo como control cruzado de la cadena entera.

    Cada trozo de la adquisición recarga una **realización nueva** (semilla
    distinta) vía `acquire_chunks(on_chunk=...)`, así ninguna realización
    particular domina el resultado. El MCA queda parado durante la recarga, así
    que el tiempo del ARB no cuenta como tiempo vivo.

    `rates` en Hz, o `rhos` + `tau_s` para elegir los puntos por ocupación.
    """
    print('\n=== barrido de tasa con arribos POISSON ===')
    c = {**DEFAULT_CFG, **cfg}
    width_s = PULSE_WIDTH_S if width_s is None else width_s
    if rates is None:
        rhos = np.asarray([0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 0.9, 1.5]
                          if rhos is None else rhos, dtype=float)
        rates = rhos / float(tau_s)
    rates = np.asarray(rates, dtype=float)

    filas = []
    for r in rates:
        n_ev = _n_events_factible(r, width_s, n_events)
        if n_ev < 4:
            print(f'  {r:9.0f} Hz: SALTEADO — con {width_s*1e6:g} us de ancho '
                  f'entran {n_ev} eventos por ciclo en los {rg.ARB_MAX_POINTS} '
                  f'puntos del ARB. Subí width_s o la tasa.')
            continue

        infos = []

        def _cargar(k):
            infos.append(rg.apply_poisson_train(
                gen, rate_hz=r, width_s=width_s, ch=ch, amp_vpp=amp_vpp,
                n_events=n_ev, seed=seed0 + k))

        _cargar(0)
        gen.output(ch, True)
        mca.configure(**c)
        time.sleep(0.3)
        spec, _, cnt = mca.acquire_chunks(seconds, chunk_s,
                                          on_chunk=lambda k: _cargar(k + 1))

        rt       = max(cnt['realtime_s'], 1e-9)
        llegados = cnt['total'] + cnt['dropped']
        p_loss   = cnt['dropped'] / max(llegados, 1)
        tau_med  = cnt['deadtime_s'] / max(cnt['total'], 1)
        # rho con el tau MEDIDO: el modelo se contrasta sin asumir el servicio
        rho_med  = r * tau_med
        # control cruzado: lo que el estimulo dice que emitio en el tiempo vivo
        n_emit = sum(i['n_events'] * i['freq_hz'] for i in infos) / len(infos) * rt
        filas.append(dict(
            rate_hz=float(r), n_events=n_ev, n_realizaciones=len(infos),
            total=int(cnt['total']), dropped=int(cnt['dropped']),
            pileup=int(cnt['pileup']), accepted=int(cnt['accepted']),
            realtime_s=rt, livetime_s=cnt['livetime_s'],
            deadtime_s=cnt['deadtime_s'],
            p_loss=float(p_loss), tau_med_s=float(tau_med), rho=float(rho_med),
            p_loss_poisson=float(rho_med / (1.0 + rho_med)),
            p_loss_periodico=float(1.0 - 1.0 / max(np.ceil(rho_med), 1.0)),
            r_out=cnt['accepted'] / rt,
            n_emit_estimulo=float(n_emit), n_llegados_hw=int(llegados),
            frac_pileup_gen=float(np.mean([i['frac_pileup'] for i in infos])),
            rate_real_gen=float(np.mean([i['rate_real'] for i in infos])),
            dt_s=float(infos[0]['dt_s']),
        ))
        f = filas[-1]
        # Si el estimulo y el HW no coinciden en cuantos eventos llegaron, el
        # punto no mide perdidas: mide que el generador entrego otra cosa.
        coincide = abs(n_emit - llegados) <= 0.15 * max(llegados, 1)
        f['valido'] = bool(coincide)
        print(f'  {r:9.0f} Hz (n_ev={n_ev:3d}, dt={f["dt_s"]*1e9:6.1f} ns) -> '
              f'rho={f["rho"]:5.3f}  P_loss={100*p_loss:5.1f}%  '
              f'(Poisson {100*f["p_loss_poisson"]:5.1f}%, '
              f'periodico {100*f["p_loss_periodico"]:5.1f}%)  '
              f'tau={tau_med*1e6:6.2f} us  pileup={100*cnt["pileup"]/max(cnt["total"],1):4.1f}%'
              + ('' if coincide else
                 f'   <-- INVALIDO: el estimulo dice {n_emit:.0f} y el HW '
                 f'vio {llegados}'))

    gen.output(ch, False)
    if not filas:
        print('  no quedo ningun punto medible.')
        return {'filas': [], 'validos': 0}

    col = lambda k: np.array([f[k] for f in filas], dtype=float)
    val = np.array([f['valido'] for f in filas], dtype=bool)
    if not val.all():
        print(f'  {int((~val).sum())} de {len(val)} puntos INVALIDOS '
              '(estimulo != lo que vio el HW): se excluyen del analisis.')

    rho, pl = col('rho')[val], col('p_loss')[val]
    if rho.size >= 2:
        err_p = np.abs(pl - rho / (1 + rho))
        err_d = np.abs(pl - (1 - 1 / np.maximum(np.ceil(rho), 1)))
        print(f'  |medido - Poisson|   medio = {100*err_p.mean():.2f} pp')
        print(f'  |medido - periodico| medio = {100*err_d.mean():.2f} pp')
        print(f'  => los datos se parecen mas al modelo '
              f'{"POISSON" if err_p.mean() < err_d.mean() else "PERIODICO"}')

    _save(outdir, 'sweep_rate_poisson',
          rate_hz=col('rate_hz'), rho=col('rho'), p_loss=col('p_loss'),
          p_loss_poisson=col('p_loss_poisson'),
          p_loss_periodico=col('p_loss_periodico'),
          tau_med_s=col('tau_med_s'), r_out=col('r_out'),
          total=col('total'), dropped=col('dropped'), pileup=col('pileup'),
          livetime_s=col('livetime_s'), realtime_s=col('realtime_s'),
          n_emit_estimulo=col('n_emit_estimulo'),
          n_llegados_hw=col('n_llegados_hw'),
          frac_pileup_gen=col('frac_pileup_gen'), valido=val)
    return {'filas': filas, 'validos': int(val.sum())}


# =============================================================================
# 6. Par de pulsos — resolución par-pulso
# =============================================================================

def test_pulse_pair(mca, gen, ch=1, gaps_s=None, seconds=4.0, amp_vpp=0.5,
                    width_s=200e-9, burst_period_s=1e-3, outdir=None, **cfg):
    """Dos pulsos separados por `gap`: mínimo para contarlos como dos.

    Reutiliza set_pulse_pair_burst, que ya existía para el scope.

    Tres cosas cambiaron respecto de la versión que dio un resultado inválido:

    1. **El ancho del pulso y el período del burst son FIJOS.** Antes eran
       `width=gap/4` y `burst_period=max(10*gap, 1ms)`, o sea que se movían
       junto con el gap y la curva mezclaba tres variables.
    2. **La normalización es contra la medición a gap MÁXIMO**, no contra un
       número de bursts estimado a partir de `realtime/burst_period`. Ese
       estimador era el que producía fracciones de 1.00 por debajo del tiempo
       muerto de 2.3 µs, que es imposible. Con la referencia medida:
       1.0 = se contaron los dos pulsos, 0.5 = se fusionaron en uno.
    3. **`dropped` se informa como número absoluto**, no como porcentaje de
       `cnt_total`: son eventos que nunca entraron en `total`, así que el
       cociente puede pasar de 100 % (fue el "101 % de descartes" del informe).
    """
    print('\n=== par de pulsos (resolución par-pulso) ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    # Desde 0.5 us: por debajo del tiempo muerto (~2.3 us) no hay nada que ver,
    # y el generador tampoco puede con gaps mucho menores que el ancho.
    gaps_s = np.logspace(np.log10(5e-7), -4, 12) if gaps_s is None else np.asarray(gaps_s)
    gaps_s = np.sort(np.asarray(gaps_s, dtype=float))

    if width_s >= gaps_s[0]:
        width_s = gaps_s[0] / 3.0
        print(f'  ancho reducido a {width_s*1e9:.0f} ns para que entre en el gap mínimo')

    def _punto(g):
        gen.set_pulse_pair_burst(ch=ch, gap_s=float(g), width_s=float(width_s),
                                 amp_vpp=amp_vpp, offset_v=amp_vpp / 2,
                                 burst_period_s=burst_period_s)
        gen.output(ch, True)
        time.sleep(0.3)
        _, _, cnt = _acquire(mca, seconds)
        return cnt

    # Referencia: el gap mas grande, donde los dos pulsos son inequivocamente
    # dos eventos. Todo lo demas se normaliza contra esta MEDICION.
    cnt_ref = _punto(gaps_s[-1])
    n_ref = cnt_ref['total'] / max(cnt_ref['realtime_s'], 1e-9)
    print(f'  referencia a gap {gaps_s[-1]*1e6:.1f} us: {n_ref:.0f} eventos/s '
          f'(= 2 por burst de {burst_period_s*1e3:.1f} ms)')
    if n_ref <= 0:
        print('  la referencia no cuenta eventos: revisá umbral y amplitud')
        gen.output(ch, False)
        gen.disable_burst(ch)
        return None

    gaps, ratio, pileup, dropped = [], [], [], []
    for g in gaps_s:
        cnt = cnt_ref if g == gaps_s[-1] else _punto(g)
        tasa = cnt['total'] / max(cnt['realtime_s'], 1e-9)
        gaps.append(g)
        ratio.append(tasa / n_ref)
        pileup.append(cnt['pileup'])
        dropped.append(cnt['dropped'])
        print(f'  gap {g*1e6:8.3f} us -> {tasa:8.0f} ev/s   fracción '
              f'{ratio[-1]:.2f}   apilamientos {cnt["pileup"]}   '
              f'perdidos {cnt["dropped"]}')
    gen.output(ch, False)
    gen.disable_burst(ch)

    gaps = np.array(gaps); ratio = np.array(ratio)
    # Cruce del 75%: entre "los dos" (1.0) y "uno solo" (0.5), el punto medio.
    resueltos = np.where(ratio >= 0.75)[0]
    tau_pp = gaps[resueltos[0]] if len(resueltos) else np.nan
    print(f'  resolución par-pulso (cruce del 75% entre 1.0 y 0.5): '
          f'{tau_pp*1e6:.2f} us')
    if np.isfinite(tau_pp) and tau_pp < 1e-6:
        print('  AVISO: sale por debajo de 1 us, menos que el tiempo muerto '
              'medido (~2.3 us). Revisá que el generador esté entregando los '
              'dos pulsos (miralos con el scope) antes de creerle.')
    _save(outdir, 'pulse_pair', gaps=gaps, ratio=ratio, pileup=np.array(pileup),
          dropped=np.array(dropped), n_ref=n_ref)
    return {'gaps': gaps, 'ratio': ratio, 'pileup': np.array(pileup),
            'dropped': np.array(dropped), 'tau_pair_s': tau_pp, 'n_ref': n_ref}


# =============================================================================
# 7. Barrido de umbral — curva S y LLD
# =============================================================================

def sweep_threshold(mca, gen, ch=1, thrs=None, seconds=3.0, amp_vpp=0.2,
                    rate_hz=2e3, width_s=None, outdir=None, **cfg):
    """Fracción de pulsos detectados vs umbral (curva S). El 50% define el LLD
    efectivo. Con la entrada terminada da además el piso de ruido."""
    print('\n=== barrido de umbral (curva S / LLD) ===')
    _pulse_train(gen, ch, rate_hz, amp_vpp, width_s)

    if thrs is None:
        # El rango se deriva de la amplitud MEDIDA. Con un rango fijo bajo, la
        # curva S sale plana (todo por encima del umbral) y no dice nada: hay
        # que barrer HASTA pasar la amplitud del pulso.
        mca.configure(**{**DEFAULT_CFG, **cfg, 'thr': 100, 'hyst': 40})
        _acquire(mca, 0.5)
        amp = mca.last_event()['amp']
        if amp <= 0:
            print('  no se detecta señal; revisá el generador')
            return None
        thrs = np.linspace(20, 1.25 * amp, 26).astype(int)
        print(f'  amplitud medida {amp} cuentas -> umbrales de '
              f'{thrs[0]} a {thrs[-1]}')
    else:
        thrs = np.asarray(thrs)

    det = []
    for t in thrs:
        mca.configure(**{**DEFAULT_CFG, **cfg, 'thr': int(t),
                         'hyst': max(4, int(t) // 3)})
        _, _, cnt = _acquire(mca, seconds)
        det.append(cnt['total'] / max(cnt['realtime_s'], 1e-9))
        print(f'  umbral {t:5d} -> {det[-1]:9.0f} cps')
    gen.output(ch, False)

    det = np.array(det, dtype=float)
    # La MESETA es la referencia, no el máximo: a umbral muy bajo el sistema
    # dispara con ruido y la tasa se dispara (se midieron 262 kcps a thr=20 con
    # una señal de 2 kHz). Tomar el máximo haría que el "50 %" cayera en la
    # zona de ruido en vez de en el flanco de la curva S.
    plateau = float(np.median(det[det > 0])) if np.any(det > 0) else 0.0
    ruido = det > 5 * plateau if plateau > 0 else np.zeros_like(det, bool)
    lld = np.nan
    if plateau > 0:
        util = np.where(~ruido)[0]
        below = [i for i in util if det[i] < 0.5 * plateau]
        if below:
            lld = thrs[below[0]]
    print(f'  meseta {plateau:.0f} cps   umbrales con ruido: '
          f'{int(ruido.sum())} de {len(thrs)}')
    print(f'  LLD efectivo (50% de la meseta): {lld}')

    print('  midiendo el piso de ruido: DESCONECTÁ o terminá la entrada...')
    gen.output(ch, False)
    time.sleep(1.0)
    noise = []
    for t in thrs:
        mca.configure(**{**DEFAULT_CFG, **cfg, 'thr': int(t),
                         'hyst': max(4, int(t) // 3)})
        _, _, cnt = _acquire(mca, 1.0)
        noise.append(cnt['total'] / max(cnt['realtime_s'], 1e-9))
    noise = np.array(noise, dtype=float)
    quiet = np.where(noise < 1.0)[0]
    print(f'  umbral mínimo sin disparos de ruido: '
          f'{thrs[quiet[0]] if len(quiet) else "ninguno del barrido"}')
    _save(outdir, 'sweep_threshold', thrs=thrs, detected=det, noise=noise)
    return {'thrs': thrs, 'detected': det, 'noise': noise, 'lld': lld}


# =============================================================================
# 8. Dos poblaciones — FOM
# =============================================================================

def test_psd_fom(mca, gen, ch=1, seconds=30.0, amp_vpp=0.5, rate_hz=50e3,
                 tau_ratio=3.0, width_s=None, vs_energia=True,
                 amp_range=(0.35, 1.0), n_slices=4, min_cuentas=200,
                 outdir=None, **cfg):
    """Dos poblaciones con colas distintas: FOM global y FOM vs energía.

    Son dos mediciones con estímulos DISTINTOS, y hay que hacer las dos:

    - **FOM global**: las dos poblaciones con la MISMA amplitud. Al no moverse
      en el eje de amplitud, cualquier separación que aparezca es del eje de
      forma — es el caso limpio. FOM > 1.27 se considera buena separación.
    - **FOM vs energía** (`vs_energia=True`): la amplitud además varía en
      `amp_range`, así los eventos se reparten sobre el eje de amplitud del mapa
      2D y se puede ver cómo se degrada la separación a baja energía. Con el
      estímulo de amplitud fija, TODOS los eventos caen en una sola rebanada y
      las demás dan `nan` — que es lo que pasó en la campaña anterior.

    `h2_shift` se auto-escala para que el rango de amplitudes entre en las
    2^H2_AW rebanadas; sin eso la señal ocupa una sola aunque el estímulo varíe.
    """
    print('\n=== dos poblaciones (FOM de PSD) ===')
    if not mca.caps & mu.CAP_HIST_H_PSD:
        print('  este bitstream no trae el motor 2D; salteando')
        return None
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    width_s = PULSE_WIDTH_S if width_s is None else width_s

    # --- 1) FOM global: misma amplitud, colas distintas ---
    _pulse_train(gen, ch, rate_hz, amp_vpp, width_s,
                 tau_choices=(1.0, float(tau_ratio)), seed=0)
    spec, m2d, cnt = _acquire(mca, seconds)

    res = mu.fom(m2d)
    print(f"  FOM global: {res.get('fom', float('nan')):.3f}")
    if cnt['rej_psd']:
        print(f"  {cnt['rej_psd']} eventos sin factor de forma válido "
              "(Q_total=0 o Q_cola>=Q_total): revisá cfg_tail_dly y el umbral")

    # --- 2) FOM vs energía: amplitud repartida sobre el eje del mapa ---
    per_slice, m2d_e = [], None
    if vs_energia:
        print('  --- FOM vs energía (amplitud variable) ---')
        _pulse_train(gen, ch, rate_hz, amp_vpp, width_s,
                     tau_choices=(1.0, float(tau_ratio)),
                     amp_range=amp_range, seed=1)
        h2 = mca.autoscale_h2_shift(**{**c, 'h2_shift': 0})
        if h2 is None:
            print('  no se detectan eventos; se saltea la FOM vs energía')
        else:
            print(f'  h2_shift auto-escalado a {h2} '
                  f'(antes {c.get("h2_shift")})')
            mca.configure(**{**c, 'h2_shift': h2})
            _, m2d_e, cnt_e = _acquire(mca, seconds)

            n_amp = m2d_e.shape[0]
            paso  = max(1, n_amp // max(n_slices, 1))
            for lo in range(0, n_amp, paso):
                hi = min(lo + paso, n_amp)
                n = float(m2d_e[lo:hi, :].sum())
                # Una rebanada sin estadistica no da una FOM "nan": da una FOM
                # que no se midio. Se dice cual es el caso.
                if n < min_cuentas:
                    per_slice.append((lo, hi, np.nan, n))
                    print(f'  amplitud [{lo:3d},{hi:3d}) -> sin estadística '
                          f'({n:.0f} cuentas < {min_cuentas})')
                    continue
                try:
                    f = mu.fom(m2d_e, lo, hi)['fom']
                except (ValueError, KeyError):
                    f = np.nan
                per_slice.append((lo, hi, f, n))
                print(f'  amplitud [{lo:3d},{hi:3d}) -> FOM {f:.3f} '
                      f'({n:.0f} cuentas)')
            medidas = [f for _, _, f, _ in per_slice if np.isfinite(f)]
            if len(medidas) < 2:
                print('  AVISO: menos de dos rebanadas con estadística; la '
                      'dependencia con la energía no se puede evaluar. Subí el '
                      'tiempo o ensanchá amp_range.')
    gen.output(ch, False)

    _save(outdir, 'psd_fom', spec=spec, map2d=m2d,
          **({'map2d_energia': m2d_e} if m2d_e is not None else {}))
    return {'fom': res, 'map2d': m2d, 'map2d_energia': m2d_e,
            'per_slice': per_slice, 'counters': cnt}


# =============================================================================
# 8b. Constante del seguidor de línea de base
# =============================================================================

def sweep_baseline_k(mca, gen, ch=1, ks=(3, 6, 9, 12, 15), seconds=1.0,
                     amp_vpp=0.5, rate_hz=2e3, width_s=None, outdir=None, **cfg):
    """Eventos detectados vs constante de tiempo del seguidor de línea de base.

    Si la constante (2^bl_k muestras, o sea 2^k * 8 ns) es comparable a la
    duración del pulso, el seguidor PERSIGUE la señal y la borra: nunca cruza el
    umbral y no se detecta nada. Este barrido encuentra el piso utilizable.

    **Hay que re-correrlo cada vez que cambia la duración del pulso**, porque el
    valor correcto depende de ella: los `bl_k` de la campaña anterior estaban
    calibrados para pulsos de ~240 µs y no valen para los de ~2 µs de ahora, ni
    para los del detector real.
    """
    print('\n=== constante del seguidor de línea de base ===')
    width_s = PULSE_WIDTH_S if width_s is None else width_s
    _pulse_train(gen, ch, rate_hz, amp_vpp, width_s)
    n_muestras = width_s * 125e6
    print(f'  el pulso dura ~{n_muestras:.0f} muestras a 125 MSPS; el seguidor '
          f'necesita 2^bl_k bastante MAYOR que eso '
          f'(bl_k >= {int(np.ceil(np.log2(max(n_muestras,2)))) + 3})')

    ks = np.asarray(ks)
    total, acc, amps, bases = [], [], [], []
    for k in ks:
        mca.configure(**{**DEFAULT_CFG, **cfg, 'bl_auto': True, 'bl_k': int(k)})
        _, _, cnt = _acquire(mca, seconds)
        ev = mca.last_event()
        total.append(cnt['total']); acc.append(cnt['accepted'])
        amps.append(ev['amp']); bases.append(ev['baseline'])
        tau_us = (1 << int(k)) * 8e-3
        print(f'  bl_k={int(k):2d}  tau={tau_us:8.1f} us  ->  '
              f'{cnt["total"]:6d} eventos   amp={ev["amp"]}')
    gen.output(ch, False)

    total = np.array(total)
    ok = np.where(total > 0)[0]
    k_min = int(ks[ok[0]]) if len(ok) else None
    print(f'  bl_k mínimo utilizable con este pulso: {k_min}')
    _save(outdir, 'sweep_baseline_k', ks=ks, total=total,
          accepted=np.array(acc), amps=np.array(amps), baselines=np.array(bases))
    return {'ks': ks, 'total': total, 'k_min': k_min}


# =============================================================================
# 9. Verificación cruzada contra el scope
# =============================================================================

def cross_check_counts(mca, gen, ch=1, seconds=5.0, amp_vpp=0.5, rate_hz=1e3,
                       width_s=None, outdir=None, **cfg):
    """`cnt_total` del MCA contra la tasa conocida del generador.

    La comparación directa con capture_n_events() del scope no es posible en el
    bitstream del MCA (los dos coexisten en el diseño, pero el scope necesita su
    propia configuración de armado); acá se contrasta contra el generador, que
    es una referencia independiente y suficiente.
    """
    print('\n=== verificación cruzada de conteo ===')
    c = {**DEFAULT_CFG, **cfg}
    mca.configure(**c)
    _pulse_train(gen, ch, rate_hz, amp_vpp, width_s)
    _, _, cnt = _acquire(mca, seconds)
    gen.output(ch, False)

    esperado = rate_hz * cnt['realtime_s']
    err = 100.0 * (cnt['total'] - esperado) / max(esperado, 1e-9)
    print(f"  esperado {esperado:.0f}, contado {cnt['total']} ({err:+.2f}%)")
    print(f"  descartados {cnt['dropped']}, apilamientos {cnt['pileup']}, "
          f"rechazados por amplitud {cnt['rej_amp']}")
    _save(outdir, 'cross_check', expected=np.array([esperado]),
          error_pct=np.array([err]), rate_hz=np.array([rate_hz]),
          **{f'cnt_{k}': np.array([v]) for k, v in cnt.items()})
    return {'expected': esperado, 'counters': cnt, 'error_pct': err}


# =============================================================================
# Graficado
# =============================================================================

# Paleta de las comparaciones de dos modos. Validada para daltonismo: el par
# tiene ΔE 24.7 en protanopia y 33.6 en visión normal (OKLab x100), muy por
# encima de los pisos de 8 y 15. Además cada curva lleva su etiqueta, así que la
# identidad nunca depende sólo del color.
C_HYST = '#eb6834'      # naranja: el modo viejo (ventana por histéresis)
C_GATE = '#2a78d6'      # azul:    el modo nuevo (compuerta de largo fijo)
INK    = '#0b0b0b'
MUTED  = '#8a8a86'


def _limpiar(ax):
    """Grilla y ejes recesivos: los datos adelante, el andamiaje atrás."""
    ax.grid(color=MUTED, alpha=.25, lw=.6)
    ax.set_axisbelow(True)
    for lado in ('top', 'right'):
        ax.spines[lado].set_visible(False)
    for lado in ('left', 'bottom'):
        ax.spines[lado].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK)


def plot_all(outdir):
    """Grafica los .npz de una campaña. Se puede correr en la PC, sin hardware."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    def _load(name):
        p = os.path.join(outdir, f'{name}.npz')
        return np.load(p) if os.path.exists(p) else None

    d = _load('single_peak')
    if d is not None:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.semilogy(d['spec'] if 'spec' in d else d['spectrum'])
        ax.set_xlabel('canal'); ax.set_ylabel('cuentas')
        ax.set_title('Espectro — pulser de amplitud fija')
        fig.savefig(os.path.join(outdir, 'single_peak.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('sweep_amplitude')
    if d is not None:
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
        a1.plot(d['amps'], d['centroids'], 'o-'); a1.set_ylabel('centroide')
        a1.set_title('Linealidad')
        a2.plot(d['amps'], d['resid'], 'o-'); a2.axhline(0, color='k', lw=.5)
        a2.set_xlabel('amplitud [Vpp]'); a2.set_ylabel('residuo (INL)')
        fig.savefig(os.path.join(outdir, 'linealidad.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('formas_inl')
    if d is not None:
        familias = [str(x) for x in d['familias']]
        estims = [str(x) for x in d['estimadores']]
        amps = np.asarray(d['amps'], dtype=float)
        # Un color por familia, el MISMO en las dos figuras: son dos vistas del
        # mismo barrido y se leen juntas. El marcador también cambia, porque hay
        # familias que caen una encima de la otra a propósito (la triangular y
        # la trapezoidal comparten factor de forma exactamente) y con sólo el
        # color una taparía a la otra.
        color = {f: plt.cm.tab10(i % 10) for i, f in enumerate(familias)}
        marca = {f: 'osD^vP*X'[i % 8] for i, f in enumerate(familias)}
        medidas = [f for f in familias
                   if f'ok_{f}' in d.files and bool(d[f'ok_{f}'])]

        # --- 1. las curvas de INL superpuestas -------------------------------
        # Sólo el residuo: la recta de calibración no aporta nada visual (todas
        # las familias dan una recta) y la INL vive enteramente en el residuo.
        # En mV y no en canales, que es la única unidad en la que el estimador
        # de pico y el de carga son comparables entre sí.
        ejes = [e for e in estims
                if any(f'resid_{f}_{e}' in d.files for f in medidas)]
        if ejes:
            fig, axs = plt.subplots(len(ejes), 1, figsize=(8, 3.2 * len(ejes)),
                                    sharex=True, squeeze=False)
            for ax, est in zip(axs[:, 0], ejes):
                curvas = []
                for f in medidas:
                    k = f'resid_{f}_{est}'
                    if k not in d.files:
                        continue
                    r = 1e3 * np.asarray(d[k]) / float(d[f'gain_{f}_{est}'])
                    curvas.append(r)
                    ax.plot(amps, r, marker=marca[f], ls='-', ms=4.5, lw=1.2,
                            color=color[f], label=f)
                if len(curvas) > 1:
                    # La media entre familias es la parte COMÚN del residuo: lo
                    # que no depende de la forma, o sea el generador y la INL
                    # estática del ADC. Lo que cada curva se aparta de ella es
                    # lo único atribuible a la cadena de medición: si todas las
                    # curvas abrazan esta línea, la amplitud se determina igual
                    # sea cual sea la forma del pulso.
                    ax.plot(amps, np.nanmean(np.vstack(curvas), axis=0), '--',
                            color='k', lw=2.2, alpha=.75, zorder=10,
                            label='común (generador + ADC)')
                ax.axhline(0, color='k', lw=.5)
                ax.set_ylabel(f'residuo [mV]\nestimador de {est}')
                ax.grid(alpha=.3)
            axs[0, 0].set_title('INL por familia de forma de pulso')
            axs[-1, 0].set_xlabel('amplitud del generador [Vpp]')
            h, lab = axs[0, 0].get_legend_handles_labels()
            fig.legend(h, lab, loc='upper center', ncol=4, fontsize=8,
                       bbox_to_anchor=(0.5, 0.03), frameon=False)
            fig.savefig(os.path.join(outdir, 'inl_formas.png'), dpi=120,
                        bbox_inches='tight'); plt.close(fig)

        # --- 2. pico vs carga -------------------------------------------------
        # Es el test de linealidad que NO depende del generador: los dos ejes
        # son estimadores internos del MISMO pulso, así que un error de consigna
        # de amplitud mueve el punto A LO LARGO de la recta, no fuera de ella.
        # Curvatura dentro de una familia = no linealidad de la electrónica.
        pares = [f for f in medidas
                 if f'cen_{f}_pico' in d.files and f'cen_{f}_carga' in d.files]
        if pares:
            fig, ax = plt.subplots(figsize=(7, 6))
            for f in pares:
                # A unidades físicas: hay que deshacer los desplazamientos de
                # binning, porque `q_shift` se autoescala POR FAMILIA y sin esto
                # la pendiente de cada una estaría contaminada por su propio
                # desplazamiento en vez de por su geometría.
                x = np.asarray(d[f'cen_{f}_pico']) * 2.0 ** float(d['h_shift'])
                y = np.asarray(d[f'cen_{f}_carga']) * 2.0 ** float(d[f'qshift_{f}_carga'])
                ax.plot(x, y / 1e3, marker=marca[f], ls='none', ms=7,
                        color=color[f], mec='white', mew=.8, alpha=.85,
                        label=f'{f}  (factor {float(d[f"factor_forma_{f}"]):.3f})')
            ax.set_xlabel('amplitud de pico [cuentas de ADC]')
            ax.set_ylabel(r'carga $Q_{tot}$ [kcuentas$\cdot$muestra]')
            ax.set_title('Pico vs carga — dos estimadores del mismo pulso')
            ax.grid(alpha=.3); ax.legend(fontsize=8)
            fig.savefig(os.path.join(outdir, 'pico_vs_carga.png'), dpi=120,
                        bbox_inches='tight'); plt.close(fig)

    d = _load('sweep_rate')
    if d is not None:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.loglog(d['r_in'], d['r_out'], 'o-', label='medido')
        ax.loglog(d['r_in'], d['r_in'], 'k--', lw=.8, label='ideal')
        # El techo es el punto que importa: donde la curva se despega y cae.
        i = int(np.argmax(d['r_out']))
        ax.plot(d['r_in'][i], d['r_out'][i], 'r*', ms=14,
                label=f'techo {d["r_out"][i]:.0f} cps')
        ax.set_xlabel('tasa incidente [Hz]'); ax.set_ylabel('tasa registrada [cps]')
        ax.legend(); ax.set_title('Throughput')
        fig.savefig(os.path.join(outdir, 'throughput.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('sweep_rate_poisson')
    if d is not None:
        # Las dos curvas de modelo son el punto del grafico: con arribos
        # deterministas no se pierde nada hasta rho=1 (escalones), con Poisson
        # se pierde rho/(1+rho) desde el principio. Que los datos caigan sobre
        # una o la otra es el resultado.
        rho = d['rho']
        o = np.argsort(rho)
        rho_s = rho[o]
        fino = np.logspace(np.log10(max(rho_s.min(), 1e-3)),
                           np.log10(max(rho_s.max(), 1e-2)), 200)
        val = d['valido'].astype(bool) if 'valido' in d.files else np.ones_like(rho, bool)
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot(fino, 100 * fino / (1 + fino), '-', color='tab:blue',
                label=r'Poisson  $\rho/(1+\rho)$')
        ax.plot(fino, 100 * (1 - 1 / np.ceil(fino)), '-', color='tab:gray',
                label=r'periodico  $1-1/\lceil\rho\rceil$')
        ax.plot(rho[val], 100 * d['p_loss'][val], 'o', color='tab:red',
                ms=7, label='medido (dropped/llegados)')
        if (~val).any():
            ax.plot(rho[~val], 100 * d['p_loss'][~val], 'x', color='k',
                    ms=9, label='invalido')
        ax.set_xscale('log')
        ax.set_xlabel(r'$\rho = \lambda\tau$  ($\tau$ medido por el FPGA)')
        ax.set_ylabel('eventos perdidos [%]')
        ax.set_title('Perdidas vs ocupacion — arribos Poisson')
        ax.grid(True, which='both', alpha=0.3); ax.legend()
        fig.savefig(os.path.join(outdir, 'poisson_loss.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('pulse_pair')
    if d is not None:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.semilogx(d['gaps'] * 1e6, d['ratio'], 'o-')
        ax.axhline(1.0, color='k', lw=.5, ls='--')
        # 0.5 = los dos pulsos se fusionaron en un solo evento.
        ax.axhline(0.5, color='r', lw=.5, ls='--')
        ax.set_xlabel('separación [µs]')
        ax.set_ylabel('eventos / referencia (1 = los dos, 0.5 = fusionados)')
        ax.set_title('Resolución par-pulso')
        fig.savefig(os.path.join(outdir, 'pulse_pair.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('dnl')
    if d is not None and 'dnl' in d:
        lo, hi = int(d['lo']), int(d['hi'])
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
        a1.plot(np.arange(lo, hi), d['spec'][lo:hi], lw=.6, label='espectro')
        if 'envelope' in d:
            a1.plot(np.arange(lo, hi), d['envelope'], 'r-', lw=1.2,
                    label='envolvente (referencia)')
        a1.set_ylabel('cuentas'); a1.legend(); a1.set_title('DNL')
        a2.plot(np.arange(lo, hi), 100 * d['dnl'], lw=.6)
        a2.axhline(0, color='k', lw=.5)
        a2.set_xlabel('canal'); a2.set_ylabel('DNL [%]')
        fig.savefig(os.path.join(outdir, 'dnl.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('psd_fom')
    if d is not None:
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.imshow(d['map2d'], origin='lower', aspect='auto')
        ax.set_xlabel('factor de forma'); ax.set_ylabel('amplitud')
        ax.set_title('Mapa amplitud x forma')
        fig.savefig(os.path.join(outdir, 'psd_map.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('sweep_gate')
    if d is not None:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot(d['largas'], d['res'], 'o-', color=C_GATE, lw=2, ms=8,
                mec='white', mew=1.5, label='compuerta fija')
        rh = float(d['res_hyst'][0])
        ax.axhline(rh, color=C_HYST, ls='--', lw=2)
        ax.annotate(f'histéresis  {rh:.3f} %',
                    xy=(d['largas'][-1], rh), xytext=(-4, 6),
                    textcoords='offset points', ha='right',
                    color=INK, fontsize=9)
        i = int(np.nanargmin(d['res']))
        ax.annotate(f'óptimo: {int(d["largas"][i])} muestras\n'
                    f'{d["res"][i]:.3f} %  (×{rh / d["res"][i]:.2f})',
                    xy=(d['largas'][i], d['res'][i]), xytext=(10, 14),
                    textcoords='offset points', color=INK, fontsize=9,
                    arrowprops=dict(arrowstyle='-', color=MUTED, lw=.8))
        ax.set_xlabel('largo de la compuerta [muestras a 125 MSPS]')
        ax.set_ylabel('resolución FWHM/centroide [%]')
        ax.set_title('Largo de compuerta óptimo')
        _limpiar(ax)
        fig.savefig(os.path.join(outdir, 'sweep_gate.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)

    d = _load('sweep_gate_espectro')
    if d is not None:
        # El FWHM en CANALES no es comparable entre modos: cada uno integra una
        # cantidad distinta de muestras, así que tienen ganancias distintas y el
        # mismo ruido de entrada da distinto número de canales. Se lo refiere a
        # la entrada dividiendo por la ganancia (canales/V) de CADA modo, sacada
        # del ajuste lineal de su propio eje. Ahí sí las dos curvas están en la
        # misma unidad física y se pueden superponer.
        amps, larga = d['amps'], int(d['larga'][0])
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 7.5), sharex=True)
        for n, col, lab in (('hist', C_HYST, 'histéresis'),
                            ('gate', C_GATE, f'compuerta fija ({larga})')):
            cen, fw = d[f'cen_{n}'], d[f'fwhm_{n}']
            m = np.isfinite(cen) & np.isfinite(fw)
            gan = np.polyfit(amps[m], cen[m], 1)[0] if m.sum() >= 2 else np.nan
            a1.plot(amps, 1e3 * fw / gan, 'o-', color=col, lw=2, ms=7,
                    mec='white', mew=1.2, label=lab)
            a2.plot(amps, d[f'res_{n}'], 'o-', color=col, lw=2, ms=7,
                    mec='white', mew=1.2, label=lab)
        a1.set_ylabel('FWHM referido a la entrada [mV]')
        a1.set_title('Precisión absoluta a lo largo del espectro')
        a2.set_ylabel('resolución FWHM/centroide [%]')
        a2.set_xlabel('amplitud del pulso [Vpp]')
        a2.set_title('Precisión relativa')
        for a in (a1, a2):
            _limpiar(a)
        # Una sola leyenda: los dos paneles comparten series. Arriba a la
        # izquierda es la zona libre en los dos (las curvas suben hacia la
        # derecha en el panel de arriba y caen en el de abajo).
        a1.legend(frameon=False, loc='upper left')
        fig.savefig(os.path.join(outdir, 'gate_espectro.png'), dpi=120,
                    bbox_inches='tight'); plt.close(fig)
    print(f'gráficos en {outdir}')


# =============================================================================
# CLI
# =============================================================================

# =============================================================================
# 10. Compuertas fijas contra ventana por histéresis
# =============================================================================

def sweep_gate(mca, gen, ch=1, largas=None, corta=32, seconds=4.0,
               amp_vpp=0.5, rate_hz=2e3, width_s=None, outdir=None, **cfg):
    """Resolución de la integral: ventana por histéresis vs compuerta fija.

    Es la medición en placa del resultado que salió offline sobre 7054 pulsos
    (`tests/estimadores/`): con la ventana cerrada por histéresis el largo lo
    decide dónde la cola cruza `thr − hyst`, que es la parte más chata del
    pulso, así que lo decide el ruido. Con compuerta fija no.

    Offline dio 0.528 % (histéresis) contra 0.149 % (compuerta de 384). Acá se
    mide lo mismo con el hardware, barriendo el largo de la compuerta: la curva
    tiene un mínimo y hay que encontrarlo, porque una compuerta muy corta pierde
    carga y una muy larga integra ruido y arrastra el error de línea de base.
    """
    print('\n=== compuerta fija vs ventana por histéresis ===')
    largas = np.array([128, 192, 256, 320, 384, 448, 512]) if largas is None \
        else np.asarray(largas)
    c = {**DEFAULT_CFG, **cfg, 'amp_src': 1}      # integral de carga

    _pulse_train(gen, ch, rate_hz, amp_vpp, width_s)

    def _res(cfg_extra):
        """Resolución del pico del espectro con una configuración dada."""
        qs = mca.autoscale_q_shift(target_channel=8000, **{**c, **cfg_extra,
                                                           'q_shift': 0})
        if qs is None:
            return None, None
        mca.configure(**{**c, **cfg_extra, 'q_shift': qs})
        spec, _, cnt = _acquire(mca, seconds)
        if not spec.any():
            return None, cnt
        return _pico(spec), cnt

    # --- referencia: el modo de siempre ---
    f_h, cnt_h = _res({'gate_mode': 0})
    if f_h is None:
        print('  no se detectan eventos; revisá umbral y amplitud')
        gen.output(ch, False)
        return None
    print(f'  histéresis      -> resolución {f_h["resolution_pct"]:6.3f} %  '
          f'(FWHM {f_h["fwhm"]:.1f} sobre {f_h["centroid"]:.0f})')

    # --- barrido de compuerta ---
    res, pileup = [], []
    for L in largas:
        f, cnt = _res({'gate_mode': 1, 'gate_short': int(corta),
                       'gate_long': int(L)})
        if f is None:
            res.append(np.nan); pileup.append(np.nan)
            print(f'  compuerta {L:4d}  -> sin eventos')
            continue
        res.append(f['resolution_pct'])
        pileup.append(100.0 * cnt['pileup'] / max(cnt['total'], 1))
        print(f'  compuerta {L:4d}  -> resolución {res[-1]:6.3f} %  '
              f'(FWHM {f["fwhm"]:.1f} sobre {f["centroid"]:.0f})   '
              f'apilamiento {pileup[-1]:.1f} %')
    gen.output(ch, False)

    res = np.array(res, dtype=float)
    ok = np.isfinite(res)
    mejor = None
    if ok.any():
        i = int(np.nanargmin(res))
        mejor = (int(largas[i]), float(res[i]))
        gan = f_h['resolution_pct'] / res[i]
        print(f'  mejor compuerta: {mejor[0]} muestras -> {mejor[1]:.3f} %, '
              f'x{gan:.2f} sobre la histéresis')
        if gan < 1.2:
            print('  AVISO: la mejora es marginal. Con este estímulo la ventana '
                  'por histéresis\n  no está limitando: revisá que la cola sea '
                  'larga (es donde el cruce tiembla).')
    _save(outdir, 'sweep_gate', largas=largas, res=res,
          pileup=np.array(pileup, dtype=float),
          res_hyst=np.array([f_h['resolution_pct']]))
    return {'largas': largas, 'res': res, 'res_hyst': f_h['resolution_pct'],
            'mejor': mejor}


def sweep_gate_espectro(mca, gen, ch=1, amps=None, corta=32, larga=384,
                        seconds=4.0, rate_hz=2e3, width_s=None,
                        target_channel=12000, outdir=None, **cfg):
    """FWHM de los dos modos de ventana A LO LARGO DEL ESPECTRO.

    `sweep_gate` compara histéresis contra compuerta fija en UN punto del
    espectro (la amplitud del estímulo). Acá se barre la amplitud y se mide el
    FWHM de los dos modos en CADA punto, para ver si la mejora es pareja o si
    depende de la energía.

    Por qué importa: los dos modos no fallan igual en función de la amplitud.

      - Con histéresis el largo de la ventana lo decide dónde la cola cruza
        `thr − hyst`, y ese punto se corre con la amplitud (un pulso más grande
        tarda más en bajar). O sea que el largo de integración **crece con la
        energía**: la ganancia no es lineal y la varianza del cruce entra en
        todos los canales.
      - Con compuerta fija el largo no depende de la amplitud por construcción,
        así que se espera ganancia lineal y un FWHM que crezca sólo como el
        ruido integrado.

    Metodología: los dos modos se miden **intercalados en cada amplitud**, con
    el mismo estímulo cargado una sola vez. Así cualquier deriva del generador
    o de la línea de base afecta a los dos por igual y la comparación se
    sostiene aunque la corrida dure varios minutos.

    `q_shift` se calibra UNA vez por modo, en la amplitud máxima, y queda fijo
    durante todo el barrido: si se re-escalara en cada punto, el eje de canales
    dejaría de ser un eje de energía y el FWHM no sería comparable entre puntos.
    """
    print('\n=== FWHM vs energía: histéresis vs compuerta fija ===')
    amps = np.linspace(0.1, 1.0, 12) if amps is None else np.asarray(amps)
    c = {**DEFAULT_CFG, **cfg, 'amp_src': 1}      # integral de carga
    modos = {'hist': {'gate_mode': 0},
             'gate': {'gate_mode': 1, 'gate_short': int(corta),
                      'gate_long': int(larga)}}

    width_s = PULSE_WIDTH_S if width_s is None else width_s
    wave, freq, info = rg.pulse_train_wave(width_s, rate_hz)
    print(f'  estímulo: {width_s*1e6:g} us FWHM a {rate_hz:g} Hz '
          f'({info["n_pulses"]} pulso(s)/forma a {freq:.1f} Hz)')
    gen.load_arb(wave, ch=ch)

    def _amplitud(a):
        gen.set_arb(ch=ch, freq_hz=freq, amp_vpp=float(a),
                    offset_v=float(a) / 2)
        gen.output(ch, True)
        time.sleep(0.3)

    # --- calibración de q_shift: una vez por modo, en la amplitud máxima ---
    _amplitud(amps.max())
    qs = {}
    for nombre, extra in modos.items():
        qs[nombre] = mca.autoscale_q_shift(target_channel=target_channel,
                                           **{**c, **extra, 'q_shift': 0})
        if qs[nombre] is None:
            print(f'  no se detectan eventos en modo {nombre}; '
                  'revisá umbral y amplitud')
            gen.output(ch, False)
            return None
        print(f'  q_shift {nombre} = {qs[nombre]} '
              f'(pico a ~{target_channel} canales con {amps.max():.2f} Vpp)')

    def _medir(nombre, extra):
        mca.configure(**{**c, **extra, 'q_shift': qs[nombre]})
        spec, _, cnt = _acquire(mca, seconds)
        if not spec.any():
            return None, cnt
        f = _pico(spec)
        # El pico tiene que ENTRAR ENTERO en el histograma. Si la cola derecha
        # se pasa del último canal, el ajuste ve una gaussiana cortada y devuelve
        # un FWHM MENOR que el real: el punto aparece como el mejor de todo el
        # barrido justo donde el instrumento se está quedando sin escala. Pasó
        # en la primera corrida (centroide 16376 + 2 FWHM = 16412 > 16383), y
        # rompía la tendencia hacia abajo. Se descarta, no se promedia.
        if f['centroid'] + 2 * f['fwhm'] > len(spec) - 1:
            print(f'    [{nombre}] pico truncado por el tope del histograma '
                  f'(centroide {f["centroid"]:.0f} + 2·FWHM > {len(spec)-1}): '
                  'punto descartado. Bajá `target_channel`.')
            return None, cnt
        return f, cnt

    out = {n: {'cen': [], 'fwhm': [], 'res': [], 'pileup': []} for n in modos}
    for a in amps:
        _amplitud(a)
        linea = f'  {a:.3f} Vpp'
        for nombre, extra in modos.items():
            f, cnt = _medir(nombre, extra)
            if f is None:
                for k in out[nombre]:
                    out[nombre][k].append(float('nan'))
                linea += f'   {nombre}: sin eventos'
                continue
            out[nombre]['cen'].append(f['centroid'])
            out[nombre]['fwhm'].append(f['fwhm'])
            out[nombre]['res'].append(f['resolution_pct'])
            out[nombre]['pileup'].append(100.0 * cnt['pileup']
                                         / max(cnt['total'], 1))
            linea += (f'   {nombre}: canal {f["centroid"]:7.0f} '
                      f'FWHM {f["fwhm"]:6.2f} ({f["resolution_pct"]:5.3f} %)')
        print(linea)
    gen.output(ch, False)

    for n in out:
        for k in out[n]:
            out[n][k] = np.array(out[n][k], dtype=float)

    # --- veredicto: mejora punto a punto y linealidad de cada eje ---
    gan = out['hist']['res'] / out['gate']['res']
    ok = np.isfinite(gan)
    inl = {}
    for n in modos:
        cen = out[n]['cen']
        m = np.isfinite(cen)
        if m.sum() >= 3:
            _, _, _, inl[n] = mu.energy_calibration(cen[m], amps[m])
        else:
            inl[n] = float('nan')
    if ok.any():
        print(f'  mejora en resolución: x{np.nanmin(gan):.2f} a '
              f'x{np.nanmax(gan):.2f} (mediana x{np.nanmedian(gan):.2f})')
        print(f'  INL del eje: histéresis {inl["hist"]:.3f} % FS   '
              f'compuerta {inl["gate"]:.3f} % FS')
        if np.nanmin(gan) < 1.0:
            print('  AVISO: hay puntos donde la compuerta NO mejora. Con esta '
                  'compuerta\n  parte del espectro pierde carga: revisá `larga` '
                  'contra la cola del pulso.')
    if np.nanmax([out[n]['pileup'].max() if out[n]['pileup'].size else 0
                  for n in modos]) > 5.0:
        print('  AVISO: apilamiento > 5 % en algún punto; los FWHM de esos '
              'puntos no son confiables.')

    _save(outdir, 'sweep_gate_espectro', amps=amps, corta=np.array([corta]),
          larga=np.array([larga]),
          q_shift=np.array([qs['hist'], qs['gate']]),
          **{f'{k}_{n}': out[n][k] for n in modos for k in out[n]})
    return {'amps': amps, 'hist': out['hist'], 'gate': out['gate'],
            'ganancia': gan, 'inl_pct_fs': inl}


TESTS = {
    'single_peak':        test_single_peak,
    'sweep_gate':         sweep_gate,
    'sweep_gate_espectro': sweep_gate_espectro,
    'sweep_amplitude':    sweep_amplitude,
    'formas_inl':         sweep_formas_inl,
    'dnl':                test_dnl,
    'compare_estimators': compare_estimators,
    'sweep_rate':         sweep_rate,
    'pulse_pair':         test_pulse_pair,
    'sweep_threshold':    sweep_threshold,
    'psd_fom':            test_psd_fom,
    'baseline_k':         sweep_baseline_k,
    'cross_check':        cross_check_counts,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('test', nargs='?', help="nombre del test, o 'all'")
    ap.add_argument('--list', action='store_true', help='listar los tests')
    ap.add_argument('--outdir', default=None, help='dónde guardar los .npz')
    ap.add_argument('--channel', type=int, default=0, help='0=IN1, 1=IN2')
    ap.add_argument('--gen-ch', type=int, default=1, help='canal del Rigol')
    ap.add_argument('--plot-only', action='store_true',
                    help='sólo graficar un --outdir ya medido (no usa hardware)')
    args = ap.parse_args(argv)

    if args.list or not args.test and not args.plot_only:
        print('tests disponibles:')
        for k in TESTS:
            print(f'  {k}')
        print("  all   (corre todos en orden)")
        return 0

    if args.plot_only:
        if not args.outdir:
            ap.error('--plot-only necesita --outdir')
        plot_all(args.outdir)
        return 0

    mca, gen, _ = connect(args.channel)
    try:
        names = list(TESTS) if args.test == 'all' else [args.test]
        for n in names:
            if n not in TESTS:
                print(f'test desconocido: {n}', file=sys.stderr)
                return 2
            TESTS[n](mca, gen, ch=args.gen_ch, outdir=args.outdir,
                     channel=args.channel)
    finally:
        try:
            gen.output(args.gen_ch, False)
        finally:
            gen.close()
            mca.close()
    if args.outdir:
        plot_all(args.outdir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
