"""
Guardia de secretos: evita que un token o clave real vuelva a quedar
committeado en el repo.

Escanea los archivos versionados (`git ls-files`) más los que están en
staging (`git diff --cached --name-only`) en busca de patrones con forma
de secreto (tokens de bot de Telegram, claves tipo api_key/secret_key/
token_key) y, específicamente en `.env.example`, cualquier valor que no
sea un placeholder reconocible.

Solo depende de la librería estándar (re, subprocess, sys, pathlib) -
sin dependencias nuevas.

Uso:
    python scripts/check_no_secrets.py
    # exit 0 -> repo limpio
    # exit 1 -> imprime "archivo:linea" por cada hallazgo
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TELEGRAM_TOKEN_RE = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35}")
GENERIC_SECRET_RE = re.compile(
    r"""(api|secret|token)[_-]?key\s*[:=]\s*['"][A-Za-z0-9_\-]{20,}['"]""",
    re.IGNORECASE,
)

# Extensiones que nunca contienen secretos de texto plano y no vale la
# pena leer (binarios, bases de datos, empaquetados).
_EXCLUDED_SUFFIXES = {
    ".db", ".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".pdf",
}
_MAX_FILE_BYTES = 2_000_000


def _is_placeholder(value: str) -> bool:
    """True si `value` tiene pinta de placeholder (no un secreto real)."""
    value = value.strip()
    if value == "":
        return True
    lowered = value.lower()
    if lowered.startswith("your-") and lowered.endswith("-here"):
        return True
    if lowered in {"changeme", "change_me", "placeholder", "xxx", "todo"}:
        return True
    if value.startswith("<") and value.endswith(">"):
        return True
    return False


def check_env_example_line(line: str) -> bool:
    """True si esta línea de .env.example asigna un valor no-placeholder."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return False
    _, _, value = stripped.partition("=")
    return not _is_placeholder(value)


def check_line(line: str) -> bool:
    """True si la línea contiene un secreto con forma reconocible."""
    return bool(TELEGRAM_TOKEN_RE.search(line) or GENERIC_SECRET_RE.search(line))


def get_files_to_scan() -> list[str]:
    """Archivos versionados + en staging, filtrando binarios y grandes."""
    tracked = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()

    candidates = sorted(set(tracked) | set(staged))
    result = []
    for name in candidates:
        path = Path(name)
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() in _EXCLUDED_SUFFIXES:
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        result.append(name)
    return result


def scan_paths(paths: list[str]) -> list[tuple[str, int]]:
    """Devuelve [(archivo, numero_de_linea), ...] por cada hallazgo."""
    findings: list[tuple[str, int]] = []
    for name in paths:
        path = Path(name)
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        is_env_example = path.name == ".env.example"
        for lineno, line in enumerate(text.splitlines(), start=1):
            suspicious = (
                check_env_example_line(line) if is_env_example else check_line(line)
            )
            if suspicious:
                findings.append((name, lineno))
    return findings


def main(files: list[str] | None = None) -> int:
    paths = files if files is not None else get_files_to_scan()
    findings = scan_paths(paths)
    if findings:
        for name, lineno in findings:
            print(f"{name}:{lineno}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
