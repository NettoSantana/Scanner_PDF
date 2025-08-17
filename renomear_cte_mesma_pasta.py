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
            out = subprocess.check_output(
                ["pdftoppm", "-v"], stderr=subprocess.STDOUT
            ).decode(errors="replace").strip()
            print("• pdftoppm -v:", out)
    except Exception as e:
        print("• Aviso: diagnóstico Poppler falhou:", e)

diagnostico_poppler()

# ================== Config / Args ==================
load_dotenv()

def _dirs_from_env():
    base = os.getcwd()
    input_dir      = os.getenv("INPUT_DIR",      os.path.join(base, "entradas"))
    output_dir     = os.getenv("OUTPUT_DIR",     os.path.join(base, "renomeados"))
    pendentes_dir  = os.getenv("PENDENTES_DIR",  os.path.join(base, "pendentes"))
    processed_dir  = os.getenv("PROCESSED_DIR",  os.path.join(base, "processados"))
    disposition    = os.getenv("INPUT_DISPOSITION", "move").lower()  # move | delete | keep
    overwrite_mode = os.getenv("OUTPUT_OVERWRITE",  "skip").lower()  # skip | replace
    return input_dir, output_dir, pendentes_dir, processed_dir, disposition, overwrite_mode

# Defaults quando importado (server/gunicorn)
(PASTA_ENTRADAS,
 PASTA_SAIDA,
 PASTA_PENDENTES,
 PASTA_PROCESSADOS,
 INPUT_DISPOSITION,
 OUTPUT_OVERWRITE) = _dirs_from_env()

for pasta in (PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES, PASTA_PROCESSADOS):
    os.makedirs(pasta, exist_ok=True)

print("🔧 PASTA_ENTRADAS:", PASTA_ENTRADAS)
print("📂 PASTA_SAIDA:", PASTA_SAIDA)
print("📂 PASTA_PENDENTES:", PASTA_PENDENTES)
print("📦 PASTA_PROCESSADOS:", PASTA_PROCESSADOS)
print("📝 OUTPUT_OVERWRITE:", OUTPUT_OVERWRITE)
print("⚙️ INPUT_DISPOSITION:", INPUT_DISPOSITION)

