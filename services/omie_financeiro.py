"""Converte a consulta do Omie no financeiro mostrado na obra. Valores em centavos.

Valor ausente na resposta fica None ("a confirmar"), nunca zero. Os campos dos títulos em
aberto ainda não foram validados com uma consulta real: a leitura fica isolada em
_valor_aberto_titulo para ajustar num só lugar.
"""
from services.omie_integracao import centavos, numero_ic, numeros_no_nome

CATEGORIA_MAT = '2.01.99'
CATEGORIAS_MO = ('2.01.97', '2.01.98')
GRUPOS = (('mat', 'MAT · materiais'), ('mo', 'MO / serviços · provisório'), ('outros', 'Outros gastos'))


def moeda(valor_centavos):
    if valor_centavos is None:
        return 'A confirmar'
    sinal = '-' if valor_centavos < 0 else ''
    inteiro, fracao = divmod(abs(valor_centavos), 100)
    return f"R$ {sinal}{inteiro:,}".replace(',', '.') + f',{fracao:02d}'


def grupo_categoria(codigo):
    codigo = (codigo or '').strip()
    if codigo == CATEGORIA_MAT:
        return 'mat'
    if codigo in CATEGORIAS_MO:
        return 'mo'
    return 'outros'


def _somar(a, b):
    return None if a is None or b is None else a + b


def _centavos_ou_none(valor):
    return None if valor is None else centavos(valor)


def _cancelado(linha):
    return (linha.get('detalhes', {}).get('cStatus') or '').upper() == 'CANCELADO'


def _valor_aberto_titulo(linha):
    """Provisório: saldo em aberto do título a pagar (campo a validar na primeira consulta real)."""
    return _centavos_ou_none(linha.get('resumo', {}).get('nValAberto'))


def montar_custos(dados):
    """Custos por categoria: pago = baixas do período (BXCP); a pagar = títulos em aberto (CP)."""
    descricoes = {r.get('cCodCategoria'): r.get('cDesCategoria') for r in dados.get('extrato', [])
                  if r.get('cCodCategoria') and r.get('cDesCategoria')}
    por_categoria = {}

    def categoria(codigo):
        codigo = (codigo or '').strip() or 'Sem categoria'
        return por_categoria.setdefault(codigo, {
            'codigo': codigo, 'descricao': descricoes.get(codigo, ''), 'grupo': grupo_categoria(codigo),
            'pago_centavos': 0, 'aberto_centavos': 0})

    series = dados.get('series', {})
    for linha in series.get('BXCP', []):
        if _cancelado(linha):
            continue
        item = categoria(linha['detalhes'].get('cCodCateg'))
        item['pago_centavos'] = _somar(item['pago_centavos'],
                                       _centavos_ou_none(linha.get('resumo', {}).get('nValLiquido')))
    for linha in series.get('CP', []):
        if _cancelado(linha):
            continue
        item = categoria(linha['detalhes'].get('cCodCateg'))
        item['aberto_centavos'] = _somar(item['aberto_centavos'], _valor_aberto_titulo(linha))
    return sorted(por_categoria.values(), key=lambda c: (-(c['pago_centavos'] or 0), c['codigo']))


def custos_mat_mo(custos):
    """Separação gerencial por categoria; serviços são MO provisória."""
    grupos = {k: {'pago': 0, 'aberto': 0} for k, _ in GRUPOS}
    for custo in custos:
        grupo = grupos[custo['grupo']]
        grupo['pago'] = _somar(grupo['pago'], custo['pago_centavos'])
        grupo['aberto'] = _somar(grupo['aberto'], custo['aberto_centavos'])
    return grupos


def totais_custos(custos):
    pago = aberto = 0
    for custo in custos:
        pago = _somar(pago, custo['pago_centavos'])
        aberto = _somar(aberto, custo['aberto_centavos'])
    return {'pago': pago, 'aberto': aberto}


def avisos_vinculo(obra, vinculo, dados=None):
    """Divergências entre o cadastro da obra e o projeto ligado. Não bloqueiam a consulta."""
    avisos = []
    numero = numero_ic(obra.get('contrato_ic'))
    if numero is None:
        avisos.append('A obra não tem IC cadastrado para conferir com o projeto do Omie.')
    elif numero not in numeros_no_nome(vinculo['nome_projeto']):
        avisos.append('O IC da obra não aparece no nome do projeto do Omie. Confira a ligação.')
    antes = numero_ic(vinculo.get('ic_na_confirmacao'))
    if antes is not None and numero is not None and antes != numero:
        avisos.append(f"O IC da obra mudou depois da ligação (era {vinculo['ic_na_confirmacao']}). Ligação a reconferir.")
    if dados:
        avisos.extend(a for a in dados.get('avisos', []) if 'renomeado' in a)
    return avisos


def resumo_obra(obra, situacao):
    """Dados do bloco do card. None quando a obra não está ligada ao Omie."""
    vinculo = situacao.get('vinculo')
    if not vinculo:
        return None
    lote = situacao.get('lote')
    resumo = {'vinculo': vinculo, 'lote': lote, 'erro': situacao.get('erro'),
              'avisos': avisos_vinculo(obra, vinculo, lote and lote['dados']), 'totais': None}
    if lote:
        resumo['totais'] = totais_custos(montar_custos(lote['dados']))
    return resumo
