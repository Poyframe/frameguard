"""Diálogos: carpetas escaneadas, ajustes, log, chequeo previo y cuenta atrás de apagado."""
import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPalette, QTextCursor
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import __version__, paths, updater
from ..i18n import plural, tr
from .prefs import prefs
from .theme import IC

def _actions() -> dict:
    """acción -> (texto de la cuenta atrás, botón «ya», glifo, color del tema)."""
    return {"shutdown": (tr("El equipo se apagará en"), tr("Apagar ahora"), IC["shutdown"], "err"),
            "restart": (tr("El equipo se reiniciará en"), tr("Reiniciar ahora"), IC["restart"], "warn"),
            "sleep": (tr("El equipo se suspenderá en"), tr("Suspender ahora"), IC["sleep"], "accent")}


def _section(glyph: str, title: str) -> tuple[QFrame, QVBoxLayout]:
    """Recuadro con icono y título en mayúsculas (mismo estilo que el panel de detalles del shot)."""
    box = QFrame()
    box.setObjectName("Section")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(9)
    head = QHBoxLayout()
    head.setSpacing(8)
    ic = QLabel(glyph)
    ic.setObjectName("SectionIcon")
    t = QLabel(title)
    t.setObjectName("SectionTitle")
    head.addWidget(ic)
    head.addWidget(t)
    head.addStretch()
    lay.addLayout(head)
    return box, lay


def _form() -> QFormLayout:
    f = QFormLayout()
    f.setHorizontalSpacing(14)
    f.setVerticalSpacing(8)
    f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    f.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
    return f


