import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import imaplib
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

from comunicacoes.imap_reader import IMAPConfig, AuthFailed, sync_mail, parse_list, resolve_folders
from comunicacoes.matching import match_message, clean_ic
from comunicacoes.parser import parse_message, MAX_MESSAGE
from comunicacoes.store import MailStore


def mail(subject='MEDINA IC 03738/2026', mid='<one@example.invalid>', body='Documento para conferência.', ref=None, attachment=False):
    msg = EmailMessage()
    msg['Subject'], msg['Message-ID'] = subject, mid
    msg['From'], msg['To'] = 'from@example.invalid', 'to@example.invalid'
    msg['Date'] = 'Wed, 23 Sep 2026 10:00:00 -0300'
    if ref:
        msg['In-Reply-To'] = ref
    msg.set_content(body)
    if attachment:
        msg.add_attachment(b'example', maintype='text', subtype='plain', filename='../../file.txt')
    return msg.as_bytes()


class MailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = MailStore(Path(self.tmp.name) / 'test.db', Path(self.tmp.name) / 'arquivos')
        self.store.save_work('1', 'Medina', '03738/2026', ['MEDINA'], True, 'admin')
        self.store.save_work('2', 'Almenara', '00744/2026', ['ALMENARA'], False, 'admin')
        self.store.save_work('3', 'Tubarão', '02351/2026', ['TUBARÃO'], False, 'admin')

    def source(self, uid='1', folder='INBOX', validity='7'):
        return ('pilot@example.invalid', folder, validity, uid)

    def test_normalize_preserves_year(self):
        self.assertEqual(clean_ic('3738.2026'), '03738/2026')
        with self.assertRaises(ValueError):
            clean_ic('3738')

    def test_confirmed_ic_and_candidate(self):
        works = self.store.works()
        self.assertEqual(match_message('MEDINA IC 3738-2026', '', works).status, 'vinculado')
        self.assertEqual(match_message('TUBARÃO IC 02351/2026', '', works).status, 'revisar')

    def test_year_and_name_conflict(self):
        works = self.store.works()
        for subject in ['ALMENARA IC 00744/2025', 'ALMENARA IC 03738/2026', 'MEDINA ALMENARA',
                        'IC 03738/2026 e IC 00744/2026']:
            self.assertEqual(match_message(subject, '', works).status, 'conflito', subject)

    def test_city_and_body_do_not_auto_link(self):
        self.assertEqual(match_message('MEDINA', '', self.store.works()).status, 'revisar')
        result = match_message('Encaminhamento', 'IC 03738/2026', self.store.works())
        self.assertEqual(result.status, 'revisar')
        self.assertEqual(result.suggestion, '1')

    def test_receipts_and_alerts_are_technical(self):
        for subject in ['Lida: MEDINA', 'Delivered: MEDINA', '🆘 [CRÍTICO] Obra ALMENARA - 9 tarefas em alerta']:
            self.assertEqual(match_message(subject, '', self.store.works()).status, 'tecnico')

    def test_dedup_across_folders_and_uidvalidity(self):
        first, fresh = self.store.import_message(mail(), self.source())
        second, new = self.store.import_message(mail(), self.source('2', 'Sent'))
        third, _ = self.store.import_message(mail(), self.source('1', validity='8'))
        self.assertTrue(fresh)
        self.assertFalse(new)
        self.assertEqual((first, first), (second, third))
        self.assertEqual(len(self.store.messages()), 1)
        self.assertEqual(len(self.store.detail(first)[3]), 3)

    def test_same_mid_different_content_conflict(self):
        self.store.import_message(mail(), self.source())
        mid, _ = self.store.import_message(mail(body='Conteúdo diferente'), self.source('2'))
        self.assertEqual(self.store.detail(mid)[0]['status'], 'conflito')

    def test_thread_and_conflicting_reference(self):
        self.store.import_message(mail(), self.source())
        mid, _ = self.store.import_message(mail('RES: informações', '<two@example.invalid>', ref='<one@example.invalid>'), self.source('2'))
        self.assertEqual(self.store.detail(mid)[0]['obra_id'], '1')
        other, _ = self.store.import_message(mail('ALMENARA IC 00744/2026', '<three@example.invalid>', ref='<one@example.invalid>'), self.source('3'))
        self.assertEqual(self.store.detail(other)[0]['status'], 'conflito')

    def test_manual_review_audit_and_reprocess(self):
        mid, _ = self.store.import_message(mail('MEDINA sem IC'), self.source())
        self.store.review(mid, '2', 'admin:1', 'Serviço confirmado manualmente.')
        self.store.reprocess('admin:1')
        detail, _, audit, _ = self.store.detail(mid)
        self.assertEqual(detail['obra_id'], '2')
        self.assertEqual(audit[-1]['actor'], 'admin:1')
        self.assertIn('before', audit[-1]['details'])

    def test_confirm_mapping_reclassifies_candidate(self):
        mid, _ = self.store.import_message(mail('ALMENARA IC 00744/2026'), self.source())
        self.assertEqual(self.store.detail(mid)[0]['status'], 'revisar')
        self.store.save_work('2', 'Almenara', '00744/2026', ['ALMENARA'], True, 'admin')
        self.store.reprocess('admin')
        self.assertEqual(self.store.detail(mid)[0]['status'], 'vinculado')

    def test_html_inert_and_attachments_preserved(self):
        msg = EmailMessage()
        msg['Subject'] = 'html'
        msg.set_content('<script>alert(1)</script><p>Texto</p><img src="https://tracker.invalid">', subtype='html')
        parsed = parse_message(msg.as_bytes())
        self.assertIn('Texto', parsed['body'])
        self.assertNotIn('alert', parsed['body'])
        self.assertNotIn('tracker', parsed['body'])
        parsed = parse_message(mail(attachment=True))
        self.assertEqual(parsed['attachments'][0]['name'], 'file.txt')
        self.assertEqual(parsed['attachments'][0]['data'], b'example')

    def test_limit_and_password_redaction(self):
        with self.assertRaises(ValueError):
            parse_message(b'x' * (MAX_MESSAGE + 1))
        self.assertNotIn('secret', repr(IMAPConfig('host', 'user', 'secret')))

    def test_forwarded_eml_remains_attachment(self):
        msg = EmailMessage()
        msg['Subject'] = 'Arquivo encaminhado'
        msg.set_content('Corpo externo')
        nested = EmailMessage()
        nested['Subject'] = 'MEDINA IC 03738/2026'
        nested.set_content('Conteúdo do anexo')
        msg.add_attachment(nested, filename='mensagem.eml')
        parsed = parse_message(msg.as_bytes())
        self.assertNotIn('Conteúdo do anexo', parsed['body'])
        self.assertEqual(parsed['attachments'][0]['name'], 'mensagem.eml')
        self.assertTrue(parsed['attachments'][0]['data'])

    def test_imap_readonly_peek_and_retry_batch(self):
        class FakeIMAP:
            def __init__(self, *args, **kwargs):
                self.commands = []
                self.readonly = False
                self.logged_out = False
                fake_instances.append(self)
            def login(self, user, password):
                pass
            def list(self):
                return 'OK', [b'(\\HasNoChildren) "." "INBOX"']
            def select(self, folder, readonly=False):
                self.readonly = readonly
                return 'OK', [b'2']
            def response(self, name):
                return name, [b'7']
            def uid(self, command, *args):
                self.commands.append((command, args))
                if command == 'SEARCH':
                    return 'OK', [b'1 2']
                raw = mail(mid=f'<uid{args[0].decode()}@example.invalid>')
                if args[1] == '(RFC822.SIZE)':
                    return 'OK', [f'1 (RFC822.SIZE {len(raw)})'.encode()]
                return 'OK', [(b'1 (BODY[] {100}', raw), b')']
            def logout(self):
                self.logged_out = True
        fake_instances = []
        cfg = IMAPConfig('host', 'pilot@example.invalid', 'secret', ['INBOX'], ['MEDINA'], batch=1)
        first = sync_mail(self.store, cfg, FakeIMAP)
        self.assertIn('Há mais', first)
        second = sync_mail(self.store, cfg, FakeIMAP)
        self.assertEqual(len(self.store.messages()), 2)
        self.assertIn('concluída', second)
        for fake in fake_instances:
            self.assertTrue(fake.readonly)
            self.assertTrue(fake.logged_out)
            self.assertTrue(all(c in ('SEARCH', 'FETCH') for c, _ in fake.commands))
            self.assertTrue(any('(BODY.PEEK[])' in a for _, a in fake.commands))

    def test_oversized_mail_not_imported_and_reported(self):
        class BigIMAP:
            commands = []
            def __init__(self, *args, **kwargs):
                pass
            def login(self, user, password):
                pass
            def list(self):
                return 'OK', [b'(\\HasNoChildren) "." "INBOX"']
            def select(self, folder, readonly=False):
                return 'OK', [b'1']
            def response(self, name):
                return name, [b'7']
            def uid(self, command, *args):
                BigIMAP.commands.append((command, args))
                if command == 'SEARCH':
                    return 'OK', [b'5']
                if args[1] == '(RFC822.SIZE)':
                    return 'OK', [f'1 (RFC822.SIZE {MAX_MESSAGE + 2 * 1024 * 1024})'.encode()]
                header = b'Subject: MEDINA projeto executivo\r\nFrom: Fulano <f@example.invalid>\r\nDate: Wed, 23 Sep 2026 10:00:00 -0300\r\n\r\n'
                return 'OK', [(b'1 (BODY[HEADER.FIELDS (SUBJECT FROM DATE)] {100}', header), b')']
            def logout(self):
                pass
        cfg = IMAPConfig('host', 'pilot@example.invalid', 'secret', ['INBOX'], ['MEDINA'])
        result = sync_mail(self.store, cfg, BigIMAP)
        self.assertEqual(self.store.messages(), [])
        self.assertIn('acima de', result)
        self.assertFalse(any('(BODY.PEEK[])' in a for _, a in BigIMAP.commands))
        self.assertTrue(all('PEEK' in a[1] for c, a in BigIMAP.commands if c == 'FETCH' and a[1] != '(RFC822.SIZE)'))
        [item] = self.store.skipped()
        self.assertEqual(item['subject'], 'MEDINA projeto executivo')
        self.assertIn('Fulano', item['sender'])
        self.assertEqual(item['size'], MAX_MESSAGE + 2 * 1024 * 1024)
        self.assertIn('salve no Drive', item['note'])
        self.assertEqual(self.store.last_run()['status'], 'parcial')

    def test_mail_limit_configurable(self):
        import importlib
        from unittest.mock import patch
        import core.config
        try:
            with patch.dict(os.environ, {'AGENDA_MAIL_MAX_MB': '10'}):
                self.assertEqual(importlib.reload(core.config).COMUNICACOES_MAX_MB, 10)
        finally:
            importlib.reload(core.config)
        self.assertEqual(core.config.COMUNICACOES_MAX_MB, int(os.getenv('AGENDA_MAIL_MAX_MB') or 15))

    def test_auth_failure_does_not_log_secret(self):
        class BadIMAP:
            def __init__(self, *args, **kwargs):
                pass
            def login(self, *args):
                raise imaplib.IMAP4.error('password SUPERSECRET')
            def logout(self):
                pass
        with self.assertRaises(AuthFailed) as ctx:
            sync_mail(self.store, IMAPConfig('host', 'user', 'SUPERSECRET', ['INBOX'], ['MEDINA']), BadIMAP)
        self.assertNotIn('SUPERSECRET', str(ctx.exception))
        self.assertNotIn('SUPERSECRET', str(self.store.last_run()))
        self.assertEqual(self.store.last_run()['status'], 'falha')

    def test_imap_error_after_login_is_not_reported_as_wrong_password(self):
        class BrokenIMAP:
            def __init__(self, *args, **kwargs):
                pass
            def login(self, *args):
                pass
            def list(self):
                return 'OK', [b'(\\HasNoChildren) "." "INBOX"']
            def select(self, *args, **kwargs):
                raise imaplib.IMAP4.error('protocol error')
            def logout(self):
                pass
        with self.assertRaises(RuntimeError) as ctx:
            sync_mail(self.store, IMAPConfig('host', 'user', 'secret', ['INBOX'], ['MEDINA']), BrokenIMAP)
        self.assertNotIsInstance(ctx.exception, AuthFailed)
        self.assertNotIn('senha', str(ctx.exception))


