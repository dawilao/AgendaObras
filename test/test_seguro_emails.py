import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import unittest
from pathlib import Path
from email.message import EmailMessage
from test_seguro import SeguroTests
from comunicacoes.store import MailStore
from comunicacoes.seguro_bridge import FontesSeguro, SeguroComEmails


class SeguroEmailTests(unittest.TestCase):
    setUpBase=SeguroTests.setUp
    def setUp(self):
        self.setUpBase()
        self.mail=MailStore(Path(self.tmp.name)/'mail.db',Path(self.tmp.name)/'arquivos')
        self.mail.save_work('1','Medina','03738/2026',['MEDINA'],True,'test')
        self.mail.save_work('2','Almenara','00744/2026',['ALMENARA'],True,'test')
        self.mid=self.message('MEDINA IC 03738/2026','one')
        self.other=self.message('ALMENARA IC 00744/2026','two')
        self.allowed=True
        def guard():
            if not self.allowed: raise PermissionError('Revogado')
        self.sources=FontesSeguro(self.mail,'1',guard,'shared')
        self.bridge=SeguroComEmails(self.service,1,self.sources)

    def message(self,subject,key):
        m=EmailMessage()
        m['Subject']=subject; m['From']='test@example.invalid'; m['Message-ID']=f'<{key}@test>'
        m['Date']='Thu, 24 Sep 2026 10:00:00 -0300'
        m.set_content('Exemplo fictício')
        m.add_attachment(b'policy'+key.encode(),maintype='application',subtype='pdf',filename='apolice.pdf')
        m.add_attachment(b'bill'+key.encode(),maintype='application',subtype='pdf',filename='boleto.pdf')
        return self.mail.import_message(m.as_bytes(),('test','INBOX','1',key))[0]

    def stage(self,action,**extra):
        state,_=self.bridge.obter(1)
        self.bridge.registrar_etapa(1,action,dict(email_id=str(self.mid),**extra),state['revisao'])

    def test_round_preserves_documents_across_evidence_updates(self):
        self.stage('solicitacao'); self.stage('pedido')
        files=self.sources.catalogo()[str(self.mid)]['attachments']
        self.stage('recebimento',apolice_id=str(files[0]['id']),boleto_id=str(files[1]['id']))
        self.stage('envio'); self.stage('aceite')
        state,_=self.bridge.obter(1)
        refs=json.loads(state['atual']['vinculos'])
        self.assertEqual(refs['apolice']['sha256'],files[0]['sha256'])
        self.assertEqual(self.sources.anexo(refs['boleto'])['name'],'boleto.pdf')
        self.assertFalse(state['definitivo'])
        self.stage('nova_rodada',motivo='Correção')
        state,_=self.bridge.obter(1)
        self.assertNotIn('apolice',json.loads(state['atual']['vinculos']))
        self.assertIn('apolice',json.loads(state['rodadas'][1]['vinculos']))

    def test_wrong_work_email_or_attachment_rejected(self):
        with self.assertRaises(ValueError): self.sources.preparar('solicitacao',{'email_id':self.other})
        files=self.mail.detail(self.other)[1]
        with self.assertRaises(ValueError): self.sources.preparar('recebimento',{'email_id':self.mid,'apolice_id':files[0]['id'],'boleto_id':files[1]['id']})

    def test_permission_revoked_on_read_and_registration(self):
        ref=self.sources.preparar('solicitacao',{'email_id':self.mid})['vinculos']['evidencia']
        self.allowed=False
        with self.assertRaises(PermissionError):self.sources.mensagem(ref)
        with self.assertRaises(PermissionError):self.stage('solicitacao')
        self.assertEqual(self.service.obter(1)[0]['rodadas'],[])

    def test_source_and_content_verified_on_open(self):
        ref=self.sources.preparar('solicitacao',{'email_id':self.mid})['vinculos']['evidencia']
        with self.assertRaises(PermissionError):self.sources.mensagem({**ref,'namespace':'different-user'})
        with self.assertRaises(PermissionError):self.sources.mensagem({**ref,'fingerprint':'changed'})

    def test_tampered_attachment_rejected(self):
        files=self.sources.catalogo()[str(self.mid)]['attachments']
        ref=self.sources.preparar('recebimento',dict(email_id=self.mid,apolice_id=files[0]['id'],boleto_id=files[1]['id']))['vinculos']['apolice']
        # Registro no banco apontando para outro arquivo.
        with self.mail.connect() as db:db.execute('UPDATE attachments SET sha256=? WHERE id=?',(files[1]['sha256'],files[0]['id']))
        with self.assertRaises(PermissionError):self.sources.anexo(ref)

    def test_tampered_file_on_disk_rejected(self):
        files=self.sources.catalogo()[str(self.mid)]['attachments']
        ref=self.sources.preparar('recebimento',dict(email_id=self.mid,apolice_id=files[0]['id'],boleto_id=files[1]['id']))['vinculos']['apolice']
        self.mail.blobs.path(files[0]['sha256']).write_bytes(b'changed')
        with self.assertRaises(ValueError):self.sources.anexo(ref)

    def test_client_text_does_not_override_selected_source(self):
        self.stage('solicitacao',evidencia='fake client text',vinculos={'evidencia':'forged'})
        state,_=self.service.obter(1)
        self.assertNotIn('fake client text',state['atual']['evidencia'])
        self.assertEqual(json.loads(state['atual']['vinculos'])['evidencia']['id'],self.mid)

if __name__=='__main__':unittest.main()
