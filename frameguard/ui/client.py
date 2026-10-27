"""Conexión de la ventana con el motor (HTTP local). Si el motor no responde, lo arranca."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def engine_command(port: int, engine: bool = True) -> tuple[list[str], str | None]:
    role = ["--engine"] if engine else []
    if getattr(sys, "frozen", False):
        return [sys.executable, *role, "--port", str(port)], None
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    root = str(Path(__file__).resolve().parents[2])
    return [str(pyw if pyw.exists() else exe), "-m", "frameguard", *role, "--port", str(port)], root


def launch_engine(port: int, engine: bool = True) -> None:
    """Arranca el motor desacoplado de la ventana: si la ventana se cierra, el motor sigue.
    Con engine=False arranca otra ventana (para reiniciarla tras cambiar el idioma)."""
    cmd, cwd = engine_command(port, engine)
    # Instancia independiente del .exe (no un subproceso "hijo" de PyInstaller que dependa de la ventana)
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    for flags in (DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB,
                  DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP):
        try:
            subprocess.Popen(cmd, cwd=cwd, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            return
        except OSError:
            continue


class EngineClient(QObject):
    stateChanged = Signal(dict)
    connectionChanged = Signal(bool)

    def __init__(self, port: int, poll_ms: int = 600):
        super().__init__()
        self.base = f"http://127.0.0.1:{port}"
        self.port = port
        self.nam = QNetworkAccessManager(self)
        self.connected = None
        self.state: dict = {}
        self._inflight = False
        self._fails = 0
        self._last_launch = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(poll_ms)
        QTimer.singleShot(0, self.poll)

    def _req(self, path: str) -> QNetworkRequest:
        r = QNetworkRequest(QUrl(self.base + path))
        r.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        r.setTransferTimeout(8000)
        return r

    def poll(self):
        if self._inflight:
            return
        self._inflight = True
        reply = self.nam.get(self._req("/api/state"))
        reply.finished.connect(lambda: self._on_state(reply))

    def _on_state(self, reply: QNetworkReply):
        self._inflight = False
        ok = reply.error() == QNetworkReply.NoError
        data = None
        if ok:
            try:
                data = json.loads(bytes(reply.readAll()).decode("utf-8"))
            except ValueError:
                ok = False
        reply.deleteLater()
        if ok:
            self._fails = 0
            self.state = data
            self._set_connected(True)
            self.stateChanged.emit(data)
            return
        self._fails += 1
        if self._fails >= 2:
            self._set_connected(False)
            if time.time() - self._last_launch > 10:
                self._last_launch = time.time()
                launch_engine(self.port)

    def _set_connected(self, value: bool):
        if value != self.connected:
            self.connected = value
            self.connectionChanged.emit(value)

    def send(self, cmd: str, callback=None, **kwargs):
        body = json.dumps({"cmd": cmd, **kwargs}).encode("utf-8")
        reply = self.nam.post(self._req("/api/cmd"), QByteArray(body))

        def done():
            res = {"ok": False, "error": reply.errorString()}
            if reply.error() == QNetworkReply.NoError or reply.attribute(QNetworkRequest.HttpStatusCodeAttribute):
                try:
                    res = json.loads(bytes(reply.readAll()).decode("utf-8"))
                except ValueError:
                    pass
            reply.deleteLater()
            if callback:
                callback(res)
            QTimer.singleShot(50, self.poll)

        reply.finished.connect(done)

    def fetch_log(self, job_id: str, callback, lines: int = 400):
        reply = self.nam.get(self._req(f"/api/log?id={job_id}&lines={lines}"))

        def done():
            try:
                callback(json.loads(bytes(reply.readAll()).decode("utf-8")).get("lines", []))
            except ValueError:
                callback([])
            reply.deleteLater()

        reply.finished.connect(done)
