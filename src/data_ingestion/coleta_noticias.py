#!/usr/bin/env python3
"""
Estação de Inteligência Qualitativa - Coleta de notícias via Playwright.

Pipeline síncrono que, dado o nome de um fundo:
  1. Pesquisa no DuckDuckGo restrito a portais de jornalismo financeiro
  2. Abre o primeiro resultado orgânico no Firefox headless
  3. Extrai o texto limpo do corpo da notícia (sem nav/footer/ads)

A saída é um `NoticiaFII` com o texto pronto para ser injetado no
Groq/LangChain em um passo separado (análise de sentimento + estratégia).

Por que síncrono: o pipeline a jusante é Pandas (iterrows), também síncrono.
Async traria overhead de `asyncio.run()` por linha sem ganho real. Para
paralelismo futuro, envolver a API síncrona em `ThreadPoolExecutor`.
"""

import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)
from pydantic import BaseModel, Field

from src.data_ingestion.scrape_portais import limpar_nome_fundo


# ─── Contrato de saída ────────────────────────────────────────────────────────

class NoticiaFII(BaseModel):
    """Resultado da coleta de uma notícia financeira sobre um fundo."""
    nome_fundo: str
    url: str | None = None
    fonte: str | None = Field(default=None, description="Domínio da notícia (ex: infomoney.com.br)")
    titulo: str | None = None
    conteudo: str = Field(default="", description="Texto limpo do corpo, pronto para LLM")
    sucesso: bool = False
    erro: str | None = None


# ─── Configuração ─────────────────────────────────────────────────────────────

PORTAIS_PRIORITARIOS = [
    "infomoney.com.br",
    "suno.com.br",
    "clubefii.com.br/noticias",
    "fii.com.br",
]

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) "
    "Gecko/20100101 Firefox/120.0"
)

TIMEOUT_NAVEGACAO_MS = 30_000
TIMEOUT_BUSCA_MS = 30_000
BUFFER_ANTIBOT_MS = 1_500
BUFFER_LAZY_LOAD_MS = 800
TAMANHO_MAX_TEXTO = 10_000
TAMANHO_MIN_ARTIGO = 300
TAMANHO_MIN_VALIDO = 200

SELETORES_ARTIGO = [
    "article",
    "main article",
    ".article-content",
    ".post-content",
    ".entry-content",
    "main",
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _montar_query(nome_fundo: str) -> str:
    nome_reduzido = limpar_nome_fundo(nome_fundo)
    sites = " OR ".join(f"site:{p}" for p in PORTAIS_PRIORITARIOS)
    return f"{nome_reduzido} nova oferta emissão ({sites})"


def _url_busca_ddg(query: str) -> str:
    return f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"


def _limpar_url_ddg(link: str) -> str:
    """Desfaz o redirect do DuckDuckGo, devolvendo a URL canônica."""
    if "uddg=" not in link:
        return link
    parsed = urlparse(link)
    return parse_qs(parsed.query).get("uddg", [link])[0]


def _extrair_fonte(url: str) -> str | None:
    try:
        return urlparse(url).netloc.replace("www.", "") or None
    except Exception:
        return None


EXTENSOES_BINARIAS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip")


def _buscar_url_noticia(page: Page, nome_fundo: str) -> str | None:
    """Faz a busca no DuckDuckGo e devolve o primeiro link orgânico (não-anúncio, não-binário)."""
    page.goto(_url_busca_ddg(_montar_query(nome_fundo)), timeout=TIMEOUT_BUSCA_MS)
    page.wait_for_timeout(BUFFER_ANTIBOT_MS)

    resultados = page.locator(".result__a")
    for i in range(resultados.count()):
        link_sujo = resultados.nth(i).get_attribute("href")
        if not link_sujo or "y.js" in link_sujo or "ad_domain" in link_sujo:
            continue
        url_real = _limpar_url_ddg(link_sujo)
        # PDFs e outros binários disparam Download em vez de render — pula
        if url_real.lower().split("?")[0].endswith(EXTENSOES_BINARIAS):
            continue
        return url_real
    return None


def _extrair_texto_pagina(page: Page) -> tuple[str, str | None]:
    """Retorna (texto, titulo). Tenta containers de artigo antes do body inteiro."""
    titulo: str | None = None
    try:
        titulo = page.title()
    except Exception:
        pass

    for seletor in SELETORES_ARTIGO:
        loc = page.locator(seletor).first
        if loc.count() == 0:
            continue
        try:
            texto = loc.inner_text(timeout=5_000).strip()
            if len(texto) >= TAMANHO_MIN_ARTIGO:
                return texto[:TAMANHO_MAX_TEXTO], titulo
        except PlaywrightTimeout:
            continue

    # Fallback: body inteiro (vem com lixo, mas é melhor que vazio)
    texto = page.locator("body").inner_text(timeout=10_000).strip()
    return texto[:TAMANHO_MAX_TEXTO], titulo


# ─── Sessão Playwright reutilizável ───────────────────────────────────────────

@contextmanager
def _abrir_sessao() -> Iterator[BrowserContext]:
    """Abre Firefox headless com perfil pt-BR realista. Use como context manager."""
    with sync_playwright() as p:
        browser: Browser = p.firefox.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )
        try:
            yield context
        finally:
            context.close()
            browser.close()


