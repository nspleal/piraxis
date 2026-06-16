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

Ao abrir a pasta do projeto você verá só **duas coisas**: o ícone de início e a
pasta `Programa` (que guarda todo o funcionamento interno — você **não precisa**
entrar nela).

Dê **dois cliques** no ícone de início:

- **Windows:** **`INICIAR EXTRATOR DE RADIAÇÃO.bat`** ← é só esse, o único ícone.
- **Mac/Linux:** abra a pasta `Programa` e dê dois cliques em
  **`INICIAR (Mac e Linux).command`**.

Na **primeira vez**, ele instala tudo o que é necessário (pode demorar alguns
minutos — é normal) e abre o aplicativo no navegador. Nas próximas vezes abre
direto. Para encerrar, feche a janela preta que aparece.

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

1. **Abra a ferramenta** (dois cliques no `INICIAR EXTRATOR DE RADIAÇÃO.bat`).
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

O arquivo `radiacao_<local>_<inicio>_<fim>.xlsx` é salvo na pasta `data/` e segue
o **modelo oficial do projeto** (planilha_modelo_para_IC), com duas abas:

- **Resumo** — título, informações gerais do estudo e a tabela "Estatísticas de
  Radiação" (Média, Média Diurna, Máximo, Mínimo Diurno, Energia e kWh/m²/dia),
  tudo calculado com **fórmulas do Excel**, mais um **gráfico comparativo** por
  componente.
- **Dados** — a série temporal completa numa **tabela do Excel** chamada
  `TabDados` (filtros automáticos e listras), uma tabela de **Energia Diária**
  e dois gráficos: radiação ao longo do tempo e energia por dia.

Na extração **combinada** (duas fontes), as colunas aparecem com o sufixo da
fonte (ex.: `GHI_McClear`, `GHI_NASA`) e o índice de claridade `kt` entra como
coluna na própria tabela de dados.

Além dessas, a planilha traz mais **duas abas**:

- **Qualidade** — o relatório automático de **controle de qualidade** (veja
  abaixo): completude, alertas e o resultado de cada verificação, com uma
  legenda dos critérios usados.
- **Reprodutibilidade** — a **proveniência** da extração (de onde, quando e
  como os dados vieram) e o bloco de **citações e agradecimentos** prontos para
  um artigo.

A ferramenta também salva, ao lado da planilha, dois arquivos para o seu artigo:

- **`..._reprodutibilidade.md`** — texto de metodologia (em **português e
  inglês**) e as referências/agradecimentos.
- **`..._proveniencia.json`** — o registro técnico da extração (versões de
  software, parâmetros etc.). *O e-mail da conta SoDa nunca é incluído* — é uma
  credencial pessoal e irrelevante para a ciência (o dado é o mesmo seja qual
  for a conta).

---

## Controle de qualidade (o que cada verificação significa)

Toda extração passa por checagens automáticas, no padrão da radiometria solar.
O **status geral** é **OK**, **Atenção** ou **Problemas**:

- **Completude / lacunas** — quantos instantes do período realmente vieram com
  dado, e onde há "buracos".
- **Valores negativos** — radiação não pode ser negativa (um pequeno ruído de
  arredondamento, até −1, é tolerado).
- **Radiação noturna** — à noite (Sol abaixo do horizonte) a radiação deve ser
  ~0; valores altos são sinalizados.
- **Envelope de céu limpo** — a radiação **real** (com nuvens) não pode superar
  a de **céu limpo** além de uma margem (10% em passo ≥ 1 h; 25% em alta
  frequência, por causa do fenômeno real de *cloud enhancement*).
- **Equação de fechamento** — confere a relação física `GHI ≈ DHI + DNI·cos(θz)`.
  Vale em **alta frequência** (1 e 15 min, e 1 h com tolerância maior); em
  **diário/mensal** é marcada como **"não aplicável"** (a relação não vale sobre
  valores somados no tempo).
- **Concordância entre fontes** — quando você usa as duas, compara o céu limpo
  do **McClear** com o do **NASA (CLRSKY)** — duas estimativas independentes —
  com RMSE, viés e correlação. Não custa requisição extra.

A geometria solar (posição do Sol) é calculada com a biblioteca **pvlib**.

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
Pasta-do-projeto/
├── INICIAR EXTRATOR DE RADIAÇÃO.bat   # ⭐ O único ícone: dois cliques aqui (Windows)
└── Programa/                          # Todo o funcionamento interno (não precisa entrar)
    ├── app/streamlit_app.py     # Interface (ponto de entrada do usuário)
    ├── core/
    │   ├── config.py            # Constantes, Local, Botucatu, caminhos
    │   ├── credenciais.py       # E-mail SoDa por máquina
    │   └── combinador.py        # Combina McClear + NASA e calcula kt
    ├── sources/
    │   ├── base.py              # Interface FonteRadiacao + cache + grade do período
    │   ├── cams_mcclear.py      # Cliente CAMS McClear (via pvlib)
    │   └── nasa_power.py        # Cliente NASA POWER
    ├── output/exporta_excel.py  # Gera a planilha Excel formatada
    ├── cache/                   # Cache local (criado em runtime)
    ├── data/                    # Planilhas geradas (criado em runtime)
    ├── tests/                   # Testes pytest (sem rede real)
    ├── INICIAR (Mac e Linux).command  # Início para Mac/Linux
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
