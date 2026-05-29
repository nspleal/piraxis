# ☀️ Extrator de Radiação Solar (UNESP)

Ferramenta **local** (roda no seu computador, sem nada na nuvem) para **extrair,
comparar e exportar** dados de **radiação solar** de um ponto geográfico para uma
**planilha Excel** formatada. A interface é um aplicativo que abre no navegador.

Projeto acadêmico da UNESP. Foco exclusivo em **radiação solar** (não há
temperatura, vento ou outras variáveis).

Local padrão de estudo: **Botucatu/SP** (latitude −22.8867, longitude −48.4450,
altitude 786 m). Você pode usar qualquer ponto do mundo.

---

## O que a ferramenta faz

Ela combina **duas fontes gratuitas** de dados:

| Fonte | Papel | Precisa de cadastro? |
|-------|-------|----------------------|
| **CAMS McClear** (SoDa) | Radiação em **céu limpo** (o "teto teórico", sem nuvens) | **Sim** — uma conta gratuita e individual em [soda-pro.com](https://www.soda-pro.com) |
| **NASA POWER** | Radiação **real** (considerando nuvens) | **Não** — funciona sem cadastro |

Você escolhe usar **só uma** ou **as duas combinadas**. Com as duas, a ferramenta
calcula o **índice de claridade** (`kt = radiação real / radiação céu limpo`), uma
medida muito útil cientificamente.

---

## Instalação passo a passo (para quem nunca usou Python no terminal)

### 1. Instale o Python

- Baixe o Python **3.11 ou mais novo** em [python.org/downloads](https://www.python.org/downloads/).
- **No Windows**, na hora de instalar, marque a caixinha **"Add Python to PATH"**.

### 2. Baixe esta ferramenta

Baixe a pasta do projeto (pelo Git ou como arquivo .zip) e descompacte em um
lugar fácil de achar, por exemplo a Área de Trabalho.

### 3. Inicie com dois cliques

Abra a pasta **`INICIAR AQUI`** (ela aparece no topo do projeto) e dê **dois
cliques** no arquivo da sua plataforma:

- **Windows:** **`Iniciar Aplicação (Windows).bat`**
- **Mac/Linux:** **`Iniciar Aplicação (Mac e Linux).command`**

Há também um **`LEIA-ME.txt`** dentro dessa pasta com instruções simples.

Na **primeira vez**, o script cria o ambiente, instala tudo o que é necessário
(pode demorar alguns minutos) e abre o aplicativo no navegador. Nas próximas
vezes ele abre direto.

> Se preferir o terminal, os comandos manuais são:
> ```bash
> python -m venv .venv
> # Windows:  .venv\Scripts\activate
> # Linux/Mac: source .venv/bin/activate
> pip install -r requirements.txt
> streamlit run app/streamlit_app.py
> ```

---

## Primeiro uso

1. **Abra a ferramenta** (dois cliques no atalho dentro da pasta `INICIAR AQUI`).
2. Para usar a **NASA POWER**, não precisa fazer nada: já funciona.
3. Para usar o **CAMS McClear**, você precisa de uma **conta gratuita** no SoDa:
   - Acesse [soda-pro.com](https://www.soda-pro.com) e **crie sua conta** com seu
     e-mail (de preferência o institucional `@unesp.br`).
   - **Por que individual?** O SoDa não usa senha/chave de API — a credencial é o
     **próprio e-mail cadastrado**. O limite de requisições é **por conta**, então
     cada pesquisador deve usar o **seu** e-mail. Compartilhar um e-mail faz todos
     competirem pela mesma cota e pode bloquear o acesso.
   - Na primeira abertura, o aplicativo pede esse e-mail e o **guarda só nesta
     máquina** (no arquivo `~/.radiacao_solar/config.json`, fora do projeto — ele
     **nunca** vai para o Git).
4. Preencha **local**, **período** e **passo temporal**, escolha as **fontes** e
   clique em **🚀 Extrair dados**.
5. Veja a **pré-visualização** (tabela + gráfico) e clique em **📊 Baixar Excel**.

### Computadores compartilhados de laboratório

O campo **E-mail SoDa** na barra lateral é sempre editável. Você pode **digitar o
seu e-mail só para aquela sessão** (sem salvar) — ele tem **prioridade** sobre o
e-mail salvo na máquina. Para gravar como padrão da máquina, use o botão
**"Salvar como padrão desta máquina"**.

---

## A planilha gerada

O arquivo `radiacao_<local>_<inicio>_<fim>.xlsx` é salvo na pasta `data/` e tem:

- **Resumo** — metadados do estudo e estatísticas (média/máx/mín) calculadas com
  **fórmulas do Excel**.
- **Dados** — a série temporal completa, uma linha por instante.
- **Comparação** — só quando você usa as duas fontes: índice de claridade,
  diferença McClear vs NASA e um **gráfico** nativo do Excel.

---

## Detalhes técnicos úteis

- **Defasagem dos dados:** o McClear sempre tem **2 dias de atraso**. A ferramenta
  impede datas mais recentes que isso e avisa.
- **Unidades:** tudo é normalizado para **Wh/m²**.
- **Cache:** repetir a mesma extração **não** chama a API de novo — lê do cache
  local (pasta `cache/`). Isso acelera o trabalho e protege contra limites de uso.
- **Valores ausentes** (ex.: `-999` da NASA) viram células vazias, não zeros.

---

## Estrutura do projeto

```
radiacao-solar/
├── app/streamlit_app.py     # Interface (ponto de entrada do usuário)
├── core/
│   ├── config.py            # Constantes, Local, Botucatu, caminhos
│   ├── credenciais.py       # E-mail SoDa por máquina
│   └── combinador.py        # Combina McClear + NASA e calcula kt
├── sources/
│   ├── base.py              # Interface FonteRadiacao + cache
│   ├── cams_mcclear.py      # Cliente CAMS McClear (SoDa)
│   └── nasa_power.py        # Cliente NASA POWER
├── output/exporta_excel.py  # Gera a planilha Excel formatada
├── cache/                   # Cache local (criado em runtime)
├── data/                    # Planilhas geradas (criado em runtime)
├── tests/                   # Testes pytest (sem rede real)
├── INICIAR AQUI/            # Atalhos de inicialização por duplo clique + LEIA-ME
├── requirements.txt
├── pyproject.toml
└── README.md
```

A arquitetura de fontes é **extensível**: para adicionar uma nova fonte no futuro,
basta criar um arquivo em `sources/` com uma classe que herde de `FonteRadiacao`.

---

## Rodando os testes (desenvolvedores)

```bash
pip install -r requirements.txt   # inclui pytest e responses
pytest
```

Os testes **não fazem rede real** — as APIs são simuladas.
