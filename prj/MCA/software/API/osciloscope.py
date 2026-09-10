#!/usr/bin/env python3
"""Osciloscopio clásico del Red Pitaya: configuración, captura y lectura.

Slot 1 del bus de sistema (0x4010_0000). Cubre lo que ya existía en el diseño
original — umbral, decimación, delay, histéresis, filtros, calibración,
punteros de escritura y las aperturas de BRAM — mientras que las máscaras OR,
el trigger_shield y el snapshot que AÑADIÓ este proyecto viven en
`API/multitrigger.py`. Son dos APIs sobre el mismo bloque físico.

    from API.osciloscope import Osciloscope, osciloscope_set_decim
    from API.multitrigger import MultiTrigger, multitrigger_arm

    osc = Osciloscope.open()
    mt  = MultiTrigger.open(osc=osc)
    osciloscope_set_decim(osc, 8)
    multitrigger_arm(osc, mt, thr=0.5)
    eventos, dur = osciloscope_read_events(osc, n=50)

El bring-up de la PL (bitstream, puentes AXI) está en `API/fpga.py`: no es del
osciloscopio, aunque viviera en el mismo fichero por accidente histórico.
"""

import ctypes          # _fb_to_np: envuelve el fBuffer de rp sin copiarlo
import mmap
import os
import struct
import time

import numpy as np

from API.fpga import (                                              # noqa: F401
    BITSTREAM_DEFAULT, FPGA_STATE, FPGA_BRIDGE_DIR,
    fpgautil_bin, fpga_state, fpga_bridges, set_fpga_bridges,
    pl_probe, pl_bus_ready, load_bitstream,
)


class _RpPerezoso:
    """Proxy que importa `rp` en el primer uso, no al importar el módulo.

    La librería de RedPitaya sólo existe en la Pitaya. Con `import rp` arriba,
    este fichero entero era inimportable desde la PC — y con él la
    configuración, los registros y cualquier test offline. Así los cuerpos que
    llaman `rp.rp_AcqGetDataPosV(...)` quedan igual que estaban y el error, si
    falta, sale donde se usa y no donde se importa.
    """

    def __getattr__(self, nombre):
        import rp as _real
        globals()['rp'] = _real          # se auto-reemplaza: sin coste después
        return getattr(_real, nombre)


rp = _RpPerezoso()



SCOPE_PHYS = 0x4010_0000
SCOPE_SIZE = 0x30000
N_BUF      = 16384
FS         = 125e6                # Hz, sampling rate con decim=1

ADC_CNT_PER_V = 8192              # escala LV (±1 V): cuentas por volt
DEC_LEGAL     = (1, 8, 64, 1024, 8192, 65536)

# struct precompilado para los accesos al mmap: `unpack_from`/`pack_into` no
# alocan el slice intermedio ni re-parsean el formato en cada llamada, que es
# lo que domina el costo del loop de polling de capture_n_events.
_U32 = struct.Struct('<I')

# valores de reset usados como sanity check del bus (existen también en el
# scope stock — necesarios pero NO suficientes para identificar el diseño)
RESET_SET_DEC    = 1
RESET_CALIB_GAIN = 0x8000


# =============================================================================
# Registros del osciloscopio
# =============================================================================
#
# El fichero original no tenía constantes de offset: cada dirección era un
# literal hex inline. Nombrarlas es lo que permite que test_compat_api.py
# verifique los valores contra el baseline en vez de confiar en la vista.
# Sufijo _CH1 = el mismo registro para el canal 1 (offset +0x100 salvo excepciones).

R_CMD          = 0x000      # W: arm[0] rst[1] we_keep[3] indep[5] | R: adc_state
R_SW_TRIG      = 0x004      # W: [3:0]==1 dispara | R: trg_state
R_THR_CH0      = 0x008
R_THR_CH1      = 0x00C
R_DLY_CH0      = 0x010
R_DLY_CH1      = 0x110
R_DEC_CH0      = 0x014
R_DEC_CH1      = 0x114
R_WP_CUR_CH0   = 0x018
R_WP_CUR_CH1   = 0x118
R_WP_TRIG_CH0  = 0x01C
R_WP_TRIG_CH1  = 0x11C
R_HYST_CH0     = 0x020
R_HYST_CH1     = 0x024
R_AVG_EN       = 0x028
R_WE_CNT_CH0   = 0x02C
R_WE_CNT_CH1   = 0x12C
R_DEB_LEN      = 0x090
R_TRIG_DIS_CLR = 0x094
R_FILT_BYPASS  = 0x098
R_CALIB_OFF_CH0 = 0x200
R_CALIB_GAIN_CH0 = 0x204
R_CALIB_OFF_CH1 = 0x208
R_CALIB_GAIN_CH1 = 0x20C

APERTURE_BRAM = (0x10000, 0x20000, 0x30000, 0x40000)   # una por canal

# `decode_snap` decodifica el snapshot de 0x218, que es un registro del
# multitrigger: la definición única vive allá. Acá se importa porque los dos
# volcados de diagnóstico (`debug_trigger`, `debug_dump`) imprimen registros de
# los dos bloques. No hay ciclo: API.multitrigger sólo importa mmap/os/struct.
from API.multitrigger import decode_snap                            # noqa: E402,F401


