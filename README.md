# BTG Pactual — Monitor de Ofertas Públicas de FIIs

Pipeline de inteligência de mercado para monitoramento de ofertas públicas de Fundos de Investimento Imobiliário (Resolução CVM 160), com ranqueamento determinístico por P/VP e enriquecimento qualitativo via LLM.

---

## Arquitetura

Pipeline em três fases, separando processamento barato (matemática) de processamento caro (IA), aplicado seletivamente.

```
┌─────────────────────────────────────────────────────────────────────┐
│ FASE 1 — Matemática e cruzamento (rápido, barato)                   │
│   CVM 160 (ofertas 30d)  ─┐                                          │
│                            ├──► merge por CNPJ  ──►  P/VP calculado  │
│   CVM informe mensal (VPA) ┘                                          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ FASE 2 — Inteligência qualitativa (pesado, caro, SELETIVO)          │
│   Triagem: Top 10 P/VP + IPOs sem VPA                                │
│        │                                                              │
│        ▼                                                              │
│   Playwright headless ──► texto limpo da notícia                     │
│        │                                                              │
│        ▼                                                              │
│   Groq (Llama 3.1) ──► segmento, estratégia, yield                   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ FASE 3 — Consolidação                                               │
│   Merge CVM (números) + Groq (qualitativos) → dados_finais.json     │
│   Dashboard Streamlit lê o JSON e renderiza o ranking               │
└─────────────────────────────────────────────────────────────────────┘
```

**Princípio:** a CVM é a fonte da verdade para números (determinística); o Groq é a fonte da verdade para narrativa (segmento, estratégia, yield). A triagem garante que o custo de Playwright + LLM cai apenas sobre o subconjunto relevante.

---

## Setup

```bash
# 1. Criar e ativar venv
python3 -m venv .venv
source .venv/bin/activate

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Baixar o browser do Playwright (~150 MB, uma única vez)
playwright install firefox

# 4. Configurar chave do Groq
echo "GROQ_API_KEY=sua_chave_aqui" > .env
```

Obtenha sua chave gratuita em [console.groq.com](https://console.groq.com).

---

## Uso

### Geração do ranking

```bash
python gerar_ranking.py
```

Saída: `dados_finais.json` na raiz do projeto. Tempo típico: ~3–5 minutos (Playwright + Groq aplicados em ~10–15 fundos selecionados).

### Dashboard

```bash
streamlit run app.py
```

Acesse [http://localhost:8501](http://localhost:8501). O painel exibe:

- Top 3 ofertas em destaque com P/VP
- Tabela completa ordenada por score
- Detalhe por fundo com segmento, estratégia e link da fonte analisada

---

## Estrutura do projeto

```
.
├── app.py                              # Dashboard Streamlit
├── gerar_ranking.py                    # Orquestrador do pipeline (F1 → F2 → F3)
├── dados_finais.json                   # Saída consolidada (gerada)
├── requirements.txt
├── .env                                # GROQ_API_KEY (não commitado)
└── src/data_ingestion/
    ├── download_cvm_ofertas.py         # F1.1 — ofertas Res. 160 últimos 30 dias
    ├── calculo_vpa_cvm.py              # F1.2 + F1.3 — VPA + merge + P/VP
    ├── coleta_noticias.py              # F2.5 — Playwright (busca + extração)
    ├── extract_fii_dados.py            # F2.6 — Groq via LangChain
    └── scrape_portais.py               # Utilitário de normalização de nome
```

---

## Decisões de design

| Decisão | Justificativa |
|---|---|
| **Playwright síncrono** | Pandas é síncrono. Async exigiria `asyncio.run()` por linha do `iterrows()` sem ganho real em execução sequencial. |
| **Browser reutilizado em batch** | Startup do Firefox custa ~2–3s. Reutilizar uma única instância para N fundos corta dezenas de segundos no lote. |
| **Triagem antes da IA** | Playwright + Groq em todas as ofertas custaria minutos e tokens. Aplicar só em Top 10 + IPOs sem VPA reduz drasticamente o custo mantendo cobertura de oportunidades. |
| **Groq devolve só campos qualitativos** | Campos numéricos no schema do LLM causam oscilação de tipo (string vs número) e alucinação (atribuição cruzada entre fundos). A CVM já é a fonte determinística. |
| **Erro por fundo não derruba o lote** | Cada coleta retorna `sucesso=False` em vez de levantar exceção, mantendo o pipeline resiliente. |

---

## Stack

- **Python 3.13**
- **Pandas** — processamento tabular
- **Playwright (Firefox headless)** — web scraping resiliente
- **LangChain + Groq (Llama 3.1 8B Instant)** — extração estruturada via Pydantic
- **Streamlit** — dashboard interativo

---

## Limitações conhecidas

- **Relevância da busca para fundos com nome obscuro:** o DuckDuckGo às vezes devolve a mesma landing page genérica do portal financeiro para diferentes fundos com baixa pegada em mídia. A análise do Groq nesses casos pode descrever um fundo correlato em vez do alvo. Mitigação parcial via guard anti-hallucination no prompt; mitigação completa requer ou (a) busca com palavras-chave mais específicas, ou (b) verificação semântica pós-extração.
- **Free tier do Groq (TPM):** o pipeline aplica `sleep(2)` entre chamadas para respeitar o limite de tokens por minuto. Para volumes maiores, considerar tier pago ou batching.
- **Tempo de execução:** o gargalo é o Playwright (carregamento de páginas pesadas). Para acelerar, paralelizar via `ThreadPoolExecutor` sobre a API síncrona já exposta.
