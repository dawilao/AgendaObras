"""
Módulo de serviço de envio de emails via SMTP para o sistema AgendaObras.
Responsável pelo envio de notificações e alertas de prazos.
"""

import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Tuple, Dict, List
from error_logger import log_error
from config import (
    EmailConfig, 
    TEMPLATE_EMAIL_ALERTA_A, 
    TEMPLATE_EMAIL_ALERTA_B, 
    TEMPLATE_EMAIL_CRITICO_ATRASADO,
    TEMPLATE_EMAIL_AGRUPADO_POR_OBRA,
    SECAO_REITERACAO,
    SECAO_CRITICO_ATRASADO,
    SECAO_TIPO_B
)


class EmailService:
    """Serviço para envio de emails via SMTP"""
    
    def __init__(self, database: 'Database'):
        self.database = database
        self.config = EmailConfig.carregar()
    
    def recarregar_config(self):
        """Recarrega configuração de email"""
        self.config = EmailConfig.carregar()
    
    def enviar_email(self, destinatario: str, assunto: str, corpo_html: str) -> Tuple[bool, str]:
        """Envia email via SMTP"""
        if not self.config.is_configured():
            return (False, "Configuração SMTP não encontrada. Configure em ⚙️ Configurações.")
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = assunto
            msg['From'] = self.config.email_remetente
            msg['To'] = destinatario
            
            html_part = MIMEText(corpo_html, 'html', 'utf-8')
            msg.attach(html_part)
            
            # Conecta ao servidor SMTP
            if self.config.usar_tls:
                server = smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=30)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.config.smtp_server, self.config.smtp_port, timeout=30)
            
            server.login(self.config.smtp_user, self.config.smtp_password)
            server.send_message(msg)
            server.quit()
            
            print(f"✅ Email enviado com sucesso para {destinatario}")
            return (True, "Email enviado com sucesso")
            
        except smtplib.SMTPAuthenticationError as e:
            erro = "Falha na autenticação SMTP. Verifique usuário e senha."
            log_error(e, "email_service", f"Autenticação SMTP para {destinatario}")
            print(f"❌ {erro}")
            return (False, erro)
        except smtplib.SMTPException as e:
            erro = f"Erro SMTP: {str(e)}"
            log_error(e, "email_service", f"Envio de email SMTP para {destinatario}")
            print(f"❌ {erro}")
            return (False, erro)
        except Exception as e:
            erro = f"Erro ao enviar email: {str(e)}"
            log_error(e, "email_service", f"Enviar email para {destinatario} - assunto: {assunto}")
            print(f"❌ {erro}")
            return (False, erro)
    
    def testar_conexao(self) -> Tuple[bool, str]:
        """Testa conexão SMTP sem enviar email"""
        if not self.config.is_configured():
            return (False, "Configuração incompleta")
        
        try:
            if self.config.usar_tls:
                server = smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=10)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.config.smtp_server, self.config.smtp_port, timeout=10)
            
            server.login(self.config.smtp_user, self.config.smtp_password)
            server.quit()
            return (True, "Conexão SMTP bem-sucedida!")
        except Exception as e:
            log_error(e, "email_service", "Teste de conexão SMTP")
            return (False, f"Erro: {str(e)}")
    
    def criar_email_alerta_tipo_a(self, tarefa: Dict, reiteracao: int) -> str:
        """Cria HTML de email para tarefa Tipo A (com reiteração)"""
        data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
        prazo_formatado = data_limite.strftime('%d/%m/%Y')
        
        dias_atraso = (datetime.date.today() - data_limite.date()).days
        
        if reiteracao == 3:
            mensagem_adicional = "<p style='color: #d32f2f; font-weight: bold;'>⚠️ ATENÇÃO: Esta é a última reiteração automática. Após esta, os alertas se tornarão CRÍTICOS e DIÁRIOS.</p>"
        else:
            mensagem_adicional = f"<p>Próxima reiteração em 2 dias caso a tarefa não seja concluída.</p>"
        
        return TEMPLATE_EMAIL_ALERTA_A.format(
            reiteracao=reiteracao,
            nome_contrato=tarefa['nome_contrato'],
            cliente=tarefa['cliente'],
            tarefa=tarefa['descricao'],
            prazo=prazo_formatado,
            dias_atraso=dias_atraso,
            mensagem_adicional=mensagem_adicional,
            data_envio=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        )
    
    def criar_email_alerta_tipo_b(self, tarefa: Dict) -> str:
        """Cria HTML de email para tarefa Tipo B (prazo fixo)"""
        data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
        prazo_formatado = data_limite.strftime('%d/%m/%Y')
        
        hoje = datetime.date.today()
        if data_limite.date() == hoje:
            status = "ÚLTIMO DIA DO PRAZO - HOJE"
        elif data_limite.date() < hoje:
            status = f"ATRASADA - {(hoje - data_limite.date()).days} dias"
        else:
            status = "Dentro do prazo"
        
        return TEMPLATE_EMAIL_ALERTA_B.format(
            nome_contrato=tarefa['nome_contrato'],
            cliente=tarefa['cliente'],
            tarefa=tarefa['descricao'],
            prazo=prazo_formatado,
            status=status,
            data_envio=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        )
    
    def criar_email_critico_atrasado(self, tarefa: Dict, dias_atraso: int) -> str:
        """Cria HTML de email crítico para tarefa atrasada"""
        data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
        prazo_formatado = data_limite.strftime('%d/%m/%Y')
        
        return TEMPLATE_EMAIL_CRITICO_ATRASADO.format(
            nome_contrato=tarefa['nome_contrato'],
            cliente=tarefa['cliente'],
            tarefa=tarefa['descricao'],
            prazo=prazo_formatado,
            dias_atraso=dias_atraso,
            data_envio=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        )
    
    def registrar_envio(self, obra_id: int, tarefa_id: int, tipo_notificacao: str, 
                       destinatarios: str, sucesso: bool, mensagem_erro: str = None):
        """Registra envio de notificação no histórico"""
        conn = self.database.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO historico_notificacoes 
            (obra_id, tarefa_id, tipo_notificacao, data_envio, destinatarios, sucesso, mensagem_erro)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (obra_id, tarefa_id, tipo_notificacao, 
              datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
              destinatarios, 1 if sucesso else 0, mensagem_erro))
        
        conn.commit()
        conn.close()
    
    def criar_email_agrupado_por_obra(self, obra_info: Dict, tarefas_agrupadas: Dict[str, List[Dict]]) -> Tuple[str, str]:
        """Cria HTML de email agrupado por obra com múltiplas tarefas
        
        Args:
            obra_info: Dict com 'nome_contrato' e 'cliente'
            tarefas_agrupadas: Dict com chaves 'reiteracao_1', 'reiteracao_2', 'reiteracao_3', 'critico_atrasado', 'tipo_b'
                               Cada chave contém lista de dicts com dados da tarefa
        
        Returns:
            Tuple (assunto, corpo_html)
        """
        # Conta total de tarefas
        total_tarefas = sum(len(tarefas) for tarefas in tarefas_agrupadas.values())
        
        # Determina se há tarefas críticas para ajustar estilo
        tem_critico = len(tarefas_agrupadas.get('critico_atrasado', [])) > 0 or len(tarefas_agrupadas.get('tipo_b', [])) > 0
        header_class = ' critico' if tem_critico else ''
        resumo_class = ' critico' if tem_critico else ''
        
        # Texto singular/plural
        texto_tarefas = 'tarefa' if total_tarefas == 1 else 'tarefas'
        
        # Gera seções de conteúdo - ORDEM POR CRITICIDADE (mais crítico primeiro)
        secoes_html = []
        
        # 1. MAIS CRÍTICO: Tarefas Críticas Atrasadas
        tarefas_critico = tarefas_agrupadas.get('critico_atrasado', [])
        if tarefas_critico:
            # Ordena por dias de atraso (mais atrasadas primeiro)
            tarefas_critico_ordenadas = sorted(
                tarefas_critico, 
                key=lambda t: (datetime.date.today() - datetime.datetime.strptime(t['data_limite'], '%Y-%m-%d').date()).days,
                reverse=True
            )
            
            linhas = []
            for tarefa in tarefas_critico_ordenadas:
                data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
                prazo_formatado = data_limite.strftime('%d/%m/%Y')
                dias_atraso = (datetime.date.today() - data_limite.date()).days
                
                linha = f"""
                <tr>
                    <td class="tarefa-nome">{tarefa['descricao']}</td>
                    <td class="prazo-data">{prazo_formatado}</td>
                    <td class="center"><span class="badge badge-critico">CRÍTICO</span></td>
                    <td class="center dias-atraso">{dias_atraso}</td>
                </tr>
                """
                linhas.append(linha)
            
            secao = SECAO_CRITICO_ATRASADO.format(
                linhas_tarefas=''.join(linhas),
                contador=len(tarefas_critico_ordenadas)
            )
            secoes_html.append(secao)
        
        # 2. Tarefas Tipo B (Prazo Fixo) - Último dia ou atrasadas
        tarefas_tipo_b = tarefas_agrupadas.get('tipo_b', [])
        if tarefas_tipo_b:
            # Ordena por dias de atraso (mais atrasadas primeiro)
            tarefas_tipo_b_ordenadas = sorted(
                tarefas_tipo_b,
                key=lambda t: (datetime.date.today() - datetime.datetime.strptime(t['data_limite'], '%Y-%m-%d').date()).days,
                reverse=True
            )
            linhas = []
            for tarefa in tarefas_tipo_b_ordenadas:
                data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
                prazo_formatado = data_limite.strftime('%d/%m/%Y')
                
                hoje = datetime.date.today()
                if data_limite.date() == hoje:
                    status = "ÚLTIMO DIA"
                    dias = "HOJE"
                    classe_dias = "dias-atraso"
                elif data_limite.date() < hoje:
                    dias_atraso = (hoje - data_limite.date()).days
                    status = "ATRASADA"
                    dias = f"{dias_atraso} dias"
                    classe_dias = "dias-atraso"
                else:
                    status = "No prazo"
                    dias = "OK"
                    classe_dias = "dias-atraso leve"
                
                linha = f"""
                <tr>
                    <td class="tarefa-nome">{tarefa['descricao']}</td>
                    <td class="prazo-data">{prazo_formatado}</td>
                    <td class="center"><span class="badge badge-tipo-b">{status}</span></td>
                    <td class="center {classe_dias}">{dias}</td>
                </tr>
                """
                linhas.append(linha)
            
            secao = SECAO_TIPO_B.format(
                linhas_tarefas=''.join(linhas),
                contador=len(tarefas_tipo_b_ordenadas)
            )
            secoes_html.append(secao)
        
        # 3. Reiterações - Ordem decrescente (3ª, 2ª, 1ª) para mostrar mais críticas primeiro
        for num_reiteracao in [3, 2, 1]:
            chave = f'reiteracao_{num_reiteracao}'
            tarefas = tarefas_agrupadas.get(chave, [])
            
            if tarefas:
                # Ordena por dias de atraso (mais atrasadas primeiro)
                tarefas_ordenadas = sorted(
                    tarefas,
                    key=lambda t: (datetime.date.today() - datetime.datetime.strptime(t['data_limite'], '%Y-%m-%d').date()).days,
                    reverse=True
                )
                
                linhas = []
                for tarefa in tarefas_ordenadas:
                    data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
                    prazo_formatado = data_limite.strftime('%d/%m/%Y')
                    dias_atraso = (datetime.date.today() - data_limite.date()).days
                    
                    # Classe CSS baseada nos dias de atraso
                    if dias_atraso > 7:
                        classe_dias = "dias-atraso"
                    elif dias_atraso > 3:
                        classe_dias = "dias-atraso medio"
                    else:
                        classe_dias = "dias-atraso leve"
                    
                    linha = f"""
                    <tr>
                        <td class="tarefa-nome">{tarefa['descricao']}</td>
                        <td class="prazo-data">{prazo_formatado}</td>
                        <td class="center"><span class="badge badge-reiteracao-{num_reiteracao}">{num_reiteracao}ª</span></td>
                        <td class="center {classe_dias}">{dias_atraso}</td>
                    </tr>
                    """
                    linhas.append(linha)
                
                # Mensagem especial para 3ª reiteração
                mensagem_rodape = ""
                if num_reiteracao == 3:
                    mensagem_rodape = '<div class="secao-rodape urgente">⚠️ ÚLTIMA REITERAÇÃO: Após esta, os alertas se tornarão CRÍTICOS e DIÁRIOS.</div>'
                
                if num_reiteracao == 1:
                    titulo = "Reiterações - Primeira Notificação"
                elif num_reiteracao == 2:
                    titulo = "Reiterações - Segunda Notificação"
                else:
                    titulo = "Reiterações - Terceira Notificação (ÚLTIMA)"
                
                secao = SECAO_REITERACAO.format(
                    titulo_secao=titulo,
                    linhas_tarefas=''.join(linhas),
                    mensagem_rodape=mensagem_rodape,
                    contador=len(tarefas_ordenadas)
                )
                secoes_html.append(secao)
        
        # Monta HTML final
        corpo_html = TEMPLATE_EMAIL_AGRUPADO_POR_OBRA.format(
            header_class=header_class,
            resumo_class=resumo_class,
            total_tarefas=total_tarefas,
            texto_tarefas=texto_tarefas,
            nome_contrato=obra_info['nome_contrato'],
            cliente=obra_info['cliente'],
            secoes_conteudo=''.join(secoes_html),
            data_envio=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        )
        
        # Gera assunto
        if tem_critico:
            assunto = f"🆘 [CRÍTICO] Obra {obra_info['nome_contrato']} - {total_tarefas} {texto_tarefas} em alerta"
        else:
            assunto = f"⚠️ Obra {obra_info['nome_contrato']} - {total_tarefas} {texto_tarefas} precisam de atenção"
        
        return (assunto, corpo_html)
