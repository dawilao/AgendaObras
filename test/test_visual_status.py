import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unittest
from comunicacoes.visual_status import conversation_status,insurance_color,sender_color,readings_color

class VisualTests(unittest.TestCase):
    def test_sender_domains(self):
        self.assertEqual(sender_color('Equipe <CELOG@CAIXA.GOV.BR>'),'blue')
        self.assertEqual(sender_color('Equipe MACH <equipe@machengenharia.com.br>'),'green')
        self.assertEqual(sender_color('CAIXA <pessoa@gmail.com>'),'yellow')
        self.assertEqual(sender_color('x@caixa.gov.br.example.com'),'yellow')
        self.assertEqual(sender_color(''),'gray')
    def test_latest_sender(self):
        self.assertEqual(readings_color([{'timestamp':1,'source':{'sender':'x@caixa.gov.br'}},{'timestamp':2,'source':{'sender':'x@machengenharia.com.br'}}]),'green')
        self.assertEqual(readings_color([]),'gray')
    def status(self,body,subject='Projeto',sender='banco@caixa.gov.br',**kw):
        return conversation_status(dict(subject=subject,body=body,sender=sender,**kw))[1]
    def test_request_not_approval(self):
        self.assertNotEqual(self.status('Solicitamos o projeto aprovado.'),'green')
        self.assertNotEqual(self.status('O projeto não foi aprovado.'),'green')
    def test_quote_not_approval(self):
        self.assertNotEqual(self.status('Bom dia.\n> Projeto aprovado.'),'green')
    def test_bank_approval(self):
        self.assertEqual(self.status('Projeto aprovado.'),'green')
        self.assertNotEqual(self.status('Projeto aprovado.',sender='equipe@machengenharia.com.br'),'green')
    def test_conflict(self):
        self.assertNotEqual(self.status('Projeto aprovado.',conflict=True),'green')
    def test_pending(self):
        self.assertEqual(self.status('O projeto foi reprovado. Favor corrigir.'),'red')
        self.assertEqual(self.status('O acesso não foi solicitado.','Acesso'),'red')
    def test_unknown_not_unsolicited(self):
        self.assertEqual(self.status('Bom dia.'),'yellow')
    def test_insurance(self):
        self.assertEqual(insurance_color({'definitivo':True},'Aprovada'),'green')
        self.assertEqual(insurance_color({'definitivo':False,'atual':{'etapa':'pedido'}},'Pedido'),'red')
        self.assertEqual(insurance_color({'definitivo':False,'atual':{'etapa':'analise'}},'Análise'),'yellow')
        self.assertEqual(insurance_color({'definitivo':True},'Conferir sequência'),'yellow')
