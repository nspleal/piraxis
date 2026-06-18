"""
core/config.py
==============

Configurações centrais do Extrator de Radiação Solar.

Reúne, num único lugar:
  - a dataclass ``Local`` (ponto geográfico de estudo) e o ponto padrão Botucatu;
  - a dataclass ``Config`` (configurações opcionais, lidas do .env) com validação;
  - os dicionários de metadados dos componentes de radiação e dos passos temporais;
  - os caminhos base do projeto (cache/ e data/), criados automaticamente.

IMPORTANTE: o e-mail da conta SoDa (CAMS McClear) NÃO é lido daqui. Ele é
individual de cada pesquisador e gerido por ``core/credenciais.py`` (salvo em
~/.radiacao_solar/config.json). O .env fica reservado a opções como o cache.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Carrega o .env (se existir) para o ambiente. Silencioso se o arquivo faltar.
load_dotenv()


# ---------------------------------------------------------------------------
# Ponto geográfico de estudo
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Local:
    """Representa um ponto geográfico de estudo.

    A altitude padrão -999.0 é um valor sentinela que faz o serviço SoDa
    estimar automaticamente a altitude do ponto.
    """

    nome: str
    latitude: float
    longitude: float
    altitude: float = -999.0

    def __post_init__(self) -> None:
        # Validação básica das coordenadas. Como a dataclass é congelada,
        # usamos object.__setattr__ apenas se precisássemos ajustar — aqui só
        # validamos e levantamos erro amigável em caso de coordenada inválida.
        if not (-90.0 <= self.latitude <= 90.0):
            raise ValueError(
                f"Latitude inválida ({self.latitude}). Deve estar entre -90 e 90."
            )
        if not (-180.0 <= self.longitude <= 180.0):
            raise ValueError(
                f"Longitude inválida ({self.longitude}). Deve estar entre -180 e 180."
            )


# Local padrão de estudo do projeto (UNESP, Botucatu/SP).
BOTUCATU = Local("Botucatu", -22.8867, -48.4450, 786.0)


# ---------------------------------------------------------------------------
# Configurações opcionais (lidas do .env)
# ---------------------------------------------------------------------------
@dataclass
class Config:
    """Configurações opcionais da ferramenta.

    Apenas opções não sensíveis. O e-mail SoDa NÃO mora aqui (ver credenciais.py).
    """

    cache_habilitado: bool = field(
        default_factory=lambda: os.getenv("CACHE_HABILITADO", "true").strip().lower()
        not in {"false", "0", "nao", "não", "no"}
    )

    def validar(self) -> list[str]:
        """Retorna uma lista de problemas de configuração (vazia se tudo OK)."""
        problemas: list[str] = []
        # No momento não há configurações obrigatórias. Mantido para extensão
        # futura e para manter a interface estável esperada pela interface.
        return problemas


# ---------------------------------------------------------------------------
# Metadados dos componentes de radiação
# ---------------------------------------------------------------------------
# Cada componente tem rótulo amigável, unidade e descrição em português.
# Unidade padrão: Wh/m² (consistência entre McClear e NASA POWER).
COMPONENTES_RADIACAO: dict[str, dict[str, str]] = {
    "GHI": {
        "rotulo": "GHI — Irradiação Global Horizontal",
        "unidade": "Wh/m²",
        "descricao": "Radiação total recebida numa superfície horizontal.",
    },
    "DNI": {
        "rotulo": "DNI — Irradiação Normal Direta",
        "unidade": "Wh/m²",
        "descricao": "Radiação direta recebida numa superfície perpendicular ao Sol.",
    },
    "DHI": {
        "rotulo": "DHI — Irradiação Difusa Horizontal",
        "unidade": "Wh/m²",
        "descricao": "Radiação difusa (espalhada pela atmosfera) numa superfície horizontal.",
    },
    "BHI": {
        "rotulo": "BHI — Irradiância de Feixe Horizontal",
        "unidade": "Wh/m²",
        "descricao": "Componente direta projetada na horizontal (do McClear).",
    },
}


# ---------------------------------------------------------------------------
# Passos temporais suportados
# ---------------------------------------------------------------------------
# Mapeia rótulos amigáveis para os códigos ISO 8601 usados pelas APIs.
PASSOS_TEMPORAIS: dict[str, str] = {
    "1 minuto": "PT01M",
    "15 minutos": "PT15M",
    "1 hora": "PT01H",
    "1 dia": "P01D",
    "1 mês": "P01M",
}


# ---------------------------------------------------------------------------
# Caminhos do projeto
# ---------------------------------------------------------------------------
# BASE_DIR aponta para a raiz do projeto (a pasta acima de core/).
BASE_DIR: Path = Path(__file__).resolve().parent.parent
CACHE_DIR: Path = BASE_DIR / "cache"
OUTPUT_DIR: Path = BASE_DIR / "data"

# Cria as pastas de runtime se ainda não existirem.
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
