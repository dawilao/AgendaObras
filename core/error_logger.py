"""
Sistema Centralizado de Logging de Erros - AgendaObras
"""

import traceback
import datetime
import os
import sys
from pathlib import Path
from typing import Optional

# Aponta para a raiz do projeto (um nível acima de core/)
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERRO_DIR = os.path.join(_SCRIPT_DIR, "erros")

if os.getenv('AGENDAOBRAS_ERRO_DIR'):
    ERRO_DIR = os.getenv('AGENDAOBRAS_ERRO_DIR')


def log_error(e: Exception, modulo: str, contexto: str = "") -> None:
    conteudo_erro = _formatar_traceback(e, modulo, contexto)
    sucesso = _salvar_erro_arquivo(conteudo_erro, modulo)

    if sucesso:
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
        print(f"\n{'='*80}")
        print(f"⚠️ NÃO FOI POSSÍVEL SALVAR O ERRO EM ARQUIVO")
        print(f"📋 Exibindo traceback completo no console:")
        print(f"{'='*80}\n")
        print(conteudo_erro)
        print(f"\n{'='*80}\n")


def _formatar_traceback(e: Exception, modulo: str, contexto: str) -> str:
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
    tb_string = ''.join(tb_lines)

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
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y-%H-%M-%S")
    modulo_limpo = "".join(c for c in modulo if c.isalnum() or c in ('-', '_'))
    return f"{modulo_limpo}_{timestamp}.txt"


def _garantir_diretorio() -> bool:
    try:
        Path(ERRO_DIR).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def _salvar_erro_arquivo(conteudo: str, modulo: str) -> bool:
    try:
        if not _garantir_diretorio():
            return False
        nome_arquivo = _criar_nome_arquivo(modulo)
        caminho_completo = os.path.join(ERRO_DIR, nome_arquivo)
        with open(caminho_completo, 'w', encoding='utf-8') as f:
            f.write(conteudo)
        return True
    except Exception:
        return False


def log_error_simples(mensagem: str, modulo: str) -> None:
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
    sucesso = _salvar_erro_arquivo(conteudo_texto, modulo)

    if sucesso:
        nome_arquivo = _criar_nome_arquivo(modulo)
        caminho_completo = os.path.join(ERRO_DIR, nome_arquivo)
        print(f"❌ Erro registrado: {mensagem}")
        print(f"💾 Salvo em: {caminho_completo}")
    else:
        print(f"❌ Erro: {mensagem}")
        print(f"⚠️ Não foi possível salvar em arquivo")
