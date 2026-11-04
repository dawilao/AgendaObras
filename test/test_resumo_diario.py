"""
Resumo diário de alertas: um único e-mail por destinatário.

Cobre: agrupamento por destinatário, regras de permissão por item (coordenador,
admin resumido, e-mail crítico, fallback), obras com pendências, falha parcial/total
de envio, escape de HTML, tamanho do e-mail, reiterações por limite e histórico.

Nenhum e-mail real é enviado: EmailService.enviar_email é substituído.
"""

import datetime
import os
import smtplib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database
from db.auth_repo import AuthDatabase
from db.contratos_repo import ContratosDatabase
from services.email_service import EmailService
from services.notificador import GeradorTarefasRecorrentes, NotificadorPrazos

CONTRATO_BA = 'C.E.F BAHIA - 4922.2024'
CONTRATO_AM = 'C.E.F MANAUS - 4569.2024'


class _DummyConfig:
    def __init__(self, fallback=None, critico=''):
        self.email_destinatarios = fallback or []
        self.email_critico = critico


class _Base(unittest.TestCase):
    HOJE = datetime.date(2026, 11, 4)  # quarta-feira

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='agenda_resumo_')
        self.old_env = {k: os.getenv(k) for k in (
            'AGENDA_OBRAS_DB_PATH', 'AGENDA_OBRAS_USERS_DB_PATH', 'AGENDA_OBRAS_CONTRATOS_DB_PATH')}
        os.environ['AGENDA_OBRAS_DB_PATH'] = os.path.join(self.temp_dir.name, 'agendaobras.db')
        os.environ['AGENDA_OBRAS_USERS_DB_PATH'] = os.path.join(self.temp_dir.name, 'users.db')
        os.environ['AGENDA_OBRAS_CONTRATOS_DB_PATH'] = os.path.join(self.temp_dir.name, 'contratos.db')

        self.db = Database(os.environ['AGENDA_OBRAS_DB_PATH'])
        self.auth_db = AuthDatabase(os.environ['AGENDA_OBRAS_USERS_DB_PATH'])
        self.contr_db = ContratosDatabase(os.environ['AGENDA_OBRAS_CONTRATOS_DB_PATH'])

        self.email_service = EmailService(self.db)
        self.email_service.config = _DummyConfig()
        self.enviados = []        # (destinatario, assunto, html)
        self.falhar_para = set()  # e-mails cujo envio deve falhar
        self.email_service.enviar_email = self._fake_enviar
        self.email_service.enviar_emails_em_lote = lambda msgs: [self._fake_enviar(*m) for m in msgs]

        self.notificador = NotificadorPrazos(self.db, self.email_service)
        tz = self.notificador.fuso_horario
        agora = datetime.datetime.combine(self.HOJE, datetime.time(8, 0), tzinfo=tz)
        self._patch_agora = patch.object(self.notificador, '_agora_referencia', return_value=agora)
        self._patch_agora.start()

    def tearDown(self):
        self._patch_agora.stop()
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.temp_dir.cleanup()

    # ---------- helpers ----------

    def _fake_enviar(self, destinatario, assunto, corpo_html):
        self.enviados.append((destinatario, assunto, corpo_html))
        if destinatario in self.falhar_para:
            return (False, 'SMTP fora do ar')
        return (True, 'ok')

    def _obra(self, nome, contrato, com_pendencias=False):
        obra_id = self.db.criar_obra(nome, contrato, 100_000.0, '2026-01-01')
        conn = self.db.get_connection()
        conn.execute('DELETE FROM obra_checklist WHERE obra_id = ?', (obra_id,))
        if com_pendencias:
            conn.execute("UPDATE obras SET status_conclusao_obra = 'com_pendencias' WHERE id = ?", (obra_id,))
        conn.commit()
        conn.close()
        return obra_id

    def _tarefa(self, obra_id, descricao, dias_atraso, tipo='A', tentativas=0, status='pendente'):
        """Cria tarefa com prazo `dias_atraso` dias antes de HOJE."""
        data_limite = (self.HOJE - datetime.timedelta(days=dias_atraso)).isoformat()
        conn = self.db.get_connection()
        cur = conn.execute(
            '''INSERT INTO obra_checklist (obra_id, template_id, descricao, prazo_dias, data_limite, tipo,
                                           tentativas_reiteracao, status_notificacao)
               VALUES (?, 0, ?, 0, ?, ?, ?, ?)''',
            (obra_id, descricao, data_limite, tipo, tentativas, status))
        conn.commit()
        tarefa_id = cur.lastrowid
        conn.close()
        return tarefa_id

    def _usuario(self, email, contratos=(), is_admin=False, critico=True, nome='Usuario'):
        self.auth_db.criar_usuario(nome, 'Teste', email, '123456', is_admin=is_admin,
                                   receber_alerta_critico=critico)
        uid = next(u['id'] for u in self.auth_db.listar_usuarios() if u['email'] == email)
        for c in contratos:
            self.contr_db.vincular_usuario_contrato(uid, c)
        return uid

    def _linha_tarefa(self, tarefa_id):
        conn = self.db.get_connection()
        row = dict(conn.execute('SELECT * FROM obra_checklist WHERE id = ?', (tarefa_id,)).fetchone())
        conn.close()
        return row

    def _historico(self, tarefa_id=None, obra_id=None):
        conn = self.db.get_connection()
        if tarefa_id is not None:
            rows = conn.execute('SELECT * FROM historico_notificacoes WHERE tarefa_id = ?', (tarefa_id,)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM historico_notificacoes WHERE obra_id = ? AND tarefa_id = 0',
                                (obra_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def _por_destinatario(self):
        return {dest: (assunto, html) for dest, assunto, html in self.enviados}


class TestAgrupamentoPorDestinatario(_Base):

    def test_coordenador_com_tres_obras_recebe_um_unico_email(self):
        self._usuario('coord@empresa.com', [CONTRATO_BA], nome='Ana')
        for i in range(3):
            obra = self._obra(f'Obra {i}', CONTRATO_BA)
            self._tarefa(obra, f'Tarefa {i}', dias_atraso=2)

        self.notificador._verificar_prazos()

        self.assertEqual(len(self.enviados), 1)
        destinatario, assunto, html = self.enviados[0]
        self.assertEqual(destinatario, 'coord@empresa.com')  # "Para" individual
        self.assertIn('3 obras', assunto)
        for i in range(3):
            self.assertIn(f'Obra {i}', html)
        self.assertIn('Ana', html)

    def test_coordenadores_de_contratos_diferentes_veem_so_suas_obras(self):
        self._usuario('ba@empresa.com', [CONTRATO_BA])
        self._usuario('am@empresa.com', [CONTRATO_AM])
        self._tarefa(self._obra('Obra Salvador', CONTRATO_BA), 'Tarefa BA', 2)
        self._tarefa(self._obra('Obra Manaus', CONTRATO_AM), 'Tarefa AM', 2)

        self.notificador._verificar_prazos()

        por_dest = self._por_destinatario()
        self.assertEqual(set(por_dest), {'ba@empresa.com', 'am@empresa.com'})
        self.assertIn('Obra Salvador', por_dest['ba@empresa.com'][1])
        self.assertNotIn('Obra Manaus', por_dest['ba@empresa.com'][1])
        self.assertIn('Obra Manaus', por_dest['am@empresa.com'][1])
        self.assertNotIn('Obra Salvador', por_dest['am@empresa.com'][1])

    def test_admin_recebe_versao_resumida_so_com_criticos(self):
        self._usuario('admin@empresa.com', is_admin=True)
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        obra_critica = self._obra('Obra Critica', CONTRATO_BA)
        self._tarefa(obra_critica, 'Atrasada demais', dias_atraso=10)
        self._tarefa(obra_critica, 'Reiteracao comum', dias_atraso=2)
        self._tarefa(self._obra('Obra Tranquila', CONTRATO_BA), 'Outra reiteracao', 2)

        self.notificador._verificar_prazos()

        _, html_admin = self._por_destinatario()['admin@empresa.com']
        self.assertIn('Vers&atilde;o resumida', html_admin)
        self.assertIn('Atrasada demais', html_admin)
        self.assertNotIn('Reiteracao comum', html_admin)
        self.assertNotIn('Obra Tranquila', html_admin)

        _, html_coord = self._por_destinatario()['coord@empresa.com']
        self.assertNotIn('Vers&atilde;o resumida', html_coord)
        self.assertIn('Reiteracao comum', html_coord)
        self.assertIn('Obra Tranquila', html_coord)

    def test_coordenador_sem_alerta_critico_recebe_reiteracoes(self):
        """Antes perdia a obra inteira quando havia qualquer item crítico."""
        self._usuario('coord@empresa.com', [CONTRATO_BA], critico=False)
        obra = self._obra('Obra Mista', CONTRATO_BA)
        self._tarefa(obra, 'Item critico', dias_atraso=10)
        self._tarefa(obra, 'Item reiteracao', dias_atraso=2)

        self.notificador._verificar_prazos()

        _, html = self._por_destinatario()['coord@empresa.com']
        self.assertIn('Item reiteracao', html)
        self.assertNotIn('Item critico', html)

    def test_email_critico_que_tambem_e_coordenador_recebe_uniao(self):
        self.email_service.config = _DummyConfig(critico='chefe@empresa.com')
        self._usuario('chefe@empresa.com', [CONTRATO_BA])
        self._tarefa(self._obra('Obra Propria', CONTRATO_BA), 'Reiteracao propria', 2)
        self._tarefa(self._obra('Obra Alheia', CONTRATO_AM), 'Critico alheio', 10)
        self._tarefa(self._obra('Obra Alheia 2', CONTRATO_AM), 'Reiteracao alheia', 2)

        self.notificador._verificar_prazos()

        enviados_chefe = [e for e in self.enviados if e[0] == 'chefe@empresa.com']
        self.assertEqual(len(enviados_chefe), 1)
        html = enviados_chefe[0][2]
        self.assertIn('Reiteracao propria', html)
        self.assertIn('Critico alheio', html)
        self.assertNotIn('Reiteracao alheia', html)
        self.assertNotIn('Vers&atilde;o resumida', html)

    def test_obra_com_pendencias_entra_no_resumo_sem_email_separado(self):
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        obra_pend = self._obra('Obra Pendente', CONTRATO_BA, com_pendencias=True)
        self._tarefa(self._obra('Obra Normal', CONTRATO_BA), 'Tarefa normal', 2)

        self.notificador._verificar_prazos()

        self.assertEqual(len(self.enviados), 1)
        _, assunto, html = self.enviados[0]
        self.assertIn('Obra Pendente', html)
        self.assertIn('pend&ecirc;ncias em aberto', html)
        self.assertIn('[CRÍTICO]', assunto)
        historico = self._historico(obra_id=obra_pend)
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0]['tipo_notificacao'], 'obra_pendencias')
        self.assertEqual(historico[0]['sucesso'], 1)

    def test_sem_usuarios_usa_fallback(self):
        self.email_service.config = _DummyConfig(fallback=['geral@empresa.com'])
        self._tarefa(self._obra('Obra X', CONTRATO_BA), 'Tarefa X', 2)

        self.notificador._verificar_prazos()

        self.assertEqual([e[0] for e in self.enviados], ['geral@empresa.com'])
        self.assertIn('Tarefa X', self.enviados[0][2])


