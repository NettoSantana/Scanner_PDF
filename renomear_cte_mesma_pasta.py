# renomear_cte_mesma_pasta.py
import os, re, sys, shutil, unicodedata, subprocess, argparse, statistics, json
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

# ===== Parâmetros de OCR por ENV =====
def _as_int(env, default):
    try:
        return int(os.getenv(env, str(default)))
    except Exception:
        return default
OCR_DPI   = _as_int("OCR_DPI", 300)
FORCE_OCR = (os.getenv("FORCE_OCR", "false").lower() == "true")

# ===== Modo Emissor Fixo =====
EMISSOR_CHOICES = {
    "1": "WANDER_PEREIRA_DE_MATOS",
    "2": "WASHINGTON_BALTAZAR_SOUZA_LIMA_ME",
}
EMISSOR_FIXO_ID   = (os.getenv("EMISSOR_FIXO_ID") or "").strip() or None
EMISSOR_FIXO_NAME = (os.getenv("EMISSOR_FIXO_NAME") or "").strip() or None

def remover_acentos(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii","ignore").decode("ascii")

def slugify(nome: str) -> str:
    nome = remover_acentos((nome or "").strip())
    nome = re.sub(r"\b\d{2,}\b", " ", nome)
    nome = re.sub(r"\s{2,}", " ", nome).strip()
    nome = re.sub(r"\W+", "_", nome)
    nome = re.sub(r"_+", "_", nome).strip("_")
    return nome or "DESCONHECIDO"

def _resolve_emissor_fixo() -> Optional[str]:
    if EMISSOR_FIXO_NAME:
        return slugify(EMISSOR_FIXO_NAME)
    if EMISSOR_FIXO_ID and EMISSOR_FIXO_ID in EMISSOR_CHOICES:
        return slugify(EMISSOR_CHOICES[EMISSOR_FIXO_ID])
    return None

EMISSOR_FIXO = _resolve_emissor_fixo()

print("🔧 PASTA_ENTRADAS:", PASTA_ENTRADAS)
print("📂 PASTA_SAIDA:", PASTA_SAIDA)
print("📂 PASTA_PENDENTES:", PASTA_PENDENTES)
print("📦 PASTA_PROCESSADOS:", PASTA_PROCESSADOS)
print("📝 OUTPUT_OVERWRITE:", OUTPUT_OVERWRITE)
print("⚙️ INPUT_DISPOSITION:", INPUT_DISPOSITION)
print("🖨️ OCR_DPI:", OCR_DPI)
print("🧲 FORCE_OCR:", FORCE_OCR)
print("🏷️ MODO:", "fixed" if EMISSOR_FIXO else "auto", "— emissor_fixo=", EMISSOR_FIXO or "-")

# ===== Mapa CNPJ → Nome canônico (usado só no modo auto) =====
def _load_cnpj_canon() -> Dict[str, str]:
    d: Dict[str, str] = {}
    raw = (os.getenv("CNPJ_CANON_JSON") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            for k, v in parsed.items():
                kdig = re.sub(r"\D+", "", str(k))
                if kdig:
                    d[kdig] = str(v).strip()
        except Exception as e:
            print(f"⚠️ CNPJ_CANON_JSON inválido: {e}")
    INLINE = {
        # "12512889000154": "WASHINGTON_BALTAZAR_SOUZA_LIMA_ME",
        # "20263922000107": "WANDER_PEREIRA_DE_MATOS",
    }
    d.update(INLINE)
    return d

CNPJ_CANON: Dict[str, str] = _load_cnpj_canon()
if CNPJ_CANON:
    print(f"🔒 CNPJ_CANON carregado ({len(CNPJ_CANON)} entr.)")

# ===== Util =====
NEG_TOKENS = (
    # layout/papelada
    "CONHECIMENT", "DOCUMENTO AUXILIAR", "DACTE", "CHAVE", "ACESSO", "PROTOC",
    "RECEITA", "FISCO", "DESTINAT", "REMET", "TOMADOR", "QRCODE", "CONSULTE",
    "TIPO DO CT", "TIPO DO SERVI", "INICIO DA PRESTAC", "TERMINO DA PRESTAC",
    "DATA E HORA", "MODELO", "SERIE", "NUMERO", "N PROTOCOLO", "PAGINA",
    # endereço
    "MUNICIPIO", "CEP", "ENDERECO", "ENDEREÇO", "UF", "BAIRRO", "SALA",
    "AVENIDA", "AV ", "AV.", "RUA", "R.", "RODOVIA", "ROD.", "BR-", "BA-", "KM", "LOTE", "QUADRA",
    # canhoto
    "DECLARO", "RECEBI", "VOLUMES", "CANHOTO", "ASSINATURA", "CARIMBO", "ENTREGA", "COMPROVANTE"
)
ROLE_TOKENS = ("EXPEDIDOR", "REMETENTE", "DESTINAT", "RECEBEDOR", "EMBARCADOR")
PREF_TOKENS = (" LTDA", " S/A", " SA ", " ME ", " EPP", " MEI", " TRANSPORT", " LOGIST", " COMERC", " INDUSTR", " SERVI", " DISTRIB", " TRANS ")

def identificar_tipo(texto: str) -> str:
    up = remover_acentos(texto).upper()
    if "DACTE" in up or "CONHECIMENTO DE TRANSPORTE" in up: return "CTE"
    if "NOTA FISCAL" in up or "NF-E" in up or "NFS-E" in up: return "NF"
    if "BOLETO" in up or "FICHA DE COMPENSAC" in up:        return "BOLETO"
    return "DESCONHECIDO"

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
def page_to_pil(page: fitz.Page, dpi: Optional[int] = None) -> Image.Image:
    d = dpi or OCR_DPI
    mat = fitz.Matrix(d/72.0, d/72.0)
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

# ===== OCR =====
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

# ===== Heurísticas =====
def _is_bad_line(s: str) -> bool:
    u = remover_acentos(s).upper()
    if sum(c.isdigit() for c in u) > max(2, len(u)//4):
        return True
    return any(tok in u for tok in NEG_TOKENS)

def _looks_like_address(s: str) -> bool:
    u = remover_acentos(s).upper()
    if any(tok in u for tok in ("AVENIDA", "AV ", "AV.", "RUA", "R.", "RODOVIA", "ROD.", "BR-", "BA-", "KM", "CEP", "BAIRRO", "SALA", "LOTE", "QUADRA")):
        return True
    if re.search(r"\b\d{2,5}\b", u) and ("CEP" in u or "RUA" in u or "AV" in u or "KM" in u):
        return True
    return False

def _clean_company_line(s: str) -> str:
    s = s.strip(" :.-\t")
    s = re.sub(r"^(RAZAO\s+SOCIAL|RAZAO|EMITENTE|EMISSOR|PRESTADOR(?:\s+DE\s+SERVI[ÇC]O)?|EMPRESA)\s*[:\-]*\s*", "", s, flags=re.I)
    cut_regex = r"\b(" + "|".join(list(ROLE_TOKENS) + ["MUNICIPIO", "CEP", "ENDERECO", "ENDEREÇO", "UF"]) + r")\b"
    s = re.split(cut_regex, remover_acentos(s), maxsplit=1, flags=re.I)[0]
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

def _score_company_line(s: str) -> int:
    u = remover_acentos(s).upper()
    score = len(u)
    for t in PREF_TOKENS:
        if t in u: score += 25
    if _is_bad_line(u) or _looks_like_address(u): score -= 200
    if "DECLARO" in u or "RECEBI" in u or "VOLUMES" in u: score -= 300
    return score

def guess_emissor_from_data(data: Dict[str, Any], cnpj14: Optional[str]) -> Optional[str]:
    n = len(data.get("text", []))
    if n == 0: return None

    # monta linhas por (block, par, line)
    lines: Dict[Tuple[int,int,int], Dict[str, Any]] = {}
    page_h = 0
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt: continue
        conf_raw = str(data.get("conf", ["-1"])[i])
        try: conf = int(float(conf_raw))
        except: conf = -1
        if conf < 35: continue
        b = int(data.get("block_num", [0])[i] or 0)
        p = int(data.get("par_num", [0])[i] or 0)
        ln = int(data.get("line_num", [0])[i] or 0)
        key = (b,p,ln)
        rec = lines.setdefault(key, {"words": [], "xs": [], "left": 10**9, "right": -1, "top": 10**9, "bottom": -1, "block": b})
        left = int(data.get("left", [0])[i] or 0)
        width = int(data.get("width", [0])[i] or 0)
        top = int(data.get("top", [0])[i] or 0)
        h   = int(data.get("height", [0])[i] or 0)
        x_center = left + width/2.0
        rec["words"].append(txt)
        rec["xs"].append(x_center)
        rec["left"] = min(rec["left"], left)
        rec["right"] = max(rec["right"], left + width)
        rec["top"] = min(rec["top"], top)
        rec["bottom"] = max(rec["bottom"], top+h)
        page_h = max(page_h, rec["bottom"])

    # âncoras
    dacte_top = None
    label_blocks: set[int] = set()
    for (b,p,ln), rec in lines.items():
        uline = remover_acentos(" ".join(rec["words"])).upper()
        if "DACTE" in uline:
            if dacte_top is None or rec["top"] < dacte_top:
                dacte_top = rec["top"]
        if any(tok in uline for tok in ("EMITENTE", "EMISSOR", "PRESTADOR", "TRANSPORTADOR")):
            label_blocks.add(b)

    # CNPJs detectados
    def _fmt_cnpj(c):
        if not c or len(c)!=14: return None
        return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"
    cnpj_fmt = _fmt_cnpj(cnpj14)

    candidates = []
    for key, rec in lines.items():
        line_text = " ".join(rec["words"])
        u = remover_acentos(line_text).upper()
        if "CNPJ" in u or (cnpj14 and cnpj14 in _digits_only(u)) or (cnpj_fmt and cnpj_fmt in u):
            candidates.append((key, rec))

    if not candidates:
        return None

    by_label = [(k,r) for (k,r) in candidates if r.get("block") in label_blocks]
    if by_label:
        candidates = by_label

    candidates.sort(key=lambda kv: kv[1]["top"])
    if dacte_top is not None:
        near = [kv for kv in candidates if kv[1]["top"] <= dacte_top + 220]
        if near:
            candidates = near

    top_half = [kv for kv in candidates if kv[1]["top"] <= page_h * 0.60]
    if top_half:
        candidates = top_half

    (b,p,ln), cnpj_rec = candidates[0]
    cnpj_x_med = statistics.median(cnpj_rec["xs"]) if cnpj_rec["xs"] else (cnpj_rec["left"] + cnpj_rec["right"]) / 2.0

    best_name = None
    best_score = -10**9

    for offset in (1,2,3,4,5):
        prev_key = (b,p,ln - offset)
        prev = lines.get(prev_key)
        if not prev: continue
        if prev["top"] > page_h * 0.60:  # descarta rodapé/canhoto
            continue
        words_filtered = [w for w,x in zip(prev["words"], prev["xs"]) if x <= cnpj_x_med + 40]
        cand = _clean_company_line(" ".join(words_filtered)) if words_filtered else _clean_company_line(" ".join(prev["words"]))
        if not cand: continue
        if _is_bad_line(cand) or _looks_like_address(cand): continue
        sc = _score_company_line(cand)
        if sc > best_score:
            best_score, best_name = sc, cand

    if not best_name:
        cutoff = page_h * 0.30
        for (kb,kp,kl), rec in sorted(lines.items(), key=lambda kv: kv[1]["top"]):
            if rec["top"] > cutoff: break
            cand = _clean_company_line(" ".join(rec["words"]))
            if not cand or len(remover_acentos(cand)) < 8: continue
            if _is_bad_line(cand) or _looks_like_address(cand): continue
            sc = _score_company_line(cand)
            if sc > best_score:
                best_score, best_name = sc, cand

    return best_name

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
    # 1) Texto embutido (para número via modelos) — nome pode ser ignorado se modo fixo
    texto = pagina.get_text("text") or ""
    tipo_doc = identificar_tipo(texto)
    has_text = bool(texto.strip())
    numero_doc = "000"
    nome_emissor_auto = "EMISSOR_DESCONHECIDO"

    mode = "fixed" if EMISSOR_FIXO else "auto"
    print(f"🧭 Estratégia: mode={mode} has_text={has_text} force_ocr={FORCE_OCR}")

    # Se texto embutido e bater com modelos, extrai NÚMERO (nome só se auto)
    if tipo_doc == "CTE" and has_text:
        for _, regras in MODELOS.items():
            if regras["regex_cte"].search(texto) or regras["regex_emissor"].search(texto):
                m_num = regras["regex_cte"].search(texto)
                if m_num:
                    numero_doc = str(int(m_num.group(1)))
                if not EMISSOR_FIXO:
                    m_emp = regras["regex_emissor"].search(texto)
                    if m_emp:
                        nome_emissor_auto = slugify(m_emp.group(1))
                print("→ Caminho: TEXT-EMBUTIDO/MODELO (número coletado)")
                # não retornamos ainda: ainda tentaremos QR pra validar número

    # 2) Raster + QR para número (prioritário)
    img = page_to_pil(pagina, dpi=OCR_DPI)
    img_p = preprocess(img)
    chave = None
    for payload in decode_qr_from_image(img_p):
        c = parse_chave_acesso_from_payload(payload)
        if c: chave = c; break
    nct = nct_from_chave(chave) if chave else None
    if nct:
        numero_doc = nct
        tipo_doc = "CTE"

    # 3) Se ainda sem número, OCR texto e tenta heurística secundária (auto) — nome só se auto
    if numero_doc == "000":
        ocr = ocr_text(img_p)
        if tipo_doc == "DESCONHECIDO":
            tipo_doc = identificar_tipo(ocr)
        if not EMISSOR_FIXO:
            data = ocr_data(img_p)
            nome_guess = guess_emissor_from_data(data, cnpj_from_chave(chave) if chave else None) or ""
            if not nome_guess and ocr:
                linhas = [l.strip() for l in ocr.splitlines() if l.strip()]
                for i,l in enumerate(linhas):
                    if "CNPJ" in remover_acentos(l).upper():
                        for j in range(max(0,i-3), i):
                            cand = _clean_company_line(linhas[j])
                            if cand and not _is_bad_line(cand) and not _looks_like_address(cand):
                                nome_guess = cand; break
                        if nome_guess: break
            nome_emissor_auto = slugify(nome_guess) if nome_guess else nome_emissor_auto

    # 4) Decide o nome conforme modo
    if EMISSOR_FIXO:
        nome_emissor = EMISSOR_FIXO
        fonte_nome = "fixed"
    else:
        # modo auto: tenta CNPJ canônico pelo QR
        cnpj14 = cnpj_from_chave(chave) if chave else None
        nome_canon = CNPJ_CANON.get(cnpj14) if cnpj14 else None
        if nome_canon:
            nome_emissor = slugify(nome_canon); fonte_nome = "canon"
        else:
            nome_emissor = nome_emissor_auto; fonte_nome = "ocr"
    print(f"→ Nome: {nome_emissor} (fonte={fonte_nome}); nCT={numero_doc}")

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
    # Novo: modo emissor fixo
    p.add_argument("--emissor-id", choices=list(EMISSOR_CHOICES.keys()))
    p.add_argument("--emissor-fixo", help="Nome canônico do emissor para o lote (sobrepõe emissor-id)")
    a = p.parse_args()

    # aplica CLI sobre env
    if a.emissor_fixo:
        EMISSOR_FIXO_NAME = a.emissor_fixo
        EMISSOR_FIXO_ID = None
    elif a.emissor_id:
        EMISSOR_FIXO_ID = a.emissor_id
        EMISSOR_FIXO_NAME = None
    # recalcula emissor fixo global
    EMISSOR_FIXO = _resolve_emissor_fixo()

    PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES, PASTA_PROCESSADOS = a.input, a.output, a.pendentes, a.processed
    INPUT_DISPOSITION, OUTPUT_OVERWRITE = a.disposition, a.overwrite
    for pasta in (PASTA_ENTRADAS, PASTA_SAIDA, PASTA_PENDENTES, PASTA_PROCESSADOS):
        os.makedirs(pasta, exist_ok=True)
    processar()
