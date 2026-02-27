"""
Módulo de sistema de notificações automáticas de prazos.
Responsável por verificar prazos e enviar alertas por email conforme regras de negócio.
"""

import threading
import time
import datetime
import sqlite3
from typing import Dict
from error_logger import log_error

# Flag global para controlar se o notificador já está executando
_notificador_ativo = False
_notificador_lock = threading.Lock()

class NotificadorPrazos:
    def __init__(self, database: 'Database', email_service: 'EmailService', gerador_recorrentes: 'GeradorTarefasRecorrentes'):
        self.database = database
        self.email_service = email_service
        self.gerador_recorrentes = gerador_recorrentes
        self.executando = False
    
    def iniciar_verificacao(self):
        """Inicia thread de verificação periódica de prazos (singleton global)"""
        global _notificador_ativo
        
        with _notificador_lock:
            if _notificador_ativo:
                # Já existe um notificador ativo, não inicia outro
                return
            
            _notificador_ativo = True
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
        """Verifica tarefas atrasadas e envia alertas agrupados por obra. Retorna total de alertas enviados."""
        # Retry mechanism para lidar com database locked
        max_tentativas = 3
        for tentativa in range(max_tentativas):
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
                
                # Dicionário para agrupar alertas por obra
                # Estrutura: {obra_id: {'info': {...}, 'tarefas': {tipo_alerta: [tarefa_data, ...]}}}
                alertas_por_obra = {}
                
                for tarefa in tarefas:
                    data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d').date()
                    dias_diff = (hoje - data_limite).days if isinstance(hoje, datetime.date) else (datetime.datetime.strptime(hoje, '%Y-%m-%d').date() - data_limite).days
                    
                    try:
                        # Processa tarefa e obtém dados de alerta (se aplicável)
                        if tarefa['tipo'] == 'A':
                            # Tipo A: Com reiterações (dias 2, 4, 6, depois diário)
                            alerta_data = self._processar_tipo_a(cursor, tarefa, dias_diff)
                        else:
                            # Tipo B: Prazo fixo (último dia crítico, depois diário)
                            alerta_data = self._processar_tipo_b(cursor, tarefa, dias_diff)
                        
                        # Se deve enviar alerta, adiciona ao agrupamento por obra
                        if alerta_data:
                            obra_id = tarefa['obra_id']
                            
                            # Inicializa estrutura da obra se não existir
                            if obra_id not in alertas_por_obra:
                                alertas_por_obra[obra_id] = {
                                    'info': {
                                        'nome_contrato': tarefa['nome_contrato'],
                                        'cliente': tarefa['cliente']
                                    },
                                    'tarefas': {
                                        'reiteracao_1': [],
                                        'reiteracao_2': [],
                                        'reiteracao_3': [],
                                        'critico_atrasado': [],
                                        'tipo_b': []
                                    }
                                }
                            
                            # Adiciona tarefa no tipo de alerta correspondente
                            tipo_alerta = alerta_data['tipo_alerta']
                            alertas_por_obra[obra_id]['tarefas'][tipo_alerta].append(alerta_data)
                            
                    except Exception as e:
                        print(f"⚠️ Erro ao processar tarefa {tarefa['id']}: {e}")
                        continue
                
                # Envia emails agrupados por obra
                total_emails_enviados = 0
                for obra_id, dados_obra in alertas_por_obra.items():
                    if self._enviar_email_agrupado_por_obra(obra_id, dados_obra):
                        total_emails_enviados += 1
                
                if total_emails_enviados > 0:
                    total_tarefas = sum(
                        len(tarefas) 
                        for obra in alertas_por_obra.values() 
                        for tarefas in obra['tarefas'].values()
                    )
                    print(f"\n📧 {total_emails_enviados} email(s) enviado(s) para {total_tarefas} tarefa(s)\n")
                    obras_com_emails = [dados['info']['nome_contrato'] for obra_id, dados in alertas_por_obra.items() if any(dados['tarefas'].values())]
                    
                    print(f"Obra(s) com e-mails enviados:")
                    for nome in obras_com_emails:
                        print(f"   - {nome}\n")

                return total_tarefas if alertas_por_obra else 0

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    if tentativa < max_tentativas - 1:
                        print(f"⚠️ Banco de dados temporariamente bloqueado, tentando novamente em 5 segundos... (tentativa {tentativa + 1}/{max_tentativas})")
                        time.sleep(5)
                        continue
                    else:
                        print(f"❌ Banco de dados permanece bloqueado após {max_tentativas} tentativas")
                        return 0
                else:
                    raise
            finally:
                if conn:
                    conn.close()
        
        return 0
    
    def _processar_tipo_a(self, cursor, tarefa: Dict, dias_diff: int):
        """Processa notificação para tarefa Tipo A (com reiterações)
        
        Returns:
            Dict com dados do alerta se deve enviar, None caso contrário
        """
        tentativas = tarefa['tentativas_reiteracao']
        ultima_notif = tarefa['ultima_notificacao']
        tipo_recorrencia = tarefa.get('tipo_recorrencia', 'padrao')
        
        # Se ainda não passou do prazo, não faz nada
        if dias_diff < 0:
            return None
        
        hoje_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        hoje_data_str = datetime.date.today().strftime('%Y-%m-%d')
        hoje_obj = datetime.date.today()
        
        # Verifica se já enviou hoje (compara apenas a data)
        if ultima_notif:
            # Extrai apenas a data do campo ultima_notificacao (pode ter hora ou não)
            data_ultima_notif = ultima_notif.split(' ')[0] if ' ' in ultima_notif else ultima_notif
            if data_ultima_notif == hoje_data_str:
                return None
        
        deve_enviar = False
        tipo_alerta = None
        nova_tentativa = tentativas
        
        # Lógica especial para CONFIRMAÇÃO DE MEDIÇÃO (dias do mês 11, 12, 13+)
        if tipo_recorrencia == 'confirmacao':
            dia_mes = hoje_obj.day
            
            # Dia 10: Criação da tarefa (sem alerta)
            # Dia 11: Reiteração 1
            if dia_mes == 11 and tentativas == 0:
                deve_enviar = True
                nova_tentativa = 1
                tipo_alerta = 'reiteracao_1'
            # Dia 12: Reiteração 2
            elif dia_mes == 12 and tentativas <= 1:
                deve_enviar = True
                nova_tentativa = 2
                tipo_alerta = 'reiteracao_2'
            # Dia 13+: Crítico diário
            elif dia_mes >= 13:
                deve_enviar = True
                nova_tentativa = 3
                tipo_alerta = 'critico_atrasado'
        else:
            # Lógica padrão de reiterações: dias 2, 4, 6 após o prazo
            if dias_diff == 2 and tentativas == 0:
                deve_enviar = True
                nova_tentativa = 1
                tipo_alerta = 'reiteracao_1'
            elif dias_diff == 4 and tentativas == 1:
                deve_enviar = True
                nova_tentativa = 2
                tipo_alerta = 'reiteracao_2'
            elif dias_diff == 6 and tentativas == 2:
                deve_enviar = True
                nova_tentativa = 3
                tipo_alerta = 'reiteracao_3'
            elif dias_diff > 6:
                # Após 3ª reiteração: alerta crítico diário
                deve_enviar = True
                tipo_alerta = 'critico_atrasado'
        
        if deve_enviar:
            # Retorna dados do alerta para processamento posterior
            return {
                'tarefa_id': tarefa['id'],
                'obra_id': tarefa['obra_id'],
                'descricao': tarefa['descricao'],
                'data_limite': tarefa['data_limite'],
                'tipo_alerta': tipo_alerta,
                'nova_tentativa': nova_tentativa,
                'dias_diff': dias_diff,
                'hoje_str': hoje_str,
                'status': 'atrasado' if tipo_alerta == 'critico_atrasado' else 'alerta'
            }
        
        return None
    
    def _processar_tipo_b(self, cursor, tarefa: Dict, dias_diff: int):
        """Processa notificação para tarefa Tipo B (prazo fixo)
        
        Returns:
            Dict com dados do alerta se deve enviar, None caso contrário
        """
        ultima_notif = tarefa['ultima_notificacao']
        hoje_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        hoje_data_str = datetime.date.today().strftime('%Y-%m-%d')
        
        # Verifica se já enviou hoje (compara apenas a data)
        if ultima_notif:
            # Extrai apenas a data do campo ultima_notificacao (pode ter hora ou não)
            data_ultima_notif = ultima_notif.split(' ')[0] if ' ' in ultima_notif else ultima_notif
            if data_ultima_notif == hoje_data_str:
                return None
        
        deve_enviar = False
        tipo_alerta = None
        
        if dias_diff == 0:
            # Último dia - alerta crítico
            deve_enviar = True
            tipo_alerta = 'tipo_b'
        elif dias_diff > 0:
            # Atrasado - alerta crítico diário  
            deve_enviar = True
            tipo_alerta = 'tipo_b'
        
        if deve_enviar:
            # Retorna dados do alerta para processamento posterior
            return {
                'tarefa_id': tarefa['id'],
                'obra_id': tarefa['obra_id'],
                'descricao': tarefa['descricao'],
                'data_limite': tarefa['data_limite'],
                'tipo_alerta': tipo_alerta,
                'dias_diff': dias_diff,
                'hoje_str': hoje_str,
                'status': 'critico' if dias_diff == 0 else 'atrasado'
            }
        
        return None
    
    def _enviar_email_agrupado_por_obra(self, obra_id: int, dados_obra: Dict) -> bool:
        """Envia email agrupado com todas as tarefas de uma obra e atualiza banco
        
        Args:
            obra_id: ID da obra
            dados_obra: Dict com 'info' (nome_contrato, cliente) e 'tarefas' (agrupadas por tipo)
        
        Returns:
            True se enviou com sucesso, False caso contrário
        """
        obra_info = dados_obra['info']
        tarefas_agrupadas = dados_obra['tarefas']
        
        # Filtra apenas tipos que têm tarefas
        tarefas_com_conteudo = {
            tipo: tarefas 
            for tipo, tarefas in tarefas_agrupadas.items() 
            if len(tarefas) > 0
        }
        
        if not tarefas_com_conteudo:
            return False
        
        # Gera email agrupado
        try:
            assunto, corpo_html = self.email_service.criar_email_agrupado_por_obra(
                obra_info, 
                tarefas_com_conteudo
            )
            
            # Envia email
            destinatario = self.email_service.config.email_destinatarios
            sucesso, msg = self.email_service.enviar_email(destinatario, assunto, corpo_html)
            
            if not sucesso:
                print(f"❌ Falha ao enviar email para obra {obra_info['nome_contrato']}: {msg}")
                return False
            
            # Atualiza banco para todas as tarefas
            for tipo_alerta, lista_tarefas in tarefas_com_conteudo.items():
                for tarefa_data in lista_tarefas:
                    tarefa_id = tarefa_data['tarefa_id']
                    
                    # Atualiza campos de controle da tarefa
                    if 'nova_tentativa' in tarefa_data:
                        # Tipo A (com reiterações)
                        self._atualizar_tarefa_com_retry(
                            tarefa_id,
                            tarefa_data['nova_tentativa'],
                            tarefa_data['hoje_str'],
                            tarefa_data['status']
                        )
                    else:
                        # Tipo B (sem reiterações)
                        self._atualizar_tarefa_tipo_b_com_retry(
                            tarefa_id,
                            tarefa_data['hoje_str'],
                            tarefa_data['status']
                        )
                    
                    # Registra histórico individual para cada tarefa
                    self._registrar_historico_com_retry(
                        obra_id,
                        tarefa_id,
                        tipo_alerta,
                        destinatario,
                        sucesso,
                        None if sucesso else msg
                    )
            
            # Log de sucesso
            total_tarefas = sum(len(tarefas) for tarefas in tarefas_com_conteudo.values())
            print(f"📧 Email agrupado enviado: {obra_info['nome_contrato']} ({total_tarefas} tarefa(s))")
            return True
            
        except Exception as e:
            print(f"❌ Erro ao enviar email agrupado para obra {obra_info['nome_contrato']}: {e}")
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
    
    def _atualizar_tarefa_com_retry(self, tarefa_id: int, tentativas: int, ultima_notif: str, status: str, max_tentativas: int = 5):
        """Atualiza tarefa com retry em caso de database locked"""
        for tentativa in range(max_tentativas):
            conn = None
            try:
                conn = self.database.get_connection()
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET tentativas_reiteracao = ?, ultima_notificacao = ?, status_notificacao = ?
                    WHERE id = ?
                ''', (tentativas, ultima_notif, status, tarefa_id))
                
                conn.commit()
                conn.close()
                return True
                
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    if conn:
                        try:
                            conn.close()
                        except Exception as e_close:
                            log_error(e_close, "notificador_prazos", "Fechar conexão após database locked em _atualizar_tarefa_com_retry")
                            pass
                    if tentativa < max_tentativas - 1:
                        time.sleep(0.5)  # Aguarda 500ms antes de tentar novamente
                        continue
                    else:
                        print(f"❌ Falha ao atualizar tarefa {tarefa_id} após {max_tentativas} tentativas")
                        return False
                else:
                    raise
            except Exception as e:
                log_error(e, "notificador_prazos", f"Atualizar tarefa {tarefa_id} com retry")
                print(f"❌ Erro ao atualizar tarefa {tarefa_id}: {e}")
                if conn:
                    try:
                        conn.close()
                    except Exception as e_close:
                        log_error(e_close, "notificador_prazos", "Fechar conexão após erro em _atualizar_tarefa_com_retry")
                        pass
                return False
        return False
    
    def _registrar_historico_com_retry(self, obra_id: int, tarefa_id: int, tipo: str, destinatarios: str, sucesso: bool, erro: str = None, max_tentativas: int = 5):
        """Registra histórico com retry em caso de database locked"""
        for tentativa in range(max_tentativas):
            conn = None
            try:
                conn = self.database.get_connection()
                cursor = conn.cursor()
                
                data_envio = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Converte a lista de destinatários em string para armazenamento (se for lista)
                if isinstance(destinatarios, list):
                    destinatarios_str = ", ".join(destinatarios)

                cursor.execute('''
                    INSERT INTO historico_notificacoes 
                    (obra_id, tarefa_id, tipo_notificacao, data_envio, destinatarios, sucesso, mensagem_erro)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (obra_id, tarefa_id, tipo, data_envio, destinatarios_str, 1 if sucesso else 0, erro))
                
                conn.commit()
                conn.close()
                return True
                
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    if conn:
                        try:
                            conn.close()
                        except Exception as e_close:
                            log_error(e_close, "notificador_prazos", "Fechar conexão após database locked em _registrar_historico_com_retry")
                            pass
                    if tentativa < max_tentativas - 1:
                        time.sleep(0.5)  # Aguarda 500ms antes de tentar novamente
                        continue
                    else:
                        print(f"❌ Falha ao registrar histórico após {max_tentativas} tentativas")
                        return False
                else:
                    raise
            except Exception as e:
                log_error(e, "notificador_prazos", "Registrar histórico com retry")
                print(f"❌ Erro ao registrar histórico: {e}")
                if conn:
                    try:
                        conn.close()
                    except Exception as e_close:
                        log_error(e_close, "notificador_prazos", "Fechar conexão após erro em _registrar_historico_com_retry")
                        pass
                return False
        return False
    
    def _atualizar_tarefa_tipo_b_com_retry(self, tarefa_id: int, ultima_notif: str, status: str, max_tentativas: int = 5):
        """Atualiza tarefa tipo B com retry em caso de database locked"""
        for tentativa in range(max_tentativas):
            conn = None
            try:
                conn = self.database.get_connection()
                cursor = conn.cursor()
                
                cursor.execute('''
                    UPDATE obra_checklist 
                    SET ultima_notificacao = ?, status_notificacao = ?
                    WHERE id = ?
                ''', (ultima_notif, status, tarefa_id))
                
                conn.commit()
                conn.close()
                return True
                
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    if conn:
                        try:
                            conn.close()
                        except Exception as e_close:
                            log_error(e_close, "notificador_prazos", "Fechar conexão após database locked em _atualizar_tarefa_tipo_b_com_retry")
                            pass
                    if tentativa < max_tentativas - 1:
                        time.sleep(0.5)  # Aguarda 500ms antes de tentar novamente
                        continue
                    else:
                        print(f"❌ Falha ao atualizar tarefa tipo B {tarefa_id} após {max_tentativas} tentativas")
                        return False
                else:
                    raise
            except Exception as e:
                log_error(e, "notificador_prazos", f"Atualizar tarefa tipo B {tarefa_id} com retry")
                print(f"❌ Erro ao atualizar tarefa tipo B {tarefa_id}: {e}")
                if conn:
                    try:
                        conn.close()
                    except Exception as e_close:
                        log_error(e_close, "notificador_prazos", "Fechar conexão após erro em _atualizar_tarefa_tipo_b_com_retry")
                        pass
                return False
        return False