class TestDestinatariosSoCriticos(_Base):
    """Admins e e-mail crítico da config: recebem apenas críticos, prazo fixo e pendências."""

    def test_email_critico_sozinho_recebe_resumido_de_todas_as_obras(self):
        self.email_service.config = _DummyConfig(critico='diretoria@empresa.com')
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        self._tarefa(self._obra('Obra BA', CONTRATO_BA), 'Critico BA', dias_atraso=10)
        obra_am = self._obra('Obra AM', CONTRATO_AM)  # contrato sem coordenador
        self._tarefa(obra_am, 'Critico AM', dias_atraso=10)
        self._tarefa(obra_am, 'Reiteracao AM', dias_atraso=2)

        self.notificador._verificar_prazos()

        assunto, html = self._por_destinatario()['diretoria@empresa.com']
        self.assertIn('[CRÍTICO]', assunto)
        self.assertIn('Vers&atilde;o resumida', html)
        self.assertIn('Ol&aacute;,', html)  # sem nome cadastrado
        self.assertIn('Critico BA', html)
        self.assertIn('Critico AM', html)
        self.assertNotIn('Reiteracao AM', html)

    def test_admin_recebe_prazo_fixo_e_pendencias(self):
        self._usuario('admin@empresa.com', is_admin=True, nome='Chefe')
        self._tarefa(self._obra('Obra Prazo Fixo', CONTRATO_BA), 'Entrega ART', dias_atraso=0, tipo='B')
        self._obra('Obra Pendente', CONTRATO_BA, com_pendencias=True)

        self.notificador._verificar_prazos()

        assunto, html = self._por_destinatario()['admin@empresa.com']
        self.assertIn('[CRÍTICO]', assunto)
        self.assertIn('Entrega ART', html)
        self.assertIn('&Uacute;LTIMO DIA', html)
        self.assertIn('Obra Pendente', html)
        self.assertIn('pend&ecirc;ncias em aberto', html)
        self.assertIn('Chefe', html)

    def test_admin_vinculado_a_contrato_nao_recebe_reiteracao(self):
        self._usuario('admin@empresa.com', [CONTRATO_BA], is_admin=True)
        obra = self._obra('Obra', CONTRATO_BA)
        self._tarefa(obra, 'Critico', dias_atraso=10)
        self._tarefa(obra, 'Reiteracao', dias_atraso=2)

        self.notificador._verificar_prazos()

        _, html = self._por_destinatario()['admin@empresa.com']
        self.assertIn('Critico', html)
        self.assertNotIn('Reiteracao', html)
        self.assertIn('Vers&atilde;o resumida', html)

    def test_admin_com_alerta_critico_desligado_nao_recebe_nada(self):
        self._usuario('admin@empresa.com', is_admin=True, critico=False)
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        self._tarefa(self._obra('Obra', CONTRATO_BA), 'Critico', dias_atraso=10)
        self._obra('Obra Pendente', CONTRATO_BA, com_pendencias=True)

        self.notificador._verificar_prazos()

        self.assertEqual([e[0] for e in self.enviados], ['coord@empresa.com'])

    def test_dia_sem_critico_nao_gera_email_para_quem_so_recebe_critico(self):
        self.email_service.config = _DummyConfig(critico='diretoria@empresa.com')
        self._usuario('admin@empresa.com', is_admin=True)
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        self._tarefa(self._obra('Obra', CONTRATO_BA), 'Reiteracao', dias_atraso=2)

        self.notificador._verificar_prazos()

        self.assertEqual([e[0] for e in self.enviados], ['coord@empresa.com'])

    def test_critico_entregue_so_ao_admin_marca_tarefa(self):
        """Coordenador desligou críticos: o crítico chega só ao admin e conta como notificado."""
        self._usuario('admin@empresa.com', is_admin=True)
        self._usuario('coord@empresa.com', [CONTRATO_BA], critico=False)
        tarefa = self._tarefa(self._obra('Obra', CONTRATO_BA), 'Critico', dias_atraso=10)

        self.notificador._verificar_prazos()

        self.assertEqual([e[0] for e in self.enviados], ['admin@empresa.com'])
        self.assertTrue(self._linha_tarefa(tarefa)['ultima_notificacao'].startswith(self.HOJE.isoformat()))
        historico = self._historico(tarefa_id=tarefa)
        self.assertEqual(historico[0]['sucesso'], 1)
        self.assertEqual(historico[0]['destinatarios'], 'admin@empresa.com')

    def test_falha_no_unico_destinatario_critico_nao_marca_tarefa(self):
        self._usuario('admin@empresa.com', is_admin=True)
        self._usuario('coord@empresa.com', [CONTRATO_BA], critico=False)
        self.falhar_para = {'admin@empresa.com'}
        tarefa = self._tarefa(self._obra('Obra', CONTRATO_BA), 'Critico', dias_atraso=10)

        # Único resumo do dia falhou: o ciclo vira erro para o loop tentar de novo
        with self.assertRaises(RuntimeError):
            self.notificador._verificar_prazos()

        self.assertIsNone(self._linha_tarefa(tarefa)['ultima_notificacao'])
        historico = self._historico(tarefa_id=tarefa)
        self.assertEqual(historico[0]['sucesso'], 0)
        self.assertIn('admin@empresa.com: SMTP fora do ar', historico[0]['mensagem_erro'])


