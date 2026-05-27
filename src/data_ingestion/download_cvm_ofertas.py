#!/usr/bin/env python3
"""
Download e filtro dos dados de Ofertas Públicas de Distribuição da CVM.
Baseado na estrutura da Liga AI, adaptado para o pipeline do BTG Pactual.
"""

import os
import zipfile
import io
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# ─── Configuração ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CVM_BASE_URL = "https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS"
ZIP_URL = f"{CVM_BASE_URL}/oferta_distribuicao.zip"
DATA_DIR = PROJECT_ROOT / "data" / "cvm"

# ─── Download e Extração ──────────────────────────────────────────────────────

def download_zip(url: str) -> zipfile.ZipFile:
    """Baixa o ZIP da CVM e retorna o objeto ZipFile."""
    print(f"📥 Baixando dados da CVM...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(resp.content))

def extract_csv(zf: zipfile.ZipFile, csv_name: str) -> pd.DataFrame:
    """Extrai um CSV específico do ZIP e retorna como DataFrame."""
    print(f"📄 Extraindo: {csv_name}")
    with zf.open(csv_name) as f:
        # A CVM usa ponto e vírgula e encoding latin-1
        df = pd.read_csv(
            f, sep=";", encoding="latin-1",
            engine="python", on_bad_lines="skip",
        )
    return df

# ─── Regras de Negócio (Filtro BTG) ───────────────────────────────────────────

def filtrar_ofertas_fii_recentes(df: pd.DataFrame, dias: int = 7) -> pd.DataFrame:
    """Aplica as regras de negócio para encontrar oportunidades de FIIs."""
    print("🔍 Aplicando filtros de negócio (FIIs de concorrentes)...")
    
    # 1. Apenas FIIs
    df_fiis = df[df["Valor_Mobiliario"].str.contains("FII|Fundo de Investimento Imobiliário", na=False, case=False)].copy()
    
    # 2. Remover BTG (Líder ou Emissor) e Securitizadoras (CRIs)
    df_fiis = df_fiis[~df_fiis["Nome_Lider"].str.contains("BTG Pactual|BTG", na=False, case=False)]
    df_fiis = df_fiis[~df_fiis["Nome_Emissor"].str.contains("SECURITIZADORA|CRI|BTG", na=False, case=False)]
    
    # 3. Filtro de tempo (Últimos X dias)
    df_fiis["Data_Registro_Clean"] = pd.to_datetime(df_fiis["Data_Registro"], errors="coerce")
    data_limite = datetime.now() - timedelta(days=dias)
    df_recentes = df_fiis[df_fiis["Data_Registro_Clean"] >= data_limite].copy()
    
    # 4. Ordenar por volume (do maior para o menor)
    df_recentes["Valor_Total_Registrado"] = pd.to_numeric(df_recentes["Valor_Total_Registrado"], errors="coerce")
    df_recentes = df_recentes.sort_values(by="Valor_Total_Registrado", ascending=False)
    
    print(f"🎯 Encontradas {len(df_recentes)} ofertas relevantes nos últimos {dias} dias.")
    return df_recentes

# ─── Função de Interface (Para uso em outros arquivos) ────────────────────────

def obter_dados_cvm() -> pd.DataFrame:
    """Função principal para ser importada pelo pipeline."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    zf = download_zip(ZIP_URL)
    
    # Focamos no rito automático (Resolução 160) que contém as ofertas atuais
    df_160 = extract_csv(zf, "oferta_resolucao_160.csv")
    
    # Salva backup localmente (padrão do repo)
    csv_path = DATA_DIR / "oferta_resolucao_160.csv"
    df_160.to_csv(csv_path, index=False, sep=";", encoding="utf-8")
    
    df_filtrado = filtrar_ofertas_fii_recentes(df_160, dias=30)
    return df_filtrado

# ─── Main (Para testes isolados) ──────────────────────────────────────────────
if __name__ == "__main__":
    df = obter_dados_cvm()
    if not df.empty:
        print("\nTop 3 Ofertas Encontradas:")
        colunas_exibicao = ['Nome_Emissor', 'Nome_Lider', 'Valor_Total_Registrado']
        print(df[colunas_exibicao].head(3))