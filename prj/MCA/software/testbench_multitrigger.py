"""
Banco de pruebas / caracterización del scope multitrigger.

Mientras `multitrigger_utils.py` es el *driver* (wrapper de /dev/mem, arm,
captura), este módulo tiene los **métodos de caracterización**: sondas de HW,
análisis de tiempos con reloj de FPGA y los barridos de dead-time.

Uso típico desde el notebook:

    from multitrigger_utils import MultiTriggerScope
    import testbench_multitrigger as tb

    sc = MultiTriggerScope.open()
    print(tb.poll_floor_us(sc))                  # piso del método de medición
    res = tb.sweep_periods(sc, rg, [1e-3, 1e-4], save=save_tb)
    tb.plot_deadtime_curve(res)

Convenciones:

- Ninguna función usa globals del notebook: `sc` (scope) y `rg` (generador) se
  pasan explícitos.
- Las que guardan reciben `save=None`, un callable
  `save(label, meta=None, **arrays)` — el notebook le pasa su `save_capture`
  (típicamente envuelto para que inyecte `scope_regs(sc)` en la meta).
- `matplotlib` y `multitrigger_utils` se importan DENTRO de las funciones que
  los necesitan, así este módulo se puede importar en la PC (sin el paquete
  `rp` ni /dev/mem) para reanalizar los .npz offline.

Los tres regímenes que hay que separar al medir dead-time (ver
docs/ y el análisis del plan):

    HW (re-arm del trigger)      ~24 ns   -> sólo visible con `sweep_pulse_width`
    dt entre disparos por Δwp      8 ns   -> resolución de `events_to_hw_intervals`
    lazo de polling en Python   ~2-6 µs   -> piso real de `capture_n_events`
"""

import time

import numpy as np


# ---------- constantes ----------
# Duplicadas a propósito (y no importadas de multitrigger_utils) para que este
# módulo se importe sin el paquete `rp`. Coinciden con las de allá.

N_BUF      = 16384
FS         = 125e6                # Hz, sampling rate con decim=1
TS_NS      = 1e9 / FS             # 8 ns por sample @ decim=1

BIT_ADC_P0 = 1 << 1               # bits de la OR_MASK (trg_src_bits)
BIT_ADC_N0 = 1 << 2

# OJO: el snapshot @0x218 NO usa el mismo layout que la máscara. La máscara
# alterna posedge/negedge por canal (bit1=p0, bit2=n0, bit3=p1, ...), mientras
# que el snapshot agrupa: {trig_ch[3:0], asg_n, asg_p, ext_n, ext_p,
# adc_n[3:0], adc_p[3:0], sw_any} -> bits 1..4 = adc_p0..p3, bits 5..8 =
# adc_n0..n3 (multitrigger_event_logic.v:139 y _SNAP_NAMES de multitrigger_utils).
SNAP_ADC_P0 = 1 << 1
SNAP_ADC_N0 = 1 << 5

# offsets usados por las sondas (ver docs/register_map_multitrigger_rp_scope_cfg.md)
OFF_ADC_STATE = 0x000
OFF_WP_TRIG   = (0x01C, 0x11C)
OFF_WP_CUR    = (0x018, 0x118)
OFF_WE_CNT    = (0x02C, 0x12C)
OFF_SNAPSHOT  = 0x218
OFF_DIS_WE    = 0x21C
OFF_MASK      = (0x240, 0x244)


# ---------- análisis de tiempos con reloj de FPGA ----------

def wp_dt_us(wp_prev, wp_cur, dt_sw_us=None, dec=1, n_buf=N_BUF, fs=FS):
    """dt entre dos triggers a partir de `Δwp_trig`, en µs.

    `adc_wp_trig` (@0x1C) es el sample exacto en el que disparó el FPGA, así que
    la diferencia entre dos lecturas mide el intervalo con resolución de **1
    sample** (8 ns con decim=1) en vez de los ±4 µs del reloj de Python.

    El puntero es de 14 bits: envuelve cada `n_buf` samples (131.072 µs con
    decim=1), así que `Δwp` sólo es no-ambiguo por debajo de eso. Con `dt_sw_us`
    (el mismo intervalo medido por SW) se des-envuelve contando cuántos wraps
    enteros pasaron.

    OJO con el criterio: `t_ns` marca cuándo el SW **se enteró** del disparo, no
    cuándo disparó el FPGA, así que `dt_sw` trae la latencia del polling y algún
    hipo del scheduler de +100 µs. Redondear a medio wrap (65 µs) hace que uno
    de esos hipos sume un wrap fantasma — medido en la placa: dt_hw daba
    101.3 µs en vez de 100.000 con un tren de 10 kHz, y el exceso era exactamente
    131.072 µs en un solo intervalo. Por eso el umbral es **0.75 wrap** (98 µs)
    de evidencia antes de agregar un wrap:

        k  = floor((dt_sw − dwp·Ts)/wrap + 0.25)
        dt = dwp·Ts + max(k,0)·wrap

    Con eso el des-envuelto aguanta latencias de SW de hasta ~98 µs y sigue
    resolviendo bien los intervalos largos (que superan el wrap por ≥1 wrap
    completo). Si sólo hace falta el dt y no importa el rango >131 µs, pasar
    `dt_sw_us=None` y no hay ambigüedad posible.
    """
    ts_us   = dec / fs * 1e6
    wrap_us = n_buf * ts_us
    dt = ((int(wp_cur) - int(wp_prev)) % n_buf) * ts_us
    if dt_sw_us is not None:
        k = int(np.floor((float(dt_sw_us) - dt) / wrap_us + 0.25))
        if k > 0:
            dt += k * wrap_us
    return dt


