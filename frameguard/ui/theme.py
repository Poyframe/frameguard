"""Tema claro / oscuro / según el sistema (los colores del boceto aprobado)."""
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from .prefs import prefs

DARK = {
    "bg": "#1d2128", "panel": "#252a32", "row": "#2a2f38", "row_hover": "#303643", "border": "#3a414c",
    "text": "#e6e8eb", "muted": "#9aa2ad", "accent": "#4d9be6", "ok": "#4cc38a", "warn": "#e2a93b",
    "err": "#e5534b", "off": "#59606b", "track": "#353b46", "on_accent": "#ffffff",
}
LIGHT = {
    "bg": "#eef0f3", "panel": "#ffffff", "row": "#ffffff", "row_hover": "#f5f7fa", "border": "#d9dde3",
    "text": "#1f2328", "muted": "#5c6470", "accent": "#1f6fc5", "ok": "#1b8752", "warn": "#9a6208",
    "err": "#c2352d", "off": "#b3b9c2", "track": "#e4e7ec", "on_accent": "#ffffff",
}
ICON_FONT = '"Segoe Fluent Icons", "Segoe MDL2 Assets"'

# Glifos de Segoe Fluent Icons / MDL2 (incluidas en Windows 10/11)
IC = {
    "add": "", "settings": "", "play": "", "pause": "", "folder": "",
    "file": "", "sun": "", "moon": "", "desktop": "", "delete": "",
    "refresh": "", "close": "", "warn": "", "info": "", "check": "",
    "list": "", "report": "", "log": "", "openfolder": "", "power": "",
    "error": "", "grip": "", "redo": "", "chevron": "",
}
IC.update({
    "monitor": "", "restart": "", "sleep": "", "shield": "", "chip": "",
    "bell": "", "palette": "", "download": "", "app": "", "folder_add": "",
    "shutdown": "",
})