class TestResultadosDeEnvio(_Base):

    def test_falha_parcial_marca_tarefa_e_historico_so_com_quem_recebeu(self):
        self._usuario('ok@empresa.com', [CONTRATO_BA])
        self._usuario('falha@empresa.com', [CONTRATO_BA])
        self.falhar_para = {'falha@empresa.com'}
        tarefa = self._tarefa(self._obra('Obra', CONTRATO_BA), 'Tarefa', dias_atraso=2)

        self.notificador._verificar_prazos()

        linha = self._linha_tarefa(tarefa)
        self.assertEqual(linha['tentativas_reiteracao'], 1)
        self.assertTrue(linha['ultima_notificacao'].startswith(self.HOJE.isoformat()))
        historico = self._historico(tarefa_id=tarefa)
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0]['sucesso'], 1)
        self.assertEqual(historico[0]['destinatarios'], 'ok@empresa.com')

    def test_falha_total_nao_marca_tarefa_e_registra_erro(self):
        self._usuario('falha@empresa.com', [CONTRATO_BA])
        self.falhar_para = {'falha@empresa.com'}
        tarefa = self._tarefa(self._obra('Obra', CONTRATO_BA), 'Tarefa', dias_atraso=2)

        # Nenhum resumo saiu: o ciclo vira erro para o loop tentar de novo
        with self.assertRaises(RuntimeError) as ctx:
            self.notificador._verificar_prazos()
        self.assertIn('SMTP fora do ar', str(ctx.exception))

        linha = self._linha_tarefa(tarefa)
        self.assertEqual(linha['tentativas_reiteracao'], 0)
        self.assertIsNone(linha['ultima_notificacao'])
        historico = self._historico(tarefa_id=tarefa)
        self.assertEqual(len(historico), 1)
        self.assertEqual(historico[0]['sucesso'], 0)
        self.assertIn('SMTP fora do ar', historico[0]['mensagem_erro'])

    def test_historico_aceita_destinatario_em_texto(self):
        obra = self._obra('Obra', CONTRATO_BA)
        ok = self.notificador._registrar_historico_com_retry(obra, 0, 'teste', 'unico@empresa.com', True)
        self.assertTrue(ok)
        self.assertEqual(self._historico(obra_id=obra)[0]['destinatarios'], 'unico@empresa.com')


