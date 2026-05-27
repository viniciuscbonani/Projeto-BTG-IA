#!/usr/bin/env python3
"""
Orquestrador do Pipeline de Inteligência de Mercado.

Arquitetura em 3 fases:

  FASE 1 (rápida, barata) - Matemática e cruzamento determinístico
    - Coleta de ofertas dos últimos 30 dias na CVM (cvm160)
    - Download do informe mensal (cvm_mensal) para VPA por CNPJ
    - Merge via CNPJ -> P/VP calculado matematicamente

  FASE 2 (pesada, cara, seletiva) - Inteligência qualitativa
    - Triagem: Top N P/VP + IPOs sem VPA na CVM
    - Coleta Playwright das notícias só do subconjunto triado
    - Groq/LangChain extrai segmento, estratégia e yield dos textos

  FASE 3 - Consolidação e exportação
    - Merge dos sinais quantitativos (CVM) + qualitativos (Groq)
    - Score de ranking
    - Saída para dados_finais.json (consumido pelo Streamlit)
"""

import json
import time

import pandas as pd

from src.data_ingestion.calculo_vpa_cvm import enriquecer_ofertas_com_pvp
from src.data_ingestion.coleta_noticias import coletar_noticias_em_lote
from src.data_ingestion.download_cvm_ofertas import obter_dados_cvm
from src.data_ingestion.extract_fii_dados import extract_from_text


ARQUIVO_SAIDA = "dados_finais.json"
TOP_N_TRIAGEM = 10
SLEEP_ENTRE_CHAMADAS_GROQ_S = 2  # respeita TPM do free tier do llama-3.1-8b-instant


# ─── Score ────────────────────────────────────────────────────────────────────

def calcular_score_ranking(volume, pvp_numerico):
    """Atratividade da oferta priorizando P/VP < 1."""
    volume_score = min(volume / 100_000_000, 10)

    if pvp_numerico is None:
        return round(volume_score, 2)

    desconto_pvp = max(0, 1 - pvp_numerico) * 100
    penalidade_agio = max(0, pvp_numerico - 1) * 120
    return round(70 + desconto_pvp - penalidade_agio + volume_score, 2)


def normaliza_valor(valor, vazio="Não disponível"):
    if pd.isna(valor):
        return vazio
    return valor


# ─── Fase 2.4: Triagem ────────────────────────────────────────────────────────

def triagem_para_ia(df_enriquecido: pd.DataFrame, top_n: int = TOP_N_TRIAGEM) -> pd.DataFrame:
    """Seleciona o subconjunto que merece análise pesada de IA.

    Regra de negócio: gastamos Playwright + Groq APENAS em
      (a) Top N ofertas com melhor P/VP (com VPA conhecido), e
      (b) IPOs sem VPA na CVM (onde a IA é o único caminho para qualitativos).
    """
    top_pvp = (
        df_enriquecido
        .dropna(subset=["P_VP_Calculado"])
        .nsmallest(top_n, "P_VP_Calculado")
    )
    ipos_sem_vpa = df_enriquecido[df_enriquecido["Valor_Patrimonial_Cotas"].isna()]

    return (
        pd.concat([top_pvp, ipos_sem_vpa])
        .drop_duplicates(subset="CNPJ_Emissor")
        .reset_index(drop=True)
    )


# ─── Fase 2.5 + 2.6: Coleta + Groq ────────────────────────────────────────────

def enriquecer_com_ia(df_triagem: pd.DataFrame) -> dict:
    """Para cada fundo da triagem, coleta notícia e extrai métricas via Groq.

    Retorna dict {CNPJ -> {'metricas': MetricasFII, 'url_fonte': str}}.
    Falha de coleta ou de Groq em um fundo NÃO derruba o lote.
    """
    if df_triagem.empty:
        return {}

    nomes = df_triagem["Nome_Emissor"].tolist()
    cnpjs = df_triagem["CNPJ_Emissor"].tolist()

    print(f"\n📰 Fase 2.5 - Coleta Playwright ({len(nomes)} fundos)...")
    noticias = coletar_noticias_em_lote(nomes)

    print(f"\n🤖 Fase 2.6 - Análise Groq...")
    metricas_por_cnpj = {}
    for cnpj, noticia in zip(cnpjs, noticias):
        if not noticia.sucesso:
            print(f"   ⏭️  Pulando {noticia.nome_fundo}: {noticia.erro}")
            continue
        try:
            metricas = extract_from_text(noticia.conteudo, noticia.url or "")
            metricas_por_cnpj[cnpj] = {"metricas": metricas, "url_fonte": noticia.url}
            print(f"   ✅ {noticia.nome_fundo[:50]} | seg={metricas.segmento}")
        except Exception as e:
            print(f"   ⚠️  Groq falhou em {noticia.nome_fundo}: {type(e).__name__}: {e}")
        time.sleep(SLEEP_ENTRE_CHAMADAS_GROQ_S)

    return metricas_por_cnpj