def events_to_hw_intervals(events, dec=1, n_buf=N_BUF, fs=FS):
    """Intervalos entre triggers consecutivos en µs, medidos por `Δwp_trig`.

    Gemelo de `multitrigger_utils.events_to_intervals` (que usa el reloj de
    Python), pero con el reloj del FPGA. Usa `t_ns` de cada evento sólo para
    des-envolver el wrap del puntero.
    """
    if len(events) < 2:
        return np.array([])
    out = np.empty(len(events) - 1, dtype=float)
    for i in range(1, len(events)):
        dt_sw = (events[i]['t_ns'] - events[i-1]['t_ns']) / 1000.0
        out[i-1] = wp_dt_us(events[i-1]['wp'], events[i]['wp'], dt_sw,
                            dec=dec, n_buf=n_buf, fs=fs)
    return out


def missed_events(dt_hw_us, period_us):
    """Cuántos disparos de HW se perdió el SW entre dos observaciones.

    Los triggers sólo pueden ocurrir en los pulsos, así que cada `dt_hw` es un
    múltiplo del período del estímulo: `k = round(dt_hw/period)` es el número de
    pulsos transcurridos y `k-1` los que el polling no llegó a ver.
    """
    dt = np.asarray(dt_hw_us, dtype=float)
    if not dt.size or not period_us:
        return np.array([])
    return np.maximum(np.round(dt / period_us) - 1, 0)


# ---------- sondas de HW (sin Python en el lazo) ----------

def we_time_since_arm_us(sc, ch=0, dec=1, fs=FS):
    """Samples escritos desde el último arm / reset / pulso a 0x94, en µs.

    OJO con lo que NO es: `adc_we_cnt` (@0x02C ch0 / @0x12C ch1) se resetea con
    `(adc_rst_do || adc_arm_do) || (trig_dis_clr && adc_we_keep)`
    (rp_bram_sm.v:71), y el `trig_dis_clr` que llega al bram_sm es el del
    **registro 0x94 (clear de SW)**, no el del trigger_shield: el clear del
    shield se queda dentro de multitrigger_event_logic
    (rp_scope_multitrigger_com.sv:597 lo cablea desde el cfg, no desde el
    shield). Así que con auto_rearm este contador **NO** marca el tiempo desde
    el último disparo — crece libre desde el arm. Verificado en la placa.

    Para saber si el FPGA está disparando, usar `trigger_alive` (mira wp_trig).
    """
    return sc.r32(OFF_WE_CNT[ch]) * dec / fs * 1e6


def trigger_alive(sc, dwell_s=0.05, ch=0, dec=1, fs=FS, n_buf=N_BUF):
    """¿El FPGA está disparando? Mira si `wp_trig` (@0x1C) se mueve.

    `adc_wp_trig` se re-latchea en cada disparo aceptado, así que basta con
    verlo cambiar durante `dwell_s` para saber que el camino de trigger está
    vivo — sin depender de que el SW llegue a ver TODOS los disparos. Es el
    discriminador entre "el FPGA no dispara" y "el FPGA dispara pero el polling
    no lo sigue", que es la ambigüedad central del barrido de dead-time.

    Devuelve dict con:
      alive        : hubo al menos un cambio de wp_trig en el dwell
      n_cambios    : cambios observados (COTA INFERIOR de los disparos reales:
                     el polling tarda ~5-10 µs por vuelta)
      rate_min_hz  : n_cambios/dwell, también cota inferior
      dt_hw_med_us : mediana de Δwp entre cambios consecutivos, en µs (8 ns de
                     resolución). Es un múltiplo del período real; si el polling
                     no se saltea nada, ES el período.
      dt_hw_min_us : el menor Δwp observado -> cota superior del dead-time real
      + el estado de los registros que hacen falta para el diagnóstico.

    Requiere el scope ARMADO.
    """
    wp_addr = OFF_WP_TRIG[ch]
    r32 = sc.r32
    ts_us = dec / fs * 1e6
    wp_prev = r32(wp_addr)
    deltas = []
    t_end = time.perf_counter() + dwell_s
    while time.perf_counter() < t_end:
        wp = r32(wp_addr)
        if wp != wp_prev:
            deltas.append((wp - wp_prev) % n_buf)
            wp_prev = wp
    d = np.asarray(deltas, dtype=float) * ts_us              # µs
    dis_we = r32(OFF_DIS_WE)
    return dict(
        alive        = bool(d.size),
        n_cambios    = int(d.size),
        rate_min_hz  = float(d.size / dwell_s),
        dt_hw_med_us = float(np.median(d)) if d.size else float('nan'),
        dt_hw_min_us = float(d.min())      if d.size else float('nan'),
        dwell_s      = dwell_s,
        dis_act      = dis_we & 0xF,
        we_keep      = (dis_we >> 4) & 0xF,
        mask_ch0     = r32(OFF_MASK[0]),
        adc_state    = r32(OFF_ADC_STATE),
        snapshot     = r32(OFF_SNAPSHOT),
        we_cnt_us    = we_time_since_arm_us(sc, ch, dec, fs),
    )


