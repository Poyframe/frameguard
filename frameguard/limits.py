"""Límite de recursos del render: cuántos hilos del procesador puede usar Blender y con qué prioridad.

Se hace con la afinidad del proceso (Blender solo puede usar ciertos hilos) y prioridad baja (Windows atiende
antes al resto de programas). Se aplica al lanzar Blender y también en caliente al que ya está renderizando.

Lo que NO se limita, a propósito:
- La tarjeta gráfica (EEVEE, Cycles con GPU): Windows no ofrece una forma estable de limitarla.
- La memoria RAM: ponerle un tope haría que Blender se cerrara a mitad del render.
"""
import ctypes
import os
from ctypes import wintypes

from .i18n import tr

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS = 0x00000020
_ACCESS = 0x0200 | 0x0400  # PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION

# Instancia propia de kernel32: los argtypes de aquí no afectan a otros usos de ctypes.windll.kernel32
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.GetCurrentProcess.restype = wintypes.HANDLE
_k32.GetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t),
                                        ctypes.POINTER(ctypes.c_size_t)]
_k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
_k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]


def system_mask() -> int:
    """Hilos del procesador que Windows deja usar (bits de la máscara)."""
    proc, system = ctypes.c_size_t(), ctypes.c_size_t()
    if _k32.GetProcessAffinityMask(_k32.GetCurrentProcess(), ctypes.byref(proc), ctypes.byref(system)) \
            and system.value:
        return system.value
    return (1 << min(os.cpu_count() or 1, 64)) - 1


def plan(percent: int) -> tuple[int, int, int]:
    """(hilos para Blender, hilos totales, máscara). Blender se queda con los ÚLTIMOS hilos: los primeros,
    donde Windows atiende la mayoría de interrupciones, quedan libres para el resto del PC."""
    bits = [i for i in range(64) if system_mask() >> i & 1]
    n = max(1, min(len(bits), round(len(bits) * int(percent) / 100)))
    mask = 0
    for i in bits[-n:]:
        mask |= 1 << i
    return n, len(bits), mask


def apply(pid: int, limited: bool, percent: int) -> str:
    """Aplica (o quita) el límite a un proceso en marcha. Devuelve una descripción para el log."""
    h = _k32.OpenProcess(_ACCESS, False, int(pid))
    if not h:
        return tr("no se pudo ajustar el proceso {pid} (error {code})", pid=pid, code=ctypes.get_last_error())
    try:
        if limited:
            n, total, mask = plan(percent)
            ok = _k32.SetProcessAffinityMask(h, mask) and _k32.SetPriorityClass(h, BELOW_NORMAL_PRIORITY_CLASS)
            desc = tr("limitado a {n} de {total} hilos del procesador, prioridad baja", n=n, total=total)
        else:
            ok = _k32.SetProcessAffinityMask(h, system_mask()) and _k32.SetPriorityClass(h, NORMAL_PRIORITY_CLASS)
            desc = tr("sin límite de recursos")
        return desc if ok else tr("no se pudo aplicar el límite (error {code})", code=ctypes.get_last_error())
    finally:
        _k32.CloseHandle(h)
