"""
Configurações do Sistema AgendaObras
"""
import json
import os
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from core.error_logger import log_error

# Raiz do projeto (um nível acima de core/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _limpar_valor_env(valor: Optional[str]) -> str:
    if valor is None:
        return ""
    valor_limpo = str(valor).strip()
    if len(valor_limpo) >= 2 and (
        (valor_limpo[0] == '"' and valor_limpo[-1] == '"')
        or (valor_limpo[0] == "'" and valor_limpo[-1] == "'")
    ):
        valor_limpo = valor_limpo[1:-1].strip()
    else:
        valor_limpo = valor_limpo.strip('"').strip("'").strip()
    if valor_limpo.endswith('>') and '<' not in valor_limpo:
        valor_limpo = valor_limpo[:-1].strip()
    return valor_limpo


def _obter_variavel_ambiente(nome: str, padrao: Optional[str] = None) -> str:
    valor = os.getenv(nome)
    if valor is not None and str(valor).strip():
        return _limpar_valor_env(valor)
    return _limpar_valor_env(padrao)


def _parsear_destinatarios_env(valor: Optional[str]) -> List[str]:
    valor_limpo = _limpar_valor_env(valor)
    if not valor_limpo:
        return []
    destinatarios = []
    for item in valor_limpo.split(','):
        email = _limpar_valor_env(item).strip().strip('"').strip("'").strip('<>').strip()
        if email:
            destinatarios.append(email)
    return destinatarios


def _parsear_bool_env(valor: Optional[str], padrao: bool) -> bool:
    valor_limpo = _limpar_valor_env(valor)
    if not valor_limpo:
        return padrao
    return valor_limpo.lower() in ['true', '1', 'yes', 'sim', 'on']


def _esta_em_producao() -> bool:
    ambiente = _obter_variavel_ambiente('AMBIENTE', '').lower()
    if ambiente in ['producao', 'production', 'prod']:
        return True
    deploy_env = _obter_variavel_ambiente('DEPLOY_ENV', '').lower()
    if deploy_env in ['production', 'prod']:
        return True
    if os.path.exists('/etc/production'):
        return True
    try:
        with open('/etc/hostname', 'r') as f:
            hostname = f.read().strip().lower()
            if any(x in hostname for x in ['vps', 'prod', 'server', 'cloud']):
                return True
    except Exception:
        pass
    return False

AMBIENTE_PRODUCAO = _esta_em_producao()

VERSION = '2.0.0'
EMAIL_DISPARO_HORA = 8
EMAIL_DISPARO_MINUTO = 0
EMAIL_DISPARO_TIMEZONE = 'America/Sao_Paulo'
EMAIL_DISPARO_CATCHUP = True
GITHUB_REPO_URL = "https://github.com/dawilao/AgendaObras"
VERSION_JSON_URL = "https://raw.githubusercontent.com/dawilao/AgendaObras/main/version.json"

BIBLIOTECA_PDF_MAX_MB = int(_obter_variavel_ambiente('BIBLIOTECA_PDF_MAX_MB', '5'))


