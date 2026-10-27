"""Ventana de Novedades: aparece tras actualizar (con confeti) y desde Ajustes → «Notas de la versión»."""
import math
import random

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import __version__, changelog
from ..changelog import CHANGELOG
from ..i18n import tr
from .icon import render_icon


def _tags() -> dict:
    return {"nuevo": (tr("NUEVO"), "ok"), "mejora": (tr("MEJORA"), "accent"),
            "correccion": (tr("CORRECCIÓN"), "warn")}


class Confetti(QWidget):
    """Ráfaga corta de confeti dibujada a mano (no recibe clics)."""

    def __init__(self, parent, colors):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.colors = [QColor(c) for c in colors]
        self.parts = []
        self.t = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)

    def burst(self, n: int = 90):
        w = max(1, self.width())
        self.parts = [{"x": random.uniform(0.15, 0.85) * w, "y": random.uniform(-30, 30),
                       "vx": random.uniform(-3.2, 3.2), "vy": random.uniform(-7.5, -2.5),
                       "r": random.uniform(0, 360), "vr": random.uniform(-14, 14),
                       "s": random.uniform(5, 10), "c": random.choice(self.colors),
                       "round": random.random() < 0.3} for _ in range(n)]
        self.t = 0
        self.timer.start(16)
        self.show()
        self.raise_()

    def _step(self):
        self.t += 1
        for p in self.parts:
            p["vy"] += 0.32
            p["vx"] *= 0.99
            p["x"] += p["vx"] + math.sin((self.t + p["s"]) / 9) * 0.6
            p["y"] += p["vy"]
            p["r"] += p["vr"]
        if self.t > 150:
            self.timer.stop()
            self.parts = []
            self.hide()
        self.update()

    def paintEvent(self, _):
        if not self.parts:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fade = 1.0 if self.t < 100 else max(0.0, 1 - (self.t - 100) / 50)
        for c in self.parts:
            col = QColor(c["c"])
            col.setAlphaF(fade)
            p.save()
            p.translate(c["x"], c["y"])
            p.rotate(c["r"])
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            if c["round"]:
                p.drawEllipse(QRectF(-c["s"] / 2, -c["s"] / 2, c["s"], c["s"]))
            else:
                p.drawRect(QRectF(-c["s"] / 2, -c["s"] / 4, c["s"], c["s"] / 2))
            p.restore()


