import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from comunicacoes.refino_dia3 import classify,out_of_scope


def sample():
    """Casos sintéticos do Dia 3 (mesmos dados da demonstração, sem depender dela)."""
    works=[dict(id='test-altos',name='Altos — reforma da cobertura',ic='14126/2025',confirmed=True,aliases=['ALTOS']),dict(id='test-almenara',name='Almenara',ic='00744/2025',confirmed=True,aliases=['ALMENARA']),dict(id='test-itaberaba',name='Itaberaba',ic='',confirmed=False,aliases=['ITABERABA']),dict(id='test-alagoas',name='Exemplo de obra em Alagoas',ic='00999/2026',confirmed=True,aliases=['EXEMPLO ALAGOAS'])]
    rows=[]
    def add(subject,body,sender='equipe@machengenharia.com.br',files=()):
        i=len(rows)+1
        rows.append(dict(id=i,subject=subject,body=body,sender=sender,recipients='engenharia@caixa.gov.br',cc='',sent_date='Tue, 28 Apr 2026 09:54:00 -0300',message_id=f'<demo-{i}@example.invalid>',refs='[]',fingerprint=f'demo-{i}',status='revisar',obra_id=None,suggestion=None,work_name=None,reviewed=0,attachments=[dict(id=i*10+j,name=n,mime='application/pdf',size=1024,sha256=f'demo-{i}-{j}') for j,n in enumerate(files)]))
    add('CONFIRMAÇÃO DE MEDIÇÃO — Agência de Altos — IC14126-2025','Solicitamos conferência da medição da reforma da cobertura.')
    add('RES: CONFIRMAÇÃO DE MEDIÇÃO — Agência de Altos — IC14126-2025','Favor observar e responder à mensagem anexa.','fiscal@caixa.gov.br')
    add('ALMENARA IC 00744/2025 — documentos contratuais','Encaminhamos a apólice de seguro garantia contratual de Almenara.',files=['apolice-garantia.pdf','boleto.pdf'])
    add('ALMENARA IC 00744/2025 — Projetos','Solicitamos ajuste na apólice do seguro de risco de engenharia da obra Almenara.','engenharia@caixa.gov.br')
    add('O futuro das instalações técnicas!','Convite para workshop. Inscreva-se no evento.','comunicacao@crea.example.invalid')
    add('Alterada senha de acesso','Aviso de alteração de senha. Conteúdo de autenticação omitido.','conta@example.invalid')
    add('Seu voo para Curitiba foi alterado','Atualização da sua viagem.','companhia@example.invalid')
    add('Implantação de Política — Cartão Corporativo Vexpense','Política administrativa corporativa.','administracao@machengenharia.com.br')
    add('Nova mensagem em Armário Arquivo Gabinete','Aviso de entrega do vendedor.','loja@example.invalid')
    add('Protocolo de substituição de ART sem custo','Exemplo informado por Lucas como fora do escopo.','crea@example.invalid')
    add('EXEMPLO ALAGOAS IC 00999/2026 — Projetos','Encaminhamos o projeto para análise.')
    skipped=[dict(subject='Impacto de Obras no Sistema de Climatização — Itaberaba',sender='obras@caixa.gov.br',sent_date='Wed, 18 Mar 2026 08:52:00 -0300',size=18979225,note='18,1 MB acima do limite de 15 MB',uid='demo-heavy',folder='INBOX',mailbox='demo',validity='1')]
    return rows,works,skipped


