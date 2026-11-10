import argparse
import json
import signal
import sys
import threading

from .api import API
from .config import load_settings
from .runtime import Runtime
from .scheduler import Commander
from .ownership import owner


def main():
    parser = argparse.ArgumentParser(description="Kienzledoku-Modellumschaltung auf einer NVIDIA-GPU (Python 3.12+)")
    parser.add_argument("--config", required=True)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.check_config:
            print(json.dumps({"vram_gib": settings.tier, "default_quality": settings.default,
                "allowed_qualities": settings.allowed, "baseline_llm": settings.baseline_llm}, ensure_ascii=False))
            return 0
        with owner(settings.control_dir):
            commander = Commander(settings, Runtime(settings))
            try:
                server = API((settings.host, settings.port), commander)
                def stop(signum, frame):
                    threading.Thread(target=server.shutdown, daemon=True).start()
                signal.signal(signal.SIGTERM, stop)
                signal.signal(signal.SIGINT, stop)
                try:
                    server.serve_forever()
                finally:
                    server.server_close()
            finally:
                commander.close()
    except (ValueError, OSError):
        # Configuration has no patient data; errors still never print tokens.
        print("Commander konnte nicht gestartet werden: Konfiguration, Pfade und Ports prüfen.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
