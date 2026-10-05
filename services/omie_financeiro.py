"""Converte a consulta do Omie no financeiro mostrado na obra. Valores em centavos.

Valor ausente na resposta fica None ("a confirmar"), nunca zero. Os campos dos títulos em
aberto e das notas ainda não foram validados com uma consulta real: a leitura fica isolada em
_valor_aberto_titulo e _valores_nota para ajustar num só lugar.
"""
import csv
import io
from datetime import date, datetime

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


# ---------------------------------------------------------------------------
# Recebimento e saldos
# ---------------------------------------------------------------------------

def _valores_nota(linha):
    """Provisório: campos das NFs a validar na primeira consulta real (resposta do Lucas, 05/10/2026).

    Bruto = valor do título; recebido e aberto líquidos do bloco resumo. As retenções podem existir,
    mas o campo ainda não foi identificado: ficam "a confirmar", nunca "sem retenção".
    """
    detalhes, resumo = linha.get('detalhes', {}), linha.get('resumo', {})
    return {'bruto_centavos': _centavos_ou_none(detalhes.get('nValorTitulo')),
            'retencoes_centavos': None,
            'recebido_centavos': _centavos_ou_none(resumo.get('nValPago')),
            'aberto_centavos': _centavos_ou_none(resumo.get('nValAberto'))}


def situacao_nota(nota):
    recebido, aberto = nota['recebido_centavos'], nota['aberto_centavos']
    if recebido is None or aberto is None:
        return 'A confirmar'
    if aberto == 0 and recebido > 0:
        return 'Recebida'
    if recebido > 0:
        return 'Recebida em parte'
    return 'Em aberto'


def montar_notas(dados):
    """NFs da obra (títulos a receber do projeto). None quando o Omie não trouxe nenhuma: não é zero."""
    linhas = [l for l in dados.get('series', {}).get('CR', []) if not _cancelado(l)]
    if not linhas:
        return None
    notas, vistos = [], set()
    for linha in linhas:
        detalhes = linha.get('detalhes', {})
        titulo = detalhes.get('nCodTitulo')
        if titulo is not None:
            if titulo in vistos:
                continue
            vistos.add(titulo)
        nf = str(detalhes.get('cNumDocFiscal') or '').strip()
        nota = {'titulo': titulo, 'nf': nf or f'Título {titulo}', 'parcela': detalhes.get('cNumParcela') or '',
                'vencimento': detalhes.get('dDtVenc') or '', **_valores_nota(linha)}
        nota['situacao'] = situacao_nota(nota)
        notas.append(nota)
    return sorted(notas, key=lambda n: (n['nf'], n['parcela']))


def _soma(valores):
    total = 0
    for valor in valores:
        total = _somar(total, valor)
    return total


def _menos(a, b):
    return None if a is None or b is None else a - b


def valor_obra_centavos(obra):
    """Total da Obra do cadastro (contrato + aditivo). Sem valor → None."""
    try:
        valor = float(obra.get('total_obra') or 0)
    except (TypeError, ValueError):
        return None
    return round(valor * 100) if valor > 0 else None


def indicadores(custos, notas, valor_obra):
    totais = totais_custos(custos)
    resultado = {'custos_pagos': totais['pago'], 'custos_abertos': totais['aberto'], 'valor_obra': valor_obra,
                 'recebido': None, 'recebido_bruto': None, 'faturado': None, 'faturado_aberto': None}
    if notas is not None:
        recebidas = [n for n in notas if (n['recebido_centavos'] or 0) > 0]
        resultado.update(
            recebido=_soma(n['recebido_centavos'] for n in notas),
            faturado=_soma(n['bruto_centavos'] for n in notas),
            faturado_aberto=_soma(n['aberto_centavos'] for n in notas),
            # Bruto só é atribuível quando nenhuma nota foi recebida em parte.
            recebido_bruto=(None if any(n['situacao'] != 'Recebida' for n in recebidas)
                            else _soma(n['bruto_centavos'] for n in recebidas)))
    resultado['saldo_caixa'] = _menos(resultado['recebido'], resultado['custos_pagos'])
    resultado['saldo_contratual'] = _menos(valor_obra, resultado['recebido'])
    return resultado


