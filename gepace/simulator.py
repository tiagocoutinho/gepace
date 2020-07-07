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
      package: gepace.simulator
      transports:
      - type: tcp
        url: :5000

A simple *nc* client can be used to connect to the instrument:

    $ nc 0 5000
    *IDN?
    GE,Pace5000,204683,1.01A
"""

import time

from sinstruments.simulator import BaseDevice

import scpi


DEFAULT = {
    '*idn': '*IDN GE Druck,PACE5000,10388796,DK0367  v02.02.14',
    'sys_error': ':SYST:ERR 0, No error',
}


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
            'SYSTem:DATe': scpi.Cmd(get=self.sys_date, set=self.sys_date),
            'SYSTem:TIMe': scpi.Cmd(get=self.sys_time, set=self.sys_time),
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
            return cmd['get'](request)
        else:
            setter = cmd.get('set')
            if setter is None:
                return 'NACK'
            return cmd['set'](request)

    def sys_error(self, request):
        return self._config['sys_error']

    def sys_date(self, request):
        if request.query:
            return time.strftime('"%m/%d/%Y"')
        # cannot change machine date!

    def sys_time(self, request):
        if request.query:
            return time.strftime('"%H:%M:%S"')
        # cannot change machine time!