def poll_floor_us(sc, n=20000, addr=0x1C):
    """Mide el dead-time del MÉTODO: cuánto tarda una iteración del lazo de
    polling de Python sobre /dev/mem.

    Devuelve dict con:
      read_us    : costo puro de una lectura (bulk: n lecturas / n, sin
                   timestamp por iteración) — lo que paga el lazo optimizado.
      p50/p90/p99: percentiles del intervalo entre lecturas midiendo con
                   `perf_counter_ns` en cada vuelta — es una cota superior,
                   incluye el costo del propio timestamp.

    El período de pulsos tiene que ser bastante mayor que este número para que
    `capture_n_events` no saltee disparos.
    """
    r32 = sc.r32
    # 1) costo puro de la lectura (sin timestamps de por medio)
    t0 = time.perf_counter_ns()
    for _ in range(n):
        r32(addr)
    read_us = (time.perf_counter_ns() - t0) / 1000.0 / n

    # 2) distribución del intervalo por iteración
    ts = np.empty(n, dtype=np.int64)
    pc = time.perf_counter_ns
    for i in range(n):
        r32(addr)
        ts[i] = pc()
    d = np.diff(ts) / 1000.0
    return dict(n=n, read_us=read_us,
                p50=float(np.percentile(d, 50)), p90=float(np.percentile(d, 90)),
                p99=float(np.percentile(d, 99)), mean=float(d.mean()),
                min=float(d.min()))


# ---------- caracterización de la señal que llega al ADC ----------

def _hyst_edges(d, thr=0.5, hyst=0.02):
    """Cruces con histéresis, vectorizado. Devuelve (subidas, bajadas) en índices.

    Misma semántica que `multitrigger_utils.pulses_from_buffer` (que sólo da las
    subidas y lo hace con un loop de Python), pero sin el loop — importa porque
    esto corre sobre buffers de 16 k samples en la Pitaya — y devolviendo
    también las bajadas, que son las que dan el ancho del pulso.
    """
    d = np.asarray(d, dtype=float)
    marks = np.zeros(d.size, dtype=np.int8)
    marks[d > (thr + hyst)] =  1
    marks[d < (thr - hyst)] = -1
    # forward-fill del último cruce (estado del comparador con histéresis)
    idx  = np.where(marks != 0, np.arange(d.size), -1)
    last = np.maximum.accumulate(idx)
    state = np.zeros(d.size, dtype=bool)
    valid = last >= 0
    state[valid] = marks[last[valid]] > 0
    diff = np.diff(state.astype(np.int8))
    return np.flatnonzero(diff > 0), np.flatnonzero(diff < 0)


def pulse_metrics(d, thr=0.5, hyst=0.02, dec=1, fs=FS):
    """Qué llega realmente a la entrada del ADC, a partir de un buffer crudo.

    Es la evidencia que separa "el generador dejó de entregar el pulso" de
    "el pulso llega pero el trigger no lo toma": si `cruza_umbral` es False o
    `v_max` < thr, el problema está antes del FPGA.

    OJO con `ventana_us`: el buffer son N_BUF samples (131 µs con decim=1). Si
    el período de pulsos es del orden de la ventana o mayor, que no aparezcan
    pulsos NO significa que el generador esté mudo — significa que la ventana no
    los cubre. `cobertura_ok` marca ese caso.
    """
    d = np.asarray(d, dtype=float)
    ts_ns = dec / fs * 1e9
    rises, falls = _hyst_edges(d, thr=thr, hyst=hyst)

    ancho_ns = np.array([])
    if rises.size and falls.size:
        j  = np.searchsorted(falls, rises, side='right')
        ok = j < falls.size
        if ok.any():
            ancho_ns = (falls[j[ok]] - rises[ok]) * ts_ns

    per_us = np.diff(rises) * ts_ns / 1000.0 if rises.size >= 2 else np.array([])
    return dict(
        n_pulsos      = int(rises.size),
        cruza_umbral  = bool(rises.size),
        v_max         = float(d.max()),
        v_min         = float(d.min()),
        v_media       = float(d.mean()),
        amp_pp        = float(d.max() - d.min()),
        ancho_med_ns  = float(ancho_ns.mean()) if ancho_ns.size else float('nan'),
        ancho_std_ns  = float(ancho_ns.std())  if ancho_ns.size else float('nan'),
        periodo_med_us= float(per_us.mean())   if per_us.size   else float('nan'),
        periodo_std_us= float(per_us.std())    if per_us.size   else float('nan'),
        ventana_us    = float(d.size * ts_ns / 1000.0),
        thr=thr, hyst=hyst,
    )


