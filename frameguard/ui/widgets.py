"""Componentes visuales: interruptor, barra de progreso, etiqueta de estado, fila de shot y panel flotante."""
import math
import os

from PySide6.QtCore import QEasingCurve, QMimeData, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QDrag, QFontMetrics, QIntValidator, QLinearGradient, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .. import util
from ..i18n import fmt_int, plural, tr
from . import anim
from .theme import IC, alpha

MIME_JOB = "application/x-frameguard-job"


def status_view(job: dict, c: dict, max_attempts: int) -> tuple[str, str]:
    """(texto, color) de la etiqueta de estado."""
    st = job.get("status")
    fails = int(job.get("failures", 0))
    warns = [w for w in job.get("warnings", []) if w.get("level") in ("warn", "error")]
    if st == "reading":
        return tr("Leyendo…"), c["muted"]
    if st == "rendering":
        return (tr("Renderizando") if not fails else tr("Intento {n} de {total}", n=fails + 1, total=max_attempts)), c["accent"]
    if st == "done":
        return tr("Terminado"), c["ok"]
    if st == "failed":
        return tr("Falló"), c["err"]
    if st == "error_read":
        return tr("No se pudo leer"), c["err"]
    if st == "paused":
        return tr("En pausa"), c["warn"]
    if fails:
        return tr("Reintento {n} de {total}", n=fails + 1, total=max_attempts), c["err"]
    if warns:
        return plural(len(warns), "{n} aviso", "{n} avisos"), c["warn"]
    return tr("En espera"), c["muted"]


