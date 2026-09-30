"""Publicação explícita e idempotente no histórico compartilhado de uma obra."""
import hashlib
import json
from .store import now

# Situações ainda sem decisão do usuário na própria caixa.
UNDECIDED = ('revisar', 'conflito')


def publication_fingerprint(message, attachments):
    """Identifica o mesmo e-mail em caixas diferentes (mesmo cálculo da publicação)."""
    # Destinatários e cabeçalhos de transporte podem variar entre cópias da mesma mensagem.
    content = {key: message[key] for key in ('message_id', 'subject', 'sender', 'sent_date', 'body')}
    content['attachments'] = sorted((a['name'], a['sha256']) for a in attachments)
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def team_pending(rows, shared, allowed_ids):
    """{id da mensagem: obra} das mensagens sem decisão que a equipe já publicou numa obra permitida."""
    if shared is None:
        return {}
    published = shared.published_works()
    allowed = set(allowed_ids)
    found = {}
    for row in rows:
        if row['status'] not in UNDECIDED:
            continue
        wid = published.get(publication_fingerprint(row, row.get('fingerprint_attachments', row['attachments'])))
        if wid and wid in allowed:
            found[row['id']] = wid
    return found


def adopt_team_links(private, shared, actor, allowed_ids):
    """OK de um coordenador vale para a equipe: mensagens sem decisão na caixa pessoal cuja cópia
    já foi publicada por decisão humana (não automática) numa obra permitida passam a Vinculadas.
    Não cria cópia no histórico; só registra a auditoria. Retorna quantas foram adotadas."""
    if shared is None:
        return 0
    published = shared.human_published_works()
    if not published:
        return 0
    # Obra precisa estar na identificação desta caixa (review exige o cadastro).
    allowed = set(allowed_ids) & {w['id'] for w in private.works()}
    adopted = 0
    for row in private.conversation_rows():
        # Sem decisão humana: pendentes e também as vinculadas só pela identificação automática.
        if row['reviewed'] or row['status'] not in UNDECIDED + ('vinculado',):
            continue
        wid = published.get(publication_fingerprint(row, row['fingerprint_attachments']))
        if not wid or wid not in allowed:
            continue
        private.review(row['id'], wid, actor, 'Vínculo confirmado pela equipe (OK de coordenador).')
        publish_message(private, shared, row['id'], actor, allowed)
        adopted += 1
    return adopted


def publish_message(private, shared, mid, actor, allowed_ids, *, automatic=False):
    message, _, _, sources = private.detail(mid)
    wid = message['obra_id']
    if message['status'] != 'vinculado' or not wid or wid not in set(allowed_ids):
        raise PermissionError('Confirme uma obra à qual você tenha acesso antes de publicar.')
    work = next(w for w in private.works() if w['id'] == wid)
    with private.connect() as db:
        attachments = [dict(r) for r in db.execute('SELECT * FROM attachments WHERE message_id=?', (mid,))]
    fingerprint = publication_fingerprint(message, attachments)
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
                 wid, 'Publicado por identificação automática segura.' if automatic else 'Publicado após conferência do usuário.', now()))
            public_id = cur.lastrowid
            # Mesmo arquivo em disco: o histórico compartilhado referencia o sha256, sem nova cópia.
            # Anexo na lixeira segue na lixeira; publicar não o traz de volta.
            db.executemany('''INSERT INTO attachments(message_id,name,mime,sha256,size,trash_id,trashed_at,purged_at)
                           VALUES(?,?,?,?,?,?,?,?)''',
                           [(public_id, a['name'], a['mime'], a['sha256'], a['size'],
                             a['trash_id'], a['trashed_at'], a['purged_at']) for a in attachments])
            db.execute('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                       (public_id, now(), actor, 'publicacao_automatica' if automatic else 'publicacao', message['reason'] if automatic else 'Mensagem e anexos confirmados para a obra.'))
        else:
            public_id = existing['id']
    with private.connect() as db:
        db.execute('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                   (mid, now(), actor, 'publicacao' if fresh else 'ja_publicada',
                    f'Registro compartilhado {public_id}; obra {wid}.'))
    return public_id, fresh


def publish_identified(private, shared, actor, allowed_ids):
    """Executado após importação/revisão; não remove a cópia pessoal nem aprova seguros."""
    from .matching import ics
    result = dict(new=0, existing=0, pending=0)
    if shared is None:
        return result
    allowed = set(allowed_ids)
    private.reprocess(actor)
    published = shared.published_works()
    works = {w['id']: w for w in private.works()}
    for row in private.conversation_rows():
        wid = row['obra_id']
        if row['status'] != 'vinculado' or wid not in allowed:
            continue
        # Mesmo com IC no assunto, divergência no corpo exige conferência.
        body_codes = ics(row['body'])
        if not row['reviewed'] and body_codes and body_codes != {works[wid]['ic']}:
            reason = 'IC divergente no corpo; conferir antes de compartilhar.'
        else:
            fingerprint = publication_fingerprint(row, row['fingerprint_attachments'])
            if published.get(fingerprint) == wid:
                result['existing'] += 1
                continue
            try:
                _, fresh = publish_message(private, shared, row['id'], actor, allowed, automatic=True)
                published[fingerprint] = wid
                result['new' if fresh else 'existing'] += 1
                continue
            except ValueError as exc:
                reason = str(exc)
        # Mantém a mensagem na fila; a próxima sincronização não libera o conflito.
        with private.connect() as db:
            db.execute("UPDATE messages SET status='conflito',obra_id=NULL,suggestion=?,reason=?,reviewed=1 WHERE id=?",
                       (wid, reason, row['id']))
            db.execute('INSERT INTO audit(message_id,at,actor,action,details) VALUES(?,?,?,?,?)',
                       (row['id'], now(), actor, 'publicacao_pendente', reason))
        result['pending'] += 1
    return result
