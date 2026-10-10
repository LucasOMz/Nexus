"""Modelos do núcleo compartilhado (comuns aos dois domínios)."""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.contrato import Contrato
    from app.models.impressora import AtivoImpressora, SuprimentoImpressora
    from app.models.ti import AtivoTI

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    BaseModel,
    CreatedAtMixin,
    CreatedAtModel,
    sa_enum,
)
from app.models.enums import (
    Dominio,
    FormaAquisicao,
    PapelUsuario,
    StatusAtivo,
    StatusManut,
    TipoItem,
    TipoMov,
)


class Planta(BaseModel, Base):
    """Planta / localidade da empresa.

    Cada planta é um **inventário próprio**: os ativos, etiquetas e o restante
    dos cadastros carregam `planta_id`, e o usuário só enxerga a planta dele.

    `sigla` é o que aparece na coluna "Planta" da tela de Ativos — mantenha
    curta (3 a 5 letras), ex.: `MAT`, `CPS`, `REC`.
    """

    __tablename__ = "plantas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    sigla: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(18))
    endereco: Mapped[str | None] = mapped_column(String(200))
    cidade: Mapped[str | None] = mapped_column(String(120))
    uf: Mapped[str | None] = mapped_column(String(2))
    observacoes: Mapped[str | None] = mapped_column(Text)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Departamento(BaseModel, Base):
    __tablename__ = "departamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    sigla: Mapped[str | None] = mapped_column(String(20))

    usuarios: Mapped[list[Usuario]] = relationship(back_populates="departamento")


class Localizacao(BaseModel, Base):
    __tablename__ = "localizacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)


class Fornecedor(BaseModel, Base):
    __tablename__ = "fornecedores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    cnpj: Mapped[str | None] = mapped_column(String(18))
    contato: Mapped[str | None] = mapped_column(String(120))
    telefone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(160))


class Categoria(BaseModel, Base):
    __tablename__ = "categorias"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    dominio: Mapped[Dominio | None] = mapped_column(sa_enum(Dominio), nullable=True)  # NULL = comum
    descricao: Mapped[str | None] = mapped_column(Text)


