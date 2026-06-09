import os
from io import BytesIO
from uuid import uuid4

from PIL import Image

_MAX_LADO = 1600
_QUALIDADE = 82


def processar_e_salvar_imagem(dados: bytes, pasta_destino: str) -> str:
    """
    Comprime e salva imagem em disco. Retorna o caminho absoluto do arquivo salvo.
    Redimensiona se o lado maior ultrapassar 1600px. Salva sempre como JPEG quality=82.
    """
    os.makedirs(pasta_destino, exist_ok=True)

    img = Image.open(BytesIO(dados))

    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    largura, altura = img.size
    if max(largura, altura) > _MAX_LADO:
        fator = _MAX_LADO / max(largura, altura)
        novo_tamanho = (int(largura * fator), int(altura * fator))
        img = img.resize(novo_tamanho, Image.LANCZOS)

    nome_arquivo = uuid4().hex + '.jpg'
    caminho = os.path.join(pasta_destino, nome_arquivo)
    img.save(caminho, format='JPEG', quality=_QUALIDADE, optimize=True)

    return caminho
