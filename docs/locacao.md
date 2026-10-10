# Locação de ativos — desenho

O sistema foi construído supondo **compra**: o ativo tem um `valor` e uma
`data_aquisicao`, e o financeiro calcula depreciação linear. No parque real, a
**maioria é locação** — mensalidade, sem patrimônio a depreciar — e a minoria
comprada é legado já depreciado.

Este documento fixa o desenho antes de mexer no modelo.

## Decisões tomadas

| Pergunta | Decisão |
|---|---|
| Mensalidade | **Por contrato** — um contrato cobre vários ativos; o custo por ativo é derivado |
| Prazo | **Tem fim definido**, com **alerta de vencimento** |
| Fim do contrato | **Existe opção de compra** — precisa registrar a transição locado → comprado |

## Modelo

### Nova entidade: `Contrato`

```
contratos
  id
  numero          str(80)   unique   ex.: "2024/117"
  tipo            enum      locacao | comodato | compra
  fornecedor_id   FK fornecedores
  inicio          date
  fim             date | null    null = prazo indeterminado
  valor_mensal    Numeric | null  locação
  valor_total     Numeric | null  compra
  dia_vencimento  int | null  1..31, para o calendário de pagamentos
  observacoes     Text | null
```

### `Ativo` ganha

| Campo | Tipo | Por quê |
|---|---|---|
| `forma_aquisicao` | enum `comprado` \| `locado` | **default `comprado`** — preserva o que já existe sem migração de dado |
| `contrato_id` | FK nullable | O contrato do qual o ativo faz parte |
| `valor_residual` | Numeric nullable | Preço de compra ao fim da locação, quando houver |

`valor` e `data_aquisicao` **continuam existindo**, mas passam a valer só para
`comprado`. Não renomear: renomear obrigaria a migrar todo o histórico e
quebrar relatórios antigos.

## Regras financeiras

### Comprado

Como hoje. `depreciacao()` linear sobre `valor`, a partir de `data_aquisicao`,
pela taxa do domínio (`TAXA_PADRAO`: TI 20%/ano, impressora 10%/ano).

TCO = `valor` + manutenção + consumíveis − `valor_residual`.

### Locado

**Sem depreciação.** Não há patrimônio — a depreciação mediria o quê?

Custo acumulado = `meses_decorridos × custo_mensal_do_ativo`.

TCO = custo acumulado + manutenção + consumíveis.
(Não se soma `valor`: numa locação ele não existe.)

### O rateio — e o ponto que engana

O custo por ativo de um contrato é:

```
custo_mensal_do_ativo = contrato.valor_mensal / nº de ativos ATIVOS no contrato
```

**Tem que ser calculado na hora, nunca gravado.** Se um equipamento é devolvido
no meio do contrato, a mensalidade **não cai** — o custo dos que ficaram sobe.
Um valor gravado mentiria a partir da primeira devolução.

Devem entrar na contagem apenas ativos com `deleted_at IS NULL` e que ainda
pertençam ao contrato. Equipamento já comprado (transição feita) sai da conta.

### Transição locado → comprado

Quando a opção de compra é exercida:

1. `forma_aquisicao` vira `comprado`
2. `valor` recebe o preço de compra (`valor_residual`)
3. `data_aquisicao` recebe a data da compra
4. O ativo sai do rateio do contrato
5. **A depreciação começa a contar dessa data** — não retroage ao início da
   locação. Antes disso não era patrimônio da empresa.

Registrar como movimentação, com autor e data. É uma mudança de natureza
patrimonial, e precisa de rastro.

## Alerta de vencimento

Locação com prazo: devolver atrasado gera multa. É o aviso mais valioso deste
tipo de parque.

| Antecedência | Nível |
|---|---|
| 90 dias | informativo |
| 60 dias | atenção |
| 30 dias | urgente |
| vencido | crítico |

Reaproveitar o módulo de notificações existente
(`app/routers/notificacoes.py`), que já tem sino e contagem.

**Cuidado:** a data de fim é do **contrato**, não do ativo. Um contrato com 50
notebooks gera **um** alerta, não 50 — senão o sino vira ruído e ninguém olha.

## O que muda no código

| Arquivo | Mudança |
|---|---|
| `app/models/contrato.py` | **novo** — o modelo acima |
| `app/models/core.py` | `Ativo` ganha os 3 campos |
| `app/models/enums.py` | `FormaAquisicao`, `TipoContrato` |
| `app/services/financeiro.py` | separar os dois caminhos; `depreciacao` só para comprado; rateio para locado |
| `app/routers/contratos.py` | **novo** — CRUD + ativos vinculados + exercer compra |
| `app/routers/financeiro.py` | resumo do parque com os dois tipos |
| `frontend/js/views/contratos.js` | **novo** — tela de contratos |
| `frontend/js/views/financeiro.js` | separar comprado × locado |
| `frontend/js/views/ativos.js` | campo forma de aquisição + contrato |

## Armadilhas

**1. `valor` tem dois significados.** Para comprado é o preço; para locado não
existe. Todo código que lê `valor` precisa checar `forma_aquisicao` primeiro —
e o padrão do campo é `comprado`, então o legado continua correto.

**2. Depreciação de locado é zero, não "não calculada".** Se `depreciacao()`
devolver `None` para locado, todo relatório que soma precisa tratar `None`.
Melhor devolver `0` e documentar.

**3. `data_garantia` não se aplica a locado.** Quem cobre é o fornecedor, pelo
contrato. Não inventar data.

**4. O resumo do parque não pode somar as duas naturezas cruas.** "Valor total
do parque" misturando comprado e locado é uma métrica sem sentido. Separar:
*valor patrimonial* (comprado) e *custo mensal* (locado).

## Ordem de implementação

1. Enums + modelo `Contrato` + campos no `Ativo` + migração
2. `financeiro.py` com os dois caminhos + testes
3. Router de contratos + exercer compra + testes
4. Alerta de vencimento + testes
5. Telas: contratos, financeiro separado, campo no cadastro de ativo

Cada passo fecha com os testes passando. O passo **2** é o que muda os números
que a gestão olha — é o que não pode sair errado.
