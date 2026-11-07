/**
 * Kanban — quadro de atividades.
 *
 * ## Por que um modal próprio
 *
 * O `dialog()` do sistema serve formulário de três campos. Aqui precisa de
 * título editável, abas (Detalhes / Checklist / Responsáveis), rodapé com
 * três ações e campos com borda por sombra. Encaixar isso no diálogo padrão
 * exigiria estender o componente compartilhado — e o pedido é manter o core
 * como está.
 *
 * As classes `kb-*` vivem em `styles.css` e partem dos tokens do tema, então
 * modo escuro e paleta continuam funcionando.
 *
 * ## Subatividades
 *
 * São os itens do checklist dentro do cartão. Cada um é marcável e tem
 * ordem; o progresso aparece na barra do rodapé.
 *
 * @module views/kanban
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, skeleton, emptyState, mostrarErro } from "../ui.js";

let dados = [];
let busca = "";
let usuarios = [];
let filtroPrioridade = "";
let mostrarConcluidas = true;

/** Colunas recolhidas — guardado no navegador, nao no servidor. */
function colunasRecolhidas() {
  try {
    return new Set(JSON.parse(localStorage.getItem("nexus.kanban.recolhidas") || "[]"));
  } catch (e) {
    return new Set();
  }
}

function guardarRecolhidas(conjunto) {
  try {
    localStorage.setItem("nexus.kanban.recolhidas", JSON.stringify([...conjunto]));
  } catch (e) { /* modo privado pode bloquear */ }
}

// ---------------------------------------------------------------------------
// Datas
// ---------------------------------------------------------------------------

