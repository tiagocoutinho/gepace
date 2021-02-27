# -*- coding: utf-8 -*-
#
# This file is part of the instrument simulator project
#
# Copyright (c) 2019 Tiago Coutinho
# Distributed under the MIT. See LICENSE for more info.

"""
.. code-block:: yaml

    devices:
    - class: Pace
      transports:
      - type: tcp
        url: :5000

A simple *nc* client can be used to connect to the instrument:

    $ nc 0 5000
    *IDN?
    GE,Pace5000,204683,1.01A
"""

import time
import random

from sinstruments.simulator import BaseDevice

import scpi


DEFAULT = {
    '*idn': 'GE Druck,PACE5000,10388796,DK0367  v02.02.14',
    'sys_error': '0, No error',
    'src_pressure': 12.464,
    'src_slew': "2.0",
    'src_slew_mode': "LIN",
    'src_slew_over_state': '1',
    'src_amp': '0.4',
    'sens1_pressure': 34.567,
    'syst_set': 'CONT, 100.00',
    'out_stat': '0',
}


def ConfigCmd(cfg, name, get=None, set=None, read_only=False):
    if get is None:
        def get(req):
            return cfg[name]
    if read_only:
        set = None
    else:
        if set is None:
            def set(req):
                cfg[name] = req.args
    return scpi.Cmd(get=get, set=set)


def FloatRandCmd(cfg, name):
    def get(req):
        return str(cfg[name] + random.random())
    return scpi.Cmd(get=get)


class Pace(BaseDevice):


    def __init__(self, name, **opts):
        kwargs = {}
        if 'newline' in opts:
            kwargs['newline'] = opts.pop('newline')
        self._config = dict(DEFAULT, **opts)
        super().__init__(name, **kwargs)
        self._cmds = scpi.Commands({
            '*IDN': scpi.Cmd(get=lambda req: self._config['*idn']),
            'SYSTem:ERRor': scpi.Cmd(get=self.sys_error),
            'SYSTem:DATE': scpi.Cmd(get=self.sys_date, set=self.sys_date),
            'SYSTem:TIME': scpi.Cmd(get=self.sys_time, set=self.sys_time),
            'SYSTem:SET': ConfigCmd(self._config, 'syst_set', read_only=False),
            'SOUR1[:PRESsure]:COMP[1]': FloatRandCmd(self._config, 'src_pressure'),
            'SOUR1[:PRESsure]:SLEW': ConfigCmd(self._config, 'src_slew'),
            'SOUR1[:PRESsure]:SLEW:MODE': ConfigCmd(self._config, 'src_slew_mode'),
            'SOUR1[:PRESsure]:SLEW:OVERshoot[:STATe]': ConfigCmd(self._config, 'src_slew_over_state'),
            'SOUR1[:PRESsure][:LEVel][:IMMediate][:AMPLitude]': ConfigCmd(self._config, 'src_amp'),
            'SENS1[:PRESsure]': FloatRandCmd(self._config, 'sens1_pressure'),
            'OUTP1:STATe': ConfigCmd(self._config, 'out_stat'),
        })

    def handle_message(self, line):
        self._log.debug('request %r', line)
        line = line.decode()
        requests = scpi.split_line(line)
        results = (self.handle_request(request) for request in requests)
        results = (result for result in results if result is not None)
        reply = ';'.join(results).encode()
        if reply:
            reply += b'\n'
            self._log.debug('reply %r', reply)
            return reply

    def handle_request(self, request):
        cmd = self._cmds.get(request.name)
        if cmd is None:
            return 'NACK'
        if request.query:
            getter = cmd.get('get')
            if getter is None:
                return 'NACK'
            return "{} {}".format(request.name.upper(), cmd['get'](request))
        else:
            setter = cmd.get('set')
            if setter is None:
                return 'NACK'
            return cmd['set'](request)

    def sys_error(self, request):
        return self._config['sys_error']

    def sys_date(self, request):
        if request.query:
            return time.strftime('%y, %m, %d')
        # cannot change machine date!

    def sys_time(self, request):
        if request.query:
            return time.strftime('%H, %M, %S')
        # cannot change machine time!

    def slew_over_state(self, request):
        if request.query:
            return "1"
