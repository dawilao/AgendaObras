"""Conecta evidências de e-mail ao controle existente de seguro, sem aprovar automaticamente."""
import hashlib
import json
import re
from .matching import normalized, ics
from .conversations import build_conversations, topic_label


def obra_da_conversa(group, works):
    candidates={r.get('obra_id') or r.get('suggestion') for r in group['messages']} - {None,''}
    if not candidates:
        subjects=' '.join(normalized(r['subject']) for r in group['messages'])
        codes=set().union(*(ics(r['subject']) for r in group['messages']))
        for work in works:
            ic=work['ic']
            if (any(normalized(a) in subjects for a in work['aliases'] if a.strip())
                or (ic and any(c.split('/')[0]==ic.split('/')[0] for c in codes))
                or (ic and re.search(r'(?<![0-9])0*'+str(int(ic.split('/')[0]))+r'\s*[/.-]\s*'+ic.split('/')[1]+r'(?![0-9])',subjects))):
                candidates.add(work['id'])
    return next(iter(candidates)) if len(candidates)==1 else None


class FontesSeguro:
    def __init__(self, store, work_id, guard, namespace, suggested=False):
        self.store=store
        self.work_id=str(work_id)
        self.guard=guard
        self.namespace=namespace
        self.suggested=suggested

    def catalogo(self):
        self.guard()
        if self.suggested:
            groups=build_conversations(self.store.conversation_rows())
            rows=[m for g in groups if obra_da_conversa(g,self.store.works())==self.work_id for m in g['messages']]
        else:
            rows=self.store.conversation_rows({self.work_id})
        rows=[r for r in rows if r['status'] not in ('tecnico','ignorado')]
        from .seguro_interpretacao import tipos_mensagem
        for group in build_conversations(rows):
            types=sorted({t for m in group['messages'] for t in tipos_mensagem(m)})
            if not group['conflict'] and len(types)==1:
                for m in group['messages']: m['_tipos_conversa']=types
        return {str(r['id']):r for r in rows}

    def preparar(self, action, dados):
        rows=self.catalogo()
        key=str(dados.get('email_id') or '')
        if key not in rows: raise ValueError('Selecione um e-mail disponível desta obra.')
        row=rows[key]
        def email_ref(m):
            return dict(namespace=self.namespace,work_id=self.work_id,id=m['id'],
                        fingerprint=m['fingerprint'],subject=m['subject'],sender=m['sender'],date=m['sent_date'],topic=topic_label(m['subject']))
        refs={'evidencia':email_ref(row)}
        result={'evidencia':f"{row['subject']} | {row['sender']} | {row['sent_date']}", 'motivo':dados.get('motivo','')}
        if action=='recebimento':
            attachments={str(a['id']):(a,m) for m in rows.values() for a in m['attachments']}
            for field in ('apolice','boleto'):
                aid=str(dados.get(field+'_id') or '')
                if aid not in attachments: raise ValueError('Selecione o anexo de '+field+' desta obra.')
                attachment,origin=attachments[aid]
                refs[field]={**attachment,'origin':email_ref(origin)}
                result[field]=attachment['name']+' | e-mail #'+str(origin['id'])
        result['vinculos']=refs
        return result

    def mensagem(self, ref):
        if ref.get('namespace')!=self.namespace or str(ref.get('work_id'))!=self.work_id:
            raise PermissionError('Fonte de outra conta ou obra. Abra no histórico correspondente.')
        rows=self.catalogo()
        row=rows.get(str(ref.get('id')))
        if not row or row['fingerprint']!=ref.get('fingerprint'):
            raise PermissionError('E-mail indisponível ou sem acesso nesta obra.')
        return row

    def anexo(self, ref):
        row=self.mensagem(ref['origin'])
        if not any(a['id']==ref['id'] and a['sha256']==ref['sha256'] for a in row['attachments']):
            raise PermissionError('Anexo não corresponde à versão registrada.')
        attachment=self.store.attachment(ref['id'])
        if attachment['message_id']!=row['id'] or hashlib.sha256(attachment['payload']).hexdigest()!=ref['sha256']:
            raise PermissionError('Anexo alterado ou de outra mensagem.')
        return attachment


