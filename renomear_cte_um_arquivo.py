import os
import re
import fitz  # PyMuPDF
import shutil

# Caminhos
PASTA_ENTRADAS = r'C:\Users\vlula\ScannerOCR\entradas'
PASTA_SAIDA = r'C:\Users\vlula\ScannerOCR\renomeados'

# Garante que a pasta de saída existe
os.makedirs(PASTA_SAIDA, exist_ok=True)

# Lista todos os PDFs da pasta de entrada
pdfs = [f for f in os.listdir(PASTA_ENTRADAS) if f.lower().endswith('.pdf')]

if not pdfs:
    print("❌ Nenhum PDF encontrado em:", PASTA_ENTRADAS)
    exit(1)

for nome_arquivo in pdfs:
    caminho_pdf = os.path.join(PASTA_ENTRADAS, nome_arquivo)
    print(f"\n📄 Processando: {nome_arquivo}")

    # Lê o conteúdo do PDF
    with fitz.open(caminho_pdf) as doc:
        texto = ""
        for page in doc:
            texto += page.get_text()

    # Extrai nome do emissor
    match_emissor = re.search(r'\n([A-Z ]{5,})\s+CNPJ:\s*[\d./-]+\s+IE:', texto)
    if match_emissor:
        nome_emissor = match_emissor.group(1).strip()
        nome_emissor = re.sub(r'\W+', '_', nome_emissor).strip('_')
    else:
        nome_emissor = 'EMISSOR_DESCONHECIDO'
        print("⚠️ Nome do emissor não encontrado. Usando padrão.")

    # Extrai número da CTE com base na linha "SÉRIE 1 <número>"
    match_cte = re.search(r'SÉRIE\s*1\s*(\d{3,6})', texto)
    if match_cte:
        numero_cte = match_cte.group(1)
    else:
        numero_cte = '000'
        print("⚠️ Número da CTE não encontrado. Usando 000.")

    # Monta nome final
    nome_final = f"{nome_emissor}_CTE_{numero_cte}.pdf"
    caminho_destino = os.path.join(PASTA_SAIDA, nome_final)

    # Move e renomeia
    shutil.move(caminho_pdf, caminho_destino)
    print(f"✅ Arquivo movido e renomeado para: {nome_final}")
