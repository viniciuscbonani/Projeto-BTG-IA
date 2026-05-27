#!/usr/bin/env python3
"""
Extrai métricas de FIIs usando r.jina.ai + LangChain + LLM.
Arquitetura baseada no padrão do repositório de agentes inteligentes.
"""

import os
import json
import requests
from pathlib import Path
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from dotenv import load_dotenv

# Resolve o caminho para encontrar o .env na raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# ─── 1. Schema de Saída (O Contrato de Dados) ─────────────────────────────────
class MetricasFII(BaseModel):
    """Métricas financeiras extraídas do documento ou portal de um FII."""
    pvp_numerico: float | None = Field(default=None, description="Valor numérico exato do P/VP (ex: 0.95, 1.02)")
    preco_emissao: str | None = Field(default=None, description="Preço de emissão da cota na oferta")
    valor_patrimonial_cota: str | None = Field(default=None, description="Valor patrimonial por cota")
    dividend_yield_alvo: str | None = Field(default=None, description="Dividend Yield alvo ou histórico (ex: 11% a.a.)")
    resumo_estrategia: str | None = Field(default=None, description="Breve resumo da estratégia do fundo")

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

    prompt = f"""Você é um analista do BTG Pactual. Extraia os dados da oferta imobiliária do texto abaixo.
    Priorize encontrar o valor do P/VP (Preço sobre Valor Patrimonial).
    Se não achar alguma informação no texto fornecido, retorne null. Não invente dados.
    
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