class Toggle(QAbstractButton):
    """Interruptor: la bolita se desliza y el color se funde."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(34, 20)
        self.setProperty("noRipple", True)
        self._t = 0.0
        self._first = True   # el primer estado se pinta directo, sin animar
        self._snap = False
        self.toggled.connect(self._animate)

    def _animate(self, on: bool):
        if self._snap:
            self._set_t(1.0 if on else 0.0)
        else:
            anim.tween(self, self._t, 1.0 if on else 0.0, 160, self._set_t)

    def _set_t(self, v):
        self._t = float(v)
        self.update()

    def setChecked(self, on: bool):
        first, self._first = self._first, False
        if on != self.isChecked():
            self._snap = first
            super().setChecked(on)  # toggled -> animación (o salto si es el primer estado)
            self._snap = False

    def paintEvent(self, _):
        c = self.theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(anim.mix(QColor(c["off"]), QColor(c["accent"]), self._t))
        p.drawRoundedRect(QRectF(1, 2, 32, 16), 8, 8)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(5 + 14 * self._t, 5, 10, 10))


class ProgressLine(QWidget):
    """Barra de progreso como un depósito que se llena de líquido. Avanza suave; mientras renderiza, el frente
    del líquido ondula, sube alguna burbuja y, con cada frame terminado, el líquido «chapotea».
    Solo repinta durante un render y con la ventana a la vista (a 25 fps, sobre un widget diminuto)."""
    HEIGHT = 12

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.value = 0.0      # valor mostrado (animado)
        self.target = 0.0
        self.color = None
        self.active = False
        self.phase = 0.0      # avance de la ola, en vueltas
        self.slosh = 0.0      # chapoteo al terminar un frame (1 = máximo, se calma solo)
        self.setFixedHeight(self.HEIGHT)
        self.timer = QTimer(self)
        self.timer.setInterval(40)  # 25 fps
        self.timer.timeout.connect(self._tick)

    def set(self, value: float, color: str, active: bool = False):
        value = max(0.0, min(1.0, value))
        if color != self.color:
            self.color = color
            self.update()
        if value != self.target:
            jump = value < self.target  # al reiniciar no animamos hacia atrás
            self.target = value
            if jump or not self.isVisible():
                self.value = value
                self.update()
            else:
                if self.active:
                    self.slosh = 1.0
                anim.tween(self, self.value, value, 650, self._set_value, QEasingCurve.OutQuad)
        active = active and anim.enabled()
        if active != self.active:
            self.active = active
            if active:
                self.timer.start()
            else:
                self.timer.stop()
                self.update()

    def _set_value(self, v):
        self.value = float(v)
        self.update()

    def _tick(self):
        if not _on_screen(self):
            self.timer.stop()  # ventana minimizada o en la bandeja: cero repintados (showEvent lo reanuda)
            return
        self.phase = (self.phase + 0.045) % 1000.0
        if self.slosh > 0:
            self.slosh = max(0.0, self.slosh * 0.94 - 0.004)
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        if self.active and not self.timer.isActive():
            self.timer.start()

    @staticmethod
    def _liquid(x: float, h: float, amp: float, phase: float) -> QPainterPath:
        """Líquido desde la izquierda hasta x, con el frente ondulado (una ola vertical que se desplaza)."""
        path = QPainterPath(QPointF(-1, -1))
        steps = 8
        for i in range(steps + 1):
            y = -1 + (h + 2) * i / steps
            path.lineTo(QPointF(x + amp * math.sin(2 * math.pi * (y / h * 0.85 + phase)), y))
        path.lineTo(QPointF(-1, h + 1))
        path.closeSubpath()
        return path

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = float(self.width()), float(self.height())
        tank = QPainterPath()
        tank.addRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        p.fillPath(tank, QColor(self.theme.c["track"]))
        if self.value <= 0:
            return
        p.setClipPath(tank)
        base = QColor(self.color or self.theme.c["accent"])
        body = QLinearGradient(0, 0, 0, h)  # más claro arriba, como un líquido con luz
        body.setColorAt(0.0, base.lighter(135))
        body.setColorAt(0.45, base)
        body.setColorAt(1.0, base.darker(115))
        x = w * self.value
        if self.value >= 0.999:
            p.fillRect(QRectF(0, 0, w, h), body)
        else:
            amp = (1.3 + 2.6 * self.slosh) if self.active else 0.9
            back = QColor(base)
            back.setAlphaF(0.35)
            p.fillPath(self._liquid(x + 3.0, h, amp * 1.15, self.phase + 0.45), back)  # ola de fondo
            p.fillPath(self._liquid(x, h, amp, self.phase), body)
        # reflejo de la superficie
        p.setPen(QPen(QColor(255, 255, 255, 70), 1.2))
        p.drawLine(QPointF(h * 0.45, 2.2), QPointF(max(h * 0.45, x - 4), 2.2))
        if self.active and x > 14:  # burbujas que suben (solo mientras renderiza)
            p.setPen(Qt.NoPen)
            for i in range(4):
                t = (self.phase * 0.55 + i * 0.29) % 1.0
                bx = x * (0.12 + 0.76 * ((i * 0.618 + 0.21) % 1.0)) + 3 * math.sin(2 * math.pi * (t + i * 0.3))
                by = h - 2.0 - t * (h - 3.5)
                bub = QColor(255, 255, 255, int(150 * math.sin(math.pi * t)))
                p.setBrush(bub)
                p.drawEllipse(QPointF(bx, by), 1.1 + 0.5 * (1 - t), 1.1 + 0.5 * (1 - t))


class Chip(QWidget):
    """Etiqueta de estado: al cambiar, el color se funde y da un pequeño pulso."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text, self.color = "", "#888"
        self.shown = QColor("#888")
        self.pulse = 0.0
        self.setFixedHeight(22)

    def set(self, text: str, color: str):
        if (text, color) == (self.text, self.color):
            return
        first = not self.text
        self.text, self.color = text, color
        self.setMinimumWidth(QFontMetrics(self.font()).horizontalAdvance(text) + 22)
        if first or not self.isVisible():
            self.shown = QColor(color)
            self.update()
            return
        anim.tween(self, QColor(self.shown), QColor(color), 260, self._set_color)
        anim.tween(self, 1.0, 0.0, 700, self._set_pulse, QEasingCurve.OutQuad)

    def _set_color(self, c):
        self.shown = QColor(c)
        self.update()

    def _set_pulse(self, v):
        self.pulse = float(v)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = QFontMetrics(self.font()).horizontalAdvance(self.text) + 20
        r = QRectF(0, 0, w, self.height())
        p.setPen(Qt.NoPen)
        c = QColor(self.shown)
        c.setAlphaF(0.16 + 0.30 * self.pulse)
        p.setBrush(c)
        p.drawRoundedRect(r, 6, 6)
        p.setPen(self.shown)
        p.drawText(r, Qt.AlignCenter, self.text)


class ElideLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.full = text
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.set_full(text)

    def set_full(self, text: str):
        self.full = text or ""
        self.setToolTip(self.full)
        self._elide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        super().setText(QFontMetrics(self.font()).elidedText(self.full, Qt.ElideMiddle, max(10, self.width())))


class JobRow(QFrame):
    clicked = Signal(str)
    toggledEnabled = Signal(str, bool)
    contextRequested = Signal(str, QPoint)
    removeRequested = Signal(str)

    def __init__(self, job_id: str, theme, parent=None):
        super().__init__(parent)
        self.job_id = job_id
        self.theme = theme
        self.bar_color = theme.c["muted"]
        self.hover = False
        self.selected = False
        self._press = None
        self._hover_t = 0.0
        self._flash = 0.0
        self._flash_color = QColor(theme.c["accent"])
        self._last_status = None
        self.dying = False
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(54)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 14, 6)
        lay.setSpacing(12)
        self.toggle = Toggle(theme)
        self.toggle.clicked.connect(lambda checked: self.toggledEnabled.emit(self.job_id, checked))
        self.name = ElideLabel()
        self.name.setObjectName("JobName")
        self.chip = Chip()
        self.chip_box = QWidget()
        cb = QHBoxLayout(self.chip_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.addWidget(self.chip)
        cb.addStretch()
        self.chip_box.setFixedWidth(150)
        self.range = QLabel()
        self.range.setFixedWidth(96)
        prog = QWidget()
        pv = QVBoxLayout(prog)
        pv.setContentsMargins(0, 4, 0, 0)
        pv.setSpacing(4)
        self.bar = ProgressLine(theme)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        pv.addWidget(self.bar)
        pv.addWidget(self.count)
        self.b_remove = icon_button(IC["delete"], tr("Quitar de la cola (no borra archivos)"))
        self.b_remove.setObjectName("RowIcon")
        self.b_remove.setFixedSize(30, 30)
        self.b_remove.clicked.connect(lambda: self.removeRequested.emit(self.job_id))
        lay.addWidget(self.toggle)
        lay.addWidget(self.name, 5)
        lay.addWidget(self.chip_box)
        lay.addWidget(self.range)
        lay.addWidget(prog, 4)
        lay.addWidget(self.b_remove)

    def update_job(self, job: dict, max_attempts: int):
        c = self.theme.c
        self.toggle.setChecked(bool(job.get("enabled", True)))
        self.name.set_full(job.get("name", ""))
        text, color = status_view(job, c, max_attempts)
        self.chip.set(text, color)
        info = job.get("info") or {}
        if job.get("range"):
            a, b = job["range"]
        elif info:
            a, b = info.get("frame_start"), info.get("frame_end")
        else:
            a = b = None
        self.range.setText(f"{a}–{b}" if a is not None else "—")
        total = job.get("frames_total", 0) or 0
        done = job.get("done_count", 0) or 0
        status = job.get("status")
        self.bar.set(done / total if total else 0, color if status != "ready" or done else c["accent"],
                     active=status == "rendering")
        if self._last_status is not None and status != self._last_status:
            if status == "done":
                self.flash(c["ok"])
            elif status in ("failed", "error_read"):
                self.flash(c["err"])
            elif status == "rendering":
                self.flash(c["accent"], strength=0.6)
        self._last_status = status
        extra = ""
        if job.get("status") == "rendering" and job.get("current_frame") is not None:
            extra = "  ·  " + tr("frame {n}", n=job["current_frame"])
            if job.get("eta"):
                extra += f"  ·  {util.fmt_duration(job['eta'])}"
        self.count.setText(f"{done} / {total}{extra}" if total else "—")
        self.bar_color = color
        self.b_remove.setEnabled(job.get("status") != "rendering")
        self.b_remove.setToolTip(tr("Pausa la cola para quitar el shot que se está renderizando")
                                 if job.get("status") == "rendering" else tr("Quitar de la cola (no borra archivos)"))
        self.setEnabledLook(bool(job.get("enabled", True)))
        self.update()

    def setEnabledLook(self, on: bool):
        for w in (self.name, self.range, self.count):
            w.setEnabled(on)

    def set_selected(self, on: bool):
        if on != self.selected:
            self.selected = on
            self.update()

    def event(self, e):
        if e.type() in (e.Type.HoverEnter, e.Type.HoverLeave):
            self.hover = e.type() == e.Type.HoverEnter
            anim.tween(self, self._hover_t, 1.0 if self.hover else 0.0, 140, self._set_hover)
        return super().event(e)

    def _set_hover(self, v):
        self._hover_t = float(v)
        self.update()

    # --- animaciones de la fila
    def flash(self, color: str, strength: float = 1.0):
        """Destello de color que se desvanece (terminado, fallo, empieza a renderizar)."""
        self._flash_color = QColor(color)
        anim.tween(self, strength, 0.0, 1100, self._set_flash, QEasingCurve.OutQuad)

    def _set_flash(self, v):
        self._flash = float(v)
        self.update()

    def appear(self):
        """Entrada al agregar el shot: se expande, aparece y se ilumina."""
        if not anim.enabled():
            return
        eff = QGraphicsOpacityEffect(self)
        eff.setOpacity(0.0)
        self.setGraphicsEffect(eff)
        self.setFixedHeight(0)
        anim.tween(self, 0.0, 54.0, 260, lambda v: self.setFixedHeight(int(v)))
        anim.tween(self, 0.0, 1.0, 320, lambda v: eff.setOpacity(float(v)), on_done=lambda: self.setGraphicsEffect(None))
        self.flash(self.theme.c["accent"], strength=0.7)

    def disappear(self, done):
        """Salida al quitar el shot: se pliega y se desvanece; luego llama done()."""
        self.dying = True
        self.setEnabled(False)
        if not anim.enabled():
            done()
            return
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        anim.tween(self, 1.0, 0.0, 180, lambda v: eff.setOpacity(float(v)))
        anim.tween(self, float(self.height()), 0.0, 240, lambda v: self.setFixedHeight(int(v)),
                   QEasingCurve.InCubic, on_done=done)

    def paintEvent(self, _):
        c = self.theme.c
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, anim.mix(QColor(c["row"]), QColor(c["row_hover"]), self._hover_t))
        if self._flash > 0:
            fc = QColor(self._flash_color)
            fc.setAlphaF(0.22 * self._flash)
            p.fillRect(r, fc)
        edge = 1.0 if self.selected else self._hover_t
        p.setPen(QPen(anim.mix(QColor(c["border"]), QColor(c["accent"]), edge), 1))
        p.drawRect(r.adjusted(0, 0, -1, -1))
        p.fillRect(0, 0, 3, r.height(), QColor(self.bar_color))

    # --- clic, menú contextual y arrastre para reordenar
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() > QApplication.startDragDistance():
            self._press = None
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(MIME_JOB, self.job_id.encode())
            drag.setMimeData(mime)
            drag.setPixmap(self.grab().scaledToWidth(min(420, self.width()), Qt.SmoothTransformation))
            drag.setHotSpot(QPoint(20, 20))
            drag.exec(Qt.MoveAction)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._press is not None:
            self._press = None
            self.clicked.emit(self.job_id)
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        self.contextRequested.emit(self.job_id, e.globalPos())


