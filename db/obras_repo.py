"""
Repositório de Obras — CRUD e recálculo de checklist.
Extraído de database.py sem alteração de lógica.
"""

import datetime
import os
from typing import List, Dict, Optional

from core.migrations import run_migrations
from core.error_logger import log_error
from db.connection import BaseRepository, CAMINHO_DB


class ObrasRepository(BaseRepository):

    def __init__(self, db_name: str = CAMINHO_DB):
        super().__init__(db_name)
        self.init_database()
        run_migrations(db_name)

    def init_database(self):
        """Inicializa o banco de dados com as tabelas necessárias"""
        conn = self.get_connection()
        cursor = conn.cursor()

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
                valor_aditivo REAL DEFAULT 0.0,
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

        cursor.execute("PRAGMA table_info(obra_checklist)")
        checklist_cols = [r[1] for r in cursor.fetchall()]
        if 'valor_medido' not in checklist_cols:
            cursor.execute("ALTER TABLE obra_checklist ADD COLUMN valor_medido REAL")

        cursor.execute("PRAGMA table_info(obras)")
        cols = [r[1] for r in cursor.fetchall()]
        if 'status_conclusao_obra' not in cols:
            cursor.execute("ALTER TABLE obras ADD COLUMN status_conclusao_obra TEXT DEFAULT NULL")

        cursor.execute('SELECT COUNT(*) as count FROM checklist_templates')
        if cursor.fetchone()['count'] == 0:
            templates = [
                ('RETORNO PROJETO E ORÇAMENTO', 1, 2, 'A', 'criacao', None, 0, 'unica', None, None, 1),
                ('ANÁLISE', 2, 3, 'B', 'fim_tarefa', 1, 0, 'unica', None, None, 0),
                ('ANÁLISE - GESTOR', 3, 2, 'B', 'fim_tarefa', 2, 0, 'unica', None, None, 0),
                ('RETORNO DO QUESTIONAMENTO', 4, 2, 'A', 'fim_tarefa', 3, 0, 'unica', None, None, 1),
                ('CONTRATO ASSINADO', 5, 5, 'B', 'fim_tarefa', 3, 0, 'unica', None, 'data_assinatura', 0),
                ('SOLICITAR A DATA DA AIO', 6, 1, 'A', 'assinatura', None, 0, 'unica', None, 'data_aio', 1),
                ('PEDIDO MATERIAL ABC', 7, 8, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('ART', 8, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('SOLICITAÇÃO SEGUROS', 9, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('ACEITE SEGURO', 10, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('PAGAMENTO SEGURO', 11, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('ENVIO DO SEGURO + ART', 12, 5, 'B', 'assinatura', None, 0, 'unica', None, None, 0),
                ('CRONOGRAMA DE OBRA', 13, 0, 'B', 'aio', None, 0, 'unica', None, None, 0),
                ('RELATÓRIO', 14, 5, 'B', 'aio', None, 0, 'unica', None, None, 0),
                ('CONTRATAÇÃO DA EQUIPE', 15, -15, 'B', 'inicio', None, 0, 'unica', None, None, 0),
                ('SOLICITAÇÃO DE ACESSO', 16, -10, 'B', 'inicio', None, 0, 'unica', None, None, 0),
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
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            nome_contrato = (nome_contrato or '').strip()
            cliente = (cliente or '').strip()

            contrato_ic = kwargs.get('contrato_ic', None) or None
            pedido_sap = kwargs.get('pedido_sap', None) or None
            prefixo_agencia = kwargs.get('prefixo_agencia', None) or None
            servico = kwargs.get('servico', None) or None
            valor_parceiro = kwargs.get('valor_parceiro', None) or None
            valor_percentual = kwargs.get('valor_percentual', None) or None
            valor_aditivo = kwargs.get('valor_aditivo', None)
            total_obra = kwargs.get('total_obra', None) or None
            mes_execucao = kwargs.get('mes_execucao', None) or None
            ano_execucao = kwargs.get('ano_execucao', None)
            data_conclusao = kwargs.get('data_conclusao', None) or None
            data_assinatura = kwargs.get('data_assinatura', None) or None
            data_aio = kwargs.get('data_aio', None) or None
            data_acionamento = kwargs.get('data_acionamento', None) or None

            valor_contrato = round(float(valor_contrato), 2)
            valor_parceiro = round(float(valor_parceiro), 2) if valor_parceiro is not None else None
            valor_percentual = round(float(valor_percentual), 2) if valor_percentual is not None else None
            valor_aditivo = round(float(valor_aditivo), 2) if valor_aditivo is not None else 0.0
            total_obra = round(float(total_obra), 2) if total_obra is not None else None

            data_inicio = data_inicio or None
            data_criacao = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            cursor.execute('''
                INSERT INTO obras (nome_contrato, cliente, valor_contrato, data_inicio, status,
                                 contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual,
                                 valor_aditivo, total_obra, mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio,
                                 data_acionamento, data_criacao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (nome_contrato, cliente, valor_contrato, data_inicio, status,
                  contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual,
                  valor_aditivo, total_obra, mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio,
                  data_acionamento, data_criacao))

            obra_id = cursor.lastrowid

            obra_dados = {
                'data_inicio': data_inicio,
                'data_assinatura': data_assinatura,
                'data_aio': data_aio,
                'data_acionamento': data_acionamento,
            }

            self._criar_checklist_obra(cursor, obra_id, obra_dados)

            conn.commit()
            conn.close()
            return obra_id

        except Exception as e:
            log_error(e, "db.obras_repo", f"Criar obra: {nome_contrato}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            raise

    def listar_obras(self, filtro: str = None) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        if filtro:
            cursor.execute('''
                SELECT * FROM obras
                WHERE nome_contrato LIKE ? OR cliente LIKE ? OR status LIKE ?
                ORDER BY data_inicio DESC
            ''', (f'%{filtro}%', f'%{filtro}%', f'%{filtro}%'))
        else:
            cursor.execute('SELECT * FROM obras ORDER BY data_inicio DESC')
        obras = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return obras

    def listar_obras_por_contratos(self, contratos_permitidos: List[str], filtro: str = None) -> List[Dict]:
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
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM obras WHERE id = ?', (obra_id,))
        obra = cursor.fetchone()
        conn.close()
        return dict(obra) if obra else None

    def atualizar_obra(self, obra_id: int, nome_contrato: str, cliente: str,
                       valor_contrato: float, data_inicio: str, status: str, **kwargs) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            nome_contrato = (nome_contrato or '').strip()
            cliente = (cliente or '').strip()

            cursor.execute('SELECT data_inicio, data_assinatura, data_aio, data_acionamento FROM obras WHERE id = ?', (obra_id,))
            obra_antiga = cursor.fetchone()

            contrato_ic = kwargs.get('contrato_ic', None) or None
            pedido_sap = kwargs.get('pedido_sap', None) or None
            prefixo_agencia = kwargs.get('prefixo_agencia', None) or None
            servico = kwargs.get('servico', None) or None
            valor_parceiro = kwargs.get('valor_parceiro', None) or None
            valor_percentual = kwargs.get('valor_percentual', None) or None
            valor_aditivo = kwargs.get('valor_aditivo', None)
            total_obra = kwargs.get('total_obra', None) or None
            mes_execucao = kwargs.get('mes_execucao', None) or None
            ano_execucao = kwargs.get('ano_execucao', None)
            data_conclusao = kwargs.get('data_conclusao', None) or None
            data_assinatura = kwargs.get('data_assinatura', None) or None
            data_aio = kwargs.get('data_aio', None) or None
            data_acionamento = kwargs.get('data_acionamento', None) or None

            valor_contrato = round(float(valor_contrato), 2)
            valor_parceiro = round(float(valor_parceiro), 2) if valor_parceiro is not None else None
            valor_percentual = round(float(valor_percentual), 2) if valor_percentual is not None else None
            valor_aditivo = round(float(valor_aditivo), 2) if valor_aditivo is not None else 0.0
            total_obra = round(float(total_obra), 2) if total_obra is not None else None

            data_inicio = data_inicio or None

            cursor.execute('''
                UPDATE obras
                SET nome_contrato = ?, cliente = ?, valor_contrato = ?,
                    data_inicio = ?, status = ?, contrato_ic = ?, pedido_sap = ?, prefixo_agencia = ?,
                    servico = ?, valor_parceiro = ?, valor_percentual = ?, valor_aditivo = ?, total_obra = ?,
                    mes_execucao = ?, ano_execucao = ?, data_conclusao = ?,
                    data_assinatura = ?, data_aio = ?, data_acionamento = ?
                WHERE id = ?
            ''', (nome_contrato, cliente, valor_contrato, data_inicio, status,
                  contrato_ic, pedido_sap, prefixo_agencia, servico, valor_parceiro, valor_percentual, valor_aditivo, total_obra,
                  mes_execucao, ano_execucao, data_conclusao, data_assinatura, data_aio, data_acionamento, obra_id))

            requer_confirmacao = False
            if obra_antiga:
                if obra_antiga['data_inicio'] != data_inicio:
                    cursor.execute('''
                        SELECT COUNT(*) as count FROM obra_checklist
                        WHERE obra_id = ? AND base_calculo = 'inicio'
                    ''', (obra_id,))
                    if cursor.fetchone()['count'] > 0:
                        requer_confirmacao = True

                if obra_antiga['data_acionamento'] != data_acionamento:
                    cursor.execute('''
                        SELECT COUNT(*) as count FROM obra_checklist
                        WHERE obra_id = ? AND base_calculo = 'criacao'
                    ''', (obra_id,))
                    if cursor.fetchone()['count'] > 0:
                        requer_confirmacao = True

                if obra_antiga['data_assinatura'] != data_assinatura or obra_antiga['data_aio'] != data_aio:
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
            log_error(e, "db.obras_repo", f"Atualizar obra - ID: {obra_id}, Nome: {nome_contrato}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            raise

    def deletar_obra(self, obra_id: int):
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM obra_checklist WHERE obra_id = ?', (obra_id,))
            cursor.execute('DELETE FROM obras WHERE id = ?', (obra_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            log_error(e, "db.obras_repo", f"Deletar obra - ID: {obra_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            raise

    def recalcular_checklist(self, obra_id: int, campo_atualizado: str, nova_data: str):
        conn = self.get_connection()
        cursor = conn.cursor()

        base_calculo_map = {
            'data_assinatura': 'assinatura',
            'data_aio': 'aio',
            'data_inicio': 'inicio',
            'data_acionamento': 'criacao',
        }

        base_calculo = base_calculo_map.get(campo_atualizado)
        if not base_calculo:
            conn.close()
            return

        if not nova_data or not nova_data.strip():
            print(f"\n🔒 Data {campo_atualizado} removida. Bloqueando tarefas relacionadas...")
            cursor.execute('''
                UPDATE obra_checklist
                SET bloqueado = 1, data_limite = NULL, data_base_calculo = NULL
                WHERE obra_id = ? AND base_calculo = ? AND concluido = 0
            ''', (obra_id, base_calculo))

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

        cursor.execute('SELECT descricao, base_calculo, concluido, bloqueado, data_limite, recorrencia FROM obra_checklist WHERE obra_id = ?', (obra_id,))
        todas = cursor.fetchall()
        print(f"   === DEBUG: TODAS as tarefas da obra ===")
        for t in todas:
            print(f"   - {t['descricao']}: base={t['base_calculo']}, concluido={t['concluido']}, bloqueado={t['bloqueado']}, limite={t['data_limite']}, recorrencia={t['recorrencia']}")
        print(f"   =====================================")

        if campo_atualizado == 'data_inicio':
            hoje = datetime.date.today()
            data_inicio_obj = datetime.datetime.strptime(nova_data, '%Y-%m-%d').date()
            if data_inicio_obj <= hoje:
                cursor.execute('''
                    UPDATE obra_checklist
                    SET bloqueado = 0
                    WHERE obra_id = ? AND recorrencia = 'mensal' AND bloqueado = 1
                ''', (obra_id,))
                rows_updated = cursor.rowcount
                if rows_updated > 0:
                    print(f"   ✅ Desbloqueadas {rows_updated} tarefa(s) mensal(is)")
            else:
                cursor.execute('''
                    UPDATE obra_checklist
                    SET bloqueado = 1
                    WHERE obra_id = ? AND recorrencia = 'mensal' AND concluido = 0
                ''', (obra_id,))
                rows_updated = cursor.rowcount
                if rows_updated > 0:
                    print(f"   🔒 Bloqueadas {rows_updated} tarefa(s) mensal(is)")

        cursor.execute('''
            SELECT * FROM obra_checklist
            WHERE obra_id = ? AND base_calculo = ? AND concluido = 0
        ''', (obra_id, base_calculo))

        tarefas = cursor.fetchall()
        print(f"   Tarefas encontradas para recálculo: {len(tarefas)}")

        tarefas_atualizadas = 0
        for tarefa in tarefas:
            data_obj = datetime.datetime.strptime(nova_data, '%Y-%m-%d')
            prazo_dias = tarefa['prazo_dias']
            nova_data_limite = data_obj + datetime.timedelta(days=prazo_dias)

            print(f"   📝 {tarefa['descricao']}: prazo={prazo_dias} dias, antiga={tarefa['data_limite']}, nova={nova_data_limite.strftime('%d/%m/%Y')}")

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

    def atualizar_data_critica(self, obra_id: int, campo: str, data: str):
        if campo not in ('data_assinatura', 'data_aio'):
            raise ValueError(f"Campo de data crítica inválido: {campo}")
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(f'UPDATE obras SET {campo} = ? WHERE id = ?', (data or None, obra_id))
        conn.commit()
        conn.close()

    def atualizar_observacoes_obra(self, obra_id: int, observacoes: Optional[str],
                                   obs_usuario: Optional[str], obs_data: Optional[str]) -> bool:
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
            log_error(e, "db.obras_repo", f"Atualizar observações da obra - ID: {obra_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            return False