# ---------- estado y límites del generador ----------

def rigol_state(rg, ch=1):
    """Snapshot de lo que el generador tiene puesto REALMENTE (no lo pedido).

    Los setters del driver no validan nada (`set_pulse_period` sólo manda
    `:FREQuency`), así que si el instrumento recorta el ancho o rechaza el
    período, la única forma de enterarse es preguntándole. `err` es la cola
    SCPI: '0,"No error"' significa que aceptó el último comando.
    """
    def _f(cmd, default=float('nan')):
        try:
            return float(rg.query(cmd))
        except Exception:
            return default
    try:
        err = rg.check_error()
    except Exception as e:
        err = f'<sin respuesta: {e}>'
    return dict(
        freq     = _f(f':SOURce{ch}:FREQuency?'),
        width    = _f(f':SOURce{ch}:PULSe:WIDTh?'),
        ampl     = _f(f':SOURce{ch}:VOLTage?'),
        offset   = _f(f':SOURce{ch}:VOLTage:OFFSet?'),
        outp     = _f(f':OUTPut{ch}:STATe?', default=-1.0),
        err      = err,
    )


def rigol_limits(rg, ch=1):
    """Límites que declara el propio instrumento (no el datasheet).

    Fija el piso del ESTÍMULO: por debajo del ancho/transición mínimos o por
    encima de la frecuencia máxima en modo pulso no se puede testear nada,
    independientemente de lo que resuelva el FPGA. Correr una vez y guardar en
    la meta.
    """
    def _f(cmd):
        try:
            return float(rg.query(cmd))
        except Exception:
            return float('nan')
    return dict(
        width_min = _f(f':SOURce{ch}:PULSe:WIDTh? MIN'),
        width_max = _f(f':SOURce{ch}:PULSe:WIDTh? MAX'),
        tran_min  = _f(f':SOURce{ch}:PULSe:TRANsition? MIN'),
        freq_max  = _f(f':SOURce{ch}:FREQuency? MAX'),
        freq_min  = _f(f':SOURce{ch}:FREQuency? MIN'),
    )


# ---------- helpers internos de los barridos ----------

def _fmt(x):
    """Número -> string apto para nombre de archivo (1000, 0p5, 2p5)."""
    return f'{x:g}'.replace('.', 'p').replace('-', 'm')


def _flat_meta(prefix, d):
    """dict anidado -> claves planas con prefijo (para la meta del .npz)."""
    return {f'{prefix}_{k}': v for k, v in d.items()}


def _save(save, label, meta=None, **arrays):
    """Llama al callback de guardado si el notebook lo pasó."""
    if save is None:
        return None
    return save(label, meta=meta, **arrays)


# ---------- barridos ----------

