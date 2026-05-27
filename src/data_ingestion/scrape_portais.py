#!/usr/bin/env python3
"""
Web Scraping com Playwright focado em Jornalismo Financeiro e Fatos Relevantes.
Esta abordagem garante o timing D+0 para o pipeline, extraindo dados
antes mesmo de os agregadores atualizarem seus painéis.
"""

import urllib.parse
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

def limpar_nome_fundo(nome: str) -> str:
    """Remove termos genéricos da CVM para focar no nome real do ativo."""
    termos_remover = [
        "FUNDO DE INVESTIMENTO IMOBILIÁRIO",
        "FUNDO DE INVESTIMENTO IMOBILIARIO",
        "RESPONSABILIDADE LIMITADA",
        "FII",
        "S.A.",
        "SA",
        "-"
    ]
    nome_limpo = nome.upper()
    for termo in termos_remover:
        nome_limpo = nome_limpo.replace(termo, " ")
    
    # Remove espaços em branco duplicados gerados pelos replaces
    nome_limpo = " ".join(nome_limpo.split())
    
    # Se sobrar algo útil, usa. Senão, faz o fallback para as 3 primeiras palavras
    return nome_limpo if len(nome_limpo) > 2 else " ".join(nome.split()[:3])


def buscar_link_portal_playwright(nome_fundo: str) -> str:
    """Abre o Firefox invisível para buscar notícias quentes sobre a emissão do FII."""
    
    nome_reduzido = limpar_nome_fundo(nome_fundo)
    
    # MUDANÇA ESTRATÉGICA: Foco em notícias para não perder o timing da nova oferta
    query = f"{nome_reduzido} nova oferta emissão (site:infomoney.com.br OR site:suno.com.br OR site:clubefii.com.br/noticias OR site:fii.com.br)"
    
    url_busca = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"

    print(f"🌐 [Playwright] Buscando notícias/fatos relevantes para: {nome_reduzido}")

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()

            page.goto(url_busca, timeout=30000)
            page.wait_for_timeout(1500) # Pausa para evitar bloqueios simples

            resultados = page.locator(".result__a")

            # Itera sobre os resultados da página para garantir que não vai pegar um anúncio
            for i in range(resultados.count()):
                link_sujo = resultados.nth(i).get_attribute("href")
                
                # Pula anúncios e links patrocinados
                if not link_sujo or "y.js" in link_sujo or "ad_domain" in link_sujo:
                    continue

                browser.close()

                # Limpa o redirect do DuckDuckGo para extrair a URL limpa do InfoMoney/Suno
                if "uddg=" in link_sujo:
                    parsed = urlparse(link_sujo)
                    link_real = parse_qs(parsed.query).get('uddg', [link_sujo])[0]
                    return link_real
                
                return link_sujo

            browser.close()
            return None
            
    except Exception as e:
        print(f"❌ Erro no Playwright ao buscar {nome_reduzido}: {e}")
        return None

# ─── Main (Para testes isolados do módulo) ────────────────────────────────────
if __name__ == "__main__":
    print("Iniciando teste dinâmico de scraping...")
    
    # Importa o módulo da CVM para pegar um alvo real e atualizado
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
    from src.data_ingestion.download_cvm_ofertas import obter_dados_cvm
    
    df_ofertas = obter_dados_cvm()
    
    if df_ofertas is not None and not df_ofertas.empty:
        # Pega o fundo mais relevante (primeira linha) do dia de hoje
        fundo_do_dia = df_ofertas.iloc[0]["Nome_Emissor"]
        print(f"🎯 Alvo dinâmico selecionado: {fundo_do_dia}")
        
        url_encontrada = buscar_link_portal_playwright(fundo_do_dia)
        
        print("\n" + "="*50)
        print(f"✅ LINK DE NOTÍCIA ENCONTRADO: {url_encontrada}")
        print("="*50)
    else:
        print("⚠️ A CVM não tem ofertas novas nos últimos 7 dias. Teste abortado.")