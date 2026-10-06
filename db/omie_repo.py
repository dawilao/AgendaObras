"""Financeiro Omie no banco de obras: vínculo obra ↔ projeto, consultas guardadas e auditoria."""
import json
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from core.config import OMIE_LOTES_MANTIDOS
from db.connection import BaseRepository

EM_CONFERENCIA = 'em_conferencia'
CONFERIDO = 'conferido'


def criar_schema(conn):
    conn.execute('SAVEPOINT omie_schema')
    try:
        _criar_schema(conn)
        conn.execute('RELEASE SAVEPOINT omie_schema')
    except Exception:
        conn.execute('ROLLBACK TO SAVEPOINT omie_schema')
        conn.execute('RELEASE SAVEPOINT omie_schema')
        raise


def _criar_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS omie_vinculos (
        obra_id INTEGER PRIMARY KEY REFERENCES obras(id),
        codigo_projeto INTEGER NOT NULL UNIQUE,
        nome_projeto TEXT NOT NULL,
        ic_na_confirmacao TEXT,
        estado TEXT NOT NULL DEFAULT 'em_conferencia' CHECK(estado IN ('em_conferencia','conferido')),
        confirmado_por INTEGER, confirmado_por_nome TEXT, confirmado_em TEXT NOT NULL,
        conferido_por INTEGER, conferido_por_nome TEXT, conferido_em TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS omie_lotes (
        id INTEGER PRIMARY KEY, obra_id INTEGER NOT NULL, consultado_em TEXT NOT NULL,
        inicio TEXT, fim TEXT, status TEXT NOT NULL CHECK(status IN ('ok','erro')),
        motivo TEXT, payload_json TEXT)""")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_omie_lotes_obra ON omie_lotes(obra_id, status, id)')
    conn.execute("""CREATE TABLE IF NOT EXISTS financeiro_auditoria (
        id INTEGER PRIMARY KEY, quando TEXT NOT NULL, usuario_id INTEGER, usuario_nome TEXT,
        acao TEXT NOT NULL, obra_id INTEGER, detalhe_json TEXT)""")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_fin_auditoria_obra ON financeiro_auditoria(obra_id, id)')


def criar_schema_parceiros(conn):
    conn.execute('SAVEPOINT omie_parceiros_schema')
    try:
        # Fornecedor: só código, nome e documento já mascarado (nunca o documento completo).
        conn.execute("""CREATE TABLE IF NOT EXISTS omie_fornecedores (
            codigo INTEGER PRIMARY KEY, nome TEXT NOT NULL, documento_mascarado TEXT, consultado_em TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS obra_parceiros (
            obra_id INTEGER NOT NULL, fornecedor_codigo INTEGER NOT NULL,
            papel TEXT NOT NULL CHECK(papel IN ('parceiro','outro')),
            validado_por INTEGER, validado_por_nome TEXT, validado_em TEXT NOT NULL,
            PRIMARY KEY (obra_id, fornecedor_codigo))""")
        conn.execute('RELEASE SAVEPOINT omie_parceiros_schema')
    except Exception:
        conn.execute('ROLLBACK TO SAVEPOINT omie_parceiros_schema')
        conn.execute('RELEASE SAVEPOINT omie_parceiros_schema')
        raise


PARCEIRO = 'parceiro'
OUTRO = 'outro'


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _autor(user) -> tuple:
    user = user or {}
    nome = f"{user.get('nome') or ''} {user.get('sobrenome') or ''}".strip() or user.get('email') or ''
    return user.get('id'), nome


def registrar_auditoria(conn, user, acao: str, obra_id: Optional[int] = None, detalhe: Optional[Dict] = None):
    """Grava uma ação em financeiro_auditoria na transação de conn (o chamador faz o commit)."""
    uid, nome = _autor(user)
    conn.execute('INSERT INTO financeiro_auditoria(quando,usuario_id,usuario_nome,acao,obra_id,detalhe_json) '
                 'VALUES(?,?,?,?,?,?)',
                 (agora(), uid, nome, acao, obra_id,
                  json.dumps(detalhe, ensure_ascii=False) if detalhe else None))


class OmieRepository(BaseRepository):

    # ---------- auditoria ----------
    def _registrar(self, conn, user, acao: str, obra_id: Optional[int] = None, detalhe: Optional[Dict] = None):
        registrar_auditoria(conn, user, acao, obra_id, detalhe)

    def registrar_acao(self, user, acao: str, obra_id: Optional[int] = None, detalhe: Optional[Dict] = None):
        conn = self.get_connection()
        try:
            self._registrar(conn, user, acao, obra_id, detalhe)
            conn.commit()
        finally:
            conn.close()

    def auditoria(self, obra_id: Optional[int] = None, limite: int = 50) -> List[Dict]:
        conn = self.get_connection()
        try:
            if obra_id is None:
                rows = conn.execute('SELECT * FROM financeiro_auditoria ORDER BY id DESC LIMIT ?', (limite,))
            else:
                rows = conn.execute('SELECT * FROM financeiro_auditoria WHERE obra_id=? ORDER BY id DESC LIMIT ?',
                                    (obra_id, limite))
            return [{**dict(r), 'detalhe': json.loads(r['detalhe_json']) if r['detalhe_json'] else {}}
                    for r in rows]
        finally:
            conn.close()

    # ---------- vínculos ----------
    def vinculo(self, obra_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT * FROM omie_vinculos WHERE obra_id=?', (obra_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def vinculos(self, obra_ids: Optional[Iterable[int]] = None) -> List[Dict]:
        conn = self.get_connection()
        try:
            rows = [dict(r) for r in conn.execute('SELECT * FROM omie_vinculos ORDER BY obra_id')]
        finally:
            conn.close()
        if obra_ids is not None:
            ids = {int(i) for i in obra_ids}
            rows = [r for r in rows if r['obra_id'] in ids]
        return rows

    def _validar_projeto_livre(self, conn, obra_id: int, codigo_projeto: int):
        if int(codigo_projeto) <= 0:
            raise ValueError('Código de projeto inválido.')
        outro = conn.execute('SELECT obra_id FROM omie_vinculos WHERE codigo_projeto=? AND obra_id<>?',
                             (int(codigo_projeto), obra_id)).fetchone()
        if outro:
            raise ValueError('Este projeto do Omie já está ligado a outra obra.')

    def _gravar_vinculo(self, conn, obra_id, codigo_projeto, nome_projeto, ic, user):
        """Devolve (ação, vínculo anterior); ação None quando nada mudou."""
        nome_projeto = (nome_projeto or '').strip()
        if not nome_projeto:
            raise ValueError('Informe o nome do projeto do Omie.')
        self._validar_projeto_livre(conn, obra_id, codigo_projeto)
        ic = (ic or '').strip() or None
        uid, nome = _autor(user)
        anterior = conn.execute('SELECT codigo_projeto, nome_projeto, ic_na_confirmacao FROM omie_vinculos '
                                'WHERE obra_id=?', (obra_id,)).fetchone()
        anterior = dict(anterior) if anterior else None
        if anterior and anterior['codigo_projeto'] == int(codigo_projeto):
            if anterior['nome_projeto'] == nome_projeto and anterior['ic_na_confirmacao'] == ic:
                return None, anterior
            # Mesmo projeto (renomeado no Omie ou IC corrigido): as consultas continuam valendo.
            conn.execute('UPDATE omie_vinculos SET nome_projeto=?, ic_na_confirmacao=?, confirmado_por=?, '
                         'confirmado_por_nome=?, confirmado_em=? WHERE obra_id=?',
                         (nome_projeto, ic, uid, nome, agora(), obra_id))
            return 'vinculo_reconfirmado', anterior
        # Projeto novo: as consultas do anterior deixam de valer e a obra volta à conferência.
        conn.execute('DELETE FROM omie_lotes WHERE obra_id=?', (obra_id,))
        conn.execute('DELETE FROM omie_vinculos WHERE obra_id=?', (obra_id,))
        conn.execute('INSERT INTO omie_vinculos(obra_id,codigo_projeto,nome_projeto,ic_na_confirmacao,estado,'
                     'confirmado_por,confirmado_por_nome,confirmado_em) VALUES(?,?,?,?,?,?,?,?)',
                     (obra_id, int(codigo_projeto), nome_projeto, ic, EM_CONFERENCIA, uid, nome, agora()))
        return ('vinculo_trocado' if anterior else 'vinculo_criado'), anterior

    def salvar_vinculo(self, obra_id: int, codigo_projeto: int, nome_projeto: str, ic: Optional[str], user) -> bool:
        conn = self.get_connection()
        try:
            acao, anterior = self._gravar_vinculo(conn, obra_id, codigo_projeto, nome_projeto, ic, user)
            if acao is None:
                return False
            self._registrar(conn, user, acao, obra_id,
                            {'codigo_projeto': int(codigo_projeto), 'projeto': nome_projeto,
                             **({'anterior': anterior['nome_projeto']} if anterior else {})})
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def salvar_vinculos_em_lote(self, itens: List[Dict], user) -> int:
        """Tudo ou nada: um projeto repetido ou já usado por outra obra cancela o lote inteiro."""
        codigos = [int(i['codigo_projeto']) for i in itens]
        if len(codigos) != len(set(codigos)) or len({i['obra_id'] for i in itens}) != len(itens):
            raise ValueError('O mesmo projeto ou a mesma obra aparece mais de uma vez na seleção.')
        conn = self.get_connection()
        try:
            gravados = 0
            for item in itens:
                acao, _ = self._gravar_vinculo(conn, item['obra_id'], item['codigo_projeto'],
                                               item['nome_projeto'], item.get('ic'), user)
                if acao is not None:
                    gravados += 1
            self._registrar(conn, user, 'vinculo_em_lote', None,
                            {'obras': [i['obra_id'] for i in itens], 'gravados': gravados})
            conn.commit()
            return gravados
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def desfazer_vinculo(self, obra_id: int, user) -> bool:
        conn = self.get_connection()
        try:
            atual = conn.execute('SELECT nome_projeto FROM omie_vinculos WHERE obra_id=?', (obra_id,)).fetchone()
            if not atual:
                return False
            conn.execute('DELETE FROM omie_lotes WHERE obra_id=?', (obra_id,))
            conn.execute('DELETE FROM omie_vinculos WHERE obra_id=?', (obra_id,))
            self._registrar(conn, user, 'vinculo_desfeito', obra_id, {'projeto': atual['nome_projeto']})
            conn.commit()
            return True
        finally:
            conn.close()

    def marcar_conferido(self, obra_id: int, user) -> bool:
        conn = self.get_connection()
        try:
            if not conn.execute("SELECT 1 FROM omie_lotes WHERE obra_id=? AND status='ok'", (obra_id,)).fetchone():
                raise ValueError('Atualize a obra do Omie antes de marcar como conferida.')
            uid, nome = _autor(user)
            cur = conn.execute("UPDATE omie_vinculos SET estado=?, conferido_por=?, conferido_por_nome=?, conferido_em=? "
                               "WHERE obra_id=? AND estado<>?", (CONFERIDO, uid, nome, agora(), obra_id, CONFERIDO))
            if not cur.rowcount:
                return False
            self._registrar(conn, user, 'lote_conferido', obra_id)
            conn.commit()
            return True
        finally:
            conn.close()

    # ---------- consultas guardadas ----------
    def gravar_lote(self, obra_id: int, status: str, inicio: Optional[str], fim: Optional[str],
                    dados: Optional[Dict] = None, motivo: Optional[str] = None,
                    consultado_em: Optional[str] = None) -> int:
        if status not in ('ok', 'erro'):
            raise ValueError('Situação de consulta inválida.')
        payload = json.dumps(dados, ensure_ascii=False) if status == 'ok' else None
        conn = self.get_connection()
        try:
            cur = conn.execute('INSERT INTO omie_lotes(obra_id,consultado_em,inicio,fim,status,motivo,payload_json) '
                               'VALUES(?,?,?,?,?,?,?)',
                               (obra_id, consultado_em or agora(), inicio, fim, status, motivo, payload))
            self._reter(conn, obra_id)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    @staticmethod
    def _reter(conn, obra_id: int):
        # Pelo menos 2: a consulta anterior é usada para mostrar o que mudou.
        manter = max(2, OMIE_LOTES_MANTIDOS)
        for status in ('ok', 'erro'):
            conn.execute('DELETE FROM omie_lotes WHERE obra_id=? AND status=? AND id NOT IN '
                         '(SELECT id FROM omie_lotes WHERE obra_id=? AND status=? ORDER BY id DESC LIMIT ?)',
                         (obra_id, status, obra_id, status, manter))

    @staticmethod
    def _lote(row) -> Optional[Dict]:
        if not row:
            return None
        lote = dict(row)
        lote['dados'] = json.loads(lote.pop('payload_json')) if lote.get('payload_json') else None
        return lote

    def ultimo_lote(self, obra_id: int, status: Optional[str] = None) -> Optional[Dict]:
        conn = self.get_connection()
        try:
            if status:
                row = conn.execute('SELECT * FROM omie_lotes WHERE obra_id=? AND status=? ORDER BY id DESC LIMIT 1',
                                   (obra_id, status)).fetchone()
            else:
                row = conn.execute('SELECT * FROM omie_lotes WHERE obra_id=? ORDER BY id DESC LIMIT 1',
                                   (obra_id,)).fetchone()
            return self._lote(row)
        finally:
            conn.close()

    def lotes_ok(self, obra_id: int, limite: int = 2) -> List[Dict]:
        """Consultas válidas mais recentes primeiro."""
        conn = self.get_connection()
        try:
            rows = conn.execute("SELECT * FROM omie_lotes WHERE obra_id=? AND status='ok' ORDER BY id DESC LIMIT ?",
                                (obra_id, limite)).fetchall()
            return [self._lote(r) for r in rows]
        finally:
            conn.close()

    def situacao(self, obra_id: int) -> Dict:
        """Vínculo, última consulta válida, a válida anterior e o erro mais recente que ela (se houver)."""
        vinculo = self.vinculo(obra_id)
        if not vinculo:
            return {'vinculo': None, 'lote': None, 'anterior': None, 'erro': None}
        lotes = self.lotes_ok(obra_id, 2)
        ultimo = self.ultimo_lote(obra_id)
        erro = ultimo if ultimo and ultimo['status'] == 'erro' else None
        return {'vinculo': vinculo, 'lote': lotes[0] if lotes else None,
                'anterior': lotes[1] if len(lotes) > 1 else None, 'erro': erro}

    # ---------- fornecedores e parceiros ----------
    def fornecedores(self, codigos: Optional[Iterable[int]] = None) -> Dict[int, Dict]:
        conn = self.get_connection()
        try:
            rows = [dict(r) for r in conn.execute('SELECT * FROM omie_fornecedores')]
        finally:
            conn.close()
        por_codigo = {r['codigo']: r for r in rows}
        if codigos is not None:
            pedidos = {int(c) for c in codigos if c is not None}
            por_codigo = {c: r for c, r in por_codigo.items() if c in pedidos}
        return por_codigo

    def salvar_fornecedores(self, encontrados: Dict[int, Dict]):
        """encontrados: {codigo: {'nome', 'documento_mascarado'}}."""
        if not encontrados:
            return
        conn = self.get_connection()
        try:
            for codigo, f in encontrados.items():
                conn.execute('INSERT INTO omie_fornecedores(codigo,nome,documento_mascarado,consultado_em) '
                             'VALUES(?,?,?,?) ON CONFLICT(codigo) DO UPDATE SET nome=excluded.nome, '
                             'documento_mascarado=excluded.documento_mascarado, consultado_em=excluded.consultado_em',
                             (int(codigo), f['nome'], f.get('documento_mascarado'), agora()))
            conn.commit()
        finally:
            conn.close()

    def parceiros_da_obra(self, obra_id: int) -> Dict[int, Dict]:
        conn = self.get_connection()
        try:
            rows = conn.execute('SELECT * FROM obra_parceiros WHERE obra_id=?', (obra_id,)).fetchall()
            return {r['fornecedor_codigo']: dict(r) for r in rows}
        finally:
            conn.close()

    def validar_parceiro(self, obra_id: int, codigo: int, papel: str, user, nome: str = '') -> bool:
        """Marca o fornecedor como parceiro da obra ou outro prestador. False quando nada mudou."""
        if papel not in (PARCEIRO, OUTRO):
            raise ValueError('Papel inválido.')
        if codigo is None or int(codigo) <= 0:
            raise ValueError('Fornecedor sem código no Omie: não é possível validar.')
        uid, autor = _autor(user)
        conn = self.get_connection()
        try:
            atual = conn.execute('SELECT papel FROM obra_parceiros WHERE obra_id=? AND fornecedor_codigo=?',
                                 (obra_id, int(codigo))).fetchone()
            if atual and atual['papel'] == papel:
                return False
            conn.execute('INSERT INTO obra_parceiros(obra_id,fornecedor_codigo,papel,validado_por,validado_por_nome,'
                         'validado_em) VALUES(?,?,?,?,?,?) ON CONFLICT(obra_id, fornecedor_codigo) DO UPDATE SET '
                         'papel=excluded.papel, validado_por=excluded.validado_por, '
                         'validado_por_nome=excluded.validado_por_nome, validado_em=excluded.validado_em',
                         (obra_id, int(codigo), papel, uid, autor, agora()))
            self._registrar(conn, user, 'parceiro_alterado' if atual else 'parceiro_validado', obra_id,
                            {'fornecedor': int(codigo), 'nome': nome, 'papel': papel})
            conn.commit()
            return True
        finally:
            conn.close()

    def desfazer_validacao(self, obra_id: int, codigo: int, user, nome: str = '') -> bool:
        conn = self.get_connection()
        try:
            cur = conn.execute('DELETE FROM obra_parceiros WHERE obra_id=? AND fornecedor_codigo=?',
                               (obra_id, int(codigo)))
            if not cur.rowcount:
                return False
            self._registrar(conn, user, 'parceiro_desfeito', obra_id, {'fornecedor': int(codigo), 'nome': nome})
            conn.commit()
            return True
        finally:
            conn.close()

    def contar_lotes(self, obra_id: int, status: str) -> int:
        conn = self.get_connection()
        try:
            return conn.execute('SELECT COUNT(*) FROM omie_lotes WHERE obra_id=? AND status=?',
                                (obra_id, status)).fetchone()[0]
        finally:
            conn.close()
