"""
Módulo de serviço de envio de emails via SMTP para o sistema AgendaObras.
Responsável pelo envio de notificações e alertas de prazos.
"""

import smtplib
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Tuple, Dict
from config import EmailConfig, TEMPLATE_EMAIL_ALERTA_A, TEMPLATE_EMAIL_ALERTA_B, TEMPLATE_EMAIL_CRITICO_ATRASADO


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
            
        except smtplib.SMTPAuthenticationError:
            erro = "Falha na autenticação SMTP. Verifique usuário e senha."
            print(f"❌ {erro}")
            return (False, erro)
        except smtplib.SMTPException as e:
            erro = f"Erro SMTP: {str(e)}"
            print(f"❌ {erro}")
            return (False, erro)
        except Exception as e:
            erro = f"Erro ao enviar email: {str(e)}"
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
