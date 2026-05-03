import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agenda_obras import datas_iguais_normalizadas


class TestDatasNormalizadas(unittest.TestCase):
    def test_none_e_vazio_sao_equivalentes(self):
        self.assertTrue(datas_iguais_normalizadas(None, ''))
        self.assertTrue(datas_iguais_normalizadas('', None))

    def test_datas_iguais_sao_detectadas(self):
        self.assertTrue(datas_iguais_normalizadas('2026-04-15', '2026-04-15'))

    def test_datas_diferentes_sao_detectadas(self):
        self.assertFalse(datas_iguais_normalizadas(None, '2026-04-15'))
        self.assertFalse(datas_iguais_normalizadas('2026-04-15', ''))


if __name__ == '__main__':
    unittest.main(verbosity=2)