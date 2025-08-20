# server.py
import os
import threading
from datetime import datetime
from flask import Flask, request, Response, send_from_directory, jsonify
from dotenv import load_dotenv
import requests

# processamento
import renomear_cte_mesma_pasta as proc

# WhatsApp (Twilio)
from twilio.rest import Client

load_dotenv()

def _default_dir(env_name, fallback):
    v = os.getenv(env_name)
    if v:
        return v
    if os.path.isdir("/data"):
        mapping = {
            "INPUT_DIR": "/data/entradas",
            "OUTPUT_DIR": "/data/renomeados",
            "PENDENTES_DIR": "/data/pendentes",
        }
        return mapping.get(env_name, fallback)
    return fallback

INPUT_DIR     = _default_dir("INPUT_DIR",     os.path.join(os.getcwd(), "entradas"))
OUTPUT_DIR    = _default_dir("OUTPUT_DIR",    os.path.join(os.getcwd(), "renomeados"))
PENDENTES_DIR = _default_dir("PENDENTES_DIR", os.path.join(os.getcwd(), "pendentes"))

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(PENDENTES_DIR, exist_ok=True)

# Credenciais Twilio
TWILIO_SID    = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM   = os.getenv("TWILIO_WHATSAPP_FROM")  # ex: whatsapp:+14155238886

# Base pública para links
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")

# Limpeza pós-envio
DELETE_OUTPUT_AFTER_SEND = (os.getenv("DELETE_OUTPUT_AFTER_SEND", "true").lower() == "true")
DELETE_DELAY_SECONDS     = int(os.getenv("DELETE_DELAY_SECONDS", "180"))

app = Flask(__name__)  # server:app

# ===== Sessões simples por número (menu 1/2) =====
from threading import Lock
SESSIONS = {}  # { from_number: {"pending": [filenames], "emissor": "1"|"2"|None} }
SESS_LOCK = Lock()

EMISSOR_CHOICES = {
    "1": "WANDER_PEREIRA_DE_MATOS",
    "2": "WASHINGTON_BALTAZAR_SOUZA_LIMA_ME",
}

MENU_TXT = (
    "Escolha o emissor deste lote:\n"
    "1) WANDER_PEREIRA_DE_MATOS\n"
    "2) WASHINGTON_BALTAZAR_SOUZA_LIMA_ME\n"
    "Responda com 1 ou 2."
)

def _twilio_client():
    if not (TWILIO_SID and TWILIO_TOKEN):
        return None
    try:
        return Client(TWILIO_SID, TWILIO_TOKEN)
    except Exception:
        return None

def _send_text_whatsapp(body, to_number):
    client = _twilio_client()
    if not (client and TWILIO_FROM and to_number):
        return
    try:
        client.messages.create(from_=TWILIO_FROM, to=to_number, body=body)
    except Exception as e:
        print(f"⚠️ Erro ao enviar texto WhatsApp: {e}")

def _send_media_whatsapp(urls, to_number):
    client = _twilio_client()
    if not (client and TWILIO_FROM and to_number):
        return
    first = True
    for u in urls:
        params = {"from_": TWILIO_FROM, "to": to_number, "media_url": [u]}
        if first:
            params["body"] = "✅ Processado. Segue o PDF."
        try:
            client.messages.create(**params)
        except Exception as e:
            print(f"⚠️ Erro ao enviar mídia: {e}")
        first = False

def _safe_remove(path):
    try:
        os.remove(path)
        print(f"🧹 Removido: {path}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Erro ao remover {path}: {e}")

def _schedule_delete(paths, delay):
    def _job():
        for p in paths:
            absp = os.path.abspath(p)
            if absp.startswith(os.path.abspath(OUTPUT_DIR)) or absp.startswith(os.path.abspath(PENDENTES_DIR)):
                _safe_remove(absp)
    threading.Timer(delay, _job).start()
    print(f"⏳ Limpeza agendada em {delay}s para {len(paths)} arquivo(s).")

@app.get("/health")
def health():
    return {"status": "ok"}, 200

def _compute_base_url(req):
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    root = (req.url_root or "").strip().rstrip("/")
    if root.startswith("http://") and ".railway.app" in root:
        root = "https://" + root[len("http://"):]
    return root

@app.get("/files")
def list_files():
    out_files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".pdf")])
    pen_files = sorted([f for f in os.listdir(PENDENTES_DIR) if f.lower().endswith(".pdf")])
    return jsonify({
        "output_dir": OUTPUT_DIR,
        "pendentes_dir": PENDENTES_DIR,
        "output_count": len(out_files),
        "pendentes_count": len(pen_files),
        "output_files": out_files,
        "pendentes_files": pen_files,
    }), 200

@app.get("/files/renomeados/<path:fname>")
def download_renomeado(fname):
    return send_from_directory(OUTPUT_DIR, fname, as_attachment=True, mimetype="application/pdf")

@app.get("/files/pendentes/<path:fname>")
def download_pendente(fname):
    return send_from_directory(PENDENTES_DIR, fname, as_attachment=True, mimetype="application/pdf")