def _fb_to_np(fb, n):
    """Convierte un rp.fBuffer (array SWIG de floats) a np.ndarray(float32).

    Usa np.frombuffer sobre el puntero del buffer (fb.cast()) en vez del loop
    `np.fromiter((fb[i] for i in range(n)))`: ~800x más rápido (medido en
    API/bench/bench_read_vs_length.py; 105 ms -> 0.12 ms para 16384 samples), porque
    evita n accesos SWIG desde Python. `.copy()` es obligatorio: la memoria del
    fBuffer se reusa/libera.
    """
    addr = int(fb.cast().__int__())
    return np.frombuffer((ctypes.c_float * n).from_address(addr),
                         dtype=np.float32).copy()

class Osciloscope:
    """Wrapper del cfg del osciloscopio + helpers de diagnóstico,
    arm y captura.

    No abre por sí solo: usar :py:meth:`open` o pasar (mmap, fd) si ya los
    tenés mapeados.
    """

    def __init__(self, scope_mmap, fd):
        self._mmap = scope_mmap
        self._fd   = fd

    @classmethod
    def open(cls, phys=SCOPE_PHYS, size=SCOPE_SIZE, check_pl=True):
        """Abrir /dev/mem y mapear la región del scope.

        `check_pl` mira el FPGA manager antes de mapear: si la PL no está
        'operating' no hay quién conteste en el bus y la PRIMERA lectura del
        scope mata el proceso con SIGBUS (external abort), sin traceback. Es
        barato chequearlo acá en vez de perder el kernel.
        """
        if check_pl:
            st = fpga_state()
            # st is None -> el sysfs no existe y no se puede saber: no bloquear.
            if st is not None and st != 'operating':
                raise RuntimeError(
                    f'la PL no está programada (fpga0/state={st!r}). Cargá el '
                    'bitstream ANTES de abrir el scope: load_bitstream(). '
                    'Mapear y leer ahora daría SIGBUS.')
        fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        m  = mmap.mmap(fd, size, mmap.MAP_SHARED,
                       mmap.PROT_READ | mmap.PROT_WRITE, offset=phys)
        return cls(m, fd)

    @classmethod
    def reload_bitstream(cls, path=BITSTREAM_DEFAULT, scope=None,
                         phys=SCOPE_PHYS, size=SCOPE_SIZE, release_rp=True,
                         verbose=True):
        """Recarga la PL a mitad de sesión con el orden menos riesgoso.

        Reprogramar con los mapeos abiertos es lo que produce el
        `external abort ... *pte=40100743` de dmesg (ver `load_bitstream`).
        Acá el orden es:

            cerrar el mmap  ->  rp_Release  ->  fpgautil (con los puentes AXI
            bajos)  ->  rp_Init  ->  reabrir

        **Aun así, reconfigurar en caliente NO es seguro del todo en esta
        placa.** El bus de registros del scope está en el dominio `adc_clk` y
        en reset por `adc_rstn = frstn[0] & ~rst_after_locked`
        (red_pitaya_top.sv:227 y :289): mientras la PL se reconfigura no hay
        esclavo que conteste, y si el puerto GP0 llega a abortar una vez queda
        trabado — todo acceso posterior a 0x4010_0000 aborta aunque la PL ya
        esté bien. **De ese estado sólo se sale reiniciando la Pitaya.**

        Si venís de un kernel muerto por SIGBUS: reiniciá la placa y cargá el
        bitstream UNA vez, antes de mapear nada (primera celda del notebook).

        `scope` es la instancia actual (se cierra); devuelve la NUEVA, así que
        en el notebook hay que reasignar:  ``sc = MultiTriggerScope.reload_bitstream(scope=sc)``
        La vieja queda inutilizable.
        """
        if scope is not None:
            try:
                scope.close()
            except Exception as e:
                print('warn: cerrando el scope viejo:', e)
        if release_rp:
            try:
                rp.rp_Release()
            except Exception as e:
                print('warn: rp_Release:', e)
        info = load_bitstream(path)
        if release_rp:
            rp.rp_Init()
        new = cls.open(phys, size)
        if verbose:
            print(f'bitstream recargado: {info["path"]}  state={info["state"]}')
            print(f'  cfg sanity: trg_src ch0 @0x240 = {new.r32(0x240):#010x} '
                  f'(esperado tras reset: 0)')
        return new

    def close(self):
        try:
            self._mmap.close()
        finally:
            os.close(self._fd)

    # ---------- acceso /dev/mem ----------

    def w32(self, off, v):
        # NO cambiar por `_U32.pack_into(self._mmap, off, v)`: pack_into hace un
        # `memset` de la región antes de empaquetar, y sobre esta memoria de
        # DISPOSITIVO (mmap de /dev/mem, no cacheable) ese memset sale como
        # stores de a byte. El esclavo AXI de la PL no reconoce esos accesos
        # angostos, la transacción no se completa y el puente GP0 tira un
        # *external abort* -> SIGBUS -> se muere el proceso (en Jupyter: "el
        # kernel murió", con el fault en dmesg apuntando a *pte=40100xxx).
        # Verificado en la placa: la asignación por slice (un memcpy de 4 bytes
        # alineado) funciona; pack_into aborta. Ver API/tests/placa/test_rw_dev_mem.py.
        self._mmap[off:off+4] = _U32.pack(v & 0xFFFFFFFF)

    def r32(self, off):
        # Las LECTURAS sí pueden usar unpack_from (un load de 4 bytes alineado,
        # sin memset previo): verificado en la placa y es el camino caliente del
        # lazo de polling de capture_n_events.
        return _U32.unpack_from(self._mmap, off)[0]

    # ---------- diagnóstico ----------

    def debug_trigger(self):
        """Dump completo de regs del scope (write-side + run-time)."""
        print('--- write-side (config) ---')
        print(f'  set_tresh ch0/ch1 @0x08/0x0C = {self.r32(0x08):#010x} / {self.r32(0x0C):#010x}')
        print(f'  set_hyst  ch0/ch1 @0x20/0x24 = {self.r32(0x20):#010x} / {self.r32(0x24):#010x}')
        print(f'  set_deb_len       @0x90     = {self.r32(0x90):#010x}')
        print(f'  trg_src_stored ch0/ch1 @0x240/0x244 = {self.r32(0x240):#010x} / {self.r32(0x244):#010x}')
        print(f'  shield_cfg            @0x210 = {self.r32(0x210):#010x}')
        print('--- run-time (status / debug) ---')
        print(f'  adc_state         @0x00 = {self.r32(0x00):#010x}  (config + trigger_status por canal)')
        print(f'  trg_state         @0x04 = {self.r32(0x04):#010x}  (set_trig_src[7:0] activo por canal en bytes)')
        print(f'  shield runtime    @0x214 = {self.r32(0x214):#010x}  ({{active, cnt[15:0]}})')
        snap = self.r32(0x218)
        print(f'  snapshot          @0x218 = {snap:#010x}  -> {decode_snap(snap)}')
        dis_we = self.r32(0x21C)
        print(f'  dis+we_keep       @0x21C = {dis_we:#010x}  dis_act={dis_we & 0xF:#x} we_keep={(dis_we>>4) & 0xF:#x}')
        print(f'  wp_trig ch0/ch1   @0x1C/0x11C = {self.r32(0x1C):#010x} / {self.r32(0x11C):#010x}')
        print(f'  wp_cur  ch0/ch1   @0x18/0x118 = {self.r32(0x18):#010x} / {self.r32(0x118):#010x}')

    def debug_dump(self):
        """Versión corta — solo lo más relevante por captura."""
        snap = self.r32(0x218)
        print(f'  snapshot @0x218 = {snap:#010x}  -> {decode_snap(snap)}')
        print(f'  dis_act  @0x21C = {self.r32(0x21C):#010x}')
        print(f'  mask act ch0/ch1 = {self.r32(0x240):#010x} / {self.r32(0x244):#010x}')
        print(f'  wp_trig ch0/ch1 = {self.r32(0x1C):#010x} / {self.r32(0x11C):#010x}')
        print(f'  shield   @0x214 = {self.r32(0x214):#010x}')

    # ---------- verificación del bitstream ----------

    def _probe_rw(self, off, patterns, mask=0xFFFFFFFF):
        """Escribe cada patrón en `off` y lo lee de vuelta (comparando solo los
        bits de `mask`, para registros con nibbles no almacenados). Restaura
        siempre el valor original. Devuelve (ok, orig).

        Es la prueba fuerte de que un registro R/W EXISTE: una dirección
        read-only o no decodificada no retiene lo escrito.
        """
        orig = self.r32(off)
        ok = True
        try:
            for p in patterns:
                self.w32(off, p)
                got = self.r32(off) & mask
                if got != (p & mask):
                    ok = False
                    break
        finally:
            self.w32(off, orig)          # restaurar sí o sí
        return ok, orig

    def verify_bitstream(self, verbose=True, raise_on_fail=False):
        """Comprueba que el bitstream cargado sea realmente el diseño
        multitrigger (y no el scope stock ni una región sin decodificar).

        Estrategia (ver docs/register_map_multitrigger_rp_scope_cfg.md):

        1. **Sanity** (necesario, no suficiente): registros comunes al scope
           stock leen su valor de reset. Detecta "no hay bitstream / región
           equivocada / bus muerto", pero NO distingue este diseño del stock.
        2. **Fingerprint** (decisivo): readback R/W sobre los registros que el
           scope original NO tiene — OR_MASK (0x240/0x244) y trigger_shield
           (0x210). Si retienen patrones escritos, el cfg multitrigger está
           cargado. No destructivo: restaura los valores originales.

        Correr ANTES de armar (los probes tocan 0x210/0x240, que set_or_mask /
        arm reescriben igual). Devuelve dict con 'ok', 'sanity_ok',
        'fingerprint_ok' y 'checks' (lista de (nombre, esperado, obtenido, ok)).
        """
        checks = []   # (nombre, esperado_str, obtenido, ok, tipo)

        # 1) sanity: comunes al scope stock
        for name, off, exp in (
            ('set_dec_ch0 @0x014', 0x014, RESET_SET_DEC),
            ('set_dec_ch1 @0x114', 0x114, RESET_SET_DEC),
            ('calib_gain0 @0x204', 0x204, RESET_CALIB_GAIN),
        ):
            got = self.r32(off)
            checks.append((name, f'{exp:#010x}', got, got == exp, 'sanity'))

        # 2) fingerprint: R/W readback en registros multitrigger-only.
        #    patrones = dos valores distintos + limpieza a 0.
        #    0x210 tiene nibbles [15:12] y [7:4] no almacenados -> mask 0xFFFF0F0F.
        for name, off, pats, mask in (
            ('OR_MASK ch0 @0x240', 0x240, (0xA5A5_5A5A, 0x0000_FFFF, 0x0), 0xFFFF_FFFF),
            ('OR_MASK ch1 @0x244', 0x244, (0x5A5A_A5A5, 0xFFFF_0000, 0x0), 0xFFFF_FFFF),
            ('shield_cfg  @0x210', 0x210, (0x1234_050A, 0x0),             0xFFFF_0F0F),
        ):
            ok, _orig = self._probe_rw(off, pats, mask)
            checks.append((name, 'R/W latch', self.r32(off), ok, 'fingerprint'))

        sanity_ok = all(ok for _, _, _, ok, t in checks if t == 'sanity')
        fp_ok     = all(ok for _, _, _, ok, t in checks if t == 'fingerprint')
        ok        = sanity_ok and fp_ok

        # info suave (dependiente de estado, no afecta el veredicto)
        dis_we = self.r32(0x21C)

        if verbose:
            print('=== verify_bitstream ===')
            for name, exp, got, cok, t in checks:
                flag = 'OK ' if cok else 'FAIL'
                print(f'  [{flag}] {name:22s} esperado={exp:12s} leido={got:#010x}  ({t})')
            print(f'  info: 0x21C dis+we_keep = {dis_we:#010x} '
                  f'(dis={dis_we & 0xF:#x} we_keep={(dis_we >> 4) & 0xF:#x}; '
                  f'0 esperado recién cargado)')
            if ok:
                print('  -> VERDICTO: PASS — diseño multitrigger cargado y verificado')
            elif sanity_ok and not fp_ok:
                print('  -> VERDICTO: FAIL — hay un scope mapeado pero NO es el '
                      'multitrigger (¿bitstream stock? ¿versión vieja?)')
            else:
                print('  -> VERDICTO: FAIL — no se lee un scope válido en '
                      f'{SCOPE_PHYS:#010x} (¿bitstream sin cargar? ¿fpgautil falló?)')

        if raise_on_fail and not ok:
            raise RuntimeError('verify_bitstream: el bitstream cargado no es el '
                               'diseño multitrigger esperado')

        return {'ok': ok, 'sanity_ok': sanity_ok, 'fingerprint_ok': fp_ok,
                'checks': checks}

    # ---------- configuración acq ----------

    def acq_base(self, thr=0.5, delay=0, decim=1):
        """Reset + decim/threshold/delay por escritura directa de registros.

        Reemplaza la rp API (rp_AcqReset / SetDecimation / SetTriggerLevel /
        SetTriggerDelay) por writes a /dev/mem ya verificados en
        multitrigger_test_cfg.ipynb (tabla TESTS).

        NOTA: thr se convierte a cuentas con escala fija ADC_CNT_PER_V
        (8192 cuentas/V, rango LV ±1 V). A diferencia de
        rp_AcqSetTriggerLevel, NO aplica la calibración de EEPROM; para
        triggering por flanco la diferencia es despreciable.

        Limpia adc_trg_dis (0x94): tras un trigger single-shot el HW deja el
        trigger BLOQUEADO (adc_trg_dis latcheado) y la máscara efectiva queda
        en 0. rp_AcqReset lo reseteaba implícitamente; el reset directo
        (adc_rst_do) NO, así que lo desbloqueamos explícitamente acá para que
        cada re-config pueda volver a disparar.
        """
        if decim not in DEC_LEGAL:
            raise ValueError(f'decim {decim} no legal; usar {DEC_LEGAL}')
        self.w32(0x00, 0x0000_0202)                  # adc_rst_do ch0+ch1 (reset FSM)
        self.w32(0x94, 0x0000_0101)                  # trig_dis_clr: desbloquea el trigger
        self.w32(0x14,  decim); self.w32(0x114, decim)   # set_dec ch0/ch1 (factor crudo)
        thr_cnt = int(round(thr * ADC_CNT_PER_V)) & 0x3FFF
        self.w32(0x08, thr_cnt); self.w32(0x0C, thr_cnt) # set_tresh ch0/ch1 (14b signed)
        self.w32(0x10, delay);  self.w32(0x110, delay)   # set_dly ch0/ch1
    def set_raw_delay(self, delay=1):
        """Bypasea el offset que mete rp_AcqSetTriggerDelay. Escribe set_dly
        directamente al cfg (0x10 ch0, 0x110 ch1). Sin esto, llamar a
        rp_AcqSetTriggerDelay(0) en realidad escribe ~8192 samples = 65 µs
        de post-trigger delay, que impone un floor de dead-time de 65 µs.

        Default delay=1 (= 8 ns) en lugar de 0 porque el rp_bram_sm tiene un
        caso degenerado con set_dly=0: la FSM trata el contador en 0 como
        'delay completo' antes de ver el trigger, se salta el estado de
        espera-trigger y termina ignorando los triggers que llegan.
        delay=1 es efectivamente 0 (8 ns es << que cualquier flanco real)
        pero evita ese caso degenerado.
        """
        self.w32(0x10,  delay)
        self.w32(0x110, delay)
    # ---------- waits ----------

    @staticmethod
    def wait_triggered(timeout_ms=2000):
        """Polea rp_AcqGetTriggerState. CUIDADO: en we_keep=1 es STICKY."""
        for _ in range(timeout_ms):
            if rp.rp_AcqGetTriggerState()[1] == rp.RP_TRIG_STATE_TRIGGERED:
                return True
            time.sleep(0.001)
        return False

    @staticmethod
    def wait_fill(timeout_ms=2000):
        """Polea rp_AcqGetBufferFillState (FSM completó la captura)."""
        for _ in range(timeout_ms):
            if rp.rp_AcqGetBufferFillState()[1]:
                return True
            time.sleep(0.001)
        return False

    @staticmethod
    def read_buffers(n_buf=N_BUF):
        """Lee los dos buffers ADC como numpy arrays float32 (volts).

        Conversión con _fb_to_np (np.frombuffer del puntero); ~800x más rápido que
        el loop np.fromiter (API/bench/bench_read_vs_length.py). Devuelve float32
        (antes float64): sobra para datos de 14 bit y el análisis castea igual.
        """
        fb1 = rp.fBuffer(n_buf); rp.rp_AcqGetOldestDataV(rp.RP_CH_1, n_buf, fb1)
        d1 = _fb_to_np(fb1, n_buf)
        fb2 = rp.fBuffer(n_buf); rp.rp_AcqGetOldestDataV(rp.RP_CH_2, n_buf, fb2)
        d2 = _fb_to_np(fb2, n_buf)
        return d1, d2

    @staticmethod
    def capture_window_np(channels=None, pre=0, post=N_BUF, at_trigger=True):
        """Copia una ventana de `pre+post` samples alrededor del trigger a
        arrays NumPy con rp_AcqGetDataPosVNP (copia directa, más rápida que el
        loop fBuffer + np.fromiter de read_buffers). Si rp_AcqGetDataPosVNP no
        existe en el rp instalado (RP OS viejo), cae a rp_AcqGetDataPosV.

        Ventana = posiciones absolutas [ref-pre, ref+post-1] INCLUSIVE
        (`n = pre+post` samples). OJO: `end_pos` de rp_AcqGetDataPosV es
        INCLUSIVO y la API pide `buffer_size >= end-start+1`; si es menor
        devuelve RP_BTS y NO escribe (buffer en ceros). Por eso `end = ref+post-1`
        (no ref+post) y se chequea el return code.

        ref = rp_AcqGetWritePointerAtTrig() si at_trigger (puntero al sample
        del trigger), si no rp_AcqGetWritePointer() (puntero actual). La RTL
        de adquisición (rp_bram_sm) es stock, así que estas funciones del rp
        reflejan el HW real (equivalen a leer 0x1C / 0x18).

        Requiere rp.rp_Init() previo (mmap/calibración del rp). Devuelve
        (data, ref) con data = {channel: np.ndarray(float32)}.
        """
        if channels is None:
            channels = (rp.RP_CH_1, rp.RP_CH_2)
        ref = (rp.rp_AcqGetWritePointerAtTrig() if at_trigger
               else rp.rp_AcqGetWritePointer())[1]
        n     = pre + post
        start = (ref - pre)      % N_BUF
        end   = (ref + post - 1) % N_BUF      # end_pos INCLUSIVO -> n samples
        data  = {}
        for ch in channels:
            buf = np.zeros(n, dtype=np.float32)
            if hasattr(rp, 'rp_AcqGetDataPosVNP'):
                rp.rp_AcqGetDataPosVNP(ch, start, end, buf)
            else:                              # fallback fBuffer + copia
                fb  = rp.fBuffer(n)
                res = rp.rp_AcqGetDataPosV(ch, start, end, fb, n)
                # buffer_size es INOUT -> res puede ser [rc, size_out] o rc.
                rc  = res[0] if isinstance(res, (list, tuple)) else res
                if rc != rp.RP_OK:
                    raise RuntimeError(
                        f'rp_AcqGetDataPosV fallo (rc={rc}, RP_BTS={getattr(rp,"RP_BTS","?")}) '
                        f'ch={ch} start={start} end={end} n={n}: '
                        f'revisar buffer_size vs (end-start+1)')
                buf[:] = _fb_to_np(fb, n)      # np.frombuffer del puntero (rapido)
            data[ch] = buf
        return data, ref

    # ---------- captura ----------

    def acq_capture_sw(self, thr=0.5, delay=None, timeout_ms=500):
        """Captura single-shot forzada con SW trigger (mask=BIT_SW + pulso a 0x04).
        Devuelve (d1, d2, snapshot). Sirve para confirmar que el bram_sm
        captura el buffer correctamente, independiente del trigger ADC.
        """
        if delay is None:
            delay = N_BUF // 2
        self.acq_base(thr=thr, delay=delay)
        # Limpiar adc_trg_dis si quedó pegado de una corrida anterior. Sin esto,
        # src_mask = set_trig_src & {!adc_trg_dis} = 0 y el SW pulse no firma.
        self.w32(0x94, 0x0000_0101)
        self.set_or_mask(BIT_SW, BIT_SW)
        self.w32(0x00, 0x0000_0101)     # arm ch0+ch1 (single-shot, sin we_keep)
        time.sleep(0.01)
        self.w32(0x04, 0x0000_0101)     # pulso adc_trig_sw[0] y [1]
        self.wait_fill(timeout_ms=timeout_ms)
        d1, d2 = self.read_buffers()
        return d1, d2, self.r32(0x218)

    def capture_n_events(self, n=100, timeout_ms=2000, wp_addr=0x1C,
                          clear_both=True, read_snap=False, deadline_every=256):
        """Captura n triggers consecutivos detectando cambios en wp_trig.
        Requiere `arm_for_adc_trigger` previo.

        Con `arm_for_adc_trigger(auto_rearm=True)` (default) el trigger_shield
        del FPGA limpia adc_trg_dis automáticamente cada disparo, así que el
        loop NO necesita pulsar 0x94. Solo polea cambios de wp_trig.

        Si se llama con `auto_rearm=False`, el pulso inicial al 0x94 cubre
        el caso del trigger durante el arm. El loop sigue sin pulsar (mejor
        usar `auto_rearm=True` para alta tasa).

        **El costo de una vuelta del loop ES el dead-time del método**: los
        eventos separados por menos que eso se pierden (el HW re-arma en ~24 ns,
        cuatro órdenes de magnitud más rápido). Por eso el loop está escrito
        pegado al mínimo:

        - `unpack_from` de un `struct.Struct` precompilado sobre el mmap, en vez
          de `self.r32()` (evita la llamada a método, el slice y el parseo del
          formato en cada vuelta);
        - el deadline se chequea cada `deadline_every` vueltas y no en cada una
          (`perf_counter_ns` cuesta casi tanto como la lectura);
        - se acumula en listas planas y los dicts se arman al final;
        - `read_snap=False` (default) ahorra la lectura extra de 0x218 por
          evento; el snapshot queda en 0. Ponerlo en True sólo si el análisis
          necesita saber QUÉ fuente disparó cada evento.

        Devuelve (events, duration_s) donde events es lista de dicts con
        't_ns' (timestamp SW), 'wp' (write pointer al trigger) y 'snap'
        (snapshot del momento, 0 si `read_snap=False`)."""
        clear_mask = 0x0000_0101 if clear_both else 0x0000_0001
        # Pulso inicial defensivo: si el primer trigger firmó durante el arm
        # y el shield no está activo, esto destraba el dis.
        self.w32(0x94, clear_mask)

        mem         = self._mmap
        unpack_from = _U32.unpack_from
        pc          = time.perf_counter_ns
        ts, wps, snaps = [], [], []
        wp_prev  = unpack_from(mem, wp_addr)[0]
        t0       = pc()
        deadline = t0 + timeout_ms * 1_000_000
        ticks    = deadline_every
        count    = 0
        while count < n:
            ticks -= 1
            if ticks <= 0:
                ticks = deadline_every
                if pc() > deadline:
                    break
            wp_cur = unpack_from(mem, wp_addr)[0]
            if wp_cur != wp_prev:
                ts.append(pc())
                wps.append(wp_cur)
                if read_snap:
                    snaps.append(unpack_from(mem, 0x218)[0])
                wp_prev = wp_cur
                count += 1
        dur_s = (pc() - t0) / 1e9

        events = [{'t_ns': t - t0, 'wp': w,
                   'snap': snaps[i] if read_snap else 0}
                  for i, (t, w) in enumerate(zip(ts, wps))]
        return events, dur_s