def financeiro_obra(obra, dados):
    """Custos, notas e indicadores de uma consulta."""
    custos = montar_custos(dados)
    notas = montar_notas(dados)
    return {'custos': custos, 'notas': notas, 'indicadores': indicadores(custos, notas, valor_obra_centavos(obra))}


# ---------------------------------------------------------------------------
# O que mudou desde a consulta anterior
# ---------------------------------------------------------------------------

def _dia_consulta(iso):
    try:
        return datetime.fromisoformat(iso).astimezone().date()
    except (TypeError, ValueError):
        return None


def _dia_br(texto):
    try:
        return datetime.strptime(texto, '%d/%m/%Y').date()
    except (TypeError, ValueError):
        return None


def diferencas(anterior, novo, obra=None):
    """Compara duas consultas válidas (lotes com 'dados' e 'consultado_em'). None sem a anterior."""
    if not anterior or not novo or not anterior.get('dados') or not novo.get('dados'):
        return None
    antes, agora = anterior['dados'], novo['dados']
    obra = obra or {}

    baixas_antes = {l['detalhes'].get('nCodBaixa') for l in antes.get('series', {}).get('BXCP', [])}
    novas = [l for l in agora.get('series', {}).get('BXCP', [])
             if not _cancelado(l) and l['detalhes'].get('nCodBaixa') not in baixas_antes]

    notas_antes = {n['titulo']: n for n in montar_notas(antes) or []}
    notas_agora = montar_notas(agora) or []
    recebidas = [n['nf'] for n in notas_agora if n['situacao'] == 'Recebida'
                 and n['titulo'] in notas_antes and notas_antes[n['titulo']]['situacao'] != 'Recebida']
    notas_novas = [n['nf'] for n in notas_agora if n['titulo'] not in notas_antes]

    desde, ate = _dia_consulta(anterior['consultado_em']), _dia_consulta(novo['consultado_em'])
    vencidos = []
    if desde and ate:
        for linha in agora.get('series', {}).get('CP', []):
            vencimento = _dia_br(linha['detalhes'].get('dDtVenc'))
            aberto = _valor_aberto_titulo(linha)
            if not _cancelado(linha) and vencimento and desde <= vencimento < ate and aberto:
                vencidos.append(aberto)

    fin_antes, fin_agora = financeiro_obra(obra, antes), financeiro_obra(obra, agora)
    return {
        'desde': anterior['consultado_em'],
        'pagamentos': {'quantidade': len(novas),
                       'centavos': _soma(_centavos_ou_none(l.get('resumo', {}).get('nValLiquido')) for l in novas)},
        'notas_recebidas': recebidas,
        'notas_novas': notas_novas,
        'vencidos': {'quantidade': len(vencidos), 'centavos': sum(vencidos)},
        'variacao_pago': _menos(fin_agora['indicadores']['custos_pagos'], fin_antes['indicadores']['custos_pagos']),
        'variacao_recebido': _menos(fin_agora['indicadores']['recebido'], fin_antes['indicadores']['recebido']),
    }


def _variacao(valor):
    return ('+' if valor > 0 else '') + moeda(valor)


def textos_diferencas(dif):
    """Frases curtas do que mudou; lista vazia quando nada mudou."""
    if not dif:
        return []
    textos = []
    if dif['pagamentos']['quantidade']:
        textos.append(f"{dif['pagamentos']['quantidade']} pagamento(s) novo(s): {moeda(dif['pagamentos']['centavos'])}")
    if dif['notas_recebidas']:
        textos.append(f"NF recebida: {', '.join(dif['notas_recebidas'])}")
    if dif['notas_novas']:
        textos.append(f"NF nova: {', '.join(dif['notas_novas'])}")
    if dif['vencidos']['quantidade']:
        textos.append(f"{dif['vencidos']['quantidade']} título(s) a pagar venceram: {moeda(dif['vencidos']['centavos'])}")
    if dif['variacao_pago'] and not dif['pagamentos']['quantidade']:
        textos.append(f"Custos pagos: {_variacao(dif['variacao_pago'])}")
    if dif['variacao_recebido'] and not dif['notas_recebidas']:
        textos.append(f"Recebido: {_variacao(dif['variacao_recebido'])}")
    return textos


# ---------------------------------------------------------------------------
# Card e exportação
# ---------------------------------------------------------------------------

