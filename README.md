# AgendaObras

Sistema de rastreamento de obras e demandas de engenharia com interface web, checklist automático e notificações por e-mail.

## Instalação

```bash
pip install -r requirements.txt
python AgendaObras.py
```

Acesse em `http://localhost:8080`. No primeiro acesso, o sistema solicita a criação do usuário administrador.

> **Windows:** execute com `PYTHONUTF8=1 python AgendaObras.py` para evitar erros de codificação Unicode.

## Funcionalidades

### Gestão de obras
Cada obra é representada por um card com os campos: contrato, prefixo/agência, serviço, valor do parceiro, percentual, total, data de início, data de assinatura, data da AIO e data de conclusão.

### Checklist automático
Ao criar uma obra, o sistema gera automaticamente um checklist de tarefas com prazos e dependências. As tarefas são liberadas progressivamente conforme as anteriores são concluídas. Algumas tarefas disparam inputs adicionais, como a data de assinatura do contrato e a data da AIO, que desbloqueiam tarefas subsequentes.

Tarefas com reiteração aceitam até 3 alertas progressivos (a cada 2 dias). Tarefas sem reiteração têm prazo fixo com alerta crítico no último dia. Após o prazo, a tarefa passa para "atrasada" e recebe alertas críticos diários até ser concluída.

### Medições mensais
Obras iniciadas geram tarefas recorrentes mensais de MEDIÇÃO e CONFIRMAÇÃO DE MEDIÇÃO. O sistema controla o valor faturado por medição e, ao concluir a última medição, solicita a finalização da obra (com ou sem pendências).

### Notificações por e-mail
Os alertas são disparados automaticamente às **08:00 em dias úteis** (America/Sao_Paulo). Se o servidor reiniciar após esse horário sem ter disparado no dia, o envio ocorre imediatamente (catch-up).

Os e-mails são agrupados por obra e classificados por tipo:
- **Reiteração** (1ª, 2ª ou 3ª) — tarefas com prazo flexível pendentes
- **Prazo fixo crítico** — tarefas com prazo fixo no dia limite
- **Atrasada** — tarefas vencidas, enviadas diariamente
- **Obra com pendências** — alerta diário para obras concluídas com pendências em aberto

## Configuração de e-mail

Copie `email_config.env.example` para `email_config.env` (aceita formato `.env` ou JSON):

```env
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=seu-email@gmail.com
SMTP_PASSWORD=sua-senha-app
EMAIL_REMETENTE=seu-email@gmail.com
EMAIL_DESTINATARIOS=destinatario1@email.com,destinatario2@email.com
EMAIL_CRITICO=gestor@email.com
```

Sem este arquivo, o sistema funciona normalmente mas não envia alertas.

## Bancos de dados

O sistema cria três arquivos SQLite na raiz do projeto:

| Arquivo | Conteúdo |
|---|---|
| `agendaobras.db` | Obras, checklist, medições e valores |
| `users.db` | Usuários e autenticação |
| `contratos.db` | Vínculos de contratos |

## Tecnologias

- [NiceGUI](https://nicegui.io/) — interface web
- SQLite — banco de dados
- Python 3.12+

## Licença

MIT — veja [LICENSE](LICENSE).
