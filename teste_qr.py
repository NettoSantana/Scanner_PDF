from PIL import Image
from pyzbar.pyzbar import decode

imagem = Image.open("imagens_extraidas/pagina_1.png")  # ou outra imagem com QR
decodificados = decode(imagem)

if decodificados:
    for obj in decodificados:
        print("✅ QR Code detectado:")
        print(obj.data.decode("utf-8"))
else:
    print("❌ Nenhum QR Code detectado.")