# =============================================================================
# API de configuración y estatus
# =============================================================================

def osciloscope_open(phys=SCOPE_PHYS, size=SCOPE_SIZE, check_pl=True):
    return Osciloscope.open(phys, size, check_pl)


def osciloscope_close(osc):
    osc.close()


def osciloscope_get_thr(osc, ch=0):
    """Umbral en volts (escala fija ADC_CNT_PER_V, sin calibración de EEPROM)."""
    crudo = osc.r32(R_THR_CH1 if ch else R_THR_CH0) & 0x3FFF
    if crudo & 0x2000:
        crudo -= 0x4000
    return crudo / ADC_CNT_PER_V


def osciloscope_set_thr(osc, v, ch=None):
    cnt = int(round(v * ADC_CNT_PER_V)) & 0x3FFF
    for off in ((R_THR_CH0, R_THR_CH1) if ch is None else
                ((R_THR_CH1,) if ch else (R_THR_CH0,))):
        osc.w32(off, cnt)


def osciloscope_get_decim(osc, ch=0):
    return osc.r32(R_DEC_CH1 if ch else R_DEC_CH0)


def osciloscope_set_decim(osc, v, ch=None):
    if v not in DEC_LEGAL:
        raise ValueError(f'decim {v} no legal; usar {DEC_LEGAL}')
    for off in ((R_DEC_CH0, R_DEC_CH1) if ch is None else
                ((R_DEC_CH1,) if ch else (R_DEC_CH0,))):
        osc.w32(off, v)


