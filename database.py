"""
Módulo de gerenciamento do banco de dados SQLite para o sistema AgendaObras.
Contém a classe Database com todas as operações CRUD para obras e checklists.
"""

import sqlite3
import datetime
from typing import List, Dict, Optional
from migrations import run_migrations
from error_logger import log_error

CAMINHO_DB = r'G:\Meu Drive\17 - MODELOS\PROGRAMAS\AgendaObras\app\db\agendaobras.db'

class Database:
    def __init__(self, db_name: str = CAMINHO_DB):
        self.db_name = db_name
        self.init_database()
        # Executa migrações pendentes
        run_migrations(db_name)
    
    def get_connection(self):
        """Cria e retorna uma conexão com o banco de dados com timeout e WAL mode"""
        conn = sqlite3.connect(self.db_name, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # Permite acesso por nome de coluna
        # Habilita WAL mode para melhor concorrência
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')  # 30 segundos
        return conn
    
    def init_database(self):
        """Inicializa o banco de dados com as tabelas necessárias"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Tabela de obras
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS obras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_contrato TEXT NOT NULL,
                cliente TEXT NOT NULL,
                valor_contrato REAL NOT NULL,
                data_inicio TEXT,
                status TEXT DEFAULT 'Não Iniciada',
                data_criacao TEXT DEFAULT CURRENT_TIMESTAMP,
                contrato_ic TEXT,
                pedido_sap TEXT,
                prefixo_agencia TEXT,
                servico TEXT,
                valor_parceiro REAL,
                valor_percentual REAL,
                total_obra REAL,
                mes_execucao TEXT,
                ano_execucao INTEGER,
                data_conclusao TEXT,
                data_assinatura TEXT,
                data_aio TEXT
            )
        ''')
        
        # Tabela de templates de checklist (padrão)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS checklist_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                ordem INTEGER NOT NULL,
                prazo_dias INTEGER NOT NULL,
                tipo TEXT DEFAULT 'A',
                base_calculo TEXT DEFAULT 'inicio',
                depende_template_id INTEGER,
                dias_offset INTEGER DEFAULT 0,
                recorrencia TEXT DEFAULT 'unica',
                dia_referencia_mensal INTEGER,
                trigger_ui TEXT,
                possui_reiteracao INTEGER DEFAULT 1,
                FOREIGN KEY (depende_template_id) REFERENCES checklist_templates (id)
            )
        ''')
        
        # Tabela de checklist por obra
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS obra_checklist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                obra_id INTEGER NOT NULL,
                template_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                prazo_dias INTEGER NOT NULL,
                data_limite TEXT,
                concluido INTEGER DEFAULT 0,
                data_conclusao TEXT,
                tipo TEXT DEFAULT 'A',
                base_calculo TEXT DEFAULT 'inicio',
                data_base_calculo TEXT,
                depende_item_id INTEGER,
                bloqueado INTEGER DEFAULT 0,
                tentativas_reiteracao INTEGER DEFAULT 0,
                ultima_notificacao TEXT,
                status_notificacao TEXT DEFAULT 'pendente',
                recorrencia TEXT DEFAULT 'unica',
                mes_referencia TEXT,
                FOREIGN KEY (obra_id) REFERENCES obras (id),
                FOREIGN KEY (template_id) REFERENCES checklist_templates (id),
                FOREIGN KEY (depende_item_id) REFERENCES obra_checklist (id)
            )
        ''')
        
        # Tabela de histórico de notificações
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS historico_notificacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                obra_id INTEGER NOT NULL,
                tarefa_id INTEGER NOT NULL,
                tipo_notificacao TEXT NOT NULL,
                data_envio TEXT NOT NULL,
                destinatarios TEXT,
                sucesso INTEGER DEFAULT 1,
                mensagem_erro TEXT,
                FOREIGN KEY (obra_id) REFERENCES obras (id),
                FOREIGN KEY (tarefa_id) REFERENCES obra_checklist (id)
            )
        ''')
        
        # Insere templates padrão se não existirem
        cursor.execute('SELECT COUNT(*) as count FROM checklist_templates')
        if cursor.fetchone()['count'] == 0:
            # NOVOS TEMPLATES - 18 tarefas com dependências e lógica avançada
            templates = [
                # Grupo 1: Fluxo Inicial
                # (nome, ordem, prazo_dias, tipo, base_calculo, depende_template_id, dias_offset, recorrencia, dia_ref_mensal, trigger_ui, possui_reiteracao)
                ('RETORNO PROJETO E ORÇAMENTO', 1, 2, 'A', 'criacao', None, 0, 'unica', None, None, 1),
                ('ANÁLISE', 2, 3, 'B', 'fim_tarefa', 1, 0, 'unica', None, None, 0),
                ('ANÁLISE - GESTOR', 3, 2, 'B', 'fim_tarefa', 2, 0, 'unica', None, None, 0),
                
                # Grupo 2: Pós-Análise Gestor
                ('RETORNO DO QUESTIONAMENTO', 4, 2, 'A', 'fim_tarefa', 3, 0, 'unica', None, None, 1),
                ('CONTRATO ASSINADO', 5, 5, 'B', 'fim_tarefa', 3, 0, 'unica', None, 'data_assinatura', 0),
                
                # Grupo 3: Gatilho da Data de Assinatura
                ('SOLICITAR A DATA DA AIO', 6, 1, 'A', 'assinatura', None, 0, 'unica', None, 'data_aio', 1),
                ('PEDIDO MATERIAL ABC', 7, 8, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('ART', 8, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('SOLICITAÇÃO SEGUROS', 9, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('ACEITE SEGURO', 10, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('PAGAMENTO SEGURO', 11, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('ENVIO DO SEGURO + ART', 12, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                
                # Grupo 4: Gatilho da Data AIO
                ('CRONOGRAMA DE OBRA', 13, 0, 'B', 'aio', None, 0, 'unica', None, None, 0),
                ('RELATÓRIO', 14, 5, 'B', 'aio', None, 0, 'unica', None, None, 0),
                
                # Grupo 5: Prazos Regressivos (baseados no início da obra)
                ('CONTRATAÇÃO DA EQUIPE', 15, -15, 'B', 'inicio', None, 0, 'unica', None, None, 0),
                ('SOLICITAÇÃO DE ACESSO', 16, -10, 'B', 'inicio', None, 0, 'unica', None, None, 0),
                
                # Grupo 6: Tarefas Recorrentes (Mensais)
                ('MEDIÇÃO', 17, 0, 'B', 'inicio', None, 0, 'mensal', 20, None, 0),
                ('CONFIRMAÇÃO DE MEDIÇÃO', 18, 0, 'A', 'inicio', None, 0, 'mensal', 10, None, 1),
            ]
            cursor.executemany('''
                INSERT INTO checklist_templates 
                (nome, ordem, prazo_dias, tipo, base_calculo, depende_template_id, dias_offset, 
                 recorrencia, dia_referencia_mensal, trigger_ui, possui_reiteracao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', templates)
        
        conn.commit()
        conn.close()
    
    # ========== CRUD OBRAS ========== #
    def criar_obra(self, nome_contrato: str, cliente: str, valor_contrato: float, 
                   data_inicio: str, status: str = 'Não Iniciada', **kwargs) -> int:
        """Cria uma nova obra e retorna o ID"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
        
            # Extrai campos adicionais e converte strings vazias para None
            contrato_ic = kwargs.get('contrato_ic', None) or None
            pedido_sap = kwargs.get('pedido_sap', None) or None
            prefixo_agencia = kwargs.get('prefixo_agencia', None) or None
            servico = kwargs.get('servico', None) or None
            valor_parceiro = kwargs.get('valor_parceiro', None) or None
            valor_percentual = kwargs.get('valor_percentual', None) or None
            total_obra = kwargs.get('total_obra', None) or None
            mes_execucao = kwargs.get('mes_execucao', None) or None
            ano_execucao = kwargs.get('ano_execucao', None)
            data_conclusao = kwargs.get('data_conclusao', None) or None
            data_assinatura = kwargs.get('data_assinatura', None) or None
            data_aio = kwargs.get('data_aio', None) or None
            
            # Converte string vazia de data_inicio para None
            data_inicio = data_inicio or None
            
            # Data de criação com horário local
            data_criacao = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO obras (nome_contrato, cliente, valor_contrato, data_inicio, status,
                                 contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual,
                                 total_obra, mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio, data_criacao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (nome_contrato, cliente, valor_contrato, data_inicio, status,
                  contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual,
                  total_obra, mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio, data_criacao))
            
            obra_id = cursor.lastrowid
            
            # Prepara dados completos da obra para criar checklist
            obra_dados = {
                'data_inicio': data_inicio,
                'data_assinatura': data_assinatura,
                'data_aio': data_aio
            }
            
            # Cria checklist automático para a obra
            self._criar_checklist_obra(cursor, obra_id, obra_dados)
            
            conn.commit()
            conn.close()
            
            return obra_id
            
        except Exception as e:
            log_error(e, "database", f"Criar obra: {nome_contrato}")
            if 'conn' in locals():
                try:
                    conn.close()
                except:
                    pass
            raise
    
    def _criar_checklist_obra(self, cursor, obra_id: int, obra_dados: Dict):
        """Cria checklist automático baseado nos templates com dependências e lógica avançada"""
        cursor.execute('SELECT * FROM checklist_templates ORDER BY ordem')
        templates = cursor.fetchall()
        
        # Dicionário para mapear template_id -> obra_checklist_id (para resolver dependências)
        template_map = {}
        
        # Normaliza dados da obra: converte strings vazias para None
        data_inicio = obra_dados.get('data_inicio') or None
        data_assinatura = obra_dados.get('data_assinatura') or None
        data_aio = obra_dados.get('data_aio') or None
        
        # Verifica se a obra já começou
        hoje = datetime.date.today()
        obra_ja_comecou = False
        if data_inicio and data_inicio.strip():  # Verifica se data_inicio não é vazio
            try:
                data_inicio_obj = datetime.datetime.strptime(data_inicio, '%Y-%m-%d').date()
                obra_ja_comecou = data_inicio_obj <= hoje
            except ValueError:
                # Se data_inicio for inválida, considera que a obra não começou
                obra_ja_comecou = False
        
        # Primeira passagem: criar todos os itens
        for template in templates:
            # Para tarefas recorrentes mensais: cria template inicial bloqueado
            # Serão desbloqueadas e geradas mensalmente pelo GeradorTarefasRecorrentes
            if template['recorrencia'] == 'mensal':
                # Determina se deve bloquear: bloqueia se a obra ainda não começou ou se data_inicio não foi preenchida
                bloqueado_mensal = 0 if obra_ja_comecou else 1
                
                # Cria tarefa mensal "template" (será gerenciada pelo gerador)
                cursor.execute('''
                    INSERT INTO obra_checklist 
                    (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, 
                     base_calculo, data_base_calculo, bloqueado, status_notificacao, recorrencia)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (obra_id, template['id'], template['nome'], template['prazo_dias'],
                      None,  # data_limite será definida pelo gerador mensal
                      template['tipo'], template['base_calculo'], data_inicio, bloqueado_mensal, 
                      'pendente', template['recorrencia']))
                
                template_map[template['id']] = cursor.lastrowid
                continue
            
            # Determina se a tarefa deve iniciar bloqueada
            bloqueado = 0
            data_limite = None
            data_base = None
            
            # Calcula data_limite baseado em base_calculo
            if template['base_calculo'] == 'criacao':
                # Base na data de criação da obra (hoje)
                data_base = datetime.date.today().strftime('%Y-%m-%d')
                data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])
                    
            elif template['base_calculo'] == 'inicio':
                data_base = data_inicio
                if data_base and data_base.strip():  # Verifica se data_inicio não é vazio
                    try:
                        data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                        # Suporta prazos negativos (regressivos)
                        data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])
                    except ValueError:
                        # Se data for inválida, bloqueia a tarefa
                        bloqueado = 1
                        data_limite = None
                else:
                    bloqueado = 1  # Bloqueia até data_inicio ser preenchida
                    
            elif template['base_calculo'] == 'assinatura':
                data_base = data_assinatura
                if data_base:
                    data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                    data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])
                else:
                    bloqueado = 1  # Bloqueia até data_assinatura ser preenchida
                    
            elif template['base_calculo'] == 'aio':
                data_base = data_aio
                if data_base:
                    data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                    data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])
                else:
                    bloqueado = 1  # Bloqueia até data_aio ser preenchida
                    
            elif template['base_calculo'] == 'fim_tarefa':
                # Depende do fim de outra tarefa - será calculado na segunda passagem
                bloqueado = 1
                data_base = None
            
            # Insere item do checklist
            cursor.execute('''
                INSERT INTO obra_checklist 
                (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, 
                 base_calculo, data_base_calculo, bloqueado, status_notificacao, recorrencia)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (obra_id, template['id'], template['nome'], template['prazo_dias'],
                  data_limite.strftime('%Y-%m-%d') if data_limite else None,
                  template['tipo'], template['base_calculo'], data_base, bloqueado, 
                  'pendente', template['recorrencia']))
            
            # Armazena mapeamento
            template_map[template['id']] = cursor.lastrowid
        
        # Segunda passagem: resolver dependências fim_tarefa
        cursor.execute('SELECT * FROM checklist_templates WHERE base_calculo = "fim_tarefa" OR depende_template_id IS NOT NULL')
        templates_dependentes = cursor.fetchall()
        
        for template in templates_dependentes:
            item_id = template_map.get(template['id'])
            if not item_id:
                continue
            
            depende_template_id = template['depende_template_id']
            if depende_template_id and depende_template_id in template_map:
                depende_item_id = template_map[depende_template_id]
                
                # Atualiza dependência
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET depende_item_id = ?
                    WHERE id = ?
                ''', (depende_item_id, item_id))
                
                # Se a tarefa dependente estiver concluída, desbloqueia e calcula prazo
                cursor.execute('SELECT concluido, data_conclusao FROM obra_checklist WHERE id = ?', (depende_item_id,))
                tarefa_dep = cursor.fetchone()
                
                if tarefa_dep and tarefa_dep['concluido']:
                    data_base = tarefa_dep['data_conclusao']
                    data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                    data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])
                    
                    cursor.execute('''
                        UPDATE obra_checklist 
                        SET bloqueado = 0, data_limite = ?, data_base_calculo = ?
                        WHERE id = ?
                    ''', (data_limite.strftime('%Y-%m-%d'), data_base, item_id))

    
    def listar_obras(self, filtro: str = None) -> List[Dict]:
        """Lista todas as obras, com filtro opcional"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if filtro:
            query = '''
                SELECT * FROM obras 
                WHERE nome_contrato LIKE ? OR cliente LIKE ? OR status LIKE ?
                ORDER BY data_inicio DESC
            '''
            cursor.execute(query, (f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'))
        else:
            cursor.execute('SELECT * FROM obras ORDER BY data_inicio DESC')
        
        obras = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return obras
    
    def obter_obra(self, obra_id: int) -> Optional[Dict]:
        """Obtém uma obra específica por ID"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM obras WHERE id = ?', (obra_id,))
        obra = cursor.fetchone()
        
        conn.close()
        
        return dict(obra) if obra else None
    
    def atualizar_obra(self, obra_id: int, nome_contrato: str, cliente: str, 
                       valor_contrato: float, data_inicio: str, status: str, **kwargs) -> bool:
        """Atualiza uma obra existente. Retorna True se requer confirmação de recálculo"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
        
            # Busca dados antigos para comparação
            cursor.execute('SELECT data_inicio, data_assinatura, data_aio FROM obras WHERE id = ?', (obra_id,))
            obra_antiga = cursor.fetchone()
            
            # Extrai campos adicionais e converte strings vazias para None
            contrato_ic = kwargs.get('contrato_ic', None) or None
            pedido_sap = kwargs.get('pedido_sap', None) or None
            prefixo_agencia = kwargs.get('prefixo_agencia', None) or None
            servico = kwargs.get('servico', None) or None
            valor_parceiro = kwargs.get('valor_parceiro', None) or None
            valor_percentual = kwargs.get('valor_percentual', None) or None
            total_obra = kwargs.get('total_obra', None) or None
            mes_execucao = kwargs.get('mes_execucao', None) or None
            ano_execucao = kwargs.get('ano_execucao', None)
            data_conclusao = kwargs.get('data_conclusao', None) or None
            data_assinatura = kwargs.get('data_assinatura', None) or None
            data_aio = kwargs.get('data_aio', None) or None
            
            # Converte string vazia de data_inicio para None
            data_inicio = data_inicio or None
            
            cursor.execute('''
                UPDATE obras 
                SET nome_contrato = ?, cliente = ?, valor_contrato = ?, 
                    data_inicio = ?, status = ?, contrato_ic = ?, pedido_sap = ?, prefixo_agencia = ?,
                    servico = ?, valor_parceiro = ?, valor_percentual = ?, total_obra = ?,
                    mes_execucao = ?, ano_execucao = ?, data_conclusao = ?, 
                    data_assinatura = ?, data_aio = ?
                WHERE id = ?
            ''', (nome_contrato, cliente, valor_contrato, data_inicio, status,
                  contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual, total_obra,
                  mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio, obra_id))
            
            # Verifica se houve mudança em datas críticas
            requer_confirmacao = False
            if obra_antiga:
                # Verifica mudança em data_inicio
                if obra_antiga['data_inicio'] != data_inicio:
                    # Verifica se existem tarefas com base_calculo='inicio'
                    cursor.execute('''
                        SELECT COUNT(*) as count FROM obra_checklist 
                        WHERE obra_id = ? AND base_calculo = 'inicio'
                    ''', (obra_id,))
                    if cursor.fetchone()['count'] > 0:
                        requer_confirmacao = True
                
                # Verifica mudança em data_assinatura ou data_aio
                if obra_antiga['data_assinatura'] != data_assinatura or obra_antiga['data_aio'] != data_aio:
                    # Verifica se existem tarefas concluídas que dependem dessas datas
                    cursor.execute('''
                        SELECT COUNT(*) as count FROM obra_checklist 
                        WHERE obra_id = ? AND concluido = 1 
                        AND (base_calculo = 'assinatura' OR base_calculo = 'aio')
                    ''', (obra_id,))
                    if cursor.fetchone()['count'] > 0:
                        requer_confirmacao = True
            
            conn.commit()
            conn.close()
            
            return requer_confirmacao
            
        except Exception as e:
            log_error(e, "database", f"Atualizar obra - ID: {obra_id}, Nome: {nome_contrato}")
            if 'conn' in locals():
                try:
                    conn.close()
                except:
                    pass
            raise
    
    def deletar_obra(self, obra_id: int):
        """Deleta uma obra e seu checklist"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM obra_checklist WHERE obra_id = ?', (obra_id,))
            cursor.execute('DELETE FROM obras WHERE id = ?', (obra_id,))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            log_error(e, "database", f"Deletar obra - ID: {obra_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except:
                    pass
            raise
    
    def recalcular_checklist(self, obra_id: int, campo_atualizado: str, nova_data: str):
        """Recalcula prazos do checklist quando data crítica é alterada"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        base_calculo_map = {
            'data_assinatura': 'assinatura',
            'data_aio': 'aio',
            'data_inicio': 'inicio'
        }
        
        base_calculo = base_calculo_map.get(campo_atualizado)
        if not base_calculo:
            conn.close()
            return
        
        # Se nova_data está vazia, bloqueia as tarefas relacionadas
        if not nova_data or not nova_data.strip():
            print(f"\n🔒 Data {campo_atualizado} removida. Bloqueando tarefas relacionadas...")
            cursor.execute('''
                UPDATE obra_checklist 
                SET bloqueado = 1, data_limite = NULL, data_base_calculo = NULL
                WHERE obra_id = ? AND base_calculo = ? AND concluido = 0
            ''', (obra_id, base_calculo))
            
            # Se for data_inicio, bloqueia também tarefas mensais
            if campo_atualizado == 'data_inicio':
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET bloqueado = 1
                    WHERE obra_id = ? AND recorrencia = 'mensal' AND concluido = 0
                ''', (obra_id,))
            
            conn.commit()
            conn.close()
            print(f"✅ Tarefas bloqueadas com sucesso\n")
            return
        
        print(f"\n🔄 Recalculando tarefas com base_calculo='{base_calculo}' para obra {obra_id}...")
        print(f"   Nova data base: {nova_data}")
        
        # Debug: Mostra TODAS as tarefas da obra
        cursor.execute('SELECT descricao, base_calculo, concluido, bloqueado, data_limite, recorrencia FROM obra_checklist WHERE obra_id = ?', (obra_id,))
        todas = cursor.fetchall()
        print(f"   === DEBUG: TODAS as tarefas da obra ===")
        for t in todas:
            print(f"   - {t['descricao']}: base={t['base_calculo']}, concluido={t['concluido']}, bloqueado={t['bloqueado']}, limite={t['data_limite']}, recorrencia={t['recorrencia']}")
        print(f"   =====================================")
        
        # Se campo atualizado é data_inicio, verifica se deve desbloquear tarefas mensais
        if campo_atualizado == 'data_inicio':
            hoje = datetime.date.today()
            data_inicio_obj = datetime.datetime.strptime(nova_data, '%Y-%m-%d').date()
            
            if data_inicio_obj <= hoje:
                # Obra já começou: desbloqueia tarefas mensais
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET bloqueado = 0
                    WHERE obra_id = ? AND recorrencia = 'mensal' AND bloqueado = 1
                ''', (obra_id,))
                rows_updated = cursor.rowcount
                if rows_updated > 0:
                    print(f"   ✅ Desbloqueadas {rows_updated} tarefa(s) mensal(is)")
            else:
                # Obra ainda não começou: bloqueia tarefas mensais
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET bloqueado = 1
                    WHERE obra_id = ? AND recorrencia = 'mensal' AND concluido = 0
                ''', (obra_id,))
                rows_updated = cursor.rowcount
                if rows_updated > 0:
                    print(f"   🔒 Bloqueadas {rows_updated} tarefa(s) mensal(is)")
        
        # Busca tarefas que dependem dessa data (não concluídas)
        cursor.execute('''
            SELECT * FROM obra_checklist 
            WHERE obra_id = ? AND base_calculo = ? AND concluido = 0
        ''', (obra_id, base_calculo))
        
        tarefas = cursor.fetchall()
        print(f"   Tarefas encontradas para recálculo: {len(tarefas)}")
        
        tarefas_atualizadas = 0
        for tarefa in tarefas:
            # Recalcula data_limite usando o prazo_dias da própria tarefa
            data_obj = datetime.datetime.strptime(nova_data, '%Y-%m-%d')
            prazo_dias = tarefa['prazo_dias']
            
            # Suporta prazos negativos (regressivos)
            nova_data_limite = data_obj + datetime.timedelta(days=prazo_dias)
            
            print(f"   📝 {tarefa['descricao']}: prazo={prazo_dias} dias, antiga={tarefa['data_limite']}, nova={nova_data_limite.strftime('%d/%m/%Y')}")
            
            # Atualiza tarefa
            cursor.execute('''
                UPDATE obra_checklist 
                SET data_limite = ?, data_base_calculo = ?, bloqueado = 0, 
                    tentativas_reiteracao = 0, status_notificacao = 'pendente'
                WHERE id = ?
            ''', (nova_data_limite.strftime('%Y-%m-%d'), nova_data, tarefa['id']))
            
            print(f"   ✅ Recalculado: {tarefa['descricao']} -> {nova_data_limite.strftime('%d/%m/%Y')}")
            tarefas_atualizadas += 1
        
        conn.commit()
        conn.close()
        
        print(f"🔄 Recálculo concluído: {tarefas_atualizadas} tarefa(s) atualizada(s)\n")
        return tarefas_atualizadas
    
    # ========== CRUD CHECKLIST ========== #
    def obter_checklist(self, obra_id: int) -> List[Dict]:
        """Obtém o checklist de uma obra"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM obra_checklist 
            WHERE obra_id = ? 
            ORDER BY id
        ''', (obra_id,))
        
        checklist = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return checklist
    
    def obter_item_checklist(self, item_id: int) -> Optional[Dict]:
        """Obtém um item específico do checklist"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM obra_checklist 
            WHERE id = ?
        ''', (item_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    def marcar_item_checklist(self, item_id: int, concluido: bool) -> Optional[str]:
        """Marca/desmarca um item do checklist. Retorna trigger_ui se houver"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        trigger_ui = None
        
        if concluido:
            data_conclusao = datetime.datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                UPDATE obra_checklist 
                SET concluido = 1, data_conclusao = ?
                WHERE id = ?
            ''', (data_conclusao, item_id))
            
            # Busca se tem trigger_ui
            cursor.execute('''
                SELECT ct.trigger_ui, oc.obra_id 
                FROM obra_checklist oc
                JOIN checklist_templates ct ON oc.template_id = ct.id
                WHERE oc.id = ?
            ''', (item_id,))
            
            row = cursor.fetchone()
            if row and row['trigger_ui']:
                trigger_ui = row['trigger_ui']
            
            # Desbloqueia tarefas dependentes
            cursor.execute('''
                SELECT id, prazo_dias FROM obra_checklist 
                WHERE depende_item_id = ? AND concluido = 0
            ''', (item_id,))
            
            dependentes = cursor.fetchall()
            for dep in dependentes:
                # Calcula nova data_limite baseada na data de conclusão
                data_obj = datetime.datetime.strptime(data_conclusao, '%Y-%m-%d')
                nova_data_limite = data_obj + datetime.timedelta(days=dep['prazo_dias'])
                
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET bloqueado = 0, data_limite = ?, data_base_calculo = ?
                    WHERE id = ?
                ''', (nova_data_limite.strftime('%Y-%m-%d'), data_conclusao, dep['id']))
        else:
            cursor.execute('''
                UPDATE obra_checklist 
                SET concluido = 0, data_conclusao = NULL
                WHERE id = ?
            ''', (item_id,))
            
            # Rebloqueia tarefas dependentes
            cursor.execute('''
                UPDATE obra_checklist 
                SET bloqueado = 1, data_limite = NULL
                WHERE depende_item_id = ? AND concluido = 0
            ''', (item_id,))
        
        conn.commit()
        conn.close()
        
        return trigger_ui
    
    def obter_tarefas_atrasadas(self) -> List[Dict]:
        """Retorna tarefas não concluídas que passaram do prazo"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        hoje = datetime.date.today().strftime('%Y-%m-%d')
        
        cursor.execute('''
            SELECT oc.*, o.nome_contrato, o.cliente
            FROM obra_checklist oc
            JOIN obras o ON oc.obra_id = o.id
            WHERE oc.concluido = 0 AND oc.data_limite < ?
            ORDER BY oc.data_limite
        ''', (hoje,))
        
        tarefas = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        return tarefas