class TestObraConcluidaSemAlerta(_Base):
    """Obra concluída não gera alerta de tarefa; 'com pendências' mantém só a faixa de pendências."""

    def _marcar(self, obra_id, status, status_conclusao):
        conn = self.db.get_connection()
        conn.execute('UPDATE obras SET status = ?, status_conclusao_obra = ? WHERE id = ?',
                     (status, status_conclusao, obra_id))
        conn.commit()
        conn.close()

    def test_obra_sem_pendencias_fica_fora_do_resumo(self):
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        concluida = self._obra('Obra Concluida', CONTRATO_BA)
        self._tarefa(concluida, 'Tarefa esquecida', dias_atraso=10)
        self._marcar(concluida, 'Concluída', 'sem_pendencias')
        self._tarefa(self._obra('Obra Ativa', CONTRATO_BA), 'Tarefa ativa', dias_atraso=2)

        self.notificador._verificar_prazos()

        _, html = self._por_destinatario()['coord@empresa.com']
        self.assertIn('Tarefa ativa', html)
        self.assertNotIn('Obra Concluida', html)
        self.assertNotIn('Tarefa esquecida', html)

    def test_obra_com_pendencias_mostra_so_a_faixa(self):
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        obra = self._obra('Obra Pendente', CONTRATO_BA, com_pendencias=True)
        tarefa = self._tarefa(obra, 'Tarefa esquecida', dias_atraso=10)
        self._marcar(obra, 'Concluída', 'com_pendencias')

        self.notificador._verificar_prazos()

        _, html = self._por_destinatario()['coord@empresa.com']
        self.assertIn('Obra Pendente', html)
        self.assertIn('pend&ecirc;ncias em aberto', html)
        self.assertNotIn('Tarefa esquecida', html)
        self.assertEqual(self._historico(tarefa_id=tarefa), [])

    def test_obra_legada_concluida_sem_finalizacao_fica_fora(self):
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        obra = self._obra('Obra Legada', CONTRATO_BA)
        self._tarefa(obra, 'Tarefa legada', dias_atraso=10)
        self._marcar(obra, 'Concluída', None)

        self.notificador._verificar_prazos()

        self.assertEqual(self.enviados, [])

    def test_gerador_mensal_ignora_obra_com_pendencias(self):
        conn = self.db.get_connection()
        cur = conn.execute(
            "INSERT INTO checklist_templates (nome, ordem, prazo_dias, tipo, recorrencia, dia_referencia_mensal) "
            "VALUES ('RELATÓRIO MENSAL', 99, 0, 'B', 'mensal', 5)")
        template_id = cur.lastrowid
        conn.commit()
        conn.close()
        ativa = self._obra('Obra Ativa', CONTRATO_BA)
        pendente = self._obra('Obra Pendente', CONTRATO_BA)
        self._marcar(ativa, 'Em Andamento', None)
        self._marcar(pendente, 'Não Iniciada', 'com_pendencias')  # inconsistência real do banco

        GeradorTarefasRecorrentes(self.db).gerar_tarefas_mensais()

        conn = self.db.get_connection()
        obras_com_tarefa = {r[0] for r in conn.execute(
            'SELECT obra_id FROM obra_checklist WHERE template_id = ?', (template_id,))}
        conn.close()
        self.assertIn(ativa, obras_com_tarefa)
        self.assertNotIn(pendente, obras_com_tarefa)


