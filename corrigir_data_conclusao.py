"""
Script de correção da data de conclusão de obras finalizadas.

Problema: salvar o card de edição apagava obras.data_conclusao (o UPDATE de
atualizar_obra gravava NULL quando o campo não vinha do formulário). Obras
finalizadas (status_conclusao_obra preenchido) ficaram sem a data.

O que este script faz:
  1. Para obras finalizadas sem data_conclusao, preenche com a data da última
     tarefa concluída da obra (MAX(obra_checklist.data_conclusao)). É uma
     aproximação: a data real da finalização foi perdida.
  2. Apenas LISTA (não altera) obras com status 'Concluída' sem finalização
     registrada; elas devem ser concluídas pelo card (select Status → Concluído).

Uso:
    python corrigir_data_conclusao.py              # dry-run
    python corrigir_data_conclusao.py --executar   # aplica (pede confirmação)
"""

import argparse
import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Resolução do caminho do banco (mesma lógica de db/connection.py)
# ---------------------------------------------------------------------------
_CAMINHO_SERVIDOR = '/root/AgendaObras/db'
_DIR_SCRIPT = os.path.dirname(os.path.abspath(__file__))
_RAIZ_PROJETO = (
    _DIR_SCRIPT
    if os.path.isdir(os.path.join(_DIR_SCRIPT, 'db'))
    else os.path.dirname(_DIR_SCRIPT)
)
_CAMINHO_LOCAL = os.path.join(_RAIZ_PROJETO, 'db')


def _resolver_caminho_db() -> str:
    env_path = (os.getenv('AGENDA_OBRAS_DB_PATH') or '').strip()
    if env_path:
        return env_path
    if os.path.isdir(_CAMINHO_SERVIDOR):
        return os.path.join(_CAMINHO_SERVIDOR, 'agendaobras.db')
    return os.path.join(_CAMINHO_LOCAL, 'agendaobras.db')


CAMINHO_DB = _resolver_caminho_db()

SQL_SEM_DATA = """
    SELECT o.id, o.nome_contrato, o.status_conclusao_obra,
           (SELECT MAX(oc.data_conclusao) FROM obra_checklist oc
             WHERE oc.obra_id = o.id AND oc.concluido = 1) AS data_sugerida
    FROM obras o
    WHERE o.status_conclusao_obra IN ('sem_pendencias', 'com_pendencias')
      AND (o.data_conclusao IS NULL OR o.data_conclusao = '')
    ORDER BY o.nome_contrato
"""

SQL_INCONSISTENTES = """
    SELECT id, nome_contrato
    FROM obras
    WHERE status = 'Concluída'
      AND (status_conclusao_obra IS NULL OR status_conclusao_obra = '')
    ORDER BY nome_contrato
"""


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(CAMINHO_DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def listar_sem_data(cursor) -> list:
    cursor.execute(SQL_SEM_DATA)
    return cursor.fetchall()


def listar_inconsistentes(cursor) -> list:
    cursor.execute(SQL_INCONSISTENTES)
    return cursor.fetchall()


def aplicar_correcao(cursor, obras: list) -> int:
    """Grava a data sugerida nas obras que têm uma; retorna quantas foram corrigidas."""
    corrigidas = 0
    for obra in obras:
        if not obra['data_sugerida']:
            continue
        cursor.execute(
            "UPDATE obras SET data_conclusao = ? WHERE id = ? "
            "AND (data_conclusao IS NULL OR data_conclusao = '')",
            (obra['data_sugerida'], obra['id']),
        )
        corrigidas += cursor.rowcount
    return corrigidas


def main():
    parser = argparse.ArgumentParser(description="Preenche data_conclusao de obras finalizadas sem data.")
    parser.add_argument('--executar', action='store_true', help='Aplica as alterações no banco (padrão: dry-run).')
    args = parser.parse_args()

    if not os.path.exists(CAMINHO_DB):
        print(f"ERRO: banco de dados não encontrado em:\n  {CAMINHO_DB}")
        sys.exit(1)

    print(f"Banco de dados : {CAMINHO_DB}")
    print(f"Modo           : {'EXECUÇÃO REAL' if args.executar else 'DRY-RUN (nenhuma alteração será feita)'}")
    print("-" * 70)

    conn = conectar()
    cursor = conn.cursor()
    try:
        obras = listar_sem_data(cursor)
        print(f"Obras finalizadas sem data de conclusão: {len(obras)}\n")
        for obra in obras:
            print(
                f"  [{obra['id']:>4}] {(obra['nome_contrato'] or '')[:50]:<50} | "
                f"{obra['status_conclusao_obra']:<14} | "
                f"data sugerida: {obra['data_sugerida'] or '(sem tarefas concluídas — fica vazia)'}"
            )

        inconsistentes = listar_inconsistentes(cursor)
        if inconsistentes:
            print("-" * 70)
            print(f"Obras com status 'Concluída' sem finalização registrada: {len(inconsistentes)}")
            print("(não são alteradas aqui; conclua pelo card: select Status → Concluído)\n")
            for obra in inconsistentes:
                print(f"  [{obra['id']:>4}] {obra['nome_contrato']}")
        print("-" * 70)

        if not args.executar:
            print("\nDRY-RUN concluído. Para aplicar, execute:")
            print("  python corrigir_data_conclusao.py --executar")
            return

        if not obras:
            print("Nada a corrigir.")
            return

        confirmacao = input("\nConfirmar execução? (sim/não): ").strip().lower()
        if confirmacao != 'sim':
            print("Operação cancelada.")
            return

        try:
            conn.execute('BEGIN')
            corrigidas = aplicar_correcao(cursor, obras)
            conn.commit()
            print(f"\nConcluído com sucesso: {corrigidas} obra(s) com data de conclusão preenchida.")
        except Exception as e:
            conn.rollback()
            print(f"\nERRO durante a execução: {e}")
            print("Rollback realizado — nenhuma alteração foi salva.")
            raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
