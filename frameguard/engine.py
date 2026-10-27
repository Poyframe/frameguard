"""Motor de Frameguard: un proceso independiente de la ventana que ejecuta la cola.

Si la ventana se cierra o se cuelga, el motor sigue. La ventana habla con él por HTTP en 127.0.0.1.

Cómo decide que un shot terminó (cualquiera de estas señales, no solo una):
  1. Blender sale y todos los frames están verificados en disco.
  2. Todos los frames verificados + Blender avisó que terminó ("Blender quit" o fin del último tramo),
     pero el proceso no se cierra en `exit_grace_seconds` -> se cierra a la fuerza y se sigue.
Fallos:
  - Blender se cae o termina con frames faltantes -> reintento solo de los frames que faltan.
  - Sin señales de vida durante `stall_minutes` -> se cierra y se reintenta.
  - Tras `max_attempts` intentos fallidos el shot queda como "Falló" y la cola sigue con el siguiente.
Seguridad: si Blender empieza a renderizar sin haber cargado el script de arranque (marcador BOOT),
se mata de inmediato: nunca se renderiza con ajustes que no sean los pedidos.
"""
import collections
import ctypes
import json
import logging
import logging.handlers
import os
import queue as queue_mod
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import APP_NAME, DEFAULT_PORT, __version__, i18n, limits, paths, report, scan, util
from .i18n import plural, tr
from . import blender as bl

DEFAULT_SETTINGS = {
    "blender_path": "",           # vacío = la versión más nueva instalada
    "max_attempts": 3,            # intentos por shot antes de darlo por fallido
    "stall_minutes": 15,          # minutos sin señales de vida antes de reiniciar Blender
    "exit_grace_seconds": 60,     # espera a que Blender cierre solo cuando ya terminó
    "disable_save_output": True,  # apaga Save Output durante el render si hay File Outputs
    "inspect_workers": 2,
    "countdown_seconds": 600,     # espera antes de apagar / suspender / reiniciar al terminar la cola
    "limit_resources": False,     # limitar los hilos del procesador que usa Blender (y prioridad baja)
    "limit_percent": 50,          # % de hilos del procesador para Blender cuando se limita
    "language": "auto",           # idioma de avisos y errores: auto (el de Windows), es, en
    "update_folder": "",          # carpeta (p. ej. en la red) con los instaladores de nuevas versiones
    "update_github": True,        # avisar también de las versiones publicadas en GitHub (la carpeta manda)
    "notify_shot": True,          # aviso al terminar cada shot
    "notify_queue": True,         # aviso al terminar toda la cola
    "notify_failed": True,        # aviso cuando un shot falla
    "notify_sound": True,         # los avisos suenan
}
NOTIFY_SETTING = {"shot_done": "notify_shot", "queue_done": "notify_queue", "job_failed": "notify_failed"}
ACTIVE = ("ready", "paused")
FRA_RE = re.compile(r"Fra:\s*(-?\d+)")
RENDERING_RE = re.compile(r"Fra:\s*-?\d+|Rendering frame")
ERROR_RE = re.compile(r"(?i)\berror\b|exception|out of memory|EXCEPTION_ACCESS_VIOLATION|segmentation|"
                      r"cuda error|optix error|failed to")
# Ruido típico de add-ons que fallan al cargar en segundo plano: no es un error del render.
NOISE_RE = re.compile(r"GPUShader|gpu\.init|blendkit|During handling|^\s*Traceback|addon_utils|^\s+File \"|"
                      r"[\\/]extensions[\\/]|[\\/]addons[\\/]", re.I)

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
log = logging.getLogger("frameguard.engine")


def _setup_logging():
    h = logging.handlers.RotatingFileHandler(paths.data_dir() / "engine.log", maxBytes=2_000_000,
                                             backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger("frameguard")
    root.setLevel(logging.INFO)
    root.addHandler(h)


def _kill_pid_if_blender(pid: int) -> bool:
    """Mata un Blender huérfano de una sesión anterior del motor (solo si de verdad es blender.exe)."""
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000 | 0x0001, False, int(pid))  # QUERY_LIMITED_INFORMATION | TERMINATE
    if not h:
        return False
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return False
        if not buf.value.lower().endswith("blender.exe"):
            return False
        return bool(k32.TerminateProcess(h, 1))
    finally:
        k32.CloseHandle(h)


