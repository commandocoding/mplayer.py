#!/usr/bin/env python
# -*- coding: utf-8 -*-
# $Id$
#
# Copyright (C) 2007-2008  UP EEEI Computer Networks Laboratory
# Copyright (C) 2007-2009  Darwin M. Bautista <djclue917@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Thin, out-of-source wrapper and client/server for MPlayer

Classes:

MPlayer -- thin, out-of-process wrapper for MPlayer
Server -- asynchronous server that manages an MPlayer instance
Client -- client for sending MPlayer commands

Function:

loop() -- the asyncore.loop function, provided here for convenience

Constants:

PIPE -- subprocess.PIPE, provided here for convenience
STDOUT -- subprocess.STDOUT, provided here for convenience

"""

import socket
import asyncore
import asynchat
from time import sleep
from subprocess import Popen, PIPE, STDOUT


__all__ = [
    'MPlayer',
    'Server',
    'Client',
    'loop',
    'PIPE',
    'STDOUT'
    ]

__version__ = '0.4.0'
__author__ = 'Darwin M. Bautista <djclue917@gmail.com>'


# For convenience
loop = asyncore.loop


class MPlayer(object):
    """MPlayer(args=())

    An out-of-process wrapper for MPlayer. It provides the basic interface
    for sending commands and receiving responses to and from MPlayer. Take
    note that MPlayer is always started in 'slave', 'idle', and 'quiet' modes.

    @class attribute executable: path to or filename of the MPlayer executable
    @property args: MPlayer arguments
    @property stdout: process' stdout (read-only)
    @property stderr: process' stderr (read-only)

    """

    executable = 'mplayer'

    def __init__(self, args=()):
        self.args = args
        self._process = None
        self._stdout = _file()
        self._stderr = _file()

    def __del__(self):
        # Be sure to stop the MPlayer process.
        self.quit()

    @staticmethod
    def _check_command_args(name, types, min_argc, max_argc, args):
        argc = len(args) + 1
        min_argc += 1
        max_argc += 1
        if not min_argc and argc:
            raise TypeError('%s() takes no arguments (%d given)' % (name, argc))
        if argc < min_argc:
            raise TypeError('%s() takes at least %d arguments (%d given)' % (name, min_argc, argc))
        if min_argc == max_argc and argc != max_argc:
            raise TypeError('%s() takes exactly %d arguments (%d given)' % (name, max_argc, argc))
        if argc > max_argc:
            raise TypeError('%s() takes at most %d arguments (%d given)' % (name, max_argc, argc))
        for i in xrange(argc - 1):
            if not isinstance(args[i], types[i]):
                raise TypeError('%s() argument %d should be %s' % (name, i + 1, types[i].__name__.replace('base', '')))

    def _get_args(self):
        return self._args[3:]

    def _set_args(self, args):
        _args = ['-slave', '-idle', '-quiet']
        try:
            _args.extend(args)
        except TypeError:
            raise TypeError('args should be an iterable')
        for i in range(3, len(_args)):
            if not isinstance(_args[i], basestring):
                _args[i] = str(_args[i])
        self._args = _args

    args = property(_get_args, _set_args, doc='list of MPlayer arguments')

    @property
    def stdout(self):
        """stdout of the MPlayer process"""
        return self._stdout

    @property
    def stderr(self):
        """stderr of the MPlayer process"""
        return self._stderr

    @classmethod
    def introspect(cls):
        """Introspect the MPlayer binary

        Generate methods based on the available commands. The generated
        methods check the number and type of the passed parameters.
        """
        types = {'Integer': int, 'Float': float, 'String': basestring}
        args = [cls.executable, '-input', 'cmdlist', '-really-quiet']
        for line in Popen(args, stdout=PIPE).communicate()[0].split('\n'):
            if not line or line.startswith('quit'):
                continue
            args = line.split()
            name = args.pop(0)
            if not name.startswith('get_'):
                required = 0
                for arg in args:
                    if not arg.startswith('['):
                        required += 1
                arg_types = str([types[arg.strip('[]')].__name__ for arg in args]).replace("'", '')
                code = '''
                def %(name)s(self, *args):
                    """%(name)s(%(args)s)"""
                    try:
                        self._check_command_args('%(name)s', %(types)s, %(min_argc)d, %(max_argc)d, args)
                    except TypeError, msg:
                        raise TypeError(msg)
                    return self.command('%(name)s', *args)
                ''' % dict(
                    name = name,
                    args = ', '.join(args),
                    min_argc = required,
                    max_argc = len(args),
                    types = arg_types
                )
            elif not name.startswith('get_property'):
                code = '''
                def %(name)s(self, timeout=0.1):
                    """%(name)s(timeout=0.1)"""
                    try:
                        return self.query('%(name)s', timeout)
                    except TypeError, msg:
                        raise TypeError(msg)
                ''' % dict(name = name)
            else:
                code = '''
                def get_property(self, property, timeout=0.1):
                    """get_property(property, timeout=0.1)"""
                    try:
                        return self.query(' '.join(['get_property', property]), timeout)
                    except TypeError, msg:
                        raise TypeError(msg)
                '''
            scope = {}
            exec code.strip() in globals(), scope
            setattr(cls, name, scope[name])

    def start(self, stdout=None, stderr=None):
        """Start the MPlayer process.

        @param stdout: subprocess.PIPE | None
        @param stderr: subprocess.PIPE | subprocess.STDOUT | None

        Returns True on success, False on failure, or None if MPlayer is
        already running. stdout/stderr will be PIPEd regardless of the
        passed parameters if handlers were added to them.

        """
        if stdout not in (PIPE, None):
            raise ValueError('stdout should either be PIPE or None')
        if stderr not in (PIPE, STDOUT, None):
            raise ValueError('stderr should be one of PIPE, STDOUT, or None')
        if not self.is_alive():
            args = [self.__class__.executable]
            args.extend(self._args)
            # Force PIPE if handlers were added
            if self._stdout._handlers:
                stdout = PIPE
            if self._stderr._handlers:
                stderr = PIPE
            try:
                # Start the MPlayer process (line-buffered)
                self._process = Popen(args, bufsize=1, stdin=PIPE, stdout=stdout, stderr=stderr)
            except OSError:
                return False
            else:
                if self._process.stdout is not None:
                    self._stdout._attach(self._process.stdout)
                if self._process.stderr is not None:
                    self._stderr._attach(self._process.stderr)
                return True

    def quit(self, retcode=0):
        """Stop the MPlayer process.

        Returns the exit status of MPlayer or None if not running.

        """
        if self.is_alive():
            self._stdout._detach()
            self._stderr._detach()
            self._process.stdin.write('quit %d\n' % (retcode, ))
            return self._process.wait()

    def is_alive(self):
        """Check if MPlayer process is alive.

        Returns True if alive, else, returns False.

        """
        if self._process is not None:
            return (self._process.poll() is None)
        else:
            return False

    def command(self, cmd, *args):
        """Send a command to MPlayer.

        @param cmd: command string

        Valid MPlayer commands are documented in:
        http://www.mplayerhq.hu/DOCS/tech/slave.txt

        """
        if not isinstance(cmd, basestring):
            raise TypeError('command must be a string')
        if cmd.lower().startswith('quit'):
            raise ValueError('use the quit() method instead')
        if self.is_alive() and cmd:
            command = [cmd]
            command.extend([str(arg) for arg in args])
            command.append('\n')
            self._process.stdin.write(' '.join(command))

    def query(self, cmd, timeout=0.1):
        """Send a query to MPlayer. Result is returned, if there is.

        query() will first consume all data in stdout before proceeding.
        This is to ensure that it'll get the response from the command
        given and not just some random data.

        WARNING: This function is not thread-safe. You might want to implement
                 a locking mechanism to ensure that you get the correct result
        """
        if self._process.stdout is not None and cmd.lower().startswith('get_'):
            self._stdout._query_in_progress = True
            # Consume all data in stdout before proceeding
            try:
                self._process.stdout.read()
            except IOError:
                pass
            self.command(cmd)
            sleep(timeout)
            try:
                response = self._process.stdout.readline().rstrip()
            except IOError:
                return None
            finally:
                self._stdout._query_in_progress = False
            if response.startswith('ANS_'):
                response = response.split('=')[1].strip('\'"')
            else:
                response = None
            return response


class Server(asyncore.dispatcher):
    """Server(mplayer, port, host='', max_conn=1)

    The log method can be overridden to provide more sophisticated
    logging and warning methods.

    """

    def __init__(self, mplayer, port, host='', max_conn=1):
        asyncore.dispatcher.__init__(self)
        self._mplayer = mplayer
        self._max_conn = max_conn
        self._channels = {}
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_reuse_addr()
        self.bind((host, port))
        self.listen(self._max_conn)
        self.log('Server started.')

    def __del__(self):
        self.stop()

    def writable(self):
        return False

    def handle_close(self):
        for channel in self._channels.values():
            channel.handle_close()
        self.close()
        self.log('Server closed.')

    stop = handle_close

    def handle_accept(self):
        conn, addr = self.accept()
        if len(self._channels) < self._max_conn:
            self.log('Connection accepted: %s' % (addr, ))
            # Dispatch connection to a _ClientHandler
            _ClientHandler(self._channels, self._mplayer, conn, self.log)
        else:
            self.log('Max number of connections reached, rejected: %s' % (addr, ))
            conn.close()


class Client(asynchat.async_chat):
    """Client()

    The PyMPlayer Client

    """

    ac_in_buffer_size = 512
    ac_out_buffer_size = 512

    def __init__(self):
        asynchat.async_chat.__init__(self)
        self.buffer = []
        self.set_terminator('\r\n')

    def handle_connect(self):
        return

    def handle_error(self):
        self.close()
        raise socket.error('Connection lost.')

    def collect_incoming_data(self, data):
        self.buffer.append(data)

    def found_terminator(self):
        data = ''.join(self.buffer)
        self.buffer = []
        self.handle_data(data)

    def handle_data(self, data):
        self.log(data)

    def connect(self, (host, port)):
        if self.connected:
            return
        if self.socket:
            self.close()
        self.create_socket(socket.AF_INET, socket.SOCK_STREAM)
        asynchat.async_chat.connect(self, (host, port))

    def send_command(self, cmd):
        """Send an MPlayer command to the server

        @param cmd: valid MPlayer command

        Valid MPlayer commands are documented in:
        http://www.mplayerhq.hu/DOCS/tech/slave.txt

        """
        self.push(''.join([cmd, '\r\n\r\n']))
        if 'quit'.startswith(cmd.split()[0].lower()):
            self.close()
            return False
        else:
            return True


class _ClientHandler(asynchat.async_chat):
    """Handler for Client connections"""

    ac_in_buffer_size = 512
    ac_out_buffer_size = 512

    def __init__(self, connections, mplayer, conn, log):
        asynchat.async_chat.__init__(self, conn)
        self.add_channel(connections)
        self.set_terminator('\r\n\r\n')
        self.connections = connections
        self.mplayer = mplayer
        # hook handle_mplayer_data method to mplayer's stdout
        self.handler_id = self.mplayer.stdout.add_handler(self.handle_mplayer_data)
        self.log = log
        self.buffer = []

    def handle_close(self):
        self.mplayer.stdout.remove_handler(self.handler_id)
        del self.connections[self._fileno]
        self.close()
        self.log('Connection closed: %s' % (self.addr, ))

    def collect_incoming_data(self, data):
        self.buffer.append(data)

    def found_terminator(self):
        data = ''.join(self.buffer)
        self.buffer = []
        self.handle_data(data)

    def handle_data(self, data):
        if not data or 'quit'.startswith(data.split()[0].lower()):
            self.handle_close()
        elif data.lower() == 'reload':
            # then restart the MPlayer process;
            self.mplayer.restart()
        else:
            self.mplayer.command(data)

    def handle_mplayer_data(self, data):
        if data.startswith('ANS_'):
            self.push(''.join([data, '\r\n']))


class _file(object):
    """Wrapper for stdout and stderr

    Exposes the fileno() and readline() methods
    Provides methods for management of data handlers
    """

    def __init__(self):
        self._handlers = {}
        self._file = None
        self._query_in_progress = False

    def _attach(self, file):
        self._detach()
        self._file = file
        # create file_dispatcher instance and override handle_read method
        asyncore.file_dispatcher(file.fileno()).handle_read = self.callback

    def _detach(self):
        if self._file is not None and asyncore.socket_map.has_key(self._file.fileno()):
            del asyncore.socket_map[self._file.fileno()]
        self._file = None

    def fileno(self):
        if self._file is not None:
            return self._file.fileno()

    def readline(self):
        if self._file is not None and not self._query_in_progress:
            try:
                data = self._file.readline().rstrip()
            except IOError:
                data = None
            return data

    def callback(self, *args):
        """Callback for use with event loops of other frameworks

        m.stdout.add_handler(handle_player_data)
        m.start()

        fd = m.stdout.fileno()
        cb = m.stdout.callback

        gobject.io_add_watch(fd, gobject.IO_IN|gobject.IO_PRI, cb)
        tkinter.createfilehandler(fd, tkinter.READABLE, cb)

        """
        data = self.readline()
        if data is None:
            return True
        for handler in self._handlers.values():
            if callable(handler):
                handler(data)
            else:
                del self._handlers[id(handler)]
        return True

    def add_handler(self, handler):
        if not callable(handler):
            raise TypeError('handler should be callable')
        hid = id(handler)
        self._handlers[hid] = handler
        return hid

    def remove_handler(self, hid):
        try:
            del self._handlers[hid]
        except KeyError:
            return False
        else:
            return True


if __name__ == '__main__':
    import sys
    import signal

    def handle_data(data):
        print 'mplayer: ', data

    player = MPlayer()
    player.args = sys.argv[1:]
    player.stdout.add_handler(handle_data)
    player.start()

    signal.signal(signal.SIGTERM, lambda s, f: player.stop())
    signal.signal(signal.SIGINT, lambda s, f: player.stop())
    loop()
