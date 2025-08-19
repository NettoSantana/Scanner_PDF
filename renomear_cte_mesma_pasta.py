# renomear_cte_mesma_pasta.py
import os
import re
import sys
import shutil
import unicodedata
import subprocess
import argparse
import io
from typing import Optional, Tuple, List
import fitz  # PyMuPDF
from PIL import Image
from pyzbar.pyzbar import decode as zbar_decode
import pytesseract
from urllib.parse import urlparse, parse_qs
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
        tesseract_path = shutil.which("tesseract")
        print("• tesseract:", tesseract_path or "NÃO ENCONTRADO")
    except Exception as e:
        print("• Aviso: diagnóstico Poppler/Tesseract falhou:", e)

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

# Regex pré-compiladas (modelos específicos continuam valendo para PDFs com texto embutido)
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

# ================== Rasterização / QR / OCR ==================
def page_to_pil(page: fitz.Page, dpi: int = 300) -> Image.Image:
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img

def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def parse_chave_acesso_from_payload(payload: str) -> Optional[str]:
    """
    Aceita: 44 dígitos diretos OU URL contendo ?p=... ou chNFe/chCTe/pChaveAcesso com 44 dígitos.
    """
    if not payload:
        return None
    # URL?
    try:
        u = urlparse(payload)
        if u.query:
            q = parse_qs(u.query)
            for key in ("p", "pChaveAcesso", "chNFe", "chCTe"):
                for v in q.get(key, []):
                    d = _digits_only(v)
                    if len(d) == 44:
                        return d
    except Exception:
        pass
    # Texto cru com 44 dígitos
    d = _digits_only(payload)
    m = re.search(r"(\d{44})", d)
    return m.group(1) if m else None

def decode_qr_from_image(img: Image.Image) -> List[str]:
    try:
        results = zbar_decode(img)
        return [r.data.decode("utf-8", errors="replace") for r in results if r.data]
    except Exception:
        return []

def nct_from_chave(chave44: str) -> Optional[str]:
    """
    Chave: cUF(2) AAMM(4) CNPJ(14) mod(2) série(3) nDoc(9) tpEmis(1) cNF(8) DV(1)
    Para CT-e: mod=57 (CT-e) ou 67 (CT-e OS). Número = posições 26..34 (9 dígitos).
    """
    if not chave44 or len(chave44) != 44 or not chave44.isdigit():
        return None
    mod = chave44[20:22]
    if mod not in ("57", "67"):
        return None
    numero = chave44[25:34]  # zero-based
    return str(int(numero)) if numero.isdigit() else None

def cnpj_from_chave(chave44: str) -> Optional[str]:
    if not chave44 or len(chave44) != 44 or not chave44.isdigit():
        return None
    cnpj = chave44[6:20]
    return cnpj

def format_cnpj(cnpj14: str) -> str:
    if not cnpj14 or len(cnpj14) != 14:
        return ""
    return f"{cnpj14[0:2]}.{cnpj14[2:5]}.{cnpj14[5:8]}/{cnpj14[8:12]}-{cnpj14[12:14]}"

def ocr_text(img: Image.Image) -> str:
    # Modo rápido e robusto para caixa alta
    cfg = "--oem 1 --psm 6"
    try:
        return pytesseract.image_to_string(img, lang="por", config=cfg) or ""
    except Exception:
        try:
            return pytesseract.image_to_string(img, config=cfg) or ""
        except Exception:
            return ""

def guess_emissor(texto: str, cnpj14: Optional[str] = None) -> str:
    up = (texto or "").upper()
    nome = "EMISSOR_DESCONHECIDO"
    # Se temos CNPJ, tente capturar a linha do nome próxima do CNPJ
    if cnpj14:
        cnpj_fmt = format_cnpj(cnpj14)
        pads = [cnpj_fmt, cnpj14]
        for needle in pads:
            if not needle:
                continue
            # pega até 60 chars antes do CNPJ na mesma linha/bloco
            m = re.search(rf"([A-Z0-9 .,&'\-]{{8,60}})\s*(?:CNPJ|CPF)?.{{0,10}}{re.escape(needle)}", up, re.MULTILINE)
            if m:
                nome = m.group(1)
                break
    if nome == "EMISSOR_DESCONHECIDO":
        # fallback: primeira linha LONGA em caixa-alta sem palavras proibidas
        linhas = [l.strip() for l in up.splitlines() if l.strip()]
        linhas = [l for l in linhas if len(l) >= 8 and not any(w in l for w in ("CONHECIMENTO", "DACTE", "CHAVE", "ACESSO", "PROTOCOLO", "RECEITA", "FISCO", "DESTINAT", "REMET", "TOMADOR", "TRANSPORTE"))]
        if linhas:
            nome = linhas[0][:60]
    return slugify(nome)

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

