-- =====================================================================
-- Gestão Patrimonial Unificada — Schema PostgreSQL 16
-- DDL de produção com ENUMs nativos, MACADDR, JSONB, CHECKs e triggers.
--
-- Uso manual (sem alembic):
--   psql -U estoque -d estoque -f schema.sql
--
-- Observação: o backend também cria o schema via SQLAlchemy
-- (Base.metadata.create_all) usando tipos portáteis, o que permite rodar
-- em SQLite no desenvolvimento. Este arquivo documenta o schema otimizado
-- de produção com recursos nativos do PostgreSQL.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- ENUMs
-- ---------------------------------------------------------------------
CREATE TYPE dominio AS ENUM ('ti', 'impressora');
CREATE TYPE tipo_item AS ENUM ('ativo', 'consumivel');
CREATE TYPE status_ativo AS ENUM ('estoque', 'reservado', 'em_uso', 'manutencao', 'descartado', 'emprestado');
CREATE TYPE tipo_mov AS ENUM ('entrada', 'saida', 'transferencia', 'atribuicao', 'devolucao', 'baixa');
CREATE TYPE papel_usuario AS ENUM ('admin', 'ti', 'leitor', 'auditor');
CREATE TYPE status_manut AS ENUM ('aberta', 'em_andamento', 'concluida', 'cancelada');
CREATE TYPE tipo_impressao AS ENUM ('laser', 'jato', 'termica', 'matricial', 'plotter');
CREATE TYPE conectividade AS ENUM ('usb', 'rede', 'wifi', 'paralela', 'serial');
CREATE TYPE tipo_suprimento AS ENUM ('toner', 'cartucho', 'fita', 'cilindro', 'papel', 'outro');

-- ---------------------------------------------------------------------
-- Núcleo compartilhado
-- ---------------------------------------------------------------------