class RefinoTests(unittest.TestCase):
    def setUp(self):self.rows,self.works,self.skipped=sample()
    def test_altos(self):
        r=classify(self.rows[0],self.works)
        self.assertEqual((r['work'],r['safe']),('test-altos',True))
    def test_password_not_work_access(self):self.assertEqual(classify(self.rows[5],self.works)['bucket'],'spam')
    def test_workshop(self):self.assertEqual(classify(self.rows[4],self.works)['bucket'],'spam')
    def test_art_needs_context(self):self.assertEqual(classify(self.rows[9],self.works)['bucket'],'pending')
    def test_manual_art_exclusion(self):self.assertEqual(classify(self.rows[9],self.works,{'bucket':'spam'})['bucket'],'spam')
    def test_nao_e_spam_ignora_fora_do_escopo(self):
        self.assertNotEqual(classify(self.rows[4],self.works,allow_out_of_scope=False)['bucket'],'spam')
    def test_restore_persists(self):self.assertEqual(classify(self.rows[4],self.works,{'bucket':'pending'})['bucket'],'pending')
    def test_not_guess_year(self):
        r=dict(self.rows[0],subject='Altos IC14126-2024')
        self.assertFalse(classify(r,self.works)['safe'])
    def test_body_ic(self):
        r=dict(self.rows[0],subject='Documento da obra',body='Referente ao IC 14126/2025.')
        self.assertTrue(classify(r,self.works)['safe'])
    def test_body_conflict(self):
        r=dict(self.rows[0],body='Referente ao IC 00744/2025.')
        self.assertFalse(classify(r,self.works)['safe'])
    def test_same_city_not_safe(self):
        r=dict(self.rows[0],subject='Visita em Altos',body='Agendamento')
        self.assertFalse(classify(r,self.works)['safe'])
    def test_typo_and_year_conflict_are_suggested_not_confirmed(self):
        works=[dict(id='almenara',name='Almenara',ic='00744/2026',confirmed=False,aliases=['Almenara'])]
        r=dict(self.rows[0],subject='AIO - ALMERARA - IC 00744-2025',body='Registro de vistoria')
        result=classify(r,works)
        self.assertEqual(result['work'],'almenara')
        self.assertFalse(result['safe'])
        self.assertEqual(result['bucket'],'pending')
        self.assertIn('00744/2025',result['reason'])
        self.assertIn('00744/2026',result['reason'])
    def test_same_number_multiple_years_has_no_suggestion(self):
        works=[dict(id=str(y),name='Obra',ic=f'00744/{y}',confirmed=False,aliases=[]) for y in (2024,2026)]
        r=dict(self.rows[0],subject='IC 00744-2025',body='Registro')
        self.assertIsNone(classify(r,works)['work'])
    def test_contract_without_ic(self):
        r=dict(self.rows[0],subject='Convocação para assinatura de contrato com Garantia - 14126/2025 ARP 09198/2025',body='Documento')
        result=classify(r,self.works)
        self.assertEqual(result['work'],'test-altos')
        self.assertTrue(result['safe'])
    def test_ic_underscore(self):
        r=dict(self.rows[0],subject='Convocação: IC 14126-2025_MACH _ATA 443-2026',body='Documento')
        self.assertTrue(classify(r,self.works)['safe'])
    def test_arp_is_not_work_ic(self):
        from comunicacoes.refino_dia3 import work_codes
        self.assertEqual(work_codes('ARP 14126/2025 ATA 443-2026'),set())
    def test_different_contract_in_body_blocks_auto(self):
        r=dict(self.rows[0],subject='Contrato 14126/2025',body='Ref.: Contrato 00744/2025')
        self.assertFalse(classify(r,self.works)['safe'])
    def test_coordinator_confirmation_survives_reanalysis(self):
        decision=dict(bucket='work',work='test-altos',coordinator_ok=True,validated_at='2026-09-28T15:00:00+00:00',validated_by='Coordenador teste')
        result=classify(self.rows[0],self.works,decision)
        self.assertEqual(result['work'],'test-altos')
        self.assertTrue(result['safe'])
        self.assertIn('OK coordenador encaixe',result['reason'])
        self.assertIn('Coordenador teste',result['reason'])
    def test_pending_manual_work_is_not_safe(self):
        result=classify(self.rows[0],self.works,dict(bucket='pending',work='test-altos'))
        self.assertFalse(result['safe'])
    def test_coordinator_counter_counts_only_explicit_ok(self):
        from comunicacoes.refino_dia3 import coordinator_counts
        auto=dict(bucket='work',work='test-altos',safe=True)
        before=coordinator_counts([auto])
        after=coordinator_counts([dict(auto,coordinator_ok=True)])
        self.assertEqual((before['confirmed'],before['placed']),(0,1))
        self.assertEqual((after['confirmed'],after['placed']),(1,0))
    def test_discarded_ok_does_not_count_as_confirmed(self):
        from comunicacoes.refino_dia3 import coordinator_counts
        counts=coordinator_counts([dict(bucket='trash',work='test-altos',coordinator_ok=True),dict(bucket='pending',work=None)])
        self.assertEqual(counts,dict(confirmed=0,placed=0,unassigned=1,spam=0,trash=1))
    def test_same_city_different_ic_stays_in_correct_work(self):
        works=[dict(id='almenara-1',name='Almenara',ic='00744/2026',confirmed=True,aliases=['Almenara']),dict(id='almenara-2',name='Almenara',ic='00999/2026',confirmed=True,aliases=['Almenara'])]
        for work in works:
            row=dict(self.rows[0],subject='Almenara IC '+work['ic'],body='Documento')
            result=classify(row,works)
            self.assertEqual(result['work'],work['id'])
            self.assertFalse(result['safe'])
    def test_same_city_without_ic_does_not_choose_arbitrary_work(self):
        works=[dict(id=str(i),name='Almenara',ic=f'00{i:03}/2026',confirmed=True,aliases=['Almenara']) for i in [744,999]]
        row=dict(self.rows[0],subject='Almenara - solicitação',body='Documento')
        self.assertIsNone(classify(row,works)['work'])
if __name__=='__main__':unittest.main()
