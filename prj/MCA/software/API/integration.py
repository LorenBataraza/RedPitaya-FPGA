#!/usr/bin/env python3
"""Región de TOP (integración): identificación, descubrimiento y ruteo.

Slot 6 del bus de sistema (0x4060_0000). Es la región que el refactor de
registros añadió por encima de los módulos: dice **qué** bitstream está
cargado, **qué** módulos trae, **en qué slot** vive cada uno, y **de dónde**
toma sus muestras cada consumidor de la cadena DSP.

    from API.integration import (Integration, integration_open,
                                 integration_set_route_mca, TAP_ADC)

    ig = integration_open()
    ig.identify()                              # magic, versión, hash de git
    integration_set_route_mca(ig, TAP_ADC)     # el MCA pasa a la muestra cruda

No es housekeeping: `red_pitaya_hk` (slot 0) es un módulo de RedPitaya (LEDs,
E1/E2, DNA) y sigue donde estaba. Ver `docs/TOP/register_map_top.md`.

**Por qué existe el descubrimiento.** El multitrigger vive en el slot 3 de
`mca_red_pitaya_top` y `event_ring_red_pitaya_top`, pero en el `red_pitaya_top`
clásico está en el **7**, porque ahí los slots 2 y 3 los ocupan el ASG y el PID.
Un driver que hardcodea la base funciona en un bitstream y escribe a la nada en
el otro — sin excepción, porque el esclavo hace ack igual. `slot_base()` lee el
mapa real en vez de suponerlo.
"""

import mmap
import os
import struct

_U32 = struct.Struct('<I')

INTEGRATION_PHYS = 0x4060_0000          # slot 6 del sys bus
INTEGRATION_SIZE = 0x1000               # la región entera son 64 registros

MAGIC = 0x494E5447                      # "INTG"

SYS_BUS_BASE = 0x4000_0000              # base del bus; slot n = BASE + n*0x100000
SYS_BUS_SLOT = 0x0010_0000

# --- identificación ---
R_MAGIC   = 0x000
R_VERSION = 0x004                       # {mayor[31:24], menor, parche, variante}
R_GITH_0  = 0x008                       # hash de git, 160 b en cinco palabras
R_GITH_1  = 0x00C
R_GITH_2  = 0x010
R_GITH_3  = 0x014
R_GITH_4  = 0x018
# --- descripción del sistema ---
R_MODULES = 0x020                       # bit por módulo presente
R_SLOTS   = 0x024                       # nibble por módulo
R_CAPS_0  = 0x028                       # {EN_FILT[24], RSZ[21:16], DW[13:8], N_CH[3:0]}
R_CAPS_1  = 0x02C                       # {PSD_AW[23:16], H2_AW[15:8], H_AW[7:0]}
# --- ruteo del datapath ---
R_ROUTE_OSC  = 0x030                    # los cuatro: {en[8], tap[1:0]}
R_ROUTE_MTRG = 0x034
R_ROUTE_MCA  = 0x038
R_ROUTE_RING = 0x03C
# --- control y estado global ---
R_CTRL   = 0x040                        # bit0 run, bit1 clear*, bit2 soft_reset*
R_STATUS = 0x044                        # bit0 pll_locked, bit1 adc_rstn

# --- bits de MODULES ---
MOD_OSC  = 1 << 0
MOD_MTRG = 1 << 1
MOD_MCA  = 1 << 2
MOD_RING = 1 << 3
MOD_ASG  = 1 << 4
MOD_PID  = 1 << 5

# --- bits de CTRL ---
CTRL_RUN   = 1 << 0
CTRL_CLEAR = 1 << 1                     # autolimpiante en HW (dura 1 ciclo)
CTRL_SRST  = 1 << 2                     # autolimpiante en HW (dura 1 ciclo)

# --- bits de STATUS ---
ST_PLL_LOCKED = 1 << 0
ST_ADC_RSTN   = 1 << 1


# =============================================================================
# Taps de la cadena DSP
# =============================================================================
#
# La lista canónica vive en integration_cfg.sv; ésta es su espejo. La cadena:
#
#   adc_dat -> calib -> osc_filter -> [byp] -> adc_dec_in ------------- TAP 2
#      |                                          |                       `-> MCA (nativo)
#    TAP 1                                    rp_decim -> adc_dly_in
#                                                 |           `-> multitrigger (nativo)
#                                             rp_delay -> adc_bram_in --- TAP 3
#                                                               `-> OSC (nativo)