def osciloscope_get_delay(osc, ch=0):
    return osc.r32(R_DLY_CH1 if ch else R_DLY_CH0)


def osciloscope_set_delay(osc, v, ch=None):
    """Delay post-trigger EN CRUDO. Es dead-time real: mientras corre,
    adc_dly_do bloquea la actualización de adc_wp_trig (rp_bram_sm.v:91)."""
    for off in ((R_DLY_CH0, R_DLY_CH1) if ch is None else
                ((R_DLY_CH1,) if ch else (R_DLY_CH0,))):
        osc.w32(off, v)


def osciloscope_get_hysteresis(osc, ch=0):
    return osc.r32(R_HYST_CH1 if ch else R_HYST_CH0) / ADC_CNT_PER_V


def osciloscope_set_hysteresis(osc, v, ch=None):
    cnt = max(1, int(abs(v) * ADC_CNT_PER_V))
    for off in ((R_HYST_CH0, R_HYST_CH1) if ch is None else
                ((R_HYST_CH1,) if ch else (R_HYST_CH0,))):
        osc.w32(off, cnt)


def osciloscope_get_avg(osc):            return osc.r32(R_AVG_EN) & 1
def osciloscope_set_avg(osc, v):         osc.w32(R_AVG_EN, 1 if v else 0)
def osciloscope_get_deb_len(osc):        return osc.r32(R_DEB_LEN)
def osciloscope_set_deb_len(osc, v):     osc.w32(R_DEB_LEN, v)
def osciloscope_get_filter_bypass(osc):  return osc.r32(R_FILT_BYPASS)
def osciloscope_set_filter_bypass(osc, v): osc.w32(R_FILT_BYPASS, v)


