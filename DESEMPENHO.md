# DESEMPENHO — medições reais

Medido com o gerador de carga (`scripts/gerar_carga.py`) e o benchmark
(`scripts/benchmark.py`), neste computador, em SQLite.

```bash
python scripts/gerar_carga.py --banco loadtest.db --total 5000
python scripts/benchmark.py --banco loadtest.db --repetir 7 --saida rel.txt
```

| | 5.000 ativos | 50.000 ativos |
|---|---|---|
| Lista (1ª página) | 13 ms | 23 ms |
| Lista (última página) | 23 ms | 34 ms |
| Ordenação | 12 ms | 25 ms |
| Filtro por status | 15 ms | 22 ms |
| Busca por texto | 18 ms | 67 ms |
| KPIs do topo | 16 ms | 46 ms |
| **Relatórios (gráficos)** | **45 ms** | **343 ms** |
| Auditoria, cadastros, impressoras | 4–8 ms | 4–8 ms |

Gerar 5.000 ativos leva **0,29 s**; 50.000 levam **1,5 s** (insert em lote).

---

## O que foi otimizado (e o que quase deu errado)

### 1. Chaves estrangeiras sem índice — o maior gargalo

O SQLite **não cria índice automático para chave estrangeira** (o MySQL faz).
Então estas consultas dos relatórios varriam os 50 mil ativos uma vez por
categoria/local:

```sql
FROM categorias LEFT JOIN ativos ... GROUP BY categorias.nome   -- 269 ms
FROM categorias LEFT JOIN ativos ... sum(valor)                 -- 267 ms
FROM localizacoes LEFT JOIN ativos ... GROUP BY localizacoes.nome -- 234 ms
```

**770 ms dos 1.228 ms** estavam aqui.

**Correção:** índice em `categoria_id`, `localizacao_id`, `departamento_id` e
`fornecedor_id`. Relatórios: **1.228 ms → 343 ms (3,6x mais rápido)**.

### 2. Índices compostos para os filtros do dia a dia

Praticamente toda consulta filtra `deleted_at IS NULL` + `dominio`. Os índices
eram de coluna única, então o banco ainda visitava a tabela linha a linha.

```python
Index("ix_ativos_dominio_deleted_status", "dominio", "deleted_at", "status")
Index("ix_ativos_planta_deleted", "planta_id", "deleted_at")
```

Resultado: lista **83 → 23 ms**, última página **209 → 34 ms**, contagem
**78 → 21 ms**.

### 3. `ANALYZE` — a peça que quase faltou

⚠️ **Criar os índices sozinho PIOROU o sistema:**

| | Sem índices | Só índices | Índices + ANALYZE |
|---|---|---|---|
| Relatórios | 569 ms | **1.318 ms** | 1.235 ms → 343 ms |
| Ordenação | 77 ms | 142 ms | 25 ms |
| Última página | 209 ms | 302 ms | 34 ms |

Sem estatísticas atualizadas o planejador escolhe planos ruins e fica **mais
lento do que sem índice nenhum**. O `ANALYZE` roda no `init_db()` sempre que
índices novos aparecem.

> **Lição registrada:** índice não é ganho automático. Toda otimização aqui foi
> medida antes e depois — a primeira tentativa foi revertida por ser pior.

### 4. Migração de índice em banco existente

`Base.metadata.create_all()` **não adiciona índice a tabela que já existe** —
uma instalação antiga jamais receberia os índices novos e continuaria lenta
mesmo após atualizar. Por isso existe `_criar_indices_faltantes()`, chamado no
`init_db()`, junto com o `_adicionar_colunas_faltantes()` que já existia.

---

## Limites conhecidos

| Cenário | Comportamento |
|---|---|
| Busca por texto (`%termo%`) | *Full scan* — `LIKE` com curinga à esquerda não usa índice. 67 ms com 50 mil; aceitável, mas cresce linear |
| Última página (OFFSET alto) | 34 ms com 50 mil — o SQLite ainda percorre o deslocamento. Se passar de ~500 mil registros, considerar paginação por cursor |
| Relatórios | 343 ms com 50 mil — o mais pesado. É o endpoint mais candidato a cache, se necessário |

## Como testar no seu ambiente

```bash
# 1. cópia do banco (NUNCA aponte direto para o de produção)
copy estoque.db loadtest.db

# 2. carga
python scripts/gerar_carga.py --banco loadtest.db --total 5000 --plantas 6

# 3. medir
python scripts/benchmark.py --banco loadtest.db --repetir 10

# 4. limpar (remove só os registros LOAD-*)
python scripts/gerar_carga.py --banco loadtest.db --limpar
```

O script **recusa** rodar contra `estoque.db` sem a flag
`--eu-sei-o-que-estou-fazendo`.
