"""
Prévia do RESUMO DIÁRIO com dados reais (script manual, não é teste pytest).

- Lê o banco real SOMENTE para leitura (NotificadorPrazos.gerar_resumos_do_dia):
  não atualiza tarefas nem grava histórico.
- Sem flags: lista os destinatários do dia, tamanho de cada e-mail e salva os HTML em disco.
- --enviar: envia os exemplos SOMENTE para a caixa de teste (TESTE_PARA),
  com o assunto prefixado por "[TESTE – resumo de <destinatário real>]".

- --como-coordenador CONTRATO: simula um coordenador vinculado ao(s) contrato(s)
  (pode repetir; 'todos' = todos os contratos com alerta) para ver o modelo COMPLETO
  de coordenação. Não altera cadastro: usa as mesmas regras do envio real em memória.

Uso:
    python test/preview_resumo_diario.py
    python test/preview_resumo_diario.py --enviar
    python test/preview_resumo_diario.py --enviar --destinatario fulano@empresa.com
    python test/preview_resumo_diario.py --enviar --como-coordenador todos
    python test/preview_resumo_diario.py --enviar --como-coordenador "C.E.F MANAUS - 4569.2024"
"""

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import EmailConfig
from db import Database, CAMINHO_DB
from services.email_service import EmailService
from services.notificador import NotificadorPrazos

# Único endereço que recebe e-mails deste script.
TESTE_PARA = "dawison@machengenharia.com.br"

ENV_EXTERNO_PADRAO = r"G:\Meu Drive\17 - MODELOS\PROGRAMAS\Gerador de Requisições\app\email_config.env"


def carregar_config_email(email_service: EmailService, caminho_env: str) -> bool:
    caminho_env = (caminho_env or "").strip()
    if caminho_env and os.path.exists(caminho_env):
        email_service.config = EmailConfig.carregar(
            caminho_config=caminho_env,
            caminhos_extras=[os.path.dirname(caminho_env)],
        )
    return email_service.config.is_configured()


def contar_tarefas(resumo) -> int:
    return sum(len(lista) for obra in resumo["obras"] for lista in obra["tarefas"].values())


COORDENADOR_SIMULADO = "coordenador-simulado@preview"


def simular_coordenador(notificador: NotificadorPrazos, obras, pedidos):
    """Monta, em memória, o resumo de um coordenador fictício vinculado aos contratos pedidos."""
    contratos_alerta = sorted({(o["info"].get("cliente") or "").strip() for o in obras.values()} - {""})
    if any(p.strip().lower() == "todos" for p in pedidos):
        contratos = set(contratos_alerta)
    else:
        contratos = {p.strip() for p in pedidos if p.strip()}

    invalidos = contratos - set(contratos_alerta)
    if invalidos:
        print("⚠ Contrato(s) sem alerta hoje (ou nome diferente):")
        for c in sorted(invalidos):
            print(f"   - {c}")
        print("  Contratos com alerta hoje:")
        for c in contratos_alerta:
            print(f"   - {c}")

    usuario = {
        "email": COORDENADOR_SIMULADO,
        "nome": "Coordenador",
        "is_admin": False,
        "recebe_critico": True,
        "contratos": contratos & set(contratos_alerta),
    }
    permissoes = notificador._mapear_permissoes(obras, [usuario])
    resumo = notificador._montar_resumos(obras, permissoes).get(COORDENADOR_SIMULADO)
    return resumo, sorted(usuario["contratos"])


def escolher_exemplos(resumos, pedidos):
    if pedidos:
        pedidos = [p.strip().lower() for p in pedidos]
        faltando = [p for p in pedidos if p not in resumos]
        for p in faltando:
            print(f"⚠ {p} não tem resumo hoje.")
        return [p for p in pedidos if p in resumos]

    exemplos = []
    coordenadores = [e for e, r in resumos.items() if not r["resumido"]]
    resumidos = [e for e, r in resumos.items() if r["resumido"]]
    if coordenadores:
        exemplos.append(max(coordenadores, key=lambda e: (len(resumos[e]["obras"]), contar_tarefas(resumos[e]))))
    if resumidos:
        exemplos.append(resumidos[0])
    return exemplos


