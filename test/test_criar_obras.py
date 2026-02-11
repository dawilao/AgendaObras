"""
Script de teste para criar 4 obras aleatórias no banco de dados.
Usado para popular o sistema com dados de exemplo.
"""

import sys
import os
import random
import datetime

# Adiciona o diretório pai ao path para importar os módulos
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database

def gerar_obras_aleatorias():
    """Gera 4 obras com dados aleatórios realistas"""
    
    # Listas de dados aleatórios
    clientes = [
        "Construtora ABC Ltda",
        "Empreendimentos XYZ S.A.",
        "Engenharia Nova Era",
        "Grupo Construtor Delta"
    ]
    
    tipos_obras = [
        "Reforma de Fachada",
        "Construção de Edifício Comercial",
        "Ampliação de Instalações Industriais",
        "Modernização de Sistema Elétrico"
    ]
    
    servicos = [
        "Engenharia Civil - Estrutura",
        "Instalações Elétricas",
        "Projetos Arquitetônicos",
        "Consultoria Técnica"
    ]
    
    meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 
             'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
    
    status_list = ['Não Iniciada', 'Em Andamento', 'Em Andamento', 'Não Iniciada']
    
    obras = []
    
    for i in range(4):
        # Dados básicos
        nome_contrato = f"{tipos_obras[i]} - CT-{2026}-{(i+1):03d}"
        cliente = clientes[i]
        
        # Valores financeiros (entre 50.000 e 500.000)
        valor_contrato = round(random.uniform(50000, 500000), 2)
        valor_parceiro = round(valor_contrato * random.uniform(0.1, 0.3), 2) if random.choice([True, False]) else None
        valor_percentual = round(random.uniform(5, 15), 2) if valor_parceiro else None
        total_obra = round(valor_contrato * random.uniform(1.2, 2.0), 2)
        
        # Datas
        # Data de início: entre 30 dias atrás e 60 dias à frente
        dias_offset = random.randint(-30, 60)
        data_inicio = (datetime.date.today() + datetime.timedelta(days=dias_offset)).strftime('%Y-%m-%d')
        
        # Mês e ano de execução
        data_inicio_obj = datetime.datetime.strptime(data_inicio, '%Y-%m-%d')
        mes_execucao = meses[data_inicio_obj.month - 1]
        ano_execucao = data_inicio_obj.year
        
        # Status
        status = status_list[i]
        
        # Dados adicionais
        contrato_ic = f"IC-{random.randint(1000, 9999)}"
        prefixo_agencia = f"AG{random.randint(100, 999)}"
        servico = servicos[i]
        
        # Datas críticas (apenas para algumas obras)
        data_assinatura = None
        data_aio = None
        
        # Se a obra está em andamento, tem datas críticas
        if status == 'Em Andamento' and dias_offset < 0:  # Obras que já começaram
            # Data de assinatura: alguns dias antes do início
            data_assinatura = (data_inicio_obj - datetime.timedelta(days=random.randint(10, 30))).strftime('%Y-%m-%d')
            # Data AIO: alguns dias depois da assinatura
            if random.choice([True, False]):
                data_aio = (data_inicio_obj - datetime.timedelta(days=random.randint(1, 10))).strftime('%Y-%m-%d')
        
        obra = {
            'nome_contrato': nome_contrato,
            'cliente': cliente,
            'valor_contrato': valor_contrato,
            'data_inicio': data_inicio,
            'status': status,
            'contrato_ic': contrato_ic,
            'prefixo_agencia': prefixo_agencia,
            'servico': servico,
            'valor_parceiro': valor_parceiro,
            'valor_percentual': valor_percentual,
            'total_obra': total_obra,
            'mes_execucao': mes_execucao,
            'ano_execucao': ano_execucao,
            'data_assinatura': data_assinatura,
            'data_aio': data_aio
        }
        
        obras.append(obra)
    
    return obras


def main():
    """Função principal que cria as obras no banco de dados"""
    print("=" * 70)
    print("🏗️  TESTE: Criação de Obras Aleatórias")
    print("=" * 70)
    print()
    
    # Caminho para o banco de dados na pasta raiz
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'agendaobras.db')
    
    # Conecta ao banco de dados
    db = Database(db_path)
    
    # Gera obras aleatórias
    obras = gerar_obras_aleatorias()
    
    # Cria cada obra
    print("📝 Criando obras...")
    print()
    
    for i, obra_dados in enumerate(obras, 1):
        try:
            # Extrai dados obrigatórios
            nome = obra_dados.pop('nome_contrato')
            cliente = obra_dados.pop('cliente')
            valor = obra_dados.pop('valor_contrato')
            data_inicio = obra_dados.pop('data_inicio')
            status = obra_dados.pop('status')
            
            # Cria obra com dados adicionais em **kwargs
            obra_id = db.criar_obra(
                nome_contrato=nome,
                cliente=cliente,
                valor_contrato=valor,
                data_inicio=data_inicio,
                status=status,
                **obra_dados
            )
            
            # Formata data para exibição
            data_inicio_formatada = datetime.datetime.strptime(data_inicio, '%Y-%m-%d').strftime('%d/%m/%Y')
            
            print(f"✅ Obra {i} criada com sucesso!")
            print(f"   ID: {obra_id}")
            print(f"   Nome: {nome}")
            print(f"   Cliente: {cliente}")
            print(f"   Valor: R$ {valor:,.2f}")
            print(f"   Data Início: {data_inicio_formatada}")
            print(f"   Status: {status}")
            
            if obra_dados.get('data_assinatura'):
                data_assinatura_formatada = datetime.datetime.strptime(
                    obra_dados['data_assinatura'], '%Y-%m-%d'
                ).strftime('%d/%m/%Y')
                print(f"   Data Assinatura: {data_assinatura_formatada}")
            
            if obra_dados.get('data_aio'):
                data_aio_formatada = datetime.datetime.strptime(
                    obra_dados['data_aio'], '%Y-%m-%d'
                ).strftime('%d/%m/%Y')
                print(f"   Data AIO: {data_aio_formatada}")
            
            print()
            
        except Exception as e:
            print(f"❌ Erro ao criar obra {i}: {e}")
            print()
    
    print("=" * 70)
    print("✅ Processo concluído!")
    print("=" * 70)
    print()
    print("💡 Dica: Abra o AgendaObras para visualizar as obras criadas.")


if __name__ == "__main__":
    main()
