"""Atualização do financeiro Omie e operações de ligação obra ↔ projeto.

Toda operação confere a permissão no servidor (services.financeiro_service). Uma atualização
por vez no processo; o bloqueio de 30 min do Omie (HTTP 425) desabilita novas tentativas.
Consulta nova com alguma mudança devolve a obra conferida para "Em conferência".
"""
import re
import threading
import time
import unicodedata
from datetime import date, datetime, timezone

from services import omie_integracao as omie
from services.financeiro_service import checar_editar, checar_ver, pode_validar_parceiros
from services.omie_financeiro import (diferencas, exportar_csv, houve_mudanca, pagamentos_por_fornecedor,
                                      textos_diferencas)

PERIODO_INICIO_PADRAO = '2026-01-01'
CACHE_PROJETOS_S = 300
# Fornecedor que o Omie não devolveu não é consultado de novo antes disso.
FORNECEDOR_FALHO_S = 24 * 3600

_trava = threading.Lock()
_estado = {'rodando': False, 'progresso': '', 'cancelar': None, 'bloqueado_ate': None}
_projetos_cache = {'em': None, 'lista': None}
_fornecedores_falhos = {}   # {codigo: time.monotonic() da falha}


def estado() -> dict:
    return {'rodando': _estado['rodando'], 'progresso': _estado['progresso'], 'bloqueado_ate': bloqueado_ate()}


def bloqueado_ate():
    ate = _estado['bloqueado_ate']
    if ate and datetime.now(timezone.utc) < ate:
        return ate
    _estado['bloqueado_ate'] = None
    return None


def periodo_padrao(obras, hoje=None):
    hoje = hoje or date.today()
    datas = []
    for obra in obras:
        try:
            datas.append(date.fromisoformat((obra.get('data_inicio') or '').strip()[:10]))
        except ValueError:
            continue
    inicio = min(datas) if datas else date.fromisoformat(PERIODO_INICIO_PADRAO)
    return min(inicio, hoje).isoformat(), hoje.isoformat()


def interromper(user) -> bool:
    checar_editar(user)
    evento = _estado['cancelar']
    if evento is None:
        return False
    evento.set()
    return True


def atualizar(repo, obras, user, obra_ids=None, cliente=None, hoje=None) -> dict:
    """Consulta o Omie para as obras ligadas (todas, ou só obra_ids) e grava uma consulta por obra."""
    checar_editar(user)
    _sem_bloqueio()
    if not _trava.acquire(blocking=False):
        raise RuntimeError('Já existe uma atualização do Omie em andamento. Aguarde ou interrompa a anterior.')
    try:
        vinculos = repo.vinculos(obra_ids)
        if not vinculos:
            raise ValueError('Nenhuma obra ligada ao Omie para atualizar.')
        por_id = {o['id']: o for o in obras}
        inicio, fim = periodo_padrao([por_id[v['obra_id']] for v in vinculos if v['obra_id'] in por_id], hoje)
        cancelar = threading.Event()
        _estado.update(rodando=True, progresso='Iniciando', cancelar=cancelar)
        cliente = cliente or omie.criar_cliente(list(por_id.values()))
        if hasattr(cliente, 'ao_esperar'):
            cliente.ao_esperar = lambda s: _estado.update(progresso=f'Aguardando o limite do Omie ({int(s)} s)')
        if hasattr(cliente, 'cancelar'):
            cliente.cancelar = cancelar   # "Interromper" não espera o fim de uma pausa de até 60 s
        simulado = bool(getattr(cliente, 'simulado', False))
        unica = vinculos[0]['obra_id'] if obra_ids is not None and len(vinculos) == 1 else None
        repo.registrar_acao(user, 'atualizacao_iniciada', unica, {'obras': len(vinculos), 'inicio': inicio, 'fim': fim})
        resultado = omie.coletar(
            cliente,
            [{'obra_id': v['obra_id'], 'codigo_projeto': v['codigo_projeto'], 'projeto': v['nome_projeto'],
              'ic': v.get('ic_na_confirmacao')} for v in vinculos],
            inicio, fim, progresso=lambda texto: _estado.update(progresso=texto), cancelar=cancelar)
        ok = erro = reabertas = 0
        mudancas = {'pagamentos': 0, 'notas_recebidas': 0}
        for obra_id, item in resultado['obras'].items():
            if item['status'] == 'ok':
                dados = item['dados']
                if simulado:
                    dados['simulado'] = True   # a tela e o CSV avisam que não são dados reais
                anterior = repo.ultimo_lote(obra_id, 'ok')
                dif = diferencas(anterior, {'dados': dados, 'consultado_em': resultado['consultado_em']},
                                 por_id.get(obra_id))
                repo.gravar_lote(obra_id, 'ok', inicio, fim, dados=dados, consultado_em=resultado['consultado_em'])
                if dif:
                    mudancas['pagamentos'] += dif['pagamentos']['quantidade']
                    mudancas['notas_recebidas'] += len(dif['notas_recebidas'])
                if houve_mudanca(dif) and repo.reabrir_conferencia(
                        obra_id, user, {'mudancas': textos_diferencas(dif)[:5]}):
                    reabertas += 1
                ok += 1
            else:
                repo.gravar_lote(obra_id, 'erro', inicio, fim, motivo=item['motivo'],
                                 consultado_em=resultado['consultado_em'])
                erro += 1
        if not resultado['bloqueio'] and not resultado['interrompido']:
            resultado['bloqueio'] = _buscar_fornecedores_novos(repo, cliente, resultado, cancelar)
        resumo = {'ok': ok, 'erro': erro, 'nao_processadas': len(vinculos) - ok - erro,
                  'interrompido': resultado['interrompido'], 'bloqueado_ate': resultado['bloqueio'],
                  'mudancas': mudancas, 'reabertas': reabertas}
        if resultado['bloqueio']:
            _estado['bloqueado_ate'] = resultado['bloqueio']
            acao = 'atualizacao_bloqueada'
        else:
            acao = 'atualizacao_interrompida' if resultado['interrompido'] else 'atualizacao_concluida'
        repo.registrar_acao(user, acao, unica, {k: v for k, v in resumo.items() if k != 'bloqueado_ate'})
        return resumo
    finally:
        _estado.update(rodando=False, progresso='', cancelar=None)
        _trava.release()


