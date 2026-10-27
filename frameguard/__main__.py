"""Punto de entrada: `Frameguard.exe` abre la ventana; `Frameguard.exe --engine` arranca el motor."""
import argparse
import sys

from . import DEFAULT_PORT


def main() -> int:
    ap = argparse.ArgumentParser(prog="frameguard")
    ap.add_argument("--engine", action="store_true", help="arranca el motor de la cola (sin ventana)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("files", nargs="*", help="colas .fgq o archivos .blend para abrir")
    args, _ = ap.parse_known_args()
    if args.engine:
        from .engine import run_engine
        return run_engine(args.port)
    from .ui.app import run_ui
    return run_ui(args.port, args.files)


if __name__ == "__main__":
    sys.exit(main())
