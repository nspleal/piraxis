# CLAUDE.md — PIRAXIS (extrator de radiação solar)

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
- `core/config.py` — `Local`, `BOTUCATU`, componentes (TOA/GHI/DNI/DHI/**BHI**), passos, caminhos
  e as **cores da identidade visual** (`CORES`/`CORES_CEU_LIMPO`/`NOMES_COMPONENTES`/`ORDEM_CASCATA`).
- `core/credenciais.py` — e-mail SoDa por máquina (`~/.radiacao_solar/config.json`).
- `core/combinador.py` — une as fontes por timestamp; calcula `kt` (índice de claridade).
- `core/qualidade.py` — QC físico (lacunas, negativos, noturno, envelope, fechamento, concordância).
- `core/reprodutibilidade.py` — proveniência (.json), metodologia PT/EN e citações (sem e-mail).
- `core/pipeline.py` — extração→Excel headless (sem UI), usado pela validação.
- `core/conferencia.py` — auditoria + conferência de fidelidade (extração × CSV do site da SoDa, via `pvlib.read_cams`).
- `sources/base.py` — `FonteRadiacao` (ABC) + cache + reindex da grade temporal.
- `sources/cams_mcclear.py` — cliente McClear via `pvlib.iotools.get_cams` (cache-first, contador de API).
- `sources/nasa_power.py` — cliente NASA POWER (REST, −999→NaN, normaliza unidade).
- `output/exporta_excel.py` — Excel no modelo do pesquisador (abas Resumo, Gráficos, Dados, Qualidade, Reprodutibilidade).
- `app/streamlit_app.py` — interface **tema escuro, 4 abas** (Painel, Série temporal, Conferência, Dados);
  barra lateral de configuração; cards, cascata de atenuação, fechamento, gráficos Plotly, QC, downloads.
- `app/assets/` — logos UNESP (variante escura `unesp-horizontal-dark.png`) + `.streamlit/config.toml` (tema escuro).
- `tests/` — `pytest` (mockado, sem rede) + scripts `validar_*.py` (suíte de validação).
- `INICIAR PIRAXIS.bat` / `Programa/INICIAR PIRAXIS (Mac e Linux).command` — launchers.

## 3. Como rodar e testar
- **Rodar:** dois cliques no `INICIAR PIRAXIS.bat` (cria `.venv`, instala, abre o app).
  Manual: dentro de `Programa/` → `streamlit run app/streamlit_app.py`.
- **Testes unitários:** dentro de `Programa/` → `python -m pytest` (sem rede).
- **Validação completa:** `python tests/rodar_validacao_completa.py` (lê o e-mail SoDa de
  `~/.radiacao_solar/config.json` > `SODA_EMAIL` > `--email`; itens de API ficam PULADOS sem e-mail).

## 4. Estado e KNOWN ISSUES (desta sessão; podem não estar no código)
- **✅ NOME OFICIAL: PIRAXIS (travado 2026-06-21):** o projeto chama-se **PIRAXIS** (grafia com **I**,
  SEMPRE MAIÚSCULAS; de *piranômetro* + *axis*). O repositório é **`piraxis`** (codinome antigo:
  `IC-dal-pai`, referência aos **Profs. Dal Pai** — preservar o sobrenome em créditos/citações).
  O rename foi **só de apresentação/metadados** (UI, Excel, launchers, docstrings, README, pyproject,
  este arquivo) — **nada da lógica** de extração/QC/conferência/export mudou. "extrator de radiação
  solar" segue como **descrição/subtítulo** (minúsculo). Título visível e aba do navegador = **PIRAXIS**;
  Excel: arquivo `PIRAXIS_<local>_<ini>_<fim>.xlsx` e título "PIRAXIS — Relatório de Radiação Solar".
  ⚠️ **PENDENTE (ação do pesquisador):** renomear o repositório no GitHub para `piraxis`
  (`gh repo rename piraxis`) — não há `gh`/ferramenta MCP de rename neste ambiente; o GitHub redireciona
  o remoto antigo, mas convém atualizar a URL depois. ⚠️ Sem **símbolo/favicon PIRAXIS** no repo ainda
  (favicon segue ☀️; a logo híbrida piranômetro+arco está só no handoff de branding do cofre).
- **🎯 PRINCÍPIO DE FIDELIDADE (travado 2026-06-21):** toda extração deve sair **idêntica à sua
  fonte** — CAMS McClear no formato do CAMS; NASA POWER no formato da NASA. Hoje o Excel está fiel ao
  **CAMS** (período em faixa início–fim UTC, altitude do ponto, 4 casas decimais). ⚠️ **Ao trabalhar a
  NASA:** revisar o formato para casar com a NASA POWER — provavelmente **timestamp instantâneo único**
  (a NASA rotula a hora, não um intervalo início–fim), além de conferir unidades/colunas/decimais. Em
  extração **combinada** (as duas fontes) será preciso decidir qual formato usar (a definir).
- **✅ TOA incluído (fidelidade CAMS):** a extração do CAMS traz a coluna **TOA** (irradiação no topo
  da atmosfera = extraterrestre; `ghi_extra` da pvlib), como o arquivo do site. Ordem: **TOA, GHI, BHI,
  DHI, DNI**. Cache `CACHE_SCHEMA` = **5**.
- **Renomeação BNI→BHI** concluída: o 4º componente é **Feixe Horizontal** (`bhi_clear`).
- **Cache versionado:** a chave de cache inclui `CACHE_SCHEMA` (`sources/base.py`). Ao mudar o
  formato dos dados (unidade, fuso, nomes de coluna), **incremente a versão** — caches antigos passam
  a ser ignorados sozinhos (**não precisa apagar `Programa/cache/` na mão**). Versão atual: **5**
  (NASA em UTC; CAMS com a **altitude do ponto** — igual ao site; ordem TOA/GHI/BHI/DHI/DNI + coluna TOA).
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
- **✅ Excel: período (faixa) + valores exatos:** a 1ª coluna da aba "Dados" mostra o **PERÍODO** de
  cada valor como faixa **início–fim (UTC)** (ex.: `01/01/2026 08:00–09:00`), idêntico ao "Observation
  period" do site. ⚠️ Não havia defasagem de horário — o app sempre bateu com o site (verificado: Δ=0
  em 240 h); era só convenção de rótulo (instante × intervalo). Valores saem com **4 casas decimais**
  (`FORMATO_DADOS`), sem arredondar (o valor na célula sempre foi exato; mudou a exibição). Como a
  coluna de período virou texto, a tabela de Energia Diária por data saiu da aba Dados — mas
  **voltou na aba Gráficos** (via SUMPRODUCT, ver abaixo). Regressões em `tests/test_export.py`.
- **✅ Excel redesenhado (modelo do pesquisador, 2026-06-21):** Resumo com a tabela de estatísticas em
  **A14:G** (abaixo das Informações Gerais) e o gráfico comparativo no **topo direito (F1)**; nova aba
  **"Gráficos"** (após Resumo) com energia diária por dia (**SUMPRODUCT** sobre o texto do período,
  `LEFT(...,10)`), energia média diária por componente (referencia o Resumo) e **3 gráficos** (perfil
  temporal com cores fixas por componente; energia diária; energia média). Tudo **genérico** sobre os
  componentes presentes (CAMS/NASA/combinado). Regressões em `tests/test_export.py`.
- **✅ Identidade visual ESCURA — REDESENHO COMPLETO (4 telas, 2026-06-21):** o app passou de página
  única clara para **tema escuro** (painel de instrumento científico) com **4 abas** (Painel · Série
  temporal · Conferência · Dados) e barra lateral fixa. Direção definida pelo pesquisador (mockup
  escuro autoritativo). Tokens: fundo `#14181F`, superfícies `#1B212B`/`#222A36`, texto
  `#E6E9EF`/`#9AA5B3`/`#646F7E`, azul interativo `#34618F`/`#4A7AA8`, âmbar `#E0A050` (só o **kt**),
  verde de validação `#6FA67E`. Fontes: **Space Grotesk** (títulos), **JetBrains Mono** (números),
  system-ui (texto). Cores por componente em `core/config.py` (`CORES` real / `CORES_CEU_LIMPO`
  tracejado). Convenção dos gráficos: **real (NASA) = linha cheia; céu limpo (McClear) = tracejada**
  (a distinção só aparece quando as duas fontes estão presentes; fonte única = linha cheia). Elemento
  de assinatura: **cascata de atenuação** (TOA→GHI→DHI→BHI→DNI, % da irradiância no topo) + painel de
  **fechamento GHI = BHI + DHI** (Δ validado). Painel: cards de integral diária (kWh/m²·dia) + pico +
  **kt**. Conferência: tabela de fechamento por registro + QC + fidelidade com o site + auditoria.
  Dados: tabela completa + export Excel/CSV + reprodutibilidade. **Toda a lógica de extração/QC/export
  foi preservada** — só a apresentação mudou. Verificado: `pytest` 47/47, `validar_app` APROVADO,
  `validar_boot` APROVADO. ⚠️ Streamlit não é pixel-perfect — alvo é **fiel ao espírito** do mockup
  (não réplica exata). EM ABERTO: refinos finos de espaçamento/animações de entrada (Streamlit limita).
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
