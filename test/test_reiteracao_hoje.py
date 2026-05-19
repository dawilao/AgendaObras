"""
Script de teste INTERATIVO para criar uma obra com tarefa configurada 
para receber alertas de prazo.

Propósito: Testar se os e-mails de alerta/reiteração são enviados corretamente.

Permite escolher:
- Qual tarefa testar
- Tipo de alerta: Reiteração 1, 2, 3 ou Crítico
"""

import sys
import os
import datetime

# Adiciona o diretório pai ao path para importar os módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import Database, CAMINHO_DB


def listar_tarefas_disponiveis():
    """Retorna lista de tarefas disponíveis para teste com suas ordens"""
    return [
        ('RETORNO PROJETO E ORÇAMENTO', 'A', 2, 1),  # ordem 1
        ('ANÁLISE', 'B', 3, 2),  # ordem 2
        ('ANÁLISE - GESTOR', 'B', 2, 3),  # ordem 3
        ('RETORNO DO QUESTIONAMENTO', 'A', 2, 4),  # ordem 4
        ('CONTRATO ASSINADO', 'B', 5, 5),  # ordem 5
        ('SOLICITAR A DATA DA AIO', 'A', 1, 6),  # ordem 6
        ('PEDIDO MATERIAL ABC', 'B', 8, 7),  # ordem 7
        ('ART', 'B', 5, 8),  # ordem 8
        ('SOLICITAÇÃO SEGUROS', 'B', 5, 9),  # ordem 9
        ('ACEITE SEGURO', 'B', 5, 10),  # ordem 10
        ('PAGAMENTO SEGURO', 'B', 5, 11),  # ordem 11
        ('ENVIO DO SEGURO + ART', 'B', 5, 12),  # ordem 12
        ('CRONOGRAMA DE OBRA', 'B', 0, 13),  # ordem 13
        ('RELATÓRIO', 'B', 5, 14),  # ordem 14
        ('CONTRATAÇÃO DA EQUIPE', 'B', 15, 15),  # ordem 15
        ('SOLICITAÇÃO DE ACESSO', 'B', 10, 16),  # ordem 16
        ('MEDIÇÃO', 'B', 0, 17),  # ordem 17
        ('CONFIRMAÇÃO DE MEDIÇÃO', 'A', 0, 18),  # ordem 18
    ]


def escolher_tarefa():
    """Permite ao usuário escolher qual tarefa testar"""
    tarefas = listar_tarefas_disponiveis()
    
    print("=" * 70)
    print("📋 TAREFAS DISPONÍVEIS PARA TESTE")
    print("=" * 70)
    print()
    
    for i, (nome, tipo, prazo, ordem) in enumerate(tarefas, 1):
        tipo_desc = "Tipo A (com reiterações)" if tipo == 'A' else "Tipo B (prazo fixo)"
        print(f"  {i:2d}. {nome:40s} | {tipo_desc}")
    
    print()
    while True:
        try:
            escolha = input("Digite o número da tarefa (1-18): ").strip()
            num = int(escolha)
            if 1 <= num <= len(tarefas):
                return tarefas[num - 1]
            print("❌ Número inválido! Escolha entre 1 e 18.")
        except ValueError:
            print("❌ Digite um número válido!")
        except KeyboardInterrupt:
            print("\n\n❌ Teste cancelado pelo usuário.")
            sys.exit(0)


def concluir_tarefas_anteriores(cursor, obra_id, ordem_tarefa):
    """Marca como concluídas todas as tarefas com ordem menor que a tarefa escolhida"""
    hoje = datetime.date.today().strftime('%Y-%m-%d')
    
    # Busca tarefas anteriores (ordem menor)
    cursor.execute('''
        SELECT oc.id, oc.descricao, ct.ordem
        FROM obra_checklist oc
        JOIN checklist_templates ct ON oc.template_id = ct.id
        WHERE oc.obra_id = ? AND ct.ordem < ?
        ORDER BY ct.ordem
    ''', (obra_id, ordem_tarefa))
    
    tarefas_anteriores = cursor.fetchall()
    
    if not tarefas_anteriores:
        return 0
    
    print()
    print(f"🔄 Marcando {len(tarefas_anteriores)} tarefa(s) anterior(es) como concluída(s)...")
    
    tarefas_concluidas = 0
    for tarefa in tarefas_anteriores:
        cursor.execute('''
            UPDATE obra_checklist
            SET concluido = 1,
                data_conclusao = ?,
                bloqueado = 0
            WHERE id = ?
        ''', (hoje, tarefa['id']))
        
        print(f"   ✓ {tarefa['descricao']}")
        tarefas_concluidas += 1
    
    return tarefas_concluidas


