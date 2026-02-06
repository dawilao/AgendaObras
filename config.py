"""
Configurações do Sistema AgendaObras
"""
import json
import os
from typing import Optional, Dict
from dataclasses import dataclass


VERSION = '2.0.0'


@dataclass
class EmailConfig:
    """Configuração de email SMTP"""
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_remetente: str = ""
    usar_tls: bool = True
    
    def is_configured(self) -> bool:
        """Verifica se o email está configurado"""
        return bool(self.smtp_user and self.smtp_password and self.email_remetente)
    
    def to_dict(self) -> Dict:
        """Converte para dicionário"""
        return {
            'smtp_server': self.smtp_server,
            'smtp_port': self.smtp_port,
            'smtp_user': self.smtp_user,
            'smtp_password': self.smtp_password,
            'email_remetente': self.email_remetente,
            'usar_tls': self.usar_tls
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'EmailConfig':
        """Cria instância a partir de dicionário"""
        return cls(
            smtp_server=data.get('smtp_server', 'smtp.gmail.com'),
            smtp_port=data.get('smtp_port', 587),
            smtp_user=data.get('smtp_user', ''),
            smtp_password=data.get('smtp_password', ''),
            email_remetente=data.get('email_remetente', ''),
            usar_tls=data.get('usar_tls', True)
        )


class ConfigManager:
    """Gerenciador de configurações do sistema"""
    
    CONFIG_FILE = "smtp_config.json"
    
    @staticmethod
    def salvar_config_email(config: EmailConfig) -> bool:
        """Salva configuração de email em arquivo JSON"""
        try:
            with open(ConfigManager.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config.to_dict(), f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Erro ao salvar configuração: {e}")
            return False
    
    @staticmethod
    def carregar_config_email() -> EmailConfig:
        """Carrega configuração de email do arquivo JSON"""
        if not os.path.exists(ConfigManager.CONFIG_FILE):
            return EmailConfig()
        
        try:
            with open(ConfigManager.CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return EmailConfig.from_dict(data)
        except Exception as e:
            print(f"Erro ao carregar configuração: {e}")
            return EmailConfig()
    
    @staticmethod
    def limpar_config_email() -> bool:
        """Remove arquivo de configuração"""
        try:
            if os.path.exists(ConfigManager.CONFIG_FILE):
                os.remove(ConfigManager.CONFIG_FILE)
            return True
        except Exception as e:
            print(f"Erro ao limpar configuração: {e}")
            return False


# Templates HTML para emails
TEMPLATE_EMAIL_ALERTA_A = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #ff9800; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
        .content {{ background-color: #fff; padding: 20px; border: 1px solid #ddd; }}
        .footer {{ background-color: #f5f5f5; padding: 15px; text-align: center; font-size: 12px; color: #666; }}
        .alert-box {{ background-color: #fff3cd; border-left: 4px solid #ff9800; padding: 15px; margin: 15px 0; }}
        .info {{ margin: 10px 0; }}
        .info strong {{ color: #1976d2; }}
        .reiteracao {{ background-color: #ffebee; padding: 10px; border-radius: 4px; margin: 10px 0; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🔔 AgendaObras - Alerta de Prazo (Reiteração {reiteracao})</h2>
        </div>
        <div class="content">
            <div class="alert-box">
                <h3>⚠️ Tarefa Pendente - Reiteração {reiteracao}</h3>
                <p>Uma tarefa da obra <strong>{nome_contrato}</strong> está aguardando conclusão.</p>
            </div>
            
            <div class="info">
                <p><strong>Cliente:</strong> {cliente}</p>
                <p><strong>Tarefa:</strong> {tarefa}</p>
                <p><strong>Prazo original:</strong> {prazo}</p>
                <p><strong>Dias desde o prazo:</strong> {dias_atraso} dia(s)</p>
            </div>
            
            <div class="reiteracao">
                <p><strong>Esta é a {reiteracao}ª reiteração.</strong></p>
                {mensagem_adicional}
            </div>
            
            <p>Por favor, tome as providências necessárias para conclusão desta tarefa.</p>
        </div>
        <div class="footer">
            AgendaObras - Sistema de Rastreamento de Obras<br>
            Data/Hora: {data_envio}
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_EMAIL_ALERTA_B = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #f44336; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
        .content {{ background-color: #fff; padding: 20px; border: 1px solid #ddd; }}
        .footer {{ background-color: #f5f5f5; padding: 15px; text-align: center; font-size: 12px; color: #666; }}
        .critical-box {{ background-color: #ffebee; border-left: 4px solid #f44336; padding: 15px; margin: 15px 0; }}
        .info {{ margin: 10px 0; }}
        .info strong {{ color: #1976d2; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🚨 AgendaObras - ALERTA CRÍTICO</h2>
        </div>
        <div class="content">
            <div class="critical-box">
                <h3>🚨 Prazo Crítico</h3>
                <p>Uma tarefa da obra <strong>{nome_contrato}</strong> atingiu o prazo limite.</p>
            </div>
            
            <div class="info">
                <p><strong>Cliente:</strong> {cliente}</p>
                <p><strong>Tarefa:</strong> {tarefa}</p>
                <p><strong>Prazo limite:</strong> {prazo}</p>
                <p><strong>Status:</strong> {status}</p>
            </div>
            
            <p><strong>Ação imediata requerida!</strong></p>
        </div>
        <div class="footer">
            AgendaObras - Sistema de Rastreamento de Obras<br>
            Data/Hora: {data_envio}
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_EMAIL_CRITICO_ATRASADO = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #d32f2f; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
        .content {{ background-color: #fff; padding: 20px; border: 1px solid #ddd; }}
        .footer {{ background-color: #f5f5f5; padding: 15px; text-align: center; font-size: 12px; color: #666; }}
        .critical-box {{ background-color: #ffcdd2; border-left: 4px solid #d32f2f; padding: 15px; margin: 15px 0; }}
        .info {{ margin: 10px 0; }}
        .info strong {{ color: #1976d2; }}
        .atrasado {{ background-color: #b71c1c; color: white; padding: 10px; border-radius: 4px; margin: 10px 0; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🆘 AgendaObras - TAREFA ATRASADA</h2>
        </div>
        <div class="content">
            <div class="critical-box">
                <h3>🆘 Tarefa em Atraso</h3>
                <p>A tarefa da obra <strong>{nome_contrato}</strong> está ATRASADA.</p>
            </div>
            
            <div class="info">
                <p><strong>Cliente:</strong> {cliente}</p>
                <p><strong>Tarefa:</strong> {tarefa}</p>
                <p><strong>Prazo era:</strong> {prazo}</p>
            </div>
            
            <div class="atrasado">
                <h3>⏰ {dias_atraso} DIAS EM ATRASO</h3>
            </div>
            
            <p><strong>URGENTE: Providências imediatas necessárias!</strong></p>
        </div>
        <div class="footer">
            AgendaObras - Sistema de Rastreamento de Obras<br>
            Data/Hora: {data_envio}
        </div>
    </div>
</body>
</html>
"""