def osciloscope_get_calibration(osc, ch=0):
    off = R_CALIB_OFF_CH1 if ch else R_CALIB_OFF_CH0
    gan = R_CALIB_GAIN_CH1 if ch else R_CALIB_GAIN_CH0
    return {'offset': osc.r32(off), 'gain': osc.r32(gan)}


def osciloscope_set_calibration(osc, offset=None, gain=None, ch=0):
    if offset is not None:
        osc.w32(R_CALIB_OFF_CH1 if ch else R_CALIB_OFF_CH0, offset)
    if gain is not None:
        osc.w32(R_CALIB_GAIN_CH1 if ch else R_CALIB_GAIN_CH0, gain)


# ---------- estatus (sólo lectura) ----------

def osciloscope_get_adc_state(osc):      return osc.r32(R_CMD)
def osciloscope_get_trg_state(osc):      return osc.r32(R_SW_TRIG)
def osciloscope_get_wp_cur(osc, ch=0):   return osc.r32(R_WP_CUR_CH1 if ch else R_WP_CUR_CH0)
def osciloscope_get_wp_trig(osc, ch=0):  return osc.r32(R_WP_TRIG_CH1 if ch else R_WP_TRIG_CH0)
def osciloscope_get_we_cnt(osc, ch=0):   return osc.r32(R_WE_CNT_CH1 if ch else R_WE_CNT_CH0)