def escolher_tipo_alerta(tipo_tarefa):
    """Permite ao usuário escolher o tipo de alerta"""
    print()
    print("=" * 70)
    print("⚠️  TIPO DE ALERTA")
    print("=" * 70)
    print()
    
    if tipo_tarefa == 'A':
        print("  1. 1ª Reiteração (2 dias após vencimento)")
        print("  2. 2ª Reiteração (4 dias após vencimento)")
        print("  3. 3ª Reiteração (6 dias após vencimento)")
        print("  4. Crítico Diário (mais de 6 dias após vencimento)")
        opcoes = ['1', '2', '3', '4']
    else:
        print("  1. Último Dia (dia do vencimento)")
        print("  2. Crítico Diário (após vencimento)")
        opcoes = ['1', '2']
    
    print()
    while True:
        try:
            escolha = input(f"Digite o número do alerta ({'/'.join(opcoes)}): ").strip()
            if escolha in opcoes:
                return escolha
            print(f"❌ Opção inválida! Escolha entre {'/'.join(opcoes)}.")
        except KeyboardInterrupt:
            print("\n\n❌ Teste cancelado pelo usuário.")
            sys.exit(0)


def obter_mes_portugues(numero_mes):
    """Retorna o nome do mês em português"""
    meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
             'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
    return meses[numero_mes - 1]


def calcular_configuracao_teste(tipo_tarefa, tipo_alerta):
    """Calcula data_limite e tentativas baseado no tipo de alerta escolhido"""
    hoje = datetime.date.today()
    
    if tipo_tarefa == 'A':
        # Tipo A: Com reiterações
        if tipo_alerta == '1':
            # 1ª Reiteração: 2 dias após vencimento
            dias_atraso = 2
            tentativas = 0
            alerta_desc = "1ª Reiteração"
        elif tipo_alerta == '2':
            # 2ª Reiteração: 4 dias após vencimento
            dias_atraso = 4
            tentativas = 1
            alerta_desc = "2ª Reiteração"
        elif tipo_alerta == '3':
            # 3ª Reiteração: 6 dias após vencimento
            dias_atraso = 6
            tentativas = 2
            alerta_desc = "3ª Reiteração"
        else:  # tipo_alerta == '4'
            # Crítico: mais de 6 dias
            dias_atraso = 7
            tentativas = 3
            alerta_desc = "Crítico Diário"
    else:
        # Tipo B: Prazo fixo
        if tipo_alerta == '1':
            # Último dia
            dias_atraso = 0
            tentativas = 0
            alerta_desc = "Último Dia"
        else:  # tipo_alerta == '2'
            # Crítico após vencimento
            dias_atraso = 1
            tentativas = 0
            alerta_desc = "Crítico Atrasado"
    
    data_limite = (hoje - datetime.timedelta(days=dias_atraso)).strftime('%Y-%m-%d')
    
    return {
        'data_limite': data_limite,
        'tentativas': tentativas,
        'dias_atraso': dias_atraso,
        'alerta_desc': alerta_desc
    }


