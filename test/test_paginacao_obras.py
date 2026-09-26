"""Paginação da Grade de obras: fatiamento e ajuste da página ao intervalo válido."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.obras_helper import ObrasHelper

POR_PAGINA = 24
OBRAS = list(range(1, 52))  # 51 obras, como na base atual


class TestPaginar(unittest.TestCase):

    def test_primeira_pagina(self):
        itens, pagina, total_paginas, inicio = ObrasHelper.paginar(OBRAS, 1, POR_PAGINA)
        self.assertEqual(itens, list(range(1, 25)))
        self.assertEqual((pagina, total_paginas, inicio), (1, 3, 0))

    def test_ultima_pagina_incompleta(self):
        itens, pagina, total_paginas, inicio = ObrasHelper.paginar(OBRAS, 3, POR_PAGINA)
        self.assertEqual(itens, [49, 50, 51])
        self.assertEqual((pagina, total_paginas, inicio), (3, 3, 48))

    def test_pagina_alem_do_fim_vai_para_a_ultima(self):
        # Ex.: estava na página 3 e um filtro deixou só 10 obras.
        itens, pagina, total_paginas, _ = ObrasHelper.paginar(OBRAS[:10], 3, POR_PAGINA)
        self.assertEqual((pagina, total_paginas), (1, 1))
        self.assertEqual(itens, OBRAS[:10])

    def test_pagina_invalida_vai_para_a_primeira(self):
        itens, pagina, _, _ = ObrasHelper.paginar(OBRAS, 0, POR_PAGINA)
        self.assertEqual(pagina, 1)
        self.assertEqual(itens[0], 1)

    def test_multiplo_exato(self):
        itens, pagina, total_paginas, _ = ObrasHelper.paginar(OBRAS[:48], 2, POR_PAGINA)
        self.assertEqual((pagina, total_paginas, len(itens)), (2, 2, 24))

    def test_lista_vazia(self):
        itens, pagina, total_paginas, inicio = ObrasHelper.paginar([], 5, POR_PAGINA)
        self.assertEqual((itens, pagina, total_paginas, inicio), ([], 1, 1, 0))

    def test_todas_as_obras_aparecem_uma_vez(self):
        vistas = []
        _, _, total_paginas, _ = ObrasHelper.paginar(OBRAS, 1, POR_PAGINA)
        for p in range(1, total_paginas + 1):
            vistas += ObrasHelper.paginar(OBRAS, p, POR_PAGINA)[0]
        self.assertEqual(vistas, OBRAS)


if __name__ == '__main__':
    unittest.main()
