# -------- Worker: processa e RESPONDE com ANEXOS no WhatsApp ----------
def _links_por_prefixo(base_url: str, prefixo: str):
    files = sorted(
        f for f in os.listdir(OUTPUT_DIR)
        if f.lower().endswith(".pdf") and f.startswith(prefixo + "__")
    )
    return [f"{base_url}/files/renomeados/{f}" for f in files]

def _send_media_whatsapp(urls, to_number: str):
    # Twilio permite até 10 mídias por mensagem
    client = Client(TWILIO_SID, TWILIO_TOKEN)
    for i in range(0, len(urls), 10):
        chunk = urls[i:i+10]
        client.messages.create(
            from_=TWILIO_FROM,
            to=to_number,
            body="✅ Processado. Seguem os PDFs." if i == 0 else None,
            media_url=chunk,
        )

def _processar_e_notificar(salvos, to_number: str, base_url: str):
    try:
        proc.processar()  # processa tudo que está em INPUT_DIR

        # Links dos PDFs gerados a partir destes arquivos
        links = []
        for nome in salvos:
            prefixo = os.path.splitext(nome)[0]
            links.extend(_links_por_prefixo(base_url, prefixo))

        if links and TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM and to_number:
            try:
                _send_media_whatsapp(links, to_number)
                print(f"📤 WhatsApp enviado para {to_number} com {len(links)} anexo(s).")
            except Exception as e:
                # fallback: manda os links em texto se der erro no envio de mídia
                print(f"⚠️ Erro ao enviar mídias: {e}. Enviando links em texto…")
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
                print("ℹ️ Nada para enviar por WhatsApp (sem links).")
            else:
                print("ℹ️ Variáveis TWILIO_* ausentes; pulo resposta pelo WhatsApp.")
    except Exception as e:
        print(f"⚠️ Falha no worker de processamento/notificação: {e}")
