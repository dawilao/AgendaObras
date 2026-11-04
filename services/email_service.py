"""
Módulo de serviço de envio de emails via SMTP para o sistema AgendaObras.
Responsável pelo envio de notificações e alertas de prazos.
"""

import smtplib
import datetime
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from typing import Tuple, Dict, List
from core.error_logger import log_error
from core.config import (
    EmailConfig,
    TEMPLATE_EMAIL_ALERTA_A,
    TEMPLATE_EMAIL_ALERTA_B,
    TEMPLATE_EMAIL_CRITICO_ATRASADO,
    TEMPLATE_EMAIL_RESUMO_DIARIO,
    RESUMO_LINHA_OBRA,
    RESUMO_BLOCO_OBRA,
    RESUMO_TABELA_TAREFAS,
    RESUMO_LINHA_TAREFA,
)


class EmailService:
    """Serviço para envio de emails via SMTP"""

    def __init__(self, database: 'Database'):
        self.database = database
        self.config = EmailConfig.carregar()

    def recarregar_config(self):
        """Recarrega configuração de email"""
        self.config = EmailConfig.carregar()

    # Erros em que vale reconectar e tentar a mesma mensagem de novo (conexão caiu/expirou)
    _ERROS_RECONECTAVEIS = (
        smtplib.SMTPServerDisconnected,
        smtplib.SMTPSenderRefused,
        ConnectionError,
        TimeoutError,
    )

    def _conectar_smtp(self, timeout: int = 30):
        """Abre a conexão SMTP (TLS ou SSL) já autenticada."""
        if self.config.usar_tls:
            server = smtplib.SMTP(self.config.smtp_server, self.config.smtp_port, timeout=timeout)
        else:
            server = smtplib.SMTP_SSL(self.config.smtp_server, self.config.smtp_port, timeout=timeout)
        try:
            if self.config.usar_tls:
                server.starttls()
            server.login(self.config.smtp_user, self.config.smtp_password)
        except Exception:
            self._fechar_smtp(server)
            raise
        return server

    @staticmethod
    def _fechar_smtp(server) -> None:
        """Encerra a conexão sem propagar erro (conexão já caída também é aceita)."""
        if server is None:
            return
        try:
            server.quit()
        except Exception:
            try:
                server.close()
            except Exception:
                pass

    def _montar_mensagem(self, destinatarios: List[str], assunto: str, corpo_html: str) -> MIMEMultipart:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = str(Header(assunto or '', 'utf-8'))
        msg['From'] = self.config.email_remetente
        msg['To'] = ", ".join(destinatarios)
        msg.attach(MIMEText(corpo_html, 'html', 'utf-8'))
        return msg

    def enviar_email(self, destinatario, assunto: str, corpo_html: str) -> Tuple[bool, str]:
        """Envia email via SMTP. destinatario pode ser str ou list[str]."""
        if not self.config.is_configured():
            return (False, "Configuração SMTP não encontrada.")

        server = None
        try:
            destinatarios = [destinatario] if isinstance(destinatario, str) else list(destinatario)
            msg = self._montar_mensagem(destinatarios, assunto, corpo_html)

            server = self._conectar_smtp()
            server.send_message(msg, to_addrs=destinatarios)

            print(f"✅ Email enviado com sucesso para {', '.join(destinatarios)}")
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
        finally:
            self._fechar_smtp(server)

    def enviar_emails_em_lote(self, mensagens: List[Tuple[str, str, str]]) -> List[Tuple[bool, str]]:
        """Envia várias mensagens individuais reaproveitando UMA conexão SMTP.

        Args:
            mensagens: lista de (destinatario, assunto, corpo_html).

        Returns:
            Lista de (sucesso, mensagem) na mesma ordem de `mensagens`.

        Se a conexão cair no meio, reconecta e tenta aquela mensagem mais uma vez.
        Falha de autenticação ou SMTP não configurado reprova todas as mensagens.
        """
        if not mensagens:
            return []
        if not self.config.is_configured():
            return [(False, "Configuração SMTP não encontrada.")] * len(mensagens)

        resultados: List[Tuple[bool, str]] = []
        server = None
        try:
            try:
                server = self._conectar_smtp()
            except smtplib.SMTPAuthenticationError as e:
                erro = "Falha na autenticação SMTP. Verifique usuário e senha."
                log_error(e, "email_service", "Autenticação SMTP (envio em lote)")
                print(f"❌ {erro}")
                return [(False, erro)] * len(mensagens)
            except Exception as e:
                erro = f"Erro ao conectar ao SMTP: {e}"
                log_error(e, "email_service", "Conexão SMTP (envio em lote)")
                print(f"❌ {erro}")
                return [(False, erro)] * len(mensagens)

            for destinatario, assunto, corpo_html in mensagens:
                msg = self._montar_mensagem([destinatario], assunto, corpo_html)
                tentativas = 2  # envio + 1 nova tentativa após reconectar
                for tentativa in range(tentativas):
                    try:
                        if server is None:
                            server = self._conectar_smtp()
                        server.send_message(msg, to_addrs=[destinatario])
                        print(f"✅ Email enviado com sucesso para {destinatario}")
                        resultados.append((True, "Email enviado com sucesso"))
                        break
                    except self._ERROS_RECONECTAVEIS as e:
                        self._fechar_smtp(server)
                        server = None
                        if tentativa < tentativas - 1:
                            continue
                        erro = f"Erro SMTP: {e}"
                        log_error(e, "email_service", f"Envio em lote para {destinatario} (após reconectar)")
                        print(f"❌ {erro}")
                        resultados.append((False, erro))
                    except smtplib.SMTPException as e:
                        erro = f"Erro SMTP: {e}"
                        log_error(e, "email_service", f"Envio em lote para {destinatario}")
                        print(f"❌ {erro}")
                        resultados.append((False, erro))
                        break
                    except Exception as e:
                        erro = f"Erro ao enviar email: {e}"
                        log_error(e, "email_service", f"Envio em lote para {destinatario} - assunto: {assunto}")
                        print(f"❌ {erro}")
                        resultados.append((False, erro))
                        break
        finally:
            self._fechar_smtp(server)

        return resultados

    def testar_conexao(self) -> Tuple[bool, str]:
        """Testa conexão SMTP sem enviar email"""
        if not self.config.is_configured():
            return (False, "Configuração incompleta")

        try:
            server = self._conectar_smtp(timeout=10)
            self._fechar_smtp(server)
            return (True, "Conexão SMTP bem-sucedida!")
        except Exception as e:
            log_error(e, "email_service", "Teste de conexão SMTP")
            return (False, f"Erro: {str(e)}")

    def _montar_secao_observacoes_html(self, observacoes: str) -> str:
        """Monta bloco HTML de observações preservando quebras de linha."""
        texto = (observacoes or '').strip()
        if not texto:
            return ''

        texto_html = (
            html.escape(texto)
            .encode('ascii', errors='xmlcharrefreplace')
            .decode('ascii')
            .replace('\n', '<br>')
        )
        return (
            '<div class="observacoes-box">'
            '<p class="observacoes-titulo"><strong>Observações</strong></p>'
            f'<p class="observacoes-texto">{texto_html}</p>'
            '</div>'
        )

    def _texto_html(self, valor) -> str:
        """Normaliza texto para HTML com entidades ASCII para máxima compatibilidade."""
        texto = str(valor or '')
        return html.escape(texto).encode('ascii', errors='xmlcharrefreplace').decode('ascii')

    def criar_email_alerta_tipo_a(self, tarefa: Dict, reiteracao: int) -> str:
        """Cria HTML de email para tarefa Tipo A (com reiteração)"""
        data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
        prazo_formatado = data_limite.strftime('%d/%m/%Y')
        secao_observacoes = self._montar_secao_observacoes_html(tarefa.get('observacoes'))
        nome_contrato = self._texto_html(tarefa.get('nome_contrato'))
        cliente = self._texto_html(tarefa.get('cliente'))
        tarefa_desc = self._texto_html(tarefa.get('descricao'))

        dias_atraso = (datetime.date.today() - data_limite.date()).days

        if reiteracao == 3:
            mensagem_adicional = "<p style='color: #d32f2f; font-weight: bold;'>⚠️ ATENÇÃO: Esta é a última reiteração automática. Após esta, os alertas se tornarão CRÍTICOS e DIÁRIOS.</p>"
        else:
            mensagem_adicional = f"<p>Próxima reiteração em 2 dias caso a tarefa não seja concluída.</p>"

        return TEMPLATE_EMAIL_ALERTA_A.format(
            reiteracao=reiteracao,
            nome_contrato=nome_contrato,
            cliente=cliente,
            tarefa=tarefa_desc,
            prazo=prazo_formatado,
            dias_atraso=dias_atraso,
            mensagem_adicional=mensagem_adicional,
            secao_observacoes=secao_observacoes,
            data_envio=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        )

    def criar_email_alerta_tipo_b(self, tarefa: Dict) -> str:
        """Cria HTML de email para tarefa Tipo B (prazo fixo)"""
        data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
        prazo_formatado = data_limite.strftime('%d/%m/%Y')
        secao_observacoes = self._montar_secao_observacoes_html(tarefa.get('observacoes'))
        nome_contrato = self._texto_html(tarefa.get('nome_contrato'))
        cliente = self._texto_html(tarefa.get('cliente'))
        tarefa_desc = self._texto_html(tarefa.get('descricao'))

        hoje = datetime.date.today()
        if data_limite.date() == hoje:
            status = "ÚLTIMO DIA DO PRAZO - HOJE"
        elif data_limite.date() < hoje:
            status = f"ATRASADA - {(hoje - data_limite.date()).days} dias"
        else:
            status = "Dentro do prazo"
        status = self._texto_html(status)

        return TEMPLATE_EMAIL_ALERTA_B.format(
            nome_contrato=nome_contrato,
            cliente=cliente,
            tarefa=tarefa_desc,
            prazo=prazo_formatado,
            status=status,
            secao_observacoes=secao_observacoes,
            data_envio=datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        )

    def criar_email_critico_atrasado(self, tarefa: Dict, dias_atraso: int) -> str:
        """Cria HTML de email crítico para tarefa atrasada"""
        data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d')
        prazo_formatado = data_limite.strftime('%d/%m/%Y')
        secao_observacoes = self._montar_secao_observacoes_html(tarefa.get('observacoes'))
        nome_contrato = self._texto_html(tarefa.get('nome_contrato'))
        cliente = self._texto_html(tarefa.get('cliente'))
        tarefa_desc = self._texto_html(tarefa.get('descricao'))

        return TEMPLATE_EMAIL_CRITICO_ATRASADO.format(
            nome_contrato=nome_contrato,
            cliente=cliente,
            tarefa=tarefa_desc,
            prazo=prazo_formatado,
            dias_atraso=dias_atraso,
            secao_observacoes=secao_observacoes,
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

    # ===== Resumo diário (um e-mail por destinatário) =====

    # Ordem de gravidade das categorias dentro de cada obra (menor = mais grave).
    _ORDEM_CATEGORIAS = {
        'critico_atrasado': 0,
        'tipo_b': 1,
        'reiteracao_3': 2,
        'reiteracao_2': 3,
        'reiteracao_1': 4,
    }
    _CATEGORIAS_REITERACAO = ('reiteracao_1', 'reiteracao_2', 'reiteracao_3')

    @staticmethod
    def _plural(qtd: int, singular: str, plural: str) -> str:
        return f"{qtd} {singular if qtd == 1 else plural}"

    @staticmethod
    def _dias_desde_prazo(alerta: Dict, hoje: datetime.date) -> int:
        if alerta.get('dias_diff') is not None:
            return int(alerta['dias_diff'])
        data_limite = datetime.datetime.strptime(alerta['data_limite'], '%Y-%m-%d').date()
        return (hoje - data_limite).days

    def _linha_tarefa_resumo(self, categoria: str, alerta: Dict, hoje: datetime.date) -> str:
        dias = self._dias_desde_prazo(alerta, hoje)
        if categoria == 'critico_atrasado':
            classe, situacao, dias_txt = 's1', 'CR&Iacute;TICO', str(dias)
        elif categoria == 'tipo_b':
            classe = 's2'
            situacao = '&Uacute;LTIMO DIA' if dias <= 0 else 'PRAZO FIXO'
            dias_txt = 'HOJE' if dias <= 0 else str(dias)
        else:
            num = categoria[-1]
            classe = {'3': 's3', '2': 's4'}.get(num, 's5')
            situacao, dias_txt = f'{num}&ordf; REITERA&Ccedil;&Atilde;O', str(dias)

        try:
            prazo = datetime.datetime.strptime(alerta['data_limite'], '%Y-%m-%d').strftime('%d/%m/%Y')
        except Exception:
            prazo = self._texto_html(alerta.get('data_limite'))

        return RESUMO_LINHA_TAREFA.format(
            tarefa=self._texto_html(alerta.get('descricao')),
            novo='<span class="s nv">NOVO</span>' if alerta.get('novo') else '',
            prazo=prazo,
            classe=classe,
            situacao=situacao,
            dias=dias_txt,
        )

    def criar_email_resumo_diario(self, nome_destinatario: str, obras: List[Dict],
                                  hoje: datetime.date = None, resumido: bool = False) -> Tuple[str, str]:
        """Monta o e-mail diário único de um destinatário com todas as suas obras.

        Args:
            nome_destinatario: nome para a saudação (vazio -> "Olá,").
            obras: lista já filtrada e ordenada por gravidade; cada item tem
                'info' (nome_contrato, cliente, observacoes), 'tarefas' {categoria: [alertas]}
                e 'com_pendencias' (bool).
            hoje: data de referência (fuso do notificador).
            resumido: versão para admins/e-mail crítico (só críticos e pendências).

        Returns:
            (assunto, corpo_html)
        """
        hoje = hoje or datetime.date.today()

        tot = {'critico_atrasado': 0, 'tipo_b': 0, 'reiteracao': 0, 'pendencias': 0, 'novos': 0}
        linhas_obras, blocos = [], []

        for obra in obras:
            info = obra.get('info', {})
            tarefas = obra.get('tarefas', {})
            com_pendencias = bool(obra.get('com_pendencias'))

            n_crit = len(tarefas.get('critico_atrasado', []))
            n_tipo_b = len(tarefas.get('tipo_b', []))
            n_reit = sum(len(tarefas.get(c, [])) for c in self._CATEGORIAS_REITERACAO)
            tot['critico_atrasado'] += n_crit
            tot['tipo_b'] += n_tipo_b
            tot['reiteracao'] += n_reit
            tot['pendencias'] += 1 if com_pendencias else 0

            nome_obra = self._texto_html(info.get('nome_contrato'))
            contrato = self._texto_html(info.get('cliente'))
            linhas_obras.append(RESUMO_LINHA_OBRA.format(
                obra=nome_obra,
                contrato=contrato,
                criticas=n_crit or '&ndash;',
                prazo_fixo=n_tipo_b or '&ndash;',
                reiteracoes=n_reit or '&ndash;',
                pendencias='Sim' if com_pendencias else '&ndash;',
            ))

            itens = []
            for categoria, lista in tarefas.items():
                for alerta in lista:
                    itens.append((categoria, alerta))
                    if alerta.get('novo'):
                        tot['novos'] += 1
            itens.sort(key=lambda par: (
                self._ORDEM_CATEGORIAS.get(par[0], 9),
                -self._dias_desde_prazo(par[1], hoje),
                str(par[1].get('descricao') or ''),
            ))

            tabela = ''
            if itens:
                tabela = RESUMO_TABELA_TAREFAS.format(
                    linhas=''.join(self._linha_tarefa_resumo(c, a, hoje) for c, a in itens)
                )
            faixa = ''
            if com_pendencias:
                faixa = ('<div class="pend">Obra conclu&iacute;da com pend&ecirc;ncias em aberto &ndash; '
                         'alerta di&aacute;rio at&eacute; ser marcada como sem pend&ecirc;ncias.</div>')
            obs = (info.get('observacoes') or '').strip()
            bloco_obs = ''
            if obs:
                obs_html = self._texto_html(obs).replace('\n', '<br>')
                bloco_obs = f'<div class="obs"><strong>Observa&ccedil;&otilde;es:</strong> {obs_html}</div>'

            obra_critica = bool(n_crit or n_tipo_b or com_pendencias)
            blocos.append(RESUMO_BLOCO_OBRA.format(
                classe=' class="cr"' if obra_critica else '',
                obra=nome_obra,
                contrato=contrato,
                faixa_pendencias=faixa,
                tabela=tabela,
                observacoes=bloco_obs,
            ))

        total_tarefas = tot['critico_atrasado'] + tot['tipo_b'] + tot['reiteracao']
        tem_critico = bool(tot['critico_atrasado'] or tot['tipo_b'] or tot['pendencias'])

        partes_contagem = []
        if tot['critico_atrasado']:
            partes_contagem.append(f"&#x1F198; Cr&iacute;ticas: <strong>{tot['critico_atrasado']}</strong>")
        if tot['tipo_b']:
            partes_contagem.append(f"&#x1F6A8; Prazo fixo: <strong>{tot['tipo_b']}</strong>")
        if tot['reiteracao']:
            partes_contagem.append(f"&#x1F514; Reitera&ccedil;&otilde;es: <strong>{tot['reiteracao']}</strong>")
        if tot['pendencias']:
            partes_contagem.append(f"&#x26A0;&#xFE0F; Obras com pend&ecirc;ncias: <strong>{tot['pendencias']}</strong>")
        if tot['novos']:
            partes_contagem.append(f"&#x1F195; Novos hoje: <strong>{tot['novos']}</strong>")

        nome = (nome_destinatario or '').strip()
        saudacao = f"Ol&aacute;, {self._texto_html(nome)}." if nome else "Ol&aacute;,"
        saudacao += " Este &eacute; o resumo das suas obras com alertas hoje."

        nota = ''
        if resumido:
            nota = ('<div class="nota">Vers&atilde;o resumida: apenas itens cr&iacute;ticos, '
                    'de prazo fixo e obras com pend&ecirc;ncias.</div>')

        n_obras = len(obras)
        subtitulo = self._plural(n_obras, 'obra', 'obras')
        if total_tarefas:
            subtitulo += f" &middot; {self._plural(total_tarefas, 'tarefa', 'tarefas')} em alerta"

        corpo_html = TEMPLATE_EMAIL_RESUMO_DIARIO.format(
            classe_header=' cr' if tem_critico else '',
            data=hoje.strftime('%d/%m/%Y'),
            subtitulo=subtitulo,
            saudacao=saudacao,
            contagens=' &middot; '.join(partes_contagem),
            nota_resumida=nota,
            linhas_obras=''.join(linhas_obras),
            blocos_obras=''.join(blocos),
            data_envio=datetime.datetime.now().strftime('%d/%m/%Y %H:%M'),
        )

        resumo_assunto = f"Resumo diário {hoje.strftime('%d/%m')} · {self._plural(n_obras, 'obra', 'obras')}"
        if total_tarefas:
            resumo_assunto += f" · {self._plural(total_tarefas, 'tarefa', 'tarefas')}"
        if tem_critico:
            assunto = f"🆘 [CRÍTICO] AgendaObras – {resumo_assunto}"
        else:
            assunto = f"⚠️ AgendaObras – {resumo_assunto}"

        return (assunto, corpo_html)
