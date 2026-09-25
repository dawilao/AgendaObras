"""Publicação explícita e idempotente no histórico compartilhado de uma obra."""
import hashlib
import json
from .store import now


def publish_message(private, shared, mid, actor, allowed_ids):
    message, _, _, sources = private.detail(mid)
    wid = message['obra_id']
    if message['status'] != 'vinculado' or not wid or wid not in set(allowed_ids):
        raise PermissionError('Confirme uma obra à qual você tenha acesso antes de publicar.')
    work = next(w for w in private.works() if w['id'] == wid)
    with private.connect() as db:
        attachments = [dict(r) for r in db.execute('SELECT * FROM attachments WHERE message_id=?', (mid,))]
    # Destinatários e cabeçalhos de transporte podem variar entre cópias da mesma mensagem.
    content = {key: message[key] for key in ('message_id', 'subject', 'sender', 'sent_date', 'body')}
    content['attachments'] = sorted((a['name'], hashlib.sha256(a['payload']).hexdigest()) for a in attachments)
    fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with shared.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT id,obra_id FROM messages WHERE fingerprint=?', (fingerprint,)).fetchone()
        if existing and existing['obra_id'] != wid:
            raise ValueError('Esta mensagem já foi publicada em outra obra. Confira o vínculo antes de continuar.')
        if not existing and message['message_id'] and db.execute('SELECT 1 FROM messages WHERE message_id=?', (message['message_id'],)).fetchone():
            raise ValueError('Já existe uma mensagem com esse identificador e conteúdo diferente. É necessária conferência; nada foi substituído.')
        fresh = existing is None
        if fresh:
            db.execute('INSERT OR IGNORE INTO works VALUES(?,?,?,?,?)',
                       (wid, work['name'], work['ic'], json.dumps(work['aliases']), work['confirmed']))
            cur = db.execute('''INSERT INTO messages(fingerprint,message_id,subject,sender,recipients,cc,
                sent_date,body,refs,status,obra_id,suggestion,reason,created,reviewed)
                VALUES(?,?,?,?,?,?,?,?,?,'vinculado',?,NULL,?,?,1)''',
                (fingerprint, message['message_id'], message['subject'], message['sender'],
                 message['recipients'], message['cc'], message['sent_date'], message['body'], message['refs'],
                 wid, 'Publicado após conferência do usuário.', now()))
            public_id = cur.lastrowid
            db.executemany('INSERT INTO attachments(message_id,name,mime,payload) VALUES(?,?,?,?)',
                           [(public_id, a['name'], a['mime'], a['payload']) for a in attachments])
            db.execute('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                       (public_id, now(), actor, 'publicacao', 'Mensagem e anexos confirmados para a obra.'))
        else:
            public_id = existing['id']
    with private.connect() as db:
        db.execute('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                   (mid, now(), actor, 'publicacao' if fresh else 'ja_publicada',
                    f'Registro compartilhado {public_id}; obra {wid}.'))
    return public_id, fresh