def sweep_periods(sc, rg, periods_s, ch=1, n_events=300, timeout_ms=2000,
                  thr=0.5, hyst=0.01, settle_s=0.1, auto_rearm=True,
                  raw=True, dwell_s=0.05, save=None, verbose=True):
    """Barrido de distancia entre pulsos (el test de dead-time clásico).

    Por cada período: reconfigura el generador, verifica qué quedó puesto,
    mira la señal cruda que llega al ADC, arma, comprueba si el FPGA dispara y
    recién ahí cuenta eventos desde Python.

    Además de la eficiencia SW de siempre, cada punto reporta:

      hw_dt_med_us : dt entre disparos medido por Δwp_trig (8 ns de resolución)
      n_saltados   : disparos de HW que el polling no llegó a ver
      hw_alive     : si el FPGA seguía disparando durante el punto

    que es lo que permite decir si el dead-time observado es del FPGA o del
    software. `save` recibe un .npz por punto + el resumen del barrido.
    """
    from multitrigger_utils import BIT_ADC_P0, events_to_intervals, efficiency

    results = []
    for p in periods_s:
        f = 1.0 / p
        period_us = p * 1e6
        rg.set_pulse_period(ch=ch, period_s=p)
        time.sleep(settle_s)
        rst = rigol_state(rg, ch)

        # 1) qué llega al ADC (captura forzada por SW trigger, independiente
        #    del trigger por ADC que estamos midiendo)
        pm, d1, d2 = {}, None, None
        if raw:
            d1, d2, _snap_sw = sc.acq_capture_sw(thr=thr)
            pm = pulse_metrics(d1, thr=thr)

        # 2) armar y preguntarle al FPGA si dispara (sonda de HW)
        sc.arm_for_adc_trigger(mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                               thr=thr, hyst=hyst, auto_rearm=auto_rearm)
        alive = trigger_alive(sc, dwell_s=dwell_s)

        # 3) contar eventos desde Python
        events, dur_s = sc.capture_n_events(n=n_events, timeout_ms=timeout_ms)
        sc.disarm()

        dt_sw = events_to_intervals(events)
        dt_hw = events_to_hw_intervals(events)
        miss  = missed_events(dt_hw, period_us)
        r = {
            'period_s':       p,
            'freq':           f,
            'observed_n':     len(events),
            'duration_s':     dur_s,
            'efficiency':     efficiency(len(events), f, dur_s),
            'mean_dt_us':     float(dt_sw.mean()) if dt_sw.size else float('nan'),
            'std_dt_us':      float(dt_sw.std())  if dt_sw.size else float('nan'),
            'hw_dt_med_us':   float(np.median(dt_hw)) if dt_hw.size else float('nan'),
            'hw_dt_std_us':   float(dt_hw.std())      if dt_hw.size else float('nan'),
            'n_saltados_med': float(np.median(miss))  if miss.size  else float('nan'),
            'hw_alive':       bool(alive['alive']),
            'hw_dt_probe_us': alive['dt_hw_med_us'],
            'hw_rate_min_hz': alive['rate_min_hz'],
            'expected_dt_us': period_us,
            # ¿la ventana del buffer (131 µs) cubre al menos 2 pulsos? Si no,
            # las métricas del pulso no significan nada a este período.
            'cobertura_ok':   bool(pm) and period_us <= pm['ventana_us'] / 2,
            'rigol':          rst,
            'pulso':          pm,
            'alive':          alive,
        }
        results.append(r)

        _save(save, f'dt_p{_fmt(period_us)}us',
              meta={'period_s': p, 'freq': f, 'thr': thr, 'hyst': hyst,
                    'auto_rearm': auto_rearm, 'n_target': n_events,
                    'timeout_ms': timeout_ms, 'duration_s': dur_s,
                    'observed_n': len(events), 'efficiency': r['efficiency'],
                    **_flat_meta('rigol', rst), **_flat_meta('pulso', pm),
                    **_flat_meta('hw', alive)},
              t_ns=np.array([e['t_ns'] for e in events], dtype=np.int64),
              wp=np.array([e['wp'] for e in events], dtype=np.int32),
              dt_sw_us=dt_sw, dt_hw_us=dt_hw, n_saltados=miss,
              **({'d1': d1, 'd2': d2} if d1 is not None else {}))

        if verbose:
            if not raw:
                sig = ''
            elif r['cobertura_ok']:
                sig = (f'  pulso: vmax={pm["v_max"]:.2f} V '
                       f'w={pm["ancho_med_ns"]:.0f} ns')
            else:
                sig = f'  pulso: vmax={pm["v_max"]:.2f} V w=n/d (periodo > ventana)'
            print(f'p={period_us:>9.2f} µs  (f={f:>9.0f} Hz)  '
                  f'n={len(events):>4d}/{n_events}  eff={r["efficiency"]*100:>6.1f}%  '
                  f'dt_sw={r["mean_dt_us"]:>8.2f}±{r["std_dt_us"]:>6.2f} µs  '
                  f'dt_hw={r["hw_dt_med_us"]:>8.2f} µs  '
                  f'saltados={r["n_saltados_med"]:>4.1f}  '
                  f'hw={"vivo" if r["hw_alive"] else "MUERTO"}{sig}')

    save_sweep_summary(results, save=save)
    return results


def save_sweep_summary(results, save=None, label='dt_sweep_summary'):
    """Guarda el barrido entero como vectores en un solo .npz (para graficar
    offline sin abrir punto por punto)."""
    if save is None or not results:
        return None
    cols = ('period_s', 'freq', 'observed_n', 'duration_s', 'efficiency',
            'mean_dt_us', 'std_dt_us', 'hw_dt_med_us', 'hw_dt_std_us',
            'n_saltados_med', 'expected_dt_us')
    arrays = {c: np.array([r[c] for r in results], dtype=float) for c in cols}
    arrays['hw_alive'] = np.array([r['hw_alive'] for r in results], dtype=bool)
    arrays['v_max']    = np.array([r['pulso'].get('v_max', np.nan) for r in results])
    arrays['ancho_ns'] = np.array([r['pulso'].get('ancho_med_ns', np.nan) for r in results])
    return _save(save, label, meta={'n_puntos': len(results)}, **arrays)


