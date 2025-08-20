# renomear_cte_mesma_pasta.py
import os, re, sys, shutil, unicodedata, subprocess, argparse
from typing import Optional, Tuple, List
import fitz  # PyMuPDF
from PIL import Image
from pyzbar.pyzbar import decode as zbar_decode
import pytesseract
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

# ===== Ambiente / Poppler / Tesseract (diagnóstico) =====
for p in ("/usr/bin", "/usr/local/bin"):
    if p not in os.environ.get("PATH", ""):
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + p
os.environ.setdefault("POPPLER_PATH", "/usr/bin")

def _diag():
    try:
        print("🔎 Diagnóstico do ambiente")
        print("• sys.platform:", sys.platform)
        print("• PATH contém /usr/bin?:", "/usr/bin" in os.environ.get("PATH", ""))
        print("• pdftoppm:", shutil.which("pdftoppm") or "NÃO ENCONTRADO")
        if shutil.which("pdftoppm"):
            out = subprocess.check_output(["pdftoppm","-v"], stderr=subprocess.STDOUT).decode(errors="replace").splitlines()[0]
            print("•", out)
        print("• tesseract:", shutil.which("tesseract") or "NÃO ENCONTRADO")
    except Exception as e:
        print("• Aviso: diagnóstico falhou:", e)
_diag()

# ===== Config =====
load_dotenv()
def _dirs_from_env():
    base = os.getcwd()
    input_dir      = os.getenv("INPUT_DIR",      os.path.join(base, "entradas"))
    output_dir     = os.getenv("OUTPUT_DIR",     os.path.join(base, "renomeados"))
    pendentes_dir  = os.getenv("PENDENTES_DIR",  os.path.join(base, "pendentes"))
    processed_dir  = os.getenv("PROCESSED_DIR",  os.path.join(base, "processados"))
    disposition    = os.getenv("INPUT_DISPOSITION", "move").lower()   # move|delete|keep
    overwrite_mode = os.getenv("OUTPUT_OVERWRITE",  "skip").lower()   # skip|replace
    return input_dir, output_dir, pendentes_dir, processed_dir, disposition, overwrite_mode

(PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES, PASTA_PROCESSADOS, INPUT_DISPOSITION, OUTPUT_OVERWRITE) = _dirs_from_env()
for pasta in (PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES, PASTA_PROCESSADOS):
    os.makedirs(pasta, exist_ok=True)

print("🔧 PASTA_ENTRADAS:", PASTA_ENTRADAS)
print("📂 PASTA_SAIDA:", PASTA_SAIDA)
print("📂 PASTA_PENDENTES:", PASTA_PENDENTES)
print("📦 PASTA_PROCESSADOS:", PASTA_PROCESSADOS)
print("📝 OUTPUT_OVERWRITE:", OUTPUT_OVERWRITE)
print("⚙️ INPUT_DISPOSITION:", INPUT_DISPOSITION)

# ===== Util =====
NEG_TOKENS = (
    "CONHECIMENT", "DOCUMENTO AUXILIAR", "DACTE", "CHAVE", "ACESSO", "PROTOC",
    "RECEITA", "FISCO", "DESTINAT", "REMET", "TOMADOR", "QRCODE", "CONSULTE",
    "TIPO DO CT", "TIPO DO SERVI", "INICIO DA PRESTAC", "TERMINO DA PRESTAC",
    "DATA E HORA", "MODELO", "SERIE", "NUMERO", "N PROTOCOLO", "PAGINA",
    "SALVADOR", "CAMAÇARI", "CAMAÇARI", "BA", "BAHIA", "ENDERECO", "ENDEREÇO"
)
PREF_TOKENS = (" LTDA", " S/A", " SA ", " ME ", " EPP", " MEI", " TRANSPORT", " LOGIST", " COMERC", " INDUSTR", " SERVI", " DISTRIB", " TRANS ")

CITY_UF_TOKENS = (" SALVADOR", " CAMAÇARI", " CAMAÇARI", " BA", " - BA")

