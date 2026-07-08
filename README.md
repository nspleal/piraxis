# PIRAXIS — extrator de radiação solar

Ferramenta acadêmica **local** (UNESP / FCA Botucatu) que extrai **radiação solar**
para um ponto, valida a qualidade fisicamente e exporta uma planilha Excel no
modelo do pesquisador. Fontes de dados: **CAMS McClear** (céu limpo, via SoDa/pvlib)
e **NASA POWER** (céu real). Nome: *piranômetro* + *axis*.

> **Princípio de fidelidade:** toda extração sai **idêntica à sua fonte** — mesma
> convenção de rótulo, unidades e precisão do download oficial (comprovável pela
> aba de Conferência, que compara linha a linha com o CSV do site).

## Para usar (Windows, sem instalar nada)

1. Baixe o pacote portátil (Python embutido) na Release fixa:
   **[`PIRAXIS-windows-x64.zip`](../../releases/download/pacote-windows/PIRAXIS-windows-x64.zip)**
2. Extraia em um caminho **curto** (ex.: `C:\PIRAXIS`) — o limite de 260
   caracteres do Windows corta arquivos silenciosamente em caminhos fundos.
3. Dois cliques em **`INICIAR PIRAXIS.bat`**. Abre no navegador, offline no 1º uso.

Para gerar um pacote novo: aba **Actions** → *"Empacotar PIRAXIS (Windows portátil)"*
→ **Run workflow** (a Release acima é atualizada no mesmo link).

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
