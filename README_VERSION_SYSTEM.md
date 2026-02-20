# Sistema de Validação de Versão - AgendaObras

## 📋 Visão Geral

Este sistema implementa validação automática de versão comparando a versão local (hardcoded) com uma versão online publicada no GitHub. Quando uma atualização obrigatória está disponível, o sistema força o usuário a atualizar antes de continuar usando a aplicação.

## 🏗️ Arquitetura

### Arquivos do Sistema

1. **`version.json`** - Arquivo de metadados de versão hospedado no GitHub
2. **`version_checker.py`** - Módulo de verificação de versão
3. **`config.py`** - Configurações do sistema (inclui VERSION e URLs)
4. **`agenda_obras.py`** - Interface principal (integração da verificação)

### Fluxo de Funcionamento

```
[Inicialização do App]
        ↓
[Verificar Versão Online]
        ↓
    ┌───────────────┐
    │ Versão OK?    │
    └───────────────┘
         ↙     ↘
       SIM     NÃO
        ↓       ↓
   [Continua] [Mostra Dialog]
                ↓
        ┌─────────────────┐
        │ Força Update?   │
        └─────────────────┘
             ↙     ↘
           SIM     NÃO
            ↓       ↓
   [Bloqueante] [Opcional]
```

## 📝 Arquivo version.json

### Estrutura

```json
{
  "version": "1.0.0",
  "release_date": "2026-02-20",
  "minimum_version": "1.0.0",
  "force_update": false,
  "download_url": "https://github.com/seu-usuario/AgendaObras/releases/latest",
  "release_notes": {
    "pt-BR": "Descrição da versão em português",
    "en": "Version description in english"
  },
  "changelog": [
    "Nova funcionalidade 1",
    "Nova funcionalidade 2",
    "Correção de bug"
  ]
}
```

### Campos

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `version` | string | Versão online atual (formato semver: X.Y.Z) |
| `release_date` | string | Data de lançamento (YYYY-MM-DD) |
| `minimum_version` | string | Versão mínima obrigatória |
| `force_update` | boolean | Se true, força atualização imediata |
| `download_url` | string | URL para download da nova versão |
| `release_notes` | object | Notas de lançamento por idioma |
| `changelog` | array | Lista de mudanças da versão |

## 🚀 Como Usar

### 1. Configuração Inicial

#### Atualizar URLs no `config.py`:

```python
# URL do repositório no GitHub
GITHUB_REPO_URL = "https://github.com/SEU-USUARIO/AgendaObras"

# URL do arquivo version.json no GitHub (raw)
VERSION_JSON_URL = "https://raw.githubusercontent.com/SEU-USUARIO/AgendaObras/main/version.json"
```

**⚠️ IMPORTANTE:** Substitua `SEU-USUARIO` pelo seu nome de usuário real do GitHub!

### 2. Publicar version.json no GitHub

1. Faça commit do arquivo `version.json` no repositório
2. Certifique-se de que está na branch `main` (ou atualize a URL)
3. O arquivo estará acessível em: `https://raw.githubusercontent.com/seu-usuario/AgendaObras/main/version.json`

### 3. Lançar Nova Versão

#### a) Atualizar a versão no código:

```python
# config.py
VERSION = '1.1.0'  # Nova versão
```

#### b) Atualizar version.json:

```json
{
  "version": "1.1.0",
  "release_date": "2026-02-25",
  "minimum_version": "1.0.0",
  "force_update": false,
  "download_url": "https://github.com/seu-usuario/AgendaObras/releases/tag/v1.1.0",
  "release_notes": {
    "pt-BR": "Melhorias de performance e correções de bugs"
  },
  "changelog": [
    "Otimização do carregamento de obras",
    "Correção no envio de emails",
    "Melhorias na interface"
  ]
}
```

#### c) Criar release no GitHub:

```bash
git tag v1.1.0
git push origin v1.1.0
```

### 4. Forçar Atualização Obrigatória

Para forçar todos os usuários a atualizarem:

#### Opção 1: Usar `force_update`

```json
{
  "version": "1.2.0",
  "force_update": true,
  "minimum_version": "1.0.0"
}
```

**Resultado**: Usuários com versão < 1.2.0 verão modal bloqueante

#### Opção 2: Usar `minimum_version`

```json
{
  "version": "1.2.0",
  "force_update": false,
  "minimum_version": "1.2.0"
}
```

**Resultado**: Usuários com versão < 1.2.0 DEVEM atualizar (mais rígido)

## 🔍 API do VersionChecker

### Uso Básico

```python
from version_checker import VersionChecker

# Inicializar
checker = VersionChecker()

# Obter informações completas
info = checker.get_version_info()

# Verificar se precisa atualizar
needs_update = checker.needs_update()

# Verificar se é obrigatório
is_force = checker.is_force_update()

# Obter URL de download
download_url = checker.get_download_url()
```

### Métodos Disponíveis

