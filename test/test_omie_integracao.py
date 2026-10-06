import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import unittest
from unittest import mock
from datetime import datetime, timezone

from services import omie_integracao as omie
from services.omie_integracao import (BloqueioOmie, ClienteOmie, ErroIntegracao, classificar_extrato, coletar,
                                      conciliar, listar, sugerir_projetos, validar_vinculos)


def vinculo(codigo=10, ic='001'):
    return {'obra_id': codigo, 'codigo_projeto': codigo, 'projeto': 'CIDADE/' + ic, 'ic': ic}


def chamada_padrao(consultas=None, falha_projeto=(), movimento_de_outro=()):
    """Omie falso: duas contas, projetos 10 (CIDADE/001) e 20 (CIDADE/002) na mesma cidade."""
    def chamar(metodo, args):
        if consultas is not None:
            consultas.append((metodo, args))
        if metodo == 'ConsultarProjeto':
            if args['codigo'] in falha_projeto:
                raise ErroIntegracao('O Omie recusou ConsultarProjeto: não cadastrado')
            return {'codigo': args['codigo'], 'nome': 'CIDADE/' + ('001' if args['codigo'] == 10 else '002')}
        if metodo == 'ListarContasCorrentes':
            return {'pagina': 1, 'total_de_paginas': 1, 'total_de_registros': 2,
                    'ListarContasCorrentes': [{'nCodCC': 1}, {'nCodCC': 2}]}
        if metodo == 'ListarExtrato':
            cc = args['nCodCC']
            return {'nCodCC': cc, 'listaMovimentos': [{
                'nCodLancamento': cc, 'cProjeto': 'CIDADE/001', 'dDataLancamento': '10/09/2026',
                'cOrigem': 'Conta Paga', 'nValorDocumento': -50, 'cCodCategoria': 'MAT'}]}
        assert 'nCodCC' not in args and 'cCodDepartamento' not in args
        projeto = args['nCodProjeto']
        rows = []
        if projeto == 10 and args['cTpLancamento'] == 'BXCP':
            rows = [{'detalhes': {'cCodProjeto': 99 if projeto in movimento_de_outro else 10, 'nCodBaixa': cc,
                                  'nCodTitulo': 7, 'nCodCC': cc, 'cCodCateg': 'MAT', 'dDtPagamento': '10/09/2026'},
                     'resumo': {'nValLiquido': 50}} for cc in (1, 2)]
        return {'nPagina': 1, 'nTotPaginas': 1, 'nTotRegistros': len(rows), 'movimentos': rows}
    return chamar