function fmtPrazo(iso) {
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

// ---------------------------------------------------------------------------
// Avatares
// ---------------------------------------------------------------------------

function iniciais(nome) {
  const partes = String(nome || "").trim().split(/\s+/).filter(Boolean);
  if (!partes.length) return "?";
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
}

const CORES_PRIORIDADE = {
  baixa: "var(--md-sys-color-outline-variant)",
  normal: "var(--md-sys-color-primary)",
  alta: "#d9822b",
  urgente: "var(--md-sys-color-error)",
};

/**
 * Confirmacao estilizada.
 *
 * O `confirm()` nativo bloqueia a thread, nao segue o tema e mostra o
 * dominio na barra de titulo. 120 linhas de CSS ja existem — usar o
 * navegador para a pergunta mais destrutiva da tela e incoerente.
 */
function confirmar(titulo, mensagem, { rotulo = "Excluir", perigo = true } = {}) {
  return new Promise((resolve) => {
    const fechar = (valor) => {
      fecharModal();
      resolve(valor);
    };

    modal({
      titulo,
      abas: [{
        id: "a",
        rotulo: "Confirmar",
        render: () => el("p", {
          style: "margin:0;font-size:14px;line-height:1.55;white-space:pre-wrap",
        }, mensagem),
      }],
      acoes: [
        { label: "Cancelar", classe: "", onClick: () => fechar(false) },
        {
          label: rotulo,
          classe: perigo ? "perigo" : "cheio",
          onClick: () => fechar(true),
        },
      ],
    });
  });
}

function corDoAvatar(nome) {
  const tons = ["#7c5cff", "#0a7ea4", "#0f9d58", "#d9822b", "#c43e6b", "#5b6abf"];
  let soma = 0;
  for (const ch of String(nome || "")) soma = (soma + ch.charCodeAt(0)) % 9973;
  return tons[soma % tons.length];
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

let modalAberto = null;

/**
 * Abre um modal com abas.
 *
 * @param {object} opcoes
 * @param {string} opcoes.titulo
 * @param {Array<{id: string, rotulo: string, render: Function}>} opcoes.abas
 * @param {Array} opcoes.acoes
 */
function modal({ titulo, abas, acoes }) {
  fecharModal();

  const corpo = el("div", { class: "kb-modal-corpo" });
  const barraAbas = el("div", { class: "kb-tabs" });
  let abaAtiva = abas[0]?.id;

  const trocar = (id) => {
    abaAtiva = id;
    for (const b of barraAbas.children) b.classList.toggle("ativa", b.dataset.aba === id);
    corpo.innerHTML = "";
    const aba = abas.find((a) => a.id === id);
    if (aba) corpo.append(aba.render());
  };

  if (abas.length > 1) {
    for (const a of abas) {
      barraAbas.append(el("button", {
        class: "kb-tab" + (a.id === abaAtiva ? " ativa" : ""),
        "data-aba": a.id,
        onclick: () => trocar(a.id),
      }, a.rotulo));
    }
  }

  const caixa = el("div", { class: "kb-modal" },
    el("div", { class: "kb-modal-topo" },
      el("h2", {}, titulo),
      el("button", {
        class: "kb-fechar", title: "Fechar",
        onclick: () => fecharModal(),
        html: icon("close", 20),
      })),
    abas.length > 1 ? barraAbas : null,
    corpo,
    el("div", { class: "kb-modal-pe" }, ...acoes.map((a) => {
      // Um elemento já montado entra como está — é o caso do espaçador que
      // empurra o "Salvar" para a direita.
      if (a instanceof Node) return a;
      return el("button", {
        class: "kb-btn " + (a.classe || ""),
        onclick: () => a.onClick(fecharModal),
      }, a.label);
    })));

  const fundo = el("div", {
    class: "kb-fundo",
    onclick: (ev) => { if (ev.target === fundo) fecharModal(); },
  }, caixa);

  modalAberto = fundo;
  document.body.append(fundo);

  // Esc fecha — o mesmo atalho do resto do sistema.
  const aoTeclar = (ev) => {
    if (ev.key === "Escape") fecharModal();
  };
  document.addEventListener("keydown", aoTeclar);
  fundo._aoTeclar = aoTeclar;

  trocar(abaAtiva);
  return fundo;
}

function fecharModal() {
  if (!modalAberto) return;
  if (modalAberto._aoTeclar) document.removeEventListener("keydown", modalAberto._aoTeclar);
  modalAberto.remove();
  modalAberto = null;
}

/** Campo com rótulo, no padrão da tela. */
function campo(rotulo, entrada) {
  return el("div", { class: "kb-campo" }, el("label", {}, rotulo), entrada);
}

// ---------------------------------------------------------------------------
// Tela
// ---------------------------------------------------------------------------

export async function renderKanban(root) {
  ctx.setTitle("Kanban");
  ctx.setFab(null);

  root.innerHTML = "";
  root.append(el("div", { class: "kb-carregando" }, skeleton(3)));

  try {
    const [quadro, lista] = await Promise.all([
      api.get("/kanban"),
      api.get("/usuarios").catch(() => []),
    ]);
    dados = Array.isArray(quadro) ? quadro : [];
    usuarios = Array.isArray(lista) ? lista : [];
  } catch (e) {
    root.innerHTML = "";
    root.append(emptyState("relatorios", "Não foi possível carregar", e.message));
    return;
  }

  desenhar(root);
}

function desenhar(root) {
  root.querySelector(".kb")?.remove();
  root.querySelector(".kb-carregando")?.remove();

  const wrap = el("div", { class: "kb" });

  const seletorPrioridade = filtroPrioridade;
  const campoBusca = el("input", {
    type: "search",
    placeholder: "Buscar tarefas…",
    value: busca,
    oninput: (e) => {
      busca = e.target.value.toLowerCase().trim();
      desenhar(root);
      const novo = root.querySelector(".kb-busca input");
      if (novo) {
        novo.focus();
        novo.setSelectionRange(novo.value.length, novo.value.length);
      }
    },
  });

  wrap.append(el("div", { class: "kb-topo" },
    el("div", { class: "kb-busca" },
      el("span", { html: icon("search", 18) }),
      campoBusca),
    el("select", {
      class: "kb-filtro",
      onchange: (ev) => {
        filtroPrioridade = ev.target.value;
        desenhar(root);
      },
    },
      el("option", { value: "" }, "Prioridade: todas"),
      el("option", { value: "urgente" }, "Urgente"),
      el("option", { value: "alta" }, "Alta"),
      el("option", { value: "normal" }, "Normal"),
      el("option", { value: "baixa" }, "Baixa")),

    el("button", {
      class: "kb-btn pequeno tonal",
      title: "Mostrar ou ocultar concluídas",
      onclick: () => {
        mostrarConcluidas = !mostrarConcluidas;
        desenhar(root);
      },
    }, mostrarConcluidas ? "Ocultar concluídas" : "Mostrar concluídas"),

    el("span", { style: "flex:1" }),
    el("button", { class: "kb-btn cheio", onclick: () => criarBucket(root) },
      el("span", { html: icon("plus", 18) }),
      el("span", {}, "Nova coluna"))));

  const todas = dados.flatMap((b) => b.atividades);
  const abertas = todas.filter((a) => !a.concluida).length;
  const atrasadas = todas.filter((a) => a.atrasada).length;

  wrap.append(el("div", { class: "kb-stats" },
    el("span", {}, el("b", {}, String(todas.length)), " atividades"),
    el("span", {}, el("b", {}, String(abertas)), " abertas"),
    el("span", {}, el("b", {}, String(todas.length - abertas)), " concluídas"),
    atrasadas
      ? el("span", {},
          el("span", { class: "kb-ponto", style: "background:var(--md-sys-color-error)" }),
          el("b", {}, String(atrasadas)), " atrasadas")
      : el("span", {}, "nenhuma atrasada")));

  const trilho = el("div", { class: "kb-trilho" });

  if (!dados.length) {
    trilho.append(el("div", {
      style: "padding:40px 24px;text-align:center;color:var(--md-sys-color-on-surface-variant)",
    },
      el("p", { style: "margin:0 0 6px;font-weight:500;font-size:15px" },
        "Nenhuma coluna ainda"),
      el("p", { style: "margin:0;font-size:13px" },
        "Comece com “A fazer”, “Em andamento” e “Concluído”.")));
  }

  for (const bucket of dados) trilho.append(coluna(root, bucket));

  wrap.append(trilho);
  root.append(wrap);
}

function coluna(root, bucket) {
  const col = el("div", {
    class: "kb-coluna",
    ondragover: (ev) => { ev.preventDefault(); col.classList.add("alvo"); },
    ondragleave: () => col.classList.remove("alvo"),
    ondrop: async (ev) => {
      ev.preventDefault();
      col.classList.remove("alvo");
      const id = Number(ev.dataTransfer.getData("text/plain"));
      if (id) await mover(root, id, bucket.id);
    },
  });

  // Cor da coluna: vira o contorno da coluna inteira. Sem cor, transparente.
  col.style.setProperty("--kb-cor", bucket.cor || "transparent");

  const recolhidas = colunasRecolhidas();
  const recolhida = recolhidas.has(String(bucket.id));
  if (recolhida) col.classList.add("recolhida");

  col.append(el("div", { class: "kb-cabecalho" },
    el("button", {
      class: "kb-seta" + (recolhida ? " fechada" : ""),
      title: recolhida ? "Expandir" : "Recolher",
      onclick: () => {
        const atual = colunasRecolhidas();
        if (recolhida) atual.delete(String(bucket.id));
        else atual.add(String(bucket.id));
        guardarRecolhidas(atual);
        desenhar(root);
      },
      html: icon("seta", 14),
    }),
    el("span", { class: "kb-titulo", title: bucket.nome }, bucket.nome),
    el("span", { class: "kb-contagem" }, String(bucket.atividades.length)),
    el("span", { style: "flex:1" }),
    el("button", {
      class: "kb-fechar", title: "Mais opções",
      onclick: (ev) => {
        ev.stopPropagation();
        abrirMenuBucket(root, bucket, ev.currentTarget);
      },
      html: icon("mais", 18),
    })));

  const lista = el("div", { class: "kb-cartoes" });

  const filtradas = bucket.atividades.filter((a) => {
    if (!mostrarConcluidas && a.concluida) return false;
    if (filtroPrioridade && (a.prioridade || "normal") !== filtroPrioridade) return false;
    if (!busca) return true;
    // Busca no titulo E na descricao — a referencia faz o mesmo.
    return (a.titulo || "").toLowerCase().includes(busca)
      || (a.descricao || "").toLowerCase().includes(busca);
  });

  if (!filtradas.length) {
    lista.append(el("p", { class: "kb-vazio" },
      busca ? "Nada encontrado." : "Nenhuma atividade."));
  }

  for (const a of filtradas) lista.append(cartao(root, a));

  col.append(lista, el("button", {
    class: "kb-add",
    onclick: () => criarAtividade(root, bucket.id),
  },
    el("span", { html: icon("plus", 16) }),
    el("span", {}, "Adicionar atividade")));

  return col;
}

function cartao(root, a) {
  const d = dias(a.prazo);
  const selos = [];

  if (a.prazo) {
    const classe = a.concluida ? "" : d < 0 ? " atrasado" : d === 0 ? " hoje" : "";
    const texto = a.concluida
      ? fmtPrazo(a.prazo)
      : d < 0
        ? `Atrasada · ${fmtPrazo(a.prazo)}`
        : d === 0
          ? "Hoje"
          : fmtPrazo(a.prazo);
    selos.push(el("span", { class: "kb-selo" + classe },
      el("span", { html: icon("calendario", 12) }),
      el("span", {}, texto)));
  }

  // Prioridade alta e urgente ganham selo; baixa e normal nao precisam
  // ocupar espaco — o padrao nao merece destaque.
  const prio = a.prioridade || "normal";
  const clsSeloPrio = "kb-selo prio-" + prio;
  if (prio === "urgente" || prio === "alta") {
    selos.push(el("span", { class: clsSeloPrio },
      el("span", { html: icon("bandeira", 12) }),
      el("span", {}, prio === "urgente" ? "Urgente" : "Alta")));
  }

  if (a.total_itens) {
    selos.push(el("span", {
      class: "kb-selo" + (a.itens_feitos === a.total_itens ? " completo" : ""),
    },
      el("span", { html: icon("check", 12) }),
      el("span", {}, `${a.itens_feitos}/${a.total_itens}`)));
  }

  const avatares = (a.responsaveis || []).slice(0, 4).map((r) =>
    el("span", {
      class: "kb-avatar",
      title: r.nome,
      style: `background:${corDoAvatar(r.nome)}`,
    }, iniciais(r.nome)));

  const extras = (a.responsaveis || []).length - avatares.length;
  const pct = a.total_itens ? Math.round((a.itens_feitos / a.total_itens) * 100) : 0;
  const estado = a.concluida ? "feita" : pct > 0 ? "andamento" : "";

  // A classe e montada fora do literal: o verificador de DOM le apenas o
  // texto entre aspas, e "prio-" sozinho pareceria uma classe inexistente.
  const clsCartao = ["kb-cartao", "prio-" + prio, a.concluida ? "concluida" : ""]
    .filter(Boolean).join(" ");

  const card = el("div", {
    class: clsCartao,
    draggable: "true",
    ondragstart: (ev) => {
      ev.dataTransfer.setData("text/plain", String(a.id));
      ev.dataTransfer.effectAllowed = "move";
      card.classList.add("arrastando");
    },
    ondragend: () => card.classList.remove("arrastando"),
  },
    el("input", {
      class: "kb-check",
      type: "checkbox",
      checked: a.concluida ? "checked" : null,
      title: a.concluida ? "Reabrir" : "Concluir",
      onclick: (ev) => ev.stopPropagation(),
      onchange: async () => {
        try {
          await api.post(`/kanban/atividades/${a.id}/concluir`);
          await recarregar(root);
        } catch (e) { mostrarErro(e); }
      },
    }),
    el("div", { class: "kb-corpo" },
      el("div", {
        class: "kb-titulo-cartao",
        onclick: () => abrirAtividade(root, a),
      }, a.titulo),
      a.descricao ? el("div", { class: "kb-desc" }, a.descricao) : null,
      (selos.length || avatares.length)
        ? el("div", { class: "kb-rodape" },
            ...selos,
            el("span", { style: "flex:1" }),
            ...avatares,
            extras > 0 ? el("span", { class: "kb-avatar extra" }, `+${extras}`) : null)
        : null,
      el("div", { class: "kb-progresso" },
        el("span", {
          class: estado,
          style: `width:${a.concluida ? 100 : pct}%`,
        }))),
    el("button", {
      class: "kb-remover",
      title: "Excluir",
      onclick: async (ev) => {
        ev.stopPropagation();
        if (!confirm(`Excluir "${a.titulo}"?`)) return;
        try {
          await api.del(`/kanban/atividades/${a.id}`);
          await recarregar(root);
        } catch (e) { mostrarErro(e); }
      },
      html: icon("trash", 15),
    }));

  return card;
}

// ---------------------------------------------------------------------------
// Dados
// ---------------------------------------------------------------------------

async function recarregar(root) {
  try {
    dados = await api.get("/kanban");
  } catch (e) { mostrarErro(e); }
  desenhar(root);
}

async function mover(root, atividadeId, bucketId) {
  try {
    await api.post(`/kanban/atividades/${atividadeId}/mover`,
      { bucket_id: bucketId, ordem: 0 });
    await recarregar(root);
  } catch (e) { mostrarErro(e); }
}

// ---------------------------------------------------------------------------
// Colunas
// ---------------------------------------------------------------------------

const CORES = [
  { valor: "", nome: "Sem cor" },
  { valor: "#0f9d58", nome: "Verde" },
  { valor: "#0a7ea4", nome: "Azul" },
  { valor: "#7c5cff", nome: "Roxo" },
  { valor: "#d9822b", nome: "Laranja" },
  { valor: "#c43e6b", nome: "Rosa" },
  { valor: "#8a8f98", nome: "Cinza" },
];

let menuAberto = null;

/** Fecha o menu de contexto, se houver. */
function fecharMenu() {
  if (!menuAberto) return;
  document.removeEventListener("mousedown", menuAberto.aoClicar);
  menuAberto.elemento.remove();
  menuAberto = null;
}

/**
 * Menu de três pontos da coluna.
 *
 * Posicionado por `fixed`, a partir do botão que o abriu — assim não é
 * cortado pelo `overflow` do trilho, que é horizontal.
 */
function abrirMenuBucket(root, bucket, ancora) {
  fecharMenu();

  const menu = el("div", { class: "kb-menu" },
    el("button", {
      class: "kb-menu-item",
      onclick: () => { fecharMenu(); renomearBucket(root, bucket); },
    }, el("span", { html: icon("edit", 16) }), el("span", {}, "Renomear")),

    el("button", {
      class: "kb-menu-item",
      onclick: () => { fecharMenu(); alterarCor(root, bucket); },
    }, el("span", { html: icon("paleta", 16) }), el("span", {}, "Alterar cor")),

    el("button", {
      class: "kb-menu-item perigo",
      onclick: () => { fecharMenu(); excluirBucket(root, bucket); },
    }, el("span", { html: icon("trash", 16) }), el("span", {}, "Excluir coluna")));

  document.body.append(menu);

  // Posiciona abaixo do botão, preso à direita da tela se faltar espaço.
  const r = ancora.getBoundingClientRect();
  const largura = 180;
  menu.style.top = `${r.bottom + 6}px`;
  menu.style.left = `${Math.min(r.left, window.innerWidth - largura - 12)}px`;

  const aoClicar = (ev) => {
    if (!menu.contains(ev.target)) fecharMenu();
  };

  // `mousedown` e não `click`: fecha antes de o próximo botão receber o
  // evento, evitando que o menu do anterior fique aberto.
  setTimeout(() => document.addEventListener("mousedown", aoClicar), 0);

  menuAberto = { elemento: menu, aoClicar };
}

function alterarCor(root, bucket) {
  const atual = bucket.cor || "";

  const paleta = el("div", { class: "kb-cores" });
  let escolhida = atual;

  for (const c of CORES) {
    const botao = el("button", {
      class: "kb-cor-opcao" + (c.valor === atual ? " escolhida" : "") +
             (c.valor ? "" : " sem-cor"),
      title: c.nome,
      style: c.valor ? `background:${c.valor}` : "",
      onclick: () => {
        escolhida = c.valor;
        for (const outro of paleta.children) {
          outro.classList.toggle("escolhida", outro === botao);
        }
      },
    }, c.valor ? "" : "—");

    paleta.append(botao);
  }

  modal({
    titulo: "Cor da coluna",
    abas: [{
      id: "a",
      rotulo: "Cor",
      render: () => el("div", {},
        el("p", {
          style: "margin:0 0 14px;font-size:13px;color:var(--md-sys-color-on-surface-variant)",
        }, "A cor aparece como contorno da coluna."),
        paleta),
    }],
    acoes: [
      { label: "Cancelar", classe: "", onClick: (fechar) => fechar() },
      {
        label: "Aplicar",
        classe: "cheio",
        onClick: async (fechar) => {
          try {
            await api.patch(`/kanban/buckets/${bucket.id}`, { cor: escolhida });
            fechar();
            await recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
    ],
  });
}

function criarBucket(root) {
  const entrada = el("input", { placeholder: "Ex.: Em andamento" });

  modal({
    titulo: "Nova coluna",
    abas: [{ id: "a", rotulo: "Coluna", render: () => campo("Nome da coluna", entrada) }],
    acoes: [
      { label: "Cancelar", classe: "", onClick: (fechar) => fechar() },
      {
        label: "Criar",
        classe: "cheio",
        onClick: async (fechar) => {
          const nome = entrada.value.trim();
          if (!nome) { toast("Informe o nome."); return; }
          try {
            await api.post("/kanban/buckets", { nome });
            fechar();
            await recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
    ],
  });
  setTimeout(() => entrada.focus(), 60);
}

function renomearBucket(root, bucket) {
  const entrada = el("input", { value: bucket.nome });

  modal({
    titulo: "Renomear coluna",
    abas: [{ id: "a", rotulo: "Coluna", render: () => campo("Nome da coluna", entrada) }],
    acoes: [
      { label: "Cancelar", classe: "", onClick: (fechar) => fechar() },
      {
        label: "Salvar",
        classe: "cheio",
        onClick: async (fechar) => {
          const nome = entrada.value.trim();
          if (!nome) { toast("Informe o nome."); return; }
          try {
            await api.patch(`/kanban/buckets/${bucket.id}`, { nome });
            fechar();
            await recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
    ],
  });
  setTimeout(() => entrada.select(), 60);
}

async function excluirBucket(root, bucket) {
  const quantas = bucket.atividades.length;
  const aviso = quantas
    ? `A coluna tem ${quantas} atividade(s) e elas serão excluídas junto.`
    : "A coluna está vazia.";
  if (!confirm(`Excluir a coluna "${bucket.nome}"?\n\n${aviso}`)) return;
  try {
    await api.del(`/kanban/buckets/${bucket.id}`);
    await recarregar(root);
  } catch (e) { mostrarErro(e); }
}

// ---------------------------------------------------------------------------
// Atividades
// ---------------------------------------------------------------------------

function criarAtividade(root, bucketId) {
  const entrada = el("input", { placeholder: "O que precisa ser feito?" });
  const prazo = el("input", { type: "date" });

  modal({
    titulo: "Nova atividade",
    abas: [{
      id: "a",
      rotulo: "Detalhes",
      render: () => el("div", {},
        campo("Título", entrada),
        campo("Prazo", prazo)),
    }],
    acoes: [
      { label: "Cancelar", classe: "", onClick: (fechar) => fechar() },
      {
        label: "Criar",
        classe: "cheio",
        onClick: async (fechar) => {
          const titulo = entrada.value.trim();
          if (!titulo) { toast("Informe o título."); return; }
          try {
            await api.post("/kanban/atividades", {
              bucket_id: bucketId,
              titulo,
              prazo: prazo.value ? `${prazo.value}T12:00:00` : null,
            });
            fechar();
            await recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
    ],
  });
  setTimeout(() => entrada.focus(), 60);
}

function abrirAtividade(root, a) {
  let itens = a.itens || [];
  const escolhidos = new Set((a.responsaveis || []).map((r) => r.usuario_id));
  const podeAtribuir = state.papel === "admin";

  const entradaTitulo = el("input", { value: a.titulo });
  const entradaDesc = el("textarea", { rows: "3", placeholder: "Detalhes (opcional)" });
  entradaDesc.value = a.descricao || "";
  const entradaPrazo = el("input", {
    type: "date",
    value: a.prazo ? new Date(a.prazo).toISOString().slice(0, 10) : "",
  });

  // --- aba checklist ----------------------------------------------------
  const listaItens = el("div", {});

  const desenharItens = () => {
    listaItens.innerHTML = "";
    if (!itens.length) {
      listaItens.append(el("p", { class: "kb-vazio" }, "Nenhuma subatividade ainda."));
      return;
    }
    for (const item of itens) {
      listaItens.append(el("div", { class: "kb-item" },
        el("input", {
          type: "checkbox",
          checked: item.feito ? "checked" : null,
          onchange: async () => {
            try {
              const r = await api.post(`/kanban/itens/${item.id}/alternar`);
              itens = r.itens;
              desenharItens();
              await recarregar(root);
            } catch (e) { mostrarErro(e); }
          },
        }),
        el("span", { class: "kb-item-texto" + (item.feito ? " riscado" : "") },
          item.texto),
        el("button", {
          class: "kb-remover", title: "Remover",
          style: "position:static;opacity:1",
          onclick: async () => {
            try {
              await api.del(`/kanban/itens/${item.id}`);
              itens = itens.filter((x) => x.id !== item.id);
              desenharItens();
              await recarregar(root);
            } catch (e) { mostrarErro(e); }
          },
          html: icon("trash", 14),
        })));
    }
  };
  desenharItens();

  const novaSub = el("input", {
    placeholder: "Nova subatividade — Enter para adicionar",
    onkeydown: async (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      const texto = ev.target.value.trim();
      if (!texto) return;
      try {
        const r = await api.post(`/kanban/atividades/${a.id}/itens`, { texto });
        itens = r.itens;
        ev.target.value = "";
        desenharItens();
        await recarregar(root);
      } catch (e) { mostrarErro(e); }
    },
  });

  // --- aba responsáveis -------------------------------------------------
  const listaPessoas = el("div", {});
  if (podeAtribuir) {
    for (const u of usuarios) {
      listaPessoas.append(el("label", { class: "kb-pessoa" },
        el("input", {
          type: "checkbox",
          checked: escolhidos.has(u.id) ? "checked" : null,
          onchange: (ev) => {
            if (ev.target.checked) escolhidos.add(u.id);
            else escolhidos.delete(u.id);
          },
        }),
        el("span", {
          class: "kb-avatar",
          style: `background:${corDoAvatar(u.nome)}`,
        }, iniciais(u.nome)),
        el("span", { class: "kb-pessoa-nome" }, u.nome),
        el("span", { class: "kb-pessoa-email" }, u.email || "")));
    }
    if (!usuarios.length) {
      listaPessoas.append(el("p", { class: "kb-vazio" }, "Nenhum usuário cadastrado."));
    }
  }

  const abas = [
    {
      id: "detalhes",
      rotulo: "Detalhes",
      render: () => el("div", {},
        campo("Título", entradaTitulo),
        campo("Descrição", entradaDesc),
        campo("Prazo", entradaPrazo)),
    },
    {
      id: "checklist",
      rotulo: `Subatividades (${itens.length})`,
      render: () => el("div", {}, listaItens, novaSub),
    },
  ];

  if (podeAtribuir) {
    abas.push({
      id: "responsaveis",
      rotulo: "Responsáveis",
      render: () => listaPessoas,
    });
  }

  modal({
    titulo: "Atividade",
    abas,
    acoes: [
      {
        label: a.concluida ? "Reabrir" : "Concluir",
        classe: "tonal",
        onClick: async () => {
          try {
            await api.post(`/kanban/atividades/${a.id}/concluir`);
            await recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
      { label: "Excluir", classe: "perigo", onClick: async (fechar) => {
        if (!confirm(`Excluir "${a.titulo}"?`)) return;
        try {
          await api.del(`/kanban/atividades/${a.id}`);
          fechar();
          await recarregar(root);
        } catch (e) { mostrarErro(e); }
      } },
      el("span", { class: "kb-espaco" }),
      { label: "Salvar", classe: "cheio", onClick: async (fechar) => {
        try {
          await api.patch(`/kanban/atividades/${a.id}`, {
            bucket_id: a.bucket_id,
            titulo: entradaTitulo.value.trim(),
            descricao: entradaDesc.value.trim() || null,
            prazo: entradaPrazo.value ? `${entradaPrazo.value}T12:00:00` : null,
          });
          if (podeAtribuir) {
            await api.post(`/kanban/atividades/${a.id}/responsaveis`,
              { usuario_ids: [...escolhidos] });
          }
          fechar();
          await recarregar(root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}
