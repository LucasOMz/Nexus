# Módulo de software — o que falta

Plano de trabalho para fechar o módulo. **Ordem por dependência**, não por
tamanho: cada bloco assume que o anterior está pronto.

Estado atual verificado: 19 módulos, 34 telas, 182 rotas, 1187 testes.

---

## Bloco A — Correções pontuais

Sem dependência entre si. Baratas, e destravam o resto.

### T1. Atualizar `docs/software.md`

O documento abre dizendo **"Documento de projeto. Ainda não implementado"** — e
o módulo existe, tem API, tela e 100+ testes.

**Por que primeiro:** um projeto que mente sobre o próprio estado faz qualquer
análise seguinte partir de premissa errada. Custa minutos.

- [ ] Trocar "não implementado" por "implementado"
- [ ] Registrar o que ficou **fora** do plano original: atribuição incompleta,
      métrica ausente, coleta síncrona
- [ ] Apontar para este arquivo como continuação

### T2. Casamento ignorar acento

```
Antivírus   ≠   antivirus*
```

Num sistema em português: `Antivírus`, `Configuração`, `Impressão`,
`Aplicação`. O software não casa, some da contagem e vira **"sem licença"** —
o número mente.

**Decisão necessária antes de codar:** remover acento pode fazer dois
softwares distintos colidirem (`Aplicação` e `Aplicacao` viram o mesmo). O
caminho seguro é **normalizar dos dois lados** — no nome instalado e no
padrão — e **manter o nome original gravado** para exibição.

- [ ] `normalizar()` remove acentos (NFD + descarta combining marks)
- [ ] Teste que quebra de propósito é atualizado/removido
- [ ] Teste com `Antivírus`, `Configuração`, `Impressão`
- [ ] Confirmar que o nome exibido na tela continua com acento

### T3. `reconhecer` corrigir o que já foi reconhecido (parecer #8)

`aplicar_reconhecimento` filtra `software_id.is_(None)` — só preenche vazio.
Mudar um padrão **não conserta** o que foi associado errado.

**Cenário que dói:** alguém cadastrou `Office` com padrão `office*`, e isso
pegou `Office Viewer` também. Corrige o padrão, roda o reconhecer, e **nada
muda** — a associação errada continua.

- [ ] Recasar **todos** os nomes, não só os nulos
- [ ] Só gravar quando o resultado **mudar** (evitar 300 mil UPDATEs)
- [ ] Retornar quantos mudaram e **de → para**, para a tela poder explicar
- [ ] Teste: associação errada é corrigida após mudar o padrão

### T4. Coleta vazia limpar o estado (parecer #7)

`if not itens: resumo.falhas += 1; continue` — uma resposta **válida com zero
programas** é tratada como falha, e o snapshot antigo fica.

**Diferença que importa:** falha de comunicação (não mexer) × resposta válida
com lista vazia (limpar — os programas foram desinstalados).

- [ ] `listar_softwares` distingue `None` (falhou) de `[]` (vazio)
- [ ] Vazio **substitui** a lista da máquina
- [ ] Falha **preserva** e conta em `falhas`
- [ ] Teste para os dois casos

### T5. `atualizado_em` dizer a verdade (parecer #10)

Hoje é `datetime.now()` — a hora em que a tela foi consultada. Dado de três
meses aparece como recém-atualizado.

- [ ] `atualizado_em` = **a coleta mais recente** (`max(coletado_em)`)
- [ ] Campo separado para "consultado em", se a tela precisar
- [ ] Aviso visível quando a coleta tem mais de X dias
- [ ] Teste: sem coleta, `atualizado_em` é nulo — não a hora atual

---

## Bloco B — Fechar o fluxo de licenças

Depende do Bloco A (o casamento tem de estar certo antes de medir).

### T6. Endpoint de listagem de atribuições

**Pré-requisito do T7.** Hoje o backend cria e libera, mas **não lista** — a
tela não tem de onde tirar os dados.

- [ ] `GET /licencas/{id}/atribuicoes` — quem usa o quê
- [ ] `GET /atribuicoes` — a visão inversa: o que este ativo/usuário tem
- [ ] Resolver `ativo_patrimonio` e `usuario_nome` na resposta
- [ ] Filtro por planta (o escopo do resto do módulo)
- [ ] Testes de escopo e de atribuição vazia

### T7. Tela de atribuições

A aba existe, mostra contagem e **não faz nada**. É função central do módulo.

- [ ] Listar as atribuições da licença, com ativo ou pessoa
- [ ] Botão **Atribuir** — seletor de ativo ou usuário
- [ ] Botão **Liberar** em cada linha
- [ ] Bloqueio visível quando os seats acabaram
- [ ] Confirmação antes de liberar

