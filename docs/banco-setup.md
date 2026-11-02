# Banco de dados — configuração para subir

Guia curto, na ordem em que se faz. **Só o necessário para o sistema subir.**

> Para o *porquê* de cada decisão, e para o que fazer depois do primeiro
> acesso, veja `docs/banco.md`. Este aqui é só o passo a passo.

---

## 1. Antes de subir: escolha o cenário

### A. PostgreSQL do compose — **o padrão, nada a fazer**

O `docker-compose.yml` já cria o banco, o usuário e a senha.

**Vá para a seção 2.** Não precisa de nada nesta etapa.

---

### B. PostgreSQL externo (outro servidor, RDS, Azure, Neon)

O Nexus **cria as tabelas, não o banco**. No servidor do banco, rode:

```sql
CREATE DATABASE nexus;
CREATE USER nexus WITH PASSWORD 'sua-senha';
GRANT ALL PRIVILEGES ON DATABASE nexus TO nexus;
\c nexus
GRANT ALL ON SCHEMA public TO nexus;
```

**O último `GRANT` é o que mais falta.** Sem ele o sistema sobe e falha na
primeira criação de tabela, com `permission denied for schema public`.

**Se a senha tiver** `@ : / # ? %` **ou espaço**, codifique:

```bash
python -c "import urllib.parse; print(urllib.parse.quote('SUA-SENHA', safe=''))"
```

**Teste antes de seguir** — se o `psql` não conecta daqui, o Nexus também não:

```bash
psql "postgresql://nexus:senha@10.0.0.50:5432/nexus" -c "select 1;"
```

---

## 2. No servidor: criar as pastas de dados

Os dados ficam em **pastas no host**, não em volume nomeado — é o que permite
o Kopia (ou rsync, ou tar) fazer backup por caminho.

Tudo mora sob **`NEXUS_DADOS`**:

```
/srv/nexus/pgdata     banco
/srv/nexus/media      fotos, termos em PDF, anexos
/srv/nexus/backups    dumps feitos pelo próprio Nexus
/srv/nexus/segredos   JWT, chave de QR, chave de licenças
```

**Antes do primeiro deploy:**

```bash
sudo mkdir -p /srv/nexus/{pgdata,media,backups,segredos}
sudo chown -R 999:999 /srv/nexus/pgdata
```

> **O `chown` não é opcional.** O PostgreSQL roda como **uid 999** dentro da
> imagem. Sem ele o banco não sobe, e o log diz `data directory has wrong
> ownership` — mensagem que não menciona permissão de pasta do host.

**As outras três pastas não precisam de ajuste**: a aplicação roda como root
na imagem.

**No Kopia**, aponte o backup para **`/srv/nexus`** — um caminho só cobre
banco, mídia, backups e segredos.

---

## 3. No Portainer: variáveis da stack

**Stacks → sua stack → Environment variables → Advanced mode**

### Cenário A — banco do compose

```ini
POSTGRES_USER=estoque
POSTGRES_PASSWORD=SENHA-FORTE-AQUI
POSTGRES_DB=estoque

SEED_ADMIN_EMAIL=admin@empresa.com
SEED_ADMIN_PASSWORD=SENHA-DO-ADMIN
```

**Só isso.** `DATABASE_URL` vazio faz o compose montar a conexão.

`NEXUS_DADOS` também precisa estar definido — é onde os dados ficam no host,
e o caminho que o Kopia vai encontrar. Use o mesmo da seção 2
(`/srv/nexus`).

### Cenário B — banco externo

```ini
DATABASE_URL=postgresql+psycopg://nexus:senha@10.0.0.50:5432/nexus

SEED_ADMIN_EMAIL=admin@empresa.com
SEED_ADMIN_PASSWORD=SENHA-DO-ADMIN
```

**Os `POSTGRES_*` não são usados** nesse caso — o serviço `db` do compose
sobe vazio. Pode ignorá-lo.

> **Mantenha o `+psycopg`.** Sem ele o SQLAlchemy procura `psycopg2`, que não
> está instalado, e o erro não menciona banco nenhum.

### Variáveis que você **não** define

```ini
JWT_SECRET=            # deixe vazio
QR_HMAC_SECRET=        # deixe vazio
NEXUS_CHAVE_LICENCAS=  # deixe vazio
CORS_ORIGINS=          # deixe vazio
```

**Os três segredos são gerados no primeiro boot** e guardados no volume
`segredos`. **`CORS_ORIGINS` vazio é o normal** — o frontend é servido pela
mesma aplicação, então não há requisição cross-origin.

Arquivo pronto para colar: **`.env.stack`**

---

## 4. Deploy e conferência

**Deploy the stack.** Depois, três checagens:

**a) O container subiu?**
```bash
docker ps --filter name=api
```

**b) Qual banco ele está usando?**
```bash
docker exec <container_api> python -c \
  "from app.config import settings; print(settings.database_url)"
```

Deve imprimir **exatamente** o que você definiu. Se apontou para banco
externo e apareceu `@db:5432`, a stack não pegou o `DATABASE_URL`.

**c) As tabelas nasceram?**
```bash
docker exec -it <container_db> psql -U estoque -d estoque -c '\dt'
```

**~41 tabelas.** No log da API deve aparecer `Planta padrão criada`.

**Acesse `http://IP:4545`** e entre com `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD`.
O sistema **força a troca de senha** no primeiro acesso.

---

## 5. Se não subir

| Mensagem no log | Causa | Correção |
|---|---|---|
| `password authentication failed` | senha do banco ≠ variável | `ALTER USER` no banco **e** a variável (ver `banco.md` §5) |
| `could not translate host name` | `DATABASE_URL` aponta para host que não resolve | conferir IP/nome |
| `database "nexus" does not exist` | o banco não foi criado | seção 1B |
| `permission denied for schema public` | falta o `GRANT` | seção 1B, último comando |
| `ModuleNotFoundError: psycopg2` | falta o `+psycopg` na URL | corrigir a URL |
| `DATABASE_URL aponta para SQLite, mas ENV=production` | URL sem banco definido | seção 2, escolher A ou B |
| Reinicia em loop, log sem erro | banco inacessível | `docker logs <container_api> --tail 50` |

---

## 6. Trocar a senha do banco depois

**A senha real fica no banco, não na variável.** Mudar só a variável quebra a
conexão.

```bash
# 1. no banco
docker exec -it <container_db> psql -U estoque -d estoque -c \
  "ALTER USER estoque WITH PASSWORD 'senha-nova';"

# 2. na stack
#    POSTGRES_PASSWORD=senha-nova
# 3. redeploy
```

**As duas coisas, nesta ordem.**

---

## Antes de qualquer atualização de imagem

```bash
docker exec -it <container_db> pg_dump -U estoque -Fc -d estoque > antes.dump
```

**O backup interno do Nexus vive no mesmo host** — não protege contra perder o
volume nem contra trocar a imagem errada.
