"""Réplica del MCA2 (las ranuras) para el Monte Carlo: el disparo y la medición.

Corre en la PC, sin placa. Es lo que `pileup.py` es para el MCA1, pero del
mapa "MCA2" (`docs/mca/register_map_mca.md`):

  - LA VENTANA LA ABRE EL MULTITRIGGER. El disparo por pendiente de
    `mt_slope_trig.sv` (un trapezoidal rápido con su Schmitt) o el disparo con
    polo-cero de `mt_pz_trig.sv` (un trapecio corto de `mca_trap.sv`, que no ve
    la cola de los pulsos anteriores) llega al MCA como `trig_i`; el MCA retrasa
    la muestra `pre_dly` ciclos para que la ventana abra en el pie del pulso.
  - LA CIERRA LA COMPUERTA LARGA: `gate_long` muestras desde el disparo, pase lo
    que pase con la señal. La cola arranca en `gate_short`.
  - VARIAS RANURAS MIDEN A LA VEZ. Un disparo abre la ranura libre de menor
    índice; si no hay, se pierde (`lost_active` si todas están midiendo,
    `lost_busy` si alguna espera al publicador). El publicador (los divisores de
    forma, 18 ciclos) es uno solo y atiende en orden de cierre.
  - LO QUE SE SOLAPA SE MARCA, NO SE CORRIGE: `F_SOLAPE` dice cuántas ventanas
    había abiertas al abrir, si llegó otro disparo adentro y si alguno se
    perdió; `F_DTPREV`/`F_DTNEXT` dicen a qué distancia. La corrección es el
    trapecio (`F_TRAP`), que se lee en una ventana de la meseta.
  - EL BANCO DE TRAPECIOS ELIGE LA FORMA AL PUBLICAR. Cada ranura mide las
    `n_formas` a la vez; gana la primera con `antes <= F_DTPREV` y
    `despues <= F_DTNEXT`, la más larga cuya ventana no alcanza al vecino. Si
    ninguna cumple, el pulso queda marcado: `F_TRAP` = 0 y `F_FORMA` = 0xFFFF.

QUÉ ES LA REFERENCIA
--------------------
La semántica sale del MODELO de `modulos/mca/sim/tb_mca_multi.sv`, que el TB
compara ciclo a ciclo contra `mca_pulse_feature.sv`, y del RTL de
`mt_slope_trig.sv` y `mt_pz_trig.sv`. Esta réplica además se compara EVENTO POR EVENTO contra el
RTL entero (`mt_top` + `mca_top`, como en el top) con el volcado de
`sim/tb_mca2_volcado.sv`: `test_replica_mca2.py`.

CÓMO ES RÁPIDA
--------------
Las features de una ventana dependen sólo de las muestras, así que se calculan
vectorizadas para TODOS los disparos antes de decidir cuáles abren. Lo único
secuencial es el asignador de ranuras, y es un lazo por disparo, no por
muestra.

LO QUE NO SE MODELA
-------------------
  - El seguidor de línea de base: la base es fija (`baseline`), como en el
    barrido de `montecarlo.py`.
  - El veto del shield y la decimación: no se usan en el Monte Carlo.
  - Dos disparos a menos de 3 muestras: el multitrigger se deshabilita un ciclo
    después de disparar. Con la histéresis del Schmitt no pasa; si pasara, el
    volcado lo mostraría.
  - El arranque del disparo con polo-cero: la traza empieza en base quieta con
    su línea ya llena.
"""

import numpy as np

