"""
Script para testes manuais do serviço de email
Execute este arquivo para testar o envio de emails reais
"""

import sys
import os
import datetime

# Adiciona o diretório pai ao path para importar os módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from email_service import EmailService
from database import Database
from config import EmailConfig


def teste_configuracao():
    """Testa se a configuração está carregada corretamente"""
    print("\n" + "="*60)
    print("1️⃣  TESTE: Configuração de Email")
    print("="*60)
    
    try:
        config = EmailConfig.carregar()
        
        if config.is_configured():
            print("✅ Configuração carregada com sucesso!")
            print(f"   Servidor SMTP: {config.smtp_server}:{config.smtp_port}")
            print(f"   Usuário: {config.smtp_user}")
            print(f"   Remetente: {config.email_remetente}")
            print(f"   Usar TLS: {'Sim' if config.usar_tls else 'Não'}")
            return True
        else:
            print("❌ Configuração incompleta!")
            print("   Configure o arquivo Email_config.env antes de continuar.")
            return False
            
    except Exception as e:
        print(f"❌ Erro ao carregar configuração: {e}")
        return False


def teste_conexao_smtp(email_service):
    """Testa a conexão com o servidor SMTP"""
    print("\n" + "="*60)
    print("2️⃣  TESTE: Conexão SMTP")
    print("="*60)
    
    sucesso, mensagem = email_service.testar_conexao()
    
    if sucesso:
        print(f"✅ {mensagem}")
        return True
    else:
        print(f"❌ {mensagem}")
        return False


