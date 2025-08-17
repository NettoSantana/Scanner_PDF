# server.py
import os
import threading
from datetime import datetime
from flask import Flask, request, Response, send_from_directory, jsonify
from dotenv import load_dotenv
import requests
from typing import List  # <<< Python 3.8: usar List

# processamento
import renomear_cte_mesma_pasta as proc

# opcional: reply no WhatsApp (anexos)
from twilio.rest import Client

load_dotenv()

# Pastas (se houver /data montado e vars não setadas, usa /data)
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

# Limpeza pós-envio (padrão: apagar depois de 180s)
DELETE_OUTPUT_AFTER_SEND = (os.getenv("DELETE_OUTPUT_AFTER_SEND", "true").lower() == "true")
DELETE_DELAY_SECONDS     = int(os.getenv("DELETE_DELAY_SECONDS", "180"))

app = Flask(__name__)  # server:app

@app.get("/health")
def health():
    return {"status": "ok"}, 200

# -------- Listagem / Download ----------
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

# -------- Envio WhatsApp ----------
def _send_media_whatsapp(urls, to_number: str):
    # Envia 1 PDF por mensagem (mais estável no WhatsApp/Twilio)
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    first = True
    for u in urls:
        client.messages.create(
            from_=TWILIO_FROM,
            to=to_number,
            body="✅ Processado. Segue o PDF." if first else None,
            media_url=[u],  # exatamente 1 mídia por mensagem
        )
        first = False

def _safe_remove(path: str):
    try:
        os.remove(path)
        print(f"🧹 Removido: {path}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"⚠️ Erro ao remover {path}: {e}")

def _schedule_delete(paths: List[str], delay: int):  # <<< aqui
    def _job():
        for p in paths:
            absp = os.path.abspath(p)
            # só remove o que estiver nas pastas de saída/pendentes
            if absp.startswith(os.path.abspath(OUTPUT_DIR)) or absp.startswith(os.path.abspath(PENDENTES_DIR)):
                _safe_remove(absp)
    threading.Timer(delay, _job).start()
    print(f"⏳ Limpeza agendada em {delay}s para {len(paths)} arquivo(s).")

# -------- Worker: processa e responde por WhatsApp ----------
def _processar_e_notificar(salvos, to_number: str, base_url: str):
    try:
        # snapshot antes de processar
        before = set(f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".pdf"))

        # processa tudo que está em INPUT_DIR (gera arquivos NOVOS sem prefixo)
        proc.processar()

        # diff: arquivos novos gerados
        after = set(f for f in os.listdir(OUTPUT_DIR) if f.lower().endswith(".pdf"))
        novos = sorted(after - before)

        links = [f"{base_url}/files/renomeados/{f}" for f in novos]
        paths_abs = [os.path.join(OUTPUT_DIR, f) for f in novos]

        if links and TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM and to_number:
            try:
                _send_media_whatsapp(links, to_number)
                print(f"📤 WhatsApp enviado para {to_number} com {len(links)} arquivo(s).")
                if DELETE_OUTPUT_AFTER_SEND and paths_abs:
                    _schedule_delete(paths_abs, DELETE_DELAY_SECONDS)
            except Exception as e:
                print(f"⚠️ Erro ao enviar mídias: {e}. Não vou apagar os arquivos.")
                # fallback texto (não apaga, pra não quebrar link)
                try:
                    client = Client(TWILIO_SID, TWILIO_TOKEN)
                    chunk = links[:10]
                    body = "✅ Processado.\n" + "\n".join(f"- {u}" for u in chunk)
                    if len(links) > 10:
                        body += f"\n(+{len(links)-10} arquivos, acesse /files)"
                    client.messages.create(from_=TWILIO_FROM, to=to_number, body=body)
                except Exception as e2:
                    print(f"⚠️ Falha também no fallback de links: {e2}")
        else:
            if not links:
                print("ℹ️ Nada novo para enviar por WhatsApp (sem arquivos gerados).")
            else:
                print("ℹ️ Variáveis TWILIO_* ausentes; não apago arquivos.")
    except Exception as e:
        print(f"⚠️ Falha no worker de processamento/notificação: {e}")

# -------- Webhook Twilio ----------
@app.post("/whatsapp")
def whatsapp_webhook():
    from_number = request.form.get("From", "")
    num_media = int(request.form.get("NumMedia", "0") or 0)

    if num_media <= 0:
        return Response("Envie um PDF do CT-e.", 200)

    base_url = request.url_root.rstrip("/")

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

    threading.Thread(target=_processar_e_notificar, args=(salvos, from_number, base_url), daemon=True).start()
    return Response(f"Recebido(s): {', '.join(salvos)}. Processamento iniciado.", 200)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
