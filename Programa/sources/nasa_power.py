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
from datetime import date, timedelta

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

# A NASA POWER só oferece as resoluções horária e diária. Passos fora desta
# tabela são REJEITADOS com erro claro (nunca rebaixados em silêncio): rebaixar
# 1 min/15 min para horário deixaria a série ~98% vazia, e "1 mês" no endpoint
# diário devolveria só o valor do dia 1º rotulado como o mês inteiro.
PASSOS_SUPORTADOS: dict[str, str] = {"PT01H": "horário", "P01D": "diário"}

# Defasagem típica de publicação da NASA POWER (dias). Datas mais recentes que
# hoje-DEFASAGEM voltam como -999 (tudo NaN) — "extração vazia sem erro". Por
# isso rejeitamos com mensagem clara, como o CAMS já faz.
DEFASAGEM_DIAS = 2


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

    @staticmethod
    def ultima_data_disponivel() -> date:
        """Data mais recente aceita (hoje - defasagem de publicação)."""
        return date.today() - timedelta(days=DEFASAGEM_DIAS)

    # ------------------------------------------------------------------
    def buscar(
        self,
        local,
        data_inicio: date,
        data_fim: date,
        passo_temporal: str,
    ) -> pd.DataFrame:
        """Busca radiação real na NASA POWER e retorna DataFrame padronizado."""
        if passo_temporal not in PASSOS_SUPORTADOS:
            suportados = " e ".join(PASSOS_SUPORTADOS.values())
            raise ValueError(
                f"A NASA POWER não oferece o passo temporal '{passo_temporal}': "
                f"apenas {suportados}. Escolha um destes passos ou extraia sem "
                "a fonte NASA POWER."
            )
        if data_inicio > data_fim:
            raise ValueError(
                "A data de início não pode ser depois da data de fim. "
                "Revise o período escolhido."
            )
        limite = self.ultima_data_disponivel()
        if data_fim > limite:
            raise ValueError(
                "Os dados da NASA POWER levam alguns dias para serem publicados. "
                f"A data final pedida ({data_fim:%d/%m/%Y}) ainda não está "
                f"disponível. A data mais recente que você pode usar é "
                f"{limite:%d/%m/%Y}. Ajuste o período e tente de novo."
            )

        # Cache primeiro: mesma consulta nunca rebate na API. A resposta CRUA
        # persistida acompanha (o download de auditoria não fica vazio).
        chave = self._chave_cache(local, data_inicio, data_fim, passo_temporal)
        em_cache = self._ler_cache(chave)
        if em_cache is not None:
            self.resposta_crua = self._ler_cru(chave)
            return em_cache

        diario = passo_temporal == "P01D"
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
        except requests.HTTPError as exc:
            # Erros HTTP têm causas distintas — não achatar tudo em "verifique
            # sua conexão" (mensagem enganosa para 429/4xx).
            status = exc.response.status_code if exc.response is not None else 0
            if status == 429:
                raise RuntimeError(
                    "A NASA POWER limitou temporariamente as consultas "
                    "(HTTP 429 — muitas requisições). Aguarde alguns minutos "
                    "e tente novamente."
                ) from exc
            if 400 <= status < 500:
                raise RuntimeError(
                    f"A NASA POWER recusou a consulta (HTTP {status}). "
                    "Verifique as coordenadas e o período escolhidos e tente "
                    "novamente."
                ) from exc
            raise RuntimeError(
                f"O serviço da NASA POWER parece indisponível no momento "
                f"(HTTP {status}). Tente novamente mais tarde."
            ) from exc
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
        self._salvar_cru(chave, bruto)
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
