"""
sources/base.py
===============

Interface comum a todas as fontes de radiação solar.

Define a classe abstrata ``FonteRadiacao``. Para adicionar uma nova fonte no
futuro (ex.: CAMS Radiation), basta criar um novo arquivo em sources/ com uma
classe que herde de ``FonteRadiacao`` e implemente ``buscar`` e ``cobre_local``.

Contrato do DataFrame padronizado retornado por qualquer fonte:
  - uma coluna ``timestamp`` (datetime);
  - uma coluna por componente disponível, nomeada EXATAMENTE GHI, DNI, DHI, BNI;
  - componentes não fornecidos pela fonte ficam AUSENTES (não inventar zeros).

Inclui também utilidades de cache local compartilhadas pelas fontes concretas.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import pandas as pd

from core.config import CACHE_DIR

logger = logging.getLogger(__name__)

# Nomes padronizados das colunas de componentes (ordem canônica).
COMPONENTES_PADRAO: tuple[str, ...] = ("GHI", "DNI", "DHI", "BNI")


class FonteRadiacao(ABC):
    """Classe base abstrata para uma fonte de dados de radiação solar."""

    #: Nome amigável da fonte (exibido na interface e nas planilhas).
    nome: str = "fonte"
    #: Indica se a fonte considera nuvens (dados reais) ou é céu limpo.
    inclui_nuvens: bool = False

    @abstractmethod
    def buscar(
        self,
        local,
        data_inicio: date,
        data_fim: date,
        passo_temporal: str,
    ) -> pd.DataFrame:
        """Busca os dados de radiação e retorna o DataFrame padronizado."""
        raise NotImplementedError

    @abstractmethod
    def cobre_local(self, local) -> bool:
        """Indica se a fonte cobre o ``local`` informado."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Utilidades de cache compartilhadas
    # ------------------------------------------------------------------
    def _chave_cache(
        self,
        local,
        data_inicio: date,
        data_fim: date,
        passo_temporal: str,
    ) -> str:
        """Gera um hash estável a partir dos parâmetros da consulta.

        A chave inclui a fonte (self.nome), o local, as datas e o passo. Isso
        garante que parâmetros idênticos reusem o mesmo arquivo de cache.
        """
        bruto = "|".join(
            [
                self.nome,
                local.nome,
                f"{local.latitude:.4f}",
                f"{local.longitude:.4f}",
                f"{local.altitude:.1f}",
                data_inicio.isoformat(),
                data_fim.isoformat(),
                passo_temporal,
            ]
        )
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:16]

    def _caminho_cache(self, chave: str) -> Path:
        """Caminho do arquivo de cache (CSV) para uma chave."""
        return CACHE_DIR / f"{chave}.csv"

    def _ler_cache(self, chave: str) -> pd.DataFrame | None:
        """Lê o cache se existir; retorna None caso contrário."""
        caminho = self._caminho_cache(chave)
        if caminho.exists():
            logger.info("[%s] Lendo do cache: %s", self.nome, caminho.name)
            df = pd.read_csv(caminho, parse_dates=["timestamp"])
            return df
        return None

    def _salvar_cache(self, chave: str, df: pd.DataFrame) -> None:
        """Salva o DataFrame no cache local."""
        caminho = self._caminho_cache(chave)
        df.to_csv(caminho, index=False)
        logger.info("[%s] Resposta salva no cache: %s", self.nome, caminho.name)

    @staticmethod
    def _padronizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
        """Reordena as colunas para timestamp + componentes na ordem canônica.

        Colunas auxiliares (ex.: GHI_ceu_limpo) são mantidas ao final.
        """
        if "timestamp" not in df.columns:
            raise ValueError("DataFrame da fonte não possui coluna 'timestamp'.")

        principais = [c for c in COMPONENTES_PADRAO if c in df.columns]
        auxiliares = [
            c
            for c in df.columns
            if c != "timestamp" and c not in COMPONENTES_PADRAO
        ]
        return df[["timestamp", *principais, *auxiliares]]