def main() -> int:
    parser = argparse.ArgumentParser(description="Prévia do resumo diário de alertas")
    parser.add_argument("--env-path", default=ENV_EXTERNO_PADRAO, help="Caminho do email_config.env")
    parser.add_argument("--enviar", action="store_true", help=f"Envia exemplos SOMENTE para {TESTE_PARA}")
    parser.add_argument("--destinatario", action="append", default=[],
                        help="De quem é o resumo a pré-visualizar (pode repetir)")
    parser.add_argument("--saida", default="", help="Pasta para salvar os HTML (padrão: pasta temporária)")
    parser.add_argument("--como-coordenador", action="append", default=[], metavar="CONTRATO",
                        help="Simula coordenador do(s) contrato(s) ('todos' = todos com alerta)")
    args = parser.parse_args()

    print("=" * 72)
    print("📋 PRÉVIA DO RESUMO DIÁRIO (somente leitura)")
    print("=" * 72)
    print(f"📂 Banco: {CAMINHO_DB}")

    db = Database()
    email_service = EmailService(db)
    configurado = carregar_config_email(email_service, args.env_path)
    notificador = NotificadorPrazos(db, email_service)
    hoje = notificador._hoje_referencia()

    obras, resumos = notificador.gerar_resumos_do_dia()
    total_tarefas = sum(len(l) for o in obras.values() for l in o["tarefas"].values())
    print(f"📅 Data de referência: {hoje.strftime('%d/%m/%Y')}")
    print(f"🏗 Obras com alerta: {len(obras)} | Tarefas em alerta: {total_tarefas}")
    print(f"📧 Resumos (1 por pessoa): {len(resumos)}\n")

    contratos_simulados = []
    if args.como_coordenador:
        resumo_sim, contratos_simulados = simular_coordenador(notificador, obras, args.como_coordenador)
        if resumo_sim:
            resumos = dict(resumos)
            resumos[COORDENADOR_SIMULADO] = resumo_sim
            print(f"🧪 Coordenador simulado para {len(contratos_simulados)} contrato(s):")
            for c in contratos_simulados:
                print(f"   - {c}")
            print()
        else:
            print("⚠ Nenhum alerta para os contratos simulados.\n")

    if not resumos:
        print("Nenhum resumo a enviar hoje.")
        return 0

    saida = args.saida or tempfile.mkdtemp(prefix="resumo_diario_")
    os.makedirs(saida, exist_ok=True)

    gerados = {}
    print(f"{'Destinatário':40s} {'Obras':>5s} {'Taref.':>6s} {'Tipo':>9s} {'KB':>7s}")
    print("-" * 72)
    for email, resumo in sorted(resumos.items()):
        assunto, html = email_service.criar_email_resumo_diario(
            resumo["nome"], resumo["obras"], hoje, resumo["resumido"]
        )
        gerados[email] = (assunto, html)
        tamanho_kb = len(html.encode("utf-8")) / 1024
        tipo = "resumido" if resumo["resumido"] else "completo"
        print(f"{email:40s} {len(resumo['obras']):5d} {contar_tarefas(resumo):6d} {tipo:>9s} {tamanho_kb:7.1f}")
        nome_arquivo = email.replace("@", "_at_").replace(".", "_") + ".html"
        with open(os.path.join(saida, nome_arquivo), "w", encoding="utf-8") as f:
            f.write(html)

    print(f"\n💾 HTML salvos em: {saida}")

    if not args.enviar:
        print("\nℹ Nada foi enviado. Use --enviar para mandar exemplos para", TESTE_PARA)
        return 0

    if not configurado:
        print("\n❌ SMTP não configurado; não é possível enviar. Informe --env-path.")
        return 1

    if COORDENADOR_SIMULADO in resumos:
        exemplos = [COORDENADOR_SIMULADO] + escolher_exemplos(resumos, args.destinatario) if args.destinatario \
            else [COORDENADOR_SIMULADO]
    else:
        exemplos = escolher_exemplos(resumos, args.destinatario)
    print(f"\n🚀 Enviando {len(exemplos)} exemplo(s) SOMENTE para {TESTE_PARA}...")
    for email in exemplos:
        assunto, html = gerados[email]
        if email == COORDENADOR_SIMULADO:
            assunto_teste = f"[TESTE – modelo coordenação] {assunto}"
        else:
            assunto_teste = f"[TESTE – resumo de {email}] {assunto}"
        sucesso, msg = email_service.enviar_email(TESTE_PARA, assunto_teste, html)
        print(f"   {'✅' if sucesso else '❌'} {assunto_teste} {'' if sucesso else msg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
