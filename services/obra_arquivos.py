"""Aba Arquivos da obra: CCT, orçamento e aditivos.

Ver e baixar: administrador, Financeiro e coordenador da própria obra (mesma regra do financeiro).
Enviar e anexar das Comunicações: só o Financeiro. Sem exclusão pela tela; cada envio é uma versão.

O conteúdo vai para um BlobStore próprio (compactação sem perda das Comunicações), em raiz separada
da dos e-mails: a limpeza de órfãos das Comunicações só conhece os bancos de e-mail e apagaria
arquivos de obras numa pasta compartilhada.
"""
import hashlib
import os
from pathlib import Path

from comunicacoes.blobs import BlobStore
from db.obra_arquivos_repo import TIPOS
from services.financeiro_service import checar_editar, checar_ver

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIMITE_BYTES = 20 * 1024 * 1024
FORMATOS = {'cct': ('.pdf',), 'orcamento': ('.pdf', '.xlsx', '.xls', '.csv'),
            'aditivo': ('.pdf', '.xlsx', '.xls', '.csv')}
_ASSINATURAS = {'.xlsx': b'PK\x03\x04', '.xls': b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'}


def raiz_arquivos():
    return Path((os.getenv('AGENDA_OBRAS_ARQUIVOS_ROOT') or '').strip() or _PROJECT_ROOT / 'uploads' / 'obras')


def blob_store():
    return BlobStore(raiz_arquivos())


def _exigir_ver(user, obra):
    checar_ver(user, obra, 'Arquivos restritos ao administrador, ao Financeiro e ao coordenador desta obra.')


def _exigir_enviar(user):
    checar_editar(user, 'Somente o Financeiro envia arquivos da obra.')


def nome_limpo(nome):
    nome = str(nome or '').replace('\\', '/').split('/')[-1]
    nome = ''.join(c for c in nome if c.isprintable()).strip()
    if len(nome) > 150:
        sufixo = Path(nome).suffix[:10]
        nome = nome[:150 - len(sufixo)] + sufixo
    return nome


def validar_arquivo(tipo, nome, conteudo):
    """Nome limpo, se o arquivo serve para o tipo; ValueError com o motivo, senão."""
    if tipo not in FORMATOS:
        raise ValueError('Tipo de documento inválido.')
    nome = nome_limpo(nome)
    extensao = Path(nome).suffix.lower()
    if not nome or extensao not in FORMATOS[tipo]:
        aceitos = ', '.join(e.lstrip('.').upper() for e in FORMATOS[tipo])
        raise ValueError(f'Formato não permitido para {TIPOS[tipo]}. Aceitos: {aceitos}.')
    if not conteudo or len(conteudo) > LIMITE_BYTES:
        raise ValueError('O arquivo deve ter conteúdo e no máximo 20 MB.')
    if extensao == '.pdf':
        confere = b'%PDF-' in conteudo[:1024]
    elif extensao == '.csv':
        confere = b'\x00' not in conteudo[:4096]
    else:
        confere = conteudo.startswith(_ASSINATURAS[extensao])
    if not confere:
        raise ValueError('O conteúdo do arquivo não corresponde à extensão.')
    return nome


def listar(repo, obra, user):
    """{tipo: [versões, mais recente primeiro]}."""
    _exigir_ver(user, obra)
    grupos = {tipo: [] for tipo in TIPOS}
    for arquivo in repo.listar(obra['id']):
        grupos[arquivo['tipo']].append(arquivo)
    return grupos


def _gravar(repo, obra, tipo, nome, conteudo, user, origem, origem_ref=None, store=None):
    nome = validar_arquivo(tipo, nome, conteudo)
    store = store or blob_store()
    sha = hashlib.sha256(conteudo).hexdigest()
    existente = repo.existe_sha(obra['id'], sha)
    if existente:
        raise ValueError(f"Este arquivo já está na obra ({TIPOS[existente['tipo']]}: {existente['nome']}).")
    # O conteúdo vai para o disco dentro da transação do registro: falha no disco não deixa registro,
    # e falha no registro não chega a gravar o arquivo.
    arquivo_id = repo.registrar(obra['id'], tipo, nome, sha, len(conteudo), origem, user, origem_ref,
                                antes_do_commit=lambda: store.put(conteudo))
    return repo.obter(arquivo_id)


def enviar(repo, obra, tipo, nome, conteudo, user, store=None):
    _exigir_enviar(user)
    return _gravar(repo, obra, tipo, nome, conteudo, user, 'upload', store=store)


def baixar(repo, obra, arquivo_id, user, store=None):
    """(nome, conteúdo) conferindo no servidor quem pode ver e se o arquivo é desta obra."""
    _exigir_ver(user, obra)
    arquivo = repo.obter(arquivo_id)
    if not arquivo or arquivo['obra_id'] != obra['id']:
        raise ValueError('Arquivo não encontrado nesta obra.')
    return arquivo['nome'], (store or blob_store()).get(arquivo['sha256'])


# ---------------------------------------------------------------------------
# Anexar das Comunicações (só do Histórico da equipe, nunca das caixas pessoais)
# ---------------------------------------------------------------------------

def _historico_equipe():
    from comunicacoes.runtime import get_shared_store
    return get_shared_store()


def _anexos_da_obra(shared, obra_id):
    anexos = []
    for mensagem in shared.messages(status='vinculado', work=str(obra_id)):
        if not mensagem.get('attachment_count'):
            continue
        _, itens, _, _ = shared.detail(mensagem['id'])
        for item in itens:
            if Path(item['name'] or '').suffix.lower() in FORMATOS['orcamento']:
                anexos.append({'id': item['id'], 'nome': item['name'], 'bytes': item['size'], 'sha256': item['sha256'],
                               'assunto': mensagem.get('subject') or '(sem assunto)',
                               'data': mensagem.get('sent_date') or ''})
    return anexos


def anexos_comunicacoes(repo, obra, user, shared=None):
    """Anexos (PDF, planilhas, CSV) dos e-mails vinculados a esta obra no Histórico da equipe."""
    _exigir_enviar(user)
    ja_na_obra = {a['sha256'] for a in repo.listar(obra['id'])}
    return [{**a, 'ja_na_obra': a['sha256'] in ja_na_obra}
            for a in _anexos_da_obra(shared or _historico_equipe(), obra['id'])]


def anexar_de_comunicacoes(repo, obra, tipo, anexo_id, user, shared=None, store=None):
    _exigir_enviar(user)
    shared = shared or _historico_equipe()
    anexo = next((a for a in _anexos_da_obra(shared, obra['id']) if a['id'] == anexo_id), None)
    if anexo is None:
        raise ValueError('Anexo não encontrado nos e-mails desta obra no Histórico da equipe.')
    conteudo = shared.attachment(anexo_id)['payload']
    return _gravar(repo, obra, tipo, anexo['nome'], conteudo, user, 'comunicacoes', str(anexo_id), store)