def glyph_icon(glyph: str, color: str, size: int = 16):
    """QIcon a partir de un glifo de Segoe Fluent Icons (nítido también en pantallas con escalado)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QFont, QIcon, QPainter, QPixmap
    icon = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.TextAntialiasing)
        f = QFont()
        f.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
        f.setPixelSize(int(size * scale * 0.9))
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRectF(0, 0, size * scale, size * scale), Qt.AlignCenter, glyph)
        p.end()
        pm.setDevicePixelRatio(scale)
        icon.addPixmap(pm)
    return icon


def _glyph_images(c: dict) -> dict:
    """Genera (una vez por color) los PNG del chulito y de las flechas que usa la hoja de estilos.
    Se crean también en @2x para pantallas con escalado."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage, QPainter, QPen

    from .. import paths
    folder = paths.sub("ui")
    out = {}

    def make(name, color, size, draw):
        key = f"{name}_{color.lstrip('#')}"
        for scale, suffix in ((1, ""), (2, "@2x")):
            f = folder / f"{key}{suffix}.png"
            if not f.exists():
                img = QImage(size * scale, size * scale, QImage.Format_ARGB32)
                img.fill(Qt.transparent)
                p = QPainter(img)
                p.setRenderHint(QPainter.Antialiasing)
                p.scale(scale, scale)
                draw(p, QColor(color))
                p.end()
                img.save(str(f))
        out[name] = (folder / f"{key}.png").as_posix()

    def check(p, col):
        p.setPen(QPen(col, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(3.6, 8.4), QPointF(6.6, 11.3), QPointF(12.4, 4.9)])

    def chevron(up):
        def draw(p, col):
            p.setPen(QPen(col, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            pts = [QPointF(2.5, 6.8), QPointF(5.5, 3.8), QPointF(8.5, 6.8)] if up else \
                  [QPointF(2.5, 4.2), QPointF(5.5, 7.2), QPointF(8.5, 4.2)]
            p.drawPolyline(pts)
        return draw

    make("check", "#ffffff", 16, check)
    make("up", c["muted"], 11, chevron(True))
    make("down", c["muted"], 11, chevron(False))
    make("up_hover", c["text"], 11, chevron(True))
    make("down_hover", c["text"], 11, chevron(False))
    return out


def alpha(hex_color: str, a: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(a * 255)})"


class Theme(QObject):
    changed = Signal()
    aboutToChange = Signal()  # antes de aplicar otro tema (para el fundido)

    def __init__(self):
        super().__init__()
        self.settings = prefs()
        self.mode = self.settings.value("theme", "system")
        self.c = DARK
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self.apply())

    def is_dark(self) -> bool:
        if self.mode == "dark":
            return True
        if self.mode == "light":
            return False
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Unknown:
            try:
                import winreg
                k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                   r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
            except OSError:
                return True
        return scheme == Qt.ColorScheme.Dark

    def set_mode(self, mode: str):
        was_dark = self.is_dark()
        self.mode = mode
        self.settings.setValue("theme", mode)
        if self.is_dark() != was_dark:
            self.aboutToChange.emit()
        self.apply()

    def apply(self):
        self.c = DARK if self.is_dark() else LIGHT
        app = QGuiApplication.instance()
        pal = QPalette()
        c = self.c
        for role, key in ((QPalette.Window, "bg"), (QPalette.Base, "panel"), (QPalette.AlternateBase, "row"),
                          (QPalette.Text, "text"), (QPalette.WindowText, "text"), (QPalette.Button, "panel"),
                          (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"),
                          (QPalette.ToolTipBase, "panel"), (QPalette.ToolTipText, "text"),
                          (QPalette.PlaceholderText, "muted")):
            pal.setColor(role, QColor(c[key]))
        pal.setColor(QPalette.HighlightedText, QColor(c["on_accent"]))
        app.setPalette(pal)
        app.setStyleSheet(self.qss())
        self.changed.emit()

    def qss(self) -> str:
        c = self.c
        try:
            g = _glyph_images(c)
        except Exception:  # noqa: BLE001  (sin iconos de estilo, la ventana funciona igual)
            g = {}
        extra = ""
        if g:
            extra = f"""
QCheckBox::indicator:checked {{ image: url("{g['check']}"); }}
QSpinBox, QDoubleSpinBox {{ padding-right: 28px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
          width: 24px; border-left: 1px solid {c['border']}; border-top-right-radius: 7px; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
          width: 24px; border-left: 1px solid {c['border']}; border-top: 1px solid {c['border']};
          border-bottom-right-radius: 7px; background: transparent; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {alpha(c['accent'], .18)}; }}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{ background: {alpha(c['accent'], .32)}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{g['up']}"); width: 11px; height: 11px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{g['down']}"); width: 11px; height: 11px; }}
QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {{ image: url("{g['up_hover']}"); }}
QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {{ image: url("{g['down_hover']}"); }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{g['down']}"); width: 11px; height: 11px; }}
QComboBox::down-arrow:hover {{ image: url("{g['down_hover']}"); }}
"""
        base = f"""
QWidget {{ color: {c['text']}; font-family: "Segoe UI"; font-size: 10pt; }}
QMainWindow, QDialog, #Root {{ background: {c['bg']}; }}
QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 4px; }}
#Card {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
#CardLabel, #Muted {{ color: {c['muted']}; font-size: 9pt; }}
#CardValue {{ font-size: 15pt; font-weight: 600; }}
#Title {{ font-size: 12pt; font-weight: 600; }}
#Version {{ color: {c['muted']}; font-size: 9pt; }}
#ColHeader {{ color: {c['muted']}; font-size: 9pt; }}
#JobName {{ font-weight: 600; }}
#Mono {{ font-family: Consolas, "Cascadia Mono", monospace; font-size: 9pt; color: {c['muted']};
          background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px; padding: 6px 8px; }}
#Empty {{ color: {c['muted']}; font-size: 11pt; }}
#DropZone {{ border: 2px dashed {c['border']}; border-radius: 10px; }}
QPushButton {{ background: transparent; border: 1px solid {c['border']}; border-radius: 7px; padding: 6px 12px; }}
QPushButton:hover {{ background: {c['row_hover']}; border-color: {c['muted']}; }}
QPushButton:pressed {{ background: {c['track']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#Primary {{ background: {c['accent']}; color: {c['on_accent']}; border-color: {c['accent']}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {QColor(c['accent']).lighter(112).name()}; }}
QPushButton#Danger {{ color: {c['err']}; }}
QPushButton#Icon {{ font-family: {ICON_FONT}; font-size: 11pt; padding: 6px 9px; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{ background: {c['panel']}; border: 1px solid {c['border']};
          border-radius: 7px; padding: 5px 8px; min-height: 18px; }}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: {c['muted']}; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; border: 1px solid {c['border']};
          selection-background-color: {c['accent']}; selection-color: {c['on_accent']}; outline: 0; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QMenu {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 4px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['accent']}; color: {c['on_accent']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}
QScrollArea, #ListHost {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['off']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {c['border']}; background: {c['panel']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QPlainTextEdit, QListWidget, QTreeWidget {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
QTreeWidget::item {{ padding: 3px; }}
QHeaderView::section {{ background: {c['panel']}; color: {c['muted']}; border: none; border-bottom: 1px solid {c['border']}; padding: 5px; }}
#Popup {{ background: {c['panel']}; border: 1px solid {c['accent']}; border-radius: 10px; }}
#Warn {{ color: {c['warn']}; background: {alpha(c['warn'], .13)}; border-radius: 6px; padding: 7px 9px; }}
#Err {{ color: {c['err']}; background: {alpha(c['err'], .13)}; border-radius: 6px; padding: 7px 9px; }}
#Info {{ color: {c['muted']}; background: {alpha(c['muted'], .12)}; border-radius: 6px; padding: 7px 9px; }}
#KvLabel {{ color: {c['muted']}; font-size: 8.5pt; }}
QPushButton#RowIcon {{ font-family: {ICON_FONT}; font-size: 10pt; padding: 0; border: 1px solid transparent; color: {c['muted']}; }}
QPushButton#RowIcon:hover {{ color: {c['err']}; border-color: {c['err']}; background: {alpha(c['err'], .12)}; }}
QPushButton#RowIcon:disabled {{ color: {c['off']}; }}
#Section {{ background: {c['row']}; border: 1px solid {c['border']}; border-radius: 8px; }}
#SectionTitle {{ color: {c['muted']}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
#Drawer {{ background: {c['panel']}; border-right: 1px solid {c['border']}; border-radius: 0; }}
QPushButton#NavItem {{ border: none; border-radius: 8px; padding: 0; text-align: left; background: transparent; }}
QPushButton#NavItem:hover {{ background: {alpha(c['accent'], .16)}; }}
QPushButton#NavItem:pressed {{ background: {alpha(c['accent'], .28)}; }}
QLabel#NavIcon {{ color: {c['accent']}; }}
QLabel#NavText {{ color: {c['text']}; font-size: 10.5pt; }}
#Banner {{ background: {alpha(c['accent'], .14)}; border: 1px solid {c['accent']}; border-radius: 8px; }}
QPushButton#HeaderBtn {{ font-family: "Segoe UI", {ICON_FONT}; font-size: 9pt; color: {c['muted']};
          border: 1px solid transparent; padding: 3px 9px; border-radius: 6px; background: transparent; }}
QPushButton#HeaderBtn:hover {{ color: {c['err']}; border-color: {c['err']}; background: {alpha(c['err'], .10)}; }}
QComboBox[armed="true"] {{ border-color: {c['warn']}; background: {alpha(c['warn'], .10)}; }}
QLabel#SectionIcon {{ font-family: {ICON_FONT}; font-size: 11pt; color: {c['accent']}; }}
QLabel#Hint {{ color: {c['muted']}; font-size: 8.5pt; }}
QLabel#FormLabel {{ color: {c['text']}; }}
QLabel#Badge {{ color: {c['ok']}; background: {alpha(c['ok'], .14)}; border-radius: 5px; padding: 1px 7px; font-size: 8.5pt; }}
QLabel#BigGlyph {{ font-family: {ICON_FONT}; font-size: 26pt; }}
"""
        return base + extra
