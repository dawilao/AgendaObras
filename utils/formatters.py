"""
Funções puras de formatação, conversão de datas e constantes de status.
Extraídas de agenda_obras.py e obras_helper.py — sem dependências de UI ou DB.
"""

import datetime
from typing import Union

# ========== Constantes de Status ========== #

STATUS_OPTIONS = ['Não Iniciada', 'Em Andamento', 'Atrasada', 'Concluída']

STATUS_VISUAL_EDICAO_OPTIONS = [
    'Não Iniciada',
    'Em Andamento',
    'Atrasada',
    'Pronta para concluir',
    'Concluído',
    'Concluída com Pendências',
]


# ========== Conversores de Data ========== #

def normalizar_valor_data(valor) -> str:
    """Normaliza valor de data para string (suporta tipos retornados pelo NiceGUI)."""
    if valor is None:
        return ''

    if isinstance(valor, datetime.datetime):
        return valor.strftime('%Y-%m-%d')

    if isinstance(valor, datetime.date):
        return valor.strftime('%Y-%m-%d')

    if isinstance(valor, (list, tuple)):
        if not valor:
            return ''
        valor = valor[0]

    if isinstance(valor, dict):
        valor = valor.get('from') or valor.get('to') or ''

    if not isinstance(valor, str):
        valor = str(valor)

    return valor.strip()


def converter_data_para_iso(data_str) -> str:
    """Converte data de qualquer formato para aaaa-mm-dd. Retorna '' se vazio."""
    data_str = normalizar_valor_data(data_str)
    if not data_str:
        return ''

    if '-' in data_str:
        try:
            datetime.datetime.strptime(data_str, '%Y-%m-%d')
            return data_str
        except ValueError:
            pass

    if '/' in data_str:
        try:
            dt = datetime.datetime.strptime(data_str, '%d/%m/%Y')
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            pass

    return data_str


def formatar_data_exibicao(data_str) -> str:
    """Converte data do banco (ISO ou BR) para dd/mm/aaaa para exibição."""
    data_str = normalizar_valor_data(data_str)
    if not data_str:
        return ''

    if '-' in data_str:
        try:
            dt = datetime.datetime.strptime(data_str, '%Y-%m-%d')
            return dt.strftime('%d/%m/%Y')
        except ValueError:
            pass

    if '/' in data_str:
        try:
            dt = datetime.datetime.strptime(data_str, '%d/%m/%Y')
            return dt.strftime('%d/%m/%Y')
        except ValueError:
            pass

    return data_str


# ========== Formatadores de Valor ========== #

def formatar_valor(valor: float) -> str:
    """Formata float para moeda brasileira: R$ 1.234,56"""
    try:
        return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return f"R$ {valor}"


# ========== Utilitários de Status ========== #

def datas_iguais_normalizadas(valor_antigo, valor_novo) -> bool:
    """Compara datas tratando None e string vazia como equivalentes."""
    return (valor_antigo or '').strip() == (valor_novo or '').strip()


def rotulo_alterar_medicoes(quantidade: int, habilitado: bool = True) -> str:
    """Retorna o rótulo do botão de configuração de medições."""
    if not habilitado:
        return 'Alterar medições'
    quantidade_normalizada = max(0, int(quantidade or 0))
    return f'Alterar medições ({quantidade_normalizada}/6)'


def status_edicao_para_banco(status: str) -> str:
    """Normaliza o valor do select de edição para o formato persistido no banco."""
    status_normalizado = (status or '').strip()
    if status_normalizado in {'Concluído', 'Pronta para concluir', 'Concluída com Pendências'}:
        return 'Concluída'
    return status_normalizado
