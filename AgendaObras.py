from nicegui import ui
from agenda_obras import AgendaObras
import sys
import os

# Corrige paths quando executável
if getattr(sys, 'frozen', False):
    application_path = sys._MEIPASS
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

@ui.page('/')
def index():
    AgendaObras()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='AgendaObras - Rastreador de Obras',
        native=False,
        reload=True,
        language='pt-BR',
        favicon='🏗️',
        binding_refresh_interval=0.1,
    )
