import pandas as pd
import requests
from io import BytesIO
import zipfile
from datetime import datetime
import unicodedata


def _normalize(col: str) -> str:
    s = col.lower()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    s = s.replace(' ', '_').replace('-', '_')
    return s


def obter_informe_mensal_cvm():
    """Baixa o ZIP anual dos Informes Mensais de FIIs e retorna um DataFrame com
    as colunas `CNPJ_Fundo` e `Valor_Patrimonial_Cotas` quando encontradas.
    O código tenta ser tolerante a variações de nomes de colunas.
    """
    ano_atual = datetime.today().year
    url = f"https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{ano_atual}.zip"
    print(f"📥 Baixando base anual da CVM ({ano_atual}). Isso pode levar alguns segundos...")

    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Erro ao baixar ZIP da CVM: {e}")
        return None

    try:
        zf = zipfile.ZipFile(BytesIO(resp.content))
    except Exception as e:
        print(f"❌ Erro ao ler o ZIP da CVM: {e}")
        return None

    dfs_meses = []

    for nome_arquivo in zf.namelist():
        if not nome_arquivo.lower().endswith('.csv'):
            continue

        try:
            conteudo = zf.read(nome_arquivo)
        except Exception:
            continue

        # Tenta ler apenas o cabeçalho para economizar memória
        try:
            df_head = pd.read_csv(BytesIO(conteudo), sep=';', encoding='latin-1', nrows=0, engine='python', on_bad_lines='skip')
        except Exception:
            continue

        colunas_originais = df_head.columns.tolist()
        colunas_norm = {c: _normalize(c) for c in colunas_originais}
        col_norm_upper = [c.upper() for c in colunas_norm.values()]

        # Detecta presença de VPA em alguma coluna
        has_vpa = any('valor_patrimonial' in cn for cn in colunas_norm.values()) or any('vpa' == cn for cn in colunas_norm.values())
        if not has_vpa:
            continue

        # Lê o CSV completo de forma resiliente
        try:
            df = pd.read_csv(BytesIO(conteudo), sep=';', encoding='latin-1', engine='python', on_bad_lines='skip')
        except Exception:
            continue

        # Normaliza e renomeia colunas
        rename_map = {c: _normalize(c) for c in df.columns}
        df.rename(columns=rename_map, inplace=True)

        # Possíveis nomes para buscar
        possible_cnpj = ['cnpj_fundo_classe', 'cnpj_fundo', 'cnpj', 'cnpj_fi']
        possible_vpa = ['valor_patrimonial_cotas', 'valor_patrimonial_cota', 'vpa', 'valor_patrimonial']
        possible_patrimonio = ['patrimonio_liquido', 'patrimonio_liquido_total', 'patrimonio_total']
        possible_cotas = ['cotas_emitidas', 'quantidade_cotas_emitidas', 'cotas_emitidas_total']
        possible_data = ['data_referencia', 'data', 'dt_comptc', 'data_refer']

        found_cnpj = next((c for c in possible_cnpj if c in df.columns), None)
        found_vpa = next((c for c in possible_vpa if c in df.columns), None)
        found_patrimonio = next((c for c in possible_patrimonio if c in df.columns), None)
        found_cotas = next((c for c in possible_cotas if c in df.columns), None)
        found_data = next((c for c in possible_data if c in df.columns), None)

        if not found_vpa and found_patrimonio and found_cotas:
            # fallback calculado a partir de patrimônio líquido e cotas emitidas
            try:
                df['valor_patrimonial_cotas'] = pd.to_numeric(df[found_patrimonio], errors='coerce') / pd.to_numeric(df[found_cotas], errors='coerce')
                found_vpa = 'valor_patrimonial_cotas'
                print(f"ℹ️ Fallback VPA calculado em {nome_arquivo} usando {found_patrimonio} / {found_cotas}.")
            except Exception:
                found_vpa = None

        if not found_vpa or not found_cnpj:
            # Log para diagnóstico
            continue

        # Seleciona colunas essenciais
        cols = [found_cnpj, found_vpa]
        if found_cotas and found_cotas not in cols:
            cols.append(found_cotas)
        if found_data:
            cols.append(found_data)

        df_limpo = df[cols].dropna(subset=[found_cnpj, found_vpa], how='any').copy()

        # Renomeia para padrão esperado
        rename_to_standard = {found_cnpj: 'CNPJ_Fundo', found_vpa: 'Valor_Patrimonial_Cotas'}
        if found_cotas and found_cotas not in rename_to_standard:
            rename_to_standard[found_cotas] = 'Cotas_Emitidas'
        if found_data:
            rename_to_standard[found_data] = 'Data_Referencia'
        df_limpo.rename(columns=rename_to_standard, inplace=True)

        # Ajusta escala de VPA quando a quantidade de cotas está em milhares
        if 'Cotas_Emitidas' in df_limpo.columns:
            df_limpo['Cotas_Emitidas'] = pd.to_numeric(df_limpo['Cotas_Emitidas'], errors='coerce')
            too_large_vpa = df_limpo['Valor_Patrimonial_Cotas'].abs() > 1000
            small_cotas = df_limpo['Cotas_Emitidas'].abs() < 1000
            ajustar = too_large_vpa & small_cotas
            if ajustar.any():
                df_limpo.loc[ajustar, 'Valor_Patrimonial_Cotas'] = (
                    df_limpo.loc[ajustar, 'Valor_Patrimonial_Cotas'] / 1000
                )

        dfs_meses.append(df_limpo)

    if not dfs_meses:
        print('⚠️ Coluna de VPA não encontrada em nenhum arquivo dentro do ZIP da CVM.')
        return None

    # Consolida e fica com a última referência por CNPJ
    df_concat = pd.concat(dfs_meses, ignore_index=True)
    if 'Data_Referencia' in df_concat.columns:
        # Tenta parsear datas e ordenar
        try:
            df_concat['Data_Referencia'] = pd.to_datetime(df_concat['Data_Referencia'], errors='coerce')
            df_concat = df_concat.sort_values('Data_Referencia')
        except Exception:
            pass

    df_vpa = df_concat.drop_duplicates(subset=['CNPJ_Fundo'], keep='last')
    # Mantém apenas as colunas úteis
    df_vpa = df_vpa[['CNPJ_Fundo', 'Valor_Patrimonial_Cotas']].copy()

    # Garante tipos numéricos para VPA
    df_vpa['Valor_Patrimonial_Cotas'] = pd.to_numeric(df_vpa['Valor_Patrimonial_Cotas'], errors='coerce')

    print('✅ Informe mensal processado: fundos encontrados =', len(df_vpa))
    return df_vpa