# ─── Fase 3: Consolidação ─────────────────────────────────────────────────────

def consolidar_linha(linha: pd.Series, ia: dict | None) -> dict:
    """Monta o dict de saída para uma oferta: números da CVM + qualitativos da IA."""
    try:
        volume = float(linha.get("Valor_Total_Registrado", 0) or 0)
    except Exception:
        volume = 0.0

    pvp_num = linha.get("P_VP_Calculado") if "P_VP_Calculado" in linha.index else None
    if pd.isnull(pvp_num):
        pvp_num = None

    if ia is not None:
        m = ia["metricas"]
        segmento = m.segmento or "Não identificado"
        estrategia = m.resumo_estrategia or "Não disponível"
        yield_alvo = m.dividend_yield_alvo or "Não disponível"
        url_fonte = ia["url_fonte"] or "Não disponível"
    else:
        segmento = "Fora da triagem"
        estrategia = "Fora da triagem"
        yield_alvo = "Fora da triagem"
        url_fonte = "Fora da triagem"

    return {
        "fundo": linha.get("Nome_Emissor"),
        "coordenador": linha.get("Nome_Lider"),
        "volume": volume,
        "pvp": round(pvp_num, 4) if pvp_num is not None else "IPO / Sem VPA Histórico",
        "pvp_numerico": pvp_num,
        "preco_emissao": normaliza_valor(linha.get("Preco_Emissao", None), None),
        "valor_patrimonial_cota": normaliza_valor(linha.get("Valor_Patrimonial_Cotas", None), None),
        "segmento": segmento,
        "yield_alvo": yield_alvo,
        "estrategia": estrategia,
        "url_fonte": url_fonte,
        "score_ranking": calcular_score_ranking(volume, pvp_num),
    }


# ─── Pipeline principal ───────────────────────────────────────────────────────

def rodar_pipeline_btg():
    print("🚀 Iniciando Pipeline de Inteligência de Mercado (BTG Pactual)...\n")

    # FASE 1 — Matemática
    print("─── FASE 1: Matemática (CVM) ─────────────────────────────────")
    df_ofertas = obter_dados_cvm()
    if df_ofertas is None or df_ofertas.empty:
        print("Nenhuma oferta recente encontrada.")
        return

    df_enriquecido = enriquecer_ofertas_com_pvp(df_ofertas)
    com_pvp = df_enriquecido["P_VP_Calculado"].notna().sum()
    print(f"✅ F1 concluída: {len(df_enriquecido)} ofertas, {com_pvp} com P/VP calculado.\n")

    # FASE 2 — Inteligência seletiva
    print("─── FASE 2: Inteligência (Playwright + Groq) ────────────────")
    df_triagem = triagem_para_ia(df_enriquecido)
    print(f"🎯 Triagem: {len(df_triagem)} fundos selecionados (top P/VP + IPOs sem VPA).")

    metricas_por_cnpj = enriquecer_com_ia(df_triagem)
    print(f"\n✅ F2 concluída: {len(metricas_por_cnpj)}/{len(df_triagem)} fundos enriquecidos pela IA.\n")

    # FASE 3 — Consolidação
    print("─── FASE 3: Consolidação e exportação ───────────────────────")
    ranking_lista = [
        consolidar_linha(linha, metricas_por_cnpj.get(linha.get("CNPJ_Emissor")))
        for _, linha in df_enriquecido.iterrows()
    ]

    # Ordenação: menor P/VP no topo, Nones no fim
    ranking_final = sorted(
        ranking_lista,
        key=lambda x: (
            x["pvp_numerico"] is None,
            x["pvp_numerico"] if x["pvp_numerico"] is not None else 999,
        ),
    )

    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(ranking_final, f, indent=2, ensure_ascii=False, allow_nan=False)

    print(f"\n✅ Pipeline concluído! {len(ranking_final)} ativos salvos em {ARQUIVO_SAIDA}.")


if __name__ == "__main__":
    rodar_pipeline_btg()
