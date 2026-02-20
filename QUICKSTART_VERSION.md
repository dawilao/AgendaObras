# ========================================
# Guia Rápido: Sistema de Versão
# ========================================

## 🚀 Início Rápido

### 1. Configuração Inicial (APENAS UMA VEZ)

Edite o arquivo `config.py` e substitua `seu-usuario` pelo seu usuário do GitHub:

```python
# URL do repositório no GitHub
GITHUB_REPO_URL = "https://github.com/SEU-USUARIO/AgendaObras"

# URL do arquivo version.json no GitHub (raw)
VERSION_JSON_URL = "https://raw.githubusercontent.com/SEU-USUARIO/AgendaObras/main/version.json"
```

### 2. Lançar Nova Versão

Use o script `update_version.py`:

```bash
# Atualização opcional
python update_version.py 1.1.0 "Melhorias de performance"

# Atualização obrigatória
python update_version.py 2.0.0 "Grande atualização" --force

# Definir versão mínima obrigatória
python update_version.py 1.2.0 "Correções críticas" --minimum 1.2.0
```

### 3. Publicar no GitHub

Siga os comandos exibidos pelo script:

```bash
# 1. Adicionar arquivos
git add version.json config.py

# 2. Fazer commit
git commit -m "chore(version): atualizar para X.Y.Z"

# 3. Criar tag
git tag vX.Y.Z
git push origin main
git push origin vX.Y.Z

# 4. Criar release no GitHub
# Acesse: https://github.com/seu-usuario/AgendaObras/releases/new
```

## 📋 Tipos de Atualização

### Atualização Opcional (Padrão)

```bash
python update_version.py 1.1.0 "Nova funcionalidade adicionada"
```

- Usuário pode escolher "Lembrar Depois"
- Modal pode ser fechado
- Não bloqueia o uso do sistema

### Atualização Obrigatória (Force)

```bash
python update_version.py 2.0.0 "Atualização crítica" --force
```

- Modal NÃO pode ser fechado
- Apenas botão "Baixar Atualização"
- Bloqueia uso até atualizar

### Atualização com Versão Mínima

```bash
python update_version.py 1.2.0 "Correção de segurança" --minimum 1.2.0
```

- Força atualização para versões < 1.2.0
- Mais rígido que `--force`

## 🧪 Testar Sistema de Versão

### Teste 1: Verificar Sistema

```bash
python version_checker.py
```

Você verá:
```
============================================================
Sistema de Verificação de Versão - AgendaObras
============================================================

📦 Versão Atual: 1.0.0
🌐 Versão Online: 1.0.0
📊 Status: Você está usando a versão mais recente (1.0.0)

✅ Sistema atualizado!
```

### Teste 2: Simular Atualização

1. Edite `config.py` e mude a versão:
   ```python
   VERSION = '0.9.0'  # Versão anterior
   ```

2. Execute novamente:
   ```bash
   python version_checker.py
   ```

3. Você verá mensagem de atualização disponível

4. Restaure a versão:
   ```python
   VERSION = '1.0.0'
   ```

## 📝 Fluxo Completo de Release

```
1. Desenvolver nova funcionalidade
   ↓
2. Testar localmente
   ↓
3. Executar: python update_version.py X.Y.Z "Descrição"
   ↓
4. Revisar mudanças: git diff
   ↓
5. Fazer commit e push
   ↓
6. Criar release no GitHub
   ↓
7. Anexar executável ao release
   ↓
8. ✅ Usuários recebem notificação automática!
```

## 🔧 Comandos Úteis

### Verificar versão atual
```bash
grep "VERSION = " config.py
```

### Ver histórico de versões
```bash
git tag -l
```

### Ver última tag
```bash
git describe --tags --abbrev=0
```

### Deletar tag (se errou)
```bash
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
```

## ⚠️ Checklist Antes de Lançar

- [ ] Código testado localmente
- [ ] Versão atualizada em `config.py` E `version.json`
- [ ] Changelog atualizado com mudanças
- [ ] URL de download correta no `version.json`
- [ ] Commit e push realizados
- [ ] Tag criada e enviada
- [ ] Release criado no GitHub
- [ ] Executável compilado e anexado ao release

## 🐛 Problemas Comuns

### "Não foi possível verificar atualizações"
- Verifique se o `version.json` está publicado no GitHub
- Confirme que o repositório é público
- Teste a URL no navegador

### "Versão não compatível"
- Use formato semver: `X.Y.Z` (ex: 1.0.0)
- Não use prefixo `v` no VERSION
- Não use letras (use: 1.0.0, não: v1.0 ou 1.0)

### "Modal não aparece"
- Verifique se há conexão com internet
- Confirme URL do `version.json` no `config.py`
- Execute `python version_checker.py` para diagnóstico

## 📚 Documentação Completa

Para informações detalhadas, consulte:
- `README_VERSION_SYSTEM.md` - Documentação completa
- `version_checker.py` - Código do módulo
- `update_version.py` - Script auxiliar

## 🆘 Suporte

Problemas? Siga estes passos:
1. Execute: `python version_checker.py`
2. Verifique os logs no terminal
3. Revise configurações em `config.py`
4. Consulte `README_VERSION_SYSTEM.md`

---

**AgendaObras** 🏗️ - Sistema de Rastreamento de Demandas de Engenharia
