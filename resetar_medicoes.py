"""
Script de reset de medições legadas.

Problema: atualizações na quantidade de medições não sobrescreviam tarefas
preexistentes, gerando inconsistências nas abas Financeiro e de valores.

O que este script faz (somente para obras NÃO concluídas e NÃO em conclusão):
  1. Remove todas as tarefas MEDIÇÃO e CONFIRMAÇÃO DE MEDIÇÃO de obra_checklist
  2. Remove todos os registros de medicoes_valores
  3. Zera medicoes_obra.quantidade para que coordenadores recadastem do zero

Uso:
    python scripts/resetar_medicoes.py                       # dry-run, todas as obras elegíveis
    python scripts/resetar_medicoes.py --executar             # aplica em todas as obras elegíveis
    python scripts/resetar_medicoes.py --obra-id 42           # dry-run, somente a obra de id 42
    python scripts/resetar_medicoes.py --obra-id 42 --executar # aplica somente na obra de id 42
    python scripts/resetar_medicoes.py --buscar guarapuava     # lista obras com o termo no IC ou nome, com ids
"""

import argparse
import sqlite3

import os
import sys
import datetime
import unicodedata

# ---------------------------------------------------------------------------
# Resolução do caminho do banco (mesma lógica de db/connection.py)
# ---------------------------------------------------------------------------
_CAMINHO_SERVIDOR = '/root/AgendaObras/db'
_DIR_SCRIPT = os.path.dirname(os.path.abspath(__file__))
# Suporta o script tanto em scripts/ (subpasta) quanto na raiz do projeto
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

