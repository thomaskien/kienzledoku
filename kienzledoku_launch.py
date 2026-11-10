"""Strict Windows direct-protocol entry point; URI data cannot become CLI options."""
import sys
import kienzledoku as record


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    try:
        if len(args) != 1 or not args[0].startswith('kienzledoku-record://record'):
            raise ValueError('Ungültiger direkter Record-Aufruf')
        record.run_session(args[0])
        return 0
    except Exception as exc:
        record.safe_log('Direct protocol launch failed', error=type(exc).__name__)
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'kienzledoku record 1.3.3', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
