"""
Sistema de Validação de Versão do AgendaObras
"""
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Tuple
from packaging import version as pkg_version
from core.error_logger import log_error
from core.config import VERSION, VERSION_JSON_URL


class VersionChecker:
    def __init__(self, version_url: Optional[str] = None):
        self.version_url = version_url or VERSION_JSON_URL
        self.current_version = VERSION
        self._online_data: Optional[Dict] = None

    def fetch_online_version(self, timeout: int = 10) -> Optional[Dict]:
        try:
            with urllib.request.urlopen(self.version_url, timeout=timeout) as response:
                data = response.read().decode('utf-8')
                self._online_data = json.loads(data)
                return self._online_data
        except urllib.error.URLError as e:
            log_error(e, "version_checker", "Buscar versão online do GitHub")
            print(f"Erro ao buscar versão online: {e}")
            return None
        except json.JSONDecodeError as e:
            log_error(e, "version_checker", "Decodificar JSON de versão")
            print(f"Erro ao decodificar JSON: {e}")
            return None
        except Exception as e:
            log_error(e, "version_checker", "Verificar versão - erro inesperado")
            print(f"Erro inesperado ao verificar versão: {e}")
            return None

    def compare_versions(self) -> Tuple[bool, str]:
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        if not self._online_data:
            return False, "Não foi possível verificar atualizações (sem conexão ou erro de rede)"
        try:
            online_version = self._online_data.get('version', '0.0.0')
            minimum_version = self._online_data.get('minimum_version', '0.0.0')
            force_update = self._online_data.get('force_update', False)
            current_ver = pkg_version.parse(self.current_version)
            online_ver = pkg_version.parse(online_version)
            minimum_ver = pkg_version.parse(minimum_version)
            if current_ver < minimum_ver:
                return True, f"Atualização obrigatória! Versão atual {self.current_version} < mínima {minimum_version}"
            if force_update and current_ver < online_ver:
                return True, f"Atualização obrigatória disponível! Versão {online_version}"
            if current_ver < online_ver:
                return True, f"Atualização disponível! Versão {online_version}"
            return False, f"Você está usando a versão mais recente ({self.current_version})"
        except Exception as e:
            log_error(e, "version_checker", "Comparar versões")
            print(f"Erro ao comparar versões: {e}")
            return False, f"Erro ao comparar versões: {e}"

    def needs_update(self) -> bool:
        needs_update, _ = self.compare_versions()
        return needs_update

    def is_force_update(self) -> bool:
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        if not self._online_data:
            return False
        try:
            online_version = self._online_data.get('version', '0.0.0')
            minimum_version = self._online_data.get('minimum_version', '0.0.0')
            force_update = self._online_data.get('force_update', False)
            current_ver = pkg_version.parse(self.current_version)
            online_ver = pkg_version.parse(online_version)
            minimum_ver = pkg_version.parse(minimum_version)
            return current_ver < minimum_ver or (force_update and current_ver < online_ver)
        except Exception as e:
            log_error(e, "version_checker", "Verificar força de atualização")
            return False

    def get_download_url(self) -> Optional[str]:
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        return self._online_data.get('download_url') if self._online_data else None

    def get_release_notes(self, lang: str = 'pt-BR') -> str:
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        if not self._online_data:
            return "Notas de lançamento não disponíveis"
        release_notes = self._online_data.get('release_notes', {})
        return release_notes.get(lang, release_notes.get('pt-BR', 'Sem notas de lançamento'))

    def get_changelog(self) -> list:
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        return self._online_data.get('changelog', []) if self._online_data else []

    def get_online_version(self) -> Optional[str]:
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        return self._online_data.get('version') if self._online_data else None

    def get_version_info(self) -> Dict:
        needs_update, message = self.compare_versions()
        return {
            'current_version': self.current_version,
            'online_version': self.get_online_version(),
            'needs_update': needs_update,
            'force_update': self.is_force_update(),
            'message': message,
            'download_url': self.get_download_url(),
            'release_notes': self.get_release_notes(),
            'changelog': self.get_changelog()
        }


def check_version_and_notify() -> Tuple[bool, Dict]:
    checker = VersionChecker()
    info = checker.get_version_info()
    return info['needs_update'], info
