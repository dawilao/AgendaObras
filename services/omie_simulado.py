"""Omie simulado (OMIE_MODO=simulado): dados fictícios, no formato das respostas usadas pela coleta.

Um projeto por obra com IC ("…/CIDADE/<número do IC>"), duas contas, pagamento parcial em duas
baixas, títulos em aberto, notas da CAIXA (recebida, parcial e em aberto) e tarifa no extrato.
Nenhum dado real; os valores são sempre os mesmos para a mesma obra, período e rodada. A partir
da 2ª atualização no processo (rodada ≥ 1) aparecem pagamentos novos e a nota parcial é quitada,
para conferir na tela o que mudou desde a consulta anterior.
"""
import itertools
import random
from datetime import date, datetime, timedelta

from services.omie_integracao import ErroIntegracao, numero_ic

_rodadas = itertools.count()

CONTAS = ((101, 'Conta simulada A'), (102, 'Conta simulada B'))
CATEGORIAS = {'2.01.99': 'Fornecedor de Material', '2.01.97': 'Prestador de Serviço/Parceiro',
              '2.01.98': 'Fornecedor de Serviços', '2.04.08': 'Seguros', '1.01.01': 'Medições CAIXA'}
FORNECEDORES = {'2.01.99': (601, 602), '2.01.97': (501, 502, 503), '2.01.98': (701,), '2.04.08': (801,)}
ORDEM_CATEGORIAS = ('2.01.99', '2.01.97', '2.01.98', '2.01.99', '2.01.97', '2.04.08', '2.01.97', '2.01.99')


def _br(d):
    return d.strftime('%d/%m/%Y')


def _de_br(texto):
    return datetime.strptime(texto, '%d/%m/%Y').date()


