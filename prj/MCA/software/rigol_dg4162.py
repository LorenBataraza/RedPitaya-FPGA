"""
Driver mínimo para Rigol DG4162 (y resto de la serie DG4000), sin
dependencias externas (no requiere pyvisa). Soporta dos transportes:

  - USB-TMC vía /dev/usbtmcN (driver del kernel Linux, default).
  - TCP vía socket al puerto SCPI 5555.

Uso típico desde el notebook:

    from rigol_dg4162 import RigolDG4162

    rg = RigolDG4162.usbtmc('/dev/usbtmc0')
    print(rg.id)
    rg.reset()
    rg.set_pulse_periodic(ch=1, period_s=100e-6, width_s=200e-9,
                          amp_vpp=1.0, offset_v=0.5)
    rg.output(1, True)
    # ... corre tu test ...
    rg.output(1, False)
    rg.close()

Para sweep de distancia entre pulsos:

    for p in periods:
        rg.set_pulse_period(ch=1, period_s=p)
        # capturás y medís eficiencia
"""

import select
import socket
import time

class _TransportVXI11:
    def __init__(self, host):
        import vxi11
        self.instr = vxi11.Instrument(host)

    def write(self, b):
        self.instr.write(b.decode().strip())

    def read(self, n=4096, timeout=None):
        if timeout is not None:
            self.instr.timeout = timeout
        try:
            return self.instr.read_raw()
        except Exception as e:
            raise TimeoutError(f'VXI-11 read timeout/error: {e}') from e

    def close(self):
        self.instr.close()

class _TransportUSBTMC:
    def __init__(self, device='/dev/usbtmc0'):
        self.f = open(device, 'r+b', buffering=0)

    def write(self, b):
        self.f.write(b)

    def read(self, n=4096, timeout=None):
        # select() sobre el fd del USBTMC: si no hay datos en `timeout` segundos
        # devolvemos TimeoutError antes de tocar f.read() (que bloquea sin límite).
        if timeout is not None:
            r, _, _ = select.select([self.f], [], [], timeout)
            if not r:
                raise TimeoutError(f'USBTMC sin respuesta en {timeout}s')
        return self.f.read(n)

    def close(self):
        self.f.close()


class _TransportTCP:
    def __init__(self, host, port=5555, timeout=5):
        self.s = socket.create_connection((host, port), timeout=timeout)

    def write(self, b):
        self.s.sendall(b)

    def read(self, n=4096, timeout=None):
        if timeout is not None:
            self.s.settimeout(timeout)
        try:
            return self.s.recv(n)
        except socket.timeout as e:
            raise TimeoutError(f'TCP sin respuesta en {timeout}s') from e

    def close(self):
        self.s.close()


