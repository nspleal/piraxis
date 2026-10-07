# PIRAXIS — extrator de radiação solar

Ferramenta acadêmica **local** (UNESP / FCA Botucatu) que extrai **radiação solar**
para um ponto, valida a qualidade fisicamente e exporta uma planilha Excel no
modelo do pesquisador. Fontes de dados: **CAMS McClear** (céu limpo, via SoDa/pvlib)
e **NASA POWER** (céu real). Nome: *piranômetro* + *axis*.

> **Princípio de fidelidade:** toda extração sai **idêntica à sua fonte** — mesma
> convenção de rótulo, unidades e precisão do download oficial (comprovável pela
> aba de Conferência, que compara linha a linha com o CSV do site).

## Para usar a versão 1.1 (Windows, sem instalar nada)

1. O build da branch `piraxis-1.1-interface` publica o pacote separado na
   **[Release 1.1](../../releases/tag/v1.1)** após passar nas verificações.
2. Baixe `PIRAXIS-1.1-windows-x64.zip` e extraia em um caminho curto e novo,
   por exemplo `C:\PIRAXIS-1.1`, preservando a pasta da versão anterior.
3. Dois cliques em **`INICIAR PIRAXIS.bat`**. O Python já está embutido.
   Use `VERIFICAR INSTALACAO.bat` para o autoteste offline.

A versão anterior continua disponível no mesmo link:
**[`PIRAXIS-windows-x64.zip`](../../releases/download/pacote-windows/PIRAXIS-windows-x64.zip)**.
O workflow desta branch cria exclusivamente a release `v1.1` e falha se ela já
existir. Detalhes de preservação, diagnóstico e verificação em
[`VERSAO-1.1.md`](VERSAO-1.1.md).

## Para desenvolver

O código vive em [`Programa/`](Programa/) — instruções completas no
[`Programa/README.md`](Programa/README.md). Resumo:

```bash
cd Programa
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest          # suíte sem rede (mockada)
streamlit run app/streamlit_app.py
```

Todo push/PR roda a suíte automaticamente (workflow **Testes**).

## Estrutura

| Pasta/arquivo | O quê |
|---|---|
| `Programa/core/` | combinação de fontes, QC físico, conferência de fidelidade, reprodutibilidade |
| `Programa/sources/` | clientes CAMS McClear e NASA POWER (cache-first, UTC) |
| `Programa/output/` | exportador Excel (modelo do pesquisador) |
| `Programa/app/` | interface Streamlit (tema escuro, 4 abas) |
| `empacotar.py` | build do pacote portátil (CPython embutido, reprodutível via `requirements.lock`) |
| `CLAUDE.md` | estado vivo do projeto (decisões, pendências) |

## Status

Projeto de Iniciação Científica (UNESP). **Todos os direitos reservados** — o
modelo de proteção/licenciamento (registro INPI) está em definição; este
repositório é privado e o código não está licenciado para redistribuição.
