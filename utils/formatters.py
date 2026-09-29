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


def tempo_desde_data(data_str, hoje: datetime.date = None) -> str:
    """Distância entre a data e hoje em dias ('há 27 dias', 'hoje', 'em 3 dias'). Retorna '' se inválida."""
    try:
        data = datetime.date.fromisoformat(converter_data_para_iso(data_str))
    except ValueError:
        return ''
    dias = ((hoje or datetime.date.today()) - data).days
    if dias == 0:
        return 'hoje'
    n = abs(dias)
    texto = f'{n} dia{"s" if n != 1 else ""}'
    return f'há {texto}' if dias > 0 else f'em {texto}'


# ========== Formatadores de Valor ========== #

def formatar_valor(valor: float) -> str:
    """Formata float para moeda brasileira: R$ 1.234,56"""
    try:
        return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return f"R$ {valor}"


# ========== Regra do % Parceiro ========== #
# >>> REGRA PARCEIRO <<< — ponto único da base de cálculo do % Parceiro.
# Hoje o % incide sobre o Total da Obra (contrato + aditivo), e cada medição
# aplica o % sobre o valor medido inteiro. Para o % incidir só sobre o
# contrato, retorne valor_contrato em base_calculo_parceiro e, em
# calcular_split_medicao, aplique o % proporcionalmente (valor_contrato / total_obra).

def base_calculo_parceiro(valor_contrato, total_obra) -> float:
    """Valor sobre o qual o % Parceiro incide (ver REGRA PARCEIRO)."""
    return float(total_obra or valor_contrato or 0)


def calcular_valor_parceiro(valor_contrato, total_obra, percentual) -> float:
    """Valor total do parceiro na obra."""
    return round(base_calculo_parceiro(valor_contrato, total_obra) * float(percentual or 0) / 100, 2)


def calcular_split_medicao(valor_medido, percentual) -> tuple:
    """Divide o valor de uma medição em (parceiro, empresa)."""
    valor = float(valor_medido or 0)
    parceiro = round(valor * float(percentual or 0) / 100, 2)
    return parceiro, round(valor - parceiro, 2)


# ========== Medições ========== #

def competencias_medicoes(data_inicio: datetime.date, quantidade: int) -> list:
    """(ano, mês) de cada medição, mês a mês a partir do mês de início da obra."""
    competencias = []
    for i in range(max(0, int(quantidade or 0))):
        m = data_inicio.month + i
        competencias.append((data_inicio.year + (m - 1) // 12, (m - 1) % 12 + 1))
    return competencias


def previa_medicoes(data_inicio_iso: str, quantidade: int, quantidade_atual: int = 0) -> str:
    """Texto que antecipa quais competências serão criadas ao configurar as medições."""
    try:
        data_inicio = datetime.date.fromisoformat((data_inicio_iso or '').strip())
    except ValueError:
        return ''
    competencias = competencias_medicoes(data_inicio, quantidade)
    if not competencias:
        return ''

    def _fmt(ano_mes):
        return f'{ano_mes[1]:02d}/{ano_mes[0]}'

    if len(competencias) == 1:
        texto = f'Será criada a medição de {_fmt(competencias[0])}.'
    else:
        texto = f'Serão criadas as medições de {_fmt(competencias[0])} a {_fmt(competencias[-1])}.'
    if quantidade_atual and quantidade < quantidade_atual:
        texto += (f' Medições pendentes após {_fmt(competencias[-1])} serão removidas;'
                  ' as já concluídas são mantidas.')
    return texto


def resumo_valor_medicao(total_obra, ja_medido, valor) -> dict:
    """Situação da obra se o valor informado for lançado (saldo, % medido e estouro)."""
    total = float(total_obra or 0)
    medido = float(ja_medido or 0)
    novo = float(valor or 0)
    saldo = round(total - medido, 2)
    return {
        'saldo': saldo,
        'saldo_apos': round(saldo - novo, 2),
        'pct_apos': round((medido + novo) / total * 100, 2) if total > 0 else 0.0,
        'excede': total > 0 and round(novo - saldo, 2) > 0,
    }


# ========== Utilitários de Status ========== #

def datas_iguais_normalizadas(valor_antigo, valor_novo) -> bool:
    """Compara datas tratando None e string vazia como equivalentes."""
    return (valor_antigo or '').strip() == (valor_novo or '').strip()


def rotulo_alterar_medicoes(quantidade: int, habilitado: bool = True) -> str:
    """Retorna o rótulo do botão de configuração de medições."""
    if not habilitado:
        return 'Alterar medições'
    quantidade_normalizada = max(0, int(quantidade or 0))
    return f'Alterar medições ({quantidade_normalizada}/12)'


def status_edicao_para_banco(status: str) -> str:
    """Normaliza o valor do select de edição para o formato persistido no banco."""
    status_normalizado = (status or '').strip()
    if status_normalizado in {'Concluído', 'Pronta para concluir', 'Concluída com Pendências'}:
        return 'Concluída'
    return status_normalizado