def resumo_obra(obra, situacao):
    """Dados do bloco do card. None quando a obra não está ligada ao Omie."""
    vinculo = situacao.get('vinculo')
    if not vinculo:
        return None
    lote = situacao.get('lote')
    resumo = {'vinculo': vinculo, 'lote': lote, 'erro': situacao.get('erro'),
              'avisos': avisos_vinculo(obra, vinculo, lote and lote['dados']), 'totais': None,
              'indicadores': None, 'notas_encontradas': False}
    if lote:
        financeiro = financeiro_obra(obra, lote['dados'])
        resumo['totais'] = totais_custos(financeiro['custos'])
        resumo['indicadores'] = financeiro['indicadores']
        resumo['notas_encontradas'] = financeiro['notas'] is not None
    return resumo


def _numero(valor_centavos):
    """Número para planilha (vírgula decimal, sem milhar). Ausente → 'a confirmar'."""
    if valor_centavos is None:
        return 'a confirmar'
    sinal = '-' if valor_centavos < 0 else ''
    inteiro, fracao = divmod(abs(valor_centavos), 100)
    return f'{sinal}{inteiro},{fracao:02d}'


def _texto(valor):
    """Evita que a planilha interprete texto vindo do Omie como fórmula."""
    texto = '' if valor is None else str(valor)
    return "'" + texto if texto[:1] in ('=', '+', '-', '@', '\t', '\r') else texto


def exportar_csv(obra, vinculo, lote):
    """Financeiro da obra em CSV (';', UTF-8 com BOM, abre direto no Excel)."""
    financeiro = financeiro_obra(obra, lote['dados'])
    ind = financeiro['indicadores']
    rotulos = dict(GRUPOS)
    saida = io.StringIO()
    w = csv.writer(saida, delimiter=';', lineterminator='\r\n')
    estado = 'Conferido' if vinculo.get('estado') == 'conferido' else 'Em conferência'
    for rotulo, valor in (('Obra', obra.get('nome_contrato')), ('IC', obra.get('contrato_ic')),
                          ('Projeto Omie', vinculo.get('nome_projeto')), ('Situação', estado),
                          ('Consulta', lote.get('consultado_em')),
                          ('Período', f"{lote.get('inicio') or ''} a {lote.get('fim') or ''}"),
                          ('Exportado em', date.today().isoformat())):
        w.writerow([rotulo, _texto(valor)])
    w.writerow([])
    w.writerow(['Indicador', 'Valor (R$)'])
    for rotulo, chave in (('Custos pagos líquidos', 'custos_pagos'), ('Custos a pagar', 'custos_abertos'),
                          ('Recebido da CAIXA (líquido)', 'recebido'), ('Recebido bruto', 'recebido_bruto'),
                          ('Faturado nos títulos consultados', 'faturado'),
                          ('Faturado em aberto (líquido)', 'faturado_aberto'),
                          ('Saldo bruto de caixa', 'saldo_caixa'), ('Total da Obra (cadastro)', 'valor_obra'),
                          ('Saldo contratual a receber', 'saldo_contratual')):
        w.writerow([rotulo, _numero(ind[chave])])
    w.writerow([])
    w.writerow(['Grupo', 'Categoria Omie', 'Descrição', 'Pago líquido (R$)', 'A pagar (R$)'])
    for custo in financeiro['custos']:
        w.writerow([rotulos[custo['grupo']], _texto(custo['codigo']), _texto(custo['descricao']),
                    _numero(custo['pago_centavos']), _numero(custo['aberto_centavos'])])
    w.writerow([])
    if financeiro['notas'] is None:
        w.writerow(['Recebimentos não encontrados no Omie para este projeto (não significa zero).'])
    else:
        w.writerow(['NF', 'Parcela', 'Vencimento', 'Bruto (R$)', 'Retenções (R$)', 'Recebido líquido (R$)',
                    'Aberto líquido (R$)', 'Situação'])
        for nota in financeiro['notas']:
            w.writerow([_texto(nota['nf']), _texto(nota['parcela']), _texto(nota['vencimento']),
                        _numero(nota['bruto_centavos']), _numero(nota['retencoes_centavos']),
                        _numero(nota['recebido_centavos']), _numero(nota['aberto_centavos']), nota['situacao']])
    return ('﻿' + saida.getvalue()).encode('utf-8')
