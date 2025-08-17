import os
import threading
from datetime import datetime
from flask import Flask, request, Response, send_from_directory, jsonify
from dotenv import load_dotenv
import requests

# processamento
import renomear_cte_mesma_pasta as proc

load_dotenv()

# Pastas (funciona em Linux/Docker)
INPUT_DIR     = os.getenv("INPUT_DIR",     os.path.join(os.getcwd(), "entradas"))
OUTPUT_DIR    = os.getenv("OUTPUT_DIR",    os.path.join(os.getcwd(), "renomeados"))
PENDENTES_DIR = os.getenv("PENDENTES_DIR", os.path.join(os.getcwd(), "pendentes"))

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(PENDENTES_DIR, exist_ok=True)

# Credenciais p/ baixar mídia da Twilio (URLs exigem Basic Auth)
TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

app = Flask(__name__)

@app.get("/health")
def health():
    return {"status": "ok"}, 200

# ---- LISTAGEM/DOWNLOAD ----
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
    return send_from_directory(OUTPUT_DIR, fname, as_attachment=True)

@app.get("/files/pendentes/<path:fname>")
def download_pendente(fname):
    return send_from_directory(PENDENTES_DIR, fname, as_attachment=True)

# ---- WEBHOOK TWILIO ----
@app.post("/whatsapp")
def whatsapp_webhook():
    from_number = request.form.get("From", "")
    num_media = int(request.form.get("NumMedia", "0") or 0)

    if num_media <= 0:
        return Response("Envie um PDF do CT-e.", 200)

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

    # dispara o processamento em segundo plano (não bloqueia webhook)
    threading.Thread(target=proc.processar, daemon=True).start()
    return Response(f"Recebido(s): {', '.join(salvos)}. Processamento iniciado.", 200)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
