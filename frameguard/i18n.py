"""Idioma de Frameguard: español o inglés.

Por defecto se usa el idioma de Windows del equipo (español si Windows está en español; inglés en cualquier
otro idioma). El usuario puede fijarlo en Ajustes. Lo usan la ventana y el motor (que genera avisos y errores).

En el código los textos se escriben en español y se envuelven en tr("..."); en inglés se buscan en EN
(i18n_en.py). Con variables: tr("Se encontraron {n} archivos", n=3). Si faltara una traducción se muestra el
texto en español en vez de fallar; tools/check_i18n.py lo comprueba antes de compilar.
"""
import ctypes
import os

LANGUAGES = ("es", "en")
_lang: str | None = None


def system_lang() -> str:
    """Idioma de la interfaz de Windows: «es» si es cualquier variante de español, si no «en»."""
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return "en"
    return "es" if (langid & 0x3FF) == 0x0A else "en"  # 0x0A = LANG_SPANISH (idioma principal)


def resolve(pref: str | None) -> str:
    return pref if pref in LANGUAGES else system_lang()


def set_lang(pref: str | None):
    """pref: «auto» (el de Windows), «es» o «en». FRAMEGUARD_LANG lo fuerza (pruebas)."""
    global _lang
    _lang = resolve(os.environ.get("FRAMEGUARD_LANG") or pref)


def lang() -> str:
    if _lang is None:
        set_lang("auto")
    return _lang


def tr(text: str, **values) -> str:
    if lang() != "es":
        from .i18n_en import EN
        text = EN.get(text, text)
    return text.format(**values) if values else text


def fmt_int(n: int) -> str:
    """1.234 en español, 1,234 en inglés."""
    s = f"{int(n):,}"
    return s.replace(",", ".") if lang() == "es" else s


def plural(n: int, one: str, many: str, **values) -> str:
    """tr con singular/plural: plural(n, "{n} archivo", "{n} archivos")."""
    return tr(one if n == 1 else many, n=n, **values)