class WhatsNewDialog(QDialog):
    """mode="update": novedades de la(s) versión(es) nuevas, con confeti. mode="history": todas."""

    def __init__(self, theme, entries: list[dict], mode: str = "update", parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setProperty("noPop", True)  # tiene su propia animación de entrada
        self.theme = theme
        self.mode = mode
        self.entries = entries
        self._drag = None
        self.setFixedWidth(640)
        c = theme.c
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.card = QFrame()
        self.card.setObjectName("WNCard")
        self.card.setStyleSheet(f"#WNCard {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 16px; }}")
        outer.addWidget(self.card)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(0, 0, 0, 18)
        lay.setSpacing(0)

        # --- cabecera con degradado
        head = QFrame()
        head.setObjectName("WNHead")
        head.setStyleSheet("#WNHead { border-top-left-radius: 16px; border-top-right-radius: 16px;"
                           f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['accent']}, stop:1 #f5792a); }}")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(26, 22, 18, 22)
        hl.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(QPixmap.fromImage(render_icon(128)).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        col = QVBoxLayout()
        col.setSpacing(4)
        big = QLabel(tr("¡Novedades!") if mode == "update" else tr("Notas de la versión"))
        big.setStyleSheet("color: white; font-size: 21pt; font-weight: 700; background: transparent;")
        if mode == "update":
            sub_text = f"Frameguard {entries[0]['version']}" + (f"  ·  {changelog.date(entries[0])}" if entries else "")
        else:
            sub_text = tr("Versión instalada:") + f" {__version__}"
        sub = QLabel(sub_text)
        sub.setStyleSheet("color: white; background: rgba(255,255,255,40); border-radius: 10px; padding: 3px 10px;"
                          "font-weight: 600;")
        col.addWidget(big)
        row_sub = QHBoxLayout()
        row_sub.addWidget(sub)
        row_sub.addStretch()
        col.addLayout(row_sub)
        close = QPushButton("×")
        close.setFixedSize(30, 30)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet("QPushButton { color: white; font-size: 16pt; border: none; background: transparent;"
                            " padding: 0 0 4px 0; border-radius: 15px; } QPushButton:hover { background: rgba(255,255,255,50); }")
        close.clicked.connect(self.accept)
        hl.addWidget(logo)
        hl.addLayout(col, 1)
        hl.addWidget(close, 0, Qt.AlignTop)
        lay.addWidget(head)
        self.head = head

        # --- cuerpo
        self.body_host = QWidget()
        self.body = QVBoxLayout(self.body_host)
        self.body.setContentsMargins(22, 18, 22, 6)
        self.body.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.body_host)
        scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setMaximumHeight(460)
        self.scroll = scroll
        lay.addWidget(scroll)
        self.cards: list[QWidget] = []
        self._fill(entries, show_versions=(mode != "update" or len(entries) > 1))

        # --- pie
        foot = QHBoxLayout()
        foot.setContentsMargins(22, 10, 22, 0)
        if mode == "update":
            self.b_hist = QPushButton(tr("Ver todas las versiones"))
            self.b_hist.clicked.connect(self._show_history)
            foot.addWidget(self.b_hist)
        foot.addStretch()
        ok = QPushButton(tr("¡Entendido!") if mode == "update" else tr("Cerrar"))
        ok.setObjectName("Primary")
        ok.setMinimumWidth(140)
        ok.clicked.connect(self.accept)
        foot.addWidget(ok)
        lay.addLayout(foot)

        self.confetti = Confetti(self.card, [c["accent"], "#f5792a", c["ok"], c["warn"], "#d4537e", "#ffffff"])
        self.confetti.hide()

    # ------------------------------------------------------------------ contenido
    def _fill(self, entries, show_versions: bool):
        c = self.theme.c
        while self.body.count():
            it = self.body.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.cards = []
        for e in entries:
            if show_versions:
                vh = QLabel(tr("Versión {v}", v=e["version"])
                            + ("  " + tr("(instalada)") if e["version"] == __version__ else "")
                            + f"   ·   {changelog.date(e)}")
                vh.setStyleSheet(f"color: {c['muted']}; font-weight: 600; font-size: 9pt; letter-spacing: 1px;"
                                 "padding-top: 6px;")
                self.body.addWidget(vh)
                self.cards.append(vh)
            for kind, title, text in changelog.items(e):
                self.body.addWidget(self._item(kind, title, text))
        self.body.addStretch()

    def _item(self, kind, title, text):
        c = self.theme.c
        label, key = _tags().get(kind, (tr("NUEVO"), "ok"))
        color = QColor(c[key])
        card = QFrame()
        card.setObjectName("WNItem")
        card.setStyleSheet(f"#WNItem {{ background: {c['row']}; border: 1px solid {c['border']};"
                           f" border-left: 4px solid {c[key]}; border-radius: 10px; }}")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 13)
        lay.setSpacing(5)
        top = QHBoxLayout()
        tag = QLabel(label)
        tag.setStyleSheet(f"color: {c[key]}; background: rgba({color.red()},{color.green()},{color.blue()},40);"
                          " border-radius: 8px; padding: 2px 9px; font-size: 8pt; font-weight: 700; letter-spacing: 1px;")
        t = QLabel(title)
        t.setStyleSheet(f"font-size: 11pt; font-weight: 600; color: {c['text']}; background: transparent;")
        top.addWidget(tag)
        top.addSpacing(6)
        top.addWidget(t, 1)
        d = QLabel(text)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {c['muted']}; background: transparent;")
        lay.addLayout(top)
        lay.addWidget(d)
        self.cards.append(card)
        return card

    def _show_history(self):
        self._fill(CHANGELOG, show_versions=True)
        self.b_hist.hide()
        self._stagger(0)

    # ------------------------------------------------------------------ animaciones
    def showEvent(self, e):
        super().showEvent(e)
        self.adjustSize()
        par = self.parentWidget()
        if par is not None:
            g = par.frameGeometry()
            target = QPoint(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2)
        else:
            target = self.pos()
        self.move(target + QPoint(0, 28))
        self.setWindowOpacity(0.0)
        grp = QParallelAnimationGroup(self)
        a = QPropertyAnimation(self, b"pos")
        a.setDuration(420)
        a.setEndValue(target)
        a.setEasingCurve(QEasingCurve.OutCubic)
        b = QPropertyAnimation(self, b"windowOpacity")
        b.setDuration(320)
        b.setEndValue(1.0)
        grp.addAnimation(a)
        grp.addAnimation(b)
        grp.start()
        self._intro = grp
        self._stagger(180)
        if self.mode == "update":
            QTimer.singleShot(260, self._burst)

    def _burst(self):
        self.confetti.setGeometry(0, 0, self.card.width(), self.card.height())
        self.confetti.burst()

    def _stagger(self, delay_ms: int):
        """Las notas aparecen una tras otra (fundido)."""
        self._anims = []
        for i, w in enumerate(self.cards):
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(0.0)
            w.setGraphicsEffect(eff)
            an = QPropertyAnimation(eff, b"opacity", self)
            an.setDuration(360)
            an.setEndValue(1.0)
            an.setEasingCurve(QEasingCurve.OutCubic)
            QTimer.singleShot(delay_ms + i * 70, an.start)
            an.finished.connect(lambda w=w: w.setGraphicsEffect(None))
            self._anims.append(an)

    # ------------------------------------------------------------------ mover arrastrando la cabecera
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.head.geometry().contains(e.position().toPoint()):
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