CREATE TABLE departamentos (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(120) NOT NULL UNIQUE,
    sigla       VARCHAR(20),
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE localizacoes (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(120) NOT NULL,
    descricao   TEXT,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE fornecedores (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(160) NOT NULL,
    cnpj        VARCHAR(18),
    contato     VARCHAR(120),
    telefone    VARCHAR(30),
    email       VARCHAR(160),
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE categorias (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(120) NOT NULL,
    dominio     dominio,               -- NULL = comum aos dois domínios
    descricao   TEXT,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE usuarios (
    id              SERIAL PRIMARY KEY,
    nome            VARCHAR(160) NOT NULL,
    email           VARCHAR(160) NOT NULL UNIQUE,
    senha_hash      VARCHAR(255) NOT NULL,
    papel           papel_usuario NOT NULL DEFAULT 'leitor',
    departamento_id INTEGER REFERENCES departamentos(id),
    ativo           BOOLEAN NOT NULL DEFAULT TRUE,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE produtos (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(80) NOT NULL UNIQUE,
    nome            VARCHAR(200) NOT NULL,
    descricao       TEXT,
    categoria_id    INTEGER REFERENCES categorias(id),
    fornecedor_id   INTEGER REFERENCES fornecedores(id),
    dominio         dominio NOT NULL,
    tipo_item       tipo_item NOT NULL DEFAULT 'consumivel',
    unidade         VARCHAR(20) DEFAULT 'un',
    estoque_minimo  INTEGER NOT NULL DEFAULT 0,
    preco_unitario  NUMERIC(12,2),
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ativos (
    id                SERIAL PRIMARY KEY,
    dominio           dominio NOT NULL,
    tipo_item         tipo_item NOT NULL DEFAULT 'ativo',
    patrimonio        VARCHAR(80) NOT NULL UNIQUE,
    numero_serie      VARCHAR(160),
    modelo            VARCHAR(160),
    marca             VARCHAR(120),
    status            status_ativo NOT NULL DEFAULT 'estoque',
    categoria_id      INTEGER REFERENCES categorias(id),
    fornecedor_id     INTEGER REFERENCES fornecedores(id),
    localizacao_id    INTEGER REFERENCES localizacoes(id),
    departamento_id   INTEGER REFERENCES departamentos(id),
    data_aquisicao    DATE,
    data_garantia     DATE,
    valor             NUMERIC(14,2),
    observacoes       TEXT,
    qr_payload        TEXT,
    deleted_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE movimentacoes (
    id                      SERIAL PRIMARY KEY,
    tipo                    tipo_mov NOT NULL,
    ativo_id                INTEGER REFERENCES ativos(id),
    produto_id              INTEGER REFERENCES produtos(id),
    quantidade              INTEGER NOT NULL DEFAULT 1,
    origem_localizacao_id   INTEGER REFERENCES localizacoes(id),
    destino_localizacao_id  INTEGER REFERENCES localizacoes(id),
    origem_usuario_id       INTEGER REFERENCES usuarios(id),
    destino_usuario_id      INTEGER REFERENCES usuarios(id),
    data_mov                TIMESTAMPTZ NOT NULL DEFAULT now(),
    observacoes             TEXT,
    usuario_id              INTEGER REFERENCES usuarios(id),
    deleted_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Movimentação referencia OU um ativo OU um produto (nunca ambos/nem nenhum)
    CONSTRAINT mov_ref_check CHECK (
        (ativo_id IS NOT NULL AND produto_id IS NULL) OR
        (ativo_id IS NULL AND produto_id IS NOT NULL)
    )
);

CREATE TABLE manutencoes (
    id                SERIAL PRIMARY KEY,
    ativo_id          INTEGER NOT NULL REFERENCES ativos(id),
    fornecedor_id     INTEGER REFERENCES fornecedores(id),
    status            status_manut NOT NULL DEFAULT 'aberta',
    descricao         TEXT,
    custo             NUMERIC(14,2),
    data_abertura     TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_conclusao    TIMESTAMPTZ,
    tecnico           VARCHAR(160),
    observacoes       TEXT,
    deleted_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE termos (
    id              SERIAL PRIMARY KEY,
    ativo_id        INTEGER NOT NULL REFERENCES ativos(id),
    usuario_id      INTEGER NOT NULL REFERENCES usuarios(id),
    hash_sha256     VARCHAR(64) NOT NULL,
    data_assinatura TIMESTAMPTZ NOT NULL DEFAULT now(),
    pdf_path        VARCHAR(500),
    observacoes     TEXT,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE anexos (
    id          SERIAL PRIMARY KEY,
    entidade    VARCHAR(40) NOT NULL,
    entidade_id INTEGER NOT NULL,
    nome_arquivo VARCHAR(255) NOT NULL,
    caminho     VARCHAR(500) NOT NULL,
    mime_type   VARCHAR(120),
    tamanho     INTEGER,
    uploaded_by INTEGER REFERENCES usuarios(id),
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE logs_auditoria (
    id          BIGSERIAL PRIMARY KEY,
    usuario_id  INTEGER REFERENCES usuarios(id),
    acao        VARCHAR(40) NOT NULL,
    entidade    VARCHAR(40) NOT NULL,
    entidade_id INTEGER,
    ip          VARCHAR(45),
    diff        JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Extensão TI (1:1 com ativos)
-- ---------------------------------------------------------------------
CREATE TABLE ativos_ti (
    ativo_id           INTEGER PRIMARY KEY REFERENCES ativos(id) ON DELETE CASCADE,
    hostname           VARCHAR(120),
    mac_address        MACADDR,
    ip                 INET,
    so                 VARCHAR(120),
    dominio_ad         VARCHAR(120),
    cpu                VARCHAR(120),
    ram_gb             INTEGER,
    armazenamento_gb   INTEGER
);

-- ---------------------------------------------------------------------
-- Extensão Impressora (1:1 com ativos)
-- ---------------------------------------------------------------------
CREATE TABLE ativos_impressora (
    ativo_id          INTEGER PRIMARY KEY REFERENCES ativos(id) ON DELETE CASCADE,
    ip                VARCHAR(45),
    hostname          VARCHAR(120),
    driver            VARCHAR(200),
    tipo_impressao    tipo_impressao NOT NULL DEFAULT 'laser',
    colorida          BOOLEAN NOT NULL DEFAULT FALSE,
    contador_paginas  BIGINT NOT NULL DEFAULT 0,
    conectividade     conectividade NOT NULL DEFAULT 'rede'
);

CREATE TABLE suprimentos_impressora (
    id                  SERIAL PRIMARY KEY,
    ativo_id            INTEGER NOT NULL REFERENCES ativos(id) ON DELETE CASCADE,
    tipo                tipo_suprimento NOT NULL,
    modelo              VARCHAR(160),
    cor                 VARCHAR(60),
    rendimento_paginas  INTEGER,
    estoque_atual       INTEGER NOT NULL DEFAULT 0,
    estoque_minimo      INTEGER NOT NULL DEFAULT 0,
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE leituras_contador (
    id            BIGSERIAL PRIMARY KEY,
    ativo_id      INTEGER NOT NULL REFERENCES ativos(id) ON DELETE CASCADE,
    data_leitura  TIMESTAMPTZ NOT NULL DEFAULT now(),
    contador      BIGINT NOT NULL,
    observacoes   TEXT,
    deleted_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Índices
-- ---------------------------------------------------------------------
CREATE INDEX idx_ativos_dominio_status ON ativos (dominio, status);
CREATE INDEX idx_ativos_garantia ON ativos (data_garantia);
CREATE INDEX idx_ativos_qr ON ativos (qr_payload);
CREATE INDEX idx_produtos_dominio ON produtos (dominio);
CREATE INDEX idx_movimentacoes_data ON movimentacoes (data_mov DESC);
CREATE INDEX idx_movimentacoes_ativo ON movimentacoes (ativo_id);
CREATE INDEX idx_movimentacoes_produto ON movimentacoes (produto_id);
CREATE INDEX idx_manutencoes_ativo_status ON manutencoes (ativo_id, status);
CREATE INDEX idx_ativos_ti_hostname ON ativos_ti (hostname);
CREATE INDEX idx_ativos_impressora_ip ON ativos_impressora (ip);
CREATE INDEX idx_auditoria_entidade ON logs_auditoria (entidade, entidade_id);
CREATE INDEX idx_suprimentos_ativo ON suprimentos_impressora (ativo_id);

-- ---------------------------------------------------------------------
-- Trigger: atualiza updated_at automaticamente
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'departamentos','localizacoes','fornecedores','categorias','usuarios',
        'produtos','ativos','movimentacoes','manutencoes','termos','suprimentos_impressora'
    ]
    LOOP
        EXECUTE format(
            'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I
             FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t, t);
    END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- Trigger: ao abrir manutenção, muda status do ativo para 'manutencao'
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION on_manutencao_aberta() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'aberta' OR NEW.status = 'em_andamento' THEN
        UPDATE ativos SET status = 'manutencao'
        WHERE id = NEW.ativo_id AND status <> 'descartado';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_manutencao_aberta
AFTER INSERT OR UPDATE OF status ON manutencoes
FOR EACH ROW EXECUTE FUNCTION on_manutencao_aberta();

-- ---------------------------------------------------------------------
-- Trigger: ao concluir manutenção, restaura status anterior (estoque)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION on_manutencao_concluida() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'concluida' THEN
        -- Restaura para 'em_uso' se havia usuário atribuído; senão 'estoque'
        UPDATE ativos a SET status = CASE
            WHEN EXISTS (
                SELECT 1 FROM movimentacoes m
                WHERE m.ativo_id = a.id
                  AND m.tipo = 'atribuicao'
                  AND m.deleted_at IS NULL
                ORDER BY m.data_mov DESC LIMIT 1
            ) THEN 'em_uso'::status_ativo
            ELSE 'estoque'::status_ativo
        END
        WHERE a.id = NEW.ativo_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_manutencao_concluida
AFTER UPDATE OF status ON manutencoes
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION on_manutencao_concluida();

-- ---------------------------------------------------------------------
-- Administração: permissões por usuário, banco de fotos e dispositivos
-- ---------------------------------------------------------------------

-- Permissões granulares por usuário (NULL = derivado do papel).
-- Estrutura: {"inventarios": [...], "modulos": [...], "pode_escrever": bool, "pode_excluir": bool}
ALTER TABLE usuarios ADD COLUMN permissoes JSONB;

-- Banco de Fotos (estilo Zabbix): imagens reutilizáveis atribuíveis a ativos.
CREATE TABLE imagens (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(160) NOT NULL,
    descricao   TEXT,
    tags        VARCHAR(200),
    dominio     dominio,                  -- NULL = comum aos dois inventários
    caminho     VARCHAR(500) NOT NULL,
    mime_type   VARCHAR(120),
    tamanho     INTEGER,
    uploaded_by INTEGER REFERENCES usuarios(id),
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Foto principal do ativo.
ALTER TABLE ativos ADD COLUMN foto_id INTEGER REFERENCES imagens(id);
CREATE INDEX idx_ativos_foto ON ativos (foto_id);

-- Destino de impressão cadastrável (Raspberry Pi, compartilhamento UNC ou CUPS).
-- Exemplo: nome='Recepcao', hostname='RTAT0001', compartilhamento='\\RTAT0001\sip'
CREATE TABLE dispositivos_impressao (
    id               SERIAL PRIMARY KEY,
    nome             VARCHAR(160) NOT NULL,
    tipo             VARCHAR(30) NOT NULL DEFAULT 'agente',   -- agente | compartilhamento | cups
    hostname         VARCHAR(160),
    compartilhamento VARCHAR(300),
    agente_url       VARCHAR(300),
    fila_cups        VARCHAR(160),
    formato          VARCHAR(10) NOT NULL DEFAULT 'zpl',      -- zpl | tspl | pdf
    dominio          dominio,
    padrao           BOOLEAN NOT NULL DEFAULT FALSE,
    ativo            BOOLEAN NOT NULL DEFAULT TRUE,
    observacoes      TEXT,
    deleted_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_dispositivos_padrao ON dispositivos_impressao (padrao);

CREATE TRIGGER trg_imagens_updated_at BEFORE UPDATE ON imagens
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_dispositivos_updated_at BEFORE UPDATE ON dispositivos_impressao
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- Configuração do sistema (LDAP/AD) e templates de etiqueta
-- ---------------------------------------------------------------------

-- Origem do login: 'local' (senha no sistema, inclui o root) ou 'ad'.
ALTER TABLE usuarios ADD COLUMN origem VARCHAR(10) NOT NULL DEFAULT 'local';

-- Configuração global (linha única, id = 1).
-- A senha da conta de serviço é gravada CIFRADA (app/core/cripto.py).
CREATE TABLE configuracoes (
    id                       INTEGER PRIMARY KEY DEFAULT 1,
    ldap_ativo               BOOLEAN NOT NULL DEFAULT FALSE,
    ldap_servidor            VARCHAR(300),
    ldap_porta               INTEGER NOT NULL DEFAULT 636,
    ldap_tls                 BOOLEAN NOT NULL DEFAULT TRUE,
    ldap_base_dn             VARCHAR(300),
    ldap_bind_dn             VARCHAR(300),
    ldap_bind_senha          VARCHAR(500),
    ldap_filtro_usuario      VARCHAR(300) NOT NULL DEFAULT '(sAMAccountName={usuario})',
    ldap_grupo_acesso        VARCHAR(300),   -- ex.: YM_ESTOQUE_TI
    ldap_grupo_admin         VARCHAR(300),
    ldap_provisionar         BOOLEAN NOT NULL DEFAULT TRUE,
    ldap_grupos_aninhados    BOOLEAN NOT NULL DEFAULT TRUE,
    ldap_ignorar_certificado BOOLEAN NOT NULL DEFAULT FALSE,
    ldap_admin_por_cargo     BOOLEAN NOT NULL DEFAULT FALSE,
    ldap_ultimo_teste_ok     VARCHAR(40),
    ldap_ultimo_teste_msg    TEXT,
    deleted_at               TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT configuracao_unica CHECK (id = 1)
);

-- Templates de etiqueta (layout configurável; `config` guarda o detalhamento).
CREATE TABLE templates_etiqueta (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(160) NOT NULL,
    descricao   TEXT,
    largura_mm  NUMERIC(6,2) NOT NULL DEFAULT 100.0,
    altura_mm   NUMERIC(6,2) NOT NULL DEFAULT 50.0,
    dpi         INTEGER NOT NULL DEFAULT 203,
    dominio     dominio,
    padrao      BOOLEAN NOT NULL DEFAULT FALSE,
    config      JSONB NOT NULL DEFAULT '{}'::jsonb,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cada dispositivo pode ter o seu template (NULL = usa o padrão).
ALTER TABLE dispositivos_impressao
    ADD COLUMN template_id INTEGER REFERENCES templates_etiqueta(id);

CREATE TRIGGER trg_configuracoes_updated_at BEFORE UPDATE ON configuracoes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_templates_updated_at BEFORE UPDATE ON templates_etiqueta
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ===========================================================================
-- Software, licenças e locação
-- ===========================================================================
-- Duas frentes que chegaram depois do esquema original e nunca foram
-- refletidas aqui: os CONTRATOS (locação de equipamento) e o inventário de
-- SOFTWARE/LICENÇAS.
--
-- Uma instalação PostgreSQL que siga este arquivo ficava sem as tabelas — e
-- só funcionava com `AUTO_CREATE_TABLES` ligado. Este bloco fecha isso.
--
-- Os `IF NOT EXISTS` permitem rodar sobre uma base que já tenha as tabelas
-- criadas pelo SQLAlchemy: nada é sobrescrito nem perdido.

-- --- Locação: colunas novas no ativo -------------------------------------
-- `forma_aquisicao` nasce 'comprado' de propósito: todo ativo cadastrado
-- antes deste campo existir foi tratado como comprado, e continua correto
-- sem migração de dado.
ALTER TABLE ativos
    ADD COLUMN IF NOT EXISTS forma_aquisicao VARCHAR(20) NOT NULL DEFAULT 'comprado';
ALTER TABLE ativos
    ADD COLUMN IF NOT EXISTS contrato_id INTEGER;
ALTER TABLE ativos
    ADD COLUMN IF NOT EXISTS valor_residual NUMERIC(14, 2);

-- --- Contratos -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS contratos (
    id              SERIAL PRIMARY KEY,
    numero          VARCHAR(80) NOT NULL UNIQUE,
    tipo            VARCHAR(20) NOT NULL DEFAULT 'locacao',
    planta_id       INTEGER REFERENCES plantas(id),
    fornecedor_id   INTEGER REFERENCES fornecedores(id),
    inicio          DATE NOT NULL,
    fim             DATE,
    valor_mensal    NUMERIC(14, 2),
    valor_total     NUMERIC(14, 2),
    dia_vencimento  INTEGER,
    observacoes     TEXT,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A FK do ativo para o contrato entra DEPOIS: na primeira execução a tabela
-- `contratos` ainda não existia quando `ativos` foi criada.
DO $$
BEGIN
    ALTER TABLE ativos
        ADD CONSTRAINT fk_ativos_contrato
        FOREIGN KEY (contrato_id) REFERENCES contratos(id);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE INDEX IF NOT EXISTS ix_ativos_contrato ON ativos(contrato_id);
CREATE INDEX IF NOT EXISTS ix_ativos_forma ON ativos(forma_aquisicao);

-- --- Software ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS softwares (
    id           SERIAL PRIMARY KEY,
    nome         VARCHAR(200) NOT NULL,
    fabricante   VARCHAR(120),
    versao       VARCHAR(60),
    categoria    VARCHAR(80),
    plataforma   VARCHAR(20) NOT NULL DEFAULT 'windows',
    descricao    TEXT,
    -- Padrões de reconhecimento separados por ';', casados contra o nome que
    -- o OCS reporta. Sem eles o cruzamento não acha nada — ver
    -- app/services/conformidade.py.
    padroes      TEXT,
    site         VARCHAR(300),
    obrigatorio  BOOLEAN NOT NULL DEFAULT false,
    planta_id    INTEGER REFERENCES plantas(id),
    deleted_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_softwares_nome ON softwares(nome);
CREATE INDEX IF NOT EXISTS ix_softwares_fabricante ON softwares(fabricante);

-- --- Licenças ------------------------------------------------------------
-- ATENÇÃO: a chave NÃO é gravada em claro.
--   chave_cifrada   → o valor, cifrado com a chave mestra (app/core/segredos.py)
--   chave_versao    → qual chave mestra abriu aquele valor (rotação)
--   chave_impressao → as 4 últimas posições, para conferência humana
--   chave_hash      → SHA-256 normalizado, para achar duplicata SEM decifrar
--
-- A chave mestra NÃO fica neste banco: sem ela, estas colunas são
-- irrecuperáveis, e é isso que impede que quem rouba o dump leia as licenças.
CREATE TABLE IF NOT EXISTS licencas (
    id               SERIAL PRIMARY KEY,
    software_id      INTEGER NOT NULL REFERENCES softwares(id),
    tipo             VARCHAR(20) NOT NULL,
    situacao         VARCHAR(20) NOT NULL DEFAULT 'ativa',
    chave_cifrada    BYTEA,
    chave_versao     INTEGER NOT NULL DEFAULT 1,
    chave_impressao  VARCHAR(8),
    chave_hash       VARCHAR(64),
    seats            INTEGER NOT NULL DEFAULT 1,
    -- Como a licença é CONTADA: por máquina ou por pessoa.
    --
    -- O OCS conta máquinas; a licença conta seats. Para Office LTSC os dois
    -- são a mesma coisa. Para Microsoft 365 e Adobe CC NÃO são — o seat é
    -- por pessoa, e uma pessoa pode usar dois computadores.
    --
    -- O padrão 'dispositivo' existe para os registros anteriores a este
    -- campo. Na criação pela API o valor é OBRIGATÓRIO: o sistema pergunta
    -- em vez de assumir, porque um padrão silencioso deixaria o cálculo
    -- errado sem ninguém perceber.
    metrica          VARCHAR(20) NOT NULL DEFAULT 'dispositivo',
    validade         DATE,
    numero_pedido    VARCHAR(80),
    fornecedor_id    INTEGER REFERENCES fornecedores(id),
    -- Assinatura SaaS É locação: reusa o contrato, com mensalidade e
    -- vencimento — e o alerta de vencimento que já existe.
    contrato_id      INTEGER REFERENCES contratos(id),
    valor            NUMERIC(14, 2),
    valor_mensal     NUMERIC(14, 2),
    data_compra      DATE,
    observacoes      TEXT,
    planta_id        INTEGER REFERENCES plantas(id),
    deleted_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_licencas_software ON licencas(software_id);
CREATE INDEX IF NOT EXISTS ix_licencas_validade ON licencas(validade);
-- Índice no hash: a checagem de duplicata é por igualdade, e não pode
-- exigir varredura da tabela inteira a cada cadastro.
CREATE INDEX IF NOT EXISTS ix_licencas_chave_hash ON licencas(chave_hash);

-- --- Software instalado (o que o OCS reporta) ----------------------------
CREATE TABLE IF NOT EXISTS softwares_instalados (
    id           SERIAL PRIMARY KEY,
    ativo_id     INTEGER NOT NULL REFERENCES ativos(id),
    -- O nome como o OCS mandou, SEM normalizar: é o que permite explicar
    -- depois por que uma instalação contou (ou não) e corrigir o padrão.
    nome         VARCHAR(300) NOT NULL,
    versao       VARCHAR(80),
    fabricante   VARCHAR(120),
    dominio      VARCHAR(20),
    origem       VARCHAR(40) NOT NULL DEFAULT 'ocs',
    coletado_em  TIMESTAMPTZ,
    -- Qual software cadastrado reconheceu esta instalação. Nulo = nenhum,
    -- e nulo é o caso que vira "sem licença" no relatório.
    software_id  INTEGER REFERENCES softwares(id),
    deleted_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_instalados_ativo ON softwares_instalados(ativo_id);
CREATE INDEX IF NOT EXISTS ix_instalados_nome ON softwares_instalados(nome);
CREATE INDEX IF NOT EXISTS ix_instalados_software ON softwares_instalados(software_id);
CREATE INDEX IF NOT EXISTS ix_instalados_dominio ON softwares_instalados(dominio);

-- --- Atribuições ---------------------------------------------------------
-- Uma licença aplicada numa MÁQUINA (Office LTSC, AutoCAD) ou numa PESSOA
-- (Microsoft 365, Adobe CC). Exatamente um dos dois é preenchido — modelar
-- só um caso obrigaria a inventar um "ativo virtual" para representar gente.
CREATE TABLE IF NOT EXISTS atribuicoes_licenca (
    id                SERIAL PRIMARY KEY,
    licenca_id        INTEGER NOT NULL REFERENCES licencas(id),
    ativo_id          INTEGER REFERENCES ativos(id),
    usuario_id        INTEGER REFERENCES usuarios(id),
    versao_instalada  VARCHAR(60),
    data_atribuicao   DATE,
    origem            VARCHAR(40),
    observacoes       TEXT,
    deleted_at        TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_atribuicao_um_dono
        CHECK ((ativo_id IS NULL) <> (usuario_id IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_atribuicoes_licenca ON atribuicoes_licenca(licenca_id);
CREATE INDEX IF NOT EXISTS ix_atribuicoes_ativo ON atribuicoes_licenca(ativo_id);
CREATE INDEX IF NOT EXISTS ix_atribuicoes_usuario ON atribuicoes_licenca(usuario_id);

-- --- Gatilhos de updated_at ----------------------------------------------
CREATE TRIGGER trg_contratos_updated_at BEFORE UPDATE ON contratos
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_softwares_updated_at BEFORE UPDATE ON softwares
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_licencas_updated_at BEFORE UPDATE ON licencas
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_instalados_updated_at BEFORE UPDATE ON softwares_instalados
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_atribuicoes_updated_at BEFORE UPDATE ON atribuicoes_licenca
FOR EACH ROW EXECUTE FUNCTION set_updated_at();


COMMIT;
