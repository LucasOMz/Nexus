# Inventário de Software e Licenças

Documento de projeto. Ainda **não implementado** — este é o desenho.

---

## 1. Por que um inventário separado

Seria mais barato acrescentar um campo em `Ativo`. Não serve, por três motivos:

**Uma licença não é um bem único.** Você compra "50 seats de Office" e instala
em 63 máquinas. O ativo é *a licença*; o que existe fisicamente são *as
instalações*. Modelar isso como um ativo com quantidade não cabe em `Ativo`.

**A chave é um SEGREDO.** Todo o resto do sistema guarda dado patrimonial. Um
número de série vazado não faz mal; uma chave de volume da Microsoft vazada
permite uso ilegal e pode ser **revogada pelo fabricante**. Isso muda os
requisitos de acesso, de criptografia e de auditoria.

**A contagem é o produto.** O valor deste inventário não está na lista — está
na comparação **instalado × licenciado**. É o número que responde "estamos em
risco numa auditoria?".

---

## 2. As três entidades

```
Software (o produto)          Licença (o direito)         Atribuição (o uso)
─────────────────────         ───────────────────         ──────────────────
nome, fabricante              software_id                 licenca_id
versao, categoria             tipo, chave (CIFRADA)       ativo_id     ┐ um dos
plataforma                    seats, validade             usuario_id   ┘ dois
                              valor, contrato_id
```

**Por que três, e não duas.** Uma `Licença` pode ter várias `Atribuições`
(50 seats = 50 linhas). E a `Atribuição` aponta para um **ativo** ou um
**usuário** — porque nem toda licença é por máquina: Adobe e Microsoft 365
são por pessoa.

### Decisões de modelagem

| Campo | Decisão | Motivo |
|---|---|---|
| `seats` | inteiro, obrigatório | sem ele não há como comparar com instalações |
| `tipo` | `perpetua`, `assinatura`, `oem`, `volume`, `open_source`, `trial` | cada um tem regra de custo e validade diferente |
| `validade` | nula em perpétua e open source | perpétua não vence |
| `contrato_id` | FK para `Contrato` (reuso) | assinatura SaaS **é** locação — já existe o modelo |
| `chave_cifrada` | `LargeBinary` | ver seção 3 |
| `chave_hash` | `String`, indexado | para detectar chave duplicada **sem** decifrar |

**O `chave_hash` merece explicação.** Para responder "esta chave já está
cadastrada?" seria preciso comparar o texto — o que obriga a decifrar tudo a
cada verificação. Um hash (SHA-256 do valor normalizado) permite achar
duplicata **sem nunca decifrar**. O hash não permite recuperar a chave.

---

## 3. A chave da licença — o núcleo deste módulo

### O princípio

> A chave é tratada como **senha**, não como dado de cadastro.

### Criptografia de verdade

```python
from cryptography.fernet import Fernet

# A chave MESTRA vive FORA do banco.
CHAVE_MESTRA = os.environ["NEXUS_CHAVE_LICENCAS"]   # 32 bytes base64
fernet = Fernet(CHAVE_MESTRA)

cifrada = fernet.encrypt(chave.encode())      # grava no banco
texto   = fernet.decrypt(cifrada).decode()    # só na hora de mostrar
```

### ⚠️ A regra que separa criptografia de teatro

**A chave mestra NÃO pode ficar no banco de dados.**

Se ela estiver numa tabela ao lado da chave cifrada, quem lê o banco lê as
duas — e a cifra não protegeu nada. Foi apenas ofuscação com passos extras.

| Onde a chave mestra vive | Serve? |
|---|---|
| Variável de ambiente / arquivo de segredo fora do banco | ✅ |
| Tabela do banco | ❌ teatro |
| Código-fonte versionado | ❌ pior ainda |
| Junto no backup do banco | ❌ anula o backup |

**Consequência prática, e é importante:** se a chave mestra se perde, **as
chaves de licença não podem ser recuperadas**. O projeto precisa deixar isso
explícito — no `.env.example`, na tela e no README:

> *"Guarde `NEXUS_CHAVE_LICENCAS` num cofre separado. Sem ela, as chaves
> cadastradas são irrecuperáveis — e o backup do banco não ajuda, porque a
> chave não está nele."*

### Rotação da chave mestra

