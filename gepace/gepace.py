import enum
import asyncio
import logging
import functools

NACK = "NACK"


class PaceError(Exception):
    pass


def nop(value):
    return value


def to_nop(text):
    """Strip the command name from the answer"""
    return text.split(" ", 1)[-1]


from_nop = nop


def to_name(text):
    return to_nop(text).strip('"')


def from_name(value):
    return '"{}"'.format(value)


def to_error(text):
    code, text = to_nop(text).split(",", 1)
    return int(code), text


def to_bool(text):
    return bool(int(to_nop(text)))


def from_bool(value):
    return "1" if value else "0"


def to_float(text):
    return float(to_nop(text))


def to_int(text):
    return int(to_nop(text))


def to_float_bool(text):
    pressure, in_limit = to_nop(text).split(",", 1)
    return float(pressure), bool(int(in_limit))


def handle_reply(reply):
    if reply is None:
        return
    return reply.decode().strip()


async def handle_async_io(func, request, log):
    log.debug("REQ: %r", request)
    reply = handle_reply(await func(request))
    log.debug("REP: %r", reply)
    return reply


def handle_sync_io(func, request, log):
    log.debug("REQ: %r", request)
    reply = handle_reply(func(request))
    log.debug("REP: %r", reply)
    return reply


def member(name, fget=to_nop, fset=None):
    assert not (fget is None and fset is None)
    cmd = name.upper()
    if not cmd.startswith("*"):
        cmd = ":{}".format(cmd)

    def command(obj, value=None):
        request = cmd
        if value is None:
            if fget is None:
                raise ValueError("{} is not readable".format(request))
            request += "?"
        elif fset is None:
            raise ValueError("{} is not writable".format(request))
        else:
            set_command = "{} {}".format(request, fset(value))
            if fget is None:
                return obj._command(set_command)
            request = "{};{}?".format(set_command, request)
        return request, fget

    def get_set(obj, value=None):
        request, fget = command(obj, value=value)
        return obj._query(request, fget)

    get_set.template = cmd
    get_set.command = command
    get_set.member = True
    return get_set


def sub_member(prefix, name="", fget=lambda x: x, fset=None):
    assert not (fget is None and fset is None)
    cmd = ':{}:{}'.format(prefix, name) if name else ':{}'.format(prefix)

    def command(obj, value=None):
        request = cmd.format(module=obj.id).upper()
        if value is None:
            if fget is None:
                raise ValueError('{} is not readable'.format(request))
            request += '?'
        elif fset is None:
            raise ValueError('{} is not writable'.format(request))
        else:
            set_command = '{} {}'.format(request, fset(value))
            if fget is None:
                return obj.ctrl._command(set_command)
            request = '{};{}?'.format(set_command, request)
        return request, fget

    def get_set(obj, value=None):
        request, fget = command(obj, value=value)
        return obj.ctrl._query(request, fget)

    get_set.template = cmd
    get_set.command = command
    get_set.member = True
    return get_set


sens_member = functools.partial(sub_member, 'SENS{module}')
sens_pres_member = functools.partial(sub_member, 'SENS{module}:PRES')
src_member = functools.partial(sub_member, 'SOUR{module}')
src_pres_member = functools.partial(sub_member, 'SOUR{module}:PRES')
output_member = functools.partial(sub_member, 'OUTP{module}')
unit_member = functools.partial(sub_member, 'UNIT{module}')


class RateMode(enum.Enum):
    Maximum = 'MAX'
    Linear = 'LIN'

    @classmethod
    def decode(cls, text):
        return cls(to_nop(text))

    def encode(self):
        return self.value


class Channel:

    pressure = sens_pres_member(fget=to_float)
    pressure_range = sens_pres_member("RANG", to_name, from_name)
    pressure_in_limits = sens_pres_member("INL", to_float_bool)
    barometric_pressure = sens_pres_member("BAR", to_float)  # mbar
    pressure_resolution = sens_pres_member("RES", to_int, from_nop)

    src_pressure_pos_ve = src_pres_member("COMP1", to_float)
    src_pressure_neg_ve = src_pres_member("COMP2", to_float)
    src_pressure = src_pressure_pos_ve
    src_pressure_effort = src_pres_member("EFF", to_float, from_nop)  # %
    src_pressure_setpoint = src_pres_member("LEV:IMM:AMPL", to_float, from_nop)
    src_pressure_rate = src_pres_member("SLEW", to_float, from_nop)
    src_pressure_rate_mode = src_pres_member("SLEW:MODE", RateMode.decode,
                                             RateMode.encode)
    src_pressure_rate_overshoot = src_pres_member("SLEW:OVER", to_bool, from_bool)

    pressure_control = output_member("STAT", to_bool, from_bool)

    unit = unit_member("PRES", to_nop, from_nop)

    def __init__(self, channel, ctrl):
        self.id = channel
        self.ctrl = ctrl

    def start(self):
        return self.pressure_control(True)

    def stop(self):
        return self.pressure_control(False)


