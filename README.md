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

## Variáveis de ambiente

Ajustes opcionais, lidos do ambiente do processo. Todos têm valor padrão, então nenhum é obrigatório.

> **Importante:** estas variáveis são lidas quando o sistema inicia, **antes** do `email_config.env` ser carregado. Por isso, **não** coloque estas variáveis nesse arquivo. Defina-as no ambiente do serviço (ex.: `Environment=` ou `EnvironmentFile=` no systemd) ou exporte antes de iniciar (`export AGENDA_MAIL_MAX_MB=20`). As variáveis de SMTP continuam na seção [Configuração de e-mail](#configuração-de-e-mail).

### Caminhos

| Variável | Padrão | Para que serve |
|---|---|---|
| `AGENDA_OBRAS_DB_PATH` | `db/agendaobras.db` (ou na raiz do projeto, se a pasta `db/` não existir) | Banco principal |
| `AGENDA_OBRAS_USERS_DB_PATH` | idem, `users.db` | Usuários e autenticação |
| `AGENDA_OBRAS_CONTRATOS_DB_PATH` | idem, `contratos.db` | Vínculos de contratos |
| `AGENDA_OBRAS_BIBLIOTECA_DB_PATH` | idem, `biblioteca.db` | Biblioteca |
| `AGENDA_OBRAS_BIBLIOTECA_UPLOADS_PATH` | `uploads/biblioteca` | PDFs da Biblioteca |
| `AGENDA_MAIL_ROOT` | `comunicacoes/usuarios`, ao lado do banco principal | Bancos das Comunicações (um por usuário e o compartilhado) |
| `AGENDA_MAIL_FILES_ROOT` | `uploads/comunicacoes` | Anexos dos e-mails (uma cópia por conteúdo) |
| `AGENDAOBRAS_ERRO_DIR` | `erros/` | Logs de erro |

### Limites e comportamento

| Variável | Padrão | Para que serve |
|---|---|---|
| `BIBLIOTECA_PDF_MAX_MB` | `5` | Tamanho máximo de um PDF enviado à Biblioteca |
| `AGENDA_MAIL_MAX_MB` | `15` | Tamanho máximo de um e-mail importado (com anexos). Os maiores aparecem em "E-mails não importados" |
| `AGENDA_MAIL_COMPACTAR` | `1` | Compactação sem perda dos anexos novos. Use `0` para gravar os anexos como chegaram. Com `0`, os anexos já compactados continuam legíveis |
| `AGENDA_OBRAS_TIMEZONE` | `America/Sao_Paulo` | Fuso do processo (servidores Linux costumam rodar em UTC) |
| `NICEGUI_STORAGE_SECRET` | — | Chave das sessões. Também pode ficar no `email_config.env` |

## Manutenção dos anexos das Comunicações

Os anexos ficam em `AGENDA_MAIL_FILES_ROOT`, sempre com compactação **sem perda**: o arquivo baixado é idêntico ao recebido, e o sha256 é conferido na leitura. O formato gravado depende do conteúdo:

- **ZIPs** (inclusive `.docx` e `.xlsx`): os trechos comprimidos grandes ficam guardados uma única vez. Assim, as pranchas que se repetem entre revisões de um projeto não ocupam espaço de novo.
- **PDF, XML, TXT e similares:** comprimidos com lzma, quando isso compensa.
- **Imagens, DWG, RAR e 7z:** gravados como chegaram, porque já vêm comprimidos.

Comandos (rodar na raiz do projeto, com as mesmas variáveis de ambiente do serviço):

```bash
python -m comunicacoes.espaco                        # relatório: espaço por tipo, economia possível, órfãos
python -m comunicacoes.compactar                     # simulação: não altera nada
python -m comunicacoes.compactar --aplicar           # compacta os anexos gravados antes desta versão
python -m comunicacoes.compactar --aplicar --orfaos  # também remove arquivos sem uso há mais de 24 h
```

**Lixeira da equipe:** no Histórico da equipe, administradores podem enviar um arquivo de uma conversa para a lixeira. Ele sai do histórico e das caixas pessoais que têm os mesmos e-mails. Por 15 dias é possível restaurar; depois disso, ou quando alguém usa "Excluir definitivamente", o arquivo sai do disco, desde que nenhum outro e-mail use o mesmo conteúdo. A rotina que esvazia a lixeira vencida roda na inicialização do app e a cada 24 h. Arquivos registrados como apólice ou boleto no controle de seguro não podem ser excluídos.

Faça backup de `AGENDA_MAIL_FILES_ROOT` antes de usar `--aplicar`. Os dois comandos mostram na primeira linha as pastas de bancos e de anexos que estão usando; confira se são as do serviço. A limpeza de órfãos se recusa a rodar se algum banco ou manifesto de ZIP não puder ser lido, e também se os órfãos passarem de 10 arquivos e de 20% do total, o que costuma indicar pastas erradas. Nesse último caso, use `--forcar` só depois de conferir.

## Tecnologias

- [NiceGUI](https://nicegui.io/) — interface web
- SQLite — banco de dados
- Python 3.12+

## Licença

MIT — veja [LICENSE](LICENSE).