def criar_obra_teste_reiteracao():
    """Cria obra e tarefa configuradas para teste de alertas"""
    
    print()
    print("=" * 70)
    print("🧪 TESTE INTERATIVO DE ALERTAS DE PRAZO")
    print("=" * 70)
    print()
    
    # Usuário escolhe a tarefa
    nome_tarefa, tipo_tarefa, prazo_original, ordem_tarefa = escolher_tarefa()
    
    # Usuário escolhe o tipo de alerta
    tipo_alerta = escolher_tipo_alerta(tipo_tarefa)
    
    # Calcula configuração do teste
    config = calcular_configuracao_teste(tipo_tarefa, tipo_alerta)
    
    # Usa o mesmo caminho do banco que o AgendaObras usa
    print()
    print("=" * 70)
    print("⚙️  CONFIGURAÇÃO DO TESTE")
    print("=" * 70)
    print()
    print(f"📂 Banco de dados: {CAMINHO_DB}")
    print(f"📋 Tarefa: {nome_tarefa}")
    print(f"🏷️  Tipo: {tipo_tarefa} ({'Com reiterações' if tipo_tarefa == 'A' else 'Prazo fixo'})")
    print(f"⚠️  Alerta: {config['alerta_desc']}")
    print(f"📅 Data limite: {datetime.datetime.strptime(config['data_limite'], '%Y-%m-%d').strftime('%d/%m/%Y')}")
    print(f"📊 Tentativas: {config['tentativas']}")
    print(f"⏰ Dias em atraso: {config['dias_atraso']}")
    print()
    
    # Confirmação
    confirma = input("Continuar com esta configuração? (S/n): ").strip().lower()
    if confirma and confirma not in ['s', 'sim', 'y', 'yes']:
        print("\n❌ Teste cancelado.")
        return
    
    # Conecta ao banco de dados
    db = Database()
    hoje = datetime.date.today()

    conn = None
    try:
        # 1. Cria a obra de teste
        print()
        print("📝 Criando obra de teste com todas as tarefas...")
        print()
        
        obra_id = db.criar_obra(
            nome_contrato=f'TESTE - {config["alerta_desc"]}',
            cliente='Cliente Teste Ltda',
            valor_contrato=100000.00,
            data_inicio='',
            status='Em Andamento',
            contrato_ic='IC-TESTE',
            prefixo_agencia='AG999',
            servico=f'Teste: {nome_tarefa} - {config["alerta_desc"]}',
            mes_execucao=obter_mes_portugues(hoje.month),
            ano_execucao=hoje.year
        )
        
        print(f"✅ Obra criada com ID: {obra_id}")
        print(f"   • Todas as tarefas padrão foram criadas automaticamente")
        print()
        
        # 2. Marca tarefas anteriores como concluídas (para respeitar dependências)
        conn = db.get_connection()
        cursor = conn.cursor()
        
        if ordem_tarefa > 1:
            tarefas_concluidas = concluir_tarefas_anteriores(cursor, obra_id, ordem_tarefa)
            if tarefas_concluidas > 0:
                print()
        
        # 3. Modifica a tarefa escolhida para teste
        print(f"🔧 Configurando tarefa '{nome_tarefa}' para teste...")
        
        cursor.execute('''
            UPDATE obra_checklist 
            SET data_limite = ?,
                tentativas_reiteracao = ?,
                ultima_notificacao = NULL,
                status_notificacao = 'pendente',
                bloqueado = 0
            WHERE obra_id = ? 
            AND descricao = ?
        ''', (config['data_limite'], config['tentativas'], obra_id, nome_tarefa))
        
        if cursor.rowcount == 0:
            print(f"❌ Tarefa '{nome_tarefa}' não encontrada!")
            conn.close()
            return
        
        # Busca a tarefa modificada
        cursor.execute('''
            SELECT id, descricao, tipo, prazo_dias, data_limite, tentativas_reiteracao
            FROM obra_checklist 
            WHERE obra_id = ? AND descricao = ?
        ''', (obra_id, nome_tarefa))
        
        tarefa = cursor.fetchone()
        if not tarefa:
            print(f"❌ Erro ao buscar tarefa '{nome_tarefa}'!")
            conn.close()
            return
        
        tarefa_id = tarefa['id']
        
        # Conta total de tarefas criadas
        cursor.execute('''
            SELECT COUNT(*) as total FROM obra_checklist WHERE obra_id = ?
        ''', (obra_id,))
        total_tarefas = cursor.fetchone()['total']
        
        # Commit das mudanças
        conn.commit()
        
        print()
        print("✅ Tarefa configurada com sucesso!")
        print(f"   • ID: {tarefa_id}")
        print(f"   • Descrição: {tarefa['descricao']}")
        print(f"   • Tipo: {tarefa['tipo']} ({'Com reiterações' if tarefa['tipo'] == 'A' else 'Prazo fixo'})")
        print(f"   • Data Limite: {datetime.datetime.strptime(config['data_limite'], '%Y-%m-%d').strftime('%d/%m/%Y')}")
        print(f"   • Tentativas: {config['tentativas']}")
        print(f"   • Status: {'Vencida há ' + str(config['dias_atraso']) + ' dia(s)' if config['dias_atraso'] > 0 else 'Vence hoje'}")
        print()
        print(f"📊 Total de tarefas na obra: {total_tarefas}")
        print()
        
        # Exibe resumo
        print("=" * 70)
        print("✅ CONFIGURAÇÃO CONCLUÍDA!")
        print("=" * 70)
        print()
        print("📋 RESUMO DO TESTE:")
        print(f"   • Obra: {obra_id}")
        print(f"   • Tarefa: {nome_tarefa}")
        print(f"   • Alerta Esperado: {config['alerta_desc']}")
        print(f"   • Data: {hoje.strftime('%d/%m/%Y')}")
        print()
        print("🔔 PRÓXIMOS PASSOS:")
        print()
        print("   1. Execute: python test\\test_forcar_verificacao.py")
        print("      (Para limpar verificação de hoje e permitir novo teste)")
        print()
        print("   2. Execute: python test\\test_envio_email_manual.py")
        print("      OU inicie o AgendaObras: python AgendaObras.py")
        print()
        print("   3. O sistema deve detectar a tarefa e enviar o e-mail")
        print("   4. Verifique sua caixa de entrada")
        print()
        
        if tipo_tarefa == 'A':
            print("💡 LEMBRETES SOBRE TIPO A (Com Reiterações):")
            print("   • 1ª Reiteração: 2 dias após vencimento")
            print("   • 2ª Reiteração: 4 dias após vencimento")
            print("   • 3ª Reiteração: 6 dias após vencimento")
            print("   • Crítico: Diário após 6 dias")
            print()
        else:
            print("💡 LEMBRETES SOBRE TIPO B (Prazo Fixo):")
            print("   • Último Dia: Alerta no dia do vencimento")
            print("   • Crítico: Diário após vencimento")
            print()
        
    except Exception as e:
        print()
        print(f"❌ Erro ao criar teste: {e}")
        print()
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
    try:
        try:
            from test.test_forcar_verificacao import limpar_execucao_hoje
        except ImportError:
            from test_forcar_verificacao import limpar_execucao_hoje

        limpar_execucao_hoje(limpar_todas=True)
        criar_obra_teste_reiteracao()
    except KeyboardInterrupt:
        print("\n\n❌ Teste cancelado pelo usuário.")
        sys.exit(0)

        # rode python test\test_reiteracao_hoje.py