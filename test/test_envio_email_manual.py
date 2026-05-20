"""
Script para testar envio de e-mails de reiteração manualmente,
sem precisar abrir a UI do AgendaObras.
"""

import sys
import os

# Adiciona o diretório pai ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database, CAMINHO_DB
from services.email_service import EmailService
from services.notificador import GeradorTarefasRecorrentes, NotificadorPrazos

def main():
    print("=" * 70)
    print("📧 TESTE DE ENVIO DE E-MAILS - NotificadorPrazos")
    print("=" * 70)
    print()
    
    print(f"📂 Banco de dados: {CAMINHO_DB}")
    print()
    
    # Inicializa serviços
    print("🔧 Inicializando serviços...")
    db = Database()
    email_service = EmailService(db)
    gerador_recorrentes = GeradorTarefasRecorrentes(db)
    notificador = NotificadorPrazos(db, email_service, gerador_recorrentes)
    
    print("✅ Serviços inicializados!")
    print()
    
    # Verifica configuração de e-mail
    if not email_service.config.email_remetente or not email_service.config.smtp_servidor:
        print("⚠️  AVISO: Configurações de e-mail não encontradas!")
        print("   Configure o e-mail em 'Configurações > E-mail' antes de testar.")
        print()
        resposta = input("Deseja continuar mesmo assim? (s/N): ")
        if resposta.lower() != 's':
            print("❌ Teste cancelado.")
            return
        print()
    
    # Executa verificação FORÇADA (ignora se já executou hoje)
    print("🔄 Executando verificação FORÇADA de prazos...")
    print("   (Isso vai enviar e-mails se houver tarefas atrasadas)")
    print()
    
    sucesso = notificador.verificar_agora(forcar=True)
    
    print()
    print("=" * 70)
    if sucesso:
        print("✅ Verificação concluída com sucesso!")
    else:
        print("❌ Verificação não pôde ser executada (já foi feita hoje).")
        print("   Execute: python test\\test_forcar_verificacao.py")
        print("   Para limpar o registro e permitir nova execução.")
    print("=" * 70)
    print()
    print("💡 Dica: Verifique sua caixa de entrada para ver os e-mails enviados.")
    print("   Logs de envio são salvos na tabela 'historico_notificacoes' do banco.")

if __name__ == "__main__":
    main()
