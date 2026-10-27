"""Menú hamburguesa: panel lateral que entra deslizándose con el fondo oscurecido (fundido)."""
import os

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from .. import __version__
from .icon import render_icon
from ..i18n import tr
from .theme import IC, ICON_FONT

WIDTH = 300


class NavItem(QPushButton):
    def __init__(self, glyph: str, text: str, sub: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("NavItem")
        self.setCursor(Qt.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 7, 12, 7)
        lay.setSpacing(12)
        ic = QLabel(glyph)
        ic.setObjectName("NavIcon")
        ic.setStyleSheet(f"font-family: {ICON_FONT}; font-size: 12pt;")
        ic.setFixedWidth(20)
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel(text)
        t.setObjectName("NavText")
        col.addWidget(t)
        if sub:
            s = QLabel(sub)
            s.setObjectName("Muted")
            col.addWidget(s)
        for w in (ic, t):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(ic)
        lay.addLayout(col, 1)
        self.setMinimumHeight(44 if sub else 38)


class NavDrawer(QWidget):
    """Capa que cubre la ventana: fondo oscuro + panel a la izquierda."""
    closed = Signal()

    def __init__(self, window, theme):
        super().__init__(window)
        self.window_ = window
        self.theme = theme
        self.hide()
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.panel = QFrame(self)
        self.panel.setObjectName("Drawer")
        self.panel.setFixedWidth(WIDTH)
        outer = QVBoxLayout(self.panel)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()  # con muchas colas recientes o la ventana baja, el menú se desplaza
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        inner = QWidget()
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        self.lay = QVBoxLayout(inner)
        self.lay.setContentsMargins(10, 14, 10, 12)
        self.lay.setSpacing(2)
        self.anim = None

    # ------------------------------------------------------------------ contenido
    def _clear(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _section(self, title: str):
        lab = QLabel(title)
        lab.setObjectName("SectionTitle")
        lab.setContentsMargins(12, 12, 0, 4)
        self.lay.addWidget(lab)

    def _item(self, glyph, text, fn, sub="", enabled=True):
        b = NavItem(glyph, text, sub)
        b.setEnabled(enabled)
        b.clicked.connect(lambda: (self.close_drawer(), fn()))
        self.lay.addWidget(b)

    def build(self, w):
        """w = MainWindow (acciones)."""
        self._clear()
        head = QHBoxLayout()
        head.setContentsMargins(10, 0, 4, 6)
        logo = QLabel()
        logo.setPixmap(QPixmap.fromImage(render_icon(64)).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        col = QVBoxLayout()
        col.setSpacing(0)
        t = QLabel("Frameguard")
        t.setObjectName("Title")
        cur = w.current_queue()
        s = QLabel(os.path.splitext(os.path.basename(cur))[0] if cur else tr("Cola sin guardar"))
        s.setObjectName("Muted")
        col.addWidget(t)
        col.addWidget(s)
        close = QPushButton("")
        close.setObjectName("Icon")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close_drawer)
        head.addWidget(logo)
        head.addSpacing(6)
        head.addLayout(col, 1)
        head.addWidget(close, 0, Qt.AlignTop)
        hw = QWidget()
        hw.setLayout(head)
        self.lay.addWidget(hw)

        self._section(tr("COLA"))
        self._item("", tr("Abrir cola…"), w.open_queue_dialog)
        self._item("", tr("Guardar"), w.save_queue, sub=os.path.basename(cur) if cur else tr("Elegirás dónde guardarla"))
        self._item("", tr("Guardar como nueva…"), lambda: w.save_queue(ask=True))
        self._item("", tr("Nueva cola"), w.new_queue)
        rec = [p for p in (w._settings().value("recent_queues", []) or []) if os.path.isfile(p)][:5]
        if rec:
            self._section(tr("RECIENTES"))
            for p in rec:
                self._item("", os.path.splitext(os.path.basename(p))[0],
                           lambda x=p: w.open_queue_file(x), sub=os.path.dirname(p)[-38:])
        self._section(tr("AGREGAR"))
        self._item("", tr("Archivos .blend…"), w.add_files)
        self._item("", tr("Carpetas…"), w.add_folder, sub=tr("Ctrl o Shift para elegir varias"))
        self._section(tr("HERRAMIENTAS"))
        self._item("", tr("Chequeo previo"), w.open_preflight)
        self._item("", tr("Informe de la última cola"), w.open_report)
        self._item(IC["check"], tr("Quitar los terminados"), w.clear_finished)
        self._item(IC["refresh"], tr("Volver a leer todos los archivos"), w.reinspect_all)
        self._item(IC["log"], tr("Carpeta de logs"), w.open_logs_folder)
        self._item("", tr("Ajustes"), w.open_settings)
        self.lay.addStretch()
        ver = QLabel(f"Frameguard {__version__}")
        ver.setObjectName("Muted")
        ver.setContentsMargins(12, 6, 0, 0)
        self.lay.addWidget(ver)

    # ------------------------------------------------------------------ animación
    def open_drawer(self):
        self.build(self.window_)
        self.setGeometry(self.window_.rect())
        self.panel.setFixedHeight(self.height())
        self.panel.move(-WIDTH, 0)
        self.effect.setOpacity(0.0)
        self.show()
        self.raise_()
        self._animate(opening=True)
        self.setFocus()

    def close_drawer(self):
        if self.isVisible() and not (self.anim and getattr(self.anim, "closing", False)):
            self._animate(opening=False)

    def _animate(self, opening: bool):
        if self.anim:
            self.anim.stop()
        grp = QParallelAnimationGroup(self)
        slide = QPropertyAnimation(self.panel, b"pos")
        slide.setDuration(320 if opening else 220)
        slide.setStartValue(self.panel.pos())
        slide.setEndValue(QPoint(0 if opening else -WIDTH, 0))
        curve = QEasingCurve(QEasingCurve.OutBack if opening else QEasingCurve.InCubic)
        if opening:
            curve.setOvershoot(0.8)  # un pequeño rebote al llegar
        slide.setEasingCurve(curve)
        fade = QPropertyAnimation(self.effect, b"opacity")
        fade.setDuration(260 if opening else 200)
        fade.setStartValue(self.effect.opacity())
        fade.setEndValue(1.0 if opening else 0.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        grp.addAnimation(slide)
        grp.addAnimation(fade)
        grp.closing = not opening
        if not opening:
            grp.finished.connect(lambda: (self.hide(), self.closed.emit()))
        self.anim = grp
        grp.start()

    def is_open(self) -> bool:
        return self.isVisible() and not getattr(self.anim, "closing", False)

    # ------------------------------------------------------------------ fondo y eventos
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

    def mousePressEvent(self, e):
        if not self.panel.geometry().contains(e.position().toPoint()):
            self.close_drawer()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_drawer()
        else:
            super().keyPressEvent(e)
