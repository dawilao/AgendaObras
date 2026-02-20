"""
Sistema de Validação de Versão do AgendaObras

Este módulo verifica se há atualizações disponíveis comparando a versão
local com a versão disponível no GitHub.
"""
import json
import urllib.request
import urllib.error
from typing import Optional, Dict, Tuple
from packaging import version as pkg_version
from config import VERSION, VERSION_JSON_URL


class VersionChecker:
    """Verifica atualizações do sistema comparando com versão online no GitHub"""
    
    def __init__(self, version_url: Optional[str] = None):
        """
        Inicializa o verificador de versão
        
        Args:
            version_url: URL customizada para o arquivo version.json (opcional)
        """
        self.version_url = version_url or VERSION_JSON_URL
        self.current_version = VERSION
        self._online_data: Optional[Dict] = None
    
    def fetch_online_version(self, timeout: int = 10) -> Optional[Dict]:
        """
        Busca informações de versão online do GitHub
        
        Args:
            timeout: Tempo limite da requisição em segundos
            
        Returns:
            Dicionário com dados de versão ou None se falhar
        """
        try:
            with urllib.request.urlopen(self.version_url, timeout=timeout) as response:
                data = response.read().decode('utf-8')
                self._online_data = json.loads(data)
                return self._online_data
        except urllib.error.URLError as e:
            print(f"Erro ao buscar versão online: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Erro ao decodificar JSON: {e}")
            return None
        except Exception as e:
            print(f"Erro inesperado ao verificar versão: {e}")
            return None
    
    def compare_versions(self) -> Tuple[bool, str]:
        """
        Compara a versão local com a versão online
        
        Returns:
            Tupla (precisa_atualizar, mensagem)
            - precisa_atualizar: bool indicando se atualização é necessária
            - mensagem: string com descrição do status
        """
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
            
            # Verifica se a versão atual é menor que a mínima permitida
            if current_ver < minimum_ver:
                return True, f"Atualização obrigatória! Versão atual {self.current_version} < mínima {minimum_version}"
            
            # Verifica se há atualização forçada
            if force_update and current_ver < online_ver:
                return True, f"Atualização obrigatória disponível! Versão {online_version}"
            
            # Verifica se há atualização opcional
            if current_ver < online_ver:
                return True, f"Atualização disponível! Versão {online_version}"
            
            return False, f"Você está usando a versão mais recente ({self.current_version})"
            
        except Exception as e:
            print(f"Erro ao comparar versões: {e}")
            return False, f"Erro ao comparar versões: {e}"
    
    def needs_update(self) -> bool:
        """
        Verifica se precisa atualizar (simplificado)
        
        Returns:
            True se precisa atualizar, False caso contrário
        """
        needs_update, _ = self.compare_versions()
        return needs_update
    
    def is_force_update(self) -> bool:
        """
        Verifica se a atualização é obrigatória
        
        Returns:
            True se a atualização é obrigatória, False caso contrário
        """
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
            
            # Atualização obrigatória se versão atual < mínima OU force_update ativado
            return current_ver < minimum_ver or (force_update and current_ver < online_ver)
            
        except Exception as e:
            print(f"Erro ao verificar força de atualização: {e}")
            return False
    
    def get_download_url(self) -> Optional[str]:
        """
        Obtém a URL de download da nova versão
        
        Returns:
            URL de download ou None se não disponível
        """
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        
        return self._online_data.get('download_url') if self._online_data else None
    
    def get_release_notes(self, lang: str = 'pt-BR') -> str:
        """
        Obtém as notas de lançamento da nova versão
        
        Args:
            lang: Idioma das notas de lançamento
            
        Returns:
            Texto das notas de lançamento
        """
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        
        if not self._online_data:
            return "Notas de lançamento não disponíveis"
        
        release_notes = self._online_data.get('release_notes', {})
        return release_notes.get(lang, release_notes.get('pt-BR', 'Sem notas de lançamento'))
    
    def get_changelog(self) -> list:
        """
        Obtém o changelog da nova versão
        
        Returns:
            Lista de mudanças
        """
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        
        return self._online_data.get('changelog', []) if self._online_data else []
    
    def get_online_version(self) -> Optional[str]:
        """
        Obtém a versão online
        
        Returns:
            String da versão online ou None
        """
        if not self._online_data:
            self._online_data = self.fetch_online_version()
        
        return self._online_data.get('version') if self._online_data else None
    
    def get_version_info(self) -> Dict:
        """
        Obtém informações completas sobre as versões
        
        Returns:
            Dicionário com informações de versão
        """
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
    """
    Função auxiliar para verificar versão e retornar informações
    
    Returns:
        Tupla (precisa_atualizar, informações_completas)
    """
    checker = VersionChecker()
    info = checker.get_version_info()
    return info['needs_update'], info


if __name__ == '__main__':
    # Teste do sistema de verificação
    print("=" * 60)
    print("Sistema de Verificação de Versão - AgendaObras")
    print("=" * 60)
    
    checker = VersionChecker()
    info = checker.get_version_info()
    
    print(f"\n📦 Versão Atual: {info['current_version']}")
    print(f"🌐 Versão Online: {info['online_version'] or 'Não disponível'}")
    print(f"📊 Status: {info['message']}")
    
    if info['needs_update']:
        print(f"\n⚠️  {'ATUALIZAÇÃO OBRIGATÓRIA!' if info['force_update'] else 'Atualização disponível'}")
        print(f"\n📝 Notas de Lançamento:\n{info['release_notes']}")
        
        if info['changelog']:
            print(f"\n📋 Changelog:")
            for item in info['changelog']:
                print(f"  • {item}")
        
        if info['download_url']:
            print(f"\n🔗 Download: {info['download_url']}")
    else:
        print("\n✅ Sistema atualizado!")
    
    print("\n" + "=" * 60)
