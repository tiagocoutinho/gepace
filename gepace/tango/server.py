import tango
from tango.server import Device, attribute, command, device_property

from sockio.aio import TCP
from gepace.gepace import Pace, RateMode


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
    "pressure1": lambda pace: pace[1].pressure(),
    "src_pressure1": lambda pace: pace[1].src_pressure(),
    "pressure1_setpoint": lambda pace: pace[1].src_pressure_setpoint(),
    "pressure1_overshoot": lambda pace: pace[1].src_pressure_rate_overshoot(),
    "pressure1_rate_mode": lambda pace: pace[1].src_pressure_rate_mode(),
    "pressure1_rate": lambda pace: pace[1].src_pressure_rate(),
}

class GEPace(Device):

    green_mode = tango.GreenMode.Asyncio

    address = device_property(dtype=str)

    async def init_device(self):
        await super().init_device()
        conn = create_connection(self.address)
        self.pace = Pace(conn)
        self.last_values = {}

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
#        self._update_state_status(self.last_values["control"])

    @attribute(dtype=str)
    def idn(self):
        return self.last_values["idn"]

    @attribute(dtype=float)
    def pressure1(self):
        return self.last_values["pressure1"]

    @attribute(dtype=float)
    def src_pressure1(self):
        return self.last_values["src_pressure1"]

    @attribute(dtype=float)
    def pressure1_setpoint(self):
        return self.last_values["pressure1_setpoint"]

    @pressure1_setpoint.write
    async def pressure1_setpoint(self, value):
        await self.ctrl[1].src_pressure_setpoint(value)

    @attribute(dtype=bool)
    def pressure1_overshoot(self):
        return self.last_values["pressure1_overshoot"]

    @attribute(dtype=str)
    def pressure1_rate_mode(self):
        return self.last_values["pressure1_rate_mode"].name

    @pressure1_rate_mode.write
    async def pressure1_rate_mode(self, value):
        value = RateMode[value.capitalize()]
        await self.pace[1].src_pressure_rate_mode(value)

    @attribute(dtype=float)
    def pressure1_rate(self):
        return self.last_values["pressure1_rate"]

    @pressure1_rate.write
    async def pressure1_rate(self, value):
        await self.pace[1].src_pressure_rate(value)


if __name__ == "__main__":
    import logging
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level="DEBUG", format=fmt)
    GEPace.run_server()
