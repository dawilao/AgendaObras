"""
Módulo de gerenciamento do banco de dados SQLite para o sistema AgendaObras.
Contém a classe Database com todas as operações CRUD para obras e checklists.
"""

import sqlite3
import datetime
import os
from typing import List, Dict, Optional
from migrations import run_migrations
from error_logger import log_error

_CAMINHO_DRIVE = r'G:\Meu Drive\17 - MODELOS\PROGRAMAS\AgendaObras\app\db'
_CAMINHO_LOCAL = os.path.dirname(os.path.abspath(__file__))


def _resolver_caminho_db() -> str:
    """Resolve o caminho do banco principal com suporte a ambiente Linux.
    Prioriza variável de ambiente, depois Google Drive e por fim caminho local."""
    env_path = (os.getenv('AGENDA_OBRAS_DB_PATH') or '').strip()
    if env_path:
        return env_path

    if os.path.isdir(_CAMINHO_DRIVE):
        return os.path.join(_CAMINHO_DRIVE, 'agendaobras.db')

    return os.path.join(_CAMINHO_LOCAL, 'agendaobras.db')


CAMINHO_DB = _resolver_caminho_db()

TAREFAS_COM_DIAS_UTEIS = {'ANÁLISE', 'ANÁLISE - GESTOR'}

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

    def _adicionar_dias_uteis(self, data_base: datetime.datetime, dias: int) -> datetime.datetime:
        """Adiciona dias úteis (ignora sábado e domingo) a partir da data base."""
        if dias == 0:
            return data_base

        passo = 1 if dias > 0 else -1
        restantes = abs(dias)
        data_resultado = data_base

        while restantes > 0:
            data_resultado += datetime.timedelta(days=passo)
            if data_resultado.weekday() < 5:
                restantes -= 1

        return data_resultado

    def _calcular_data_limite(self, data_base: datetime.datetime, prazo_dias: int, descricao: Optional[str] = None) -> datetime.datetime:
        """Calcula a data limite com regra especial para tarefas em dias úteis."""
        if descricao in TAREFAS_COM_DIAS_UTEIS:
            return self._adicionar_dias_uteis(data_base, prazo_dias)
        return data_base + datetime.timedelta(days=prazo_dias)
    
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
                data_aio TEXT,
                data_acionamento TEXT,
                observacoes TEXT,
                obs_usuario TEXT,
                obs_data TEXT
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

        # Tabela para rastrear medições configuradas por obra (dinâmico)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS medicoes_obra (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                obra_id INTEGER NOT NULL UNIQUE,
                quantidade INTEGER NOT NULL DEFAULT 0,
                data_ultima_alteracao TEXT,
                FOREIGN KEY (obra_id) REFERENCES obras (id)
            )
        ''')
        cursor.execute('PRAGMA table_info(medicoes_obra)')
        medicoes_cols = [r[1] for r in cursor.fetchall()]
        if 'data_ultima_alteracao' not in medicoes_cols:
            cursor.execute('ALTER TABLE medicoes_obra ADD COLUMN data_ultima_alteracao TEXT')
        if 'atualizado_em' not in medicoes_cols:
            cursor.execute('ALTER TABLE medicoes_obra ADD COLUMN atualizado_em TEXT')

        # Tabela para histórico de valores medidos (Fase 3 - Financeiro)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS medicoes_valores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                obra_id INTEGER NOT NULL,
                tarefa_id INTEGER NOT NULL,
                valor_medido REAL NOT NULL,
                data_medicao TEXT NOT NULL,
                mes_referencia TEXT,
                FOREIGN KEY (obra_id) REFERENCES obras (id),
                FOREIGN KEY (tarefa_id) REFERENCES obra_checklist (id)
            )
        ''')

        # Garante coluna valor_medido na tabela obra_checklist (Fase 3)
        cursor.execute("PRAGMA table_info(obra_checklist)")
        checklist_cols = [r[1] for r in cursor.fetchall()]
        if 'valor_medido' not in checklist_cols:
            cursor.execute("ALTER TABLE obra_checklist ADD COLUMN valor_medido REAL")

        # Garante coluna de status de conclusão específica para a obra
        cursor.execute("PRAGMA table_info(obras)")
        cols = [r[1] for r in cursor.fetchall()]
        if 'status_conclusao_obra' not in cols:
            cursor.execute("ALTER TABLE obras ADD COLUMN status_conclusao_obra TEXT DEFAULT NULL")
        
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

            nome_contrato = (nome_contrato or '').strip()
            cliente = (cliente or '').strip()
        
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
            data_acionamento = kwargs.get('data_acionamento', None) or None
            
            # Converte string vazia de data_inicio para None
            data_inicio = data_inicio or None
            
            # Data de criação com horário local
            data_criacao = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO obras (nome_contrato, cliente, valor_contrato, data_inicio, status,
                                 contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual,
                                 total_obra, mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio,
                                 data_acionamento, data_criacao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (nome_contrato, cliente, valor_contrato, data_inicio, status,
                  contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual,
                  total_obra, mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio,
                  data_acionamento, data_criacao))
            
            obra_id = cursor.lastrowid
            
            # Prepara dados completos da obra para criar checklist
            obra_dados = {
                'data_inicio': data_inicio,
                'data_assinatura': data_assinatura,
                'data_aio': data_aio,
                'data_acionamento': data_acionamento
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
        data_acionamento = obra_dados.get('data_acionamento') or None
        
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
            # Não cria tarefas mensais padrão no card inicial.
            # MEDIÇÃO/CONFIRMAÇÃO serão geradas apenas pelo fluxo dinâmico de medições.
            if template['recorrencia'] == 'mensal':
                continue
            
            # Determina se a tarefa deve iniciar bloqueada
            bloqueado = 0
            data_limite = None
            data_base = None
            
            # Calcula data_limite baseado em base_calculo
            if template['base_calculo'] == 'criacao':
                # Base na data de acionamento (se informada) ou data de hoje como fallback
                if data_acionamento and data_acionamento.strip():
                    data_base = data_acionamento
                else:
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
                    data_limite = self._calcular_data_limite(data_obj, template['prazo_dias'], template['nome'])
                    
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

    def listar_obras_por_contratos(self, contratos_permitidos: List[str], filtro: str = None) -> List[Dict]:
        """Lista obras filtrando por contratos permitidos (campo cliente)."""
        contratos_limpos = [(c or '').strip() for c in (contratos_permitidos or []) if (c or '').strip()]
        if not contratos_limpos:
            return []

        conn = self.get_connection()
        cursor = conn.cursor()

        placeholders = ','.join(['?'] * len(contratos_limpos))
        params = list(contratos_limpos)

        query = f'SELECT * FROM obras WHERE TRIM(cliente) IN ({placeholders})'

        if filtro:
            query += ' AND (nome_contrato LIKE ? OR cliente LIKE ? OR status LIKE ?)'
            params.extend([f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'])

        query += ' ORDER BY data_inicio DESC'

        cursor.execute(query, params)
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

            nome_contrato = (nome_contrato or '').strip()
            cliente = (cliente or '').strip()
        
            # Busca dados antigos para comparação
            cursor.execute('SELECT data_inicio, data_assinatura, data_aio, data_acionamento FROM obras WHERE id = ?', (obra_id,))
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
            data_acionamento = kwargs.get('data_acionamento', None) or None
            
            # Converte string vazia de data_inicio para None
            data_inicio = data_inicio or None
            
            cursor.execute('''
                UPDATE obras 
                SET nome_contrato = ?, cliente = ?, valor_contrato = ?, 
                    data_inicio = ?, status = ?, contrato_ic = ?, pedido_sap = ?, prefixo_agencia = ?,
                    servico = ?, valor_parceiro = ?, valor_percentual = ?, total_obra = ?,
                    mes_execucao = ?, ano_execucao = ?, data_conclusao = ?, 
                    data_assinatura = ?, data_aio = ?, data_acionamento = ?
                WHERE id = ?
            ''', (nome_contrato, cliente, valor_contrato, data_inicio, status,
                  contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual, total_obra,
                  mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio, data_acionamento, obra_id))
            
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
                
                # Verifica mudança em data_acionamento
                if obra_antiga['data_acionamento'] != data_acionamento:
                    cursor.execute('''
                        SELECT COUNT(*) as count FROM obra_checklist 
                        WHERE obra_id = ? AND base_calculo = 'criacao'
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
            'data_inicio': 'inicio',
            'data_acionamento': 'criacao'
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

    def atualizar_data_critica(self, obra_id: int, campo: str, data: str):
        """Atualiza apenas um campo de data crítica (data_assinatura ou data_aio) sem afetar outros campos"""
        if campo not in ('data_assinatura', 'data_aio'):
            raise ValueError(f"Campo de data crítica inválido: {campo}")
        
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(f'UPDATE obras SET {campo} = ? WHERE id = ?', (data or None, obra_id))
        conn.commit()
        conn.close()

    def atualizar_observacoes_obra(self, obra_id: int, observacoes: Optional[str],
                                   obs_usuario: Optional[str], obs_data: Optional[str]) -> bool:
        """Atualiza observações e metadados de edição da obra."""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            observacoes = (observacoes or '').strip() or None
            obs_usuario = (obs_usuario or '').strip() or None
            obs_data = (obs_data or '').strip() or None

            cursor.execute('''
                UPDATE obras
                SET observacoes = ?, obs_usuario = ?, obs_data = ?
                WHERE id = ?
            ''', (observacoes, obs_usuario, obs_data, obra_id))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            log_error(e, "database", f"Atualizar observações da obra - ID: {obra_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            return False
    
    def marcar_item_checklist(self, item_id: int, concluido: bool) -> Optional[str]:
        """Marca/desmarca um item do checklist. Retorna trigger_ui se houver"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        trigger_ui = None
        
        # Busca trigger_ui e obra_id (necessário tanto ao marcar quanto desmarcar)
        cursor.execute('''
            SELECT ct.trigger_ui, oc.obra_id, oc.descricao 
            FROM obra_checklist oc
            JOIN checklist_templates ct ON oc.template_id = ct.id
            WHERE oc.id = ?
        ''', (item_id,))
        row_info = cursor.fetchone()
        obra_id = row_info['obra_id'] if row_info else None
        item_descricao = (row_info['descricao'] or '') if row_info else ''
        if row_info and row_info['trigger_ui']:
            trigger_ui = row_info['trigger_ui']
        
        if concluido:
            data_conclusao = datetime.datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                UPDATE obra_checklist 
                SET concluido = 1, data_conclusao = ?
                WHERE id = ?
            ''', (data_conclusao, item_id))
            
            # Desbloqueia tarefas dependentes
            cursor.execute('''
                SELECT id, prazo_dias, descricao FROM obra_checklist 
                WHERE depende_item_id = ? AND concluido = 0
            ''', (item_id,))
            
            dependentes = cursor.fetchall()
            for dep in dependentes:
                # Calcula nova data_limite baseada na data de conclusão
                data_obj = datetime.datetime.strptime(data_conclusao, '%Y-%m-%d')
                nova_data_limite = self._calcular_data_limite(data_obj, dep['prazo_dias'], dep['descricao'])
                
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

            # Se a tarefa desmarcada faz parte do fluxo de medições, invalida a conclusão da obra
            if obra_id and (item_descricao.startswith('MEDIÇÃO ') or item_descricao.startswith('CONFIRMAÇÃO DE MEDIÇÃO')):
                cursor.execute('''
                    UPDATE obras
                    SET status = 'Em Andamento',
                        status_conclusao_obra = NULL,
                        data_conclusao = NULL
                    WHERE id = ?
                ''', (obra_id,))
            
            # Rebloqueia tarefas dependentes diretas (por depende_item_id)
            cursor.execute('''
                UPDATE obra_checklist 
                SET bloqueado = 1, data_limite = NULL
                WHERE depende_item_id = ? AND concluido = 0
            ''', (item_id,))
            
            # Se tem trigger_ui, limpa a data correspondente e rebloqueia tarefas baseadas nela
            if trigger_ui and obra_id:
                # Mapa trigger_ui -> campo na tabela obras e base_calculo no checklist
                trigger_map = {
                    'data_assinatura': ('data_assinatura', 'assinatura'),
                    'data_aio': ('data_aio', 'aio'),
                }
                if trigger_ui in trigger_map:
                    campo_obra, base_calculo = trigger_map[trigger_ui]
                    
                    # Limpa a data na tabela obras
                    cursor.execute(f'UPDATE obras SET {campo_obra} = NULL WHERE id = ?', (obra_id,))
                    
                    # Rebloqueia e limpa prazos de tarefas que dependem dessa data
                    cursor.execute('''
                        UPDATE obra_checklist 
                        SET bloqueado = 1, data_limite = NULL, data_base_calculo = NULL
                        WHERE obra_id = ? AND base_calculo = ? AND concluido = 0
                    ''', (obra_id, base_calculo))
                    
                    # Tarefas com base_calculo dessa data que foram concluídas e têm trigger_ui
                    # também devem ter seus efeitos cascateados (ex: desmarcar CONTRATO ASSINADO
                    # limpa data_assinatura, que afeta SOLICITAR A DATA DA AIO que tem trigger_ui=data_aio)
                    cursor.execute('''
                        SELECT oc.id, ct.trigger_ui
                        FROM obra_checklist oc
                        JOIN checklist_templates ct ON oc.template_id = ct.id
                        WHERE oc.obra_id = ? AND oc.base_calculo = ? AND oc.concluido = 1
                        AND ct.trigger_ui IS NOT NULL
                    ''', (obra_id, base_calculo))
                    
                    tarefas_cascata = cursor.fetchall()
                    for tarefa_cascata in tarefas_cascata:
                        # Desmarca a tarefa em cascata
                        cursor.execute('''
                            UPDATE obra_checklist 
                            SET concluido = 0, data_conclusao = NULL
                            WHERE id = ?
                        ''', (tarefa_cascata['id'],))
                        
                        # Se essa tarefa cascateada também tem trigger_ui, limpa a data correspondente
                        cascata_trigger = tarefa_cascata['trigger_ui']
                        if cascata_trigger in trigger_map:
                            campo_cascata, base_cascata = trigger_map[cascata_trigger]
                            cursor.execute(f'UPDATE obras SET {campo_cascata} = NULL WHERE id = ?', (obra_id,))
                            cursor.execute('''
                                UPDATE obra_checklist 
                                SET bloqueado = 1, data_limite = NULL, data_base_calculo = NULL
                                WHERE obra_id = ? AND base_calculo = ? AND concluido = 0
                            ''', (obra_id, base_cascata))
        
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

    # ========== Medições Dinâmicas ========== #
    def obter_medicoes_obra(self, obra_id: int) -> Optional[Dict]:
        """Retorna registro de medições configuradas para a obra"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM medicoes_obra WHERE obra_id = ?', (obra_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def criar_medicoes_dinamicas(self, obra_id: int, quantidade: int) -> bool:
        """Cria/atualiza medições dinâmicas para uma obra (máx 12).

        Gera tarefas `MEDIÇÃO MM/YYYY` (dia 20 do mês) e
        `CONFIRMAÇÃO DE MEDIÇÃO MM/YYYY` (dia 10 do mês seguinte).
        Não deleta medições já concluídas.
        """
        if quantidade is None:
            return False
        quantidade = int(quantidade)
        if quantidade < 1 or quantidade > 12:
            raise ValueError('Quantidade de medições deve ser entre 1 e 12')

        conn = self.get_connection()
        cursor = conn.cursor()

        def _mes_ref(ano: int, mes: int) -> str:
            return f"{ano:04d}-{mes:02d}"

        def _avancar_mes(ano: int, mes: int) -> tuple[int, int]:
            proximo_mes = mes + 1
            proximo_ano = ano + (proximo_mes - 1) // 12
            proximo_mes = ((proximo_mes - 1) % 12) + 1
            return proximo_ano, proximo_mes

        # Limpa tarefas mensais padrão legadas (sem mês/ano) para evitar soma com as dinâmicas
        cursor.execute('''
            DELETE FROM obra_checklist
            WHERE obra_id = ?
              AND descricao IN ('MEDIÇÃO', 'CONFIRMAÇÃO DE MEDIÇÃO')
              AND (mes_referencia IS NULL OR mes_referencia = '')
        ''', (obra_id,))

        # Busca data de início da obra
        cursor.execute('SELECT data_inicio FROM obras WHERE id = ?', (obra_id,))
        row = cursor.fetchone()
        if not row or not row['data_inicio']:
            conn.close()
            raise ValueError('Data de início da obra não preenchida')

        try:
            data_inicio = datetime.datetime.strptime(row['data_inicio'], '%Y-%m-%d').date()
        except Exception:
            conn.close()
            raise ValueError('Formato de data_inicio inválido')

        # Obtém template ids para MEDIÇÃO e CONFIRMAÇÃO
        cursor.execute('SELECT id FROM checklist_templates WHERE nome = ?', ('MEDIÇÃO',))
        t_med = cursor.fetchone()
        cursor.execute('SELECT id FROM checklist_templates WHERE nome = ?', ('CONFIRMAÇÃO DE MEDIÇÃO',))
        t_conf = cursor.fetchone()
        template_med_id = t_med['id'] if t_med else None
        template_conf_id = t_conf['id'] if t_conf else None

        cursor.execute('''
            SELECT id, descricao, concluido, mes_referencia
            FROM obra_checklist
            WHERE obra_id = ?
              AND (
                    descricao LIKE 'MEDIÇÃO %'
                    OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %'
                  )
        ''', (obra_id,))
        tarefas_existentes = cursor.fetchall()

        desejados = set()

        for i in range(quantidade):
            m = data_inicio.month + i
            y = data_inicio.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            mes_referencia = _mes_ref(y, m)
            desejados.add(mes_referencia)

            ano_conf, mes_conf = _avancar_mes(y, m)
            competencia = f"{m:02d}/{y}"
            # A nomenclatura segue a competência da medição, não a data de emissão do alerta.
            descr_med = f"MEDIÇÃO {competencia}"
            descr_conf = f"CONFIRMAÇÃO DE MEDIÇÃO {competencia}"
            data_limite_med = datetime.date(y, m, 20)
            data_limite_conf = datetime.date(ano_conf, mes_conf, 10)

            cursor.execute('''
                SELECT id, concluido
                FROM obra_checklist
                WHERE obra_id = ? AND descricao = ?
            ''', (obra_id, descr_med))
            existente_med = cursor.fetchone()
            if not existente_med:
                cursor.execute('''
                    INSERT INTO obra_checklist
                    (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, base_calculo, data_base_calculo, bloqueado, recorrencia, mes_referencia)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    obra_id,
                    template_med_id or 0,
                    descr_med,
                    0,
                    data_limite_med.strftime('%Y-%m-%d'),
                    'B',
                    'inicio',
                    data_inicio.strftime('%Y-%m-%d'),
                    0,
                    'unica',
                    mes_referencia
                ))
            elif not existente_med['concluido']:
                cursor.execute('''
                    UPDATE obra_checklist
                    SET template_id = ?, prazo_dias = ?, data_limite = ?, tipo = ?, base_calculo = ?,
                        data_base_calculo = ?, bloqueado = 0, recorrencia = 'unica', mes_referencia = ?
                    WHERE id = ?
                ''', (
                    template_med_id or 0,
                    0,
                    data_limite_med.strftime('%Y-%m-%d'),
                    'B',
                    'inicio',
                    data_inicio.strftime('%Y-%m-%d'),
                    mes_referencia,
                    existente_med['id']
                ))

            cursor.execute('''
                SELECT id, concluido
                FROM obra_checklist
                WHERE obra_id = ? AND descricao = ?
            ''', (obra_id, descr_conf))
            existente_conf = cursor.fetchone()
            if not existente_conf:
                cursor.execute('''
                    INSERT INTO obra_checklist
                    (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, base_calculo, data_base_calculo, bloqueado, recorrencia, mes_referencia)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    obra_id,
                    template_conf_id or 0,
                    descr_conf,
                    0,
                    data_limite_conf.strftime('%Y-%m-%d'),
                    'A',
                    'inicio',
                    data_inicio.strftime('%Y-%m-%d'),
                    0,
                    'unica',
                    mes_referencia
                ))
            elif not existente_conf['concluido']:
                cursor.execute('''
                    UPDATE obra_checklist
                    SET template_id = ?, prazo_dias = ?, data_limite = ?, tipo = ?, base_calculo = ?,
                        data_base_calculo = ?, bloqueado = 0, recorrencia = 'unica', mes_referencia = ?
                    WHERE id = ?
                ''', (
                    template_conf_id or 0,
                    0,
                    data_limite_conf.strftime('%Y-%m-%d'),
                    'A',
                    'inicio',
                    data_inicio.strftime('%Y-%m-%d'),
                    mes_referencia,
                    existente_conf['id']
                ))

        tarefas_por_mes = {}
        for tarefa in tarefas_existentes:
            mes_ref_tarefa = (tarefa['mes_referencia'] or '').strip()
            if not mes_ref_tarefa:
                continue
            tarefas_por_mes.setdefault(mes_ref_tarefa, []).append(tarefa)

        for mes_ref_tarefa, tarefas_mes in tarefas_por_mes.items():
            if mes_ref_tarefa in desejados:
                continue
            if any(t['concluido'] for t in tarefas_mes):
                continue
            for tarefa in tarefas_mes:
                cursor.execute('DELETE FROM obra_checklist WHERE id = ?', (tarefa['id'],))

        # Atualiza/insere registro em medicoes_obra
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('SELECT id FROM medicoes_obra WHERE obra_id = ?', (obra_id,))
        registro = cursor.fetchone()
        # Guarda quantidade anterior (se existir) para detectar alterações
        cursor.execute('SELECT quantidade FROM medicoes_obra WHERE obra_id = ?', (obra_id,))
        prev = cursor.fetchone()
        prev_qtd = int(prev['quantidade']) if prev and prev['quantidade'] is not None else None

        if registro:
            cursor.execute(
                'UPDATE medicoes_obra SET quantidade = ?, data_ultima_alteracao = ?, atualizado_em = ? WHERE obra_id = ?',
                (quantidade, now, now, obra_id)
            )
        else:
            cursor.execute(
                'INSERT INTO medicoes_obra (obra_id, quantidade, data_ultima_alteracao, atualizado_em) VALUES (?, ?, ?, ?)',
                (obra_id, quantidade, now, now)
            )

        # Se a obra estava marcada como concluída (com ou sem pendências) e houve
        # alteração na configuração de medições, limpa o status de conclusão para
        # que o fluxo de confirmações volte a perguntar ao finalizar novas medições.
        cursor.execute('SELECT status_conclusao_obra FROM obras WHERE id = ?', (obra_id,))
        status_row = cursor.fetchone()
        status_atual = (status_row['status_conclusao_obra'] or '').strip() if status_row else ''
        if status_atual and prev_qtd != quantidade:
            cursor.execute(
                "UPDATE obras SET status_conclusao_obra = NULL, data_conclusao = NULL, status = 'Em Andamento' WHERE id = ?",
                (obra_id,)
            )

        conn.commit()
        conn.close()
        return True

    def verificar_todas_medicoes_concluidas(self, obra_id: int) -> bool:
        """Retorna True se todas as tarefas de medição/confirmacao desta obra estiverem concluídas."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as pendentes
            FROM obra_checklist
            WHERE obra_id = ?
              AND (
                descricao LIKE 'MEDIÇÃO %'
                OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %'
              )
              AND concluido = 0
        ''', (obra_id,))
        row = cursor.fetchone()
        conn.close()
        return (row['pendentes'] == 0)

    def registrar_finalizacao_obra(self, obra_id: int, status_conclusao_obra: str) -> bool:
        """Marca a obra como concluída e registra se ficou com ou sem pendências."""
        status_normalizado = (status_conclusao_obra or '').strip().lower()
        if status_normalizado not in {'sem_pendencias', 'com_pendencias'}:
            raise ValueError('Status de conclusão inválido')

        conn = self.get_connection()
        cursor = conn.cursor()
        agora = datetime.datetime.now().strftime('%Y-%m-%d')

        cursor.execute('''
            UPDATE obras
            SET status = 'Concluída',
                status_conclusao_obra = ?,
                data_conclusao = ?
            WHERE id = ?
        ''', (status_normalizado, agora, obra_id))

        conn.commit()
        conn.close()
        return True

    # ========== FASE 3 - GERENCIAMENTO DE VALORES MEDIDOS ========== #
    def registrar_valor_medido(self, tarefa_id: int, valor_medido: float, mes_referencia: str = None) -> bool:
        """Registra um valor medido para uma tarefa de CONFIRMAÇÃO DE MEDIÇÃO (Fase 3 - Financeiro)"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Busca informações da tarefa
            cursor.execute('''
                SELECT obra_id, descricao, mes_referencia FROM obra_checklist
                WHERE id = ?
            ''', (tarefa_id,))
            tarefa = cursor.fetchone()
            
            if not tarefa:
                conn.close()
                return False
            
            obra_id = tarefa['obra_id']
            mes_ref = mes_referencia or (tarefa['mes_referencia'] or '')
            data_medicao = datetime.datetime.now().strftime('%Y-%m-%d')
            
            # Atualiza coluna valor_medido na tabela obra_checklist
            cursor.execute('''
                UPDATE obra_checklist
                SET valor_medido = ?
                WHERE id = ?
            ''', (valor_medido, tarefa_id))
            
            # 1. Apaga a medição anterior dessa tarefa (se existir)
            cursor.execute('DELETE FROM medicoes_valores WHERE tarefa_id = ?', (tarefa_id,))
            
            # 2. Insere o novo valor
            cursor.execute('''
                INSERT INTO medicoes_valores
                (obra_id, tarefa_id, valor_medido, data_medicao, mes_referencia)
                VALUES (?, ?, ?, ?, ?)
            ''', (obra_id, tarefa_id, valor_medido, data_medicao, mes_ref))
                        
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            log_error(e, "database", f"Registrar valor medido - Tarefa: {tarefa_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except:
                    pass
            return False

    def obter_soma_valores_medidos(self, obra_id: int) -> float:
        """Retorna a soma de todos os valores medidos para uma obra (Fase 3 - Financeiro)"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT COALESCE(SUM(valor_medido), 0) as total
                FROM medicoes_valores
                WHERE obra_id = ?
            ''', (obra_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            return float(result['total']) if result else 0.0
            
        except Exception as e:
            log_error(e, "database", f"Obter soma valores medidos - Obra: {obra_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except:
                    pass
            return 0.0

    def calcular_percentual_faturado(self, obra_id: int) -> float:
        """Calcula o percentual faturado da obra (Fase 3 - Financeiro)"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Busca total_obra
            cursor.execute('SELECT total_obra FROM obras WHERE id = ?', (obra_id,))
            obra = cursor.fetchone()
            conn.close()
            
            if not obra or not obra['total_obra'] or obra['total_obra'] <= 0:
                return 0.0
            
            total_obra = float(obra['total_obra'])
            soma_valores = self.obter_soma_valores_medidos(obra_id)
            
            percentual = (soma_valores / total_obra) * 100
            return round(percentual, 2)
            
        except Exception as e:
            log_error(e, "database", f"Calcular percentual faturado - Obra: {obra_id}")
            return 0.0

    def calcular_total_faturar(self, obra_id: int) -> float:
        """Calcula o total a faturar da obra (Fase 3 - Financeiro)"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Busca total_obra
            cursor.execute('SELECT total_obra FROM obras WHERE id = ?', (obra_id,))
            obra = cursor.fetchone()
            conn.close()
            
            if not obra or not obra['total_obra']:
                return 0.0
            
            total_obra = float(obra['total_obra'])
            soma_valores = self.obter_soma_valores_medidos(obra_id)

            return round(total_obra - soma_valores, 2)
            
        except Exception as e:
            log_error(e, "database", f"Calcular total a faturar - Obra: {obra_id}")
            return 0.0

    def obter_valores_medicoes(self, obra_id: int) -> List[Dict]:
        """Retorna todos os valores medidos de uma obra com detalhes (Fase 3 - Financeiro)"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    mv.id,
                    mv.tarefa_id,
                    mv.valor_medido,
                    mv.data_medicao,
                    mv.mes_referencia,
                    oc.descricao as tarefa_descricao,
                    oc.data_conclusao
                FROM medicoes_valores mv
                LEFT JOIN obra_checklist oc ON mv.tarefa_id = oc.id
                WHERE mv.obra_id = ?
                ORDER BY mv.mes_referencia DESC, mv.data_medicao DESC
            ''', (obra_id,))
            
            medicoes = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return medicoes
            
        except Exception as e:
            log_error(e, "database", f"Obter valores medições - Obra: {obra_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except:
                    pass
            return []