class Usuario(BaseModel, Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    papel: Mapped[PapelUsuario] = mapped_column(sa_enum(PapelUsuario), default=PapelUsuario.LEITOR, nullable=False)
    departamento_id: Mapped[int | None] = mapped_column(ForeignKey("departamentos.id"))
    # Planta à qual o usuário pertence. Tudo que ele cria/edita fica nesta
    # planta. NULL = acesso a TODAS (usado pelos administradores).
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)
    planta: Mapped[Planta | None] = relationship(lazy="joined")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Origem do login: 'local' (senha no sistema) ou 'ad' (autentica no AD).
    # O root/admin é sempre 'local' e não depende do grupo do AD.
    origem: Mapped[str] = mapped_column(String(10), default="local", nullable=False)
    # Usuário de logon no AD (`sAMAccountName`), quando a conta é do diretório.
    # Fica separado do e-mail porque costuma ser diferente dele — o login é
    # `joao.silva` e o e-mail, `joao.silva@empresa.com`. A busca no login
    # procura nos dois campos.
    login_ad: Mapped[str | None] = mapped_column(String(120), index=True)
    # Módulos que o usuário marcou como favoritos na barra lateral (JSON).
    # Fica no banco, e não no navegador, para seguir a pessoa em qualquer
    # computador em que ela entrar.
    barra_favoritos: Mapped[str | None] = mapped_column(Text)
    # A ordem da lista INTEIRA da gaveta (JSON). É separada dos favoritos de
    # propósito: quem reordena mexe em todas as linhas, não só nas marcadas.
    barra_ordem: Mapped[str | None] = mapped_column(Text)
    # Permissões granulares por usuário (JSON). NULL = derivado do papel.
    # Estrutura: {"inventarios": [...], "modulos": [...], "pode_escrever": bool, "pode_excluir": bool}
    permissoes: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- MFA (segunda etapa) ----------------------------------------------
    # Segredo TOTP em base32, gravado só DEPOIS que a pessoa confirma um
    # código. Guardar antes deixaria um segredo pendente que ninguém usa.
    mfa_segredo: Mapped[str | None] = mapped_column(String(64))
    mfa_ativo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_ativado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Códigos de recuperação (JSON, lista de hashes): uso único, para quando o
    # celular é perdido. Sem eles, a saída seria desligar o MFA.
    mfa_recuperacao: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # --- Primeiro acesso ---------------------------------------------------
    # Senha criada pelo administrador e entregue ao técnico. Enquanto for
    # verdadeiro, o sistema exige a troca antes de liberar qualquer coisa —
    # senha que o admin conhece não é senha da pessoa.
    # Tema de interface escolhido. Fica na CONTA (e nao so no navegador)
    # para acompanhar a pessoa: trocar de computador nao deveria
    # obrigar a reconfigurar a tela.
    tema: Mapped[str | None] = mapped_column(String(20))
    # Cor de destaque — o SEGUNDO eixo visual, independente do claro/escuro.
    paleta: Mapped[str | None] = mapped_column(String(20))
    # Cor de fundo — terceiro eixo, independente do destaque.
    fundo: Mapped[str | None] = mapped_column(String(20))

    senha_temporaria: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Cadastro do MFA exigido no primeiro acesso. Vale para conta nova (local
    # ou AD): quem entra pela primeira vez precisa registrar a segunda etapa.
    mfa_obrigatorio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    primeiro_acesso_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    departamento: Mapped[Departamento | None] = relationship(back_populates="usuarios")

    @property
    def permissoes_efetivas(self) -> dict:
        """Permissões calculadas (papel + customizações) — usada na API."""
        from app.core.permissoes import permissoes_efetivas

        return permissoes_efetivas(self)

    @property
    def is_admin(self) -> bool:
        papel = getattr(self.papel, "value", self.papel)
        return papel == "admin"

    @property
    def planta_sigla(self) -> str | None:
        """Sigla da planta do usuário (None = acesso a todas)."""
        planta = getattr(self, "planta", None)
        return planta.sigla if planta is not None else None


class Transferencia(CreatedAtModel, Base):
    """Transferência de um ativo entre plantas, com dupla aprovação.

    Fluxo: o técnico da planta de origem solicita → **aprovação de quem vai
    receber** (técnicos da planta de destino) → **aprovação do administrador**
    → o ativo muda de planta.

    Qualquer pessoa autorizada da planta de destino pode aprovar (não precisa
    ser uma pessoa específica) — o primeiro que decidir move o processo.
    """

    __tablename__ = "transferencias"

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False, index=True)
    ativo: Mapped[Ativo] = relationship(foreign_keys=[ativo_id])

    planta_origem_id: Mapped[int] = mapped_column(ForeignKey("plantas.id"), nullable=False, index=True)
    planta_origem: Mapped[Planta | None] = relationship(foreign_keys=[planta_origem_id])
    planta_destino_id: Mapped[int] = mapped_column(ForeignKey("plantas.id"), nullable=False, index=True)
    planta_destino: Mapped[Planta | None] = relationship(foreign_keys=[planta_destino_id])

    # emprestimo | transferencia | outro
    motivo: Mapped[str] = mapped_column(String(30), nullable=False)
    # Preenchido quando o motivo é "outro" (e opcional nos demais).
    motivo_detalhe: Mapped[str | None] = mapped_column(Text)
    observacoes: Mapped[str | None] = mapped_column(Text)

    solicitado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    solicitado_por: Mapped[Usuario | None] = relationship(foreign_keys=[solicitado_por_id])

    # aguardando_destino | aguardando_admin | aprovada | recusada | cancelada
    status: Mapped[str] = mapped_column(String(30), default="aguardando_destino", nullable=False, index=True)

    aprovado_destino_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    aprovado_destino_por: Mapped[Usuario | None] = relationship(foreign_keys=[aprovado_destino_por_id])
    aprovado_destino_em: Mapped[datetime | None] = mapped_column(DateTime)

    aprovado_admin_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    aprovado_admin_por: Mapped[Usuario | None] = relationship(foreign_keys=[aprovado_admin_por_id])
    aprovado_admin_em: Mapped[datetime | None] = mapped_column(DateTime)

    recusado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    recusado_por: Mapped[Usuario | None] = relationship(foreign_keys=[recusado_por_id])
    recusado_em: Mapped[datetime | None] = mapped_column(DateTime)
    motivo_recusa: Mapped[str | None] = mapped_column(Text)