TAP_NATIVE  = 0     # como estaba cableado antes del refactor. Es el RESET.
TAP_ADC     = 1     # muestra cruda, ANTES de calibración y ecualizador
TAP_DEC_IN  = 2     # post-calib/ecualizador, PRE-decimación (125 MSPS)
TAP_BRAM_IN = 3     # después de todo el DSP (decimación + delay)

TAP_NAMES = {TAP_NATIVE: 'nativo', TAP_ADC: 'adc_dat',
             TAP_DEC_IN: 'adc_dec_in', TAP_BRAM_IN: 'adc_bram_in'}

# El nativo de cada consumidor, para poder informarlo sin adivinar. El del
# multitrigger NO es ninguno de los tres taps: es adc_dly_in, post-decimación
# pero PRE-delay. Por eso TAP_NATIVE existe como valor aparte.
TAP_NATIVO_DE = {'osc': 'adc_bram_in', 'mtrg': 'adc_dly_in',
                 'mca': 'adc_dec_in',  'ring': 'adc_dec_in'}

_R_ROUTE = {'osc': R_ROUTE_OSC, 'mtrg': R_ROUTE_MTRG,
            'mca': R_ROUTE_MCA, 'ring': R_ROUTE_RING}


class IntegrationNotPresent(RuntimeError):
    """El bitstream cargado no tiene la región de TOP en el slot 6.

    Pasa con cualquier bitstream anterior al refactor de registros. No es
    fatal: los drivers siguen andando con sus bases por defecto, sólo se
    pierden el descubrimiento y el ruteo.
    """


# =============================================================================
# Driver
# =============================================================================