def diagnose_point(sc, rg, p, ch=1, width_s=None, thr=0.5, hyst=0.01,
                   n_events=50, timeout_ms=500, settle_s=0.2, dwell_s=0.05,
                   save=None, verbose=True):
    """Diagnóstico de UN período: dónde se corta la cadena.

    Corre los cuatro pasos en orden (generador → señal en el ADC → FPGA → SW) y
    dictamina con esta tabla:

      señal ausente / bajo umbral            -> GENERADOR
      señal OK + FPGA muerto                 -> CAMINO DE TRIGGER (mask/dis/we)
      señal OK + FPGA vivo + SW n=0          -> POLLING (el lazo, no el HW)
      señal OK + FPGA vivo + SW n<esperado   -> DEAD-TIME SW (cuantificado por dt_hw)

    Con períodos comparables a la ventana del buffer (131 µs) la señal no se
    puede juzgar desde una sola captura: ahí el veredicto es INDETERMINADO en
    vez de acusar al generador.
    """
    from multitrigger_utils import BIT_ADC_P0, decode_snap, efficiency

    if width_s is not None:
        rg.set_pulse_width(ch=ch, width_s=width_s)
    rg.set_pulse_period(ch=ch, period_s=p)
    time.sleep(settle_s)
    rst = rigol_state(rg, ch)

    d1, d2, snap_sw = sc.acq_capture_sw(thr=thr)
    pm = pulse_metrics(d1, thr=thr)

    sc.arm_for_adc_trigger(mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                           thr=thr, hyst=hyst, auto_rearm=True)
    alive = trigger_alive(sc, dwell_s=dwell_s)
    events, dur_s = sc.capture_n_events(n=n_events, timeout_ms=timeout_ms)
    sc.disarm()

    dt_hw = events_to_hw_intervals(events)
    eff   = efficiency(len(events), 1.0 / p, dur_s)

    # La ventana del buffer son 131 µs: si el período es del orden de eso o
    # mayor, no ver pulsos es esperable y NO acusa al generador.
    cobertura_ok = (p * 1e6) <= pm['ventana_us'] / 2

    if not pm['cruza_umbral'] and not cobertura_ok:
        veredicto = ('INDETERMINADO: el buffer (%.0f µs) no cubre el período; '
                     'la señal no se puede juzgar acá' % pm['ventana_us'])
    elif (not pm['cruza_umbral'] or pm['v_max'] < thr) and cobertura_ok:
        veredicto = 'GENERADOR: no llega un pulso que cruce el umbral a la entrada'
    elif not alive['alive']:
        veredicto = 'CAMINO DE TRIGGER: el pulso llega pero el FPGA no dispara'
    elif not events:
        veredicto = 'POLLING: el FPGA dispara pero el lazo de Python no ve wp_trig'
    elif eff < 0.95:
        veredicto = 'DEAD-TIME SW: el FPGA sigue el ritmo, el polling no'
    else:
        veredicto = 'OK: sin pérdidas apreciables'

    out = dict(period_s=p, width_s=width_s, thr=thr, rigol=rst, pulso=pm,
               hw=alive, observed_n=len(events), duration_s=dur_s,
               efficiency=eff, snap_sw=snap_sw, cobertura_ok=cobertura_ok,
               hw_dt_med_us=float(np.median(dt_hw)) if dt_hw.size else float('nan'),
               veredicto=veredicto)

    if verbose:
        print(f'--- diagnose_point p={p*1e6:g} µs ---')
        print(f'  1. Rigol      : freq={rst["freq"]:.6g} Hz  width={rst["width"]:.3g} s  '
              f'outp={rst["outp"]:.0f}  err={rst["err"]}')
        print(f'  2. Señal IN1  : n_pulsos={pm["n_pulsos"]}  v_max={pm["v_max"]:.3f} V  '
              f'ancho={pm["ancho_med_ns"]:.0f} ns  período={pm["periodo_med_us"]:.3f} µs')
        print(f'  3. FPGA       : alive={alive["alive"]}  cambios de wp_trig={alive["n_cambios"]}'
              f'  dt_hw={alive["dt_hw_med_us"]:.3f} µs  '
              f'dis_act={alive["dis_act"]:#x}  we_keep={alive["we_keep"]:#x}  '
              f'mask={alive["mask_ch0"]:#010x}  snap={decode_snap(alive["snapshot"])}')
        print(f'  4. SW         : n={len(events)}  eff={eff*100:.1f}%  '
              f'dt_hw={out["hw_dt_med_us"]:.3f} µs')
        print(f'  => {veredicto}')

    _save(save, f'dt_diag_p{_fmt(p*1e6)}us',
          meta={'period_s': p, 'width_s': width_s, 'thr': thr,
                'veredicto': veredicto, 'efficiency': eff,
                **_flat_meta('rigol', rst), **_flat_meta('pulso', pm),
                **_flat_meta('hw', alive)},
          d1=d1, d2=d2,
          t_ns=np.array([e['t_ns'] for e in events], dtype=np.int64),
          wp=np.array([e['wp'] for e in events], dtype=np.int32),
          dt_hw_us=dt_hw)
    return out