class ColetaTest(unittest.TestCase):
    def test_cidade_igual_nao_mistura_projetos_e_duas_contas(self):
        consultas = []
        dados = coletar(chamada_padrao(consultas), [vinculo(), vinculo(20, '002')], '2026-09-01', '2026-09-30')
        primeira, segunda = dados['obras'][10]['dados'], dados['obras'][20]['dados']
        self.assertEqual(len(primeira['extrato']), 2)
        self.assertEqual(segunda['extrato'], [])
        self.assertEqual(primeira['conciliacao']['status'], 'Totais conferem')
        self.assertEqual(sum(r['extrato'] for r in primeira['conciliacao']['linhas']), 10000)
        self.assertEqual(len([q for q in consultas if q[0] == 'ListarExtrato']), 2)

    def test_nao_aceita_mesmo_projeto_em_duas_obras(self):
        with self.assertRaises(ErroIntegracao):
            validar_vinculos([vinculo(), dict(vinculo(), obra_id=30)])

    def test_obra_com_erro_nao_derruba_as_outras(self):
        dados = coletar(chamada_padrao(falha_projeto=(20,)), [vinculo(), vinculo(20, '002')],
                        '2026-09-01', '2026-09-30')
        self.assertEqual(dados['obras'][10]['status'], 'ok')
        self.assertEqual(dados['obras'][20]['status'], 'erro')
        self.assertIn('ConsultarProjeto', dados['obras'][20]['motivo'])

    def test_movimento_de_outro_projeto_vira_erro_so_da_obra(self):
        dados = coletar(chamada_padrao(movimento_de_outro=(10,)), [vinculo(), vinculo(20, '002')],
                        '2026-09-01', '2026-09-30')
        self.assertEqual(dados['obras'][10]['status'], 'erro')
        self.assertEqual(dados['obras'][20]['status'], 'ok')

    def test_projeto_renomeado_vira_aviso_e_usa_o_nome_atual_no_extrato(self):
        v = dict(vinculo(), projeto='NOME ANTIGO')
        dados = coletar(chamada_padrao(), [v], '2026-09-01', '2026-09-30')['obras'][10]
        self.assertEqual(dados['status'], 'ok')
        self.assertEqual(len(dados['dados']['extrato']), 2)
        self.assertTrue(any('renomeado' in a for a in dados['dados']['avisos']))

    def test_falha_nas_contas_marca_todas_como_erro(self):
        base = chamada_padrao()

        def chamar(metodo, args):
            if metodo == 'ListarContasCorrentes':
                return {'pagina': 1}
            return base(metodo, args)
        dados = coletar(chamar, [vinculo(), vinculo(20, '002')], '2026-09-01', '2026-09-30')
        self.assertEqual({o['status'] for o in dados['obras'].values()}, {'erro'})

    def test_cancelamento_deixa_obras_sem_resultado(self):
        cancelar = threading.Event()

        def progresso(texto):
            if texto.startswith('Obra 1 de 2 · movimentos'):
                cancelar.set()
        dados = coletar(chamada_padrao(), [vinculo(), vinculo(20, '002')], '2026-09-01', '2026-09-30',
                        progresso=progresso, cancelar=cancelar)
        self.assertTrue(dados['interrompido'])
        self.assertIn(10, dados['obras'])
        self.assertNotIn(20, dados['obras'])

    def test_valor_malformado_vira_erro_so_da_obra(self):
        base = chamada_padrao()

        def chamar(metodo, args):
            resposta = base(metodo, args)
            if metodo == 'ListarMovimentos' and args['nCodProjeto'] == 10 and args['cTpLancamento'] == 'BXCP':
                for linha in resposta['movimentos']:
                    linha['resumo']['nValLiquido'] = ''
            return resposta
        dados = coletar(chamar, [vinculo(), vinculo(20, '002')], '2026-09-01', '2026-09-30')
        self.assertEqual(dados['obras'][10]['status'], 'erro')
        self.assertEqual(dados['obras'][20]['status'], 'ok')

    def test_conta_sem_codigo_vira_erro_das_obras_sem_derrubar_a_coleta(self):
        base = chamada_padrao()

        def chamar(metodo, args):
            if metodo == 'ListarContasCorrentes':
                return {'pagina': 1, 'total_de_paginas': 1, 'total_de_registros': 1,
                        'ListarContasCorrentes': [{'descricao': 'sem código'}]}
            return base(metodo, args)
        dados = coletar(chamar, [vinculo(), vinculo(20, '002')], '2026-09-01', '2026-09-30')
        self.assertEqual({o['status'] for o in dados['obras'].values()}, {'erro'})
        self.assertIn('formato inesperado', dados['obras'][10]['motivo'])

    def test_interrupcao_durante_a_espera_guarda_obras_concluidas(self):
        base = chamada_padrao()

        def chamar(metodo, args):
            if metodo == 'ListarMovimentos' and args['nCodProjeto'] == 20:
                raise omie.Interrompida()
            return base(metodo, args)
        dados = coletar(chamar, [vinculo(), vinculo(20, '002')], '2026-09-01', '2026-09-30')
        self.assertTrue(dados['interrompido'])
        self.assertEqual(dados['obras'][10]['status'], 'ok')
        self.assertNotIn(20, dados['obras'])

    def test_bloqueio_guarda_obras_concluidas(self):
        base = chamada_padrao()
        ate = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)

        def chamar(metodo, args):
            if metodo == 'ListarMovimentos' and args['nCodProjeto'] == 20:
                raise BloqueioOmie(ate)
            return base(metodo, args)
        dados = coletar(chamar, [vinculo(), vinculo(20, '002')], '2026-09-01', '2026-09-30')
        self.assertEqual(dados['bloqueio'], ate)
        self.assertEqual(dados['obras'][10]['status'], 'ok')
        self.assertNotIn(20, dados['obras'])


