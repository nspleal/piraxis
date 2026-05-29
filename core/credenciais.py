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
import re
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

    # Preserva eventuais outras chaves já presentes no arquivo.
    dados: dict = {}
    if ARQUIVO_CONFIG.exists():
        try:
            dados = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            dados = {}

    dados["email_soda"] = email
    ARQUIVO_CONFIG.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("E-mail SoDa salvo em %s.", ARQUIVO_CONFIG)
