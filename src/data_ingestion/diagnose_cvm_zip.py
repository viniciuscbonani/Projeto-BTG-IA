"""Script diagnóstico: baixa o ZIP anual da CVM e lista arquivos CSV e seus cabeçalhos.
Usar para identificar nomes reais de colunas e adaptar a lógica de extração.
"""
import requests
import zipfile
from io import BytesIO
import pandas as pd

URL = f"https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_{__import__('datetime').datetime.today().year}.zip"

print('📥 Baixando:', URL)
resp = requests.get(URL, timeout=60)
resp.raise_for_status()

zf = zipfile.ZipFile(BytesIO(resp.content))
print('\nArquivos no ZIP:')
for name in zf.namelist():
    print('-', name)

print('\n=== Cabeçalhos dos CSVs (primeiras 5 colunas) ===')
for name in zf.namelist():
    if not name.lower().endswith('.csv'):
        continue
    try:
        raw = zf.read(name)
        # lê só o header
        df_head = pd.read_csv(BytesIO(raw), sep=';', encoding='latin-1', nrows=0, engine='python', on_bad_lines='skip')
        cols = df_head.columns.tolist()
        print(f'\n{name}:')
        for c in cols[:10]:
            print('  -', c)
    except Exception as e:
        print(f'\n{name}: erro ao ler cabeçalho ->', e)

print('\nDiagnóstico concluído.')