class Integration:
    """Acceso a la región de TOP por /dev/mem."""

    def __init__(self, mem, fd):
        self._mmap = mem
        self._fd   = fd

    @classmethod
    def open(cls, phys=INTEGRATION_PHYS, size=INTEGRATION_SIZE, check_magic=True):
        """Mapear la región de TOP.

        Igual que el resto de los drivers: si la PL no está programada la
        PRIMERA lectura mata el proceso con SIGBUS sin traceback.
        `API.fpga.fpga_state()` permite chequearlo antes.
        """
        fd = os.open('/dev/mem', os.O_RDWR | os.O_SYNC)
        try:
            m = mmap.mmap(fd, size, mmap.MAP_SHARED,
                          mmap.PROT_READ | mmap.PROT_WRITE, offset=phys)
        except Exception:
            os.close(fd)
            raise
        dev = cls(m, fd)
        if check_magic:
            got = dev.r32(R_MAGIC)
            if got != MAGIC:
                dev.close()
                raise IntegrationNotPresent(
                    f'MAGIC {got:#010x} en {phys:#010x}, esperado {MAGIC:#010x} '
                    '("INTG"). El bitstream no tiene región de TOP: es anterior '
                    'al refactor de registros, o el slot 6 lo ocupa otra cosa.')
        return dev

    def close(self):
        try:
            self._mmap.close()
        finally:
            os.close(self._fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def w32(self, off, v):
        # Asignación por slice, NO struct.pack_into: pack_into hace un memset
        # previo que sobre memoria de dispositivo sale como stores de a byte,
        # el esclavo AXI no los reconoce y el puente GP0 tira un external abort
        # -> SIGBUS. Ver tests/test_rw_dev_mem.py.
        self._mmap[off:off+4] = _U32.pack(v & 0xFFFFFFFF)

    def r32(self, off):
        return _U32.unpack_from(self._mmap, off)[0]

    # ---------- identificación ----------

    def identify(self, verbose=True):
        """Magic, versión y hash de git del bitstream cargado."""
        v = self.r32(R_VERSION)
        info = {
            'magic':   self.r32(R_MAGIC),
            'version': ((v >> 24) & 0xFF, (v >> 16) & 0xFF,
                        (v >> 8) & 0xFF, v & 0xFF),
            'gith':    ''.join(f'{self.r32(o):08x}' for o in
                               (R_GITH_4, R_GITH_3, R_GITH_2, R_GITH_1, R_GITH_0)),
        }
        if verbose:
            may, men, par, var = info['version']
            print(f'región de TOP: magic {info["magic"]:#010x} '
                  f'v{may}.{men}.{par} (variante {var})')
            print(f'  git {info["gith"]}')
        return info

    # ---------- descripción del sistema ----------

    def modules(self):
        """Qué módulos trae este bitstream, como dict de bool."""
        w = self.r32(R_MODULES)
        return {'osc':  bool(w & MOD_OSC),  'mtrg': bool(w & MOD_MTRG),
                'mca':  bool(w & MOD_MCA),  'ring': bool(w & MOD_RING),
                'asg':  bool(w & MOD_ASG),  'pid':  bool(w & MOD_PID)}

    def slots(self):
        """En qué slot vive cada módulo EN ESTE bitstream.

        No es decorativo: el multitrigger está en el slot 3 del top del MCA y
        en el 7 del `red_pitaya_top` clásico.
        """
        w = self.r32(R_SLOTS)
        return {'osc':  (w >> 0)  & 0xF, 'ring': (w >> 4)  & 0xF,
                'mtrg': (w >> 8)  & 0xF, 'top':  (w >> 12) & 0xF,
                'mca':  (w >> 16) & 0xF}

    def base(self, modulo):
        """Dirección física de la base de un módulo, según el mapa real."""
        return SYS_BUS_BASE + self.slots()[modulo] * SYS_BUS_SLOT

    def caps(self):
        """Parámetros de síntesis: anchos, número de canales, profundidades."""
        c0, c1 = self.r32(R_CAPS_0), self.r32(R_CAPS_1)
        return {'n_ch':    (c0 >> 0)  & 0xF,
                'dw':      (c0 >> 8)  & 0x3F,
                'rsz':     (c0 >> 16) & 0x3F,
                'en_filt': bool(c0 & (1 << 24)),
                'h_aw':    (c1 >> 0)  & 0xFF,
                'h2_aw':   (c1 >> 8)  & 0xFF,
                'psd_aw':  (c1 >> 16) & 0xFF}

    # ---------- ruteo del datapath ----------

    def get_route(self, consumidor):
        """`{'tap': int, 'nombre': str, 'enable': bool}` de un consumidor.

        `consumidor` es 'osc', 'mtrg', 'mca' o 'ring'.
        """
        w = self.r32(_R_ROUTE[consumidor])
        tap = w & 0x3
        nombre = (TAP_NATIVO_DE[consumidor] + ' (nativo)' if tap == TAP_NATIVE
                  else TAP_NAMES[tap])
        return {'tap': tap, 'nombre': nombre, 'enable': bool(w & (1 << 8))}

    def set_route(self, consumidor, tap=TAP_NATIVE, enable=True, verify=True):
        """Elegir de qué punto de la cadena DSP toma sus muestras un consumidor.

        Con `enable=False` el `val` del consumidor se fuerza a 0: deja de
        recibir muestras sin tocar el resto del sistema.

        OJO, cambiar de tap CORRE LA LATENCIA: `rp_bram_sm` cuenta el delay en
        muestras decimadas, así que un OSC en TAP_ADC y un multitrigger en
        nativo desalinean el pre-trigger. Es legítimo, no es gratis.

        OJO 2, el camino a DDR por AXI NO se rutea: `rp_axi_sm` sigue siempre en
        su nodo nativo, así que esto afecta la captura en BRAM pero no las
        capturas `rp_AcqAxi*`.
        """
        if tap not in TAP_NAMES:
            raise ValueError(f'tap {tap!r} inválido; usar TAP_NATIVE/TAP_ADC/'
                             'TAP_DEC_IN/TAP_BRAM_IN')
        off = _R_ROUTE[consumidor]
        self.w32(off, (tap & 0x3) | ((1 if enable else 0) << 8))
        if verify:
            rb = self.r32(off)
            esperado = (tap & 0x3) | ((1 if enable else 0) << 8)
            if (rb & 0x103) != esperado:
                raise RuntimeError(
                    f'ROUTE_{consumidor.upper()} no latcheó: {rb:#010x} '
                    f'!= {esperado:#010x}')

    def routes(self):
        """Los cuatro ruteos de una, para imprimir."""
        return {c: self.get_route(c) for c in _R_ROUTE}

    def reset_routes(self):
        """Devolver los cuatro consumidores a NATIVO habilitado.

        Es el estado de reset del hardware, o sea el comportamiento
        pre-refactor. Sirve para volver a terreno conocido sin recargar el
        bitstream.
        """
        for c in _R_ROUTE:
            self.set_route(c, TAP_NATIVE, enable=True)

    # ---------- control y estado global ----------

    def set_run(self, on=True):
        self.w32(R_CTRL, CTRL_RUN if on else 0)

    def get_run(self):
        return bool(self.r32(R_CTRL) & CTRL_RUN)

    def clear(self):
        """Pulso global de clear (el HW lo autolimpia en un ciclo)."""
        self.w32(R_CTRL, (self.r32(R_CTRL) & CTRL_RUN) | CTRL_CLEAR)

    def soft_reset(self):
        """Pulso global de soft reset (autolimpiante)."""
        self.w32(R_CTRL, (self.r32(R_CTRL) & CTRL_RUN) | CTRL_SRST)

    def status(self):
        w = self.r32(R_STATUS)
        return {'pll_locked': bool(w & ST_PLL_LOCKED),
                'adc_rstn':   bool(w & ST_ADC_RSTN)}

    # ---------- volcado ----------

    def dump(self):
        """Volcado legible de la región entera."""
        self.identify()
        mods = self.modules()
        slots = self.slots()
        print('  módulos:', ' '.join(k for k, v in mods.items() if v) or '(ninguno)')
        print('  slots:  ', ' '.join(f'{k}={v}' for k, v in sorted(
            slots.items(), key=lambda kv: kv[1])))
        c = self.caps()
        print(f'  caps:    n_ch={c["n_ch"]} dw={c["dw"]} rsz={c["rsz"]} '
              f'en_filt={c["en_filt"]} h_aw={c["h_aw"]} h2_aw={c["h2_aw"]} '
              f'psd_aw={c["psd_aw"]}')
        for nombre, r in self.routes().items():
            marca = '' if r['enable'] else '   [DESHABILITADO]'
            print(f'  route {nombre:<5} tap={r["tap"]} {r["nombre"]}{marca}')
        st = self.status()
        print(f'  status:  pll_locked={st["pll_locked"]} adc_rstn={st["adc_rstn"]} '
              f'run={self.get_run()}')


# =============================================================================
# Descubrimiento de bases — lo usan los otros drivers
# =============================================================================

def slot_base(modulo, default=None):
    """Base física de un módulo leída del bitstream, o `default` si no se puede.

    Devuelve `default` —sin lanzar— cuando no hay región de TOP, no hay
    /dev/mem o la PL no está programada: un driver que hardcodeaba su base
    tiene que poder seguir hardcodeándola. Lo que se gana es que, cuando la
    información ESTÁ, se usa.

    Se abre y se cierra el mapeo en cada llamada a propósito: se llama una vez
    por `open()` de driver, no en ningún camino caliente.
    """
    try:
        with Integration.open() as ig:
            return ig.base(modulo)
    except (IntegrationNotPresent, OSError, ValueError, KeyError):
        return default


# =============================================================================
# API por nombre — nomenclatura <módulo>_<capa>_<campo> (ver API/README.md)
# =============================================================================

def integration_open(phys=INTEGRATION_PHYS, size=INTEGRATION_SIZE,
                     check_magic=True):
    return Integration.open(phys, size, check_magic)


def integration_close(ig):
    ig.close()


def integration_identify(ig, verbose=True):
    return ig.identify(verbose)


def integration_dump(ig):
    return ig.dump()


# --- descripción del sistema ---

def integration_get_modules(ig):     return ig.modules()
def integration_get_slots(ig):       return ig.slots()
def integration_get_base(ig, m):     return ig.base(m)
def integration_get_caps(ig):        return ig.caps()


# --- ruteo ---

def integration_get_routes(ig):      return ig.routes()
def integration_reset_routes(ig):    ig.reset_routes()


def integration_get_route_osc(ig):   return ig.get_route('osc')
def integration_get_route_mtrg(ig):  return ig.get_route('mtrg')
def integration_get_route_mca(ig):   return ig.get_route('mca')
def integration_get_route_ring(ig):  return ig.get_route('ring')


def integration_set_route_osc(ig, tap=TAP_NATIVE, enable=True):
    ig.set_route('osc', tap, enable)


def integration_set_route_mtrg(ig, tap=TAP_NATIVE, enable=True):
    ig.set_route('mtrg', tap, enable)


def integration_set_route_mca(ig, tap=TAP_NATIVE, enable=True):
    ig.set_route('mca', tap, enable)


def integration_set_route_ring(ig, tap=TAP_NATIVE, enable=True):
    ig.set_route('ring', tap, enable)


# --- control global ---

def integration_get_run(ig):         return ig.get_run()
def integration_set_run(ig, on=True): ig.set_run(on)
def integration_clear(ig):           ig.clear()
def integration_soft_reset(ig):      ig.soft_reset()
def integration_get_status(ig):      return ig.status()


if __name__ == '__main__':
    with Integration.open() as _ig:
        _ig.dump()
