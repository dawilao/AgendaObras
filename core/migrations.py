"""
Sistema de Migrações de Banco de Dados - AgendaObras
"""

import sqlite3
from typing import Callable, List
from core.error_logger import log_error


class Migration:
    def __init__(self, version: int, description: str, upgrade: Callable, downgrade: Callable = None):
        self.version = version
        self.description = description
        self.upgrade = upgrade
        self.downgrade = downgrade

    def apply(self, conn: sqlite3.Connection):
        print(f"  Aplicando migração {self.version}: {self.description}")
        self.upgrade(conn)
        self._mark_as_applied(conn)

    def _mark_as_applied(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO schema_migrations (version, description, applied_at)
            VALUES (?, ?, datetime('now'))
        ''', (self.version, self.description))
        conn.commit()


class MigrationManager:
    def __init__(self, db_name: str = "agendaobras.db"):
        self.db_name = db_name
        self.migrations: List[Migration] = []
        self._init_migrations_table()
        self._register_migrations()

    def _init_migrations_table(self):
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
        self.migrations.append(Migration(version=1, description="Adicionar tipo_recorrencia para lógica customizada de CONFIRMAÇÃO", upgrade=self._migration_001_add_tipo_recorrencia))
        self.migrations.append(Migration(version=2, description="Corrigir base_calculo de tarefas de CONTRATAÇÃO e ACESSO", upgrade=self._migration_002_fix_base_calculo))
        self.migrations.append(Migration(version=3, description="Criar tarefas mensais MEDIÇÃO e CONFIRMAÇÃO para obras existentes", upgrade=self._migration_003_create_monthly_templates))
        self.migrations.append(Migration(version=4, description="Ajustar base_calculo 'criacao' e dependências corretas", upgrade=self._migration_004_fix_bases_and_dependencies))
        self.migrations.append(Migration(version=5, description="Criar tabela verificacoes_prazos para controle de execuções diárias", upgrade=self._migration_005_create_verificacoes_prazos_table))
        self.migrations.append(Migration(version=6, description="Permitir NULL na coluna data_inicio da tabela obras", upgrade=self._migration_006_allow_null_data_inicio))
        self.migrations.append(Migration(version=7, description="Converter datas do formato brasileiro para ISO nas tabelas obras e obra_checklist", upgrade=self._migration_007_fix_date_formats))
        self.migrations.append(Migration(version=8, description="Adicionar coluna pedido_sap à tabela obras", upgrade=self._migration_008_add_pedido_sap))
        self.migrations.append(Migration(version=9, description="Adicionar coluna data_acionamento à tabela obras", upgrade=self._migration_009_add_data_acionamento))
        self.migrations.append(Migration(version=10, description="Adicionar colunas observacoes, obs_usuario e obs_data na tabela obras", upgrade=self._migration_010_add_observacoes))
        self.migrations.append(Migration(version=11, description="Adicionar tabela medicoes_obra e coluna status_conclusao_obra em obras", upgrade=self._migration_011_medicoes_e_status))

    def _migration_001_add_tipo_recorrencia(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(checklist_templates)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'tipo_recorrencia' not in columns:
            cursor.execute("ALTER TABLE checklist_templates ADD COLUMN tipo_recorrencia TEXT DEFAULT 'padrao'")
            print("    ✅ Coluna tipo_recorrencia adicionada")
            cursor.execute("UPDATE checklist_templates SET tipo_recorrencia = 'confirmacao' WHERE nome = 'CONFIRMAÇÃO DE MEDIÇÃO'")
            print("    ✅ CONFIRMAÇÃO DE MEDIÇÃO configurada com lógica customizada")
        else:
            print("    ⏭️  Coluna tipo_recorrencia já existe, pulando...")
        conn.commit()

    def _migration_002_fix_base_calculo(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        for tarefa_nome in ['CONTRATAÇÃO DA EQUIPE', 'SOLICITAÇÃO DE ACESSO', 'RETORNO PROJETO E ORÇAMENTO']:
            cursor.execute("UPDATE obra_checklist SET base_calculo = 'inicio' WHERE descricao = ? AND base_calculo != 'inicio'", (tarefa_nome,))
            if cursor.rowcount > 0:
                print(f"    ✅ Corrigidas {cursor.rowcount} instância(s) de '{tarefa_nome}'")
        cursor.execute("UPDATE checklist_templates SET base_calculo = 'inicio' WHERE nome IN ('CONTRATAÇÃO DA EQUIPE', 'SOLICITAÇÃO DE ACESSO', 'RETORNO PROJETO E ORÇAMENTO') AND base_calculo != 'inicio'")
        conn.commit()
        print("    ✅ Templates corrigidos")

    def _migration_003_create_monthly_templates(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        import datetime
        cursor.execute('SELECT id, data_inicio FROM obras')
        obras = cursor.fetchall()
        cursor.execute('SELECT * FROM checklist_templates WHERE recorrencia = "mensal"')
        templates_mensais = cursor.fetchall()
        if not templates_mensais:
            print("    ⚠️ Nenhum template mensal encontrado")
            return
        hoje = datetime.date.today()
        tarefas_criadas = 0
        for obra in obras:
            obra_id, data_inicio = obra[0], obra[1]
            obra_ja_comecou = False
            if data_inicio:
                try:
                    data_inicio_obj = datetime.datetime.strptime(data_inicio, '%Y-%m-%d').date()
                    obra_ja_comecou = data_inicio_obj <= hoje
                except Exception as e:
                    log_error(e, "migrations", f"Parse de data_inicio na migração 3 - obra_id: {obra_id}")
            for template in templates_mensais:
                template_id, nome, _, prazo_dias, tipo, base_calculo = template[0], template[1], None, template[3], template[4], template[5]
                cursor.execute("SELECT COUNT(*) as count FROM obra_checklist WHERE obra_id = ? AND template_id = ? AND recorrencia = 'mensal'", (obra_id, template_id))
                if cursor.fetchone()[0] == 0:
                    bloqueado = 0 if obra_ja_comecou else 1
                    cursor.execute("INSERT INTO obra_checklist (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, base_calculo, data_base_calculo, bloqueado, status_notificacao, recorrencia) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (obra_id, template_id, nome, prazo_dias, None, tipo, base_calculo, data_inicio, bloqueado, 'pendente', 'mensal'))
                    tarefas_criadas += 1
        conn.commit()
        print(f"    ✅ {tarefas_criadas} tarefa(s) mensal(is) criada(s)")

    def _migration_004_fix_bases_and_dependencies(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute("UPDATE checklist_templates SET base_calculo = 'criacao' WHERE nome = 'RETORNO PROJETO E ORÇAMENTO'")
        print("    ✅ Template 'RETORNO PROJETO E ORÇAMENTO' atualizado para base_calculo='criacao'")
        cursor.execute("UPDATE checklist_templates SET prazo_dias = 2, depende_template_id = 2 WHERE nome = 'ANÁLISE - GESTOR'")
        print("    ✅ Template 'ANÁLISE - GESTOR' atualizado: prazo=2 dias, depende de ANÁLISE")
        cursor.execute("UPDATE obra_checklist SET base_calculo = 'criacao' WHERE descricao = 'RETORNO PROJETO E ORÇAMENTO'")
        if cursor.rowcount > 0:
            print(f"    ✅ {cursor.rowcount} tarefa(s) 'RETORNO PROJETO E ORÇAMENTO' atualizadas em obras existentes")
        cursor.execute("SELECT oc1.id as analise_gestor_id, oc2.id as analise_id, oc1.obra_id FROM obra_checklist oc1 JOIN obra_checklist oc2 ON oc1.obra_id = oc2.obra_id WHERE oc1.descricao = 'ANÁLISE - GESTOR' AND oc2.descricao = 'ANÁLISE'")
        dependencias = cursor.fetchall()
        for row in dependencias:
            analise_gestor_id, analise_id = row[0], row[1]
            cursor.execute("UPDATE obra_checklist SET depende_item_id = ?, prazo_dias = 2 WHERE id = ?", (analise_id, analise_gestor_id))
            cursor.execute('SELECT concluido, data_conclusao FROM obra_checklist WHERE id = ?', (analise_id,))
            analise = cursor.fetchone()
            if analise and analise[0]:
                import datetime
                data_obj = datetime.datetime.strptime(analise[1], '%Y-%m-%d')
                nova_data = data_obj + datetime.timedelta(days=2)
                cursor.execute("UPDATE obra_checklist SET data_limite = ?, data_base_calculo = ?, bloqueado = 0 WHERE id = ?", (nova_data.strftime('%Y-%m-%d'), analise[1], analise_gestor_id))
        if dependencias:
            print(f"    ✅ {len(dependencias)} dependência(s) de 'ANÁLISE - GESTOR' corrigidas")
        conn.commit()

    def _migration_005_create_verificacoes_prazos_table(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='verificacoes_prazos'")
        if cursor.fetchone():
            print("    ⏭️  Tabela verificacoes_prazos já existe, pulando...")
        else:
            cursor.execute('''CREATE TABLE verificacoes_prazos (id INTEGER PRIMARY KEY AUTOINCREMENT, data_verificacao TEXT NOT NULL UNIQUE, data_hora_inicio TEXT NOT NULL, data_hora_fim TEXT, tarefas_verificadas INTEGER DEFAULT 0, alertas_enviados INTEGER DEFAULT 0, status TEXT DEFAULT 'concluida', mensagem_erro TEXT)''')
            print("    ✅ Tabela verificacoes_prazos criada com sucesso")
            cursor.execute('CREATE INDEX idx_verificacoes_data ON verificacoes_prazos(data_verificacao)')
            print("    ✅ Índice idx_verificacoes_data criado")
        conn.commit()

    def _migration_006_allow_null_data_inicio(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        print("    🔄 Modificando estrutura da tabela obras...")
        cursor.execute("PRAGMA table_info(obras)")
        data_inicio_info = [col for col in cursor.fetchall() if col[1] == 'data_inicio']
        if data_inicio_info and data_inicio_info[0][3] == 0:
            print("    ⏭️  Coluna data_inicio já permite NULL, pulando...")
            return
        cursor.execute('''CREATE TABLE obras_new (id INTEGER PRIMARY KEY AUTOINCREMENT, nome_contrato TEXT NOT NULL, cliente TEXT NOT NULL, valor_contrato REAL NOT NULL, data_inicio TEXT, status TEXT DEFAULT 'Não Iniciada', data_criacao TEXT DEFAULT CURRENT_TIMESTAMP, contrato_ic TEXT, prefixo_agencia TEXT, servico TEXT, valor_parceiro REAL, valor_percentual REAL, total_obra REAL, mes_execucao TEXT, ano_execucao INTEGER, data_conclusao TEXT, data_assinatura TEXT, data_aio TEXT)''')
        print("    ✅ Tabela obras_new criada")
        cursor.execute('''INSERT INTO obras_new (id, nome_contrato, cliente, valor_contrato, data_inicio, status, data_criacao, contrato_ic, prefixo_agencia, servico, valor_parceiro, valor_percentual, total_obra, mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio) SELECT id, nome_contrato, cliente, valor_contrato, data_inicio, status, data_criacao, contrato_ic, prefixo_agencia, servico, valor_parceiro, valor_percentual, total_obra, mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio FROM obras''')
        print(f"    ✅ {cursor.rowcount} registro(s) copiado(s)")
        cursor.execute('DROP TABLE obras')
        print("    ✅ Tabela antiga removida")
        cursor.execute('ALTER TABLE obras_new RENAME TO obras')
        print("    ✅ Tabela renomeada para 'obras'")
        conn.commit()
        print("    ✅ Migração concluída: data_inicio agora permite NULL")

    def _migration_007_fix_date_formats(self, conn: sqlite3.Connection):
        import datetime as dt
        cursor = conn.cursor()
        print("    🔄 Verificando e corrigindo formatos de datas...")

        def converter_data(data_str):
            if not data_str or not isinstance(data_str, str):
                return data_str
            if '/' in data_str:
                try:
                    return dt.datetime.strptime(data_str, '%d/%m/%Y').strftime('%Y-%m-%d')
                except ValueError:
                    return data_str
            if '-' in data_str:
                try:
                    dt.datetime.strptime(data_str, '%Y-%m-%d')
                    return data_str
                except ValueError:
                    return data_str
            return data_str

        cursor.execute('SELECT id, data_inicio, data_assinatura, data_aio, data_conclusao FROM obras')
        obras_corrigidas = 0
        for obra in cursor.fetchall():
            di, da, daio, dc = converter_data(obra[1]), converter_data(obra[2]), converter_data(obra[3]), converter_data(obra[4])
            if (di, da, daio, dc) != (obra[1], obra[2], obra[3], obra[4]):
                cursor.execute("UPDATE obras SET data_inicio = ?, data_assinatura = ?, data_aio = ?, data_conclusao = ? WHERE id = ?", (di, da, daio, dc, obra[0]))
                obras_corrigidas += 1
        if obras_corrigidas > 0:
            print(f"    ✅ {obras_corrigidas} obra(s) com datas corrigidas")
        else:
            print("    ⏭️  Nenhuma data precisou ser corrigida na tabela obras")

        cursor.execute('SELECT id, data_limite, data_base_calculo, data_conclusao FROM obra_checklist')
        tarefas_corrigidas = 0
        for tarefa in cursor.fetchall():
            dl, dbc, dc = converter_data(tarefa[1]), converter_data(tarefa[2]), converter_data(tarefa[3])
            if (dl, dbc, dc) != (tarefa[1], tarefa[2], tarefa[3]):
                cursor.execute("UPDATE obra_checklist SET data_limite = ?, data_base_calculo = ?, data_conclusao = ? WHERE id = ?", (dl, dbc, dc, tarefa[0]))
                tarefas_corrigidas += 1
        if tarefas_corrigidas > 0:
            print(f"    ✅ {tarefas_corrigidas} tarefa(s) com datas corrigidas")
        else:
            print("    ⏭️  Nenhuma data precisou ser corrigida na tabela obra_checklist")
        conn.commit()
        print("    ✅ Migração concluída: todas as datas estão no formato ISO")

    def _migration_008_add_pedido_sap(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(obras)")
        if 'pedido_sap' not in [row[1] for row in cursor.fetchall()]:
            cursor.execute("ALTER TABLE obras ADD COLUMN pedido_sap TEXT")
            print("    ✅ Coluna pedido_sap adicionada à tabela obras")
        else:
            print("    ⏭️  Coluna pedido_sap já existe, pulando...")
        conn.commit()

    def _migration_009_add_data_acionamento(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(obras)")
        if 'data_acionamento' not in [row[1] for row in cursor.fetchall()]:
            cursor.execute("ALTER TABLE obras ADD COLUMN data_acionamento TEXT")
            print("    ✅ Coluna data_acionamento adicionada à tabela obras")
            cursor.execute("UPDATE obras SET data_acionamento = SUBSTR(data_criacao, 1, 10) WHERE data_acionamento IS NULL AND data_criacao IS NOT NULL")
            if cursor.rowcount > 0:
                print(f"    ✅ {cursor.rowcount} obra(s) existente(s) preenchida(s) com data_criacao como fallback")
        else:
            print("    ⏭️  Coluna data_acionamento já existe, pulando...")
        conn.commit()

    def _migration_010_add_observacoes(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(obras)")
        columns = [row[1] for row in cursor.fetchall()]
        for nome_coluna, tipo_coluna in [('observacoes', 'TEXT'), ('obs_usuario', 'TEXT'), ('obs_data', 'TEXT')]:
            if nome_coluna not in columns:
                cursor.execute(f'ALTER TABLE obras ADD COLUMN {nome_coluna} {tipo_coluna}')
                print(f"    ✅ Coluna {nome_coluna} adicionada à tabela obras")
            else:
                print(f"    ⏭️  Coluna {nome_coluna} já existe, pulando...")
        conn.commit()

    def _migration_011_medicoes_e_status(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='medicoes_obra'")
        if cursor.fetchone():
            print("    ⏭️  Tabela medicoes_obra já existe, pulando...")
        else:
            cursor.execute('''CREATE TABLE medicoes_obra (id INTEGER PRIMARY KEY AUTOINCREMENT, obra_id INTEGER NOT NULL, quantidade INTEGER DEFAULT 0, criado_em TEXT DEFAULT (datetime('now')), data_ultima_alteracao TEXT, atualizado_em TEXT)''')
            cursor.execute('CREATE INDEX idx_medicoes_obra_obra_id ON medicoes_obra(obra_id)')
            print("    ✅ Tabela medicoes_obra criada")
        cursor.execute('PRAGMA table_info(obras)')
        if 'status_conclusao_obra' not in [row[1] for row in cursor.fetchall()]:
            cursor.execute("ALTER TABLE obras ADD COLUMN status_conclusao_obra TEXT DEFAULT ''")
            print("    ✅ Coluna status_conclusao_obra adicionada à tabela obras")
        else:
            print("    ⏭️  Coluna status_conclusao_obra já existe, pulando...")
        conn.commit()

    def _get_applied_versions(self) -> List[int]:
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('SELECT version FROM schema_migrations ORDER BY version')
        versions = [row[0] for row in cursor.fetchall()]
        conn.close()
        return versions

    def run_migrations(self):
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
            log_error(e, "migrations", "Aplicar migrações pendentes")
            print(f"\n❌ Erro ao aplicar migrações: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()

    def show_status(self):
        applied = self._get_applied_versions()
        print("\n📋 Status das Migrações:")
        print("=" * 60)
        for migration in self.migrations:
            status = "✅ Aplicada" if migration.version in applied else "⏳ Pendente"
            print(f"  [{status}] v{migration.version}: {migration.description}")
        print("=" * 60)
        print(f"Total: {len(applied)}/{len(self.migrations)} aplicadas\n")


def run_migrations(db_name: str = "agendaobras.db"):
    MigrationManager(db_name).run_migrations()


def show_migration_status(db_name: str = "agendaobras.db"):
    MigrationManager(db_name).show_status()


if __name__ == "__main__":
    print("🚀 Iniciando sistema de migrações AgendaObras\n")
    run_migrations()
    show_migration_status()
