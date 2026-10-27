"""Ventana principal de Frameguard."""
import logging
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QObject, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSystemTrayIcon, QVBoxLayout, QWidget)

from .. import __version__, paths, scan, updater, util
from .. import changelog, sounds
from .. import i18n
from ..i18n import fmt_int, plural, tr
from .drawer import NavDrawer
from .folderpicker import pick_folders
from .prefs import prefs
from .toast import ToastManager
from .whatsnew import WhatsNewDialog
from .dialogs import CountdownDialog, LogDialog, PreflightDialog, ScanDialog, SettingsDialog
from .icon import app_icon, render_icon
from .theme import ICON_FONT, IC, glyph_icon
from . import anim
from .widgets import MIME_JOB, DetailPopup, JobRow, MetricCard, PulseDot, icon_button, status_view


def after_options():
    """Al terminar la cola: (texto, valor, glifo, color del tema). Mismo orden e iconos que el menú de Windows."""
    return [(tr("No hacer nada"), "none", "monitor", "muted"), (tr("Suspender"), "sleep", "sleep", "accent"),
            (tr("Apagar"), "shutdown", "shutdown", "err"), (tr("Reiniciar"), "restart", "restart", "warn")]


class _HeaderRow(QWidget):
    """Fila de títulos de columna con un botón superpuesto pegado a la derecha."""
    overlay = None

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.overlay is not None:
            self.overlay.adjustSize()
            self.overlay.move(self.width() - self.overlay.width() - 20, (self.height() - self.overlay.height()) // 2 + 2)
            self.overlay.raise_()


class _UpdateBridge(QObject):
    """Trae el resultado de la búsqueda de actualizaciones (hilo aparte: la red puede ir lenta)."""
    found = Signal(object)


class _ScanBridge(QObject):
    """Trae el resultado de buscar .blend en carpetas (hilo aparte: por la red puede tardar)."""
    done = Signal(object)


def classify_paths(paths_: list[str]) -> tuple[list[str], list[str], list[str]]:
    """(archivos .blend, colas .fgq, carpetas) de una lista de rutas; lo demás se ignora."""
    blends = [os.path.normpath(p) for p in paths_ if os.path.isfile(p) and p.lower().endswith(".blend")]
    queues = [p for p in paths_ if os.path.isfile(p) and p.lower().endswith(".fgq")]
    folders = [os.path.normpath(p) for p in paths_ if os.path.isdir(p)]
    return blends, queues, folders


class DropOverlay(QWidget):
    """Capa que aparece al arrastrar archivos o carpetas sobre la ventana y dice qué pasará al soltar."""
    dropped = Signal(list)

    def __init__(self, window, theme):
        super().__init__(window)
        self.theme = theme
        self.setAcceptDrops(True)
        self.hide()
        self.t = 0.0          # 0 = oculta, 1 = visible (animado)
        self.ok = True
        self.title, self.sub = "", ""
        self.hovering = False
        self.leaving = False

    def show_for(self, paths_: list[str]):
        blends, queues, folders = classify_paths(paths_)
        parts = []
        if blends:
            parts.append(plural(len(blends), "{n} archivo .blend: va directo a la cola",
                                "{n} archivos .blend: van directo a la cola"))
        if folders:
            parts.append(plural(len(folders), "{n} carpeta: elegirás qué archivos agregar",
                                "{n} carpetas: elegirás qué archivos agregar"))
        if queues:
            parts.append(tr("cola guardada (.fgq): se abre"))
        self.ok = bool(parts)
        self.title = tr("Suelta para agregar") if self.ok else tr("Esto no se puede agregar")
        self.sub = "\n".join(parts) if self.ok else tr("Solo archivos .blend, carpetas o colas .fgq")
        self.setGeometry(self.parentWidget().rect())
        if not self.isVisible() or self.leaving:
            self.leaving = False
            self.show()
            self._animate(1.0, 180)
        self.raise_()
        self.update()

    def hide_animated(self):
        if not self.isVisible() or self.leaving:
            return
        self.leaving = True
        self._animate(0.0, 140, lambda: self.hide() if self.leaving else None)

    def _animate(self, end: float, ms: int, on_done=None):
        """Una sola animación a la vez: entrar y salir no se pisan si el arrastre va y viene."""
        prev, self._anim = getattr(self, "_anim", None), None
        if prev is not None:
            try:
                prev.stop()
            except RuntimeError:  # ya terminó y Qt la borró
                pass
        self._anim = anim.tween(self, self.t, end, ms, self._set_t, QEasingCurve.OutCubic, on_done)

    def _set_t(self, v):
        self.t = float(v)
        self.update()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self.hovering = True
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction() if self.ok else e.ignore()

    def dragLeaveEvent(self, e):
        self.hovering = False
        self.hide_animated()

    def dropEvent(self, e):
        self.hovering = False
        paths_ = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        logging.info("Soltado: %s", paths_ if self.ok else f"nada aprovechable en {paths_}")
        self.hide_animated()
        if self.ok and paths_:
            e.acceptProposedAction()
            self.dropped.emit(paths_)

    def paintEvent(self, _):
        c = self.theme.c
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(c["bg"])
        bg.setAlphaF(0.88 * self.t)
        p.fillRect(self.rect(), bg)
        color = QColor(c["accent"] if self.ok else c["err"])
        inset = 16 + 10 * (1 - self.t)  # el recuadro «se acerca» al aparecer
        box = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        fill = QColor(color)
        fill.setAlphaF(0.07 * self.t)
        path = QPainterPath()
        path.addRoundedRect(box, 14, 14)
        p.fillPath(path, fill)
        pen = QPen(color, 2.2, Qt.DashLine)
        pen.setDashPattern([5, 4])
        edge = QColor(color)
        edge.setAlphaF(self.t)
        pen.setColor(edge)
        p.setPen(pen)
        p.drawPath(path)
        cx, cy = box.center().x(), box.center().y() - 30
        circle = QColor(color)
        circle.setAlphaF(0.16 * self.t)
        p.setPen(Qt.NoPen)
        p.setBrush(circle)
        p.drawEllipse(QRectF(cx - 38, cy - 38, 76, 76))
        text = QColor(c["text"])
        text.setAlphaF(self.t)
        glyph = QColor(color)
        glyph.setAlphaF(self.t)
        f = QFont()
        f.setFamilies([ICON_FONT.split(",")[0].strip('" '), "Segoe MDL2 Assets"])
        f.setPixelSize(34)
        p.setFont(f)
        p.setPen(glyph)
        p.drawText(QRectF(cx - 38, cy - 38 + 6 * (1 - self.t), 76, 76), Qt.AlignCenter,
                   IC["download"] if self.ok else IC["error"])
        f = QFont("Segoe UI")
        f.setPixelSize(19)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(text)
        p.drawText(QRectF(box.left(), cy + 48, box.width(), 30), Qt.AlignCenter, self.title)
        f.setPixelSize(13)
        f.setWeight(QFont.Normal)
        p.setFont(f)
        muted = QColor(c["muted"])
        muted.setAlphaF(self.t)
        p.setPen(muted)
        p.drawText(QRectF(box.left() + 20, cy + 82, box.width() - 40, 70), Qt.AlignHCenter | Qt.AlignTop, self.sub)


class QueueList(QWidget):
    moveRequested = Signal(str, int)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.setObjectName("ListHost")
        self.theme = theme
        self.setAcceptDrops(True)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 4, 0)
        self.lay.setSpacing(6)
        self.lay.addStretch()
        self.rows: dict[str, JobRow] = {}
        self.order: list[str] = []
        self.drop_y = None
        self._synced = False

    def sync(self, jobs: list[dict], factory, max_attempts: int):
        ids = [j["id"] for j in jobs]
        initial = not self._synced  # al abrir la ventana, la cola aparece sin animación de entrada
        self._synced = True
        for jid in list(self.rows):
            if jid not in ids:
                row = self.rows.pop(jid)
                row.disappear(lambda r=row: (self.lay.removeWidget(r), r.deleteLater()))
        new_rows = []
        for j in jobs:
            if j["id"] not in self.rows:
                self.rows[j["id"]] = factory(j["id"])
                new_rows.append(self.rows[j["id"]])
            self.rows[j["id"]].update_job(j, max_attempts)
        if ids != self.order:
            for jid in self.order:
                if jid in self.rows:
                    self.lay.removeWidget(self.rows[jid])
            for i, jid in enumerate(ids):
                self.lay.insertWidget(i, self.rows[jid])
            self.order = ids
        if not initial and anim.enabled():
            for k, row in enumerate(new_rows):  # varias a la vez: entran escalonadas
                if k:
                    row.setFixedHeight(0)
                QTimer.singleShot(min(k, 12) * 45, row.appear)

    def _index_at(self, y: int) -> int:
        for i, jid in enumerate(self.order):
            g = self.rows[jid].geometry()
            if y < g.center().y():
                return i
        return len(self.order)

    # Aquí solo se arrastran filas para reordenar. Los archivos y carpetas de fuera se pasan a la ventana, que
    # muestra la capa «Suelta para agregar» (la capa queda encima y recibe el resto del arrastre).
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_JOB):
            e.acceptProposedAction()
        elif e.mimeData().hasUrls() and hasattr(self.window(), "drop_overlay"):
            self.window().dragEnterEvent(e)
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(MIME_JOB):
            e.ignore()
            return
        idx = self._index_at(int(e.position().y()))
        if idx < len(self.order):
            self.drop_y = self.rows[self.order[idx]].geometry().top() - 3
        elif self.order:
            self.drop_y = self.rows[self.order[-1]].geometry().bottom() + 3
        self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.drop_y = None
        self.update()

    def dropEvent(self, e):
        self.drop_y = None
        self.update()
        md = e.mimeData()
        if md.hasFormat(MIME_JOB):
            jid = bytes(md.data(MIME_JOB)).decode()
            idx = self._index_at(int(e.position().y()))
            cur = self.order.index(jid) if jid in self.order else -1
            if cur >= 0 and idx > cur:
                idx -= 1
            if idx != cur:
                self.moveRequested.emit(jid, idx)
            e.acceptProposedAction()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.drop_y is not None:
            p = QPainter(self)
            p.setPen(QPen(QColor(self.theme.c["accent"]), 2))
            p.drawLine(4, self.drop_y, self.width() - 8, self.drop_y)


