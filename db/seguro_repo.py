"""Validação de seguro no mesmo banco de obras e padrão BaseRepository."""
import json
from datetime import datetime, timezone
from db.connection import BaseRepository

COTACOES = ('Não informada', 'Solicitada', 'Recebida', 'Aprovada')
TIPOS_SEGURO = {'garantia':'Seguro-garantia contratual',
                'obra':'Seguro da obra — risco de engenharia e responsabilidade civil'}


def criar_schema(conn):
    conn.execute('SAVEPOINT seguro_schema')
    try:
        _criar_schema(conn)
        conn.execute('RELEASE SAVEPOINT seguro_schema')
    except Exception:
        conn.execute('ROLLBACK TO SAVEPOINT seguro_schema')
        conn.execute('RELEASE SAVEPOINT seguro_schema')
        raise


def _criar_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS obra_seguro (
        obra_id INTEGER PRIMARY KEY REFERENCES obras(id), cotacao TEXT NOT NULL DEFAULT 'Não informada',
        ok_seguro INTEGER NOT NULL DEFAULT 0 CHECK(ok_seguro IN (0,1)),
        ok_boleto INTEGER NOT NULL DEFAULT 0 CHECK(ok_boleto IN (0,1)),
        revisao INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS historico_seguro (
        id INTEGER PRIMARY KEY, obra_id INTEGER NOT NULL REFERENCES obras(id),
        campo TEXT NOT NULL, anterior TEXT NOT NULL, novo TEXT NOT NULL,
        usuario_id INTEGER NOT NULL, usuario_nome TEXT NOT NULL, data_hora TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS seguro_rodadas (
        id INTEGER PRIMARY KEY, obra_id INTEGER NOT NULL REFERENCES obras(id), numero INTEGER NOT NULL,
        etapa TEXT NOT NULL, apolice TEXT NOT NULL DEFAULT '', boleto TEXT NOT NULL DEFAULT '',
        evidencia TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '',
        ok_seguro INTEGER NOT NULL DEFAULT 0, ok_boleto INTEGER NOT NULL DEFAULT 0,
        UNIQUE(obra_id,numero))""")
    if 'vinculos' not in {r[1] for r in conn.execute('PRAGMA table_info(seguro_rodadas)')}:
        conn.execute("ALTER TABLE seguro_rodadas ADD COLUMN vinculos TEXT NOT NULL DEFAULT '{}'")
    if 'rodada_id' not in {r[1] for r in conn.execute('PRAGMA table_info(historico_seguro)')}:
        conn.execute('ALTER TABLE historico_seguro ADD COLUMN rodada_id INTEGER')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_historico_seguro_obra ON historico_seguro(obra_id,id)')
    # Preservar o legado sem atribuir os OKs antigos a um tipo por suposição.
    if 'tipo' not in {r[1] for r in conn.execute('PRAGMA table_info(obra_seguro)')}:
        conn.execute('''CREATE TABLE obra_seguro_tipado (
            obra_id INTEGER NOT NULL REFERENCES obras(id), tipo TEXT NOT NULL,
            cotacao TEXT NOT NULL DEFAULT 'Não informada',
            ok_seguro INTEGER NOT NULL DEFAULT 0 CHECK(ok_seguro IN (0,1)),
            ok_boleto INTEGER NOT NULL DEFAULT 0 CHECK(ok_boleto IN (0,1)),
            revisao INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(obra_id,tipo))''')
        conn.execute("INSERT INTO obra_seguro_tipado SELECT obra_id,'nao_classificado',cotacao,ok_seguro,ok_boleto,revisao FROM obra_seguro")
        conn.execute('DROP TABLE obra_seguro')
        conn.execute('ALTER TABLE obra_seguro_tipado RENAME TO obra_seguro')
    if 'tipo' not in {r[1] for r in conn.execute('PRAGMA table_info(seguro_rodadas)')}:
        conn.execute('''CREATE TABLE seguro_rodadas_tipado (
            id INTEGER PRIMARY KEY, obra_id INTEGER NOT NULL REFERENCES obras(id),
            tipo TEXT NOT NULL, numero INTEGER NOT NULL, etapa TEXT NOT NULL,
            apolice TEXT NOT NULL DEFAULT '', boleto TEXT NOT NULL DEFAULT '',
            evidencia TEXT NOT NULL DEFAULT '', motivo TEXT NOT NULL DEFAULT '',
            ok_seguro INTEGER NOT NULL DEFAULT 0, ok_boleto INTEGER NOT NULL DEFAULT 0,
            vinculos TEXT NOT NULL DEFAULT '{}', UNIQUE(obra_id,tipo,numero))''')
        conn.execute("INSERT INTO seguro_rodadas_tipado SELECT id,obra_id,'nao_classificado',numero,etapa,apolice,boleto,evidencia,motivo,ok_seguro,ok_boleto,vinculos FROM seguro_rodadas")
        conn.execute('DROP TABLE seguro_rodadas')
        conn.execute('ALTER TABLE seguro_rodadas_tipado RENAME TO seguro_rodadas')
    if 'tipo' not in {r[1] for r in conn.execute('PRAGMA table_info(historico_seguro)')}:
        conn.execute("ALTER TABLE historico_seguro ADD COLUMN tipo TEXT NOT NULL DEFAULT 'nao_classificado'")


class SeguroRepository(BaseRepository):
    def __init__(self, db_name, tipo='obra'):
        super().__init__(db_name)
        if tipo not in TIPOS_SEGURO: raise ValueError('Tipo de seguro inválido.')
        self.tipo=tipo

    def obter(self, obra_id):
        conn = self.get_connection()
        try:
            if not conn.execute('SELECT 1 FROM obras WHERE id=?', (obra_id,)).fetchone():
                raise ValueError('Obra não encontrada.')
            row = conn.execute('SELECT * FROM obra_seguro WHERE obra_id=? AND tipo=?', (obra_id,self.tipo)).fetchone()
            state = dict(row) if row else dict(obra_id=obra_id, cotacao='Não informada', ok_seguro=0, ok_boleto=0, revisao=0)
            state['tipo']=self.tipo
            state['legado']=[dict(r) for r in conn.execute("SELECT * FROM seguro_rodadas WHERE obra_id=? AND tipo='nao_classificado' ORDER BY numero DESC",(obra_id,))]
            state['historico'] = [dict(r) for r in conn.execute('SELECT * FROM historico_seguro WHERE obra_id=? AND tipo=? ORDER BY id DESC', (obra_id,self.tipo))]
            readings={}
            for h in state['historico']:
                if h['campo']=='leitura:email':
                    reading=json.loads(h['novo'])
                    readings.setdefault(reading['fingerprint'],reading)
            state['leituras'] = list(readings.values())
            state['rodadas'] = [dict(r) for r in conn.execute('SELECT * FROM seguro_rodadas WHERE obra_id=? AND tipo=? ORDER BY numero DESC', (obra_id,self.tipo))]
            state['atual'] = state['rodadas'][0] if state['rodadas'] else None
            atual = state['atual']
            state['ok_seguro'] = atual['ok_seguro'] if atual else 0
            state['ok_boleto'] = atual['ok_boleto'] if atual else 0
            state['definitivo'] = bool(atual and atual['etapa'] in ('aceito','sem_resposta') and atual['ok_seguro'] and atual['ok_boleto'])
            return state
        finally:
            conn.close()

    def registrar_leitura(self, obra_id, leitura, usuario):
        conn=self.get_connection()
        try:
            conn.execute('BEGIN IMMEDIATE')
            existentes=conn.execute("SELECT novo FROM historico_seguro WHERE obra_id=? AND tipo=? AND campo='leitura:email' ORDER BY id DESC",(obra_id,self.tipo))
            previous=next((json.loads(r['novo']) for r in existentes if json.loads(r['novo'])['fingerprint']==leitura['fingerprint']),None)
            if previous and (previous['result']==leitura['result'] or previous['result']=='Registrado automaticamente'):
                conn.rollback(); return
            conn.execute('INSERT OR IGNORE INTO obra_seguro(obra_id,tipo) VALUES(?,?)',(obra_id,self.tipo))
            conn.execute('INSERT INTO historico_seguro(obra_id,tipo,campo,anterior,novo,usuario_id,usuario_nome,data_hora) VALUES(?,?,?,?,?,?,?,?)',
                         (obra_id,self.tipo,'leitura:email',json.dumps(previous,ensure_ascii=False),json.dumps(leitura,ensure_ascii=False),usuario['id'],
                          (usuario['nome']+' '+usuario.get('sobrenome','')).strip(),datetime.now(timezone.utc).isoformat()))
            conn.execute('UPDATE obra_seguro SET revisao=revisao+1 WHERE obra_id=? AND tipo=?',(obra_id,self.tipo))
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()

    def alterar(self, obra_id, campo, valor, usuario, revisao):
        if campo not in ('cotacao', 'ok_seguro', 'ok_boleto'):
            raise ValueError('Controle inválido.')
        if campo == 'cotacao':
            if valor not in COTACOES: raise ValueError('Cotação inválida.')
        elif type(valor) is not bool:
            raise ValueError('A validação deve ser sim ou não.')
        conn = self.get_connection()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM obras WHERE id=?', (obra_id,)).fetchone():
                raise ValueError('Obra não encontrada.')
            conn.execute('INSERT OR IGNORE INTO obra_seguro(obra_id,tipo) VALUES(?,?)', (obra_id,self.tipo))
            state = conn.execute('SELECT * FROM obra_seguro WHERE obra_id=? AND tipo=?', (obra_id,self.tipo)).fetchone()
            if state['revisao'] != revisao:
                raise ValueError('Outro usuário atualizou o seguro. Confira os dados atualizados antes de tentar novamente.')
            atual = conn.execute('SELECT * FROM seguro_rodadas WHERE obra_id=? AND tipo=? ORDER BY numero DESC LIMIT 1', (obra_id,self.tipo)).fetchone()
            if campo != 'cotacao':
                if not atual or atual['etapa'] not in ('aceito','sem_resposta'):
                    raise ValueError('Registre primeiro a aprovação do banco ou a validação interna por ausência de resposta.')
                conn.execute(f'UPDATE seguro_rodadas SET {campo}=? WHERE id=?', (int(valor),atual['id']))
            old = state[campo] if campo == 'cotacao' else bool(state[campo])
            if old == valor:
                conn.rollback()
                return
            conn.execute(f'UPDATE obra_seguro SET {campo}=?, revisao=revisao+1 WHERE obra_id=? AND tipo=?', (valor, obra_id,self.tipo))
            name = (usuario['nome'] + ' ' + usuario.get('sobrenome', '')).strip()
            conn.execute('INSERT INTO historico_seguro(obra_id,tipo,campo,anterior,novo,usuario_id,usuario_nome,data_hora,rodada_id) VALUES(?,?,?,?,?,?,?,?,?)',
                         (obra_id,self.tipo,campo,json.dumps(old,ensure_ascii=False),json.dumps(valor,ensure_ascii=False),usuario['id'],name,datetime.now(timezone.utc).isoformat(),atual['id'] if atual else None))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


    def registrar_etapa(self, obra_id, acao, dados, usuario, revisao):
        conn = self.get_connection()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM obras WHERE id=?',(obra_id,)).fetchone():
                raise ValueError('Obra não encontrada.')
            conn.execute('INSERT OR IGNORE INTO obra_seguro(obra_id,tipo) VALUES(?,?)',(obra_id,self.tipo))
            state=conn.execute('SELECT * FROM obra_seguro WHERE obra_id=? AND tipo=?',(obra_id,self.tipo)).fetchone()
            if state['revisao'] != revisao:
                raise ValueError('A situação mudou. Atualize e confira antes de registrar.')
            row=conn.execute('SELECT * FROM seguro_rodadas WHERE obra_id=? AND tipo=? ORDER BY numero DESC LIMIT 1',(obra_id,self.tipo)).fetchone()
            old=dict(row) if row else None
            def required(key):
                value=str(dados.get(key) or '').strip()
                if not value: raise ValueError('Preencha ' + {'evidencia':'a referência do e-mail/documento','apolice':'a identificação da apólice','boleto':'a identificação do boleto','motivo':'o motivo ou ajustes solicitados'}[key] + '.')
                if len(value)>2000: raise ValueError('Referência muito extensa (máximo 2000 caracteres).')
                return value
            evidence=required('evidencia')
            if acao=='solicitacao':
                if row: raise ValueError('A solicitação inicial já foi registrada.')
                conn.execute("INSERT INTO seguro_rodadas(obra_id,tipo,numero,etapa,evidencia) VALUES(?,?,1,'solicitado',?)",(obra_id,self.tipo,evidence))
            elif acao=='nova_rodada':
                if not row: raise ValueError('Registre a solicitação inicial.')
                reason=required('motivo')
                conn.execute("INSERT INTO seguro_rodadas(obra_id,tipo,numero,etapa,evidencia,motivo) VALUES(?,?,?,'pedido',?,?)",(obra_id,self.tipo,row['numero']+1,evidence,reason))
            else:
                transitions={'pedido':('solicitado','pedido'),'recebimento':('pedido','recebido'),
                             'envio':('recebido','analise'),'ajustes':('analise','ajustes'),'aceite':('analise','aceito'),
                             'sem_resposta':('analise','sem_resposta')}
                if acao not in transitions or not row or row['etapa']!=transitions[acao][0]:
                    raise ValueError('Esta ação não corresponde à etapa atual.')
                stage=transitions[acao][1]
                apolice=row['apolice']; boleto=row['boleto']; reason=row['motivo']
                if acao=='recebimento': apolice=required('apolice'); boleto=required('boleto')
                if acao in ('ajustes','sem_resposta'): reason=required('motivo')
                conn.execute('UPDATE seguro_rodadas SET etapa=?,apolice=?,boleto=?,evidencia=?,motivo=? WHERE id=?',
                             (stage,apolice,boleto,evidence,reason,row['id']))
            current=conn.execute('SELECT id,vinculos FROM seguro_rodadas WHERE obra_id=? AND tipo=? ORDER BY numero DESC LIMIT 1',(obra_id,self.tipo)).fetchone()
            links=json.loads(current['vinculos'])
            incoming=dados.get('vinculos') or {}
            links.update(incoming)
            if 'automatico' not in incoming: links.pop('automatico',None)
            if 'evidencia' not in incoming: links.pop('evidencia',None)
            if acao=='recebimento':
                for field in ('apolice','boleto'):
                    if field not in incoming: links.pop(field,None)
            conn.execute('UPDATE seguro_rodadas SET vinculos=? WHERE id=?',(json.dumps(links,ensure_ascii=False),current['id']))
            new=dict(conn.execute('SELECT * FROM seguro_rodadas WHERE obra_id=? AND tipo=? ORDER BY numero DESC LIMIT 1',(obra_id,self.tipo)).fetchone())
            conn.execute('UPDATE obra_seguro SET revisao=revisao+1,ok_seguro=?,ok_boleto=? WHERE obra_id=? AND tipo=?',(new['ok_seguro'],new['ok_boleto'],obra_id,self.tipo))
            name=(usuario['nome']+' '+usuario.get('sobrenome','')).strip()
            conn.execute('INSERT INTO historico_seguro(obra_id,tipo,campo,anterior,novo,usuario_id,usuario_nome,data_hora,rodada_id) VALUES(?,?,?,?,?,?,?,?,?)',
                         (obra_id,self.tipo,'rodada:'+acao,json.dumps(old,ensure_ascii=False),json.dumps(new,ensure_ascii=False),usuario['id'],name,datetime.now(timezone.utc).isoformat(),new['id']))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