def sweep_pulse_width(sc, rg, widths_s, ch=1, period_s=1e-3, thr=0.3,
                      hyst=0.01, settle_s=0.2, n_events=50, timeout_ms=500,
                      raw_period_s=20e-6, save=None, verbose=True):
    """**Resolución par-pulso del camino de trigger** — sin Python en el lazo.

    Un pulso de ancho W genera un flanco de subida y uno de bajada separados
    *exactamente* por W. Armando con `OR_MASK = BIT_ADC_P0 | BIT_ADC_N0`, el
    `trig_snapshot` (@0x218) guarda cuál fue el ÚLTIMO evento aceptado:

      snapshot con adc_n0  ->  se aceptaron los dos flancos separados por W
      snapshot con adc_p0  ->  el de bajada cayó dentro del dead-time

    Barriendo W de µs a decenas de ns, el W donde el snapshot cambia de `adc_n0`
    a `adc_p0` **es** la resolución par-pulso del stack (esperado ~25-30 ns:
    re-arm del trigger ~24 ns + ancho de banda analógica).

    El generador va a tasa cómoda (`period_s`, 1 kHz por default): el resultado
    NO depende de la velocidad del polling, que es justamente el punto.

    Cross-check independiente por Δwp: si se aceptan los dos flancos, los
    intervalos dejan de ser múltiplos exactos del período y aparece un residuo
    de ±W. `resid_med_ns` lo reporta.

    OJO con el umbral: a W chico el pulso no llega a amplitud plena (BW ~50 MHz
    de la entrada), por eso el default baja a thr=0.3 V. `amp_pp`/`v_max` de
    cada punto dicen si el codo es dead-time real o el pulso que se apagó. Esa
    medición de forma se hace a `raw_period_s` (20 µs) y no a `period_s`: en la
    ventana del buffer (131 µs) tienen que entrar varios pulsos para poder
    medirlos.
    """
    from multitrigger_utils import BIT_ADC_P0 as _P0, BIT_ADC_N0 as _N0, decode_snap

    mask = _P0 | _N0                       # máscara: bits 1 y 2
    period_us = period_s * 1e6
    results = []
    for w in widths_s:
        rg.set_pulse_width(ch=ch, width_s=w)

        # La forma del pulso se mide a una tasa en la que ENTREN varios en el
        # buffer: la ventana es de N_BUF samples (131 µs con decim=1), así que a
        # 1 kHz normalmente no hay ningún pulso adentro y v_max no diría nada.
        rg.set_pulse_period(ch=ch, period_s=raw_period_s)
        time.sleep(settle_s)
        d1, d2, _ = sc.acq_capture_sw(thr=thr)
        pm = pulse_metrics(d1, thr=thr)

        # ...y la medición de trigger, a la tasa cómoda (el SW no participa)
        rg.set_pulse_period(ch=ch, period_s=period_s)
        time.sleep(settle_s)
        rst = rigol_state(rg, ch)

        sc.arm_for_adc_trigger(mask_ch0=mask, mask_ch1=mask, thr=thr,
                               hyst=hyst, auto_rearm=True)
        # dejar pasar varios pulsos y leer el snapshot SIN carrera de polling:
        # así el último evento registrado es el del último pulso completo.
        time.sleep(max(0.05, 20 * period_s))
        snap = sc.r32(OFF_SNAPSHOT)
        events, dur_s = sc.capture_n_events(n=n_events, timeout_ms=timeout_ms,
                                            read_snap=True)
        sc.disarm()

        dt_hw = events_to_hw_intervals(events)
        # residuo respecto del período, plegado a [-T/2, T/2)
        resid = ((dt_hw + period_us / 2) % period_us) - period_us / 2 if dt_hw.size else np.array([])
        # OJO: el snapshot usa OTRO layout de bits que la máscara (ver
        # SNAP_ADC_N0 arriba); en la máscara adc_n0 es el bit 2, en el snapshot
        # el bit 5.
        snaps = np.array([e['snap'] for e in events], dtype=np.int64)
        frac_n = float(np.mean((snaps & SNAP_ADC_N0) != 0)) if snaps.size else float('nan')

        r = dict(
            width_s      = w,
            width_real_s = rst['width'],
            resuelto     = bool(snap & SNAP_ADC_N0),
            snapshot     = int(snap),
            snap_txt     = decode_snap(snap),
            frac_n0      = frac_n,
            resid_med_ns = float(np.median(np.abs(resid)) * 1000.0) if resid.size else float('nan'),
            n_events     = len(events),
            v_max        = pm['v_max'],
            amp_pp       = pm['amp_pp'],
            ancho_med_ns = pm['ancho_med_ns'],
            cruza_umbral = pm['cruza_umbral'],
            rigol        = rst,
            pulso        = pm,
        )
        results.append(r)

        _save(save, f'dt_width_w{_fmt(w*1e9)}ns',
              meta={'width_s': w, 'period_s': period_s, 'thr': thr, 'hyst': hyst,
                    'mask': mask, 'snapshot': int(snap), 'resuelto': r['resuelto'],
                    **_flat_meta('rigol', rst), **_flat_meta('pulso', pm)},
              d1=d1,
              t_ns=np.array([e['t_ns'] for e in events], dtype=np.int64),
              wp=np.array([e['wp'] for e in events], dtype=np.int32),
              snap=snaps, dt_hw_us=dt_hw, resid_us=resid)

        if verbose:
            print(f'W={w*1e9:>8.1f} ns (real {rst["width"]*1e9:>8.1f})  '
                  f'snap={decode_snap(snap)}  resuelto={"SI" if r["resuelto"] else "no"}  '
                  f'frac_n0={frac_n:>5.2f}  resid={r["resid_med_ns"]:>7.1f} ns  '
                  f'v_max={pm["v_max"]:.3f} V  ancho_medido={pm["ancho_med_ns"]:.0f} ns')

    if save is not None and results:
        _save(save, 'dt_width_summary', meta={'period_s': period_s, 'thr': thr},
              width_s=np.array([r['width_s'] for r in results], dtype=float),
              width_real_s=np.array([r['width_real_s'] for r in results], dtype=float),
              resuelto=np.array([r['resuelto'] for r in results], dtype=bool),
              frac_n0=np.array([r['frac_n0'] for r in results], dtype=float),
              resid_med_ns=np.array([r['resid_med_ns'] for r in results], dtype=float),
              v_max=np.array([r['v_max'] for r in results], dtype=float),
              amp_pp=np.array([r['amp_pp'] for r in results], dtype=float),
              ancho_med_ns=np.array([r['ancho_med_ns'] for r in results], dtype=float))

    res_ok = [r['width_s'] for r in results if r['resuelto']]
    if verbose and res_ok:
        print(f'\nAncho mínimo con los dos flancos resueltos: {min(res_ok)*1e9:.1f} ns '
              f'=> resolución par-pulso ≈ {min(res_ok)*1e9:.1f} ns')
    elif verbose:
        print('\nNingún ancho resolvió los dos flancos (revisar umbral/amplitud).')
    return results