Um campo `chave_versao` em cada licença permite trocar a chave mestra sem
perder dado: a versão 1 usa a chave antiga, a 2 a nova, e um comando
re-cifra tudo. **Sem isso, trocar a chave mestra significa recadastrar todas
as licenças** — e ninguém troca.

---

## 4. O acesso à chave

### Permissão separada

Ver a chave é **diferente** de ver a licença. Duas permissões:

| Permissão | O que dá |
|---|---|
| `licencas` | vê a lista, o software, a validade, o custo, os seats |
| `licencas.ver_chave` | **revela** o conteúdo da chave |

**A maioria das pessoas precisa da primeira, não da segunda.** Saber que
existem 50 licenças de Office é útil; ler a chave, não.

### O padrão é mascarado

```
Lista:   Microsoft Office LTSC 2021 · 50 seats · chave ••••-••••-••••-4F2A
Botão:   [ Revelar ]     ← só com a permissão; some sem ela
```

No banco, para o hash e para o índice, guarda-se o **sufixo** em claro
(`ultimos4`). É o suficiente para o operador conferir de qual licença se
trata sem expor nada.

### Revelar é um evento auditado

```python
def revelar_chave(licenca, user, db):
    registrar_auditoria(
        acao="revelar_chave_licenca",
        recurso="licenca", recurso_id=licenca.id,
        detalhe="Chave revelada",          # o VALOR não entra
    )
    return decifrar(licenca)
```

---

## 5. 🚨 A armadilha que já existe no sistema

**A auditoria guarda um `diff` do antes e depois de cada alteração.** E o
`diff` **não passa por anonimização** — é uma pendência conhecida e documentada
neste projeto (dado pessoal sobrevive ao prazo de retenção da LGPD).

Leve isso para cá e o resultado é grave:

```python
# Se a chave entrar no diff, ela fica gravada PARA SEMPRE:
{
  "antes":  {"chave": None},
  "depois": {"chave": "XXXXX-XXXXX-XXXXX-XXXXX"}   # ← em claro, permanente
}
```

E a auditoria é **imutável por encadeamento de hash**. Não dá para editar
depois. **Uma chave que entra no `diff` está vazada de forma permanente e
irreversível.**

### A regra

Todo campo sensível precisa estar numa lista de **exclusão do diff**, no
serviço de auditoria:

```python
CAMPOS_FORA_DO_DIFF = {
    "chave_cifrada", "chave", "chave_hash",
}
```

E o registro de auditoria da licença deve guardar apenas **que a chave mudou**:

```python
"depois": {"chave": "<alterada>"}    # nunca o valor
```

**Este é o requisito mais importante do módulo.** Mais até que a criptografia:
cifra protege o banco; a exclusão do diff protege o histórico — e o histórico
não pode ser corrigido depois.

---

## 6. Onde mais a chave pode vazar

Cada um destes precisa de tratamento explícito. Não é paranoia: são os caminhos
por onde o dado sai do sistema.

| Caminho | Risco | Tratamento |
|---|---|---|
| **Exportação CSV** | o arquivo circula por e-mail | coluna da chave **sai mascarada**; exportar em claro exige a permissão e é auditado |
| **Relatórios PDF** | idem | nunca incluir |
| **Log da aplicação** | `logger.info(licenca)` grava tudo | `__repr__` do modelo **não** inclui a chave |
| **Mensagem de erro** | `ValidationError` ecoa o valor | validar formato, nunca devolver o conteúdo |
| **Backup do banco** | o arquivo `.bak` fica por aí | cifrado — e a chave mestra **fora** dele |
| **Busca global (Ctrl+K)** | indexa e exibe | **não** indexar `chave`; buscar por nome do software |
| **`diff` da auditoria** | ver seção 5 | excluído |
| **Resposta da API** | schema devolve tudo | `LicencaOut` **não tem** o campo `chave`; só `chave_mascarada` |

**O último é o mais fácil de errar.** Um `model_config = ConfigDict(from_attributes=True)`
com o modelo inteiro devolve a chave sem ninguém perceber. O schema de saída
precisa **omitir** o campo — não basta não usá-lo.

---

## 7. Compliance:instalado × licenciado

**É o motivo de o módulo existir.**

```
Software: Microsoft Office LTSC 2021
  Licenciado ....... 50 seats
  Instalado ........ 63       ← OCS Inventory já reporta isso
  ─────────────────────────────
  Situação ......... ⚠️ 13 ACIMA DO LICENCIADO
```

