import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from comunicacoes import runtime
from comunicacoes.encaixe import encaixar, contadores, categoria, uf_contrato, avisos_por_obra, TOPIC_ICONS
from comunicacoes.store import MailStore
from test_comunicacoes import mail


class EncaixeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = MailStore(Path(self.tmp.name) / 'test.db', Path(self.tmp.name) / 'arquivos')
        self.store.save_work('1', 'Medina', '03738/2026', ['MEDINA'], True, 'admin')
        self.store.save_work('2', 'Almenara', '00744/2026', ['ALMENARA'], True, 'admin')
        self.store.save_work('3', 'Almenara', '00999/2026', ['ALMENARA'], True, 'admin')

    def add(self, **kw):
        uid = str(len(self.store.messages()) + 1)
        kw.setdefault('mid', f'<m{uid}@example.invalid>')
        return self.store.import_message(mail(**kw), ('test', 'INBOX', '1', uid))[0]

    def matches(self):
        return encaixar(self.store.conversation_rows(), self.store.works())

    def test_ic_completo_encaixa_sem_contar_como_vinculo_seguro(self):
        mid = self.add()
        match = self.matches()[mid]
        self.assertEqual((match['bucket'], match['work']), ('work', '1'))
        self.assertFalse(match.get('coordinator_ok'))
        counts = contadores(self.matches().values())
        self.assertEqual((counts['confirmed'], counts['placed']), (0, 1))

    def test_ok_humano_vira_vinculo_seguro(self):
        mid = self.add()
        self.store.review(mid, '1', 'usuario:1', 'OK coordenador encaixe')
        match = self.matches()[mid]
        self.assertTrue(match['coordinator_ok'])
        self.assertEqual(contadores(self.matches().values())['confirmed'], 1)

    def test_mesma_cidade_com_ics_diferentes_fica_em_obras_distintas(self):
        a = self.add(subject='ALMENARA IC 00744/2026 projeto')
        b = self.add(subject='ALMENARA IC 00999/2026 projeto')
        c = self.add(subject='ALMENARA solicitação')
        found = self.matches()
        self.assertEqual(found[a]['work'], '2')
        self.assertEqual(found[b]['work'], '3')
        self.assertIsNone(found[c]['work'])

    def test_resposta_herda_obra_da_mensagem_segura(self):
        self.add(mid='<origem@example.invalid>')
        reply = self.add(subject='RES: documento', body='Segue retorno.', ref='<origem@example.invalid>')
        self.assertEqual(self.matches()[reply]['work'], '1')

    def test_divulgacao_vai_para_provavel_spam(self):
        mid = self.add(subject='Workshop de instalações', body='Inscreva-se no evento.')
        self.assertEqual(self.matches()[mid]['bucket'], 'spam')

    def test_spam_lixeira_e_restauracao_preservam_a_decisao(self):
        mid = self.add()
        self.store.mark_spam(mid, 'usuario:1')
        self.assertEqual(self.matches()[mid]['bucket'], 'spam')
        self.store.review(mid, None, 'usuario:1', 'Enviado à lixeira pessoal.')
        self.assertEqual(self.matches()[mid]['bucket'], 'trash')
        self.store.relocate(mid, None, 'usuario:1', 'Restaurado.')
        self.store.reprocess('usuario:1')  # Reprocessar não desfaz a decisão manual.
        match = self.matches()[mid]
        self.assertEqual((match['bucket'], match['work']), ('pending', None))
        self.assertEqual(contadores(self.matches().values())['unassigned'], 1)
        actions = [a['action'] for a in self.store.detail(mid)[2]]
        self.assertIn('spam', actions)
        self.assertIn('realocacao', actions)

    def test_realocar_aguarda_ok(self):
        mid = self.add()
        self.store.relocate(mid, '2', 'usuario:1')
        match = self.matches()[mid]
        self.assertEqual((match['bucket'], match['work']), ('pending', '2'))
        self.assertFalse(match.get('coordinator_ok'))
        with self.assertRaises(ValueError):
            self.store.relocate(mid, 'inexistente', 'usuario:1')

    def test_aviso_automatico_fica_fora_dos_contadores(self):
        counts = contadores([dict(bucket='tecnico', work=None)])
        self.assertEqual(sum(counts.values()), 0)

    def test_avisos_de_email_grande_vao_para_a_obra(self):
        skipped = [dict(subject='MEDINA IC 03738/2026 fotos', sender='a@caixa.gov.br'),
                   dict(subject='Sem relação', sender='x@example.invalid'), dict(subject=None, sender=None)]
        by_work, unmatched = avisos_por_obra(skipped, self.store.works())
        self.assertEqual(len(by_work['1']), 1)
        self.assertEqual(len(unmatched), 2)

    def test_uf_do_contrato(self):
        self.assertEqual(uf_contrato('C.E.F MINAS GERAIS - 8756.2025'), ('MG', '8756.2025'))
        self.assertEqual(uf_contrato('C.E.F SERGIPE ALAGOAS - 111.2026'), ('SE/AL', '111.2026'))
        self.assertEqual(uf_contrato('C.E.F PIAUI - 9218.2025')[0], 'PI')
        self.assertEqual(uf_contrato('C.E.F NITERÓI - 9852.2025')[0], 'RJ')
        self.assertEqual(uf_contrato('Contrato novo'), ('?', 'Contrato novo'))
        self.assertEqual(uf_contrato(None), ('?', 'Contrato a conferir'))

    def test_icones_por_assunto(self):
        self.assertEqual(TOPIC_ICONS['Medições'], 'straighten')
        self.assertEqual(TOPIC_ICONS['Assinatura de contrato'], 'draw')
        self.assertEqual(TOPIC_ICONS['Seguro e garantia'], 'verified_user')