class ReporteErro(CreatedAtModel, Base):
    """Reporte de erro enviado por qualquer usuário.

    Recurso **temporário**: existe para acompanhar a fase de implantação e será
    desativado (`REPORTE_ERRO_ATIVO=false` no `.env`). A listagem é restrita ao
    administrador; qualquer usuário autenticado pode enviar.
    """

    __tablename__ = "reportes_erro"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False, index=True)
    usuario: Mapped[Usuario | None] = relationship(foreign_keys=[usuario_id])
    # Guardado no momento do envio: o relato é sobre a planta de quem reportou.
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)
    planta: Mapped[Planta | None] = relationship(foreign_keys=[planta_id])

    titulo: Mapped[str] = mapped_column(String(200), nullable=False)
    descricao: Mapped[str] = mapped_column(Text, nullable=False)
    # Print opcional, salvo em media/reportes.
    imagem: Mapped[str | None] = mapped_column(String(300))
    mime_type: Mapped[str | None] = mapped_column(String(80))
    # A tela em que o erro aconteceu, para facilitar a reprodução.
    tela: Mapped[str | None] = mapped_column(String(120))
    # aberto | em_analise | resolvido | descartado
    status: Mapped[str] = mapped_column(String(20), default="aberto", nullable=False, index=True)
    observacao_admin: Mapped[str | None] = mapped_column(Text)

    @property
    def usuario_nome(self) -> str | None:
        u = getattr(self, "usuario", None)
        return u.nome if u is not None else None

    @property
    def usuario_email(self) -> str | None:
        u = getattr(self, "usuario", None)
        return u.email if u is not None else None

    @property
    def planta_sigla(self) -> str | None:
        p = getattr(self, "planta", None)
        return p.sigla if p is not None else None


class Produto(BaseModel, Base):
    """Consumíveis (toners, cabos, etc.) — extensível a qualquer item de estoque."""

    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"))
    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedores.id"))
    dominio: Mapped[Dominio] = mapped_column(sa_enum(Dominio), nullable=False)
    tipo_item: Mapped[TipoItem] = mapped_column(sa_enum(TipoItem), default=TipoItem.CONSUMIVEL, nullable=False)
    unidade: Mapped[str] = mapped_column(String(20), default="un")
    estoque_minimo: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preco_unitario: Mapped[float | None] = mapped_column(Numeric(12, 2))

    categoria: Mapped[Categoria | None] = relationship()
    fornecedor: Mapped[Fornecedor | None] = relationship()


