import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextlib
import io
import sqlite3
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from core.migrations import run_migrations
from db import Database
from db.omie_repo import OmieRepository, CONFERIDO, EM_CONFERENCIA
from services import omie_atualizacao as atualizacao
from services.omie_financeiro import (avisos_vinculo, custos_mat_mo, diferencas, exportar_csv, financeiro_obra,
                                      moeda, montar_custos, montar_notas, resumo_obra, textos_diferencas,
                                      totais_custos)
from services.omie_integracao import BloqueioOmie, ErroIntegracao
from services.omie_simulado import ClienteSimulado

FIN = {'id': 1, 'nome': 'Fin', 'sobrenome': 'Teste', 'financeiro': 1}
ADMIN = {'id': 2, 'nome': 'Adm', 'sobrenome': '', 'is_admin': True, 'financeiro': 0}


def baixa(codigo, titulo, categoria, valor, status='PAGO'):
    return {'detalhes': {'nCodBaixa': codigo, 'nCodTitulo': titulo, 'cCodCateg': categoria, 'cStatus': status},
            'resumo': {'nValLiquido': valor}}


def titulo(codigo, categoria, aberto, status='A VENCER'):
    return {'detalhes': {'nCodTitulo': codigo, 'cCodCateg': categoria, 'cStatus': status},
            'resumo': {} if aberto is None else {'nValAberto': aberto}}


class ConversaoTest(unittest.TestCase):
    def dados(self, **extra):
        series = {'BXCP': [baixa(1, 10, '2.01.99', 100.10), baixa(2, 11, '2.01.97', 200),
                           baixa(3, 11, '2.01.97', 50),          # 2ª baixa do mesmo título (parcial)
                           baixa(4, 12, '2.01.98', 30), baixa(5, 13, '2.04.08', 20),
                           baixa(6, 14, '2.01.99', 999, status='CANCELADO')],
                  'CP': [titulo(20, '2.01.99', 10), titulo(21, '2.01.97', 0), titulo(22, '2.04.08', 5)],
                  'CR': [], 'BXCR': []}
        series.update(extra)
        return {'series': series, 'extrato': [{'cCodCategoria': '2.01.99', 'cDesCategoria': 'Fornecedor de Material'}]}

    def test_custos_por_categoria_e_grupos(self):
        custos = montar_custos(self.dados())
        por_codigo = {c['codigo']: c for c in custos}
        self.assertEqual(por_codigo['2.01.99']['pago_centavos'], 10010)      # cancelada fora
        self.assertEqual(por_codigo['2.01.97']['pago_centavos'], 25000)      # duas baixas somadas
        self.assertEqual(por_codigo['2.01.99']['descricao'], 'Fornecedor de Material')
        grupos = custos_mat_mo(custos)
        self.assertEqual((grupos['mat']['pago'], grupos['mo']['pago'], grupos['outros']['pago']), (10010, 28000, 2000))
        self.assertEqual(totais_custos(custos), {'pago': 40010, 'aberto': 1500})

    def test_valor_ausente_fica_a_confirmar(self):
        dados = self.dados(CP=[titulo(20, '2.01.99', None)])
        totais = totais_custos(montar_custos(dados))
        self.assertIsNone(totais['aberto'])
        self.assertEqual(moeda(totais['aberto']), 'A confirmar')
        self.assertEqual(moeda(123456), 'R$ 1.234,56')
        self.assertEqual(moeda(-50), 'R$ -0,50')

    def test_avisos_de_ligacao(self):
        vinculo = {'nome_projeto': '8756/0606/ALMENARA/00744', 'ic_na_confirmacao': '00744/2026'}
        self.assertEqual(avisos_vinculo({'contrato_ic': '00744/2026'}, vinculo), [])
        self.assertTrue(any('não aparece' in a for a in avisos_vinculo({'contrato_ic': '00745/2026'}, vinculo)))
        self.assertTrue(any('mudou' in a for a in avisos_vinculo({'contrato_ic': '00745/2026'}, vinculo)))
        self.assertTrue(any('IC cadastrado' in a for a in avisos_vinculo({'contrato_ic': ''}, vinculo)))
        renomeado = {'avisos': ['O projeto foi renomeado no Omie para "X". Ligação a reconferir.']}
        self.assertEqual(len(avisos_vinculo({'contrato_ic': '00744/2026'}, vinculo, renomeado)), 1)