class MetricCard(QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        lab = QLabel(label)
        lab.setObjectName("CardLabel")
        self.value = QLabel("—")
        self.value.setObjectName("CardValue")
        self.value.setTextFormat(Qt.RichText)
        lay.addWidget(lab)
        lay.addWidget(self.value)

        self._num = None
        self._sub = ("", "#888")

    def set(self, main: str, sub: str = "", muted_color: str = "#888"):
        self._num = None
        self._show(main, sub, muted_color)

    def set_number(self, value: int, sub: str = "", muted_color: str = "#888"):
        """Número que «cuenta» hasta el valor nuevo en vez de saltar."""
        self._sub = (sub, muted_color)
        old = self._num
        self._num = value
        if old is None or old == value:
            self._show(_fmt_int(value), sub, muted_color)
            return
        anim.tween(self, float(old), float(value), 500,
                   lambda v: self._show(_fmt_int(int(round(v))), *self._sub))

    def _show(self, main: str, sub: str, muted_color: str):
        self.value.setText(f"{main} <span style='font-size:10pt;font-weight:400;color:{muted_color}'>{sub}</span>" if sub else main)


def _on_screen(w: QWidget) -> bool:
    win = w.window()
    return w.isVisible() and not win.isMinimized()


def _fmt_int(n: int) -> str:
    return fmt_int(n)


class PulseDot(QWidget):
    """Punto de estado del motor: late suavemente solo mientras renderiza."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.color = QColor("#888")
        self.phase = 0.0
        self.pulsing = False
        self.timer = QTimer(self)
        self.timer.setInterval(66)  # 15 fps
        self.timer.timeout.connect(self._tick)

    def set_state(self, color: str, pulsing: bool):
        color = QColor(color)
        pulsing = pulsing and anim.enabled()
        if color == self.color and pulsing == self.pulsing:
            return
        self.color, self.pulsing = color, pulsing
        if pulsing and not self.timer.isActive() and _on_screen(self):
            self.timer.start()
        elif not pulsing and self.timer.isActive():
            self.timer.stop()
            self.phase = 0.0
        self.update()

    def _tick(self):
        if not _on_screen(self):
            self.timer.stop()
            return
        self.phase = (self.phase + 0.045) % 1.0
        self.update()

    def showEvent(self, e):
        super().showEvent(e)
        if self.pulsing and not self.timer.isActive():
            self.timer.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        cx = cy = 7.0
        if self.timer.isActive():
            halo = QColor(self.color)
            halo.setAlphaF(0.45 * (1 - self.phase))
            p.setBrush(halo)
            rad = 3.5 + 3.5 * self.phase
            p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.setBrush(self.color)
        p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)


def icon_button(glyph: str, tip: str) -> QPushButton:
    b = QPushButton(glyph)
    b.setObjectName("Icon")
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class DetailPopup(QFrame):
    """Panel flotante con todos los datos del shot (se cierra al hacer clic fuera)."""
    action = Signal(str, str, dict)  # (acción, job_id, datos)

    def __init__(self, theme, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.theme = theme
        self.setObjectName("Popup")
        self.job_id = None
        self.setFixedWidth(700)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        head = QHBoxLayout()
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("Title")
        self.path = ElideLabel()
        self.path.setObjectName("Muted")
        tv.addWidget(self.title)
        tv.addWidget(self.path)
        head.addLayout(tv, 1)
        close = icon_button(IC["close"], tr("Cerrar"))
        close.clicked.connect(self.close)
        head.addWidget(close, 0, Qt.AlignTop)
        root.addLayout(head)
        # --- Sección ESCENA y sección PROGRESO, lado a lado
        self.kv = {}
        top = QHBoxLayout()
        top.setSpacing(10)
        # (clave interna, texto visible)
        top.addWidget(self._kv_section(tr("ESCENA"), [
            ("Cámara", tr("Cámara")), ("Resolución", tr("Resolución")), ("Engine", "Engine"), ("Samples", "Samples"),
            ("Escena", tr("Escena")), ("FPS", "FPS"), ("Guardado con", tr("Guardado con"))]), 1)
        top.addWidget(self._kv_section(tr("PROGRESO"), [
            ("Frames verificados", tr("Frames verificados")), ("Tiempo por frame", tr("Tiempo por frame")),
            ("Tiempo restante", tr("Tiempo restante")), ("Intentos", tr("Intentos")), ("Modo", tr("Modo"))]), 1)
        root.addLayout(top)
        # --- Sección SALIDAS
        sec_out, out_lay = self._section(tr("SALIDAS"))
        self.outputs = QGridLayout()
        self.outputs.setHorizontalSpacing(12)
        self.outputs.setVerticalSpacing(3)
        self.outputs.setColumnStretch(1, 1)
        out_lay.addLayout(self.outputs)
        root.addWidget(sec_out)
        # --- Sección AVISOS (solo si hay)
        self.sec_msgs, msgs_lay = self._section(tr("AVISOS"))
        self.msgs = QVBoxLayout()
        self.msgs.setSpacing(6)
        msgs_lay.addLayout(self.msgs)
        root.addWidget(self.sec_msgs)
        # --- Sección RENDER: rango y acciones
        sec_r, r_lay = self._section(tr("RENDER"))
        rng = QHBoxLayout()
        lab = QLabel(tr("Rango"))
        lab.setObjectName("Muted")
        self.r_start, self.r_end = QLineEdit(), QLineEdit()
        for s in (self.r_start, self.r_end):
            s.setValidator(QIntValidator(-100000, 1000000, s))
            s.setFixedWidth(84)
            s.setAlignment(Qt.AlignCenter)
        b_apply = QPushButton(tr("Aplicar"))
        b_apply.clicked.connect(self._apply_range)
        b_reset = QPushButton(tr("Usar el de la escena"))
        b_reset.clicked.connect(lambda: self.action.emit("set_range", self.job_id, {"start": None, "end": None}))
        self.b_mode = QPushButton()
        for w in (lab, self.r_start, QLabel("–"), self.r_end, b_apply, b_reset):
            rng.addWidget(w)
        rng.addStretch()
        rng.addWidget(self.b_mode)
        r_lay.addLayout(rng)
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.b_out = QPushButton(tr("Abrir salida"))
        self.b_log = QPushButton(tr("Ver log"))
        self.b_retry = QPushButton(tr("Reintentar"))
        self.b_full = QPushButton(tr("Re-render completo"))
        self.b_del = QPushButton(tr("Quitar de la cola"))
        self.b_del.setObjectName("Danger")
        for b in (self.b_out, self.b_log):
            btns.addWidget(b)
        btns.addStretch()
        for b in (self.b_retry, self.b_full, self.b_del):
            btns.addWidget(b)
        for b, act in ((self.b_out, "open_output"), (self.b_log, "log"), (self.b_retry, "retry"),
                       (self.b_full, "rerender"), (self.b_mode, "toggle_mode"), (self.b_del, "remove")):
            b.clicked.connect(lambda _=False, a=act: self.action.emit(a, self.job_id, {}))
        r_lay.addLayout(btns)
        root.addWidget(sec_r)

    def _section(self, title: str):
        box = QFrame()
        box.setObjectName("Section")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 9, 12, 11)
        lay.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        lay.addWidget(t)
        box.title = t
        return box, lay

    def _kv_section(self, title: str, keys: list[tuple[str, str]]) -> QFrame:
        box, lay = self._section(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(7)
        for i, (k, label) in enumerate(keys):
            col = QVBoxLayout()
            col.setSpacing(0)
            lab = QLabel(label)
            lab.setObjectName("KvLabel")
            val = QLabel("—")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            col.addWidget(lab)
            col.addWidget(val)
            grid.addLayout(col, i // 2, i % 2)
            self.kv[k] = val
        lay.addLayout(grid)
        lay.addStretch()
        return box

    def _apply_range(self):
        try:
            a, b = int(self.r_start.text()), int(self.r_end.text())
        except ValueError:
            return
        if b < a:
            a, b = b, a
        self.action.emit("set_range", self.job_id, {"start": a, "end": b})

    def _clear_msgs(self):
        while self.msgs.count():
            w = self.msgs.takeAt(0).widget()
            if w:
                w.deleteLater()

    def show_job(self, job: dict, max_attempts: int, anchor: QPoint, running: bool):
        first = self.job_id != job["id"] or not self.isVisible()
        self.job_id = job["id"]
        self.update_job(job, max_attempts, running, set_range=first)
        if first:
            self.adjustSize()
            screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
            geo = screen.availableGeometry()
            x = min(max(geo.left() + 8, anchor.x()), geo.right() - self.width() - 8)
            y = anchor.y()
            if y + self.height() > geo.bottom() - 8:
                y = max(geo.top() + 8, anchor.y() - self.height() - 60)
            self.move(x, y)
            self.show()
            anim.pop_window(self, dy=-8, ms=180)

    def update_job(self, job: dict, max_attempts: int, running: bool, set_range: bool = False):
        info = job.get("info") or {}
        self.title.setText(job.get("name", ""))
        self.path.set_full(job.get("path", ""))
        res = info.get("resolution") or []
        kv = self.kv
        kv["Cámara"].setText(info.get("camera") or "—")
        kv["Resolución"].setText(f"{res[0]}×{res[1]} · {res[2]} %" if len(res) == 3 else "—")
        eng = {"BLENDER_EEVEE": "EEVEE", "BLENDER_EEVEE_NEXT": "EEVEE", "CYCLES": "Cycles",
               "BLENDER_WORKBENCH": "Workbench"}.get(info.get("engine"), info.get("engine") or "—")
        kv["Engine"].setText(eng)
        kv["Escena"].setText(job.get("scene") or info.get("scene") or "—")
        kv["Frames verificados"].setText(f"{job.get('done_count', 0)} / {job.get('frames_total', 0)}")
        kv["Tiempo por frame"].setText(util.fmt_duration(job.get("avg_frame")) if job.get("avg_frame") else "—")
        kv["Tiempo restante"].setText(util.fmt_duration(job.get("eta")) if job.get("eta") else "—")
        kv["Intentos"].setText(tr("{n} fallidos de {total}", n=int(job.get("failures", 0)), total=max_attempts))
        kv["FPS"].setText(f"{info.get('fps'):g}" if info.get("fps") else "—")
        kv["Modo"].setText(tr("Solo frames faltantes") if job.get("mode") == "missing" else tr("Completo"))
        fv = info.get("file_version")
        kv["Guardado con"].setText(f"Blender {fv[0]}.{fv[1]}" if fv else "—")
        kv["Samples"].setText(str(info.get("samples")) if info.get("samples") else "—")
        while self.outputs.count():
            w = self.outputs.takeAt(0).widget()
            if w:
                w.deleteLater()
        outs = info.get("outputs") or []
        save_off = any(w.get("code") == "save_off" or w["text"].startswith("Save Output está encendido: se apagará")
                       for w in job.get("warnings", []))
        for i, o in enumerate(outs or [{"node": "—", "directory": "", "kind": ""}]):
            name = QLabel(o["node"])
            name.setObjectName("JobName")
            path = ElideLabel(os.path.normpath(o["directory"]) if o.get("directory") else "—")
            if o["kind"] == "main" and save_off:
                path.set_full(path.full + "   " + tr("(se apaga durante el render)"))
                path.setObjectName("Muted")
            self.outputs.addWidget(name, i, 0)
            self.outputs.addWidget(path, i, 1)
        self._clear_msgs()
        if job.get("error"):
            lab = QLabel(job["error"])
            lab.setObjectName("Err")
            lab.setWordWrap(True)
            self.msgs.addWidget(lab)
        for w in job.get("warnings", []):
            lab = QLabel(w["text"])
            lab.setObjectName({"error": "Err", "warn": "Warn"}.get(w.get("level"), "Info"))
            lab.setWordWrap(True)
            self.msgs.addWidget(lab)
        hist = [h for h in job.get("history", []) if h.get("reason")]
        if hist:
            lab = QLabel(tr("Historial:") + " " + " · ".join(h["reason"] for h in hist[-3:]))
            lab.setObjectName("Info")
            lab.setWordWrap(True)
            self.msgs.addWidget(lab)
        n = self.msgs.count()
        self.sec_msgs.setVisible(n > 0)
        self.sec_msgs.title.setText(tr("AVISOS") + f" ({n})")
        self.adjustSize()
        if set_range:
            a, b = job.get("range") or [info.get("frame_start", 1), info.get("frame_end", 1)]
            self.r_start.setText(str(int(a)))
            self.r_end.setText(str(int(b)))
        is_running = running
        self.b_mode.setText(tr("Renderizar todo") if job.get("mode") == "missing" else tr("Solo faltantes"))
        self.b_mode.setToolTip(tr("Completo: renderiza todo el rango.\nSolo faltantes: salta los frames que ya existen en disco."))
        self.b_retry.setEnabled(job.get("status") in ("failed", "paused", "error_read", "done") or bool(job.get("failures")))
        self.b_del.setEnabled(not is_running)
        self.b_full.setEnabled(not is_running)
        self.b_log.setEnabled(bool(job.get("logs")))

    def sizeHint(self):
        return QSize(700, super().sizeHint().height())
