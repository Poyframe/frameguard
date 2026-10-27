"""Genera assets/frameguard.ico (varios tamaños, PNG dentro de ICO) a partir del icono dibujado en código."""
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from frameguard.ui.icon import render_icon  # noqa: E402


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    render_icon(size).save(buf, "PNG")
    return bytes(buf.data())


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    images = [png_bytes(s) for s in sizes]
    out = Path(__file__).resolve().parents[1] / "assets" / "frameguard.ico"
    out.parent.mkdir(exist_ok=True)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s, img in zip(sizes, images):
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(img), offset + len(data))
        data += img
    out.write_bytes(header + entries + data)
    render_icon(256).save(str(out.with_suffix(".png")))
    print("icono:", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
