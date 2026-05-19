"""
Mixin com dialogs de administração: gerenciar usuários e contratos.
"""

from nicegui import ui
from secrets import randbelow
from services.auth_service import obter_usuario_logado
from db.auth_repo import AuthDatabase


class AdminDialogsMixin:
    def abrir_gerenciar_usuarios(self):
        """Abre diálogo de gerenciamento de usuários."""
        usuario_logado = obter_usuario_logado()
        if not usuario_logado.get('is_admin'):
            self.notificar('⛔ Apenas administradores podem gerenciar usuários.', tipo='negative')
            return

        auth_db = AuthDatabase()

        with ui.dialog() as dialog, ui.card().classes('responsive-dialog').style(
            'padding: 20px; max-height: 90vh; overflow-y: auto;'
        ):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('👥 Gerenciar Usuários').style(
                    'font-size: 22px; font-weight: bold; color: #1976d2;'
                )
                ui.button('✕', on_click=dialog.close).props('flat dense round').style('color: #666;')

            ui.separator().style('margin: 10px 0;')

            lista_container = ui.column().classes('w-full')

            def abrir_vinculos_usuario(user_id: int, user_nome: str, is_admin_usuario: bool = False):
                contratos_disponiveis = self.contratos_db.listar_contratos()
                vinculados = set(contratos_disponiveis) if is_admin_usuario else set(self.contratos_db.listar_contratos_usuario(user_id))

                with ui.dialog() as vinculo_dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px; max-height: 90vh; overflow-y: auto;'):
                    ui.label(f'🔗 Contratos de {user_nome}').style('font-size: 20px; font-weight: bold; color: #1976d2;')
                    ui.label('Selecione os contratos que este usuário poderá visualizar.').style('font-size: 13px; color: #666; margin-bottom: 10px;')
                    if is_admin_usuario:
                        ui.label('Este usuário é administrador e vê todos os contratos automaticamente.').style('font-size: 12px; color: #999; margin-bottom: 10px;')

                    if not contratos_disponiveis:
                        ui.label('⚠️ Nenhum contrato cadastrado em contratos.db').style('color: #f44336; font-size: 13px;')
                    else:
                        checkboxes = {}
                        with ui.column().classes('w-full').style('max-height: 350px; overflow-y: auto; border: 1px solid #e0e0e0; padding: 10px; border-radius: 6px;'):
                            for contrato_nome in contratos_disponiveis:
                                checkboxes[contrato_nome] = ui.checkbox(
                                    contrato_nome,
                                    value=contrato_nome in vinculados,
                                )

                        def salvar_vinculos():
                            selecionados = contratos_disponiveis if is_admin_usuario else [nome for nome, cb in checkboxes.items() if cb.value]
                            ok = self.contratos_db.substituir_vinculos_usuario(user_id, selecionados)
                            if not ok:
                                ui.notification('Erro ao salvar vínculos de contrato.', type='negative', timeout=3)
                                return

                            ui.notification('Vínculos de contratos atualizados.', type='positive', timeout=3)
                            vinculo_dialog.close()
                            renderizar_lista()

                        with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                            ui.button('Cancelar', on_click=vinculo_dialog.close).props('flat').style('color: #666;')
                            ui.button('Salvar Vínculos', on_click=salvar_vinculos).style(
                                'background-color: #1976d2; color: white; font-weight: bold;'
                            )

                vinculo_dialog.open()

            def renderizar_lista():
                lista_container.clear()
                lista_atualizada = auth_db.listar_usuarios()
                contagem_vinculos = self.contratos_db.contar_contratos_por_usuario()
                usuario_logado = obter_usuario_logado()
                total_admins = auth_db.contar_admins()

                with lista_container:
                    if not lista_atualizada:
                        ui.label('Nenhum usuário cadastrado.').style('color: #999;')
                        return

                    for u in lista_atualizada:
                        with ui.card().classes('w-full').style(
                            'padding: 12px 15px; margin-bottom: 8px; background-color: #fafafa;'
                        ):
                            with ui.row().classes('w-full items-center justify-between'):
                                with ui.column().style('gap: 2px;'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label(f'{u["nome"]} {u["sobrenome"]}').style(
                                            'font-weight: bold; font-size: 15px;'
                                        )
                                        if u['is_admin']:
                                            ui.badge('Admin', color='blue').style('font-size: 10px;')
                                    ui.label(u['email']).style('color: #666; font-size: 13px;')
                                    if u['is_admin']:
                                        ui.label('Acesso: todos os contratos').style('color: #999; font-size: 12px;')
                                    else:
                                        total_contratos = contagem_vinculos.get(u['id'], 0)
                                        ui.label(f'Contratos vinculados: {total_contratos}').style('color: #999; font-size: 12px;')

                                    recebe_alerta_critico = bool(u.get('receber_alerta_critico', 1))
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label('Alertas críticos:').style('color: #999; font-size: 12px;')
                                        ui.switch(
                                            value=recebe_alerta_critico,
                                            on_change=lambda e, uid=u['id'], nome=f'{u["nome"]} {u["sobrenome"]}': alternar_alerta_critico(uid, nome, e.value),
                                        ).props('dense').style('transform: scale(0.9);')
                                        ui.label('Recebe' if recebe_alerta_critico else 'Não recebe').style(
                                            'color: #999; font-size: 12px;'
                                        )

                                pode_excluir = (
                                    u['id'] != usuario_logado.get('id')
                                    and not (u['is_admin'] and total_admins <= 1)
                                )

                                user_id = u['id']
                                user_nome = f'{u["nome"]} {u["sobrenome"]}'
                                user_email = u['email']

                                with ui.row().classes('items-center gap-1'):
                                    ui.button(
                                        '🔗',
                                        on_click=lambda uid=user_id, un=user_nome, admin=u['is_admin']: abrir_vinculos_usuario(uid, un, admin)
                                    ).props('flat dense round').style('color: #1976d2;').tooltip('Vincular contratos ao usuário')

                                    if not u['is_admin']:
                                        ui.button(
                                            '⭐',
                                            on_click=lambda uid=user_id, un=user_nome: promover_usuario_admin(uid, un)
                                        ).props('flat dense round').style('color: #ff9800;').tooltip('Promover usuário para administrador')

                                    ui.button(
                                        '🔑',
                                        on_click=lambda uid=user_id, un=user_nome, ue=user_email: redefinir_senha_usuario(uid, un, ue)
                                    ).props('flat dense round').style('color: #1976d2;').tooltip('Redefinir senha do usuário')

                                    if pode_excluir:
                                        ui.button(
                                            '🗑️',
                                            on_click=lambda uid=user_id, un=user_nome: confirmar_exclusao(uid, un)
                                        ).props('flat dense round').style('color: #f44336;').tooltip('Excluir usuário')

            def alternar_alerta_critico(user_id: int, user_nome: str, receber_alerta_critico: bool):
                usuario_logado = obter_usuario_logado()
                if not usuario_logado.get('is_admin'):
                    ui.notification('Apenas administradores podem alterar essa preferência.', type='negative', timeout=3)
                    return

                try:
                    ok = auth_db.atualizar_receber_alerta_critico(user_id, receber_alerta_critico)
                    if ok:
                        renderizar_lista()
                        texto = 'passará a receber' if receber_alerta_critico else 'não receberá mais'
                        ui.notification(f'Usuário "{user_nome}" {texto} alertas críticos.', type='positive', timeout=3)
                    else:
                        ui.notification('Não foi possível atualizar a preferência.', type='negative', timeout=3)
                except Exception:
                    ui.notification('Erro ao atualizar preferência de alertas críticos.', type='negative', timeout=3)

            def promover_usuario_admin(user_id: int, user_nome: str):
                usuario_logado = obter_usuario_logado()
                if not usuario_logado.get('is_admin'):
                    ui.notification('Apenas administradores podem promover usuários.', type='negative', timeout=3)
                    return

                try:
                    promovido = auth_db.promover_para_admin(user_id)
                    if promovido:
                        renderizar_lista()
                        ui.notification(f'Usuário "{user_nome}" promovido para administrador.', type='positive', timeout=3)
                    else:
                        ui.notification(f'"{user_nome}" já é administrador.', type='info', timeout=3)
                except Exception:
                    ui.notification('Erro ao promover usuário.', type='negative', timeout=3)

            def redefinir_senha_usuario(user_id: int, user_nome: str, user_email: str):
                nova_senha = f'{randbelow(1_000_000):06d}'
                ok = auth_db.redefinir_senha(user_id, nova_senha)

                if not ok:
                    ui.notification('Erro ao redefinir senha.', type='negative', timeout=3)
                    return

                with ui.dialog() as senha_dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
                    ui.label('🔑 Senha redefinida com sucesso').style(
                        'font-size: 20px; font-weight: bold; color: #1976d2; margin-bottom: 10px;'
                    )
                    ui.label(f'Usuário: {user_nome}').style('font-size: 14px; color: #666;')
                    ui.label(f'E-mail: {user_email}').style('font-size: 14px; color: #666; margin-bottom: 10px;')

                    ui.label('Nova senha para envio:').style('font-size: 14px; color: #333;')
                    senha_label = ui.input(value=nova_senha).props('readonly outlined dense').classes('w-full')
                    senha_label.style('font-size: 22px; font-weight: bold; color: #1976d2; margin: 8px 0 12px 0;')

                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button(
                            'Copiar senha',
                            on_click=lambda: ui.run_javascript(f'navigator.clipboard.writeText("{nova_senha}")')
                        ).props('flat').style('color: #1976d2;')
                        ui.button('Fechar', on_click=senha_dialog.close).style(
                            'background-color: #1976d2; color: white;'
                        )

                senha_dialog.open()
                ui.notification(f'Senha de "{user_nome}" redefinida.', type='positive', timeout=3)

            def confirmar_exclusao(user_id: int, user_nome: str):
                with ui.dialog() as confirm_dialog, ui.card().style('padding: 25px;'):
                    ui.label(f'Deseja excluir o usuário "{user_nome}"?').style(
                        'font-size: 16px; margin-bottom: 15px;'
                    )
                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button('Cancelar', on_click=confirm_dialog.close).props('flat').style('color: #666;')

                        def executar_exclusao():
                            self.contratos_db.remover_todos_vinculos_usuario(user_id)
                            excluido = auth_db.excluir_usuario(user_id)

                            if not excluido:
                                ui.notification('Erro ao excluir usuário.', type='negative', timeout=3)
                                return

                            ui.notification(f'Usuário "{user_nome}" excluído.', type='warning', timeout=3)
                            confirm_dialog.close()
                            renderizar_lista()

                        ui.button('Excluir', on_click=executar_exclusao).style(
                            'background-color: #f44336; color: white;'
                        )
                confirm_dialog.open()

            def abrir_form_novo_usuario():
                with ui.dialog() as form_dialog, ui.card().classes('responsive-dialog-sm').style(
                    'padding: 20px;'
                ):
                    ui.label('Novo Usuário').style(
                        'font-size: 20px; font-weight: bold; color: #1976d2; margin-bottom: 15px;'
                    )
                    nome_input = ui.input('Nome').props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
                    sobrenome_input = ui.input('Sobrenome').props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
                    email_input = ui.input('E-mail').props('outlined dense').classes('w-full').style('margin-bottom: 8px;')
                    senha_input = ui.input('Senha').props('outlined dense type=password').classes('w-full').style('margin-bottom: 8px;')
                    admin_check = ui.checkbox('Administrador').style('margin-bottom: 10px;')
                    receber_criticos_check = ui.checkbox('Receber alertas críticos').style('margin-bottom: 10px;')
                    receber_criticos_check.value = True
                    erro_label = ui.label('').style('color: #f44336; font-size: 13px; display: none; margin-bottom: 8px;')

                    def salvar_usuario():
                        nome = nome_input.value.strip() if nome_input.value else ''
                        sobrenome = sobrenome_input.value.strip() if sobrenome_input.value else ''
                        email = email_input.value.strip() if email_input.value else ''
                        senha = senha_input.value if senha_input.value else ''

                        if not all([nome, sobrenome, email, senha]):
                            erro_label.set_text('Preencha todos os campos.')
                            erro_label.style('display: block;')
                            return

                        if len(senha) < 4:
                            erro_label.set_text('Senha deve ter pelo menos 4 caracteres.')
                            erro_label.style('display: block;')
                            return

                        ok = auth_db.criar_usuario(
                            nome,
                            sobrenome,
                            email,
                            senha,
                            is_admin=admin_check.value,
                            receber_alerta_critico=receber_criticos_check.value,
                        )
                        if not ok:
                            erro_label.set_text('E-mail já cadastrado.')
                            erro_label.style('display: block;')
                            return

                        form_dialog.close()
                        renderizar_lista()
                        ui.notification(f'Usuário "{nome}" criado!', type='positive', timeout=3)

                    with ui.row().classes('w-full justify-end gap-2'):
                        ui.button('Cancelar', on_click=form_dialog.close).props('flat').style('color: #666;')
                        ui.button('Salvar', on_click=salvar_usuario).style(
                            'background-color: #1976d2; color: white;'
                        )
                form_dialog.open()

            renderizar_lista()

            ui.separator().style('margin: 10px 0;')

            ui.button('➕ Novo Usuário', on_click=abrir_form_novo_usuario).style(
                'background-color: #1976d2; color: white; font-weight: bold;'
            )

        dialog.open()

    def abrir_gerenciar_contratos(self):
        """Abre diálogo de gerenciamento de contratos."""
        usuario_logado = obter_usuario_logado()
        if not usuario_logado.get('is_admin'):
            self.notificar('⛔ Apenas administradores podem gerenciar contratos.', tipo='negative')
            return

        with ui.dialog() as dialog, ui.card().classes('responsive-dialog').style(
            'padding: 20px; max-height: 90vh; overflow-y: auto;'
        ):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('📄 Gerenciar Contratos').style(
                    'font-size: 22px; font-weight: bold; color: #1976d2;'
                )
                ui.button('✕', on_click=dialog.close).props('flat dense round').style('color: #666;')

            ui.separator().style('margin: 10px 0;')
            lista_container = ui.column().classes('w-full')

            def renderizar_lista():
                lista_container.clear()
                contratos = self.contratos_db.listar_contratos()

                with lista_container:
                    if not contratos:
                        ui.label('Nenhum contrato cadastrado.').style('color: #999;')
                        return

                    for contrato_nome in contratos:
                        uso = self._contar_uso_contrato_catalogo(contrato_nome)

                        with ui.card().classes('w-full').style(
                            'padding: 12px 15px; margin-bottom: 8px; background-color: #fafafa;'
                        ):
                            with ui.row().classes('w-full items-center justify-between'):
                                with ui.column().style('gap: 2px;'):
                                    ui.label(contrato_nome).style('font-weight: bold; font-size: 15px;')
                                    ui.label(
                                        f'Vínculos de usuários: {uso["vinculos_usuarios"]} • Obras vinculadas: {uso["obras_cliente"]}'
                                    ).style('color: #999; font-size: 12px;')

                                with ui.row().classes('items-center gap-1'):
                                    ui.button(
                                        '✏️',
                                        on_click=lambda nome=contrato_nome: abrir_form_editar_contrato(nome)
                                    ).props('flat dense round').style('color: #1976d2;').tooltip('Renomear contrato')

                                    ui.button(
                                        '🗑️',
                                        on_click=lambda nome=contrato_nome: confirmar_exclusao_contrato(nome)
                                    ).props('flat dense round').style('color: #f44336;').tooltip('Excluir contrato')

            def abrir_form_novo_contrato():
                with ui.dialog() as form_dialog, ui.card().classes('responsive-dialog-sm').style(
                    'padding: 20px;'
                ):
                    ui.label('Novo Contrato').style(
                        'font-size: 20px; font-weight: bold; color: #1976d2; margin-bottom: 15px;'
                    )

                    nome_input = ui.input('Nome do Contrato').props('outlined dense').classes('w-full')
                    erro_label = ui.label('').style(
                        'color: #f44336; font-size: 13px; display: none; margin-top: 8px;'
                    )

                    def salvar_contrato():
                        ok, mensagem = self._adicionar_contrato_catalogo(nome_input.value)
                        if not ok:
                            erro_label.set_text(f'❌ {mensagem}')
                            erro_label.style('display: block;')
                            return

                        form_dialog.close()
                        renderizar_lista()
                        self.renderizar_obras()
                        ui.notification(f'✅ {mensagem}', type='positive', timeout=3)

                    with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                        ui.button('Cancelar', on_click=form_dialog.close).props('flat').style('color: #666;')
                        ui.button('Salvar', on_click=salvar_contrato).style(
                            'background-color: #1976d2; color: white;'
                        )

                form_dialog.open()

            def abrir_form_editar_contrato(nome_atual: str):
                with ui.dialog() as form_dialog, ui.card().classes('responsive-dialog-sm').style(
                    'padding: 20px;'
                ):
                    ui.label('Renomear Contrato').style(
                        'font-size: 20px; font-weight: bold; color: #1976d2; margin-bottom: 10px;'
                    )
                    ui.label(f'Atual: {nome_atual}').style('font-size: 13px; color: #666; margin-bottom: 10px;')

                    novo_nome_input = ui.input('Novo Nome').props('outlined dense').classes('w-full')
                    novo_nome_input.value = nome_atual
                    erro_label = ui.label('').style(
                        'color: #f44336; font-size: 13px; display: none; margin-top: 8px;'
                    )

                    def salvar_edicao():
                        ok, mensagem = self._editar_contrato_catalogo(nome_atual, novo_nome_input.value)
                        if not ok:
                            erro_label.set_text(f'❌ {mensagem}')
                            erro_label.style('display: block;')
                            return

                        form_dialog.close()
                        renderizar_lista()
                        self.renderizar_obras()
                        ui.notification(f'✅ {mensagem}', type='positive', timeout=3)

                    with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                        ui.button('Cancelar', on_click=form_dialog.close).props('flat').style('color: #666;')
                        ui.button('Salvar', on_click=salvar_edicao).style(
                            'background-color: #1976d2; color: white;'
                        )

                form_dialog.open()

            def confirmar_exclusao_contrato(nome_contrato: str):
                uso = self._contar_uso_contrato_catalogo(nome_contrato)
                contratos_disponiveis = [
                    nome for nome in self.contratos_db.listar_contratos()
                    if nome != nome_contrato
                ]

                with ui.dialog() as confirm_dialog, ui.card().classes('responsive-dialog-sm').style('padding: 20px;'):
                    ui.label(f'Deseja excluir o contrato "{nome_contrato}"?').style(
                        'font-size: 16px; margin-bottom: 8px;'
                    )

                    ui.label(
                        f'Vínculos de usuários: {uso["vinculos_usuarios"]} • Obras vinculadas: {uso["obras_cliente"]}'
                    ).style('font-size: 13px; color: #666; margin-bottom: 10px;')

                    substituto_select = None
                    erro_label = ui.label('').style(
                        'color: #f44336; font-size: 13px; display: none; margin-bottom: 8px;'
                    )

                    if uso['total'] > 0:
                        ui.label(
                            'Este contrato está em uso. Selecione um contrato substituto para migrar referências antes de excluir.'
                        ).style('font-size: 12px; color: #f44336; margin-bottom: 8px;')

                        substituto_select = ui.select(
                            contratos_disponiveis,
                            label='Contrato substituto *',
                        ).classes('w-full').props('outlined dense')

                        if not contratos_disponiveis:
                            ui.label(
                                'Não há outro contrato disponível para substituição. Cadastre outro contrato antes de excluir este.'
                            ).style('font-size: 12px; color: #f44336; margin-top: 8px;')

                    def executar_exclusao():
                        replace_with = ''
                        if uso['total'] > 0:
                            if not contratos_disponiveis:
                                erro_label.set_text('❌ Não há contrato substituto disponível para migração.')
                                erro_label.style('display: block;')
                                return
                            replace_with = (substituto_select.value or '').strip() if substituto_select else ''
                            if not replace_with:
                                erro_label.set_text('❌ Selecione um contrato substituto para prosseguir.')
                                erro_label.style('display: block;')
                                return

                        ok, mensagem = self._remover_contrato_catalogo(nome_contrato, replace_with)
                        if not ok:
                            erro_label.set_text(f'❌ {mensagem}')
                            erro_label.style('display: block;')
                            return

                        confirm_dialog.close()
                        renderizar_lista()
                        self.renderizar_obras()
                        ui.notification(f'✅ {mensagem}', type='positive', timeout=3)

                    with ui.row().classes('w-full justify-end gap-2').style('margin-top: 12px;'):
                        ui.button('Cancelar', on_click=confirm_dialog.close).props('flat').style('color: #666;')
                        ui.button('Excluir', on_click=executar_exclusao).style(
                            'background-color: #f44336; color: white;'
                        )

                confirm_dialog.open()

            renderizar_lista()

            ui.separator().style('margin: 10px 0;')
            ui.button('➕ Novo Contrato', on_click=abrir_form_novo_contrato).style(
                'background-color: #1976d2; color: white; font-weight: bold;'
            )

        dialog.open()
