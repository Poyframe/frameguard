"""Sonidos de aviso de Frameguard, sintetizados por el propio programa (sin archivos externos).

- shot_done:  dos notas ascendentes cortas (un shot terminó)
- queue_done: arpegio ascendente más largo (terminó toda la cola)
- job_failed: dos notas descendentes graves (un shot falló)
Se generan como WAV en %APPDATA%\\Frameguard\\sonidos la primera vez y se reproducen sin bloquear."""
import math
import struct
import wave

from . import paths

RATE = 44100
VERSION = 1  # subir si cambian los sonidos para regenerarlos

# (frecuencia Hz, inicio s, duración s, volumen)
SOUNDS = {
    "shot_done": [(659.25, 0.00, 0.55, 0.55), (987.77, 0.11, 0.75, 0.50)],
    "queue_done": [(523.25, 0.00, 0.9, 0.45), (659.25, 0.12, 0.9, 0.45), (783.99, 0.24, 0.9, 0.45),
                   (1046.50, 0.38, 1.3, 0.50)],
    "job_failed": [(440.00, 0.00, 0.55, 0.50), (311.13, 0.18, 0.85, 0.50)],
}


def _synth(notes) -> bytes:
    length = max(start + dur for _, start, dur, _ in notes) + 0.05
    n = int(length * RATE)
    buf = [0.0] * n
    for freq, start, dur, vol in notes:
        s0 = int(start * RATE)
        for i in range(int(dur * RATE)):
            t = i / RATE
            # campanita: fundamental + armónicos suaves, ataque rápido y caída exponencial
            env = min(1.0, t / 0.006) * math.exp(-t * 5.5 / dur)
            v = (math.sin(2 * math.pi * freq * t) + 0.35 * math.sin(4 * math.pi * freq * t)
                 + 0.12 * math.sin(6 * math.pi * freq * t)) / 1.47
            if s0 + i < n:
                buf[s0 + i] += v * env * vol
    peak = max(1e-9, max(abs(x) for x in buf))
    scale = 0.85 / peak if peak > 0.85 else 1.0
    return b"".join(struct.pack("<h", int(max(-1, min(1, x * scale)) * 32767)) for x in buf)


def sound_path(kind: str):
    return paths.sub("sonidos") / f"{kind}_v{VERSION}.wav"


def ensure_sounds() -> None:
    for kind, notes in SOUNDS.items():
        p = sound_path(kind)
        if p.exists():
            continue
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(_synth(notes))


def play(kind: str) -> None:
    """Reproduce sin bloquear. Nunca lanza excepción (un sonido no debe romper nada)."""
    try:
        import winsound
        ensure_sounds()
        p = sound_path(kind)
        if p.exists():
            winsound.PlaySound(str(p), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:  # noqa: BLE001
        pass