class TestGravacaoEmLote(_Base):

    def test_resultados_gravados_numa_unica_transacao(self):
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        obra = self._obra('Obra', CONTRATO_BA)
        reit = self._tarefa(obra, 'Reiteracao', dias_atraso=2)
        prazo_fixo = self._tarefa(obra, 'Prazo fixo', dias_atraso=0, tipo='B')
        critica = self._tarefa(obra, 'Critica', dias_atraso=10)

        original = self.notificador._gravar_resultados
        with patch.object(self.notificador, '_gravar_resultados', side_effect=original) as gravar:
            self.notificador._verificar_prazos()

        self.assertEqual(gravar.call_count, 1)
        self.assertEqual(self._linha_tarefa(reit)['tentativas_reiteracao'], 1)
        self.assertEqual(self._linha_tarefa(reit)['status_notificacao'], 'alerta')
        self.assertEqual(self._linha_tarefa(prazo_fixo)['status_notificacao'], 'critico')
        self.assertEqual(self._linha_tarefa(critica)['status_notificacao'], 'atrasado')
        for tarefa in (reit, prazo_fixo, critica):
            historico = self._historico(tarefa_id=tarefa)
            self.assertEqual(len(historico), 1)
            self.assertEqual(historico[0]['destinatarios'], 'coord@empresa.com')
            self.assertTrue(historico[0]['data_envio'].startswith(self.HOJE.isoformat()))

    def test_falha_parcial_nao_dispara_nova_tentativa(self):
        self._usuario('ok@empresa.com', [CONTRATO_BA])
        self._usuario('falha@empresa.com', [CONTRATO_BA])
        self.falhar_para = {'falha@empresa.com'}
        self._tarefa(self._obra('Obra', CONTRATO_BA), 'Tarefa', dias_atraso=2)

        total = self.notificador._verificar_prazos()  # não lança

        self.assertEqual(total, 1)


