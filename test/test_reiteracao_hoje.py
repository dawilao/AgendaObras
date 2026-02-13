"""
Script de teste para criar uma obra com tarefa configurada para receber
a PRIMEIRA REITERAÇÃO hoje (13/02/2026).

Propósito: Testar se o e-mail de reiteração é enviado ao abrir o programa.

Lógica:
- Cria uma obra com data de criação há 5 dias (08/02/2026)
- Cria uma tarefa do tipo A (com reiteração) com prazo de 2 dias
- Data limite: 11/02/2026 (2 dias atrás)
- Hoje (13/02/2026): Sistema deve detectar e enviar 1ª reiteração
"""

import sys
import os
import datetime

# Adiciona o diretório pai ao path para importar os módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database, CAMINHO_DB

def criar_obra_teste_reiteracao():
    """Cria obra e tarefa configuradas para reiteração hoje"""
    
    print("=" * 70)
    print("🔔 TESTE: Primeira Reiteração Hoje (13/02/2026)")
    print("=" * 70)
    print()
    
    # Usa o mesmo caminho do banco que o AgendaObras usa
    print(f"📂 Banco de dados: {CAMINHO_DB}")
    print()
    
    # Conecta ao banco de dados
    db = Database()  # Usa o caminho padrão do sistema
    
    # Data de hoje: 13/02/2026
    hoje = datetime.date.today()
    
    # Data limite da tarefa: 2 dias atrás (11/02/2026) para reiteração hoje
    data_limite_tarefa = (hoje - datetime.timedelta(days=2)).strftime('%Y-%m-%d')
    
    conn = None
    try:
        # 1. Cria a obra de teste usando o método normal (gera todas as tarefas)
        print("📝 Criando obra de teste com todas as tarefas...")
        obra_id = db.criar_obra(
            nome_contrato='TESTE 3',
            cliente='Cliente Teste Ltda',
            valor_contrato=100000.00,
            data_inicio='',
            status='Em Andamento',
            contrato_ic='IC-TESTE',
            prefixo_agencia='AG999',
            servico='Teste de Sistema de Reiteração',
            mes_execucao='Fevereiro',
            ano_execucao=2026
        )
        
        print(f"✅ Obra criada com ID: {obra_id}")
        print(f"   Nome: TESTE 3")
        print(f"   Todas as tarefas padrão foram criadas automaticamente!")
        print()
        
        # 2. Agora modifica a tarefa "RETORNO PROJETO E ORÇAMENTO" para ter reiteração hoje
        conn = db.get_connection()
        cursor = conn.cursor()
        
        print("🔧 Modificando tarefa 'RETORNO PROJETO E ORÇAMENTO' para teste...")
        cursor.execute('''
            UPDATE obra_checklist 
            SET data_limite = ?,
                tentativas_reiteracao = 0,
                ultima_notificacao = NULL,
                status_notificacao = 'pendente'
            WHERE obra_id = ? 
            AND descricao = 'RETORNO PROJETO E ORÇAMENTO'
        ''', (data_limite_tarefa, obra_id))
        
        if cursor.rowcount == 0:
            print("❌ Tarefa 'RETORNO PROJETO E ORÇAMENTO' não encontrada!")
            conn.close()
            return
        
        # Busca a tarefa modificada para exibir info
        cursor.execute('''
            SELECT id, descricao, tipo, prazo_dias, data_limite
            FROM obra_checklist 
            WHERE obra_id = ? AND descricao = 'RETORNO PROJETO E ORÇAMENTO'
        ''', (obra_id,))
        
        tarefa = cursor.fetchone()
        tarefa_id = tarefa['id']
        
        # Conta total de tarefas criadas
        cursor.execute('''
            SELECT COUNT(*) as total FROM obra_checklist WHERE obra_id = ?
        ''', (obra_id,))
        total_tarefas = cursor.fetchone()['total']
        
        print(f"✅ Tarefa modificada com ID: {tarefa_id}")
        print(f"   Descrição: {tarefa['descricao']}")
        print(f"   Tipo: {tarefa['tipo']} (com reiteração)")
        print(f"   Data Limite ORIGINAL: removida")
        print(f"   Data Limite NOVA: {datetime.datetime.strptime(data_limite_tarefa, '%Y-%m-%d').strftime('%d/%m/%Y')}")
        print(f"   Status: Vencida há 2 dias")
        print(f"   Tentativas Reiteração: 0")
        print()
        print(f"📊 Total de tarefas na obra: {total_tarefas}")
        print()
        
        # Commit das mudanças
        conn.commit()
        
        print("=" * 70)
        print("✅ CONFIGURAÇÃO CONCLUÍDA!")
        print("=" * 70)
        print()
        print("📋 RESUMO DO TESTE:")
        print(f"   • Hoje: {hoje.strftime('%d/%m/%Y')}")
        print(f"   • Data Limite da Tarefa: {datetime.datetime.strptime(data_limite_tarefa, '%Y-%m-%d').strftime('%d/%m/%Y')}")
        print(f"   • Dias em Atraso: 2 dias")
        print(f"   • Reiteração Esperada: 1ª REITERAÇÃO")
        print()
        print("🔔 PRÓXIMOS PASSOS:")
        print("   1. Execute: python test\\test_forcar_verificacao.py")
        print("      (Para limpar verificação de hoje e permitir novo teste)")
        print()
        print("   2. Execute o AgendaObras: python AgendaObras.py")
        print("      OU execute: python test\\test_envio_email_manual.py")
        print()
        print("   3. O sistema deve detectar a tarefa vencida há 2 dias")
        print("   4. Um e-mail de 1ª reiteração deve ser enviado")
        print("   5. Verifique sua caixa de entrada")
        print()
        print("💡 CRONOGRAMA DE REITERAÇÕES:")
        print("   • Dia 11/02: Tarefa venceu")
        print("   • Dia 13/02 (HOJE): 1ª Reiteração")
        print("   • Dia 15/02: 2ª Reiteração (se não concluída)")
        print("   • Dia 17/02: 3ª Reiteração (CRÍTICA)")
        print("   • Dia 18/02+: Alertas críticos diários")
        print()
        print("📝 NOTA: A obra foi criada com TODAS as tarefas padrão,")
        print("   mas apenas 'RETORNO PROJETO E ORÇAMENTO' está configurada")
        print("   para disparar reiteração hoje.")
        print()
        
    except Exception as e:
        print(f"❌ Erro ao criar teste: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
            except:
                pass
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


if __name__ == "__main__":
    criar_obra_teste_reiteracao()

    # Rode python test\test_reiteracao_hoje.py no terminal