def _hint(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("Hint")
    lab.setWordWrap(True)
    return lab


def _row(*widgets, stretch_first=True) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for i, x in enumerate(widgets):
        lay.addWidget(x, 1 if (i == 0 and stretch_first) else 0)
    if not stretch_first:
        lay.addStretch()
    return w


class ScanDialog(QDialog):
    """.blend encontrados en una o varias carpetas: el usuario marca cuáles agregar.
    Con varias carpetas, se agrupan por carpeta (marcar la carpeta marca todo lo de dentro)."""

    def __init__(self, folders: list[str], items: list[dict], queued: set[str] | None = None,
                 empty: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Agregar desde carpetas"))
        self.resize(820, 560)
        queued = queued or set()
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        n_queued = sum(1 for it in items if os.path.normcase(it["path"]) in queued)
        where = f"<b>{folders[0]}</b>" if len(folders) == 1 else "<b>" + tr("{n} carpetas", n=len(folders)) + "</b>"
        text = tr("Se encontraron <b>{n}</b> archivos en {where}. De cada uno se eligió la versión más alta "
                  "(por el nombre, p. ej. _V03).", n=len(items), where=where)
        if n_queued:
            text += " " + plural(n_queued, "{n} ya está en la cola y no se volverá a agregar.",
                                 "{n} ya están en la cola y no se volverán a agregar.")
        lab = QLabel(text)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        if empty:
            e = _hint(tr("Sin archivos .blend:") + " " + ", ".join(os.path.basename(f) or f for f in empty))
            e.setToolTip("\n".join(empty))
            lay.addWidget(e)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Archivo"), tr("Versión"), tr("Modificado"), tr("Versiones anteriores")])
        self.tree.setColumnWidth(0, 360)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 130)
        grouped = len(folders) > 1
        self.tree.setRootIsDecorated(grouped)
        groups = {}
        if grouped:
            for f in folders:
                g = QTreeWidgetItem([os.path.basename(f.rstrip("\\/")) or f])
                g.setToolTip(0, f)
                f0 = g.font(0)
                f0.setBold(True)
                g.setFont(0, f0)
                groups[f] = g
        for it in items:
            already = os.path.normcase(it["path"]) in queued
            name = it["name"] + ("   · " + tr("ya en la cola") if already else "")
            row = QTreeWidgetItem([name, f"V{it['version']:02d}" if it["version"] is not None else "—",
                                   time.strftime("%d/%m/%Y %H:%M", time.localtime(it["mtime"])),
                                   ", ".join(it.get("older", [])) or "—"])
            row.setToolTip(0, it["path"])
            row.setData(0, Qt.UserRole, it["path"])
            if already:
                row.setFlags(row.flags() & ~Qt.ItemIsUserCheckable & ~Qt.ItemIsEnabled)
                muted = QApplication.palette().color(QPalette.PlaceholderText)  # color atenuado del tema
                for col in range(4):
                    row.setForeground(col, muted)
            else:
                row.setCheckState(0, Qt.Checked)
            parent_item = groups.get(it.get("root"))
            if parent_item is not None:
                parent_item.addChild(row)
            else:
                self.tree.addTopLevelItem(row)
        self._syncing = False
        for f, g in groups.items():
            if g.childCount():
                self.tree.addTopLevelItem(g)
                g.setText(0, f"{g.text(0)}   ({g.childCount()})")
                g.setExpanded(True)
                self._sync_group(g)
        self.tree.itemChanged.connect(self._item_changed)
        lay.addWidget(self.tree, 1)
        bar = QHBoxLayout()
        b_all, b_none = QPushButton(tr("Marcar todos")), QPushButton(tr("Desmarcar todos"))
        b_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        b_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        bar.addWidget(b_all)
        bar.addWidget(b_none)
        bar.addStretch()
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton()
        self.ok.setObjectName("Primary")
        self.ok.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(self.ok)
        lay.addLayout(bar)
        self._update_count()

    def _files(self):
        """Todas las filas de archivo (dentro de grupos o sueltas)."""
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.childCount():
                for k in range(top.childCount()):
                    yield top.child(k)
            elif top.data(0, Qt.UserRole):
                yield top

    @staticmethod
    def _checkable(item) -> bool:
        return bool(item.flags() & Qt.ItemIsUserCheckable)

    def _sync_group(self, g):
        """Casilla de la carpeta según sus archivos (los que ya están en la cola no cuentan)."""
        kids = [g.child(k) for k in range(g.childCount()) if self._checkable(g.child(k))]
        self._syncing = True
        if not kids:
            g.setFlags(g.flags() & ~Qt.ItemIsUserCheckable)
        else:
            g.setFlags(g.flags() | Qt.ItemIsUserCheckable)
            n = sum(k.checkState(0) == Qt.Checked for k in kids)
            g.setCheckState(0, Qt.Checked if n == len(kids) else Qt.Unchecked if n == 0 else Qt.PartiallyChecked)
        self._syncing = False

    def _item_changed(self, item, _col):
        if self._syncing:
            return
        if item.childCount():  # carpeta: marca o desmarca todos sus archivos
            state = Qt.Unchecked if item.checkState(0) == Qt.Unchecked else Qt.Checked
            self._syncing = True
            for k in range(item.childCount()):
                if self._checkable(item.child(k)):
                    item.child(k).setCheckState(0, state)
            self._syncing = False
            self._sync_group(item)
        elif item.parent() is not None:
            self._sync_group(item.parent())
        self._update_count()

    def _set_all(self, state):
        for it in self._files():
            if self._checkable(it):
                it.setCheckState(0, state)

    def _update_count(self):
        n = len(self.selected())
        self.ok.setText(tr("Agregar {n} a la cola", n=n) if n else tr("Agregar a la cola"))
        self.ok.setEnabled(n > 0)

    def selected(self) -> list[str]:
        return [it.data(0, Qt.UserRole) for it in self._files()
                if it.flags() & Qt.ItemIsUserCheckable and it.checkState(0) == Qt.Checked]


class SettingsDialog(QDialog):
    """Ajustes por secciones: a la izquierda lo del render, a la derecha avisos, apariencia y actualizaciones."""
    testNotify = Signal(str, str, str)
    showNotes = Signal()

    def __init__(self, settings: dict, blenders: list[dict], theme_mode: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Ajustes"))
        self.setMinimumSize(760, 480)
        screen = (parent.screen() if parent is not None else None)
        avail = screen.availableGeometry().height() if screen is not None else 900
        self.resize(980, min(700, avail - 60))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel(tr("Ajustes"))
        title.setObjectName("Title")
        info = QLabel(f"Frameguard {__version__}")
        info.setObjectName("Muted")
        head.addWidget(title)
        head.addSpacing(10)
        head.addWidget(info, 1)
        outer.addLayout(head)

        body = QWidget()
        cols = QHBoxLayout(body)
        cols.setContentsMargins(0, 0, 4, 0)
        cols.setSpacing(12)
        # dos columnas de igual ancho (Ignored: el ancho lo reparte el layout, no el contenido más largo)
        col_l, col_r = QWidget(), QWidget()
        left, right = QVBoxLayout(col_l), QVBoxLayout(col_r)
        for w, lay_ in ((col_l, left), (col_r, right)):
            w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lay_.setContentsMargins(0, 0, 0, 0)
            lay_.setSpacing(12)
            cols.addWidget(w, 1)

        # --- BLENDER
        box, lay = _section(IC["app"], tr("BLENDER"))
        self.blender = QComboBox()
        self.blender.addItem(tr("Automático (la versión más nueva instalada)"), "")
        for b in blenders:
            self.blender.addItem(f"{b['label']}  —  {b['path']}", b["path"])
        cur = settings.get("blender_path", "")
        if cur and self.blender.findData(cur) < 0:
            self.blender.addItem(cur, cur)
        self.blender.setCurrentIndex(max(0, self.blender.findData(cur)))
        b_browse = QPushButton(tr("Buscar…"))
        b_browse.clicked.connect(self._browse)
        lay.addWidget(_row(self.blender, b_browse))
        lay.addWidget(_hint(tr("Se usa para todos los shots de la cola.")))
        left.addWidget(box)

        # --- RENDER Y FIABILIDAD
        box, lay = _section(IC["shield"], tr("RENDER Y FIABILIDAD"))
        form = _form()
        self.attempts = QSpinBox()
        self.attempts.setRange(1, 10)
        self.attempts.setValue(int(settings.get("max_attempts", 3)))
        self.attempts.setToolTip(tr("Si Blender se cae, se reintenta solo con los frames que faltan."))
        form.addRow(tr("Intentos por shot"), self.attempts)
        self.stall = QDoubleSpinBox()
        self.stall.setRange(1, 600)
        self.stall.setDecimals(0)
        self.stall.setSuffix(" min")
        self.stall.setValue(float(settings.get("stall_minutes", 15)))
        self.stall.setToolTip(tr("Si Blender no da señales de vida durante este tiempo, se reinicia el shot."))
        form.addRow(tr("Reiniciar Blender si no responde en"), self.stall)
        self.grace = QSpinBox()
        self.grace.setRange(10, 900)
        self.grace.setSuffix(" s")
        self.grace.setValue(int(settings.get("exit_grace_seconds", 60)))
        self.grace.setToolTip(tr("Cuando todos los frames están en disco y Blender no se cierra solo, se cierra a la "
                                 "fuerza tras este tiempo."))
        form.addRow(tr("Esperar a que Blender cierre"), self.grace)
        lay.addLayout(form)
        self.save_out = QCheckBox(tr("Apagar Save Output durante el render si hay nodos File Output"))
        self.save_out.setChecked(bool(settings.get("disable_save_output", True)))
        self.save_out.setToolTip(tr("No modifica el .blend: solo afecta a la sesión de render."))
        lay.addWidget(self.save_out)
        left.addWidget(box)

        # --- RENDIMIENTO DEL PC
        box, lay = _section(IC["chip"], tr("RENDIMIENTO DEL PC"))
        self.limit = QCheckBox(tr("Limitar los recursos que usa el render"))
        self.limit.setChecked(bool(settings.get("limit_resources", False)))
        lay.addWidget(self.limit)
        self.limit_pct = QComboBox()
        for pct in (25, 50, 75):
            self.limit_pct.addItem(tr("{n} % del procesador", n=pct), pct)
        self.limit_pct.setCurrentIndex(max(0, self.limit_pct.findData(int(settings.get("limit_percent", 50)))))
        self.limit_threads = QLabel()
        self.limit_threads.setObjectName("Muted")
        form = _form()
        form.addRow(tr("Usar como máximo"), _row(self.limit_pct, self.limit_threads, stretch_first=False))
        lay.addLayout(form)
        lay.addWidget(_hint(tr("Blender usa solo esa parte del procesador y con prioridad baja, para que puedas "
                               "seguir trabajando en el PC mientras renderiza; el render tarda más. Se aplica al "
                               "momento, también al shot que se está renderizando.\nNo limita la tarjeta gráfica "
                               "(EEVEE o Cycles con GPU) ni la memoria RAM: limitarlas haría que Blender se "
                               "cerrara.")))
        self.limit.toggled.connect(self._update_limit)
        self.limit_pct.currentIndexChanged.connect(self._update_limit)
        self._update_limit()
        left.addWidget(box)

        left.addStretch()

        # --- AL TERMINAR LA COLA
        box, lay = _section(IC["shutdown"], tr("AL TERMINAR LA COLA"))
        self.countdown = QSpinBox()
        self.countdown.setRange(1, 60)
        self.countdown.setSuffix(" min")
        self.countdown.setValue(max(1, round(float(settings.get("countdown_seconds", 600)) / 60)))
        form = _form()
        form.addRow(tr("Tiempo de espera"), _row(self.countdown, stretch_first=False))
        lay.addLayout(form)
        lay.addWidget(_hint(tr("Antes de apagar, suspender o reiniciar (se elige abajo, en «Al terminar la cola»). "
                               "Durante la espera aparece una cuenta atrás para cancelarlo o hacerlo ya.")))
        right.addWidget(box)

        # --- NOTIFICACIONES
        box, lay = _section(IC["bell"], tr("NOTIFICACIONES"))
        self.n_shot = QCheckBox(tr("Al terminar cada shot"))
        self.n_queue = QCheckBox(tr("Al terminar toda la cola"))
        self.n_fail = QCheckBox(tr("Cuando un shot falla"))
        self.n_sound = QCheckBox(tr("Con sonido"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        for i, (cb, key) in enumerate(((self.n_shot, "notify_shot"), (self.n_queue, "notify_queue"),
                                       (self.n_fail, "notify_failed"), (self.n_sound, "notify_sound"))):
            cb.setChecked(bool(settings.get(key, True)))
            grid.addWidget(cb, i // 2, i % 2)
        lay.addLayout(grid)
        lab_t = QLabel(tr("Probar cómo se ven y suenan:"))
        lab_t.setObjectName("Muted")
        lay.addWidget(lab_t)
        tests = QHBoxLayout()
        tests.setSpacing(6)
        for text, kind, ttl, msg in (
                (tr("Shot terminado"), "shot_done", tr("Shot terminado"),
                 tr("{name} · {n} frames en {time}", name="SH040_RND_V01", n=70, time="14 m 05 s")),
                (tr("Cola terminada"), "queue_done", tr("Cola terminada"),
                 tr("{done} de {total} shots · {frames} frames · {time}", done=6, total=6, frames=398, time="1 h 22 m")),
                (tr("Fallo"), "job_failed", tr("Shot fallido"),
                 "SH050_RND_V01 · " + tr("Blender dejó de responder durante {n} minutos", n=15))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=kind, t=ttl, m=msg: self.testNotify.emit(k, t, m))
            tests.addWidget(b)
        tests.addStretch()
        lay.addLayout(tests)
        right.addWidget(box)

        # --- APARIENCIA
        box, lay = _section(IC["palette"], tr("APARIENCIA"))
        self.theme = QComboBox()
        for label, val in ((tr("Según el sistema"), "system"), (tr("Claro"), "light"), (tr("Oscuro"), "dark")):
            self.theme.addItem(label, val)
        self.theme.setCurrentIndex(max(0, self.theme.findData(theme_mode)))
        form = _form()
        form.addRow(tr("Tema"), self.theme)
        self.language = QComboBox()  # los nombres de idioma van siempre en su propio idioma
        for label, val in ((tr("Automático (el idioma de Windows)"), "auto"), ("Español", "es"), ("English", "en")):
            self.language.addItem(label, val)
        self.language.setCurrentIndex(max(0, self.language.findData(prefs().value("language", "auto"))))
        self.language.setToolTip(tr("Se aplica al reiniciar la ventana de Frameguard (el render no se detiene)."))
        form.addRow(tr("Idioma"), self.language)
        lay.addLayout(form)
        from . import anim
        self.anims = QCheckBox(tr("Animaciones de la interfaz"))
        self.anims.setChecked(anim.enabled())
        self.anims.setToolTip(tr("Desactívalas si usas Frameguard por escritorio remoto con poca conexión.\n"
                                 "No afectan a la velocidad del render."))
        lay.addWidget(self.anims)
        right.addWidget(box)

        # --- ACTUALIZACIONES
        box, lay = _section(IC["download"], tr("ACTUALIZACIONES"))
        self.upd = QLineEdit(settings.get("update_folder", ""))
        self.upd.setCursorPosition(0)  # que se vea el principio de la ruta (la unidad)
        self.upd.setPlaceholderText(tr(r"Ej.: N:\carpeta\compartida\Frameguard\actualizaciones"))
        self.upd.setToolTip(tr("Carpeta donde se dejan los instaladores nuevos (Frameguard-Setup-X.Y.Z.exe).\n"
                               "Todos los PC que la vean recibirán el aviso de actualización."))
        b_upd = QPushButton(tr("Buscar…"))
        b_upd.clicked.connect(self._browse_updates)
        lab_u = QLabel(tr("Carpeta de actualizaciones"))
        lab_u.setObjectName("Muted")
        lay.addWidget(lab_u)
        lay.addWidget(_row(self.upd, b_upd))
        b_vers = QPushButton(tr("Versiones…"))
        b_vers.setToolTip(tr("Instalar otra versión (más nueva o anterior) desde la carpeta de actualizaciones"))
        b_vers.clicked.connect(lambda: VersionsDialog(self.upd.text().strip(), self).exec())
        b_notes = QPushButton(tr("Notas de la versión"))
        b_notes.setToolTip(tr("Lo nuevo de cada versión de Frameguard"))
        b_notes.clicked.connect(self.showNotes.emit)
        lay.addWidget(_row(b_vers, b_notes, stretch_first=False))
        right.addWidget(box)
        right.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        bar = QHBoxLayout()
        b_data = QPushButton(tr("Abrir carpeta de datos"))
        b_data.setToolTip(tr("Cola, ajustes, logs e informes:") + f"\n{paths.data_dir()}")
        b_data.clicked.connect(lambda: os.startfile(str(paths.data_dir())))
        bar.addWidget(b_data)
        bar.addStretch()
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(tr("Guardar"))
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(ok)
        outer.addLayout(bar)

    def _update_limit(self, *_):
        from .. import limits
        n, total, _mask = limits.plan(self.limit_pct.currentData())
        self.limit_pct.setEnabled(self.limit.isChecked())
        self.limit_threads.setText(tr("{n} de {total} hilos", n=n, total=total))
        self.limit_threads.setEnabled(self.limit.isChecked())

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Elegir blender.exe"), r"C:\Program Files", "blender.exe (blender.exe)")
        if path:
            path = os.path.normpath(path)
            if self.blender.findData(path) < 0:
                self.blender.addItem(path, path)
            self.blender.setCurrentIndex(self.blender.findData(path))

    def _browse_updates(self):
        d = QFileDialog.getExistingDirectory(self, tr("Carpeta de actualizaciones"), self.upd.text())
        if d:
            self.upd.setText(os.path.normpath(d))

    def values(self) -> dict:
        return {"blender_path": self.blender.currentData(), "max_attempts": self.attempts.value(),
                "stall_minutes": self.stall.value(), "exit_grace_seconds": self.grace.value(),
                "disable_save_output": self.save_out.isChecked(), "update_folder": self.upd.text().strip(),
                "notify_shot": self.n_shot.isChecked(), "notify_queue": self.n_queue.isChecked(),
                "notify_failed": self.n_fail.isChecked(), "notify_sound": self.n_sound.isChecked(),
                "limit_resources": self.limit.isChecked(), "limit_percent": int(self.limit_pct.currentData()),
                "countdown_seconds": self.countdown.value() * 60, "language": self.language.currentData()}


class VersionsDialog(QDialog):
    """Instalar cualquier versión disponible: actualizar o volver a una anterior."""
    install = Signal(dict)

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Versiones de Frameguard"))
        self.resize(640, 420)
        self.items = updater.list_versions(folder)
        lay = QVBoxLayout(self)
        head = QLabel(tr("Versión instalada:") + f" <b>{__version__}</b><br><span style='color:gray'>"
                      + (folder or tr("Sin carpeta de actualizaciones configurada")) + "</span>")
        lay.addWidget(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Versión"), tr("Estado"), tr("Novedades")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 90)
        self.tree.setColumnWidth(1, 110)
        for it in self.items:
            estado = tr("Instalada") if it["current"] else (tr("Más nueva") if it["newer"] else tr("Anterior"))
            row = QTreeWidgetItem([it["label"], estado, (it["notes"].splitlines() or ["—"])[0]])
            row.setToolTip(2, it["notes"] or "")
            self.tree.addTopLevelItem(row)
        lay.addWidget(self.tree, 1)
        bar = QHBoxLayout()
        bar.addStretch()
        close = QPushButton(tr("Cerrar"))
        close.clicked.connect(self.reject)
        self.b_inst = QPushButton(tr("Instalar esta versión"))
        self.b_inst.setObjectName("Primary")
        self.b_inst.clicked.connect(self._install)
        bar.addWidget(close)
        bar.addWidget(self.b_inst)
        lay.addLayout(bar)

    def _install(self):
        i = self.tree.indexOfTopLevelItem(self.tree.currentItem()) if self.tree.currentItem() else -1
        if i < 0:
            return
        main = self.parent()
        while main is not None and not hasattr(main, "install_update"):
            main = main.parent()
        if main is not None:
            self.accept()
            main.install_update(self.items[i])


class LogDialog(QDialog):
    def __init__(self, client, job: dict, parent=None):
        super().__init__(parent)
        self.client, self.job_id = client, job["id"]
        self.setWindowTitle(f"Log — {job['name']}")
        self.resize(980, 600)
        lay = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        f = QFont("Consolas")
        f.setPointSize(9)
        self.text.setFont(f)
        lay.addWidget(self.text, 1)
        bar = QHBoxLayout()
        self.follow = QCheckBox(tr("Seguir el final"))
        self.follow.setChecked(True)
        bar.addWidget(self.follow)
        bar.addStretch()
        logs = job.get("logs") or []
        b_open = QPushButton(tr("Abrir carpeta de logs"))
        b_open.clicked.connect(lambda: os.startfile(str(paths.logs_dir())))
        bar.addWidget(b_open)
        if logs:
            b_file = QPushButton(tr("Abrir archivo"))
            b_file.clicked.connect(lambda: os.startfile(logs[-1]))
            bar.addWidget(b_file)
        lay.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    def refresh(self):
        self.client.fetch_log(self.job_id, self._show, 600)

    def _show(self, lines):
        bar = self.text.verticalScrollBar()
        keep = bar.value()
        self.text.setPlainText("\n".join(lines))
        if self.follow.isChecked():
            self.text.moveCursor(QTextCursor.End)
        else:
            bar.setValue(keep)


class PreflightDialog(QDialog):
    """Chequeo previo: avisos de todos los shots activos antes de irse a dormir."""
    reinspectAll = Signal()

    def __init__(self, jobs: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Chequeo previo"))
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        active = [j for j in jobs if j.get("enabled", True) and j["status"] not in ("done",)]
        errors = sum(1 for j in active for w in j.get("warnings", []) if w["level"] == "error") + \
            sum(1 for j in active if j["status"] in ("error_read", "failed"))
        warns = sum(1 for j in active for w in j.get("warnings", []) if w["level"] == "warn")
        reading = sum(1 for j in active if j["status"] == "reading")
        frames = sum(max(0, j.get("frames_total", 0) - j.get("done_count", 0)) for j in active)
        if not active:
            head = tr("No hay shots activos en la cola.")
        elif errors:
            head = ("<b style='color:#e5534b'>" + plural(errors, "{n} problema que impedirá renderizar bien",
                                                           "{n} problemas que impedirán renderizar bien")
                    + "</b> · " + plural(warns, "{n} aviso", "{n} avisos"))
        elif warns:
            head = plural(warns, "<b>Se puede renderizar</b>, pero revisa {n} aviso.",
                          "<b>Se puede renderizar</b>, pero revisa {n} avisos.")
        else:
            head = tr("<b>Todo listo.</b> No se encontraron problemas.")
        if reading:
            head += " · " + plural(reading, "{n} archivo aún leyéndose", "{n} archivos aún leyéndose")
        sub = QLabel(head + "<br><span style='color:gray'>"
                     + tr("{n} shots activos · {frames} frames por renderizar", n=len(active), frames=frames) + "</span>")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        tree = QTreeWidget()
        tree.setHeaderLabels([tr("Shot / aviso")])
        for j in active:
            items = list(j.get("warnings", []))
            if j["status"] == "error_read":
                items.insert(0, {"level": "error", "text": tr("No se pudo leer:") + " " + (j.get("error") or "")})
            if j["status"] == "failed":
                items.insert(0, {"level": "error", "text": tr("Falló:") + " " + (j.get("error") or "")})
            top = QTreeWidgetItem([f"{j['name']}   (" + plural(len([w for w in items if w["level"] != "info"]),
                                                            "{n} aviso", "{n} avisos") + ")"])
            top.setToolTip(0, j["path"])
            tree.addTopLevelItem(top)
            for w in items:
                mark = {"error": "✖", "warn": "⚠", "info": "ℹ"}.get(w["level"], "·")
                ch = QTreeWidgetItem([f"{mark}  {w['text']}"])
                ch.setToolTip(0, w["text"])
                top.addChild(ch)
            top.setExpanded(any(w["level"] != "info" for w in items))
        lay.addWidget(tree, 1)
        bar = QHBoxLayout()
        b_re = QPushButton(tr("Volver a leer todos"))
        b_re.clicked.connect(lambda: (self.reinspectAll.emit(), self.accept()))
        bar.addWidget(b_re)
        bar.addStretch()
        ok = QPushButton(tr("Cerrar"))
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        bar.addWidget(ok)
        lay.addLayout(bar)


class CountdownDialog(QDialog):
    """Cuenta atrás antes de apagar / suspender / reiniciar: se puede cancelar o hacerlo ya."""
    cancelled = Signal()
    nowRequested = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.WindowStaysOnTopHint)
        from .widgets import ProgressLine
        self.theme = theme
        self.action = None
        self.setWindowTitle(tr("La cola terminó"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(16)
        self.glyph = QLabel()
        self.glyph.setObjectName("BigGlyph")
        self.glyph.setFixedWidth(46)
        self.glyph.setAlignment(Qt.AlignCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        head = QLabel(tr("La cola terminó"))
        head.setObjectName("Muted")
        self.label = QLabel()
        self.label.setObjectName("Title")
        self.label.setWordWrap(True)
        col.addWidget(head)
        col.addWidget(self.label)
        top.addWidget(self.glyph)
        top.addLayout(col, 1)
        lay.addLayout(top)
        self.bar = ProgressLine(theme)
        lay.addWidget(self.bar)
        sub = QLabel(tr("Puedes cancelarlo si todavía estás usando el equipo."))
        sub.setObjectName("Muted")
        lay.addWidget(sub)
        bar = QHBoxLayout()
        bar.addStretch()
        self.b_now = QPushButton()
        self.b_now.clicked.connect(lambda: (self.nowRequested.emit(), self.hide()))
        b = QPushButton(tr("Cancelar"))
        b.setObjectName("Primary")
        b.clicked.connect(lambda: (self.cancelled.emit(), self.hide()))
        bar.addWidget(self.b_now)
        bar.addWidget(b)
        lay.addLayout(bar)

    def set_countdown(self, action: str, seconds: int, total: int | None = None):
        text, now_label, glyph, color_key = _actions().get(action, (action, tr("Ahora"), IC["shutdown"], "warn"))
        color = self.theme.c[color_key]
        if action != self.action:
            self.action = action
            self.glyph.setText(glyph)
            self.glyph.setStyleSheet(f"color: {color};")
            self.b_now.setText(now_label)
        m, s = divmod(max(0, int(seconds)), 60)
        self.label.setText(f"{text} {m}:{s:02d}")
        self.bar.set(seconds / total if total else 0.0, color)
