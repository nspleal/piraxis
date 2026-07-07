"""
Testes da gestão de credencial SoDa (core/credenciais.py).

Cobre: JSON corrompido/não-objeto (não pode derrubar o app na abertura),
roundtrip salvar/carregar com preservação de outras chaves e permissões
restritas do arquivo (a credencial não deve ser legível por outros usuários).
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from core import credenciais


@pytest.fixture()
def config_isolado(tmp_path, monkeypatch):
    """Redireciona o arquivo de credencial para uma pasta temporária."""
    d = tmp_path / ".radiacao_solar"
    monkeypatch.setattr(credenciais, "DIR_CONFIG", d)
    monkeypatch.setattr(credenciais, "ARQUIVO_CONFIG", d / "config.json")
    return d


def test_json_nao_objeto_nao_derruba(config_isolado):
    """Regressão (auditoria 2026-07-07): JSON VÁLIDO porém não-objeto (ex.:
    uma string solta) estourava AttributeError em carregar_email — chamado na
    abertura do app — e TypeError em salvar_email."""
    config_isolado.mkdir(parents=True)
    (config_isolado / "config.json").write_text(
        '"não sou um objeto"', encoding="utf-8"
    )
    assert credenciais.carregar_email() is None  # corrompido => None, sem erro
    credenciais.salvar_email("pesquisador@unesp.br")  # não pode levantar
    assert credenciais.carregar_email() == "pesquisador@unesp.br"


def test_roundtrip_preserva_outras_chaves(config_isolado):
    credenciais.salvar_email("a@b.com")
    assert credenciais.carregar_email() == "a@b.com"

    # Outra chave gravada por terceiros é preservada ao salvar de novo.
    arq = config_isolado / "config.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    dados["outra_config"] = 42
    arq.write_text(json.dumps(dados), encoding="utf-8")

    credenciais.salvar_email("c@d.com")
    final = json.loads(arq.read_text(encoding="utf-8"))
    assert final["email_soda"] == "c@d.com"
    assert final["outra_config"] == 42


def test_email_invalido_rejeitado(config_isolado):
    with pytest.raises(ValueError, match="inválido"):
        credenciais.salvar_email("sem-arroba")


@pytest.mark.skipif(os.name != "posix", reason="permissões POSIX")
def test_credencial_gravada_privada(config_isolado):
    """Regressão (auditoria 2026-07-07): o arquivo nascia legível por todos
    (644) numa máquina de laboratório multiusuário. Agora 600, e o diretório
    700."""
    credenciais.salvar_email("a@b.com")
    modo_arq = stat.S_IMODE(os.stat(config_isolado / "config.json").st_mode)
    modo_dir = stat.S_IMODE(os.stat(config_isolado).st_mode)
    assert modo_arq == 0o600
    assert modo_dir == 0o700