# ---------- configuración en bloque ----------
#
# Misma forma que `_CAMPOS` de `API/mca.py`: campo -> (offset, shift, máscara).
# Existe por la misma razón que allá — que se pueda **releer lo que se escribe**
# en una sola operación, sin una función por registro y sin que el cliente
# tenga que saber en qué bit vive cada cosa.
#
# Las máscaras salen de `modulos/osc/rtl/osc_cfg.sv`, no de suponer 32 bits:
# `set_tresh`/`set_hyst` son DW=14, `set_dec` es 17, `set_dly` 32, `set_deb_len`
# 20 y `set_filt_byp` 4. Escribir de más no rompe —el RTL trunca— pero leer de
# más devuelve bits que no existen y el readback deja de coincidir con lo
# escrito, que es justo lo que el anti-eco de la GUI usa para no reescribir.

_CAMPOS = {
    'thr_ch0':        (R_THR_CH0,        0, 0x3FFF),
    'thr_ch1':        (R_THR_CH1,        0, 0x3FFF),
    'hyst_ch0':       (R_HYST_CH0,       0, 0x3FFF),
    'hyst_ch1':       (R_HYST_CH1,       0, 0x3FFF),
    'dec_ch0':        (R_DEC_CH0,        0, 0x1FFFF),
    'dec_ch1':        (R_DEC_CH1,        0, 0x1FFFF),
    'dly_ch0':        (R_DLY_CH0,        0, 0xFFFFFFFF),
    'dly_ch1':        (R_DLY_CH1,        0, 0xFFFFFFFF),
    # avg_en NO es un bit por canal contiguo: el RTL lo lee y lo devuelve como
    # un BYTE por canal (`set_avg_en[c] <= sys_dats_all[c*8]`, y el readback
    # arma {7'h0, avg[3], 7'h0, avg[2], ...}). `osciloscope_set_avg()` escribe
    # la palabra entera con un 1 y por lo tanto toca sólo el canal 0.
    'avg_en_ch0':     (R_AVG_EN,         0, 0x1),
    'avg_en_ch1':     (R_AVG_EN,         8, 0x1),
    'deb_len':        (R_DEB_LEN,        0, 0xFFFFF),
    'filt_bypass':    (R_FILT_BYPASS,    0, 0xF),
    'calib_off_ch0':  (R_CALIB_OFF_CH0,  0, 0x3FFF),
    'calib_gain_ch0': (R_CALIB_GAIN_CH0, 0, 0xFFFF),
    'calib_off_ch1':  (R_CALIB_OFF_CH1,  0, 0x3FFF),
    'calib_gain_ch1': (R_CALIB_GAIN_CH1, 0, 0xFFFF),
}

