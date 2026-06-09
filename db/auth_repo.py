"""
Repositório de usuários para autenticação.
Banco SQLite separado do banco principal.
Senhas protegidas com SHA-256 + salt aleatório.
"""

import sqlite3
import hashlib
import os
import datetime
from typing import Optional, Dict, List
from core.error_logger import log_error

_CAMINHO_DRIVE = r'db'
# Raiz do projeto (um nível acima de db/)
_CAMINHO_LOCAL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolver_caminho_db() -> str:
    env_path = (os.getenv('AGENDA_OBRAS_USERS_DB_PATH') or '').strip()
    if env_path:
        return env_path
    if os.path.isdir(_CAMINHO_DRIVE):
        return os.path.join(_CAMINHO_DRIVE, 'users.db')
    return os.path.join(_CAMINHO_LOCAL, 'users.db')


CAMINHO_USERS_DB = _resolver_caminho_db()


def _gerar_salt() -> str:
    return os.urandom(32).hex()


def _hash_senha(senha: str, salt: str) -> str:
    return hashlib.sha256((salt + senha).encode('utf-8')).hexdigest()


class AuthDatabase:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or _resolver_caminho_db()
        self._criar_tabela()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    def _criar_tabela(self):
        conn = self.get_connection()
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    sobrenome TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    senha_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    is_admin INTEGER DEFAULT 0,
                    receber_alerta_critico INTEGER DEFAULT 1,
                    data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            colunas = {row['name'] for row in conn.execute('PRAGMA table_info(usuarios)').fetchall()}
            if 'receber_alerta_critico' not in colunas:
                conn.execute('ALTER TABLE usuarios ADD COLUMN receber_alerta_critico INTEGER DEFAULT 1')
            conn.commit()
        except Exception as e:
            log_error(e, "auth_database", "Criação da tabela de usuários")
        finally:
            conn.close()

    def tem_usuarios(self) -> bool:
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT COUNT(*) as total FROM usuarios').fetchone()
            return row['total'] > 0
        except Exception as e:
            log_error(e, "auth_database", "Verificar se existem usuários")
            return False
        finally:
            conn.close()

    def criar_usuario(self, nome: str, sobrenome: str, email: str, senha: str, is_admin: bool = False, receber_alerta_critico: bool = True) -> bool:
        salt = _gerar_salt()
        senha_hash = _hash_senha(senha, salt)
        conn = self.get_connection()
        try:
            conn.execute('INSERT INTO usuarios (nome, sobrenome, email, senha_hash, salt, is_admin, receber_alerta_critico) VALUES (?, ?, ?, ?, ?, ?, ?)', (nome.strip(), sobrenome.strip(), email.strip().lower(), senha_hash, salt, int(is_admin), int(receber_alerta_critico)))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            log_error(e, "auth_database", f"Criar usuário {email}")
            return False
        finally:
            conn.close()

    def autenticar(self, email: str, senha: str) -> Optional[Dict]:
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT * FROM usuarios WHERE email = ?', (email.strip().lower(),)).fetchone()
            if row is None:
                return None
            if _hash_senha(senha, row['salt']) == row['senha_hash']:
                return {'id': row['id'], 'nome': row['nome'], 'sobrenome': row['sobrenome'], 'email': row['email'], 'is_admin': bool(row['is_admin']), 'receber_alerta_critico': bool(row['receber_alerta_critico'])}
            return None
        except Exception as e:
            log_error(e, "auth_database", f"Autenticar usuário {email}")
            return None
        finally:
            conn.close()

    def listar_usuarios(self) -> List[Dict]:
        conn = self.get_connection()
        try:
            rows = conn.execute('SELECT id, nome, sobrenome, email, is_admin, receber_alerta_critico, data_criacao FROM usuarios ORDER BY nome').fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log_error(e, "auth_database", "Listar usuários")
            return []
        finally:
            conn.close()

    def obter_usuario_por_id(self, user_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT id, nome, sobrenome, email, is_admin, receber_alerta_critico, data_criacao FROM usuarios WHERE id = ?', (user_id,)).fetchone()
            return dict(row) if row else None
        except Exception as e:
            log_error(e, "auth_database", f"Obter usuário {user_id}")
            return None
        finally:
            conn.close()

    def excluir_usuario(self, user_id: int) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.execute('DELETE FROM usuarios WHERE id = ?', (user_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            log_error(e, "auth_database", f"Excluir usuário {user_id}")
            return False
        finally:
            conn.close()

    def redefinir_senha(self, user_id: int, nova_senha: str) -> bool:
        salt = _gerar_salt()
        senha_hash = _hash_senha(nova_senha, salt)
        conn = self.get_connection()
        try:
            cursor = conn.execute('UPDATE usuarios SET senha_hash = ?, salt = ? WHERE id = ?', (senha_hash, salt, user_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            log_error(e, "auth_database", f"Redefinir senha usuário {user_id}")
            return False
        finally:
            conn.close()

    def verificar_senha_atual(self, user_id: int, senha_atual: str) -> bool:
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT senha_hash, salt FROM usuarios WHERE id = ?', (user_id,)).fetchone()
            if row is None:
                return False
            return _hash_senha(senha_atual, row['salt']) == row['senha_hash']
        except Exception as e:
            log_error(e, "auth_database", f"Verificar senha atual usuário {user_id}")
            return False
        finally:
            conn.close()

    def atualizar_usuario(self, user_id: int, nome: str, sobrenome: str, email: str) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.execute('UPDATE usuarios SET nome = ?, sobrenome = ?, email = ? WHERE id = ?', (nome.strip(), sobrenome.strip(), email.strip().lower(), user_id))
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            log_error(e, "auth_database", f"Atualizar usuário {user_id}")
            return False
        finally:
            conn.close()

    def promover_para_admin(self, user_id: int) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.execute('UPDATE usuarios SET is_admin = 1 WHERE id = ? AND is_admin = 0', (user_id,))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            log_error(e, "auth_database", f"Promover usuário {user_id} para admin")
            return False
        finally:
            conn.close()

    def atualizar_receber_alerta_critico(self, user_id: int, receber_alerta_critico: bool) -> bool:
        conn = self.get_connection()
        try:
            cursor = conn.execute('UPDATE usuarios SET receber_alerta_critico = ? WHERE id = ?', (int(receber_alerta_critico), user_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            log_error(e, "auth_database", f"Atualizar preferência de alerta crítico do usuário {user_id}")
            return False
        finally:
            conn.close()

    def contar_admins(self) -> int:
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT COUNT(*) as total FROM usuarios WHERE is_admin = 1').fetchone()
            return row['total']
        except Exception as e:
            log_error(e, "auth_database", "Contar admins")
            return 0
        finally:
            conn.close()