# ================== Núcleo: extrair metadados de 1 página ==================
def extrair_meta_pagina(pagina: fitz.Page) -> Tuple[str, str, str]:
    """
    Retorna (tipo_doc, nome_emissor_slug, numero_doc)
    tipo_doc ∈ {"CTE","NF","BOLETO","DESCONHECIDO"}
    """
    # 1) Texto embutido (quando existir)
    texto = pagina.get_text("text") or ""
    tipo_doc = identificar_tipo(texto)

    nome_emissor = "EMISSOR_DESCONHECIDO"
    numero_doc   = "000"

    # Tenta primeiro pelos MODELOS conhecidos (rápido quando há texto embutido)
    if tipo_doc == "CTE" and texto:
        for modelo, regras in MODELOS.items():
            if regras["regex_emissor"].search(texto):
                m_emp = regras["regex_emissor"].search(texto)
                if m_emp:
                    nome_emissor = slugify(m_emp.group(1))
                m_num = regras["regex_cte"].search(texto)
                if m_num:
                    numero_doc = str(int(m_num.group(1)))
                return ("CTE", nome_emissor, numero_doc)

    # 2) Rasteriza a página e tenta QR/Barcode → chave de acesso
    img = page_to_pil(pagina, dpi=300)
    payloads = decode_qr_from_image(img)
    chave = None
    for p in payloads:
        c = parse_chave_acesso_from_payload(p)
        if c:
            chave = c
            break

    cnpj14 = cnpj_from_chave(chave) if chave else None
    nct    = nct_from_chave(chave) if chave else None
    if chave and nct:
        tipo_doc = "CTE"  # mod 57/67 confirmado pela chave
        numero_doc = nct
    # 3) OCR como fallback (nome do emissor e/ou identificação do tipo)
    ocr = ocr_text(img)
    if tipo_doc == "DESCONHECIDO":
        tipo_doc = identificar_tipo(ocr)

    # nome emissor: preferir OCR, usando CNPJ quando existir
    nome_emissor = guess_emissor(ocr or texto, cnpj14) if (ocr or texto) else "EMISSOR_DESCONHECIDO"

    return (tipo_doc, nome_emissor, numero_doc)

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
                tipo_doc, nome_emissor, numero_doc = extrair_meta_pagina(pagina)

                if not numero_doc or not numero_doc.isdigit():
                    numero_doc = "000"

                nome_final = f"{slugify(nome_emissor)}_{tipo_doc}_{numero_doc}.pdf"
                is_cte_ok = (tipo_doc == "CTE" and nome_emissor != "EMISSOR_DESCONHECIDO" and numero_doc != "000")

                destino_base = PASTA_SAIDA if is_cte_ok else PASTA_PENDENTES
                destino = os.path.join(destino_base, nome_final)

                if os.path.exists(destino) and OUTPUT_OVERWRITE == "skip":
                    print(f"⏭️  Saída já existe, pulando: {os.path.basename(destino)}")
                    if is_cte_ok:
                        saidas_cte.append(os.path.basename(destino))
                    continue

                nova_doc = fitz.open()
                nova_doc.insert_pdf(doc, from_page=i, to_page=i)
                if OUTPUT_OVERWRITE == "replace" and os.path.exists(destino):
                    pass
                nova_doc.save(destino, deflate=True, garbage=4)
                nova_doc.close()

                if is_cte_ok:
                    print(f"✅ Página {i+1} (CTE) salva: {os.path.basename(destino)}")
                    saidas_cte.append(os.path.basename(destino))
                else:
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
    parser = argparse.ArgumentParser(description="Processa PDFs (escaneados ou digitais) e renomeia por tipo/emissor/número.")
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
