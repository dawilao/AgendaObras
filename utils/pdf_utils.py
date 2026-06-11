import io
import os
from uuid import uuid4

from pypdf import PdfReader, PdfWriter

_MAGIC = b'%PDF'


def validar_pdf(dados: bytes) -> bool:
    return dados[:4] == _MAGIC


def processar_e_salvar_pdf(dados: bytes, pasta_destino: str) -> str:
    """Valida, comprime e salva PDF em disco. Retorna caminho absoluto."""
    if not validar_pdf(dados):
        raise ValueError("Arquivo não é um PDF válido")
    os.makedirs(pasta_destino, exist_ok=True)
    dados = _comprimir(dados)
    nome = f"pdf_{uuid4().hex}.pdf"
    caminho = os.path.join(pasta_destino, nome)
    with open(caminho, 'wb') as f:
        f.write(dados)
    return caminho


def _comprimir(dados: bytes) -> bytes:
    reader = PdfReader(io.BytesIO(dados))
    writer = PdfWriter()
    writer.append(reader)
    writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    for page in writer.pages:
        page.compress_content_streams()
    buf = io.BytesIO()
    writer.write(buf)
    compressed = buf.getvalue()
    return compressed if len(compressed) < len(dados) else dados
