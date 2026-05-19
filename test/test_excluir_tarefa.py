"""
Script para excluir tarefas ou obras de teste do banco de dados.
"""

import sys
import os

# Adiciona o diretório pai ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database, CAMINHO_DB


def excluir_tarefa_por_id():
    """Exclui uma tarefa específica pelo ID"""
    print()
    print("=" * 70)
    print("🗑️  EXCLUIR TAREFA POR ID")
    print("=" * 70)
    print()
    print(f"📂 Banco de dados: {CAMINHO_DB}")
    print()
    
    # Solicita o ID
    try:
        tarefa_id = input("Digite o ID da tarefa a ser excluída: ").strip()
        tarefa_id = int(tarefa_id)
    except ValueError:
        print("❌ ID inválido!")
        return
    except KeyboardInterrupt:
        print("\n❌ Operação cancelada.")
        return
    
    # Conecta ao banco
    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # Busca informações da tarefa
        cursor.execute('''
            SELECT oc.*, o.nome_contrato, o.cliente
            FROM obra_checklist oc
            JOIN obras o ON oc.obra_id = o.id
            WHERE oc.id = ?
        ''', (tarefa_id,))
        
        tarefa = cursor.fetchone()
        
        if not tarefa:
            print(f"❌ Tarefa com ID {tarefa_id} não encontrada!")
            conn.close()
            return
        
        # Exibe informações
        print()
        print("📋 INFORMAÇÕES DA TAREFA:")
        print(f"   • ID: {tarefa['id']}")
        print(f"   • Descrição: {tarefa['descricao']}")
        print(f"   • Obra: {tarefa['nome_contrato']}")
        print(f"   • Cliente: {tarefa['cliente']}")
        print(f"   • Tipo: {tarefa['tipo']}")
        print(f"   • Data Limite: {tarefa['data_limite'] or 'Não definida'}")
        print(f"   • Concluída: {'Sim' if tarefa['concluido'] else 'Não'}")
        print()
        
        # Confirmação
        confirma = input("⚠️  Tem certeza que deseja EXCLUIR esta tarefa? (sim/não): ").strip().lower()
        
        if confirma not in ['sim', 's', 'yes', 'y']:
            print("\n❌ Exclusão cancelada.")
            conn.close()
            return
        
        # Exclui a tarefa
        cursor.execute('DELETE FROM obra_checklist WHERE id = ?', (tarefa_id,))
        conn.commit()
        
        print()
        print(f"✅ Tarefa {tarefa_id} excluída com sucesso!")
        print()
        
    except Exception as e:
        print(f"❌ Erro ao excluir tarefa: {e}")
        conn.rollback()
    finally:
        conn.close()


def excluir_obra_por_id():
    """Exclui uma obra e todas as suas tarefas pelo ID"""
    print()
    print("=" * 70)
    print("🗑️  EXCLUIR OBRA POR ID")
    print("=" * 70)
    print()
    print(f"📂 Banco de dados: {CAMINHO_DB}")
    print()
    
    # Solicita o ID
    try:
        obra_id = input("Digite o ID da obra a ser excluída: ").strip()
        obra_id = int(obra_id)
    except ValueError:
        print("❌ ID inválido!")
        return
    except KeyboardInterrupt:
        print("\n❌ Operação cancelada.")
        return
    
    # Conecta ao banco
    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # Busca informações da obra
        cursor.execute('SELECT * FROM obras WHERE id = ?', (obra_id,))
        obra = cursor.fetchone()
        
        if not obra:
            print(f"❌ Obra com ID {obra_id} não encontrada!")
            conn.close()
            return
        
        # Conta tarefas
        cursor.execute('SELECT COUNT(*) as total FROM obra_checklist WHERE obra_id = ?', (obra_id,))
        total_tarefas = cursor.fetchone()['total']
        
        # Exibe informações
        print()
        print("📋 INFORMAÇÕES DA OBRA:")
        print(f"   • ID: {obra['id']}")
        print(f"   • Nome: {obra['nome_contrato']}")
        print(f"   • Cliente: {obra['cliente']}")
        print(f"   • Status: {obra['status']}")
        print(f"   • Total de Tarefas: {total_tarefas}")
        print()
        
        # Confirmação
        print("⚠️  ATENÇÃO: Isso excluirá a obra E TODAS as suas tarefas!")
        confirma = input("Tem certeza que deseja EXCLUIR? (sim/não): ").strip().lower()
        
        if confirma not in ['sim', 's', 'yes', 'y']:
            print("\n❌ Exclusão cancelada.")
            conn.close()
            return
        
        # Exclui tarefas primeiro
        cursor.execute('DELETE FROM obra_checklist WHERE obra_id = ?', (obra_id,))
        print(f"   ✓ {total_tarefas} tarefa(s) excluída(s)")
        
        # Exclui a obra
        cursor.execute('DELETE FROM obras WHERE id = ?', (obra_id,))
        print(f"   ✓ Obra excluída")
        
        conn.commit()
        
        print()
        print(f"✅ Obra {obra_id} e suas tarefas excluídas com sucesso!")
        print()
        
    except Exception as e:
        print(f"❌ Erro ao excluir obra: {e}")
        conn.rollback()
    finally:
        conn.close()