### T8. Histórico de alterações da licença

Reusa a auditoria, que **já registra** tudo. Falta a tela que mostra.

- [ ] Linha do tempo por licença: criada, editada, atribuída, liberada,
      chave revelada
- [ ] Mostrar **quem** e **quando**
- [ ] Nunca mostrar o valor da chave (o diff já grava `<protegido>`)

### T9. Métrica da licença: por dispositivo × por usuário (parecer #11)

**O item mais caro e o mais importante deste bloco.**

Hoje o OCS conta **máquinas** e a licença conta **seats**. Para Microsoft 365
e Adobe, o seat é **por pessoa** — e uma pessoa usa dois dispositivos.
Comparar máquinas com seats **acusa excesso falso**, e a empresa compra
licença que não falta.

- [ ] Enum `MetricaLicenca`: `dispositivo`, `usuario`, `contrato`
- [ ] Campo em `Licenca`, com padrão `dispositivo` (não quebra o existente)
- [ ] `calcular()` compara na **mesma unidade** dos dois lados
- [ ] Instalações contadas por **usuário distinto** quando a métrica for essa
- [ ] Teste: 1 pessoa com 2 máquinas e 1 seat = **conforme**, não excedente
- [ ] A tela explica a métrica de cada linha

### T10. Métricas por fabricante

- [ ] Agrupar custo e seats por fabricante (Microsoft, Adobe, Autodesk…)
- [ ] Gráfico de concentração — quanto do gasto vai para cada fornecedor
- [ ] Base para renegociar contrato com o maior

### T11. Relatório que **explica** a conformidade

O pedido original: *"relatórios que expliquem por que algo está conforme ou
fora de conformidade"*.

- [ ] Por linha: licenciado, instalado, a diferença **e a causa**
- [ ] Quais nomes do OCS casaram e formaram o número
- [ ] Quando não casou: qual padrão tentou e falhou
- [ ] Exportar CSV

> **É o que separa uma lista de um relatório.** Sem a explicação, quem lê
> "13 acima" não sabe se compra licença ou corrige cadastro.

---

## Bloco C — Operação da coleta

Depende do Bloco A (a coleta precisa estar correta antes de ficar frequente).

### T12. Coleta em segundo plano (parecer #9)

Uma requisição por máquina, com pausa. Em 5.000 máquinas, isso estoura o
timeout do proxy e deixa coleta parcial.

- [ ] `POST /ocs/coletar` dispara e **retorna na hora** com um id
- [ ] `GET /ocs/coleta/{id}` — progresso, processadas, falhas
- [ ] Semear no agendador existente (`ocs_agendador`)
- [ ] Botão na tela com barra de progresso
- [ ] Teste: disparar não bloqueia

### T13. Indicar atualidade e falha

- [ ] Última coleta bem-sucedida, por máquina e no geral
- [ ] Aviso quando passar do intervalo esperado
- [ ] Lista das máquinas que falharam, com o motivo
- [ ] Na tela de conformidade: "última coleta há N dias"

### T14. Reconciliação consistente

- [ ] Máquinas que saíram do inventário: instalações órfãs
- [ ] Ativo sem `ocs_id`: nunca será coletado — listar
- [ ] Nomes que nunca casaram: relatório dos top 20, para virar padrão

> O último é o de maior retorno: **transforma o trabalho de cadastro em algo
> guiado pelo dado**, em vez de adivinhação.

---

## Ordem sugerida

```
Bloco A   T1 → T2 → T3 → T4 → T5      correções, ~1 dia
Bloco B   T6 → T7 → T8 → T9 → T10 → T11   ~uma semana
Bloco C   T12 → T13 → T14             ~3 dias
```

**T9 é o que eu faria com mais cuidado.** É modelagem, muda o cálculo de
conformidade, e o erro que ele evita custa dinheiro real.

---

## Decisões que preciso de você

| # | Decisão |
|---|---|
| **T2** | Normalizar acento dos dois lados mantendo o nome original — confirma? |
| **T9** | O padrão de `metrica` fica `dispositivo` para todo mundo, ou os softwares por usuário são cadastrados de novo? |
| **T7** | Atribuir a **pessoa** exige que a pessoa exista como usuário do sistema. É o esperado, ou precisa aceitar nome livre? |

---

## Fora deste plano, e por quê

| Item | Onde |
|---|---|
| Alembic baseline | dívida estrutural, não do módulo |
| 12 tabelas fora do `schema.sql` | idem |
| Riscos de implantação (Compose, HTTPS, fila offline) | transversais ao sistema |
| Agente nas máquinas | produto novo — fase 5 |
