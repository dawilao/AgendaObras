"""ZIP fatiado sem descompactar: os trechos comprimidos grandes viram blobs próprios.

Revisões de projeto zipadas pela mesma ferramenta repetem os bytes das pranchas que
não mudaram; separá-los permite guardar cada trecho uma única vez. Nada é
descompactado, então ZIP bomb, caminhos maliciosos e ZIP com senha não importam.
"""
import io
import struct
import zipfile

LOCAL_HEADER = b'PK\x03\x04'
MIN_ZIP = 256 * 1024
MIN_MEMBER = 64 * 1024


def split(data):
    """Trechos cuja concatenação é exatamente `data`: (True, bytes) vira blob, (False, bytes)
    fica no manifesto. None quando não é um ZIP aproveitável."""
    if len(data) < MIN_ZIP or data[:4] != LOCAL_HEADER:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
    except Exception:  # Qualquer ZIP ilegível é guardado como veio.
        return None
    spans = []
    for info in infos:
        if info.compress_size < MIN_MEMBER:
            continue
        offset = info.header_offset
        header = data[offset:offset + 30]
        if len(header) < 30 or header[:4] != LOCAL_HEADER:
            return None
        name_len, extra_len = struct.unpack('<HH', header[26:30])
        start = offset + 30 + name_len + extra_len
        end = start + info.compress_size
        if end > len(data):
            return None
        spans.append((start, end))
    if not spans:
        return None
    parts, position = [], 0
    for start, end in sorted(spans):
        if start < position:
            return None
        if start > position:
            parts.append((False, data[position:start]))
        parts.append((True, data[start:end]))
        position = end
    if position < len(data):
        parts.append((False, data[position:]))
    return parts
