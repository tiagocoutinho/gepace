import asyncio
import urllib.parse

import tango
from tango.server import Device, attribute, command, device_property

from connio import connection_for_url
from gepace.pace import Pace as PaceHW, Mode, RateMode


def create_connection(address, connection_timeout=1, timeout=1):
    if address.startswith("tcp://"):
        address = address[6:]
        pars = address.split(":")
        host = pars[0]
        port = int(pars[1]) if len(pars) > 1 else 5025
        conn = TCP(host, port,
                   connection_timeout=connection_timeout,
                   timeout=timeout)
        return conn
    else:
        raise NotImplementedError(
            "address {!r} not supported".format(address))


ATTR_MAP = {
    "idn": lambda pace: pace.idn(),
    "startup_mode": lambda pace: pace.startup_mode(),
    "pressure1": lambda pace: pace[1].pressure(),
    "src_pressure1": lambda pace: pace[1].src_pressure(),
    "pressure1_setpoint": lambda pace: pace[1].src_pressure_setpoint(),
    "pressure1_overshoot": lambda pace: pace[1].src_pressure_rate_overshoot(),
    "pressure1_rate_mode": lambda pace: pace[1].src_pressure_rate_mode(),
    "pressure1_rate": lambda pace: pace[1].src_pressure_rate(),
    "pressure1_control": lambda pace: pace[1].pressure_control(),
    "unit1": lambda pace: pace[1].unit(),
    "error": lambda pace: pace.error()
}


class Pace(Device):

    green_mode = tango.GreenMode.Asyncio

    url = device_property(dtype=str)
    baudrate = device_property(dtype=int, default_value=9600)
    bytesize = device_property(dtype=int, default_value=8)
    parity = device_property(dtype=str, default_value='N')

    # If true, when setting a new setpoint, will also update the startup setpoint.
    # This is useful is the device needs to be restarted in the same conditions it was stopped
    sync_startup_set_point = device_property(dtype=bool, default_value=True)

    async def init_device(self):
        await super().init_device()
        self.lock = asyncio.Lock()
        kwargs = dict(concurrency="async")
        if self.url.startswith("serial:") or self.url.startswith("rfc2217:"):
            kwargs.update(dict(baudrate=self.baudrate, bytesize=self.bytesize,
                               parity=self.parity))
        elif self.url.startswith("tcp:"):
            addr = urllib.parse.urlparse(self.url)
            if addr.port is None:
                self.url += ":5025"
            kwargs["timeout"] = 1
            kwargs["connection_timeout"] = 1
        self.connection = connection_for_url(self.url, **kwargs)
        self.pace = PaceHW(self.connection)
        self.last_values = {}

    async def delete_device(self):
        await super().delete_device()
        await self.pace.close()

    async def read_attr_hardware(self, indexes):
        multi_attr = self.get_device_attr()
        names = [
            multi_attr.get_attr_by_ind(index).get_name().lower()
            for index in indexes
        ]
        funcs = [ATTR_MAP[name] for name in names]
        async with self.pace as group:
            [func(self.pace) for func in funcs]
        values = group.replies
        self.last_values = dict(zip(names, values))

    async def dev_state(self):
        try:
            control = await self.pace[1].pressure_control()
        except Exception:
            state = tango.DevState.FAULT
        else:
            state = tango.DevState.ON if control else tango.DevState.OFF
        self.set_state(state)
        return state

    async def dev_status(self):
        try:
            return await self._dev_status()
        except Exception as error:
            return repr(error)

    async def _dev_status(self):
        try:
            control = await self.pace[1].pressure_control()
        except Exception as error:
            self.__status = "Disconnected: {!r}\n".format(error)
        else:
            state = "Control (ON)" if control else "Measurement (OFF)"
            self.__status = "Connected; In {}".format(state)
        self.set_status(self.__status)
        return self.__status

    @attribute(dtype=str, description="Identification")
    def idn(self):
        return self.last_values["idn"]

    @attribute(dtype=float, unit="bar", label="Pressure")
    def pressure1(self):
        return self.last_values["pressure1"]

    @attribute(dtype=float, unit="bar", label="Source pressure",
               description="Source pressure (+ve)")
    def src_pressure1(self):
        return self.last_values["src_pressure1"]

    @attribute(dtype=float, unit="bar", label="Pressure setpoint",
               description="Pressure setpoint")
    def pressure1_setpoint(self):
        return self.last_values["pressure1_setpoint"]

    @pressure1_setpoint.write
    async def pressure1_setpoint(self, value):
        await self.pace[1].src_pressure_setpoint(value)
        if self.sync_startup_set_point:
            mode, set_point = await self.pace.startup_mode()
            if set_point != value:
                await self.pace.startup_mode([mode, value])

    @attribute(dtype=bool, label="Overshoot",
               description="pressure overshoot active?")
    def pressure1_overshoot(self):
        return self.last_values["pressure1_overshoot"]

    @pressure1_overshoot.write
    async def pressure1_overshoot(self, value):
        await self.pace[1].src_pressure_rate_overshoot(value)

    @attribute(dtype=str, label="Rate mode",
               description="Rate mode (linear or maximum) case insensitive")
    def pressure1_rate_mode(self):
        return self.last_values["pressure1_rate_mode"].name

    @pressure1_rate_mode.write
    async def pressure1_rate_mode(self, value):
        value = RateMode[value.capitalize()]
        await self.pace[1].src_pressure_rate_mode(value)

    @attribute(dtype=float, unit="bar/s", label="Rate",
               description="Pressure rate")
    def pressure1_rate(self):
        return self.last_values["pressure1_rate"]

    @pressure1_rate.write
    async def pressure1_rate(self, value):
        await self.pace[1].src_pressure_rate(value)

    @attribute(dtype=bool, label="Control",
               description="Control active?")
    def pressure1_control(self):
        return self.last_values["pressure1_control"]

    @pressure1_control.write
    async def pressure1_control(self, value):
        await self.pace[1].pressure_control(value)

    @attribute(dtype=[str], max_dim_x=2, label="Startup mode",
               description="Mode and pressure applied at startup")
    def startup_mode(self):
        mode, setpoint = self.last_values["startup_mode"]
        return [mode.name, str(setpoint)]

    @startup_mode.write
    async def startup_mode(self, value):
        mode = Mode[value[0].capitalize()]
        setpoint = float(value[1])
        await self.pace.startup_mode([mode, setpoint])

    @attribute(dtype=str)
    def error(self):
        code, error = self.last_values["error"]
        return "{}: {}".format(code, error) if code else ""

    @attribute(dtype=str, label="Unit")
    def unit1(self):
        return self.last_values["unit1"]

    @unit1.write
    async def unit1(self, value):
        await self.pace[1].unit(value)

    @command(dtype_in=str)
    async def write(self, data):
        async with self.lock:
            await self.conn.write(data.encode())

    @command(dtype_in=str, dtype_out=str)
    async def write_readline(self, data):
        async with self.lock:
            return (await self.conn.write_readline(data.encode())).decode()


if __name__ == "__main__":
    import logging
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level="DEBUG", format=fmt)
    GEPace.run_server()
