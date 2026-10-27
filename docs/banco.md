# Banco de dados — da primeira conexão em diante

O que acontece quando o Nexus aponta para um banco vazio, o que ele cria
sozinho, o que você precisa criar à mão, e o que conferir quando algo não
bate.

> **Quer só o passo a passo para subir?** Veja docs/banco-setup.md —
> curto, na ordem em que se faz. Este documento explica o *porquê* e o
> que fazer **depois** do primeiro acesso.
>
> Para **como escolher e configurar** o banco (SQLite, PostgreSQL, MySQL,
> URL, senha com caractere especial), veja `.env.example` — a seção
> "BANCO DE DADOS". Este documento começa **depois** disso.

---

## 1. Na primeira subida, com o banco vazio

O `init_db()` roda no boot e faz **cinco coisas, nesta ordem**:

| # | Passo | O que resolve |
|---|---|---|
| 1 | `create_all` | **cria as tabelas e os tipos (enum)** que faltarem |
| 2 | colunas faltantes | acrescenta colunas novas a tabelas que já existiam |
| 3 | índices faltantes | cria os índices que faltarem |
| 4 | valores de enum | `ALTER TYPE ... ADD VALUE` — o caso do `tinta` |
| 5 | `ANALYZE` | estatísticas para o planejador escolher plano bom |

Depois disso, o **seed** roda dentro de uma transação:

| O que | Regra |
|---|---|
| **Planta padrão `Central-SP`** | criada **só se não houver nenhuma** |
| **Vínculo à planta** | ativos, QR zerados e dispositivos **sem planta** passam a pertencer a ela |
| **Administrador** | criado **só se o e-mail não existir** |

**O administrador fica sem planta de propósito** — assim enxerga todas as
unidades e escolhe no seletor do topo.

> `AUTO_CREATE_TABLES=true` no compose é o que liga os passos 1–5. É o padrão.

---

## 2. Como saber se deu certo

### No log do container

Procure estas linhas:

```
Planta padrão criada: Central-SP
Colunas adicionadas automaticamente: ...
Índices criados automaticamente: ...
Estatísticas do banco atualizadas (ANALYZE).
```

**A ausência de "Planta padrão criada" na segunda subida é o esperado** — o
seed não repete.

### No banco

```bash
docker exec -it <container_db> psql -U estoque -d estoque -c '\dt'
```

**Devem aparecer ~41 tabelas.** As principais:

```
ativos            usuarios          emprestimos
ativos_ti         plantas            emails_enviados
ativos_impressora departamentos      preferencias_notificacao
suprimentos_impressora  categorias   config_smtp
...                                  templates_notificacao
```

### Pela aplicação

```
GET /health  →  { "status": "ok", "database": true }
```

**`database: true` significa que a conexão respondeu** — não qual banco é.
Para saber o banco:

```bash
docker exec -it <container_api> python -c \
  "from app.config import settings; print(settings.database_url)"
```

---

## 3. O que **já existe** e o que **você cria**

### Criado automaticamente

- ✅ **Todas as tabelas, índices e enums**
- ✅ **Planta `Central-SP`**
- ✅ **Usuário administrador** (`SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`)

### Você cria, depois de entrar

**Nesta ordem** — cada item depende do anterior:

| # | O que | Onde | Por quê |
|---|---|---|---|
| 1 | **Senha do administrador** | primeiro acesso | o sistema **força** a troca |
| 2 | **Plantas** | Administração → Plantas | limite de acesso entre unidades |
| 3 | **Departamentos** | Cadastros | a quem o ativo é atribuído |
| 4 | **Localizações** | Cadastros | onde o ativo está fisicamente |
| 5 | **Categorias** | Cadastros | agrupa o inventário |
| 6 | **Usuários** | Administração → Usuários | com papel e planta |
| 7 | **Ativos** | Ativos → Novo, ou Importar CSV | o inventário em si |

> **Por que não vem tudo pronto:** departamento e localização são a
> estrutura da **sua** empresa. Um conjunto genérico só criaria registros
> para apagar.

**Se a empresa tem uma unidade só**, a planta `Central-SP` pode ser
renomeada em vez de criar outra — **ela não pode ser excluída enquanto tiver
ativos.**

---

## 4. Primeiro acesso