class ListagemTest(unittest.TestCase):
    def test_paginacao_completa(self):
        def chamar(m, a):
            return {'nPagina': a['nPagina'], 'nTotPaginas': 2, 'nTotRegistros': 2, 'movimentos': [{'id': a['nPagina']}]}
        self.assertEqual(len(listar(chamar, 'ListarMovimentos', {}, 'movimentos')), 2)

    def test_pagina_repetida_e_falha_nao_viram_zero(self):
        def repetida(m, a):
            return {'nPagina': a['nPagina'], 'nTotPaginas': 2, 'nTotRegistros': 2, 'movimentos': [{'id': 1}]}
        with self.assertRaises(ErroIntegracao):
            listar(repetida, 'ListarMovimentos', {}, 'movimentos')

        def falha(m, a):
            raise ErroIntegracao('O Omie recusou')
        with self.assertRaises(ErroIntegracao):
            listar(falha, 'ListarMovimentos', {}, 'movimentos')

    def test_sem_registros_na_primeira_pagina_e_lista_vazia(self):
        def vazia(m, a):
            raise omie.SemRegistros('sem registros')
        self.assertEqual(listar(vazia, 'ListarMovimentos', {}, 'movimentos'), [])

    def test_falha_em_pagina_intermediaria(self):
        def chamar(m, a):
            if a['nPagina'] == 2:
                raise omie.SemRegistros('sem registros')
            return {'nPagina': 1, 'nTotPaginas': 3, 'nTotRegistros': 3, 'movimentos': [{'id': 1}]}
        with self.assertRaises(ErroIntegracao):
            listar(chamar, 'ListarMovimentos', {}, 'movimentos')

    def test_classificacao_e_nao_conciliado(self):
        for origem, tipo, esperado in [('Conta Paga', '', 'pagamentos'),
                                       ('Débito em Conta Corrente', 'Tarifa', 'tarifas'),
                                       ('Adiantamento de Compra', '', 'adiantamentos'),
                                       ('Previsão de Pedido de Compra', '', 'previsoes_abertos'),
                                       ('Crédito em Conta Corrente', '', 'creditos_diretos')]:
            self.assertEqual(classificar_extrato({'cOrigem': origem, 'cTipoDocumento': tipo,
                                                  'cSituacao': 'Não Conciliado'}), esperado)

    def test_diferenca_por_conta_nao_compensa_em_total(self):
        series = {'BXCP': [{'detalhes': {'nCodCC': 1, 'cCodCateg': 'MAT'}, 'resumo': {'nValLiquido': 100}}], 'BXCR': []}
        extrato = [{'conta_codigo': 2, 'cCodCategoria': 'MAT', 'cOrigem': 'Conta Paga', 'nValorDocumento': -100}]
        self.assertEqual(conciliar(series, extrato)['status'], 'Divergência')

    def test_baixa_sem_valor_liquido_fica_pendente(self):
        series = {'BXCP': [{'detalhes': {'nCodCC': 1, 'cCodCateg': 'MAT'}, 'resumo': {}}], 'BXCR': []}
        self.assertEqual(conciliar(series, [])['status'], 'Pendente')


class SugestaoTest(unittest.TestCase):
    PROJETOS = [{'codigo': 1, 'nome': '8756/0606/ALMENARA/00744'}, {'codigo': 2, 'nome': '1000/0001/MEDINA/03738'},
                {'codigo': 3, 'nome': '1000/0002/BOM JESUS/01111'}, {'codigo': 4, 'nome': '1000/0003/BOM JESUS/01111'}]

    def test_unica_ambigua_e_nenhuma(self):
        obras = [{'id': 1, 'contrato_ic': '00744/2026'}, {'id': 2, 'contrato_ic': '03738-2026'},
                 {'id': 3, 'contrato_ic': '01111/2026'}, {'id': 4, 'contrato_ic': '99999/2026'}, {'id': 5}]
        s = sugerir_projetos(obras, self.PROJETOS)
        self.assertEqual((s[1]['situacao'], s[1]['projetos'][0]['codigo']), ('sugerida', 1))
        self.assertEqual(s[2]['projetos'][0]['codigo'], 2)
        self.assertEqual(s[3]['situacao'], 'ambigua')
        self.assertEqual(s[4]['situacao'], 'nenhuma')
        self.assertEqual(s[5]['situacao'], 'nenhuma')

    def test_projeto_ja_ligado_nao_e_sugerido(self):
        s = sugerir_projetos([{'id': 1, 'contrato_ic': '00744/2026'}], self.PROJETOS, ja_ligados=[1])
        self.assertEqual(s[1]['situacao'], 'nenhuma')


