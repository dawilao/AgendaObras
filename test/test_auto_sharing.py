import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tempfile
import unittest
from pathlib import Path
from comunicacoes.store import MailStore
from comunicacoes.publishing import publish_identified
from comunicacoes.session import register, unregister
from test_comunicacoes import mail

class AutoSharingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.private=MailStore(root/'private.db',root/'files')
        self.shared=MailStore(root/'shared.db',root/'files')
        self.private.save_work('1','Medina','03738/2026',['Medina'],True,'test')

    def add(self, **kw):
        return self.private.import_message(mail(**kw),('test','INBOX','1',str(len(self.private.messages())+1)))[0]

    def test_exact_shared_once_personal_copy_retained(self):
        mid=self.add(attachment=True)
        self.assertEqual(publish_identified(self.private,self.shared,'test',{'1'})['new'],1)
        self.assertEqual(publish_identified(self.private,self.shared,'test',{'1'})['new'],0)
        self.assertEqual(len(self.private.messages()),1)
        self.assertEqual(len(self.shared.messages()),1)
        self.assertTrue(any(a['action']=='publicacao_automatica' for a in self.shared.detail(self.shared.messages()[0]['id'])[2]))

    def test_city_alone_and_wrong_year_stay_pending(self):
        self.add(subject='Medina projeto')
        self.add(subject='Medina IC 03738/2025',mid='<two@example.invalid>')
        publish_identified(self.private,self.shared,'test',{'1'})
        self.assertFalse(self.shared.messages())

    def test_no_access_does_not_publish(self):
        self.add()
        publish_identified(self.private,self.shared,'test',set())
        self.assertFalse(self.shared.messages())

    def test_divergent_body_stays_blocked_after_retry(self):
        mid=self.add(body='Outra obra IC 00744/2026')
        for _ in range(2):
            publish_identified(self.private,self.shared,'test',{'1'})
            self.assertFalse(self.shared.messages())
            self.assertEqual(self.private.detail(mid)[0]['status'],'conflito')

    def test_changed_message_id_is_not_overwritten(self):
        self.add()
        publish_identified(self.private,self.shared,'test',{'1'})
        self.add(body='Outro conteúdo')
        publish_identified(self.private,self.shared,'test',{'1'})
        self.assertEqual(len(self.shared.messages()),1)

    def test_second_connection_same_user_is_rejected(self):
        first=register('test-single')
        try:
            with self.assertRaises(RuntimeError): register('test-single')
        finally: unregister('test-single',first)
        second=register('test-single')
        unregister('test-single',second)

if __name__=='__main__': unittest.main()