def _buscar_fornecedores_novos(repo, cliente, resultado, cancelar):
    """Nome e documento mascarado dos fornecedores da 2.01.97 ainda não conhecidos (um ConsultarCliente
    por fornecedor novo). Falha não afeta as obras; o fornecedor que falhou só é consultado de novo após
    FORNECEDOR_FALHO_S. Devolve o horário do bloqueio do Omie, se houver; interrupção marca o resultado."""
    codigos = {p['codigo'] for item in resultado['obras'].values() if item['status'] == 'ok'
               for p in pagamentos_por_fornecedor(item['dados']) if p['codigo']}
    agora = time.monotonic()
    novos = {c for c in codigos - set(repo.fornecedores(codigos))
             if agora - _fornecedores_falhos.get(c, float('-inf')) >= FORNECEDOR_FALHO_S}
    if not novos:
        return None
    falhas = set()
    try:
        encontrados = omie.consultar_fornecedores(cliente, novos, progresso=lambda texto: _estado.update(progresso=texto),
                                                  cancelar=cancelar, falhas=falhas)
    except omie.BloqueioOmie as bloqueio:
        return bloqueio.ate
    except omie.Interrompida:
        resultado['interrompido'] = True
        return None
    finally:
        _fornecedores_falhos.update(dict.fromkeys(falhas, agora))
    repo.salvar_fornecedores(encontrados)
    if cancelar is not None and cancelar.is_set():
        resultado['interrompido'] = True
    return None


# ---------------------------------------------------------------------------
# Projetos e ligação obra ↔ projeto
# ---------------------------------------------------------------------------

def projetos_omie(user, obras=None, cliente=None, recarregar=False):
    """Projetos ativos do Omie, guardados por alguns minutos (evita repetir a mesma consulta).

    Mesmo com recarregar, uma lista com menos de 60 s é reaproveitada: o Omie recusa a mesma
    requisição repetida nesse intervalo.
    """
    checar_editar(user)
    agora = time.monotonic()
    if _projetos_cache['lista'] is not None and _projetos_cache['em'] is not None:
        idade = agora - _projetos_cache['em']
        if idade < omie.ESPERA_IDENTICA_S or (not recarregar and idade < CACHE_PROJETOS_S):
            return _projetos_cache['lista']
    _sem_bloqueio()
    try:
        lista = omie.listar_projetos(cliente or omie.criar_cliente(obras))
    except omie.BloqueioOmie as bloqueio:
        _estado['bloqueado_ate'] = bloqueio.ate
        raise
    _projetos_cache.update(em=agora, lista=lista)
    return lista


