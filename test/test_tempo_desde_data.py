"""
Testes do contador de dias exibido ao lado da data de início no card.
"""

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.formatters import tempo_desde_data

HOJE = datetime.date(2026, 9, 28)


class TestTempoDesdeData(unittest.TestCase):
    def test_data_passada(self):
        self.assertEqual(tempo_desde_data('2026-09-01', HOJE), 'há 27 dias')

    def test_singular(self):
        self.assertEqual(tempo_desde_data('2026-09-27', HOJE), 'há 1 dia')
        self.assertEqual(tempo_desde_data('2026-09-29', HOJE), 'em 1 dia')

    def test_hoje(self):
        self.assertEqual(tempo_desde_data('2026-09-28', HOJE), 'hoje')

    def test_data_futura(self):
        self.assertEqual(tempo_desde_data('2026-10-05', HOJE), 'em 7 dias')

    def test_formato_brasileiro(self):
        self.assertEqual(tempo_desde_data('01/09/2026', HOJE), 'há 27 dias')

    def test_invalida_ou_vazia(self):
        self.assertEqual(tempo_desde_data('', HOJE), '')
        self.assertEqual(tempo_desde_data(None, HOJE), '')
        self.assertEqual(tempo_desde_data('xx/yy', HOJE), '')


if __name__ == '__main__':
    unittest.main()
