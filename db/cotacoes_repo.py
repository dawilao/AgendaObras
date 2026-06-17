"""
Repositório de cotações de itens por contrato — banco cotacoes.db separado.
"""

import os
import sqlite3
from typing import List, Optional
from core.error_logger import log_error

_CAMINHO_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'db', 'cotacoes.db')


def _resolver_caminho_cotacoes_db() -> str:
    env_path = (os.getenv('AGENDA_OBRAS_COTACOES_DB_PATH') or '').strip()
    if env_path:
        return env_path
    return _CAMINHO_DB


class CotacoesDatabase:
    def __init__(self, db_name: str = None):
        self.db_name = db_name or _resolver_caminho_cotacoes_db()
        self.init_database()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_name, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    def init_database(self):
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.executescript('''
                CREATE TABLE IF NOT EXISTS itens_referencia (
                    codigo    TEXT PRIMARY KEY,
                    descricao TEXT NOT NULL,
                    unidade   TEXT NOT NULL,
                    tipo      TEXT NOT NULL DEFAULT 'servico'
                );

                CREATE TABLE IF NOT EXISTS contrato_itens (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    contrato_id INTEGER NOT NULL,
                    item_codigo TEXT    NOT NULL REFERENCES itens_referencia(codigo),
                    curva       TEXT,
                    UNIQUE(contrato_id, item_codigo)
                );
                CREATE INDEX IF NOT EXISTS idx_ci_contrato ON contrato_itens(contrato_id);

                CREATE TABLE IF NOT EXISTS cotacoes_contrato (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    contrato_id      INTEGER NOT NULL,
                    item_codigo      TEXT    NOT NULL,
                    cot_a_fornecedor TEXT,
                    cot_a_valor      REAL,
                    cot_b_fornecedor TEXT,
                    cot_b_valor      REAL,
                    cot_c_fornecedor TEXT,
                    cot_c_valor      REAL,
                    observacao       TEXT,
                    atualizado_em    DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(contrato_id, item_codigo)
                );
                CREATE INDEX IF NOT EXISTS idx_cc_contrato ON cotacoes_contrato(contrato_id);

                CREATE TABLE IF NOT EXISTS abc_obra (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    obra_id       INTEGER NOT NULL,
                    item_codigo   TEXT    NOT NULL,
                    descricao     TEXT,
                    unidade       TEXT,
                    quantidade    REAL,
                    total_com_bdi REAL,
                    curva         TEXT,
                    UNIQUE(obra_id, item_codigo)
                );
                CREATE INDEX IF NOT EXISTS idx_ao_obra ON abc_obra(obra_id);
            ''')
            conn.commit()
        except Exception as e:
            log_error(e, "cotacoes_database", "Inicializar cotacoes.db")
        finally:
            if conn:
                conn.close()

    # ── Itens do contrato ─────────────────────────────────────────────────────

    def listar_itens_contrato(self, contrato_id: int) -> List[dict]:
        """Retorna itens do contrato com suas cotações (join)."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    ci.curva,
                    ci.item_codigo AS codigo,
                    ir.descricao,
                    ir.unidade,
                    ir.tipo,
                    COALESCE(cc.cot_a_fornecedor, '') AS cot_a_fornecedor,
                    cc.cot_a_valor,
                    COALESCE(cc.cot_b_fornecedor, '') AS cot_b_fornecedor,
                    cc.cot_b_valor,
                    COALESCE(cc.cot_c_fornecedor, '') AS cot_c_fornecedor,
                    cc.cot_c_valor,
                    ROUND(
                        (COALESCE(cc.cot_a_valor, 0) + COALESCE(cc.cot_b_valor, 0) + COALESCE(cc.cot_c_valor, 0))
                        / NULLIF(
                            (CASE WHEN cc.cot_a_valor IS NOT NULL THEN 1 ELSE 0 END
                           + CASE WHEN cc.cot_b_valor IS NOT NULL THEN 1 ELSE 0 END
                           + CASE WHEN cc.cot_c_valor IS NOT NULL THEN 1 ELSE 0 END), 0
                        ), 4
                    ) AS media,
                    COALESCE(cc.observacao, '') AS observacao
                FROM contrato_itens ci
                JOIN itens_referencia ir ON ir.codigo = ci.item_codigo
                LEFT JOIN cotacoes_contrato cc
                    ON cc.contrato_id = ci.contrato_id AND cc.item_codigo = ci.item_codigo
                WHERE ci.contrato_id = ?
                ORDER BY ci.curva NULLS LAST, ci.item_codigo
            ''', (contrato_id,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            log_error(e, "cotacoes_database", f"Listar itens contrato {contrato_id}")
            return []
        finally:
            if conn:
                conn.close()

    def upsert_itens_referencia(self, itens: List[dict]) -> None:
        """Upsert em itens_referencia. Cada item: {codigo, descricao, unidade, tipo?}."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO itens_referencia (codigo, descricao, unidade, tipo)
                VALUES (:codigo, :descricao, :unidade, :tipo)
                ON CONFLICT(codigo) DO UPDATE SET
                    descricao = excluded.descricao,
                    unidade   = excluded.unidade,
                    tipo      = excluded.tipo
            ''', itens)
            conn.commit()
        except Exception as e:
            log_error(e, "cotacoes_database", "Upsert itens_referencia")
            raise
        finally:
            if conn:
                conn.close()

    def upsert_contrato_itens(self, contrato_id: int, itens: List[dict]) -> None:
        """Upsert em contrato_itens. Cada item: {item_codigo, curva?}."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            rows = [(contrato_id, i['item_codigo'], i.get('curva')) for i in itens]
            cursor.executemany('''
                INSERT INTO contrato_itens (contrato_id, item_codigo, curva)
                VALUES (?, ?, ?)
                ON CONFLICT(contrato_id, item_codigo) DO UPDATE SET curva = excluded.curva
            ''', rows)
            conn.commit()
        except Exception as e:
            log_error(e, "cotacoes_database", f"Upsert contrato_itens contrato {contrato_id}")
            raise
        finally:
            if conn:
                conn.close()

    # ── Cotações ──────────────────────────────────────────────────────────────

    def obter_cotacao(self, contrato_id: int, item_codigo: str) -> Optional[dict]:
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM cotacoes_contrato WHERE contrato_id = ? AND item_codigo = ?',
                (contrato_id, item_codigo)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            log_error(e, "cotacoes_database", f"Obter cotação {item_codigo}")
            return None
        finally:
            if conn:
                conn.close()

    def salvar_cotacao(self, contrato_id: int, item_codigo: str, campos: dict) -> bool:
        """
        Atualiza apenas os campos presentes em `campos` para a cotação.
        Campos permitidos: cot_a_fornecedor, cot_a_valor, cot_b_fornecedor, cot_b_valor,
                           cot_c_fornecedor, cot_c_valor, observacao.
        """
        _permitidos = {
            'cot_a_fornecedor', 'cot_a_valor',
            'cot_b_fornecedor', 'cot_b_valor',
            'cot_c_fornecedor', 'cot_c_valor',
            'observacao',
        }
        campos_validos = {k: v for k, v in campos.items() if k in _permitidos}
        if not campos_validos:
            return False

        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            # Garante que o registro existe antes de atualizar
            cursor.execute('''
                INSERT OR IGNORE INTO cotacoes_contrato (contrato_id, item_codigo)
                VALUES (?, ?)
            ''', (contrato_id, item_codigo))

            set_clause = ', '.join(f'{k} = ?' for k in campos_validos)
            set_clause += ', atualizado_em = CURRENT_TIMESTAMP'
            valores = list(campos_validos.values()) + [contrato_id, item_codigo]
            cursor.execute(
                f'UPDATE cotacoes_contrato SET {set_clause} WHERE contrato_id = ? AND item_codigo = ?',
                valores
            )
            conn.commit()
            return True
        except Exception as e:
            log_error(e, "cotacoes_database", f"Salvar cotação {item_codigo}")
            return False
        finally:
            if conn:
                conn.close()

    def listar_cotacoes_contrato(self, contrato_id: int) -> List[dict]:
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM cotacoes_contrato WHERE contrato_id = ?',
                (contrato_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            log_error(e, "cotacoes_database", f"Listar cotações contrato {contrato_id}")
            return []
        finally:
            if conn:
                conn.close()

    def upsert_cotacoes_batch(self, contrato_id: int, cotacoes: List[dict]) -> None:
        """
        Importação em massa de cotações. Cada item:
        {item_codigo, cot_a_fornecedor?, cot_a_valor?, ..., observacao?}.
        Não sobrescreve campo se o novo valor for None (importação de template).
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            for cot in cotacoes:
                codigo = cot['item_codigo']
                cursor.execute('''
                    INSERT OR IGNORE INTO cotacoes_contrato (contrato_id, item_codigo)
                    VALUES (?, ?)
                ''', (contrato_id, codigo))

                campos = {}
                for campo in ('cot_a_fornecedor', 'cot_a_valor',
                              'cot_b_fornecedor', 'cot_b_valor',
                              'cot_c_fornecedor', 'cot_c_valor',
                              'observacao'):
                    if campo in cot and cot[campo] is not None:
                        campos[campo] = cot[campo]

                if campos:
                    set_clause = ', '.join(f'{k} = ?' for k in campos)
                    set_clause += ', atualizado_em = CURRENT_TIMESTAMP'
                    valores = list(campos.values()) + [contrato_id, codigo]
                    cursor.execute(
                        f'UPDATE cotacoes_contrato SET {set_clause} WHERE contrato_id = ? AND item_codigo = ?',
                        valores
                    )
            conn.commit()
        except Exception as e:
            log_error(e, "cotacoes_database", f"Upsert cotações batch contrato {contrato_id}")
            raise
        finally:
            if conn:
                conn.close()

    # ── ABC por obra ──────────────────────────────────────────────────────────

    def listar_abc_obra(self, obra_id: int) -> List[dict]:
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM abc_obra WHERE obra_id = ? ORDER BY curva NULLS LAST, item_codigo',
                (obra_id,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            log_error(e, "cotacoes_database", f"Listar abc_obra obra {obra_id}")
            return []
        finally:
            if conn:
                conn.close()

    def listar_codigos_contrato(self, contrato_id: int) -> set:
        """Retorna set de item_codigos já cadastrados para o contrato."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT item_codigo FROM contrato_itens WHERE contrato_id = ?', (contrato_id,))
            return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            log_error(e, "cotacoes_database", f"Listar codigos contrato {contrato_id}")
            return set()
        finally:
            if conn:
                conn.close()

    def listar_abc_codigos(self, obra_id: int) -> set:
        """Retorna set de item_codigos marcados para a obra."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT item_codigo FROM abc_obra WHERE obra_id = ?', (obra_id,))
            return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            log_error(e, "cotacoes_database", f"Listar abc_codigos obra {obra_id}")
            return set()
        finally:
            if conn:
                conn.close()

    def listar_abc_quantidades(self, obra_id: int) -> dict:
        """Retorna {item_codigo: quantidade} para a obra."""
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT item_codigo, quantidade FROM abc_obra WHERE obra_id = ?', (obra_id,)
            )
            return {row[0]: row[1] for row in cursor.fetchall()}
        except Exception as e:
            log_error(e, "cotacoes_database", f"Listar abc_quantidades obra {obra_id}")
            return {}
        finally:
            if conn:
                conn.close()

    def upsert_abc_item_manual(self, obra_id: int, item_codigo: str,
                                descricao: str, unidade: str) -> None:
        """Insere item em abc_obra sem sobrescrever dados de PLO já importada."""
        conn = None
        try:
            conn = self.get_connection()
            conn.execute('''
                INSERT OR IGNORE INTO abc_obra (obra_id, item_codigo, descricao, unidade)
                VALUES (?, ?, ?, ?)
            ''', (obra_id, item_codigo, descricao, unidade))
            conn.commit()
        except Exception as e:
            log_error(e, "cotacoes_database", f"Upsert abc_item_manual {item_codigo}")
            raise
        finally:
            if conn:
                conn.close()

    def remover_abc_item(self, obra_id: int, item_codigo: str) -> None:
        """Remove item de abc_obra (desmarca checkbox)."""
        conn = None
        try:
            conn = self.get_connection()
            conn.execute(
                'DELETE FROM abc_obra WHERE obra_id = ? AND item_codigo = ?',
                (obra_id, item_codigo)
            )
            conn.commit()
        except Exception as e:
            log_error(e, "cotacoes_database", f"Remover abc_item {item_codigo}")
            raise
        finally:
            if conn:
                conn.close()

    def atualizar_abc_quantidade(self, obra_id: int, item_codigo: str,
                                  quantidade) -> None:
        """Atualiza quantidade de item já existente em abc_obra."""
        conn = None
        try:
            conn = self.get_connection()
            conn.execute('''
                UPDATE abc_obra SET quantidade = ? WHERE obra_id = ? AND item_codigo = ?
            ''', (quantidade, obra_id, item_codigo))
            conn.commit()
        except Exception as e:
            log_error(e, "cotacoes_database", f"Atualizar abc_quantidade {item_codigo}")
            raise
        finally:
            if conn:
                conn.close()

    def upsert_abc_itens(self, obra_id: int, itens: List[dict]) -> None:
        """
        Upsert de itens da PLO para uma obra. Cada item:
        {item_codigo, descricao?, unidade?, quantidade?, total_com_bdi?, curva?}.
        """
        conn = None
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.executemany('''
                INSERT INTO abc_obra (obra_id, item_codigo, descricao, unidade, quantidade, total_com_bdi, curva)
                VALUES (:obra_id, :item_codigo, :descricao, :unidade, :quantidade, :total_com_bdi, :curva)
                ON CONFLICT(obra_id, item_codigo) DO UPDATE SET
                    descricao     = excluded.descricao,
                    unidade       = excluded.unidade,
                    quantidade    = excluded.quantidade,
                    total_com_bdi = excluded.total_com_bdi,
                    curva         = excluded.curva
            ''', [{**i, 'obra_id': obra_id} for i in itens])
            conn.commit()
        except Exception as e:
            log_error(e, "cotacoes_database", f"Upsert abc_obra obra {obra_id}")
            raise
        finally:
            if conn:
                conn.close()
