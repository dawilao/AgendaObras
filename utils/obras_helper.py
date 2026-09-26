"""
Módulo com funções auxiliares para operações relacionadas a obras.
Contém métodos utilitários para formatação e cálculos.
"""

import datetime
from typing import List, Dict
from core.error_logger import log_error

GRADE_TABS = [
    ('todos', 'Todos'),
    ('em_andamento', 'Em Andamento'),
    ('atrasado', 'Atrasado'),
    ('concluido', 'Concluído'),
]

KANBAN_COLUNAS = [
    ('nao_iniciada', 'Não iniciada', 'gray', 'hourglass_empty'),
    ('em_andamento', 'Em andamento', 'orange', 'schedule'),
    ('atrasada', 'Atrasada', 'red', 'warning'),
    ('concluido', 'Concluído', 'green', 'check_circle'),
]


class ObrasHelper:
    @staticmethod
    def nome_usuario(usuario: Dict) -> str:
        return f"{usuario.get('nome') or ''} {usuario.get('sobrenome') or ''}".strip() or (usuario.get('email') or '')

    @staticmethod
    def montar_contexto_coordenadores(usuarios: List[Dict], vinculos: List[Dict]):
        """Retorna (usuarios_por_id, vinculados_por_contrato) para resolver coordenadores sem
        consultar os bancos a cada card. Admins acessam todos os contratos e não contam como vinculados."""
        usuarios_por_id = {u['id']: u for u in usuarios}
        vinculados_por_contrato: Dict[str, List[str]] = {}
        for vinculo in vinculos:
            usuario = usuarios_por_id.get(vinculo['usuario_id'])
            if not usuario or usuario.get('is_admin'):
                continue
            contrato = (vinculo['contrato_nome'] or '').strip()
            vinculados_por_contrato.setdefault(contrato, []).append(ObrasHelper.nome_usuario(usuario))
        for nomes in vinculados_por_contrato.values():
            nomes.sort(key=str.casefold)
        return usuarios_por_id, vinculados_por_contrato

    @staticmethod
    def resolver_coordenador(obra: Dict, usuarios_por_id: Dict, vinculados_por_contrato: Dict):
        """Retorna (texto, automatico). Responsável definido na obra tem prioridade; senão,
        os usuários vinculados ao contrato. texto é None quando não há ninguém."""
        coordenador = usuarios_por_id.get(obra.get('coordenador_id'))
        if coordenador:
            return ObrasHelper.nome_usuario(coordenador), False
        nomes = vinculados_por_contrato.get((obra.get('cliente') or '').strip(), [])
        return (', '.join(nomes) if nomes else None), True

    @staticmethod
    def formatar_valor(valor: float) -> str:
        """Formata valor para moeda brasileira"""
        try:
            return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        except Exception as e:
            log_error(e, "obras_helper", f"Formatar valor: {valor}")
            return f"R$ {valor}"

    @staticmethod
    def calcular_progresso(checklist: List[Dict]) -> int:
        """Calcula percentual de progresso do checklist"""
        if not checklist:
            return 0
        concluidos = sum(1 for item in checklist if item['concluido'])
        return int((concluidos / len(checklist)) * 100)

    @staticmethod
    def calcular_dias_restantes(data_limite: str) -> int:
        """Calcula dias restantes até o prazo"""
        try:
            data_limite_obj = datetime.datetime.strptime(data_limite, '%Y-%m-%d').date()
            hoje = datetime.date.today()
            delta = (data_limite_obj - hoje).days
            return delta
        except Exception as e:
            log_error(e, "obras_helper", f"Calcular dias restantes - data_limite: {data_limite}")
            return 0

    @staticmethod
    def calcular_dias_uteis_restantes(data_limite: str) -> int:
        """Calcula dias úteis restantes até o prazo (ignora sábados e domingos)."""
        try:
            data_limite_obj = datetime.datetime.strptime(data_limite, '%Y-%m-%d').date()
            hoje = datetime.date.today()

            if data_limite_obj == hoje:
                return 0

            passo = 1 if data_limite_obj > hoje else -1
            data_cursor = hoje
            dias_uteis = 0

            while data_cursor != data_limite_obj:
                data_cursor += datetime.timedelta(days=passo)
                if data_cursor.weekday() < 5:
                    dias_uteis += passo

            return dias_uteis
        except Exception as e:
            log_error(e, "obras_helper", f"Calcular dias úteis restantes - data_limite: {data_limite}")
            return 0

    @staticmethod
    def obter_status_visual(obra: Dict, checklist: List[Dict]) -> tuple:
        """Retorna cor e ícone baseado no status da obra"""
        try:
            progresso = ObrasHelper.calcular_progresso(checklist)

            # Verifica se foi finalizada com pendências
            status_conclusao = (obra.get('status_conclusao_obra') or '').strip().lower()
            if status_conclusao == 'com_pendencias':
                return ('orange', 'warning', '⚠️ Concluída com Pendências')
            elif status_conclusao == 'sem_pendencias':
                return ('green', 'check_circle', 'Concluído')

            if progresso == 100:
                return ('orange', 'schedule', 'Pronta para concluir')

            # Verifica se há tarefas atrasadas
            hoje = datetime.date.today().strftime('%Y-%m-%d')
            atrasadas = [item for item in checklist
                         if not item['concluido'] and item['data_limite'] and item['data_limite'] < hoje]

            if atrasadas:
                return ('red', 'warning', 'Atrasada')
            elif progresso > 0:
                return ('orange', 'schedule', 'Em Andamento')
            else:
                return ('gray', 'hourglass_empty', 'Não Iniciada')
        except Exception as e:
            log_error(e, "obras_helper", f"Obter status visual - obra_id: {obra.get('id', 'N/A')}")
            return ('gray', 'error', 'Erro')

    @staticmethod
    def obter_bucket_grade(status_texto: str) -> str:
        """Mapeia status_texto para uma das 3 abas de filtro da Grade."""
        if status_texto == 'Atrasada':
            return 'atrasado'
        if status_texto in ('Concluído', 'Concluída com Pendências'):
            return 'concluido'
        return 'em_andamento'  # Não Iniciada, Em Andamento, Pronta para concluir

    @staticmethod
    def paginar(itens: List, pagina: int, por_pagina: int) -> tuple:
        """Fatia a lista para a página pedida, ajustando-a ao intervalo válido.

        Retorna (itens_da_pagina, pagina_ajustada, total_paginas, inicio).
        """
        total_paginas = max(1, -(-len(itens) // por_pagina))
        pagina = min(max(1, pagina), total_paginas)
        inicio = (pagina - 1) * por_pagina
        return itens[inicio:inicio + por_pagina], pagina, total_paginas, inicio

    @staticmethod
    def obter_bucket_kanban(status_texto: str) -> str:
        """Mapeia status_texto para uma das 4 colunas fixas do Kanban."""
        if status_texto == 'Não Iniciada':
            return 'nao_iniciada'
        if status_texto == 'Atrasada':
            return 'atrasada'
        if status_texto in ('Concluído', 'Concluída com Pendências'):
            return 'concluido'
        return 'em_andamento'  # Em Andamento, Pronta para concluir

    # ========== FASE 3 - FUNÇÕES FINANCEIRAS ========== #
    @staticmethod
    def obter_cor_percentual(percentual: float) -> str:
        """Retorna cor baseada no percentual faturado (Fase 3 - Financeiro)"""
        if percentual >= 75:
            return 'green'
        elif percentual >= 50:
            return 'blue'
        elif percentual >= 25:
            return 'orange'
        else:
            return 'red'

    @staticmethod
    def obter_status_faturamento(percentual: float) -> str:
        """Retorna status descritivo do faturamento (Fase 3 - Financeiro)"""
        if percentual >= 100:
            return '✓ Faturado 100%'
        elif percentual >= 75:
            return '✓ Faturado 75%+'
        elif percentual >= 50:
            return '○ Faturado 50%+'
        elif percentual >= 25:
            return '◐ Faturado 25%+'
        elif percentual > 0:
            return '◑ Iniciado'
        else:
            return '◕ Não iniciado'