# --- constantes del RTL ------------------------------------------------------
SAT16    = 0xFFFF
N_ACC_RTL = 4             # ranuras con que se sintetizan los tops
SERV     = 18             # ciclos del publicador con EN_PSD (los dos divisores)
TLAT     = 8              # latencia de mca_trap, en muestras
LAT_MCA  = 2              # registro de entrada + salida de la línea de retardo
# Ciclos desde la muestra en que s cruza el umbral hasta que `trig_i` sube, tal
# como lo ve el MCA: las tres etapas de mt_slope_trig, su Schmitt y su salida,
# y el registro de mt_trig_src. Medido en el volcado de sim/tb_mca2_volcado.sv
# (los 571 disparos, la misma latencia).
LAT_MT   = 6
# Lo mismo con el polo-cero, desde la muestra cuyo trapecio cruza: la latencia de
# mca_trap, el Schmitt y su salida, y el registro de mt_trig_src.
LAT_PZ   = 11
PZ_LMAX  = 31             # las líneas de retardo de mt_pz_trig: 2^5 - 1
N_FORMAS_RTL = 4          # formas del banco con que se sintetizan los tops
MARCADO  = 0xFFFF         # F_FORMA de un pulso que ninguna forma alcanzó
PSD_AW   = 6
DIV_W    = 16
T_MAX, T_MIN = 131071, -131072      # saturación de la salida del trapecio

# índices del bus de features (los F_* de mca_pulse_feature.sv)
F_PEAK, F_INT, F_PSD, F_INVW, F_LEN, F_TRISE = 0, 1, 2, 3, 4, 5
F_DTPREV, F_DTNEXT, F_SOLAPE, F_TRAP, F_FORMA = 6, 7, 8, 9, 10
N_FEAT = 11

# La configuración de la campaña (testbench_mca.DEFAULT_CFG / DISPARO): el
# disparo validado en placa para el pulso de 2 µs, y la compuerta de 384.
CFG = dict(n_acc=1, gate_short=32, gate_long=384, pre_dly=16, amp_src=0,
           q_shift=0, amp_min=0, amp_max=SAT16, baseline=0,
           L=8, G=4, thr=600, hyst=300,
           trap=True, trap_k=64, trap_m=32, trap_mq=0, trap_off=72,
           trap_lw=4, trap_sh=7,
           # el banco en el reset del RTL (mca_top.sv): una forma en uso. Los
           # nombres son los de mca_configure, así `cfg(**mca_banco_config(mq))`
           # es lo mismo que en la placa.
           n_formas=1, trap_antes=0, trap_despues=0,
           forma1_k=32, forma1_m=16, forma1_off=40, forma1_lw=3, forma1_sh=6,
           forma1_antes=0, forma1_despues=0,
           forma2_k=16, forma2_m=8, forma2_off=22, forma2_lw=2, forma2_sh=5,
           forma2_antes=0, forma2_despues=0,
           forma3_k=8, forma3_m=4, forma3_off=13, forma3_lw=1, forma3_sh=4,
           forma3_antes=0, forma3_despues=0,
           # el disparo: 'pendiente' (L, G, thr, hyst) o 'pz'
           fuente='pendiente', pz_k=2, pz_m=1, pz_mq=3992, pz_sh=10,
           pz_thr=353, pz_hyst=177)


def cfg(**kw):
    """CFG con lo que se pida cambiado. Rechaza claves que no existen."""
    malas = set(kw) - set(CFG)
    if malas:
        raise KeyError(f'claves que la réplica no conoce: {sorted(malas)}')
    return {**CFG, **kw}


def formas_en_uso(c):
    """Las formas que el publicador mira, [(k, m, off, lw, sh, antes, despues)]:
    `n_formas`, con el recorte de `nf_hab` en mca_top.sv (0 es 1, satura arriba)."""
    nf = min(max(int(c['n_formas']), 1), N_FORMAS_RTL)
    out = [tuple(int(c[f'trap_{n}']) for n in ('k', 'm', 'off', 'lw', 'sh', 'antes', 'despues'))]
    for f in range(1, nf):
        out.append(tuple(int(c[f'forma{f}_{n}'])
                         for n in ('k', 'm', 'off', 'lw', 'sh', 'antes', 'despues')))
    return out


# =============================================================================
# 1. El disparo por pendiente (mt_slope_trig.sv)
# =============================================================================

