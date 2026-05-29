"""
sources/cams_mcclear.py
=======================

Cliente do CAMS McClear (serviço SoDa) — fonte primária, com radiação em
CÉU LIMPO (sem nuvens), o "teto teórico" da radiação possível no ponto.

Características do serviço (decisões já tomadas no projeto):
  - Acesso via WPS (Web Processing Service) por HTTP GET.
  - Autenticação pelo e-mail cadastrado em soda-pro.com (não há chave de API).
    O e-mail é recebido como parâmetro (construtor), nunca lido de constante
    global — quem o fornece é a camada de interface (core/credenciais.py).
  - Cobertura mundial -> cobre_local sempre True.
  - Componentes retornados: GHI, DNI, DHI, BNI.
  - Atraso dos dados: sempre current_day - 2 (dois dias de defasagem).
  - Resposta em CSV com linhas de comentário iniciadas por '#'.

Observação: o nome exato dos campos do ``datainputs`` é sensível. Esta
implementação segue o formato documentado no enunciado do projeto; ao validar
contra a doc oficial (soda-pro.com), ajuste apenas as constantes abaixo se
necessário.
"""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from urllib.parse import quote

import pandas as pd
import requests

from core.credenciais import email_valido
from sources.base import FonteRadiacao

logger = logging.getLogger(__name__)

# Endpoint base do serviço WPS do SoDa.
ENDPOINT_WPS = "https://www.soda-pro.com/service/wps"

# Atraso fixo dos dados do McClear: sempre dois dias atrás.
ATRASO_DIAS = 2

# Mapeamento dos nomes de coluna do CSV do McClear para o padrão do projeto.
# O CSV traz colunas como "Clear sky GHI", "Clear sky DNI", etc.; abaixo
# cobrimos variações comuns de rotulagem (com e sem "Clear sky").
MAPA_COLUNAS: dict[str, str] = {
    "Clear sky GHI": "GHI",
    "Clear sky DNI": "DNI",
    "Clear sky DHI": "DHI",
    "Clear sky BHI": "BNI",
    "Clear sky BNI": "BNI",
    "GHI": "GHI",
    "DNI": "DNI",
    "DHI": "DHI",
    "BNI": "BNI",
    "BHI": "BNI",
}


class CamsMcClear(FonteRadiacao):
    """Cliente da fonte CAMS McClear (radiação em céu limpo)."""

    nome = "CAMS McClear"
    inclui_nuvens = False

    def __init__(self, email: str, timeout: int = 120) -> None:
        """Recebe o e-mail SoDa de autenticação (nunca de constante global)."""
        self.email = (email or "").strip()
        self.timeout = timeout

    def cobre_local(self, local) -> bool:
        """Cobertura mundial: sempre True."""
        return True

    # ------------------------------------------------------------------
    def buscar(
        self,
        local,
        data_inicio: date,
        data_fim: date,
        passo_temporal: str,
    ) -> pd.DataFrame:
        """Busca radiação em céu limpo no McClear e padroniza o DataFrame."""
        # Valida o e-mail de autenticação com mensagem amigável.
        if not email_valido(self.email):
            raise ValueError(
                "Para usar o CAMS McClear é preciso informar o e-mail da sua "
                "conta SoDa (gratuita e individual, criada em soda-pro.com). "
                "Configure-o no campo de e-mail da barra lateral."
            )

        # Respeita o atraso de 2 dias: ajusta data_fim e avisa via log.
        limite = date.today() - timedelta(days=ATRASO_DIAS)
        if data_fim > limite:
            logger.warning(
                "[%s] data_fim %s é mais recente que o limite (hoje - %d dias = "
                "%s). Ajustando para %s.",
                self.nome,
                data_fim,
                ATRASO_DIAS,
                limite,
                limite,
            )
            data_fim = limite
        if data_inicio > data_fim:
            raise ValueError(
                "Após aplicar o atraso de 2 dias do McClear, a data de início "
                "ficou depois da data de fim. Escolha um período mais antigo."
            )

        # Cache primeiro: mesma consulta nunca rebate na API.
        chave = self._chave_cache(local, data_inicio, data_fim, passo_temporal)
        em_cache = self._ler_cache(chave)
        if em_cache is not None:
            return em_cache

        parametros = self._montar_parametros(
            local, data_inicio, data_fim, passo_temporal
        )

        logger.info(
            "[%s] Consultando WPS de %s a %s (passo %s).",
            self.nome,
            data_inicio,
            data_fim,
            passo_temporal,
        )
        try:
            resposta = requests.get(
                ENDPOINT_WPS, params=parametros, timeout=self.timeout
            )
            resposta.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Falha ao consultar o CAMS McClear (SoDa): {exc}. Verifique sua "
                "conexão e se o e-mail informado está cadastrado em soda-pro.com."
            ) from exc

        df = self._parsear_csv(resposta.text)
        df = self._padronizar_colunas(df)
        self._salvar_cache(chave, df)
        return df

    # ------------------------------------------------------------------
    def _montar_parametros(
        self,
        local,
        data_inicio: date,
        data_fim: date,
        passo_temporal: str,
    ) -> dict[str, str]:
        """Monta os parâmetros da requisição WPS (incluindo o datainputs)."""
        email_codificado = quote(self.email, safe="")
        datainputs = (
            f"latitude={local.latitude};"
            f"longitude={local.longitude};"
            f"altitude={local.altitude};"
            f"date_begin={data_inicio.isoformat()};"
            f"date_end={data_fim.isoformat()};"
            f"time_step={passo_temporal};"
            f"time_ref=UT;"
            f"summarization={passo_temporal};"
            f"username={email_codificado};"
            f"verbose=false"
        )
        return {
            "Service": "WPS",
            "Request": "Execute",
            "Identifier": "get_mcclear",
            "version": "1.0.0",
            "RawDataOutput": "irradiation",
            "DataInputs": datainputs,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _parsear_csv(texto: str) -> pd.DataFrame:
        """Parseia o CSV do McClear, ignorando linhas de comentário '#'.

        O McClear usa ';' como separador e prefixa metadados com '#'. A coluna
        de tempo costuma vir como um intervalo "inicio/fim"; usamos o instante
        inicial como timestamp.
        """
        try:
            df = pd.read_csv(
                io.StringIO(texto),
                comment="#",
                sep=";",
                skipinitialspace=True,
            )
        except Exception as exc:  # pragma: no cover - erro de formato inesperado
            raise RuntimeError(
                "Não foi possível interpretar a resposta CSV do CAMS McClear."
            ) from exc

        # Limpa espaços nos nomes de coluna.
        df.columns = [str(c).strip() for c in df.columns]

        # Localiza a coluna de tempo (geralmente a primeira, com "Observation"
        # ou "period" no nome, no formato "inicio/fim").
        col_tempo = df.columns[0]
        instantes = df[col_tempo].astype(str).str.split("/").str[0].str.strip()
        timestamp = pd.to_datetime(instantes, errors="coerce", utc=False)

        # Renomeia colunas de componentes para o padrão do projeto.
        renomear = {c: MAPA_COLUNAS[c] for c in df.columns if c in MAPA_COLUNAS}
        df = df.rename(columns=renomear)

        # Mantém só timestamp + componentes padrão disponíveis.
        componentes = [c for c in ("GHI", "DNI", "DHI", "BNI") if c in df.columns]
        resultado = pd.DataFrame({"timestamp": timestamp})
        for c in componentes:
            resultado[c] = pd.to_numeric(df[c], errors="coerce")

        resultado = resultado.dropna(subset=["timestamp"]).reset_index(drop=True)
        return resultado