# ================== Utilidades ==================
def remover_acentos(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

def slugify(nome: str) -> str:
    nome = remover_acentos((nome or "").strip())
    nome = re.sub(r"\W+", "_", nome)
    nome = re.sub(r"_+", "_", nome).strip("_")
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

# Regex pré-compiladas
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

# ================== Disposição da entrada ==================
def _dispor_entrada(caminho_pdf: str):
    try:
        if INPUT_DISPOSITION == "delete":
            os.remove(caminho_pdf)
            print(f"🗑️ Entrada removida: {os.path.basename(caminho_pdf)}")
        elif INPUT_DISPOSITION == "move":
            os.makedirs(PASTA_PROCESSADOS, exist_ok=True)
            destino = os.path.join(PASTA_PROCESSADOS, os.path.basename(caminho_pdf))
            if os.path.exists(destino):
                base, ext = os.path.splitext(destino)
                k = 1
                while os.path.exists(f"{base}__{k}{ext}"):
                    k += 1
                destino = f"{base}__{k}{ext}"
            shutil.move(caminho_pdf, destino)
            print(f"📦 Entrada arquivada em: {destino}")
        else:
            print("ℹ️ INPUT_DISPOSITION=keep — mantendo entradas (pode reprocessar).")
    except Exception as e:
        print(f"⚠️ Falha ao dispor entrada: {e}")

# ================== Processamento ==================
def processar_pdf(caminho_pdf: str):
    """Processa 1 PDF e retorna uma lista de BASENAMES criados/identificados em PASTA_SAIDA (CT-e)."""
    print(f"\n📄 Processando: {os.path.basename(caminho_pdf)}")
    saidas_cte = []

    try:
        doc = fitz.open(caminho_pdf)
    except Exception as e:
        print(f"⚠️ Erro ao abrir PDF '{caminho_pdf}': {e}")
        return saidas_cte

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
                                nome_emissor = slugify(m_emp.group(1))
                            m_num = regras["regex_cte"].search(texto)
                            if m_num:
                                numero_doc = m_num.group(1)
                            break

                nome_final = f"{slugify(nome_emissor)}_{tipo_doc}_{numero_doc}.pdf"
                destino = os.path.join(
                    (PASTA_SAIDA if (tipo_doc == "CTE" and modelo_usado) else PASTA_PENDENTES),
                    nome_final
                )

                if tipo_doc == "CTE" and modelo_usado:
                    # Política de overwrite
                    if os.path.exists(destino) and OUTPUT_OVERWRITE == "skip":
                        print(f"⏭️  Saída já existe, pulando: {os.path.basename(destino)}")
                        saidas_cte.append(os.path.basename(destino))  # ainda assim reporta para envio
                    else:
                        nova_doc = fitz.open()
                        nova_doc.insert_pdf(doc, from_page=i, to_page=i)
                        # se "replace", sobrescreve; se "skip", não chega aqui; se não existir, cria
                        if OUTPUT_OVERWRITE == "replace" and os.path.exists(destino):
                            pass  # sobrescreve na mesma rota
                        nova_doc.save(destino, deflate=True, garbage=4)
                        nova_doc.close()
                        print(f"✅ Página {i+1} ({modelo_usado}) salva: {os.path.basename(destino)}")
                        saidas_cte.append(os.path.basename(destino))
                else:
                    # pendentes
                    if not os.path.exists(destino):
                        nova_doc = fitz.open()
                        nova_doc.insert_pdf(doc, from_page=i, to_page=i)
                        nova_doc.save(destino, deflate=True, garbage=4)
                        nova_doc.close()
                    print(f"➜ Página {i+1} movida para pendentes: {os.path.basename(destino)}")

            except Exception as e_pag:
                print(f"⚠️ Erro na página {i+1}: {e_pag}")
    finally:
        try:
            doc.close()
        except Exception:
            pass

    _dispor_entrada(caminho_pdf)
    return saidas_cte

def processar_arquivos(caminhos: list):
    """Processa SOMENTE os PDFs informados.
       Retorna lista de basenames na pasta de saída (CT-e), incluindo os já existentes quando OUTPUT_OVERWRITE=skip."""
    out = []
    for c in caminhos:
        if c and c.lower().endswith(".pdf") and os.path.exists(c):
            out.extend(processar_pdf(c))
    return out

def processar():
    """Processa TUDO que estiver em PASTA_ENTRADAS (modo CLI)."""
    arquivos = [f for f in os.listdir(PASTA_ENTRADAS) if f.lower().endswith(".pdf")]
    if not arquivos:
        print("ℹ️ Nenhum PDF em", PASTA_ENTRADAS)
        return
    for nome in arquivos:
        processar_pdf(os.path.join(PASTA_ENTRADAS, nome))

# ================== Execução via CLI ==================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Processa PDFs e renomeia por tipo/emissor/número.")
    parser.add_argument("--input",     default=PASTA_ENTRADAS,   help="Pasta de entrada")
    parser.add_argument("--output",    default=PASTA_SAIDA,      help="Pasta de saída OK")
    parser.add_argument("--pendentes", default=PASTA_PENDENTES,  help="Pasta de pendentes")
    parser.add_argument("--processed", default=PASTA_PROCESSADOS, help="Pasta de processados (arquivo original)")
    parser.add_argument("--disposition", default=INPUT_DISPOSITION, choices=["move","delete","keep"],
                        help="O que fazer com a entrada após processar")
    parser.add_argument("--overwrite", default=OUTPUT_OVERWRITE, choices=["skip","replace"],
                        help="Se arquivo de saída já existir: skip (pula) ou replace (sobrescreve)")
    args = parser.parse_args()

    PASTA_ENTRADAS      = args.input
    PASTA_SAIDA         = args.output
    PASTA_PENDENTES     = args.pendentes
    PASTA_PROCESSADOS   = args.processed
    INPUT_DISPOSITION   = args.disposition
    OUTPUT_OVERWRITE    = args.overwrite

    for pasta in (PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES, PASTA_PROCESSADOS):
        os.makedirs(pasta, exist_ok=True)

    processar()