# ---------------------------------------------------------------------------
# Critério de seleção de obras
# ---------------------------------------------------------------------------
# Obras alvo: não concluídas (status != 'Concluída') e não em processo de
# conclusão (status_conclusao_obra IS NULL).
SQL_OBRAS_ALVO_BASE = """
    SELECT o.id, o.nome_contrato, o.cliente, o.status,
           mo.quantidade AS qtd_medicoes
    FROM obras o
    LEFT JOIN medicoes_obra mo ON mo.obra_id = o.id
    WHERE o.status != 'Concluída'
      AND (o.status_conclusao_obra IS NULL OR o.status_conclusao_obra = '')
      AND (
          EXISTS (
              SELECT 1 FROM obra_checklist oc
              WHERE oc.obra_id = o.id
                AND (oc.descricao LIKE 'MEDIÇÃO %' OR oc.descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %')
          )
          OR EXISTS (
              SELECT 1 FROM medicoes_valores mv WHERE mv.obra_id = o.id
          )
      )
      {filtro_obra}
    ORDER BY o.nome_contrato
"""


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(CAMINHO_DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def listar_obras_alvo(cursor, obra_id: int = None) -> list:
    if obra_id is not None:
        sql = SQL_OBRAS_ALVO_BASE.format(filtro_obra="AND o.id = :obra_id")
        cursor.execute(sql, {'obra_id': obra_id})
    else:
        sql = SQL_OBRAS_ALVO_BASE.format(filtro_obra="")
        cursor.execute(sql)
    return cursor.fetchall()


def _normalizar(texto) -> str:
    """Minúsculas e sem acentos, para busca tolerante (ex.: 'calcada' acha 'CALÇADA')."""
    sem_acento = unicodedata.normalize('NFKD', str(texto or ''))
    return ''.join(c for c in sem_acento if not unicodedata.combining(c)).casefold()


def buscar_obras(cursor, termo: str) -> list:
    """Obras cujo IC ou nome contém o termo (sem diferenciar maiúsculas/acentos)."""
    cursor.execute(
        "SELECT id, contrato_ic, nome_contrato, status, status_conclusao_obra "
        "FROM obras ORDER BY nome_contrato"
    )
    termo_norm = _normalizar(termo.strip())
    return [
        obra for obra in cursor.fetchall()
        if termo_norm in _normalizar(obra['nome_contrato'])
        or termo_norm in _normalizar(obra['contrato_ic'])
    ]


def exibir_busca(cursor, termo: str):
    obras = buscar_obras(cursor, termo)
    if not obras:
        print(f"Nenhuma obra encontrada com IC ou nome contendo '{termo}'.")
        return

    print(f"Obras encontradas para '{termo}': {len(obras)}\n")
    for obra in obras:
        elegivel = (
            obra['status'] != 'Concluída'
            and not (obra['status_conclusao_obra'] or '').strip()
        )
        print(
            f"  id: {obra['id']:>4} | "
            f"IC: {(obra['contrato_ic'] or '-'):<15} | "
            f"{(obra['nome_contrato'] or '')[:60]:<60} | "
            f"status: {(obra['status'] or '-'):<12}"
            f"{'' if elegivel else ' | (concluída/em conclusão — fora do reset)'}"
        )
    print("-" * 70)
    print("Use o id com --obra-id para simular ou aplicar o reset nessa obra.")


def contar_registros(cursor, obra_id: int) -> dict:
    cursor.execute(
        "SELECT COUNT(*) AS n FROM obra_checklist "
        "WHERE obra_id = ? AND (descricao LIKE 'MEDIÇÃO %' OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %')",
        (obra_id,),
    )
    tarefas = cursor.fetchone()['n']

    cursor.execute(
        "SELECT COUNT(*) AS n FROM medicoes_valores WHERE obra_id = ?",
        (obra_id,),
    )
    valores = cursor.fetchone()['n']

    return {'tarefas': tarefas, 'valores': valores}


def resetar_obra(cursor, obra_id: int):
    """Remove tarefas de medição, valores e zera a quantidade configurada."""

    # 1. Remove tarefas de medição do checklist
    cursor.execute(
        "DELETE FROM obra_checklist "
        "WHERE obra_id = ? AND (descricao LIKE 'MEDIÇÃO %' OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %')",
        (obra_id,),
    )

    # 2. Remove todos os valores de medição registrados
    cursor.execute(
        "DELETE FROM medicoes_valores WHERE obra_id = ?",
        (obra_id,),
    )

    # 3. Zera a quantidade em medicoes_obra (botão "Alterar medição")
    agora = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute(
        """
        INSERT INTO medicoes_obra (obra_id, quantidade, data_ultima_alteracao, atualizado_em)
        VALUES (?, 0, ?, ?)
        ON CONFLICT(obra_id) DO UPDATE SET
            quantidade = 0,
            data_ultima_alteracao = excluded.data_ultima_alteracao,
            atualizado_em = excluded.atualizado_em
        """,
        (obra_id, agora, agora),
    )


def main():
    parser = argparse.ArgumentParser(description="Reseta medições legadas de obras.")
    parser.add_argument('--executar', action='store_true', help='Aplica as alterações no banco (padrão: dry-run).')
    parser.add_argument('--obra-id', type=int, default=None, help='Restringe o reset a uma única obra pelo id.')
    parser.add_argument('--buscar', metavar='TERMO', default=None,
                        help='Lista obras cujo IC ou nome contém TERMO, com seus ids (não altera nada).')
    args = parser.parse_args()

    if args.buscar is not None and (args.executar or args.obra_id is not None):
        parser.error('--buscar não pode ser combinado com --executar ou --obra-id.')

    executar = args.executar

    if not os.path.exists(CAMINHO_DB):
        print(f"ERRO: banco de dados não encontrado em:\n  {CAMINHO_DB}")
        sys.exit(1)

    print(f"Banco de dados : {CAMINHO_DB}")

    if args.buscar is not None:
        print(f"Modo           : BUSCA (nenhuma alteração será feita)")
        print("-" * 70)
        conn = conectar()
        try:
            exibir_busca(conn.cursor(), args.buscar)
        finally:
            conn.close()
        return

    print(f"Modo          : {'EXECUÇÃO REAL' if executar else 'DRY-RUN (nenhuma alteração será feita)'}")
    if args.obra_id is not None:
        print(f"Filtro         : somente obra id {args.obra_id}")
    print("-" * 70)

    conn = conectar()
    cursor = conn.cursor()

    obras = listar_obras_alvo(cursor, obra_id=args.obra_id)

    if not obras:
        if args.obra_id is not None:
            print(f"Obra id {args.obra_id} não encontrada ou não elegível para reset "
                  f"(precisa estar não concluída, não em conclusão, e ter medições).")
        else:
            print("Nenhuma obra encontrada com medições para resetar.")
        conn.close()
        return

    print(f"Obras encontradas com medições a resetar: {len(obras)}\n")

    total_tarefas = 0
    total_valores = 0

    for obra in obras:
        contagens = contar_registros(cursor, obra['id'])
        total_tarefas += contagens['tarefas']
        total_valores += contagens['valores']

        print(
            f"  [{obra['id']:>4}] {obra['nome_contrato'][:50]:<50} | "
            f"status: {obra['status']:<12} | "
            f"qtd_medicoes: {obra['qtd_medicoes'] or 0:>2} | "
            f"tarefas: {contagens['tarefas']:>2} | "
            f"valores: {contagens['valores']:>2}"
        )

    print("-" * 70)
    print(f"Total de tarefas a remover  : {total_tarefas}")
    print(f"Total de valores a remover  : {total_valores}")
    print(f"Total de obras a zerar qtd  : {len(obras)}")
    print("-" * 70)

    if not executar:
        sufixo_obra = f" --obra-id {args.obra_id}" if args.obra_id is not None else ""
        print("\nDRY-RUN concluído. Para aplicar, execute:")
        print(f"  python scripts/resetar_medicoes.py --executar{sufixo_obra}")
        conn.close()
        return

    # --- Execução real ---
    confirmacao = input("\nConfirmar execução? (sim/não): ").strip().lower()
    if confirmacao != 'sim':
        print("Operação cancelada.")
        conn.close()
        return

    try:
        conn.execute('BEGIN')
        for obra in obras:
            resetar_obra(cursor, obra['id'])
        conn.commit()
        print(f"\nConcluído com sucesso.")
        print(f"  {total_tarefas} tarefas de medição removidas")
        print(f"  {total_valores} registros de valores removidos")
        print(f"  {len(obras)} obras com quantidade de medição zerada")
    except Exception as e:
        conn.rollback()
        print(f"\nERRO durante a execução: {e}")
        print("Rollback realizado — nenhuma alteração foi salva.")
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
