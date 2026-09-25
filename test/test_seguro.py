import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlite3
import tempfile
import unittest
from pathlib import Path
from services.seguro_service import SeguroService
from db.seguro_repo import criar_schema
from db.auth_repo import AuthDatabase


class SeguroTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name)/'obras.db')
        with sqlite3.connect(self.path) as conn:
            conn.execute('CREATE TABLE obras(id INTEGER PRIMARY KEY, cliente TEXT)')
            conn.execute("INSERT INTO obras VALUES(1,'CAIXA')")
            criar_schema(conn)
            criar_schema(conn)
        conn.close()
        self.user = dict(id=7,nome='Validador',sobrenome='Teste',is_admin=False,pode_validar_seguro=True)
        self.contracts = ['CAIXA']
        self.service = SeguroService(self.path, lambda: self.user, lambda uid:self.contracts)

    def update(self, field, value):
        state, _ = self.service.obter(1)
        self.service.alterar(1,field,value,state['revisao'])

    def stage(self, action, **data):
        state,_=self.service.obter(1)
        self.service.registrar_etapa(1,action,dict(evidencia='E-mail de teste - referência fictícia',**data),state['revisao'])

    def accept(self):
        self.stage('solicitacao')
        self.stage('pedido')
        self.stage('recebimento',apolice='Apólice V1',boleto='Boleto V1')
        self.stage('envio')
        self.stage('aceite')

    def test_initial_and_quote_not_final(self):
        self.assertFalse(self.service.obter(1)[0]['definitivo'])
        self.update('cotacao','Aprovada')
        self.assertFalse(self.service.obter(1)[0]['definitivo'])

    def test_release_without_response_requires_reason_and_final_checks(self):
        self.stage('solicitacao')
        self.stage('pedido')
        self.stage('recebimento',apolice='Apólice V1',boleto='Boleto V1')
        self.stage('envio')
        with self.assertRaises(ValueError): self.stage('sem_resposta')
        self.stage('sem_resposta',motivo='Responsável conferiu a caixa e autorizou internamente.')
        state,_=self.service.obter(1)
        self.assertEqual(state['atual']['etapa'],'sem_resposta')
        self.assertFalse(state['definitivo'])
        self.update('ok_seguro',True)
        self.update('ok_boleto',True)
        self.assertTrue(self.service.obter(1)[0]['definitivo'])
        from ui.components.seguro_panel import titulo_seguro
        self.assertIn('Validada internamente',titulo_seguro(self.service.obter(1)[0]))
        self.update('ok_boleto',False)
        self.assertFalse(self.service.obter(1)[0]['definitivo'])

    def test_no_silent_release_after_adjustment_request(self):
        self.stage('solicitacao')
        self.stage('pedido')
        self.stage('recebimento',apolice='Apólice V1',boleto='Boleto V1')
        self.stage('envio')
        self.stage('ajustes',motivo='Corrigir vigência')
        with self.assertRaises(ValueError): self.stage('sem_resposta',motivo='Sem retorno')

    def test_independent_oks_and_revoke_audit(self):
        self.accept()
        self.update('ok_boleto',True)
        self.assertFalse(self.service.obter(1)[0]['definitivo'])
        self.update('ok_seguro',True)
        self.assertTrue(self.service.obter(1)[0]['definitivo'])
        self.update('ok_boleto',False)
        state,_ = self.service.obter(1)
        self.assertFalse(state['definitivo'])
        self.assertEqual(len([h for h in state['historico'] if h['campo'].startswith('ok_')]),3)
        self.assertEqual(state['historico'][0]['anterior'],'true')
        self.assertEqual(state['historico'][0]['novo'],'false')
        self.assertEqual(state['historico'][0]['usuario_id'],7)
        self.assertTrue(state['historico'][0]['data_hora'])

    def test_viewer_and_admin_not_implicitly_validators(self):
        self.user['pode_validar_seguro']=False
        self.assertFalse(self.service.obter(1)[1])
        for admin in [False,True]:
            self.user['is_admin']=admin
            with self.assertRaises(PermissionError): self.update('ok_seguro',True)

    def test_permission_revoked_after_screen_open(self):
        state,_ = self.service.obter(1)
        self.user['pode_validar_seguro']=False
        with self.assertRaises(PermissionError): self.service.alterar(1,'ok_boleto',True,state['revisao'])

    def test_contract_access_and_session_changes(self):
        self.contracts=[]
        with self.assertRaises(PermissionError): self.service.obter(1)
        self.contracts=['CAIXA']
        self.user['id']=8
        with self.assertRaises(PermissionError): self.update('ok_seguro',True)

    def test_stale_update_does_not_overwrite(self):
        self.accept()
        self.update('ok_seguro',True)
        with self.assertRaises(ValueError): self.service.alterar(1,'ok_boleto',True,0)
        self.assertFalse(self.service.obter(1)[0]['ok_boleto'])

    def test_noop_and_bad_values(self):
        with self.assertRaises(ValueError): self.update('ok_seguro',False)
        self.assertEqual(self.service.obter(1)[0]['historico'],[])
        for field,value in [('unexpected',True),('ok_seguro','true'),('cotacao','Final')]:
            with self.assertRaises(ValueError): self.update(field,value)
        self.assertEqual(self.service.obter(1)[0]['historico'],[])

    def test_auth_migration_defaults_to_no_permission(self):
        auth=AuthDatabase(str(Path(self.tmp.name)/'users.db'))
        auth.criar_usuario('Nome','Teste','test@example.invalid','fake-test-only')
        user=auth.listar_usuarios()[0]
        self.assertEqual(user['pode_validar_seguro'],0)
        self.assertEqual(auth.obter_usuario_por_id(user['id'])['pode_validar_seguro'],0)

    def test_correction_creates_new_version_without_carrying_oks(self):
        self.accept()
        self.update('ok_seguro',True)
        self.update('ok_boleto',True)
        self.stage('nova_rodada',motivo='Nova emissão necessária')
        state,_=self.service.obter(1)
        self.assertFalse(state['definitivo'])
        self.assertEqual(state['atual']['numero'],2)
        self.assertEqual(state['atual']['apolice'],'')
        self.assertTrue(state['rodadas'][1]['ok_seguro'])
        self.assertEqual(state['rodadas'][1]['apolice'],'Apólice V1')
        with self.assertRaises(ValueError): self.update('ok_seguro',True)
        self.stage('recebimento',apolice='Apólice V2',boleto='Boleto V2')
        self.stage('envio')
        self.stage('ajustes',motivo='Banco pediu correção')
        self.stage('nova_rodada',motivo='Pedido de correção à seguradora')
        self.assertEqual(self.service.obter(1)[0]['atual']['numero'],3)

    def test_cannot_skip_steps_or_omit_documents_and_evidence(self):
        with self.assertRaises(ValueError): self.stage('aceite')
        self.stage('solicitacao')
        with self.assertRaises(ValueError): self.stage('recebimento',apolice='X',boleto='Y')
        self.stage('pedido')
        with self.assertRaises(ValueError): self.stage('recebimento',apolice='X')
        state,_=self.service.obter(1)
        with self.assertRaises(ValueError): self.service.registrar_etapa(1,'recebimento',dict(apolice='X',boleto='Y'),state['revisao'])
        self.assertEqual(self.service.obter(1)[0]['atual']['etapa'],'pedido')

    def test_old_unversioned_approvals_do_not_release(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO obra_seguro(obra_id,tipo,ok_seguro,ok_boleto) VALUES(1,'nao_classificado',1,1)")
        conn.close()
        self.assertFalse(self.service.obter(1)[0]['definitivo'])

    def test_workflow_requires_permission(self):
        self.user['pode_validar_seguro']=False
        with self.assertRaises(PermissionError): self.stage('solicitacao')

if __name__ == '__main__': unittest.main()
