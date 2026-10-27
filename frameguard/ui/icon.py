"""Icono de Frameguard: el logo de ui/logo.png (1024 px, fondo transparente). Si faltara, se dibuja en código
la versión anterior: fondo naranja, anillo con tres brazos (inspirado en Blender) y un fotograma en el centro."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

LOGO = Path(__file__).resolve().parent / "logo.png"


@lru_cache(maxsize=None)
def _master() -> QImage | None:
    img = QImage(str(LOGO)) if LOGO.exists() else QImage()
    return None if img.isNull() else img.convertToFormat(QImage.Format_ARGB32_Premultiplied)


@lru_cache(maxsize=None)
def render_icon(size: int = 256) -> QImage:
    img = _master()
    if img is None:
        return _draw_icon(size)
    # reducir a la mitad por pasos: un solo salto de 1024 a 16 px pierde detalle y deja bordes dentados
    while img.width() >= size * 2:
        img = img.scaled(img.width() // 2, img.height() // 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return img.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def _draw_icon(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0
    orange, white, navy = QColor("#f5792a"), QColor("#ffffff"), QColor("#265787")
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    p.fillPath(bg, orange)
    cx, cy, r = 152 * s, 146 * s, 66 * s
    # tres brazos con puntas redondeadas que salen del anillo
    p.setPen(QPen(white, 30 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(cx - 10 * s, cy - 52 * s), QPointF(104 * s, 44 * s))   # hacia arriba
    p.drawLine(QPointF(cx - 14 * s, cy - 48 * s), QPointF(46 * s, 98 * s))    # horizontal a la izquierda
    p.drawLine(QPointF(cx - 40 * s, cy - 24 * s), QPointF(44 * s, 196 * s))   # diagonal hacia abajo
    p.setPen(Qt.NoPen)
    p.setBrush(white)
    p.drawEllipse(QPointF(cx, cy), r, r)
    # fotograma en el centro
    fw = 60 * s
    frame = QRectF(cx - fw / 2, cy - fw / 2, fw, fw)
    p.setPen(QPen(navy, 7 * s))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(frame, 7 * s, 7 * s)
    p.setPen(Qt.NoPen)
    p.setBrush(navy)
    hs = 7 * s
    for i in range(3):
        y = frame.top() + fw * (0.17 + i * 0.28)
        p.drawRect(QRectF(frame.left() + 7 * s, y, hs, hs))
        p.drawRect(QRectF(frame.right() - 7 * s - hs, y, hs, hs))
    tri = QPainterPath()
    tri.moveTo(cx - 6 * s, cy - 11 * s)
    tri.lineTo(cx + 10 * s, cy)
    tri.lineTo(cx - 6 * s, cy + 11 * s)
    tri.closeSubpath()
    p.fillPath(tri, navy)
    p.end()
    return img


def app_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(render_icon(sz)))
    return icon