| Método | Retorno | Descrição |
|--------|---------|-----------|
| `fetch_online_version()` | Dict \| None | Busca dados online |
| `compare_versions()` | Tuple[bool, str] | Compara versões |
| `needs_update()` | bool | Precisa atualizar? |
| `is_force_update()` | bool | É obrigatória? |
| `get_download_url()` | str \| None | URL de download |
| `get_release_notes()` | str | Notas de lançamento |
| `get_changelog()` | list | Lista de mudanças |
| `get_version_info()` | Dict | Todas as informações |

### Exemplo Completo

```python
from version_checker import check_version_and_notify

# Função auxiliar simplificada
needs_update, info = check_version_and_notify()

if needs_update:
    print(f"Nova versão disponível: {info['online_version']}")
    print(f"Versão atual: {info['current_version']}")
    print(f"Obrigatória: {info['force_update']}")
    print(f"Download: {info['download_url']}")
```

## 🧪 Testando o Sistema

### Teste Local

```bash
# Executar teste do módulo
python version_checker.py
```

Saída esperada:
```
============================================================
Sistema de Verificação de Versão - AgendaObras
============================================================

📦 Versão Atual: 1.0.0
🌐 Versão Online: 1.0.0
📊 Status: Você está usando a versão mais recente (1.0.0)

✅ Sistema atualizado!

============================================================
```

### Simular Atualização Disponível

1. Mude `VERSION` no `config.py` para uma versão anterior:
   ```python
   VERSION = '0.9.0'
   ```

2. Execute novamente:
   ```bash
   python version_checker.py
   ```

3. Você verá uma mensagem de atualização disponível

## 🎨 Experiência do Usuário

### Atualização Opcional

- Modal informativo com botões:
  - **"Lembrar Depois"** - Fecha o modal
  - **"Baixar Atualização"** - Abre URL no navegador

### Atualização Obrigatória

- Modal **não pode ser fechado** (persistent)
- Notificação persistente no topo da tela
- Apenas botão **"Baixar Atualização"** disponível
- ⚠️ Ícone de aviso vermelho

### Informações Exibidas

- ✅ Versão atual vs nova versão
- 📝 Notas de lançamento
- 📋 Changelog detalhado
- 🔗 Link direto para download

## 📱 Integração na UI

O sistema é integrado automaticamente no `AgendaObras.__init__()`:

```python
# Verifica atualização antes de construir UI
self.verificar_atualizacao()

# Construção da UI
self.header()
self.body()
self.footer()
```

## 🔒 Segurança

### Tratamento de Erros

- **Falha de rede**: Não bloqueia a aplicação
- **JSON inválido**: Log de erro, continua execução
- **Timeout**: 10 segundos por padrão
- **URL inválida**: Captura exceção, não quebra

### Validação de Versões

- Usa biblioteca `packaging` para comparação semântica
- Suporta versionamento semântico (semver)
- Formato: `MAJOR.MINOR.PATCH` (ex: 1.2.3)

## 📊 Fluxo de Lançamento

```
1. Desenvolver nova versão
   ↓
2. Atualizar VERSION no config.py
   ↓
3. Atualizar version.json com metadados
   ↓
4. Commit e push para GitHub
   ↓
5. Criar tag e release no GitHub
   ↓
6. Compilar executável (se aplicável)
   ↓
7. Anexar executável ao release
   ↓
8. Usuários recebem notificação automática
```

## 🛠️ Dependências

```
packaging>=21.0
```

Instalação:
```bash
pip install packaging
```

## 📄 Exemplo de Conventional Commit

```
feat(version): adicionar sistema de validação de versão

- Implementar VersionChecker para comparar versões
- Criar arquivo version.json com metadados de versão
- Integrar verificação automática no AgendaObras
- Adicionar diálogos de atualização obrigatória/opcional
- Atualizar requirements.txt com dependência packaging

BREAKING CHANGE: Sistema agora verifica versão ao iniciar
```

## ⚙️ Configurações Avançadas

### URL Customizada

```python
from version_checker import VersionChecker

# Usar URL alternativa
checker = VersionChecker(version_url="https://seu-cdn.com/version.json")
```

### Timeout Customizado

```python
checker = VersionChecker()
data = checker.fetch_online_version(timeout=5)  # 5 segundos
```

## 🐛 Troubleshooting

### Problema: "Não foi possível verificar atualizações"

**Causas possíveis:**
- Sem conexão com internet
- URL do version.json incorreta
- Repositório privado (deve ser público)
- Arquivo não está na branch correta

**Solução:**
1. Verificar conexão
2. Testar URL no navegador
3. Confirmar que o repositório é público
4. Verificar branch na URL (main vs master)

### Problema: "Versão não comparada corretamente"

**Causa:** Formato de versão inválido

**Solução:** Use formato semver: `X.Y.Z`
- ✅ Correto: `1.0.0`, `2.1.3`, `1.0.0-beta`
- ❌ Errado: `v1.0`, `1.0`, `version-1`

## 📞 Suporte

Para problemas ou dúvidas:
1. Verifique os logs no terminal
2. Execute `python version_checker.py` para diagnóstico
3. Revise as configurações de URL no `config.py`

---

**Desenvolvido para AgendaObras** 🏗️  
Sistema de Rastreamento de Demandas de Engenharia