# ---------- ploteo ----------

def plot_deadtime_curve(results):
    """Eficiencia y dt (SW vs HW) contra la distancia entre pulsos.

    El panel del medio es el que separa las dos causas: si `dt_hw` sigue la
    diagonal y `dt_sw` se despega, el dead-time es del software.
    """
    from matplotlib import pyplot as plt

    exp_dt  = np.array([r['expected_dt_us'] for r in results])
    effs    = np.array([r['efficiency'] for r in results])
    dt_sw   = np.array([r['mean_dt_us'] for r in results])
    dt_hw   = np.array([r['hw_dt_med_us'] for r in results])
    miss    = np.array([r['n_saltados_med'] for r in results])
    alive   = np.array([r['hw_alive'] for r in results])

    fig, ax = plt.subplots(1, 3, figsize=(16, 4))
    ax[0].semilogx(exp_dt, effs * 100, 'o-')
    ax[0].axhline(100, color='gray', ls=':')
    ax[0].axhline(95, color='orange', ls='--', label='95 %')
    if (~alive).any():
        ax[0].semilogx(exp_dt[~alive], effs[~alive] * 100, 'rx', ms=10,
                       label='FPGA sin disparar')
    ax[0].set_xlabel('distancia esperada entre pulsos (µs)')
    ax[0].set_ylabel('eficiencia SW (%)')
    ax[0].set_title('Eficiencia del stack SW')
    ax[0].invert_xaxis(); ax[0].grid(True, which='both'); ax[0].legend()

    ax[1].loglog(exp_dt, dt_sw, 'o-', label='dt SW (reloj Python)')
    ax[1].loglog(exp_dt, dt_hw, 's-', label='dt HW (Δwp_trig, 8 ns)')
    ax[1].plot(exp_dt, exp_dt, 'k--', alpha=0.5, label='ideal y=x')
    ax[1].set_xlabel('dt esperado (µs)'); ax[1].set_ylabel('dt medido (µs)')
    ax[1].set_title('Medido vs esperado')
    ax[1].grid(True, which='both'); ax[1].legend()

    ax[2].semilogx(exp_dt, miss, 'o-')
    ax[2].set_xlabel('distancia esperada entre pulsos (µs)')
    ax[2].set_ylabel('disparos perdidos entre observaciones')
    ax[2].set_title('Lo que se pierde el polling')
    ax[2].invert_xaxis(); ax[2].grid(True, which='both')

    plt.tight_layout(); plt.show()

    ok = effs > 0.95
    if ok.any():
        dt_min = exp_dt[ok].min()
        print(f'Distancia mínima con eficiencia >95 %: {dt_min:.2f} µs '
              f'(= piso del método, no del FPGA)')
    else:
        print('Ninguna distancia superó 95 % de eficiencia.')


def plot_width_curve(results):
    """Curva de resolución par-pulso: flancos resueltos vs ancho del pulso."""
    from matplotlib import pyplot as plt

    w_ns  = np.array([r['width_s'] * 1e9 for r in results])
    ok    = np.array([r['resuelto'] for r in results], dtype=float)
    fr    = np.array([r['frac_n0'] for r in results], dtype=float)
    vmax  = np.array([r['v_max'] for r in results], dtype=float)

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.semilogx(w_ns, ok, 'o-', label='snapshot = adc_n0 (resuelto)')
    ax.semilogx(w_ns, fr, 's--', alpha=0.7, label='fracción de eventos con adc_n0')
    ax.set_xlabel('ancho del pulso W (ns)  = separación entre los dos flancos')
    ax.set_ylabel('resuelto'); ax.set_ylim(-0.05, 1.05)
    ax.grid(True, which='both'); ax.legend(loc='center left')

    ax2 = ax.twinx()
    ax2.semilogx(w_ns, vmax, '^:', color='tab:red', alpha=0.6)
    ax2.set_ylabel('v_max del pulso (V)', color='tab:red')

    ax.set_title('Resolución par-pulso (posedge vs negedge del mismo pulso)')
    plt.tight_layout(); plt.show()