def enriquecer_ofertas_com_pvp(df_ofertas):
    """Enriquece `df_ofertas` com Preco_Emissao, Valor_Patrimonial_Cotas e P_VP_Calculado."""
    df_vpa = obter_informe_mensal_cvm()

    # TRAVA DE SEGURANÇA: Se a CVM cair, cria as colunas vazias para o código não explodir
    if df_vpa is None or df_vpa.empty:
        df_ofertas = df_ofertas.copy()
        df_ofertas['Preco_Emissao'] = None
        df_ofertas['Valor_Patrimonial_Cotas'] = None
        df_ofertas['P_VP_Calculado'] = None
        return df_ofertas

    # Calcula o Preço de Emissão
    def calc_preco(row):
        try:
            qt = row.get('Qtde_Total_Registrada')
            val = row.get('Valor_Total_Registrado')
            if pd.notnull(qt) and qt > 0:
                return float(val) / float(qt)
        except Exception:
            return None
        return None

    df_ofertas = df_ofertas.copy()
    df_ofertas['Preco_Emissao'] = df_ofertas.apply(calc_preco, axis=1)

    # Normaliza CNPJs
    df_ofertas['CNPJ_Emissor'] = df_ofertas.get('CNPJ_Emissor', '').astype(str).str.replace('[^0-9]', '', regex=True).str.strip()
    df_vpa['CNPJ_Fundo'] = df_vpa['CNPJ_Fundo'].astype(str).str.replace('[^0-9]', '', regex=True).str.strip()

    # Merge
    df_enriquecido = pd.merge(
        df_ofertas,
        df_vpa,
        left_on='CNPJ_Emissor',
        right_on='CNPJ_Fundo',
        how='left'
    )

    # Calcula P/VP
    def calc_pvp(row):
        try:
            pe = row.get('Preco_Emissao')
            vpa = row.get('Valor_Patrimonial_Cotas')
            if pd.notnull(pe) and pd.notnull(vpa) and vpa > 0:
                return float(pe) / float(vpa)
        except Exception:
            return None
        return None

    df_enriquecido['P_VP_Calculado'] = df_enriquecido.apply(calc_pvp, axis=1)

    return df_enriquecido


# ─── Main (Para testes isolados no terminal) ────────────────────────────────────
if __name__ == "__main__":
    # Teste rápido
    df_teste = pd.DataFrame({
        'CNPJ_Emissor': ['01.201.140/0001-90'],
        'Valor_Total_Registrado': [100000000.0],
        'Qtde_Total_Registrada': [1000000.0]
    })

    resultado = enriquecer_ofertas_com_pvp(df_teste)
    print('\n' + '=' * 50)
    print(resultado[['CNPJ_Emissor', 'Preco_Emissao', 'Valor_Patrimonial_Cotas', 'P_VP_Calculado']])
    print('=' * 50)