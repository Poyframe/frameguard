"""Comprueba las traducciones antes de compilar:
- todo texto en tr("...") / plural(n, "...", "...") tiene su versión en inglés (frameguard/i18n_en.py);
- nadie pasa un f-string a tr() (no se podría traducir: hay que usar tr("... {x}", x=...));
- las variables {x} del texto en inglés son las mismas que en el español;
- avisa de traducciones que ya no se usan.
Sale con código 1 si hay problemas."""
import ast
import re
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from frameguard.i18n_en import EN  # noqa: E402

FIELDS = string.Formatter()


def fields(s: str) -> set[str]:
    return {f for _, f, _, _ in FIELDS.parse(s) if f}


def used_texts() -> tuple[dict[str, str], list[str]]:
    """{texto: dónde se usa} de todas las llamadas a tr()/plural(), y los problemas encontrados."""
    used: dict[str, str] = {}
    problems = []
    for py in sorted((ROOT / "frameguard").rglob("*.py")):
        if py.name in ("i18n_en.py", "i18n.py"):  # i18n.py define tr/plural (llamadas internas con variables)
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"), str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if name not in ("tr", "plural"):
                continue
            args = node.args[:1] if name == "tr" else node.args[1:3]
            for a in args:
                where = f"{py.relative_to(ROOT)}:{node.lineno}"
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    used[a.value] = where
                elif isinstance(a, ast.JoinedStr):
                    problems.append(f"{where}: f-string dentro de {name}() (usa tr('... {{x}}', x=...))")
                else:
                    problems.append(f"{where}: {name}() con un texto que no es literal")
    return used, problems


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no imprime «», → ni acentos
    used, problems = used_texts()
    for text, where in sorted(used.items(), key=lambda kv: kv[1]):
        if text not in EN:
            problems.append(f"{where}: falta la traducción de {text!r}")
        elif fields(text) != fields(EN[text]):
            problems.append(f"{where}: variables distintas en {text!r} -> {EN[text]!r}")
    unused = [t for t in EN if t not in used]
    for p in problems:
        print(p)
    print(f"Traducciones: {len(used)} textos en uso, {len(problems)} problema(s), {len(unused)} sin usar")
    for t in unused[:20]:
        print("  sin usar:", repr(t)[:90])
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
