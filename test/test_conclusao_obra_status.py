"""Conclusão da obra: select de Status do card, oferta do pop-up de finalização,
reabertura e preservação da data de conclusão."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database
from services.obra_service import (
    EstadoConclusao,
    acao_status_edicao,
    deve_oferecer_conclusao,
    estado_conclusao,
)
from utils.formatters import status_edicao_para_banco
from utils.obras_helper import ObrasHelper

import corrigir_data_conclusao


class TestAcaoStatusEdicao(unittest.TestCase):

    def test_concluido_em_obra_aberta_conclui_sem_pendencias(self):
        self.assertEqual(acao_status_edicao('Concluído', None), 'concluir_sem')
        self.assertEqual(acao_status_edicao('Concluído', ''), 'concluir_sem')

    def test_concluido_em_obra_com_pendencias_resolve(self):
        self.assertEqual(acao_status_edicao('Concluído', 'com_pendencias'), 'concluir_sem')

    def test_concluido_em_obra_ja_concluida_nao_faz_nada(self):
        self.assertIsNone(acao_status_edicao('Concluído', 'sem_pendencias'))

    def test_com_pendencias(self):
        self.assertEqual(acao_status_edicao('Concluída com Pendências', None), 'concluir_com')
        self.assertEqual(acao_status_edicao('Concluída com Pendências', 'sem_pendencias'), 'concluir_com')
        self.assertIsNone(acao_status_edicao('Concluída com Pendências', 'com_pendencias'))

    def test_status_aberto_em_obra_concluida_reabre(self):
        for status in ('Não Iniciada', 'Em Andamento', 'Atrasada', 'Pronta para concluir'):
            with self.subTest(status=status):
                self.assertEqual(acao_status_edicao(status, 'sem_pendencias'), 'reabrir')
                self.assertEqual(acao_status_edicao(status, 'com_pendencias'), 'reabrir')

    def test_status_aberto_em_obra_aberta_nao_faz_nada(self):
        for status in ('Não Iniciada', 'Em Andamento', 'Atrasada', 'Pronta para concluir', ''):
            with self.subTest(status=status):
                self.assertIsNone(acao_status_edicao(status, None))


class TestStatusEdicaoParaBanco(unittest.TestCase):

    def test_pronta_para_concluir_nao_vira_concluida(self):
        self.assertEqual(status_edicao_para_banco('Pronta para concluir'), 'Em Andamento')

    def test_concluidos_viram_concluida(self):
        self.assertEqual(status_edicao_para_banco('Concluído'), 'Concluída')
        self.assertEqual(status_edicao_para_banco('Concluída com Pendências'), 'Concluída')

    def test_demais_passam_direto(self):
        self.assertEqual(status_edicao_para_banco('Atrasada'), 'Atrasada')


class TestDeveOferecerConclusao(unittest.TestCase):

    def _e(self, concluida=False, medicoes_ok=False, tarefas_100=False):
        return EstadoConclusao(concluida, medicoes_ok, tarefas_100)

    def test_fechou_medicoes_com_outras_tarefas_pendentes(self):
        self.assertTrue(deve_oferecer_conclusao(self._e(), self._e(medicoes_ok=True)))

    def test_ultima_tarefa_comum_leva_a_100(self):
        antes = self._e(medicoes_ok=True)
        depois = self._e(medicoes_ok=True, tarefas_100=True)
        self.assertTrue(deve_oferecer_conclusao(antes, depois))

    def test_obra_concluida_nao_oferece(self):
        self.assertFalse(deve_oferecer_conclusao(self._e(), self._e(True, True, True)))

    def test_sem_transicao_nao_oferece(self):
        estado = self._e(medicoes_ok=True, tarefas_100=True)
        self.assertFalse(deve_oferecer_conclusao(estado, estado))
        parcial = self._e(medicoes_ok=True)
        self.assertFalse(deve_oferecer_conclusao(parcial, parcial))

    def test_medicoes_pendentes_nao_oferece(self):
        self.assertFalse(deve_oferecer_conclusao(self._e(), self._e(tarefas_100=True)))

    def test_reabrir_pelo_select_nao_oferece_de_novo(self):
        antes = self._e(concluida=True, medicoes_ok=True, tarefas_100=True)
        depois = self._e(medicoes_ok=True, tarefas_100=True)
        self.assertFalse(deve_oferecer_conclusao(antes, depois))

    def test_sem_estado_anterior_nao_oferece(self):
        self.assertFalse(deve_oferecer_conclusao(None, self._e(medicoes_ok=True, tarefas_100=True)))


class TestConclusaoNoBanco(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'test_agendaobras.db'))
        self.obra_id = self.db.criar_obra('Obra Conclusao', 'Cliente', 1000.0, '2026-04-15', status='Em Andamento')
        self.db.criar_medicoes_dinamicas(self.obra_id, 1)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _concluir(self, filtro_sql: str = '1 = 1', data: str = '2026-05-10'):
        conn = self.db.get_connection()
        conn.execute(
            f'UPDATE obra_checklist SET concluido = 1, data_conclusao = ? WHERE obra_id = ? AND {filtro_sql}',
            (data, self.obra_id))
        conn.commit()
        conn.close()

    def _status_visual(self):
        obra = self.db.obter_obra(self.obra_id)
        return ObrasHelper.obter_status_visual(obra, self.db.obter_checklist(self.obra_id))[2]

    def _salvar_card(self, **kwargs):
        """Mesmo salvamento do card de edição, que não envia data_conclusao."""
        self.db.atualizar_obra(self.obra_id, 'Obra Conclusao', 'Cliente', 1000.0, '2026-04-15',
                               'Concluída', total_obra=1000.0, **kwargs)

    def test_estado_conclusao_acompanha_tarefas(self):
        estado = estado_conclusao(self.db, self.obra_id)
        self.assertEqual(estado, EstadoConclusao(False, False, False))

        self._concluir("(descricao LIKE 'MEDIÇÃO %' OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %')")
        meio = estado_conclusao(self.db, self.obra_id)
        self.assertEqual(meio, EstadoConclusao(False, True, False))
        self.assertTrue(deve_oferecer_conclusao(estado, meio))

        self._concluir()
        fim = estado_conclusao(self.db, self.obra_id)
        self.assertEqual(fim, EstadoConclusao(False, True, True))
        self.assertTrue(deve_oferecer_conclusao(meio, fim))

    def test_obra_100_por_cento_fica_concluida_ao_registrar_finalizacao(self):
        self._concluir()
        self.assertEqual(self._status_visual(), 'Pronta para concluir')

        self.db.registrar_finalizacao_obra(self.obra_id, 'sem_pendencias')

        self.assertEqual(self._status_visual(), 'Concluído')
        self.assertTrue(estado_conclusao(self.db, self.obra_id).concluida)

    def test_reabrir_obra_limpa_conclusao(self):
        self._concluir()
        self.db.registrar_finalizacao_obra(self.obra_id, 'com_pendencias')

        self.db.reabrir_obra(self.obra_id)

        obra = self.db.obter_obra(self.obra_id)
        self.assertIsNone(obra['status_conclusao_obra'])
        self.assertIsNone(obra['data_conclusao'])
        self.assertEqual(obra['status'], 'Em Andamento')
        self.assertEqual(self._status_visual(), 'Pronta para concluir')

    def test_salvar_card_preserva_data_conclusao(self):
        self._concluir()
        self.db.registrar_finalizacao_obra(self.obra_id, 'sem_pendencias')
        data = self.db.obter_obra(self.obra_id)['data_conclusao']
        self.assertTrue(data)

        self._salvar_card()

        self.assertEqual(self.db.obter_obra(self.obra_id)['data_conclusao'], data)

    def test_atualizar_obra_com_data_conclusao_explicita_grava(self):
        self._salvar_card(data_conclusao='2026-06-01')
        self.assertEqual(self.db.obter_obra(self.obra_id)['data_conclusao'], '2026-06-01')

    def test_script_preenche_data_com_ultima_tarefa(self):
        self._concluir(data='2026-05-10')
        self._concluir("descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %'", data='2026-06-20')
        self.db.registrar_finalizacao_obra(self.obra_id, 'sem_pendencias')
        conn = self.db.get_connection()
        conn.execute('UPDATE obras SET data_conclusao = NULL WHERE id = ?', (self.obra_id,))
        conn.commit()

        cursor = conn.cursor()
        obras = corrigir_data_conclusao.listar_sem_data(cursor)
        self.assertEqual([o['id'] for o in obras], [self.obra_id])
        self.assertEqual(corrigir_data_conclusao.aplicar_correcao(cursor, obras), 1)
        conn.commit()
        conn.close()

        self.assertEqual(self.db.obter_obra(self.obra_id)['data_conclusao'], '2026-06-20')

    def test_script_lista_concluida_sem_finalizacao(self):
        self._salvar_card()  # status 'Concluída' sem status_conclusao_obra (estado das obras relatadas)
        conn = self.db.get_connection()
        ids = [o['id'] for o in corrigir_data_conclusao.listar_inconsistentes(conn.cursor())]
        conn.close()
        self.assertIn(self.obra_id, ids)


if __name__ == '__main__':
    unittest.main(verbosity=2)
