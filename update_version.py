"""
Script auxiliar para atualizar a versão do AgendaObras

Uso:
    python update_version.py 1.2.0 "Descrição da versão" [--force] [--minimum 1.0.0]

Exemplos:
    # Atualização opcional
    python update_version.py 1.1.0 "Melhorias de performance"
    
    # Atualização obrigatória
    python update_version.py 2.0.0 "Grande atualização" --force
    
    # Definir versão mínima
    python update_version.py 1.2.0 "Correções críticas" --minimum 1.2.0
"""
import json
import sys
import re
from datetime import datetime
from pathlib import Path


def validar_versao(versao: str) -> bool:
    """Valida se a versão está no formato semver (X.Y.Z)"""
    pattern = r'^\d+\.\d+\.\d+$'
    return re.match(pattern, versao) is not None


def ler_version_json() -> dict:
    """Lê o arquivo version.json atual"""
    version_file = Path('version.json')
    if version_file.exists():
        with open(version_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def atualizar_version_json(nova_versao: str, descricao: str, force_update: bool = False, minimum_version: str = None):
    """Atualiza o arquivo version.json"""
    data = ler_version_json()
    
    # Preserva changelog antigo
    changelog_antigo = data.get('changelog', [])
    
    # Atualiza dados
    data['version'] = nova_versao
    data['release_date'] = datetime.now().strftime('%Y-%m-%d')
    data['force_update'] = force_update
    
    if minimum_version:
        data['minimum_version'] = minimum_version
    
    data['release_notes'] = {
        'pt-BR': descricao,
        'en': descricao  # Pode traduzir manualmente depois
    }
    
    # Adiciona ao changelog (mantém últimos 10)
    data['changelog'] = [descricao] + changelog_antigo[:9]
    
    # Atualiza URL de download
    github_user = input("Digite seu usuário do GitHub (ou Enter para manter): ").strip()
    if github_user:
        data['download_url'] = f"https://github.com/{github_user}/AgendaObras/releases/tag/v{nova_versao}"
    
    # Salva arquivo
    with open('version.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ version.json atualizado para versão {nova_versao}")
    print(f"📅 Data: {data['release_date']}")
    print(f"⚠️  Força atualização: {force_update}")
    if minimum_version:
        print(f"🔒 Versão mínima: {minimum_version}")


def atualizar_config_py(nova_versao: str):
    """Atualiza a versão no config.py"""
    config_file = Path('config.py')
    
    if not config_file.exists():
        print("⚠️  Arquivo config.py não encontrado")
        return
    
    conteudo = config_file.read_text(encoding='utf-8')
    
    # Substitui a linha VERSION
    novo_conteudo = re.sub(
        r"VERSION = '[^']+'",
        f"VERSION = '{nova_versao}'",
        conteudo
    )
    
    config_file.write_text(novo_conteudo, encoding='utf-8')
    print(f"✅ config.py atualizado com VERSION = '{nova_versao}'")


def gerar_comandos_git(nova_versao: str):
    """Gera comandos git para commit e tag"""
    print("\n" + "="*60)
    print("📋 Próximos passos:")
    print("="*60)
    print("\n1. Revisar as mudanças:")
    print("   git diff")
    print("\n2. Fazer commit:")
    print(f"   git add version.json config.py")
    print(f"   git commit -m \"chore(version): atualizar para {nova_versao}\"")
    print("\n3. Criar tag:")
    print(f"   git tag v{nova_versao}")
    print(f"   git push origin main")
    print(f"   git push origin v{nova_versao}")
    print("\n4. Criar release no GitHub:")
    print(f"   https://github.com/seu-usuario/AgendaObras/releases/new?tag=v{nova_versao}")
    print("\n5. Compilar e anexar executável ao release")
    print("="*60)


def main():
    if len(sys.argv) < 3:
        print("Uso: python update_version.py <versão> <descrição> [--force] [--minimum <versão>]")
        print("\nExemplo:")
        print("  python update_version.py 1.1.0 \"Melhorias gerais\"")
        sys.exit(1)
    
    nova_versao = sys.argv[1]
    descricao = sys.argv[2]
    force_update = '--force' in sys.argv
    
    minimum_version = None
    if '--minimum' in sys.argv:
        idx = sys.argv.index('--minimum')
        if idx + 1 < len(sys.argv):
            minimum_version = sys.argv[idx + 1]
    
    # Validação
    if not validar_versao(nova_versao):
        print(f"❌ Versão inválida: {nova_versao}")
        print("Formato esperado: X.Y.Z (ex: 1.2.0)")
        sys.exit(1)
    
    if minimum_version and not validar_versao(minimum_version):
        print(f"❌ Versão mínima inválida: {minimum_version}")
        sys.exit(1)
    
    print("="*60)
    print("🚀 Atualizador de Versão - AgendaObras")
    print("="*60)
    print(f"\n📦 Nova versão: {nova_versao}")
    print(f"📝 Descrição: {descricao}")
    print(f"⚠️  Força atualização: {force_update}")
    if minimum_version:
        print(f"🔒 Versão mínima: {minimum_version}")
    
    confirmacao = input("\nConfirma atualização? (s/n): ").lower()
    
    if confirmacao != 's':
        print("❌ Atualização cancelada")
        sys.exit(0)
    
    # Executar atualizações
    atualizar_version_json(nova_versao, descricao, force_update, minimum_version)
    atualizar_config_py(nova_versao)
    
    # Mostrar próximos passos
    gerar_comandos_git(nova_versao)


if __name__ == '__main__':
    main()
