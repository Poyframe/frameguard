"""Avisos emergentes de Frameguard: tarjetas en la esquina inferior derecha que entran deslizándose,
no roban el foco y se van solas.

Su tiempo solo corre mientras el usuario está usando el PC (hubo ratón o teclado hace poco) y el ratón no está
encima: un aviso de madrugada se ve al volver y luego se va solo, sin tener que cerrarlo a mano."""
import ctypes

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .theme import ICON_FONT

WIDTH, MARGIN, GAP = 380, 18, 10
# cuánto tiempo se ve cada aviso (contando solo con el usuario presente)
DURATION_MS = {"shot_done": 8000, "queue_done": 15000, "job_failed": 20000}
TICK_MS = 500
AWAY_AFTER_MS = 30000  # sin ratón ni teclado durante 30 s = el usuario no está mirando


class _LastInput(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def idle_ms() -> int:
    """Milisegundos desde el último movimiento de ratón o tecla en esta sesión de Windows."""
    try:
        info = _LastInput(ctypes.sizeof(_LastInput), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    except (AttributeError, OSError):
        return 0
GLYPH = {"shot_done": "", "queue_done": "", "job_failed": "", "info": ""}


class Toast(QWidget):
    clicked = Signal()
    finished = Signal(object)

    def __init__(self, theme, kind: str, title: str, text: str, timeout_ms: int = 8000):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.theme = theme
        c = theme.c
        self.color = {"shot_done": c["ok"], "queue_done": c["accent"], "job_failed": c["err"]}.get(kind, c["accent"])
        self.remaining_ms = timeout_ms  # se descuenta en ToastManager._tick
        self.hovered = False
        self.closing = False
        self.anim = None
        self.setFixedWidth(WIDTH)
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 14, 10, 14)
        lay.setSpacing(14)
        icon = QLabel(GLYPH.get(kind, GLYPH["info"]))
        icon.setFixedSize(38, 38)
        icon.setAlignment(Qt.AlignCenter)
        bg = QColor(self.color)
        bg.setAlphaF(0.18)
        icon.setStyleSheet(f"font-family: {ICON_FONT}; font-size: 15pt; color: {self.color}; border-radius: 19px;"
                           f"background: rgba({bg.red()},{bg.green()},{bg.blue()},46);")
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"font-weight: 600; font-size: 10.5pt; color: {c['text']};")
        m = QLabel(text)
        m.setWordWrap(True)
        m.setStyleSheet(f"color: {c['muted']}; font-size: 9.5pt;")
        col.addWidget(t)
        col.addWidget(m)
        close = QPushButton("×")
        close.setFixedSize(26, 26)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(f"QPushButton {{ font-family: 'Segoe UI'; font-size: 14pt; padding: 0 0 3px 0; border: none; color: {c['muted']};"
                            f" background: transparent; border-radius: 13px; }} QPushButton:hover {{ background: {c['track']}; }}")
        close.clicked.connect(self.dismiss)
        for w in (icon, t, m):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(icon, 0, Qt.AlignTop)
        lay.addLayout(col, 1)
        lay.addWidget(close, 0, Qt.AlignTop)
        self.adjustSize()

    def paintEvent(self, _):
        c = self.theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor(c["panel"]))
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawPath(path)
        p.setClipPath(path)
        p.fillRect(QRectF(0, 0, 5, self.height()), QColor(self.color))

    # ------------------------------------------------------------------ animaciones
    def slide_in(self, target: QPoint):
        self.move(target + QPoint(40, 0))
        self.setWindowOpacity(0.0)
        self.show()
        self._animate(target, 1.0, 320, QEasingCurve.OutCubic)

    def move_to(self, target: QPoint):
        if not self.closing:
            self._animate(target, self.windowOpacity(), 220, QEasingCurve.OutCubic)

    def dismiss(self):
        if self.closing:
            return
        self.closing = True
        self._animate(self.pos() + QPoint(40, 0), 0.0, 220, QEasingCurve.InCubic, then_close=True)

    def _animate(self, pos: QPoint, opacity: float, ms: int, curve, then_close=False):
        if self.anim:
            self.anim.stop()
        grp = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self, b"pos")
        a.setDuration(ms)
        a.setEndValue(pos)
        a.setEasingCurve(curve)
        b = QPropertyAnimation(self, b"windowOpacity")
        b.setDuration(ms)
        b.setEndValue(opacity)
        grp.addAnimation(a)
        grp.addAnimation(b)
        if then_close:
            grp.finished.connect(lambda: (self.finished.emit(self), self.close()))
        self.anim = grp
        grp.start()

    # ------------------------------------------------------------------ ratón
    def enterEvent(self, e):
        self.hovered = True  # mientras el ratón está encima, no se va
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hovered = False
        self.remaining_ms = max(self.remaining_ms, 3000)  # al salir, aún se ve un momento
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            self.dismiss()


class ToastManager:
    """Apila los avisos desde la esquina inferior derecha de la pantalla principal."""

    def __init__(self, theme, on_click):
        self.theme = theme
        self.on_click = on_click
        self.toasts: list[Toast] = []
        self.timer = QTimer()  # solo corre mientras hay avisos en pantalla
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        """Descuenta el tiempo de los avisos solo si el usuario está delante del PC."""
        if not self.toasts:
            self.timer.stop()
            return
        if idle_ms() > AWAY_AFTER_MS:
            return  # nadie mirando (de noche, pantalla bloqueada...): los avisos esperan
        for t in list(self.toasts):
            if t.closing or t.hovered:
                continue
            t.remaining_ms -= TICK_MS
            if t.remaining_ms <= 0:
                t.dismiss()

    def show(self, kind: str, title: str, text: str):
        t = Toast(self.theme, kind, title, text, timeout_ms=DURATION_MS.get(kind, 10000))
        t.clicked.connect(self.on_click)
        t.finished.connect(self._removed)
        self.toasts.insert(0, t)
        while len(self.toasts) > 4:
            self.toasts.pop().dismiss()
        positions = self._positions()
        t.slide_in(positions[0])
        for other, pos in zip(self.toasts[1:], positions[1:]):
            other.move_to(pos)
        if not self.timer.isActive():
            self.timer.start()
        return t

    def _positions(self) -> list[QPoint]:
        geo = QGuiApplication.primaryScreen().availableGeometry()
        out, y = [], geo.bottom() - MARGIN
        for t in self.toasts:
            y -= t.height()
            out.append(QPoint(geo.right() - MARGIN - WIDTH, y))
            y -= GAP
        return out

    def _removed(self, t):
        if t in self.toasts:
            self.toasts.remove(t)
            for other, pos in zip(self.toasts, self._positions()):
                other.move_to(pos)
