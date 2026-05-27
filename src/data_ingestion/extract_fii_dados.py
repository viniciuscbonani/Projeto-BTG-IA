#!/usr/bin/env python3
"""
Extrai métricas de FIIs usando r.jina.ai + LangChain + LLM.
Arquitetura baseada no padrão do repositório de agentes inteligentes.
"""

import os
import json
import requests
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from langchain_groq import ChatGroq
from dotenv import load_dotenv

# Resolve o caminho para encontrar o .env na raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ─── 1. Schema de Saída (O Contrato de Dados) ─────────────────────────────────
class MetricasFII(BaseModel):
    """Inteligência QUALITATIVA do FII (números ficam com a CVM, fonte determinística).

    Schema enxuto de propósito: só campos string. Cada campo numérico extra é
    (a) uma chance de mismatch de tipo (LLM oscila entre devolver número ou string)
    e (b) uma chance de alucinação (atribuir R$/P/VP do fundo errado ao certo).
    """
    segmento: str | None = Field(default=None, description="Segmento do FII: logístico, lajes corporativas, recebíveis, shoppings, residencial, híbrido, etc.")
    dividend_yield_alvo: str | None = Field(default=None, description="Dividend Yield alvo ou histórico (ex: 11% a.a.)")
    resumo_estrategia: str | None = Field(default=None, description="Breve resumo da estratégia do fundo em 1-2 frases")

    @field_validator("segmento", "dividend_yield_alvo", "resumo_estrategia", mode="before")
    @classmethod
    def _coerce_null_string_to_none(cls, v):
        # Groq às vezes devolve a STRING literal "null"/"none"/"n/a" em vez do JSON null.
        # Normaliza isso aqui para que o caller possa usar `m.segmento or "..."` com segurança.
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("", "null", "none", "n/a", "nao disponivel", "não disponível"):
            return None
        return v

# ─── 2. Ingestão Web (Leitor Jina) ────────────────────────────────────────────
def fetch_page(url: str) -> str:
    """Busca o conteúdo de uma página web via r.jina.ai (Reader)."""
    print(f"📄 Lendo página via r.jina.ai...")
    jina_url = f"https://r.jina.ai/{url}"
    
    # Timeout de 30s pois o Jina as vezes precisa renderizar JavaScript pesado
    resp = requests.get(jina_url, headers={"Accept": "text/plain"}, timeout=30)
    resp.raise_for_status()
    return resp.text

# ─── 3. Motor de Inteligência (LangChain + Groq) ──────────────────────────────
def extract_from_text(content: str, source_url: str) -> MetricasFII:
    """Usa LangChain + ChatGroq para extrair os dados de negócio do texto."""
    
    # Mantemos o modelo de 8B para evitar o erro 429 de Rate Limit diário
    model = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0.0,
    )

    # Força o LLM a respeitar a classe Pydantic
    structured_model = model.with_structured_output(MetricasFII)

    # Limitamos o texto a 6000 caracteres para não estourar os Tokens Por Minuto (TPM)
    texto_limpo = content[:6000]

    prompt = f"""Você é um analista do BTG Pactual lendo uma notícia sobre uma oferta de FII.
    Extraia APENAS três informações qualitativas:
      1. segmento: logístico, lajes corporativas, recebíveis/CRI, shoppings, residencial, híbrido, etc.
      2. dividend_yield_alvo: yield alvo ou histórico (ex: "11% a.a.", "CDI + 2%")
      3. resumo_estrategia: 1-2 frases sobre a estratégia do fundo

    REGRAS CRÍTICAS:
    - Se a notícia for sobre um fundo DIFERENTE (ticker/nome diferente do que você está analisando), retorne TUDO null.
    - Se a informação não estiver clara no texto, retorne null. NÃO INVENTE.
    - Não preencha dados de outro FII só porque a notícia mencionou ele de passagem.

    Texto da fonte:
    ---
    {texto_limpo}
    ---

    URL da fonte original: {source_url}
    """

    print("🤖 Extraindo dados com LangChain + Groq...")
    result = structured_model.invoke(prompt)
    return result

# ─── 4. Interface principal (Para ser chamada pelo Pipeline) ──────────────────
def analisar_url(url: str) -> dict:
    """Função encapsulada para ser importada por outros scripts."""
    try:
        conteudo_markdown = fetch_page(url)
        metricas = extract_from_text(conteudo_markdown, url)
        return metricas.model_dump()
    except Exception as e:
        print(f"❌ Erro ao analisar a URL {url}: {e}")
        return None

# ─── Main (Para testes isolados do desenvolvedor) ─────────────────────────────
def main():
    if not os.environ.get("GROQ_API_KEY"):
        print("❌ Defina a variável GROQ_API_KEY no arquivo .env na raiz do projeto.")
        return

    # Usamos uma URL de teste real de um portal financeiro para validar a extração
    url_teste = "https://statusinvest.com.br/fundos-imobiliarios/rjdi11" 
    print(f"Iniciando teste de extração para o ativo RJDI11")
    
    resultado = analisar_url(url_teste)
    
    if resultado:
        print("\n" + "="*50)
        print("📊 MÉTRICAS EXTRAÍDAS COM SUCESSO")
        print("="*50)
        print(json.dumps(resultado, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()