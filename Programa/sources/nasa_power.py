"""
sources/nasa_power.py
=====================

Cliente da NASA POWER — fonte secundária, com dados de radiação REAL
(considerando nuvens). É uma API REST pública, sem cadastro, com cobertura
global, e cobre Botucatu.

Mapeamento de parâmetros NASA -> nomes padrão do projeto:
  ALLSKY_SFC_SW_DWN  -> GHI    (global horizontal, céu real)
  ALLSKY_SFC_SW_DNI  -> DNI    (direta normal, céu real)
  ALLSKY_SFC_SW_DIFF -> DHI    (difusa horizontal, céu real)
  CLRSKY_SFC_SW_DWN  -> GHI_ceu_limpo  (coluna auxiliar, p/ comparar c/ McClear)

Unidades: a NASA POWER retorna, na comunidade RE em passo horário, valores em
Wh/m² por passo. Documentamos e normalizamos para Wh/m² (ver _para_wh_m2).
Valores ausentes vêm como -999 e são convertidos para NaN.

Fuso horário (CRÍTICO): a NASA POWER entrega os dados em LST (Local Solar Time
— hora solar local) por PADRÃO, tanto no passo horário quanto no diário. O CAMS
McClear é coletado em UTC (``time_ref="UT"``) e TODO o restante do projeto
(grade temporal, controle de qualidade e suíte de validação) pressupõe UTC. Por
isso solicitamos explicitamente ``time-standard=UTC`` na requisição: sem isso,
as duas fontes ficam desalinhadas em ~3 h em Botucatu, produzindo um índice de
claridade (kt) sem sentido físico e picos de radiação em horas erradas — a
"incoerência" relatada na comparação com os sites das fontes.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import requests

from sources.base import FonteRadiacao

logger = logging.getLogger(__name__)

# Endpoints da NASA POWER por resolução temporal.
ENDPOINT_HORARIO = "https://power.larc.nasa.gov/api/temporal/hourly/point"
ENDPOINT_DIARIO = "https://power.larc.nasa.gov/api/temporal/daily/point"

# Parâmetros NASA solicitados e seus nomes padrão no projeto.
MAPA_PARAMETROS: dict[str, str] = {
    "ALLSKY_SFC_SW_DWN": "GHI",
    "ALLSKY_SFC_SW_DNI": "DNI",
    "ALLSKY_SFC_SW_DIFF": "DHI",
    "CLRSKY_SFC_SW_DWN": "GHI_ceu_limpo",
}

# Valor sentinela de ausência usado pela NASA POWER.
SENTINELA_AUSENTE = -999.0


class NasaPower(FonteRadiacao):
    """Cliente da fonte NASA POWER (radiação real, com nuvens)."""

    nome = "NASA POWER"
    inclui_nuvens = True

    def __init__(self, timeout: int = 60) -> None:
        self.timeout = timeout
        # JSON CRU da última chamada REAL à API (auditoria); None em cache.
        self.resposta_crua = None

    def cobre_local(self, local) -> bool:
        """Cobertura global: True para qualquer lat/lon válida."""
        return (-90.0 <= local.latitude <= 90.0) and (
            -180.0 <= local.longitude <= 180.0
        )

    # ------------------------------------------------------------------
    def buscar(
        self,
        local,
        data_inicio: date,
        data_fim: date,
        passo_temporal: str,
    ) -> pd.DataFrame:
        """Busca radiação real na NASA POWER e retorna DataFrame padronizado."""
        # Cache primeiro: mesma consulta nunca rebate na API.
        chave = self._chave_cache(local, data_inicio, data_fim, passo_temporal)
        em_cache = self._ler_cache(chave)
        if em_cache is not None:
            return em_cache

        # A NASA POWER só oferece resolução horária ou diária. Passos mais finos
        # (1 min, 15 min) caem para horário; mensal cai para diário.
        diario = passo_temporal in {"P01D", "P01M"}
        endpoint = ENDPOINT_DIARIO if diario else ENDPOINT_HORARIO

        parametros = {
            "parameters": ",".join(MAPA_PARAMETROS.keys()),
            "community": "RE",
            "format": "JSON",
            "latitude": local.latitude,
            "longitude": local.longitude,
            "start": data_inicio.strftime("%Y%m%d"),
            "end": data_fim.strftime("%Y%m%d"),
            # Alinha o fuso ao McClear (UTC). Sem isto, a NASA POWER usaria o
            # padrão LST e as fontes ficariam ~3 h fora de fase. Ver docstring.
            "time-standard": "UTC",
        }

        logger.info(
            "[%s] Consultando API (%s) de %s a %s.",
            self.nome,
            "diário" if diario else "horário",
            data_inicio,
            data_fim,
        )
        try:
            resposta = requests.get(endpoint, params=parametros, timeout=self.timeout)
            resposta.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Falha ao consultar a NASA POWER: {exc}. Verifique sua conexão "
                "com a internet e tente novamente."
            ) from exc

        bruto = resposta.json()
        self.resposta_crua = bruto  # JSON cru para auditoria
        df = self._parsear_json(bruto, diario=diario)
        # Garante a grade completa do período (horas faltantes viram NaN).
        df = self._reindexar_periodo(df, data_inicio, data_fim, passo_temporal)
        df = self._padronizar_colunas(df)
        self._salvar_cache(chave, df)
        return df

    # ------------------------------------------------------------------
    @staticmethod
    def _parsear_json(payload: dict, diario: bool) -> pd.DataFrame:
        """Converte o JSON da NASA POWER no DataFrame padronizado."""
        try:
            parametros = payload["properties"]["parameter"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                "Resposta inesperada da NASA POWER (estrutura JSON diferente do "
                "esperado)."
            ) from exc

        # Monta um DataFrame onde o índice são as chaves de tempo da NASA
        # (YYYYMMDDHH no horário, YYYYMMDD no diário) e as colunas, os
        # parâmetros já renomeados para o padrão do projeto.
        series_por_coluna: dict[str, pd.Series] = {}
        for nome_nasa, nome_padrao in MAPA_PARAMETROS.items():
            valores = parametros.get(nome_nasa, {})
            series_por_coluna[nome_padrao] = pd.Series(valores, dtype="float64")

        df = pd.DataFrame(series_por_coluna)
        df.index.name = "chave_tempo"
        df = df.reset_index()

        # Converte a chave de tempo em timestamp datetime.
        formato = "%Y%m%d" if diario else "%Y%m%d%H"
        df["timestamp"] = pd.to_datetime(df["chave_tempo"], format=formato)
        df = df.drop(columns="chave_tempo")

        # -999 -> NaN em todas as colunas de valores.
        colunas_valores = list(MAPA_PARAMETROS.values())
        df[colunas_valores] = df[colunas_valores].replace(SENTINELA_AUSENTE, pd.NA)

        # Normaliza unidades para Wh/m² (documentado em _para_wh_m2).
        for col in colunas_valores:
            df[col] = NasaPower._para_wh_m2(df[col], diario=diario)

        # Ordena por tempo e devolve.
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    @staticmethod
    def _para_wh_m2(serie: pd.Series, diario: bool) -> pd.Series:
        """Normaliza valores de radiação para Wh/m².

        Na comunidade RE da NASA POWER:
          - passo horário: os valores já vêm em Wh/m² por hora -> sem conversão.
          - passo diário: os valores vêm em kWh/m²/dia -> multiplicar por 1000
            para obter Wh/m²/dia.

        A conversão é mantida explícita e isolada aqui para facilitar ajustes
        caso a NASA altere as unidades retornadas.
        """
        serie = pd.to_numeric(serie, errors="coerce")
        if diario:
            # kWh/m²/dia -> Wh/m²/dia
            return serie * 1000.0
        return serie
