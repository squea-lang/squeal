"""Конвейер компиляции: source → IR → проверки → формы → .beam."""

from __future__ import annotations

import pathlib
import subprocess

from . import backend, checks, frontend
from .errors import SquealError
from .term import Atom, term_to_erlang

ESCRIPT = pathlib.Path(__file__).parent / "squeal_compile.escript"


def compile_source(source: str, path: str, name: str) -> list:
    """Исходник → Erlang-формы (значения Python)."""
    try:
        module = frontend.parse_module(source, path, name)
        checks.check(module)
        return backend.module_forms(module)
    except SquealError as e:
        msg = str(e)
        if not msg.startswith(f"{path}:"):
            raise SquealError(f"{path}:{msg}") from e
        raise


def module_name(relative_path: pathlib.PurePath) -> str:
    """``src/a/b/c.ee`` → ``a@b@c``; ``src/hello.ee`` → ``hello``."""
    return "@".join(relative_path.with_suffix("").parts)


def build(root: str | pathlib.Path) -> pathlib.Path:
    """Компилирует ``src/*.ee`` в ``build/dev/erlang/<app>/ebin``."""
    root = pathlib.Path(root).resolve()
    src = root / "src"
    app = root.name
    out = root / "build" / "dev" / "erlang" / app
    abstr_dir = out / "_squeal_artefacts"
    ebin = out / "ebin"
    abstr_dir.mkdir(parents=True, exist_ok=True)
    ebin.mkdir(parents=True, exist_ok=True)

    modules = []
    for path in sorted(src.glob("**/*.ee")):
        rel = path.relative_to(src)
        name = module_name(rel)
        modules.append(name)
        source_path = path.relative_to(root)
        forms = compile_source(path.read_text(), str(source_path), name)

        abstr = abstr_dir / f"{name}.abstr"
        abstr.write_text("".join(term_to_erlang(f) + ".\n" for f in forms))

        base = ebin / name
        subprocess.run(
            ["escript", str(ESCRIPT), str(abstr), str(base), name, str(source_path)],
            check=True,
        )

    app_spec = (
        Atom("application"),
        Atom(app),
        [
            (Atom("vsn"), "0.1.0"),
            (Atom("modules"), [Atom(m) for m in modules]),
            (Atom("registered"), []),
            (Atom("applications"), [Atom("kernel"), Atom("stdlib")]),
        ],
    )
    (ebin / f"{app}.app").write_text(term_to_erlang(app_spec) + ".\n")
    return out
