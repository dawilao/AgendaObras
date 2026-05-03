import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agenda_obras import rotulo_alterar_medicoes


class TestRotuloMedicoes(unittest.TestCase):
    def test_rotulo_com_quantidade(self):
        self.assertEqual(rotulo_alterar_medicoes(0, True), 'Alterar medições (0/6)')
        self.assertEqual(rotulo_alterar_medicoes(3, True), 'Alterar medições (3/6)')

    def test_rotulo_desabilitado(self):
        self.assertEqual(rotulo_alterar_medicoes(3, False), 'Alterar medições')


if __name__ == '__main__':
    unittest.main(verbosity=2)