def nota(codigo, nf, bruto, recebido, aberto, status='A VENCER'):
    resumo = {k: v for k, v in (('nValPago', recebido), ('nValAberto', aberto)) if v is not None}
    return {'detalhes': {'nCodTitulo': codigo, 'cNumDocFiscal': nf, 'nValorTitulo': bruto, 'cStatus': status,
                         'dDtVenc': '10/09/2026'}, 'resumo': resumo}


class RecebimentoTest(unittest.TestCase):
    OBRA = {'id': 1, 'nome_contrato': 'ALMENARA', 'contrato_ic': '00744/2026', 'total_obra': 1000.00}

    def dados(self, cr, bxcp=None, cp=None):
        return {'series': {'CR': cr, 'BXCR': [], 'BXCP': bxcp or [baixa(1, 10, '2.01.99', 100)], 'CP': cp or []},
                'extrato': []}

    def test_valores_das_notas_e_retencao_a_confirmar(self):
        notas = montar_notas(self.dados([nota(1, '1000', 120, 100, 0), nota(2, '1001', 60, 20, 30),
                                         nota(3, '1002', 50, 0, 45), nota(1, '1000', 120, 100, 0),
                                         nota(4, '1003', 80, None, 80), nota(5, '9', 10, 0, 10, 'CANCELADO')]))
        self.assertEqual([n['nf'] for n in notas], ['1000', '1001', '1002', '1003'])   # duplicado e cancelada fora
        self.assertEqual([n['situacao'] for n in notas], ['Recebida', 'Recebida em parte', 'Em aberto', 'A confirmar'])
        self.assertEqual(notas[0]['bruto_centavos'], 12000)
        self.assertTrue(all(n['retencoes_centavos'] is None for n in notas))
        self.assertEqual(moeda(notas[0]['retencoes_centavos']), 'A confirmar')

    def test_obra_sem_notas_nao_vira_zero(self):
        ind = financeiro_obra(self.OBRA, self.dados([]))['indicadores']
        self.assertIsNone(montar_notas(self.dados([])))
        for chave in ('recebido', 'faturado', 'saldo_caixa', 'saldo_contratual'):
            self.assertIsNone(ind[chave])
        self.assertEqual(ind['custos_pagos'], 10000)

    def test_saldos_e_bruto_atribuivel(self):
        ind = financeiro_obra(self.OBRA, self.dados([nota(1, '1000', 120, 100, 0), nota(3, '1002', 50, 0, 45)]))['indicadores']
        self.assertEqual((ind['recebido'], ind['recebido_bruto'], ind['faturado'], ind['faturado_aberto']),
                         (10000, 12000, 17000, 4500))
        self.assertEqual(ind['saldo_caixa'], 0)                       # 100 recebido − 100 pago
        self.assertEqual(ind['saldo_contratual'], 100000 - 10000)     # Total da Obra − recebido
        parcial = financeiro_obra(self.OBRA, self.dados([nota(1, '1000', 120, 100, 0), nota(2, '1001', 60, 20, 30)]))
        self.assertIsNone(parcial['indicadores']['recebido_bruto'])  # bruto da parcial não é atribuível
        sem_total = financeiro_obra(dict(self.OBRA, total_obra=None), self.dados([nota(1, '1000', 120, 100, 0)]))
        self.assertIsNone(sem_total['indicadores']['saldo_contratual'])

    def test_diferencas_entre_consultas(self):
        antes = {'consultado_em': '2026-10-01T12:00:00+00:00',
                 'dados': self.dados([nota(2, '1001', 60, 20, 30)], cp=[titulo(30, '2.01.99', 5)])}
        antes['dados']['series']['CP'][0]['detalhes']['dDtVenc'] = '03/10/2026'
        self.assertEqual(textos_diferencas(diferencas(antes, antes, self.OBRA)), [])
        self.assertIsNone(diferencas(None, antes))
        agora = {'consultado_em': '2026-10-05T12:00:00+00:00',
                 'dados': self.dados([nota(2, '1001', 60, 50, 0), nota(3, '1002', 50, 0, 45)],
                                     bxcp=[baixa(1, 10, '2.01.99', 100), baixa(7, 11, '2.01.97', 40)],
                                     cp=antes['dados']['series']['CP'])}
        dif = diferencas(antes, agora, self.OBRA)
        self.assertEqual(dif['pagamentos'], {'quantidade': 1, 'centavos': 4000})
        self.assertEqual((dif['notas_recebidas'], dif['notas_novas']), (['1001'], ['1002']))
        self.assertEqual(dif['vencidos'], {'quantidade': 1, 'centavos': 500})
        self.assertEqual(dif['variacao_recebido'], 3000)
        self.assertEqual(len(textos_diferencas(dif)), 4)

    def test_csv_com_cabecalho_e_texto_seguro(self):
        lote = {'consultado_em': '2026-10-05T12:00:00+00:00', 'inicio': '2026-07-01', 'fim': '2026-10-05',
                'dados': self.dados([nota(1, '=HYPERLINK("x")', 120, 100, 0)])}
        conteudo = exportar_csv(self.OBRA, {'nome_projeto': 'P/ALMENARA/00744', 'estado': 'em_conferencia'}, lote)
        self.assertTrue(conteudo.startswith(b'\xef\xbb\xbf'))
        texto = conteudo.decode('utf-8-sig')
        self.assertIn('Obra;ALMENARA', texto)
        self.assertIn('Situação;Em conferência', texto)
        self.assertIn('Recebido da CAIXA (líquido);100,00', texto)
        self.assertIn("'=HYPERLINK", texto)
        self.assertIn(';a confirmar;', texto)      # retenções


class BancoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / 'obras.db')
        with contextlib.redirect_stdout(io.StringIO()):
            self.db = Database(self.path)
        with sqlite3.connect(self.path) as conn:
            for i, (nome, ic, inicio) in enumerate((('ALMENARA', '00744/2026', '2026-08-01'),
                                                    ('MEDINA', '03738-2026', '2026-07-15'),
                                                    ('BOM JESUS', '01111/2026', None)), 1):
                conn.execute('INSERT INTO obras(id,nome_contrato,cliente,valor_contrato,contrato_ic,data_inicio,total_obra) '
                             'VALUES(?,?,?,?,?,?,?)', (i, nome, 'CAIXA', 1000, ic, inicio, 1000))
        conn.close()
        self.repo = OmieRepository(self.path)
        atualizacao._estado.update(bloqueado_ate=None, rodando=False, cancelar=None)
        atualizacao._fornecedores_falhos.clear()
        atualizacao._projetos_cache.update(em=None, lista=None)

    # ----- migração
    def test_migracao_18_aplicada_e_idempotente(self):
        with contextlib.redirect_stdout(io.StringIO()):
            run_migrations(self.path)
        with sqlite3.connect(self.path) as conn:
            versoes = {r[0] for r in conn.execute('SELECT version FROM schema_migrations')}
            tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn(18, versoes)
        self.assertTrue({'omie_vinculos', 'omie_lotes', 'financeiro_auditoria'} <= tabelas)

    # ----- vínculos
    def test_projeto_nao_pode_ficar_em_duas_obras(self):
        self.repo.salvar_vinculo(1, 900001, 'P/ALMENARA/00744', '00744/2026', FIN)
        with self.assertRaises(ValueError):
            self.repo.salvar_vinculo(2, 900001, 'P/ALMENARA/00744', '03738-2026', FIN)

    def test_trocar_projeto_apaga_consultas_e_volta_a_conferencia(self):
        self.repo.salvar_vinculo(1, 900001, 'P/A/00744', '00744/2026', FIN)
        self.repo.gravar_lote(1, 'ok', '2026-08-01', '2026-10-05', dados={'x': 1})
        self.repo.marcar_conferido(1, FIN)
        self.assertEqual(self.repo.vinculo(1)['estado'], CONFERIDO)
        self.repo.salvar_vinculo(1, 900009, 'P/OUTRO/00744', '00744/2026', FIN)
        self.assertEqual(self.repo.vinculo(1)['estado'], EM_CONFERENCIA)
        self.assertIsNone(self.repo.ultimo_lote(1))

    def test_reconfirmar_mesmo_projeto_mantem_consultas(self):
        self.repo.salvar_vinculo(1, 900001, 'NOME ANTIGO', '00744/2026', FIN)
        self.repo.gravar_lote(1, 'ok', '2026-08-01', '2026-10-05', dados={'x': 1})
        self.assertTrue(self.repo.salvar_vinculo(1, 900001, 'NOME NOVO', '00744/2026', FIN))
        self.assertEqual(self.repo.vinculo(1)['nome_projeto'], 'NOME NOVO')
        self.assertIsNotNone(self.repo.ultimo_lote(1, 'ok'))
        self.assertFalse(self.repo.salvar_vinculo(1, 900001, 'NOME NOVO', '00744/2026', FIN))
        acoes = [a['acao'] for a in self.repo.auditoria(1)]
        self.assertEqual(acoes, ['vinculo_reconfirmado', 'vinculo_criado'])

    def test_vinculo_em_lote_e_tudo_ou_nada(self):
        self.repo.salvar_vinculo(3, 900003, 'P/BJ/01111', '01111/2026', FIN)
        with self.assertRaises(ValueError):
            self.repo.salvar_vinculos_em_lote([
                {'obra_id': 1, 'codigo_projeto': 900001, 'nome_projeto': 'P/A/00744'},
                {'obra_id': 2, 'codigo_projeto': 900003, 'nome_projeto': 'P/BJ/01111'}], FIN)
        self.assertIsNone(self.repo.vinculo(1))
        with self.assertRaises(ValueError):
            self.repo.salvar_vinculos_em_lote([
                {'obra_id': 1, 'codigo_projeto': 900001, 'nome_projeto': 'P'},
                {'obra_id': 2, 'codigo_projeto': 900001, 'nome_projeto': 'P'}], FIN)
        self.assertEqual(self.repo.salvar_vinculos_em_lote([
            {'obra_id': 1, 'codigo_projeto': 900001, 'nome_projeto': 'P/A/00744'},
            {'obra_id': 2, 'codigo_projeto': 900002, 'nome_projeto': 'P/M/03738'}], FIN), 2)

    def test_conferido_exige_consulta(self):
        self.repo.salvar_vinculo(1, 900001, 'P/A/00744', '00744/2026', FIN)
        with self.assertRaises(ValueError):
            self.repo.marcar_conferido(1, FIN)

    def test_retencao_mantem_as_ultimas_e_situacao_mostra_erro_recente(self):
        self.repo.salvar_vinculo(1, 900001, 'P/A/00744', '00744/2026', FIN)
        with mock.patch('db.omie_repo.OMIE_LOTES_MANTIDOS', 3):
            for i in range(5):
                self.repo.gravar_lote(1, 'ok', '2026-08-01', '2026-10-05', dados={'n': i})
            self.repo.gravar_lote(1, 'erro', '2026-08-01', '2026-10-05', motivo='HTTP 500')
        self.assertEqual(self.repo.contar_lotes(1, 'ok'), 3)
        situacao = self.repo.situacao(1)
        self.assertEqual(situacao['lote']['dados'], {'n': 4})
        self.assertEqual(situacao['erro']['motivo'], 'HTTP 500')
        self.repo.gravar_lote(1, 'ok', '2026-08-01', '2026-10-05', dados={'n': 5})
        self.assertIsNone(self.repo.situacao(1)['erro'])

    def test_excluir_obra_remove_ligacao_e_consultas(self):
        self.repo.salvar_vinculo(1, 900001, 'P/A/00744', '00744/2026', FIN)
        self.repo.gravar_lote(1, 'ok', '2026-08-01', '2026-10-05', dados={'x': 1})
        self.db.deletar_obra(1)
        self.assertIsNone(self.repo.vinculo(1))
        self.assertIsNone(self.repo.ultimo_lote(1))
        self.assertTrue(self.repo.auditoria(1))   # histórico de ações fica

    # ----- atualização
    def obras(self):
        return self.db.listar_obras()

    def ligar_todas(self):
        cliente = ClienteSimulado(self.obras())
        projetos = {p['nome'].split('/')[-1]: p for p in
                    [{'codigo': c, 'nome': n} for c, n in cliente.projetos.items()]}
        for obra in self.obras():
            numero = ''.join(ch for ch in obra['contrato_ic'].split('/')[0].split('-')[0])
            p = projetos[numero]
            atualizacao.ligar(self.repo, obra, p, FIN)
        return cliente

    def test_atualizar_grava_uma_consulta_por_obra(self):
        cliente = self.ligar_todas()
        resumo = atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=cliente, hoje=date(2026, 10, 5))
        self.assertEqual((resumo['ok'], resumo['erro'], resumo['interrompido']), (3, 0, False))
        lote = self.repo.ultimo_lote(1, 'ok')
        self.assertEqual((lote['inicio'], lote['fim']), ('2026-07-15', '2026-10-05'))   # menor início das obras
        self.assertEqual(lote['dados']['conciliacao']['status'], 'Totais conferem')
        resumo_card = resumo_obra(self.db.obter_obra(1), self.repo.situacao(1))
        self.assertGreater(resumo_card['totais']['pago'], 0)
        self.assertEqual(resumo_card['avisos'], [])
        acoes = [a['acao'] for a in self.repo.auditoria()]
        self.assertIn('atualizacao_concluida', acoes)

    def test_duas_obras_na_mesma_cidade_nao_se_misturam(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("UPDATE obras SET nome_contrato='BOM JESUS' WHERE id=2")
        conn.close()
        cliente = self.ligar_todas()
        atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=cliente, hoje=date(2026, 10, 5))
        a = self.repo.ultimo_lote(2, 'ok')['dados']
        b = self.repo.ultimo_lote(3, 'ok')['dados']
        self.assertNotEqual(a['projeto'], b['projeto'])
        self.assertTrue(all(r['cProjeto'] == a['projeto'] for r in a['extrato']))
        self.assertTrue(all(r['cProjeto'] == b['projeto'] for r in b['extrato']))

    def test_atualizar_uma_obra_nao_mexe_nas_outras(self):
        cliente = self.ligar_todas()
        atualizacao.atualizar(self.repo, self.obras(), FIN, obra_ids=[2], cliente=cliente, hoje=date(2026, 10, 5))
        self.assertIsNotNone(self.repo.ultimo_lote(2, 'ok'))
        self.assertIsNone(self.repo.ultimo_lote(1))
        self.assertIsNone(self.repo.ultimo_lote(3))

    def test_falha_preserva_a_consulta_anterior(self):
        cliente = self.ligar_todas()
        atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=cliente, hoje=date(2026, 10, 5))
        anterior = self.repo.ultimo_lote(1, 'ok')

        def falha(metodo, args):
            if metodo == 'ListarMovimentos' and args['nCodProjeto'] == 900001 and args.get('nPagina') == 1:
                return {'nPagina': 1, 'nTotPaginas': 2, 'nTotRegistros': 2, 'movimentos': [{'detalhes': {}}]}
            return cliente(metodo, args)
        resumo = atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=falha, hoje=date(2026, 10, 6))
        self.assertEqual((resumo['ok'], resumo['erro']), (2, 1))
        situacao = self.repo.situacao(1)
        self.assertEqual(situacao['lote']['id'], anterior['id'])
        self.assertIsNotNone(situacao['erro'])

    def test_so_o_financeiro_atualiza(self):
        self.ligar_todas()
        with self.assertRaises(PermissionError):
            atualizacao.atualizar(self.repo, self.obras(), ADMIN, cliente=ClienteSimulado(self.obras()))
        with self.assertRaises(PermissionError):
            atualizacao.ligar(self.repo, self.obras()[0], {'codigo': 1, 'nome': 'X'}, ADMIN)

    def test_uma_atualizacao_por_vez(self):
        cliente = self.ligar_todas()
        atualizacao._trava.acquire()
        try:
            with self.assertRaises(RuntimeError):
                atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=cliente)
        finally:
            atualizacao._trava.release()

    def test_bloqueio_do_omie_impede_nova_tentativa(self):
        self.ligar_todas()
        ate = datetime.now(timezone.utc) + timedelta(minutes=30)

        def bloqueia(metodo, args):
            raise BloqueioOmie(ate)
        resumo = atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=bloqueia)
        self.assertEqual(resumo['bloqueado_ate'], ate)
        self.assertEqual(resumo['nao_processadas'], 3)
        with self.assertRaises(ErroIntegracao):
            atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras()))
        self.assertIn('atualizacao_bloqueada', [a['acao'] for a in self.repo.auditoria()])

    def test_sem_obras_ligadas(self):
        with self.assertRaises(ValueError):
            atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras()))

    def test_obras_sem_ligacao_com_sugestao(self):
        cliente = ClienteSimulado(self.obras())
        projetos = [{'codigo': c, 'nome': n} for c, n in cliente.projetos.items()]
        atualizacao.ligar(self.repo, self.obras()[0], projetos[0], FIN)
        linhas = atualizacao.obras_sem_ligacao(self.repo, self.obras(), projetos)
        self.assertEqual(len(linhas), 2)
        self.assertTrue(all(l['situacao'] == 'sugerida' for l in linhas))

    def test_retencao_guarda_ao_menos_a_consulta_anterior(self):
        self.repo.salvar_vinculo(1, 900001, 'P/A/00744', '00744/2026', FIN)
        with mock.patch('db.omie_repo.OMIE_LOTES_MANTIDOS', 1):
            for i in range(4):
                self.repo.gravar_lote(1, 'ok', '2026-08-01', '2026-10-05', dados={'n': i})
        self.assertEqual(self.repo.contar_lotes(1, 'ok'), 2)
        situacao = self.repo.situacao(1)
        self.assertEqual((situacao['lote']['dados'], situacao['anterior']['dados']), ({'n': 3}, {'n': 2}))

    def test_segunda_atualizacao_mostra_o_que_mudou(self):
        self.ligar_todas()
        primeira = atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras()),
                                         hoje=date(2026, 10, 5))
        self.assertEqual(primeira['mudancas'], {'pagamentos': 0, 'notas_recebidas': 0})
        segunda = atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras(), rodada=1),
                                        hoje=date(2026, 10, 5))
        self.assertEqual(segunda['mudancas'], {'pagamentos': 3, 'notas_recebidas': 3})
        situacao = self.repo.situacao(1)
        self.assertEqual(situacao['lote']['dados']['conciliacao']['status'], 'Totais conferem')
        dif = diferencas(situacao['anterior'], situacao['lote'], self.db.obter_obra(1))
        self.assertEqual(dif['pagamentos']['quantidade'], 1)
        resumo_card = resumo_obra(self.db.obter_obra(1), situacao)
        self.assertTrue(resumo_card['notas_encontradas'])
        self.assertIsNotNone(resumo_card['indicadores']['saldo_contratual'])

    # ----- conferência volta quando a consulta muda
    def test_mudanca_na_consulta_reabre_a_conferencia(self):
        self.ligar_todas()
        atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras()), hoje=date(2026, 10, 5))
        self.assertTrue(atualizacao.marcar_conferido(self.repo, 1, FIN))
        resumo = atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras(), rodada=1),
                                       hoje=date(2026, 10, 5))
        self.assertEqual(resumo['reabertas'], 1)          # só a obra 1 estava conferida
        vinculo = self.repo.vinculo(1)
        self.assertEqual(vinculo['estado'], EM_CONFERENCIA)
        self.assertIsNone(vinculo['conferido_por_nome'])
        reaberta = [a for a in self.repo.auditoria(1) if a['acao'] == 'conferencia_reaberta']
        self.assertEqual(len(reaberta), 1)
        self.assertTrue(reaberta[0]['detalhe']['mudancas'])

    def test_consulta_sem_mudanca_mantem_conferido(self):
        self.ligar_todas()
        atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras()), hoje=date(2026, 10, 5))
        atualizacao.marcar_conferido(self.repo, 1, FIN)
        resumo = atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras()),
                                       hoje=date(2026, 10, 5))
        self.assertEqual(resumo['reabertas'], 0)
        self.assertEqual(self.repo.vinculo(1)['estado'], CONFERIDO)

    def test_consulta_simulada_fica_marcada(self):
        self.ligar_todas()
        atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras()), hoje=date(2026, 10, 5))
        lote = self.repo.ultimo_lote(1, 'ok')
        self.assertTrue(lote['dados']['simulado'])
        csv = exportar_csv(self.db.obter_obra(1), self.repo.vinculo(1), lote).decode('utf-8-sig')
        self.assertIn('Dados simulados', csv)

    # ----- leituras enxutas
    def test_situacao_do_card_le_so_a_ultima_consulta(self):
        self.repo.salvar_vinculo(1, 900001, 'P/A/00744', '00744/2026', FIN)
        for i in range(2):
            self.repo.gravar_lote(1, 'ok', '2026-08-01', '2026-10-05', dados={'n': i})
        self.repo.gravar_lote(1, 'erro', '2026-08-01', '2026-10-05', motivo='falhou')
        card = self.repo.situacao(1, com_anterior=False)
        self.assertEqual(card['lote']['dados'], {'n': 1})
        self.assertIsNone(card['anterior'])
        self.assertEqual((card['erro']['motivo'], card['erro']['dados']), ('falhou', None))
        self.assertEqual(self.repo.situacao(1)['anterior']['dados'], {'n': 0})
        self.assertEqual(self.repo.situacao(2), {'vinculo': None, 'lote': None, 'anterior': None, 'erro': None})

    def test_fornecedores_e_vinculos_filtrados_no_banco(self):
        self.repo.salvar_fornecedores({501: {'nome': 'A'}, 502: {'nome': 'B'}})
        self.assertEqual(set(self.repo.fornecedores([502, None, 999])), {502})
        self.assertEqual(set(self.repo.fornecedores()), {501, 502})
        self.assertEqual(self.repo.fornecedores([]), {})
        self.repo.salvar_vinculo(2, 900002, 'P2', None, FIN)
        self.repo.salvar_vinculo(1, 900001, 'P1', None, FIN)
        self.assertEqual([v['obra_id'] for v in self.repo.vinculos([2, 5])], [2])
        self.assertEqual([v['obra_id'] for v in self.repo.vinculos([2, 1])], [1, 2])
        self.assertEqual([v['obra_id'] for v in self.repo.vinculos()], [1, 2])

    def test_lista_de_projetos_recente_nao_e_repetida(self):
        chamadas = []

        def chamar(metodo, p):
            chamadas.append(metodo)
            return {'pagina': 1, 'total_de_paginas': 1, 'total_de_registros': 1,
                    'cadastro': [{'codigo': 1, 'nome': 'X'}]}
        atualizacao.projetos_omie(FIN, cliente=chamar)
        atualizacao.projetos_omie(FIN, cliente=chamar, recarregar=True)   # < 60 s: o Omie recusaria a repetição
        self.assertEqual(chamadas, ['ListarProjetos'])
        depois = time.monotonic() + 61
        with mock.patch.object(atualizacao.time, 'monotonic', return_value=depois):
            atualizacao.projetos_omie(FIN, cliente=chamar, recarregar=True)
        self.assertEqual(len(chamadas), 2)

    def test_exportar_e_historico_seguem_quem_ve(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute('UPDATE obras SET coordenador_id=7 WHERE id=1')
        conn.close()
        self.ligar_todas()
        obra = self.db.obter_obra(1)
        with self.assertRaises(ValueError):
            atualizacao.exportar_financeiro(self.repo, obra, FIN)        # sem consulta
        atualizacao.atualizar(self.repo, self.obras(), FIN, cliente=ClienteSimulado(self.obras()), hoje=date(2026, 10, 5))
        coordenador = {'id': 7, 'nome': 'Coord', 'financeiro': 0}
        outro = {'id': 8, 'nome': 'Outro', 'financeiro': 0}
        nome, conteudo = atualizacao.exportar_financeiro(self.repo, obra, coordenador, hoje=date(2026, 10, 5))
        self.assertEqual(nome, 'financeiro_omie_almenara_2026-10-05.csv')
        self.assertIn('ALMENARA', conteudo.decode('utf-8-sig'))
        self.assertEqual(atualizacao.historico(self.repo, obra, coordenador)[0]['acao'], 'financeiro_exportado')
        for user in (outro, None):
            with self.assertRaises(PermissionError):
                atualizacao.exportar_financeiro(self.repo, obra, user)
            with self.assertRaises(PermissionError):
                atualizacao.historico(self.repo, obra, user)
        with self.assertRaises(PermissionError):
            atualizacao.historico_geral(self.repo, ADMIN)
        self.assertTrue(atualizacao.historico_geral(self.repo, FIN))

    def test_periodo_padrao(self):
        self.assertEqual(atualizacao.periodo_padrao([{'data_inicio': None}], date(2026, 10, 5)),
                         ('2026-01-01', '2026-10-05'))
        self.assertEqual(atualizacao.periodo_padrao([{'data_inicio': '2026-12-01'}], date(2026, 10, 5)),
                         ('2026-10-05', '2026-10-05'))


class SimuladoTest(unittest.TestCase):
    def test_consulta_simulada_nao_e_comparada_com_real(self):
        antes = {'dados': {'series': {'BXCP': [baixa(1, 1, '2.01.99', 100)]}, 'simulado': True},
                 'consultado_em': '2026-10-01T10:00:00+00:00'}
        depois = {'dados': {'series': {'BXCP': [baixa(1, 1, '2.01.99', 100), baixa(2, 2, '2.01.99', 50)]}},
                  'consultado_em': '2026-10-02T10:00:00+00:00'}
        self.assertIsNone(diferencas(antes, depois))
        real = {**antes, 'dados': {**antes['dados'], 'simulado': False}}
        self.assertEqual(diferencas(real, depois)['pagamentos']['quantidade'], 1)


if __name__ == '__main__':
    unittest.main()
