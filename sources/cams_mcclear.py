"""
sources/cams_mcclear.py
=======================

Cliente do CAMS McClear (serviço SoDa) — fonte primária, com radiação em
CÉU LIMPO (sem nuvens), o "teto teórico" da radiação possível no ponto.

A partir da correção, o acesso ao SoDa é feito pela biblioteca **pvlib**
(``pvlib.iotools.get_cams``), a função oficial, testada e mantida pela
comunidade de energia solar. Isso resolve o erro 404 (a montagem manual da URL
usava o endpoint e o formato de parâmetros errados) e dá credibilidade
acadêmica ao projeto, pois pvlib é a biblioteca-padrão da área.

Características do serviço (decisões já tomadas no projeto):
  - Autenticação pelo e-mail cadastrado E CONFIRMADO em soda-pro.com (não há
    chave de API). O e-mail é recebido no construtor, nunca de constante global.
  - Cobertura mundial -> cobre_local sempre True.
  - Componentes retornados: GHI, DNI, DHI, BNI.
  - Atraso dos dados: sempre current_day - 2 (dois dias de defasagem).
  - Limite de 100 requisições por dia por conta.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

from core.credenciais import email_valido
from sources.base import FonteRadiacao

logger = logging.getLogger(__name__)

# Atraso fixo dos dados do McClear: sempre dois dias atrás.
ATRASO_DIAS = 2

# A pvlib espera o passo temporal nos códigos '1min'/'15min'/'1h'/'1d'/'1M',
# não nos códigos ISO 8601 usados internamente pelo projeto. Convertemos aqui.
ISO_PARA_PVLIB: dict[str, str] = {
    "PT01M": "1min",
    "PT15M": "15min",
    "PT01H": "1h",
    "P01D": "1d",
    "P01M": "1M",
}

# Com map_variables=True a pvlib renomeia as colunas do McClear para nomes
# padronizados em minúsculas, com o sufixo "_clear" (céu limpo). Mapeamos esses
# nomes (e também as variantes sem sufixo, por robustez entre versões) para o
# padrão do projeto. Observação: "BHI" do McClear corresponde ao "BNI" do
# projeto (irradiação de feixe).
RENOMEAR_COLUNAS: dict[str, str] = {
    "ghi_clear": "GHI",
    "ghi": "GHI",
    "dni_clear": "DNI",
    "dni": "DNI",
    "dhi_clear": "DHI",
    "dhi": "DHI",
    "bhi_clear": "BNI",
    "bhi": "BNI",
}


class CamsMcClear(FonteRadiacao):
    """Cliente da fonte CAMS McClear (radiação em céu limpo) via pvlib."""

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
        """Busca radiação em céu limpo no McClear (via pvlib) e padroniza."""
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

        # Converte o passo do projeto (ISO) para o código aceito pela pvlib.
        time_step = ISO_PARA_PVLIB.get(passo_temporal, "1h")

        logger.info(
            "[%s] Consultando SoDa via pvlib de %s a %s (passo %s).",
            self.nome,
            data_inicio,
            data_fim,
            passo_temporal,
        )

        # Importa pvlib aqui dentro para que o resto do projeto não dependa dela
        # caso o pesquisador use apenas a NASA POWER.
        import pvlib

        try:
            dados, _meta = pvlib.iotools.get_cams(
                latitude=local.latitude,
                longitude=local.longitude,
                start=data_inicio,
                end=data_fim,
                email=self.email,
                identifier="mcclear",
                # Altitude None faz o SoDa estimá-la (via base de dados SRTM).
                altitude=(
                    local.altitude
                    if local.altitude and local.altitude > 0
                    else None
                ),
                time_step=time_step,
                time_ref="UT",
                verbose=False,
                # Valores integrados (Wh/m² por passo), para ficar consistente
                # com a NASA POWER, que o projeto normaliza para Wh/m².
                integrated=True,
                map_variables=True,
                timeout=self.timeout,
            )
        except Exception as exc:  # noqa: BLE001 - traduzimos para erro amigável
            raise RuntimeError(
                "Falha ao consultar o CAMS McClear (SoDa) via pvlib: "
                f"{exc}\n\n"
                "Causa mais comum: o e-mail informado precisa estar CADASTRADO "
                "e CONFIRMADO em soda-pro.com. Após criar a conta, o SoDa envia "
                "um link de confirmação por e-mail — clique nele antes de usar a "
                "ferramenta. Verifique também sua conexão com a internet."
            ) from exc

        df = self._padronizar_resposta(dados)
        df = self._padronizar_colunas(df)
        self._salvar_cache(chave, df)
        return df

    # ------------------------------------------------------------------
    @staticmethod
    def _padronizar_resposta(dados: pd.DataFrame) -> pd.DataFrame:
        """Converte o DataFrame da pvlib no DataFrame padronizado do projeto.

        A pvlib devolve os dados indexados por tempo e (com map_variables=True)
        com nomes em minúsculas. Aqui: o índice vira a coluna ``timestamp`` e os
        componentes são renomeados para o padrão GHI/DNI/DHI/BNI, mantendo
        apenas timestamp + os componentes presentes.
        """
        df = dados.reset_index()
        # A primeira colula após reset_index é o tempo (nome varia por versão).
        col_tempo = df.columns[0]
        df = df.rename(columns={col_tempo: "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)

        # Renomeia os componentes conhecidos para o padrão do projeto.
        renomear = {c: RENOMEAR_COLUNAS[c] for c in df.columns if c in RENOMEAR_COLUNAS}
        df = df.rename(columns=renomear)

        # Mantém apenas timestamp + componentes padrão presentes.
        componentes = [c for c in ("GHI", "DNI", "DHI", "BNI") if c in df.columns]
        resultado = pd.DataFrame({"timestamp": df["timestamp"]})
        for c in componentes:
            resultado[c] = pd.to_numeric(df[c], errors="coerce")

        resultado = resultado.dropna(subset=["timestamp"]).reset_index(drop=True)
        return resultado
