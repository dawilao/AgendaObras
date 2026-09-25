"""Reutiliza sessão, usuários e contratos do AgendaObras."""
from nicegui import app
from services.auth_service import verificar_autenticacao
from db.auth_repo import AuthDatabase
from db.contratos_repo import ContratosDatabase
from db.seguro_repo import SeguroRepository


def usuario_atual():
    if not verificar_autenticacao():
        raise PermissionError('Entre no portal para consultar o seguro.')
    user = AuthDatabase().obter_usuario_por_id(app.storage.user.get('user_id'))
    if not user:
        raise PermissionError('Sessão inválida.')
    return user


class SeguroService:
    def __init__(self, db_name, usuario_provider=usuario_atual, contratos_provider=None, tipo='obra'):
        self.repo = SeguroRepository(db_name,tipo)
        self.tipo=tipo
        self.usuario_provider = usuario_provider
        self.contratos_provider = contratos_provider or (lambda uid: ContratosDatabase().listar_contratos_usuario(uid))
        self.owner = usuario_provider()['id']

    def autorizar(self, obra_id, escrita=False):
        user = self.usuario_provider()
        if user['id'] != self.owner:
            raise PermissionError('A sessão mudou. Reabra a obra.')
        conn = self.repo.get_connection()
        try:
            obra = conn.execute('SELECT cliente FROM obras WHERE id=?', (obra_id,)).fetchone()
        finally:
            conn.close()
        if not obra:
            raise ValueError('Obra não encontrada.')
        if not user.get('is_admin') and obra['cliente'].strip() not in {c.strip() for c in self.contratos_provider(user['id'])}:
            raise PermissionError('Sem acesso a esta obra.')
        if escrita and not user.get('pode_validar_seguro'):
            raise PermissionError('Usuário sem autorização para validar seguro ou boleto.')
        return user

    def obter(self, obra_id):
        user = self.autorizar(obra_id)
        return self.repo.obter(obra_id), bool(user.get('pode_validar_seguro'))

    def alterar(self, obra_id, campo, valor, revisao):
        user = self.autorizar(obra_id, escrita=True)
        self.repo.alterar(obra_id, campo, valor, user, revisao)

    def registrar_etapa(self, obra_id, acao, dados, revisao):
        user = self.autorizar(obra_id, escrita=True)
        self.repo.registrar_etapa(obra_id, acao, dados, user, revisao)

    def registrar_leitura(self, obra_id, leitura):
        user=self.autorizar(obra_id, escrita=True)
        self.repo.registrar_leitura(obra_id,leitura,user)


def definir_permissao_seguro(user_id, valor):
    user = usuario_atual()
    if not user.get('is_admin'):
        raise PermissionError('Somente administrador pode autorizar validadores.')
    if type(valor) is not bool:
        raise ValueError('Permissão inválida.')
    db = AuthDatabase()
    conn = db.get_connection()
    try:
        conn.execute('UPDATE usuarios SET pode_validar_seguro=? WHERE id=?', (int(valor),user_id))
        conn.commit()
    finally:
        conn.close()
