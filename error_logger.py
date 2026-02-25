"""
Sistema Centralizado de Logging de Erros - AgendaObras

Este módulo fornece funções para capturar e registrar erros de forma estruturada,
salvando automaticamente em arquivos de texto no diretório configurado ou
imprimindo no console caso o salvamento falhe.

Autor: Sistema AgendaObras
Data: 24/02/2026
"""

import traceback
import datetime
import os
import sys
from pathlib import Path
from typing import Optional


# Caminho padrão para salvar logs de erros
ERRO_DIR = r"G:\Meu Drive\17 - MODELOS\PROGRAMAS\AgendaObras\app\erros"


def log_error(e: Exception, modulo: str, contexto: str = "") -> None:
    """
    Registra um erro de forma estruturada, salvando em arquivo ou console.
    
    Args:
        e: A exceção capturada
        modulo: Nome do módulo onde o erro ocorreu (ex: "agenda_obras", "email_service")
        contexto: Descrição adicional do contexto do erro (ex: "Salvar obra", "Enviar email")
    
    Comportamento:
        1. Tenta salvar o erro em arquivo no diretório ERRO_DIR
        2. Se falhar, imprime todo o traceback no console
        3. Sempre mostra uma mensagem resumida no console sobre o que aconteceu
    """
    # Formata o conteúdo completo do erro
    conteudo_erro = _formatar_traceback(e, modulo, contexto)
    
    # Tenta salvar em arquivo
    sucesso = _salvar_erro_arquivo(conteudo_erro, modulo)
    
    if sucesso:
        # Mostra mensagem resumida no console
        timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        nome_arquivo = _criar_nome_arquivo(modulo)
        caminho_completo = os.path.join(ERRO_DIR, nome_arquivo)
        
        print(f"\n{'='*80}")
        print(f"❌ ERRO CAPTURADO [{timestamp}]")
        print(f"📁 Módulo: {modulo}")
        if contexto:
            print(f"📋 Contexto: {contexto}")
        print(f"💾 Erro completo salvo em:")
        print(f"   {caminho_completo}")
        print(f"{'='*80}\n")
    else:
        # Se não conseguiu salvar, mostra tudo no console
        print(f"\n{'='*80}")
        print(f"⚠️ NÃO FOI POSSÍVEL SALVAR O ERRO EM ARQUIVO")
        print(f"📋 Exibindo traceback completo no console:")
        print(f"{'='*80}\n")
        print(conteudo_erro)
        print(f"\n{'='*80}\n")


def _formatar_traceback(e: Exception, modulo: str, contexto: str) -> str:
    """
    Formata o erro com todas as informações relevantes para debug.
    
    Args:
        e: A exceção capturada
        modulo: Nome do módulo
        contexto: Contexto adicional
    
    Returns:
        String formatada com timestamp, módulo, contexto, tipo de erro, mensagem e traceback completo
    """
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    
    # Captura o traceback completo
    tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
    tb_string = ''.join(tb_lines)
    
    # Monta o conteúdo estruturado
    linhas = [
        "=" * 80,
        "REGISTRO DE ERRO - AgendaObras",
        "=" * 80,
        "",
        f"📅 Data/Hora: {timestamp}",
        f"📁 Módulo: {modulo}",
        f"📋 Contexto: {contexto if contexto else 'Não especificado'}",
        f"🔴 Tipo de Erro: {type(e).__name__}",
        f"💬 Mensagem: {str(e)}",
        "",
        "-" * 80,
        "TRACEBACK COMPLETO:",
        "-" * 80,
        "",
        tb_string,
        "",
        "-" * 80,
        "INFORMAÇÕES DO SISTEMA:",
        "-" * 80,
        f"Python: {sys.version}",
        f"Plataforma: {sys.platform}",
        "",
        "=" * 80,
    ]
    
    return "\n".join(linhas)


def _criar_nome_arquivo(modulo: str) -> str:
    """
    Gera o nome do arquivo de erro no formato: [modulo]_[dd-mm-aaaa-hh-mm-ss].txt
    
    Args:
        modulo: Nome do módulo
    
    Returns:
        Nome do arquivo formatado
    """
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y-%H-%M-%S")
    # Remove caracteres inválidos do nome do módulo
    modulo_limpo = "".join(c for c in modulo if c.isalnum() or c in ('-', '_'))
    return f"{modulo_limpo}_{timestamp}.txt"


def _garantir_diretorio() -> bool:
    """
    Garante que o diretório de erros existe, criando-o se necessário.
    
    Returns:
        True se o diretório existe ou foi criado com sucesso, False caso contrário
    """
    try:
        Path(ERRO_DIR).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def _salvar_erro_arquivo(conteudo: str, modulo: str) -> bool:
    """
    Tenta salvar o erro em um arquivo de texto.
    
    Args:
        conteudo: Conteúdo formatado do erro
        modulo: Nome do módulo (usado para gerar o nome do arquivo)
    
    Returns:
        True se salvou com sucesso, False caso contrário
    """
    try:
        # Garante que o diretório existe
        if not _garantir_diretorio():
            return False
        
        # Gera nome do arquivo e caminho completo
        nome_arquivo = _criar_nome_arquivo(modulo)
        caminho_completo = os.path.join(ERRO_DIR, nome_arquivo)
        
        # Salva o conteúdo
        with open(caminho_completo, 'w', encoding='utf-8') as f:
            f.write(conteudo)
        
        return True
    except Exception:
        # Qualquer erro ao salvar retorna False
        # (isso acionará o fallback de imprimir no console)
        return False


def log_error_simples(mensagem: str, modulo: str) -> None:
    """
    Registra uma mensagem de erro simples (sem exceção).
    Útil para situações onde você quer logar algo mas não tem uma exceção.
    
    Args:
        mensagem: Mensagem de erro a ser registrada
        modulo: Nome do módulo onde ocorreu
    """
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    
    conteudo = [
        "=" * 80,
        "REGISTRO DE ERRO SIMPLES - AgendaObras",
        "=" * 80,
        "",
        f"📅 Data/Hora: {timestamp}",
        f"📁 Módulo: {modulo}",
        f"💬 Mensagem: {mensagem}",
        "",
        "=" * 80,
    ]
    
    conteudo_texto = "\n".join(conteudo)
    
    # Tenta salvar em arquivo
    sucesso = _salvar_erro_arquivo(conteudo_texto, modulo)
    
    if sucesso:
        nome_arquivo = _criar_nome_arquivo(modulo)
        caminho_completo = os.path.join(ERRO_DIR, nome_arquivo)
        print(f"❌ Erro registrado: {mensagem}")
        print(f"💾 Salvo em: {caminho_completo}")
    else:
        print(f"❌ Erro: {mensagem}")
        print(f"⚠️ Não foi possível salvar em arquivo")
