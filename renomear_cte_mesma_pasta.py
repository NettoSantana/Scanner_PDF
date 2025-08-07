import os
import re
import fitz  # PyMuPDF
from dotenv import load_dotenv

# Carrega variáveis do .env (se existir)
load_dotenv()

# ===== Raiz do projeto (portável: local/servidor) =====
# Se quiser forçar em produção, defina BASE_DIR no ambiente.
BASE_DIR = os.getenv("BASE_DIR") or os.path.dirname(os.path.abspath(__file__))

PASTA_ENTRADAS  = os.path.join(BASE_DIR, "entradas")
PASTA_SAIDA     = os.path.join(BASE_DIR, "renomeados")
PASTA_PENDENTES = os.path.join(BASE_DIR, "pendentes")

# Garante que as pastas existem
os.makedirs(PASTA_ENTRADAS, exist_ok=True)
os.makedirs(PASTA_SAIDA, exist_ok=True)
os.makedirs(PASTA_PENDENTES, exist_ok=True)

print("🔧 BASE_DIR:", BASE_DIR)
print("📂 PASTA_ENTRADAS:", PASTA_ENTRADAS)
print("📂 PASTA_SAIDA:", PASTA_SAIDA)
print("📂 PASTA_PENDENTES:", PASTA_PENDENTES)

# ===== Detecção de tipo =====
def identificar_tipo(texto: str) -> str:
    up = (texto or "").upper()
    if "CONHECIMENTO DE TRANSPORTE ELETRÔNICO" in up or "DACTE" in up:
        return "CTE"
    if "NOTA FISCAL ELETRÔNICA" in up or "NFS-E" in up or "NF-E" in up:
        return "NF"
    if "BOLETO" in up or "FICHA DE COMPENSAÇÃO" in up:
        return "BOLETO"
    return "DESCONHECIDO"

# ===== Modelos de CTE conhecidos =====
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

# ===== Utils =====
def slugify(nome: str) -> str:
    nome = re.sub(r'\W+', '_', (nome or '').strip())
    return re.sub(r'_+', '_', nome).strip('_') or 'DESCONHECIDO'

def nome_unico(caminho_base: str) -> str:
    """Se o arquivo existir, acrescenta __1, __2, ..."""
    if not os.path.exists(caminho_base):
        return caminho_base
    raiz, ext = os.path.splitext(caminho_base)
    i = 1
    while True:
        novo = f"{raiz}__{i}{ext}"
        if not os.path.exists(novo):
            return novo
        i += 1

def enviar_whatsapp(alerta_texto: str):
    """Envio opcional via Twilio. Suporta TWILIO_* antigo e novo."""
    sid    = os.getenv("TWILIO_SID")            or os.getenv("TWILIO_ACCOUNT_SID")
    token  = os.getenv("TWILIO_AUTH")           or os.getenv("TWILIO_AUTH_TOKEN")
    w_from = os.getenv("TWILIO_FROM")           or os.getenv("TWILIO_WHATSAPP_FROM")
    w_to   = os.getenv("TWILIO_TO")             or os.getenv("TWILIO_WHATSAPP_TO")
    if not (sid and token and w_from and w_to):
        return  # não configurado -> silencioso
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(from_=w_from, to=w_to, body=alerta_texto)
    except Exception as e:
        print(f"⚠️ Falha ao enviar WhatsApp (Twilio): {e}")

# ===== Execução =====
def processar():
    # Lista PDFs; se vazio, apenas loga (sem crash)
    try:
        pdfs = [f for f in os.listdir(PASTA_ENTRADAS) if f.lower().endswith('.pdf')]
    except FileNotFoundError:
        print("❌ Pasta de entradas não encontrada:", PASTA_ENTRADAS)
        return

    if not pdfs:
        print("ℹ️ Nenhum PDF em", PASTA_ENTRADAS, "- suba arquivos para processar.")
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
                        # Tenta casar com modelos conhecidos
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

                    # Monta nome final COM prefixo do arquivo original
                    nome_info = f"{slugify(nome_emissor)}_{tipo_doc}_{numero_doc}.pdf"
                    nome_final = f"{prefixo_original}__{nome_info}"

                    if tipo_doc != "CTE" or not modelo_usado:
                        print(f"⚠️ {('Tipo ' + tipo_doc) if tipo_doc!='CTE' else 'Modelo CTE desconhecido'} na página {i+1}. Enviado para pendentes.")
                        caminho_destino = nome_unico(os.path.join(PASTA_PENDENTES, nome_final))
                        nova_doc.save(caminho_destino)

                        # Salva texto extraído para facilitar criação de novo modelo
                        with open(f"{caminho_destino}.txt", "w", encoding="utf-8") as f:
                            f.write(texto)

                        enviar_whatsapp(f"⚠️ Documento pendente: {os.path.basename(caminho_destino)}")
                    else:
                        caminho_destino = nome_unico(os.path.join(PASTA_SAIDA, nome_final))
                        nova_doc.save(caminho_destino)
                        print(f"✅ Página {i+1} ({modelo_usado}) salva como: {os.path.basename(caminho_destino)}")

                    nova_doc.close()
        except Exception as e:
            print(f"⚠️ Erro ao processar {nome_arquivo}: {e}")

if __name__ == "__main__":
    processar()
