import enum
import asyncio
import logging
import functools
import threading

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


def to_sn(text):
    names = "ui", "ctrl1", "ctrl2", "ao1", "ao2", "vfc1", "vfc2"
    values = (int(to_nop(v)) for v in text.split(";"))
    return dict(zip(names, values))


def handle_reply(reply):
    if reply is None:
        return
    return reply.decode().strip()


async def handle_async_io(func, lock, request, log):
    log.debug("REQ: %r", request)
    async with lock:
        reply = await func(request)
    reply = handle_reply(reply)
    log.debug("REP: %r", reply)
    return reply


def handle_sync_io(func, lock, request, log):
    log.debug("REQ: %r", request)
    with lock:
        reply = func(request)
    reply = handle_reply(reply)
    log.debug("REP: %r", reply)
    return reply


def __member(name, fget=to_nop, fset=None, cache=False):
    assert not (fget is None and fset is None)
    cmd = name.upper()
    if not cmd.startswith("*") and not cmd.startswith(":"):
        cmd = ":{}".format(cmd)

    def command(obj, value=None):
        request = cmd
        getter = fget
        if value is None:
            if getter is None:
                raise ValueError("{} is not readable".format(request))
            if not request.endswith("?"):
                request += "?"
        elif fset is None:
            raise ValueError("{} is not writable".format(request))
        else:
            set_command = "{} {}".format(request, fset(value))
            if getter is None:
                request = ':SYST:ERR'
                getter = to_error
            request = "{};{}?".format(set_command, request)
        return request, getter

    def get_set(obj, value=None):
        is_get = value is None
        if is_get and cache:
            cache_value = obj._cache.get(name)
            if cache_value is not None:
                return cache_value
        request, getter = command(obj, value=value)
        result = obj._query(request, getter)
        if is_get or cache:
            if asyncio.iscoroutine(result):
                result = asyncio.ensure_future(result)
                def cb(futur):
                    obj._cache[name] = futur
                result.add_done_callback(cb)
            else:
                obj._cache[name] = result
        return result

    get_set.template = cmd
    get_set.command = command
    get_set.member = True
    return get_set


def member(prefix, name="", fget=to_nop, fset=None, cache=False):
    assert not (fget is None and fset is None)
    cmd = '{}:{}'.format(prefix, name) if name else '{}'.format(prefix)
    if not cmd.startswith("*") and not cmd.startswith(":"):
        cmd = ":{}".format(cmd)

    def command(obj, value=None):
        obj_id = getattr(obj, "id", None)
        request = cmd.format(module=obj_id).upper()
        getter = fget
        if value is None:
            if getter is None:
                raise ValueError('{} is not readable'.format(request))
            if not request.endswith("?"):
                request += '?'
        elif fset is None:
            raise ValueError('{} is not writable'.format(request))
        else:
            set_command = '{} {}'.format(request, fset(value))
            if getter is None:
                request = ':SYST:ERR'
                getter = to_error
            request = '{};{}?'.format(set_command, request)
        return request, getter

    def get_set(obj, value=None):
        request, getter = command(obj, value=value)
        is_get = value is None
        if is_get and cache:
            cache_value = obj._cache.get(request)
            if cache_value is not None:
                return cache_value
        result = obj._query(request, getter)
        if is_get or cache:
            if asyncio.iscoroutine(result):
                result = asyncio.ensure_future(result)
                def cb(futur):
                    obj._cache[request] = futur
                result.add_done_callback(cb)
            else:
                obj._cache[request] = result
        return result

    get_set.template = cmd
    get_set.command = command
    get_set.member = True
    return get_set


sens_member = functools.partial(member, 'SENS{module}')
sens_pres_member = functools.partial(member, 'SENS{module}:PRES')
src_member = functools.partial(member, 'SOUR{module}')
src_pres_member = functools.partial(member, 'SOUR{module}:PRES')
output_member = functools.partial(member, 'OUTP{module}')
unit_member = functools.partial(member, 'UNIT{module}')


