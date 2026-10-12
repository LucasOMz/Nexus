# Nexus

**Controle de patrimônio de TI e impressoras.**

Sabe quando alguém pergunta *"quantos notebooks nós temos?"* e ninguém sabe
responder com certeza? O Nexus existe para isso não acontecer.

Ele registra **o que a empresa tem**, **onde está**, **quem está usando** e
**quanto custa** — e mantém isso atualizado sem depender da memória de
ninguém.

---

## O que ele resolve

| A pergunta | A resposta no Nexus |
|---|---|
| Quantos equipamentos temos e onde estão? | Lista completa, por local, setor e responsável |
| Quem está com este notebook? | Histórico de empréstimo, com data e devolução |
| Quanto vale o nosso parque? | Valor de compra, depreciação e valor atual |
| Quanto gastamos por mês? | Separa o que foi **comprado** do que é **alugado** |
| Temos licença para todo esse software? | Cruza o instalado com o comprado |
| Quais garantias estão vencendo? | Alerta de 90, 60 e 30 dias |
| Quem apagou este equipamento do sistema? | Auditoria — todo registro tem autor e data |

---

## Os três inventários

O sistema separa o que é de naturezas diferentes, porque somar coisas
diferentes produz número sem sentido:

**🖥️ TI** — notebooks, desktops, monitores, periféricos.

**🖨️ Impressoras** — equipamentos, suprimentos, contador de páginas.

**💿 Software e licenças** — o que está instalado contra o que foi comprado.
É o módulo que responde *"estamos em risco numa auditoria?"*

---

## O dia a dia

### Chegar e registrar

Cada equipamento recebe um **QR Code** que vai colado nele. A partir daí,
basta ler com o celular para abrir a ficha — sem procurar patrimônio na lista.

O QR pode ser **impresso em impressora térmica**, comum em almoxarifado, ou em
folha comum.

### Movimentar, emprestar, manter

Três coisas que acontecem toda semana e que o sistema registra:

- **Movimentação** — entrou, saiu, mudou de lugar
- **Empréstimo** — quem levou, quando devolve (com aviso de atraso)
- **Manutenção** — o que quebrou, o que foi feito, quanto custou

### Conferir

A **contagem** é o inventário físico: o sistema gera a lista, você percorre os
locais conferindo item por item, e as divergências ficam registradas.

### Dar baixa

Quando um equipamento sai de vez, ele precisa de destino — venda, sucata,
doação ou perda. O sistema emite um **certificado de descarte** com o motivo,
o responsável e o destinatário.

---

## O que a gestão vê

### Financeiro

```
Comprado (patrimônio)      Locado (serviço)      Software (assinatura)
R$ 60.000                  R$ 8.500/mês          R$ 1.665/mês
```

**As três naturezas nunca são somadas.** Equipamento alugado não é patrimônio
da empresa — não deprecia e não entra no valor. Somar tudo daria um "valor do
parque" que não corresponde a nada.

### Relatórios

Gráficos de composição, distribuição por setor, garantias vencendo e a
evolução dos custos.

Os **filtros valem para o relatório inteiro** — período, unidade, forma de
aquisição e contrato. Não existe gráfico filtrado ao lado de gráfico sem
filtro: os números pareceriam certos e não seriam.

### Contratos de locação

O custo mensal é **do contrato**, e o valor por equipamento é calculado
dividindo pelos ativos vivos. Devolver um equipamento não reduz a fatura — o
custo dos que ficam sobe, e o sistema mostra isso atualizado.

Quando o contrato vence, aparece no sino. Se houver opção de compra, o
equipamento passa de locado para comprado sem perder o histórico.

---

## Segurança

**Cada pessoa vê o que precisa.** Um técnico pode ter acesso a Ativos e
Manutenções sem ver o Financeiro. As permissões são configuradas usuário por
usuário.

**Nada é apagado de verdade.** Uma exclusão fica registrada com autor e data,
e o registro original é preservado.

**A auditoria não pode ser editada.** Cada lançamento é encadeado
matematicamente ao anterior — alterar uma linha quebra a corrente, e a
verificação acusa.

**Chaves de licença são tratadas como senha.** Ficam cifradas, aparecem
mascaradas na tela, e revelar uma exige permissão própria — com registro de
quem revelou e quando.

**Verificação em duas etapas** disponível, com aplicativo autenticador.

---

## Quem usa o quê

| Perfil | O que faz |
|---|---|
| **Almoxarifado / TI** | Cadastra, movimenta, empresta, abre manutenção, imprime etiquetas |
| **Gestão** | Acompanha custos, contratos, garantias e relatórios |
| **Administrador** | Cria usuários, define permissões, configura o sistema |
| **Auditoria** | Consulta o histórico sem poder alterar nada |

---

## Como começar

**Instalação em um comando** (Windows):

```
run.bat
```

O sistema sobe, cria a base e exibe o endereço de acesso. No primeiro acesso,
use o usuário administrador e **troque a senha** — o sistema pede.

**Primeiros passos depois de entrar:**

1. Cadastre as **unidades** e os **setores** da empresa
2. Crie os **usuários** e defina o que cada um pode ver
3. Importe ou cadastre os equipamentos
4. Imprima as **etiquetas** e cole nos equipamentos
5. Faça a primeira **contagem** para conferir

---

## Onde encontrar mais

| Assunto | Onde |
|---|---|
| Instalação, Docker, servidor, impressão, backup | [docs/operacao.md](docs/operacao.md) |
| Como o módulo de software funciona | [docs/software.md](docs/software.md) |
| Como a locação funciona | [docs/locacao.md](docs/locacao.md) |

---

## Requisitos

**Para usar:** um navegador. Funciona no computador e no celular, e pode ser
instalado como aplicativo.

**Para instalar:** Windows, Linux ou Docker. Python 3.11 ou superior.
Impressora térmica é opcional — as etiquetas também saem em folha comum.

---

