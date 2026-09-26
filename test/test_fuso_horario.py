"""Fuso do processo fixado em America/Sao_Paulo, independente do fuso do servidor."""

import datetime
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import aplicar_fuso_horario, APP_TIMEZONE_PADRAO


class TestAplicarFusoHorario(unittest.TestCase):

    def setUp(self):
        tz_original = os.environ.get('TZ')

        def restaurar():
            if tz_original is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = tz_original
            if hasattr(time, 'tzset'):
                time.tzset()
        self.addCleanup(restaurar)

    def test_padrao_e_sao_paulo(self):
        with mock.patch.dict(os.environ, {'AGENDA_OBRAS_TIMEZONE': ''}):
            self.assertEqual(aplicar_fuso_horario(), APP_TIMEZONE_PADRAO)

    def test_variavel_de_ambiente_sobrescreve(self):
        with mock.patch.dict(os.environ, {'AGENDA_OBRAS_TIMEZONE': 'America/Manaus'}):
            self.assertEqual(aplicar_fuso_horario(), 'America/Manaus')

    @unittest.skipUnless(hasattr(time, 'tzset'), 'time.tzset só existe em Linux/macOS')
    def test_servidor_em_utc_passa_a_usar_brasilia(self):
        os.environ['TZ'] = 'UTC'
        time.tzset()
        aplicar_fuso_horario('America/Sao_Paulo')
        offset = datetime.datetime.now().astimezone().utcoffset()
        self.assertEqual(offset, datetime.timedelta(hours=-3))


if __name__ == '__main__':
    unittest.main()