class RateMode(enum.Enum):
    Maximum = 'MAX'
    Linear = 'LIN'

    @classmethod
    def decode(cls, text):
        return cls(to_nop(text))

    def encode(self):
        return self.value


class Mode(enum.Enum):
    Measurement = "MEAS"
    Control = "CONT"

    @classmethod
    def decode(cls, text):
        mode, setpoint = to_nop(text).split(",", 1)
        return cls(mode), float(setpoint)

    @staticmethod
    def encode(args):
        mode, setpoint = args
        return '{},{}'.format(mode.value, setpoint)


class Module:

    pressure = sens_pres_member(fget=to_float)
    pressure_range = sens_pres_member("RANG", to_name, from_name)
    pressure_in_limits = sens_pres_member("INL", to_float_bool)
    barometric_pressure = sens_pres_member("BAR", to_float)
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
    relay1 = output_member("LOG1", to_bool, from_bool)
    relay2 = output_member("LOG2", to_bool, from_bool)
    relay3 = output_member("LOG3", to_bool, from_bool)

    unit = unit_member("PRES", to_nop, from_nop)

    def __init__(self, module, ctrl):
        self.id = module
        self.ctrl = ctrl

    def _query(self, cmd, func=to_nop):
        return self.ctrl._query(cmd, func=func)

    @property
    def _cache(self):
        return self.ctrl._cache

    def start(self):
        return self.pressure_control(True)

    def stop(self):
        return self.pressure_control(False)


def _dump_module_commands(ch):
    klass = type(ch)
    cmds = []
    for name in dir(klass):
        member = getattr(klass, name)
        if getattr(member, "member", False):
            cmds.append((name, member))
    return cmds


def _dump_module_command_names(ch):
    return [
        (name, member.template, member.command(ch)[0])
        for name, member in _dump_module_commands(ch)
    ]


async def _dump_module_command_values(ch):
    cmds = _dump_module_commands(ch)
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
            # I have the impression the hardware answers with a max of 255
            # bytes. We limit the request to 128 in the hope the answer is
            # not longer
            if len(cmds) + len(cmd) > 128:
                cmds = ""
                self.cmds.append(cmds)
            cmds += ";{}".format(cmd) if cmds else cmd
            self.cmds[-1] = cmds
            self.funcs.append(func)

        def _store(self, replies):
            replies = ";".join(replies)
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

    def __init__(self, conn, modules=(1, 2)):
        self._conn = conn
        is_async = asyncio.iscoroutinefunction(conn.write_readline)
        self._lock = asyncio.Lock() if is_async else threading.Lock()
        self._cache = {}
        self._handle_io = handle_async_io if is_async else handle_sync_io
        self._log = logging.getLogger("Pace({})".format(conn))
        self.modules = {module: Module(module, self) for module in modules}
        self.group = None

    def __getitem__(self, key):
        return self.modules[key]

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

    def __call__(self, request):
        return self._query(request)

    def close(self):
        return self._conn.close()

    def _ask(self, cmd):
        query = "?" in cmd
        raw_cmd = cmd.encode() + b"\n"
        io = self._conn.write_readline if query else self._conn.write
        return self._handle_io(io, self._lock, raw_cmd, self._log)

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

    idn = member("*IDN", cache=True)
    hw_test = member("*TST", fget=to_bool)
    mac = member("INST:MAC", fget=to_name, cache=True)
    task = member("INST:TASK", fget=to_nop)
    error = member("SYST:ERR", fget=to_error)
    version = member("SYST:VERS", fget=to_name, cache=True)
    world_area = member("SYST:AREA", fget=to_nop, cache=True)
    startup_mode = member("SYST:SET", fget=Mode.decode, fset=Mode.encode)

    # TODO: does not work in group!
    serial_numbers = member(
        ";".join(":INST:SN{}?".format(i) for i in range(1, 8)),
        fget=to_sn,
        cache=True
    )
