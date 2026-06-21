#!/usr/bin/env python3
"""
atualizar.py — atualizador LEVE do PIRAXIS (só a camada de código), fail-safe
=============================================================================

Chamado pelo launcher do pacote ANTES de subir o app. Objetivo: o pesquisador
recebe novas versões do **código** sem rebaixar o pacote inteiro, mantendo o
interpretador embutido estável — e **sem nunca quebrar** a abertura do app.

Modelo de DUAS CAMADAS:
  - runtime (python/ + dependências) = pesado, pinado, NÃO é tocado aqui;
  - código (app/ core/ sources/ output/ .streamlit/) = leve, é o que se atualiza.

Trava de dependências: um update de código só é aplicado se o ``requirements_hash``
remoto for IGUAL ao local — ou seja, se o runtime existente comporta o código novo.
Se as dependências mudaram, NÃO aplica e orienta a pedir o pacote completo.

Segurança: usa APENAS ``urllib`` (sem dependências extras) e APENAS URL HTTPS
pública (NUNCA token). Nunca toca ``python/``, ``cache/``, ``data/``, ``.env``
nem ``~/.radiacao_solar/``. Qualquer falha → sai 0 em silêncio (nunca bloqueia).

⚙️ Configuração:
  URL_ATUALIZACAO = "" → no-op (auto-update DESLIGADO). Seguro de fábrica.
  Para ligar, aponte para um manifesto.json PÚBLICO (ver empacotar.py / manifesto.json):
      { "versao": "...", "requirements_hash": "...", "url_zip": "https://.../PIRAXIS-codigo-<versao>.zip" }
  ⚠️ Se o repositório for PRIVADO, publique o zip num local público (ex.: Release
  de um repo público) — não embuta credenciais aqui.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# Vazio = atualizador é no-op (updates manuais). Ligue apontando para o manifesto.
URL_ATUALIZACAO = ""

TIMEOUT = 5  # segundos (conexão curta; nunca travar a abertura)
# Apenas estas pastas são substituídas por um update de código:
PASTAS_CODIGO = ("app", "core", "sources", "output", ".streamlit")

AQUI = Path(__file__).resolve().parent  # .../PIRAXIS/Programa


def _log(msg: str) -> None:
    # Discreto: o launcher já silencia stderr; isto é só informativo.
    print(f"[atualizar] {msg}")


def _sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        for bloco in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _ler_versao_local() -> str:
    p = AQUI / "VERSAO.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _baixar_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "piraxis-update"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def main() -> int:
    # 1) Desligado de fábrica → no-op imediato.
    if not URL_ATUALIZACAO:
        return 0

    lock = AQUI / "requirements.lock"
    if not lock.exists():
        return 0  # sem lock não há como travar dependências → não arrisca
    req_hash_local = _sha256_arquivo(lock)
    versao_local = _ler_versao_local()

    try:
        manifesto = json.loads(_baixar_bytes(URL_ATUALIZACAO).decode("utf-8"))
        versao_remota = str(manifesto.get("versao", ""))
        req_hash_remoto = str(manifesto.get("requirements_hash", ""))
        url_zip = str(manifesto.get("url_zip", ""))

        # 3) Já está atualizado.
        if versao_remota and versao_remota == versao_local:
            return 0

        # 4) Trava de dependências: runtime atual não comporta → não aplica.
        if req_hash_remoto and req_hash_remoto != req_hash_local:
            _log(
                "Há uma atualização que exige um pacote completo novo (as "
                "dependências mudaram). Peça o pacote PIRAXIS atualizado."
            )
            return 0

        if not url_zip or url_zip == "<PREENCHER>":
            return 0

        # 5) Só código mudou: baixa, valida e substitui atomicamente.
        dados = _baixar_bytes(url_zip)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            try:
                zf = zipfile.ZipFile(io.BytesIO(dados))
            except zipfile.BadZipFile:
                _log("zip de atualização inválido — ignorando.")
                return 0
            zf.extractall(tmp)

            # O zip de código tem topo PIRAXIS/Programa/...
            base = tmp / "PIRAXIS" / "Programa"
            if not base.is_dir():
                # tolera zips que já tragam Programa/ no topo
                base = tmp / "Programa" if (tmp / "Programa").is_dir() else tmp

            # Substitui SOMENTE as pastas de código (nunca python/cache/data/.env).
            for nome in PASTAS_CODIGO:
                novo = base / nome
                if not novo.is_dir():
                    continue
                alvo = AQUI / nome
                anterior = AQUI / (nome + ".old")
                if alvo.exists():
                    if anterior.exists():
                        shutil.rmtree(anterior, ignore_errors=True)
                    os.replace(alvo, anterior)  # troca atômica
                try:
                    shutil.copytree(novo, alvo)
                except Exception:
                    # rollback se a cópia falhar
                    if anterior.exists():
                        shutil.rmtree(alvo, ignore_errors=True)
                        os.replace(anterior, alvo)
                    raise
                shutil.rmtree(anterior, ignore_errors=True)

            # Atualiza metadados de versão e o lock (mesmo conjunto de deps).
            nova_versao = base / "VERSAO.txt"
            if nova_versao.exists():
                shutil.copy2(nova_versao, AQUI / "VERSAO.txt")
            novo_lock = base / "requirements.lock"
            if novo_lock.exists():
                shutil.copy2(novo_lock, AQUI / "requirements.lock")
        _log(f"código atualizado para a versão {versao_remota}.")
        return 0
    except Exception as exc:  # offline, timeout, zip ruim, etc. → nunca bloqueia
        _log(f"sem atualização agora ({exc.__class__.__name__}). Seguindo normal.")
        return 0


if __name__ == "__main__":
    # Blindagem final: jamais propaga exceção / código != 0 para o launcher.
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