def pendiente(x, L=8, G=4):
    """s[n] = Σ_{i<L} x[n-i] − Σ_{i<L} x[n-L-G-i], exacto en enteros.

    Es el trapezoidal rápido del multitrigger. Antes del principio de `x` se
    supone que hubo ceros con la línea ya llena, que es lo que pasa cuando la
    traza arranca con base quieta (el volcado y los renders del Monte Carlo
    arrancan así). `L` se satura a 1..16 y `G` a 0..31, como el RTL.
    """
    L = min(max(int(L), 1), 16)
    G = min(max(int(G), 0), 31)
    x = np.asarray(x, dtype=np.int64)
    c = np.concatenate((np.zeros(1, np.int64), np.cumsum(x)))
    n = np.arange(x.size, dtype=np.int64)

    def suma(fin):                       # Σ x[fin-L+1 .. fin], ceros antes
        hi = np.clip(fin + 1, 0, x.size)
        lo = np.clip(fin + 1 - L, 0, x.size)
        return c[hi] - c[lo]

    return suma(n) - suma(n - L - G)


def schmitt(s, thr, hyst):
    """Muestras en que el Schmitt del disparo pasa de 0 a 1.

    `s >= thr` lo prende (y gana si las dos valen), `s < thr - hyst` lo re-arma.
    Arranca re-armado: la traza empieza en base quieta. Es el mismo en
    `mt_slope_trig.sv` (sobre `s`) y en `mt_pz_trig.sv` (sobre su trapecio).
    """
    s = np.asarray(s, dtype=np.int64)
    thr, rearm = int(thr), int(thr) - int(hyst)
    hi = np.flatnonzero(s >= thr)
    lo = np.flatnonzero(s < rearm)
    out = []
    pos = 0
    while True:
        j = np.searchsorted(hi, pos)
        if j >= hi.size:
            break
        f = int(hi[j])
        out.append(f)
        k = np.searchsorted(lo, f + 1)
        if k >= lo.size:
            break
        pos = int(lo[k]) + 1
    return np.asarray(out, dtype=np.int64)


def flancos_trig(x, c):
    """Los ciclos en que el MCA ve subir `trig_i`, en el índice de `x`."""
    if c['fuente'] == 'pz':
        y = trapecio(x, c['pz_k'], c['pz_m'], c['pz_mq'], c['pz_sh'], lmax=PZ_LMAX)
        return schmitt(y, c['pz_thr'], c['pz_hyst']) + LAT_PZ
    s = pendiente(x, c['L'], c['G'])
    return schmitt(s, c['thr'], c['hyst']) + LAT_MT


# =============================================================================
# 2. El trapecio (mca_trap.sv)
# =============================================================================

def trapecio(v, k, m, mq, sh, saturar=True, lmax=1023):
    """Salida del trapecio alineada con cada muestra de entrada (sin TLAT).

    La recursión de Jordanov-Knoll en enteros, la misma del modelo de
    `tb_mca_multi`: d = v[n] − v[n−k] − v[n−l] + v[n−k−l], p += d,
    s += 16·p + Mq·d, y la salida es s >> sh saturada a 18 bits. `k = 0` vale 1,
    y `k` y `l = k + m` se saturan a `lmax` (1023 en `mca_top`, 31 en
    `mt_pz_trig`). `saturar=False` devuelve la salida sin recortar, para medir
    la forma.
    """
    k = min(1 if int(k) == 0 else int(k), int(lmax))
    l = min(k + int(m), int(lmax))
    v = np.asarray(v, dtype=np.int64)

    def atras(a):
        out = np.zeros_like(v)
        if a < v.size:
            out[a:] = v[:v.size - a]
        return out

    d = v - atras(k) - atras(l) + atras(k + l)
    p = np.cumsum(d)
    s = np.cumsum(p * 16 + int(mq) * d) >> int(sh)
    return np.clip(s, T_MIN, T_MAX) if saturar else s


# =============================================================================
# 3. Las features de cada ventana, para todos los disparos a la vez
# =============================================================================

