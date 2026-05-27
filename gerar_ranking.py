#!/usr/bin/env python3
import os
import json
import time
import pandas as pd

# Importamos nossos módulos baseados na arquitetura da Liga AI
from src.data_ingestion.download_cvm_ofertas import obter_dados_cvm
from src.data_ingestion.calculo_vpa_cvm import enriquecer_ofertas_com_pvp

def calcular_score_ranking(volume, pvp_numerico):
    """Calcula a atratividade da oferta priorizando P/VP menor que 1."""
    volume_score = min(volume / 100000000, 10) 
    
    if pvp_numerico is None:
        return round(volume_score, 2)
        
    desconto_pvp = max(0, 1 - pvp_numerico) * 100
    penalidade_agio = max(0, pvp_numerico - 1) * 120
    score = 70 + desconto_pvp - penalidade_agio + volume_score

    return round(score, 2)


def normaliza_valor(valor, vazio="Não disponível"):
    if pd.isna(valor):
        return vazio
    return valor


def rodar_pipeline_btg():
    print("🚀 Iniciando Pipeline de Inteligência de Mercado (BTG Pactual)...\n")
    
    # 1. Ingestão (CVM)
    df_ofertas = obter_dados_cvm()
    if df_ofertas is None or df_ofertas.empty:
        print("Nenhuma oferta recente encontrada.")
        return
    # 2. Enriquecimento determinístico via CVM (P/VP calculado diretamente na fonte)
    df_enriquecido = enriquecer_ofertas_com_pvp(df_ofertas)

    ranking_lista = []
    # Avalia todas as ofertas filtradas pela CVM
    df_alvos = df_enriquecido

    for idx, linha in df_alvos.iterrows():
        nome = linha.get("Nome_Emissor")
        lider = linha.get("Nome_Lider")
        try:
            volume = float(linha.get("Valor_Total_Registrado", 0) or 0)
        except Exception:
            volume = 0.0

        pvp_num = linha.get('P_VP_Calculado') if 'P_VP_Calculado' in linha.index else None
        if pd.isnull(pvp_num):
            pvp_num = None

        score = calcular_score_ranking(volume, pvp_num)

        ranking_lista.append({
            "fundo": nome,
            "coordenador": lider,
            "volume": volume,
            "pvp": round(pvp_num, 4) if pvp_num is not None else "IPO / Sem VPA Histórico",
            "pvp_numerico": pvp_num,
            "preco_emissao": normaliza_valor(linha.get('Preco_Emissao', None), None),
            "valor_patrimonial_cota": normaliza_valor(linha.get('Valor_Patrimonial_Cotas', None), None),
            "yield_alvo": "Não disponível",
            "estrategia": "Não disponível",
            "url_prospecto": "Não disponível",
            "score_ranking": score,
        })

    # Ordenação (Menor P/VP no topo)
    ranking_final = sorted(
        ranking_lista,
        key=lambda x: (
            x["pvp_numerico"] is None,
            x["pvp_numerico"] if x["pvp_numerico"] is not None else 999
        ),
    )

    with open("ranking_ofertas.json", "w", encoding="utf-8") as f:
        json.dump(ranking_final, f, indent=2, ensure_ascii=False, allow_nan=False)

    print(f"\n✅ Pipeline concluído! {len(ranking_final)} ativos salvos em ranking_ofertas.json.")

if __name__ == "__main__":
    rodar_pipeline_btg()