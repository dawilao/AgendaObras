"""
Módulo responsável por gerar tarefas mensais recorrentes automaticamente.
Gerencia a criação de tarefas que se repetem mensalmente, como medições.
"""

import sqlite3
import datetime
import calendar
from typing import Dict
from error_logger import log_error


class GeradorTarefasRecorrentes:
    """Gera tarefas mensais recorrentes dinamicamente"""
    
    def __init__(self, database: 'Database'):
        self.database = database
    
    def gerar_tarefas_mensais(self):
        """Verifica e gera tarefas mensais para obras ativas"""
        conn = None
        try:
            conn = self.database.get_connection()
            cursor = conn.cursor()
            
            # Busca obras que já começaram (com data_inicio preenchida e válida)
            hoje = datetime.date.today()
            cursor.execute('''
                SELECT * FROM obras 
                WHERE data_inicio IS NOT NULL AND data_inicio != '' 
                AND data_inicio <= ? AND (data_conclusao IS NULL OR data_conclusao >= ?)
                AND status != 'Concluída'
            ''', (hoje.strftime('%Y-%m-%d'), hoje.strftime('%Y-%m-%d')))
            
            obras_ativas = [dict(row) for row in cursor.fetchall()]
            
            # Busca templates de tarefas recorrentes
            cursor.execute('''
                SELECT * FROM checklist_templates 
                WHERE recorrencia = 'mensal'
            ''')
            templates_mensais = [dict(row) for row in cursor.fetchall()]
            
            for obra in obras_ativas:
                # Desbloqueia tarefas mensais template (se ainda estiverem bloqueadas)
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET bloqueado = 0
                    WHERE obra_id = ? AND recorrencia = 'mensal' AND bloqueado = 1 AND mes_referencia IS NULL
                ''', (obra['id'],))
                
                # Cria instâncias mensais específicas
                for template in templates_mensais:
                    self._verificar_e_criar_mes_atual(cursor, obra, template, hoje)
            
            conn.commit()
            
            print(f"🔄 Gerador de tarefas recorrentes executado: {len(obras_ativas)} obra(s) verificada(s)")
        
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                print(f"⚠️ Banco de dados temporariamente bloqueado ao gerar tarefas recorrentes...")
            else:
                log_error(e, "gerador_tarefas_recorrentes", "Gerar tarefas mensais - OperationalError")
                raise
        except Exception as e:
            log_error(e, "gerador_tarefas_recorrentes", "Gerar tarefas mensais")
            print(f"❌ Erro ao gerar tarefas recorrentes: {e}")
        finally:
            if conn:
                conn.close()
    
    def _verificar_e_criar_mes_atual(self, cursor, obra: Dict, template: Dict, hoje: datetime.date):
        """Verifica se existe tarefa mensal para o mês atual e cria se necessário"""
        mes_ref = hoje.strftime('%Y-%m')
        
        # Verifica se já existe essa tarefa para este mês
        cursor.execute('''
            SELECT id FROM obra_checklist 
            WHERE obra_id = ? AND template_id = ? AND mes_referencia = ?
        ''', (obra['id'], template['id'], mes_ref))
        
        if cursor.fetchone():
            return  # Já existe
        
        # Calcula data limite baseada no dia de referência mensal
        dia_ref = template['dia_referencia_mensal']
        try:
            data_limite = datetime.date(hoje.year, hoje.month, dia_ref)
        except ValueError:
            # Se o dia não existe no mês (ex: 31 em fevereiro), usa último dia do mês
            ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
            data_limite = datetime.date(hoje.year, hoje.month, ultimo_dia)
        
        # Se a data já passou e ainda não criamos, cria mesmo assim (vai estar atrasada)
        # Se ainda não chegou no dia, cria já para aparecer no sistema
        
        # Cria a tarefa mensal - formata mês no padrão brasileiro mm/aaaa
        mes_ref_formatado = hoje.strftime('%m/%Y')
        descricao = f"{template['nome']} - {mes_ref_formatado}"
        
        cursor.execute('''
            INSERT INTO obra_checklist 
            (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, 
             base_calculo, data_base_calculo, bloqueado, recorrencia, mes_referencia,
             status_notificacao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (obra['id'], template['id'], descricao, template['prazo_dias'],
              data_limite.strftime('%Y-%m-%d'), template['tipo'],
              template['base_calculo'], obra['data_inicio'], 0, 
              'mensal', mes_ref, 'pendente'))
        
        print(f"  ✅ Criada tarefa mensal: {descricao} para obra {obra['nome_contrato']}")