class _SmtpConfig:
    smtp_server = 'smtp.teste.local'
    smtp_port = 587
    usar_tls = True
    smtp_user = 'robo@empresa.com'
    smtp_password = 'segredo'
    email_remetente = 'robo@empresa.com'
    email_destinatarios = []
    email_critico = ''

    def __init__(self, configurado=True):
        self._configurado = configurado

    def is_configured(self):
        return self._configurado


class TestEnvioSmtpEmLote(unittest.TestCase):
    """Uma conexão SMTP para todos os resumos (smtplib substituído; nada sai de verdade)."""

    MENSAGENS = [(f'p{i}@empresa.com', f'Assunto {i}', '<p>x</p>') for i in range(3)]

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix='agenda_smtp_')
        self.service = EmailService(Database(os.path.join(self.temp_dir.name, 'a.db')))
        self.service.config = _SmtpConfig()
        # Falhas simuladas não devem gravar arquivos na pasta real de erros
        self._patch_log = patch('services.email_service.log_error')
        self._patch_log.start()

    def tearDown(self):
        self._patch_log.stop()
        self.temp_dir.cleanup()

    def test_uma_conexao_e_um_login_para_todas_as_mensagens(self):
        with patch('services.email_service.smtplib.SMTP') as smtp:
            servidor = smtp.return_value
            resultados = self.service.enviar_emails_em_lote(self.MENSAGENS)

        self.assertEqual(resultados, [(True, 'Email enviado com sucesso')] * 3)
        self.assertEqual(smtp.call_count, 1)
        self.assertEqual(servidor.login.call_count, 1)
        self.assertEqual(servidor.send_message.call_count, 3)
        # Cada mensagem vai só para o seu destinatário
        destinos = [c.kwargs['to_addrs'] for c in servidor.send_message.call_args_list]
        self.assertEqual(destinos, [[m[0]] for m in self.MENSAGENS])

    def test_reconecta_quando_a_conexao_cai(self):
        with patch('services.email_service.smtplib.SMTP') as smtp:
            servidor = smtp.return_value
            servidor.send_message.side_effect = [
                None, smtplib.SMTPServerDisconnected('caiu'), None, None]
            resultados = self.service.enviar_emails_em_lote(self.MENSAGENS)

        self.assertTrue(all(ok for ok, _ in resultados))
        self.assertEqual(smtp.call_count, 2)  # conexão inicial + reconexão
        self.assertEqual(servidor.send_message.call_count, 4)

    def test_queda_persistente_reprova_so_aquela_mensagem(self):
        with patch('services.email_service.smtplib.SMTP') as smtp:
            servidor = smtp.return_value
            servidor.send_message.side_effect = [
                None, smtplib.SMTPServerDisconnected('caiu'), smtplib.SMTPServerDisconnected('caiu'), None]
            resultados = self.service.enviar_emails_em_lote(self.MENSAGENS)

        self.assertEqual([ok for ok, _ in resultados], [True, False, True])

    def test_falha_de_autenticacao_reprova_todas(self):
        with patch('services.email_service.smtplib.SMTP') as smtp:
            smtp.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b'senha errada')
            resultados = self.service.enviar_emails_em_lote(self.MENSAGENS)

        self.assertEqual(len(resultados), 3)
        self.assertFalse(any(ok for ok, _ in resultados))
        self.assertIn('autentica', resultados[0][1])

    def test_smtp_nao_configurado_reprova_todas_sem_conectar(self):
        self.service.config = _SmtpConfig(configurado=False)
        with patch('services.email_service.smtplib.SMTP') as smtp:
            resultados = self.service.enviar_emails_em_lote(self.MENSAGENS)

        smtp.assert_not_called()
        self.assertFalse(any(ok for ok, _ in resultados))

    def test_enviar_email_avulso_fecha_conexao(self):
        with patch('services.email_service.smtplib.SMTP') as smtp:
            ok, _ = self.service.enviar_email('a@empresa.com', 'Assunto', '<p>x</p>')

        self.assertTrue(ok)
        smtp.return_value.quit.assert_called_once()