1. Abra o endereço do Nexus
2. Entre com `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`
3. **O sistema pede a troca de senha** — não é opcional
4. Confira que a planta no topo é a correta
5. Cadastre departamentos, localizações e categorias
6. Importe ou cadastre os ativos

> **Troque a senha antes de qualquer outra coisa.** Enquanto ela for
> `admin123`, qualquer um que alcance a porta 4545 entra como administrador.

---

## 5. Trocar a senha do banco depois

**⚠️ Este é o erro mais comum, e o sintoma engana.**

A senha do PostgreSQL **não** é definida pelo container a cada subida. O
`initdb` roda **uma vez**, quando o volume está vazio. Depois disso,
`POSTGRES_PASSWORD` é **ignorado**.

**Consequência:** mudar a variável no stack muda **o cliente**, mas não o
banco.

```
DATABASE_URL da API ....... senha NOVA
senha real no PostgreSQL ... senha ANTIGA
resultado ................. password authentication failed
```

**E ao voltar a variável para o valor antigo, volta a funcionar** — o que dá
a impressão de que a variável é a fonte da verdade. **Não é.**

### Trocar de verdade — mantendo os dados

```bash
# 1. Troque no banco (a senha real)
docker exec -it <container_db> psql -U estoque -d estoque -c \
  "ALTER USER estoque WITH PASSWORD 'senha-nova';"

# 2. Atualize a variável no stack do Portainer
#    POSTGRES_PASSWORD=senha-nova

# 3. Redeploy da stack
```

**As duas coisas, nesta ordem.** Só uma delas deixa tudo quebrado.

### Trocar com o banco ainda vazio

Aí a variável funciona: o `initdb` ainda não rodou.

---

## 6. Antes de mexer no banco, faça backup

```bash
docker exec -it <container_db> pg_dump -U estoque -d estoque > backup.sql
```

**E antes de uma atualização de imagem:**

```bash
docker exec -it <container_db> pg_dump -U estoque -Fc -d estoque > antes-da-atualizacao.dump
```

O `-Fc` gera o formato comprimido, que o `pg_restore` lê.

> O Nexus também faz backup automático antes de operações destrutivas
> (exclusão em lote) e mantém `BACKUP_RETER` dias no volume `backups`.
> **Mas isso não substitui um dump antes de trocar a imagem** — o backup
> interno vive no mesmo host.

---

## 7. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `password authentication failed` | senha do banco ≠ variável | `ALTER USER` (seção 5) |
| `could not translate host name "db"` | banco externo, mas o compose ainda aponta para `db` | ajustar `DATABASE_URL` |
| `database "nexus" does not exist` | o banco não foi criado | `CREATE DATABASE nexus;` |
| `permission denied for schema public` | usuário sem `CREATE` | `GRANT ALL ON SCHEMA public TO usuario;` |
| Container reinicia sozinho | banco inacessível no boot | `docker logs <container_api>` |
| Dados somem ao recriar | está em SQLite, dentro do container | usar PostgreSQL ou volume |
| Acentos viram `?` (MySQL) | falta `charset=utf8mb4` na URL | ver `.env.example` |

> **`password authentication failed` é o mais traiçoeiro**: a mensagem manda
> conferir a senha na configuração, e a configuração está certa. O problema
> está no banco.

---

## 8. O que o Nexus **não** faz no banco

Para não haver surpresa:

- **Não cria o banco.** Só as tabelas. Em PostgreSQL externo,
  `CREATE DATABASE` é seu.
- **Não cria o usuário do banco** nem concede permissão.
- **Não altera tipo de coluna.** Se `VARCHAR(80)` virar `VARCHAR(160)` numa
  versão nova, `create_all` **não toca**. Isso é trabalho de migração
  (`alembic`, presente no `requirements` mas **sem versões ainda**).
- **Não apaga nada.** `AUTO_CREATE_TABLES=true` só acrescenta.

> **A limitação de tipos é o achado nº 5 da auditoria de segurança.** Hoje
> não dói — o sistema está começando. Vai doer na primeira mudança de tipo
> que exigir migração de dados.

---

## Veja também

- **`.env.example`** — como escolher e configurar o banco
- **`docs/operacao.md`** § 4 — produção com Docker Compose
- **`docs/operacao.md`** § 12 — implantação pelo Portainer
