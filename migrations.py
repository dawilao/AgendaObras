"""
Sistema de Migrações de Banco de Dados - AgendaObras
Gerencia alterações incrementais na estrutura do banco de dados
"""

import sqlite3
from typing import Callable, List, Tuple


class Migration:
    """Representa uma migração individual"""
    
    def __init__(self, version: int, description: str, upgrade: Callable, downgrade: Callable = None):
        self.version = version
        self.description = description
        self.upgrade = upgrade
        self.downgrade = downgrade
    
    def apply(self, conn: sqlite3.Connection):
        """Aplica a migração"""
        print(f"  Aplicando migração {self.version}: {self.description}")
        self.upgrade(conn)
        self._mark_as_applied(conn)
    
    def _mark_as_applied(self, conn: sqlite3.Connection):
        """Marca migração como aplicada"""
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO schema_migrations (version, description, applied_at)
            VALUES (?, ?, datetime('now'))
        ''', (self.version, self.description))
        conn.commit()


class MigrationManager:
    """Gerenciador de migrações"""
    
    def __init__(self, db_name: str = "agendaobras.db"):
        self.db_name = db_name
        self.migrations: List[Migration] = []
        self._init_migrations_table()
        self._register_migrations()
    
    def _init_migrations_table(self):
        """Cria tabela de controle de migrações se não existir"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _register_migrations(self):
        """Registra todas as migrações disponíveis"""
        
        # Migração 1: Adicionar coluna tipo_recorrencia
        self.migrations.append(Migration(
            version=1,
            description="Adicionar tipo_recorrencia para lógica customizada de CONFIRMAÇÃO",
            upgrade=self._migration_001_add_tipo_recorrencia,
            downgrade=None
        ))
        
        # Migração 2: Corrigir base_calculo de tarefas com prazos negativos
        self.migrations.append(Migration(
            version=2,
            description="Corrigir base_calculo de tarefas de CONTRATAÇÃO e ACESSO",
            upgrade=self._migration_002_fix_base_calculo,
            downgrade=None
        ))
        
        # Migração 3: Criar tarefas mensais template para obras existentes
        self.migrations.append(Migration(
            version=3,
            description="Criar tarefas mensais MEDIÇÃO e CONFIRMAÇÃO para obras existentes",
            upgrade=self._migration_003_create_monthly_templates,
            downgrade=None
        ))
        
        # Migração 4: Corrigir base_calculo de RETORNO PROJETO e dependências de ANÁLISE - GESTOR
        self.migrations.append(Migration(
            version=4,
            description="Ajustar base_calculo 'criacao' e dependências corretas",
            upgrade=self._migration_004_fix_bases_and_dependencies,
            downgrade=None
        ))
        
        # Migração 5: Criar tabela de controle de verificações de prazos
        self.migrations.append(Migration(
            version=5,
            description="Criar tabela verificacoes_prazos para controle de execuções diárias",
            upgrade=self._migration_005_create_verificacoes_prazos_table,
            downgrade=None
        ))
    
    def _migration_001_add_tipo_recorrencia(self, conn: sqlite3.Connection):
        """Adiciona coluna tipo_recorrencia à tabela checklist_templates"""
        cursor = conn.cursor()
        
        # Verifica se coluna já existe
        cursor.execute("PRAGMA table_info(checklist_templates)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'tipo_recorrencia' not in columns:
            # Adiciona coluna
            cursor.execute('''
                ALTER TABLE checklist_templates 
                ADD COLUMN tipo_recorrencia TEXT DEFAULT 'padrao'
            ''')
            print("    ✅ Coluna tipo_recorrencia adicionada")
            
            # Atualiza tarefa CONFIRMAÇÃO DE MEDIÇÃO
            cursor.execute('''
                UPDATE checklist_templates 
                SET tipo_recorrencia = 'confirmacao'
                WHERE nome = 'CONFIRMAÇÃO DE MEDIÇÃO'
            ''')
            print("    ✅ CONFIRMAÇÃO DE MEDIÇÃO configurada com lógica customizada")
        else:
            print("    ⏭️  Coluna tipo_recorrencia já existe, pulando...")
        
        conn.commit()
    
    def _migration_002_fix_base_calculo(self, conn: sqlite3.Connection):
        """Corrige base_calculo de tarefas que dependem da data de início"""
        cursor = conn.cursor()
        
        # Atualiza tarefas CONTRATAÇÃO DA EQUIPE e SOLICITAÇÃO DE ACESSO
        # para garantir que tenham base_calculo='inicio'
        tarefas_para_corrigir = [
            'CONTRATAÇÃO DA EQUIPE',
            'SOLICITAÇÃO DE ACESSO',
            'RETORNO PROJETO E ORÇAMENTO'
        ]
        
        for tarefa_nome in tarefas_para_corrigir:
            cursor.execute('''
                UPDATE obra_checklist 
                SET base_calculo = 'inicio'
                WHERE descricao = ? AND base_calculo != 'inicio'
            ''', (tarefa_nome,))
            
            rows_updated = cursor.rowcount
            if rows_updated > 0:
                print(f"    ✅ Corrigidas {rows_updated} instância(s) de '{tarefa_nome}'")
        
        # Também atualiza os templates se necessário
        cursor.execute('''
            UPDATE checklist_templates 
            SET base_calculo = 'inicio'
            WHERE nome IN ('CONTRATAÇÃO DA EQUIPE', 'SOLICITAÇÃO DE ACESSO', 'RETORNO PROJETO E ORÇAMENTO')
            AND base_calculo != 'inicio'
        ''')
        
        conn.commit()
        print("    ✅ Templates corrigidos")
    
    def _migration_003_create_monthly_templates(self, conn: sqlite3.Connection):
        """Cria tarefas mensais template para obras que não as têm"""
        cursor = conn.cursor()
        import datetime
        
        # Busca todas as obras
        cursor.execute('SELECT id, data_inicio FROM obras')
        obras = cursor.fetchall()
        
        # Busca templates de tarefas mensais
        cursor.execute('SELECT * FROM checklist_templates WHERE recorrencia = "mensal"')
        templates_mensais = cursor.fetchall()
        
        if not templates_mensais:
            print("    ⚠️ Nenhum template mensal encontrado")
            return
        
        hoje = datetime.date.today()
        tarefas_criadas = 0
        
        for obra in obras:
            obra_id = obra[0]
            data_inicio = obra[1]
            
            # Verifica se a obra já começou
            obra_ja_comecou = False
            if data_inicio:
                try:
                    data_inicio_obj = datetime.datetime.strptime(data_inicio, '%Y-%m-%d').date()
                    obra_ja_comecou = data_inicio_obj <= hoje
                except:
                    pass
            
            for template in templates_mensais:
                template_id = template[0]
                nome = template[1]
                prazo_dias = template[3]
                tipo = template[4]
                base_calculo = template[5]
                
                # Verifica se já existe tarefa mensal para esse template nessa obra
                cursor.execute('''
                    SELECT COUNT(*) as count FROM obra_checklist 
                    WHERE obra_id = ? AND template_id = ? AND recorrencia = 'mensal'
                ''', (obra_id, template_id))
                
                if cursor.fetchone()[0] == 0:
                    # Não existe, cria
                    bloqueado = 0 if obra_ja_comecou else 1
                    
                    cursor.execute('''
                        INSERT INTO obra_checklist 
                        (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, 
                         base_calculo, data_base_calculo, bloqueado, status_notificacao, recorrencia)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (obra_id, template_id, nome, prazo_dias,
                          None, tipo, base_calculo, data_inicio, bloqueado, 
                          'pendente', 'mensal'))
                    
                    tarefas_criadas += 1
        
        conn.commit()
        print(f"    ✅ {tarefas_criadas} tarefa(s) mensal(is) criada(s)")
    
    def _migration_004_fix_bases_and_dependencies(self, conn: sqlite3.Connection):
        """Corrige base_calculo 'criacao' e dependências de ANÁLISE - GESTOR"""
        cursor = conn.cursor()
        
        # 1. Atualiza template de RETORNO PROJETO E ORÇAMENTO para base_calculo 'criacao'
        cursor.execute('''
            UPDATE checklist_templates 
            SET base_calculo = 'criacao'
            WHERE nome = 'RETORNO PROJETO E ORÇAMENTO'
        ''')
        print("    ✅ Template 'RETORNO PROJETO E ORÇAMENTO' atualizado para base_calculo='criacao'")
        
        # 2. Atualiza template de ANÁLISE - GESTOR: prazo 2 dias e depende de ANÁLISE (id 2)
        cursor.execute('''
            UPDATE checklist_templates 
            SET prazo_dias = 2, depende_template_id = 2
            WHERE nome = 'ANÁLISE - GESTOR'
        ''')
        print("    ✅ Template 'ANÁLISE - GESTOR' atualizado: prazo=2 dias, depende de ANÁLISE")
        
        # 3. Para obras existentes, atualiza tarefas de RETORNO PROJETO E ORÇAMENTO
        cursor.execute('''
            UPDATE obra_checklist 
            SET base_calculo = 'criacao'
            WHERE descricao = 'RETORNO PROJETO E ORÇAMENTO'
        ''')
        rows_updated = cursor.rowcount
        if rows_updated > 0:
            print(f"    ✅ {rows_updated} tarefa(s) 'RETORNO PROJETO E ORÇAMENTO' atualizadas em obras existentes")
        
        # 4. Atualiza dependências de ANÁLISE - GESTOR em obras existentes
        # Busca o id de ANÁLISE para cada obra e atualiza ANÁLISE - GESTOR para depender dela
        cursor.execute('''
            SELECT oc1.id as analise_gestor_id, oc2.id as analise_id, oc1.obra_id
            FROM obra_checklist oc1
            JOIN obra_checklist oc2 ON oc1.obra_id = oc2.obra_id
            WHERE oc1.descricao = 'ANÁLISE - GESTOR' 
            AND oc2.descricao = 'ANÁLISE'
        ''')
        
        dependencias_para_atualizar = cursor.fetchall()
        for row in dependencias_para_atualizar:
            analise_gestor_id = row[0]
            analise_id = row[1]
            obra_id = row[2]
            
            # Atualiza dependência e prazo
            cursor.execute('''
                UPDATE obra_checklist 
                SET depende_item_id = ?, prazo_dias = 2
                WHERE id = ?
            ''', (analise_id, analise_gestor_id))
            
            # Se ANÁLISE estiver concluída, recalcula data_limite de ANÁLISE - GESTOR
            cursor.execute('SELECT concluido, data_conclusao FROM obra_checklist WHERE id = ?', (analise_id,))
            analise = cursor.fetchone()
            
            if analise and analise[0]:  # Se ANÁLISE concluída
                data_conclusao = analise[1]
                import datetime
                data_obj = datetime.datetime.strptime(data_conclusao, '%Y-%m-%d')
                nova_data_limite = data_obj + datetime.timedelta(days=2)
                
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET data_limite = ?, data_base_calculo = ?, bloqueado = 0
                    WHERE id = ?
                ''', (nova_data_limite.strftime('%Y-%m-%d'), data_conclusao, analise_gestor_id))
        
        if dependencias_para_atualizar:
            print(f"    ✅ {len(dependencias_para_atualizar)} dependência(s) de 'ANÁLISE - GESTOR' corrigidas")
        
        conn.commit()
    
    def _migration_005_create_verificacoes_prazos_table(self, conn: sqlite3.Connection):
        """Cria tabela para controle de verificações de prazos"""
        cursor = conn.cursor()
        
        # Verifica se tabela já existe
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='verificacoes_prazos'
        """)
        
        if cursor.fetchone():
            print("    ⏭️  Tabela verificacoes_prazos já existe, pulando...")
        else:
            # Cria tabela
            cursor.execute('''
                CREATE TABLE verificacoes_prazos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_verificacao TEXT NOT NULL UNIQUE,
                    data_hora_inicio TEXT NOT NULL,
                    data_hora_fim TEXT,
                    tarefas_verificadas INTEGER DEFAULT 0,
                    alertas_enviados INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'concluida',
                    mensagem_erro TEXT
                )
            ''')
            print("    ✅ Tabela verificacoes_prazos criada com sucesso")
            
            # Índice para busca rápida por data
            cursor.execute('''
                CREATE INDEX idx_verificacoes_data 
                ON verificacoes_prazos(data_verificacao)
            ''')
            print("    ✅ Índice idx_verificacoes_data criado")
        
        conn.commit()
    
    def _get_applied_versions(self) -> List[int]:
        """Retorna lista de migrações já aplicadas"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('SELECT version FROM schema_migrations ORDER BY version')
        versions = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return versions
    
    def run_migrations(self):
        """Executa todas as migrações pendentes"""
        applied = self._get_applied_versions()
        pending = [m for m in self.migrations if m.version not in applied]
        
        if not pending:
            print("✅ Todas as migrações estão atualizadas!")
            return
        
        print(f"\n🔄 Executando {len(pending)} migração(ões) pendente(s)...\n")
        
        conn = sqlite3.connect(self.db_name)
        
        try:
            for migration in pending:
                migration.apply(conn)
            
            print(f"\n✅ {len(pending)} migração(ões) aplicada(s) com sucesso!\n")
        except Exception as e:
            print(f"\n❌ Erro ao aplicar migrações: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def show_status(self):
        """Exibe status das migrações"""
        applied = self._get_applied_versions()
        
        print("\n📋 Status das Migrações:")
        print("=" * 60)
        
        for migration in self.migrations:
            status = "✅ Aplicada" if migration.version in applied else "⏳ Pendente"
            print(f"  [{status}] v{migration.version}: {migration.description}")
        
        print("=" * 60)
        print(f"Total: {len(applied)}/{len(self.migrations)} aplicadas\n")


def run_migrations(db_name: str = "agendaobras.db"):
    """Função auxiliar para executar migrações"""
    manager = MigrationManager(db_name)
    manager.run_migrations()


def show_migration_status(db_name: str = "agendaobras.db"):
    """Função auxiliar para mostrar status"""
    manager = MigrationManager(db_name)
    manager.show_status()


if __name__ == "__main__":
    # Executa migrações quando executado diretamente
    print("🚀 Iniciando sistema de migrações AgendaObras\n")
    run_migrations()
    show_migration_status()
