# GE Pace library

<img align="right" alt="Pace 5000" width="400" src="docs/pace5000.png" />

This library is used to control basic features of a GE Pressure Automated
Calibration Equipment (Pace) models 1000, 5000 and 6000.

It is composed of a core library, an optional simulator and
an optional [tango](https://tango-controls.org/) device server.

It has been tested with the Pace 5000 model, but should work with other models.

It can be used with either the ETH or the serial line connection (read below
on the recommended way to setup a serial line connection)

## Installation

From within your favorite python environment type:

`$ pip install gepace`


## Library

The core of the gepace library consists of Pace object.
To create a Pace object you need to pass a communication object.

The communication object can be any object that supports a simple API
consisting of two methods (either the sync or async version is supported):

* `write_readline(buff: bytes) -> bytes` *or*

  `async write_readline(buff: bytes) -> bytes`

* `write(buff: bytes) -> None` *or*

  `async write(buff: bytes) -> None`

A library that supports this API is [sockio](https://pypi.org/project/sockio/)
(gepace comes pre-installed so you don't have to worry about installing it).

This library includes both async and sync versions of the TCP object. It also
supports a set of features like reconnection and timeout handling.

Here is how to connect to a GE Pace controller:

```python
import asyncio

from sockio.aio import TCP
from gepace import Pace


async def main():
    tcp = TCP("192.168.1.123", 5000)  # use host name or IP
    pace = Pace(tcp)

    idn = await pace.idn()
    name = await pace.name()
    print("Connected to {} ({})".format(idn, name))

    # channel access:
    temp_A = await pace['A'].temperature()
    unit = await pace['A'].unit()
    print("Channel A temperature: {}{}".format(temp_A, unit))

    # loop access:
    source_1 = await pace[1].source()
    print("Loop 1 source: {}".format(source_1))

    # activate control
    await pace.control(True)

    # hardware only accepts queries every 100ms. Yo can, however,
    # group queries in single request:
    async with pace as group:
        pace.idn()
        pace.control()
        pace['A'].temperature()
    idn, ctrl, temp_A = group.replies


asyncio.run(main())
```

#### Serial line

To access a serial line based Pace device it is strongly recommended you spawn
a serial to tcp bridge using [ser2net](https://linux.die.net/man/8/ser2net) or
[socat](https://linux.die.net/man/1/socat)

Assuming your device is connected to `/dev/ttyS0` and the baudrate is set to 19200,
here is how you could use socat to expose your device on the machine port 5000:

`socat -v TCP-LISTEN:5000,reuseaddr,fork file:/dev/ttyS0,rawer,b19200,cs8,eol=10,icanon=1`

It might be worth considering starting socat or ser2net as a service using
[supervisor](http://supervisord.org/) or [circus](https://circus.rtfd.io/).

### Simulator

A Pace simulator is provided.

Before using it, make sure everything is installed with:

`$ pip install gepace[simulator]`

The [sinstruments](https://pypi.org/project/sinstruments/) engine is used.

To start a simulator you need to write a YAML config file where you define
how many devices you want to simulate and which properties they hold.

The following example exports 2 hardware devices. The first is a minimal
configuration using default values and the second defines some initial values
explicitly:

```yaml
# config.yml

devices:
- class: Pace
  package: gepace.simulator
  transports:
  - type: tcp
    url: :5000

```

To start the simulator type:

```terminal
$ sinstruments-server -c ./config.yml --log-level=DEBUG
2020-05-14 16:02:35,004 INFO  simulator: Bootstraping server
2020-05-14 16:02:35,004 INFO  simulator: no backdoor declared
2020-05-14 16:02:35,004 INFO  simulator: Creating device Pace ('Pace')
2020-05-14 16:02:35,080 INFO  simulator.Pace[('', 5000)]: listening on ('', 5000) (newline='\n') (baudrate=None)
```

(To see the full list of options type `sinstruments-server --help`)

You can access it as you would a real hardware:

```terminal
$ nc localhost 5000
*IDN?
GE,Pace5000,204683,1.01A
```

or using the library:
```python
$ python
>>> from sockio.sio import TCP   # use synchronous socket in the CLI!
>>> from gepace import Pace
>>> pace = Pace(TCP('localhost', 5000))
>>> print(pace.idn())
GE,Pace5000,204683,1.01A
```

### Tango server

A [tango](https://tango-controls.org/) device server is also provided.

Make sure everything is installed with:

`$ pip install gepace[tango]`

Register a gepace tango server in the tango database:
```
$ tangoctl server add -s GEPace/test -d Pace test/cryocon/1
$ tangoctl device property write -d test/pace/1 -p address -v "tcp://192.168.123:5000"
```

(the above example uses [tangoctl](https://pypi.org/project/tangoctl/). You would need
to install it with `pip install tangoctl` before using it. You are free to use any other
tango tool like [fandango](https://pypi.org/project/fandango/) or Jive)

Launch the server with:

```terminal
$ GEPace test
```

## TODO

* Add `on_connection_made` callback to initialize controller with:
  * unit=`K`
  * cache IDN, fw revision, hw revision
  * should we cache system:name? and input:name? in theory in could be modified
    directly with the hardware front panel
