import asyncio

import tango
from tango.server import Device, attribute, command, device_property

from sockio.aio import TCP
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
    "mode": lambda pace: pace.mode(),
    "pressure1": lambda pace: pace[1].pressure(),
    "src_pressure1": lambda pace: pace[1].src_pressure(),
    "pressure1_setpoint": lambda pace: pace[1].src_pressure_setpoint(),
    "pressure1_overshoot": lambda pace: pace[1].src_pressure_rate_overshoot(),
    "pressure1_rate_mode": lambda pace: pace[1].src_pressure_rate_mode(),
    "pressure1_rate": lambda pace: pace[1].src_pressure_rate(),
    "pressure1_control": lambda pace: pace[1].pressure_control(),
    "error": lambda pace: pace.error()
}


class Pace(Device):

    green_mode = tango.GreenMode.Asyncio

    address = device_property(dtype=str)

    async def init_device(self):
        await super().init_device()
        self.lock = asyncio.Lock()
        self.conn = create_connection(self.address)
        self.pace = PaceHW(self.conn)
        self.last_values = {}

    async def read_attr_hardware(self, indexes):
        multi_attr = self.get_device_attr()
        names = [
            multi_attr.get_attr_by_ind(index).get_name().lower()
            for index in indexes
        ]
        funcs = [ATTR_MAP[name] for name in names]
        try:
            async with self.lock:
                async with self.pace as group:
                    [func(self.pace) for func in funcs]
                values = group.replies
        except OSError as error:
            self.set_state(tango.DevState.FAULT)
            self.set_status("Communication error: {!r}".format(error))
            raise
        self.set_state(tango.DevState.ON)
        self.set_status("OK")
        self.last_values = dict(zip(names, values))

    @attribute(dtype=str)
    def idn(self):
        return self.last_values["idn"]

    @attribute(dtype=float, unit="mbar")
    def pressure1(self):
        return self.last_values["pressure1"]

    @attribute(dtype=float, unit="mbar")
    def src_pressure1(self):
        return self.last_values["src_pressure1"]

    @attribute(dtype=float, unit="mbar")
    def pressure1_setpoint(self):
        return self.last_values["pressure1_setpoint"]

    @pressure1_setpoint.write
    async def pressure1_setpoint(self, value):
        await self.pace[1].src_pressure_setpoint(value)

    @attribute(dtype=bool)
    def pressure1_overshoot(self):
        return self.last_values["pressure1_overshoot"]

    @pressure1_overshoot.write
    async def pressure1_overshoot(self, value):
        await self.pace[1].src_pressure_rate_overshoot(value)

    @attribute(dtype=str)
    def pressure1_rate_mode(self):
        return self.last_values["pressure1_rate_mode"].name

    @pressure1_rate_mode.write
    async def pressure1_rate_mode(self, value):
        value = RateMode[value.capitalize()]
        await self.pace[1].src_pressure_rate_mode(value)

    @attribute(dtype=float, unit="mbar/s")
    def pressure1_rate(self):
        return self.last_values["pressure1_rate"]

    @pressure1_rate.write
    async def pressure1_rate(self, value):
        await self.pace[1].src_pressure_rate(value)

    @attribute(dtype=bool)
    def pressure1_control(self):
        return self.last_values["pressure1_control"]

    @pressure1_control.write
    async def pressure1_control(self, value):
        await self.pace[1].pressure_control(value)

    @attribute(dtype=[str], max_dim_x=2)
    def mode(self):
        mode, setpoint = self.last_values["mode"]
        return [mode.name, str(setpoint)]

    @mode.write
    async def mode(self, value):
        mode = Mode[value[0].capitalize()]
        setpoint = float(value[1])
        await self.pace.mode([mode, setpoint])

    @attribute(dtype=str)
    def error(self):
        code, error = self.last_values["error"]
        return "{}: {}".format(code, error) if code else ""

    @command(dtype_in=str)
    async def write(self, data):
        await self.conn.write(data.encode())

    @command(dtype_in=str, dtype_out=str)
    async def write_readline(self, data):
        return (await self.conn.write_readline(data.encode())).decode()


if __name__ == "__main__":
    import logging
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level="DEBUG", format=fmt)
    GEPace.run_server()
