from nicegui import ui
from agenda_obras import AgendaObras

@ui.page('/')
def index():
    AgendaObras()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='AgendaObras - Rastreador de Obras',
        port=8080,
        native=False,
        reload=True,
        language='pt-BR',
        favicon='🏗️',
    )
