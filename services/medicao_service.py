"""
Identificação das tarefas de medição (MEDIÇÃO e CONFIRMAÇÃO DE MEDIÇÃO) do checklist.
Sem dependências de UI ou DB.
"""

PREFIXO_MEDICAO = 'MEDIÇÃO '
PREFIXO_CONFIRMACAO = 'CONFIRMAÇÃO DE MEDIÇÃO '


def eh_tarefa_medicao(descricao: str) -> bool:
    """Tarefas exibidas no campo Medições do checklist (e não na lista principal)."""
    descricao = descricao or ''
    return descricao.startswith(PREFIXO_MEDICAO) or descricao.startswith(PREFIXO_CONFIRMACAO)