class RigolDG4162:
    """Cliente SCPI para el Rigol DG4162 (160 MHz AWG). Métodos cubren el flujo
    de generación de pulsos para validación del scope multitrigger."""

    # Timeout default para todos los reads (segundos). Aplica a `query()`,
    # `check_error()`, etc. Si el instrumento no responde en este tiempo se
    # lanza TimeoutError en vez de colgar el proceso.
    DEFAULT_READ_TIMEOUT = 2.0

    def __init__(self, transport, read_timeout=None):
        self._t = transport
        self._read_timeout = read_timeout if read_timeout is not None else self.DEFAULT_READ_TIMEOUT
        self.id = self.query('*IDN?')

    # ---------- factory methods ----------

    @classmethod
    def usbtmc(cls, device='/dev/usbtmc0'):
        """Conexión por USB. Probá `ls /dev/usbtmc*` para ver el device disponible."""
        return cls(_TransportUSBTMC(device))

    @classmethod
    def tcp(cls, host, port=5555):
        """Conexión TCP/IP (puerto 5555 SCPI raw, standard en los Rigol DG4000)."""
        return cls(_TransportTCP(host, port))

    @classmethod
    def vxi11(cls, host):
        """Conexión VXI-11 sobre LAN (más robusta que raw TCP en redes con proxy)."""
        return cls(_TransportVXI11(host))
    
    # ---------- SCPI low-level ----------

    def write(self, cmd):
        self._t.write(cmd.encode() + b'\n')

    def query(self, cmd, delay=0.05, timeout=None):
        """Write + read con timeout. Si el instrumento no responde, lanza
        TimeoutError (no se cuelga el proceso). `timeout=None` usa el default
        de la instancia (`self._read_timeout`)."""
        if timeout is None:
            timeout = self._read_timeout
        self.write(cmd)
        time.sleep(delay)
        return self._t.read(timeout=timeout).decode().strip()

    def close(self):
        self._t.close()

    # ---------- alto nivel ----------

    def reset(self):
        """*RST + *CLS + *OPC? para esperar a que el reset termine. El sleep
        anterior era arbitrario y a veces se quedaba corto (Rigol DG4000
        puede tardar >1 s en resetear); *OPC? bloquea hasta que todos los
        comandos pendientes terminaron."""
        self.write('*CLS')                     # vacía cola de errores primero
        self.write('*RST')
        # *OPC? devuelve "1" cuando el reset completó. Damos timeout generoso.
        self.query('*OPC?', timeout=5.0)

    def output(self, ch, on, check_errors=False):
        """Enciende/apaga la salida del canal (ch=1 o 2).
        Con `check_errors=True` se valida la cola SCPI después del comando
        (1 round-trip extra)."""
        self.write(f':OUTPut{ch}:STATe {"ON" if on else "OFF"}')
        if check_errors:
            self.assert_ok(f'output(ch={ch}, on={on})')

    def assert_ok(self, ctx=''):
        """Lee la cola de errores SCPI con :SYSTem:ERRor? y lanza RuntimeError
        si el último comando dejó un error. `ctx` es texto libre para identificar
        qué llamada lo provocó.

        El Rigol responde 0 (o '+0') seguido de la descripción cuando no hay
        error; cualquier otro código numérico indica falla."""
        err = self.check_error()
        # Formato típico: '0,"No error"' o '-221,"Settings conflict"'.
        code = err.split(',', 1)[0].strip().lstrip('+')
        if code != '0':
            raise RuntimeError(f'Rigol SCPI error tras {ctx}: {err}')

    def set_pulse_periodic(self, ch=1, period_s=100e-6, width_s=200e-9,
                            amp_vpp=1.0, offset_v=0.5, check_errors=False):
        """Tren de pulsos PERIÓDICO con `period_s` entre flancos ascendentes.

        Parámetros:
          ch            : canal del Rigol (1 o 2).
          period_s      : período entre pulsos (s). 1/freq.
          width_s       : ancho de cada pulso (s). Tiene que ser < period_s/2.
          amp_vpp       : amplitud pico-pico (V).
          offset_v      : nivel DC del cero del pulso (V). Con amp_vpp=1.0 y
                          offset_v=0.5 el pulso va de 0 V a +1 V.
          check_errors  : si True, valida la cola SCPI después de los comandos.
                          Default False para no pagar el round-trip extra en
                          sweeps; subilo a True cuando estés debugueando.
        """
        if width_s >= period_s / 2:
            raise ValueError(f'width_s ({width_s}) debe ser < period_s/2 ({period_s/2})')
        freq = 1.0 / period_s
        # APPLy:PULSe <freq>,<vpp>,<offset>,<phase>
        self.write(f':SOURce{ch}:APPLy:PULSe {freq},{amp_vpp},{offset_v}')
        self.write(f':SOURce{ch}:PULSe:WIDTh {width_s}')
        # Asegurar burst off (modo continuo)
        self.write(f':SOURce{ch}:BURSt:STATe OFF')
        if check_errors:
            self.assert_ok(f'set_pulse_periodic(ch={ch}, period={period_s}, width={width_s})')

    def set_pulse_period(self, ch=1, period_s=100e-6, check_errors=False):
        """Cambiar SOLO el período de un pulse ya configurado (sweep barato).
        `check_errors=True` valida la cola SCPI después (round-trip extra)."""
        freq = 1.0 / period_s
        self.write(f':SOURce{ch}:FREQuency {freq}')
        if check_errors:
            self.assert_ok(f'set_pulse_period(ch={ch}, period={period_s})')

    def set_pulse_width(self, ch=1, width_s=200e-9, check_errors=False):
        """Cambiar SOLO el ancho del pulso.
        `check_errors=True` valida la cola SCPI después (round-trip extra)."""
        self.write(f':SOURce{ch}:PULSe:WIDTh {width_s}')
        if check_errors:
            self.assert_ok(f'set_pulse_width(ch={ch}, width={width_s})')

    def set_pulse_pair_burst(self, ch=1, gap_s=10e-6, width_s=200e-9,
                              amp_vpp=1.0, offset_v=0.5, burst_period_s=10e-3,
                              check_errors=False):
        """PAR DE PULSOS por burst: dos pulsos separados por `gap_s`, repetidos
        cada `burst_period_s`. Ideal para medir resolución par-pulso (pulse-pair
        resolution): cuán cerca pueden estar dos pulsos seguidos y todavía ser
        registrados como dos eventos distintos.

        Layout temporal por burst:
          |--width--|--(gap-width)--|--width--|--silencio (burst_period - 2*gap)--|
              ↑                          ↑
            pulso 1                   pulso 2  (flanco ascendente separado por gap)

        Parámetros:
          gap_s          : distancia entre los dos flancos ascendentes (s).
          width_s        : ancho de cada pulso.
          burst_period_s : tiempo entre el inicio de un par y el siguiente.
        """
        if width_s >= gap_s:
            raise ValueError(f'width_s ({width_s}) debe ser < gap_s ({gap_s})')
        if burst_period_s <= 2 * gap_s:
            raise ValueError(f'burst_period_s ({burst_period_s}) tiene que ser '
                             f'> 2*gap_s ({2 * gap_s})')
        # gap_s = período del pulse → 1/freq dentro del burst
        freq = 1.0 / gap_s
        self.write(f':SOURce{ch}:APPLy:PULSe {freq},{amp_vpp},{offset_v}')
        self.write(f':SOURce{ch}:PULSe:WIDTh {width_s}')
        self.write(f':SOURce{ch}:BURSt:NCYCles 2')
        self.write(f':SOURce{ch}:BURSt:MODE TRIG')
        self.write(f':SOURce{ch}:BURSt:TRIGger:SOURce INTernal')
        self.write(f':SOURce{ch}:BURSt:INTernal:PERiod {burst_period_s}')
        self.write(f':SOURce{ch}:BURSt:STATe ON')
        if check_errors:
            self.assert_ok(f'set_pulse_pair_burst(ch={ch}, gap={gap_s}, burst_period={burst_period_s})')

    def disable_burst(self, ch=1, check_errors=False):
        self.write(f':SOURce{ch}:BURSt:STATe OFF')
        if check_errors:
            self.assert_ok(f'disable_burst(ch={ch})')

    # ---------- helpers ----------

    def check_error(self):
        """Devuelve el último error SCPI (o '0,\"No error\"' si OK).
        Usa timeout corto: si no responde es síntoma de hang, no demora."""
        return self.query(':SYSTem:ERRor?', timeout=1.0)

    def drain(self):
        """Vacía cualquier respuesta pendiente en la cola del transporte (sin
        bloquear). Útil si quedó algo de un Ctrl+C anterior y el próximo
        query() lee la respuesta vieja en vez de la nueva."""
        try:
            while True:
                self._t.read(timeout=0.1)
        except TimeoutError:
            return

    def __repr__(self):
        return f'<RigolDG4162 {self.id!r}>'
