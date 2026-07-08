"""
core/versao.py
==============

Versão da ferramenta, DINÂMICA — uma única fonte de verdade para o app, a
proveniência e o Excel (antes havia três versões estáticas divergentes:
"1.0" na proveniência, "0.1.0" no pyproject e nenhuma no app).

Precedência:
  1. ``Programa/VERSAO.txt`` — gravado pelo empacotador no pacote portátil
     (formato ``<sha_curto>-<AAAA-MM-DD>``): é a versão exata do build que o
     usuário final está rodando.
  2. O commit git corrente (``dev-<sha>``): ambiente de desenvolvimento.
  3. ``"dev"`` — sem VERSAO.txt e sem git (ex.: cópia solta da pasta).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_ARQ_VERSAO = BASE_DIR / "VERSAO.txt"


def versao_ferramenta() -> str:
    """Versão rastreável da ferramenta (ver precedência na docstring)."""
    try:
        if _ARQ_VERSAO.exists():
            v = _ARQ_VERSAO.read_text(encoding="utf-8").strip()
            if v:
                return v
    except OSError:  # pragma: no cover - leitura falhou; segue o fallback
        pass
    try:
        sha = subprocess.run(
            ["git", "-C", str(BASE_DIR), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()
        if sha:
            return f"dev-{sha}"
    except Exception:  # pragma: no cover - sem git instalado/repo
        pass
    return "dev"
