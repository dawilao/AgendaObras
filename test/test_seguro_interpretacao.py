import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unittest
from email.message import EmailMessage
from comunicacoes.seguro_interpretacao import interpretar
from test_seguro_emails import SeguroEmailTests


class LeituraTests(unittest.TestCase):
    def read(self,body,sender='seguros@caixa.gov.br',**extra):
        row=dict(id=1,body=body,sender=sender,recipients='mach@machengenharia.com.br',cc='',
                 subject='Seguro Medina IC 03738/2026',sent_date='Thu, 24 Sep 2026 10:00:00 -0300',
                 fingerprint='one',status='vinculado',attachments=[])
        row.update(extra)
        return interpretar(row,dict(ic='03738/2026',aliases=['Medina']))

    def test_request_and_rejection(self):
        self.assertEqual(self.read('Lembramos da obrigatoriedade de apresentação das apólices de seguro.')['action'],'solicitacao')
        self.assertEqual(self.read('A apólice não está aprovada. Solicitamos correção.')['action'],'ajustes')

    def test_quote_does_not_become_current_acceptance(self):
        self.assertEqual(self.read('Estamos analisando o seguro.\nDe: seguros@caixa.gov.br\nApólice aprovada.')['action'],'revisar')
        self.assertEqual(self.read('Estamos analisando.\n> Apólice aprovada.')['action'],'revisar')

    def test_conditional_and_third_party_not_bank_acceptance(self):
        self.assertEqual(self.read('A apólice será aprovada após a correção.')['action'],'revisar')
        self.assertEqual(self.read('Apólice aprovada.','corretora@example.invalid')['action'],'revisar')
        self.assertEqual(self.read('A apólice está aprovada.')['action'],'aceite')

    def test_multiline_request_to_insurer_and_future_not_sent(self):
        self.assertEqual(self.read('Os ajustes foram encaminhados\nà seguradora.','mach@machengenharia.com.br')['action'],'pedido')
        self.assertEqual(self.read('Encaminharemos a apólice em anexo.','mach@machengenharia.com.br',recipients='seguros@caixa.gov.br')['action'],'revisar')

    def test_date_conflict_and_work_ambiguity(self):
        body='Lembramos da obrigatoriedade de apresentação das apólices.'
        self.assertTrue(self.read(body,sent_date='bad')['review'])
        self.assertTrue(self.read(body,status='conflito')['review'])
        self.assertTrue(self.read(body,subject='Seguro de outra obra')['review'])
        self.assertTrue(self.read(body,subject='Seguro Medina IC 03738/2025')['review'])

    def test_forwarded_request_has_provenance(self):
        r=self.read('-------- Mensagem original --------\nASSUNTO: Seguro Medina\nDATA: 24/09/2026\nDE: seguros@caixa.gov.br\nPARA: mach@machengenharia.com.br\n\nLembramos da obrigatoriedade de apresentação das apólices.',sender='mach@machengenharia.com.br')
        self.assertEqual(r['action'],'solicitacao')
        self.assertTrue(r['forwarded'])

    def test_cc_can_contain_bank(self):
        r=self.read('Segue em anexo a apólice.','mach@machengenharia.com.br',recipients='consultor@example.invalid',cc='seguros@caixa.gov.br')
        self.assertEqual(r['action'],'envio')


