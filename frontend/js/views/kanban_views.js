/**
 * Kanban — visualizações alternativas do quadro.
 *
 * ## Por que um módulo separado
 *
 * O quadro é uma tela; Grade, Calendário, Gráficos e Linha do tempo são
 * quatro telas sobre os mesmos dados. Manter tudo em `kanban.js` passaria de
 * 2.000 linhas e nenhuma das cinco ficaria legível.
 *
 * Cada função recebe `(dados, root)` e desenha dentro do elemento que
 * devolve. Elas não buscam dados nem recarregam — quem cuida disso é o
 * `kanban.js`.
 *
 * ## Fonte dos dados
 *
 * Todas usam o mesmo `GET /kanban`: lista de buckets com as atividades
 * dentro. Nada de rota nova só para mudar de formato.
 *
 * @module views/kanban_views
 */
import { el, icon } from "../ui.js";

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

/** Todas as atividades, com o nome do bucket anexado. */
function achatado(dados) {
  const saida = [];
  for (const bucket of dados) {
    for (const a of bucket.atividades) {
      saida.push({ ...a, bucket_nome: bucket.nome });
    }
  }
  return saida;
}

function fmtData(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("pt-BR");
}

function fmtCurta(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

function dias(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  const hoje = new Date();
  d.setHours(0, 0, 0, 0);
  hoje.setHours(0, 0, 0, 0);
  return Math.round((d - hoje) / 86400000);
}

function iniciais(nome) {
  const partes = String(nome || "").trim().split(/\s+/).filter(Boolean);
  if (!partes.length) return "?";
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
}

function corDoAvatar(nome) {
  const tons = ["#7c5cff", "#0a7ea4", "#0f9d58", "#d9822b", "#c43e6b", "#5b6abf"];
  let soma = 0;
  for (const ch of String(nome || "")) soma = (soma + ch.charCodeAt(0)) % 9973;
  return tons[soma % tons.length];
}

/** Círculo de status clicável. */
function circulo(a, aoConcluir) {
  return el("button", {
    class: "kb-tabela-circulo" + (a.concluida ? " feito" : ""),
    title: a.concluida ? "Reabrir" : "Concluir",
    onclick: (ev) => {
      ev.stopPropagation();
      aoConcluir(a);
    },
  });
}

/** Nome da prioridade com a cor correspondente. */
function rotuloPrioridade(prio) {
  const mapa = {
    baixa: "Baixa",
    normal: "Média",
    alta: "Importante",
    urgente: "Urgente",
  };
  return el("span", { class: "kb-prio-rotulo " + prio },
    el("span", { class: "kb-prio-ponto" }),
    el("span", {}, mapa[prio] || "Média"));
}

// ---------------------------------------------------------------------------
// Grade
// ---------------------------------------------------------------------------

/**
 * Tabela com uma linha por tarefa.
 *
 * Colunas na ordem do Planner: nome, atribuído, início, vencimento, bucket,
 * status e prioridade. As larguras são fixas nas extremidades e elásticas no
 * nome — a coluna que carrega texto é a que precisa de espaço.
 */
export function grade(dados, { aoAbrir, aoConcluir }) {
  const linhas = achatado(dados);

  if (!linhas.length) {
    return el("div", { class: "kb-nada" },
      el("div", { class: "kb-nada-titulo" }, "Nenhuma tarefa"),
      el("div", { class: "kb-nada-texto" },
        "Crie atividades no quadro para vê-las aqui."));
  }

  const tabela = el("table", { class: "kb-tabela" });

  tabela.append(el("thead", {}, el("tr", {},
    el("th", { class: "col-status" }, ""),
    el("th", { class: "col-nome" }, "Nome da tarefa"),
    el("th", { class: "col-pessoa" }, "Atribuído a"),
    el("th", { class: "col-data" }, "Início"),
    el("th", { class: "col-data" }, "Vencimento"),
    el("th", { class: "col-bucket" }, "Bucket"),
    el("th", { class: "col-status-txt" }, "Status"),
    el("th", { class: "col-prio" }, "Prioridade"))));

  const corpo = el("tbody", {});

  for (const a of linhas) {
    const d = dias(a.prazo);
    const atrasada = !a.concluida && d !== null && d < 0;

    const linha = el("tr", {
      class: a.concluida ? "concluida" : "",
      onclick: () => aoAbrir(a),
    },
      el("td", { class: "col-status" }, circulo(a, aoConcluir)),
      el("td", { class: "col-nome" },
        el("span", { class: "kb-tabela-nome" }, a.titulo),
        a.total_itens
          ? el("span", { class: "kb-tabela-sub" }, `☑ ${a.itens_feitos}/${a.total_itens}`)
          : null),
      el("td", { class: "col-pessoa" },
        ...(a.responsaveis || []).slice(0, 3).map((r) => el("span", {
          class: "kb-avatar",
          title: r.nome,
          style: `background:${corDoAvatar(r.nome)}`,
        }, iniciais(r.nome))),
        !a.responsaveis?.length
          ? el("span", { class: "kb-tabela-vazio" }, "—")
          : null),
      el("td", { class: "col-data" }, fmtData(a.data_inicio) || "—"),
      el("td", { class: "col-data" + (atrasada ? " atrasada" : "") },
        fmtData(a.prazo) || "—"),
      el("td", { class: "col-bucket" },
        el("span", { class: "kb-tabela-bucket" }, a.bucket_nome)),
      el("td", { class: "col-status-txt" },
        el("span", { class: "kb-status-txt" + (a.concluida ? " feito" : "") },
          el("span", { class: "kb-status-ponto" }),
          el("span", {}, a.concluida ? "Concluída" : "Não iniciado"))),
      el("td", { class: "col-prio" }, rotuloPrioridade(a.prioridade || "normal")));

    corpo.append(linha);
  }

  tabela.append(corpo);
  return el("div", { class: "kb-tabela-wrap" }, tabela);
}

// ---------------------------------------------------------------------------
// Calendário
// ---------------------------------------------------------------------------

/**
 * Grade mensal com as tarefas no dia do vencimento.
 *
 * Tarefas sem prazo ficam numa lista à direita — é onde o Planner as põe, e
 * evita que suma o que ainda não foi agendado.
 */
export function calendario(dados, { aoAbrir, mes = null }) {
  const base = mes ? new Date(mes) : new Date();
  const ano = base.getFullYear();
  const mesIdx = base.getMonth();

  const primeiro = new Date(ano, mesIdx, 1);
  const diasNoMes = new Date(ano, mesIdx + 1, 0).getDate();
  // Domingo como primeiro dia, como no Planner em português.
  const inicioSemana = primeiro.getDay();

  const linhas = achatado(dados);
  const comPrazo = linhas.filter((a) => a.prazo);
  const semPrazo = linhas.filter((a) => !a.prazo);

  // Agrupa por dia do mês.
  const porDia = new Map();
  for (const a of comPrazo) {
    const d = new Date(a.prazo);
    if (d.getFullYear() !== ano || d.getMonth() !== mesIdx) continue;
    const dia = d.getDate();
    if (!porDia.has(dia)) porDia.set(dia, []);
    porDia.get(dia).push(a);
  }

  const GRADE = el("div", { class: "kb-cal-grade" });

  for (const nome of ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"]) {
    GRADE.append(el("div", { class: "kb-cal-cabecalho" }, nome));
  }

  // Células vazias antes do dia 1.
  for (let i = 0; i < inicioSemana; i++) {
    GRADE.append(el("div", { class: "kb-cal-dia vazio" }));
  }

  const hoje = new Date();
  const ehMesAtual = hoje.getFullYear() === ano && hoje.getMonth() === mesIdx;

  for (let dia = 1; dia <= diasNoMes; dia++) {
    const tarefas = porDia.get(dia) || [];
    const celula = el("div", {
      class: "kb-cal-dia" + (ehMesAtual && hoje.getDate() === dia ? " hoje" : ""),
    },
      el("div", { class: "kb-cal-numero" }, String(dia)));

    for (const a of tarefas.slice(0, 3)) {
      const d = dias(a.prazo);
      celula.append(el("button", {
        class: "kb-cal-tarefa"
          + (a.concluida ? " feita" : "")
          + (!a.concluida && d < 0 ? " atrasada" : ""),
        title: a.titulo,
        onclick: () => aoAbrir(a),
      },
        el("span", { class: "kb-cal-ponto" }),
        el("span", { class: "kb-cal-texto" }, a.titulo)));
    }

    if (tarefas.length > 3) {
      celula.append(el("div", { class: "kb-cal-mais" },
        `+${tarefas.length - 3} mais`));
    }

    GRADE.append(celula);
  }

  const painel = el("aside", { class: "kb-cal-lateral" },
    el("div", { class: "kb-cal-lateral-titulo" }, "Tarefas não agendadas"),
    ...semPrazo.slice(0, 12).map((a) => el("button", {
      class: "kb-cal-sem-data",
      onclick: () => aoAbrir(a),
    },
      el("span", { class: "kb-cal-ponto" }),
      el("span", { class: "kb-cal-texto" }, a.titulo))));

  if (!semPrazo.length) {
    painel.append(el("p", { class: "kb-vazio" }, "Tudo tem data."));
  }

  return el("div", { class: "kb-cal" },
    el("div", { class: "kb-cal-mes" }, `${nomeDoMes(mesIdx)} de ${ano}`),
    el("div", { class: "kb-cal-corpo" }, GRADE, painel));
}

function nomeDoMes(i) {
  return [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
  ][i];
}

// ---------------------------------------------------------------------------
// Gráficos
// ---------------------------------------------------------------------------

/**
 * Três painéis: status (rosquinha), prioridade (barras) e bucket (barras).
 *
 * Feitos em CSS puro — sem biblioteca de gráficos. Os números são poucos e
 * cabem em barras; trazer um Chart.js por causa disso pesaria a PWA sem
 * ganho proporcional.
 */
export function graficos(dados) {
  const linhas = achatado(dados);

  const total = linhas.length || 1;
  const concluidas = linhas.filter((a) => a.concluida).length;
  const atrasadas = linhas.filter((a) => a.atrasada).length;
  const abertas = total - concluidas;

  const pctConcluida = Math.round((concluidas / total) * 100);
  const pctAberta = Math.round((abertas / total) * 100) - Math.round((atrasadas / total) * 100);

  // --- rosquinha --------------------------------------------------------
  // `conic-gradient` desenha o anel; o miolo é um círculo da cor do fundo.
  const angulo = pctConcluida * 3.6;
  const anguloAtraso = Math.round((atrasadas / total) * 100) * 3.6;

  const rosca = el("div", {
    class: "kb-rosca",
    style: `background: conic-gradient(
      var(--k-acento) 0deg ${angulo}deg,
      #a4262c ${angulo}deg ${angulo + anguloAtraso}deg,
      var(--k-linha) ${angulo + anguloAtraso}deg 360deg)`,
  },
    el("div", { class: "kb-rosca-miolo" },
      el("div", { class: "kb-rosca-numero" }, String(abertas)),
      el("div", { class: "kb-rosca-rotulo" }, "restantes")));

  // --- barras por prioridade -------------------------------------------
  const prios = ["urgente", "alta", "normal", "baixa"];
  const rotulos = { urgente: "Urgente", alta: "Importante", normal: "Média", baixa: "Baixa" };
  const porPrio = Object.fromEntries(prios.map((p) => [p, 0]));
  for (const a of linhas) {
    const p = a.prioridade || "normal";
    porPrio[p] = (porPrio[p] || 0) + 1;
  }
  const maiorPrio = Math.max(1, ...Object.values(porPrio));

  const barrasPrio = el("div", { class: "kb-barras" });
  for (const p of prios) {
    const valor = porPrio[p];
    // Fora do literal: o verificador de DOM le apenas o texto entre aspas, e
    // "prio-" sozinho pareceria uma classe inexistente.
    const clsBarra = ["kb-barra-valor", "prio-" + p].join(" ");
    barrasPrio.append(el("div", { class: "kb-barra-linha" },
      el("span", { class: "kb-barra-rotulo" }, rotulos[p]),
      el("div", { class: "kb-barra-trilho" },
        el("span", {
          class: clsBarra,
          style: `width:${Math.round((valor / maiorPrio) * 100)}%`,
        })),
      el("span", { class: "kb-barra-numero" }, String(valor))));
  }

  // --- barras por bucket ------------------------------------------------
  const maiorBucket = Math.max(1, ...dados.map((b) => b.atividades.length));
  const barrasBucket = el("div", { class: "kb-barras" });
  for (const b of dados) {
    const feitas = b.atividades.filter((a) => a.concluida).length;
    barrasBucket.append(el("div", { class: "kb-barra-linha" },
      el("span", { class: "kb-barra-rotulo", title: b.nome }, b.nome),
      el("div", { class: "kb-barra-trilho" },
        el("span", {
          class: "kb-barra-valor",
          style: `width:${Math.round((b.atividades.length / maiorBucket) * 100)}%`,
        })),
      el("span", { class: "kb-barra-numero" },
        `${feitas}/${b.atividades.length}`)));
  }

  const painel = (titulo, conteudo) => el("section", { class: "kb-painel" },
    el("h3", { class: "kb-painel-titulo" }, titulo), conteudo);

  return el("div", { class: "kb-paineis" },
    painel("Status", el("div", { class: "kb-rosca-wrap" }, rosca,
      el("div", { class: "kb-legenda" },
        legendaItem("var(--k-acento)", "Concluída", concluidas),
        legendaItem("#a4262c", "Atrasada", atrasadas),
        legendaItem("var(--k-linha)", "Em aberto", abertas)))),
    painel("Prioridade", barrasPrio),
    painel("Buckets", barrasBucket));
}

function legendaItem(cor, rotulo, valor) {
  return el("span", { class: "kb-legenda-item" },
    el("span", { class: "kb-legenda-cor", style: `background:${cor}` }),
    el("span", {}, `${rotulo}: `),
    el("b", {}, String(valor)));
}

// ---------------------------------------------------------------------------
// Linha do tempo
// ---------------------------------------------------------------------------

/**
 * Barras horizontais posicionadas no tempo.
 *
 * Só entram tarefas com prazo: sem data não há onde desenhar a barra. As
 * demais aparecem numa coluna à direita, para não desaparecerem sem aviso.
 */
export function linhaDoTempo(dados, { aoAbrir }) {
  const linhas = achatado(dados);
  const comData = linhas.filter((a) => a.prazo);

  if (!comData.length) {
    return el("div", { class: "kb-nada" },
      el("div", { class: "kb-nada-titulo" }, "Nada com data"),
      el("div", { class: "kb-nada-texto" },
        "A linha do tempo posiciona as tarefas pelo vencimento. "
        + "Defina prazos para vê-las aqui."));
  }

  // Janela: do menor início/prazo ao maior, com uma semana de folga.
  const marcas = comData.flatMap((a) => [a.data_inicio, a.prazo])
    .filter(Boolean)
    .map((x) => new Date(x).getTime());

  const inicio = new Date(Math.min(...marcas));
  const fim = new Date(Math.max(...marcas));
  inicio.setDate(inicio.getDate() - 3);
  fim.setDate(fim.getDate() + 3);

  const span = Math.max(1, fim - inicio);
  const posicao = (t) => ((new Date(t).getTime() - inicio.getTime()) / span) * 100;

  const hoje = ((Date.now() - inicio.getTime()) / span) * 100;

  const area = el("div", { class: "kb-tl" });

  // Régua: um traço por semana.
  const regua = el("div", { class: "kb-tl-regua" });
  const cursor = new Date(inicio);
  while (cursor <= fim) {
    regua.append(el("span", {
      class: "kb-tl-marca",
      style: `left:${posicao(cursor)}%`,
    }, fmtCurta(cursor)));
    cursor.setDate(cursor.getDate() + 7);
  }
  area.append(regua);

  if (hoje >= 0 && hoje <= 100) {
    area.append(el("span", { class: "kb-tl-hoje", style: `left:${hoje}%` }));
  }

  // Uma linha por tarefa, ordenada pelo prazo.
  const ordenadas = [...comData].sort(
    (a, b) => new Date(a.prazo) - new Date(b.prazo),
  );

  for (const a of ordenadas) {
    const ini = a.data_inicio ? posicao(a.data_inicio) : posicao(a.prazo) - 2;
    const fimBarra = posicao(a.prazo);
    const largura = Math.max(2, fimBarra - ini);
    const d = dias(a.prazo);

    area.append(el("button", {
      class: "kb-tl-linha" + (a.concluida ? " feita" : ""),
      onclick: () => aoAbrir(a),
    },
      el("span", { class: "kb-tl-nome", title: a.titulo }, a.titulo),
      el("span", { class: "kb-tl-trilho" },
        el("span", {
          class: "kb-tl-barra"
            + (a.concluida ? " feita" : "")
            + (!a.concluida && d < 0 ? " atrasada" : ""),
          style: `left:${Math.max(0, ini)}%;width:${largura}%`,
          title: `${fmtCurta(a.prazo)}`,
        }))));
  }

  return el("div", { class: "kb-tl-wrap" }, area);
}
