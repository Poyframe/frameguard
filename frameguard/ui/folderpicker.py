"""Selector nativo de Windows para elegir VARIAS carpetas a la vez.

Qt solo deja elegir una carpeta; el explorador de Windows (IFileOpenDialog con FOS_PICKFOLDERS y
FOS_ALLOWMULTISELECT) permite marcar varias con Ctrl o Shift. Se habla con él por COM a través de ctypes.
Si algo falla, pick_folders devuelve None y la ventana usa el selector de Qt de una sola carpeta."""
import ctypes
import os
import uuid
from ctypes import POINTER, byref, c_long, c_void_p, wintypes

FOS_PICKFOLDERS, FOS_FORCEFILESYSTEM, FOS_ALLOWMULTISELECT, FOS_PATHMUSTEXIST = 0x20, 0x40, 0x200, 0x800
SIGDN_FILESYSPATH = 0x80058000
CANCELLED = -2147023673  # HRESULT_FROM_WIN32(ERROR_CANCELLED)

# índices en la tabla de métodos (vtable) de cada interfaz COM
_RELEASE = 2
_SHOW = 3                                   # IModalWindow
_SET_OPTIONS, _GET_OPTIONS, _SET_FOLDER = 9, 10, 12
_SET_TITLE, _SET_OK_LABEL = 17, 18          # IFileDialog
_GET_RESULTS = 27                           # IFileOpenDialog
_ARRAY_COUNT, _ARRAY_ITEM = 7, 8            # IShellItemArray
_ITEM_NAME = 5                              # IShellItem.GetDisplayName


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text: str) -> "_GUID":
        u = uuid.UUID(text)
        return cls(u.time_low, u.time_mid, u.time_hi_version, (ctypes.c_ubyte * 8)(*u.bytes[8:]))


CLSID_FILE_OPEN_DIALOG = _GUID.of("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
IID_IFILE_OPEN_DIALOG = _GUID.of("D57C7288-D4AD-4768-BE02-9D969532D960")
IID_ISHELL_ITEM = _GUID.of("43826D1E-E718-42EE-BC55-A1E261C37BFE")

_ole32 = ctypes.WinDLL("ole32")
_ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = c_long
_ole32.CoUninitialize.argtypes = []
_ole32.CoCreateInstance.argtypes = [POINTER(_GUID), c_void_p, wintypes.DWORD, POINTER(_GUID), POINTER(c_void_p)]
_ole32.CoCreateInstance.restype = c_long
_ole32.CoTaskMemFree.argtypes = [c_void_p]
_shell32 = ctypes.WinDLL("shell32")
_shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(_GUID), POINTER(c_void_p)]
_shell32.SHCreateItemFromParsingName.restype = c_long


def _call(obj: c_void_p, index: int, *args, argtypes=()):
    """Llama al método `index` de la interfaz COM `obj` y devuelve su HRESULT."""
    vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(c_long, c_void_p, *argtypes)(vtable[index])
    return fn(obj, *args)


def _release(obj: c_void_p):
    if obj and obj.value:
        _call(obj, _RELEASE)


def pick_folders(hwnd: int, title: str, start: str = "", ok_label: str = "Agregar") -> list[str] | None:
    """Carpetas elegidas ([] si el usuario cancela). None si el selector nativo no está disponible."""
    init = _ole32.CoInitializeEx(None, 0x2)  # el hilo de Qt ya tiene COM: devuelve S_FALSE y no pasa nada
    dlg = c_void_p()
    try:
        if _ole32.CoCreateInstance(byref(CLSID_FILE_OPEN_DIALOG), None, 1, byref(IID_IFILE_OPEN_DIALOG),
                                   byref(dlg)) != 0:
            return None
        opts = wintypes.DWORD()
        _call(dlg, _GET_OPTIONS, byref(opts), argtypes=(POINTER(wintypes.DWORD),))
        flags = opts.value | FOS_PICKFOLDERS | FOS_ALLOWMULTISELECT | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
        if _call(dlg, _SET_OPTIONS, flags, argtypes=(wintypes.DWORD,)) != 0:
            return None
        _call(dlg, _SET_TITLE, title, argtypes=(wintypes.LPCWSTR,))
        _call(dlg, _SET_OK_LABEL, ok_label, argtypes=(wintypes.LPCWSTR,))
        if start and os.path.isdir(start):
            start = os.path.normpath(start)  # con barras «/» Windows no reconoce la carpeta inicial
            item = c_void_p()
            if _shell32.SHCreateItemFromParsingName(start, None, byref(IID_ISHELL_ITEM), byref(item)) == 0:
                _call(dlg, _SET_FOLDER, item, argtypes=(c_void_p,))
                _release(item)
        hr = _call(dlg, _SHOW, hwnd, argtypes=(wintypes.HWND,))
        if hr == CANCELLED:
            return []
        if hr != 0:
            return None
        arr = c_void_p()
        if _call(dlg, _GET_RESULTS, byref(arr), argtypes=(POINTER(c_void_p),)) != 0:
            return None
        try:
            count = wintypes.DWORD()
            _call(arr, _ARRAY_COUNT, byref(count), argtypes=(POINTER(wintypes.DWORD),))
            out = []
            for i in range(count.value):
                item = c_void_p()
                if _call(arr, _ARRAY_ITEM, i, byref(item), argtypes=(wintypes.DWORD, POINTER(c_void_p))) != 0:
                    continue
                name = c_void_p()
                if _call(item, _ITEM_NAME, SIGDN_FILESYSPATH, byref(name),
                         argtypes=(wintypes.DWORD, POINTER(c_void_p))) == 0 and name.value:
                    out.append(ctypes.wstring_at(name.value))
                    _ole32.CoTaskMemFree(name)
                _release(item)
            return out
        finally:
            _release(arr)
    except OSError:
        return None
    finally:
        _release(dlg)
        if init in (0, 1):
            _ole32.CoUninitialize()
