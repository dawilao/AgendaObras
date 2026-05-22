"""
Repositório de Checklist e Medições.
Extraído de database.py sem alteração de lógica.
"""

import datetime
from typing import List, Dict, Optional

from core.error_logger import log_error
from db.connection import BaseRepository, CAMINHO_DB


class ChecklistRepository(BaseRepository):
    """
    Métodos de checklist, medições dinâmicas e valores financeiros.
    Projetado para uso via herança múltipla em Database(ObrasRepository, ChecklistRepository).
    """

    def _criar_checklist_obra(self, cursor, obra_id: int, obra_dados: Dict):
        """Cria checklist automático baseado nos templates com dependências e lógica avançada."""
        cursor.execute('SELECT * FROM checklist_templates ORDER BY ordem')
        templates = cursor.fetchall()

        template_map = {}

        data_inicio = obra_dados.get('data_inicio') or None
        data_assinatura = obra_dados.get('data_assinatura') or None
        data_aio = obra_dados.get('data_aio') or None
        data_acionamento = obra_dados.get('data_acionamento') or None

        hoje = datetime.date.today()
        obra_ja_comecou = False
        if data_inicio and data_inicio.strip():
            try:
                data_inicio_obj = datetime.datetime.strptime(data_inicio, '%Y-%m-%d').date()
                obra_ja_comecou = data_inicio_obj <= hoje
            except ValueError:
                obra_ja_comecou = False

        for template in templates:
            if template['recorrencia'] == 'mensal':
                continue
            if ('auto_criar' in template.keys() and template['auto_criar'] == 0):
                continue

            bloqueado = 0
            data_limite = None
            data_base = None

            if template['base_calculo'] == 'criacao':
                if data_acionamento and data_acionamento.strip():
                    data_base = data_acionamento
                else:
                    data_base = datetime.date.today().strftime('%Y-%m-%d')
                data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])

            elif template['base_calculo'] == 'inicio':
                data_base = data_inicio
                if data_base and data_base.strip():
                    try:
                        data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                        data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])
                    except ValueError:
                        bloqueado = 1
                        data_limite = None
                else:
                    bloqueado = 1

            elif template['base_calculo'] == 'assinatura':
                data_base = data_assinatura
                if data_base:
                    data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                    data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])
                else:
                    bloqueado = 1

            elif template['base_calculo'] == 'aio':
                data_base = data_aio
                if data_base:
                    data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                    data_limite = data_obj + datetime.timedelta(days=template['prazo_dias'])
                else:
                    bloqueado = 1

            elif template['base_calculo'] == 'fim_tarefa':
                bloqueado = 1
                data_base = None

            cursor.execute('''
                INSERT INTO obra_checklist
                (obra_id, template_id, descricao, prazo_dias, data_limite, tipo,
                 base_calculo, data_base_calculo, bloqueado, status_notificacao, recorrencia)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (obra_id, template['id'], template['nome'], template['prazo_dias'],
                  data_limite.strftime('%Y-%m-%d') if data_limite else None,
                  template['tipo'], template['base_calculo'], data_base, bloqueado,
                  'pendente', template['recorrencia']))

            template_map[template['id']] = cursor.lastrowid

        cursor.execute('SELECT * FROM checklist_templates WHERE base_calculo = "fim_tarefa" OR depende_template_id IS NOT NULL')
        templates_dependentes = cursor.fetchall()

        for template in templates_dependentes:
            item_id = template_map.get(template['id'])
            if not item_id:
                continue

            depende_template_id = template['depende_template_id']
            if depende_template_id and depende_template_id in template_map:
                depende_item_id = template_map[depende_template_id]

                cursor.execute('''
                    UPDATE obra_checklist
                    SET depende_item_id = ?
                    WHERE id = ?
                ''', (depende_item_id, item_id))

                cursor.execute('SELECT concluido, data_conclusao FROM obra_checklist WHERE id = ?', (depende_item_id,))
                tarefa_dep = cursor.fetchone()

                if tarefa_dep and tarefa_dep['concluido']:
                    data_base = tarefa_dep['data_conclusao']
                    data_obj = datetime.datetime.strptime(data_base, '%Y-%m-%d')
                    data_limite = self._calcular_data_limite(data_obj, template['prazo_dias'], template['nome'])

                    cursor.execute('''
                        UPDATE obra_checklist
                        SET bloqueado = 0, data_limite = ?, data_base_calculo = ?
                        WHERE id = ?
                    ''', (data_limite.strftime('%Y-%m-%d'), data_base, item_id))

    # ========== CRUD CHECKLIST ========== #

    def obter_checklist(self, obra_id: int) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM obra_checklist
            WHERE obra_id = ?
            ORDER BY id
        ''', (obra_id,))
        checklist = [dict(row) for row in cursor.fetchall()]
        conn.close()

        # Reposiciona tarefas de renovação logo abaixo da sua tarefa de origem.
        renovacoes = {t['tarefa_origem_id']: t for t in checklist if t.get('tarefa_origem_id')}
        if not renovacoes:
            return checklist

        ids_renovacao = {t['id'] for t in renovacoes.values()}
        ordered: List[Dict] = []
        for tarefa in checklist:
            if tarefa['id'] in ids_renovacao:
                continue
            ordered.append(tarefa)
            if tarefa['id'] in renovacoes:
                ordered.append(renovacoes[tarefa['id']])
        return ordered

    def obter_item_checklist(self, item_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM obra_checklist WHERE id = ?', (item_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def marcar_item_checklist(self, item_id: int, concluido: bool) -> Optional[str]:
        """Marca/desmarca um item do checklist. Retorna trigger_ui se houver."""
        conn = self.get_connection()
        cursor = conn.cursor()

        trigger_ui = None

        cursor.execute('''
            SELECT ct.trigger_ui, oc.obra_id, oc.descricao
            FROM obra_checklist oc
            JOIN checklist_templates ct ON oc.template_id = ct.id
            WHERE oc.id = ?
        ''', (item_id,))
        row_info = cursor.fetchone()
        obra_id = row_info['obra_id'] if row_info else None
        item_descricao = (row_info['descricao'] or '') if row_info else ''
        if row_info and row_info['trigger_ui']:
            trigger_ui = row_info['trigger_ui']

        if concluido:
            data_conclusao = datetime.datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
                UPDATE obra_checklist
                SET concluido = 1, data_conclusao = ?
                WHERE id = ?
            ''', (data_conclusao, item_id))

            cursor.execute('''
                SELECT id, prazo_dias, descricao FROM obra_checklist
                WHERE depende_item_id = ? AND concluido = 0
            ''', (item_id,))

            dependentes = cursor.fetchall()
            for dep in dependentes:
                data_obj = datetime.datetime.strptime(data_conclusao, '%Y-%m-%d')
                nova_data_limite = self._calcular_data_limite(data_obj, dep['prazo_dias'], dep['descricao'])

                cursor.execute('''
                    UPDATE obra_checklist
                    SET bloqueado = 0, data_limite = ?, data_base_calculo = ?
                    WHERE id = ?
                ''', (nova_data_limite.strftime('%Y-%m-%d'), data_conclusao, dep['id']))
        else:
            cursor.execute('''
                UPDATE obra_checklist
                SET concluido = 0, data_conclusao = NULL
                WHERE id = ?
            ''', (item_id,))

            if obra_id and (item_descricao.startswith('MEDIÇÃO ') or item_descricao.startswith('CONFIRMAÇÃO DE MEDIÇÃO')):
                cursor.execute('''
                    UPDATE obras
                    SET status = 'Em Andamento',
                        status_conclusao_obra = NULL,
                        data_conclusao = NULL
                    WHERE id = ?
                ''', (obra_id,))

            cursor.execute('''
                UPDATE obra_checklist
                SET bloqueado = 1, data_limite = NULL
                WHERE depende_item_id = ? AND concluido = 0
            ''', (item_id,))

            if trigger_ui and obra_id:
                trigger_map = {
                    'data_assinatura': ('data_assinatura', 'assinatura'),
                    'data_aio': ('data_aio', 'aio'),
                }
                if trigger_ui in trigger_map:
                    campo_obra, base_calculo = trigger_map[trigger_ui]

                    cursor.execute(f'UPDATE obras SET {campo_obra} = NULL WHERE id = ?', (obra_id,))

                    cursor.execute('''
                        UPDATE obra_checklist
                        SET bloqueado = 1, data_limite = NULL, data_base_calculo = NULL
                        WHERE obra_id = ? AND base_calculo = ? AND concluido = 0
                    ''', (obra_id, base_calculo))

                    cursor.execute('''
                        SELECT oc.id, ct.trigger_ui
                        FROM obra_checklist oc
                        JOIN checklist_templates ct ON oc.template_id = ct.id
                        WHERE oc.obra_id = ? AND oc.base_calculo = ? AND oc.concluido = 1
                        AND ct.trigger_ui IS NOT NULL
                    ''', (obra_id, base_calculo))

                    tarefas_cascata = cursor.fetchall()
                    for tarefa_cascata in tarefas_cascata:
                        cursor.execute('''
                            UPDATE obra_checklist
                            SET concluido = 0, data_conclusao = NULL
                            WHERE id = ?
                        ''', (tarefa_cascata['id'],))

                        cascata_trigger = tarefa_cascata['trigger_ui']
                        if cascata_trigger in trigger_map:
                            campo_cascata, base_cascata = trigger_map[cascata_trigger]
                            cursor.execute(f'UPDATE obras SET {campo_cascata} = NULL WHERE id = ?', (obra_id,))
                            cursor.execute('''
                                UPDATE obra_checklist
                                SET bloqueado = 1, data_limite = NULL, data_base_calculo = NULL
                                WHERE obra_id = ? AND base_calculo = ? AND concluido = 0
                            ''', (obra_id, base_cascata))

        conn.commit()
        conn.close()
        return trigger_ui

    def obter_tarefas_atrasadas(self) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        hoje = datetime.date.today().strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT oc.*, o.nome_contrato, o.cliente
            FROM obra_checklist oc
            JOIN obras o ON oc.obra_id = o.id
            WHERE oc.concluido = 0 AND oc.data_limite < ?
            ORDER BY oc.data_limite
        ''', (hoje,))
        tarefas = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tarefas

    # ========== Medições Dinâmicas ========== #

    def obter_medicoes_obra(self, obra_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM medicoes_obra WHERE obra_id = ?', (obra_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def criar_medicoes_dinamicas(self, obra_id: int, quantidade: int) -> bool:
        if quantidade is None:
            return False
        quantidade = int(quantidade)
        if quantidade < 1 or quantidade > 12:
            raise ValueError('Quantidade de medições deve ser entre 1 e 12')

        conn = self.get_connection()
        cursor = conn.cursor()

        def _mes_ref(ano: int, mes: int) -> str:
            return f"{ano:04d}-{mes:02d}"

        def _avancar_mes(ano: int, mes: int):
            proximo_mes = mes + 1
            proximo_ano = ano + (proximo_mes - 1) // 12
            proximo_mes = ((proximo_mes - 1) % 12) + 1
            return proximo_ano, proximo_mes

        cursor.execute('''
            DELETE FROM obra_checklist
            WHERE obra_id = ?
              AND descricao IN ('MEDIÇÃO', 'CONFIRMAÇÃO DE MEDIÇÃO')
              AND (mes_referencia IS NULL OR mes_referencia = '')
        ''', (obra_id,))

        cursor.execute('SELECT data_inicio FROM obras WHERE id = ?', (obra_id,))
        row = cursor.fetchone()
        if not row or not row['data_inicio']:
            conn.close()
            raise ValueError('Data de início da obra não preenchida')

        try:
            data_inicio = datetime.datetime.strptime(row['data_inicio'], '%Y-%m-%d').date()
        except Exception:
            conn.close()
            raise ValueError('Formato de data_inicio inválido')

        cursor.execute('SELECT id FROM checklist_templates WHERE nome = ?', ('MEDIÇÃO',))
        t_med = cursor.fetchone()
        cursor.execute('SELECT id FROM checklist_templates WHERE nome = ?', ('CONFIRMAÇÃO DE MEDIÇÃO',))
        t_conf = cursor.fetchone()
        template_med_id = t_med['id'] if t_med else None
        template_conf_id = t_conf['id'] if t_conf else None

        cursor.execute('''
            SELECT id, descricao, concluido, mes_referencia
            FROM obra_checklist
            WHERE obra_id = ?
              AND (
                    descricao LIKE 'MEDIÇÃO %'
                    OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %'
                  )
        ''', (obra_id,))
        tarefas_existentes = cursor.fetchall()

        desejados = set()

        for i in range(quantidade):
            m = data_inicio.month + i
            y = data_inicio.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            mes_referencia = _mes_ref(y, m)
            desejados.add(mes_referencia)

            ano_conf, mes_conf = _avancar_mes(y, m)
            competencia = f"{m:02d}/{y}"
            descr_med = f"MEDIÇÃO {competencia}"
            descr_conf = f"CONFIRMAÇÃO DE MEDIÇÃO {competencia}"
            data_limite_med = datetime.date(y, m, 20)
            data_limite_conf = datetime.date(ano_conf, mes_conf, 10)

            cursor.execute('SELECT id, concluido FROM obra_checklist WHERE obra_id = ? AND descricao = ?', (obra_id, descr_med))
            existente_med = cursor.fetchone()
            if not existente_med:
                cursor.execute('''
                    INSERT INTO obra_checklist
                    (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, base_calculo, data_base_calculo, bloqueado, recorrencia, mes_referencia)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (obra_id, template_med_id or 0, descr_med, 0,
                      data_limite_med.strftime('%Y-%m-%d'), 'B', 'inicio',
                      data_inicio.strftime('%Y-%m-%d'), 0, 'unica', mes_referencia))
            elif not existente_med['concluido']:
                cursor.execute('''
                    UPDATE obra_checklist
                    SET template_id = ?, prazo_dias = ?, data_limite = ?, tipo = ?, base_calculo = ?,
                        data_base_calculo = ?, bloqueado = 0, recorrencia = 'unica', mes_referencia = ?
                    WHERE id = ?
                ''', (template_med_id or 0, 0, data_limite_med.strftime('%Y-%m-%d'), 'B', 'inicio',
                      data_inicio.strftime('%Y-%m-%d'), mes_referencia, existente_med['id']))

            cursor.execute('SELECT id, concluido FROM obra_checklist WHERE obra_id = ? AND descricao = ?', (obra_id, descr_conf))
            existente_conf = cursor.fetchone()
            if not existente_conf:
                cursor.execute('''
                    INSERT INTO obra_checklist
                    (obra_id, template_id, descricao, prazo_dias, data_limite, tipo, base_calculo, data_base_calculo, bloqueado, recorrencia, mes_referencia)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (obra_id, template_conf_id or 0, descr_conf, 0,
                      data_limite_conf.strftime('%Y-%m-%d'), 'A', 'inicio',
                      data_inicio.strftime('%Y-%m-%d'), 0, 'unica', mes_referencia))
            elif not existente_conf['concluido']:
                cursor.execute('''
                    UPDATE obra_checklist
                    SET template_id = ?, prazo_dias = ?, data_limite = ?, tipo = ?, base_calculo = ?,
                        data_base_calculo = ?, bloqueado = 0, recorrencia = 'unica', mes_referencia = ?
                    WHERE id = ?
                ''', (template_conf_id or 0, 0, data_limite_conf.strftime('%Y-%m-%d'), 'A', 'inicio',
                      data_inicio.strftime('%Y-%m-%d'), mes_referencia, existente_conf['id']))

        tarefas_por_mes = {}
        for tarefa in tarefas_existentes:
            mes_ref_tarefa = (tarefa['mes_referencia'] or '').strip()
            if not mes_ref_tarefa:
                continue
            tarefas_por_mes.setdefault(mes_ref_tarefa, []).append(tarefa)

        for mes_ref_tarefa, tarefas_mes in tarefas_por_mes.items():
            if mes_ref_tarefa in desejados:
                continue
            if any(t['concluido'] for t in tarefas_mes):
                continue
            for tarefa in tarefas_mes:
                cursor.execute('DELETE FROM obra_checklist WHERE id = ?', (tarefa['id'],))

        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('SELECT id FROM medicoes_obra WHERE obra_id = ?', (obra_id,))
        registro = cursor.fetchone()
        cursor.execute('SELECT quantidade FROM medicoes_obra WHERE obra_id = ?', (obra_id,))
        prev = cursor.fetchone()
        prev_qtd = int(prev['quantidade']) if prev and prev['quantidade'] is not None else None

        if registro:
            cursor.execute(
                'UPDATE medicoes_obra SET quantidade = ?, data_ultima_alteracao = ?, atualizado_em = ? WHERE obra_id = ?',
                (quantidade, now, now, obra_id))
        else:
            cursor.execute(
                'INSERT INTO medicoes_obra (obra_id, quantidade, data_ultima_alteracao, atualizado_em) VALUES (?, ?, ?, ?)',
                (obra_id, quantidade, now, now))

        cursor.execute('SELECT status_conclusao_obra FROM obras WHERE id = ?', (obra_id,))
        status_row = cursor.fetchone()
        status_atual = (status_row['status_conclusao_obra'] or '').strip() if status_row else ''
        if status_atual and prev_qtd != quantidade:
            cursor.execute(
                "UPDATE obras SET status_conclusao_obra = NULL, data_conclusao = NULL, status = 'Em Andamento' WHERE id = ?",
                (obra_id,))

        conn.commit()
        conn.close()
        return True

    def verificar_todas_medicoes_concluidas(self, obra_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as pendentes
            FROM obra_checklist
            WHERE obra_id = ?
              AND (
                descricao LIKE 'MEDIÇÃO %'
                OR descricao LIKE 'CONFIRMAÇÃO DE MEDIÇÃO %'
              )
              AND concluido = 0
        ''', (obra_id,))
        row = cursor.fetchone()
        conn.close()
        return row['pendentes'] == 0

    def registrar_finalizacao_obra(self, obra_id: int, status_conclusao_obra: str) -> bool:
        status_normalizado = (status_conclusao_obra or '').strip().lower()
        if status_normalizado not in {'sem_pendencias', 'com_pendencias'}:
            raise ValueError('Status de conclusão inválido')
        conn = self.get_connection()
        cursor = conn.cursor()
        agora = datetime.datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            UPDATE obras
            SET status = 'Concluída',
                status_conclusao_obra = ?,
                data_conclusao = ?
            WHERE id = ?
        ''', (status_normalizado, agora, obra_id))
        conn.commit()
        conn.close()
        return True

    # ========== FASE 3 - VALORES MEDIDOS ========== #

    def registrar_valor_medido(self, tarefa_id: int, valor_medido: float, mes_referencia: str = None) -> bool:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT obra_id, descricao, mes_referencia FROM obra_checklist WHERE id = ?', (tarefa_id,))
            tarefa = cursor.fetchone()
            if not tarefa:
                conn.close()
                return False
            obra_id = tarefa['obra_id']
            mes_ref = mes_referencia or (tarefa['mes_referencia'] or '')
            data_medicao = datetime.datetime.now().strftime('%Y-%m-%d')
            cursor.execute('UPDATE obra_checklist SET valor_medido = ? WHERE id = ?', (valor_medido, tarefa_id))
            cursor.execute('DELETE FROM medicoes_valores WHERE tarefa_id = ?', (tarefa_id,))
            cursor.execute('''
                INSERT INTO medicoes_valores
                (obra_id, tarefa_id, valor_medido, data_medicao, mes_referencia)
                VALUES (?, ?, ?, ?, ?)
            ''', (obra_id, tarefa_id, valor_medido, data_medicao, mes_ref))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            log_error(e, "db.checklist_repo", f"Registrar valor medido - Tarefa: {tarefa_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            return False

    def obter_soma_valores_medidos(self, obra_id: int) -> float:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT COALESCE(SUM(valor_medido), 0) as total FROM medicoes_valores WHERE obra_id = ?', (obra_id,))
            result = cursor.fetchone()
            conn.close()
            return float(result['total']) if result else 0.0
        except Exception as e:
            log_error(e, "db.checklist_repo", f"Obter soma valores medidos - Obra: {obra_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            return 0.0

    def calcular_percentual_faturado(self, obra_id: int) -> float:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT total_obra FROM obras WHERE id = ?', (obra_id,))
            obra = cursor.fetchone()
            conn.close()
            if not obra or not obra['total_obra'] or obra['total_obra'] <= 0:
                return 0.0
            total_obra = float(obra['total_obra'])
            soma_valores = self.obter_soma_valores_medidos(obra_id)
            return round((soma_valores / total_obra) * 100, 2)
        except Exception as e:
            log_error(e, "db.checklist_repo", f"Calcular percentual faturado - Obra: {obra_id}")
            return 0.0

    def calcular_total_faturar(self, obra_id: int) -> float:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT total_obra FROM obras WHERE id = ?', (obra_id,))
            obra = cursor.fetchone()
            conn.close()
            if not obra or not obra['total_obra']:
                return 0.0
            total_obra = float(obra['total_obra'])
            soma_valores = self.obter_soma_valores_medidos(obra_id)
            return round(total_obra - soma_valores, 2)
        except Exception as e:
            log_error(e, "db.checklist_repo", f"Calcular total a faturar - Obra: {obra_id}")
            return 0.0

    def obter_tarefa_origem_id(self, tarefa_id: int) -> Optional[int]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT tarefa_origem_id FROM obra_checklist WHERE id = ?', (tarefa_id,))
            row = cursor.fetchone()
            conn.close()
            return row['tarefa_origem_id'] if row and row['tarefa_origem_id'] else None
        except Exception as e:
            log_error(e, "db.checklist_repo", f"Obter tarefa origem id - tarefa: {tarefa_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            return None

    def obter_dados_acesso(self, tarefa_id: int) -> Optional[Dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT data_inicio_acesso, data_fim_acesso FROM obra_checklist WHERE id = ?',
                (tarefa_id,)
            )
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            log_error(e, "db.checklist_repo", f"Obter dados de acesso - tarefa: {tarefa_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            return None

    def salvar_dados_acesso(self, tarefa_id: int, obra_id: int, data_inicio: str, data_fim: str) -> bool:
        import datetime as _dt
        try:
            conn = self.get_connection()
            cursor = conn.cursor()

            cursor.execute(
                'UPDATE obra_checklist SET data_inicio_acesso = ?, data_fim_acesso = ? WHERE id = ?',
                (data_inicio or None, data_fim or None, tarefa_id)
            )

            if data_fim:
                data_fim_date = _dt.date.fromisoformat(data_fim)
                today = _dt.date.today()
                deadline = data_fim_date - _dt.timedelta(days=15)
                if deadline < today:
                    deadline = today

                cursor.execute(
                    "SELECT id FROM checklist_templates WHERE nome = 'RENOVAÇÃO DE SOLICITAÇÃO DE ACESSO'",
                )
                tmpl = cursor.fetchone()
                if not tmpl:
                    log_error(Exception("Template de renovação não encontrado"), "db.checklist_repo", "salvar_dados_acesso")
                    conn.commit()
                    conn.close()
                    return False
                template_id = tmpl['id']

                cursor.execute(
                    'SELECT id FROM obra_checklist WHERE tarefa_origem_id = ?',
                    (tarefa_id,)
                )
                existente = cursor.fetchone()

                if existente:
                    cursor.execute(
                        """UPDATE obra_checklist
                           SET data_limite = ?, status_notificacao = 'pendente',
                               tentativas_reiteracao = 0
                           WHERE id = ?""",
                        (deadline.isoformat(), existente['id'])
                    )
                else:
                    cursor.execute(
                        """INSERT INTO obra_checklist
                           (obra_id, template_id, descricao, prazo_dias, data_limite, tipo,
                            base_calculo, concluido, recorrencia, status_notificacao, tarefa_origem_id)
                           VALUES (?, ?, 'RENOVAÇÃO DE SOLICITAÇÃO DE ACESSO', 0, ?, 'B',
                                   'especifico', 0, 'unica', 'pendente', ?)""",
                        (obra_id, template_id, deadline.isoformat(), tarefa_id)
                    )

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            log_error(e, "db.checklist_repo", f"Salvar dados de acesso - tarefa: {tarefa_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            return False

    def obter_valores_medicoes(self, obra_id: int) -> List[Dict]:
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    mv.id, mv.tarefa_id, mv.valor_medido, mv.data_medicao, mv.mes_referencia,
                    oc.descricao as tarefa_descricao, oc.data_conclusao
                FROM medicoes_valores mv
                LEFT JOIN obra_checklist oc ON mv.tarefa_id = oc.id
                WHERE mv.obra_id = ?
                ORDER BY mv.mes_referencia DESC, mv.data_medicao DESC
            ''', (obra_id,))
            medicoes = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return medicoes
        except Exception as e:
            log_error(e, "db.checklist_repo", f"Obter valores medições - Obra: {obra_id}")
            if 'conn' in locals():
                try:
                    conn.close()
                except Exception:
                    pass
            return []
