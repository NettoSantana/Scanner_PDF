import os
import re
import fitz  # PyMuPDF
from dotenv import load_dotenv
import requests
import subprocess
import argparse

# ===== Função para verificar Poppler =====
def verificar_poppler():
    try:
        poppler_path = subprocess.check_output("which pdftoppm", shell=True).decode('utf-8').strip()
        if poppler_path:
            print(f"Poppler está no PATH: {poppler_path}")
        else:
            print("Poppler não encontrado no PATH.")
    except subprocess.CalledProcessError:
        print("Erro ao tentar encontrar Poppler no PATH.")

verificar_poppler()

# ===== Variáveis de ambiente =====
load_dotenv()

# ===== Parser para receber argumentos =====
parser = argparse.ArgumentParser(description="Processar PDFs recebidos via Twilio")
parser.add_argument("--input", help="Caminho da pasta de entrada", default=os.path.join(os.getcwd(), "entradas"))
parser.add_argument("--output", help="Caminho da pasta de saída", default=os.path.join(os.getcwd(), "renomeados"))
parser.add_argument("--pendentes", help="Caminho da pasta de pendentes", default=os.path.join(os.getcwd(), "pendentes"))
args = parser.parse_args()

PASTA_ENTRADAS = args.input
PASTA_SAIDA    = args.output
PASTA_PENDENTES= args.pendentes

# Garante que as pastas existem
os.makedirs(PASTA_ENTRADAS, exist_ok=True)
os.makedirs(PASTA_SAIDA, exist_ok=True)
os.makedirs(PASTA_PENDENTES, exist_ok=True)

print("🔧 PASTA_ENTRADAS:", PASTA_ENTRADAS)
print("📂 PASTA_SAIDA:", PASTA_SAIDA)
print("📂 PASTA_PENDENTES:", PASTA_PENDENTES)

# ===== Funções utilitárias existentes =====
def identificar_tipo(texto: str) -> str:
    up = (texto or "").upper()
    if "CONHECIMENTO DE TRANSPORTE ELETRÔNICO" in up or "DACTE" in up:
        return "CTE"
    if "NOTA FISCAL ELETRÔNICA" in up or "NFS-E" in up or "NF-E" in up:
        return "NF"
    if "BOLETO" in up or "FICHA DE COMPENSAÇÃO" in up:
        return "BOLETO"
    return "DESCONHECIDO"

MODELOS = {
    "WANDER_PEREIRA_DE_MATOS": {
        "regex_emissor": r'\n([A-Z ]{5,})\s+CNPJ:\s*[\d./-]+\s+IE:',
        "regex_cte": r'SÉRIE\s*1\s*(\d{3,6})'
    },
    "WASHINGTON_BALTAZAR_SOUZA_LIMA_ME": {
        "regex_emissor": r'(WASHINGTON\s+BALTAZAR\s+SOUZA\s+LIMA\s+ME)',
        "regex_cte": r'N[ÚU]MERO\s+(\d{3,6})'
    }
}

def slugify(nome: str) -> str:
    nome = re.sub(r'\W+', '_', (nome or '').strip())
    return re.sub(r'_+', '_', nome).strip('_') or 'DESCONHECIDO'

def nome_unico(caminho_base: str) -> str:
    if not os.path.exists(caminho_base):
        return caminho_base
    raiz, ext = os.path.splitext(caminho_base)
    i = 1
    while True:
        novo = f"{raiz}__{i}{ext}"
        if not os.path.exists(novo):
            return novo
        i += 1

# ===== Função principal =====
def processar():
    pdfs = [f for f in os.listdir(PASTA_ENTRADAS) if f.lower().endswith('.pdf')]
    if not pdfs:
        print("ℹ️ Nenhum PDF em", PASTA_ENTRADAS)
        return

    for nome_arquivo in pdfs:
        caminho_pdf = os.path.join(PASTA_ENTRADAS, nome_arquivo)
        prefixo_original = os.path.splitext(nome_arquivo)[0]
        print(f"\n📄 Processando: {nome_arquivo}")

        try:
            with fitz.open(caminho_pdf) as doc:
                for i, pagina in enumerate(doc):
                    nova_doc = fitz.open()
                    nova_doc.insert_pdf(doc, from_page=i, to_page=i)
                    texto = pagina.get_text() or ""
                    tipo_doc = identificar_tipo(texto)

                    nome_emissor = "EMISSOR_DESCONHECIDO"
                    numero_doc = "000"
                    modelo_usado = None

                    if tipo_doc == "CTE":
                        for modelo, regras in MODELOS.items():
                            if re.search(regras["regex_emissor"], texto, re.IGNORECASE):
                                modelo_usado = modelo
                                m_emp = re.search(regras["regex_emissor"], texto, re.IGNORECASE)
                                if m_emp:
                                    nome_emissor = slugify(m_emp.group(1))
                                m_num = re.search(regras["regex_cte"], texto, re.IGNORECASE)
                                if m_num:
                                    numero_doc = m_num.group(1)
                                break

                    nome_info = f"{slugify(nome_emissor)}_{tipo_doc}_{numero_doc}.pdf"
                    nome_final = f"{prefixo_original}__{nome_info}"

                    if tipo_doc != "CTE" or not modelo_usado:
                        caminho_destino = nome_unico(os.path.join(PASTA_PENDENTES, nome_final))
                        nova_doc.save(caminho_destino)
                    else:
                        caminho_destino = nome_unico(os.path.join(PASTA_SAIDA, nome_final))
                        nova_doc.save(caminho_destino)
                        print(f"✅ Página {i+1} ({modelo_usado}) salva como: {os.path.basename(caminho_destino)}")

                    nova_doc.close()
        except Exception as e:
            print(f"⚠️ Erro ao processar {nome_arquivo}: {e}")

if __name__ == "__main__":
    processar()
