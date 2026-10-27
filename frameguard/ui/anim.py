"""Animaciones de la interfaz: cortas, solo al interactuar, y desactivables.

Reglas de rendimiento:
- Nada se repinta "porque sí": cada animación dura 0,1–0,4 s y se destruye al terminar.
- Lo único continuo (brillo de la barra que renderiza, punto del motor) corre solo durante un render, a ~30 fps,
  sobre widgets diminutos.
- Ajuste «Animaciones» (QSettings "animations"); por defecto sigue «Mostrar animaciones en Windows».
"""
import ctypes

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPoint, QPointF,
                            QPropertyAnimation, QRectF, Qt, QVariantAnimation)
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QAbstractButton, QDialog, QMenu, QWidget

from .prefs import prefs

_enabled = None


def windows_animations_on() -> bool:
    try:
        val = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(val), 0)  # SPI_GETCLIENTAREAANIMATION
        return bool(val.value)
    except (AttributeError, OSError):
        return True


def enabled() -> bool:
    global _enabled
    if _enabled is None:
        v = prefs().value("animations", None)
        _enabled = windows_animations_on() if v is None else str(v).lower() in ("true", "1")
    return _enabled


def set_enabled(on: bool):
    global _enabled
    _enabled = bool(on)
    prefs().setValue("animations", bool(on))


def tween(owner: QObject, start, end, ms: int, on_value, curve=QEasingCurve.OutCubic, on_done=None):
    """Interpola un valor (float, QColor, QPoint...) y llama on_value en cada paso. Sin animaciones: salta al final."""
    if not enabled() or ms <= 0:
        on_value(end)
        if on_done:
            on_done()
        return None
    a = QVariantAnimation(owner)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setDuration(ms)
    a.setEasingCurve(curve)
    a.valueChanged.connect(on_value)
    if on_done:
        a.finished.connect(on_done)
    a.start(QVariantAnimation.DeleteWhenStopped)
    return a


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))


def pop_window(w: QWidget, dy: int = 8, ms: int = 170):
    """Ventana (menú, diálogo, panel) que aparece con fundido y un pequeño deslizamiento."""
    if not enabled():
        return
    end = w.pos()
    w.move(end + QPoint(0, dy))
    w.setWindowOpacity(0.0)
    grp = QParallelAnimationGroup(w)
    a = QPropertyAnimation(w, b"pos")
    a.setDuration(ms)
    a.setEndValue(end)
    a.setEasingCurve(QEasingCurve.OutCubic)
    b = QPropertyAnimation(w, b"windowOpacity")
    b.setDuration(ms)
    b.setStartValue(0.0)
    b.setEndValue(1.0)
    grp.addAnimation(a)
    grp.addAnimation(b)
    grp.start(QParallelAnimationGroup.DeleteWhenStopped)


class Ripple(QWidget):
    """Onda que se expande desde el punto del clic, recortada a la forma del botón."""

    def __init__(self, button: QAbstractButton, origin: QPoint, color: QColor, radius: float = 7.0):
        super().__init__(button)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(button.rect())
        self.origin = QPointF(origin)
        self.color = color
        self.radius = radius
        r = self.rect()
        corners = [QPointF(r.topLeft()), QPointF(r.topRight()), QPointF(r.bottomLeft()), QPointF(r.bottomRight())]
        self.max_r = max(((c.x() - self.origin.x()) ** 2 + (c.y() - self.origin.y()) ** 2) ** 0.5 for c in corners)
        self.t = 0.0
        self.show()
        self.raise_()
        tween(self, 0.0, 1.0, 420, self._step, QEasingCurve.OutQuad, self.deleteLater)

    def _step(self, v):
        self.t = float(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
        p.setClipPath(clip)
        c = QColor(self.color)
        c.setAlphaF(self.color.alphaF() * (1.0 - self.t))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        rad = self.max_r * (0.25 + 0.75 * self.t)
        p.drawEllipse(self.origin, rad, rad)


class MotionFilter(QObject):
    """Filtro global: onda al pulsar botones y aparición animada de menús y diálogos."""

    def __init__(self, theme):
        super().__init__()
        self.theme = theme

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.MouseButtonPress and isinstance(obj, QAbstractButton) and enabled():
            if obj.isEnabled() and not obj.property("noRipple") and ev.button() == Qt.LeftButton:
                primary = obj.objectName() in ("Primary",)
                col = QColor("#ffffff") if primary else QColor(self.theme.c["accent"])
                col.setAlphaF(0.35 if primary else 0.28)
                Ripple(obj, ev.position().toPoint(), col, 10.0 if obj.objectName() == "NavItem" else 7.0)
        elif t == QEvent.Show and enabled():
            if isinstance(obj, QMenu):
                pop_window(obj, dy=-6, ms=150)
            elif isinstance(obj, QDialog) and not obj.property("noPop") and obj.isWindow():
                pop_window(obj, dy=14, ms=200)
        return False
