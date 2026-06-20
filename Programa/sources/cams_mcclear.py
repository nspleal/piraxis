"""
sources/cams_mcclear.py
=======================

Cliente do CAMS (serviço SoDa) — fonte primária de radiação em CÉU LIMPO
(McClear), o "teto teórico" da radiação possível no ponto.

O acesso ao SoDa é feito pela biblioteca **pvlib** (``pvlib.iotools.get_cams``),
a função oficial, testada e mantida pela comunidade de energia solar. Isso
resolve o antigo erro 404 (a montagem manual da requisição usava o endpoint e
os nomes de campo errados; o correto, ``api.soda-solardata.com``, é encapsulado
pela pvlib) e dá credibilidade acadêmica ao projeto. Não há mais montagem
manual de URL, codificação de e-mail, parâmetros de requisição nem parsing de
CSV — tudo isso vive dentro da pvlib.

Características do serviço (decisões já tomadas no projeto):
  - Autenticação pelo e-mail cadastrado E CONFIRMADO em soda-pro.com (não há
    chave de API). O e-mail é recebido no construtor, nunca de constante global.
  - Cobertura mundial -> cobre_local sempre True.
  - Componentes retornados: GHI, DNI, DHI, BHI.
  - Atraso dos dados: a última data disponível é sempre hoje - 2 dias.
  - Limite de 100 requisições por dia por conta (por isso o cache-first).

Sobre ``identifier``:
  - ``"mcclear"`` (padrão): só céu limpo. É o usado pela interface.
  - ``"cams_radiation"``: além do céu limpo, traz radiação real e
    ``Reliability``. Cobertura de Botucatu confirmada. Fica EXPOSTO no cliente
    para uso futuro, mas ainda NÃO é integrado à interface (decisão do
    orientador pendente).

Sobre o cache e a divisão de períodos:
  - A ``get_cams`` aceita períodos longos (até anos) numa única chamada, então
    o cliente NÃO divide o período em blocos. O cache é organizado por período
    inteiro (hash de local + datas + passo + identifier), gravado após o
    primeiro download e lido em qualquer repetição idêntica.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import requests

from core.credenciais import email_valido
from sources.base import FonteRadiacao

logger = logging.getLogger(__name__)

# Atraso fixo dos dados do McClear: a última data disponível é hoje - 2 dias.
ATRASO_DIAS = 2

# Identificadores aceitos pela pvlib/SoDa.
IDENTIFICADORES_VALIDOS = ("mcclear", "cams_radiation")

# A pvlib espera o passo temporal nos códigos '1min'/'15min'/'1h'/'1d'/'1M',
# não nos códigos ISO 8601 usados internamente pelo projeto. Convertemos aqui.
ISO_PARA_PVLIB: dict[str, str] = {
    "PT01M": "1min",
    "PT15M": "15min",
    "PT01H": "1h",
    "P01D": "1d",
    "P01M": "1M",
}

# Mapa de cada componente padrão do projeto para os possíveis nomes que a pvlib
# devolve (com map_variables=True). Preferimos sempre a versão de CÉU LIMPO
# ("*_clear"); caímos para a variante sem sufixo apenas por robustez entre
# versões. O componente padrão "BHI" (Beam Horizontal Irradiance — feixe
# projetado na horizontal) vem de ``bhi_clear``, ficando autoconsistente. As
# colunas de radiação REAL do cams_radiation (ghi, dni, ...) não entram nos
# componentes padrão (céu limpo) e ficam de fora.
CANDIDATOS_COMPONENTE: dict[str, tuple[str, ...]] = {
    "GHI": ("ghi_clear",),
    "DNI": ("dni_clear",),
    "DHI": ("dhi_clear",),
    "BHI": ("bhi_clear",),
}


class CamsMcClear(FonteRadiacao):
    """Cliente da fonte CAMS McClear (radiação em céu limpo) via pvlib."""

    nome = "CAMS McClear"
    inclui_nuvens = False

    #: Contador GLOBAL de chamadas REAIS à API SoDa (cache miss). É de classe
    #: para o teste de cache poder comprovar que a 2ª extração faz zero
    #: requisições. Use ``resetar_contador()`` antes de medir.
    chamadas_reais_api: int = 0

    def __init__(
        self, email: str, timeout: int = 120, identifier: str = "mcclear"
    ) -> None:
        """Recebe o e-mail SoDa (nunca de constante global) e o identificador.

        ``identifier`` aceita "mcclear" (padrão) ou "cams_radiation".
        """
        self.email = (email or "").strip()
        self.timeout = timeout
        if identifier not in IDENTIFICADORES_VALIDOS:
            raise ValueError(
                f"identifier inválido: {identifier!r}. "
                f"Use um de {IDENTIFICADORES_VALIDOS}."
            )
        self.identifier = identifier

    def cobre_local(self, local) -> bool:
        """Cobertura mundial: sempre True."""
        return True

    @classmethod
    def resetar_contador(cls) -> None:
        """Zera o contador de chamadas reais à API (usado nos testes)."""
        cls.chamadas_reais_api = 0

    @staticmethod
    def ultima_data_disponivel() -> date:
        """Última data com dados (hoje - ATRASO_DIAS)."""
        return date.today() - timedelta(days=ATRASO_DIAS)

    # ------------------------------------------------------------------
    def buscar(
        self,
        local,
        data_inicio: date,
        data_fim: date,
        passo_temporal: str,
    ) -> pd.DataFrame:
        """Busca radiação em céu limpo no McClear (via pvlib) e padroniza."""
        # 1) Valida o e-mail de autenticação com mensagem amigável.
        if not email_valido(self.email):
            raise ValueError(
                "Para usar o CAMS McClear é preciso informar o e-mail da sua "
                "conta SoDa (gratuita e individual, criada em soda-pro.com). "
                "Configure-o no campo de e-mail da barra lateral."
            )

        # 2) Validação de período: rejeita datas mais recentes que o limite,
        #    com mensagem amigável informando a última data disponível.
        limite = self.ultima_data_disponivel()
        if data_fim > limite:
            raise ValueError(
                "Os dados do CAMS McClear têm cerca de 2 dias de defasagem. "
                f"A data final pedida ({data_fim:%d/%m/%Y}) ainda não está "
                f"disponível. A data mais recente que você pode usar é "
                f"{limite:%d/%m/%Y}. Ajuste o período e tente de novo."
            )
        if data_inicio > data_fim:
            raise ValueError(
                "A data de início não pode ser depois da data de fim. "
                "Revise o período escolhido."
            )

        # 3) Cache-first: a mesma consulta nunca rebate na API.
        chave = self._chave_cache_identificador(
            local, data_inicio, data_fim, passo_temporal
        )
        em_cache = self._ler_cache(chave)
        if em_cache is not None:
            return em_cache

        # 4) Cache miss -> consulta real à API via pvlib.
        dados = self._chamar_pvlib(local, data_inicio, data_fim, passo_temporal)

        df = self._padronizar_resposta(dados)
        # Garante a grade completa do período (instantes faltantes viram NaN).
        df = self._reindexar_periodo(df, data_inicio, data_fim, passo_temporal)
        df = self._padronizar_colunas(df)
        self._salvar_cache(chave, df)
        return df

    # ------------------------------------------------------------------
    def _chave_cache_identificador(
        self, local, data_inicio, data_fim, passo_temporal
    ) -> str:
        """Chave de cache que também separa por ``identifier``."""
        chave = self._chave_cache(local, data_inicio, data_fim, passo_temporal)
        # Mantém as chaves "mcclear" existentes; só diferencia outros modos.
        if self.identifier != "mcclear":
            chave = f"{chave}_{self.identifier}"
        return chave

    def _chamar_pvlib(
        self, local, data_inicio, data_fim, passo_temporal
    ) -> pd.DataFrame:
        """Faz a chamada REAL à API SoDa via pvlib, com erros amigáveis."""
        time_step = ISO_PARA_PVLIB.get(passo_temporal, "1h")

        # Contabiliza e registra a chamada real (cache miss).
        type(self).chamadas_reais_api += 1
        logger.info(
            "[%s] Chamada REAL à API SoDa (#%d): %s a %s, passo %s, identifier=%s.",
            self.nome,
            self.chamadas_reais_api,
            data_inicio,
            data_fim,
            passo_temporal,
            self.identifier,
        )

        # Importa pvlib aqui dentro para que o resto do projeto não dependa dela
        # caso o pesquisador use apenas a NASA POWER.
        import pvlib

        try:
            dados, _meta = pvlib.iotools.get_cams(
                latitude=local.latitude,
                longitude=local.longitude,
                start=pd.Timestamp(data_inicio),
                end=pd.Timestamp(data_fim),
                email=self.email,
                identifier=self.identifier,
                # Altitude None faz o SoDa estimá-la (via base de dados SRTM).
                altitude=(
                    local.altitude
                    if local.altitude and local.altitude > 0
                    else None
                ),
                time_step=time_step,
                # UTC. A NASA POWER é alinhada ao mesmo fuso via
                # time-standard=UTC (ver sources/nasa_power.py); todo o projeto
                # — grade, QC e validação — pressupõe UTC.
                time_ref="UT",
                verbose=False,
                # Valores integrados (Wh/m² por passo). No passo horário isso é
                # numericamente igual à irradiância média em W/m².
                integrated=True,
                map_variables=True,
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001 - traduzimos para erro amigável
            raise RuntimeError(self._mensagem_erro_amigavel(exc)) from exc
        return dados

    @staticmethod
    def _mensagem_erro_amigavel(exc: Exception) -> str:
        """Traduz a exceção da pvlib/SoDa para uma mensagem em português."""
        txt = str(exc).lower()

        sem_conexao = isinstance(
            exc, (requests.ConnectionError,)
        ) or any(
            t in txt
            for t in ("connection", "max retries", "failed to establish",
                      "name or service not known", "getaddrinfo")
        )
        if sem_conexao:
            return (
                "Não foi possível conectar ao servidor do CAMS (SoDa). "
                "Verifique sua conexão com a internet e tente novamente."
            )

        if isinstance(exc, requests.Timeout) or "timed out" in txt or "timeout" in txt:
            return (
                "O servidor do CAMS (SoDa) demorou demais para responder "
                "(tempo esgotado). Tente novamente em alguns minutos."
            )

        if any(
            t in txt
            for t in ("429", "too many", "limit", "quota", "exceeded",
                      "max number")
        ):
            return (
                "Você atingiu o limite de requisições do CAMS (SoDa) para hoje "
                "(são 100 por conta/dia). Tente novamente amanhã ou use um "
                "período menor — repetições idênticas usam o cache e não contam."
            )

        if any(
            t in txt
            for t in ("not registered", "unknown", "403", "forbidden", "401",
                      "unauthorized", "user", "email", "e-mail")
        ):
            return (
                "O CAMS (SoDa) recusou a autenticação. O e-mail informado "
                "precisa estar CADASTRADO e CONFIRMADO em soda-pro.com. Após "
                "criar a conta, o SoDa envia um link de confirmação por e-mail — "
                "clique nele antes de usar a ferramenta."
            )

        return (
            "O serviço do CAMS (SoDa) parece estar indisponível no momento "
            f"(detalhe técnico: {exc}). Tente novamente mais tarde."
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _padronizar_resposta(dados: pd.DataFrame) -> pd.DataFrame:
        """Converte o DataFrame da pvlib no DataFrame padronizado do projeto.

        A pvlib devolve os dados indexados por tempo e (com map_variables=True)
        com nomes em minúsculas. Aqui: o índice vira a coluna ``timestamp`` e os
        componentes de CÉU LIMPO são renomeados para o padrão GHI/DNI/DHI/BHI,
        mantendo apenas timestamp + os componentes presentes. Colunas extras
        (ghi_extra, e — no cams_radiation — ghi/dni/... reais e Reliability)
        são ignoradas, pois esta fonte representa o céu limpo.
        """
        df = dados.reset_index()
        # A primeira coluna após reset_index é o tempo (nome varia por versão).
        col_tempo = df.columns[0]
        df = df.rename(columns={col_tempo: "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)

        resultado = pd.DataFrame({"timestamp": df["timestamp"]})
        for padrao, candidatos in CANDIDATOS_COMPONENTE.items():
            for nome_pvlib in candidatos:
                if nome_pvlib in df.columns:
                    resultado[padrao] = pd.to_numeric(
                        df[nome_pvlib], errors="coerce"
                    )
                    break

        resultado = resultado.dropna(subset=["timestamp"]).reset_index(drop=True)
        return resultado
