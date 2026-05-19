"""
Script para limpar o registro de execução de hoje e forçar uma nova verificação
de prazos, permitindo testar o envio de e-mails múltiplas vezes no mesmo dia.
"""

import sys
import os
import datetime

# Adiciona o diretório pai ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database, CAMINHO_DB

def limpar_execucao_hoje(limpar_todas: bool = False):
    """Limpa os registros de verificação de hoje para permitir nova execução
    
    Args:
        limpar_todas: Se True, limpa TODAS as notificações (não só de hoje)
    """
    
    print("=" * 70)
    if limpar_todas:
        print("🔄 FORÇAR VERIFICAÇÃO - LIMPAR TODAS AS NOTIFICAÇÕES")
    else:
        print("🔄 FORÇAR NOVA VERIFICAÇÃO DE PRAZOS")
    print("=" * 70)
    print()
    
    print(f"📂 Banco de dados: {CAMINHO_DB}")
    print()
    
    # Conecta ao banco
    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    hoje = datetime.date.today().strftime('%Y-%m-%d')
    
    try:
        # Verifica se existe registro de hoje
        cursor.execute('''
            SELECT COUNT(*), status FROM verificacoes_prazos 
            WHERE data_verificacao = ?
            GROUP BY status
        ''', (hoje,))
        
        resultados = cursor.fetchall()
        
        if not resultados or len(resultados) == 0:
            print(f"ℹ️  Nenhuma verificação registrada para hoje ({hoje})")
            print("   O sistema executará normalmente ao abrir o AgendaObras.")
        else:
            print(f"📋 Verificações encontradas para hoje ({hoje}):")
            for row in resultados:
                count = row[0]
                status = row[1]
                print(f"   • {count} registro(s) com status '{status}'")
            print()
            
            # Deleta registros de hoje
            cursor.execute('''
                DELETE FROM verificacoes_prazos 
                WHERE data_verificacao = ?
            ''', (hoje,))
            
            linhas_deletadas = cursor.rowcount
            conn.commit()
            
            print(f"✅ {linhas_deletadas} registro(s) removido(s)!")
            print()
        
        # Limpa registros de notificações para forçar reenvio
        if limpar_todas:
            print("🔄 Limpando TODAS as notificações e tentativas...")
            
            # Busca todas as tarefas que têm notificação OU tentativas > 0
            cursor.execute('''
                SELECT id, descricao, tentativas_reiteracao, ultima_notificacao
                FROM obra_checklist 
                WHERE ultima_notificacao IS NOT NULL
                   OR tentativas_reiteracao > 0
                   OR status_notificacao != 'pendente'
            ''')
            
            tarefas = cursor.fetchall()
            
            if tarefas:
                print(f"   Encontradas {len(tarefas)} tarefa(s) com notificação/tentativas:")
                for t in tarefas[:10]:  # Mostra até 10
                    data_notif = t['ultima_notificacao'][:10] if t['ultima_notificacao'] else 'NULL'
                    print(f"   • Tarefa {t['id']}: {t['descricao']} (tent: {t['tentativas_reiteracao']}, última: {data_notif})")
                if len(tarefas) > 10:
                    print(f"   ... e mais {len(tarefas) - 10} tarefa(s)")
                print()
                
                # Reseta todos os campos de notificação de TODAS as tarefas
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET ultima_notificacao = NULL,
                        tentativas_reiteracao = 0,
                        status_notificacao = 'pendente'
                    WHERE ultima_notificacao IS NOT NULL
                       OR tentativas_reiteracao > 0
                       OR status_notificacao != 'pendente'
                ''')
                
                tarefas_limpas = cursor.rowcount
                conn.commit()
                
                print(f"✅ {tarefas_limpas} tarefa(s) resetada(s) completamente!")
                print("   (TODAS as notificações e tentativas foram removidas)")
            else:
                print(f"ℹ️  Nenhuma tarefa tinha notificação ou tentativas.")
        else:
            print("🔄 Limpando registros de notificações de hoje...")
            
            # Busca tarefas que foram notificadas hoje OU têm inconsistências
            cursor.execute('''
                SELECT id, descricao, tentativas_reiteracao, ultima_notificacao
                FROM obra_checklist 
                WHERE (ultima_notificacao IS NOT NULL
                       AND substr(ultima_notificacao, 1, 10) = ?)
                   OR (tentativas_reiteracao > 0 AND ultima_notificacao IS NULL)
            ''', (hoje,))
            
            tarefas = cursor.fetchall()
            
            if tarefas:
                print(f"   Encontradas {len(tarefas)} tarefa(s) para resetar:")
                for t in tarefas:
                    data_notif = t['ultima_notificacao'][:10] if t['ultima_notificacao'] else 'NULL (INCONSISTENTE!)'
                    print(f"   • Tarefa {t['id']}: {t['descricao']} (tent: {t['tentativas_reiteracao']}, última: {data_notif})")
                print()
                
                # Reseta todos os campos de notificação
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET ultima_notificacao = NULL,
                        tentativas_reiteracao = 0,
                        status_notificacao = 'pendente'
                    WHERE (ultima_notificacao IS NOT NULL
                           AND substr(ultima_notificacao, 1, 10) = ?)
                       OR (tentativas_reiteracao > 0 AND ultima_notificacao IS NULL)
                ''', (hoje,))
                
                tarefas_limpas = cursor.rowcount
                conn.commit()
                
                print(f"✅ {tarefas_limpas} tarefa(s) resetada(s) completamente!")
                print("   (última_notificacao, tentativas_reiteracao e status_notificacao)")
                print("   (incluindo tarefas com inconsistências)")
            else:
                print(f"ℹ️  Nenhuma tarefa precisava ser resetada.")
        
        print()
        
        # Limpa histórico de notificações
        if limpar_todas:
            print("🔄 Limpando TODO o histórico de notificações...")
            cursor.execute('DELETE FROM historico_notificacoes')
            historico_deletado = cursor.rowcount
            conn.commit()
            
            if historico_deletado > 0:
                print(f"✅ {historico_deletado} registro(s) de histórico removido(s)!")
            else:
                print(f"ℹ️  Nenhum registro no histórico.")
        else:
            print("🔄 Limpando histórico de notificações de hoje...")
            cursor.execute('''
                DELETE FROM historico_notificacoes 
                WHERE substr(data_envio, 1, 10) = ?
            ''', (hoje,))
            
            historico_deletado = cursor.rowcount
            conn.commit()
            
            if historico_deletado > 0:
                print(f"✅ {historico_deletado} registro(s) de histórico removido(s)!")
            else:
                print(f"ℹ️  Nenhum registro no histórico de hoje.")
        
        print()
        
        # Mostra quantas tarefas ainda precisam ser enviadas
        print("📊 Verificando tarefas que precisam de notificação...")
        hoje_obj = datetime.date.today()
        
        # Primeiro detecta inconsistências
        cursor.execute('''
            SELECT COUNT(*) as total
            FROM obra_checklist
            WHERE tentativas_reiteracao > 0 AND ultima_notificacao IS NULL
        ''')
        
        inconsistentes = cursor.fetchone()['total']
        
        if inconsistentes > 0:
            print(f"⚠️  ATENÇÃO: {inconsistentes} tarefa(s) com inconsistência detectada!")
            print(f"   (tentativas > 0 mas última_notificacao = NULL)")
            print()
        
        # Agora busca tarefas vencidas
        cursor.execute('''
            SELECT COUNT(*) as total
            FROM obra_checklist oc
            WHERE oc.concluido = 0 
            AND oc.bloqueado = 0 
            AND oc.data_limite IS NOT NULL
            AND date(oc.data_limite) <= date(?)
        ''', (hoje,))
        
        total_pendentes = cursor.fetchone()['total']
        
        if total_pendentes > 0:
            print(f"⚠️  {total_pendentes} tarefa(s) vencida(s) aguardando notificação!")
            
            # Lista as tarefas
            cursor.execute('''
                SELECT oc.id, oc.descricao, oc.data_limite, o.nome_contrato
                FROM obra_checklist oc
                JOIN obras o ON oc.obra_id = o.id
                WHERE oc.concluido = 0 
                AND oc.bloqueado = 0 
                AND oc.data_limite IS NOT NULL
                AND date(oc.data_limite) <= date(?)
                ORDER BY oc.data_limite
                LIMIT 10
            ''', (hoje,))
            
            tarefas_pendentes = cursor.fetchall()
            print()
            print("   Exemplos:")
            for t in tarefas_pendentes:
                data_limite_formatada = datetime.datetime.strptime(t['data_limite'], '%Y-%m-%d').strftime('%d/%m/%Y')
                print(f"   • {t['descricao']} - {t['nome_contrato']} (vence: {data_limite_formatada})")
            
            if total_pendentes > 10:
                print(f"   ... e mais {total_pendentes - 10} tarefa(s)")
        else:
            print("✅ Nenhuma tarefa vencida pendente no momento.")
        
        print()
        print("=" * 70)
        print("✅ LIMPEZA COMPLETA REALIZADA!")
        print("=" * 70)
        print()
        print("📊 O que foi resetado:")
        print("   • Registros de verificação de prazos de hoje")
        if limpar_todas:
            print("   • TODAS as notificações de TODAS as datas")
            print("   • TODAS as tentativas de reiteração (voltaram para 0)")
            print("   • TODOS os status de notificação (voltaram para 'pendente')")
            print("   • TODO o histórico de e-mails")
        else:
            print("   • Última notificação das tarefas (apenas hoje)")
            print("   • Tentativas de reiteração de hoje (voltaram para 0)")
            print("   • Status de notificação de hoje (voltou para 'pendente')")
            print("   • Histórico de e-mails enviados hoje")
        print()
        print("🔔 PRÓXIMOS PASSOS:")
        print("   1. Execute o AgendaObras:")
        print("      python AgendaObras.py")
        print()
        print("   2. O sistema fará a verificação automaticamente")
        print("      e enviará e-mails para TODAS as tarefas vencidas")
        print()
        print("   OU")
        print()
        print("   Execute o teste de envio manual com debug:")
        print("   python test\\test_forcar_envio_debug.py")
        print()
        if not limpar_todas:
            print("💡 DICA: Para limpar TODAS as notificações (não só de hoje):")
            print("   python test\\test_forcar_verificacao.py --all")
        print()
        
    except Exception as e:
        print(f"❌ Erro ao limpar registros: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    # Verifica se o usuário passou argumento para limpar todas
    limpar_todas = len(sys.argv) > 1 and sys.argv[1].lower() in ['--all', '-a', 'all', 'todas']
    
    if limpar_todas:
        print("\n⚠️  MODO: Limpeza COMPLETA de todas as notificações\n")
    
    limpar_execucao_hoje(limpar_todas)

    # Rode python test\test_forcar_verificacao.py --all no terminal 
