from pyzbar.pyzbar import decode
from PIL import Image

imagem = Image.open("qrcode_teste.png")  # coloque uma imagem com QR ou código de barras aqui
resultado = decode(imagem)

for r in resultado:
    print("🔍 Dados encontrados:", r.data.decode("utf-8"))
