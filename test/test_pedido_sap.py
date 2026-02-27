"""
Teste para verificar se o campo pedido_sap está sendo salvo e recuperado corretamente
"""

import sys
sys.path.insert(0, 'c:/Users/mache/OneDrive/Documentos/GitHub/AgendaObras')

from database import Database

def test_pedido_sap():
    print("🧪 Testando campo pedido_sap...\n")
    
    db = Database()
    
    # Criar nova obra com pedido_sap
    print("1️⃣ Criando obra com pedido_sap...")
    obra_id = db.criar_obra(
        nome_contrato="Teste Pedido SAP",
        cliente="Cliente Teste",
        valor_contrato=100000.00,
        data_inicio="2026-03-01",
        status="Não Iniciada",
        pedido_sap="SAP-12345"
    )
    print(f"   ✅ Obra criada com ID: {obra_id}")
    
    # Recuperar obra
    print("\n2️⃣ Recuperando obra...")
    obra = db.obter_obra(obra_id)
    print(f"   Pedido SAP recuperado: '{obra.get('pedido_sap')}'")
    
    if obra.get('pedido_sap') == 'SAP-12345':
        print("   ✅ Campo pedido_sap salvo e recuperado corretamente!")
    else:
        print(f"   ❌ ERRO: Esperado 'SAP-12345', mas obteve '{obra.get('pedido_sap')}'")
        return False
    
    # Atualizar pedido_sap
    print("\n3️⃣ Atualizando pedido_sap...")
    db.atualizar_obra(
        obra_id=obra_id,
        nome_contrato="Teste Pedido SAP",
        cliente="Cliente Teste",
        valor_contrato=100000.00,
        data_inicio="2026-03-01",
        status="Não Iniciada",
        pedido_sap="SAP-99999"
    )
    print("   ✅ Obra atualizada")
    
    # Recuperar novamente
    print("\n4️⃣ Recuperando obra atualizada...")
    obra = db.obter_obra(obra_id)
    print(f"   Pedido SAP recuperado: '{obra.get('pedido_sap')}'")
    
    if obra.get('pedido_sap') == 'SAP-99999':
        print("   ✅ Campo pedido_sap atualizado corretamente!")
    else:
        print(f"   ❌ ERRO: Esperado 'SAP-99999', mas obteve '{obra.get('pedido_sap')}'")
        return False
    
    # Limpar teste
    print("\n5️⃣ Limpando teste...")
    db.deletar_obra(obra_id)
    print("   ✅ Obra de teste deletada")
    
    print("\n✅ TODOS OS TESTES PASSARAM!\n")
    return True

if __name__ == '__main__':
    try:
        test_pedido_sap()
    except Exception as e:
        print(f"\n❌ ERRO: {e}\n")
        import traceback
        traceback.print_exc()
