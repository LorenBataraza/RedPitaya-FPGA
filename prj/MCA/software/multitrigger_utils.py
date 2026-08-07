"""
Utilidades para el scope multitrigger del Red Pitaya MCA.

Importable desde Jupyter o cualquier script:

    from multitrigger_utils import MultiTriggerScope, BIT_ADC_P0, decode_snap

    sc = MultiTriggerScope.open()
    sc.debug_trigger()
    sc.arm_for_adc_trigger(mask_ch0=BIT_ADC_P0, thr=0.5)
    events, dur = sc.capture_n_events(n=50)
    sc.disarm()
    sc.close()

Incluye:
    - MultiTriggerScope: clase que envuelve /dev/mem + helpers de arm,
      captura, debug, SW trigger forzado.
    - MultiTriggerScope.verify_bitstream(): confirma que el bitstream cargado
      es el diseño multitrigger (fingerprint R/W de los registros nuevos).
    - Constantes de bits de la máscara OR (BIT_SW, BIT_ADC_*, BIT_EXT_*).
    - decode_snap(s): nombres de las fuentes activas en el snapshot.
    - events_to_intervals, efficiency, pulses_from_buffer: análisis offline.
"""

import time
import struct
import mmap
import os
import ctypes
import subprocess
import sys

import numpy as np
import rp


# ---------- constantes del scope ----------

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


# ---------- bits de la OR_MASK (matchean trg_src_bits de multitrigger_trig_src.sv) ----------

OR_MASK_ALL = 0xFFFF_FFFF

BIT_SW       = 1 << 0
BIT_ADC_P0   = 1 << 1
BIT_ADC_N0   = 1 << 2
BIT_ADC_P1   = 1 << 3
BIT_ADC_N1   = 1 << 4
BIT_ADC_P2   = 1 << 5
BIT_ADC_N2   = 1 << 6
BIT_ADC_P3   = 1 << 7
BIT_ADC_N3   = 1 << 8
BIT_EXT_P    = 1 << 9
BIT_EXT_N    = 1 << 10
BIT_ASG_P    = 1 << 11
BIT_ASG_N    = 1 << 12
BIT_TRIG_CH0 = 1 << 13
BIT_TRIG_CH1 = 1 << 14
BIT_TRIG_CH2 = 1 << 15
BIT_TRIG_CH3 = 1 << 16


# ---------- decoder del snapshot @0x218 ----------

_SNAP_NAMES = [
    'sw_any',
    'adc_p0', 'adc_p1', 'adc_p2', 'adc_p3',
    'adc_n0', 'adc_n1', 'adc_n2', 'adc_n3',
    'ext_p', 'ext_n', 'asg_p', 'asg_n',
    'trig_ch0', 'trig_ch1', 'trig_ch2', 'trig_ch3',
]


def decode_snap(s):
    """Lista de nombres de fuentes activas en un snapshot @0x218."""
    return [n for i, n in enumerate(_SNAP_NAMES) if s & (1 << i)]


def _fb_to_np(fb, n):
    """Convierte un rp.fBuffer (array SWIG de floats) a np.ndarray(float32).

    Usa np.frombuffer sobre el puntero del buffer (fb.cast()) en vez del loop
    `np.fromiter((fb[i] for i in range(n)))`: ~800x más rápido (medido en
    tests/bench_read_vs_length.py; 105 ms -> 0.12 ms para 16384 samples), porque
    evita n accesos SWIG desde Python. `.copy()` es obligatorio: la memoria del
    fBuffer se reusa/libera.
    """
    addr = int(fb.cast().__int__())
    return np.frombuffer((ctypes.c_float * n).from_address(addr),
                         dtype=np.float32).copy()


# ---------- carga del bitstream ----------

BITSTREAM_DEFAULT = '/root/red_pitaya_top.bit.bin'
FPGA_STATE        = '/sys/class/fpga_manager/fpga0/state'
FPGA_BRIDGE_DIR   = '/sys/class/fpga_bridge'
# fpgautil vive en el PATH del entorno RP; un shell no interactivo (ssh, cron,
# systemd) no lo tiene, así que se resuelve a mano con fallback absoluto.
FPGAUTIL_PATHS    = ('/opt/redpitaya/bin/fpgautil', '/usr/local/bin/fpgautil')


def fpgautil_bin():
    """Ruta del ejecutable fpgautil (PATH primero, después las conocidas)."""
    import shutil
    return (shutil.which('fpgautil')
            or next((p for p in FPGAUTIL_PATHS if os.path.exists(p)), None))


