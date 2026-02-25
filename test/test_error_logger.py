"""
Testes para o módulo error_logger.py
Valida o sistema de logging de erros do AgendaObras
"""

import sys
import os
import datetime
import shutil
from pathlib import Path

# Adiciona o diretório pai ao path para importar módulos
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from error_logger import log_error, log_error_simples, _criar_nome_arquivo, _formatar_traceback


# Diretório temporário para testes
TEST_ERROR_DIR = os.path.join(os.path.dirname(__file__), "test_errors_temp")


def setup_test_directory():
    """Cria diretório temporário para testes"""
    if os.path.exists(TEST_ERROR_DIR):
        shutil.rmtree(TEST_ERROR_DIR)
    os.makedirs(TEST_ERROR_DIR, exist_ok=True)
    print(f"✅ Diretório de teste criado: {TEST_ERROR_DIR}")


def cleanup_test_directory():
    """Remove diretório temporário após testes"""
    if os.path.exists(TEST_ERROR_DIR):
        shutil.rmtree(TEST_ERROR_DIR)
    print(f"✅ Diretório de teste removido")


def test_criar_nome_arquivo():
    """Testa geração de nome de arquivo"""
    print("\n" + "="*80)
    print("TESTE 1: Geração de nome de arquivo")
    print("="*80)
    
    nome = _criar_nome_arquivo("test_module")
    print(f"Nome gerado: {nome}")
    
    # Verifica formato: modulo_dd-mm-aaaa-hh-mm-ss.txt
    assert nome.startswith("test_module_"), "Nome deve começar com nome do módulo"
    assert nome.endswith(".txt"), "Nome deve terminar com .txt"
    assert len(nome.split('_')) >= 3, "Nome deve ter formato correto"
    
    print("✅ PASSOU: Nome de arquivo gerado corretamente")


def test_formatar_traceback():
    """Testa formatação de traceback"""
    print("\n" + "="*80)
    print("TESTE 2: Formatação de traceback")
    print("="*80)
    
    try:
        # Força um erro
        resultado = 10 / 0
    except Exception as e:
        traceback_formatado = _formatar_traceback(e, "test_module", "Divisão por zero intencional")
        
        print("Conteúdo parcial do traceback:")
        print(traceback_formatado[:500] + "...")
        
        # Verifica conteúdo
        assert "test_module" in traceback_formatado, "Deve conter nome do módulo"
        assert "Divisão por zero intencional" in traceback_formatado, "Deve conter contexto"
        assert "ZeroDivisionError" in traceback_formatado, "Deve conter tipo de erro"
        assert "TRACEBACK COMPLETO" in traceback_formatado, "Deve ter seção de traceback"
        assert "Data/Hora:" in traceback_formatado, "Deve ter timestamp"
        
        print("✅ PASSOU: Traceback formatado corretamente")


def test_log_error_com_arquivo(usar_dir_temp=True):
    """Testa logging de erro com salvamento em arquivo"""
    print("\n" + "="*80)
    print("TESTE 3: Log de erro com salvamento em arquivo")
    print("="*80)
    
    # Temporariamente altera o diretório de erros para o diretório de teste
    import error_logger
    original_dir = error_logger.ERRO_DIR
    
    if usar_dir_temp:
        error_logger.ERRO_DIR = TEST_ERROR_DIR
        print(f"📁 Usando diretório temporário: {TEST_ERROR_DIR}")
    else:
        print(f"📁 Usando diretório real: {original_dir}")
    
    try:
        # Força um erro
        lista_vazia = []
        item = lista_vazia[10]
    except Exception as e:
        print(f"\n⚠️ Capturando erro intencional: {type(e).__name__}")
        log_error(e, "test_module", "Teste de acesso a índice inválido")
        
        # Verifica se arquivo foi criado
        if usar_dir_temp:
            arquivos = os.listdir(TEST_ERROR_DIR)
            print(f"\n📂 Arquivos criados no diretório de teste: {len(arquivos)}")
            
            assert len(arquivos) > 0, "Deve ter criado pelo menos um arquivo"
            
            # Verifica conteúdo do arquivo
            arquivo_path = os.path.join(TEST_ERROR_DIR, arquivos[0])
            with open(arquivo_path, 'r', encoding='utf-8') as f:
                conteudo = f.read()
            
            print(f"📄 Arquivo criado: {arquivos[0]}")
            print(f"📏 Tamanho: {len(conteudo)} caracteres")
            
            assert "test_module" in conteudo, "Arquivo deve conter nome do módulo"
            assert "IndexError" in conteudo, "Arquivo deve conter tipo de erro"
            assert "Teste de acesso a índice inválido" in conteudo, "Arquivo deve conter contexto"
            
            print("✅ PASSOU: Erro salvo em arquivo corretamente")
        else:
            print("✅ PASSOU: Erro registrado (verifique o diretório real)")
    
    finally:
        # Restaura diretório original
        error_logger.ERRO_DIR = original_dir