class TestConteudoDoEmail(_Base):

    def _obra_resumo(self, nome, alertas, com_pendencias=False):
        tarefas = {}
        for cat, alerta in alertas:
            tarefas.setdefault(cat, []).append(alerta)
        return {'obra_id': 1, 'info': {'nome_contrato': nome, 'cliente': CONTRATO_BA, 'observacoes': ''},
                'tarefas': tarefas, 'com_pendencias': com_pendencias}

    def _alerta(self, descricao, dias=3, novo=False):
        data = (self.HOJE - datetime.timedelta(days=dias)).isoformat()
        return {'tarefa_id': 1, 'descricao': descricao, 'data_limite': data, 'dias_diff': dias, 'novo': novo}

    def test_descricao_e_nome_sao_escapados(self):
        obra = self._obra_resumo('Obra <A&B>', [('reiteracao_1', self._alerta('Tarefa <b>&"x"'))])
        _, html = self.email_service.criar_email_resumo_diario('Zé <x>', [obra], self.HOJE)
        self.assertNotIn('<b>&"x"', html)
        self.assertIn('&lt;b&gt;&amp;&quot;x&quot;', html)
        self.assertNotIn('Obra <A&B>', html)
        self.assertNotIn('Zé <x>', html)

    def test_selo_novo_somente_para_alerta_novo(self):
        obra = self._obra_resumo('Obra', [
            ('reiteracao_1', self._alerta('Tarefa Nova', novo=True)),
            ('reiteracao_2', self._alerta('Tarefa Antiga', novo=False)),
        ])
        _, html = self.email_service.criar_email_resumo_diario('', [obra], self.HOJE)
        self.assertEqual(html.count('class="s nv"'), 1)
        self.assertIn('Tarefa Nova<span class="s nv">NOVO</span>', html)

    def test_novo_vem_do_status_notificacao(self):
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        obra = self._obra('Obra', CONTRATO_BA)
        self._tarefa(obra, 'Primeira vez', dias_atraso=10, status='pendente')
        self._tarefa(obra, 'Repetida', dias_atraso=11, status='atrasado')

        _, resumos = self.notificador.gerar_resumos_do_dia()

        alertas = {a['descricao']: a for o in resumos['coord@empresa.com']['obras']
                   for lista in o['tarefas'].values() for a in lista}
        self.assertTrue(alertas['Primeira vez']['novo'])
        self.assertFalse(alertas['Repetida']['novo'])

    def test_tamanho_com_30_obras_e_10_tarefas_cada_abaixo_de_100kb(self):
        categorias = ['critico_atrasado', 'tipo_b', 'reiteracao_3', 'reiteracao_2', 'reiteracao_1']
        obras = [
            self._obra_resumo(
                f'AGÊNCIA {i:02d} - REFORMA GERAL DO PAVIMENTO TÉRREO',
                [(categorias[j % 5], self._alerta(f'SOLICITAÇÃO DE ACESSO / RELATÓRIO FOTOGRÁFICO {j}', dias=j + 1,
                                                  novo=j % 3 == 0))
                 for j in range(10)],
                com_pendencias=i % 7 == 0,
            )
            for i in range(30)
        ]
        _, html = self.email_service.criar_email_resumo_diario('Coordenador', obras, self.HOJE)
        tamanho = len(html.encode('utf-8'))
        self.assertLess(tamanho, 100 * 1024, f'HTML com {tamanho / 1024:.1f} KB')

    def test_gerar_resumos_nao_grava_nada(self):
        self._usuario('coord@empresa.com', [CONTRATO_BA])
        tarefa = self._tarefa(self._obra('Obra', CONTRATO_BA), 'Tarefa', dias_atraso=2)

        obras, resumos = self.notificador.gerar_resumos_do_dia()

        self.assertIn('coord@empresa.com', resumos)
        self.assertEqual(self.enviados, [])
        self.assertEqual(self._linha_tarefa(tarefa)['tentativas_reiteracao'], 0)
        self.assertEqual(self._historico(tarefa_id=tarefa), [])