def mail_from(sender, subject, body='Documento.', mid=None):
    from email.message import EmailMessage
    msg = EmailMessage()
    msg['Subject'], msg['From'], msg['To'] = subject, sender, 'to@example.invalid'
    msg['Message-ID'] = mid or f'<{abs(hash((sender, subject)))}@example.invalid>'
    msg['Date'] = 'Wed, 23 Sep 2026 10:00:00 -0300'
    msg.set_content(body)
    return msg.as_bytes()


class FluxoTests(unittest.TestCase):
    """Restaurar sem congelar, remetente sempre spam e OK da equipe adotado."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = MailStore(root / 'a.db', root / 'arquivos')
        self.store.save_work('1', 'Medina', '03738/2026', ['MEDINA'], True, 'admin')
        self.uid = 0

    def add(self, raw, store=None):
        self.uid += 1
        return (store or self.store).import_message(raw, ('test', 'INBOX', '1', str(self.uid)))[0]

    def matches(self):
        return encaixar(self.store.conversation_rows(), self.store.works(), self.store.spam_senders())

    def test_nao_e_spam_volta_a_ser_classificado(self):
        mid = self.add(mail_from('eventos@crea.example', 'Convite workshop PARAISO', 'Inscreva-se no evento.'))
        self.assertEqual(self.matches()[mid]['bucket'], 'spam')
        self.store.restore([mid], 'usuario:1')
        self.assertEqual(self.store.detail(mid)[0]['reviewed'], 0)
        self.assertEqual(categoria(self.matches()[mid]), 'unassigned')
        # Cadastrar a obra depois: o e-mail restaurado se encaixa sozinho, sem voltar ao spam.
        self.store.save_work('9', 'Paraíso', '', ['PARAISO'], False, 'admin')
        self.store.reprocess('usuario:1')
        self.assertEqual(self.matches()[mid]['work'], '9')
        self.store.mark_spam(mid, 'usuario:1')
        self.assertEqual(self.matches()[mid]['bucket'], 'spam')

    def test_restaurar_da_lixeira(self):
        mid = self.add(mail(subject='MEDINA IC 03738/2026 medição'))
        self.store.review(mid, None, 'usuario:1', 'Enviado à lixeira pessoal.')
        self.store.restore([mid], 'usuario:1')
        self.assertEqual((self.matches()[mid]['bucket'], self.matches()[mid]['work']), ('work', '1'))

    def test_remetente_sempre_spam(self):
        loja = self.add(mail_from('ofertas@loja.example', 'Promoção de armários'))
        segura = self.add(mail_from('ofertas@loja.example', 'MEDINA IC 03738/2026 nota'))
        self.store.add_spam_sender('Ofertas@Loja.example', 'usuario:1')
        found = self.matches()
        self.assertEqual(found[loja]['bucket'], 'spam')
        self.assertEqual(found[segura]['work'], '1')  # IC seguro vence a regra.
        self.store.restore([loja], 'usuario:1')
        self.assertNotEqual(self.matches()[loja]['bucket'], 'spam')  # "Não é spam" vence a regra.
        self.store.remove_spam_sender('ofertas@loja.example', 'usuario:1')
        self.assertEqual(self.store.spam_senders(), [])

    def test_ok_reclassifica_so_as_respostas(self):
        origem = self.add(mail_from('fiscal@caixa.gov.br', 'Vistoria agendada', 'Sem IC.', '<origem@x>'))
        resposta = self.add(mail(subject='RES: Vistoria agendada', body='Confirmado.', mid='<resp@x>', ref='<origem@x>'))
        self.store.review(origem, '1', 'usuario:1', 'OK do coordenador: vínculo confirmado.')
        self.store.reprocess_replies('usuario:1', [origem])
        # A resposta herda a obra pelos cabeçalhos, sem reprocessar a caixa inteira.
        self.assertEqual(self.store.detail(resposta)[0]['obra_id'], '1')
        self.store.reprocess_replies('usuario:1', [])  # Sem confirmadas: nada a fazer.

    def test_restaurar_em_lote(self):
        a = self.add(mail_from('x@loja.example', 'Workshop A', 'Inscreva-se no evento.'))
        b = self.add(mail_from('y@loja.example', 'Workshop B', 'Inscreva-se no evento.'))
        self.store.restore([a, b], 'usuario:1')
        self.assertEqual({self.store.detail(m)[0]['not_spam'] for m in (a, b)}, {1})
        self.store.restore([], 'usuario:1')

    def test_regra_recusa_caixa_e_mach(self):
        for address in ('fiscal@caixa.gov.br', 'equipe@machengenharia.com.br', 'sem-arroba'):
            with self.assertRaises(ValueError):
                self.store.add_spam_sender(address, 'usuario:1')

    def test_ok_humano_da_equipe_vale_para_o_colega(self):
        from comunicacoes.publishing import adopt_team_links, publish_message
        root = Path(self.tmp.name)
        shared = MailStore(root / 'equipe.db', root / 'arquivos')
        colega = MailStore(root / 'b.db', root / 'arquivos')
        colega.save_work('1', 'Medina', '03738/2026', ['MEDINA'], True, 'admin')
        raw = mail(subject='MEDINA IC 03738/2026 medição', mid='<mesma@example.invalid>')
        mine, theirs = self.add(raw), self.add(raw, colega)
        colega.review(theirs, '1', 'usuario:2', 'OK do coordenador: vínculo confirmado.')
        publish_message(colega, shared, theirs, 'usuario:2', {'1'})
        self.assertEqual(adopt_team_links(self.store, shared, 'usuario:1', set()), 0)  # Sem acesso à obra.
        self.assertEqual(adopt_team_links(self.store, shared, 'usuario:1', {'1'}), 1)
        self.assertEqual(categoria(self.matches()[mine]), 'confirmed')
        self.assertEqual(len(shared.messages()), 1)  # Nenhuma cópia nova.
        self.assertEqual(adopt_team_links(self.store, shared, 'usuario:1', {'1'}), 0)

    def test_publicacao_automatica_nao_e_adotada(self):
        from comunicacoes.publishing import adopt_team_links, publish_message
        root = Path(self.tmp.name)
        shared = MailStore(root / 'equipe.db', root / 'arquivos')
        colega = MailStore(root / 'b.db', root / 'arquivos')
        colega.save_work('1', 'Medina', '03738/2026', ['MEDINA'], True, 'admin')
        raw = mail(subject='MEDINA IC 03738/2026 medição', mid='<auto@example.invalid>')
        self.add(raw)
        theirs = self.add(raw, colega)  # Vinculada automaticamente pelo IC confirmado.
        publish_message(colega, shared, theirs, 'importacao', {'1'}, automatic=True)
        self.assertEqual(adopt_team_links(self.store, shared, 'usuario:1', {'1'}), 0)


class PermissaoOkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / 'obras.db')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE obras (id INTEGER PRIMARY KEY, nome_contrato TEXT, cliente TEXT, coordenador_id INTEGER)')
            db.execute("INSERT INTO obras VALUES (1, 'Medina', 'C.E.F MINAS GERAIS - 8756.2025', 7)")
            db.execute("INSERT INTO obras VALUES (2, 'Almenara', 'C.E.F MINAS GERAIS - 8756.2025', NULL)")
        self.users = {'1': {'is_admin': 1}, '7': {'is_admin': 0}, '8': {'is_admin': 0}}
        auth = patch('db.auth_repo.AuthDatabase')
        contracts = patch('db.contratos_repo.ContratosDatabase')
        self.addCleanup(auth.stop)
        self.addCleanup(contracts.stop)
        auth.start().return_value.obter_usuario_por_id.side_effect = lambda uid: self.users.get(str(uid))
        contracts.start().return_value.listar_contratos_usuario.return_value = ['C.E.F MINAS GERAIS - 8756.2025']
        for target, value in [('db.connection.CAMINHO_DB', self.db),
                              ('comunicacoes.runtime.available_works',
                               lambda uid: [{'id': '1', 'name': 'Medina'}, {'id': '2', 'name': 'Almenara'}])]:
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def test_admin_confirma_qualquer_obra(self):
        self.assertTrue('1' in runtime.confirmable_works('1'))

    def test_coordenador_definido_na_obra(self):
        self.assertTrue('1' in runtime.confirmable_works('7'))
        self.assertFalse('1' in runtime.confirmable_works('8'))

    def test_sem_coordenador_vale_o_vinculo_ao_contrato(self):
        self.assertTrue('2' in runtime.confirmable_works('8'))

    def test_obra_nao_autorizada(self):
        self.assertFalse('99' in runtime.confirmable_works('1'))

    def test_fila_do_ok_por_usuario(self):
        self.assertEqual(runtime.confirmable_works('1'), {'1', '2'})  # admin
        self.assertEqual(runtime.confirmable_works('7'), {'1', '2'})  # coordenador de 1; contrato em 2
        self.assertEqual(runtime.confirmable_works('8'), {'2'})       # só a obra sem coordenador

    def test_situacao_das_obras_segue_a_aba_obras(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('ALTER TABLE obras ADD COLUMN contrato_ic TEXT')
            db.execute('ALTER TABLE obras ADD COLUMN status_conclusao_obra TEXT')
            db.execute("UPDATE obras SET contrato_ic='03738/2026', status_conclusao_obra='sem_pendencias' WHERE id=1")
            db.execute('CREATE TABLE obra_checklist (id INTEGER PRIMARY KEY, obra_id INTEGER, concluido INTEGER, '
                       'data_limite TEXT, tarefa_origem_id INTEGER)')
            db.execute("INSERT INTO obra_checklist VALUES (1, 2, 0, '2000-01-01', NULL)")
        overview = runtime.works_overview('1')
        self.assertEqual((overview['1']['bucket'], overview['1']['ic'], overview['1']['uf']), ('concluido', '03738/2026', 'MG'))
        self.assertEqual((overview['2']['status_texto'], overview['2']['bucket']), ('Atrasada', 'atrasado'))
        self.assertEqual(overview['2']['contrato'], '8756.2025')


if __name__ == '__main__':
    unittest.main()
