import streamlit as st
import pandas as pd
import json
import os

st.set_page_config(page_title="BTG Pactual - Ranking de Ofertas", layout="wide")

st.title("🏆 Ranking Inteligente de Ofertas Primárias (Concorrentes)")
st.markdown("Este painel classifica as ofertas de FIIs de concorrentes capturadas nos últimos 7 dias, priorizando P/VP abaixo de 1.")

# Verifica se o arquivo de ranking gerado pela IA existe
if not os.path.exists("dados_finais.json"):
    st.warning("O arquivo de dados 'dados_finais.json' não foi encontrado.")
    st.info("Por favor, execute o script 'python3 gerar_ranking.py' no terminal primeiro para construir a base de dados do ranking.")
else:
    # Carrega os dados processados em lote pelo backend
    with open("dados_finais.json", "r", encoding="utf-8") as f:
        dados_ranking = json.load(f)
        
    # Converte para DataFrame para manipulação visual
    df = pd.DataFrame(dados_ranking)

    if df.empty:
        st.warning("O arquivo de ranking existe, mas ainda não possui ofertas salvas com sucesso.")
        st.stop()
    
    # Exibe os top 3 fundos em destaque usando Cards do Streamlit
    st.subheader("🔥 Top Oportunidades de Mercado Monitoradas")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if len(df) > 0:
            st.metric(label="1º Lugar - P/VP", value=df.iloc[0].get('pvp', 'Não encontrado'))
            st.markdown(f"**{df.iloc[0]['fundo']}**\n\nVol: R$ {df.iloc[0]['volume']:,.2f}\n\nLíder: {df.iloc[0]['coordenador']}")
            
    with col2:
        if len(df) > 1:
            st.metric(label="2º Lugar - P/VP", value=df.iloc[1].get('pvp', 'Não encontrado'))
            st.markdown(f"**{df.iloc[1]['fundo']}**\n\nVol: R$ {df.iloc[1]['volume']:,.2f}\n\nLíder: {df.iloc[1]['coordenador']}")
            
    with col3:
        if len(df) > 2:
            st.metric(label="3º Lugar - P/VP", value=df.iloc[2].get('pvp', 'Não encontrado'))
            st.markdown(f"**{df.iloc[2]['fundo']}**\n\nVol: R$ {df.iloc[2]['volume']:,.2f}\n\nLíder: {df.iloc[2]['coordenador']}")

    st.divider()
    
    # Exibe a tabela do ranking completo ordenada pelo Score da IA
    st.subheader("📊 Classificação Completa")
    
    colunas = ['score_ranking', 'pvp', 'preco_emissao', 'valor_patrimonial_cota', 'fundo', 'segmento', 'coordenador', 'volume', 'yield_alvo']
    nomes_colunas = {
        'score_ranking': 'Score',
        'pvp': 'P/VP',
        'preco_emissao': 'Preço de Emissão',
        'valor_patrimonial_cota': 'VP/Cota',
        'fundo': 'Fundo Imobiliário',
        'segmento': 'Segmento',
        'coordenador': 'Coordenador Líder',
        'volume': 'Volume (R$)',
        'yield_alvo': 'Yield Alvo',
    }
    colunas_existentes = [coluna for coluna in colunas if coluna in df.columns]
    df_tabela = df[colunas_existentes].rename(columns=nomes_colunas)
    
    st.dataframe(df_tabela, use_container_width=True, hide_index=True)
    
    st.divider()
    
    # Seção para detalhar a estratégia de investimento de cada fundo
    st.subheader("💡 Detalhes e Estratégia de Investimento")
    fundo_escolhido = st.selectbox("Selecione um fundo para ler a análise completa:", df['fundo'].tolist())
    
    detalhes = df[df['fundo'] == fundo_escolhido].iloc[0]
    
    st.markdown(f"**P/VP:** {detalhes.get('pvp', 'Não encontrado')}")
    st.markdown(f"**Preço de Emissão:** {detalhes.get('preco_emissao', 'Não encontrado')}")
    st.markdown(f"**VP/Cota:** {detalhes.get('valor_patrimonial_cota', 'Não encontrado')}")
    st.markdown(f"**Segmento:** {detalhes.get('segmento', 'Não encontrado')}")
    st.markdown(f"**Yield Alvo:** {detalhes.get('yield_alvo', 'Não encontrado')}")
    st.markdown(f"**Resumo da Estratégia Extraído pela IA:** {detalhes.get('estrategia', 'Sem informações suficientes.')}")
    url_fonte = detalhes.get('url_fonte', 'Não disponível')
    if url_fonte and url_fonte not in ('Não disponível', 'Fora da triagem'):
        st.markdown(f"**Fonte de Análise:** [Abrir Link Original Monitorado]({url_fonte})")
    else:
        st.markdown(f"**Fonte de Análise:** {url_fonte}")