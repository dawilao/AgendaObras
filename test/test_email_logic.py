import sys
import os
import unittest

# Adiciona o diretório pai ao path para importar os módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock
from email_service import EmailService
from datetime import datetime, timedelta

class TestEmailLogic(unittest.TestCase):

    def setUp(self):
        # Mock database and email configuration
        self.mock_database = MagicMock()
        self.email_service = EmailService(self.mock_database)
        self.email_service.config = MagicMock()
        self.email_service.config.is_configured.return_value = True
        self.email_service.config.email_remetente = "test@example.com"
        self.email_service.config.smtp_server = "smtp.example.com"
        self.email_service.config.smtp_port = 587
        self.email_service.config.smtp_user = "user"
        self.email_service.config.smtp_password = "password"
        self.email_service.config.usar_tls = True

    def test_email_alerta_tipo_a(self):
        """Testa a lógica de envio de email para tarefas com reiteração."""
        print("\n" + "="*70)
        print("TESTE: E-mail de Alerta Tipo A (Com Reiteração)")
        print("="*70)
        
        tarefa = {
            'nome_contrato': "Contrato Teste",
            'cliente': "Cliente Teste",
            'descricao': "Tarefa de teste",
            'data_limite': (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
        }
        
        print(f"\n📋 Dados da tarefa:")
        print(f"   - Contrato: {tarefa['nome_contrato']}")
        print(f"   - Cliente: {tarefa['cliente']}")
        print(f"   - Descrição: {tarefa['descricao']}")
        print(f"   - Data Limite: {tarefa['data_limite']}")

        for reiteracao in range(1, 4):
            print(f"\n🔄 Testando reiteração {reiteracao}/3...")
            email_html = self.email_service.criar_email_alerta_tipo_a(tarefa, reiteracao)
            
            print(f"   ✓ E-mail gerado com {len(email_html)} caracteres")
            
            self.assertIn("Tarefa de teste", email_html)
            print(f"   ✓ Descrição da tarefa presente no e-mail")
            
            self.assertIn("Cliente Teste", email_html)
            print(f"   ✓ Nome do cliente presente no e-mail")
            
            if reiteracao == 3:
                self.assertIn("ATENÇÃO: Esta é a última reiteração automática", email_html)
                print(f"   ✓ Mensagem de última reiteração presente")
        
        print(f"\n✅ Teste concluído: Todos os e-mails de reiteração gerados corretamente")
        print("="*70)

    def test_email_critico_atrasado(self):
        """Testa a lógica de envio de email crítico para tarefas atrasadas."""
        print("\n" + "="*70)
        print("TESTE: E-mail Crítico para Tarefa Atrasada")
        print("="*70)
        
        tarefa = {
            'nome_contrato': "Contrato Teste",
            'cliente': "Cliente Teste",
            'descricao': "Tarefa de teste",
            'data_limite': (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        }
        
        dias_atraso = 5
        
        print(f"\n📋 Dados da tarefa atrasada:")
        print(f"   - Contrato: {tarefa['nome_contrato']}")
        print(f"   - Cliente: {tarefa['cliente']}")
        print(f"   - Descrição: {tarefa['descricao']}")
        print(f"   - Data Limite: {tarefa['data_limite']}")
        print(f"   - Dias de Atraso: {dias_atraso}")
        
        print(f"\n⚠️ Gerando e-mail crítico...")
        email_html = self.email_service.criar_email_critico_atrasado(tarefa, dias_atraso)
        print(f"   ✓ E-mail gerado com {len(email_html)} caracteres")
        
        self.assertIn("ATRASADA", email_html)
        print(f"   ✓ Marcação 'ATRASADA' presente no e-mail")
        
        self.assertIn("5 DIAS EM ATRASO", email_html)
        print(f"   ✓ Indicação de '{dias_atraso} DIAS EM ATRASO' presente no e-mail")
        
        print(f"\n✅ Teste concluído: E-mail crítico gerado corretamente")
        print("="*70)

if __name__ == "__main__":
    unittest.main(verbosity=2)