# Los que el RTL guarda en complemento a dos sobre DW bits. Sin extender el
# signo, un umbral de -0.5 V se lee como +15792 cuentas y el control de la GUI
# salta al tope en vez de mostrar el valor que tiene puesto.
_CON_SIGNO = frozenset(('thr_ch0', 'thr_ch1',
                        'calib_off_ch0', 'calib_off_ch1'))


def _extender_signo(v, mascara):
    bit = (mascara + 1) >> 1
    return v - (mascara + 1) if v & bit else v


def osciloscope_get_config(osc):
    """Todos los campos de `_CAMPOS`, en crudo (cuentas, no volts).

    En cuentas a propósito: es lo que está escrito en el registro. La conversión
    a volts depende de la escala del jumper (LV/HV) y de la calibración, así que
    hacerla acá metería una suposición en el dato en vez de en la vista.
    """
    fuera = {}
    for campo, (off, shift, mask) in _CAMPOS.items():
        v = (osc.r32(off) >> shift) & mask
        fuera[campo] = _extender_signo(v, mask) if campo in _CON_SIGNO else v
    return fuera


def osciloscope_configure(osc, **campos):
    """Escribe campos por nombre. Los que comparten registro se agrupan.

    Read-modify-write por registro y no por campo: `avg_en_ch0` y `avg_en_ch1`
    viven en la misma palabra, así que escribirlos de a uno haría que el segundo
    leyera un valor que el primero acaba de cambiar. Agrupando, la palabra se
    lee una vez y se escribe una vez.
    """
    desconocidos = set(campos) - set(_CAMPOS)
    if desconocidos:
        raise ValueError(f'campos desconocidos: {sorted(desconocidos)}; '
                         f'hay: {sorted(_CAMPOS)}')
    por_registro = {}
    for campo, valor in campos.items():
        off, shift, mask = _CAMPOS[campo]
        por_registro.setdefault(off, []).append((shift, mask, int(valor)))

    for off, partes in por_registro.items():
        w = osc.r32(off)
        for shift, mask, valor in partes:
            w = (w & ~(mask << shift)) | ((valor & mask) << shift)
        osc.w32(off, w)