### Por que o OCS resolve metade do problema

O sistema **já tem** OCS Inventory integrado (`app/routers/ocs.py`). Ele
reporta o software instalado em cada máquina. Cruzar isso com as licenças
compradas dá o número que interessa — **sem digitação**.

### Como comparar dois nomes diferentes

O OCS reporta `Microsoft Office LTSC Professional Plus 2021`; a licença está
cadastrada como `Office 2021`. Comparar por igualdade não acha nada.

Cada `Software` guarda uma lista de **padrões de reconhecimento**:

```python
padroes = ["microsoft office*2021", "office ltsc*"]
```

E o relatório de conformidade cruza por esses padrões. Sem isso, o cruzamento
com o OCS é inútil na prática — foi o que motivou o campo.

### Os quatro estados

| Estado | Significado | Tom |
|---|---|---|
| **Conforme** | instalado ≤ licenciado | verde |
| **Excedente** | instalado > licenciado | **vermelho** — risco em auditoria |
| **Ocioso** | instalado < licenciado | âmbar — pagando por seat sem uso |
| **Sem licença** | instalado > 0, licenciado = 0 | **vermelho** — uso irregular |

**"Ocioso" é tão valioso quanto "Excedente".** Comprar 50 e usar 31 é dinheiro
parado — e o sistema só mostra isso se comparar os dois lados.

---

## 8. Assinatura × perpétua — espelha locação × comprado

O sistema já resolveu este problema uma vez. **É o mesmo desenho:**

| Locação (já feito) | Licença |
|---|---|
| Equipamento locado não é patrimônio | Assinatura **não é** ativo imobilizado |
| Custo é a mensalidade do contrato | Custo é a mensalidade da assinatura |
| `Contrato` com `valor_mensal` | **o mesmo `Contrato`** |
| Perpétua ≈ comprado | Licença perpétua tem valor e deprecia |

**Reusar `Contrato` é a decisão certa.** Uma assinatura de Microsoft 365 é,
do ponto de vista do sistema, um contrato com mensalidade, vigência e
vencimento. O alerta de contrato a vencer **já funciona** e passa a valer para
assinaturas de software automaticamente.

E o **custo do parque** (`resumo_do_parque`) ganha uma terceira natureza:

```
Comprado     → patrimônio que deprecia
Locado       → mensalidade de equipamento
Assinatura   → mensalidade de software    ← o novo
```

**Não somar as três.** Patrimônio com mensalidade não dá número com
significado — foi a lição do módulo financeiro.

---

## 9. A tela dedicada

Pedido: *"uma tela dedicada somente para este inventário"*. Ela tem **quatro
áreas**, e a primeira é a que importa:

### 9.1 Conformidade (a tela de abertura)

