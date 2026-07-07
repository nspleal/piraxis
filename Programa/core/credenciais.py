"""
core/credenciais.py
===================

Gestão do e-mail da conta SoDa (CAMS McClear) **por máquina**.

O e-mail é individual de cada pesquisador e a credencial de acesso ao serviço
SoDa (o serviço não usa chave de API — a credencial é o próprio e-mail
cadastrado em soda-pro.com). Por isso ele:

  - NUNCA é fixado no código nem no .env;
  - é persistido fora do repositório, em ~/.radiacao_solar/config.json,
    para que cada máquina tenha o seu e nunca vá parar no Git.

A interface (app/streamlit_app.py) usa estas funções para pré-preencher o
campo de e-mail na abertura e para salvar quando o pesquisador pede.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Diretório e arquivo de configuração do usuário, fora do repositório.
DIR_CONFIG: Path = Path.home() / ".radiacao_solar"
ARQUIVO_CONFIG: Path = DIR_CONFIG / "config.json"

# Expressão regular simples para validar formato de e-mail.
_REGEX_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def email_valido(email: str | None) -> bool:
    """Retorna True se ``email`` tem um formato plausível de e-mail."""
    if not email:
        return False
    return bool(_REGEX_EMAIL.match(email.strip()))


def carregar_email() -> str | None:
    """Lê o e-mail SoDa salvo nesta máquina.

    Retorna o e-mail (str) ou None se não houver nada salvo ou se o arquivo
    estiver corrompido/inválido.
    """
    if not ARQUIVO_CONFIG.exists():
        return None
    try:
        dados = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Não foi possível ler %s: %s", ARQUIVO_CONFIG, exc)
        return None
    if not isinstance(dados, dict):
        # JSON VÁLIDO porém não-objeto (ex.: uma string solta) também é
        # arquivo corrompido — sem esta guarda, dados.get() estourava
        # AttributeError e derrubava o app na abertura.
        logger.warning("Conteúdo inesperado em %s (não é um objeto JSON).",
                       ARQUIVO_CONFIG)
        return None

    email = dados.get("email_soda")
    if email and email_valido(email):
        return str(email).strip()
    return None


def salvar_email(email: str) -> None:
    """Salva o e-mail SoDa nesta máquina (validando o formato antes).

    Levanta ValueError com mensagem amigável se o e-mail for inválido.
    """
    email = (email or "").strip()
    if not email_valido(email):
        raise ValueError(
            f"E-mail inválido: {email!r}. Informe um endereço no formato "
            "nome@dominio.com (o mesmo cadastrado em soda-pro.com)."
        )

    DIR_CONFIG.mkdir(parents=True, exist_ok=True)
    _restringir_permissoes(DIR_CONFIG, 0o700)

    # Preserva eventuais outras chaves já presentes no arquivo.
    dados: dict = {}
    if ARQUIVO_CONFIG.exists():
        try:
            lido = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
            if isinstance(lido, dict):
                dados = lido
        except (json.JSONDecodeError, OSError):
            dados = {}

    dados["email_soda"] = email
    # Escrita ATÔMICA (temp + os.replace): um crash no meio da gravação não
    # deixa o config.json truncado. E o arquivo nasce 0600 — o e-mail é a
    # credencial SoDa e não deve ficar legível por outros usuários da máquina.
    fd, tmp_nome = tempfile.mkstemp(
        dir=str(DIR_CONFIG), prefix=".config-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(dados, ensure_ascii=False, indent=2))
        _restringir_permissoes(Path(tmp_nome), 0o600)
        os.replace(tmp_nome, ARQUIVO_CONFIG)
    except BaseException:
        try:
            os.unlink(tmp_nome)
        except OSError:
            pass
        raise
    logger.info("E-mail SoDa salvo em %s.", ARQUIVO_CONFIG)


def _restringir_permissoes(caminho: Path, modo: int) -> None:
    """chmod best-effort (no Windows as permissões POSIX não se aplicam)."""
    try:
        os.chmod(caminho, modo)
    except OSError:  # pragma: no cover - sistemas sem suporte
        pass