class Ativo(BaseModel, Base):
    """Ativo patrimonial — núcleo comum. Extensões TI/Impressora são 1:1."""

    __tablename__ = "ativos"

    # Índices COMPOSTOS — medidos com 50 mil ativos.
    #
    # Praticamente toda consulta filtra `deleted_at IS NULL` + `dominio`, e os
    # relatórios ainda agrupam por `status`. Com índices de coluna única o banco
    # ainda visitava a tabela linha a linha; estes permitem resolver a consulta
    # só pelo índice.
    __table_args__ = (
        Index("ix_ativos_dominio_deleted_status", "dominio", "deleted_at", "status"),
        Index("ix_ativos_planta_deleted", "planta_id", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Planta dona do ativo. Todo cadastro e toda consulta passam por ela.
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)
    planta: Mapped[Planta | None] = relationship(lazy="joined")

    @property
    def planta_sigla(self) -> str | None:
        """Sigla da planta dona do ativo (usada na lista)."""
        planta = getattr(self, "planta", None)
        return planta.sigla if planta is not None else None

    @property
    def hostname(self) -> str | None:
        """Nome de rede do ativo, venha ele de TI ou de impressora.

        Existe para a tela não precisar saber o domínio: o hostname mora na
        ficha técnica (`AtivoTI` ou `AtivoImpressora`), e quem busca digita
        "NTAT" sem pensar em qual das duas está preenchida.

        Tem que virar `selectinload(Ativo.ti/impressora)` na consulta — sem
        isso, cada linha da lista dispara duas consultas (N+1).
        """
        for ficha in (getattr(self, "ti", None), getattr(self, "impressora", None)):
            nome = (getattr(ficha, "hostname", None) or "").strip() if ficha else ""
            if nome:
                return nome
        return None

    dominio: Mapped[Dominio] = mapped_column(sa_enum(Dominio), nullable=False, index=True)
    tipo_item: Mapped[TipoItem] = mapped_column(sa_enum(TipoItem), default=TipoItem.ATIVO, nullable=False)
    patrimonio: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    numero_serie: Mapped[str | None] = mapped_column(String(160))
    modelo: Mapped[str | None] = mapped_column(String(160))
    marca: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[StatusAtivo] = mapped_column(sa_enum(StatusAtivo), default=StatusAtivo.ESTOQUE, nullable=False, index=True)
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"), index=True)
    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedores.id"), index=True)
    localizacao_id: Mapped[int | None] = mapped_column(ForeignKey("localizacoes.id"), index=True)
    departamento_id: Mapped[int | None] = mapped_column(ForeignKey("departamentos.id"), index=True)
    data_aquisicao: Mapped[date | None] = mapped_column(Date)
    data_garantia: Mapped[date | None] = mapped_column(Date, index=True)
    # `valor` só significa algo quando o ativo é COMPRADO — é o preço pago.
    # Num locado ele fica nulo: não houve compra, e preenchê-lo com "o que
    # custaria" inflaria o patrimônio com bem que não é da empresa.
    valor: Mapped[float | None] = mapped_column(Numeric(14, 2))

    # --- Como o equipamento chegou ao parque ------------------------------
    # Padrão COMPRADO: todo ativo cadastrado antes deste campo existir foi
    # tratado como comprado, e assim continua correto sem migrar dado.
    forma_aquisicao: Mapped[FormaAquisicao] = mapped_column(
        sa_enum(FormaAquisicao), default=FormaAquisicao.COMPRADO, nullable=False, index=True
    )
    # Contrato do qual o ativo faz parte (locação/comodato/compra em lote).
    contrato_id: Mapped[int | None] = mapped_column(ForeignKey("contratos.id"), index=True)
    # Preço de compra ao fim da locação. Preenchido desde o início quando o
    # contrato já diz quanto custa — é o que permite planejar o buyout.
    valor_residual: Mapped[float | None] = mapped_column(Numeric(14, 2))
    observacoes: Mapped[str | None] = mapped_column(Text)
    qr_payload: Mapped[str | None] = mapped_column(Text)
    # Foto principal do ativo, escolhida no Banco de Fotos (estilo Zabbix).
    foto_id: Mapped[int | None] = mapped_column(ForeignKey("imagens.id"))

    # --- Empréstimo -------------------------------------------------------
    # Preenchido quando o ativo sai emprestado e limpo na devolução. O
    # `numero_chamado` é o registro do ticket que autorizou a saída.
    numero_chamado: Mapped[str | None] = mapped_column(String(60), index=True)
    emprestado_em: Mapped[date | None] = mapped_column(Date)
    devolucao_prevista: Mapped[date | None] = mapped_column(Date, index=True)
    emprestado_para_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    emprestado_para: Mapped[Usuario | None] = relationship(foreign_keys=[emprestado_para_id])

    @property
    def emprestado(self) -> bool:
        """Há um empréstimo em aberto?"""
        return self.status == StatusAtivo.EMPRESTADO

    @property
    def emprestimo_atrasado(self) -> bool:
        """Emprestado e com a devolução prevista já vencida."""
        if not self.emprestado or self.devolucao_prevista is None:
            return False
        from datetime import date as _date

        return self.devolucao_prevista < _date.today()

    @property
    def emprestado_para_nome(self) -> str | None:
        usuario = getattr(self, "emprestado_para", None)
        return usuario.nome if usuario is not None else None

    categoria: Mapped[Categoria | None] = relationship()
    fornecedor: Mapped[Fornecedor | None] = relationship()
    localizacao: Mapped[Localizacao | None] = relationship()
    departamento: Mapped[Departamento | None] = relationship()
    foto: Mapped["Imagem | None"] = relationship(foreign_keys=[foto_id])

    ti: Mapped[AtivoTI | None] = relationship(back_populates="ativo", cascade="all, delete-orphan", uselist=False)
    impressora: Mapped[AtivoImpressora | None] = relationship(
        back_populates="ativo", cascade="all, delete-orphan", uselist=False
    )
    # Sem `cascade`: o contrato existe por si. Apagar um ativo não pode
    # apagar o contrato que cobre outros cinquenta.
    contrato: Mapped[Contrato | None] = relationship(back_populates="ativos")
    suprimentos: Mapped[list[SuprimentoImpressora]] = relationship(
        back_populates="ativo", cascade="all, delete-orphan"
    )
    manutencoes: Mapped[list[Manutencao]] = relationship(back_populates="ativo")
    # `foreign_keys` explícito: a movimentação passou a ter DOIS caminhos até
    # `ativos` (o ativo movimentado e o equipamento que recebeu o consumível).
    # Sem isto, o SQLAlchemy não sabe qual usar e recusa o mapeamento.
    movimentacoes: Mapped[list[Movimentacao]] = relationship(
        back_populates="ativo", foreign_keys="Movimentacao.ativo_id"
    )


class Movimentacao(BaseModel, Base):
    """Histórico de movimentações de ativos e consumíveis."""

    __tablename__ = "movimentacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[TipoMov] = mapped_column(sa_enum(TipoMov), nullable=False)
    ativo_id: Mapped[int | None] = mapped_column(ForeignKey("ativos.id"), index=True)
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produtos.id"), index=True)
    quantidade: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    origem_localizacao_id: Mapped[int | None] = mapped_column(ForeignKey("localizacoes.id"))
    destino_localizacao_id: Mapped[int | None] = mapped_column(ForeignKey("localizacoes.id"))
    origem_usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    destino_usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    data_mov: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    # --- Finalidade da SAÍDA de consumível --------------------------------
    # Numa entrada não se aplica. Numa saída, diz para onde foi:
    #   descarte   → material descartado
    #   instalacao → consumido na manutenção de um equipamento
    finalidade: Mapped[str | None] = mapped_column(String(20))
    # Qual equipamento recebeu o consumível (só quando finalidade=instalacao).
    ativo_instalado_id: Mapped[int | None] = mapped_column(ForeignKey("ativos.id"), index=True)
    ativo_instalado: Mapped[Ativo | None] = relationship(foreign_keys=[ativo_instalado_id])

    ativo: Mapped[Ativo | None] = relationship(back_populates="movimentacoes", foreign_keys=[ativo_id])
    produto: Mapped[Produto | None] = relationship()
    usuario: Mapped[Usuario | None] = relationship(foreign_keys=[usuario_id])

    # --- Nomes para o histórico -------------------------------------------
    # O histórico é lido por gente: mostrar "usuário 3" e "produto 7" não diz
    # nada. Estas propriedades são lidas pelo schema (from_attributes).
    @property
    def usuario_nome(self) -> str | None:
        u = getattr(self, "usuario", None)
        return u.nome if u is not None else None

    @property
    def produto_nome(self) -> str | None:
        p = getattr(self, "produto", None)
        return p.nome if p is not None else None

    @property
    def produto_sku(self) -> str | None:
        p = getattr(self, "produto", None)
        return p.sku if p is not None else None

    @property
    def ativo_patrimonio(self) -> str | None:
        a = getattr(self, "ativo", None)
        return a.patrimonio if a is not None else None

    @property
    def ativo_instalado_patrimonio(self) -> str | None:
        """Equipamento que recebeu o consumível (saída por instalação)."""
        a = getattr(self, "ativo_instalado", None)
        return a.patrimonio if a is not None else None

    @property
    def ativo_instalado_hostname(self) -> str | None:
        """Hostname do equipamento — é por ele que a máquina é conhecida.

        O patrimônio sozinho não diz muito a quem lê o histórico no dia a dia;
        o nome de rede, sim.
        """
        a = getattr(self, "ativo_instalado", None)
        if a is None:
            return None
        ficha = getattr(a, "ti", None)
        return getattr(ficha, "hostname", None) if ficha is not None else None

    @property
    def finalidade_rotulo(self) -> str | None:
        return {"descarte": "Descarte", "instalacao": "Instalação"}.get(self.finalidade or "")


class Manutencao(BaseModel, Base):
    __tablename__ = "manutencoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False, index=True)
    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedores.id"))
    status: Mapped[StatusManut] = mapped_column(sa_enum(StatusManut), default=StatusManut.ABERTA, nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    custo: Mapped[float | None] = mapped_column(Numeric(14, 2))
    data_abertura: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    data_conclusao: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tecnico: Mapped[str | None] = mapped_column(String(160))
    observacoes: Mapped[str | None] = mapped_column(Text)
    # Quem CONCLUIU a ordem — vem do usuário logado, não é digitado.
    # Guardado separado de `tecnico`: o técnico pode ser terceirizado, e quem
    # fecha a ordem no sistema é quem responde por ela.
    concluido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    # Comentário obrigatório ao concluir (o que foi feito / laudo).
    # Separado de `observacoes` para não sobrescrever o que já estava lá.
    comentario_conclusao: Mapped[str | None] = mapped_column(Text)

    ativo: Mapped[Ativo] = relationship(back_populates="manutencoes")
    fornecedor: Mapped[Fornecedor | None] = relationship()
    concluido_por: Mapped[Usuario | None] = relationship(foreign_keys=[concluido_por_id])

    @property
    def concluido_por_nome(self) -> str | None:
        """Nome de quem concluiu (preenchido pelo sistema ao fechar a ordem)."""
        usuario = getattr(self, "concluido_por", None)
        return usuario.nome if usuario is not None else None


class Termo(BaseModel, Base):
    """Termo de Responsabilidade — integridade garantida por hash SHA-256."""

    __tablename__ = "termos"

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data_assinatura: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    pdf_path: Mapped[str | None] = mapped_column(String(500))
    observacoes: Mapped[str | None] = mapped_column(Text)

    ativo: Mapped[Ativo] = relationship()
    usuario: Mapped[Usuario] = relationship()


class Anexo(CreatedAtModel, Base):
    __tablename__ = "anexos"

    id: Mapped[int] = mapped_column(primary_key=True)
    entidade: Mapped[str] = mapped_column(String(40), nullable=False)
    entidade_id: Mapped[int] = mapped_column(Integer, nullable=False)
    nome_arquivo: Mapped[str] = mapped_column(String(255), nullable=False)
    caminho: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    tamanho: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    usuario: Mapped[Usuario | None] = relationship()


class FiltroSalvo(BaseModel, Base):
    """Filtros de relatório salvos por usuário."""

    __tablename__ = "filtros_salvos"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    filtros: Mapped[dict] = mapped_column(JSON, default=dict)

    usuario: Mapped[Usuario] = relationship()


class LogAuditoria(CreatedAtMixin, Base):
    """Log de auditoria append-only (sem soft delete de propósito)."""

    __tablename__ = "logs_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    acao: Mapped[str] = mapped_column(String(40), nullable=False)
    entidade: Mapped[str] = mapped_column(String(40), nullable=False)
    entidade_id: Mapped[int | None] = mapped_column(Integer, index=True)
    ip: Mapped[str | None] = mapped_column(String(45))
    diff: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    usuario: Mapped[Usuario | None] = relationship()


class Imagem(BaseModel, Base):
    """Banco de Fotos (estilo Zabbix): imagens reutilizáveis atribuíveis a ativos."""

    __tablename__ = "imagens"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(String(200))  # ex.: "notebook,dell"
    dominio: Mapped[Dominio | None] = mapped_column(sa_enum(Dominio), nullable=True)  # NULL = comum
    caminho: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    tamanho: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    usuario: Mapped[Usuario | None] = relationship()


class DispositivoImpressao(BaseModel, Base):
    """Destino de impressão cadastrável (fila compartilhada Windows, agente ou CUPS).

    Três formas de imprimir, sem precisar de um Raspberry:

    1. **Fila compartilhada (Windows)** — `tipo="compartilhamento"` e
       `compartilhamento = "\\\\DTAT7777\\SATO"`. O próprio servidor onde a API
       roda grava os bytes crus (ZPL/TSPL) na fila; o spooler do Windows entrega
       à impressora. Exige a API rodando **no Windows**, com a impressora
       compartilhada na máquina de origem.
    2. **Agente** — `tipo="agente"` e `agente_url`/`hostname`. Um agente HTTP
       (Raspberry Pi) recebe o trabalho e repassa à impressora.
    3. **CUPS** — `tipo="cups"` e `fila_cups`. Para servidores Linux.

    Cada planta cadastra a **sua** impressora. O técnico da planta gerencia
    apenas a dele; as etiquetas (templates) são padronizadas pelo administrador
    e valem para todas.

    Exemplo (Windows com impressora compartilhada):
        nome = "SATO da expedição"
        tipo = "compartilhamento"
        compartilhamento = "\\\\DTAT7777\\SATO"
        formato = "zpl"
    """

    __tablename__ = "dispositivos_impressao"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Planta dona da impressora. A impressão de cada planta sai na sua.
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)
    planta: Mapped[Planta | None] = relationship(lazy="joined")
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), default="agente", nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(160))
    compartilhamento: Mapped[str | None] = mapped_column(String(300))  # \\RTAT0001\sip
    agente_url: Mapped[str | None] = mapped_column(String(300))        # http://RTAT0001:9100
    fila_cups: Mapped[str | None] = mapped_column(String(160))         # fila no CUPS
    formato: Mapped[str] = mapped_column(String(10), default="zpl")    # zpl | tspl | pdf
    dominio: Mapped[Dominio | None] = mapped_column(sa_enum(Dominio), nullable=True)
    padrao: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)
    # Template de etiqueta deste dispositivo (NULL = usa o padrão).
    template_id: Mapped[int | None] = mapped_column(ForeignKey("templates_etiqueta.id"))

    @property
    def planta_sigla(self) -> str | None:
        """Sigla da planta dona da impressora (usada nas listas)."""
        planta = getattr(self, "planta", None)
        return planta.sigla if planta is not None else None