def _features(x, c_trig, c, bloque=8192):
    """Features de la ventana que ABRIRÍA cada disparo, sin decidir cuáles abren.

    La ventana del disparo que el MCA ve en el ciclo `t` empieza en la muestra
    `t − pre_dly − 2` y tiene `gate_long` muestras. Devuelve arrays por
    disparo; `completa` es False si la ventana no entra en la traza.
    """
    g_l = max(int(c['gate_long']), 1)
    g_s = max(int(c['gate_short']), 1)        # la primera muestra nunca es cola
    base = int(c['baseline'])
    xv = np.asarray(x, dtype=np.int64) - base
    xc = np.maximum(xv, 0)
    n = c_trig.size
    s0 = c_trig - int(c['pre_dly']) - LAT_MCA
    completa = (s0 >= 0) & (s0 + g_l <= xv.size)

    pico = np.zeros(n, np.int64)
    t_pico = np.zeros(n, np.int64)
    q_tot = np.zeros(n, np.int64)
    q_tail = np.zeros(n, np.int64)

    # Una por forma: cada trapecio corre sobre la misma muestra, con el M común.
    formas = formas_en_uso(c)
    tsum = np.zeros((n, len(formas)), np.int64)
    trap_ok = []
    T = []
    for k_f, m_f, off, lw, sh, _, _ in formas:
        ok_f = bool(c['trap']) and off + TLAT + (1 << lw) <= g_l and off + TLAT <= SAT16
        trap_ok.append(ok_f)
        T.append(trapecio(xv, k_f, m_f, c['trap_mq'], sh) if ok_f else None)

    idx = np.flatnonzero(completa)
    off = np.arange(g_l, dtype=np.int64)
    for a in range(0, idx.size, bloque):
        ii = idx[a:a + bloque]
        w = xc[s0[ii, None] + off]
        pico[ii] = w.max(axis=1)
        t_pico[ii] = w.argmax(axis=1)            # primera ocurrencia: `>` estricto
        q_tot[ii] = w.sum(axis=1)
        q_tail[ii] = w[:, g_s:].sum(axis=1) if g_s < g_l else 0
        for f, (_, _, off, lw, _, _, _) in enumerate(formas):
            if trap_ok[f]:
                # j en [off + TLAT, off + TLAT + 2^lw) ve la salida de TLAT
                # muestras antes: las muestras s0+off .. del trapecio
                tsum[ii, f] = T[f][s0[ii, None] + off + np.arange(1 << lw)].sum(axis=1)
    return dict(s0=s0, completa=completa, pico=pico, t_pico=t_pico,
                q_tot=q_tot, q_tail=q_tail, tsum=tsum, trap_ok=trap_ok)


def _amp_int(q_tot, q_shift):
    return np.minimum(np.asarray(q_tot, np.int64) >> int(q_shift), SAT16)


