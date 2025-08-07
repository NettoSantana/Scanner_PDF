# Projeto ScannerOCR

Este projeto realiza o reconhecimento de texto (OCR) em arquivos PDF com múltiplas páginas, focando inicialmente em Notas Fiscais (NF).

## Estrutura de pastas:

- entradas/ → Onde o cliente coloca o arquivo PDF de entrada (ex: entradas.pdf)
- paginas_renomeadas/ → PDFs renomeados e separados por documento detectado
- imagens_extraidas/ → Imagens temporárias das páginas (usadas para OCR)
- logs/ → Arquivos de log ou falha (em breve)
- ferramentas/ → Scripts ou funções reutilizáveis
- teste_ocr_nf.py → Script principal para rodar o OCR de Nota Fiscal

## Fluxo atual:

1. O cliente envia um único tipo de documento por vez (somente NFs nesta etapa)
2. O PDF é colocado em `/entradas/entradas.pdf`
3. O sistema detecta e agrupa páginas da mesma NF
4. Extrai o nome do fornecedor e o número da nota
5. Gera arquivos no formato:
   FORNECEDOR_NF_NUMERO.pdf
6. Os arquivos são salvos em `/paginas_renomeadas/`

## Em desenvolvimento:
- Detecção de outros tipos: CTE, Boletos
- Escolha automática ou via menu de tipo de documento
- Logs de falhas e relatórios

## Rodar o sistema:
```bash
python teste_ocr_nf.py
