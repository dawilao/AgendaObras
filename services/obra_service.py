"""
Serviço de obras — funções de orquestração com dependências de DB e ObrasHelper.
Extraídas de agenda_obras.py.
"""

from typing import Dict, List

from utils.obras_helper import ObrasHelper
from utils.formatters import STATUS_VISUAL_EDICAO_OPTIONS


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
