#!/usr/bin/env python3
"""Desktop diagnostic build only: start the Commander wizard.

Structured stderr is collected by the native launcher. Never print arguments,
environment/configuration values, exception messages, source lines or HTTP data.
"""
import sys

sys.stderr.write('[KDDEBUG] Python interpreter entered debug bootstrap\n')
sys.stderr.flush()

import os
import time
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_lock = threading.RLock()
_start = time.monotonic()
_stop = threading.Event()
_stage = 'bootstrap imports'


def emit(message):
    with _lock:
        sys.stderr.write('[KDDEBUG] +%.3fs %s\n' % (time.monotonic() - _start, message))
        sys.stderr.flush()


def location(code):
    path = Path(code.co_filename)
    try:
        name = str(path.relative_to(ROOT))
    except ValueError:
        name = path.name
    # Only code locations; never locals or the source line itself.
    return '%s:%s' % (name, code.co_name)


def exception_details(exc):
    result = type(exc).__name__
    if isinstance(exc, OSError):
        result += ' errno=%s' % exc.errno
    if isinstance(exc, ImportError) and exc.name:
        # ImportError.name is module identity, not the possibly sensitive message.
        name = str(exc.name)
        if len(name) < 160 and all(c.isalnum() or c in '._' for c in name):
            result += ' module=' + name
    return result


def record_exception(exc_type, exc, tb):
    emit('exception: ' + exception_details(exc))
    while tb is not None:
        emit('frame: %s line=%d' % (location(tb.tb_frame.f_code), tb.tb_lineno))
        tb = tb.tb_next


def heartbeat():
    while not _stop.wait(15):
        emit('Python heartbeat: ' + _stage)
        # A stack snapshot distinguishes a blocked import, sysctl, network probe
        # and server wait. Frame locations only; no arguments or local values.
        frame = sys._current_frames().get(threading.main_thread().ident)
        depth = 0
        while frame is not None and depth < 18:
            emit('main frame: %s line=%d' % (location(frame.f_code), frame.f_lineno))
            frame = frame.f_back
            depth += 1


_CORE_NAMES = {'__init__', 'hardware', 'bootstrap', 'defaults', 'huggingface_token',
               'run', 'report', 'start', '_work', '_work_locked', '_finalize'}
_WIZARD_NAMES = {'main', 'handler', 'do_GET', 'do_POST'}


def profile(frame, event, arg):
    global _stage
    if event not in ('call', 'return'):
        return
    code = frame.f_code
    filename = code.co_filename.replace('\\', '/')
    name = code.co_name
    selected = ((filename.endswith('/installer/core.py') and name in _CORE_NAMES)
                or (filename.endswith('/installer/uninstall_macos.py') and name in _CORE_NAMES)
                or (filename.endswith('/installer/wizard.py') and name in _WIZARD_NAMES)
                or (filename.endswith('/kienzledoku_http.py') and name == 'configure_server')
                or (filename.endswith('/socketserver.py') and name in ('__init__', 'server_bind', 'server_activate', 'serve_forever'))
                or (filename.endswith('/http/server.py') and name == 'server_bind')
                or (filename.startswith(str(ROOT) + '/') and name == '<module>'))
    if selected:
        where = location(code)
        if event == 'call':
            _stage = where
        emit('%s %s' % (event, where))


def install_subprocess_diagnostics():
    import subprocess
    original = subprocess.Popen.__init__
    original_poll = subprocess.Popen.poll
    original_wait = subprocess.Popen.wait

    def traced_init(self, args, *positional, **kwargs):
        self._kd_debug_exit_logged = False
        if isinstance(args, (tuple, list)) and args:
            executable = Path(os.fsdecode(args[0])).name
            count = len(args)
        else:
            executable, count = '<shell string omitted>', 0
        # Executable names here are fixed by the installer. Restrict unusual
        # names instead of accidentally recording user-provided shell content.
        if len(executable) > 80 or any(not (c.isalnum() or c in '._-') for c in executable):
            executable = '<name omitted>'
        emit('subprocess launch executable=%s argc=%d (arguments omitted)' % (executable, count))
        try:
            original(self, args, *positional, **kwargs)
        except BaseException as exc:
            emit('subprocess launch failed: ' + exception_details(exc))
            raise
        emit('subprocess started pid=%d' % self.pid)

    def record_exit(process, code):
        if code is not None and not process._kd_debug_exit_logged:
            process._kd_debug_exit_logged = True
            emit('subprocess exited pid=%d code=%d' % (process.pid, code))
        return code

    def traced_poll(self):
        return record_exit(self, original_poll(self))

    def traced_wait(self, *args, **kwargs):
        return record_exit(self, original_wait(self, *args, **kwargs))

    subprocess.Popen.__init__ = traced_init
    subprocess.Popen.poll = traced_poll
    subprocess.Popen.wait = traced_wait


def main():
    emit('Python=%s version=%s platform=%s pointer_bits=%d' %
         (Path(sys.executable).name, sys.version.split()[0], sys.platform, 64 if sys.maxsize > 2**32 else 32))
    sys.excepthook = record_exception
    threading.excepthook = lambda args: record_exception(args.exc_type, args.exc_value, args.exc_traceback)
    threading.Thread(target=heartbeat, daemon=True, name='installer-debug-heartbeat').start()
    try:
        emit('import runpy/subprocess begins')
        import runpy
        install_subprocess_diagnostics()
        emit('import runpy/subprocess finished')
        sys.setprofile(profile)
        threading.setprofile(profile)
        emit('running original installer/wizard.py')
        runpy.run_path(str(ROOT / 'installer/wizard.py'), run_name='__main__')
    except SystemExit as exc:
        emit('wizard SystemExit code=%s' % (exc.code if isinstance(exc.code, int) or exc.code is None else '<message omitted>'))
        raise
    except BaseException:
        record_exception(*sys.exc_info())
        raise SystemExit(1)
    finally:
        sys.setprofile(None)
        threading.setprofile(None)
        _stop.set()
        emit('debug bootstrap finished')


if __name__ == '__main__':
    main()
