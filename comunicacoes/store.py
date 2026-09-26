"""Persistência isolada, procedência de importação e revisão auditável."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .blobs import BlobStore, default_root
from .matching import clean_ic, match_message
from .parser import parse_message


# trashed_at: na lixeira; purged_at: excluído de vez (o conteúdo pode ter saído do disco).
TRASH_COLUMNS = ('trash_id INTEGER', 'trashed_at TEXT', 'purged_at TEXT')
ACTIVE = 'trashed_at IS NULL'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class MailStore:
    def __init__(self, path, files_root=None):
        self.path = str(Path(path).resolve())
        self.blobs = BlobStore(files_root or default_root())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS works (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, ic TEXT NOT NULL DEFAULT '',
                    aliases TEXT NOT NULL, confirmed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, message_id TEXT,
                    subject TEXT, sender TEXT, recipients TEXT, cc TEXT, sent_date TEXT,
                    body TEXT, refs TEXT, status TEXT NOT NULL, obra_id TEXT REFERENCES works(id),
                    suggestion TEXT, reason TEXT, created TEXT, reviewed INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS idx_mid ON messages(message_id);
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY, message_id INTEGER REFERENCES messages(id),
                    name TEXT, mime TEXT, sha256 TEXT NOT NULL, size INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sources (
                    mailbox TEXT, folder TEXT, validity TEXT, uid TEXT,
                    message_id INTEGER REFERENCES messages(id), note TEXT,
                    subject TEXT, sender TEXT, sent_date TEXT, size INTEGER,
                    PRIMARY KEY(mailbox, folder, validity, uid));
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, message_id INTEGER, at TEXT, actor TEXT,
                    action TEXT, details TEXT);
                CREATE TABLE IF NOT EXISTS mail_folders (
                    mailbox TEXT, name TEXT, flags TEXT, PRIMARY KEY(mailbox, name));
                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY, started TEXT, finished TEXT, status TEXT, detail TEXT);
                CREATE TABLE IF NOT EXISTS trash (
                    id INTEGER PRIMARY KEY, sha256 TEXT NOT NULL, names TEXT NOT NULL, size INTEGER,
                    obra_id TEXT, subject TEXT, deleted_by TEXT, deleted_by_name TEXT, deleted_at TEXT,
                    expires_at TEXT, status TEXT NOT NULL, closed_by TEXT, closed_at TEXT);
            ''')
            # Lixeira: o anexo é marcado, nunca apagado do banco. Ids ficam estáveis para o
            # Seguro e a identificação da publicação continua batendo entre as caixas.
            columns = {r[1] for r in db.execute('PRAGMA table_info(attachments)')}
            for column in TRASH_COLUMNS:
                if column.split()[0] not in columns:
                    db.execute(f'ALTER TABLE attachments ADD COLUMN {column}')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def works(self):
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM works ORDER BY name')]
        for row in rows:
            row['aliases'] = json.loads(row['aliases'])
        return rows

    def save_work(self, wid, name, ic, aliases, confirmed, actor):
        if not wid or not name.strip() or not actor:
            raise ValueError('Obra e responsável são obrigatórios.')
        ic = clean_ic(ic) if ic.strip() else ''
        if confirmed and not ic:
            raise ValueError('Confirme um IC completo antes de ativar a vinculação automática.')
        with self.connect() as db:
            old = db.execute('SELECT * FROM works WHERE id=?', (str(wid),)).fetchone()
            db.execute('''INSERT INTO works VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                       name=excluded.name, ic=excluded.ic, aliases=excluded.aliases,
                       confirmed=excluded.confirmed''',
                       (str(wid), name.strip(), ic, json.dumps(aliases), int(confirmed)))
            db.execute('INSERT INTO audit(at,actor,action,details) VALUES(?,?,?,?)',
                       (now(), actor, 'cadastro_obra', json.dumps({'before': dict(old) if old else None,
                         'after': {'id': str(wid), 'name': name, 'ic': ic, 'confirmed': confirmed}}, ensure_ascii=False)))

    def _known(self, fingerprint, source):
        with self.connect() as db:
            return bool(db.execute('SELECT 1 FROM sources WHERE mailbox=? AND folder=? AND validity=? AND uid=?', source).fetchone()
                        or db.execute('SELECT 1 FROM messages WHERE fingerprint=?', (fingerprint,)).fetchone())

    def _store_attachments(self, parsed):
        return [(a['name'], a['type'], *self.blobs.put(a['data'])) for a in parsed['attachments']]

    def import_message(self, raw, source, actor='importacao'):
        parsed = parse_message(raw)
        works = self.works()
        # Anexos vão ao disco (com compactação) antes de travar o banco para escrita.
        # Numa corrida, o pior caso é um arquivo sem referência, que o compactar --orfaos remove.
        stored = None if self._known(parsed['key'], source) else self._store_attachments(parsed)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing_source = db.execute('SELECT message_id FROM sources WHERE mailbox=? AND folder=? AND validity=? AND uid=?', source).fetchone()
            if existing_source:
                return existing_source['message_id'], False
            existing = db.execute('SELECT id FROM messages WHERE fingerprint=?', (parsed['key'],)).fetchone()
            fresh = existing is None
            if existing:
                mid = existing['id']
            else:
                refs = set()
                for reference in parsed['references']:
                    refs.update(r[0] for r in db.execute(
                        "SELECT DISTINCT obra_id FROM messages WHERE message_id=? AND status='vinculado' AND obra_id IS NOT NULL",
                        (reference,)))
                match = match_message(parsed['subject'], parsed['body'], works, refs)
                if parsed['message_id'] and db.execute('SELECT 1 FROM messages WHERE message_id=?', (parsed['message_id'],)).fetchone():
                    match.status, match.obra_id, match.reason = 'conflito', None, 'Message-ID repetido com conteúdo diferente.'
                cur = db.execute('''INSERT INTO messages(fingerprint,message_id,subject,sender,recipients,cc,
                         sent_date,body,refs,status,obra_id,suggestion,reason,created)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                         (parsed['key'], parsed['message_id'], parsed['subject'], parsed['sender'],
                          parsed['recipients'], parsed['cc'], parsed['date'], parsed['body'],
                          json.dumps(parsed['references']), match.status, match.obra_id,
                          match.suggestion, match.reason, now()))
                mid = cur.lastrowid
                # Conteúdo fica no disco (uma cópia por sha256); o banco guarda só metadados.
                if stored is None:  # Visto como já importado na checagem prévia; garante os arquivos.
                    stored = self._store_attachments(parsed)
                db.executemany('INSERT INTO attachments(message_id,name,mime,sha256,size) VALUES(?,?,?,?,?)',
                               [(mid, *item) for item in stored])
                db.execute('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                           (mid, now(), actor, 'importacao', match.reason))
            db.execute('INSERT INTO sources(mailbox,folder,validity,uid,message_id,note) VALUES(?,?,?,?,?,?)',
                       (*source, mid, 'Importada'))
            return mid, fresh

    def seen(self, source):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM sources WHERE mailbox=? AND folder=? AND validity=? AND uid=?', source).fetchone() is not None

    def skip(self, source, reason, info=None):
        info = info or {}
        with self.connect() as db:
            db.execute('''INSERT OR IGNORE INTO sources(mailbox,folder,validity,uid,message_id,note,
                       subject,sender,sent_date,size) VALUES(?,?,?,?,NULL,?,?,?,?,?)''',
                       (*source, reason, info.get('subject'), info.get('sender'), info.get('date'), info.get('size')))

    def skipped(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM sources WHERE message_id IS NULL')]

    def review(self, mid, wid, actor, note):
        if not actor or not note.strip():
            raise ValueError('Registre o motivo da decisão.')
        with self.connect() as db:
            old = db.execute('SELECT status,obra_id FROM messages WHERE id=?', (mid,)).fetchone()
            if not old:
                raise ValueError('Mensagem não encontrada.')
            if wid and not db.execute('SELECT 1 FROM works WHERE id=?', (wid,)).fetchone():
                raise ValueError('Obra não cadastrada.')
            status = 'vinculado' if wid else 'ignorado'
            db.execute('UPDATE messages SET status=?,obra_id=?,reason=?,reviewed=1 WHERE id=?',
                       (status, wid, note.strip(), mid))
            db.execute('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                       (mid, now(), actor, 'revisao', json.dumps({'before': dict(old), 'after':
                         {'status': status, 'obra_id': wid}, 'note': note}, ensure_ascii=False)))

    def messages(self, status=None, work=None):
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('''SELECT m.id,m.subject,m.sender,m.sent_date,m.status,
                m.obra_id,m.suggestion,m.reason,w.name AS work_name,
                (SELECT COUNT(*) FROM attachments a WHERE a.message_id=m.id AND a.trashed_at IS NULL) AS attachment_count
                FROM messages m LEFT JOIN works w ON w.id=m.obra_id
                WHERE (? IS NULL OR m.status=?) AND (? IS NULL OR m.obra_id=?)
                ORDER BY m.id DESC''', (status, status, work, work))]
        def chronological(row):
            try:
                dt = parsedate_to_datetime(row['sent_date'])
                return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).timestamp(), row['id']
            except (ValueError, TypeError, OverflowError):
                return 0, row['id']
        return sorted(rows, key=chronological, reverse=True)

    def reprocess(self, actor):
        works = self.works()
        with self.connect() as db:
            rows = db.execute('SELECT * FROM messages WHERE reviewed=0 ORDER BY id').fetchall()
            for row in rows:
                if row['reason'] == 'Message-ID repetido com conteúdo diferente.':
                    continue
                refs = set()
                for ref in json.loads(row['refs']):
                    refs.update(r[0] for r in db.execute("SELECT obra_id FROM messages WHERE message_id=? AND status='vinculado' AND obra_id IS NOT NULL", (ref,)))
                match = match_message(row['subject'], row['body'], works, refs)
                if (match.status, match.obra_id, match.reason) == (row['status'], row['obra_id'], row['reason']):
                    continue
                db.execute('UPDATE messages SET status=?,obra_id=?,suggestion=?,reason=? WHERE id=?',
                           (match.status, match.obra_id, match.suggestion, match.reason, row['id']))
                db.execute('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                           (row['id'], now(), actor, 'reprocessamento', json.dumps({'before':
                             {'status': row['status'], 'obra_id': row['obra_id']}, 'after':
                         {'status': match.status, 'obra_id': match.obra_id}, 'reason': match.reason})))

    def conversation_rows(self, allowed_ids=None):
        """Filtra autorização antes de agrupar, inclusive corpos e anexos.
        'attachments' traz só os ativos; 'fingerprint_attachments', todos (identificação da publicação)."""
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('''SELECT m.*, w.name AS work_name
                FROM messages m LEFT JOIN works w ON w.id=m.obra_id''')
                if allowed_ids is None or r['obra_id'] in allowed_ids]
            by_id = {r['id']: r for r in rows}
            for row in rows:
                row['attachments'], row['fingerprint_attachments'] = [], []
            for item in db.execute('SELECT id,message_id,name,mime,sha256,size,trashed_at FROM attachments'):
                if item['message_id'] in by_id:
                    row = by_id[item['message_id']]
                    attachment = {'id': item['id'], 'name': item['name'], 'mime': item['mime'],
                                  'size': item['size'], 'sha256': item['sha256']}
                    row['fingerprint_attachments'].append(attachment)
                    if item['trashed_at'] is None:
                        row['attachments'].append(attachment)
        return rows

    def detail(self, mid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()
            if not row:
                raise ValueError('Mensagem não encontrada.')
            return dict(row), [dict(r) for r in db.execute(f'SELECT id,name,mime,size,sha256 FROM attachments WHERE message_id=? AND {ACTIVE}', (mid,))], [dict(r) for r in db.execute('SELECT * FROM audit WHERE message_id=? ORDER BY id', (mid,))], [dict(r) for r in db.execute('SELECT * FROM sources WHERE message_id=?', (mid,))]

    def fingerprint_attachments(self, mid):
        """Todos os anexos da mensagem, inclusive na lixeira: a identificação da publicação não muda."""
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,name,mime,size,sha256 FROM attachments WHERE message_id=?', (mid,))]

    def published_works(self):
        """No histórico compartilhado: impressão digital de publicação → obra."""
        with self.connect() as db:
            return {r['fingerprint']: r['obra_id'] for r in db.execute(
                "SELECT fingerprint, obra_id FROM messages WHERE status='vinculado' AND obra_id IS NOT NULL")}

    def attachment(self, aid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM attachments WHERE id=?', (aid,)).fetchone()
        if not row:
            raise ValueError('Anexo não encontrado.')
        if row['trashed_at']:
            raise ValueError('Este anexo está na lixeira.')
        return {**dict(row), 'payload': self.blobs.get(row['sha256'])}

    def save_folders(self, mailbox, folders):
        """Pastas encontradas na última conexão daquela caixa (só nomes; nenhuma credencial)."""
        with self.connect() as db:
            db.execute('DELETE FROM mail_folders WHERE mailbox=?', (mailbox,))
            db.executemany('INSERT OR IGNORE INTO mail_folders VALUES(?,?,?)',
                           [(mailbox, name, ' '.join(sorted(flags))) for name, flags in folders])

    def folders(self, mailbox):
        with self.connect() as db:
            return [(r['name'], set(r['flags'].split())) for r in
                    db.execute('SELECT name, flags FROM mail_folders WHERE mailbox=? ORDER BY name', (mailbox,))]

    def start_run(self):
        with self.connect() as db:
            return db.execute('INSERT INTO sync_runs(started,status) VALUES(?,?)', (now(), 'executando')).lastrowid

    def end_run(self, rid, status, detail):
        with self.connect() as db:
            db.execute('UPDATE sync_runs SET finished=?,status=?,detail=? WHERE id=?', (now(), status, detail, rid))

    def last_run(self):
        with self.connect() as db:
            row = db.execute('SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1').fetchone()
            return dict(row) if row else None