class AutomaticWorkflowTests(unittest.TestCase):
    setUp=SeguroEmailTests.setUp
    setUpBase=SeguroEmailTests.setUpBase
    message=SeguroEmailTests.message

    def add(self,key,body,sender,day,files=False):
        m=EmailMessage()
        m['Subject']='Seguro da obra Medina IC 03738/2026'
        m['From']=sender; m['To']='seguros@caixa.gov.br'
        m['Message-ID']=f'<auto-{key}@test>'
        m['Date']=f'{day} Sep 2026 10:00:00 -0300'
        m.set_content(body)
        if files:
            for name in ['apolice.pdf','boleto.pdf']:
                m.add_attachment(name.encode(),maintype='application',subtype='pdf',filename=name)
        return self.mail.import_message(m.as_bytes(),('test','INBOX','1',key))[0]

    def test_initial_automatic_and_idempotent(self):
        self.add('request','Lembramos da obrigatoriedade de apresentação das apólices.','seguros@caixa.gov.br',1)
        self.bridge.interpretar_emails()
        state,_=self.bridge.obter(1)
        self.assertEqual(state['atual']['etapa'],'solicitado')
        count=len(state['historico'])
        self.bridge.interpretar_emails()
        self.assertEqual(len(self.bridge.obter(1)[0]['historico']),count)
        self.assertIn('automaticamente',state['atual']['evidencia'])

    def test_complete_evidence_advances_but_never_final_oks(self):
        self.add('r','Lembramos da obrigatoriedade de apresentação das apólices.','seguros@caixa.gov.br',1)
        self.add('p','Solicitamos emissão do seguro.','mach@machengenharia.com.br',2)
        self.add('d','Segue em anexo a apólice e boleto.','corretora@example.invalid',3,True)
        self.add('s','Segue em anexo a apólice.','mach@machengenharia.com.br',4)
        self.add('a','A apólice está aprovada.','seguros@caixa.gov.br',5)
        self.bridge.interpretar_emails()
        state,_=self.bridge.obter(1)
        self.assertEqual(state['atual']['etapa'],'aceito')
        self.assertFalse(state['definitivo'])
        self.assertFalse(state['ok_seguro']); self.assertFalse(state['ok_boleto'])

    def test_gaps_remain_visible_without_fabricated_documents(self):
        self.add('r','Lembramos da obrigatoriedade de apresentação das apólices.','seguros@caixa.gov.br',1)
        self.add('a','A apólice não está aprovada. Solicitamos correção.','seguros@caixa.gov.br',5)
        self.bridge.interpretar_emails()
        state,_=self.bridge.obter(1)
        self.assertEqual(state['atual']['etapa'],'solicitado')
        self.assertEqual(state['atual']['boleto'],'')
        self.assertTrue(any(r['action']=='ajustes' and 'conferência' in r['result'] for r in state['leituras']))

    def test_permission_and_manual_state_preserved(self):
        self.add('r','Lembramos da obrigatoriedade de apresentação das apólices.','seguros@caixa.gov.br',1)
        self.user['pode_validar_seguro']=False
        self.bridge.interpretar_emails()
        self.assertEqual(self.bridge.obter(1)[0]['leituras'],[])
        self.user['pode_validar_seguro']=True
        self.bridge.registrar_etapa(1,'solicitacao',{'email_id':self.mid},0)
        self.add('p','Solicitamos emissão do seguro.','mach@machengenharia.com.br',2)
        self.bridge.interpretar_emails()
        self.assertEqual(self.bridge.obter(1)[0]['atual']['etapa'],'solicitado')

    def test_later_import_fills_gap_without_duplicate_readings(self):
        self.add('r','Lembramos da obrigatoriedade de apresentação das apólices.','seguros@caixa.gov.br',1)
        self.add('p','Solicitamos emissão do seguro.','mach@machengenharia.com.br',2)
        self.add('s','Segue em anexo a apólice.','mach@machengenharia.com.br',4)
        self.bridge.interpretar_emails()
        self.assertEqual(self.bridge.obter(1)[0]['atual']['etapa'],'pedido')
        self.add('d','Segue em anexo a apólice e boleto.','corretora@example.invalid',3,True)
        self.bridge.interpretar_emails()
        state,_=self.bridge.obter(1)
        self.assertEqual(state['atual']['etapa'],'analise')
        self.assertEqual(len(state['leituras']),len({r['fingerprint'] for r in state['leituras']}))

    def test_manual_step_after_automatic_takes_control(self):
        import json
        self.add('r','Lembramos da obrigatoriedade de apresentação das apólices.','seguros@caixa.gov.br',1)
        self.bridge.interpretar_emails()
        state,_=self.bridge.obter(1)
        self.bridge.registrar_etapa(1,'pedido',{'email_id':self.mid},state['revisao'])
        self.add('d','Segue em anexo a apólice e boleto.','corretora@example.invalid',3,True)
        self.bridge.interpretar_emails()
        state,_=self.bridge.obter(1)
        self.assertEqual(state['atual']['etapa'],'pedido')
        self.assertNotIn('automatico',json.loads(state['atual']['vinculos']))
