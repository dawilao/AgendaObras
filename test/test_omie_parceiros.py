import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextlib
import io
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from core.migrations import run_migrations
from db import Database
from db.omie_repo import OmieRepository
from services import omie_atualizacao as atualizacao
from services.financeiro_service import pode_validar_parceiros
from services.omie_financeiro import (classificar_parceiros, comparar_parceiro, exportar_csv,
                                      pagamentos_por_fornecedor)
from services.omie_integracao import BloqueioOmie, ErroIntegracao, consultar_fornecedores, mascarar_documento
from services.omie_simulado import CADASTRO, ClienteSimulado

FIN = {'id': 1, 'nome': 'Fin', 'sobrenome': 'Teste', 'financeiro': 1}
ADMIN = {'id': 2, 'nome': 'Adm', 'is_admin': True, 'financeiro': 0}
COORDENADOR = {'id': 7, 'nome': 'Coord', 'financeiro': 0}
OUTRO_COORDENADOR = {'id': 9, 'nome': 'Outro', 'financeiro': 0}


def baixa(codigo, fornecedor, valor, categoria='2.01.97', status='PAGO'):
    return {'detalhes': {'nCodBaixa': codigo, 'nCodCliente': fornecedor, 'cCodCateg': categoria, 'cStatus': status},
            'resumo': {'nValLiquido': valor}}


def validacao(papel):
    return {'papel': papel, 'validado_por_nome': 'Fin Teste', 'validado_em': '2026-10-05T12:00:00+00:00'}


class RegrasTest(unittest.TestCase):
    DADOS = {'series': {'BXCP': [baixa(1, 501, 100), baixa(2, 501, 50), baixa(2, 501, 50),   # baixa repetida
                                 baixa(3, 502, 30), baixa(4, 503, 999, status='CANCELADO'),
                                 baixa(5, 601, 70, categoria='2.01.99'), baixa(6, None, 10)]},
             'extrato': [{'nCodCliente': 502, 'cDesCliente': 'Nome do extrato'}]}

    def test_pagamentos_por_fornecedor_sem_duplicar(self):
        pagos = {p['codigo']: p for p in pagamentos_por_fornecedor(self.DADOS)}
        self.assertEqual(set(pagos), {501, 502, None})          # 2.01.99 e cancelada fora
        self.assertEqual((pagos[501]['pago_centavos'], pagos[501]['pagamentos']), (15000, 2))
        self.assertEqual(pagos[502]['nome_extrato'], 'Nome do extrato')

    def test_tres_grupos(self):
        grupos = classificar_parceiros(pagamentos_por_fornecedor(self.DADOS),
                                       {501: validacao('parceiro'), 502: validacao('outro'), 777: validacao('parceiro')},
                                       {501: {'nome': 'Alfa', 'documento_mascarado': '11.222.***/0001-**'}})
        self.assertEqual([i['codigo'] for i in grupos['parceiros']], [501, 777])
        self.assertEqual(grupos['parceiros'][1]['pago_centavos'], 0)   # validado sem pagamento no período
        self.assertEqual(grupos['parceiros'][0]['nome'], 'Alfa')
        self.assertEqual([i['nome'] for i in grupos['outros']], ['Nome do extrato'])
        self.assertEqual([i['nome'] for i in grupos['a_validar']], ['Fornecedor não informado no Omie'])

    def test_comparacao_so_com_validados(self):
        obra = {'valor_percentual': 10, 'valor_contrato': 1000, 'total_obra': 1000}   # previsto R$ 100
        medicoes = [{'valor_parceiro_medicao': 40.0}, {'valor_parceiro_medicao': 20.0}]  # medido R$ 60

        def comparar(pago):
            return comparar_parceiro(obra, [{'pago_centavos': pago}], medicoes)
        self.assertEqual(comparar(5000)['nivel'], 'ok')
        acima = comparar(8000)
        self.assertEqual((acima['nivel'], acima['medido'], acima['previsto']), ('ambar', 6000, 10000))
        self.assertIn('R$ 20,00', acima['texto'])
        self.assertEqual(comparar(12000)['nivel'], 'vermelho')
        self.assertEqual(comparar_parceiro(dict(obra, valor_percentual=0), [{'pago_centavos': 1}], medicoes)['nivel'],
                         'indisponivel')
        self.assertEqual(comparar_parceiro(obra, [], medicoes)['nivel'], 'sem_parceiro')

    def test_mascarar_documento(self):
        self.assertEqual(mascarar_documento('11.222.333/0001-81'), '11.222.***/0001-**')
        self.assertEqual(mascarar_documento('11222333000181'), '11.222.***/0001-**')
        self.assertEqual(mascarar_documento('123.456.789-09'), '***.456.789-**')
        self.assertEqual(mascarar_documento('12345678909'), '***.456.789-**')
        for vazio in (None, '', '123', 'abc'):
            self.assertEqual(mascarar_documento(vazio), 'documento não informado')

    def test_consultar_fornecedores_isola_falhas(self):
        chamadas = []

        def chamar(metodo, p):
            chamadas.append(p['codigo_cliente_omie'])
            if p['codigo_cliente_omie'] == 502:
                raise ErroIntegracao('falhou')
            return {'codigo_cliente_omie': p['codigo_cliente_omie'], 'razao_social': 'X', 'cnpj_cpf': '12345678909'}
        encontrados = consultar_fornecedores(chamar, [501, 502, 501, None])
        self.assertEqual(chamadas, [501, 502])
        self.assertEqual(encontrados, {501: {'nome': 'X', 'documento_mascarado': '***.456.789-**'}})

        def bloqueia(metodo, p):
            raise BloqueioOmie(__import__('datetime').datetime.now())
        with self.assertRaises(BloqueioOmie):
            consultar_fornecedores(bloqueia, [501])

    def test_para_apos_falhas_seguidas_e_informa_quais(self):
        chamadas, falhas = [], set()

        def falha(metodo, p):
            chamadas.append(p['codigo_cliente_omie'])
            raise ErroIntegracao('falhou')
        self.assertEqual(consultar_fornecedores(falha, [1, 2, 3, 4, 5], falhas=falhas), {})
        self.assertEqual(chamadas, [1, 2, 3])       # o Omie bloqueia o método após 10 erros seguidos
        self.assertEqual(falhas, {1, 2, 3})

    def test_permissao_de_validar(self):
        obra = {'id': 1, 'coordenador_id': 7}
        self.assertTrue(pode_validar_parceiros(FIN, obra))
        self.assertTrue(pode_validar_parceiros(COORDENADOR, obra))
        for user in (ADMIN, OUTRO_COORDENADOR, None, {}):
            self.assertFalse(pode_validar_parceiros(user, obra))


class BancoParceirosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'obras.db')
        with contextlib.redirect_stdout(io.StringIO()):
            self.db = Database(self.path)
        with sqlite3.connect(self.path) as conn:
            for i, (nome, ic) in enumerate((('ALMENARA', '00744/2026'), ('MEDINA', '03738/2026')), 1):
                conn.execute('INSERT INTO obras(id,nome_contrato,cliente,valor_contrato,contrato_ic,data_inicio,'
                             'total_obra,valor_percentual,coordenador_id) VALUES(?,?,?,?,?,?,?,?,?)',
                             (i, nome, 'CAIXA', 100000, ic, '2026-08-01', 100000, 30, 7))
        conn.close()
        self.repo = OmieRepository(self.path)
        atualizacao._estado.update(bloqueado_ate=None, rodando=False, cancelar=None)
        atualizacao._fornecedores_falhos.clear()
        atualizacao._projetos_cache.update(em=None, lista=None)

    def obras(self):
        return self.db.listar_obras()

    def ligar_e_atualizar(self, cliente):
        for obra in self.obras():
            codigo = 900000 + obra['id']
            atualizacao.ligar(self.repo, obra, {'codigo': codigo, 'nome': ClienteSimulado(self.obras()).projetos[codigo]},
                              FIN)
        return atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=cliente, hoje=date(2026, 10, 5))

    def test_migracao_19_aplicada_e_idempotente(self):
        with contextlib.redirect_stdout(io.StringIO()):
            run_migrations(self.path)
        with sqlite3.connect(self.path) as conn:
            versoes = {r[0] for r in conn.execute('SELECT version FROM schema_migrations')}
            colunas = {r[1] for r in conn.execute('PRAGMA table_info(omie_fornecedores)')}
        conn.close()
        self.assertIn(19, versoes)
        self.assertEqual(colunas, {'codigo', 'nome', 'documento_mascarado', 'consultado_em'})

    def test_fornecedores_consultados_uma_vez_e_documento_so_mascarado(self):
        simulado = ClienteSimulado(self.obras())
        clientes_consultados = []

        def contando(metodo, p):
            if metodo == 'ConsultarCliente':
                clientes_consultados.append(p['codigo_cliente_omie'])
            return simulado(metodo, p)
        self.ligar_e_atualizar(contando)
        primeira = list(clientes_consultados)
        self.assertTrue(primeira)
        self.assertTrue(set(primeira) <= {501, 502, 503})            # só fornecedores da 2.01.97
        atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=contando, hoje=date(2026, 10, 5))
        self.assertEqual(clientes_consultados, primeira)              # já conhecidos: não consulta de novo

        fornecedores = self.repo.fornecedores()
        self.assertEqual(fornecedores[503]['documento_mascarado'], '***.456.789-**')   # pessoa física
        self.assertEqual(fornecedores[501]['documento_mascarado'], '11.222.***/0001-**')
        # Documento completo não fica no banco (vínculos, consultas, auditoria, fornecedores) nem no CSV.
        with sqlite3.connect(self.path) as conn:
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            despejo = '\n'.join(conn.iterdump())
        conn.close()
        csv = exportar_csv(self.db.obter_obra(1), self.repo.vinculo(1), self.repo.ultimo_lote(1, 'ok')).decode('utf-8-sig')
        for _, documento in CADASTRO.values():
            self.assertNotIn(documento, despejo)
            self.assertNotIn(documento, csv)

    def test_falha_nos_fornecedores_nao_derruba_a_obra(self):
        simulado = ClienteSimulado(self.obras())

        def falha_cliente(metodo, p):
            if metodo == 'ConsultarCliente':
                raise ErroIntegracao('O Omie recusou ConsultarCliente: erro.')
            return simulado(metodo, p)
        resumo = self.ligar_e_atualizar(falha_cliente)
        self.assertEqual((resumo['ok'], resumo['erro']), (2, 0))
        self.assertEqual(self.repo.fornecedores(), {})

    def test_fornecedor_que_falhou_nao_e_consultado_de_novo(self):
        simulado = ClienteSimulado(self.obras())
        consultas = []

        def falha_cliente(metodo, p):
            if metodo == 'ConsultarCliente':
                consultas.append(p['codigo_cliente_omie'])
                raise ErroIntegracao('O Omie recusou ConsultarCliente: erro.')
            return simulado(metodo, p)
        self.ligar_e_atualizar(falha_cliente)
        primeira = len(consultas)
        self.assertTrue(primeira)
        atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=falha_cliente, hoje=date(2026, 10, 5))
        self.assertEqual(len(consultas), primeira)

    def test_validar_alterar_desfazer_por_obra(self):
        obra1, obra2 = self.db.obter_obra(1), self.db.obter_obra(2)
        self.assertTrue(atualizacao.validar_parceiro(self.repo, obra1, 501, 'parceiro', COORDENADOR))
        self.assertTrue(atualizacao.validar_parceiro(self.repo, obra2, 501, 'outro', FIN))
        self.assertFalse(atualizacao.validar_parceiro(self.repo, obra1, 501, 'parceiro', FIN))   # nada mudou
        self.assertEqual(self.repo.parceiros_da_obra(1)[501]['papel'], 'parceiro')
        self.assertEqual(self.repo.parceiros_da_obra(2)[501]['papel'], 'outro')
        self.assertTrue(atualizacao.validar_parceiro(self.repo, obra1, 501, 'outro', FIN))
        self.assertTrue(atualizacao.desfazer_parceiro(self.repo, obra1, 501, FIN))
        self.assertEqual(self.repo.parceiros_da_obra(1), {})
        acoes = [a['acao'] for a in self.repo.auditoria(1)]
        self.assertEqual(acoes, ['parceiro_desfeito', 'parceiro_alterado', 'parceiro_validado'])
        with self.assertRaises(ValueError):
            atualizacao.validar_parceiro(self.repo, obra1, None, 'parceiro', FIN)

    def test_validar_negado_a_adm_e_a_outros(self):
        obra = self.db.obter_obra(1)
        for user in (ADMIN, OUTRO_COORDENADOR, None):
            with self.assertRaises(PermissionError):
                atualizacao.validar_parceiro(self.repo, obra, 501, 'parceiro', user)
            with self.assertRaises(PermissionError):
                atualizacao.desfazer_parceiro(self.repo, obra, 501, user)

    def test_excluir_obra_remove_validacoes(self):
        atualizacao.validar_parceiro(self.repo, self.db.obter_obra(1), 501, 'parceiro', FIN)
        self.db.deletar_obra(1)
        self.assertEqual(self.repo.parceiros_da_obra(1), {})


if __name__ == '__main__':
    unittest.main()
