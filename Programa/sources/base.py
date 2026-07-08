"""
sources/base.py
===============

Interface comum a todas as fontes de radiação solar.

Define a classe abstrata ``FonteRadiacao``. Para adicionar uma nova fonte no
futuro (ex.: CAMS Radiation), basta criar um novo arquivo em sources/ com uma
classe que herde de ``FonteRadiacao`` e implemente ``buscar`` e ``cobre_local``.

Contrato do DataFrame padronizado retornado por qualquer fonte:
  - uma coluna ``timestamp`` (datetime);
  - uma coluna por componente disponível, nomeada EXATAMENTE GHI, DNI, DHI, BHI;
  - componentes não fornecidos pela fonte ficam AUSENTES (não inventar zeros).

Inclui também utilidades de cache local compartilhadas pelas fontes concretas.
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import pandas as pd

from core.config import CACHE_DIR, Config

logger = logging.getLogger(__name__)


def tamanho_cache_bytes() -> int:
    """Tamanho total (bytes) dos arquivos de cache no disco."""
    if not CACHE_DIR.exists():
        return 0
    return sum(p.stat().st_size for p in CACHE_DIR.glob("*") if p.is_file())


def limpar_cache() -> int:
    """Apaga todos os arquivos de cache (dados e respostas cruas).

    O cache é 100% regenerável (re-extrair refaz tudo); sem isto ele crescia
    para sempre — inclusive arquivos órfãos de versões antigas do CACHE_SCHEMA,
    que nunca mais seriam lidos. Retorna o número de arquivos removidos.
    """
    if not CACHE_DIR.exists():
        return 0
    removidos = 0
    for p in CACHE_DIR.glob("*"):
        if p.is_file():
            try:
                p.unlink()
                removidos += 1
            except OSError as exc:  # pragma: no cover - arquivo em uso etc.
                logger.warning("Não consegui remover %s: %s", p, exc)
    return removidos

# Nomes padronizados das colunas de componentes, NA ORDEM do arquivo do site da
# SoDa/CAMS McClear (TOA, GHI, BHI, DHI, BNI), para facilitar a conferência coluna
# a coluna com o download oficial. Obs.: o "DNI" do projeto é o "BNI" da SoDa
# (feixe normal) e "TOA" é a irradiação no topo da atmosfera (extraterrestre).
COMPONENTES_PADRAO: tuple[str, ...] = ("TOA", "GHI", "BHI", "DHI", "DNI")

# Versão do ESQUEMA do cache. Faz parte da chave de cache: ao incrementar, todos
# os arquivos de cache antigos passam a ser ignorados (nunca lidos), evitando que
# respostas gravadas por uma versão anterior — com unidade, fuso, altitude ou
# nomes/ordem de coluna diferentes — mascarem correções. Histórico:
#   v1: formato original.
#   v2: NASA POWER passou a ser coletada em UTC (time-standard=UTC) e a
#       renomeação "BNI" -> "BHI"; caches anteriores são incompatíveis.
#   v3: ordem de colunas passou a espelhar a SoDa (GHI, BHI, DHI, DNI).
#   v4: CAMS McClear usa a altitude CONFIGURADA do ponto (ex.: 786 m), igual ao
#       site, para fidelidade exata (a v3 usava SRTM e ficava ~0,2% off).
#   v5: inclui a coluna TOA (topo da atmosfera) do CAMS, como no arquivo do site.
CACHE_SCHEMA = "5"

# Frequência pandas correspondente a cada passo temporal ISO do projeto.
# Usada para montar a grade completa de horários do período solicitado.
FREQ_POR_PASSO: dict[str, str] = {
    "PT01M": "1min",
    "PT15M": "15min",
    "PT01H": "1h",
    "P01D": "1D",
    "P01M": "1MS",
}


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
                CACHE_SCHEMA,
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
        """Lê o cache se existir (e se o cache estiver habilitado)."""
        if not Config().cache_habilitado:
            return None
        caminho = self._caminho_cache(chave)
        if caminho.exists():
            logger.info("[%s] Lendo do cache: %s", self.nome, caminho.name)
            df = pd.read_csv(caminho, parse_dates=["timestamp"])
            return df
        return None

    def _salvar_cache(self, chave: str, df: pd.DataFrame) -> None:
        """Salva o DataFrame no cache local (a menos que esteja desabilitado)."""
        if not Config().cache_habilitado:
            return
        caminho = self._caminho_cache(chave)
        df.to_csv(caminho, index=False)
        logger.info("[%s] Resposta salva no cache: %s", self.nome, caminho.name)

    # ------------------------------------------------------------------
    # Resposta CRUA (auditoria) — persistida junto do cache para que um
    # cache hit não deixe o download de auditoria silenciosamente vazio.
    # ------------------------------------------------------------------
    def _caminho_cru(self, chave: str, formato: str) -> Path:
        return CACHE_DIR / f"{chave}.cru.{formato}"

    def _salvar_cru(self, chave: str, conteudo) -> None:
        """Persiste a resposta crua (dict -> .json; DataFrame -> .csv).

        Best-effort: falha aqui nunca derruba a extração (o cru é auditoria,
        não dado).
        """
        if conteudo is None or not Config().cache_habilitado:
            return
        try:
            if isinstance(conteudo, pd.DataFrame):
                conteudo.to_csv(self._caminho_cru(chave, "csv"))
            else:
                self._caminho_cru(chave, "json").write_text(
                    json.dumps(conteudo, ensure_ascii=False), encoding="utf-8"
                )
        except Exception as exc:  # pragma: no cover - só log, nunca quebra
            logger.warning("[%s] Não persisti a resposta crua: %s", self.nome, exc)

    def _ler_cru(self, chave: str):
        """Recupera a resposta crua do cache (ou None se não houver)."""
        if not Config().cache_habilitado:
            return None
        caminho_json = self._caminho_cru(chave, "json")
        if caminho_json.exists():
            try:
                return json.loads(caminho_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        caminho_csv = self._caminho_cru(chave, "csv")
        if caminho_csv.exists():
            try:
                return pd.read_csv(caminho_csv, index_col=0)
            except Exception:  # noqa: BLE001 - cru ilegível = ausente
                return None
        return None

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

    @staticmethod
    def _grade_periodo(
        data_inicio: date, data_fim: date, passo_temporal: str
    ) -> pd.DatetimeIndex:
        """Monta a grade COMPLETA de horários (UTC, sem fuso) do período pedido.

        Garante, por exemplo, que um pedido de 1 dia em passo horário tenha
        exatamente 24 instantes (00:00 a 23:00), independentemente de quantos a
        fonte devolveu. As datas são tratadas como dias inteiros: de
        ``data_inicio`` 00:00 até o fim de ``data_fim``.
        """
        freq = FREQ_POR_PASSO.get(passo_temporal, "1h")
        inicio = pd.Timestamp(data_inicio)
        if passo_temporal == "P01M":
            # Mensal: um ponto por mês, alinhado ao início de cada mês.
            inicio = inicio.to_period("M").to_timestamp()
            fim = pd.Timestamp(data_fim).to_period("M").to_timestamp()
            return pd.date_range(start=inicio, end=fim, freq="MS")
        # Demais passos: cobre dias inteiros (fim exclusivo no dia seguinte).
        fim = pd.Timestamp(data_fim) + pd.Timedelta(days=1)
        return pd.date_range(start=inicio, end=fim, freq=freq, inclusive="left")

    def _reindexar_periodo(
        self,
        df: pd.DataFrame,
        data_inicio: date,
        data_fim: date,
        passo_temporal: str,
    ) -> pd.DataFrame:
        """Encaixa os dados da fonte na grade completa do período.

        Horários que a fonte não trouxe passam a existir como linhas com
        valores ausentes (NaN), em vez de simplesmente desaparecerem. Assim o
        número de linhas sempre corresponde ao período solicitado.
        """
        if df.empty:
            return df
        grade = self._grade_periodo(data_inicio, data_fim, passo_temporal)
        sem_duplicatas = (
            df.assign(timestamp=pd.to_datetime(df["timestamp"]))
            .drop_duplicates(subset="timestamp")
            .set_index("timestamp")
            .sort_index()
        )
        reindexado = sem_duplicatas.reindex(grade)
        reindexado.index.name = "timestamp"
        faltantes = int(reindexado.iloc[:, 0].isna().sum()) if len(grade) else 0
        if faltantes:
            logger.info(
                "[%s] %d de %d instantes do período não vieram da fonte "
                "(preenchidos como vazios).",
                self.nome,
                faltantes,
                len(grade),
            )
        return reindexado.reset_index()