class ClienteSimulado:
    ao_esperar = None

    @classmethod
    def proxima(cls, obras):
        """Cliente da próxima rodada do processo (usado pela tela em OMIE_MODO=simulado)."""
        return cls(obras, rodada=next(_rodadas))

    def __init__(self, obras, rodada=0):
        self.rodada = rodada
        self.projetos = {}
        for obra in obras:
            numero = numero_ic(obra.get('contrato_ic'))
            if numero is None:
                continue
            nome = (obra.get('nome_contrato') or 'OBRA').strip().upper()
            self.projetos[900000 + int(obra['id'])] = f"{1000 + int(obra['id']) % 9000:04d}/0001/{nome}/{numero:05d}"
        hoje = date.today()
        self._periodo = (_br(hoje - timedelta(days=120)), _br(hoje))
        self._cache = {}

    def __call__(self, metodo, p):
        if 'dPeriodoInicial' in p:
            self._periodo = (p['dPeriodoInicial'], p['dPeriodoFinal'])
        elif 'dDtPagtoDe' in p:
            self._periodo = (p['dDtPagtoDe'], p['dDtPagtoAte'])
        if metodo == 'ListarProjetos':
            cadastro = [{'codigo': c, 'nome': n, 'inativo': 'N'} for c, n in sorted(self.projetos.items())]
            return {'pagina': 1, 'total_de_paginas': 1, 'total_de_registros': len(cadastro), 'cadastro': cadastro}
        if metodo == 'ConsultarProjeto':
            codigo = int(p['codigo'])
            if codigo not in self.projetos:
                raise ErroIntegracao('O Omie recusou ConsultarProjeto: projeto não cadastrado.')
            return {'codigo': codigo, 'nome': self.projetos[codigo], 'inativo': 'N'}
        if metodo == 'ListarContasCorrentes':
            contas = [{'nCodCC': c, 'descricao': d} for c, d in CONTAS]
            return {'pagina': 1, 'total_de_paginas': 1, 'total_de_registros': len(contas),
                    'ListarContasCorrentes': contas}
        if metodo == 'ListarExtrato':
            conta = int(p['nCodCC'])
            lista = [{k: v for k, v in r.items() if k != 'conta'} for codigo in self.projetos
                     for r in self._dados(codigo)['extrato'] if r['conta'] == conta]
            return {'nCodCC': conta, 'listaMovimentos': lista}
        if metodo == 'ListarMovimentos':
            codigo = int(p['nCodProjeto'])
            linhas = self._dados(codigo)[p['cTpLancamento']] if codigo in self.projetos else []
            return {'nPagina': 1, 'nTotPaginas': 1, 'nTotRegistros': len(linhas), 'movimentos': linhas}
        raise ErroIntegracao(f'Método {metodo} não simulado.')

    def _dados(self, codigo):
        chave = (codigo, self._periodo)
        if chave not in self._cache:
            self._cache[chave] = self._gerar(codigo, *self._periodo)
        return self._cache[chave]

    def _gerar(self, codigo, de, ate):
        rng = random.Random(codigo)
        inicio, fim = _de_br(de), _de_br(ate)
        nome = self.projetos[codigo]

        def dia(k):
            return _br(max(inicio, fim - timedelta(days=9 * k + 1)))

        def movimento(titulo, baixa, conta, categoria, fornecedor, valor, data, status, resumo, extra=None):
            detalhes = {'nCodTitulo': titulo, 'nCodBaixa': baixa, 'cCodProjeto': codigo, 'nCodCC': conta,
                        'nCodCliente': fornecedor, 'cCodCateg': categoria, 'cStatus': status,
                        'cOrigem': 'SIMULADO', 'dDtPagamento': data, 'dDtVenc': data,
                        'cNumParcela': '001/001', 'nValorTitulo': valor, **(extra or {})}
            return {'detalhes': detalhes, 'resumo': resumo, 'categorias': [{'cCodCateg': categoria}]}

        def extrato(lancamento, conta, categoria, fornecedor, valor, data, origem, tipo=''):
            return {'conta': conta, 'nCodLancamento': lancamento, 'dDataLancamento': data, 'cOrigem': origem,
                    'cSituacao': 'Conciliado', 'cTipoDocumento': tipo, 'nValorDocumento': valor,
                    'cCodCategoria': categoria, 'cDesCategoria': CATEGORIAS.get(categoria, 'Tarifas bancárias'),
                    'cProjeto': nome, 'nCodCliente': fornecedor, 'cDesCliente': f'Fornecedor simulado {fornecedor}'}

        bxcp, cp, cr, bxcr, linhas_extrato = [], [], [], [], []
        pagamentos = [(i, ORDEM_CATEGORIAS[i]) for i in range(len(ORDEM_CATEGORIAS))]
        pagamentos.append((len(pagamentos), '2.01.97'))   # 2ª baixa do título anterior (pagamento parcial)
        for k, categoria in pagamentos:
            parcial = k == len(pagamentos) - 1
            titulo = codigo * 100 + (k - 1 if parcial else k)
            baixa = codigo * 1000 + k
            conta = CONTAS[k % 2][0]
            fornecedor = rng.choice(FORNECEDORES[categoria])
            valor = round(rng.uniform(800, 25000), 2)
            data = dia(k)
            bxcp.append(movimento(titulo, baixa, conta, categoria, fornecedor, valor, data, 'PAGO',
                                  {'nValLiquido': valor, 'nValPago': valor, 'nValAberto': 0}))
            linhas_extrato.append(extrato(baixa, conta, categoria, fornecedor, -valor, data, 'Conta Paga'))
            if not parcial:
                cp.append(movimento(titulo, None, conta, categoria, fornecedor, valor, data, 'PAGO',
                                    {'nValPago': valor, 'nValAberto': 0, 'nValLiquido': valor}))
        for r in range(min(self.rodada, 3)):     # pagamentos novos a cada rodada
            k = len(pagamentos) + r
            valor = round(random.Random(codigo * 10 + r).uniform(800, 9000), 2)   # não altera os demais valores
            titulo, baixa, data = codigo * 100 + 60 + r, codigo * 1000 + 600 + r, _br(fim)
            bxcp.append(movimento(titulo, baixa, CONTAS[k % 2][0], '2.01.99', FORNECEDORES['2.01.99'][0], valor,
                                  data, 'PAGO', {'nValLiquido': valor, 'nValPago': valor, 'nValAberto': 0}))
            cp.append(movimento(titulo, None, CONTAS[k % 2][0], '2.01.99', FORNECEDORES['2.01.99'][0], valor,
                                data, 'PAGO', {'nValPago': valor, 'nValAberto': 0, 'nValLiquido': valor}))
            linhas_extrato.append(extrato(baixa, CONTAS[k % 2][0], '2.01.99', FORNECEDORES['2.01.99'][0], -valor,
                                          data, 'Conta Paga'))
        for j, categoria in enumerate(('2.01.99', '2.01.97')):
            valor = round(rng.uniform(2000, 15000), 2)
            cp.append(movimento(codigo * 100 + 40 + j, None, CONTAS[0][0], categoria,
                                FORNECEDORES[categoria][0], valor, dia(0), 'A VENCER',
                                {'nValPago': 0, 'nValAberto': valor, 'nValLiquido': valor}))
        # Notas da CAIXA: recebida, parcialmente recebida (quitada a partir da rodada 1) e em aberto.
        for j, fator in enumerate((1.0, 1.0 if self.rodada else 0.5, 0.0)):
            bruto = round(rng.uniform(40000, 120000), 2)
            liquido = round(bruto * 0.89, 2)
            recebido = round(liquido * fator, 2)
            titulo = codigo * 100 + 50 + j
            data = dia(j + 1)
            cr.append(movimento(titulo, None, CONTAS[1][0], '1.01.01', 100, bruto, data,
                                'RECEBIDO' if fator == 1 else 'A VENCER',
                                {'nValPago': recebido, 'nValAberto': round(liquido - recebido, 2), 'nValLiquido': liquido},
                                {'cNumDocFiscal': str(1000 + j)}))
            if recebido:
                baixa = codigo * 1000 + 500 + j
                bxcr.append(movimento(titulo, baixa, CONTAS[1][0], '1.01.01', 100, bruto, data, 'RECEBIDO',
                                      {'nValLiquido': recebido, 'nValPago': recebido, 'nValAberto': 0},
                                      {'cNumDocFiscal': str(1000 + j)}))
                linhas_extrato.append(extrato(baixa, CONTAS[1][0], '1.01.01', 100, recebido, data, 'Conta Recebida'))
        linhas_extrato.append(extrato(codigo * 1000 + 900, CONTAS[0][0], '2.10.01', 0, -15.9, dia(2),
                                      'Débito em Conta Corrente', 'Tarifa'))
        return {'CP': cp, 'CR': cr, 'BXCP': bxcp, 'BXCR': bxcr, 'extrato': linhas_extrato}
