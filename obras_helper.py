"""
Módulo com funções auxiliares para operações relacionadas a obras.
Contém métodos utilitários para formatação e cálculos.
"""

import datetime
from typing import List, Dict


class ObrasHelper:
    @staticmethod
    def formatar_valor(valor: float) -> str:
        """Formata valor para moeda brasileira"""
        return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    
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
        data_limite_obj = datetime.datetime.strptime(data_limite, '%Y-%m-%d').date()
        hoje = datetime.date.today()
        delta = (data_limite_obj - hoje).days
        return delta
    
    @staticmethod
    def obter_status_visual(obra: Dict, checklist: List[Dict]) -> tuple:
        """Retorna cor e ícone baseado no status da obra"""
        progresso = ObrasHelper.calcular_progresso(checklist)
        
        if progresso == 100:
            return ('green', 'check_circle', 'Concluída')
        
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