def teste_envio_email_simples(email_service, destinatario):
    """Testa envio de email simples"""
    print("\n" + "="*60)
    print("3️⃣  TESTE: Envio de Email Simples")
    print("="*60)
    
    assunto = "🧪 Teste - AgendaObras"
    corpo_html = """
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #2196F3;">🧪 Email de Teste</h2>
            <p>Este é um email de teste do sistema <strong>AgendaObras</strong>.</p>
            <p>Se você recebeu este email, significa que o serviço de email está funcionando corretamente!</p>
            <hr style="border: 1px solid #ddd; margin: 20px 0;">
            <p style="color: #666; font-size: 12px;">
                Data/Hora: {data_hora}<br>
                Sistema: AgendaObras v1.0
            </p>
        </body>
    </html>
    """.format(data_hora=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S'))
    
    print(f"Enviando email para: {destinatario}")
    sucesso, mensagem = email_service.enviar_email(destinatario, assunto, corpo_html)
    
    if sucesso:
        print(f"✅ {mensagem}")
        return True
    else:
        print(f"❌ {mensagem}")
        return False


def teste_email_alerta_tipo_a(email_service, destinatario):
    """Testa envio de email de alerta Tipo A"""
    print("\n" + "="*60)
    print("4️⃣  TESTE: Email Alerta Tipo A (com reiteração)")
    print("="*60)
    
    tarefa_exemplo = {
        'nome_contrato': "Contrato Exemplo - Teste",
        'cliente': "Cliente Teste LTDA",
        'descricao': "Entrega de documentação técnica",
        'data_limite': "2026-02-05"
    }
    
    corpo_html = email_service.criar_email_alerta_tipo_a(tarefa_exemplo, reiteracao=1)
    assunto = f"⚠️ Alerta de Prazo - {tarefa_exemplo['nome_contrato']}"
    
    print(f"Enviando alerta Tipo A para: {destinatario}")
    sucesso, mensagem = email_service.enviar_email(destinatario, assunto, corpo_html)
    
    if sucesso:
        print(f"✅ {mensagem}")
        return True
    else:
        print(f"❌ {mensagem}")
        return False


def teste_email_alerta_tipo_b(email_service, destinatario):
    """Testa envio de email de alerta Tipo B"""
    print("\n" + "="*60)
    print("5️⃣  TESTE: Email Alerta Tipo B (prazo fixo)")
    print("="*60)
    
    tarefa_exemplo = {
        'nome_contrato': "Contrato Infraestrutura - Teste",
        'cliente': "Prefeitura Municipal",
        'descricao': "Vistoria e aprovação de obra",
        'data_limite': datetime.date.today().strftime('%Y-%m-%d')  # Hoje
    }
    
    corpo_html = email_service.criar_email_alerta_tipo_b(tarefa_exemplo)
    assunto = f"🔔 Prazo Importante - {tarefa_exemplo['nome_contrato']}"
    
    print(f"Enviando alerta Tipo B para: {destinatario}")
    sucesso, mensagem = email_service.enviar_email(destinatario, assunto, corpo_html)
    
    if sucesso:
        print(f"✅ {mensagem}")
        return True
    else:
        print(f"❌ {mensagem}")
        return False


def teste_email_critico(email_service, destinatario):
    """Testa envio de email crítico"""
    print("\n" + "="*60)
    print("6️⃣  TESTE: Email Crítico (tarefa atrasada)")
    print("="*60)
    
    data_passada = datetime.date.today() - datetime.timedelta(days=7)
    
    tarefa_exemplo = {
        'nome_contrato': "Contrato Urgente - Teste",
        'cliente': "Cliente Prioritário S.A.",
        'descricao': "Regularização pendente",
        'data_limite': data_passada.strftime('%Y-%m-%d')
    }
    
    corpo_html = email_service.criar_email_critico_atrasado(tarefa_exemplo, dias_atraso=7)
    assunto = f"🚨 CRÍTICO - {tarefa_exemplo['nome_contrato']}"
    
    print(f"Enviando alerta crítico para: {destinatario}")
    sucesso, mensagem = email_service.enviar_email(destinatario, assunto, corpo_html)
    
    if sucesso:
        print(f"✅ {mensagem}")
        return True
    else:
        print(f"❌ {mensagem}")
        return False


def menu_interativo():
    """Menu interativo para escolher testes"""
    print("\n" + "="*60)
    print("📧 TESTES DE EMAIL - AgendaObras")
    print("="*60)
    
    # Verifica configuração
    if not teste_configuracao():
        print("\n⚠️  Configure o email antes de continuar!")
        return
    
    # Cria instância do serviço (com database mock para testes)
    from unittest.mock import Mock
    mock_db = Mock(spec=Database)
    email_service = EmailService(mock_db)
    
    # Testa conexão
    if not teste_conexao_smtp(email_service):
        print("\n⚠️  Não foi possível conectar ao servidor SMTP!")
        continuar = input("Deseja continuar mesmo assim? (s/n): ")
        if continuar.lower() != 's':
            return
    
    # Solicita email de destino
    print("\n" + "="*60)
    destinatario = input("Digite o email de destino para os testes: ").strip()
    
    if not destinatario or '@' not in destinatario:
        print("❌ Email inválido!")
        return
    
    # Menu de testes
    while True:
        print("\n" + "="*60)
        print("Escolha o teste a executar:")
        print("="*60)
        print("1 - Enviar email simples")
        print("2 - Enviar email de alerta Tipo A")
        print("3 - Enviar email de alerta Tipo B")
        print("4 - Enviar email crítico de atraso")
        print("5 - Executar todos os testes")
        print("0 - Sair")
        print("="*60)
        
        opcao = input("\nOpção: ").strip()
        
        if opcao == '0':
            print("\n👋 Encerrando testes...")
            break
        elif opcao == '1':
            teste_envio_email_simples(email_service, destinatario)
        elif opcao == '2':
            teste_email_alerta_tipo_a(email_service, destinatario)
        elif opcao == '3':
            teste_email_alerta_tipo_b(email_service, destinatario)
        elif opcao == '4':
            teste_email_critico(email_service, destinatario)
        elif opcao == '5':
            print("\n🚀 Executando todos os testes...")
            resultados = []
            resultados.append(teste_envio_email_simples(email_service, destinatario))
            resultados.append(teste_email_alerta_tipo_a(email_service, destinatario))
            resultados.append(teste_email_alerta_tipo_b(email_service, destinatario))
            resultados.append(teste_email_critico(email_service, destinatario))
            
            print("\n" + "="*60)
            print("📊 RESUMO DOS TESTES")
            print("="*60)
            print(f"Total de testes: {len(resultados)}")
            print(f"✅ Sucesso: {sum(resultados)}")
            print(f"❌ Falhas: {len(resultados) - sum(resultados)}")
        else:
            print("❌ Opção inválida!")
        
        input("\nPressione ENTER para continuar...")


if __name__ == '__main__':
    try:
        menu_interativo()
    except KeyboardInterrupt:
        print("\n\n⚠️  Teste interrompido pelo usuário.")
    except Exception as e:
        print(f"\n❌ Erro durante os testes: {e}")
        import traceback
        traceback.print_exc()
