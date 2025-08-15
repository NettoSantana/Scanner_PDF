import argparse
from pyzbar.pyzbar import decode, ZBarSymbol
from PIL import Image, ImageOps

def carregar_imagem(path: str) -> Image.Image:
    img = Image.open(path)
    if img.mode not in ("L", "LA", "RGB", "RGBA"):
        img = img.convert("RGB")
    return img

def tentar_decode(img: Image.Image):
    # 1) Direto, priorizando QR e códigos comuns
    res = decode(
        img,
        symbols=[
            ZBarSymbol.QRCODE,
            ZBarSymbol.CODE128,
            ZBarSymbol.EAN13,
            ZBarSymbol.EAN8,
            ZBarSymbol.CODE39,
            ZBarSymbol.ITF,
            ZBarSymbol.UPCA,
            ZBarSymbol.UPCE,
            ZBarSymbol.DATABAR,
            ZBarSymbol.DATABAR_EXP,
        ],
    )
    if res:
        return res

    # 2) Em escala de cinza
    res = decode(ImageOps.grayscale(img))
    if res:
        return res

    # 3) Rotacionando (90/180/270)
    for ang in (90, 180, 270):
        res = decode(img.rotate(ang, expand=True))
        if res:
            return res

    return []

def main():
    parser = argparse.ArgumentParser(description="Leitor de QR/código de barras")
    parser.add_argument("imagem", nargs="?", default="qrcode_teste.png", help="Caminho da imagem")
    args = parser.parse_args()

    img = carregar_imagem(args.imagem)
    resultados = tentar_decode(img)

    if not resultados:
        print("❌ Nenhum QR/código encontrado.")
        return

    for r in resultados:
        data = r.data.decode("utf-8", errors="replace")
        print(f"🔍 Tipo: {r.type} | Dados: {data}")
        if r.rect:
            x, y, w, h = r.rect
            print(f"   Caixa: x={x}, y={y}, w={w}, h={h}")

if __name__ == "__main__":
    main()
