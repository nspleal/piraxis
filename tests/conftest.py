"""
Configuração compartilhada dos testes.

Garante a raiz do projeto no sys.path e isola o cache em uma pasta temporária
para que os testes não dependam (nem sujem) o cache real do projeto.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


@pytest.fixture(autouse=True)
def cache_temporario(tmp_path, monkeypatch):
    """Redireciona o CACHE_DIR das fontes para uma pasta temporária por teste."""
    import sources.base as base

    monkeypatch.setattr(base, "CACHE_DIR", tmp_path)
    return tmp_path
