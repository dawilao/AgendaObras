"""
Módulo de sistema de notificações automáticas de prazos.
Responsável por verificar prazos e enviar alertas por email conforme regras de negócio.
"""

import threading
import time
import datetime
import sqlite3
from typing import Dict


class NotificadorPrazos:
    def __init__(self, database: 'Database', email_service: 'EmailService', gerador_recorrentes: 'GeradorTarefasRecorrentes'):
        self.database = database
        self.email_service = email_service
        self.gerador_recorrentes = gerador_recorrentes
        self.executando = False
    
    def iniciar_verificacao(self):
        """Inicia thread de verificação periódica de prazos"""
        if not self.executando:
            self.executando = True
            thread = threading.Thread(target=self._verificar_loop, daemon=True)
            thread.start()
            print("🔔 Sistema de notificação de prazos iniciado!")
    
    def verificar_agora(self, forcar: bool = False):
        """Executa verificação manual de prazos
        
        Args:
            forcar: Se True, ignora verificação de última execução e força o envio
        """
        if forcar:
            print("🔄 Verificação manual FORÇADA de prazos...")
            try:
                self.gerador_recorrentes.gerar_tarefas_mensais()
                alertas = self._verificar_prazos()
                self._registrar_execucao(alertas, 'concluida')
                print("✅ Verificação manual concluída!")
                return True
            except Exception as e:
                print(f"❌ Erro na verificação manual: {e}")
                self._registrar_execucao(0, 'erro', str(e))
                return False
        else:
            if self._ja_executou_hoje():
                print("ℹ️ Verificação já foi executada hoje. Use forcar=True para executar de qualquer forma.")
                return False
            else:
                print("🔄 Executando verificação manual de prazos...")
                try:
                    self.gerador_recorrentes.gerar_tarefas_mensais()
                    alertas = self._verificar_prazos()
                    self._registrar_execucao(alertas, 'concluida')
                    print("✅ Verificação manual concluída!")
                    return True
                except Exception as e:
                    print(f"❌ Erro na verificação manual: {e}")
                    self._registrar_execucao(0, 'erro', str(e))
                    return False
    
    def _verificar_loop(self):
        """Loop de verificação (executa a cada 24 horas)"""
        while self.executando:
            # Verifica se já executou hoje
            if self._ja_executou_hoje():
                print("ℹ️  Verificação de prazos já executada hoje. Aguardando próximo ciclo...")
                time.sleep(3600)  # Verifica a cada 1 hora se mudou o dia
                continue
            
            # Gera tarefas mensais recorrentes
            try:
                self.gerador_recorrentes.gerar_tarefas_mensais()
            except Exception as e:
                print(f"❌ Erro ao gerar tarefas recorrentes: {e}")
            
            # Verifica prazos e envia alertas
            try:
                alertas = self._verificar_prazos()
                # Registra que executou hoje
                self._registrar_execucao(alertas, 'concluida')
            except Exception as e:
                print(f"❌ Erro ao verificar prazos: {e}")
                self._registrar_execucao(0, 'erro', str(e))
            
            time.sleep(3600)  # Verifica a cada 1 hora se mudou o dia
    
    def _verificar_prazos(self) -> int:
        """Verifica tarefas atrasadas e envia alertas conforme tipo. Retorna total de alertas enviados."""
        conn = None
        try:
            conn = self.database.get_connection()
            cursor = conn.cursor()
            
            hoje = datetime.date.today().strftime('%Y-%m-%d')
            
            # Busca tarefas não concluídas e não bloqueadas
            cursor.execute('''
                SELECT oc.*, o.nome_contrato, o.cliente, ct.possui_reiteracao, ct.tipo_recorrencia
                FROM obra_checklist oc
                JOIN obras o ON oc.obra_id = o.id 
                LEFT JOIN checklist_templates ct ON oc.template_id = ct.id
                WHERE oc.concluido = 0 AND oc.bloqueado = 0 
                AND oc.data_limite IS NOT NULL
                ORDER BY oc.data_limite
            ''')
            
            tarefas = [dict(row) for row in cursor.fetchall()]
            
            alertas_enviados = 0
            
            for tarefa in tarefas:
                data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d').date()
                dias_diff = (hoje - data_limite).days if isinstance(hoje, datetime.date) else (datetime.datetime.strptime(hoje, '%Y-%m-%d').date() - data_limite).days
                
                if tarefa['tipo'] == 'A':
                    # Tipo A: Com reiterações (dias 2, 4, 6, depois diário)
                    if self._processar_tipo_a(cursor, tarefa, dias_diff):
                        alertas_enviados += 1
                else:
                    # Tipo B: Prazo fixo (último dia crítico, depois diário)
                    if self._processar_tipo_b(cursor, tarefa, dias_diff):
                        alertas_enviados += 1
            
            conn.commit()
            
            if alertas_enviados > 0:
                print(f"\n📧 Total de alertas enviados: {alertas_enviados}\n")
            
            return alertas_enviados
        
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                print(f"⚠️ Banco de dados temporariamente bloqueado, tentando novamente em 5 segundos...")
                time.sleep(5)
            else:
                raise
        finally:
            if conn:
                conn.close()
        
        return 0
    
    def _processar_tipo_a(self, cursor, tarefa: Dict, dias_diff: int) -> bool:
        """Processa notificação para tarefa Tipo A (com reiterações)"""
        tentativas = tarefa['tentativas_reiteracao']
        ultima_notif = tarefa['ultima_notificacao']
        tipo_recorrencia = tarefa.get('tipo_recorrencia', 'padrao')
        
        # Se ainda não passou do prazo, não faz nada
        if dias_diff < 0:
            return False
        
        hoje_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        hoje_data_str = datetime.date.today().strftime('%Y-%m-%d')
        hoje_obj = datetime.date.today()
        
        # Verifica se já enviou hoje (compara apenas a data)
        if ultima_notif:
            # Extrai apenas a data do campo ultima_notificacao (pode ter hora ou não)
            data_ultima_notif = ultima_notif.split(' ')[0] if ' ' in ultima_notif else ultima_notif
            if data_ultima_notif == hoje_data_str:
                return False
        
        deve_enviar = False
        tipo_alerta = None
        
        # Lógica especial para CONFIRMAÇÃO DE MEDIÇÃO (dias do mês 11, 12, 13+)
        if tipo_recorrencia == 'confirmacao':
            dia_mes = hoje_obj.day
            
            # Dia 10: Criação da tarefa (sem alerta)
            # Dia 11: Reiteração 1
            if dia_mes == 11 and tentativas == 0:
                deve_enviar = True
                tentativas = 1
                tipo_alerta = 'reiteracao_1'
            # Dia 12: Reiteração 2
            elif dia_mes == 12 and tentativas <= 1:
                deve_enviar = True
                tentativas = 2
                tipo_alerta = 'reiteracao_2'
            # Dia 13+: Crítico diário
            elif dia_mes >= 13:
                deve_enviar = True
                tentativas = 3
                tipo_alerta = 'critico_atrasado'
        else:
            # Lógica padrão de reiterações: dias 2, 4, 6 após o prazo
            if dias_diff == 2 and tentativas == 0:
                deve_enviar = True
                tentativas = 1
                tipo_alerta = 'reiteracao_1'
            elif dias_diff == 4 and tentativas == 1:
                deve_enviar = True
                tentativas = 2
                tipo_alerta = 'reiteracao_2'
            elif dias_diff == 6 and tentativas == 2:
                deve_enviar = True
                tentativas = 3
                tipo_alerta = 'reiteracao_3'
            elif dias_diff > 6:
                # Após 3ª reiteração: alerta crítico diário
                deve_enviar = True
                tipo_alerta = 'critico_atrasado'
        
        if deve_enviar:
            # Cria email apropriado
            if tipo_alerta.startswith('reiteracao'):
                html = self.email_service.criar_email_alerta_tipo_a(tarefa, tentativas)
                assunto = f"⚠️ AgendaObras - Reiteração {tentativas}: {tarefa['descricao']}"
            else:
                html = self.email_service.criar_email_critico_atrasado(tarefa, dias_diff)
                assunto = f"🆘 CRÍTICO - {tarefa['descricao']} - {dias_diff} dias em atraso"
            
            # TODO: Definir destinatários (pode ser campo na obra ou configuração)
            destinatario = self.email_service.config.email_remetente  # Por enquanto envia para si mesmo
            
            sucesso, msg = self.email_service.enviar_email(destinatario, assunto, html)
            
            # Atualiza banco
            status = 'atrasado' if tipo_alerta == 'critico_atrasado' else 'alerta'
            cursor.execute('''
                UPDATE obra_checklist 
                SET tentativas_reiteracao = ?, ultima_notificacao = ?, status_notificacao = ?
                WHERE id = ?
            ''', (tentativas, hoje_str, status, tarefa['id']))
            
            # Registra histórico
            self.email_service.registrar_envio(
                tarefa['obra_id'], tarefa['id'], tipo_alerta,
                destinatario, sucesso, None if sucesso else msg
            )
            
            print(f"📧 Tipo A - {tipo_alerta}: {tarefa['descricao']} ({tarefa['nome_contrato']})")
            return True
        
        return False
    
    def _processar_tipo_b(self, cursor, tarefa: Dict, dias_diff: int) -> bool:
        """Processa notificação para tarefa Tipo B (prazo fixo)"""
        ultima_notif = tarefa['ultima_notificacao']
        hoje_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        hoje_data_str = datetime.date.today().strftime('%Y-%m-%d')
        
        # Verifica se já enviou hoje (compara apenas a data)
        if ultima_notif:
            # Extrai apenas a data do campo ultima_notificacao (pode ter hora ou não)
            data_ultima_notif = ultima_notif.split(' ')[0] if ' ' in ultima_notif else ultima_notif
            if data_ultima_notif == hoje_data_str:
                return False
        
        deve_enviar = False
        tipo_alerta = None
        
        if dias_diff == 0:
            # Último dia - alerta crítico
            deve_enviar = True
            tipo_alerta = 'critico_ultimo_dia'
        elif dias_diff > 0:
            # Atrasado - alerta crítico diário
            deve_enviar = True
            tipo_alerta = 'critico_atrasado'
        
        if deve_enviar:
            html = self.email_service.criar_email_alerta_tipo_b(tarefa) if dias_diff == 0 else self.email_service.criar_email_critico_atrasado(tarefa, dias_diff)
            
            if dias_diff == 0:
                assunto = f"🚨 ÚLTIMO DIA: {tarefa['descricao']}"
            else:
                assunto = f"🆘 ATRASADO {dias_diff}d: {tarefa['descricao']}"
            
            destinatario = self.email_service.config.email_remetente
            sucesso, msg = self.email_service.enviar_email(destinatario, assunto, html)
            
            # Atualiza banco
            status = 'critico' if dias_diff == 0 else 'atrasado'
            cursor.execute('''
                UPDATE obra_checklist 
                SET ultima_notificacao = ?, status_notificacao = ?
                WHERE id = ?
            ''', (hoje_str, status, tarefa['id']))
            
            self.email_service.registrar_envio(
                tarefa['obra_id'], tarefa['id'], tipo_alerta,
                destinatario, sucesso, None if sucesso else msg
            )
            
            print(f"📧 Tipo B - {tipo_alerta}: {tarefa['descricao']} ({tarefa['nome_contrato']})")
            return True
        
        return False
    
    def _ja_executou_hoje(self) -> bool:
        """Verifica se a verificação de prazos já foi executada hoje"""
        try:
            conn = self.database.get_connection()
            cursor = conn.cursor()
            
            hoje = datetime.date.today().strftime('%Y-%m-%d')
            cursor.execute('''
                SELECT COUNT(*) FROM verificacoes_prazos 
                WHERE data_verificacao = ? AND status = 'concluida'
            ''', (hoje,))
            
            count = cursor.fetchone()[0]
            conn.close()
            
            return count > 0
        except Exception as e:
            print(f"⚠️ Erro ao verificar última execução: {e}")
            return False
    
    def _registrar_execucao(self, alertas_enviados: int = 0, status: str = 'concluida', mensagem_erro: str = None):
        """Registra que a verificação foi executada hoje"""
        try:
            conn = self.database.get_connection()
            cursor = conn.cursor()
            
            hoje = datetime.date.today().strftime('%Y-%m-%d')
            agora = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Conta tarefas verificadas
            cursor.execute('''
                SELECT COUNT(*) FROM obra_checklist 
                WHERE concluido = 0 AND bloqueado = 0 AND data_limite IS NOT NULL
            ''')
            tarefas_verificadas = cursor.fetchone()[0]
            
            # Insere ou atualiza registro
            cursor.execute('''
                INSERT OR REPLACE INTO verificacoes_prazos 
                (data_verificacao, data_hora_inicio, data_hora_fim, tarefas_verificadas, alertas_enviados, status, mensagem_erro)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (hoje, agora, agora, tarefas_verificadas, alertas_enviados, status, mensagem_erro))
            
            conn.commit()
            conn.close()
            
            if status == 'concluida':
                print(f"✅ Verificação de prazos concluída e registrada para {hoje} ({tarefas_verificadas} tarefas verificadas, {alertas_enviados} alertas enviados)")
            else:
                print(f"⚠️ Verificação de prazos registrada com status '{status}' para {hoje}")
        except Exception as e:
            print(f"⚠️ Erro ao registrar execução: {e}")
