# Refatorar `app/routers/graficos.py` com filtro base

Especificação pronta para execução. **Não tente fazer isto por script** — ver
"O erro das três tentativas" no fim.

## Objetivo

Todos os blocos do relatório de gráficos passam a compartilhar os mesmos
filtros: `inicio`, `fim`, `planta_id`, `forma_aquisicao`, `contrato_id`.

Hoje cada bloco monta a sua própria consulta. Um filtro acrescentado a um
bloco só vale ali — e um relatório com alguns gráficos filtrados e outros não
é **pior** do que nenhum: os números parecem filtrados e não são.

## Passo 1 — assinatura do endpoint

Trocar:

```python
def graficos(
    dominio: Dominio = Query(default=Dominio.TI),
    meses: int = Query(default=6, ge=1, le=24),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
```

por:

```python
def graficos(
    dominio: Dominio = Query(default=Dominio.TI),
    meses: int = Query(default=6, ge=1, le=24),
    inicio: date | None = Query(default=None),
    fim: date | None = Query(default=None),
    planta_id: int | None = Query(default=None),
    forma_aquisicao: FormaAquisicao | None = Query(default=None),
    contrato_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
```

## Passo 2 — o helper, antes de `graficos`

```python
def _condicoes(
    dominio: Dominio,
    *,
    inicio: date | None = None,
    fim: date | None = None,
    planta_id: int | None = None,
    forma_aquisicao: FormaAquisicao | None = None,
    contrato_id: int | None = None,
) -> list:
    """Condições comuns a TODOS os blocos que consultam ativos.

    Devolve uma lista para ser espalhada em `filter(*cond)` ou, quando há
    outra condição na mesma expressão, em `and_(outra, *cond)`.

    A ORDEM dos dois primeiros itens é invertida de propósito: se fosse
    `deleted_at, dominio`, esta linha seria atingida por uma substituição
    textual do filtro antigo e viraria `cond = [*cond]`.
    """
    cond = [Ativo.dominio == dominio, Ativo.deleted_at.is_(None)]
    if inicio is not None:
        cond.append(Ativo.data_aquisicao >= inicio)
    if fim is not None:
        cond.append(Ativo.data_aquisicao <= fim)
    if planta_id is not None:
        cond.append(Ativo.planta_id == planta_id)
    if forma_aquisicao is not None:
        cond.append(Ativo.forma_aquisicao == forma_aquisicao)
    if contrato_id is not None:
        cond.append(Ativo.contrato_id == contrato_id)
    return cond
```

## Passo 3 — calcular no corpo do endpoint

Trocar:

```python
    base = db.query(Ativo).filter(Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
```

por:

```python
    cond = _condicoes(
        dominio, inicio=inicio, fim=fim, planta_id=planta_id,
        forma_aquisicao=forma_aquisicao, contrato_id=contrato_id,
    )
    base = db.query(Ativo).filter(*cond)
```

## Passo 4 — os 11 pontos, um a um

**A mesma condição está escrita de 5 formas.** É por isso que script não
funciona: cada busca cobre uma forma e ignora as outras.

### Forma A — `filter` simples (3 pontos)

Linhas ~76 e ~246 (bloco 1 e `_parque`):

```python
.filter(Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
```
→ `.filter(*cond)`

### Forma B — `outerjoin` com `&` (4 pontos) ← **a que escapa**

Linhas ~85, ~94, ~103, ~112:

```python
.outerjoin(Ativo, (Ativo.categoria_id == Categoria.id) & (Ativo.deleted_at.is_(None)) & (Ativo.dominio == dominio))
```
→ `.outerjoin(Ativo, and_(Ativo.categoria_id == Categoria.id, *cond))`

Idem para `localizacao_id`, `departamento_id` e o `sum(Ativo.valor)`.

**Precisa importar `and_`:** `from sqlalchemy import and_, func, ...`

### Forma C — manutenções (1 ponto)

Linha ~162:

```python
.filter(Manutencao.deleted_at.is_(None), Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
```
→ `.filter(Manutencao.deleted_at.is_(None), *cond)`

### Forma D — domínio fixo (4 pontos)

Linhas ~174, ~182 (`Dominio.TI`) e ~191, ~202 (`Dominio.IMPRESSORA`):

```python
.filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.TI)
```
→ `.filter(*cond)`

**É seguro:** o bloco só roda quando `dominio` já é aquele valor.

### Forma E — multi-linha (1 ponto)

Linhas ~200-205:

```python
            .filter(
                Ativo.deleted_at.is_(None),
                Ativo.dominio == Dominio.IMPRESSORA,
                SuprimentoImpressora.deleted_at.is_(None),
                SuprimentoImpressora.estoque_atual <= SuprimentoImpressora.estoque_minimo,
            )
```
→ `*cond,` no lugar das duas primeiras linhas.

### `_parque` (2 pontos)

- Assinatura: `def _parque(db, dominio, cond)`
- Chamada: `parque = _parque(db, dominio, cond)`
- Dentro: o `.filter(...)` de `forma_aquisicao` e o `sum(Ativo.valor)`

## Passo 5 — imports

```python
from datetime import date, datetime, timezone     # `date` é novo
from sqlalchemy import and_, func, ...            # `and_` é novo
from app.models.enums import Dominio, FormaAquisicao, TipoMov
```

**Cuidado:** `from __future__ import annotations` faz o import faltante
**não** estourar no boot — só na primeira requisição. Um teste que chama o
endpoint pega; um `import` não.

## Passo 6 — a guarda que faltava

Teste que verifica **na fonte** que nenhuma consulta de ativo ficou sem as
condições. É o que pega bloco esquecido:

```python
def test_nenhuma_consulta_de_ativo_sem_filtro():
    fonte = Path("app/routers/graficos.py").read_text(encoding="utf-8")
    i = fonte.find("def _condicoes")
    j = fonte.find("def graficos")
    resto = fonte[:i] + fonte[j:]
    assert "Ativo.dominio ==" not in resto
```

## Passo 7 — o teste que importa

**Comparar dois blocos sob o mesmo filtro.** É o que distingue filtro
completo de filtro parcial:

```python
def test_o_filtro_vale_em_todos_os_blocos(client, auth_headers):
    """Com um filtro que zera o resultado, TODOS os blocos zeram.

    Se algum não zerar, ele ignora o filtro — e é o caso que passa
    despercebido, porque o gráfico continua mostrando número.
    """
    # Cria 2 ativos de plantas diferentes
    # Filtra por uma planta
    # Verifica que status, categoria, localizacao, departamento,
    # valor_categoria e parque contam só 1
```

## O erro das três tentativas — não repita

| # | O que fiz | Por que falhou |
|---|---|---|
| 1 | Substituição textual | Destruiu a linha do próprio helper: `cond = [*cond]` |
| 2 | Ordem invertida | Resolveu o helper, mas só cobria a **forma A** — 7 filtros ficaram |
| 3 | Todas as 5 formas | 11 substituídos, mas um `BinaryExpression` vazou para a resposta |

**A conclusão:** o método de script está condenado. Não pelo padrão — pela
**verificação**. Eu não conseguia ver o resultado antes de aplicar.

**Faça com a ferramenta de edição, um ponto por vez, rodando
`tests/test_relatorio_parque.py` a cada três edições.**

## Baseline

Antes de começar: **985 testes passando**, `ruff` limpo, versão 3.01.0.
Ao terminar, os 985 + os novos têm que passar.
