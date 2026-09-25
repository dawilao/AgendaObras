"""Regressões do ciclo diário de prazos: falha de envio e novas tentativas (catch-up)."""

import datetime
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database
from services.notificador import NotificadorPrazos


class TestCicloDiarioCatchup(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(os.path.join(self.temp_dir.name, 'test_catchup.db'))
        self.obra_id = self.db.criar_obra('Obra Catchup', 'Cliente Teste', 100_000.0, '2026-01-01')
        self.notificador = NotificadorPrazos(self.db, MagicMock())

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_alertas_sem_email_enviado_nao_quebra_verificacao(self):
        """Sem SMTP nenhum e-mail sai; antes isso gerava NameError em total_tarefas."""
        conn = self.db.get_connection()
        conn.execute(
            "UPDATE obra_checklist SET data_limite = '2026-01-01', bloqueado = 0, concluido = 0 WHERE obra_id = ?",
            (self.obra_id,),
        )
        total_pendentes = conn.execute(
            "SELECT COUNT(*) FROM obra_checklist WHERE obra_id = ?", (self.obra_id,)
        ).fetchone()[0]
        conn.commit()
        conn.close()
        self.assertGreater(total_pendentes, 0)

        alerta = {'tipo_alerta': 'critico_atrasado'}
        with patch.object(self.notificador, '_processar_tipo_a', return_value=alerta), \
             patch.object(self.notificador, '_processar_tipo_b', return_value=alerta), \
             patch.object(self.notificador, '_enviar_email_agrupado_por_obra', return_value=False):
            total = self.notificador._verificar_prazos()

        self.assertEqual(total, total_pendentes)

    def test_falhas_esperam_intervalo_e_desistem_no_limite(self):
        """Falhas não repetem em loop: esperam o intervalo e param após o máximo do dia."""
        tz = self.notificador.fuso_horario
        agora = datetime.datetime(2026, 9, 24, 10, 0, tzinfo=tz)  # quinta-feira, após as 08:00
        esperas = []

        def aguardar(alvo):
            esperas.append(alvo)
            if len(esperas) > self.notificador.max_tentativas_dia:
                self.notificador.executando = False

        self.notificador.executando = True
        with patch.object(self.notificador, '_agora_referencia', return_value=agora), \
             patch.object(self.notificador, '_ja_executou_hoje', return_value=False), \
             patch.object(self.notificador, '_executar_ciclo_diario', return_value=False) as ciclo, \
             patch.object(self.notificador, '_aguardar_ate', side_effect=aguardar):
            self.notificador._verificar_loop()

        maximo = self.notificador.max_tentativas_dia
        self.assertEqual(ciclo.call_count, maximo)
        retry = agora + self.notificador.intervalo_retry
        self.assertEqual(esperas[:maximo - 1], [retry] * (maximo - 1))
        # Depois do limite, aguarda o próximo horário agendado (sexta às 08:00).
        self.assertEqual(esperas[-1], self.notificador._horario_alvo_no_dia(datetime.date(2026, 9, 25)))


if __name__ == '__main__':
    unittest.main()
