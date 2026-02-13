"""
Script para forçar verificação e envio de e-mails com debug detalhado.
Permite ver exatamente o que acontece durante o processamento.
"""

import sys
import os

# Adiciona o diretório pai ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database, CAMINHO_DB
from email_service import EmailService
from gerador_tarefas_recorrentes import GeradorTarefasRecorrentes
from notificador_prazos import NotificadorPrazos
import datetime

def forcar_envio_debug():
    """Força envio de e-mails com debug completo"""
    
    print("=" * 70)
    print("🔬 VERIFICAÇÃO COM DEBUG DETALHADO")
    print("=" * 70)
    print()
    
    print(f"📂 Banco: {CAMINHO_DB}")
    print(f"📅 Hoje: {datetime.date.today().strftime('%d/%m/%Y')}")
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
    print("🔍 Verificando configuração de e-mail...")
    if email_service.config.is_configured():
        print(f"✅ E-mail configurado: {email_service.config.email_remetente}")
        print(f"   Servidor: {email_service.config.smtp_server}")
        print(f"   Porta: {email_service.config.smtp_port}")
    else:
        print("⚠️  E-mail NÃO configurado!")
        print("   Os e-mails não serão enviados, mas o processamento será simulado.")
    print()
    
    # Limpa verificação de hoje
    print("🧹 Limpando verificação de hoje...")
    conn = db.get_connection()
    cursor = conn.cursor()
    hoje = datetime.date.today().strftime('%Y-%m-%d')
    
    cursor.execute('DELETE FROM verificacoes_prazos WHERE data_verificacao = ?', (hoje,))
    linhas = cursor.rowcount
    print(f"   {linhas} registro(s) removido(s)")
    
    # Limpa última_notificacao de tarefas de teste
    cursor.execute('''
        UPDATE obra_checklist 
        SET ultima_notificacao = NULL
        WHERE obra_id IN (
            SELECT id FROM obras WHERE nome_contrato LIKE '%TESTE%REITERAÇÃO%'
        )
        AND date(ultima_notificacao) = ?
    ''', (hoje,))
    linhas = cursor.rowcount
    print(f"   {linhas} tarefa(s) com última_notificacao resetada")
    
    conn.commit()
    conn.close()
    print()
    
    # Busca tarefas que deveriam ser processadas
    print("🔍 Buscando tarefas de teste que deveriam receber e-mail...")
    conn = db.get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            oc.*,
            o.nome_contrato,
            o.cliente
        FROM obra_checklist oc
        JOIN obras o ON oc.obra_id = o.id
        WHERE o.nome_contrato LIKE '%TESTE%REITERAÇÃO%'
        AND oc.descricao = 'RETORNO PROJETO E ORÇAMENTO'
        AND oc.concluido = 0
        AND oc.bloqueado = 0
        AND oc.data_limite IS NOT NULL
        ORDER BY oc.id
    ''')
    
    tarefas = cursor.fetchall()
    conn.close()
    
    print(f"✅ Encontradas {len(tarefas)} tarefa(s)")
    for t in tarefas:
        print(f"   • Tarefa {t['id']}: {t['nome_contrato']} - {t['descricao']}")
    print()
    
    # Executa verificação FORÇADA
    print("=" * 70)
    print("🚀 EXECUTANDO VERIFICAÇÃO FORÇADA...")
    print("=" * 70)
    print()
    
    try:
        sucesso = notificador.verificar_agora(forcar=True)
        
        print()
        print("=" * 70)
        if sucesso:
            print("✅ VERIFICAÇÃO CONCLUÍDA!")
        else:
            print("⚠️  Verificação retornou False")
        print("=" * 70)
        print()
        
        # Verifica o que foi enviado
        print("📊 CONFERINDO RESULTADO...")
        print("-" * 70)
        
        conn = db.get_connection()
        cursor = conn.cursor()
        
        # Verifica histórico de hoje
        cursor.execute('''
            SELECT COUNT(*) as total
            FROM historico_notificacoes
            WHERE date(data_envio) = ?
            AND obra_id IN (
                SELECT id FROM obras WHERE nome_contrato LIKE '%TESTE%REITERAÇÃO%'
            )
        ''', (hoje,))
        
        total_enviados = cursor.fetchone()['total']
        
        print(f"📧 E-mails enviados hoje: {total_enviados}")
        
        if total_enviados > 0:
            cursor.execute('''
                SELECT 
                    hn.*,
                    o.nome_contrato,
                    oc.descricao
                FROM historico_notificacoes hn
                JOIN obras o ON hn.obra_id = o.id
                JOIN obra_checklist oc ON hn.tarefa_id = oc.id
                WHERE date(hn.data_envio) = ?
                AND o.nome_contrato LIKE '%TESTE%REITERAÇÃO%'
                ORDER BY hn.data_envio
            ''', (hoje,))
            
            envios = cursor.fetchall()
            
            for envio in envios:
                print(f"\n✅ Enviado:")
                print(f"   Obra: {envio['nome_contrato']}")
                print(f"   Tarefa: {envio['descricao']}")
                print(f"   Tipo: {envio['tipo_notificacao']}")
                print(f"   Para: {envio['destinatarios']}")
                print(f"   Sucesso: {'Sim' if envio['sucesso'] else 'Não'}")
                if envio['mensagem_erro']:
                    print(f"   ❌ Erro: {envio['mensagem_erro']}")
        else:
            print("\n⚠️  NENHUM E-MAIL FOI ENVIADO!")
            print("\nPossíveis causas:")
            print("1. Configuração de e-mail não está completa")
            print("2. Erro na conexão SMTP")
            print("3. Tarefas não atendem critérios de envio")
            print("4. Bug na lógica do notificador")
        
        # Verifica estado atualizado das tarefas
        print()
        print("-" * 70)
        print("📋 ESTADO FINAL DAS TAREFAS:")
        
        cursor.execute('''
            SELECT 
                oc.id,
                oc.descricao,
                oc.tentativas_reiteracao,
                oc.ultima_notificacao,
                o.nome_contrato
            FROM obra_checklist oc
            JOIN obras o ON oc.obra_id = o.id
            WHERE o.nome_contrato LIKE '%TESTE%REITERAÇÃO%'
            AND oc.descricao = 'RETORNO PROJETO E ORÇAMENTO'
            ORDER BY oc.id
        ''')
        
        tarefas_final = cursor.fetchall()
        
        for t in tarefas_final:
            print(f"\n📌 Tarefa {t['id']}: {t['nome_contrato']}")
            print(f"   Tentativas: {t['tentativas_reiteracao']}")
            print(f"   Última Notif: {t['ultima_notificacao'] or 'Nenhuma'}")
        
        conn.close()
        
    except Exception as e:
        print(f"\n❌ ERRO DURANTE VERIFICAÇÃO:")
        print(f"   {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    forcar_envio_debug()