def _cociente(num, den):
    """floor(num·2^16 / den), el divisor restaurador con num < den."""
    num = np.asarray(num, np.int64)
    den = np.asarray(den, np.int64)
    return np.where(den > 0, (num << DIV_W) // np.maximum(den, 1), 0)


# =============================================================================
# 4. Las ranuras y el publicador
# =============================================================================

ABRE, LOST_ACTIVE, LOST_BUSY = 0, 1, 2


def _ranuras(c_trig, ok, g_l, nh, serv=SERV):
    """El asignador del modelo de tb_mca_multi, un paso por disparo.

    Para cada disparo en el ciclo t: la ranura habilitada libre de menor índice
    lo toma. Una ranura que abre en t está ocupada desde t+1; cierra en
    C = t + g_l + 1 (procesa la muestra g_l y la descarta). Si la amplitud no
    entra, queda libre desde C+1. Si entra, espera al publicador: arranca en
    max(C, fin_anterior + 1), emite 18 ciclos después (E) y la ranura queda
    libre desde E+1. Mientras espera o se publica está CERRADA, y un disparo
    sin ranura libre con alguna CERRADA es `lost_busy`; sin ninguna,
    `lost_active`.

    Devuelve (estado, ranura, cierre, emite, libre, otras) por disparo.
    """
    n = c_trig.size
    estado = np.full(n, ABRE, np.int8)
    ranura = np.full(n, -1, np.int64)
    cierre = np.full(n, -1, np.int64)
    emite = np.full(n, -1, np.int64)
    libre = np.full(n, -1, np.int64)
    otras = np.zeros(n, np.int64)

    free_at = [0] * nh           # ciclo desde el que la ranura está libre
    c_abierta = [-1] * nh        # cierre de la ventana en curso (si abierta)
    cerr_ini = [1] * nh          # intervalo CERRADA [ini, fin] de la ranura
    cerr_fin = [0] * nh
    pub_sig = 0                  # primer ciclo en que el publicador puede arrancar
    for i in range(n):
        t = int(c_trig[i])
        k = -1
        for j in range(nh):
            if free_at[j] <= t:
                k = j
                break
        if k < 0:
            ocupada = any(cerr_ini[j] <= t <= cerr_fin[j] for j in range(nh))
            estado[i] = LOST_BUSY if ocupada else LOST_ACTIVE
            continue
        otras[i] = min(sum(1 for j in range(nh) if c_abierta[j] >= t), 15)
        C = t + g_l + 1
        ranura[i], cierre[i] = k, C
        c_abierta[k] = C
        if ok[i]:
            T = max(C, pub_sig)
            E = T + serv
            pub_sig = E + 1
            emite[i] = E
            free_at[k] = E + 1
            cerr_ini[k], cerr_fin[k] = C + 1, E
        else:
            free_at[k] = C + 1
            cerr_ini[k], cerr_fin[k] = 1, 0
        libre[i] = free_at[k]
    return estado, ranura, cierre, emite, libre, otras


# =============================================================================
# 5. La medición entera
# =============================================================================

def medir(x, c=None, trig=None, hasta=None):
    """El MCA2 sobre una traza: disparos, ventanas, eventos y contadores.

    `x` son las muestras del ADC (enteros), `c` la configuración (ver `CFG`).
    `trig` permite pasar los ciclos de `trig_i` ya calculados (si no, salen del
    disparo por pendiente sobre la misma `x`). `hasta` es el último ciclo con
    `run` (por defecto, el fin de la traza): los disparos después no cuentan.

    Devuelve un dict:
      trig        ciclos de los flancos de trig_i
      estado      por disparo: ABRE, LOST_ACTIVE o LOST_BUSY
      ev          las ventanas que ABRIERON y cerraron adentro de la traza,
                  con sus features, `ok` (la amplitud entró) y `emite`
      eventos     las publicadas, en orden: amp, psd, psd_ok y feat[0..10]
      cnt         los contadores del RTL
      t_ocup      ciclos con j ranuras ocupadas, j = 0..N_ACC_RTL
    """
    c = CFG if c is None else c
    x = np.asarray(x, dtype=np.int64)
    hasta = x.size if hasta is None else int(hasta)
    t = flancos_trig(x, c) if trig is None else np.asarray(trig, np.int64)
    t = t[t < hasta]

    g_l = max(int(c['gate_long']), 1)
    nh = min(max(int(c['n_acc']), 1), N_ACC_RTL)
    f = _features(x, t, c)
    amp_int = _amp_int(f['q_tot'], c['q_shift'])
    amp = amp_int if c['amp_src'] else f['pico']
    ok = (amp >= int(c['amp_min'])) & (amp <= int(c['amp_max']))

    estado, ranura, cierre, emite, libre, otras = _ranuras(t, ok, g_l, nh)
    abre = estado == ABRE
    perdido_d = estado != ABRE

    # dt_anterior: desde el disparo anterior (cualquiera), saturado
    dtprev = np.full(t.size, SAT16, np.int64)
    if t.size > 1:
        dtprev[1:] = np.minimum(np.diff(t), SAT16)
    # adentro / dt_siguiente / perdido: disparos en [t+1, t+g_l-1]
    j1 = np.searchsorted(t, t + 1)
    j2 = np.searchsorted(t, t + g_l - 1, side='right')
    adentro = j2 > j1
    dtnext = np.where(adentro, t[np.minimum(j1, t.size - 1)] - t, SAT16)
    cum_perd = np.concatenate(([0], np.cumsum(perdido_d)))
    perdido = (cum_perd[j2] - cum_perd[j1]) > 0

    cerro = abre & f['completa'] & (cierre < x.size)
    sel = np.flatnonzero(cerro)

    # La forma: la primera en uso cuyos umbrales cumple. Sin ninguna, marcado.
    formas = formas_en_uso(c)
    forma = np.full(t.size, MARCADO, np.int64)
    trap = np.zeros(t.size, np.int64)
    for k in range(len(formas) - 1, -1, -1):
        _, _, _, lw, _, antes, despues = formas[k]
        gana = (antes <= dtprev) & (despues <= dtnext)
        forma[gana] = k
        trap[gana] = (np.clip(f['tsum'][gana, k] >> lw, 0, SAT16)
                      if f['trap_ok'][k] else 0)

    psd_ok = (f['q_tot'] != 0) & (f['q_tail'] < f['q_tot'])
    feat = np.zeros((t.size, N_FEAT), np.int64)
    feat[:, F_PEAK] = f['pico'] << 2
    feat[:, F_INT] = amp_int
    feat[:, F_PSD] = np.where(psd_ok, _cociente(f['q_tail'], f['q_tot']), 0)
    feat[:, F_INVW] = np.where(f['q_tot'] == 0, 0,
                               np.where(f['pico'] >= f['q_tot'], SAT16,
                                        _cociente(f['pico'], f['q_tot'])))
    feat[:, F_LEN] = g_l
    feat[:, F_TRISE] = f['t_pico']
    feat[:, F_DTPREV] = dtprev
    feat[:, F_DTNEXT] = dtnext
    feat[:, F_SOLAPE] = (perdido.astype(np.int64) << 5) | (adentro.astype(np.int64) << 4) | otras
    feat[:, F_TRAP] = trap
    feat[:, F_FORMA] = forma

    ev = dict(i=sel, t=t[sel], s0=f['s0'][sel], ok=ok[sel], emite=emite[sel],
              ranura=ranura[sel], pico=f['pico'][sel], q_tot=f['q_tot'][sel],
              q_tail=f['q_tail'][sel], t_pico=f['t_pico'][sel], amp=amp[sel],
              psd_ok=psd_ok[sel], feat=feat[sel], otras=otras[sel],
              adentro=adentro[sel], perdido=perdido[sel],
              dtprev=dtprev[sel], dtnext=dtnext[sel], trap=trap[sel], forma=forma[sel])
    pub = sel[ok[sel]]
    pub = pub[np.argsort(emite[pub], kind='stable')]
    eventos = dict(emite=emite[pub], amp=amp[pub],
                   psd=np.where(psd_ok[pub], feat[pub, F_PSD] >> (DIV_W - PSD_AW), 0),
                   psd_ok=psd_ok[pub], feat=feat[pub], i=pub)

    pile = (otras[sel] != 0) | adentro[sel]
    cnt = dict(trig=int(t.size), cross=int(t.size), open=int(abre.sum()),
               lost_active=int((estado == LOST_ACTIVE).sum()),
               lost_busy=int((estado == LOST_BUSY).sum()), lost_veto=0,
               windows=int(abre.sum()), total=int(sel.size),
               rej_amp=int((~ok[sel]).sum()), pileup=int(pile.sum()),
               accepted=int(pub.size), rej_psd=int((~psd_ok[pub]).sum()))

    # ocupación: cada ventana ocupa su ranura en [t+1, libre-1]
    occ = np.zeros(x.size + 2, np.int64)
    a_idx = np.flatnonzero(abre)
    ini = np.minimum(t[a_idx] + 1, x.size)
    fin = np.minimum(libre[a_idx], x.size)
    np.add.at(occ, ini, 1)
    np.add.at(occ, fin, -1)
    n_ocup = np.cumsum(occ)[:hasta]
    t_ocup = np.bincount(n_ocup, minlength=N_ACC_RTL + 1)[:N_ACC_RTL + 1]

    return dict(trig=t, estado=estado, ev=ev, eventos=eventos, cnt=cnt,
                t_ocup=t_ocup, cfg=dict(c))


# =============================================================================
# 6. Para el Monte Carlo: el disparo y el trapecio de una forma, y los eventos
# =============================================================================

def forma_preamp(tau=250.0, tr10=1.2, n=2048):
    """El pulso para el que está pensado el banco: el del preamplificador.

    Sube en ~`tr10` muestras (10-90 %), y cae con `tau`. Es el del Rigol en
    `etapa_banco_rtl` de `test_mca2_placa.py`, normalizado al pico. Nada que ver
    con la semi-gaussiana de 2 µs de `pileup.forma_referencia`, que tarda ~100
    muestras en subir: con ésa no hay meseta para k = 8.
    """
    t = np.arange(int(n), dtype=float)
    f = (1.0 - np.exp(-t / (float(tr10) / 2.197))) * np.exp(-t / float(tau))
    return f / f.max()


def disparo_pz_para(forma, mq, a_umbral=50.0, k=2, m=1, sh=10, pre_dly=16):
    """Umbral del disparo con polo-cero para una forma, en la salida del trapecio.

    `a_umbral` son cuentas de amplitud, como `thr_cuentas` de
    `multitrigger_armar_mca`; el re-armado, en la mitad.
    """
    f = np.asarray(forma, dtype=float)
    esc = 1 << 16
    y = trapecio(np.round(f * esc).astype(np.int64), k, m, mq, sh, saturar=False, lmax=PZ_LMAX)
    thr = max(1, int(round(float(y.max()) / esc * float(a_umbral))))
    return dict(fuente='pz', pz_k=int(k), pz_m=int(m), pz_mq=int(mq), pz_sh=int(sh),
                pz_thr=thr, pz_hyst=thr // 2, pre_dly=int(pre_dly))


def disparo_para(forma, a_umbral=100.0, L=8, G=4, margen=4, sigma=2.8, a_pre=None):
    """Umbral, histéresis y `pre_dly` del disparo por pendiente para una forma.

    El umbral se pone donde un pulso de `a_umbral` cuentas apenas dispara (el
    análogo del `thr = 100` de nivel del MCA1), la histéresis en la mitad, y
    `pre_dly` con la regla de register_map_mca.md: que la ventana abra `margen`
    muestras antes del pie aun para el pulso más chico, que es el que más tarda
    en cruzar (el *walk*).

    Con una forma lenta (la rampa de 250 muestras del triangular) ese umbral cae en
    el ruido de s, que es sigma·sqrt(2L): dispararía solo. Por eso el piso de 7
    sigmas, que a cambio sube la amplitud mínima que se ve.

    `a_pre` es la amplitud para la que se ajusta `pre_dly`, si no es la mínima. Con
    una forma lenta importa: el pulso alto dispara mucho antes que el chico (en la
    CR-RC⁴, 60 muestras entre 100 y 1920 cuentas), así que con el `pre_dly` del
    chico su ventana abre mucho antes del pie, y una compuerta fija cierra en pleno
    flanco. Un barrido a una sola amplitud lo ajusta a esa amplitud.
    """
    f = np.asarray(forma, dtype=float)
    esc = 1 << 16
    s_unit = pendiente(np.round(f * esc).astype(np.int64), L, G).max() / esc
    piso = int(np.ceil(7.0 * float(sigma) * np.sqrt(2.0 * max(int(L), 1))))
    thr = max(1, piso, int(round(s_unit * float(a_umbral))))
    a_umbral = thr / s_unit if s_unit > 0 else float(a_umbral)
    hyst = thr // 2
    pie = 64
    x = np.zeros(pie + f.size, np.int64)
    x[pie:] = np.round(1.02 * float(a_umbral if a_pre is None else a_pre) * f)
    d = schmitt(pendiente(x, L, G), thr, hyst)
    lat = int(d[0]) - pie if d.size else 0
    pre = min(max(lat + LAT_MT - LAT_MCA + int(margen), 0), 127)
    return dict(L=int(L), G=int(G), thr=thr, hyst=hyst, pre_dly=pre)


def trap_para(forma, c, a_ref=2000.0, lw=4, a_max=8191.0):
    """Parámetros del trapecio para una forma: la meseta adentro de la ventana.

    `trap_k`, `trap_m` y `trap_mq` vienen en `c`; acá se eligen `trap_off`, la
    ventana centrada en la meseta medida desde que abre la ventana (el disparo
    corre con la amplitud: centrada aguanta para los dos lados), y `trap_sh`, para
    que el pulso más alto (`a_max`) no sature los 16 bits. Se mide sobre un pulso
    sin ruido pasado por el mismo disparo de la réplica. Si la meseta no entra en
    la compuerta, baja `trap_lw`; si ni así, devuelve None.
    """
    f = np.asarray(forma, dtype=float)
    pie = 256
    x = np.zeros(pie + f.size + 512, np.int64)
    x[pie:pie + f.size] = np.round(float(a_ref) * f)
    t = flancos_trig(x, c)
    if t.size == 0:
        return None
    s0 = int(t[0]) - int(c['pre_dly']) - LAT_MCA
    T = trapecio(x, c['trap_k'], c['trap_m'], c['trap_mq'], 0, saturar=False)
    i_max = int(np.argmax(T))
    meseta = np.flatnonzero(T >= 0.995 * T[i_max])
    ini, fin = int(meseta[0]) - s0, int(meseta[-1]) + 1 - s0
    for w in range(int(lw), -1, -1):
        tw = 1 << w
        tope = int(c['gate_long']) - TLAT - tw      # lo más tarde que entra
        off = min((ini + fin - tw) // 2, tope)
        if off >= max(ini, 0):
            sh = max(0, int(np.ceil(np.log2((T[i_max] * a_max / a_ref + 1) / SAT16))))
            return dict(trap_off=off, trap_lw=w, trap_sh=sh)
    return None


def eventos_mc(x, c):
    """Las ventanas que el MCA2 publica sobre `x`, con las claves de `pileup.py`.

    `i0`, `largo`, `q_tot`, `q_tail`, `pico`, `t_pico` y `cerrado` son las que
    usan las métricas del motor del MCA1; `apilado` es lo que el propio RTL
    marca (`F_SOLAPE ≠ 0`: otra abierta, otro disparo adentro, uno perdido) y
    `i_par` el ciclo del disparo, que es lo que permite aparear cada evento con
    su pulso (la ventana abre ANTES del pulso, el disparo siempre después).
    `forma` es la del banco, `MARCADO` si ninguna alcanzó.
    Devuelve `(ev, cnt)` con los contadores de la réplica.
    """
    m = medir(x, c)
    e = m['ev']
    ok = e['ok']
    ev = dict(i0=e['s0'][ok], i_par=e['t'][ok],
              largo=np.full(int(ok.sum()), max(int(c['gate_long']), 1), np.int64),
              q_tot=e['q_tot'][ok], q_tail=e['q_tail'][ok], pico=e['pico'][ok],
              t_pico=e['t_pico'][ok], trap=e['trap'][ok], forma=e['forma'][ok],
              otras=e['otras'][ok], adentro=e['adentro'][ok], perdido=e['perdido'][ok])
    ev['cerrado'] = np.ones(ev['pico'].size, bool)
    ev['apilado'] = (ev['otras'] != 0) | ev['adentro'] | ev['perdido']
    return ev, m['cnt']


def contar_arribos(ev, loc, antes=None):
    """Pulsos VERDADEROS que tocan la ventana de cada evento (sólo en el MC).

    Con varias ranuras las ventanas se solapan, así que la partición del eje de
    `pileup.contar_arribos` no sirve. Acá un evento es limpio si su pulso es el
    único arribo en `[i0 − antes, i0 + largo)`: nada adentro de la ventana y
    nada en la compuerta anterior, donde la cola de un pulso todavía pesa
    (e^-2 del alto a 384 muestras con tau = 186). `antes` por defecto es el
    largo de la ventana.
    """
    i0 = np.asarray(ev['i0'], np.int64)
    L = np.asarray(ev['largo'], np.int64)
    a = L if antes is None else int(antes)
    loc = np.asarray(loc, np.int64)
    return np.searchsorted(loc, i0 + L) - np.searchsorted(loc, i0 - a)


# =============================================================================
# 7. Modelos de la pérdida por ranuras
# =============================================================================

def erlang_b(n, rho):
    """Probabilidad de bloqueo de un M/G/n/n con carga ofrecida `rho`."""
    b = 1.0
    for k in range(1, int(n) + 1):
        b = rho * b / (k + rho * b)
    return b


def tau_ranura(c, serv=SERV):
    """Ciclos que una ventana aceptada tiene ocupada su ranura, sin esperar:
    la compuerta, el ciclo del cierre y el publicador."""
    return max(int(c['gate_long']), 1) + 1 + serv