class SeguroComEmails:
    def __init__(self, service, obra_id, fontes):
        self.service=service
        self.obra_id=obra_id
        self.fontes=fontes
        self.tipo=service.tipo

    def obter(self, obra_id):
        return self.service.obter(self.obra_id)

    def alterar(self, obra_id, campo, valor, revisao):
        return self.service.alterar(self.obra_id,campo,valor,revisao)

    def interpretar_emails(self):
        from .seguro_interpretacao import interpretar
        state,can_edit=self.service.obter(self.obra_id)
        if not can_edit: return
        rows=self.fontes.catalogo()
        work=next((w for w in self.fontes.store.works() if str(w['id'])==self.fontes.work_id),None)
        if not work: return
        done={r['fingerprint'] for r in state['leituras'] if r['review'] or r['result']=='Registrado automaticamente'}
        readings=[r for m in rows.values() if m['fingerprint'] not in done if (r:=interpretar(m,work))]
        for reading in sorted(readings,key=lambda r:(r['timestamp'],r['email_id'])):
            if reading['types'] and self.tipo not in reading['types']: continue
            if reading['types'] != [self.tipo]:
                reading['review']=True
                reading['reason']='Tipo de seguro ambíguo ou mensagem com os dois seguros. '+reading['reason']
            state,_=self.service.obter(self.obra_id)
            action=reading['action']
            atual=state['atual']
            stage=atual['etapa'] if atual else None
            expected={'solicitacao':None,'pedido':'solicitado','recebimento':'pedido','envio':'recebido','ajustes':'analise','aceite':'analise'}
            data=dict(email_id=reading['email_id'],apolice_id=reading['apolice_id'],boleto_id=reading['boleto_id'],motivo=reading['excerpt'])
            # Toda leitura tem uma fonte verificável, mesmo quando faltam etapas.
            prepared=self.fontes.preparar('solicitacao',data)
            reading['source']=prepared['vinculos']['evidencia']
            reading['result']='Precisa de conferência' if reading['review'] else 'Identificado; sequência anterior ou documentos precisam de conferência'
            prior=[h for h in state['historico'] if h['campo'].startswith('rodada:')]
            # Não sobrescrever a condução manual nem tratar e-mail antigo como
            # fato posterior a uma rodada nova. Novas evidências ficam visíveis.
            latest_auto=json.loads(prior[0]['novo']).get('vinculos','{}') if prior else '{}'
            latest_auto=json.loads(latest_auto).get('automatico')
            chronological=not prior or (latest_auto and reading['timestamp']>=latest_auto['timestamp'])
            if not reading['review'] and action in expected and stage==expected[action] and chronological:
                try:
                    prepared=self.fontes.preparar(action,data)
                    prepared['evidencia']='Identificado automaticamente • '+prepared['evidencia']
                    prepared['vinculos']['automatico']={'fingerprint':reading['fingerprint'],'timestamp':reading['timestamp'],'version':reading['version']}
                    self.service.registrar_etapa(self.obra_id,action,prepared,state['revisao'])
                    reading['result']='Registrado automaticamente'
                except ValueError as error:
                    reading['review']=True
                    reading['result']='Precisa de conferência: '+str(error)
            self.service.registrar_leitura(self.obra_id,reading)

    def registrar_etapa(self, obra_id, acao, dados, revisao):
        self.service.autorizar(self.obra_id,escrita=True)
        from .seguro_interpretacao import tipos_mensagem, tipos_no_texto
        row=self.fontes.catalogo().get(str(dados.get('email_id')))
        if row:
            tipos=tipos_mensagem(row)
            if tipos and self.tipo not in tipos:
                raise ValueError('Este e-mail pertence ao outro tipo de seguro. Abra o controle correspondente.')
        prepared=self.fontes.preparar(acao,dados)
        for field in ('apolice','boleto'):
            attachment=prepared['vinculos'].get(field)
            if attachment:
                tipos=tipos_no_texto(attachment['name'])
                if tipos and self.tipo not in tipos:
                    raise ValueError('O anexo selecionado identifica o outro tipo de seguro.')
                origin=self.fontes.catalogo().get(str(attachment['origin']['id']))
                tipos=tipos_mensagem(origin) if origin else []
                if tipos and self.tipo not in tipos:
                    raise ValueError('O e-mail de origem do anexo pertence ao outro tipo de seguro.')
        return self.service.registrar_etapa(self.obra_id,acao,prepared,revisao)
