# renomear_cte_mesma_pasta.py
import os, re, sys, shutil, unicodedata, subprocess, argparse
from typing import Optional, Tuple, List, Dict, Any
import fitz  # PyMuPDF
from PIL import Image, ImageOps, ImageFilter
from pyzbar.pyzbar import decode as zbar_decode
import pytesseract
from pytesseract import Output
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
    "SALVADOR", "CAMA", "BA", "ENDERECO", "ENDEREÇO"
)
PREF_TOKENS = (" LTDA", " S/A", " SA ", " ME ", " EPP", " MEI", " TRANSPORT", " LOGIST", " COMERC", " INDUSTR", " SERVI", " DISTRIB", " TRANS ")

def remover_acentos(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii","ignore").decode("ascii")

def slugify(nome: str) -> str:
    nome = remover_acentos((nome or "").strip())
    nome = re.sub(r"\b\d{2,}\b", " ", nome)          # tira números soltos
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

# ===== Raster / pré-processamento =====
def page_to_pil(page: fitz.Page, dpi: int = 300) -> Image.Image:
    mat = fitz.Matrix(dpi/72.0, dpi/72.0)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img

def preprocess(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.MedianFilter(3))
    return g

def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s or "")

# ===== QR / chave / CNPJ / número =====
from urllib.parse import urlparse, parse_qs
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

# ===== OCR bruto =====
def ocr_text(img: Image.Image) -> str:
    cfg = "--oem 1 --psm 6"
    try:    return pytesseract.image_to_string(img, lang="por", config=cfg) or ""
    except Exception:
        try: return pytesseract.image_to_string(img, config=cfg) or ""
        except Exception: return ""

def ocr_data(img: Image.Image) -> Dict[str, Any]:
    cfg = "--oem 1 --psm 6"
    try:
        return pytesseract.image_to_data(img, lang="por", config=cfg, output_type=Output.DICT)
    except Exception:
        return {"text": [], "conf": [], "left": [], "top": [], "width": [], "height": [], "line_num": [], "block_num": [], "par_num": []}

