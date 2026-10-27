"""Arranque de la ventana de Frameguard (una sola instancia por usuario)."""
import ctypes
import faulthandler
import getpass
import logging
import os
import sys

from PySide6.QtCore import QLibraryInfo, QPoint, Qt, QTimer, QTranslator
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .. import i18n
from .anim import MotionFilter
from .client import EngineClient, launch_engine
from .icon import app_icon
from .main_window import MainWindow
from .prefs import prefs
from .theme import Theme


def _single_instance_name() -> str:
    return f"frameguard-ui-{getpass.getuser()}"


def _screenshot_hook(win: MainWindow, client=None):
    """FRAMEGUARD_SCREENSHOT=ruta.png: guarda una captura de la ventana y sale (para revisar la interfaz).
    FRAMEGUARD_SCREENSHOT_POPUP=1 abre antes el panel de detalles del primer shot."""
    target = os.environ.get("FRAMEGUARD_SCREENSHOT")
    if not target:
        return
    delay = int(os.environ.get("FRAMEGUARD_SCREENSHOT_DELAY", "4000"))

    def popup():
        if os.environ.get("FRAMEGUARD_SCREENSHOT_DRAWER"):
            win.drawer.open_drawer()
            return
        jobs = win.st.get("jobs") or []
        if os.environ.get("FRAMEGUARD_SCREENSHOT_POPUP") and jobs:
            idx = int(os.environ.get("FRAMEGUARD_SCREENSHOT_POPUP_INDEX", "0"))
            win.open_popup(jobs[min(idx, len(jobs) - 1)]["id"])

    def shot():
        import json
        with open(target + ".json", "w", encoding="utf-8") as f:  # resultado comprobable de la prueba
            json.dump({"connected": bool(client and client.connected), "rows": len(win.list.rows),
                       "jobs": len(win.st.get("jobs") or []), "drawer": win.drawer.isVisible(),
                       "popup": win.popup.isVisible(), "size": [win.width(), win.height()],
                       "toasts": len(win.toasts.toasts)}, f)
        for i, t in enumerate(win.toasts.toasts):
            t.grab().save(target.replace(".png", f"_aviso{i}.png"))
        if win.whats_new is not None and win.whats_new.isVisible():
            win.whats_new.grab().save(target.replace(".png", "_novedades.png"))
        if os.environ.get("FRAMEGUARD_SCREENSHOT_SETTINGS"):
            from .dialogs import SettingsDialog
            d = SettingsDialog(win.st.get("settings") or {}, win.st.get("blenders") or [], win.theme.mode, win)
            d.show()
            QApplication.processEvents()
            d.grab().save(target.replace(".png", "_ajustes.png"))
            d.close()
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not win.whats_new:  # p. ej. la lista de carpetas escaneadas
            modal.grab().save(target.replace(".png", "_dialogo.png"))
        if win.countdown.isVisible():
            win.countdown.grab().save(target.replace(".png", "_cuenta.png"))
        if win.after.view().isVisible():
            win.after.view().window().grab().save(target.replace(".png", "_alterminar.png"))
        pm = win.grab()
        if win.popup.isVisible():
            win.popup.grab().save(target.replace(".png", "_panel.png"))
            from PySide6.QtGui import QPainter
            painter = QPainter(pm)
            pos = win.mapFromGlobal(win.popup.pos())
            painter.drawPixmap(pos, win.popup.grab())
            painter.end()
        pm.save(target)
        QApplication.quit()

    QTimer.singleShot(800, lambda: win.resize(win.width() - 30, win.height() - 20))  # ejercita resizeEvent
    add_path = os.environ.get("FRAMEGUARD_SCREENSHOT_ANIM_ADD")
    if add_path:  # fotogramas en mitad de las animaciones: agregar shots + onda en un botón
        t0 = 2200

        def trigger():
            win.client.send("add", paths=add_path.split("|"))
            from PySide6.QtCore import QPoint as _P
            from .anim import Ripple
            from PySide6.QtGui import QColor as _C
            c = _C(win.theme.c["accent"])
            c.setAlphaF(0.3)
            Ripple(win.b_add_txt, _P(20, 14), c)

        QTimer.singleShot(t0, trigger)
        for k, dt in enumerate((140, 330, 700, 1300)):
            QTimer.singleShot(t0 + dt, lambda k=k: win.grab().save(target.replace(".png", f"_anim{k}.png")))
    def extras():
        if os.environ.get("FRAMEGUARD_SCREENSHOT_DROP"):  # capa «Suelta para agregar»
            win.drop_overlay.show_for(os.environ["FRAMEGUARD_SCREENSHOT_DROP"].split("|"))
        if os.environ.get("FRAMEGUARD_SCREENSHOT_COUNTDOWN"):
            win.countdown.set_countdown(os.environ["FRAMEGUARD_SCREENSHOT_COUNTDOWN"], 541, 600)
            win.countdown.show()
        if os.environ.get("FRAMEGUARD_SCREENSHOT_AFTER"):
            win.after.setCurrentIndex(win.after.findData(os.environ["FRAMEGUARD_SCREENSHOT_AFTER"]))
            win.after.showPopup()
        if os.environ.get("FRAMEGUARD_SCREENSHOT_SCAN"):  # varias carpetas -> lista para elegir
            win.scan_folders(os.environ["FRAMEGUARD_SCREENSHOT_SCAN"].split("|"))

    QTimer.singleShot(delay - 1200, popup)
    QTimer.singleShot(delay - 1500, extras)
    QTimer.singleShot(delay, shot)