def excluir_obras_teste():
    """Exclui todas as obras de teste (começam com 'TESTE')"""
    print()
    print("=" * 70)
    print("🗑️  EXCLUIR TODAS AS OBRAS DE TESTE")
    print("=" * 70)
    print()
    print(f"📂 Banco de dados: {CAMINHO_DB}")
    print()
    
    # Conecta ao banco
    db = Database()
    conn = db.get_connection()
    cursor = conn.cursor()
    
    try:
        # Busca obras de teste
        cursor.execute('''
            SELECT id, nome_contrato, cliente 
            FROM obras 
            WHERE nome_contrato LIKE 'TESTE%'
            ORDER BY id
        ''')
        
        obras_teste = cursor.fetchall()
        
        if not obras_teste:
            print("ℹ️  Nenhuma obra de teste encontrada.")
            conn.close()
            return
        
        print(f"📋 Encontradas {len(obras_teste)} obra(s) de teste:")
        print()
        
        total_tarefas = 0
        for obra in obras_teste:
            cursor.execute('SELECT COUNT(*) as total FROM obra_checklist WHERE obra_id = ?', (obra['id'],))
            num_tarefas = cursor.fetchone()['total']
            total_tarefas += num_tarefas
            print(f"   • ID {obra['id']:3d}: {obra['nome_contrato']:40s} ({num_tarefas} tarefas)")
        
        print()
        print(f"📊 Total: {len(obras_teste)} obra(s) e {total_tarefas} tarefa(s)")
        print()
        
        # Confirmação
        confirma = input("⚠️  Excluir TODAS estas obras de teste? (sim/não): ").strip().lower()
        
        if confirma not in ['sim', 's', 'yes', 'y']:
            print("\n❌ Exclusão cancelada.")
            conn.close()
            return
        
        # Exclui todas as obras e tarefas
        obras_ids = [obra['id'] for obra in obras_teste]
        placeholders = ','.join('?' * len(obras_ids))
        
        # Exclui tarefas
        cursor.execute(f'DELETE FROM obra_checklist WHERE obra_id IN ({placeholders})', obras_ids)
        print(f"   ✓ {total_tarefas} tarefa(s) excluída(s)")
        
        # Exclui obras
        cursor.execute(f'DELETE FROM obras WHERE id IN ({placeholders})', obras_ids)
        print(f"   ✓ {len(obras_teste)} obra(s) excluída(s)")
        
        conn.commit()
        
        print()
        print("✅ Todas as obras de teste foram excluídas com sucesso!")
        print()
        
    except Exception as e:
        print(f"❌ Erro ao excluir obras de teste: {e}")
        conn.rollback()
    finally:
        conn.close()


def menu_principal():
    """Menu principal de exclusão"""
    print()
    print("=" * 70)
    print("🗑️  EXCLUIR TAREFAS E OBRAS DE TESTE")
    print("=" * 70)
    print()
    print("  1. Excluir tarefa por ID")
    print("  2. Excluir obra por ID (e todas suas tarefas)")
    print("  3. Excluir todas as obras de teste (nome começa com 'TESTE')")
    print("  0. Sair")
    print()
    
    try:
        opcao = input("Escolha uma opção: ").strip()
        
        if opcao == '1':
            excluir_tarefa_por_id()
        elif opcao == '2':
            excluir_obra_por_id()
        elif opcao == '3':
            excluir_obras_teste()
        elif opcao == '0':
            print("\n👋 Saindo...")
            return
        else:
            print("\n❌ Opção inválida!")
            
    except KeyboardInterrupt:
        print("\n\n❌ Operação cancelada.")


if __name__ == "__main__":
    menu_principal()
