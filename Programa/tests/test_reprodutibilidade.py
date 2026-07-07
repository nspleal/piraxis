"""
Testes do módulo de reprodutibilidade (core/reprodutibilidade.py).

Verifica: proveniência com os campos esperados e SEM o e-mail; metodologia
preenchida com os valores reais; citações só das fontes usadas; e geração dos
arquivos .md e .json.
"""

from __future__ import annotations

import json
from datetime import date

from core.config import BOTUCATU
from core.reprodutibilidade import (
    gerar_reprodutibilidade,
    montar_proveniencia,
    salvar_artefatos,
)

EMAIL = "pesquisador@unesp.br"


def test_proveniencia_campos_e_sem_email():
    prov = montar_proveniencia(
        BOTUCATU, date(2026, 6, 7), date(2026, 6, 9), "PT01H", "1 hora",
        ["CAMS McClear", "NASA POWER"], ["GHI", "DNI", "DHI", "BHI"],
    )
    # Campos esperados.
    for chave in ("ferramenta", "data_extracao", "local", "periodo", "fontes",
                  "componentes", "unidade", "ambiente"):
        assert chave in prov
    assert prov["local"]["latitude"] == BOTUCATU.latitude
    assert prov["periodo"]["passo_codigo"] == "PT01H"
    assert {f["nome"] for f in prov["fontes"]} == {"CAMS McClear", "NASA POWER"}
    assert "pvlib" in prov["ambiente"]

    # O e-mail NÃO pode aparecer em lugar nenhum.
    texto = json.dumps(prov, ensure_ascii=False).lower()
    assert "@" not in texto
    assert EMAIL not in texto


def test_metodologia_preenchida_com_valores_reais():
    repro = gerar_reprodutibilidade(
        BOTUCATU, date(2026, 6, 7), date(2026, 6, 9), "PT01H", "1 hora",
        ["CAMS McClear", "NASA POWER"], ["GHI", "DNI", "DHI", "BHI"],
    )
    assert "Botucatu" in repro.metodologia_pt
    assert "07/06/2026" in repro.metodologia_pt
    assert "1 hora" in repro.metodologia_pt
    assert "McClear" in repro.metodologia_pt
    assert "NASA POWER" in repro.metodologia_pt
    # Inglês com datas ISO e termos em inglês.
    assert "2026-06-07" in repro.metodologia_en
    assert "clear-sky" in repro.metodologia_en.lower()


def test_citacoes_so_das_fontes_usadas():
    # Só McClear: não deve citar NASA; deve citar Copernicus, McClear e pvlib.
    repro = gerar_reprodutibilidade(
        BOTUCATU, date(2026, 6, 7), date(2026, 6, 9), "PT01H", "1 hora",
        ["CAMS McClear"], ["GHI", "DNI", "DHI", "BHI"],
    )
    cit = repro.citacoes_md
    assert "Lefèvre" in cit
    assert "Gschwind" in cit
    assert "Copernicus" in cit
    assert "2026" in cit  # ano dos dados na atribuição
    assert "Holmgren" in cit  # pvlib sempre
    assert "NASA Langley" not in cit  # NASA não foi usada

    # Só NASA: cita NASA e pvlib, não cita McClear/Copernicus.
    repro2 = gerar_reprodutibilidade(
        BOTUCATU, date(2026, 6, 7), date(2026, 6, 9), "PT01H", "1 hora",
        ["NASA POWER"], ["GHI", "DNI", "DHI"],
    )
    assert "NASA Langley" in repro2.citacoes_md
    assert "Holmgren" in repro2.citacoes_md
    assert "Lefèvre" not in repro2.citacoes_md
    assert "Copernicus" not in repro2.citacoes_md


def test_geracao_dos_arquivos(tmp_path):
    repro = gerar_reprodutibilidade(
        BOTUCATU, date(2026, 6, 7), date(2026, 6, 9), "PT01H", "1 hora",
        ["CAMS McClear", "NASA POWER"], ["GHI", "DNI", "DHI", "BHI"],
    )
    caminho_md, caminho_json = salvar_artefatos(repro, "estudo", tmp_path)

    assert caminho_md.name == "estudo_reprodutibilidade.md"
    assert caminho_json.name == "estudo_proveniencia.json"
    assert caminho_md.exists() and caminho_json.exists()

    md = caminho_md.read_text(encoding="utf-8")
    assert "## Metodologia (PT)" in md
    assert "## Methodology (EN)" in md
    assert "Referências" in md
    assert EMAIL not in md  # nunca o e-mail

    dados = json.loads(caminho_json.read_text(encoding="utf-8"))
    assert dados["ferramenta"]
    assert "@" not in json.dumps(dados)


def test_metodologia_sem_pais_fixo_e_sem_sentinela_de_altitude():
    """Regressão (auditoria 2026-07-07): o texto EN fixava ", Brazil" para
    qualquer ponto do globo, e a altitude-sentinela (-999) vazava para a
    metodologia com a afirmação FALSA de que a altitude informada foi usada
    (quando ≤ 0 o serviço SoDa estima por SRTM)."""
    from core.config import Local
    from core.reprodutibilidade import gerar_metodologia

    ushuaia = Local("Ushuaia", -54.8, -68.3)  # altitude default: não informada
    pt, en = gerar_metodologia(
        ushuaia, date(2026, 1, 1), date(2026, 1, 3), "1 hora", ["CAMS McClear"]
    )
    assert "Brazil" not in en
    assert "-999" not in pt and "-999" not in en
    assert "SRTM" in pt and "SRTM" in en

    # Com altitude informada, o número aparece e a claim do site vale.
    pt2, en2 = gerar_metodologia(
        BOTUCATU, date(2026, 1, 1), date(2026, 1, 3), "1 hora", ["CAMS McClear"]
    )
    assert "786" in pt2 and "786" in en2
    assert "SRTM" not in pt2 and "SRTM" not in en2


def test_proveniencia_altitude_sentinela_vira_none():
    from core.config import Local

    prov = montar_proveniencia(
        Local("Ushuaia", -54.8, -68.3), date(2026, 1, 1), date(2026, 1, 3),
        "PT01H", "1 hora", ["CAMS McClear"], ["GHI"],
    )
    assert prov["local"]["altitude_m"] is None
    assert "SRTM" in prov["local"]["altitude_origem"]

    prov2 = montar_proveniencia(
        BOTUCATU, date(2026, 1, 1), date(2026, 1, 3),
        "PT01H", "1 hora", ["CAMS McClear"], ["GHI"],
    )
    assert prov2["local"]["altitude_m"] == BOTUCATU.altitude
    assert "informada" in prov2["local"]["altitude_origem"]