class TemplateEtiqueta(BaseModel, Base):
    """Template de etiqueta — layout configurável pelo administrador.

    A configuração fica em JSON para ser flexível (campos exibidos, tamanhos,
    alinhamento, DPI, fonte, etc.). Ver `app/services/label_layout.py`.
    """

    __tablename__ = "templates_etiqueta"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    # Largura/altura em mm e DPI da impressora (203 / 300...).
    largura_mm: Mapped[float] = mapped_column(Numeric(6, 2), default=100.0, nullable=False)
    altura_mm: Mapped[float] = mapped_column(Numeric(6, 2), default=50.0, nullable=False)
    dpi: Mapped[int] = mapped_column(Integer, default=203, nullable=False)
    dominio: Mapped[Dominio | None] = mapped_column(sa_enum(Dominio), nullable=True)
    padrao: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class ConfiguracaoSistema(BaseModel, Base):
    """Configuração global editável pela tela de Administração (linha única, id=1).

    Hoje guarda a autenticação via LDAP/AD. A senha da conta de serviço é
    gravada CIFRADA (ver `app/core/cripto.py`).
    """

    __tablename__ = "configuracoes"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Autenticação LDAP/AD ---
    ldap_ativo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ldap_servidor: Mapped[str | None] = mapped_column(String(300))
    ldap_porta: Mapped[int] = mapped_column(Integer, default=636, nullable=False)
    ldap_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ldap_base_dn: Mapped[str | None] = mapped_column(String(300))
    ldap_bind_dn: Mapped[str | None] = mapped_column(String(300))
    ldap_bind_senha: Mapped[str | None] = mapped_column(String(500))  # cifrada
    ldap_filtro_usuario: Mapped[str] = mapped_column(
        String(300), default="(sAMAccountName={usuario})", nullable=False
    )
    ldap_grupo_acesso: Mapped[str | None] = mapped_column(String(300))  # YM_ESTOQUE_TI
    ldap_grupo_admin: Mapped[str | None] = mapped_column(String(300))
    ldap_provisionar: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ldap_grupos_aninhados: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ldap_ignorar_certificado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ldap_admin_por_cargo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Última vez que a conexão foi testada com sucesso.
    ldap_ultimo_teste_ok: Mapped[str | None] = mapped_column(String(40))
    ldap_ultimo_teste_msg: Mapped[str | None] = mapped_column(Text)

    # --- Marca da empresa (definida no setup inicial) ---
    # O nome aparece no topo, no login e no título da aba; o logo e o favicon
    # são arquivos em media/empresa.
    empresa_nome: Mapped[str | None] = mapped_column(String(160))
    empresa_logo: Mapped[str | None] = mapped_column(String(300))
    empresa_favicon: Mapped[str | None] = mapped_column(String(300))
    # Frase curta exibida no login (opcional).
    empresa_rodape: Mapped[str | None] = mapped_column(String(200))


