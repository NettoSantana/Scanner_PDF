import os
import re
from pdf2image import convert_from_path
import pytesseract
from fpdf import FPDF
from PIL import Image

# ✅ Caminho do executável do Tesseract OCR
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# ✅ Caminho da pasta bin do Poppler
poppler_path = r'C:\Users\vlula\OneDrive\Área de Trabalho\Projetos Backup\ScannerOCR\Release-24.08.0-0\poppler-24.08.0\Library\bin'

# ✅ Caminho da pasta com os PDFs de entrada
entrada_dir = r'C:\Users\vlula\ScannerOCR\entradas'

# 🔍 Função para extrair texto da imagem
def extrair_texto_da_pagina(imagem):
    return pytesseract.image_to_string(imagem, lang='por')

# 💾 Função para salvar imagens em um único PDF
def salvar_pdf(paginas, nome_arquivo):
    pdf = FPDF()
    for pagina in paginas:
        temp_img_path = "temp_page.jpg"
        pagina.save(temp_img_path, "JPEG")
        pdf.add_page()
        pdf.image(temp_img_path, 0, 0, 210, 297)
        os.remove(temp_img_path)
    os.makedirs("paginas_renomeadas", exist_ok=True)
    pdf.output(os.path.join("paginas_renomeadas", nome_arquivo))

# 🔎 Função para identificar nome do emitente e número da nota
def identificar_nome_e_numero(texto):
    texto_limpo = re.sub(r'[^\w\s\/\.-:]', '', texto)
    linhas = texto_limpo.splitlines()

    nome = "DESCONHECIDO"
    numero = "0000"

    for i, linha in enumerate(linhas):
        linha_up = linha.upper()

        # Número da Nota (na mesma linha ou na próxima)
        if "NUMERO DA NOTA" in linha_up or "NÚMERO DA NOTA" in linha_up:
            match = re.search(r'\d{3,}', linha)
            if match:
                numero = match.group().zfill(4)
            elif i + 1 < len(linhas):
                match = re.search(r'\d{3,}', linhas[i + 1])
                if match:
                    numero = match.group().zfill(4)

        # Nome do Emitente
        if ("NOME/RAZAO SOCIAL" in linha_up or "NOME/RAZÃO SOCIAL" in linha_up) and nome == "DESCONHECIDO":
            partes = linha.split(":")
            if len(partes) > 1:
                nome_raw = partes[1].strip()
                nome_sem_numeros = re.split(r'\d', nome_raw)[0].strip()
                nome = nome_sem_numeros.replace(" ", "_").upper()

        # Nome fixo se detectado
        if "SAN MAN MANUTENCAO" in linha_up:
            nome = "SAN_MAN_MANUTENCAO_LTDA"

    return nome, numero

# 🚀 Início do processamento
print("🔍 Iniciando OCR e separação de páginas...")

# 🔄 Itera por todos os arquivos PDF da pasta de entrada
for arquivo in os.listdir(entrada_dir):
    if not arquivo.lower().endswith(".pdf"):
        continue

    caminho_pdf = os.path.join(entrada_dir, arquivo)
    print(f"\n📁 Processando arquivo: {arquivo}")

    try:
        images = convert_from_path(caminho_pdf, poppler_path=poppler_path)
    except Exception as e:
        print(f"❌ Erro ao converter {arquivo}: {e}")
        continue

    documentos = []
    for i, img in enumerate(images):
        texto = extrair_texto_da_pagina(img)
        print(f"📝 Texto OCR detectado - Página {i+1}:\n{texto}\n{'-'*50}")
        nome, numero = identificar_nome_e_numero(texto)
        print(f"📄 Página {i+1}: info extraída -> ({nome}, {numero})")
        documentos.append((nome, numero, img))

    # 📦 Agrupa páginas por nome e número
    agrupados = {}
    for nome, numero, img in documentos:
        chave = (nome, numero)
        if chave not in agrupados:
            agrupados[chave] = []
        agrupados[chave].append(img)

    # 🧾 Gera os PDFs renomeados
    for (nome, numero), paginas in agrupados.items():
        nome_arquivo = f"{nome}_NF_{numero}.pdf"
        salvar_pdf(paginas, nome_arquivo)

print("\n✅ Processamento finalizado.")
print("📂 PDFs gerados em: paginas_renomeadas")
