# CLAUDE.md — Extrator de Radiação Solar (IC-dal-pai)

> Guia ENXUTO para sessões do Claude Code. O conhecimento profundo (decisões,
> arquitetura, roadmap) vive no **cofre** (LLM Wiki) — ver bloco no fim. **Não
> duplique aqui.**

## 1. Visão rápida
Ferramenta local (app Streamlit, sem deploy web) que extrai **radiação solar**
para um ponto, valida, e exporta uma planilha Excel no modelo do pesquisador.
Projeto acadêmico da UNESP; local padrão **Botucatu/SP** (−22.8867, −48.4450,
786 m). Fontes: **CAMS McClear** (céu limpo, via `pvlib`) e **NASA POWER** (real).

## 2. Mapa de pastas/módulos (tudo dentro de `Programa/`)
- `Programa/` — o projeto; a raiz só tem o launcher + esta pasta.
- `core/config.py` — `Local`, `BOTUCATU`, componentes (GHI/DNI/DHI/**BHI**), passos, caminhos.
- `core/credenciais.py` — e-mail SoDa por máquina (`~/.radiacao_solar/config.json`).
- `core/combinador.py` — une as fontes por timestamp; calcula `kt` (índice de claridade).
- `core/qualidade.py` — QC físico (lacunas, negativos, noturno, envelope, fechamento, concordância).
- `core/reprodutibilidade.py` — proveniência (.json), metodologia PT/EN e citações (sem e-mail).
- `core/pipeline.py` — extração→Excel headless (sem UI), usado pela validação.
- `core/conferencia.py` — auditoria + conferência de fidelidade (extração × CSV do site da SoDa, via `pvlib.read_cams`).
- `sources/base.py` — `FonteRadiacao` (ABC) + cache + reindex da grade temporal.
- `sources/cams_mcclear.py` — cliente McClear via `pvlib.iotools.get_cams` (cache-first, contador de API).
- `sources/nasa_power.py` — cliente NASA POWER (REST, −999→NaN, normaliza unidade).
- `output/exporta_excel.py` — Excel no modelo oficial (abas Resumo, Dados, Qualidade, Reprodutibilidade).
- `app/streamlit_app.py` — interface (cards, gráficos Plotly, painel de QC, downloads).
- `tests/` — `pytest` (mockado, sem rede) + scripts `validar_*.py` (suíte de validação).
- `INICIAR EXTRATOR DE RADIAÇÃO.bat` / `Programa/INICIAR (Mac e Linux).command` — launchers.

## 3. Como rodar e testar
- **Rodar:** dois cliques no `INICIAR EXTRATOR DE RADIAÇÃO.bat` (cria `.venv`, instala, abre o app).
  Manual: dentro de `Programa/` → `streamlit run app/streamlit_app.py`.
- **Testes unitários:** dentro de `Programa/` → `python -m pytest` (sem rede).
- **Validação completa:** `python tests/rodar_validacao_completa.py` (lê o e-mail SoDa de
  `~/.radiacao_solar/config.json` > `SODA_EMAIL` > `--email`; itens de API ficam PULADOS sem e-mail).

## 4. Estado e KNOWN ISSUES (desta sessão; podem não estar no código)
- **Renomeação BNI→BHI** concluída: o 4º componente é **Feixe Horizontal** (`bhi_clear`).
- **Cache versionado:** a chave de cache inclui `CACHE_SCHEMA` (`sources/base.py`). Ao mudar o
  formato dos dados (unidade, fuso, nomes de coluna), **incremente a versão** — caches antigos passam
  a ser ignorados sozinhos (**não precisa apagar `Programa/cache/` na mão**). Versão atual: **4**
  (NASA em UTC; CAMS com a **altitude do ponto** — igual ao site; ordem de colunas GHI/BHI/DHI/DNI).
- **✅ Incoerência dos dados — CAUSA CONFIRMADA E CORRIGIDA (fuso horário):** a **NASA POWER** entrega
  **LST (hora solar local)** por padrão, enquanto o **McClear é UTC** e todo o projeto (grade, QC,
  validação) pressupõe UTC → as fontes ficavam **~3 h fora de fase** em Botucatu (kt sem sentido,
  picos deslocados). **Fix:** `sources/nasa_power.py` envia `time-standard=UTC` (horário e diário);
  o cache versionado impede que respostas antigas (LST) mascarem a correção; o app deixa explícito
  que os horários são **UTC**. Teste de regressão em `tests/test_nasa.py`. ⚠️ **Validar com rede real**
  na máquina do pesquisador.
- **✅ Incoerência do CAMS McClear — CORRIGIDA (altitude + ordem de colunas):** (a) **valores
  levemente off = ALTITUDE.** O download do site registra a altitude usada no cabeçalho (ex.: `Altitude
  (m): 786.00`). O cliente envia a **altitude configurada do ponto** (786 m), **não SRTM**, para bater
  exato — **use a MESMA altitude no formulário da SoDa** (cai em SRTM só se a altitude for ≤ 0). ⚠️ Isto
  REVERTEU a tentativa anterior de usar SRTM, que deixava ~0,2% de diferença. (b) **"colunas trocadas"**
  = a ordem diferia da SoDa → `COMPONENTES_PADRAO` = **GHI, BHI, DHI, DNI** (o **DNI** do projeto é o
  **BNI** da SoDa). Regressão em `tests/test_cams.py`. ⚠️ **Validar com rede real**.
- **✅ Auditoria/conferência — IMPLEMENTADO:** `core/conferencia.py` compara a extração com o CSV
  baixado do site (via `pvlib.read_cams`) e gera um **relatório de fidelidade** (status + Δ por
  componente, alinhado por timestamp). No app: aba "🔬 Conferência com o site" (sobe o CSV → relatório
  + download `.md`) e download das **respostas cruas** das fontes (auditoria). As fontes guardam a
  resposta crua em `self.resposta_crua`. A conferência **detecta e decodifica sozinha** um CSV aberto/
  salvo no Excel pt-BR (ponto decimal vira separador de milhar → valores ~10.000× maiores) e **avisa**
  quando a altitude do site difere da extração. Testes em `tests/test_conferencia.py`.
- **Ambiente de nuvem:** sem rede para a API SoDa e sem e-mail → validações de API ficam PULADAS aqui;
  confirme na máquina local do pesquisador.

## 5. Modo de trabalho (autonomia acordada com o pesquisador)
- **Autonomia:** ao fazer uma mudança, rode a verificação (`python -m pytest`; `validar_*.py` quando
  fizer sentido) e, **se passar**, **committe e pushe na branch de trabalho** sem pedir confirmação.
  Mantenha docs/estado **atualizados proativamente** (este arquivo inclusive).
- **Sem teste cobrindo a mudança:** adicione um; se não for viável, **avise** em vez de empurrar no
  escuro. **Se um teste falhar:** não pushe — corrija ou reporte.
- **Auto-merge autorizado (2026-06-20):** com a verificação **verde**, posso **abrir o PR e mergear na
  branch padrão** do repositório **sem pedir confirmação** (o pesquisador revisa pelo histórico/PR
  depois). A branch padrão hoje é `claude/confident-turing-1NV8t` (não existe `main`).
- **Ainda confirmar antes:** ações **irreversíveis** (apagar/sobrescrever o que não criei, reescrever
  histórico, `force-push`) e mudanças que contrariem decisões travadas/escopo.
- **Cofre (`obsidian`):** **somente leitura** — nunca editar/commitar/pushar (ver bloco abaixo).

------------------------------------------------------------------
## Base de conhecimento do projeto — cofre (LLM Wiki, SOMENTE LEITURA)

Este projeto tem uma base de conhecimento externa (um "LLM Wiki" em markdown) no repositório
privado nspleal/obsidian (o "cofre"), que documenta decisões, arquitetura, estado e roadmap. É a
FONTE DE VERDADE. Consulte-a SEMPRE.

No início de TODA sessão:
1. Garanta o cofre atualizado:
   - se a pasta cofre/ não existir:  git clone https://github.com/nspleal/obsidian.git cofre
   - se já existir:                  git -C cofre pull
2. Leia: cofre/CLAUDE.md, cofre/wiki/index.md, cofre/wiki/overview.md (este traz a PRIORIDADE ATUAL).

Antes de QUALQUER decisão importante:
1. Veja o histórico recente:  grep -n "^## \[" cofre/wiki/log.md | tail -15  (e leia as relevantes).
2. Aprofunde nas páginas do domínio meteo: cofre/wiki/entidades/extrator-radiacao-solar.md,
   cofre/wiki/conceitos/arquitetura-extrator-radiacao.md, cofre/wiki/conceitos/pipeline-e-validacao-radiacao.md,
   cofre/wiki/conceitos/componentes-irradiancia-solar.md, cofre/wiki/entidades/fontes-de-dados-candidatas.md.
3. Respeite as decisões já travadas e a prioridade atual; se algo conflitar, aponte explicitamente.

REGRA DE OURO — somente leitura: NUNCA edite/commite/push no cofre. Ele é mantido só pela sessão
LOCAL do Claude Code. Decisões novas: NÃO escreva no cofre — RESUMA para o usuário levar à sessão local.
Adicione cofre/ ao .gitignore deste repositório.
------------------------------------------------------------------
