"""
Módulo de gerenciamento do banco de dados de usuários para autenticação.
Utiliza SQLite separado do banco principal do AgendaObras.
Senhas protegidas com SHA-256 + salt aleatório.
"""

import sqlite3
import hashlib
import os
import datetime
from typing import Optional, Dict, List
from error_logger import log_error

# Caminho padrão: mesmo diretório do banco principal (Google Drive)
_CAMINHO_DRIVE = r'G:\Meu Drive\17 - MODELOS\PROGRAMAS\AgendaObras\app\db'
# Caminho fallback: diretório local junto ao código
_CAMINHO_LOCAL = os.path.dirname(os.path.abspath(__file__))


def _resolver_caminho_db() -> str:
    """Resolve o caminho do banco de usuários.
    Tenta usar o diretório do Google Drive; se não existir, usa local."""
    if os.path.isdir(_CAMINHO_DRIVE):
        return os.path.join(_CAMINHO_DRIVE, 'users.db')
    return os.path.join(_CAMINHO_LOCAL, 'users.db')


CAMINHO_USERS_DB = _resolver_caminho_db()


def _gerar_salt() -> str:
    """Gera um salt aleatório de 32 bytes em hexadecimal."""
    return os.urandom(32).hex()


def _hash_senha(senha: str, salt: str) -> str:
    """Gera hash SHA-256 da senha concatenada com o salt."""
    return hashlib.sha256((salt + senha).encode('utf-8')).hexdigest()


class AuthDatabase:
    """Gerencia o banco de dados de usuários (users.db)."""

    def __init__(self, db_path: str = CAMINHO_USERS_DB):
        self.db_path = db_path
        self._criar_tabela()

    # ========== Conexão ========== #

    def get_connection(self) -> sqlite3.Connection:
        """Cria e retorna conexão com WAL mode e acesso por nome de coluna."""
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        return conn

    # ========== Inicialização ========== #

    def _criar_tabela(self):
        """Cria a tabela de usuários se não existir."""
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
                    data_criacao TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        except Exception as e:
            log_error(e, "auth_database", "Criação da tabela de usuários")
        finally:
            conn.close()

    # ========== CRUD ========== #

    def tem_usuarios(self) -> bool:
        """Retorna True se já existir ao menos um usuário cadastrado."""
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT COUNT(*) as total FROM usuarios').fetchone()
            return row['total'] > 0
        except Exception as e:
            log_error(e, "auth_database", "Verificar se existem usuários")
            return False
        finally:
            conn.close()

    def criar_usuario(self, nome: str, sobrenome: str, email: str, senha: str, is_admin: bool = False) -> bool:
        """Cria um novo usuário com senha criptografada. Retorna True se criado com sucesso."""
        salt = _gerar_salt()
        senha_hash = _hash_senha(senha, salt)
        conn = self.get_connection()
        try:
            conn.execute(
                'INSERT INTO usuarios (nome, sobrenome, email, senha_hash, salt, is_admin) VALUES (?, ?, ?, ?, ?, ?)',
                (nome.strip(), sobrenome.strip(), email.strip().lower(), senha_hash, salt, int(is_admin))
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            # E-mail já existe
            return False
        except Exception as e:
            log_error(e, "auth_database", f"Criar usuário {email}")
            return False
        finally:
            conn.close()

    def autenticar(self, email: str, senha: str) -> Optional[Dict]:
        """Autentica usuário por e-mail e senha.
        Retorna dict com dados do usuário se válido, None caso contrário."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                'SELECT * FROM usuarios WHERE email = ?', (email.strip().lower(),)
            ).fetchone()
            if row is None:
                return None
            # Verifica senha
            senha_hash = _hash_senha(senha, row['salt'])
            if senha_hash == row['senha_hash']:
                return {
                    'id': row['id'],
                    'nome': row['nome'],
                    'sobrenome': row['sobrenome'],
                    'email': row['email'],
                    'is_admin': bool(row['is_admin']),
                }
            return None
        except Exception as e:
            log_error(e, "auth_database", f"Autenticar usuário {email}")
            return None
        finally:
            conn.close()

    def listar_usuarios(self) -> List[Dict]:
        """Retorna lista de todos os usuários (sem dados sensíveis)."""
        conn = self.get_connection()
        try:
            rows = conn.execute(
                'SELECT id, nome, sobrenome, email, is_admin, data_criacao FROM usuarios ORDER BY nome'
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log_error(e, "auth_database", "Listar usuários")
            return []
        finally:
            conn.close()

    def excluir_usuario(self, user_id: int) -> bool:
        """Exclui um usuário pelo ID. Retorna True se excluído."""
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
        """Redefine a senha de um usuário com novo hash e salt."""
        salt = _gerar_salt()
        senha_hash = _hash_senha(nova_senha, salt)
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                'UPDATE usuarios SET senha_hash = ?, salt = ? WHERE id = ?',
                (senha_hash, salt, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            log_error(e, "auth_database", f"Redefinir senha usuário {user_id}")
            return False
        finally:
            conn.close()

    def verificar_senha_atual(self, user_id: int, senha_atual: str) -> bool:
        """Verifica se a senha atual informada confere para o usuário."""
        conn = self.get_connection()
        try:
            row = conn.execute(
                'SELECT senha_hash, salt FROM usuarios WHERE id = ?',
                (user_id,),
            ).fetchone()
            if row is None:
                return False
            senha_hash = _hash_senha(senha_atual, row['salt'])
            return senha_hash == row['senha_hash']
        except Exception as e:
            log_error(e, "auth_database", f"Verificar senha atual usuário {user_id}")
            return False
        finally:
            conn.close()

    def atualizar_usuario(self, user_id: int, nome: str, sobrenome: str, email: str) -> bool:
        """Atualiza informações pessoais de um usuário (nome, sobrenome, email).
        Retorna True se atualizado com sucesso."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                'UPDATE usuarios SET nome = ?, sobrenome = ?, email = ? WHERE id = ?',
                (nome.strip(), sobrenome.strip(), email.strip().lower(), user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.IntegrityError:
            # E-mail já existe para outro usuário
            return False
        except Exception as e:
            log_error(e, "auth_database", f"Atualizar usuário {user_id}")
            return False
        finally:
            conn.close()

    def promover_para_admin(self, user_id: int) -> bool:
        """Promove um usuário para administrador."""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                'UPDATE usuarios SET is_admin = 1 WHERE id = ? AND is_admin = 0',
                (user_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            log_error(e, "auth_database", f"Promover usuário {user_id} para admin")
            return False
        finally:
            conn.close()

    def contar_admins(self) -> int:
        """Retorna a quantidade de administradores cadastrados."""
        conn = self.get_connection()
        try:
            row = conn.execute('SELECT COUNT(*) as total FROM usuarios WHERE is_admin = 1').fetchone()
            return row['total']
        except Exception as e:
            log_error(e, "auth_database", "Contar admins")
            return 0
        finally:
            conn.close()
