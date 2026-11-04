"""
Módulo de sistema de notificações automáticas de prazos e gerador de tarefas recorrentes.
"""

import threading
import time
import datetime
import sqlite3
import calendar
from typing import Dict, List
from zoneinfo import ZoneInfo
from core.error_logger import log_error
from db.auth_repo import AuthDatabase
from db.contratos_repo import ContratosDatabase
from core.config import (
    EMAIL_DISPARO_HORA,
    EMAIL_DISPARO_MINUTO,
    EMAIL_DISPARO_TIMEZONE,
    EMAIL_DISPARO_CATCHUP,
    EMAIL_DISPARO_RETRY_MINUTOS,
    EMAIL_DISPARO_MAX_TENTATIVAS,
)

# Flag global para controlar se o notificador já está executando
_notificador_ativo = False
_notificador_lock = threading.Lock()

# Valores de receber_alerta_critico que significam "não receber"
_VALORES_FALSOS = (0, False, '0', 'false', 'False', None)

# Categorias de alerta usadas no resumo diário
CATEGORIAS_REITERACAO = frozenset({'reiteracao_1', 'reiteracao_2', 'reiteracao_3'})
CATEGORIAS_CRITICAS = frozenset({'critico_atrasado', 'tipo_b', 'pendencias'})
TODAS_CATEGORIAS = CATEGORIAS_REITERACAO | CATEGORIAS_CRITICAS


class GeradorTarefasRecorrentes:
    """Gera tarefas mensais recorrentes dinamicamente"""

    _TAREFAS_DINAMICAS_EXCLUIDAS = {'MEDIÇÃO', 'CONFIRMAÇÃO DE MEDIÇÃO'}

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
            templates_mensais = [
                dict(row)
                for row in cursor.fetchall()
                if (row['nome'] or '').strip() not in self._TAREFAS_DINAMICAS_EXCLUIDAS
            ]

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