# ===== Worker que processa já com o emissor escolhido =====
def _processar_e_notificar(salvos, to_number, base_url, emissor_id=None, emissor_nome=None):
    try:
        # fixa o emissor no módulo (se suportado) apenas durante este lote
        if hasattr(proc, "set_emissor_fixo_runtime"):
            if emissor_nome:
                proc.set_emissor_fixo_runtime(emissor_nome=emissor_nome)
            elif emissor_id in ("1", "2"):
                proc.set_emissor_fixo_runtime(emissor_id=emissor_id)

        caminhos_abs = [os.path.join(INPUT_DIR, n) for n in salvos]
        basenames = proc.processar_arquivos(caminhos_abs)

        links = [f"{base_url}/files/renomeados/{b}" for b in basenames]
        paths_abs = [os.path.join(OUTPUT_DIR, b) for b in basenames]

        if links:
            _send_media_whatsapp(links, to_number)
            if DELETE_OUTPUT_AFTER_SEND and paths_abs:
                _schedule_delete(paths_abs, DELETE_DELAY_SECONDS)
        else:
            print("ℹ️ Nada novo para enviar (sem renomeados gerados).")
    except Exception as e:
        print(f"⚠️ Falha no worker: {e}")
    finally:
        # reseta o emissor fixo no módulo para evitar vazar para próximo lote
        if hasattr(proc, "set_emissor_fixo_runtime"):
            try:
                proc.set_emissor_fixo_runtime()
            except Exception as e:
                print(f"⚠️ Falha ao resetar emissor runtime: {e}")

def _session_get_or_create(num):
    with SESS_LOCK:
        sess = SESSIONS.get(num)
        if not sess:
            sess = {"pending": [], "emissor": None}
            SESSIONS[num] = sess
        return sess

def _set_emissor(sess, choice):
    if choice in ("1","2"):
        sess["emissor"] = choice
        return True
    return False

# ===== Webhook Twilio =====
@app.post("/whatsapp")
def whatsapp_webhook():
    from_number = request.form.get("From", "")
    body_raw = request.form.get("Body", "") or ""
    body = body_raw.strip().lower()
    num_media = int(request.form.get("NumMedia", "0") or 0)

    base_url = _compute_base_url(request)
    sess = _session_get_or_create(from_number)

    # 1) Escolha recebida (sem mídia): processa o que estiver pendente e SEMPRE zera a escolha
    if num_media <= 0 and body in ("1","2"):
        _set_emissor(sess, body)
        pend = list(sess["pending"])
        sess["pending"].clear()
        if pend:
            _send_text_whatsapp(f"Ok, emissor: {EMISSOR_CHOICES[body]}. Processando {len(pend)} arquivo(s)…", from_number)
            # single-use: zera para forçar menu no próximo envio
            sess["emissor"] = None
            threading.Thread(
                target=_processar_e_notificar,
                args=(pend, from_number, base_url, body, None),
                daemon=True
            ).start()
            return Response("Processando.", 200)
        else:
            # nenhuma pendência: não mantém escolha; obriga novo menu no próximo envio
            sess["emissor"] = None
            _send_text_whatsapp("Escolha registrada. Envie os PDFs agora que eu vou perguntar novamente o emissor.", from_number)
            return Response("Aguardando PDFs.", 200)

    # 2) Recebimento de PDFs: SEMPRE exigir escolha a cada lote
    if num_media > 0:
        salvos = []
        for i in range(num_media):
            content_type = (request.form.get(f"MediaContentType{i}", "") or "").lower()
            media_url    = request.form.get(f"MediaUrl{i}", "") or ""
            if "pdf" not in content_type or not media_url:
                continue
            try:
                auth = (TWILIO_SID, TWILIO_TOKEN) if (TWILIO_SID and TWILIO_TOKEN) else None
                with requests.get(media_url, stream=True, timeout=30, auth=auth) as r:
                    r.raise_for_status()
                    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                    nome  = f"zap_{stamp}_{i+1}.pdf"
                    caminho = os.path.join(INPUT_DIR, nome)
                    with open(caminho, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    salvos.append(nome)
                    print(f"📥 PDF salvo de {from_number}: {nome}")
            except Exception as e:
                print(f"⚠️ Falha ao baixar mídia {i}: {e}")

        if not salvos:
            return Response("Nenhum PDF válido encontrado no envio.", 200)

        # Empilha e força perguntar SEMPRE (não usa escolha anterior)
        sess["pending"].extend(salvos)
        sess["emissor"] = None  # invalida qualquer escolha anterior
        _send_text_whatsapp(MENU_TXT, from_number)
        return Response("Escolha requerida.", 200)

    # 3) Comandos auxiliares
    if body in ("menu","opcoes","opções","emissor"):
        sess["emissor"] = None  # garante que vai perguntar
        _send_text_whatsapp(MENU_TXT, from_number)
        return Response("Menu enviado.", 200)
    if body in ("trocar","reset","alterar"):
        sess["emissor"] = None
        _send_text_whatsapp("Emissor limpo. " + MENU_TXT, from_number)
        return Response("Emissor resetado.", 200)

    return Response("Envie um PDF do CT-e. Após o envio, vou pedir para escolher 1 (Wander) ou 2 (Washington).", 200)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