class EmptyState(QFrame):
    def __init__(self, on_files, on_folder, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        t = QLabel(tr("Arrastra aquí archivos .blend o carpetas"))
        t.setObjectName("Empty")
        t.setAlignment(Qt.AlignCenter)
        s = QLabel(tr("De cada archivo se toma la versión más alta (por ejemplo _RND_V03)."))
        s.setObjectName("Muted")
        s.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.addStretch()
        b1, b2 = QPushButton(tr("Agregar archivos")), QPushButton(tr("Agregar carpetas"))
        b1.clicked.connect(on_files)
        b2.clicked.connect(on_folder)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch()
        lay.addWidget(t)
        lay.addWidget(s)
        lay.addSpacing(8)
        lay.addLayout(row)


class MainWindow(QMainWindow):
    def __init__(self, client, theme):
        super().__init__()
        self.client, self.theme = client, theme
        self.st: dict = {}
        self.prev_status: dict[str, str] = {}
        self.tray_hint_shown = False
        self.popup = DetailPopup(theme, self)
        self.popup.action.connect(self.on_popup_action)
        self.countdown = CountdownDialog(theme, self)
        self.countdown.cancelled.connect(lambda: self.client.send("cancel_countdown"))
        self.countdown.nowRequested.connect(lambda: self.client.send("countdown_now"))
        self.setWindowTitle("Frameguard")
        self.setWindowIcon(app_icon())
        self.resize(1080, 720)
        self.setMinimumSize(860, 520)
        self.setAcceptDrops(True)
        self._build()
        self._build_tray()
        self._update_queue_label()
        self.drawer = NavDrawer(self, theme)
        self.drop_overlay = DropOverlay(self, theme)
        self.drop_overlay.dropped.connect(self.add_paths)
        self._scan = _ScanBridge()
        self._scan.done.connect(self._scan_done)
        self.toasts = ToastManager(theme, self.show_normal)
        self._ev_pid = None
        self._ev_seen = 0
        client.stateChanged.connect(self.on_state)
        client.connectionChanged.connect(self.on_connection)
        theme.changed.connect(self._retheme)
        theme.aboutToChange.connect(self._before_retheme)
        self.update_item = None
        self._upd_checked = False
        self._upd = _UpdateBridge()
        self._upd.found.connect(self._on_update_found)
        self.upd_timer = QTimer(self)
        self.upd_timer.timeout.connect(self.check_updates)
        self.upd_timer.start(6 * 3600 * 1000)
        self.whats_new = None
        QTimer.singleShot(1200, self._maybe_whats_new)

    # ------------------------------------------------------------------ novedades
    def _maybe_whats_new(self):
        """Primera apertura tras instalar o actualizar: muestra lo nuevo de la(s) versión(es)."""
        forced = bool(os.environ.get("FRAMEGUARD_SCREENSHOT_WHATSNEW"))
        testing = bool(os.environ.get("FRAMEGUARD_SCREENSHOT"))
        if testing and not forced:
            return
        s = self._settings()
        last = s.value("last_seen_version", "") or None
        if last == __version__ and not forced:
            return
        entries = changelog.versions_after(last, __version__)
        if not testing:
            s.setValue("last_seen_version", __version__)
        if entries:
            self.show_release_notes(entries, mode="update")

    def show_release_notes(self, entries=None, mode: str = "history"):
        self.whats_new = WhatsNewDialog(self.theme, entries or changelog.CHANGELOG, mode=mode, parent=self)
        self.whats_new.setModal(True)
        self.whats_new.show()

    def toggle_drawer(self):
        if self.drawer.is_open():
            self.drawer.close_drawer()
        else:
            self.drawer.open_drawer()

    # ------------------------------------------------------------------ ahorro cuando no se ve la ventana
    def _visibility_changed(self):
        """Minimizada o en la bandeja: consulta al motor cada 2 s (los avisos siguen llegando) y sin animaciones
        continuas. Al volver: 0,6 s y se reanudan."""
        if not hasattr(self, "dot"):
            return
        on_screen = self.isVisible() and not self.isMinimized()
        self.client.timer.setInterval(600 if on_screen else 2000)
        if on_screen and getattr(self, "_stale", False) and self.st:
            QTimer.singleShot(0, lambda: self.on_state(self.st))  # ponerse al día al volver
        if on_screen:
            for row in self.list.rows.values():
                if row.bar.active and not row.bar.timer.isActive():
                    row.bar.timer.start()
            if self.dot.pulsing and not self.dot.timer.isActive():
                self.dot.timer.start()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange:
            self._visibility_changed()

    def showEvent(self, e):
        super().showEvent(e)
        self._visibility_changed()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._visibility_changed()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "drawer", None) and self.drawer.isVisible():
            self.drawer.setGeometry(self.rect())
            self.drawer.panel.setFixedHeight(self.height())
        if getattr(self, "drop_overlay", None) and self.drop_overlay.isVisible():
            self.drop_overlay.setGeometry(self.rect())

    # ------------------------------------------------------------------ arrastrar y soltar desde el explorador
    def dragEnterEvent(self, e):
        """Al entrar con archivos o carpetas aparece la capa «Suelta para agregar», que recibe el resto del
        arrastre (la lista solo acepta filas para reordenar)."""
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            paths_ = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if not self.drop_overlay.isVisible():
                logging.info("Arrastre sobre la ventana: %s ruta(s)", len(paths_))
            self.drop_overlay.show_for(paths_)

    def dragLeaveEvent(self, e):
        # al aparecer la capa, el arrastre «sale» de la ventana y entra en la capa: solo se oculta si de
        # verdad salió de la ventana
        QTimer.singleShot(80, lambda: None if self.drop_overlay.hovering else self.drop_overlay.hide_animated())

    def dropEvent(self, e):
        paths_ = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.drop_overlay.hide_animated()
        if paths_:
            e.acceptProposedAction()
            self.add_paths(paths_)

    # ------------------------------------------------------------------ construcción
    def _build(self):
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(10)

        head = QHBoxLayout()
        self.logo = QLabel()
        self.logo.setPixmap(QPixmap.fromImage(render_icon(56)).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.b_menu = icon_button("", tr("Menú"))
        self.b_menu.clicked.connect(self.toggle_drawer)
        head.addWidget(self.b_menu)
        head.addSpacing(4)
        title = QLabel("Frameguard")
        title.setObjectName("Title")
        ver = QLabel(f"v{__version__}")
        ver.setObjectName("Version")
        self.dot = PulseDot()
        self.conn = QLabel(tr("Conectando con el motor…"))
        self.conn.setObjectName("Muted")
        head.addWidget(self.logo)
        head.addWidget(title)
        head.addWidget(ver)
        self.queue_label = QLabel()
        self.queue_label.setObjectName("Muted")
        head.addSpacing(10)
        head.addWidget(self.queue_label)
        head.addSpacing(12)
        head.addWidget(self.dot)
        head.addWidget(self.conn)
        head.addStretch()
        self.b_theme = icon_button(IC["desktop"], tr("Tema"))
        tm = QMenu(self)
        grp = QActionGroup(self)
        for label, mode in ((tr("Según el sistema"), "system"), (tr("Claro"), "light"), (tr("Oscuro"), "dark")):
            a = QAction(label, self, checkable=True)
            a.setChecked(self.theme.mode == mode)
            a.triggered.connect(lambda _=False, m=mode: self.theme.set_mode(m))
            grp.addAction(a)
            tm.addAction(a)
        self.b_theme.setMenu(tm)
        self.b_theme.setText({"system": IC["desktop"], "light": IC["sun"], "dark": IC["moon"]}.get(self.theme.mode, IC["desktop"]))
        b_add_txt = QPushButton(tr("Agregar"))
        am = QMenu(self)
        am.addAction(tr("Archivos .blend…"), self.add_files)
        am.addAction(tr("Carpetas…"), self.add_folder)
        b_add_txt.setMenu(am)
        self.b_add_txt = b_add_txt
        b_set = icon_button(IC["settings"], tr("Ajustes"))
        b_set.clicked.connect(self.open_settings)
        head.addWidget(self.b_theme)
        head.addWidget(b_add_txt)
        head.addWidget(b_set)
        v.addLayout(head)

        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 10, 8)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.b_upd_now = QPushButton(tr("Actualizar ahora"))
        self.b_upd_now.setObjectName("Primary")
        self.b_upd_now.clicked.connect(lambda: self.install_update(self.update_item))
        b_later = QPushButton(tr("Más tarde"))
        b_later.clicked.connect(self.banner.hide)
        b_skip = QPushButton(tr("Omitir esta versión"))
        b_skip.setToolTip(tr("Te quedas con la versión actual y no vuelve a avisarte de esta."))
        b_skip.clicked.connect(self.skip_update)
        bl.addWidget(self.banner_text, 1)
        for b in (self.b_upd_now, b_later, b_skip):
            bl.addWidget(b)
        self.banner.hide()
        v.addWidget(self.banner)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.m_frames = MetricCard(tr("Frames en disco"))
        self.m_jobs = MetricCard(tr("Shots"))
        self.m_eta = MetricCard(tr("Tiempo restante"))
        for m in (self.m_frames, self.m_jobs, self.m_eta):
            cards.addWidget(m)
        v.addLayout(cards)

        cols = QHBoxLayout()
        cols.setContentsMargins(14, 6, 18, 0)
        cols.setSpacing(12)
        cols.addSpacing(34)
        for text, stretch, width in ((tr("Shot"), 5, None), (tr("Estado"), 0, 150), (tr("Rango"), 0, 96),
                                     (tr("Progreso"), 4, None)):
            lab = QLabel(text)
            lab.setObjectName("ColHeader")
            if width:
                lab.setFixedWidth(width)
            cols.addWidget(lab, stretch)
        cols.addSpacing(30)  # misma columna que la papelera de cada fila: los títulos quedan alineados
        cols_host = _HeaderRow()
        cols_host.setLayout(cols)
        # «Vaciar cola» va superpuesto a la derecha, fuera de las columnas, para no descuadrarlas
        self.b_clear = QPushButton(IC["delete"] + "  " + tr("Vaciar cola"), cols_host)
        self.b_clear.setObjectName("HeaderBtn")
        self.b_clear.setCursor(Qt.PointingHandCursor)
        self.b_clear.setToolTip(tr("Quitar todos los shots de la cola (no borra ningún archivo)"))
        self.b_clear.clicked.connect(self.clear_queue)
        cols_host.overlay = self.b_clear
        v.addWidget(cols_host)

        self.list = QueueList(self.theme)
        self.list.moveRequested.connect(lambda jid, idx: self.client.send("move", id=jid, index=idx))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.list)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.empty = EmptyState(self.add_files, self.add_folder)
        v.addWidget(self.scroll, 1)
        v.addWidget(self.empty, 1)
        self.empty.hide()

        self.last_line = QLabel(tr("Listo."))
        self.last_line.setObjectName("Mono")
        self.last_line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.last_line)

        bottom = QHBoxLayout()
        lab = QLabel(tr("Al terminar la cola:"))
        lab.setObjectName("Muted")
        self.after = QComboBox()
        self.after.setIconSize(QSize(16, 16))
        self.after.setMinimumWidth(170)
        for label, val, _glyph, _color in after_options():
            self.after.addItem(label, val)
        self._after_icons()
        self.after.currentIndexChanged.connect(self._after_changed)
        bottom.addWidget(lab)
        bottom.addWidget(self.after)
        bottom.addStretch()
        b_pre = QPushButton(tr("Chequeo previo"))
        b_pre.clicked.connect(self.open_preflight)
        b_rep = QPushButton(tr("Informe"))
        b_rep.clicked.connect(self.open_report)
        self.b_run = QPushButton(tr("Iniciar render"))
        self.b_run.setObjectName("Primary")
        self.b_run.setMinimumWidth(150)
        self.b_run.setStyleSheet('font-family: "Segoe UI", "Segoe Fluent Icons", "Segoe MDL2 Assets";')
        self.b_run.clicked.connect(self.toggle_run)
        for b in (b_pre, b_rep, self.b_run):
            bottom.addWidget(b)
        v.addLayout(bottom)

    def _after_icons(self):
        """Iconos de «Al terminar la cola» con los colores del tema actual."""
        c = self.theme.c
        for i, (_label, _val, glyph, color) in enumerate(after_options()):
            self.after.setItemIcon(i, glyph_icon(IC[glyph], c[color], 16))
        self._after_look()

    def _after_look(self):
        """Con apagar / suspender / reiniciar elegido, el desplegable se resalta (para no olvidarlo)."""
        val = self.after.currentData()
        armed = val not in (None, "none")
        if self.after.property("armed") != armed:
            self.after.setProperty("armed", armed)
            self.after.style().unpolish(self.after)
            self.after.style().polish(self.after)
        wait = round(float((self.st.get("settings") or {}).get("countdown_seconds", 600)) / 60) if self.st else 10
        self.after.setToolTip(tr("Al terminar la cola, Frameguard esperará {n} min con una cuenta atrás que "
                                 "puedes cancelar.", n=wait) if armed else
                              tr("Al terminar la cola el equipo se queda como está."))

    def _after_changed(self, _):
        self.client.send("set_after", action=self.after.currentData())
        self._after_look()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("Frameguard")
        m = QMenu()
        m.addAction(tr("Mostrar Frameguard"), self.show_normal)
        self.tray_run = m.addAction(tr("Iniciar render"), self.toggle_run)
        m.addSeparator()
        m.addAction(tr("Cerrar la ventana"), self.quit_ui)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_normal() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    def _before_retheme(self):
        """Foto de la ventana antes de cambiar el tema: luego se desvanece encima (fundido entre temas)."""
        if not anim.enabled() or not self.isVisible():
            return
        shot = QLabel(self)
        shot.setPixmap(self.grab())
        shot.setGeometry(self.rect())
        shot.setAttribute(Qt.WA_TransparentForMouseEvents)
        shot.show()
        shot.raise_()
        self._theme_shot = shot

    def _retheme(self):
        for row in self.list.rows.values():
            row.update()
        self.b_theme.setText({"system": IC["desktop"], "light": IC["sun"], "dark": IC["moon"]}[self.theme.mode])
        self._after_icons()
        if self.st:
            self.on_state(self.st)
        self.on_connection(self.client.connected)
        shot = getattr(self, "_theme_shot", None)
        if shot is not None:
            self._theme_shot = None
            eff = QGraphicsOpacityEffect(shot)
            shot.setGraphicsEffect(eff)
            anim.tween(shot, 1.0, 0.0, 320, lambda v: eff.setOpacity(float(v)), on_done=shot.deleteLater)

    # ------------------------------------------------------------------ estado
    def on_connection(self, ok):
        c = self.theme.c
        running = bool(self.st.get("running_job")) if ok else False
        self.dot.set_state(c["ok"] if ok else c["warn"], pulsing=running)
        if ok:
            lim = self.st.get("limit")
            if running and lim:
                self.conn.setText(tr("Renderizando · limitado al {n} %", n=lim["percent"]))
                self.conn.setToolTip(tr("Blender usa {n} de {total} hilos del procesador, con prioridad baja "
                                        "(Ajustes → Rendimiento del PC).", n=lim["threads"], total=lim["total"]))
            else:
                self.conn.setText(tr("Renderizando") if running else tr("Motor activo"))
                self.conn.setToolTip("")
        else:
            self.conn.setText(tr("Conectando con el motor…"))

    def _row_factory(self, jid):
        row = JobRow(jid, self.theme)
        row.clicked.connect(self.open_popup)
        row.toggledEnabled.connect(lambda j, on: self.client.send("enable", id=j, enabled=on))
        row.contextRequested.connect(self.row_menu)
        row.removeRequested.connect(lambda j: self.on_popup_action("remove", j, {}))
        return row

    def max_attempts(self) -> int:
        return int((self.st.get("settings") or {}).get("max_attempts", 3))

    def job(self, jid):
        return next((j for j in self.st.get("jobs", []) if j["id"] == jid), None)

    def on_state(self, st: dict):
        self.st = st
        if not self._upd_checked:
            self._upd_checked = True
            QTimer.singleShot(1500, self.check_updates)
            # el motor escribe avisos y errores en el idioma de la ventana
            pref = prefs().value("language", "auto")
            if (st.get("settings") or {}).get("language", "auto") != pref:
                self.client.send("settings", values={"language": pref})
        t = st.get("totals", {})
        if not (self.isVisible() and not self.isMinimized()):
            # Ventana minimizada o en la bandeja: solo lo imprescindible (avisos, cuenta atrás, tooltip).
            # La lista se pone al día al volver a mostrarla (_visibility_changed).
            self._stale = True
            self._countdown(st)
            self.tray.setToolTip(self._tray_text(t))
            self._handle_events(st)
            return
        self._stale = False
        busy_now = bool(st.get("queue", {}).get("running") or st.get("running_job"))
        self.b_upd_now.setEnabled(not busy_now)
        self.b_upd_now.setToolTip(tr("Disponible cuando termine o pauses la cola.") if busy_now else "")
        c = self.theme.c
        self.m_frames.set_number(int(t.get("frames_done", 0)), "/ " + fmt_int(t.get("frames_total", 0)), c["muted"])
        self.m_jobs.set_number(int(t.get("jobs_done", 0)), f"/ {t.get('jobs_total', 0)}", c["muted"])
        self.m_eta.set(util.fmt_duration(t.get("eta")) if t.get("eta") else "—")
        jobs = st.get("jobs", [])
        self.list.sync(jobs, self._row_factory, self.max_attempts())
        self.scroll.setVisible(bool(jobs))
        self.empty.setVisible(not jobs)
        running_id = st.get("running_job")
        for jid, row in self.list.rows.items():
            row.set_selected(self.popup.isVisible() and self.popup.job_id == jid)
        rj = self.job(running_id) if running_id else None
        if rj:
            self.last_line.setText(f"{rj['name']}  ·  " + (rj.get("last_line") or tr("iniciando Blender…")))
        elif st.get("queue", {}).get("running"):
            self.last_line.setText(tr("Esperando a que terminen de leerse los archivos…"))
        else:
            self.last_line.setText(tr("Listo.") if jobs else tr("Agrega archivos para empezar."))
        running = st.get("queue", {}).get("running") or bool(running_id)
        self.b_run.setText(IC["pause"] + "  " + tr("Pausar") if running else IC["play"] + "  " + tr("Iniciar render"))
        self.tray_run.setText(tr("Pausar") if running else tr("Iniciar render"))
        after = st.get("queue", {}).get("after", "none")
        idx = self.after.findData(after)
        if idx >= 0 and idx != self.after.currentIndex():
            self.after.blockSignals(True)
            self.after.setCurrentIndex(idx)
            self.after.blockSignals(False)
            self._after_look()
        if self.popup.isVisible() and self.popup.job_id:
            j = self.job(self.popup.job_id)
            if j:
                self.popup.update_job(j, self.max_attempts(), j["id"] == running_id)
            else:
                self.popup.close()
        self._countdown(st)
        self.tray.setToolTip(self._tray_text(t))
        self._handle_events(st)
        self.on_connection(True)  # punto del motor: late solo mientras renderiza

    @staticmethod
    def _tray_text(t: dict) -> str:
        return "Frameguard · " + tr("{done}/{total} shots · {frames} frames", done=t.get("jobs_done", 0),
                                     total=t.get("jobs_total", 0), frames=t.get("frames_done", 0))

    def _countdown(self, st):
        cd = st.get("countdown")
        if cd:
            self.countdown.set_countdown(cd["action"], cd["seconds"], cd.get("total"))
            if not self.countdown.isVisible():
                self.show_normal()
                self.countdown.show()
        elif self.countdown.isVisible():
            self.countdown.hide()

    def _handle_events(self, st):
        """Muestra los avisos nuevos del motor (tarjeta + sonido). Al abrir la ventana no repite los viejos;
        si el motor se reinició, muestra solo los de los últimos segundos."""
        events = st.get("events") or []
        pid = st.get("pid")
        if self._ev_pid is None:
            self._ev_pid, self._ev_seen = pid, max((e["id"] for e in events), default=0)
            return
        if pid != self._ev_pid:
            now = st.get("now", 0)
            self._ev_pid = pid
            self._ev_seen = max((e["id"] for e in events if now - e["t"] > 10), default=0)
        for e in events:
            if e["id"] > self._ev_seen:
                self._ev_seen = e["id"]
                self.notify(e["kind"], e["title"], e["text"])

    def notify(self, kind: str, title: str, text: str):
        self.toasts.show(kind, title, text)
        if (self.st.get("settings") or {}).get("notify_sound", True):
            sounds.play(kind)

    # ------------------------------------------------------------------ acciones
    def toggle_run(self):
        q = self.st.get("queue", {})
        if q.get("running") or self.st.get("running_job"):
            self.client.send("pause")
            return
        pending = [j for j in self.st.get("jobs", []) if j.get("enabled", True) and j["status"] in ("ready", "paused", "reading")]
        if not pending:
            QMessageBox.information(self, "Frameguard", tr("No hay shots activos pendientes en la cola."))
            return
        self.client.send("start")

    # ------------------------------------------------------------------ últimas carpetas usadas
    def _last_dir(self, key: str) -> str:
        d = prefs().value(key, "")
        return d if d and os.path.isdir(d) else ""

    def _remember_dir(self, key: str, path: str):
        d = path if os.path.isdir(path) else os.path.dirname(path)
        prefs().setValue(key, os.path.normpath(d))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Agregar archivos .blend"), self._last_dir("last_blend_dir"),
                                                "Blender (*.blend)")
        if files:
            self._remember_dir("last_blend_dir", files[0])
            self.add_paths(files)

    def add_folder(self):
        """Elegir una o varias carpetas (Ctrl o Shift para marcar varias) y buscar los .blend de dentro."""
        start = self._last_dir("last_folder_dir") or self._last_dir("last_blend_dir")
        folders = pick_folders(int(self.winId()), tr("Agregar carpetas (Ctrl o Shift para elegir varias)"), start,
                               ok_label=tr("Agregar"))
        if folders is None:  # sin el selector de Windows: el de Qt, de una carpeta
            one = QFileDialog.getExistingDirectory(self, tr("Agregar carpeta"), start)
            folders = [one] if one else []
        if folders:
            # se recuerda la carpeta que las contiene: la próxima vez se abre ahí para elegir sus hermanas
            self._remember_dir("last_folder_dir", os.path.dirname(os.path.normpath(folders[0])) or folders[0])
            self.add_paths(folders)

    # ------------------------------------------------------------------ colas guardadas (.fgq)
    def _settings(self):
        return prefs()

    def current_queue(self) -> str:
        return self._settings().value("current_queue", "") or ""

    def _set_current_queue(self, path: str):
        self._settings().setValue("current_queue", path)
        if path:
            rec = [p for p in (self._settings().value("recent_queues", []) or []) if p != path]
            self._settings().setValue("recent_queues", [path] + rec[:7])
        self._update_queue_label()

    def _update_queue_label(self):
        cur = self.current_queue()
        self.queue_label.setText(f"·  {os.path.splitext(os.path.basename(cur))[0]}" if cur else "·  " + tr("Cola sin guardar"))
        self.queue_label.setToolTip(cur)

    def clear_finished(self):
        n = sum(1 for j in self.st.get("jobs", []) if j["status"] == "done")
        if not n:
            QMessageBox.information(self, "Frameguard", tr("No hay shots terminados en la lista."))
            return
        self.client.send("clear_finished")

    def open_logs_folder(self):
        os.startfile(str(paths.logs_dir()))

    def _busy(self) -> bool:
        return bool(self.st.get("queue", {}).get("running") or self.st.get("running_job"))

    def new_queue(self):
        self.clear_queue()

    def clear_queue(self):
        """Vacía la cola (no borra archivos ni la cola guardada en .fgq). Si está renderizando, ofrece
        quitar todos los shots menos el que se está renderizando."""
        jobs = self.st.get("jobs") or []
        if not jobs:
            QMessageBox.information(self, "Frameguard", tr("La cola ya está vacía."))
            return
        running_id = self.st.get("running_job")
        if self._busy():
            cur = self.job(running_id)
            others = len(jobs) - (1 if cur else 0)
            if not others:
                QMessageBox.information(self, "Frameguard", tr("Solo queda el shot que se está renderizando. "
                                                              "Pausa la cola si también quieres quitarlo."))
                return
            msg = (tr("La cola está renderizando «{name}».\n\n¿Quitar los otros {n} shots? "
                      "El que se está renderizando sigue.", name=cur["name"], n=others) if cur else
                   tr("¿Quitar los {n} shots de la cola?", n=others))
            if QMessageBox.question(self, tr("Vaciar cola"), msg) != QMessageBox.Yes:
                return
            self.client.send("clear", keep_current=True, callback=self._cmd_error)
        else:
            if QMessageBox.question(self, tr("Vaciar cola"), tr("¿Quitar los {n} shots de la cola?", n=len(jobs))
                                    + "\n\n" + tr("No se borra ningún archivo, y la cola guardada (si la hay) no "
                                                  "cambia.")) != QMessageBox.Yes:
                return
            self.client.send("clear", callback=self._cmd_error)
        self.popup.close()
        self._set_current_queue("")

    def save_queue(self, ask: bool = False):
        jobs = self.st.get("jobs") or []
        if not jobs:
            QMessageBox.information(self, "Frameguard", tr("La cola está vacía: no hay nada que guardar."))
            return
        path = self.current_queue()
        if ask or not path:
            start = path or os.path.join(self._last_dir("last_queue_dir") or self._last_dir("last_blend_dir"),
                                         tr("cola") + ".fgq")
            path, _ = QFileDialog.getSaveFileName(self, tr("Guardar cola"), start, tr("Cola de Frameguard") + " (*.fgq)")
            if not path:
                return
            if not path.lower().endswith(".fgq"):
                path += ".fgq"
        data = {"frameguard_queue": 1, "app_version": __version__, "saved_at": time.strftime("%Y-%m-%d %H:%M"),
                "jobs": [{"path": j["path"], "name": j["name"], "enabled": j.get("enabled", True),
                          "range": j.get("range"), "mode": j.get("mode", "full"), "scene": j.get("scene")}
                         for j in jobs]}
        try:
            util.atomic_write_json(Path(path), data)
        except OSError as e:
            QMessageBox.warning(self, "Frameguard", tr("No se pudo guardar la cola:") + f"\n{e}")
            return
        self._remember_dir("last_queue_dir", path)
        self._set_current_queue(os.path.normpath(path))
        self.tray.showMessage(tr("Cola guardada"), tr("{n} shots en {file}", n=len(jobs), file=os.path.basename(path)),
                              QSystemTrayIcon.Information, 3000)

    def open_queue_dialog(self):
        start = self._last_dir("last_queue_dir") or self._last_dir("last_blend_dir")
        path, _ = QFileDialog.getOpenFileName(self, tr("Abrir cola"), start, tr("Cola de Frameguard") + " (*.fgq)")
        if path:
            self.open_queue_file(path)

    def open_queue_file(self, path: str):
        data = util.read_json(Path(path))
        if not isinstance(data, dict) or "jobs" not in data:
            QMessageBox.warning(self, "Frameguard", tr("No es una cola de Frameguard válida:") + f"\n{path}")
            return
        replace = False
        if self.st.get("jobs"):
            box = QMessageBox(self)
            box.setWindowTitle(tr("Abrir cola"))
            box.setText(tr("La cola actual tiene {n} shots. ¿Qué hago con «{file}»?", n=len(self.st["jobs"]),
                            file=os.path.basename(path)))
            b_rep = box.addButton(tr("Reemplazar la cola"), QMessageBox.AcceptRole)
            b_add = box.addButton(tr("Añadir al final"), QMessageBox.AcceptRole)
            box.addButton(tr("Cancelar"), QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() not in (b_rep, b_add):
                return
            replace = box.clickedButton() is b_rep
            if replace and self._busy():
                QMessageBox.information(self, "Frameguard", tr("Pausa la cola antes de reemplazarla."))
                return
        self._remember_dir("last_queue_dir", path)

        def done(res):
            if not res.get("ok", True):
                QMessageBox.warning(self, "Frameguard", res.get("error") or tr("No se pudo abrir la cola."))
                return
            if replace or not self.st.get("jobs"):
                self._set_current_queue(os.path.normpath(path))
            if res.get("missing"):
                QMessageBox.warning(self, "Frameguard", tr("Estos archivos ya no existen y no se cargaron:") + "\n\n"
                                    + "\n".join(res["missing"]))

        self.client.send("load_queue", items=data["jobs"], replace=replace, callback=done)

    def add_paths(self, paths: list[str]):
        """.blend sueltos: directo a la cola. Carpetas: se buscan sus .blend y se elige cuáles agregar.
        Colas .fgq: se abren."""
        files, queues, folders = classify_paths(paths)
        if queues:
            self.open_queue_file(queues[0])
        if files:
            self.client.send("add", paths=files, callback=self._after_add)
        if folders:
            self.scan_folders(folders)

    def _after_add(self, res):
        if res.get("skipped"):
            QMessageBox.information(self, "Frameguard", tr("Estos archivos ya estaban en la cola:") + "\n\n"
                                    + "\n".join(res["skipped"]))

    def scan_folders(self, folders: list[str]):
        """Busca los .blend de varias carpetas en un hilo aparte (por la red puede tardar) y luego muestra la
        lista para elegir. Si eliges una carpeta y otra de dentro, cada archivo aparece una sola vez."""
        n = len(folders)
        self.last_line.setText(tr("Buscando archivos .blend en {folder}…", folder=folders[0]) if n == 1 else
                               tr("Buscando archivos .blend en {n} carpetas…", n=n))
        QApplication.setOverrideCursor(Qt.BusyCursor)

        def work():
            items, empty, seen = [], [], set()
            for f in folders:
                try:
                    found = scan.scan_folder(f)
                except OSError:
                    found = []
                new = [dict(it, root=f) for it in found if os.path.normcase(it["path"]) not in seen]
                seen.update(os.path.normcase(it["path"]) for it in new)
                if new:
                    items.extend(new)
                elif not found:
                    empty.append(f)
            self._scan.done.emit((folders, items, empty))

        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, payload):
        folders, items, empty = payload
        QApplication.restoreOverrideCursor()
        if self.st:
            self.on_state(self.st)  # devuelve la última línea a su texto normal
        if not items:
            QMessageBox.information(self, "Frameguard", tr("No se encontraron archivos .blend en:") + "\n\n"
                                    + "\n".join(folders))
            return
        queued = {os.path.normcase(j["path"]) for j in self.st.get("jobs", []) if j["status"] not in ("done", "failed")}
        dlg = ScanDialog(folders, items, queued, empty, self)
        if dlg.exec():
            sel = dlg.selected()
            if sel:
                self.client.send("add", paths=sel, callback=self._after_add)

    def open_popup(self, jid):
        j = self.job(jid)
        if not j:
            return
        if self.popup.isVisible() and self.popup.job_id == jid:
            self.popup.close()
            return
        row = self.list.rows[jid]
        anchor = row.mapToGlobal(QPoint(40, row.height() + 4))
        self.popup.show_job(j, self.max_attempts(), anchor, jid == self.st.get("running_job"))
        for k, r in self.list.rows.items():
            r.set_selected(k == jid)

    def row_menu(self, jid, pos):
        j = self.job(jid)
        if not j:
            return
        running = jid == self.st.get("running_job")
        m = QMenu(self)
        m.addAction(tr("Ver detalles"), lambda: self.open_popup(jid))
        m.addAction(tr("Ver log"), lambda: self.on_popup_action("log", jid, {})).setEnabled(bool(j.get("logs")))
        m.addSeparator()
        m.addAction(tr("Reintentar"), lambda: self.on_popup_action("retry", jid, {}))
        m.addAction(tr("Re-render completo"), lambda: self.on_popup_action("rerender", jid, {})).setEnabled(not running)
        m.addAction(tr("Renderizar todo") if j.get("mode") == "missing" else tr("Solo frames faltantes"),
                    lambda: self.on_popup_action("toggle_mode", jid, {}))
        m.addSeparator()
        n = len(self.st.get("jobs", []))
        m.addAction(tr("Mover al inicio"), lambda: self.client.send("move", id=jid, index=0))
        m.addAction(tr("Mover al final"), lambda: self.client.send("move", id=jid, index=n))
        m.addSeparator()
        m.addAction(tr("Abrir carpeta del .blend"), lambda: os.startfile(os.path.dirname(j["path"])))
        m.addAction(tr("Abrir salida"), lambda: self.on_popup_action("open_output", jid, {}))
        m.addSeparator()
        m.addAction(tr("Quitar de la cola"), lambda: self.on_popup_action("remove", jid, {})).setEnabled(not running)
        m.exec(pos)

    def on_popup_action(self, action, jid, data):
        j = self.job(jid)
        if not j:
            return
        if action == "log":
            LogDialog(self.client, j, self).show()
        elif action == "open_output":
            outs = (j.get("runtime_outputs") or (j.get("info") or {}).get("outputs") or [])
            dirs = [o["directory"] for o in outs if o.get("directory")]
            target = next((d for d in dirs if os.path.isdir(d)), None) or \
                next((os.path.dirname(d) for d in dirs if os.path.isdir(os.path.dirname(d))), None)
            if target:
                os.startfile(target)
            else:
                QMessageBox.information(self, "Frameguard", tr("La carpeta de salida todavía no existe."))
        elif action == "retry":
            self.client.send("reinspect" if j["status"] == "error_read" else "retry", id=jid)
        elif action == "rerender":
            if QMessageBox.question(self, tr("Re-render completo"),
                                    tr("Se volverán a renderizar TODOS los frames de {name} y se sobrescribirán "
                                       "los archivos existentes.\n\n¿Continuar?", name=j["name"])) == QMessageBox.Yes:
                self.client.send("rerender", id=jid)
        elif action == "toggle_mode":
            self.client.send("set_mode", id=jid, mode="full" if j.get("mode") == "missing" else "missing")
        elif action == "remove":
            if QMessageBox.question(self, tr("Quitar de la cola"), tr("¿Quitar {name} de la cola?\n\n"
                                    "No se borra ningún archivo.", name=j["name"])) == QMessageBox.Yes:
                self.popup.close()
                self.client.send("remove", id=jid, callback=self._cmd_error)
        elif action == "set_range":
            self.client.send("set_range", id=jid, **data, callback=self._cmd_error)

    def _cmd_error(self, res):
        if not res.get("ok", True) and res.get("error"):
            QMessageBox.warning(self, "Frameguard", res["error"])

    def reinspect_all(self):
        for j in self.st.get("jobs", []):
            if j["id"] != self.st.get("running_job") and j["status"] not in ("done",):
                self.client.send("reinspect", id=j["id"])

    def open_settings(self):
        dlg = SettingsDialog(self.st.get("settings") or {}, self.st.get("blenders") or [], self.theme.mode, self)
        dlg.testNotify.connect(lambda kind, title, text: (self.toasts.show(kind, title, text), sounds.play(kind)))
        dlg.showNotes.connect(lambda: WhatsNewDialog(self.theme, changelog.CHANGELOG, mode="history", parent=dlg).exec())
        if dlg.exec():
            values = dlg.values()
            self.client.send("settings", values=values)
            anim.set_enabled(dlg.anims.isChecked())
            self.theme.set_mode(dlg.theme.currentData())
            QTimer.singleShot(1200, lambda: self.check_updates(True))
            if values["language"] != prefs().value("language", "auto"):
                prefs().setValue("language", values["language"])
                if i18n.resolve(values["language"]) != i18n.lang():  # cambia de verdad: hay que reabrir la ventana
                    self._ask_restart(i18n.resolve(values["language"]))

    def _ask_restart(self, new_lang: str):
        """El idioma se aplica al reabrir la ventana. El mensaje va en el idioma NUEVO (quien lo eligió lo entiende)."""
        es = new_lang == "es"
        box = QMessageBox(self)
        box.setWindowTitle("Frameguard")
        box.setText("Frameguard se mostrará en español al reabrir la ventana. El render no se detiene."
                    if es else "Frameguard will switch to English when the window reopens. Rendering is not interrupted.")
        b_now = box.addButton("Reabrir ahora" if es else "Reopen now", QMessageBox.AcceptRole)
        box.addButton("Más tarde" if es else "Later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_now and callable(getattr(self, "restart_ui", None)):
            self.restart_ui()

    def open_preflight(self):
        dlg = PreflightDialog(self.st.get("jobs", []), self)
        dlg.reinspectAll.connect(self.reinspect_all)
        dlg.exec()

    def open_report(self):
        rep = self.st.get("last_report")
        if rep and os.path.isfile(rep):
            os.startfile(rep)
        else:
            QMessageBox.information(self, "Frameguard", tr("Todavía no hay informe: se genera al terminar la cola."))

    # ------------------------------------------------------------------ actualizaciones
    def check_updates(self, manual: bool = False):
        folder = (self.st.get("settings") or {}).get("update_folder", "")
        if not folder:
            return
        threading.Thread(target=lambda: self._upd.found.emit((updater.newest(folder), manual)), daemon=True).start()

    def _on_update_found(self, payload):
        item, manual = payload
        skipped = prefs().value("skip_version", "")
        if item and (manual or item["label"] != skipped):
            self.update_item = item
            notes = item["notes"].splitlines()[0] if item["notes"] else ""
            self.banner_text.setText(tr("<b>Hay una versión nueva de Frameguard: {new}</b> (tienes la {current}).",
                                        new=item["label"], current=__version__) + ("  " + notes if notes else ""))
            self.banner_text.setToolTip(item["notes"])
            self.banner.show()

    def skip_update(self):
        if self.update_item:
            prefs().setValue("skip_version", self.update_item["label"])
        self.banner.hide()

    def install_update(self, item):
        if not item:
            return
        if self.st.get("queue", {}).get("running") or self.st.get("running_job"):
            QMessageBox.information(self, "Frameguard", tr("La cola está renderizando. Pausa la cola o espera a que "
                                    "termine para actualizar: nunca se actualiza a mitad de un render."))
            return
        if QMessageBox.question(self, tr("Instalar versión"), tr(
                "Se instalará Frameguard {new} encima de la versión actual ({current}). Tu cola, ajustes y logs se "
                "conservan.\n\nFrameguard se cerrará y volverá a abrirse solo. ¿Continuar?",
                new=item["label"], current=__version__)) != QMessageBox.Yes:
            return
        self.client.send("quit")
        try:
            updater.launch_installer(item)
        except OSError as e:
            QMessageBox.warning(self, "Frameguard", tr("No se pudo lanzar el instalador:") + f"\n{e}")
            return
        QTimer.singleShot(600, self.quit_ui_now)

    def quit_ui_now(self):
        self.tray.hide()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    # ------------------------------------------------------------------ ventana / bandeja
    def show_normal(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def closeEvent(self, e):
        busy = self.st.get("queue", {}).get("running") or self.st.get("running_job")
        if busy and QSystemTrayIcon.isSystemTrayAvailable():
            e.ignore()
            self.hide()
            if not self.tray_hint_shown:
                self.tray.showMessage(tr("Frameguard sigue renderizando"),
                                      tr("La cola continúa en segundo plano. Ábrelo desde el icono de la bandeja."),
                                      QSystemTrayIcon.Information, 6000)
                self.tray_hint_shown = True
            return
        self.tray.hide()
        e.accept()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def quit_ui(self):
        busy = self.st.get("queue", {}).get("running") or self.st.get("running_job")
        if busy:
            QMessageBox.information(self, "Frameguard", tr("La ventana se cierra, pero la cola sigue renderizando en "
                                    "segundo plano. Al abrir Frameguard otra vez verás el progreso."))
        self.tray.hide()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()
