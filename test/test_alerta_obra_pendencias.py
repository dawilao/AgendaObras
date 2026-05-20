"""
Teste manual para validar trigger e envio de alerta de obra concluida com pendencias.

Fluxo:
1) Carrega configuracao SMTP (aceita caminho externo do email_config.env)
2) Lista obras com status_conclusao_obra = 'com_pendencias'
3) Envia 1 email de teste direto para a primeira obra encontrada
4) Dispara o trigger real (notificador.verificar_agora(forcar=True))
5) Exibe historico de envios do dia (tipo obra_pendencias)
"""

import argparse
import datetime
import os
import sys
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import EmailConfig
from db import Database, CAMINHO_DB
from services.email_service import EmailService
from services.notificador import NotificadorPrazos


ENV_EXTERNO_PADRAO = r"G:\Meu Drive\17 - MODELOS\PROGRAMAS\AgendaObras\app\email_config.env"


def carregar_config_email(email_service: EmailService, caminho_env: str) -> bool:
    """Forca recarga da configuracao SMTP, inclusive de arquivo externo."""
    caminho_env = (caminho_env or "").strip()
    caminhos_extras = [os.path.dirname(caminho_env)] if caminho_env else None
    config = EmailConfig.carregar(
        caminho_config=caminho_env if caminho_env else None,
        caminhos_extras=caminhos_extras,
    )
    email_service.config = config
    return email_service.config.is_configured()


def buscar_obras_com_pendencias(db: Database) -> List[Dict]:
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, nome_contrato, cliente, observacoes, status_conclusao_obra
        FROM obras
        WHERE LOWER(TRIM(COALESCE(status_conclusao_obra, ''))) = 'com_pendencias'
        ORDER BY id
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def enviar_alerta_teste_direto(
    notificador: NotificadorPrazos,
    email_service: EmailService,
    obra: Dict,
) -> bool:
    """Envia um alerta de teste manual para a obra com pendencias."""
    assunto, corpo_html, _ = email_service.criar_email_obras_com_pendencias(obra)
    destinatarios = ["dawison@machengenharia.com.br"]

    if not destinatarios:
        print(
            f"⚠ Sem destinatarios para teste direto da obra: {obra.get('nome_contrato')}"
        )
        return False

    sucesso, msg = email_service.enviar_email(destinatarios, assunto, corpo_html)
    notificador._registrar_historico_com_retry(
        obra["id"],
        0,
        "obra_pendencias_teste_manual",
        destinatarios,
        sucesso,
        None if sucesso else msg,
    )

    if sucesso:
        print(f"✅ Teste direto enviado para obra: {obra.get('nome_contrato')}")
    else:
        print(f"❌ Falha no teste direto para obra {obra.get('nome_contrato')}: {msg}")

    return sucesso


def mostrar_historico_hoje(db: Database) -> None:
    hoje = datetime.date.today().strftime("%Y-%m-%d")
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            hn.id,
            hn.obra_id,
            hn.tarefa_id,
            hn.tipo_notificacao,
            hn.destinatarios,
            hn.sucesso,
            hn.mensagem_erro,
            hn.data_envio,
            o.nome_contrato
        FROM historico_notificacoes hn
        LEFT JOIN obras o ON o.id = hn.obra_id
        WHERE DATE(hn.data_envio) = ?
          AND hn.tipo_notificacao IN ('obra_pendencias', 'obra_pendencias_teste_manual')
        ORDER BY hn.id DESC
        """,
        (hoje,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    print("\n" + "=" * 72)
    print(f"📊 Historico de hoje ({hoje}) para alertas de obra pendencias")
    print("=" * 72)

    if not rows:
        print("Nenhum registro encontrado para hoje.")
        return

    for r in rows:
        ok = "SIM" if r["sucesso"] else "NAO"
        print(
            f"ID={r['id']} | Obra={r.get('nome_contrato') or r['obra_id']} | "
            f"Tipo={r['tipo_notificacao']} | Sucesso={ok} | Data={r['data_envio']}"
        )
        if r.get("mensagem_erro"):
            print(f"   Erro: {r['mensagem_erro']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida trigger e envio de alerta para obra com pendencias"
    )
    parser.add_argument(
        "--env-path",
        default=ENV_EXTERNO_PADRAO,
        help="Caminho do email_config.env externo",
    )
    parser.add_argument(
        "--sem-teste-direto",
        action="store_true",
        help="Nao envia o email de teste direto",
    )
    parser.add_argument(
        "--sem-trigger-real",
        action="store_true",
        help="Nao executa notificador.verificar_agora(forcar=True)",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("🧪 TESTE - ALERTA OBRA COM PENDENCIAS")
    print("=" * 72)
    print(f"📂 Banco: {CAMINHO_DB}")
    print(f"📄 Env: {args.env_path}")

    db = Database()
    email_service = EmailService(db)
    notificador = NotificadorPrazos(db, email_service)

    configurado = carregar_config_email(email_service, args.env_path)
    if configurado:
        print("✅ SMTP configurado")
        print(f"   Remetente: {email_service.config.email_remetente}")
        print(
            f"   Servidor: {email_service.config.smtp_server}:{email_service.config.smtp_port}"
        )
    else:
        print("⚠ SMTP NAO configurado. O envio deve falhar ou ser ignorado.")

    obras = buscar_obras_com_pendencias(db)
    print(f"\n🔎 Obras com pendencias encontradas: {len(obras)}")
    for obra in obras:
        print(f"   - ID {obra['id']}: {obra['nome_contrato']} (cliente={obra['cliente']})")

    if not obras:
        print("\n⚠ Nenhuma obra com status 'com_pendencias' encontrada.")
        print("   Marque uma obra como 'OBRA CONCLUIDA COM PENDENCIAS' e rode novamente.")
        return 1

    if not args.sem_teste_direto:
        print("\n📧 Enviando email de teste direto (obra_pendencias_teste_manual)...")
        enviar_alerta_teste_direto(notificador, email_service, obras[0])

    if not args.sem_trigger_real:
        print("\n🚀 Disparando trigger real: notificador.verificar_agora(forcar=True)...")
        resultado = notificador.verificar_agora(forcar=True)
        print(f"Resultado do trigger real: {resultado}")

    mostrar_historico_hoje(db)

    print("\n✅ Teste finalizado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
