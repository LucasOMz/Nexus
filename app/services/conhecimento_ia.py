"""Catálogo de navegação usado pelo assistente do Nexus."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TelaNexus = Literal[
    "ativos", "produtos", "movimentacoes", "manutencoes", "scanner", "contagens",
    "financeiro", "contratos", "descarte", "software", "emprestimos", "monitor",
    "seguranca", "relatorios", "calendario", "kanban", "mapa", "impressao",
    "cadastros", "reporte", "avisos", "admin", "admin_usuarios", "admin_plantas",
    "admin_ollama", "admin_agente", "admin_backups", "admin_auditoria",
]


class ConsultaTelas(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telas: list[TelaNexus] = Field(min_length=1, max_length=4)


# Rótulo, instrução e aba administrativa quando necessária.
TELAS = {
    "ativos": ("Ativos", "Escolha o inventário de TI ou Impressoras. Busque por patrimônio, hostname ou número de série. Abra Detalhes para ver a ficha e o inventário coletado."),
    "produtos": ("Consumíveis", "Busque o consumível pelo nome ou SKU. Use as ações do item para ver o histórico, cadastrar entradas e saídas ou registrar a instalação em um ativo."),
    "movimentacoes": ("Transferências", "Consulte transferências e movimentações. Use os filtros da tela para localizar o registro do equipamento."),
    "manutencoes": ("Manutenções", "Registre e acompanhe ordens de manutenção, do chamado à conclusão com laudo."),
    "scanner": ("Leitura", "Use a câmera ou um leitor para identificar um ativo pela etiqueta QR e abrir suas ações."),
    "contagens": ("Contagens", "Crie uma sessão de inventário, leia as etiquetas dos equipamentos e confira as divergências."),
    "financeiro": ("Financeiro", "Consulte custos, depreciação, garantias e o rateio de ativos por departamento."),
    "contratos": ("Contratos", "Cadastre contratos e vincule os equipamentos cobertos. Acompanhe vigência, locação e valores do contrato."),
    "descarte": ("Certificado de descarte", "Cadastre e acompanhe o descarte de equipamentos e emita o certificado."),
    "software": ("Software e licenças", "Consulte os programas coletados no inventário, licenças, atribuições e conformidade."),
    "emprestimos": ("Empréstimos", "Reserve equipamentos, faça a entrega com checklist ou termo e registre a devolução."),
    "monitor": ("Monitor de impressoras", "Selecione a planta e abra a impressora para consultar o contador e os suprimentos. A comunicação e os níveis dependem do SNMP."),
    "seguranca": ("Segurança da conta", "Gerencie a sua verificação em duas etapas e os códigos de recuperação."),
    "relatorios": ("Relatórios", "Abra os indicadores e escolha os filtros. Use os relatórios de parque para conferir os equipamentos e exportar dados."),
    "calendario": ("Calendário", "Acompanhe reservas, entregas e devoluções de empréstimos no calendário."),
    "kanban": ("Kanban", "Organize atividades em colunas e acompanhe responsáveis e prazos."),
    "mapa": ("Mapa 3D", "Escolha a planta e abra a planta baixa ou a vista 3D para localizar equipamentos. Clique em um equipamento para ver seus detalhes."),
    "impressao": ("Impressão", "Gerencie os dispositivos de impressão da sua planta e faça o teste de impressão de etiquetas."),
    "cadastros": ("Cadastros", "Gerencie departamentos, categorias, localizações e fornecedores usados nos formulários do Nexus."),
    "reporte": ("Reporte de Erro", "Registre um problema com os passos para reproduzi-lo e as evidências disponíveis."),
    "avisos": ("Avisos", "Consulte as notificações recebidas pela sua conta."),
    "admin": ("Administração", "Use os grupos e a busca para abrir a área administrativa que deseja configurar."),
    "admin_usuarios": ("Usuários e permissões", "Em Administração, abra Usuários & Permissões. Para redefinir o MFA, abra Editar usuário e expanda Segurança da conta (MFA).", "usuarios"),
    "admin_plantas": ("Plantas e localidades", "Em Administração, abra Plantas. Edite a unidade para associar os códigos de localidade usados nos hostnames do agente.", "plantas"),
    "admin_ollama": ("Configuração do Ollama", "Informe o endereço do servidor Ollama, teste a conexão, selecione um modelo e salve.", "ollama"),
    "admin_agente": ("Agente Nexus", "Gerencie a instalação do agente, os registros pendentes e as opções de coleta.", "agente"),
    "admin_backups": ("Backups", "Consulte os backups e as opções administrativas de criação ou restauração.", "backups"),
    "admin_auditoria": ("Logs de auditoria", "Use os filtros para conferir as alterações registradas e os responsáveis.", "auditoria"),
}


def link_nexus(tela: str, *, rotulo: str | None = None, consulta: str = "", dominio: str | None = None) -> dict:
    entrada = TELAS[tela]
    modulo = "admin" if tela.startswith("admin") else tela
    sufixo = f"?aba={entrada[2]}" if len(entrada) == 3 else consulta
    return {"rotulo": rotulo or entrada[0], "rota": f"#/{modulo}{sufixo}", "modulo": modulo, "dominio": dominio}


def orientar(consulta: ConsultaTelas, modulos: frozenset[str]) -> dict:
    telas = [(TELAS[tela], link_nexus(tela)) for tela in dict.fromkeys(consulta.telas)]
    disponiveis = [(entrada, link) for entrada, link in telas if link["modulo"] in modulos]
    if not disponiveis:
        return {"tipo": "informacoes", "resumo": "Sua conta não tem acesso às telas pedidas.", "blocos": [], "links": []}
    return {
        "tipo": "informacoes",
        "resumo": f"Abra {disponiveis[0][0][0]} para começar." if len(disponiveis) == 1 else "Encontrei estas telas no Nexus.",
        "blocos": [{"titulo": entrada[0], "linhas": [["Como usar", entrada[1]]]} for entrada, _ in disponiveis],
        "links": [link for _, link in disponiveis],
        "modulos_dados": sorted({link["modulo"] for _, link in disponiveis}),
    }