# ===== Heurísticas de nome do emissor com OCR-TSV =====
def _is_bad_line(s: str) -> bool:
    u = remover_acentos(s).upper()
    if sum(c.isdigit() for c in u) > max(2, len(u)//4):
        return True
    return any(tok in u for tok in NEG_TOKENS)

def _clean_company_line(s: str) -> str:
    s = s.strip(" :.-\t")
    s = re.sub(r"^(RAZAO\s+SOCIAL|RAZAO|EMITENTE|EMISSOR|PRESTADOR(?:\s+DE\s+SERVI[ÇC]O)?|EMPRESA)\s*[:\-]*\s*", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()

def _score_company_line(s: str) -> int:
    u = remover_acentos(s).upper()
    score = len(u)
    for t in PREF_TOKENS:
        if t in u: score += 25
    if _is_bad_line(u): score -= 100
    return score

def guess_emissor_from_data(data: Dict[str, Any], cnpj14: Optional[str]) -> Optional[str]:
    n = len(data.get("text", []))
    if n == 0: return None

    # monta linhas por (block, par, line)
    lines: Dict[Tuple[int,int,int], Dict[str, Any]] = {}
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt: continue
        conf = int(data.get("conf", ["-1"])[i]) if str(data.get("conf", ["-1"])[i]).isdigit() else -1
        if conf < 40:  # ignora baixíssima confiança
            continue
        b = int(data.get("block_num", [0])[i] or 0)
        p = int(data.get("par_num", [0])[i] or 0)
        ln = int(data.get("line_num", [0])[i] or 0)
        key = (b,p,ln)
        rec = lines.setdefault(key, {"words": [], "top": 10**9, "bottom": -1})
        rec["words"].append(txt)
        top = int(data.get("top", [0])[i] or 0)
        h   = int(data.get("height", [0])[i] or 0)
        rec["top"] = min(rec["top"], top)
        rec["bottom"] = max(rec["bottom"], top+h)

    # procura linha que contenha "CNPJ" OU o CNPJ cru/formatado
    def _fmt_cnpj(c):
        if not c or len(c)!=14: return None
        return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"
    cnpj_fmt = _fmt_cnpj(cnpj14)

    candidate_lines = []
    for key, rec in lines.items():
        line_text = " ".join(rec["words"])
        u = remover_acentos(line_text).upper()
        if "CNPJ" in u or (cnpj14 and cnpj14 in _digits_only(u)) or (cnpj_fmt and cnpj_fmt in u):
            candidate_lines.append((key, rec))

    best_name = None
    best_score = -10**9
    # para cada linha de CNPJ, pega 1..3 linhas imediatamente acima, no mesmo bloco
    for (b,p,ln), rec in candidate_lines:
        for offset in (1,2,3):
            prev_key = (b,p,ln - offset)
            if prev_key not in lines: continue
            prev = lines[prev_key]
            cand = _clean_company_line(" ".join(prev["words"]))
            if not cand or _is_bad_line(cand): continue
            sc = _score_company_line(cand)
            if sc > best_score:
                best_score, best_name = sc, cand

    # fallback: bloco acima de "DACTE" (procura linha "DACTE" e olha 3..6 acima)
    if not best_name:
        # acha primeira linha com DACTE
        dacte_lines = [(k,v) for k,v in lines.items() if "DACTE" in remover_acentos(" ".join(v["words"])).upper()]
        if dacte_lines:
            (b,p,ln), rec = sorted(dacte_lines, key=lambda kv: kv[1]["top"])[0]
            for offset in (1,2,3,4,5,6):
                prev_key = (b,p,ln - offset)
                if prev_key not in lines: continue
                prev = lines[prev_key]
                cand = _clean_company_line(" ".join(prev["words"]))
                if not cand or _is_bad_line(cand): continue
                sc = _score_company_line(cand)
                if sc > best_score:
                    best_score, best_name = sc, cand

    # fallback global: melhor linha longa no topo
    if not best_name:
        for (b,p,ln), rec in sorted(lines.items(), key=lambda kv: kv[1]["top"])[:25]:
            cand = _clean_company_line(" ".join(rec["words"]))
            if not cand or len(remover_acentos(cand)) < 8 or _is_bad_line(cand): continue
            sc = _score_company_line(cand)
            if sc > best_score:
                best_score, best_name = sc, cand

    return best_name

# ===== Núcleo =====
def extrair_meta_pagina(pagina: fitz.Page) -> Tuple[str, str, str]:
    # 1) tenta texto embutido (rápido)
    texto = pagina.get_text("text") or ""
    tipo_doc = identificar_tipo(texto)
    nome_emissor = "EMISSOR_DESCONHECIDO"
    numero_doc = "000"

    if tipo_doc == "CTE" and texto:
        for _, regras in MODELOS.items():
            if regras["regex_emissor"].search(texto):
                m_emp = regras["regex_emissor"].search(texto)
                if m_emp: nome_emissor = slugify(m_emp.group(1))
                m_num = regras["regex_cte"].search(texto)
                if m_num: numero_doc = str(int(m_num.group(1)))
                return ("CTE", nome_emissor, numero_doc)

    # 2) rasteriza + QR
    img = page_to_pil(pagina, dpi=300)
    img_p = preprocess(img)
    chave = None
    for payload in decode_qr_from_image(img_p):
        c = parse_chave_acesso_from_payload(payload)
        if c: chave = c; break
    cnpj14 = cnpj_from_chave(chave) if chave else None
    nct    = nct_from_chave(chave) if chave else None
    if chave and nct:
        tipo_doc = "CTE"; numero_doc = nct

    # 3) OCR (texto e TSV)
    ocr = ocr_text(img_p)
    data = ocr_data(img_p)
    if tipo_doc == "DESCONHECIDO":
        tipo_doc = identificar_tipo(ocr)

    nome_guess = guess_emissor_from_data(data, cnpj14) or ""
    if not nome_guess and ocr:
        # último recurso: heurística simples no texto corrido
        linhas = [l.strip() for l in ocr.splitlines() if l.strip()]
        for i,l in enumerate(linhas):
            if "CNPJ" in remover_acentos(l).upper():
                for j in range(max(0,i-3), i):
                    cand = _clean_company_line(linhas[j])
                    if cand and not _is_bad_line(cand):
                        nome_guess = cand; break
                if nome_guess: break

    nome_emissor = slugify(nome_guess) if nome_guess else "EMISSOR_DESCONHECIDO"
    return (tipo_doc, nome_emissor, numero_doc)

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
