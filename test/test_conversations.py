import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import tempfile
import unittest
from pathlib import Path
from email.message import EmailMessage
from comunicacoes.conversations import build_conversations, excerpt
from comunicacoes.store import MailStore


def row(i, subject='MEDINA — reunião', refs=(), sender='a@example.invalid', **changes):
    return dict(id=i, subject=subject, refs=json.dumps(refs), message_id=f'<{i}@test>',
                sender=sender, recipients='lucas@example.invalid', cc='',
                sent_date=f'Tue, {i:02d} Sep 2026 10:00:00 -0300', body='Novidade\n> histórico',
                status='vinculado', obra_id='medina', suggestion=None, attachments=[], **changes)


class ConversationsTests(unittest.TestCase):
    def test_reference_groups_changed_subject_and_missing_root(self):
        a, b = row(1, refs=['<absent@test>']), row(2, subject='Novo assunto', refs=['<absent@test>'])
        group, = build_conversations([b, a])
        self.assertEqual(group['id'], 2)
        self.assertEqual(group['message_count'], 2)
        self.assertIn('cabeçalhos', group['group_reason'])

    def test_subject_continuity_is_only_probable(self):
        groups = build_conversations([row(1), row(2, subject='Re: ENC: MEDINA — reunião')])
        self.assertEqual(len(groups), 1)
        self.assertIn('provável', groups[0]['group_reason'])

    def test_same_inbox_does_not_prove_continuity(self):
        self.assertEqual(len(build_conversations([row(1), row(2, sender='other@example.invalid')])), 2)

    def test_different_works_and_years_not_merged_by_subject(self):
        a, b = row(1), row(2)
        b['obra_id'] = 'almenara'
        self.assertEqual(len(build_conversations([a, b])), 2)
        self.assertEqual(len(build_conversations([row(1, subject='IC 00744/2025'), row(2, subject='IC 00744/2026')])), 2)

    def test_cross_work_references_flag_conflict_without_mutation(self):
        a, b = row(1), row(2, refs=['<1@test>'])
        b['obra_id'] = 'almenara'
        group, = build_conversations([a, b])
        self.assertTrue(group['conflict'])
        self.assertEqual(a['obra_id'], 'medina')
        self.assertEqual(b['obra_id'], 'almenara')

    def test_technical_receipts_do_not_become_latest_reply(self):
        a, b = row(1), row(2, refs=['<1@test>'])
        b['status'] = 'tecnico'
        self.assertEqual(len(build_conversations([a, b])), 2)

    def test_old_attachment_retained_same_bytes_dedup_versions_separate(self):
        messages = [row(1), row(2, refs=['<1@test>']), row(3, refs=['<2@test>'])]
        for r, digest in zip(messages[:2], ['same', 'same']):
            r['attachments'] = [dict(id=r['id'], name='planilha.xlsx', sha256=digest, size=20)]
        messages[0]['attachments'].append(dict(id=4, name='planilha.xlsx', sha256='different', size=21))
        group, = build_conversations(messages)
        self.assertEqual(group['id'], 3)
        self.assertEqual(len(group['files']), 2)
        self.assertEqual(len(group['files'][0]['origins']), 2)
        self.assertEqual(group['excerpt'], 'Novidade')

    def test_excerpt_preserves_original_and_stops_at_quote(self):
        body = 'Prazo alterado para sexta.\n\nEm ontem escreveu:\nPrazo antigo.'
        self.assertEqual(excerpt(body), 'Prazo alterado para sexta.')
        self.assertIn('Prazo antigo.', body)

    def test_store_filters_before_grouping_and_keeps_attachment_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MailStore(Path(tmp) / 'mail.db')
            store.save_work('medina', 'Medina', '03738/2026', ['MEDINA'], True, 'test')
            msg = EmailMessage()
            msg['Subject'] = 'MEDINA IC 03738/2026'
            msg['From'] = 'a@example.invalid'
            msg.set_content('Conteúdo')
            msg.add_attachment(b'file', maintype='application', subtype='pdf', filename='doc.pdf')
            store.import_message(msg.as_bytes(), ('test', 'INBOX', '1', '1'))
            self.assertEqual(store.conversation_rows(set()), [])
            rows = store.conversation_rows({'medina'})
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(rows[0]['attachments'][0]['sha256']), 64)
            self.assertNotIn('payload', rows[0]['attachments'][0])


if __name__ == '__main__':
    unittest.main()