def remover_acentos(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii","ignore").decode("ascii")

def slugify(nome: str) -> str:
    nome = remover_acentos((nome or "").strip())
    # remove tokens numéricos (mais de 1 dígito) dentro do nome
    nome = re.sub(r"\b\d{2,}\b", " ", nome)
    nome = re.sub(r"\s{2,}", " ", nome).strip()
    nome = re.sub(r"\W+", "_", nome)
    nome = re.sub(r"_+", "_", nome).strip("_")
    return nome or "DESCONHECIDO"

def identificar_tipo(texto: str) -> str:
    up = remover_acentos(texto).upper()
    if "DACTE" in up or "CONHECIMENTO DE TRANSPORTE" in up: return "CTE"
    if "NOTA FISCAL" in up or "NF-E" in up or "NFS-E" in up: return "NF"
    if "BOLETO" in up or "FICHA DE COMPENSAC" in up:        return "BOLETO"
    return "DESCONHECIDO"

# Padrões quando há texto embutido
MODELOS = {
    "WANDER_PEREIRA_DE_MATOS": {
        "regex_emissor": re.compile(r"\n([A-Z ]{5,})\s+CNPJ:\s*[\d./-]+\s+IE:", re.I),
        "regex_cte":     re.compile(r"S[ÉE]RIE\s*1\s*(\d{3,6})", re.I),
    },
    "WASHINGTON_BALTAZAR_SOUZA_LIMA_ME": {
        "regex_emissor": re.compile(r"(WASHINGTON\s+BALTAZAR\s+SOUZA\s+LIMA\s+ME)", re.I),
        "regex_cte":     re.compile(r"N[ÚU]MERO\s+(\d{3,6})", re.I),
    },
}

# ===== Raster / QR / OCR =====
def page_to_pil(page: fitz.Page, dpi: int = 300) -> Image.Image:
    mat = fitz.Matrix(dpi/72.0, dpi/72.0)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

def parse_chave_acesso_from_payload(payload: str) -> Optional[str]:
    if not payload: return None
    try:
        u = urlparse(payload)
        if u.query:
            q = parse_qs(u.query)
            for key in ("p","pChaveAcesso","chNFe","chCTe"):
                for v in q.get(key, []):
                    d = _digits_only(v)
                    if len(d) == 44: return d
    except Exception: pass
    d = _digits_only(payload)
    m = re.search(r"(\d{44})", d)
    return m.group(1) if m else None

def decode_qr_from_image(img: Image.Image) -> List[str]:
    try:
        return [r.data.decode("utf-8","replace") for r in zbar_decode(img) if r.data]
    except Exception:
        return []

def nct_from_chave(chave44: str) -> Optional[str]:
    if not (chave44 and len(chave44)==44 and chave44.isdigit()): return None
    if chave44[20:22] not in ("57","67"): return None
    numero = chave44[25:34]
    return str(int(numero)) if numero.isdigit() else None

def cnpj_from_chave(chave44: str) -> Optional[str]:
    if not (chave44 and len(chave44)==44 and chave44.isdigit()): return None
    return chave44[6:20]

def format_cnpj(cnpj14: str) -> str:
    if not cnpj14 or len(cnpj14)!=14: return ""
    return f"{cnpj14[0:2]}.{cnpj14[2:5]}.{cnpj14[5:8]}/{cnpj14[8:12]}-{cnpj14[12:14]}"

def ocr_text(img: Image.Image) -> str:
    cfg = "--oem 1 --psm 6"
    try:    return pytesseract.image_to_string(img, lang="por", config=cfg) or ""
    except Exception:
        try: return pytesseract.image_to_string(img, config=cfg) or ""
        except Exception: return ""

# ===== Heurísticas de nome do emissor =====
def _is_bad_line(s: str) -> bool:
    u = remover_acentos(s).upper()
    if sum(c.isdigit() for c in u) > max(2, len(u)//4):  # muito dígito => não é razão social
        return True
    if any(tok in u for tok in NEG_TOKENS):
        return True
    return False

def _clean_company_line(s: str) -> str:
    s = s.strip(" :.-\t")
    s = re.sub(r"^(RAZAO\s+SOCIAL|RAZAO|EMITENTE|EMISSOR|PRESTADOR(?:\s+DE\s+SERVI[ÇC]O)?|EMPRESA)\s*[:\-]*\s*", "", s, flags=re.I)
    # Remove cidade/UF no fim
    for tok in CITY_UF_TOKENS:
        if remover_acentos(s).upper().endswith(tok):
            s = s[: -len(tok)]
    # remove tokens muito curtos ou numéricos
    s = " ".join(t for t in s.split() if not re.fullmatch(r"\d{2,}", t) and len(t) > 1)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()

def _score_company_line(s: str) -> int:
    u = remover_acentos(s).upper()
    score = len(u)
    for t in PREF_TOKENS:
        if t in u: score += 25
    if _is_bad_line(u): score -= 100
    return score

def _guess_by_cnpj_block(linhas: List[str], cnpj14: Optional[str]) -> Optional[str]:
    if not cnpj14: return None
    tgt = cnpj14
    for i,l in enumerate(linhas):
        ld = _digits_only(l)
        if tgt in ld or "CNPJ" in remover_acentos(l).upper():
            cand_list = []
            for j in range(max(0, i-3), i):
                cand = _clean_company_line(linhas[j])
                if cand and not _is_bad_line(cand):
                    cand_list.append(cand)
            if cand_list:
                return max(cand_list, key=_score_company_line)
    return None

def _guess_by_dacte_block(linhas: List[str]) -> Optional[str]:
    for i,l in enumerate(linhas):
        if "DACTE" in remover_acentos(l).upper():
            cand_list = []
            for j in range(max(0, i-6), i):
                cand = _clean_company_line(linhas[j])
                if cand and not _is_bad_line(cand):
                    cand_list.append(cand)
            if cand_list:
                return max(cand_list, key=_score_company_line)
    return None

def _guess_by_global_best(linhas: List[str]) -> Optional[str]:
    # varre apenas o topo do documento (primeiras ~20 linhas)
    topo = linhas[:20] if len(linhas) > 20 else linhas
    cand_list = []
    for l in topo:
        cand = _clean_company_line(l)
        if cand and not _is_bad_line(cand) and len(remover_acentos(cand)) >= 8:
            cand_list.append(cand)
    if cand_list:
        return max(cand_list, key=_score_company_line)
    return None

def guess_emissor(ocr_texto: str, cnpj14: Optional[str] = None) -> str:
    if not ocr_texto:
        return "EMISSOR_DESCONHECIDO"
    linhas = [l.strip() for l in ocr_texto.splitlines() if l.strip()]

    # 1) CNPJ (linha acima) ou linha acima de onde aparece "CNPJ"
    nome = _guess_by_cnpj_block(linhas, cnpj14)
    if not nome:
        # 2) bloco acima de DACTE
        nome = _guess_by_dacte_block(linhas)
    if not nome:
        # 3) melhor linha global no topo
        nome = _guess_by_global_best(linhas)
    return slugify(nome or "EMISSOR_DESCONHECIDO")

# ===== Disposição da entrada =====
def _dispor_entrada(caminho_pdf: str):
    try:
        if INPUT_DISPOSITION == "delete":
            os.remove(caminho_pdf); print(f"🗑️ Entrada removida: {os.path.basename(caminho_pdf)}")
        elif INPUT_DISPOSITION == "move":
            os.makedirs(PASTA_PROCESSADOS, exist_ok=True)
            destino = os.path.join(PASTA_PROCESSADOS, os.path.basename(caminho_pdf))
            if os.path.exists(destino):
                base, ext = os.path.splitext(destino); k = 1
                while os.path.exists(f"{base}__{k}{ext}"): k += 1
                destino = f"{base}__{k}{ext}"
            shutil.move(caminho_pdf, destino); print(f"📦 Entrada arquivada em: {destino}")
        else:
            print("ℹ️ INPUT_DISPOSITION=keep — mantendo entradas.")
    except Exception as e:
        print(f"⚠️ Falha ao dispor entrada: {e}")

# ===== Núcleo =====
def extrair_meta_pagina(pagina: fitz.Page) -> Tuple[str, str, str]:
    texto = pagina.get_text("text") or ""
    tipo_doc = identificar_tipo(texto)
    nome_emissor = "EMISSOR_DESCONHECIDO"
    numero_doc = "000"

    # Padrões quando há texto embutido
    if tipo_doc == "CTE" and texto:
        for _, regras in MODELOS.items():
            if regras["regex_emissor"].search(texto):
                m_emp = regras["regex_emissor"].search(texto)
                if m_emp: nome_emissor = slugify(m_emp.group(1))
                m_num = regras["regex_cte"].search(texto)
                if m_num: numero_doc = str(int(m_num.group(1)))
                return ("CTE", nome_emissor, numero_doc)

    # Raster + QR/Barcode
    img = page_to_pil(pagina, dpi=300)
    chave = None
    for payload in decode_qr_from_image(img):
        c = parse_chave_acesso_from_payload(payload)
        if c: chave = c; break
    cnpj14 = cnpj_from_chave(chave) if chave else None
    nct    = nct_from_chave(chave) if chave else None
    if chave and nct:
        tipo_doc = "CTE"; numero_doc = nct

    # OCR
    ocr = ocr_text(img)
    if tipo_doc == "DESCONHECIDO":
        tipo_doc = identificar_tipo(ocr)
    nome_emissor = guess_emissor(ocr or texto, cnpj14) if (ocr or texto) else "EMISSOR_DESCONHECIDO"

    return (tipo_doc, nome_emissor, numero_doc)

def processar_pdf(caminho_pdf: str) -> List[str]:
    print(f"\n📄 Processando: {os.path.basename(caminho_pdf)}")
    saidas_cte: List[str] = []
    try:
        doc = fitz.open(caminho_pdf)
    except Exception as e:
        print(f"⚠️ Erro ao abrir '{caminho_pdf}': {e}"); return saidas_cte

    try:
        for i in range(doc.page_count):
            try:
                pagina = doc.load_page(i)
                tipo_doc, nome_emissor, numero_doc = extrair_meta_pagina(pagina)
                if not numero_doc.isdigit(): numero_doc = "000"

                nome_final = f"{slugify(nome_emissor)}_{tipo_doc}_{numero_doc}.pdf"
                is_cte_ok = (tipo_doc == "CTE" and nome_emissor != "EMISSOR_DESCONHECIDO" and numero_doc != "000")
                destino_base = PASTA_SAIDA if is_cte_ok else PASTA_PENDENTES
                destino = os.path.join(destino_base, nome_final)

                if os.path.exists(destino) and OUTPUT_OVERWRITE == "skip":
                    print(f"⏭️  Saída já existe, pulando: {os.path.basename(destino)}")
                    if is_cte_ok: saidas_cte.append(os.path.basename(destino))
                    continue

                nova = fitz.open(); nova.insert_pdf(doc, from_page=i, to_page=i)
                nova.save(destino, deflate=True, garbage=4); nova.close()

                if is_cte_ok:
                    print(f"✅ Página {i+1} (CTE) salva: {os.path.basename(destino)}")
                    saidas_cte.append(os.path.basename(destino))
                else:
                    print(f"➜ Página {i+1} movida p/ pendentes: {os.path.basename(destino)}")
            except Exception as e_pag:
                print(f"⚠️ Erro na página {i+1}: {e_pag}")
    finally:
        try: doc.close()
        except Exception: pass

    _dispor_entrada(caminho_pdf)
    return saidas_cte

def processar_arquivos(caminhos: list) -> List[str]:
    out: List[str] = []
    for c in caminhos:
        if c and c.lower().endswith(".pdf") and os.path.exists(c):
            out.extend(processar_pdf(c))
    return out

def processar():
    arquivos = [f for f in os.listdir(PASTA_ENTRADAS) if f.lower().endswith(".pdf")]
    if not arquivos:
        print("ℹ️ Nenhum PDF em", PASTA_ENTRADAS); return
    for nome in arquivos:
        processar_pdf(os.path.join(PASTA_ENTRADAS, nome))

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Processa PDFs (escaneados ou digitais) e renomeia por tipo/emissor/número.")
    p.add_argument("--input",     default=PASTA_ENTRADAS)
    p.add_argument("--output",    default=PASTA_SAIDA)
    p.add_argument("--pendentes", default=PASTA_PENDENTES)
    p.add_argument("--processed", default=PASTA_PROCESSADOS)
    p.add_argument("--disposition", default=INPUT_DISPOSITION, choices=["move","delete","keep"])
    p.add_argument("--overwrite", default=OUTPUT_OVERWRITE, choices=["skip","replace"])
    a = p.parse_args()
    PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES, PASTA_PROCESSADOS = a.input, a.output, a.pendentes, a.processed
    INPUT_DISPOSITION, OUTPUT_OVERWRITE = a.disposition, a.overwrite
    for pasta in (PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES, PASTA_PROCESSADOS):
        os.makedirs(pasta, exist_ok=True)
    processar()