class Relogio:
    def __init__(self):
        self.t = 0.0
        self.esperas = []

    def agora(self):
        return self.t

    def dormir(self, s):
        self.esperas.append(round(s, 3))
        self.t += s


class ClienteTest(unittest.TestCase):
    def cliente(self, respostas, intervalo=0.3):
        self.relogio = Relogio()
        self.enviados = []
        fila = list(respostas)

        def enviar(url, corpo):
            self.enviados.append((self.relogio.t, url, corpo))
            return fila.pop(0)
        return ClienteOmie('chave', 'segredo', intervalo=intervalo, relogio=self.relogio.agora,
                           dormir=self.relogio.dormir, enviar=enviar)

    def test_requisicao_identica_espera_60_segundos(self):
        c = self.cliente([(200, {'ok': 1}), (200, {'ok': 2})])
        c('ListarProjetos', {'pagina': 1})
        c('ListarProjetos', {'pagina': 1})
        self.assertGreaterEqual(self.enviados[1][0] - self.enviados[0][0], 60)

    def test_intervalo_minimo_entre_chamadas_do_mesmo_metodo(self):
        c = self.cliente([(200, {'a': 1}), (200, {'a': 2})])
        c('ListarProjetos', {'pagina': 1})
        c('ListarProjetos', {'pagina': 2})
        self.assertAlmostEqual(self.enviados[1][0] - self.enviados[0][0], 0.3)

    def test_transitorio_tenta_de_novo_so_depois_de_60_segundos(self):
        c = self.cliente([(503, None), (200, {'ok': True})])
        self.assertEqual(c('ListarProjetos', {'pagina': 1}), {'ok': True})
        self.assertGreaterEqual(self.enviados[1][0] - self.enviados[0][0], 60)

    def test_transitorio_duas_vezes_e_erro(self):
        c = self.cliente([(503, None), (503, None)])
        with self.assertRaises(ErroIntegracao):
            c('ListarProjetos', {'pagina': 1})
        self.assertEqual(len(self.enviados), 2)

    def test_425_e_bloqueio(self):
        c = self.cliente([(425, None)])
        with self.assertRaises(BloqueioOmie) as ctx:
            c('ListarProjetos', {'pagina': 1})
        self.assertIsNotNone(ctx.exception.ate)
        self.assertEqual(len(self.enviados), 1)

    def test_sem_registros_e_erro_de_negocio(self):
        c = self.cliente([(500, {'faultstring': 'ERROR: Não existem registros para a página [1]!'}),
                          (500, {'faultstring': 'ERROR: Tag inválida'})])
        with self.assertRaises(omie.SemRegistros):
            c('ListarMovimentos', {'nPagina': 1})
        with self.assertRaises(ErroIntegracao) as ctx:
            c('ListarMovimentos', {'nPagina': 2})
        self.assertNotIsInstance(ctx.exception, omie.SemRegistros)

    def test_metodo_fora_da_lista_e_recusado(self):
        c = self.cliente([])
        with self.assertRaises(ErroIntegracao):
            c('IncluirContaPagar', {})
        self.assertEqual(self.enviados, [])

    def test_centavos_invalido_e_erro_de_integracao(self):
        for valor in ('', 'abc', [1]):
            with self.assertRaises(ErroIntegracao):
                omie.centavos(valor)
        self.assertEqual(omie.centavos('12.345'), 1235)

    def test_dois_clientes_do_mesmo_processo_respeitam_os_60_segundos(self):
        relogio, enviados, ritmo = Relogio(), [], omie.novo_ritmo()

        def enviar(url, corpo):
            enviados.append(relogio.t)
            return 200, {'ok': 1}
        for _ in range(2):   # ex.: "Atualizar esta obra" e logo depois "Atualizar" na barra
            ClienteOmie('chave', 'segredo', intervalo=0.3, relogio=relogio.agora, dormir=relogio.dormir,
                        enviar=enviar, ritmo=ritmo)('ListarContasCorrentes', {'pagina': 1})
        self.assertGreaterEqual(enviados[1] - enviados[0], 60)

    def test_criar_cliente_usa_o_ritmo_do_processo(self):
        with mock.patch.dict(os.environ, {'OMIE_APP_KEY': 'k', 'OMIE_APP_SECRET': 's', 'OMIE_MODO': ''}):
            primeiro, segundo = omie.criar_cliente(), omie.criar_cliente()
        self.assertIs(primeiro.ritmo, segundo.ritmo)

    def test_interromper_nao_espera_a_pausa(self):
        c = self.cliente([(200, {'ok': 1})])
        c('ListarProjetos', {'pagina': 1})
        c.cancelar = threading.Event()
        c.cancelar.set()
        with self.assertRaises(omie.Interrompida):
            c('ListarProjetos', {'pagina': 1})     # idêntica: esperaria 60 s
        self.assertEqual(len(self.enviados), 1)

    def test_mensagem_de_erro_nao_contem_as_chaves(self):
        c = self.cliente([(500, {'faultstring': 'ERROR: Tag inválida'})])
        with self.assertRaises(ErroIntegracao) as ctx:
            c('ListarProjetos', {'pagina': 1})
        self.assertNotIn('segredo', str(ctx.exception))
        self.assertNotIn('chave', str(ctx.exception))