def fpga_state():
    """Estado del FPGA manager ('operating' = PL programada y corriendo).

    Devuelve None si el sysfs no existe (RP OS viejo / no es una Pitaya): en ese
    caso no se puede saber, y quien lo use NO debe bloquear por las dudas.
    """
    try:
        with open(FPGA_STATE) as f:
            return f.read().strip()
    except OSError:
        return None


def fpga_bridges():
    """Puentes AXI PS-PL expuestos por el kernel (vacío si el DT no los declara)."""
    try:
        return [os.path.join(FPGA_BRIDGE_DIR, d)
                for d in sorted(os.listdir(FPGA_BRIDGE_DIR))]
    except OSError:
        return []


def set_fpga_bridges(enable, verbose=False):
    """Habilita/deshabilita los puentes AXI entre el PS y la PL.

    Hay que BAJARLOS antes de reconfigurar y subirlos después. Si no, una
    transacción del PS puede quedar sin esclavo que la conteste (el bus del
    scope vive en el dominio `adc_clk` y en reset por `adc_rstn`, ver
    red_pitaya_top.sv:227 y :289) y el puente GP0 tira un *external abort*
    → SIGBUS. Peor: el puerto puede quedar TRABADO y seguir abortando aunque
    la PL ya esté bien, hasta reiniciar la placa.

    Devuelve la lista de puentes tocados (vacía si el kernel no los expone).
    """
    done = []
    for b in fpga_bridges():
        try:
            with open(os.path.join(b, 'enable'), 'w') as f:
                f.write('1' if enable else '0')
            done.append(os.path.basename(b))
        except OSError as e:
            print(f'warn: no pude {"subir" if enable else "bajar"} el puente {b}: {e}')
    if verbose and done:
        print(f'  puentes AXI {"habilitados" if enable else "deshabilitados"}: {done}')
    return done


# Lectura de prueba de un registro del scope, para correr en un proceso APARTE.
_PROBE_SRC = (
    'import mmap, os, struct\n'
    'fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)\n'
    'm = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED,\n'
    '              mmap.PROT_READ | mmap.PROT_WRITE, offset={phys})\n'
    'print(struct.unpack_from("<I", m, {off})[0])\n'
)


def pl_probe(phys=SCOPE_PHYS, off=0x14):
    """¿Contesta la PL en `phys+off`? Devuelve (ok, detalle).

    La lectura se hace en un **proceso hijo**: si el bus no está listo, el que
    muere con SIGBUS es el hijo y nos enteramos por el returncode, en vez de
    perder el kernel de Jupyter. Es la única forma segura de preguntar
    "¿ya puedo tocar el scope?" después de reconfigurar la PL.
    """
    r = subprocess.run([sys.executable, '-c',
                        _PROBE_SRC.format(phys=hex(phys), off=hex(off))],
                       capture_output=True, text=True)
    if r.returncode == 0:
        return True, r.stdout.strip()
    if r.returncode < 0:                      # murió por señal
        sig = -r.returncode
        return False, (f'el hijo murió con señal {sig} '
                       f'({"SIGBUS: la PL no contesta" if sig == 7 else "SIGSEGV"})')
    last = (r.stderr.strip().splitlines() or [''])[-1]
    return False, f'error de entorno (no del bus): {last}'


def pl_bus_ready(phys=SCOPE_PHYS, off=0x14, timeout_s=8.0, interval_s=0.3,
                 verbose=False):
    """Espera a que la PL conteste en el bus, sondeando con `pl_probe`.

    Después de reconfigurar hay una ventana en la que el esclavo no responde
    (el bus del scope está en el dominio adc_clk y en reset por adc_rstn, ver
    red_pitaya_top.sv:227/:289). Medido en esta placa: a los 0.7 s todavía
    abortaba. Acá se espera hasta `timeout_s` en vez de adivinar un sleep.

    Devuelve (ok, detalle, esperado_s). Si el hijo falla por algo que no es el
    bus (p. ej. sin permisos sobre /dev/mem) corta enseguida: reintentar no
    arregla nada.
    """
    t0 = time.time()
    while True:
        ok, det = pl_probe(phys, off)
        el = time.time() - t0
        if ok:
            if verbose:
                print(f'  bus de la PL listo tras {el:.2f} s (leyó {det})')
            return True, det, el
        if det.startswith('error de entorno'):
            return False, det, el
        if el > timeout_s:
            return False, f'{det} (tras {el:.1f} s)', el
        time.sleep(interval_s)


