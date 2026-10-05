"""Consulta somente leitura ao Omie, por projeto (obra). Portado de Novos_ajustes (Dia 4).

Fontes: /api/v1/financas/mf/, /financas/extrato/, /geral/projetos/, /geral/contacorrente/,
/geral/clientes/ (só nome e documento mascarado dos fornecedores).
A chave do Omie dá acesso total à conta: a lista fechada ROTAS é a barreira do lado do
AgendaObras. Resultado incompleto nunca vira zero; erro numa obra não derruba as outras.

Limites do Omie (ajuda.omie.com.br, "Limites de Consumo da API"): requisição idêntica em
menos de 60 s é bloqueada; 10 erros seguidos no mesmo método bloqueiam por 30 min (HTTP 425);
até 240 chamadas por minuto por método.
"""
import json
import os
import re
import time
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.config import OMIE_INTERVALO_MIN_S

URL_BASE = 'https://app.omie.com.br/api/v1/'
ROTAS = {
    'ConsultarProjeto': 'geral/projetos/',
    'ListarProjetos': 'geral/projetos/',
    'ListarContasCorrentes': 'geral/contacorrente/',
    'ListarMovimentos': 'financas/mf/',
    'ListarExtrato': 'financas/extrato/',
    'ConsultarCliente': 'geral/clientes/',
}
ESPERA_IDENTICA_S = 60
BLOQUEIO_MIN = 30
HTTP_TRANSITORIO = (429, 502, 503, 504)

# (página, total de páginas, total de registros, lista, tamanho da página)
FORMATOS = {
    'movimentos': ('nPagina', 'nTotPaginas', 'nTotRegistros', 'movimentos', 'nRegPorPagina'),
    'contas': ('pagina', 'total_de_paginas', 'total_de_registros', 'ListarContasCorrentes', 'registros_por_pagina'),
    'projetos': ('pagina', 'total_de_paginas', 'total_de_registros', 'cadastro', 'registros_por_pagina'),
}


class ErroIntegracao(ValueError):
    pass


class SemRegistros(ErroIntegracao):
    """O Omie responde listagem vazia como erro ("Não existem registros...")."""


class BloqueioOmie(ErroIntegracao):
    def __init__(self, ate: datetime):
        self.ate = ate
        super().__init__(f'O Omie bloqueou as consultas por {BLOQUEIO_MIN} min; tente após '
                         f'{ate.astimezone().strftime("%H:%M")}.')