class ChavesTest(unittest.TestCase):
    FIN = {'id': 1, 'nome': 'Fin', 'sobrenome': 'Teste', 'financeiro': 1}

    def setUp(self):
        self.antes = {k: os.environ.pop(k, None) for k in ('OMIE_APP_KEY', 'OMIE_APP_SECRET')}
        omie._chaves_tela.update(por=None, em=None)

    def tearDown(self):
        for k, v in self.antes.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v
        omie._chaves_tela.update(por=None, em=None)

    def test_so_o_financeiro_informa_as_chaves(self):
        with self.assertRaises(PermissionError):
            omie.configurar_chaves('k', 's', {'id': 2, 'is_admin': True}, testar=lambda: None)
        self.assertNotIn('OMIE_APP_KEY', os.environ)

    def test_chaves_recusadas_nao_sao_guardadas(self):
        def recusa():
            raise ErroIntegracao('HTTP 500')
        with self.assertRaises(ErroIntegracao) as ctx:
            omie.configurar_chaves('minha-chave', 'meu-segredo', self.FIN, testar=recusa)
        self.assertNotIn('OMIE_APP_KEY', os.environ)
        self.assertNotIn('minha-chave', str(ctx.exception))

    def test_chaves_aceitas_ficam_na_memoria(self):
        omie.configurar_chaves(' k ', ' s ', self.FIN, testar=lambda: None)
        self.assertEqual((os.environ['OMIE_APP_KEY'], os.environ['OMIE_APP_SECRET']), ('k', 's'))
        info = omie.chaves_configuradas()
        self.assertEqual((info['origem'], info['por']), ('tela', 'Fin Teste'))
        omie.remover_chaves(self.FIN)
        self.assertFalse(omie.chaves_configuradas()['configuradas'])

    def test_chaves_do_servidor_nao_sao_removidas_pela_tela(self):
        os.environ['OMIE_APP_KEY'], os.environ['OMIE_APP_SECRET'] = 'k', 's'
        self.assertEqual(omie.chaves_configuradas()['origem'], 'servidor')
        with self.assertRaises(ValueError):
            omie.remover_chaves(self.FIN)


if __name__ == '__main__':
    unittest.main()