def test_log_error_simples():
    """Testa logging de mensagem simples"""
    print("\n" + "="*80)
    print("TESTE 4: Log de erro simples (sem exceção)")
    print("="*80)
    
    import error_logger
    original_dir = error_logger.ERRO_DIR
    error_logger.ERRO_DIR = TEST_ERROR_DIR
    
    try:
        log_error_simples("Esta é uma mensagem de erro de teste", "test_module")
        
        arquivos = os.listdir(TEST_ERROR_DIR)
        print(f"\n📂 Total de arquivos: {len(arquivos)}")
        
        # Encontra o arquivo mais recente
        arquivos_completos = [os.path.join(TEST_ERROR_DIR, f) for f in arquivos]
        arquivo_mais_recente = max(arquivos_completos, key=os.path.getctime)
        
        with open(arquivo_mais_recente, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        
        print(f"📄 Conteúdo do arquivo:\n{conteudo}")
        
        assert "Esta é uma mensagem de erro de teste" in conteudo
        assert "REGISTRO DE ERRO SIMPLES" in conteudo
        
        print("✅ PASSOU: Erro simples registrado corretamente")
    
    finally:
        error_logger.ERRO_DIR = original_dir


def test_multiplos_erros():
    """Testa registro de múltiplos erros consecutivos"""
    print("\n" + "="*80)
    print("TESTE 5: Múltiplos erros consecutivos")
    print("="*80)
    
    import error_logger
    original_dir = error_logger.ERRO_DIR
    error_logger.ERRO_DIR = TEST_ERROR_DIR
    
    try:
        # Limpa diretório
        for arquivo in os.listdir(TEST_ERROR_DIR):
            os.remove(os.path.join(TEST_ERROR_DIR, arquivo))
        
        # Gera 3 erros diferentes
        erros = []
        
        try:
            x = int("não é um número")
        except Exception as e:
            erros.append(e)
            log_error(e, "test_conversao", "Teste de conversão inválida")
        
        try:
            arquivo_inexistente = open("arquivo_que_nao_existe_12345.txt")
        except Exception as e:
            erros.append(e)
            log_error(e, "test_arquivo", "Teste de arquivo inexistente")
        
        try:
            resultado = None.split()
        except Exception as e:
            erros.append(e)
            log_error(e, "test_none", "Teste de operação em None")
        
        arquivos = os.listdir(TEST_ERROR_DIR)
        print(f"\n📂 Arquivos criados: {len(arquivos)}")
        
        for arquivo in sorted(arquivos):
            print(f"  - {arquivo}")
        
        assert len(arquivos) == 3, f"Deveria ter 3 arquivos, mas tem {len(arquivos)}"
        
        # Verifica nomes dos arquivos
        nomes_arquivos = " ".join(arquivos)
        assert "test_conversao" in nomes_arquivos
        assert "test_arquivo" in nomes_arquivos
        assert "test_none" in nomes_arquivos
        
        print("✅ PASSOU: Múltiplos erros registrados corretamente")
    
    finally:
        error_logger.ERRO_DIR = original_dir


def test_fallback_console():
    """Testa fallback para console quando não consegue salvar arquivo"""
    print("\n" + "="*80)
    print("TESTE 6: Fallback para console (diretório inválido)")
    print("="*80)
    
    import error_logger
    original_dir = error_logger.ERRO_DIR
    
    # Define um diretório inválido/inacessível
    error_logger.ERRO_DIR = "Z:\\caminho\\totalmente\\invalido\\que\\nao\\existe"
    
    try:
        print("\n⚠️ Forçando erro de salvamento (diretório inválido)...")
        print("O traceback completo deve aparecer no console abaixo:\n")
        
        try:
            valor = {"chave": "valor"}["chave_inexistente"]
        except Exception as e:
            log_error(e, "test_fallback", "Teste de fallback para console")
        
        print("\n✅ PASSOU: Fallback funcionou (erro exibido no console acima)")
    
    finally:
        error_logger.ERRO_DIR = original_dir


def test_diretorio_real():
    """Testa com o diretório real configurado"""
    print("\n" + "="*80)
    print("TESTE 7: Teste com diretório REAL do sistema")
    print("="*80)
    
    import error_logger
    print(f"📁 Diretório configurado: {error_logger.ERRO_DIR}")
    
    resposta = input("\n⚠️ Deseja testar com o diretório real? (s/n): ").strip().lower()
    
    if resposta == 's':
        try:
            teste_valor = {"a": 1, "b": 2}
            resultado = teste_valor["c"]
        except Exception as e:
            log_error(e, "test_real", "Teste no diretório real do sistema")
            print("\n✅ Erro registrado! Verifique o diretório configurado.")
    else:
        print("⏭️ Pulado pelo usuário")


def executar_todos_testes():
    """Executa todos os testes"""
    print("\n" + "="*80)
    print("🧪 INICIANDO TESTES DO ERROR_LOGGER")
    print("="*80)
    print(f"Data/Hora: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    
    try:
        setup_test_directory()
        
        # Testes unitários
        test_criar_nome_arquivo()
        test_formatar_traceback()
        test_log_error_com_arquivo(usar_dir_temp=True)
        test_log_error_simples()
        test_multiplos_erros()
        test_fallback_console()
        
        # Teste opcional com diretório real
        test_diretorio_real()
        
        print("\n" + "="*80)
        print("✅ TODOS OS TESTES PASSARAM COM SUCESSO!")
        print("="*80)
        
    except AssertionError as e:
        print("\n" + "="*80)
        print(f"❌ TESTE FALHOU: {e}")
        print("="*80)
        raise
    
    except Exception as e:
        print("\n" + "="*80)
        print(f"❌ ERRO INESPERADO: {e}")
        print("="*80)
        import traceback
        traceback.print_exc()
        raise
    
    finally:
        cleanup_test_directory()


if __name__ == "__main__":
    executar_todos_testes()