class Run:
    """Un proceso de Blender en marcha y todo lo que se sabe de él."""

    def __init__(self, job_id, popen, log_path, frames, segments):
        self.job_id = job_id
        self.popen = popen
        self.log_path = log_path
        self.frames = set(frames)
        self.segments = segments
        self.started = util.now()
        self.last_output = self.started
        self.boot = None
        self.quit_seen = None
        self.completes = 0
        self.last_complete = None
        self.current_frame = None
        self.frame_started = None
        self.before = {}            # frame -> {archivo: mtime previo} para exigir archivos nuevos
        self.pending_verify = {}    # frame -> momento en que llegó FRAME_DONE sin archivo aún
        self.done_in_run = set()
        self.errors = collections.deque(maxlen=12)
        self.kill_reason = None
        self.forced_exit = False
        self.user_stop = False
        self.exit_seen = None
        self.eof = False
        self.lines = queue_mod.Queue()
        self._log = open(log_path, "a", encoding="utf-8", errors="replace")
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for raw in iter(self.popen.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                self._log.write(time.strftime("%H:%M:%S ") + line + "\n")
                self._log.flush()
                self.lines.put(line)
        except Exception as e:  # noqa: BLE001
            self.lines.put("[frameguard] " + tr("error leyendo la salida de Blender: {e}", e=e))
        finally:
            self.lines.put(None)

    def close_log(self, note: str = ""):
        try:
            if note:
                self._log.write(time.strftime("%H:%M:%S ") + "[frameguard] " + note + "\n")
            self._log.close()
        except OSError:
            pass

    def kill(self, reason: str, forced_exit: bool = False):
        if self.kill_reason is None:
            self.kill_reason = reason
        self.forced_exit = self.forced_exit or forced_exit
        try:
            self.popen.kill()
        except OSError:
            pass


class Engine:
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.run: Run | None = None
        self.dirty = False
        self.last_save = 0.0
        self.last_client = util.now()
        self.started_at = util.now()
        self._awake = None
        self.events = collections.deque(maxlen=50)  # avisos para la ventana (no se guardan en disco)
        self.event_seq = 0
        self.state = self._load()
        i18n.set_lang(self.settings.get("language"))
        self.pool = ThreadPoolExecutor(max_workers=int(self.settings["inspect_workers"]))
        self._recover()

    # ---------------------------------------------------------------- estado / persistencia
    @property
    def settings(self) -> dict:
        return self.state["settings"]

    def _load(self) -> dict:
        st = util.read_json(paths.state_file(), {}) or {}
        st.setdefault("schema", 1)
        st["settings"] = {**DEFAULT_SETTINGS, **st.get("settings", {})}
        if st.get("settings_rev", 1) < 2:  # 0.1.8: la espera antes de apagar pasa de 60 s a 10 min
            if st["settings"].get("countdown_seconds") == 60:
                st["settings"]["countdown_seconds"] = 600
            st["settings_rev"] = 2
        st.setdefault("queue", {"running": False, "after": "none", "started_at": None})
        st.setdefault("jobs", [])
        st["countdown"] = None
        st.setdefault("last_report", None)
        return st

    def _recover(self):
        """Tras un cierre inesperado del motor o un reinicio del PC."""
        for j in self.state["jobs"]:
            if j.get("status") == "rendering":
                if j.get("pid") and _kill_pid_if_blender(j["pid"]):
                    log.warning("Blender huérfano %s cerrado (%s)", j["pid"], j["name"])
                j["status"] = "ready" if self.state["queue"]["running"] else "paused"
                j["pid"] = None
                j.setdefault("history", []).append({"t": util.now(), "reason": tr("El motor se reinició a mitad del render; se reanuda desde el último frame verificado")})
            if j.get("status") == "reading":
                self._submit_inspect(j)
        if self.state["queue"]["running"]:
            log.info("La cola estaba corriendo: se reanuda")
        self._mark()

    def _mark(self):
        self.dirty = True

    def _save(self, force=False):
        if not (self.dirty or force):
            return
        if not force and util.now() - self.last_save < 2:
            return
        data = {k: v for k, v in self.state.items() if k != "countdown"}
        util.atomic_write_json(paths.state_file(), data)
        self.dirty = False
        self.last_save = util.now()

    def job(self, job_id) -> dict | None:
        for j in self.state["jobs"]:
            if j["id"] == job_id:
                return j
        return None

    def blender_path(self) -> str:
        p = self.settings.get("blender_path")
        if p and os.path.isfile(p):
            return p
        found = bl.detect_blenders()
        if not found:
            raise RuntimeError(tr("No se encontró Blender instalado. Elige blender.exe en Ajustes."))
        return found[0]["path"]

    # ---------------------------------------------------------------- avisos
    def _event(self, kind: str, title: str, text: str, job_id: str | None = None):
        """Aviso para la ventana (que muestra la tarjeta y suena). Si no hay ninguna ventana conectada,
        el motor reproduce el sonido él mismo."""
        if not self.settings.get(NOTIFY_SETTING.get(kind, ""), True):
            return
        self.event_seq += 1
        self.events.append({"id": self.event_seq, "kind": kind, "title": title, "text": text,
                            "job": job_id, "t": util.now()})
        log.info("Aviso: %s — %s", title, text)
        if self.settings.get("notify_sound") and util.now() - self.last_client > 15:
            from . import sounds
            sounds.play(kind)

    # ---------------------------------------------------------------- frames de un job
    @staticmethod
    def targets(job) -> list[int]:
        info = job.get("info") or {}
        if job.get("range"):
            a, b = job["range"]
        else:
            a, b = info.get("frame_start", 1), info.get("frame_end", 1)
        return util.frame_list(a, b, info.get("frame_step", 1))

    @staticmethod
    def check_outputs(job) -> list:
        """Salidas para verificar en disco. Las del último BOOT son exactas (ya con redirecciones)."""
        if job.get("runtime_outputs"):
            return job["runtime_outputs"]
        outs = (job.get("info") or {}).get("outputs") or []
        root = (job.get("test") or {}).get("output_root")
        if not root:
            return outs
        red = []
        for o in outs:
            o = dict(o)
            sub = o["node"] if o["kind"] == "file_output" else "SaveOutput"
            o["patterns"] = [os.path.join(root, sub, os.path.basename(p)) for p in o.get("patterns", [])]
            red.append(o)
        return red

    def _set_done(self, job, done: set[int]):
        job["done"] = util.to_ranges(done, (job.get("info") or {}).get("frame_step", 1))
        job["done_count"] = len(done)

    # ---------------------------------------------------------------- inspección
    def _submit_inspect(self, job):
        job["status"] = "reading"
        self.pool.submit(self._inspect_worker, job["id"], job["path"], job.get("scene"))

    def _inspect_worker(self, job_id, path, scene):
        try:
            blender = self.blender_path()
            info = bl.inspect_blend(blender, path, scene)
            error = None
        except Exception as e:  # noqa: BLE001
            info, error = None, str(e) or e.__class__.__name__
            log.warning("No se pudo leer %s: %s", path, error)
        with self.lock:
            j = self.job(job_id)
            if j is None:
                return
            if error:
                j["status"], j["error"] = "error_read", error
            else:
                j["info"] = info
                j["scene"] = info["scene"]
                j["frames_total"] = len(self.targets(j))
                j["warnings"] = self._warnings(info)
                j["status"] = "ready" if j.get("status") == "reading" else j["status"]
                j["error"] = None
            self._mark()

    def _warnings(self, info) -> list[dict]:
        w = []
        outs = info.get("outputs") or []
        file_outs = [o for o in outs if o["kind"] == "file_output"]
        if not info.get("camera"):
            w.append({"level": "error", "text": tr("La escena no tiene cámara activa: Blender no podrá renderizar.")})
        if not outs:
            w.append({"level": "error", "text": tr("No hay ninguna salida activa (ni Save Output ni File Output): el render no guardará nada.")})
        if info.get("save_output") and file_outs:
            if self.settings.get("disable_save_output"):
                w.append({"level": "info", "code": "save_off",  # el código no depende del idioma
                          "text": tr("Save Output está encendido: se apagará solo durante el render (el .blend no se modifica).")})
            else:
                w.append({"level": "warn", "text": tr("Save Output está encendido además de los File Output: se escribirán archivos extra.")})
        save_disabled = bool(file_outs and self.settings.get("disable_save_output"))
        for o in outs:
            if (o["kind"] == "main" and not save_disabled
                    and re.match(r"(?i)^([a-z]:)?[\\/]+tmp([\\/]|$)", o.get("directory", ""))):
                w.append({"level": "warn", "text": tr("Save Output escribe en {path}", path=o["directory"])})
            if o.get("media_type") == "VIDEO":
                w.append({"level": "warn", "text": tr("La salida «{node}» es video: no se puede reanudar por frames.", node=o["node"])})
        mi = info.get("missing_images") or []
        if mi:
            names = ", ".join(m["name"] for m in mi[:4]) + ("…" if len(mi) > 4 else "")
            w.append({"level": "warn", "text": plural(len(mi), "{n} textura no encontrada: {names}", "{n} texturas no encontradas: {names}", names=names)})
        ml = info.get("missing_libraries") or []
        if ml:
            names = ", ".join(m["name"] for m in ml[:3]) + ("…" if len(ml) > 3 else "")
            w.append({"level": "error", "text": plural(len(ml), "{n} archivo enlazado no encontrado: {names}", "{n} archivos enlazados no encontrados: {names}", names=names)})
        mc = info.get("missing_caches") or []
        if mc:
            w.append({"level": "warn", "text": plural(len(mc), "{n} caché no encontrada: {names}", "{n} cachés no encontradas: {names}", names=", ".join(m["name"] for m in mc[:3]))})
        scenes = info.get("scenes") or []
        if len(scenes) > 1:
            w.append({"level": "info", "text": tr("El archivo tiene {n} escenas; se renderiza «{scene}».", n=len(scenes), scene=info.get("scene"))})
        fv, bv = info.get("file_version") or [0, 0], info.get("blender_version") or [0, 0]
        if fv[:2] > bv[:2]:
            w.append({"level": "warn", "text": tr("Guardado con Blender {saved} y se renderiza con {used}.", saved=f"{fv[0]}.{fv[1]}", used=f"{bv[0]}.{bv[1]}")})
        return w

    # ---------------------------------------------------------------- bucle principal
    def loop(self):
        while not self.stop_event.is_set():
            try:
                with self.lock:
                    self._tick()
                    self._save()
            except Exception:  # noqa: BLE001
                log.error("Error en el bucle del motor:\n%s", traceback.format_exc())
            busy = self.run is not None or self.state["countdown"] is not None
            self._keep_awake(busy)
            self._render_lock(busy or bool(self.state["queue"]["running"]))
            time.sleep(0.25)
        self._render_lock(False)
        with self.lock:
            self._save(force=True)

    def _render_lock(self, on: bool):
        """runtime/rendering.lock existe mientras la cola trabaja: el instalador lo consulta para no
        cerrar Frameguard a mitad de un render."""
        if getattr(self, "_lock_on", None) == on:
            return
        lock = paths.runtime_dir() / "rendering.lock"
        try:
            if on:
                lock.write_text(str(os.getpid()), encoding="utf-8")
            elif lock.exists():
                lock.unlink()
            self._lock_on = on
        except OSError:
            pass

    def _tick(self):
        q = self.state["queue"]
        if self.run:
            self._pump()
            self._check_run()
        elif q["running"]:
            nxt = self._next_job()
            if nxt is not None:
                self._start_job(nxt)
            elif not any(j["status"] == "reading" and j.get("enabled", True) for j in self.state["jobs"]):
                self._finish_queue()
        self._countdown_tick()
        self._idle_exit()

    def _next_job(self):
        for j in self.state["jobs"]:
            if j.get("enabled", True) and j["status"] in ACTIVE:
                return j
        return None

    def _start_job(self, job):
        if not os.path.isfile(job["path"]):
            job["status"], job["error"] = "failed", "No se encuentra el archivo .blend"
            self._event("job_failed", "Shot fallido", f"{job['name']} · {job['error']}", job["id"])
            self._mark()
            return
        targets = self.targets(job)
        done = set(util.from_ranges(job.get("done")))
        if job.get("mode") == "missing" and not job.get("disk_checked"):
            outs = self.check_outputs(job)
            for f in targets:
                if f not in done and util.frame_on_disk(outs, f):
                    done.add(f)
            job["disk_checked"] = True
            self._set_done(job, done)
        todo = [f for f in targets if f not in done]
        if not todo:
            job["status"], job["finished_at"] = "done", util.now()
            self._mark()
            return
        info = job["info"]
        step = int(info.get("frame_step", 1) or 1)
        attempt = int(job.get("failures", 0)) + 1
        safe = re.sub(r"[^\w\-]+", "_", job["name"])[:60]
        cfg_path = paths.runtime_dir() / f"{job['id']}_cfg.json"
        try:
            blender = self.blender_path()
            cmd, segments = bl.render_command(blender, job["path"], job.get("scene"), todo, step, cfg_path)
            cfg = {"disable_save_output": bool(self.settings.get("disable_save_output")),
                   "attempt": attempt, "segments": segments, **(job.get("test") or {})}
            util.atomic_write_json(cfg_path, cfg)
            log_path = paths.logs_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}_intento{attempt}.log"
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            limited = bool(self.settings.get("limit_resources"))
            flags = bl.CREATE_NO_WINDOW | (limits.BELOW_NORMAL_PRIORITY_CLASS if limited else 0)
            popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=flags,
                                     cwd=os.path.dirname(job["path"]), env=env)
            limit_note = limits.apply(popen.pid, True, self.settings.get("limit_percent", 50)) if limited else ""
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "failed", f"No se pudo lanzar Blender: {e}"
            log.error("No se pudo lanzar Blender para %s: %s", job["name"], traceback.format_exc())
            self._event("job_failed", "Shot fallido", f"{job['name']} · {job['error']}", job["id"])
            self._mark()
            return
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[frameguard] {APP_NAME} {__version__} — intento {attempt}\n[frameguard] frames: "
                    f"{util.ranges_label(todo, step)}\n[frameguard] comando: {subprocess.list2cmdline(cmd)}\n")
            if limit_note:
                f.write("[frameguard] " + tr("recursos: {note}", note=limit_note) + "\n")
        self.run = Run(job["id"], popen, log_path, todo, segments)
        job.update(status="rendering", pid=popen.pid, error=None, current_frame=None, last_line="")
        job.setdefault("started_at", util.now())
        job.setdefault("logs", []).append(str(log_path))
        job["logs"] = job["logs"][-10:]
        job["run_started_at"] = util.now()
        log.info("Inicia %s (intento %s, %s frames, pid %s)", job["name"], attempt, len(todo), popen.pid)
        self._mark()

    def _pump(self):
        run, job = self.run, self.job(self.run.job_id)
        for _ in range(5000):
            try:
                line = run.lines.get_nowait()
            except queue_mod.Empty:
                break
            if line is None:
                run.eof = True
                break
            run.last_output = util.now()
            if job is not None:
                self._handle_line(job, run, line)

    def _handle_line(self, job, run, line):
        if line.startswith("@@FG|"):
            parts = line.split("|", 2)
            kind = parts[1] if len(parts) > 1 else ""
            try:
                payload = json.loads(parts[2]) if len(parts) > 2 and parts[2] else {}
            except ValueError:
                payload = {}
            if kind == "BOOT":
                run.boot = payload
                job["runtime_outputs"] = payload.get("outputs") or []
                job["applied"] = payload.get("applied") or {}
                if (job.get("test") or {}).get("output_root") and "output_root" not in job["applied"]:
                    run.kill(tr("La redirección de prueba no se aplicó: render detenido por seguridad"))
            elif kind == "FRAME_START":
                f = int(payload.get("frame"))
                run.current_frame, run.frame_started = f, util.now()
                job["current_frame"] = f
                # foto previa tomada por Blender antes de renderizar el frame (sin carreras)
                run.before[f] = payload["before"] if "before" in payload else self._mtimes(job, f)
            elif kind == "FRAME_DONE":
                self._frame_done(job, run, int(payload.get("frame")), payload.get("files"))
            elif kind == "COMPLETE":
                run.completes += 1
                run.last_complete = util.now()
            elif kind == "ERROR":
                msg_lines = (payload.get("msg") or "").strip().splitlines()
                run.errors.append(msg_lines[-1] if msg_lines else tr("error en el script de arranque"))
            self._mark()
            return
        if run.boot is None and RENDERING_RE.search(line):
            run.kill(tr("Blender empezó a renderizar sin el script de seguridad: render detenido"))
        m = FRA_RE.search(line)
        if m:
            job["current_frame"] = int(m.group(1))
        stripped = line.strip()
        if stripped:
            job["last_line"] = stripped[-240:]
        if stripped == "Blender quit":
            run.quit_seen = util.now()
        if ERROR_RE.search(line) and not NOISE_RE.search(line):
            run.errors.append(stripped[-300:])

    def _mtimes(self, job, frame):
        out = {}
        for f in util.frame_files(self.check_outputs(job), frame):
            try:
                out[f] = os.path.getmtime(f)
            except OSError:
                out[f] = None
        return out

    def _frame_verified(self, job, run, frame) -> bool | None:
        outs = self.check_outputs(job)
        files = util.frame_files(outs, frame)
        if not files:
            return None
        before = run.before.get(frame, {})
        for f in files:
            try:
                st = os.stat(f)
            except OSError:
                return False
            if st.st_size <= 0:
                return False
            if f in before and before[f] is not None and st.st_mtime == before[f]:
                return False  # el archivo es viejo: Blender no lo reescribió
        return True

    def _frame_done(self, job, run, frame, files=None):
        if files and all(f.get("fresh") and f.get("size", 0) > 0 for f in files):
            self._accept_frame(job, run, frame)  # Blender confirmó archivos nuevos y no vacíos
            return
        ok = self._frame_verified(job, run, frame)
        if ok is False:
            run.pending_verify.setdefault(frame, util.now())
            return
        self._accept_frame(job, run, frame)

    def _accept_frame(self, job, run, frame):
        done = set(util.from_ranges(job.get("done")))
        done.add(frame)
        self._set_done(job, done)
        run.done_in_run.add(frame)
        run.pending_verify.pop(frame, None)
        if run.frame_started and run.current_frame == frame:
            dt = util.now() - run.frame_started
            times = job.setdefault("frame_times", [])
            times.append(round(dt, 2))
            del times[:-30]
            job["avg_frame"] = round(sum(times) / len(times), 2)
        self._mark()

    def _check_run(self):
        run, job, t = self.run, self.job(self.run.job_id), util.now()
        if job is None:
            run.kill(tr("El shot se quitó de la cola"))
        for frame, since in list(run.pending_verify.items()) if job else []:
            ok = self._frame_verified(job, run, frame)
            if ok is not False:
                self._accept_frame(job, run, frame)
            elif t - since > 30:
                run.pending_verify.pop(frame, None)
                run.errors.append(tr("El frame {frame} terminó pero sus archivos no aparecieron en disco", frame=frame))
        rc = run.popen.poll()
        if rc is None:
            missing = run.frames - run.done_in_run
            finished = run.quit_seen is not None or (run.completes >= run.segments and run.segments > 0)
            grace = float(self.settings["exit_grace_seconds"])
            if not missing and finished and t - run.last_output > grace:
                run.kill(tr("Blender terminó todos los frames pero no se cerraba: se cerró a la fuerza"), forced_exit=True)
                log.warning("%s: Blender colgado al salir, se cierra a la fuerza", job["name"] if job else "?")
            elif run.boot is None and t - run.started > 600:
                run.kill(tr("Blender no arrancó en 10 minutos"))
            elif t - run.last_output > float(self.settings["stall_minutes"]) * 60:
                run.kill(tr("Blender dejó de responder durante {n} minutos", n=self.settings["stall_minutes"]))
            if job:
                job["render_seconds_live"] = round(t - run.started, 1)
            return
        if run.exit_seen is None:
            run.exit_seen = t
        if not run.eof and t - run.exit_seen < 5:
            return  # termina de leer lo que Blender dejó en la tubería
        self._pump()
        self._finish_run(job, run, rc)

    def _finish_run(self, job, run, rc):
        self.run = None
        t = util.now()
        if job is None:
            run.close_log(tr("shot quitado de la cola"))
            return
        for frame in list(run.pending_verify):
            if self._frame_verified(job, run, frame) is not False:
                self._accept_frame(job, run, frame)
        job["pid"] = None
        job["render_seconds"] = round(job.get("render_seconds", 0.0) + (t - run.started), 1)
        job.pop("render_seconds_live", None)
        left = [f for f in self.targets(job) if f not in set(util.from_ranges(job.get("done")))]
        if run.user_stop:
            job["status"] = "paused"
            run.close_log(tr("pausado por el usuario"))
            self._mark()
            return
        if not left:
            job["status"], job["finished_at"] = "done", t
            if run.forced_exit:
                job.setdefault("history", []).append({"t": t, "reason": run.kill_reason})
            run.close_log(tr("shot terminado (Blender se cerró a la fuerza)") if run.forced_exit else tr("shot terminado"))
            log.info("Terminado %s", job["name"])
            self._event("shot_done", tr("Shot terminado"), tr("{name} · {n} frames en {time}", name=job["name"],
                        n=job.get("done_count", 0), time=util.fmt_duration(job.get("render_seconds"))), job["id"])
            self._mark()
            return
        job["failures"] = int(job.get("failures", 0)) + 1
        if run.kill_reason:
            reason = run.kill_reason
        elif rc == bl.SAFETY_EXIT_CODE:
            reason = tr("El script de arranque falló: Blender se cerró sin renderizar (seguridad)")
        elif rc != 0:
            reason = tr("Blender se cerró inesperadamente (código {rc}) en el frame {frame}", rc=rc,
                        frame=job.get("current_frame"))
        else:
            reason = tr("Blender terminó pero faltan frames en disco")
        detail = " | ".join(list(run.errors)[-3:])
        job.setdefault("history", []).append({"t": t, "reason": reason, "rc": rc, "detail": detail,
                                              "frames_ok": len(run.done_in_run), "log": str(run.log_path)})
        job["history"] = job["history"][-20:]
        nxt = min(left)
        if job["failures"] >= int(self.settings["max_attempts"]):
            job["status"] = "failed"
            job["error"] = f"{reason}. {detail}".strip(". ")
            run.close_log(tr("FALLÓ tras {n} intentos: {reason}", n=job["failures"], reason=reason))
            log.warning("Falló %s: %s", job["name"], reason)
            self._event("job_failed", tr("Shot fallido"), f"{job['name']} · {reason}", job["id"])
        else:
            job["status"] = "ready"
            job["error"] = tr("{reason}. Sigue desde el frame {frame}.", reason=reason, frame=nxt)
            run.close_log(tr("{reason}. Se reintenta desde el frame {frame}", reason=reason, frame=nxt))
            log.warning("Reintento %s: %s", job["name"], reason)
        self._mark()

    def _finish_queue(self):
        q = self.state["queue"]
        q["running"] = False
        try:
            path = report.write_report(self.state, q.get("started_at"))
            self.state["last_report"] = str(path)
        except Exception:  # noqa: BLE001
            log.error("No se pudo escribir el informe:\n%s", traceback.format_exc())
        enabled = [j for j in self.state["jobs"] if j.get("enabled", True)]
        n_done = sum(j["status"] == "done" for j in enabled)
        n_fail = sum(j["status"] == "failed" for j in enabled)
        frames = sum(j.get("done_count", 0) for j in enabled)
        took = util.fmt_duration(util.now() - q["started_at"]) if q.get("started_at") else "—"
        text = tr("{done} de {total} shots · {frames} frames · {time}", done=n_done, total=len(enabled),
                  frames=frames, time=took)
        if n_fail:
            text += " · " + tr("{n} con fallos", n=n_fail)
        self._event("queue_done", tr("Cola terminada") if not n_fail else tr("Cola terminada con fallos"), text)
        action = q.get("after", "none")
        if action != "none":
            wait = float(self.settings["countdown_seconds"])
            self.state["countdown"] = {"action": action, "deadline": util.now() + wait, "total": wait}
        log.info("Cola terminada (después: %s)", action)
        self._mark()

    def _countdown_tick(self):
        cd = self.state["countdown"]
        if not cd or util.now() < cd["deadline"]:
            return
        action = cd["action"]
        self.state["countdown"] = None
        self.state["queue"]["after"] = "none"  # que no se repita tras reiniciar
        self._save(force=True)
        log.info("Acción al terminar la cola: %s", action)
        if os.environ.get("FRAMEGUARD_DRY_POWER"):
            log.info("FRAMEGUARD_DRY_POWER: no se ejecuta %s", action)
            return
        if action == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "5", "/c", tr("Frameguard: la cola de render terminó")],
                             creationflags=bl.CREATE_NO_WINDOW)
        elif action == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "5", "/c", tr("Frameguard: la cola de render terminó")],
                             creationflags=bl.CREATE_NO_WINDOW)
        elif action == "sleep":
            ctypes.windll.powrprof.SetSuspendState(False, False, False)

    def _keep_awake(self, on: bool):
        if self._awake == on:
            return
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
        self._awake = on

    def _idle_exit(self):
        busy = (self.run or self.state["queue"]["running"] or self.state["countdown"]
                or any(j["status"] == "reading" for j in self.state["jobs"]))
        if not busy and util.now() - self.last_client > 15 * 60:
            log.info("Sin ventana conectada y sin trabajo: el motor se cierra")
            self.stop_event.set()

    # ---------------------------------------------------------------- comandos de la ventana
    def command(self, cmd: str, a: dict) -> dict:
        with self.lock:
            fn = getattr(self, "cmd_" + cmd, None)
            if fn is None:
                return {"ok": False, "error": tr("Comando desconocido: {cmd}", cmd=cmd)}
            res = fn(**a) or {}
            self._mark()
            self._save(force=True)
            return {"ok": True, **res}

    def cmd_set_range(self, id: str = "", start: int | None = None, end: int | None = None, **_):  # noqa: A002
        """Renderizar solo una parte del shot (None/None = el rango de la escena)."""
        j = self.job(id)
        if j and not (self.run and self.run.job_id == id):
            j["range"] = [int(start), int(end)] if start is not None and end is not None else None
            j["frames_total"] = len(self.targets(j)) if j.get("info") else 0
        return {}

    def cmd_add(self, paths_: list[str] = None, test: dict | None = None, mode: str = "full",
                range: list[int] | None = None, scene: str | None = None, **_):  # noqa: A002
        added, skipped = [], []
        for p in paths_ or []:
            p = os.path.normpath(p)
            if any(os.path.normcase(j["path"]) == os.path.normcase(p) and j["status"] not in ("done", "failed")
                   for j in self.state["jobs"]):
                skipped.append(p)
                continue
            j = {"id": uuid.uuid4().hex[:12], "path": p, "name": Path(p).stem, "enabled": True,
                 "status": "reading", "mode": mode, "done": [], "done_count": 0, "frames_total": 0,
                 "failures": 0, "history": [], "warnings": [], "added_at": util.now()}
            if test:
                j["test"] = test
            if range:
                j["range"] = [int(range[0]), int(range[1])]
            if scene:
                j["scene"] = scene
            self.state["jobs"].append(j)
            self._submit_inspect(j)
            added.append(j["id"])
        return {"added": added, "skipped": skipped}

    def cmd_load_queue(self, items: list[dict] | None = None, replace: bool = False, **_):
        """Carga una cola guardada. Cada shot vuelve a leerse y empieza de cero (para re-renderizar)."""
        if replace:
            if self.run or self.state["queue"]["running"]:
                return {"ok": False, "error": tr("Pausa la cola antes de reemplazarla.")}
            self.state["jobs"] = []
        added, missing = [], []
        for it in items or []:
            p = os.path.normpath(it.get("path", ""))
            if not os.path.isfile(p):
                missing.append(p)
                continue
            res = self.cmd_add(paths_=[p], mode=it.get("mode", "full"), range=it.get("range"),
                               scene=it.get("scene"))
            for jid in res["added"]:
                self.job(jid)["enabled"] = bool(it.get("enabled", True))
                added.append(jid)
        return {"added": added, "missing": missing}

    def cmd_clear(self, keep_current: bool = False, **_):
        """Vacía la cola. Con la cola corriendo solo se permite con keep_current: se queda el shot que se
        está renderizando y se quitan todos los demás."""
        if self.run or self.state["queue"]["running"]:
            if not keep_current:
                return {"ok": False, "error": tr("La cola está renderizando: pausa la cola para vaciarla entera.")}
            cur = self.run.job_id if self.run else None
            self.state["jobs"] = [j for j in self.state["jobs"] if j["id"] == cur]
            return {"kept": 1 if cur else 0}
        self.state["jobs"] = []
        return {}

    def cmd_scan(self, folder: str = "", **_):
        return {"items": scan.scan_folder(folder)}

    def cmd_start(self, **_):
        q = self.state["queue"]
        if not q["running"]:
            q["running"] = True
            q["started_at"] = util.now()
            self.state["countdown"] = None
        return {}

    def cmd_pause(self, **_):
        self.state["queue"]["running"] = False
        if self.run:
            self.run.user_stop = True
            self.run.kill(tr("Pausado por el usuario"))
        return {}

    def cmd_remove(self, id: str = "", **_):  # noqa: A002
        if self.run and self.run.job_id == id:
            return {"ok": False, "error": tr("Pausa la cola antes de quitar el shot que se está renderizando.")}
        self.state["jobs"] = [j for j in self.state["jobs"] if j["id"] != id]
        return {}

    def cmd_clear_finished(self, **_):
        self.state["jobs"] = [j for j in self.state["jobs"] if j["status"] != "done"]
        return {}

    def cmd_move(self, id: str = "", index: int = 0, **_):  # noqa: A002
        jobs = self.state["jobs"]
        j = self.job(id)
        if j is None:
            return {}
        jobs.remove(j)
        jobs.insert(max(0, min(int(index), len(jobs))), j)
        return {}

    def cmd_enable(self, id: str = "", enabled: bool = True, **_):  # noqa: A002
        j = self.job(id)
        if j:
            j["enabled"] = bool(enabled)
        return {}

    def cmd_retry(self, id: str = "", **_):  # noqa: A002
        j = self.job(id)
        if j and j["status"] in ("failed", "paused", "done", "ready"):
            j.update(status="ready", failures=0, error=None)
        return {}

    def cmd_rerender(self, id: str = "", **_):  # noqa: A002
        """Vuelve a renderizar todo el shot desde cero."""
        j = self.job(id)
        if j and not (self.run and self.run.job_id == id):
            j.update(status="ready", failures=0, error=None, done=[], done_count=0, disk_checked=False,
                     runtime_outputs=None)
        return {}

    def cmd_set_mode(self, id: str = "", mode: str = "full", **_):  # noqa: A002
        j = self.job(id)
        if j and mode in ("full", "missing"):
            j["mode"], j["disk_checked"] = mode, False
        return {}

    def cmd_reinspect(self, id: str = "", scene: str | None = None, **_):  # noqa: A002
        j = self.job(id)
        if j and not (self.run and self.run.job_id == id):
            if scene:
                j["scene"] = scene
            self._submit_inspect(j)
        return {}

    def cmd_set_after(self, action: str = "none", **_):
        if action in ("none", "shutdown", "sleep", "restart"):
            self.state["queue"]["after"] = action
        return {}

    def cmd_countdown_now(self, **_):
        """«Apagar ahora» en la cuenta atrás: no espera lo que queda."""
        if self.state["countdown"]:
            self.state["countdown"]["deadline"] = util.now()
        return {}

    def cmd_cancel_countdown(self, **_):
        self.state["countdown"] = None
        self.state["queue"]["after"] = "none"
        return {}

    def cmd_settings(self, values: dict | None = None, **_):
        before = (bool(self.settings.get("limit_resources")), self.settings.get("limit_percent"))
        for k, v in (values or {}).items():
            if k in DEFAULT_SETTINGS:
                self.settings[k] = v
        after = (bool(self.settings.get("limit_resources")), self.settings.get("limit_percent"))
        i18n.set_lang(self.settings.get("language"))
        if after != before and self.run:  # el Blender que ya renderiza cambia al momento
            note = limits.apply(self.run.popen.pid, after[0], after[1])
            log.info("Límite de recursos cambiado en caliente: %s", note)
            try:
                self.run._log.write(time.strftime("%H:%M:%S ") + "[frameguard] " + tr("recursos: {note}", note=note) + "\n")
                self.run._log.flush()
            except (OSError, ValueError):
                pass
        return {}

    def cmd_quit(self, **_):
        if self.run or self.state["queue"]["running"]:
            return {"ok": False, "error": tr("La cola está corriendo: el motor no se cierra.")}
        self.stop_event.set()
        return {}

    # ---------------------------------------------------------------- foto del estado
    def snapshot(self) -> dict:
        with self.lock:
            jobs = json.loads(json.dumps(self.state["jobs"]))
            total_frames = done_frames = 0
            eta = 0.0
            avgs = [j["avg_frame"] for j in jobs if j.get("avg_frame")]
            global_avg = sum(avgs) / len(avgs) if avgs else None
            for j in jobs:
                if not j.get("enabled", True):
                    continue
                total_frames += j.get("frames_total", 0)
                done_frames += j.get("done_count", 0)
                left = max(0, j.get("frames_total", 0) - j.get("done_count", 0))
                avg = j.get("avg_frame") or global_avg
                j["eta"] = round(left * avg, 1) if (avg and left and j["status"] != "failed") else None
                if j["eta"] and j["status"] in ("ready", "paused", "rendering", "reading"):
                    eta += j["eta"]
            enabled = [j for j in jobs if j.get("enabled", True)]
            cd = self.state["countdown"]
            return {
                "app": APP_NAME, "version": __version__, "pid": os.getpid(),
                "uptime": round(util.now() - self.started_at),
                "settings": self.settings, "queue": self.state["queue"], "jobs": jobs,
                "running_job": self.run.job_id if self.run else None,
                "countdown": {"action": cd["action"], "seconds": max(0, round(cd["deadline"] - util.now())),
                              "total": round(cd.get("total") or self.settings["countdown_seconds"])} if cd else None,
                "last_report": self.state.get("last_report"),
                "events": list(self.events), "now": util.now(),
                "totals": {"frames_done": done_frames, "frames_total": total_frames,
                           "jobs_done": sum(j["status"] == "done" for j in enabled), "jobs_total": len(enabled),
                           "eta": round(eta) if eta else None},
                "blenders": self._blenders(),
                "limit": self._limit_info(),
            }

    def _limit_info(self) -> dict | None:
        """Hilos que puede usar Blender con el límite activado (para mostrarlo en la ventana)."""
        if not self.settings.get("limit_resources"):
            return None
        n, total, _ = limits.plan(self.settings.get("limit_percent", 50))
        return {"threads": n, "total": total, "percent": int(self.settings.get("limit_percent", 50))}

    def _blenders(self) -> list[dict]:
        """Instalaciones de Blender, en caché 60 s (la ventana pregunta el estado cada 0,6 s)."""
        now = util.now()
        if not hasattr(self, "_bl_cache") or now - self._bl_cache[0] > 60:
            self._bl_cache = (now, bl.detect_blenders())
        return self._bl_cache[1]

    def tail(self, job_id: str, lines: int = 200) -> list[str]:
        j = self.job(job_id)
        if not j or not j.get("logs"):
            return []
        try:
            with open(j["logs"][-1], encoding="utf-8", errors="replace") as f:
                return f.read().splitlines()[-lines:]
        except OSError:
            return []


