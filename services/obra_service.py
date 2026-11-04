"""
Serviço de obras — funções de orquestração com dependências de DB e ObrasHelper.
Extraídas de agenda_obras.py.
"""

from typing import Dict, List, NamedTuple, Optional, Tuple

from utils.obras_helper import ObrasHelper
from utils.formatters import STATUS_VISUAL_EDICAO_OPTIONS, status_edicao_para_banco

STATUS_CONCLUSAO_VALIDOS = {'sem_pendencias', 'com_pendencias'}


class EstadoConclusao(NamedTuple):
    """Retrato da obra usado para decidir quando oferecer o pop-up de finalização."""
    concluida: bool
    medicoes_ok: bool
    tarefas_100: bool


def status_visual_para_edicao(obra: Dict, checklist: List[Dict]) -> str:
    """Converte o status visual do card para o valor exibido no select de edição."""
    _, _, status_texto = ObrasHelper.obter_status_visual(obra, checklist)
    if status_texto in STATUS_VISUAL_EDICAO_OPTIONS:
        return status_texto

    status_salvo = (obra.get('status') or '').strip()
    if status_salvo in STATUS_VISUAL_EDICAO_OPTIONS:
        return status_salvo

    return 'Não Iniciada'


def obra_tem_medicoes_concluidas(db, obra_id: int) -> bool:
    """Indica se a obra já concluiu todas as medições e ainda não foi finalizada."""
    obra = db.obter_obra(obra_id) or {}
    status_conclusao = (obra.get('status_conclusao_obra') or '').strip().lower()
    if status_conclusao in {'sem_pendencias', 'com_pendencias'}:
        return False
    return db.verificar_todas_medicoes_concluidas(obra_id)


def acao_status_edicao(status_select: str, status_conclusao_atual: Optional[str]) -> Optional[str]:
    """Traduz a escolha do select de Status (card de edição) na ação sobre a conclusão da obra.

    Retorna 'concluir_sem', 'concluir_com', 'reabrir' ou None (nada a fazer).
    """
    escolha = (status_select or '').strip()
    atual = (status_conclusao_atual or '').strip().lower()
    if escolha == 'Concluído':
        return None if atual == 'sem_pendencias' else 'concluir_sem'
    if escolha == 'Concluída com Pendências':
        return None if atual == 'com_pendencias' else 'concluir_com'
    if escolha and atual in STATUS_CONCLUSAO_VALIDOS:
        return 'reabrir'
    return None


def resolver_status_edicao(status_select: str, obra_antiga: Optional[Dict],
                           checklist: List[Dict]) -> Tuple[str, Optional[str]]:
    """Decide o status a gravar e a ação de conclusão ao salvar o card de edição.

    Se o select ainda mostra o valor derivado do banco (o usuário não mexeu nele),
    o status do banco é mantido e nada é concluído/reaberto. Isso evita que uma obra
    legada 'Concluída' (sem finalização registrada), exibida como "Pronta para concluir",
    seja reaberta só por salvar outro campo.

    Retorna (status_banco, acao) com acao em 'concluir_sem', 'concluir_com', 'reabrir' ou None.
    """
    obra_antiga = obra_antiga or {}
    escolha = (status_select or '').strip()
    status_banco_atual = (obra_antiga.get('status') or '').strip()

    if escolha == status_visual_para_edicao(obra_antiga, checklist or []):
        return (status_banco_atual or status_edicao_para_banco(escolha), None)

    conclusao_atual = (obra_antiga.get('status_conclusao_obra') or '').strip().lower()
    acao = acao_status_edicao(escolha, conclusao_atual)
    if acao == 'concluir_com' and not conclusao_atual:
        # Só vira 'Concluída' quando o pop-up de pendências for confirmado
        status = status_banco_atual if status_banco_atual and status_banco_atual != 'Concluída' else 'Em Andamento'
        return (status, acao)
    return (status_edicao_para_banco(escolha), acao)


def estado_conclusao(db, obra_id: int) -> EstadoConclusao:
    """Lê do banco se a obra está concluída, se as medições acabaram e se todas as tarefas acabaram."""
    obra = db.obter_obra(obra_id) or {}
    checklist = db.obter_checklist(obra_id) or []
    concluida = (obra.get('status_conclusao_obra') or '').strip().lower() in STATUS_CONCLUSAO_VALIDOS
    return EstadoConclusao(
        concluida=concluida,
        medicoes_ok=db.verificar_todas_medicoes_concluidas(obra_id),
        tarefas_100=bool(checklist) and ObrasHelper.calcular_progresso(checklist) == 100,
    )


def deve_oferecer_conclusao(antes: Optional[EstadoConclusao], depois: EstadoConclusao) -> bool:
    """Oferece a finalização quando a obra (não concluída) acaba de fechar as medições
    ou acaba de chegar a 100% das tarefas, qualquer que tenha sido a última tarefa."""
    if depois.concluida or not depois.medicoes_ok:
        return False
    if antes is None:
        return False
    fechou_medicoes = not antes.medicoes_ok
    fechou_tarefas = depois.tarefas_100 and not antes.tarefas_100
    return fechou_medicoes or fechou_tarefas


def usuario_pode_acessar_contrato(contratos_db, usuario: Dict, contrato_nome: str) -> bool:
    """Valida se o usuário logado pode acessar um contrato específico."""
    if bool(usuario.get('is_admin')):
        return True

    user_id = usuario.get('id')
    if not user_id:
        return False

    contratos_vinculados = set(contratos_db.listar_contratos_usuario(user_id))
    contrato_normalizado = (contrato_nome or '').strip()
    return contrato_normalizado in contratos_vinculados