class TestReiteracaoPorLimite(_Base):

    def _alerta(self, dias_diff, tentativas=0, recorrencia=None):
        tarefa = {
            'id': 1, 'obra_id': 1, 'descricao': 'T', 'data_limite': '2026-11-01',
            'tentativas_reiteracao': tentativas, 'ultima_notificacao': None, 'tipo_recorrencia': recorrencia,
        }
        return self.notificador._processar_tipo_a(None, tarefa, dias_diff)

    def assertAlerta(self, alerta, tipo, nova_tentativa=None):
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta['tipo_alerta'], tipo)
        if nova_tentativa is not None:
            self.assertEqual(alerta['nova_tentativa'], nova_tentativa)

    def test_limites_padrao(self):
        self.assertIsNone(self._alerta(1))
        self.assertAlerta(self._alerta(2), 'reiteracao_1', 1)
        self.assertAlerta(self._alerta(3, tentativas=0), 'reiteracao_1', 1)  # dia 2 perdido
        self.assertIsNone(self._alerta(3, tentativas=1))                     # já reiterou
        self.assertAlerta(self._alerta(5, tentativas=0), 'reiteracao_2', 2)
        self.assertAlerta(self._alerta(6, tentativas=2), 'reiteracao_3', 3)
        self.assertIsNone(self._alerta(6, tentativas=3))
        self.assertAlerta(self._alerta(7, tentativas=0), 'critico_atrasado')

    def test_fim_de_semana_nao_pula_reiteracao(self):
        """Prazo na quinta, 2º dia cai no sábado: na segunda (dd=4) sai a 2ª reiteração."""
        self.assertAlerta(self._alerta(4, tentativas=0), 'reiteracao_2', 2)

    def test_confirmacao_de_medicao(self):
        self.assertAlerta(self._alerta(1, 0, 'confirmacao'), 'reiteracao_1', 1)   # dia 11
        self.assertAlerta(self._alerta(2, 0, 'confirmacao'), 'reiteracao_2', 2)   # dia 12 sem a 1ª
        self.assertIsNone(self._alerta(2, 2, 'confirmacao'))
        self.assertAlerta(self._alerta(4, 2, 'confirmacao'), 'critico_atrasado', 3)  # dia 14
        # Confirmação do mês anterior ainda aberta continua crítica (antes silenciava até o dia 13)
        self.assertAlerta(self._alerta(25, 3, 'confirmacao'), 'critico_atrasado', 3)


if __name__ == '__main__':
    unittest.main()