def osciloscope_get_status(osc):
    """Lo que se refresca en pantalla: estado de las FSM y punteros.

    Sólo lectura y sin efectos: se puede poléar con una captura corriendo.
    """
    return {
        'adc_state':  osciloscope_get_adc_state(osc),
        'trg_state':  osciloscope_get_trg_state(osc),
        'wp_cur_ch0': osciloscope_get_wp_cur(osc, 0),
        'wp_cur_ch1': osciloscope_get_wp_cur(osc, 1),
        'wp_trig_ch0': osciloscope_get_wp_trig(osc, 0),
        'wp_trig_ch1': osciloscope_get_wp_trig(osc, 1),
        'we_cnt_ch0': osciloscope_get_we_cnt(osc, 0),
        'we_cnt_ch1': osciloscope_get_we_cnt(osc, 1),
    }


# ---------- comandos ----------

def osciloscope_reset(osc):
    """Reset del FSM de ambos canales + desbloqueo de adc_trg_dis."""
    osc.w32(R_CMD, 0x0000_0202)
    osc.w32(R_TRIG_DIS_CLR, 0x0000_0101)


def osciloscope_sw_trigger(osc):
    osc.w32(R_SW_TRIG, 0x0000_0001)


def osciloscope_wait_triggered(timeout_ms=2000):
    return Osciloscope.wait_triggered(timeout_ms)


def osciloscope_wait_fill(timeout_ms=2000):
    return Osciloscope.wait_fill(timeout_ms)


# =============================================================================
# API de lectura
# =============================================================================

def osciloscope_read_buffers(osc, n_buf=N_BUF):
    return osc.read_buffers(n_buf)


def osciloscope_read_window(osc, channels=None, pre=0, post=N_BUF, at_trigger=True):
    """Ventana alrededor del trigger, por canal. Ver capture_window_np."""
    return osc.capture_window_np(channels=channels, pre=pre, post=post,
                                 at_trigger=at_trigger)


def osciloscope_read_events(osc, n=100, timeout_ms=2000, wp_addr=R_WP_TRIG_CH0,
                            **kw):
    return osc.capture_n_events(n=n, timeout_ms=timeout_ms, wp_addr=wp_addr, **kw)


def osciloscope_read_capture_sw(osc, thr=0.5, delay=None, timeout_ms=500):
    """Captura forzada por SW trigger: no depende de que haya señal."""
    return osc.acq_capture_sw(thr=thr, delay=delay, timeout_ms=timeout_ms)


# =============================================================================
# Análisis offline de buffers capturados (no tocan hardware)
# =============================================================================

def events_to_intervals(events):
    """Intervalos SW entre triggers consecutivos en µs."""
    if len(events) < 2:
        return np.array([])
    ts = np.array([e['t_ns'] for e in events])
    return np.diff(ts) / 1000.0


def efficiency(observed_n, target_freq_hz, duration_s):
    """Cuántos triggers debería haber visto vs cuántos vio."""
    expected = target_freq_hz * duration_s
    return observed_n / max(expected, 1)


def pulses_from_buffer(d, threshold=0.0, hyst=0.05):
    """Detecta cruces ascendentes en un buffer con histéresis.
    Devuelve índices (samples) de cada cruce ascendente."""
    above = d > (threshold + hyst)
    below = d < (threshold - hyst)
    state = np.zeros(len(d), dtype=bool)
    s = False
    for i in range(len(d)):
        if   above[i]: s = True
        elif below[i]: s = False
        state[i] = s
    return np.where(np.diff(state.astype(np.int8)) > 0)[0]
