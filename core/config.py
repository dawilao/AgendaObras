"""
Configurações do Sistema AgendaObras
"""
import json
import os
import time
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
# Se o ciclo diário falhar, tenta de novo após este intervalo, até o limite de tentativas no dia.
EMAIL_DISPARO_RETRY_MINUTOS = 30
EMAIL_DISPARO_MAX_TENTATIVAS = 3
GITHUB_REPO_URL = "https://github.com/dawilao/AgendaObras"
VERSION_JSON_URL = "https://raw.githubusercontent.com/dawilao/AgendaObras/main/version.json"

BIBLIOTECA_PDF_MAX_MB = int(_obter_variavel_ambiente('BIBLIOTECA_PDF_MAX_MB', '5'))
# Tamanho máximo de um e-mail importado nas Comunicações (mensagem inteira, anexos em base64).
COMUNICACOES_MAX_MB = int(_obter_variavel_ambiente('AGENDA_MAIL_MAX_MB', '15'))
# Compactação sem perda dos anexos em disco (lzma e deduplicação dentro de ZIPs). 0 desliga.
COMUNICACOES_COMPACTAR = _obter_variavel_ambiente('AGENDA_MAIL_COMPACTAR', '1') != '0'

APP_TIMEZONE_PADRAO = 'America/Sao_Paulo'


def aplicar_fuso_horario(tz: Optional[str] = None) -> str:
    """Fixa o fuso do processo para que datetime.now()/date.today() usem a hora de Brasília.

    Servidores Linux costumam rodar em UTC. No Windows time.tzset não existe e o
    fuso da máquina é mantido. Pode ser trocado com AGENDA_OBRAS_TIMEZONE.
    """
    tz = tz or _obter_variavel_ambiente('AGENDA_OBRAS_TIMEZONE', APP_TIMEZONE_PADRAO)
    if hasattr(time, 'tzset'):
        os.environ['TZ'] = tz
        time.tzset()
    return tz


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

# ===== Resumo diário (um e-mail por destinatário) =====
# HTML enxuto: CSS curto, sem degradês/sombras/flex/grid, para caber no limite
# de ~100 KB do Gmail e renderizar bem no Outlook.

TEMPLATE_EMAIL_RESUMO_DIARIO = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
body{{font-family:Arial,sans-serif;color:#333;background:#f5f5f5;margin:0}}
.c{{max-width:760px;margin:0 auto;background:#fff}}
.h{{background:#ef6c00;color:#fff;padding:16px 20px}}
.h.cr{{background:#c62828}}
.h h1{{margin:0;font-size:20px}}
.h p{{margin:4px 0 0;font-size:13px}}
.b{{padding:16px 20px}}
.k{{font-size:14px;margin:0 0 12px}}
.nota{{background:#e3f2fd;color:#0d47a1;padding:8px 10px;font-size:12px;margin:0 0 12px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;background:#fafafa;color:#555;font-size:11px;text-transform:uppercase;padding:6px 8px;border-bottom:2px solid #e0e0e0}}
td{{padding:6px 8px;border-bottom:1px solid #eee}}
.n{{text-align:center}}
.o{{margin:22px 0 0}}
.o h2{{font-size:15px;margin:0 0 6px;padding:6px 8px;background:#eceff1;border-left:4px solid #ef6c00}}
.o h2.cr{{border-left-color:#c62828}}
.o h2 small{{color:#666;font-weight:normal}}
.pend{{background:#ffebee;color:#b71c1c;padding:6px 8px;font-size:12px;font-weight:bold;margin:0 0 6px}}
.obs{{background:#f7f7f7;border-left:3px solid #ccc;padding:6px 8px;font-size:12px;margin:6px 0 0}}
.s{{display:inline-block;padding:2px 6px;border-radius:3px;font-size:10px;font-weight:bold;color:#fff;white-space:nowrap}}
.s1{{background:#c62828}}
.s2{{background:#d84315}}
.s3{{background:#f57c00}}
.s4{{background:#ffb74d;color:#5d4037}}
.s5{{background:#fff59d;color:#795548}}
.nv{{background:#1565c0;margin-left:6px}}
.d{{font-weight:bold;color:#c62828;text-align:center}}
.f{{background:#263238;color:#cfd8dc;padding:12px;text-align:center;font-size:11px}}
</style></head><body><div class="c">
<div class="h{classe_header}"><h1>AgendaObras &ndash; Resumo di&aacute;rio {data}</h1><p>{subtitulo}</p></div>
<div class="b">
<p class="k">{saudacao}<br>{contagens}</p>
{nota_resumida}
<table><thead><tr><th>Obra</th><th>Contrato</th><th class="n">Cr&iacute;t.</th><th class="n">Prazo fixo</th><th class="n">Reit.</th><th class="n">Pend.</th></tr></thead><tbody>{linhas_obras}</tbody></table>
{blocos_obras}
</div>
<div class="f">AgendaObras - Sistema de Rastreamento de Obras &middot; {data_envio}<br>Este resumo &eacute; enviado em dias &uacute;teis enquanto houver tarefas em alerta.</div>
</div></body></html>
"""

RESUMO_LINHA_OBRA = (
    '<tr><td>{obra}</td><td>{contrato}</td><td class="n">{criticas}</td>'
    '<td class="n">{prazo_fixo}</td><td class="n">{reiteracoes}</td><td class="n">{pendencias}</td></tr>'
)

RESUMO_BLOCO_OBRA = (
    '<div class="o"><h2{classe}>{obra} <small>&middot; {contrato}</small></h2>'
    '{faixa_pendencias}{tabela}{observacoes}</div>'
)

RESUMO_TABELA_TAREFAS = (
    '<table><thead><tr><th>Tarefa</th><th>Prazo</th><th class="n">Situa&ccedil;&atilde;o</th>'
    '<th class="n">Dias</th></tr></thead><tbody>{linhas}</tbody></table>'
)

RESUMO_LINHA_TAREFA = (
    '<tr><td>{tarefa}{novo}</td><td>{prazo}</td>'
    '<td class="n"><span class="s {classe}">{situacao}</span></td><td class="d">{dias}</td></tr>'
)