def load_bitstream(path=BITSTREAM_DEFAULT, settle_s=0.2, check=True,
                   bridges=True, wait_bus_s=8.0, verbose=False):
    """Programa la PL con `fpgautil -b` (sin device tree).

    **NUNCA reprogramar con mapeos del scope abiertos.** Mientras la PL se
    reconfigura no hay esclavo que conteste en el bus AXI, y el primer acceso
    posterior a 0x4010_0000 da un *external abort* → SIGBUS → se muere el
    proceso (en Jupyter: "el kernel murió"). En dmesg se ve así:

        Unhandled fault: external abort on non-linefetch (0x1818) at 0x...
        [........] *pgd=........, *pte=40100743      <- física 0x40100xxx

    Para recargar a mitad de sesión usar `MultiTriggerScope.reload_bitstream()`,
    que cierra el mapeo y el rp ANTES de programar y los reabre después.

    `bridges=True` baja los puentes AXI PS-PL mientras dura la reconfiguración
    (lo que `fpgautil -b` a secas NO hace y sí hace el camino del device tree
    overlay). Si el kernel no los expone, avisa: en ese caso reprogramar con el
    sistema vivo puede dejar el puerto GP0 trabado hasta reiniciar la placa.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f'no existe el bitstream {path}')
    exe = fpgautil_bin()
    if exe is None:
        raise FileNotFoundError(
            'no encuentro `fpgautil` (ni en PATH ni en ' + ', '.join(FPGAUTIL_PATHS) + ')')

    have_bridges = bool(fpga_bridges())
    if bridges and not have_bridges:
        print('warn: el kernel no expone /sys/class/fpga_bridge; se reprograma '
              'con los puentes AXI arriba. Si algo accede a la PL en ese '
              'momento, el puerto puede quedar trabado (external abort) hasta '
              'reiniciar la Pitaya.')
    try:
        if bridges and have_bridges:
            set_fpga_bridges(False, verbose=verbose)
        r = subprocess.run([exe, '-b', path], capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip()
        if r.returncode != 0:
            raise RuntimeError(f'fpgautil falló ({r.returncode}): {out}')
        # dar tiempo al PLL (adc_clk) y a que se suelte adc_rstn antes de que
        # alguien toque 0x4010_0000
        time.sleep(settle_s)
    finally:
        if bridges and have_bridges:
            set_fpga_bridges(True, verbose=verbose)
            time.sleep(0.05)

    st = fpga_state()
    if check and st is not None and st != 'operating':
        raise RuntimeError(f'la PL no quedó operativa tras programar (state={st!r}); '
                           'leer el scope ahora daría SIGBUS')

    # `state == operating` NO alcanza: el bus tarda en contestar después de la
    # reconfiguración. Se sondea desde un proceso hijo hasta que responda.
    espera = 0.0
    if wait_bus_s:
        ok, det, espera = pl_bus_ready(timeout_s=wait_bus_s, verbose=verbose)
        if not ok:
            raise RuntimeError(
                f'la PL no contesta en el bus tras programar: {det}. '
                'NO toques el scope desde este kernel (moriría con SIGBUS); '
                'reiniciá la Pitaya.')
    return {'path': path, 'state': st or 'desconocido', 'fpgautil': out,
            'bus_wait_s': espera}


# ---------- clase scope ----------

class MultiTriggerScope:
    """Wrapper del cfg del scope multitrigger + helpers de diagnóstico,
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
        # alineado) funciona; pack_into aborta. Ver tests/test_rw_dev_mem.py.
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

    def set_or_mask(self, mask_ch0=OR_MASK_ALL, mask_ch1=None):
        """Escribe la máscara en 0x240/0x244 con assert de readback."""
        if mask_ch1 is None:
            mask_ch1 = mask_ch0
        self.w32(0x240, mask_ch0)
        self.w32(0x244, mask_ch1)
        rb0 = self.r32(0x240)
        rb1 = self.r32(0x244)
        assert rb0 == mask_ch0, f'OR_MASK ch0 no latcheada: {rb0:#010x} != {mask_ch0:#010x}'
        assert rb1 == mask_ch1, f'OR_MASK ch1 no latcheada: {rb1:#010x} != {mask_ch1:#010x}'

    def configure_shield_autorearm(self, channels=0x3, dur=0):
        """Configura el trigger_shield para clear automático del adc_trg_dis.
        Con dur=0 el clear se emite en el MISMO ciclo del trigger (ver
        trigger_shield.sv:44-48), lo que reemplaza el pulso manual a 0x94
        después de cada disparo y permite re-triggering a velocidad de HW.

        channels: bits de los canales a auto-rearmar (0x3 = ch0+ch1).
        dur:      ciclos de ADC de holdoff antes del clear (0 = inmediato).
        Layout 0x210: {dur[31:16], 4'h0, dst[11:8], 4'h0, src[3:0]}.
        """
        word = ((dur & 0xFFFF) << 16) | ((channels & 0xF) << 8) | (channels & 0xF)
        self.w32(0x210, word)

    def disable_shield(self):
        """Apaga el shield (vuelve al modo SW-clear manual de 0x94)."""
        self.w32(0x210, 0)

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

    def arm_for_adc_trigger(self, mask_ch0=BIT_ADC_P0, mask_ch1=BIT_ADC_P0,
                             thr=0.0, hyst=0.01, delay=0, we_keep_both=True,
                             auto_rearm=True):
        """Arma el scope para trigger por flanco del ADC.

        auto_rearm=True (default): activa el trigger_shield para clear
            automático de adc_trg_dis (shield_dur=0, inmediato) Y
            sobreescribe set_dly raw para eliminar los 65 µs de offset
            que mete rp_AcqSetTriggerDelay. Esto baja drásticamente el
            dead-time del sistema (de ~65 µs a ~µs).
        auto_rearm=False: comportamiento legacy. El SW tiene que pulsar
            0x94 entre triggers (tradicional, más alto dead-time).

        `delay` se respeta en los DOS modos: con auto_rearm se escribe raw
        (sin el offset de la API) y `delay=0` se traduce a 1 sample, que es el
        mínimo que no cae en el caso degenerado del bram_sm. OJO: el post-
        trigger delay ES dead-time real — mientras corre, `adc_dly_do` bloquea
        la actualización de `adc_wp_trig` (rp_bram_sm.v:91), así que para medir
        dead-time hay que dejarlo en el mínimo y sólo subirlo cuando se quiere
        una ventana post-trigger (capture_window_np).

        El arm se hace por escritura directa a 0x00 con bit0 (arm) y bit3
        (we_keep) a la vez, así que no hay carrera con rp_AcqStart (que
        rescribía byte0 con 0x01 y borraba we_keep como side-effect).

        ORDEN CRÍTICO (arm ANTES de la máscara): se arma la bram_sm (0x00)
        y RECIÉN DESPUÉS se habilita la OR-mask (0x240/0x244). Es la misma
        convención que la API de RedPitaya (rp_AcqStart antes de
        rp_AcqSetTriggerSrc). Si se hiciera al revés, con una señal viva un
        flanco de ADC puede disparar en la ventana pre-arm: engancha
        adc_trg_dis y (en single-shot) auto-limpia set_trig_src ANTES de que
        la bram_sm esté armada, dejándola armada esperando un trigger
        imposible (wp_trig=0 permanente). El SW trigger es inmune porque
        adc_trig_sw es pasivo hasta el pulso 0x04. Ver
        docs/orden_arm_trigger_captura.md.
        """
        self.acq_base(thr=thr, delay=delay)
        # hyst en counts (14 b signed escala = 8192)
        hyst_cnt = max(1, int(abs(hyst) * 8192))
        self.w32(0x20, hyst_cnt)
        self.w32(0x24, hyst_cnt)
        if auto_rearm:
            self.configure_shield_autorearm(channels=0x3, dur=0)
            # delay pedido, en crudo; 0 -> 1 sample (evita el caso degenerado
            # set_dly=0 del bram_sm, que ignora los triggers).
            self.set_raw_delay(delay or 1)
        else:
            self.disable_shield()
        # arm (bit0) + we_keep (bit3) en una sola escritura, ch0 byte0 + ch1 byte1.
        # PRIMERO armar...
        b = 0x09 if we_keep_both else 0x01
        self.w32(0x00, (b << 8) | b)
        # ...y DESPUÉS habilitar la máscara (arm-antes-de-fuente, ver docstring).
        self.set_or_mask(mask_ch0, mask_ch1)

    def disarm(self):
        """Apaga we_keep, limpia el shield, limpia adc_trg_dis y resetea el
        FSM. Deja el scope en un estado IDLE limpio para la próxima corrida."""
        self.w32(0x00, 0x0000_0000)
        self.disable_shield()           # desactivar trigger_shield
        self.w32(0x94, 0x0000_0101)     # trig_dis_clr: limpia adc_trg_dis
        self.w32(0x00, 0x0000_0202)     # adc_rst_do[0] y [1]: reset FSM

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
        el loop np.fromiter (tests/bench_read_vs_length.py). Devuelve float32
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


# ---------- helpers offline ----------

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
