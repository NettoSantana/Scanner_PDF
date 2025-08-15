import os
import re
import sys
import shutil
import unicodedata
import subprocess
import argparse
import fitz  # PyMuPDF
from dotenv import load_dotenv

# ================== Ambiente / Poppler (diagnóstico defensivo) ==================
# Em containers Ubuntu (Railway/Docker), binários ficam aqui:
for p in ("/usr/bin", "/usr/local/bin"):
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + p
os.environ.setdefault("POPPLER_PATH", "/usr/bin")

def diagnostico_poppler():
    try:
        print("🔎 Diagnóstico do ambiente")
        print("• sys.platform:", sys.platform)
        print("• PATH contém /usr/bin?:", "/usr/bin" in os.environ.get("PATH", ""))
        pdftoppm_path = shutil.which("pdftoppm")
        print("• pdftoppm:", pdftoppm_path or "NÃO ENCONTRADO")
        if pdftoppm_path:
            out = subprocess.check_output(["pdftoppm", "-v"], stderr=subprocess.STDOUT).decode(errors="replace").strip()
            print("• pdftoppm -v:", out)
    except Exception as e:
        # Não aborta o fluxo se diagnóstico falhar
        print("• Aviso: diagnóstico Poppler falhou:", e)

diagnostico_poppler()

# ================== Config / Args ==================
load_dotenv()

parser = argparse.ArgumentParser(description="Processa PDFs (split por página) e renomeia por tipo/emissor/número.")
parser.add_argument("--input",     default=os.path.join(os.getcwd(), "entradas"),   help="Pasta de entrada")
parser.add_argument("--output",    default=os.path.join(os.getcwd(), "renomeados"), help="Pasta de saída OK")
parser.add_argument("--pendentes", default=os.path.join(os.getcwd(), "pendentes"),  help="Pasta de pendentes")
args = parser.parse_args()

PASTA_ENTRADAS  = args.input
PASTA_SAIDA     = args.output
PASTA_PENDENTES = args.pendentes

for pasta in (PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES):
    os.makedirs(pasta, exist_ok=True)

print("🔧 PASTA_ENTRADAS:", PASTA_ENTRADAS)
print("📂 PASTA_SAIDA:", PASTA_SAIDA)
print("📂 PASTA_PENDENTES:", PASTA_PENDENTES)

# ================== Utilidades ==================
def remover_acentos(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

def slugify(nome: str) -> str:
    nome = remover_acentos((nome or "").strip())
    nome = re.sub(r"\W+", "_", nome)           # troca não-alfanum por _
    nome = re.sub(r"_+", "_", nome).strip("_") # colapsa _
    return nome or "DESCONHECIDO"

def nome_unico(caminho_base: str) -> str:
    if not os.path.exists(caminho_base):
        return caminho_base
    raiz, ext = os.path.splitext(caminho_base)
    i = 1
    while True:
        candidato = f"{raiz}__{i}{ext}"
        if not os.path.exists(candidato):
            return candidato
        i += 1

def identificar_tipo(texto: str) -> str:
    up = (texto or "").upper()
    if ("CONHECIMENTO DE TRANSPORTE ELETRÔNICO" in up) or ("DACTE" in up):
        return "CTE"
    if ("NOTA FISCAL ELETRÔNICA" in up) or ("NFS-E" in up) or ("NF-E" in up):
        return "NF"
    if ("BOLETO" in up) or ("FICHA DE COMPENSAÇÃO" in up):
        return "BOLETO"
    return "DESCONHECIDO"

# Regex pré-compiladas (case-insensitive)
MODELOS = {
    "WANDER_PEREIRA_DE_MATOS": {
        "regex_emissor": re.compile(r"\n([A-Z ]{5,})\s+CNPJ:\s*[\d./-]+\s+IE:", re.IGNORECASE),
        "regex_cte":     re.compile(r"S[ÉE]RIE\s*1\s*(\d{3,6})", re.IGNORECASE),
    },
    "WASHINGTON_BALTAZAR_SOUZA_LIMA_ME": {
        "regex_emissor": re.compile(r"(WASHINGTON\s+BALTAZAR\s+SOUZA\s+LIMA\s+ME)", re.IGNORECASE),
        "regex_cte":     re.compile(r"N[ÚU]MERO\s+(\d{3,6})", re.IGNORECASE),
    },
}

# ================== Processamento ==================
def processar_pdf(caminho_pdf: str):
    prefixo_original = os.path.splitext(os.path.basename(caminho_pdf))[0]
    print(f"\n📄 Processando: {os.path.basename(caminho_pdf)}")

    doc = None
    try:
        doc = fitz.open(caminho_pdf)
    except Exception as e:
        print(f"⚠️ Erro ao abrir PDF '{caminho_pdf}': {e}")
        return

    try:
        for i in range(doc.page_count):
            try:
                pagina = doc.load_page(i)
                texto = pagina.get_text("text") or ""
                tipo_doc = identificar_tipo(texto)

                nome_emissor = "EMISSOR_DESCONHECIDO"
                numero_doc   = "000"
                modelo_usado = None

                if tipo_doc == "CTE":
                    for modelo, regras in MODELOS.items():
                        if regras["regex_emissor"].search(texto):
                            modelo_usado = modelo
                            m_emp = regras["regex_emissor"].search(texto)
                            if m_emp:
