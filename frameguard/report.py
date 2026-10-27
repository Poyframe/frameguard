"""Informe de la mañana: un HTML sencillo con lo que pasó en la cola."""
import html
import time
from pathlib import Path

from . import __version__, i18n, paths, util
from .i18n import tr


def _status(st: str) -> str:
    return {"done": tr("Terminado"), "failed": tr("Falló"), "paused": tr("En pausa"), "ready": tr("En espera"),
            "rendering": tr("Renderizando"), "reading": tr("Leyendo"),
            "error_read": tr("No se pudo leer")}.get(st, st)


COLOR = {"done": "#1b8752", "failed": "#c2352d", "paused": "#9a6208", "error_read": "#c2352d"}


def write_report(state: dict, started_at: float | None) -> Path:
    stamp = time.strftime("%Y-%m-%d_%H%M")
    out = paths.reports_dir() / (tr("informe") + f"_{stamp}.html")
    rows = []
    totals = {"done": 0, "failed": 0, "frames": 0, "secs": 0.0}
    for j in state.get("jobs", []):
        if not j.get("enabled", True) and j.get("status") != "done":
            continue
        st = j.get("status", "")
        done = j.get("done_count", 0)
        total = j.get("frames_total", 0)
        secs = j.get("render_seconds", 0.0)
        totals["frames"] += done
        totals["secs"] += secs
        totals["done"] += st == "done"
        totals["failed"] += st == "failed"
        notes = [h.get("reason", "") for h in j.get("history", [])]
        if j.get("error"):
            notes.append(j["error"])
        warn = [w["text"] for w in j.get("warnings", []) if w.get("level") in ("warn", "error")]
        rows.append(
            "<tr><td><b>{n}</b><br><small>{p}</small></td><td style='color:{c}'>{s}</td>"
            "<td>{d} / {t}</td><td>{dur}</td><td>{f}</td><td>{notes}</td></tr>".format(
                n=html.escape(j.get("name", "")), p=html.escape(j.get("path", "")),
                c=COLOR.get(st, "#555"), s=_status(st), d=done, t=total,
                dur=util.fmt_duration(secs), f=j.get("failures", 0),
                notes="<br>".join(html.escape(x) for x in notes + warn if x) or "—"))
    head = time.strftime("%d/%m/%Y %H:%M")
    since = time.strftime("%d/%m/%Y %H:%M", time.localtime(started_at)) if started_at else "—"
    t = {"Informe de render": tr("Informe de render"), "Inicio de la cola": tr("Inicio de la cola"),
         "Shots terminados": tr("Shots terminados"), "Fallidos": tr("Fallidos"),
         "Frames renderizados": tr("Frames renderizados"), "Tiempo de render": tr("Tiempo de render"),
         "Estado": tr("Estado"), "Tiempo": tr("Tiempo"), "Fallos": tr("Fallos"), "Notas": tr("Notas")}
    doc = f"""<!doctype html><html lang="{i18n.lang()}"><meta charset="utf-8"><title>Frameguard — {head}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1f2328}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top;font-size:14px}}small{{color:#666}}
.k{{display:inline-block;margin-right:24px}}</style>
<h2>{t["Informe de render"]} — {head}</h2>
<p><span class="k">{t["Inicio de la cola"]}: <b>{since}</b></span><span class="k">{t["Shots terminados"]}: <b>{totals['done']}</b></span>
<span class="k">{t["Fallidos"]}: <b>{totals['failed']}</b></span><span class="k">{t["Frames renderizados"]}: <b>{totals['frames']}</b></span>
<span class="k">{t["Tiempo de render"]}: <b>{util.fmt_duration(totals['secs'])}</b></span></p>
<table><tr><th>Shot</th><th>{t["Estado"]}</th><th>Frames</th><th>{t["Tiempo"]}</th><th>{t["Fallos"]}</th><th>{t["Notas"]}</th></tr>
{''.join(rows)}</table><p><small>Frameguard {__version__}</small></p></html>"""
    out.write_text(doc, encoding="utf-8")
    return out