def _coletar_em_contexto(context: BrowserContext, nome_fundo: str) -> NoticiaFII:
    """Faz uma coleta dentro de um contexto Playwright já aberto."""
    resultado = NoticiaFII(nome_fundo=nome_fundo)
    page = context.new_page()
    try:
        url = _buscar_url_noticia(page, nome_fundo)
        if not url:
            resultado.erro = "Nenhum link de notícia encontrado nos portais monitorados."
            return resultado

        resultado.url = url
        resultado.fonte = _extrair_fonte(url)

        page.goto(url, timeout=TIMEOUT_NAVEGACAO_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(BUFFER_LAZY_LOAD_MS)

        texto, titulo = _extrair_texto_pagina(page)
        resultado.titulo = titulo
        resultado.conteudo = texto

        if len(texto) < TAMANHO_MIN_VALIDO:
            resultado.erro = f"Conteúdo muito curto ({len(texto)} chars) — possível paywall/bloqueio."
            return resultado

        resultado.sucesso = True
        return resultado

    except PlaywrightTimeout as e:
        resultado.erro = f"Timeout Playwright: {e}"
        return resultado
    except Exception as e:
        resultado.erro = f"{type(e).__name__}: {e}"
        return resultado
    finally:
        try:
            page.close()
        except Exception:
            pass


# ─── API pública ──────────────────────────────────────────────────────────────

def coletar_noticia(nome_fundo: str) -> NoticiaFII:
    """Coleta UMA notícia. Abre e fecha o browser internamente.

    Use para casos esporádicos. Em pipelines com N fundos, prefira
    `coletar_noticias_em_lote` — reaproveita o mesmo browser e corta
    o overhead de startup (~2-3s por chamada).
    """
    with _abrir_sessao() as context:
        return _coletar_em_contexto(context, nome_fundo)


def coletar_noticias_em_lote(nomes_fundos: Iterable[str]) -> list[NoticiaFII]:
    """Coleta notícias para vários fundos reutilizando o mesmo browser."""
    resultados: list[NoticiaFII] = []
    with _abrir_sessao() as context:
        for nome in nomes_fundos:
            print(f"📰 Coletando: {limpar_nome_fundo(nome)}")
            r = _coletar_em_contexto(context, nome)
            status = "✅" if r.sucesso else "⚠️"
            print(f"   {status} {r.fonte or 'sem fonte'} | {len(r.conteudo)} chars | {r.erro or 'ok'}")
            resultados.append(r)
    return resultados


# ─── Main (teste isolado) ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
    from src.data_ingestion.download_cvm_ofertas import obter_dados_cvm

    df = obter_dados_cvm()
    if df is None or df.empty:
        print("⚠️ Nenhuma oferta recente na CVM. Teste abortado.")
        sys.exit(0)

    alvos = df["Nome_Emissor"].head(2).tolist()
    print(f"\n🎯 Alvos do teste ({len(alvos)} fundos): {alvos}\n")

    resultados = coletar_noticias_em_lote(alvos)

    print("\n" + "=" * 60)
    print("📊 RESUMO DA COLETA")
    print("=" * 60)
    for r in resultados:
        print(f"\n📌 {r.nome_fundo}")
        print(f"   Fonte:   {r.fonte}")
        print(f"   URL:     {r.url}")
        print(f"   Título:  {r.titulo}")
        print(f"   Sucesso: {r.sucesso}")
        if r.erro:
            print(f"   Erro:    {r.erro}")
        else:
            preview = r.conteudo[:300].replace("\n", " ")
            print(f"   Preview: {preview}...")