class NotificadorPrazos:
    def __init__(self, database: 'Database', email_service: 'EmailService', gerador_recorrentes: 'GeradorTarefasRecorrentes' = None):
        self.database = database
        self.email_service = email_service
        self.gerador_recorrentes = gerador_recorrentes
        self.executando = False
        self.hora_disparo = EMAIL_DISPARO_HORA
        self.minuto_disparo = EMAIL_DISPARO_MINUTO
        self.habilitar_catchup = EMAIL_DISPARO_CATCHUP
        self.intervalo_retry = datetime.timedelta(minutes=EMAIL_DISPARO_RETRY_MINUTOS)
        self.max_tentativas_dia = EMAIL_DISPARO_MAX_TENTATIVAS
        self._falhas_por_dia: Dict[datetime.date, int] = {}
        try:
            self.fuso_horario = ZoneInfo(EMAIL_DISPARO_TIMEZONE)
        except Exception as e:
            self.fuso_horario = datetime.timezone(
                datetime.timedelta(hours=-3),
                name=EMAIL_DISPARO_TIMEZONE,
            )
            print(
                f"[AVISO] Timezone '{EMAIL_DISPARO_TIMEZONE}' indisponivel no sistema. "
                "Usando fallback fixo UTC-03:00."
            )

    def _carregar_usuarios_alerta(self) -> List[Dict]:
        """Carrega, uma única vez por ciclo, os usuários com e-mail e seus contratos vinculados.

        Retorna lista de dicts: {email, nome, is_admin, recebe_critico, contratos: set}.
        """
        usuarios = AuthDatabase().listar_usuarios() or []
        contratos_db = ContratosDatabase()

        resultado = []
        for usuario in usuarios:
            email = (usuario.get('email') or '').strip().lower()
            if not email:
                continue
            is_admin = bool(usuario.get('is_admin'))
            contratos = set()
            if not is_admin and usuario.get('id'):
                contratos = {
                    (c or '').strip()
                    for c in contratos_db.listar_contratos_usuario(usuario['id'])
                    if (c or '').strip()
                }
            resultado.append({
                'email': email,
                'nome': (usuario.get('nome') or '').strip(),
                'is_admin': is_admin,
                'recebe_critico': usuario.get('receber_alerta_critico', 1) not in _VALORES_FALSOS,
                'contratos': contratos,
            })
        return resultado

    def _config_email(self, chave: str, padrao):
        valor = getattr(self.email_service.config, chave, padrao)
        return valor if isinstance(valor, type(padrao)) else padrao

    def _obter_destinatarios_por_contrato(self, contrato_nome: str, tem_critico: bool = False,
                                          usuarios: List[Dict] = None) -> List[str]:
        """Resolve destinatários de um contrato (visão por obra, sem filtro por item):
        - Admin recebe apenas quando há alerta crítico (e não desativou alertas críticos)
        - Não-admin recebe apenas alertas dos contratos vinculados
        - Se ninguém se qualificar, usa fallback da configuração de email
        """
        fallback = list(self._config_email('email_destinatarios', []))
        destinatarios = []

        try:
            if usuarios is None:
                usuarios = self._carregar_usuarios_alerta()
            contrato_normalizado = (contrato_nome or '').strip()

            emails = set()
            for usuario in usuarios:
                if usuario['is_admin']:
                    if tem_critico and usuario['recebe_critico']:
                        emails.add(usuario['email'])
                    continue
                if contrato_normalizado in usuario['contratos']:
                    if tem_critico and not usuario['recebe_critico']:
                        continue
                    emails.add(usuario['email'])

            # Fallback: mantém compatibilidade quando users.db estiver ausente/incompleto
            destinatarios = sorted(emails) or fallback

        except Exception as e:
            log_error(e, "notificador_prazos", "Resolver destinatários por contrato")
            destinatarios = fallback

        if tem_critico:
            email_critico = self._config_email('email_critico', '').strip().lower()
            if email_critico:
                destinatarios = list(destinatarios) + [email_critico]

        # Remove vazios e deduplica preservando ordem
        deduplicados = []
        vistos = set()
        for email in destinatarios:
            email_limpo = (email or '').strip().lower()
            if email_limpo and email_limpo not in vistos:
                vistos.add(email_limpo)
                deduplicados.append(email_limpo)

        return deduplicados

    def _mapear_permissoes(self, obras: Dict[int, Dict], usuarios: List[Dict]) -> Dict[str, Dict]:
        """Define, por destinatário, quais categorias de alerta ele recebe em cada obra.

        Regras (por item):
        - Coordenador (não-admin vinculado ao contrato): reiterações + críticos/pendências
          (sem críticos/pendências se desativou alertas críticos).
        - Admin com alertas críticos ativos e e-mail crítico da config: só críticos/pendências, todas as obras.
        - Fallback da config: categorias de uma obra que nenhum usuário cobre.

        Retorna {email: {'nome', 'resumido', 'obras': {obra_id: set(categorias)}}}.
        """
        permissoes: Dict[str, Dict] = {}

        def conceder(email: str, nome: str, obra_id: int, categorias, coordenador: bool):
            email = (email or '').strip().lower()
            if not email or not categorias:
                return
            perm = permissoes.setdefault(email, {'nome': '', 'coordena': False, 'obras': {}})
            if nome and not perm['nome']:
                perm['nome'] = nome
            perm['obras'].setdefault(obra_id, set()).update(categorias)
            perm['coordena'] = perm['coordena'] or coordenador

        email_critico = self._config_email('email_critico', '').strip().lower()
        fallback = self._config_email('email_destinatarios', [])

        for obra_id, obra in obras.items():
            contrato = (obra['info'].get('cliente') or '').strip()
            presentes = self._categorias_presentes(obra)
            cobertas = set()

            for usuario in usuarios:
                if usuario['is_admin']:
                    if usuario['recebe_critico']:
                        conceder(usuario['email'], usuario['nome'], obra_id, CATEGORIAS_CRITICAS, False)
                        cobertas |= CATEGORIAS_CRITICAS
                    continue
                if contrato and contrato in usuario['contratos']:
                    categorias = TODAS_CATEGORIAS if usuario['recebe_critico'] else CATEGORIAS_REITERACAO
                    conceder(usuario['email'], usuario['nome'], obra_id, categorias, True)
                    cobertas |= categorias

            if email_critico:
                conceder(email_critico, '', obra_id, CATEGORIAS_CRITICAS, False)

            descobertas = presentes - cobertas
            for email in fallback:
                conceder(email, '', obra_id, descobertas, True)

        return {
            email: {'nome': perm['nome'], 'resumido': not perm['coordena'], 'obras': perm['obras']}
            for email, perm in permissoes.items()
        }

    @staticmethod
    def _categorias_presentes(obra: Dict) -> set:
        presentes = {cat for cat, lista in obra['tarefas'].items() if lista}
        if obra.get('com_pendencias'):
            presentes.add('pendencias')
        return presentes

    @staticmethod
    def _gravidade_obra(obra: Dict):
        """Chave de ordenação: obras com crítico/pendência primeiro, depois mais tarefas."""
        tarefas = obra['tarefas']
        critica = bool(tarefas.get('critico_atrasado') or tarefas.get('tipo_b') or obra.get('com_pendencias'))
        total = sum(len(lista) for lista in tarefas.values())
        return (0 if critica else 1, -total, str(obra['info'].get('nome_contrato') or ''))

    def _montar_resumos(self, obras: Dict[int, Dict], permissoes: Dict[str, Dict]) -> Dict[str, Dict]:
        """Filtra as obras/tarefas de cada destinatário conforme as permissões.

        Retorna {email: {'nome', 'resumido', 'obras': [obra filtrada, ordenada por gravidade]}}.
        Destinatários sem nenhum item ficam de fora.
        """
        resumos = {}
        for email, perm in permissoes.items():
            obras_email = []
            for obra_id, categorias in perm['obras'].items():
                obra = obras[obra_id]
                tarefas = {
                    cat: list(lista)
                    for cat, lista in obra['tarefas'].items()
                    if lista and cat in categorias
                }
                com_pendencias = bool(obra.get('com_pendencias')) and 'pendencias' in categorias
                if not tarefas and not com_pendencias:
                    continue
                obras_email.append({
                    'obra_id': obra_id,
                    'info': obra['info'],
                    'tarefas': tarefas,
                    'com_pendencias': com_pendencias,
                })
            if obras_email:
                obras_email.sort(key=self._gravidade_obra)
                resumos[email] = {'nome': perm['nome'], 'resumido': perm['resumido'], 'obras': obras_email}
        return resumos

    def _nome_fuso_horario(self) -> str:
        """Retorna nome amigável da timezone atual."""
        return getattr(self.fuso_horario, 'key', self.fuso_horario.tzname(None) or str(self.fuso_horario))

    def iniciar_verificacao(self):
        """Inicia thread de verificação periódica de prazos (singleton global)"""
        global _notificador_ativo

        with _notificador_lock:
            if _notificador_ativo:
                # Já existe um notificador ativo, não inicia outro
                return

            _notificador_ativo = True
            self.executando = True

            agora = self._agora_referencia()
            hoje = agora.date()
            horario_alvo = self._horario_alvo_no_dia(hoje)
            ja_executou = self._ja_executou_hoje(hoje)
            eh_dia_util = self._eh_dia_util(hoje)

            print(
                "🔔 Sistema de notificação de prazos iniciado "
                f"({self.hora_disparo:02d}:{self.minuto_disparo:02d}, seg-sex, tz={self._nome_fuso_horario()})!"
            )

            thread = threading.Thread(target=self._verificar_loop, daemon=True)
            thread.start()

    def verificar_agora(self, forcar: bool = False):
        """Executa verificação manual de prazos

        Args:
            forcar: Se True, ignora verificação de última execução e força o envio
        """
        if forcar:
            print("🔄 Verificação manual FORÇADA de prazos...")
            return self._executar_ciclo_diario(origem='manual-forcada')
        else:
            if self._ja_executou_hoje(self._hoje_referencia()):
                print("ℹ️ Verificação já foi executada hoje. Use forcar=True para executar de qualquer forma.")
                return False
            print("🔄 Executando verificação manual de prazos...")
            return self._executar_ciclo_diario(origem='manual')

    def _agora_referencia(self) -> datetime.datetime:
        """Retorna data/hora atual timezone-aware da operação de notificações."""
        return datetime.datetime.now(self.fuso_horario)

    def _hoje_referencia(self) -> datetime.date:
        """Retorna data atual da timezone de referência."""
        return self._agora_referencia().date()

    def _eh_dia_util(self, data: datetime.date) -> bool:
        """Retorna True para segunda a sexta-feira."""
        return data.weekday() < 5

    def _horario_alvo_no_dia(self, data: datetime.date) -> datetime.datetime:
        """Retorna datetime timezone-aware do horário alvo no dia informado."""
        return datetime.datetime.combine(
            data,
            datetime.time(self.hora_disparo, self.minuto_disparo),
            tzinfo=self.fuso_horario,
        )

    def _proximo_horario_execucao(self, agora: datetime.datetime = None) -> datetime.datetime:
        """Calcula próximo horário útil de execução (seg-sex às HH:MM)."""
        agora = agora or self._agora_referencia()
        alvo_hoje = self._horario_alvo_no_dia(agora.date())

        if self._eh_dia_util(agora.date()) and agora < alvo_hoje:
            return alvo_hoje

        proxima_data = agora.date() + datetime.timedelta(days=1)
        while not self._eh_dia_util(proxima_data):
            proxima_data += datetime.timedelta(days=1)

        return self._horario_alvo_no_dia(proxima_data)

    def _deve_executar_neste_momento(self, agora: datetime.datetime = None) -> bool:
        """Decide se o ciclo diário deve rodar agora."""
        agora = agora or self._agora_referencia()
        hoje = agora.date()

        if not self._eh_dia_util(hoje):
            return False

        if self._ja_executou_hoje(hoje):
            return False

        horario_alvo = self._horario_alvo_no_dia(hoje)
        if agora < horario_alvo:
            return False

        if agora > horario_alvo and not self.habilitar_catchup:
            return False

        # Após falhas repetidas, desiste do dia e aguarda o próximo horário agendado.
        if self._falhas_por_dia.get(hoje, 0) >= self.max_tentativas_dia:
            return False

        return True

    def _aguardar_ate(self, instante_alvo: datetime.datetime):
        """Aguarda até o instante informado com interrupções curtas."""
        while self.executando:
            agora = self._agora_referencia()
            segundos_restantes = (instante_alvo - agora).total_seconds()
            if segundos_restantes <= 0:
                return

            intervalo = min(60, int(segundos_restantes))
            if intervalo <= 0:
                intervalo = 1
            time.sleep(intervalo)

    def _executar_ciclo_diario(self, origem: str = 'agendado') -> bool:
        """Executa ciclo diário completo de verificação e registro."""
        try:
            alertas = self._verificar_prazos()
            self._registrar_execucao(alertas, 'concluida')
            print(f"✅ Verificação diária concluída ({origem}).")
            return True
        except Exception as e:
            print(f"❌ Erro ao verificar prazos ({origem}): {e}")
            self._registrar_execucao(0, 'erro', str(e))
            return False

    def _verificar_loop(self):
        """Loop principal: executa em dias úteis às 08:00 (timezone configurada)."""
        while self.executando:
            agora = self._agora_referencia()
            hoje = agora.date()
            horario_alvo = self._horario_alvo_no_dia(hoje)

            if self._deve_executar_neste_momento(agora):
                origem = 'catch-up' if agora > horario_alvo else 'agendado'
                if origem == 'catch-up':
                    print(f"[CATCH-UP] Executando em modo catch-up às {agora.strftime('%H:%M:%S')} (horário alvo: {horario_alvo.strftime('%H:%M:%S')})")
                if self._executar_ciclo_diario(origem=origem):
                    continue

                # Falhou: espera o intervalo antes de tentar de novo, em vez de repetir em loop.
                falhas = self._falhas_por_dia.get(hoje, 0) + 1
                self._falhas_por_dia = {hoje: falhas}
                if falhas < self.max_tentativas_dia:
                    nova_tentativa = self._agora_referencia() + self.intervalo_retry
                    print(f"[RETRY] Tentativa {falhas}/{self.max_tentativas_dia} falhou. Nova tentativa às {nova_tentativa.strftime('%H:%M:%S')}")
                    self._aguardar_ate(nova_tentativa)
                else:
                    print(f"[RETRY] {falhas} tentativas falharam hoje. Verificação suspensa até o próximo horário agendado.")
                continue

            proximo_horario = self._proximo_horario_execucao(agora)

            if self._ja_executou_hoje(hoje):
                print(f"[JA EXECUTOU] Verificacao realizada em {hoje.strftime('%d/%m/%Y')}")
                print(f"[PRÓX. EXEC] {proximo_horario.strftime('%d/%m/%Y %H:%M:%S')}")
            else:
                print(f"[PRÓX. EXEC] {proximo_horario.strftime('%d/%m/%Y %H:%M:%S')}")

            segundos = int((proximo_horario - agora).total_seconds())
            if segundos > 0:
                self._aguardar_ate(proximo_horario)

    def _verificar_prazos(self) -> int:
        """Ciclo diário: coleta alertas, envia UM resumo por destinatário e registra resultados.

        Retorna o total de tarefas em alerta no dia.
        """
        obras, resumos = self.gerar_resumos_do_dia()
        total_tarefas = sum(
            len(lista) for obra in obras.values() for lista in obra['tarefas'].values()
        )
        if not obras:
            return 0

        entregas_tarefas, entregas_pendencias, erros = self._enviar_resumos(resumos)
        self._registrar_resultados(obras, resumos, entregas_tarefas, entregas_pendencias, erros)

        enviados = len(resumos) - len(erros)
        print(
            f"\n📧 {enviados}/{len(resumos)} resumo(s) diário(s) enviado(s) — "
            f"{len(obras)} obra(s), {total_tarefas} tarefa(s) em alerta\n"
        )
        for email, msg in erros.items():
            print(f"   ❌ {email}: {msg}")

        return total_tarefas

    def gerar_resumos_do_dia(self):
        """Monta os resumos do dia SEM enviar nem gravar nada no banco.

        Returns:
            (obras, resumos) — obras: {obra_id: {info, tarefas, com_pendencias}};
            resumos: {email: {nome, resumido, obras: [...]}}.
        """
        obras = self._coletar_alertas()
        if not obras:
            return obras, {}

        try:
            usuarios = self._carregar_usuarios_alerta()
        except Exception as e:
            log_error(e, "notificador_prazos", "Carregar usuários para o resumo diário")
            usuarios = []

        permissoes = self._mapear_permissoes(obras, usuarios)
        return obras, self._montar_resumos(obras, permissoes)

    @staticmethod
    def _nova_obra(info: Dict) -> Dict:
        return {
            'info': {
                'nome_contrato': info.get('nome_contrato'),
                'cliente': info.get('cliente'),
                'observacoes': info.get('observacoes'),
            },
            'tarefas': {
                'reiteracao_1': [],
                'reiteracao_2': [],
                'reiteracao_3': [],
                'critico_atrasado': [],
                'tipo_b': [],
            },
            'com_pendencias': False,
        }

    def _coletar_alertas(self) -> Dict[int, Dict]:
        """Lê tarefas em alerta e obras com pendências (somente leitura, com retry de 'locked')."""
        max_tentativas = 3
        for tentativa in range(max_tentativas):
            conn = None
            try:
                conn = self.database.get_connection()
                cursor = conn.cursor()
                hoje = self._hoje_referencia()

                cursor.execute('''
                    SELECT oc.*, o.nome_contrato, o.cliente, o.observacoes, ct.possui_reiteracao, ct.tipo_recorrencia
                    FROM obra_checklist oc
                    JOIN obras o ON oc.obra_id = o.id
                    LEFT JOIN checklist_templates ct ON oc.template_id = ct.id
                    WHERE oc.concluido = 0 AND oc.bloqueado = 0
                    AND oc.data_limite IS NOT NULL
                    ORDER BY oc.data_limite
                ''')
                tarefas = [dict(row) for row in cursor.fetchall()]

                obras: Dict[int, Dict] = {}
                for tarefa in tarefas:
                    try:
                        data_limite = datetime.datetime.strptime(tarefa['data_limite'], '%Y-%m-%d').date()
                        dias_diff = (hoje - data_limite).days

                        if tarefa['tipo'] == 'A':
                            # Tipo A: com reiterações (2, 4, 6 dias, depois crítico diário)
                            alerta = self._processar_tipo_a(cursor, tarefa, dias_diff)
                        else:
                            # Tipo B: prazo fixo (último dia e atrasada: crítico diário)
                            alerta = self._processar_tipo_b(cursor, tarefa, dias_diff)

                        if alerta:
                            alerta['novo'] = (tarefa.get('status_notificacao') or 'pendente') == 'pendente'
                            obra = obras.setdefault(tarefa['obra_id'], self._nova_obra(tarefa))
                            obra['tarefas'][alerta['tipo_alerta']].append(alerta)
                    except Exception as e:
                        print(f"⚠️ Erro ao processar tarefa {tarefa.get('id')}: {e}")
                        continue

                # Obras concluídas com pendências entram no mesmo resumo (alerta diário)
                cursor.execute(
                    'SELECT id, nome_contrato, cliente, observacoes FROM obras WHERE status_conclusao_obra = ?',
                    ('com_pendencias',),
                )
                for row in cursor.fetchall():
                    obra_pend = dict(row)
                    obra = obras.setdefault(obra_pend['id'], self._nova_obra(obra_pend))
                    obra['com_pendencias'] = True

                return obras

            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and tentativa < max_tentativas - 1:
                    print(f"⚠️ Banco de dados temporariamente bloqueado, tentando novamente em 5 segundos... (tentativa {tentativa + 1}/{max_tentativas})")
                    time.sleep(5)
                    continue
                # Propaga: o ciclo registra erro e o loop agenda nova tentativa
                raise
            finally:
                if conn:
                    conn.close()

        return {}

    def _enviar_resumos(self, resumos: Dict[str, Dict]):
        """Envia um e-mail individual por destinatário.

        Returns:
            (entregas_tarefas {tarefa_id: [emails ok]},
             entregas_pendencias {obra_id: [emails ok]},
             erros {email: mensagem})
        """
        hoje = self._hoje_referencia()
        entregas_tarefas: Dict[int, List[str]] = {}
        entregas_pendencias: Dict[int, List[str]] = {}
        erros: Dict[str, str] = {}

        for email, resumo in resumos.items():
            try:
                assunto, corpo_html = self.email_service.criar_email_resumo_diario(
                    resumo['nome'], resumo['obras'], hoje, resumo['resumido']
                )
                sucesso, msg = self.email_service.enviar_email(email, assunto, corpo_html)
            except Exception as e:
                log_error(e, "notificador_prazos", f"Enviar resumo diário para {email}")
                sucesso, msg = False, str(e)

            if not sucesso:
                erros[email] = msg or 'Falha no envio'
                continue

            for obra in resumo['obras']:
                for lista in obra['tarefas'].values():
                    for alerta in lista:
                        entregas_tarefas.setdefault(alerta['tarefa_id'], []).append(email)
                if obra['com_pendencias']:
                    entregas_pendencias.setdefault(obra['obra_id'], []).append(email)

        return entregas_tarefas, entregas_pendencias, erros

    def _registrar_resultados(self, obras: Dict[int, Dict], resumos: Dict[str, Dict],
                              entregas_tarefas: Dict[int, List[str]],
                              entregas_pendencias: Dict[int, List[str]],
                              erros: Dict[str, str]):
        """Atualiza controle das tarefas e histórico.

        A tarefa conta como notificada se PELO MENOS UM destinatário recebeu o resumo.
        """
        # Quem deveria receber cada item (para registrar falhas com destinatários e motivo)
        previstos_tarefa: Dict[int, List[str]] = {}
        previstos_pendencia: Dict[int, List[str]] = {}
        for email, resumo in resumos.items():
            for obra in resumo['obras']:
                for lista in obra['tarefas'].values():
                    for alerta in lista:
                        previstos_tarefa.setdefault(alerta['tarefa_id'], []).append(email)
                if obra['com_pendencias']:
                    previstos_pendencia.setdefault(obra['obra_id'], []).append(email)

        def motivo_falha(previstos: List[str]) -> str:
            return '; '.join(f"{e}: {erros.get(e, 'não enviado')}" for e in previstos)

        sem_destinatario = []
        for obra_id, obra in obras.items():
            nome_obra = obra['info'].get('nome_contrato')

            for tipo_alerta, lista in obra['tarefas'].items():
                for alerta in lista:
                    tarefa_id = alerta['tarefa_id']
                    entregues = entregas_tarefas.get(tarefa_id, [])
                    previstos = previstos_tarefa.get(tarefa_id, [])

                    if entregues:
                        if 'nova_tentativa' in alerta:
                            self._atualizar_tarefa_com_retry(
                                tarefa_id, alerta['nova_tentativa'], alerta['hoje_str'], alerta['status']
                            )
                        else:
                            self._atualizar_tarefa_tipo_b_com_retry(
                                tarefa_id, alerta['hoje_str'], alerta['status']
                            )
                        self._registrar_historico_com_retry(obra_id, tarefa_id, tipo_alerta, entregues, True)
                    elif previstos:
                        self._registrar_historico_com_retry(
                            obra_id, tarefa_id, tipo_alerta, previstos, False, motivo_falha(previstos)
                        )
                    else:
                        sem_destinatario.append(f"{nome_obra} / {alerta.get('descricao')}")

            if obra.get('com_pendencias'):
                entregues = entregas_pendencias.get(obra_id, [])
                previstos = previstos_pendencia.get(obra_id, [])
                if entregues:
                    self._registrar_historico_com_retry(obra_id, 0, 'obra_pendencias', entregues, True)
                elif previstos:
                    self._registrar_historico_com_retry(
                        obra_id, 0, 'obra_pendencias', previstos, False, motivo_falha(previstos)
                    )
                else:
                    sem_destinatario.append(f"{nome_obra} (pendências)")

        if sem_destinatario:
            print(f"⚠️ {len(sem_destinatario)} alerta(s) sem destinatário:")
            for item in sem_destinatario:
                print(f"   - {item}")

    def _processar_tipo_a(self, cursor, tarefa: Dict, dias_diff: int):
        """Processa notificação para tarefa Tipo A (com reiterações)

        Returns:
            Dict com dados do alerta se deve enviar, None caso contrário
        """
        tentativas = tarefa['tentativas_reiteracao'] or 0
        ultima_notif = tarefa['ultima_notificacao']
        tipo_recorrencia = tarefa.get('tipo_recorrencia', 'padrao')

        # Se ainda não passou do prazo, não faz nada
        if dias_diff < 0:
            return None

        agora = self._agora_referencia()
        hoje_str = agora.strftime('%Y-%m-%d %H:%M:%S')
        hoje_data_str = agora.strftime('%Y-%m-%d')

        # Verifica se já enviou hoje (compara apenas a data)
        if ultima_notif:
            # Extrai apenas a data do campo ultima_notificacao (pode ter hora ou não)
            data_ultima_notif = ultima_notif.split(' ')[0] if ' ' in ultima_notif else ultima_notif
            if data_ultima_notif == hoje_data_str:
                return None

        deve_enviar = False
        tipo_alerta = None
        nova_tentativa = tentativas

        # Reiterações por LIMITE (não por dia exato): se o ciclo não rodou no dia
        # certo (fim de semana, falha de envio), a reiteração sai no próximo dia útil,
        # já no estágio correto. Tarefas muito atrasadas seguem como crítico diário.
        if tipo_recorrencia == 'confirmacao':
            # CONFIRMAÇÃO DE MEDIÇÃO vence no dia 10: reitera em +1 e +2 dias, crítico a partir de +3.
            # Usa dias desde o vencimento (e não o dia do mês) para não silenciar
            # confirmações de meses anteriores ainda em aberto.
            if dias_diff >= 3:
                deve_enviar = True
                nova_tentativa = 3
                tipo_alerta = 'critico_atrasado'
            elif dias_diff >= 2 and tentativas <= 1:
                deve_enviar = True
                nova_tentativa = 2
                tipo_alerta = 'reiteracao_2'
            elif dias_diff >= 1 and tentativas == 0:
                deve_enviar = True
                nova_tentativa = 1
                tipo_alerta = 'reiteracao_1'
        else:
            # Padrão: reiterações 2, 4 e 6 dias após o prazo; depois crítico diário
            if dias_diff > 6:
                deve_enviar = True
                tipo_alerta = 'critico_atrasado'
            else:
                estagio = 3 if dias_diff >= 6 else 2 if dias_diff >= 4 else 1 if dias_diff >= 2 else 0
                if estagio > (tentativas or 0):
                    deve_enviar = True
                    nova_tentativa = estagio
                    tipo_alerta = f'reiteracao_{estagio}'

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
        agora = self._agora_referencia()
        hoje_str = agora.strftime('%Y-%m-%d %H:%M:%S')
        hoje_data_str = agora.strftime('%Y-%m-%d')

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

    def _ja_executou_hoje(self, data_referencia: datetime.date = None) -> bool:
        """Verifica se a verificação de prazos já foi executada na data de referência."""
        try:
            conn = self.database.get_connection()
            cursor = conn.cursor()

            data_referencia = data_referencia or self._hoje_referencia()
            hoje = data_referencia.strftime('%Y-%m-%d')
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
        """Registra a execução na data da timezone de referência."""
        try:
            conn = self.database.get_connection()
            cursor = conn.cursor()

            agora_ref = self._agora_referencia()
            hoje = agora_ref.strftime('%Y-%m-%d')
            agora = agora_ref.strftime('%Y-%m-%d %H:%M:%S')

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
                        time.sleep(0.5)
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

                data_envio = self._agora_referencia().strftime('%Y-%m-%d %H:%M:%S')

                # Converte a lista de destinatários em string para armazenamento
                if isinstance(destinatarios, (list, tuple, set)):
                    destinatarios_str = ", ".join(destinatarios)
                else:
                    destinatarios_str = str(destinatarios or '')

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
                        time.sleep(0.5)
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
                        time.sleep(0.5)
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
