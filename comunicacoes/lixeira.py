"""Lixeira dos arquivos do Histórico da equipe: 15 dias para restaurar, depois exclusão definitiva.

Excluir um arquivo numa conversa do histórico marca o anexo no histórico e nas caixas pessoais que
têm a mesma mensagem (mesma identificação de publicação). O banco nunca perde a linha do anexo: só as
marcas trashed_at/purged_at mudam. Na exclusão definitiva, o conteúdo sai do disco se nenhum anexo
ativo, em nenhuma caixa, usar o mesmo arquivo.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .espaco import OrphanScanError, release
from .publishing import publication_fingerprint
from .store import now

TRASH_DAYS = 15
SYSTEM_ACTOR = 'sistema:lixeira'
_FINGERPRINT_FIELDS = 'id, message_id, subject, sender, sent_date, body'


class Lixeira:
    def __init__(self, shared, personal_stores):
        """personal_stores: função que devolve as caixas pessoais (usuários novos entram a cada chamada)."""
        self.shared = shared
        self.personal_stores = personal_stores
        self.problem = None  # Motivo da última vez que o disco não pôde ser liberado.

    def stores(self):
        return [self.shared, *self.personal_stores()]

    def send(self, message_ids, sha, actor, actor_name='', protected=frozenset()):
        """Manda para a lixeira o arquivo `sha` das mensagens `message_ids` do histórico.
        Primeiro lê tudo (histórico e caixas pessoais); só depois grava: uma caixa ilegível
        interrompe antes de qualquer mudança."""
        if sha in protected:
            raise ValueError('Este arquivo está registrado como apólice ou boleto no controle de seguro. '
                             'Troque o documento no seguro antes de excluí-lo.')
        ids = [int(mid) for mid in message_ids]
        found = self._shared_copies(self.shared, ids, sha)
        if not found:
            raise ValueError('Este arquivo não está mais disponível nesta conversa. Atualize a lista.')
        personal = [(store, self._personal_copies(store, found, sha)) for store in self.personal_stores()]
        at = now()
        expires = (datetime.fromisoformat(at) + timedelta(days=TRASH_DAYS)).isoformat(timespec='seconds')
        with self.shared.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Conferido de novo sob a trava: outro admin pode ter excluído o arquivo neste meio tempo.
            found = self._shared_copies(db, ids, sha)
            if not found:
                raise ValueError('Este arquivo não está mais disponível nesta conversa. Atualize a lista.')
            trash_id = db.execute('''INSERT INTO trash(sha256,names,size,obra_id,subject,deleted_by,deleted_by_name,
                deleted_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?,?,'lixeira')''',
                (sha, json.dumps(sorted({r['name'] for r in found}), ensure_ascii=False), found[0]['size'],
                 found[0]['obra_id'], found[0]['subject'], actor, actor_name, at, expires)).lastrowid
            self._mark(db, trash_id, at, sha, sorted({r['id'] for r in found}), actor)
        for store, mids in personal:
            if mids:
                with store.connect() as db:
                    self._mark(db, trash_id, at, sha, mids, actor)
        return trash_id

    @staticmethod
    def _shared_copies(source, ids, sha):
        marks = ','.join('?' for _ in ids)
        query = f'''SELECT m.id, m.fingerprint, m.subject, m.obra_id, a.name, a.size
            FROM attachments a JOIN messages m ON m.id=a.message_id
            WHERE a.sha256=? AND a.trashed_at IS NULL AND m.id IN ({marks})'''
        if isinstance(source, sqlite3.Connection):
            return source.execute(query, (sha, *ids)).fetchall()
        with source.connect() as db:
            return db.execute(query, (sha, *ids)).fetchall()

    @staticmethod
    def _personal_copies(store, found, sha):
        """Mensagens da caixa pessoal que são as mesmas do histórico e ainda têm o arquivo ativo.
        Só as de mesmo assunto têm a identificação calculada; caixa no formato antigo (anexos dentro
        do banco, sem sha256) não usa os arquivos em disco e fica de fora."""
        fingerprints = {r['fingerprint'] for r in found}
        subjects = sorted({r['subject'] for r in found})
        marks = ','.join('?' for _ in subjects)
        try:
            with store.connect() as db:
                if 'sha256' not in {r[1] for r in db.execute('PRAGMA table_info(attachments)')}:
                    return []
                messages = {r['id']: dict(r) for r in db.execute(
                    f'SELECT {_FINGERPRINT_FIELDS} FROM messages WHERE subject IN ({marks})', subjects)}
                if not messages:
                    return []
                ids = ','.join('?' for _ in messages)
                attachments = {}
                for r in db.execute(f'''SELECT id,message_id,name,mime,size,sha256,trashed_at FROM attachments
                                        WHERE message_id IN ({ids})''', list(messages)):
                    attachments.setdefault(r['message_id'], []).append(dict(r))
        except sqlite3.Error as error:
            raise ValueError(f'Não foi possível conferir a caixa pessoal {store.path} ({error}). '
                             'Nada foi excluído.') from error
        return sorted(mid for mid, message in messages.items()
                      if publication_fingerprint(message, attachments.get(mid, [])) in fingerprints
                      and any(a['sha256'] == sha and a['trashed_at'] is None for a in attachments.get(mid, [])))

    @staticmethod
    def _mark(db, trash_id, at, sha, mids, actor):
        marks = ','.join('?' for _ in mids)
        db.execute(f'''UPDATE attachments SET trash_id=?, trashed_at=? WHERE sha256=? AND trashed_at IS NULL
                   AND message_id IN ({marks})''', (trash_id, at, sha, *mids))
        db.executemany('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                       [(mid, at, actor, 'lixeira', f'Arquivo {sha[:12]}… na lixeira {trash_id}.') for mid in mids])

    def items(self, when=None):
        """Arquivos na lixeira, do mais recente para o mais antigo, com os dias restantes."""
        moment = when or datetime.now(timezone.utc)
        with self.shared.connect() as db:
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM trash WHERE status='lixeira' ORDER BY deleted_at DESC, id DESC")]
        for row in rows:
            row['names'] = json.loads(row['names'])
            left = datetime.fromisoformat(row['expires_at']) - moment
            row['days_left'] = max(0, left.days + (1 if left.seconds else 0))
        return rows

    def item(self, trash_id):
        with self.shared.connect() as db:
            row = db.execute("SELECT * FROM trash WHERE id=? AND status='lixeira'", (trash_id,)).fetchone()
        if not row:
            raise ValueError('Este arquivo não está mais na lixeira. Atualize a lista.')
        return dict(row)

    def restore(self, trash_id, actor):
        self._close(trash_id, actor, 'restaurado')
        for store in self.stores():
            with store.connect() as db:
                mids = [r[0] for r in db.execute(
                    'SELECT DISTINCT message_id FROM attachments WHERE trash_id=? AND purged_at IS NULL', (trash_id,))]
                db.execute('UPDATE attachments SET trash_id=NULL, trashed_at=NULL WHERE trash_id=? AND purged_at IS NULL',
                           (trash_id,))
                db.executemany('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                               [(mid, now(), actor, 'restauracao', f'Arquivo restaurado da lixeira {trash_id}.')
                                for mid in mids])

    def purge(self, trash_id, actor):
        """Exclusão definitiva. Devolve quantos arquivos saíram do disco (0 se ficou para depois)."""
        # Fecha o item antes de marcar as caixas: se cair no meio, purge_expired completa as marcas.
        sha = self._close(trash_id, actor, 'excluido')
        self._mark_purged([trash_id])
        return self.free_disk({sha})

    def _mark_purged(self, trash_ids):
        at = now()
        marks = ','.join('?' for _ in trash_ids)
        for store in self.stores():
            with store.connect() as db:
                db.execute(f'UPDATE attachments SET purged_at=? WHERE purged_at IS NULL AND trash_id IN ({marks})',
                           (at, *trash_ids))

    def purge_expired(self, when=None):
        """Rotina diária: exclui o que venceu, completa exclusões interrompidas e tenta de novo liberar o
        disco do que ficou para depois. Devolve (itens vencidos, arquivos liberados)."""
        moment = (when or datetime.now(timezone.utc)).isoformat(timespec='seconds')
        with self.shared.connect() as db:
            expired = [r[0] for r in db.execute(
                "SELECT id FROM trash WHERE status='lixeira' AND expires_at<=?", (moment,))]
            closed = db.execute("SELECT id, sha256 FROM trash WHERE status='excluido'").fetchall()
        for trash_id in expired:
            try:
                self._close(trash_id, SYSTEM_ACTOR, 'excluido')
            except ValueError:
                pass  # Restaurado ou excluído por outra sessão enquanto a rotina rodava.
        # Todas as exclusões fechadas: marcar de novo é inofensivo e completa as que caíram no meio.
        with self.shared.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM trash WHERE status='excluido'")]
        if ids:
            self._mark_purged(ids)
        shas = {r['sha256'] for r in closed} | self._shas(expired)
        # Só o que ainda está no disco precisa de nova tentativa.
        return len(expired), self.free_disk({sha for sha in shas if self.shared.blobs.exists(sha)})

    def _shas(self, trash_ids):
        if not trash_ids:
            return set()
        marks = ','.join('?' for _ in trash_ids)
        with self.shared.connect() as db:
            return {r[0] for r in db.execute(
                f"SELECT sha256 FROM trash WHERE status='excluido' AND id IN ({marks})", trash_ids)}

    def free_disk(self, shas):
        """Conteúdos sem uso saem do disco. Qualquer dúvida (banco ou manifesto ilegível) adia para a
        próxima rodada; o motivo fica em self.problem para a rotina registrar."""
        self.problem = None
        if not shas:
            return 0
        try:
            return release(self.shared.blobs, shas, [store.path for store in self.stores()])
        except OrphanScanError as error:
            self.problem = f'Disco não liberado: {error}.'
            return 0

    def _close(self, trash_id, actor, status):
        with self.shared.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT sha256 FROM trash WHERE id=? AND status='lixeira'", (trash_id,)).fetchone()
            if not row:
                raise ValueError('Este arquivo não está mais na lixeira. Atualize a lista.')
            db.execute('UPDATE trash SET status=?, closed_by=?, closed_at=? WHERE id=?',
                       (status, actor, now(), trash_id))
        return row['sha256']