class FolderTests(unittest.TestCase):
    LISTING = [b'(\\HasNoChildren) "." "INBOX"',
               b'(\\HasNoChildren \\Sent) "." "INBOX.Sent"',
               b'(\\Noselect \\HasChildren) NIL Arquivo',
               (b'(\\HasNoChildren) "." {16}', b'INBOX.Obras 2026')]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = MailStore(Path(self.tmp.name) / 'test.db', Path(self.tmp.name) / 'arquivos')

    def fake(self, listing, failing=()):
        selected = []
        class FolderIMAP:
            def __init__(self, *args, **kwargs):
                pass
            def login(self, *args):
                pass
            def list(self):
                return 'OK', listing
            def select(self, folder, readonly=False):
                selected.append(folder)
                return ('NO', [b'fail']) if folder.strip('"') in failing else ('OK', [b'1'])
            def response(self, name):
                return name, [b'7']
            def uid(self, command, *args):
                return 'OK', [b'']
            def logout(self):
                pass
        return FolderIMAP, selected

    def config(self, folders):
        return IMAPConfig('host', 'pilot@example.invalid', 'secret', folders, ['MEDINA'])

    def test_parse_list_variants(self):
        folders = parse_list(self.LISTING)
        self.assertEqual([n for n, _ in folders], ['INBOX', 'INBOX.Sent', 'Arquivo', 'INBOX.Obras 2026'])
        self.assertIn('\\Sent', folders[1][1])
        self.assertEqual(parse_list([b'(\\HasNoChildren) "/" "Itens \\"x\\""'])[0][0], 'Itens "x"')

    def test_resolve_by_flag_name_and_missing(self):
        available = parse_list(self.LISTING)
        resolved, missing = resolve_folders(['inbox', 'sent', 'INBOX.Obras 2026', 'Nada', 'INBOX'], available)
        self.assertEqual(resolved, [('Caixa de entrada', 'INBOX'), ('Enviados (INBOX.Sent)', 'INBOX.Sent'),
                                    ('INBOX.Obras 2026', 'INBOX.Obras 2026')])
        self.assertEqual(missing, ['Nada'])
        # Sem a marcação \Sent, reconhece pelo nome; sem nenhuma pasta de enviados, fica ausente.
        self.assertEqual(resolve_folders(['sent'], [('INBOX', set()), ('INBOX.Enviados', set())])[0],
                         [('Enviados (INBOX.Enviados)', 'INBOX.Enviados')])
        self.assertEqual(resolve_folders(['sent'], [('INBOX', set())]), ([], ['Enviados']))

    def test_sync_uses_real_names_and_remembers_folders(self):
        factory, selected = self.fake(self.LISTING)
        result = sync_mail(self.store, self.config(['inbox', 'sent']), factory)
        self.assertEqual(selected, ['"INBOX"', '"INBOX.Sent"'])
        self.assertIn('Pastas consultadas: Caixa de entrada, Enviados (INBOX.Sent)', result)
        self.assertEqual([n for n, _ in self.store.folders('pilot@example.invalid')],
                         ['Arquivo', 'INBOX', 'INBOX.Obras 2026', 'INBOX.Sent'])
        self.assertEqual(self.store.folders('outra@example.invalid'), [])
        self.assertEqual(self.store.last_run()['status'], 'concluido')

    def test_missing_or_failing_folder_does_not_abort(self):
        factory, selected = self.fake([b'(\\HasNoChildren) "." "INBOX"', b'(\\HasNoChildren) "." "INBOX.Obras"'],
                                      failing={'INBOX.Obras'})
        result = sync_mail(self.store, self.config(['inbox', 'sent', 'INBOX.Obras']), factory)
        self.assertEqual(selected, ['"INBOX"', '"INBOX.Obras"'])
        self.assertIn('Não encontradas: Enviados, INBOX.Obras', result)
        self.assertEqual(self.store.last_run()['status'], 'parcial')

    def test_no_existing_folder_is_an_error(self):
        factory, _ = self.fake([b'(\\HasNoChildren) "." "INBOX"'])
        with self.assertRaises(RuntimeError) as ctx:
            sync_mail(self.store, self.config(['sent']), factory)
        self.assertIn('Nenhuma das pastas', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