def _setup_logging():
    """La ventana compilada no tiene consola: los errores van a ui.log (y los cierres duros a ui_crash.log)."""
    from .. import __version__, paths
    log_path = paths.data_dir() / "ui.log"
    if log_path.exists() and log_path.stat().st_size > 2_000_000:
        log_path.replace(log_path.with_suffix(".log.1"))
    logging.basicConfig(filename=str(log_path), level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    faulthandler.enable(open(paths.data_dir() / "ui_crash.log", "a", encoding="utf-8"))
    sys.excepthook = lambda t, v, tb: logging.error("Excepción no controlada", exc_info=(t, v, tb))
    logging.info("Ventana %s iniciada (pid %s, args %s)", __version__, os.getpid(), sys.argv[1:])


def run_ui(port: int, files: list[str] | None = None) -> int:
    files = [os.path.abspath(f) for f in (files or []) if os.path.exists(f)]
    _setup_logging()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Frameguard.App")
    except (AttributeError, OSError):
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("Frameguard")
    app.setOrganizationName("Frameguard")
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    i18n.set_lang(prefs().value("language", "auto"))  # el de Windows, salvo que se eligiera otro en Ajustes
    logging.info("Idioma: %s", i18n.lang())
    if i18n.lang() == "es":  # botones estándar de Qt (Sí / No / Cancelar) en español
        qt_tr = QTranslator(app)
        if qt_tr.load("qtbase_es", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
            app.installTranslator(qt_tr)

    name = _single_instance_name()
    if not os.environ.get("FRAMEGUARD_SCREENSHOT"):
        sock = QLocalSocket()
        sock.connectToServer(name)
        if sock.waitForConnected(300):
            sock.write(("open\n" + "\n".join(files)).encode("utf-8") if files else b"show")
            sock.waitForBytesWritten(300)
            logging.info("Ya había una ventana abierta: se trae al frente y esta instancia sale")
            return 0
    server = QLocalServer()
    QLocalServer.removeServer(name)
    server.listen(name)

    theme = Theme()
    if os.environ.get("FRAMEGUARD_THEME"):
        theme.mode = os.environ["FRAMEGUARD_THEME"]
    theme.apply()
    client = EngineClient(port)
    motion = MotionFilter(theme)  # onda al pulsar botones y aparición animada de menús y diálogos
    app.installEventFilter(motion)
    win = MainWindow(client, theme)
    def on_connection():
        conn = server.nextPendingConnection()

        def read():
            msg = bytes(conn.readAll()).decode("utf-8", "replace").splitlines()
            win.show_normal()
            if msg and msg[0] == "open":
                QTimer.singleShot(300, lambda: win.add_paths(msg[1:]))

        conn.readyRead.connect(read)

    server.newConnection.connect(on_connection)

    def restart():
        """Reabre la ventana (p. ej. tras cambiar el idioma). El motor y el render no se tocan."""
        logging.info("Se reinicia la ventana")
        server.close()  # si no, la ventana nueva creería que ya hay una abierta y se cerraría
        launch_engine(port, engine=False)
        win.quit_ui_now()

    win.restart_ui = restart
    if os.environ.pop("FRAMEGUARD_TEST_RESTART", None):  # prueba: reinicia una vez (la ventana nueva ya no)
        QTimer.singleShot(3000, restart)
    win.show()
    if files:
        QTimer.singleShot(1500, lambda: win.add_paths(files))  # espera a tener el estado del motor
    _screenshot_hook(win, client)
    # Un error puntual en la ventana no debe cerrarla (el render corre aparte, en el motor):
    # se registra en ui.log y la ventana sigue.
    errors = 0
    while True:
        try:
            return app.exec()
        except Exception:  # noqa: BLE001
            errors += 1
            logging.exception("Error en la ventana (%s); se continúa", errors)
            if errors > 50:
                raise