class QRZerado(CreatedAtModel, Base):
    """Etiqueta QR gerada EM BRANCO, para colar no equipamento e cadastrar depois.

    O fluxo é: gera N etiquetas sem dono → imprime → cola no equipamento →
    na tela de Leitura o código abre o formulário de cadastro já preenchido com
    essa etiqueta → ao salvar, a etiqueta passa a apontar para o ativo.

    O `payload` fica gravado no ativo criado, então a leitura continua
    funcionando pela via normal (o código em branco resolve para o ativo).
    """

    __tablename__ = "qr_zerados"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Planta que gerou a etiqueta — só ela pode vincular esse código.
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)
    # Código curto impresso no QR (ex.: ZQ7K2M4PXR), sem caracteres ambíguos.
    codigo: Mapped[str] = mapped_column(String(24), unique=True, index=True, nullable=False)
    payload: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    # Agrupa as etiquetas geradas na mesma leva (para imprimir/baixar em lote).
    lote: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # Inventário sugerido na geração (a leitura usa o inventário aberto).
    dominio: Mapped[str | None] = mapped_column(String(12))
    # livre = ainda sem dono | usado = já vinculada a um ativo
    status: Mapped[str] = mapped_column(String(12), default="livre", index=True, nullable=False)
    ativo_id: Mapped[int | None] = mapped_column(ForeignKey("ativos.id"))
    usado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    impresso_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
