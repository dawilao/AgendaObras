"""
Página principal do AgendaObras.
Atualmente delega para a classe AgendaObras existente enquanto os sub-componentes
(ObraCard, ObraDialogs, AdminDialogs) não estão completamente separados.
"""

from agenda_obras import AgendaObras as _AgendaObras


class MainPage:
    """Entry point da interface principal. Instancia AgendaObras."""

    def __init__(self):
        _AgendaObras()