@dataclass
class EmailConfig:
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_remetente: str = ""
    usar_tls: bool = True
    caminhos_alternativos: List[str] = field(default_factory=lambda: [])

    def _buscar_arquivo_env(self, nome_arquivo: str = "email_config.env") -> Optional[str]:
        caminhos = [
            nome_arquivo,
            os.path.join(_PROJECT_ROOT, nome_arquivo),
            os.path.join(r'G:\Meu Drive\17 - MODELOS\PROGRAMAS\AgendaObras\app', nome_arquivo),
            *[os.path.join(caminho, nome_arquivo) for caminho in self.caminhos_alternativos],
        ]
        for caminho in caminhos:
            if os.path.exists(caminho):
                print(f"✓ Arquivo de configuração encontrado: {caminho}")
                return caminho
        return None

    def _carregar_json_env(self, caminho: str) -> Dict:
        try:
            with open(caminho, 'r', encoding='utf-8') as f:
                conteudo = f.read()
        except Exception as e:
            print(f"Erro ao ler arquivo {caminho}: {e}")
            log_error(e, "config", f"Ler arquivo de configuração: {caminho}")
            return {}

        try:
            data_json = json.loads(conteudo)
            if isinstance(data_json, dict):
                return data_json
        except json.JSONDecodeError:
            pass

        data_env: Dict[str, object] = {}
        for linha in conteudo.splitlines():
            linha = linha.strip()
            if not linha or linha.startswith('#') or '=' not in linha:
                continue
            chave, valor = linha.split('=', 1)
            chave = chave.strip().lower()
            valor_limpo = _limpar_valor_env(valor)
            if chave == 'smtp_port':
                try:
                    data_env[chave] = int(valor_limpo)
                except ValueError:
                    data_env[chave] = valor_limpo
            elif chave == 'usar_tls':
                data_env[chave] = _parsear_bool_env(valor_limpo, True)
            elif chave == 'email_destinatarios':
                data_env[chave] = _parsear_destinatarios_env(valor_limpo)
            else:
                data_env[chave] = valor_limpo

        aliases = {
            'SMTP_SERVER': 'smtp_server', 'SMTP_PORT': 'smtp_port',
            'SMTP_USER': 'smtp_user', 'SMTP_PASSWORD': 'smtp_password',
            'EMAIL_REMETENTE': 'email_remetente', 'EMAIL_DESTINATARIOS': 'email_destinatarios',
            'EMAIL_CRITICO': 'email_critico', 'USAR_TLS': 'usar_tls',
        }
        for origem, destino in aliases.items():
            origem_lower = origem.lower()
            if origem_lower in data_env and destino not in data_env:
                data_env[destino] = data_env[origem_lower]
        return data_env

    def config_email(self, caminho_config: Optional[str] = None,
                     caminhos_extras: Optional[List[str]] = None) -> bool:
        if caminhos_extras:
            self.caminhos_alternativos.extend(caminhos_extras)
        arquivo_encontrado = None
        if caminho_config and os.path.exists(caminho_config):
            arquivo_encontrado = caminho_config
        else:
            arquivo_encontrado = self._buscar_arquivo_env()
        if arquivo_encontrado:
            try:
                data = self._carregar_json_env(arquivo_encontrado)
                if data:
                    self.smtp_server = data.get('smtp_server', self.smtp_server)
                    self.smtp_port = data.get('smtp_port', self.smtp_port)
                    self.smtp_user = data.get('smtp_user', self.smtp_user)
                    self.smtp_password = data.get('smtp_password', self.smtp_password)
                    self.email_remetente = data.get('email_remetente', self.email_remetente)
                    self.email_destinatarios = data.get('email_destinatarios', [])
                    self.email_critico = data.get('email_critico', '')
                    self.usar_tls = data.get('usar_tls', self.usar_tls)
                    print("✓ Configurações de email carregadas do arquivo .env")
                    return True
            except Exception as e:
                print(f"Erro ao configurar email a partir do arquivo: {e}")
                log_error(e, "config", f"Configurar email a partir do arquivo: {arquivo_encontrado}")

        print("⚠ Arquivo .env não encontrado ou inválido. Tentando variáveis de ambiente do processo...")
        self.smtp_server = _obter_variavel_ambiente('SMTP_SERVER', self.smtp_server)
        smtp_port_env = _obter_variavel_ambiente('SMTP_PORT', '')
        if smtp_port_env:
            try:
                self.smtp_port = int(smtp_port_env)
            except ValueError:
                print(f"⚠ Valor inválido para SMTP_PORT: {smtp_port_env}")
        self.smtp_user = _obter_variavel_ambiente('SMTP_USER', self.smtp_user)
        self.smtp_password = _obter_variavel_ambiente('SMTP_PASSWORD', self.smtp_password)
        self.email_remetente = _obter_variavel_ambiente('EMAIL_REMETENTE', self.email_remetente)
        self.email_destinatarios = _parsear_destinatarios_env(
            _obter_variavel_ambiente('EMAIL_DESTINATARIOS', '')
        )
        self.email_critico = _obter_variavel_ambiente('EMAIL_CRITICO', '')
        usar_tls_env = _obter_variavel_ambiente('USAR_TLS', '')
        self.usar_tls = _parsear_bool_env(usar_tls_env, self.usar_tls)

        if self.is_configured():
            print("✓ Configurações de email carregadas com sucesso")
            if AMBIENTE_PRODUCAO:
                print("✓ Modo PRODUÇÃO ativado - credenciais seguras de variáveis de ambiente")
            return True
        else:
            print("✗ Não foi possível configurar o email.")
            if AMBIENTE_PRODUCAO:
                print("✗ Em PRODUÇÃO, defina as variáveis de ambiente: SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_REMETENTE")
                log_error(Exception("Variáveis de ambiente SMTP não definidas"),
                         "config", "Email não configurado em ambiente de produção")
            else:
                print("✗ Verifique o arquivo email_config.env ou as variáveis de ambiente")
            return False

    def adicionar_caminho_busca(self, caminho: str) -> None:
        if caminho and caminho not in self.caminhos_alternativos:
            self.caminhos_alternativos.append(caminho)

    def is_configured(self) -> bool:
        return bool(self.smtp_user and self.smtp_password and self.email_remetente)

    def to_dict(self) -> Dict:
        return {
            'smtp_server': self.smtp_server, 'smtp_port': self.smtp_port,
            'smtp_user': self.smtp_user, 'smtp_password': self.smtp_password,
            'email_remetente': self.email_remetente,
            'email_destinatarios': self.email_destinatarios,
            'email_critico': getattr(self, 'email_critico', ''),
            'usar_tls': self.usar_tls
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'EmailConfig':
        config = cls(
            smtp_server=data.get('smtp_server', 'smtp.gmail.com'),
            smtp_port=data.get('smtp_port', 587),
            smtp_user=data.get('smtp_user', ''),
            smtp_password=data.get('smtp_password', ''),
            email_remetente=data.get('email_remetente', ''),
            email_destinatarios=data.get('email_destinatarios', []),
            usar_tls=data.get('usar_tls', True)
        )
        config.email_critico = data.get('email_critico', '')
        return config

    def salvar(self, caminho: Optional[str] = None) -> bool:
        arquivo = caminho or "email_config.env"
        try:
            with open(arquivo, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, indent=4, ensure_ascii=False)
            print(f"✓ Configuração salva em: {arquivo}")
            return True
        except Exception as e:
            print(f"✗ Erro ao salvar configuração: {e}")
            log_error(e, "config", f"Salvar configuração em: {arquivo}")
            return False

    @staticmethod
    def carregar(caminho_config: Optional[str] = None,
                 caminhos_extras: Optional[List[str]] = None) -> 'EmailConfig':
        config = EmailConfig()
        config.config_email(caminho_config, caminhos_extras)
        return config

    @staticmethod
    def limpar(caminho: Optional[str] = None) -> bool:
        arquivo = caminho or "email_config.env"
        try:
            if os.path.exists(arquivo):
                os.remove(arquivo)
                print(f"✓ Arquivo removido: {arquivo}")
                return True
            else:
                print(f"⚠ Arquivo não encontrado: {arquivo}")
                return False
        except Exception as e:
            print(f"✗ Erro ao remover configuração: {e}")
            log_error(e, "config", f"Remover arquivo de configuração: {arquivo}")
            return False


# ===== Templates HTML para emails =====

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
        .observacoes-box {{ background-color: #f7f7f7; border-left: 4px solid #ccc; padding: 12px; margin: 18px 0 6px 0; }}
        .observacoes-titulo {{ margin: 0 0 6px 0; color: #555; }}
        .observacoes-texto {{ margin: 0; white-space: normal; }}
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
            {secao_observacoes}
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
        .observacoes-box {{ background-color: #f7f7f7; border-left: 4px solid #ccc; padding: 12px; margin: 18px 0 6px 0; }}
        .observacoes-titulo {{ margin: 0 0 6px 0; color: #555; }}
        .observacoes-texto {{ margin: 0; white-space: normal; }}
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
            {secao_observacoes}
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
        .observacoes-box {{ background-color: #f7f7f7; border-left: 4px solid #ccc; padding: 12px; margin: 18px 0 6px 0; }}
        .observacoes-titulo {{ margin: 0 0 6px 0; color: #555; }}
        .observacoes-texto {{ margin: 0; white-space: normal; }}
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
            {secao_observacoes}
        </div>
        <div class="footer">
            AgendaObras - Sistema de Rastreamento de Obras<br>
            Data/Hora: {data_envio}
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_EMAIL_OBRA_PENDENCIAS = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f5f5f5; }}
        .container {{ max-width: 750px; margin: 20px auto; background-color: white; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: linear-gradient(135deg, #f57c00 0%, #ff9800 100%); color: white; padding: 25px 30px; }}
        .header.critico {{ background: linear-gradient(135deg, #c62828 0%, #d32f2f 100%); }}
        .header h1 {{ margin: 0 0 10px 0; font-size: 24px; font-weight: 600; }}
        .header p {{ margin: 0; font-size: 15px; opacity: 0.95; }}
        .resumo-executivo {{ background-color: #fff8e1; border-left: 5px solid #ffa000; padding: 20px 25px; margin: 20px 25px; border-radius: 4px; }}
        .resumo-executivo.critico {{ background-color: #ffebee; border-left-color: #c62828; }}
        .resumo-titulo {{ font-size: 18px; font-weight: 600; color: #333; margin: 0 0 15px 0; }}
        .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 15px; }}
        .info-item {{ display: flex; align-items: center; }}
        .info-label {{ color: #666; font-size: 13px; margin-right: 8px; }}
        .info-valor {{ color: #1565c0; font-weight: 600; font-size: 14px; }}
        .resumo-executivo p {{ margin: 10px 0 0 0; color: #555; }}
        .content {{ padding: 0 25px 25px 25px; }}
        .footer {{ background-color: #263238; color: white; padding: 20px; text-align: center; }}
        .footer-texto {{ margin: 5px 0; font-size: 13px; opacity: 0.9; }}
        .footer-data {{ margin: 8px 0 0 0; font-size: 12px; opacity: 0.7; }}
        .observacoes-box {{ background-color: #f7f7f7; border-left: 4px solid #ccc; padding: 12px; margin: 18px 0 6px 0; }}
        .observacoes-titulo {{ margin: 0 0 6px 0; color: #555; }}
        .observacoes-texto {{ margin: 12px 0; white-space: normal; font-size: 13px; color: #333; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header{header_class}">
            <h1>⚠️ AgendaObras - Alertas Diário de Obra Concluída com Pendências</h1>
        </div>
        <div class="resumo-executivo{resumo_class}">
            <div class="resumo-titulo">📋 {nome_contrato}</div>
            <div class="info-grid">
                <div class="info-item">
                    <span class="info-label">👤 Cliente:</span>
                    <span class="info-valor">{cliente}</span>
                </div>
            </div>
            <p>A obra <strong>{nome_contrato}</strong> foi concluída com pendências em aberto.</p>
        </div>
        <div class="content">
            {secao_observacoes}
            <p class="observacoes-texto">Este alerta é enviado diariamente até que a obra seja marcada como <strong>sem pendências</strong>.</p>
        </div>
        <div class="footer">
            <div class="footer-texto">AgendaObras - Sistema de Rastreamento de Obras</div>
            <div class="footer-data">📅 {data_envio}</div>
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_EMAIL_AGRUPADO_POR_OBRA = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f5f5f5; }}
        .container {{ max-width: 750px; margin: 20px auto; background-color: white; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: linear-gradient(135deg, #f57c00 0%, #ff9800 100%); color: white; padding: 25px 30px; }}
        .header.critico {{ background: linear-gradient(135deg, #c62828 0%, #d32f2f 100%); }}
        .header h1 {{ margin: 0 0 10px 0; font-size: 24px; font-weight: 600; }}
        .header p {{ margin: 0; font-size: 15px; opacity: 0.95; }}
        .resumo-executivo {{ background-color: #fff8e1; border-left: 5px solid #ffa000; padding: 20px 25px; margin: 20px 25px; border-radius: 4px; }}
        .resumo-executivo.critico {{ background-color: #ffebee; border-left-color: #c62828; }}
        .resumo-titulo {{ font-size: 18px; font-weight: 600; color: #333; margin: 0 0 15px 0; }}
        .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 15px; }}
        .info-item {{ display: flex; align-items: center; }}
        .info-label {{ color: #666; font-size: 13px; margin-right: 8px; }}
        .info-valor {{ color: #1565c0; font-weight: 600; font-size: 14px; }}
        .content {{ padding: 0 25px 25px 25px; }}
        .secao {{ margin: 25px 0; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
        .secao-header {{ padding: 14px 18px; font-weight: 600; font-size: 15px; color: white; display: flex; align-items: center; justify-content: space-between; }}
        .secao-header .icone {{ font-size: 20px; margin-right: 8px; }}
        .secao-header .contador {{ background-color: rgba(255,255,255,0.25); padding: 2px 10px; border-radius: 12px; font-size: 13px; }}
        .secao-critico .secao-header {{ background: linear-gradient(135deg, #c62828 0%, #d32f2f 100%); }}
        .secao-tipo-b .secao-header {{ background: linear-gradient(135deg, #d84315 0%, #f4511e 100%); }}
        .secao-reiteracao .secao-header {{ background: linear-gradient(135deg, #ef6c00 0%, #f57c00 100%); }}
        table {{ width: 100%; border-collapse: collapse; background-color: white; }}
        thead {{ background-color: #fafafa; }}
        th {{ padding: 12px 15px; text-align: left; font-size: 12px; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 2px solid #e0e0e0; }}
        th.center {{ text-align: center; }}
        td {{ padding: 14px 15px; font-size: 14px; border-bottom: 1px solid #f0f0f0; }}
        td.center {{ text-align: center; }}
        tbody tr:last-child td {{ border-bottom: none; }}
        tbody tr:hover {{ background-color: #f9f9f9; }}
        .tarefa-nome {{ font-weight: 500; color: #333; }}
        .prazo-data {{ color: #666; font-size: 13px; }}
        .badge {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px; }}
        .badge-critico {{ background-color: #d32f2f; color: white; }}
        .badge-tipo-b {{ background-color: #f4511e; color: white; }}
        .badge-reiteracao-1 {{ background-color: #fff59d; color: #f57f17; }}
        .badge-reiteracao-2 {{ background-color: #ffb74d; color: #e65100; }}
        .badge-reiteracao-3 {{ background-color: #ff9800; color: white; }}
        .dias-atraso {{ font-weight: 700; color: #d32f2f; font-size: 15px; }}
        .dias-atraso.medio {{ color: #f57c00; }}
        .dias-atraso.leve {{ color: #ffa726; }}
        .secao-rodape {{ padding: 12px 18px; background-color: #f5f5f5; font-size: 12px; color: #666; border-top: 1px solid #e0e0e0; }}
        .secao-rodape.urgente {{ background-color: #ffebee; color: #c62828; font-weight: 500; }}
        .cta-box {{ margin: 25px 0 15px 0; padding: 20px; background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%); border-radius: 6px; border: 1px solid #90caf9; }}
        .cta-titulo {{ font-size: 16px; font-weight: 600; color: #1565c0; margin: 0 0 10px 0; }}
        .cta-texto {{ color: #424242; margin: 0; font-size: 14px; line-height: 1.6; }}
        .observacoes-box {{ background-color: #f7f7f7; border-left: 4px solid #ccc; padding: 12px; margin: 0 0 18px 0; }}
        .observacoes-titulo {{ margin: 0 0 6px 0; color: #555; }}
        .observacoes-texto {{ margin: 0; white-space: normal; font-size: 13px; color: #333; }}
        .footer {{ background-color: #263238; color: white; padding: 20px; text-align: center; }}
        .footer-texto {{ margin: 5px 0; font-size: 13px; opacity: 0.9; }}
        .footer-data {{ margin: 8px 0 0 0; font-size: 12px; opacity: 0.7; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header{header_class}">
            <h1>⚠️ AgendaObras - Alertas de Tarefas Pendentes</h1>
            <p>{total_tarefas} {texto_tarefas} aguardando providências</p>
        </div>
        <div class="resumo-executivo{resumo_class}">
            <div class="resumo-titulo">📋 {nome_contrato}</div>
            <div class="info-grid">
                <div class="info-item">
                    <span class="info-label">👤 Cliente:</span>
                    <span class="info-valor">{cliente}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">📌 Total de alertas:</span>
                    <span class="info-valor">{total_tarefas}</span>
                </div>
            </div>
        </div>
        <div class="content">
            {secoes_conteudo}
        </div>
        {secao_observacoes}
        <div class="footer">
            <div class="footer-texto">AgendaObras - Sistema de Rastreamento de Obras</div>
            <div class="footer-data">📅 {data_envio}</div>
        </div>
    </div>
</body>
</html>
"""

SECAO_REITERACAO = """
<div class="secao secao-reiteracao">
    <div class="secao-header">
        <div><span class="icone">🔔</span>{titulo_secao}</div>
        <span class="contador">{contador}</span>
    </div>
    <table>
        <thead>
            <tr>
                <th>Tarefa</th>
                <th style="width: 120px;">Prazo Original</th>
                <th class="center" style="width: 100px;">Reiteração</th>
                <th class="center" style="width: 100px;">Dias Atraso</th>
            </tr>
        </thead>
        <tbody>{linhas_tarefas}</tbody>
    </table>
    {mensagem_rodape}
</div>
"""

SECAO_CRITICO_ATRASADO = """
<div class="secao secao-critico">
    <div class="secao-header">
        <div><span class="icone">🆘</span>Tarefas Críticas em Atraso</div>
        <span class="contador">{contador}</span>
    </div>
    <table>
        <thead>
            <tr>
                <th>Tarefa</th>
                <th style="width: 120px;">Prazo Original</th>
                <th class="center" style="width: 100px;">Status</th>
                <th class="center" style="width: 100px;">Dias Atraso</th>
            </tr>
        </thead>
        <tbody>{linhas_tarefas}</tbody>
    </table>
    <div class="secao-rodape urgente">⚠️ URGENTE: Essas tarefas requerem ação imediata!</div>
</div>
"""

SECAO_TIPO_B = """
<div class="secao secao-tipo-b">
    <div class="secao-header">
        <div><span class="icone">🚨</span>Tarefas de Prazo Fixo (Críticas)</div>
        <span class="contador">{contador}</span>
    </div>
    <table>
        <thead>
            <tr>
                <th>Tarefa</th>
                <th style="width: 120px;">Prazo Limite</th>
                <th class="center" style="width: 100px;">Status</th>
                <th class="center" style="width: 100px;">Situação</th>
            </tr>
        </thead>
        <tbody>{linhas_tarefas}</tbody>
    </table>
    <div class="secao-rodape urgente">🚨 Atenção: Prazo fixo - Não há prorrogação possível!</div>
</div>
"""
