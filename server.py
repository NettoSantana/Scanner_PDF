import os
from datetime import datetime
from flask import Flask, request, Response
from dotenv import load_dotenv
import requests

load_dotenv()

# Pasta de entrada (compatível com Linux/Docker)
INPUT_DIR = os.getenv("INPUT_DIR", os.path.join(os.getcwd(), "entradas"))
os.makedirs(INPUT_DIR, exist_ok=True)

# Credenciais para baixar mídia da Twilio (URLs exigem Basic Auth)
TWILIO_SID   = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

app = Flask(__name__)

@app.get("/health")
def health():
    return {"status": "ok"}, 200

@app.post("/whatsapp")
def whatsapp_webhook():
    from_number = request.form.get("From", "")
    num_media = int(request.form.get("NumMedia", "0") or 0)

    if num_media <= 0:
        return Response("Envie um PDF do CT-e.", 200)

    salvos = []
    for i in range(num_media):
        content_type = request.form.get(f"MediaContentType{i}", "") or ""
        media_url    = request.form.get(f"MediaUrl{i}", "") or ""
        if "pdf" not in content_type.lower() or not media_url:
            continue

        try:
            # Auth só se tivermos SID/TOKEN; senão tenta sem (pode falhar)
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

    if salvos:
        # Opcional: chamar processamento aqui (deixe comentado se preferir fila/cron)
        # import renomear_cte_mesma_pasta as proc
        # proc.processar()

        return Response(f"Recebido(s): {', '.join(salvos)}. Processamento em fila.", 200)
    else:
        return Response("Nenhum PDF válido encontrado no envio.", 200)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