def centavos(valor):
    if valor is None:
        raise ErroIntegracao('Valor obrigatório ausente; não foi convertido em zero.')
    return int((Decimal(str(valor)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(texto or '').strip().upper())
                   if not unicodedata.combining(c))


def periodo(inicio, fim):
    a, b = date.fromisoformat(inicio), date.fromisoformat(fim)
    if a > b:
        raise ErroIntegracao('Período invertido.')
    return a.strftime('%d/%m/%Y'), b.strftime('%d/%m/%Y')


# ---------------------------------------------------------------------------
# Cliente HTTP
# ---------------------------------------------------------------------------

def _enviar_http(url, corpo):
    """Devolve (status HTTP, corpo JSON ou None)."""
    request = Request(url, data=corpo, headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=60) as resposta:
            return resposta.status, json.load(resposta)
    except HTTPError as erro:
        try:
            dados = json.loads(erro.read() or b'null')
        except (ValueError, OSError):
            dados = None
        return erro.code, dados


class ClienteOmie:
    """Chamadas sequenciais, com ritmo mínimo por método e sem repetir requisição idêntica em < 60 s."""

    def __init__(self, chave, segredo, intervalo=None, relogio=time.monotonic, dormir=time.sleep,
                 enviar=_enviar_http, agora=lambda: datetime.now(timezone.utc)):
        if not chave or not segredo:
            raise ErroIntegracao('Chaves do Omie não configuradas.')
        self._chave, self._segredo = chave, segredo
        self.intervalo = OMIE_INTERVALO_MIN_S if intervalo is None else intervalo
        self.relogio, self.dormir, self.enviar, self.agora = relogio, dormir, enviar, agora
        self._ultima_por_metodo = {}
        self._ultima_identica = {}
        self.ao_esperar = None   # callback opcional (segundos) para mostrar a espera no progresso

    def _esperar_ate(self, instante):
        falta = instante - self.relogio()
        if falta > 0:
            if self.ao_esperar and falta >= 1:
                self.ao_esperar(falta)
            self.dormir(falta)

    def _tentar(self, metodo, parametros, assinatura):
        self._esperar_ate(self._ultima_por_metodo.get(metodo, float('-inf')) + self.intervalo)
        self._esperar_ate(self._ultima_identica.get(assinatura, float('-inf')) + ESPERA_IDENTICA_S)
        corpo = json.dumps({'call': metodo, 'app_key': self._chave, 'app_secret': self._segredo,
                            'param': [parametros]}).encode()
        momento = self.relogio()
        self._ultima_por_metodo[metodo] = momento
        self._ultima_identica[assinatura] = momento
        try:
            return self.enviar(URL_BASE + ROTAS[metodo], corpo)
        except (URLError, TimeoutError, OSError):
            return None, None

    def __call__(self, metodo, parametros):
        if metodo not in ROTAS:
            raise ErroIntegracao('Método não permitido: integração somente leitura.')
        assinatura = metodo + json.dumps(parametros, sort_keys=True)
        for tentativa in range(2):
            status, dados = self._tentar(metodo, parametros, assinatura)
            if status == 425:
                raise BloqueioOmie(self.agora() + timedelta(minutes=BLOQUEIO_MIN))
            transitorio = status is None or status in HTTP_TRANSITORIO
            if transitorio and tentativa == 0:
                continue   # a próxima tentativa espera os 60 s da requisição idêntica
            if isinstance(dados, dict) and ('faultstring' in dados or 'omie_fail' in dados):
                mensagem = str(dados.get('faultstring') or 'erro não informado')
                if 'NAO EXISTEM REGISTROS' in normalizar(mensagem):
                    raise SemRegistros(f'{metodo}: sem registros.')
                raise ErroIntegracao(f'O Omie recusou {metodo}: {mensagem[:150]}')
            if status is None:
                raise ErroIntegracao(f'Falha de conexão em {metodo}.')
            if status != 200 or not isinstance(dados, dict):
                raise ErroIntegracao(f'HTTP {status} em {metodo}.')
            return dados
        raise ErroIntegracao(f'Falha de conexão em {metodo}.')


# ---------------------------------------------------------------------------
# Chaves (só na memória do processo, ou no ambiente do servidor)
# ---------------------------------------------------------------------------

_chaves_tela = {'por': None, 'em': None}


def chaves_configuradas() -> dict:
    no_ambiente = bool(os.environ.get('OMIE_APP_KEY') and os.environ.get('OMIE_APP_SECRET'))
    if not no_ambiente:
        return {'configuradas': False, 'origem': None, 'por': None, 'em': None}
    if _chaves_tela['por']:
        return {'configuradas': True, 'origem': 'tela', **_chaves_tela}
    return {'configuradas': True, 'origem': 'servidor', 'por': None, 'em': None}


def modo_simulado() -> bool:
    return os.environ.get('OMIE_MODO', '').strip().lower() == 'simulado'


def configurar_chaves(chave, segredo, user, testar=None):
    """Testa as chaves com uma consulta leve antes de guardá-las. Nunca registra o valor."""
    from services.financeiro_service import nome_usuario, pode_editar_financeiro
    if not pode_editar_financeiro(user):
        raise PermissionError('Somente o Financeiro pode informar as chaves do Omie.')
    chave, segredo = (chave or '').strip(), (segredo or '').strip()
    if not chave or not segredo:
        raise ValueError('Informe a APP KEY e a APP SECRET.')
    if testar is None:
        testar = lambda: ClienteOmie(chave, segredo)(
            'ListarContasCorrentes', {'pagina': 1, 'registros_por_pagina': 1, 'apenas_importado_api': 'N'})
    try:
        testar()
    except BloqueioOmie:
        raise
    except ErroIntegracao:
        raise ErroIntegracao('O Omie não aceitou as chaves informadas. Confira e tente de novo.') from None
    os.environ['OMIE_APP_KEY'] = chave
    os.environ['OMIE_APP_SECRET'] = segredo
    _chaves_tela.update(por=nome_usuario(user), em=datetime.now(timezone.utc).isoformat(timespec='seconds'))


def remover_chaves(user):
    from services.financeiro_service import pode_editar_financeiro
    if not pode_editar_financeiro(user):
        raise PermissionError('Somente o Financeiro pode remover as chaves do Omie.')
    if not _chaves_tela['por']:
        raise ValueError('As chaves configuradas no servidor só podem ser trocadas no servidor.')
    os.environ.pop('OMIE_APP_KEY', None)
    os.environ.pop('OMIE_APP_SECRET', None)
    _chaves_tela.update(por=None, em=None)


def criar_cliente(obras=None):
    if modo_simulado():
        from services.omie_simulado import ClienteSimulado
        return ClienteSimulado.proxima(obras or [])
    return ClienteOmie(os.environ.get('OMIE_APP_KEY'), os.environ.get('OMIE_APP_SECRET'))


# ---------------------------------------------------------------------------
# Listagens
# ---------------------------------------------------------------------------

def listar(chamar, metodo, filtros, formato):
    pk, tk, nk, rk, tamanho = FORMATOS[formato]
    pagina, paginas, total, resultado, vistos = 1, None, None, [], set()
    while True:
        try:
            resposta = chamar(metodo, dict(filtros, **{pk: pagina, tamanho: 100}))
        except SemRegistros:
            if pagina == 1:
                return []
            raise ErroIntegracao('Página intermediária sem registros; coleta interrompida.') from None
        if any(k not in resposta for k in (pk, tk, nk, rk)) or not isinstance(resposta[rk], list):
            raise ErroIntegracao('Resposta incompleta; nenhum total será substituído.')
        if int(resposta[pk]) != pagina or int(resposta[tk]) > 10000:
            raise ErroIntegracao('Paginação inválida.')
        if paginas is None:
            paginas, total = int(resposta[tk]), int(resposta[nk])
        if paginas != int(resposta[tk]) or total != int(resposta[nk]):
            raise ErroIntegracao('Dados mudaram durante a consulta; repita a atualização.')
        impressao = json.dumps(resposta[rk], sort_keys=True)
        if resposta[rk] and impressao in vistos:
            raise ErroIntegracao('Página repetida; coleta interrompida.')
        vistos.add(impressao)
        resultado.extend(resposta[rk])
        if pagina >= paginas:
            break
        pagina += 1
    if len(resultado) != total:
        raise ErroIntegracao('Quantidade recebida difere do total informado pelo Omie.')
    return resultado


def listar_projetos(chamar):
    """Projetos ativos: [{'codigo', 'nome'}]."""
    projetos = listar(chamar, 'ListarProjetos', {'apenas_importado_api': 'N'}, 'projetos')
    return [{'codigo': int(p['codigo']), 'nome': str(p.get('nome') or '').strip()}
            for p in projetos if p.get('codigo') and str(p.get('inativo') or 'N').upper() != 'S']


def numero_ic(ic):
    """'00744/2026' → 744; None se não houver número."""
    achado = re.search(r'\d+', str(ic or ''))
    return int(achado.group()) if achado else None


def numeros_no_nome(nome):
    return {int(t) for t in re.split(r'[^\d]+', str(nome or '')) if t}


def sugerir_projetos(obras, projetos, ja_ligados=()):
    """Por obra: projeto cujo nome contém o número do IC. Nunca pela cidade."""
    livres = [p for p in projetos if p['codigo'] not in set(ja_ligados)]
    sugestoes = {}
    for obra in obras:
        numero = numero_ic(obra.get('contrato_ic'))
        candidatos = [p for p in livres if numero is not None and numero in numeros_no_nome(p['nome'])]
        situacao = 'sugerida' if len(candidatos) == 1 else 'ambigua' if candidatos else 'nenhuma'
        sugestoes[obra['id']] = {'situacao': situacao, 'projetos': candidatos}
    return sugestoes


# ---------------------------------------------------------------------------
# Extrato e conciliação (regras do pacote)
# ---------------------------------------------------------------------------

def validar_vinculos(vinculos):
    ids, projetos, nomes = set(), set(), set()
    for v in vinculos:
        if not all(v.get(k) for k in ('obra_id', 'codigo_projeto', 'projeto')):
            raise ErroIntegracao('Cada obra exige ID, código do projeto e nome exato.')
        if int(v['codigo_projeto']) <= 0:
            raise ErroIntegracao('Código de projeto inválido.')
        for valor, usados in ((int(v['obra_id']), ids), (int(v['codigo_projeto']), projetos), (v['projeto'], nomes)):
            if valor in usados:
                raise ErroIntegracao('Vínculo duplicado/ambíguo. Não juntar obras pelo nome da cidade.')
            usados.add(valor)


def classificar_extrato(r):
    origem, situacao = normalizar(r.get('cOrigem', '')), normalizar(r.get('cSituacao', ''))
    if 'CANCEL' in situacao:
        return 'cancelados'
    if 'PREVISAO' in origem or situacao in ('PREVISTO', 'ATRASADO', 'VENCE HOJE', 'A VENCER'):
        return 'previsoes_abertos'
    if 'ADIANTAMENTO' in origem:
        return 'adiantamentos'
    if 'TRANSFER' in origem:
        return 'transferencias'
    # Origem distingue liquidação de mera previsão, inclusive não conciliada.
    if origem == 'CONTA PAGA':
        return 'pagamentos'
    if origem == 'CONTA RECEBIDA':
        return 'recebimentos'
    if origem == 'DEBITO EM CONTA CORRENTE':
        return 'tarifas' if normalizar(r.get('cTipoDocumento')) == 'TARIFA' else 'debitos_diretos'
    if origem == 'CREDITO EM CONTA CORRENTE':
        return 'creditos_diretos'
    return 'a_classificar'


def resumir_extrato(registros):
    grupos = defaultdict(lambda: {'centavos': 0, 'quantidade': 0})
    for r in registros:
        grupo = grupos[classificar_extrato(r)]
        grupo['centavos'] += centavos(r['nValorDocumento'])
        grupo['quantidade'] += 1
    return dict(grupos)


def conciliar(series, extrato):
    """Compara baixas do período (não títulos acumulados) por conta e categoria."""
    api, banco = defaultdict(int), defaultdict(int)
    for tipo, grupo in (('BXCP', 'pagamentos'), ('BXCR', 'recebimentos')):
        for r in series[tipo]:
            d = r['detalhes']
            if d.get('cStatus') == 'CANCELADO':
                continue
            if not d.get('nCodCC') or not d.get('cCodCateg'):
                return {'status': 'Pendente', 'motivo': 'Baixa sem conta/categoria; não confirmar por total geral.'}
            if len(r.get('categorias', [])) > 1:
                return {'status': 'Pendente', 'motivo': 'Rateio entre categorias exige conferência da distribuição.'}
            liquido = r.get('resumo', {}).get('nValLiquido')
            if liquido is None:
                return {'status': 'Pendente', 'motivo': 'Baixa sem valor líquido; conferir os campos no Omie.'}
            api[(grupo, str(d['nCodCC']), d['cCodCateg'])] += centavos(liquido)
    for r in extrato:
        grupo = classificar_extrato(r)
        if grupo in ('pagamentos', 'recebimentos'):
            valor = centavos(r['nValorDocumento'])
            banco[(grupo, str(r['conta_codigo']), r.get('cCodCategoria'))] += -valor if grupo == 'pagamentos' else valor
    linhas = [{'tipo': k[0], 'conta': k[1], 'categoria': k[2], 'api': api[k], 'extrato': banco[k],
               'diferenca': api[k] - banco[k]} for k in sorted(set(api) | set(banco), key=str)]
    confere = all(r['diferenca'] == 0 for r in linhas)
    return {'status': 'Totais conferem' if confere else 'Divergência', 'linhas': linhas,
            'escopo': 'Baixas do período por conta e categoria; não valida documentos ou classificação contábil.'}


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------

CAMPOS_EXTRATO = ('nCodLancamento', 'nCodLancRelac', 'cSituacao', 'dDataLancamento', 'cDesCliente',
                  'cTipoDocumento', 'cNumero', 'nValorDocumento', 'cCodCategoria', 'cDesCategoria',
                  'cDocumentoFiscal', 'cParcela', 'cOrigem', 'cProjeto', 'nCodCliente')
CAMPOS_MOVIMENTO = ('nCodTitulo', 'nCodBaixa', 'cCodProjeto', 'nCodCC', 'nCodCliente', 'cCodCateg', 'cStatus',
                    'cOrigem', 'dDtPagamento', 'dDtVenc', 'cNumParcela', 'cNumDocFiscal', 'nValorTitulo')


def _iso(data_br):
    return datetime.strptime(data_br, '%d/%m/%Y').date().isoformat()


def _series_do_projeto(chamar, codigo, de, ate, inicio, fim, avisos):
    """CP/CR: retrato atual dos títulos; BXCP/BXCR: baixas no período. Nunca somados juntos."""
    series = {}
    for tipo in ('CP', 'CR', 'BXCP', 'BXCR'):
        filtros = {'nCodProjeto': int(codigo), 'cTpLancamento': tipo}
        if tipo.startswith('BX'):
            filtros.update(dDtPagtoDe=de, dDtPagtoAte=ate)
        linhas = listar(chamar, 'ListarMovimentos', filtros, 'movimentos')
        if not linhas:
            avisos.append(f'O Omie não trouxe registros de {tipo} para este projeto.')
        ids = set()
        for linha in linhas:
            d = linha.get('detalhes', {})
            if str(d.get('cCodProjeto')) != str(codigo):
                raise ErroIntegracao('Movimento financeiro de outro projeto.')
            chave = d.get('nCodBaixa') if tipo.startswith('BX') else d.get('nCodTitulo')
            if not chave or chave in ids:
                raise ErroIntegracao('Título/baixa sem identidade única.')
            ids.add(chave)
            if tipo.startswith('BX'):
                try:
                    pago_em = _iso(d.get('dDtPagamento', ''))
                except ValueError:
                    raise ErroIntegracao('Baixa sem data de pagamento.') from None
                if not inicio <= pago_em <= fim:
                    raise ErroIntegracao('Baixa fora do período solicitado.')
        series[tipo] = [{'detalhes': {k: r['detalhes'].get(k) for k in CAMPOS_MOVIMENTO},
                         'resumo': r.get('resumo', {}), 'categorias': r.get('categorias', [])} for r in linhas]
    return series


def coletar(chamar, vinculos, inicio, fim, progresso=None, cancelar=None):
    """Uma atualização. Devolve {'obras': {obra_id: {'status': 'ok'|'erro', ...}}, 'interrompido', 'bloqueio'}.

    Obras ausentes de 'obras' não foram processadas (interrupção ou bloqueio): mantêm a consulta anterior.
    """
    validar_vinculos(vinculos)
    de, ate = periodo(inicio, fim)
    resultado = {'consultado_em': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                 'inicio': inicio, 'fim': fim, 'obras': {}, 'interrompido': False, 'bloqueio': None}

    def avisar(texto):
        if progresso:
            progresso(texto)

    def parar():
        if cancelar is not None and cancelar.is_set():
            resultado['interrompido'] = True
            return True
        return False

    def erro(obra_id, motivo):
        resultado['obras'][obra_id] = {'status': 'erro', 'motivo': motivo}

    total = len(vinculos)
    try:
        pendentes = {}
        for i, v in enumerate(vinculos, 1):
            if parar():
                return resultado
            avisar(f'Obra {i} de {total} · conferindo o projeto')
            oid = int(v['obra_id'])
            try:
                projeto = chamar('ConsultarProjeto', {'codigo': int(v['codigo_projeto'])})
                if str(projeto.get('codigo')) != str(v['codigo_projeto']):
                    raise ErroIntegracao('Projeto não encontrado no Omie com este código.')
                nome = str(projeto.get('nome') or '').strip()
                avisos = []
                if nome != v['projeto']:
                    avisos.append(f'O projeto foi renomeado no Omie para "{nome}". Ligação a reconferir.')
                pendentes[oid] = {'vinculo': v, 'projeto': nome or v['projeto'], 'avisos': avisos}
            except BloqueioOmie:
                raise
            except ErroIntegracao as e:
                erro(oid, str(e))
        if not pendentes:
            return resultado

        por_nome = {p['projeto']: oid for oid, p in pendentes.items()}
        try:
            avisar('Contas correntes')
            contas = listar(chamar, 'ListarContasCorrentes', {'apenas_importado_api': 'N'}, 'contas')
            contas_ids = [int(c['nCodCC']) for c in contas]
            if not contas_ids or len(contas_ids) != len(set(contas_ids)):
                raise ErroIntegracao('Cadastro de contas vazio ou duplicado.')
            extratos, chaves, erros_extrato = defaultdict(list), defaultdict(set), {}
            for j, conta in enumerate(contas, 1):
                if parar():
                    return resultado
                avisar(f'Extrato da conta {j} de {len(contas)}')
                cc = int(conta['nCodCC'])
                resposta = chamar('ListarExtrato', {'nCodCC': cc, 'dPeriodoInicial': de,
                                                    'dPeriodoFinal': ate, 'cExibirApenasSaldo': 'N'})
                if int(resposta.get('nCodCC', -1)) != cc or not isinstance(resposta.get('listaMovimentos'), list):
                    raise ErroIntegracao('Extrato incompleto ou de outra conta.')
                for r in resposta['listaMovimentos']:
                    oid = por_nome.get(r.get('cProjeto'))
                    if oid is None or oid in erros_extrato:
                        continue
                    try:
                        if not r.get('nCodLancamento') or not r.get('dDataLancamento'):
                            raise ErroIntegracao('Movimento do extrato sem código/data; não é possível deduplicar.')
                        if not inicio <= _iso(r['dDataLancamento']) <= fim:
                            raise ErroIntegracao('Extrato retornou data fora do período.')
                        chave = (cc, r['nCodLancamento'], r['dDataLancamento'], r.get('cOrigem'), r.get('cParcela'))
                        if chave in chaves[oid]:
                            raise ErroIntegracao('Extrato com identidade repetida; conferir antes de somar.')
                        chaves[oid].add(chave)
                    except ValueError as e:
                        erros_extrato[oid] = str(e) if isinstance(e, ErroIntegracao) else 'Data inválida no extrato.'
                        continue
                    # Sem CPF/CNPJ, dados bancários, observações ou credenciais no resultado.
                    extratos[oid].append({**{k: r.get(k) for k in CAMPOS_EXTRATO},
                                          'conta_codigo': cc, 'conta_nome': conta.get('descricao', str(cc))})
        except BloqueioOmie:
            raise
        except ErroIntegracao as e:
            for oid in pendentes:
                erro(oid, f'Consulta de contas/extrato falhou: {e}')
            return resultado

        contas_resumo = [{'codigo': c['nCodCC'], 'nome': c.get('descricao')} for c in contas]
        for k, (oid, p) in enumerate(pendentes.items(), 1):
            if parar():
                return resultado
            if oid in erros_extrato:
                erro(oid, erros_extrato[oid])
                continue
            avisar(f'Obra {k} de {len(pendentes)} · movimentos financeiros')
            try:
                avisos = list(p['avisos'])
                codigo = int(p['vinculo']['codigo_projeto'])
                series = _series_do_projeto(chamar, codigo, de, ate, inicio, fim, avisos)
                registros = extratos[oid]
                resultado['obras'][oid] = {'status': 'ok', 'dados': {
                    'projeto': p['projeto'], 'codigo_projeto': codigo, 'series': series,
                    'extrato': registros, 'resumo_extrato': resumir_extrato(registros),
                    'conciliacao': conciliar(series, registros), 'contas': contas_resumo, 'avisos': avisos}}
            except BloqueioOmie:
                raise
            except ErroIntegracao as e:
                erro(oid, str(e))
    except BloqueioOmie as bloqueio:
        resultado['bloqueio'] = bloqueio.ate
    return resultado


# ---------------------------------------------------------------------------
# Fornecedores (nome e documento mascarado, para validar os parceiros da obra)
# ---------------------------------------------------------------------------

def mascarar_documento(documento):
    """CNPJ 12.345.***/0001-** · CPF ***.456.789-**. O documento completo nunca sai desta função."""
    digitos = re.sub(r'\D', '', str(documento or ''))
    if len(digitos) == 14:
        return f'{digitos[:2]}.{digitos[2:5]}.***/{digitos[8:12]}-**'
    if len(digitos) == 11:
        return f'***.{digitos[3:6]}.{digitos[6:9]}-**'
    return 'documento não informado'


def consultar_fornecedores(chamar, codigos, progresso=None, cancelar=None):
    """{codigo: {'nome', 'documento_mascarado'}}. Fornecedor que falhar fica de fora (a tela mostra o
    nome do extrato ou o código); só o bloqueio do Omie interrompe."""
    encontrados = {}
    codigos = sorted({int(c) for c in codigos if c})
    for i, codigo in enumerate(codigos, 1):
        if cancelar is not None and cancelar.is_set():
            break
        if progresso:
            progresso(f'Fornecedor {i} de {len(codigos)}')
        try:
            resposta = chamar('ConsultarCliente', {'codigo_cliente_omie': codigo})
        except BloqueioOmie:
            raise
        except ErroIntegracao:
            continue
        if str(resposta.get('codigo_cliente_omie', codigo)) != str(codigo):
            continue
        nome = str(resposta.get('razao_social') or resposta.get('nome_fantasia') or '').strip()
        if nome:
            encontrados[codigo] = {'nome': nome[:150], 'documento_mascarado': mascarar_documento(resposta.get('cnpj_cpf'))}
    return encontrados