def _dump_channel_commands(ch):
    klass = type(ch)
    cmds = []
    for name in dir(klass):
        member = getattr(klass, name)
        if getattr(member, "member", False):
            cmds.append((name, member))
    return cmds


def _dump_channel_command_names(ch):
    return [
        (name, member.template, member.command(ch)[0])
        for name, member in _dump_channel_commands(ch)
    ]


async def _dump_channel_command_values(ch):
    cmds = _dump_channel_commands(ch)
    async with ch.ctrl as grp:
        for name, _ in cmds:
            getattr(ch, name)()
    return {
        name: value
        for (name, _), value in zip(cmds, grp.replies)
    }


class Pace:

    class Group:

        def __init__(self, ctrl):
            self.ctrl = ctrl
            self.cmds = [""]
            self.funcs = []

        def append(self, cmd, func):
            cmds = self.cmds[-1]
            # maximum of 255 characters per command
            if len(cmds) + len(cmd) > 500:
                cmds = ""
                self.cmds.append(cmds)
            cmds += ";{}".format(cmd) if cmds else cmd
            self.cmds[-1] = cmds
            self.funcs.append(func)

        def _store(self, replies):
            replies = "".join(replies)
            replies = (msg.strip() for msg in replies.split(";"))
            replies = [func(text) for func, text in zip(self.funcs, replies)]
            self.replies = replies

        async def _async_store(self, replies):
            self._store([await reply for reply in replies])

        def query(self):
            replies = [self.ctrl._ask(request) for request in self.cmds]
            is_async = replies and asyncio.iscoroutine(replies[0])
            store = self._async_store if is_async else self._store
            return store(replies)

    def __init__(self, conn, channels=(1, 2)):
        self._conn = conn
        is_async = asyncio.iscoroutinefunction(conn.write_readline)
        self._handle_io = handle_async_io if is_async else handle_sync_io
        self._log = logging.getLogger("Pace({})".format(conn))
        self.channels = {channel: Channel(channel, self) for channel in channels}
        self.group = None

    def __getitem__(self, key):
        return self.channels[key]

    def __enter__(self):
        self.group = self.Group(self)
        return self.group

    def __exit__(self, exc_type, exc_value, traceback):
        group = self.group
        self.group = None
        group.query()

    async def __aenter__(self):
        self.group = self.Group(self)
        return self.group

    async def __aexit__(self, exc_type, exc_value, traceback):
        group = self.group
        self.group = None
        await group.query()

    def __repr__(self):
        if asyncio.iscoroutinefunction(self._handle_io):
            data = "(asynchonous)"
        else:
            items = ("idn",)
            try:
                with self as group:
                    for item in items:
                        getattr(self, item)()
                data = "\n".join("{}: {}".format(key.upper(), value)
                                 for key, value in zip(items, group.replies))
            except OSError:
                data = "(disconnected)"

        return "Pace({})\n{}".format(self._conn, data)

    def _ask(self, cmd):
        query = "?" in cmd
        raw_cmd = cmd.encode() + b"\n"
        io = self._conn.write_readline if query else self._conn.write
        return self._handle_io(io, raw_cmd, self._log)

    def _query(self, cmd, func=to_nop):
        if self.group is None:
            reply = self._ask(cmd)
            if asyncio.iscoroutine(reply):
                async def async_func(reply):
                    return func(await reply)
                reply = async_func(reply)
            else:
                reply = func(reply)
            return reply
        else:
            self.group.append(cmd, func)

    def _command(self, cmd):
        return self._ask(cmd)

    idn = member("*IDN")
    hw_test = member("*TST", to_bool)
    mac = member("INST:MAC", to_name)
    task = member("INST:TASK", to_nop)
    error = member("SYST:ERR", to_error)
    version = member("SYST:VERS", to_name)
    world_area = member("SYST:AREA", to_nop)

