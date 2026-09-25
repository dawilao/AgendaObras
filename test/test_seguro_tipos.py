import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import unittest
from pathlib import Path
from test_seguro import SeguroTests
from test_seguro_interpretacao import AutomaticWorkflowTests
from services.seguro_service import SeguroService
from db.seguro_repo import criar_schema
from comunicacoes.seguro_bridge import SeguroComEmails
from comunicacoes.seguro_interpretacao import tipos_mensagem, interpretar


class TiposRepositoryTests(unittest.TestCase):
    setUp=SeguroTests.setUp

    def test_independent_rounds_approvals_and_revisions(self):
        guarantee=SeguroService(self.path,lambda:self.user,lambda uid:self.contracts,tipo='garantia')
        for action,data in [('solicitacao',{}),('pedido',{}),('recebimento',dict(apolice='G',boleto='BG')),('envio',{}),('aceite',{})]:
            guarantee.registrar_etapa(1,action,dict(evidencia='Exemplo',**data),guarantee.obter(1)[0]['revisao'])
        for field in ['ok_seguro','ok_boleto']:
            guarantee.alterar(1,field,True,guarantee.obter(1)[0]['revisao'])
        self.assertTrue(guarantee.obter(1)[0]['definitivo'])
        obra=self.service.obter(1)[0]
        self.assertFalse(obra['definitivo']); self.assertEqual(obra['revisao'],0)
        self.assertEqual(obra['historico'],[])
        self.service.registrar_etapa(1,'solicitacao',dict(evidencia='Outro seguro'),0)
        self.assertEqual(self.service.obter(1)[0]['atual']['numero'],1)
        self.assertEqual(guarantee.obter(1)[0]['atual']['numero'],1)
        self.assertNotEqual(self.service.obter(1)[0]['atual']['id'],guarantee.obter(1)[0]['atual']['id'])

    def test_old_database_preserved_without_inheriting_approvals(self):
        path=str(Path(self.tmp.name)/'old.db')
        with sqlite3.connect(path) as c:
            c.execute('CREATE TABLE obras(id INTEGER PRIMARY KEY, cliente TEXT)')
            c.execute("INSERT INTO obras VALUES(1,'CAIXA')")
            c.execute('CREATE TABLE obra_seguro(obra_id INTEGER PRIMARY KEY,cotacao TEXT,ok_seguro INTEGER,ok_boleto INTEGER,revisao INTEGER)')
            c.execute("INSERT INTO obra_seguro VALUES(1,'Aprovada',1,1,7)")
            c.execute("CREATE TABLE seguro_rodadas(id INTEGER PRIMARY KEY,obra_id INTEGER,numero INTEGER,etapa TEXT,apolice TEXT,boleto TEXT,evidencia TEXT,motivo TEXT,ok_seguro INTEGER,ok_boleto INTEGER, UNIQUE(obra_id,numero))")
            c.execute("INSERT INTO seguro_rodadas VALUES(42,1,1,'aceito','policy','bill','mail','',1,1)")
            criar_schema(c); criar_schema(c)
        c.close()
        for tipo in ['obra','garantia']:
            state=SeguroService(path,lambda:self.user,lambda uid:self.contracts,tipo=tipo).obter(1)[0]
            self.assertFalse(state['definitivo']); self.assertIsNone(state['atual'])
            self.assertEqual(state['legado'][0]['id'],42)
            self.assertEqual(state['legado'][0]['apolice'],'policy')
            self.assertTrue(state['legado'][0]['ok_seguro'])


class TiposReadingTests(unittest.TestCase):
    setUp=AutomaticWorkflowTests.setUp
    setUpBase=AutomaticWorkflowTests.setUpBase
    message=AutomaticWorkflowTests.message

    def row(self,body,subject='Contrato 03738/2026 - Medina'):
        return dict(id=999,fingerprint='type-example',body=body,subject=subject,sender='bank@caixa.gov.br',
                    recipients='mach@machengenharia.com.br',cc='',sent_date='24 Sep 2026 10:00:00 -0300',status='vinculado',attachments=[])

    def test_types_and_mixed_message(self):
        self.assertEqual(tipos_mensagem(self.row('Apólice de seguro-garantia.')),['garantia'])
        self.assertEqual(tipos_mensagem(self.row('Seguro de risco de engenharia e responsabilidade civil.')),['obra'])
        self.assertEqual(set(tipos_mensagem(self.row('Seguro-garantia e risco de engenharia.'))),{'obra','garantia'})

    def test_contract_topic_and_pending_not_sent(self):
        row=self.row('O contrato assinado deverá vir acompanhado da garantia contratual.',subject='Assinatura com garantia - Contrato 03738/2026')
        result=interpretar(row,dict(ic='03738/2026',aliases=['Medina']))
        self.assertEqual(result['action'],'solicitacao'); self.assertFalse(result['review'])
        row=self.row('Segue o contrato em anexo. O seguro-garantia está em confecção e será enviado após emissão.')
        row['sender']='mach@machengenharia.com.br';row['recipients']='bank@caixa.gov.br'
        self.assertEqual(interpretar(row,dict(ic='03738/2026',aliases=['Medina']))['action'],'revisar')

    def test_wrong_type_rejected_in_manual_selection(self):
        mid=self.message('MEDINA IC 03738/2026 Seguro-garantia','guarantee')
        with self.assertRaises(ValueError): self.bridge.registrar_etapa(1,'solicitacao',dict(email_id=mid),0)
        self.bridge.registrar_etapa(1,'solicitacao',dict(email_id=self.mid),0)
        self.bridge.registrar_etapa(1,'pedido',dict(email_id=self.mid),self.bridge.obter(1)[0]['revisao'])
        files=self.sources.catalogo()[str(mid)]['attachments']
        with self.assertRaises(ValueError):
            self.bridge.registrar_etapa(1,'recebimento',dict(email_id=self.mid,apolice_id=files[0]['id'],boleto_id=files[1]['id']),self.bridge.obter(1)[0]['revisao'])

    def test_no_cross_type_automatic_registration(self):
        from email.message import EmailMessage
        m=EmailMessage();m['Subject']='Assinatura de contrato com Garantia - Contrato 03738/2026'
        m['From']='bank@caixa.gov.br';m['Date']='1 Sep 2026 10:00:00 -0300';m['Message-ID']='<guarantee-request@test>'
        m.set_content('O contrato assinado deverá vir acompanhado da garantia contratual.')
        mid=self.mail.import_message(m.as_bytes(),('test','INBOX','1','typed'))[0]
        self.mail.review(mid,'1','test','Vínculo confirmado para o teste')
        guarantee=SeguroComEmails(SeguroService(self.path,lambda:self.user,lambda uid:self.contracts,tipo='garantia'),1,self.sources)
        guarantee.interpretar_emails();self.bridge.interpretar_emails()
        self.assertIsNotNone(guarantee.obter(1)[0]['atual'])
        self.assertIsNone(self.bridge.obter(1)[0]['atual'])
        reading=next(r for r in guarantee.obter(1)[0]['leituras'] if r['source']['id']==mid)
        self.assertEqual(reading['source']['topic'],'Assinatura de contrato')
