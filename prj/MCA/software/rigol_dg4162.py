"""
Driver mínimo para Rigol DG4162 (y resto de la serie DG4000), sin
dependencias externas (no requiere pyvisa). Soporta cuatro transportes:

  - USB-TMC vía /dev/usbtmcN (driver del kernel Linux).
  - USB crudo vía pyusb/libusb (`RigolDG4162.usb()`), para cuando el kernel
    no trae el módulo usbtmc — es el caso de la RedPitaya (5.15.0-xilinx).
  - TCP vía socket al puerto SCPI 5555.
  - VXI-11 sobre LAN.

Uso típico desde el notebook:

    from rigol_dg4162 import RigolDG4162

    rg = RigolDG4162.usb()          # o .usbtmc('/dev/usbtmc0') / .tcp(ip)
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

class _TransportUSBRaw:
    """Transporte USBTMC en espacio de usuario vía pyusb/libusb, sin depender
    del driver de kernel /dev/usbtmcN (que en la RedPitaya no está compilado:
    `modprobe usbtmc` → "Module usbtmc not found"). Implementa el protocolo
    USBTMC/USB488 mínimo sobre los endpoints bulk directamente.

    Notas de implementación (razón de cada una: el DG4162 stallea el bulk-OUT
    — [Errno 32] Pipe error — si no se respetan):

      - NO se llama `set_configuration()` si el device ya está configurado;
        libusb avisa que re-configurar hace perder estado al dispositivo.
      - Se reclama la interfaz explícitamente y se corre la secuencia de
        inicialización USBTMC (INITIATE_CLEAR/CHECK_CLEAR_STATUS), que deja
        los buffers del instrumento limpios aunque haya quedado a mitad de
        una transacción de una sesión anterior.
      - Todo stall se recupera con CLEAR_FEATURE(ENDPOINT_HALT) + reintento.
    """

    # --- USBTMC bulk message IDs ---
    MSG_ID_DEV_DEP_MSG_OUT = 1
    MSG_ID_REQUEST_DEV_DEP_MSG_IN = 2
    MSG_ID_DEV_DEP_MSG_IN = 2

    # --- USBTMC control requests (bmRequestType = 0xA1 iface / 0xA2 endpoint) ---
    INITIATE_ABORT_BULK_IN = 3
    CHECK_ABORT_BULK_IN_STATUS = 4
    INITIATE_CLEAR = 5
    CHECK_CLEAR_STATUS = 6
    GET_CAPABILITIES = 7

    STATUS_SUCCESS = 0x01
    STATUS_PENDING = 0x81

    USBTMC_CLASS = 0xFE      # Application Specific Interface
    USBTMC_SUBCLASS = 0x03   # Test and Measurement Class

    def __init__(self, vid=0x1ab1, pid=0x0641, serial=None):
        # Import diferido: así el módulo sigue importándose en máquinas sin
        # pyusb (la PC de desarrollo), donde solo se usan TCP/VXI-11.
        import usb.core
        import usb.util
        self._usb = usb

        # Si hay más de un instrumento con el mismo VID:PID, filtrar por serial.
        devs = list(usb.core.find(idVendor=vid, idProduct=pid, find_all=True))
        if not devs:
            raise IOError(f'No se encontró dispositivo USB {vid:04x}:{pid:04x}')
        if serial is not None:
            devs = [d for d in devs
                    if usb.util.get_string(d, d.iSerialNumber) == serial]
            if not devs:
                raise IOError(f'Ningún dispositivo {vid:04x}:{pid:04x} con serial {serial}')
        self.dev = devs[0]

        # Configuración activa. Solo se setea si el device NO está configurado:
        # `get_active_configuration()` tira USBError en ese caso.
        try:
            cfg = self.dev.get_active_configuration()
        except usb.core.USBError:
            self.dev.set_configuration()
            cfg = self.dev.get_active_configuration()

        # Buscar la interfaz USBTMC por clase (0xFE/0x03) en vez de asumir (0,0).
        intf = None
        for i in cfg:
            if (i.bInterfaceClass == self.USBTMC_CLASS
                    and i.bInterfaceSubClass == self.USBTMC_SUBCLASS):
                intf = i
                break
        if intf is None:
            raise IOError('El dispositivo no expone una interfaz USBTMC (0xFE/0x03)')
        self.iface_num = intf.bInterfaceNumber

        # En esta Pitaya no hay driver usbtmc en el kernel, pero por robustez
        # se desacopla igual antes de reclamar la interfaz.
        try:
            if self.dev.is_kernel_driver_active(self.iface_num):
                self.dev.detach_kernel_driver(self.iface_num)
        except (NotImplementedError, usb.core.USBError):
            pass

        try:
            usb.util.claim_interface(self.dev, self.iface_num)
        except usb.core.USBError as e:
            if e.errno == 16:  # EBUSY: otro proceso tiene la interfaz tomada
                raise IOError(
                    'La interfaz USBTMC está tomada por otro proceso (típicamente un '
                    'kernel de Jupyter que abrió el instrumento y no llamó a close()). '
                    'Reiniciá ese kernel, o mirá quién la tiene con: '
                    'fuser -v /dev/bus/usb/001/*') from e
            raise

        self.ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
            and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)
        self.ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
            and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK)
        if self.ep_out is None or self.ep_in is None:
            raise IOError('No se encontraron endpoints bulk IN/OUT en la interfaz USBTMC')
        self._mps_in = self.ep_in.wMaxPacketSize or 64

        self._btag = 0

        # Inicialización USBTMC: capabilities (informativo, algunos firmwares
        # lo esperan antes del primer bulk) + clear de los buffers.
        self.capabilities = self._get_capabilities()
        self.clear()

    # ---------- helpers de bajo nivel ----------

    def _next_btag(self):
        # bTag cicla 1..255, nunca 0 (0 está reservado por el spec USBTMC).
        self._btag = (self._btag % 255) + 1
        return self._btag

    def _clear_halt(self, ep):
        try:
            self.dev.clear_halt(ep.bEndpointAddress)
        except self._usb.core.USBError:
            pass

    def _get_capabilities(self):
        """GET_CAPABILITIES (0xA1, bRequest=7). Devuelve los 24 bytes crudos o
        None si el instrumento no lo soporta (no es fatal)."""
        try:
            return bytes(self.dev.ctrl_transfer(0xA1, self.GET_CAPABILITIES,
                                                0, self.iface_num, 0x18,
                                                timeout=1000))
        except self._usb.core.USBError:
            return None

    def clear(self):
        """INITIATE_CLEAR + CHECK_CLEAR_STATUS: descarta los buffers de entrada
        y salida del instrumento y deja los endpoints en estado conocido. Es la
        recuperación estándar de un stall (Pipe error)."""
        try:
            r = self.dev.ctrl_transfer(0xA1, self.INITIATE_CLEAR, 0,
                                       self.iface_num, 1, timeout=1000)
        except self._usb.core.USBError:
            self._clear_halt(self.ep_out)
            return False
        if not len(r) or r[0] != self.STATUS_SUCCESS:
            self._clear_halt(self.ep_out)
            return False

        for _ in range(100):
            try:
                r = self.dev.ctrl_transfer(0xA1, self.CHECK_CLEAR_STATUS, 0,
                                           self.iface_num, 2, timeout=1000)
            except self._usb.core.USBError:
                break
            if r[0] != self.STATUS_PENDING:
                break
            # bmClear bit0 = quedan datos en el bulk-IN: hay que drenarlos.
            if len(r) > 1 and (r[1] & 0x01):
                try:
                    self.ep_in.read(self._mps_in, 100)
                except self._usb.core.USBError:
                    pass
            time.sleep(0.01)

        # El spec exige limpiar el halt del bulk-OUT al terminar el CLEAR.
        self._clear_halt(self.ep_out)
        return True

    def _abort_bulk_in(self, btag):
        """INITIATE_ABORT_BULK_IN: cancela una transferencia IN que quedó
        pendiente (típico tras un timeout). Sin esto, el próximo query lee la
        respuesta vieja y todo queda corrido un mensaje."""
        try:
            r = self.dev.ctrl_transfer(0xA2, self.INITIATE_ABORT_BULK_IN, btag,
                                       self.ep_in.bEndpointAddress, 2, timeout=1000)
        except self._usb.core.USBError:
            self._clear_halt(self.ep_in)
            return
        if not len(r) or r[0] != self.STATUS_SUCCESS:
            self._clear_halt(self.ep_in)
            return
        for _ in range(100):
            try:
                self.ep_in.read(self._mps_in, 100)
            except self._usb.core.USBError:
                pass
            try:
                r = self.dev.ctrl_transfer(0xA2, self.CHECK_ABORT_BULK_IN_STATUS, 0,
                                           self.ep_in.bEndpointAddress, 8, timeout=1000)
            except self._usb.core.USBError:
                break
            if r[0] != self.STATUS_PENDING:
                break

    def _bulk_out(self, packet, tmo_ms):
        """Escribe en el bulk-OUT recuperándose de un stall (errno 32) una vez."""
        try:
            return self.ep_out.write(packet, tmo_ms)
        except self._usb.core.USBError as e:
            if e.errno != 32:  # EPIPE == stall; cualquier otra cosa se propaga
                raise
            self._clear_halt(self.ep_out)
            self.clear()
            return self.ep_out.write(packet, tmo_ms)

    def _bulk_in(self, nbytes, tmo_ms):
        try:
            return bytes(self.ep_in.read(nbytes, tmo_ms))
        except self._usb.core.USBError as e:
            if e.errno == 32:
                self._clear_halt(self.ep_in)
            raise

    # ---------- API de transporte ----------

    def write(self, data, timeout=None):
        tmo_ms = 5000 if timeout is None else max(1, int(timeout * 1000))
        btag = self._next_btag()
        header = bytes([
            self.MSG_ID_DEV_DEP_MSG_OUT,
            btag,
            (~btag) & 0xFF,
            0x00,
        ]) + len(data).to_bytes(4, 'little') + bytes([0x01, 0x00, 0x00, 0x00])
        # EOM=1 (bit0 de bmTransferAttributes): este mensaje termina acá.
        packet = header + data
        packet += b'\x00' * ((-len(packet)) % 4)  # alineación a 4 bytes (spec)
        self._bulk_out(packet, tmo_ms)

    def read(self, n=4096, timeout=None):
        tmo_ms = 5000 if timeout is None else max(1, int(timeout * 1000))
        # Buffer múltiplo de wMaxPacketSize: si libusb recibe más de lo que le
        # pedimos, el transfer falla con overflow.
        bufsize = ((n + 12 + self._mps_in - 1) // self._mps_in) * self._mps_in

        out = b''
        while True:
            btag = self._next_btag()
            # REQUEST_DEV_DEP_MSG_IN va por el mismo endpoint bulk OUT.
            req = bytes([
                self.MSG_ID_REQUEST_DEV_DEP_MSG_IN,
                btag,
                (~btag) & 0xFF,
                0x00,
            ]) + n.to_bytes(4, 'little') + bytes([0x00, 0x00, 0x00, 0x00])
            self._bulk_out(req, tmo_ms)

            try:
                resp = self._bulk_in(bufsize, tmo_ms)
            except self._usb.core.USBError as e:
                self._abort_bulk_in(btag)
                raise TimeoutError(f'USBTMC (pyusb) sin respuesta: {e}') from e

            if len(resp) < 12 or resp[0] != self.MSG_ID_DEV_DEP_MSG_IN:
                self.clear()
                raise IOError(f'Respuesta USBTMC inválida ({len(resp)} bytes): {resp[:12]!r}')

            size = int.from_bytes(resp[4:8], 'little')
            eom = bool(resp[8] & 0x01)
            payload = resp[12:12 + size]
            # El mensaje puede venir partido en varios transfers bulk.
            while len(payload) < size:
                try:
                    payload += self._bulk_in(bufsize, tmo_ms)
                except self._usb.core.USBError as e:
                    self._abort_bulk_in(btag)
                    raise TimeoutError(f'USBTMC: mensaje incompleto ({len(payload)}/{size}): {e}') from e
            out += payload[:size]

            if eom or len(out) >= n:
                return out

    def close(self):
        try:
            self._usb.util.release_interface(self.dev, self.iface_num)
        except Exception:
            pass
        self._usb.util.dispose_resources(self.dev)



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
    def usb(cls, vid=0x1ab1, pid=0x0641, serial=None):
        """Conexión USB directa vía pyusb/libusb (sin driver de kernel usbtmc).
        Usar cuando /dev/usbtmcN no está disponible."""
        return cls(_TransportUSBRaw(vid=vid, pid=pid, serial=serial))
        
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

    def clear(self):
        """Vacía los buffers de E/S del instrumento y limpia cualquier stall.
        Solo tiene efecto en el transporte USB crudo; en el resto es no-op."""
        clear = getattr(self._t, 'clear', None)
        return clear() if clear is not None else None

    def close(self):
        self._t.close()

    # ---------- alto nivel ----------

    def reset(self, settle_s=1.0, timeout=15.0):
        """*CLS + *RST, esperando a que el instrumento vuelva a responder.

        No se usa *OPC?: sobre USBTMC el DG4000 no lo contesta mientras está
        reseteando (y hay firmwares que directamente no lo implementan), así
        que el read se queda esperando una respuesta que nunca llega. En vez
        de eso se sondea con *IDN?, que responde apenas el reset termina.

        Sobre USBTMC un query sin respuesta es un timeout duro, no una espera:
        cada intento fallido aborta su transferencia bulk-IN pendiente antes
        de reintentar, para no leer una respuesta corrida en el próximo query.
        """
        self.write('*CLS')                     # vacía cola de errores primero
        self.write('*RST')
        time.sleep(settle_s)

        deadline = time.time() + timeout
        last = None
        while True:
            try:
                idn = self.query('*IDN?', timeout=1.0)
                if idn:
                    return idn
            except OSError as e:              # TimeoutError y USBError son OSError
                last = e
                if getattr(e, 'errno', None) == 19:   # ENODEV: se re-enumeró
                    raise IOError(
                        'El instrumento desapareció del bus USB durante el *RST; '
                        'hay que reabrir la conexión con RigolDG4162.usb()') from e
            if time.time() >= deadline:
                raise TimeoutError(
                    f'El Rigol no volvió a responder {timeout:g}s después de *RST'
                    + (f' (último error: {last})' if last else ''))
            self.clear()
            time.sleep(0.3)

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

    # ================================================================
    # Forma de onda ARBITRARIA
    #
    # Hace falta para caracterizar el MCA: con pulso rectangular no se puede
    # ni sintetizar un pulso de detector realista, ni generar dos poblaciones
    # con colas distintas (sin las cuales no hay FOM que medir), ni hacer el
    # sliding pulser que mide la DNL.
    #
    # AVISO: estos métodos siguen la guía de programación de la serie DG4000
    # pero NO pudieron probarse contra el instrumento. Verificar con
    # assert_ok() la primera vez que se usen.
    # ================================================================

    ARB_MAX_POINTS = 16384        # memoria de forma arbitraria por canal

    def load_arb(self, samples, ch=1, chunk=512, check_errors=True):
        """Carga una forma de onda normalizada en la memoria volátil del canal.

        `samples` es cualquier secuencia numérica; se re-escala automáticamente
        al rango [-1, 1] que espera el instrumento (la amplitud real la fija
        `set_arb` con amp_vpp). Se manda en trozos porque una sola línea SCPI
        con 16384 números supera el largo de comando admitido.
        """
        import numpy as _np
        v = _np.asarray(samples, dtype=float).ravel()
        if v.size == 0:
            raise ValueError('la forma de onda está vacía')
        if v.size > self.ARB_MAX_POINTS:
            raise ValueError(f'{v.size} puntos > {self.ARB_MAX_POINTS} '
                             'de memoria arbitraria')
        peak = _np.abs(v).max()
        if peak > 0:
            v = v / peak
        v = _np.clip(v, -1.0, 1.0)

        # El primer bloque abre VOLATILE; los siguientes concatenan con
        # :DATA:CATenate para no rearmar el comando entero.
        head = ','.join(f'{x:.5f}' for x in v[:chunk])
        self.write(f':SOURce{ch}:DATA VOLATILE,{head}')
        for i in range(chunk, v.size, chunk):
            blk = ','.join(f'{x:.5f}' for x in v[i:i + chunk])
            self.write(f':SOURce{ch}:DATA:CATenate VOLATILE,{blk}')
        if check_errors:
            self.assert_ok(f'load_arb(ch={ch}, n={v.size})')
        return v.size

    def set_arb(self, ch=1, freq_hz=1e3, amp_vpp=1.0, offset_v=0.0,
                phase_deg=0.0, check_errors=False):
        """Aplica la forma de onda cargada en VOLATILE.

        `freq_hz` es la frecuencia de REPETICIÓN de la forma completa. Si la
        forma contiene N pulsos, la tasa de pulsos es N*freq_hz — es así como
        se llega a tasas altas sin quedarse sin memoria.
        """
        self.write(f':SOURce{ch}:BURSt:STATe OFF')
        self.write(f':SOURce{ch}:APPLy:USER {freq_hz:g},{amp_vpp:g},'
                   f'{offset_v:g},{phase_deg:g}')
        if check_errors:
            self.assert_ok(f'set_arb(ch={ch}, f={freq_hz})')


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


# ================================================================
# Constructores de forma de onda (numpy puro, sin instrumento)
#
# Se dejan fuera de la clase a propósito: son funciones puras, así que se
# pueden graficar y validar sin tener el Rigol conectado.
# ================================================================

def detector_pulse(n_pts=64, t_rise=4.0, tau=16.0, amplitude=1.0, t0=2.0):
    """Pulso de detector: subida suave y cola exponencial.

    Es la forma que hace falta para que el MCA vea algo parecido a un evento
    real; un rectángulo no ejercita ni el tiempo de subida ni la relación
    Q_cola/Q_total, que es el observable del eje de forma.

    `tau` controla la cola: es el parámetro que separa las dos poblaciones en
    una medición de PSD.
    """
    import numpy as _np
    t = _np.arange(n_pts, dtype=float) - t0
    y = _np.where(t < 0, 0.0,
                  (1.0 - _np.exp(-t / max(t_rise, 1e-6))) * _np.exp(-t / max(tau, 1e-6)))
    peak = y.max()
    return (amplitude * y / peak) if peak > 0 else y


def two_population_wave(n_pulses=64, pts_per_pulse=128, tau_a=12.0, tau_b=40.0,
                        frac_b=0.5, amplitude=1.0, t_rise=4.0, seed=0):
    """Forma con dos poblaciones de pulsos que difieren SÓLO en la cola.

    Misma amplitud, distinto `tau`: es exactamente el estímulo que separa dos
    grupos en el eje de factor de forma sin moverlos en el eje de amplitud, o
    sea el caso que permite medir la FOM de forma limpia.
    """
    import numpy as _np
    rng = _np.random.default_rng(seed)
    out = _np.zeros(n_pulses * pts_per_pulse)
    for k in range(n_pulses):
        tau = tau_b if rng.random() < frac_b else tau_a
        out[k * pts_per_pulse:(k + 1) * pts_per_pulse] = detector_pulse(
            pts_per_pulse, t_rise=t_rise, tau=tau, amplitude=amplitude)
    return out


def sliding_pulser_wave(n_pulses=128, pts_per_pulse=128, tau=16.0,
                        t_rise=4.0, amp_min=0.1, amp_max=1.0, seed=0):
    """Forma con pulsos de amplitud UNIFORMEMENTE aleatoria (sliding pulser).

    Es el estímulo canónico para medir la DNL: si todos los canales tienen el
    mismo ancho, un barrido uniforme de amplitud tiene que llenarlos a todos
    por igual, y la desviación relativa respecto de esa media ES la DNL.
    """
    import numpy as _np
    rng = _np.random.default_rng(seed)
    out = _np.zeros(n_pulses * pts_per_pulse)
    amps = rng.uniform(amp_min, amp_max, n_pulses)
    for k, a in enumerate(amps):
        out[k * pts_per_pulse:(k + 1) * pts_per_pulse] = detector_pulse(
            pts_per_pulse, t_rise=t_rise, tau=tau, amplitude=a)
    return out
