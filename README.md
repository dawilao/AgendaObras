# 🏗️ AgendaObras

Sistema de rastreamento de obras e demandas de engenharia com interface web e notificações automáticas.

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## 🚀 Instalação

```bash
# Clone o repositório
git clone https://github.com/dawilao/AgendaObras.git
cd AgendaObras

# Instale as dependências
pip install -r requirements.txt

# Execute a aplicação
python AgendaObras.py
```

Acesse em: `http://localhost:8080`

## ✨ Funcionalidades

- **Gestão de Obras**: Cadastro e acompanhamento de obras
- **Tarefas com Dependências**: Sistema de tarefas interligadas
- **Notificações por Email**: Alertas automáticos com reiteração progressiva
- **Tarefas Recorrentes**: Geração automática de tarefas periódicas
- **Sistema de Versão**: Validação automática de atualizações

## ⚙️ Configuração

### Email (Opcional)

Copie `email_config.env.example` para `email_config.env` e configure:

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu-email@gmail.com
SMTP_PASSWORD=sua-senha-app
```

## 🛠️ Tecnologias

- **[NiceGUI](https://nicegui.io/)** - Interface web
- **SQLite** - Banco de dados
- **Python 3.13+** - Backend

## 📄 Licença

Licença MIT - veja [LICENSE](LICENSE) para detalhes.