```
┌─ Conformidade de licenças ────────────────────────────────────┐
│                                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐         │
│  │   142    │ │    3     │ │    8     │ │  R$ 4.280│         │
│  │ TÍTULOS  │ │ EXCEDENTE│ │ OCIOSO   │ │ /MÊS     │         │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘         │
│                                                               │
│  ⚠️ 3 softwares instalados acima do licenciado                │
│  ┌──────────────────────┬──────────┬──────────┬────────────┐ │
│  │ SOFTWARE             │ LICENC.  │ INSTALADO│ SITUAÇÃO   │ │
│  │ Microsoft Office 2021│   50     │    63    │ ⚠️ +13     │ │
│  │ Adobe Acrobat Pro    │   10     │    14    │ ⚠️ +4      │ │
│  │ AutoCAD 2024         │    5     │     5    │ ✅ conforme │ │
│  └──────────────────────┴──────────┴──────────┴────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

**Abre por aqui, não pela lista.** Quem entra nesta tela quer saber se está em
risco — não quantos títulos existem.

### 9.2 Software

Lista com busca, filtro por fabricante e por situação. Cada linha mostra o
saldo (licenciado − instalado) com cor.

### 9.3 Licenças

As chaves, **mascaradas**. Coluna de validade com alerta. Botão *Revelar* só
para quem tem a permissão — e o clique fica na auditoria.

### 9.4 Atribuições

Quem usa o quê. Duas visões:
- **Por licença** — os 50 seats, e quem está em cada um
- **Por ativo/usuário** — o que esta máquina tem instalado e licenciado

A segunda é a que responde "posso formatar esta máquina?".

---

## 10. Alertas

| Alerta | Quando | Nível |
|---|---|---|
| Licença vencendo | 60 dias | âmbar |
| Assinatura vencendo | 30 dias | vermelho |
| Instalado > licenciado | sempre | **vermelho** |
| Seat ocioso | > 20% sem uso por 90 dias | âmbar |
| Software sem licença | instalado e não licenciado | **vermelho** |

**O último é o mais grave e o mais fácil de não ver.** Um software instalado
em 30 máquinas sem nenhuma licença cadastrada não aparece em nenhum relatório
de conformidade tradicional — porque não há linha de licença para comparar.

A tela precisa de uma seção **"Instalado e não licenciado"**, alimentada só
pelo OCS.

---

## 11. Reuso — o que já existe e serve

| Já existe | Como o software usa |
|---|---|
| `Contrato` | assinatura SaaS, com mensalidade e vencimento |
| `notificacoes._contratos_vencendo` | passa a alertar assinatura também |
| `auditoria_cadeia` | registro de revelação da chave |
| `financeiro.resumo_do_parque` | terceira natureza: assinatura |
| `ocs.py` | a fonte do "instalado" |
| `busca.py` | indexa **nome do software**, nunca a chave |
| `Ativo` | a atribuição aponta para um ativo |
| `Usuario` | a atribuição aponta para uma pessoa |
| `planta.py` / `aplicar_filtro` | multi-tenant por linha |
| Padrão `_condicoes` (relatórios) | filtros valendo em todos os blocos |

**Quase nada é novo.** O que é novo de verdade é: a cifra, a exclusão do
`diff` e o cruzamento com o OCS.

---

## 12. O que NÃO fazer

| Não | Por quê |
|---|---|
| Guardar a chave em claro | é um segredo; vaza em backup, log e exportação |
| Cifrar com chave no mesmo banco | teatro — quem lê o banco lê as duas |
| Deixar a chave no `diff` da auditoria | **permanente e irreversível** — a cadeia é imutável |
| Devolver a chave no schema da API | vaza em toda listagem, para todo mundo |
| Indexar a chave na busca global | transforma a busca em vazamento |
| Incluir a chave no CSV por padrão | o arquivo circula por e-mail |
| Somar patrimônio + locação + assinatura | número sem significado |
| Comparar software por nome exato com o OCS | nunca casa, e o módulo perde a utilidade |
| Tratar assinatura como ativo imobilizado | não é patrimônio — é serviço |

---

## 13. Ordem de implementação

```
1. Modelos e enums
     Software, Licenca, AtribuicaoLicenca
     enums: TipoLicenca, SituacaoLicenca
2. Cifra
     app/core/segredos.py — cifrar/decifrar, versão da chave
     NEXUS_CHAVE_LICENCAS no .env.example, com o aviso de irrecuperabilidade
3. Exclusão do diff  ← ANTES de qualquer rota
     auditoria: CAMPOS_FORA_DO_DIFF
     Teste que grava uma licença e confere que a chave NÃO está na auditoria
4. API
     schemas que OMITEM a chave
     permissões: licencas, licencas.ver_chave
     rotas CRUD + /revelar (auditado) + /conformidade
5. Cruzamento com o OCS
     campo `padroes` no Software + relatório de conformidade
6. Tela dedicada
     4 áreas, abrindo por Conformidade
7. Financeiro
     terceira natureza: assinatura
8. Busca e relatórios
     nome no índice; filtros pelo padrão dos relatórios
```

**O passo 3 vem antes do 4 de propósito.** Se as rotas existirem primeiro, a
chave entra na auditoria nos primeiros testes — e **não sai mais**.

---

## 14. Pendências que isto herda

| Pendência | Efeito aqui |
|---|---|
| `diff` da auditoria não é anonimizado | **crítico** — ver seção 5 |
| Expurgo LGPD não roda sozinho | atribuição a usuário é dado pessoal |
| Selo do certificado vive no banco | quem controla o servidor reemite |
| Limitador por processo | relevante se `/revelar` for exposto |
| Multi-tenant por linha | software é global ou por planta? **decidir** |

**A última é uma decisão em aberto.** Uma licença de volume da empresa toda
não pertence a uma planta. Mas uma licença comprada pela filial, sim. O
caminho provável é `planta_id` anulável: nulo = corporativo.
