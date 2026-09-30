"""Status visual de obras finalizadas: texto, coluna do Kanban, aba da Grade e select de edição."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.obras_helper import ObrasHelper
from services.obra_service import status_visual_para_edicao


class TestStatusObraConcluida(unittest.TestCase):

    def _status(self, status_conclusao):
        obra = {'id': 1, 'status': 'Concluída', 'status_conclusao_obra': status_conclusao}
        return obra, ObrasHelper.obter_status_visual(obra, [])[2]

    def test_com_pendencias(self):
        obra, status = self._status('com_pendencias')
        self.assertEqual(status, 'Concluída com Pendências')
        self.assertEqual(ObrasHelper.obter_bucket_kanban(status), 'concluido')
        self.assertEqual(ObrasHelper.obter_bucket_grade(status), 'concluido')
        self.assertEqual(status_visual_para_edicao(obra, []), 'Concluída com Pendências')

    def test_sem_pendencias(self):
        obra, status = self._status('sem_pendencias')
        self.assertEqual(status, 'Concluído')
        self.assertEqual(ObrasHelper.obter_bucket_kanban(status), 'concluido')
        self.assertEqual(ObrasHelper.obter_bucket_grade(status), 'concluido')
        self.assertEqual(status_visual_para_edicao(obra, []), 'Concluído')


if __name__ == '__main__':
    unittest.main()