def _sem_bloqueio():
    ate = bloqueado_ate()
    if ate:
        raise omie.ErroIntegracao(str(omie.BloqueioOmie(ate)))


def obras_sem_ligacao(repo, obras, projetos):
    ligados = {v['obra_id']: v for v in repo.vinculos()}
    livres = [o for o in obras if o['id'] not in ligados]
    sugestoes = omie.sugerir_projetos(livres, projetos, ja_ligados=[v['codigo_projeto'] for v in ligados.values()])
    return [{'obra': o, **sugestoes[o['id']]} for o in sorted(livres, key=lambda o: (o.get('nome_contrato') or '').upper())]


def ligar(repo, obra, projeto, user) -> bool:
    checar_editar(user)
    return repo.salvar_vinculo(obra['id'], projeto['codigo'], projeto['nome'], obra.get('contrato_ic'), user)


def ligar_em_lote(repo, pares, user) -> int:
    """pares: [(obra, projeto)]; tudo ou nada."""
    checar_editar(user)
    return repo.salvar_vinculos_em_lote(
        [{'obra_id': o['id'], 'codigo_projeto': p['codigo'], 'nome_projeto': p['nome'], 'ic': o.get('contrato_ic')}
         for o, p in pares], user)


def desfazer_ligacao(repo, obra_id, user) -> bool:
    checar_editar(user)
    return repo.desfazer_vinculo(obra_id, user)


def marcar_conferido(repo, obra_id, user) -> bool:
    checar_editar(user)
    return repo.marcar_conferido(obra_id, user)


def configurar_chaves(repo, chave, segredo, user, testar=None):
    _sem_bloqueio()
    try:
        omie.configurar_chaves(chave, segredo, user, testar=testar)
    except omie.BloqueioOmie as bloqueio:
        _estado['bloqueado_ate'] = bloqueio.ate
        raise
    _projetos_cache.update(em=None, lista=None)
    repo.registrar_acao(user, 'chaves_configuradas')


def remover_chaves(repo, user):
    omie.remover_chaves(user)
    repo.registrar_acao(user, 'chaves_removidas')


# ---------------------------------------------------------------------------
# Consulta (mesma regra de quem vê o financeiro)
# ---------------------------------------------------------------------------

def _nome_arquivo(texto):
    texto = unicodedata.normalize('NFKD', texto or 'obra').encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Za-z0-9]+', '_', texto).strip('_').lower() or 'obra'


def exportar_financeiro(repo, obra, user, hoje=None):
    """(nome do arquivo, conteúdo CSV) da última consulta válida da obra."""
    checar_ver(user, obra)
    situacao = repo.situacao(obra['id'])
    if not situacao['lote']:
        raise ValueError('Ainda não há consulta do Omie para exportar.')
    conteudo = exportar_csv(obra, situacao['vinculo'], situacao['lote'])
    repo.registrar_acao(user, 'financeiro_exportado', obra['id'], {'consulta': situacao['lote']['consultado_em']})
    nome = f"financeiro_omie_{_nome_arquivo(obra.get('nome_contrato'))}_{(hoje or date.today()).isoformat()}.csv"
    return nome, conteudo


def historico(repo, obra, user, limite=50):
    """Ações do financeiro desta obra (sem chaves nem valores sensíveis)."""
    checar_ver(user, obra)
    return repo.auditoria(obra['id'], limite)


def historico_geral(repo, user, limite=40):
    checar_editar(user)
    return repo.auditoria(None, limite)


# ---------------------------------------------------------------------------
# Parceiros da obra (Financeiro ou coordenador da própria obra)
# ---------------------------------------------------------------------------

def _exigir_validar(user, obra):
    if not pode_validar_parceiros(user, obra):
        raise PermissionError('Somente o Financeiro e o coordenador desta obra validam os parceiros.')


def validar_parceiro(repo, obra, codigo, papel, user) -> bool:
    _exigir_validar(user, obra)
    nome = (repo.fornecedores([codigo]).get(int(codigo)) or {}).get('nome', '') if codigo else ''
    return repo.validar_parceiro(obra['id'], codigo, papel, user, nome)


def desfazer_parceiro(repo, obra, codigo, user) -> bool:
    _exigir_validar(user, obra)
    nome = (repo.fornecedores([codigo]).get(int(codigo)) or {}).get('nome', '')
    return repo.desfazer_validacao(obra['id'], codigo, user, nome)