# -------------------------------------------------------------------- servidor HTTP local
def _handler_for(engine: Engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencio
            pass

        def _send(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            engine.last_client = util.now()
            u = urlparse(self.path)
            if u.path == "/api/ping":
                return self._send({"app": APP_NAME, "version": __version__, "pid": os.getpid()})
            if u.path == "/api/state":
                return self._send(engine.snapshot())
            if u.path == "/api/log":
                qs = parse_qs(u.query)
                return self._send({"lines": engine.tail(qs.get("id", [""])[0], int(qs.get("lines", ["200"])[0]))})
            self._send({"error": "no encontrado"}, 404)

        def do_POST(self):  # noqa: N802
            engine.last_client = util.now()
            if urlparse(self.path).path != "/api/cmd":
                return self._send({"error": "no encontrado"}, 404)
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n) or b"{}")
                cmd = body.pop("cmd", "")
                if "paths" in body:
                    body["paths_"] = body.pop("paths")
                self._send(engine.command(cmd, body))
            except Exception as e:  # noqa: BLE001
                log.error("Error en comando: %s", traceback.format_exc())
                self._send({"ok": False, "error": str(e)}, 500)

    return Handler


def run_engine(port: int = DEFAULT_PORT) -> int:
    _setup_logging()
    import faulthandler
    faulthandler.enable(open(paths.data_dir() / "engine_crash.log", "a", encoding="utf-8"))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), None)
    except OSError:
        log.info("Ya hay un motor escuchando en el puerto %s", port)
        return 0
    engine = Engine(port)
    server.RequestHandlerClass = _handler_for(engine)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Motor %s iniciado (pid %s, puerto %s)", __version__, os.getpid(), port)
    try:
        engine.loop()
    finally:
        server.shutdown()
        engine.pool.shutdown(wait=False, cancel_futures=True)
        log.info("Motor detenido")
    return 0


if __name__ == "__main__":
    sys.exit(run_engine())
