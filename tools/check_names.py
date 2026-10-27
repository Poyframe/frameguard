"""Chequeo previo a compilar: busca nombres usados que no están definidos en ningún sitio
(variables mal escritas, código pegado fuera de su función, imports que faltan).
Sale con código 1 si encuentra alguno."""
import builtins
import symtable
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frameguard"
SKIP = {"blender_scripts"}  # corren dentro de Blender (bpy), se revisan aparte
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__package__", "__builtins__",
                                 "SPECPATH", "Analysis", "PYZ", "EXE", "COLLECT"}


def module_names(top: symtable.SymbolTable) -> set[str]:
    return {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()
            or s.is_namespace()}


def walk(table, defined, path, problems):
    for sym in table.get_symbols():
        name = sym.get_name()
        if sym.is_referenced() and sym.is_global() and not sym.is_declared_global():
            if name not in defined and name not in BUILTINS:
                problems.append(f"{path}: «{name}» no está definido (en {table.get_name()})")
    for child in table.get_children():
        walk(child, defined, path, problems)


def main() -> int:
    problems = []
    for f in sorted(ROOT.rglob("*.py")):
        if SKIP & set(f.relative_to(ROOT).parts):
            continue
        src = f.read_text(encoding="utf-8")
        top = symtable.symtable(src, str(f), "exec")
        walk(top, module_names(top), f.relative_to(ROOT.parent), problems)
    for p in problems:
        print("ERROR", p)
    print(f"Nombres revisados: {'sin problemas' if not problems else f'{len(problems)} problema(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
