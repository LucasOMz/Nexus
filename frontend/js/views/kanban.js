/**
 * Kanban — quadro de atividades em colunas.
 *
 * ## Estrutura visual
 *
 * Topo com busca e criação de coluna, faixa de números (total, concluídas,
 * atrasadas), e o trilho de colunas. Cada coluna tem cabeçalho próprio e
 * rodapé "Adicionar atividade".
 *
 * O cartão tem a **caixa de concluir à esquerda**, o que faz o gesto mais
 * comum custar um clique — em vez de abrir o detalhe para marcar.
 *
 * ## Arrastar
 *
 * `dragstart` / `dragover` / `drop` do navegador, sem biblioteca. Não há
 * arraste no toque; por isso o cartão abre com um clique e tudo o que muda
 * o cartão está no detalhe.
 *
 * @module views/kanban
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, skeleton, emptyState, mostrarErro } from "../ui.js";

let dados = [];
let busca = "";
let usuarios = [];

// ---------------------------------------------------------------------------
// Datas
// ---------------------------------------------------------------------------

function fmtPrazo(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

/** Dias até o prazo. Negativo = vencido. */
function dias(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  const hoje = new Date();
  d.setHours(0, 0, 0, 0);
  hoje.setHours(0, 0, 0, 0);
  return Math.round((d - hoje) / 86400000);
}

// ---------------------------------------------------------------------------
// Tela
// ---------------------------------------------------------------------------

export async function renderKanban(root) {
  ctx.setTitle("Kanban");
  ctx.setFab(null);

  root.innerHTML = "";
  const alvo = el("div", { class: "kanban-carregando" }, skeleton(3));
  root.append(alvo);

  try {
    const [quadro, lista] = await Promise.all([
      api.get("/kanban"),
      api.get("/usuarios").catch(() => []),
    ]);
    dados = Array.isArray(quadro) ? quadro : [];
    usuarios = Array.isArray(lista) ? lista : [];
  } catch (e) {
    alvo.innerHTML = "";
    alvo.append(emptyState("relatorios", "Não foi possível carregar", e.message));
    return;
  }

  desenhar(root);
}

function desenhar(root) {
  // Remove o quadro anterior **e** o esqueleto de carregamento. Só o quadro
  // era removido antes: o esqueleto ficava órfão no DOM e, a cada redesenho,
  // empilhava mais barras cinzentas acima da barra de busca.
  root.querySelector(".kanban")?.remove();
  root.querySelector(".kanban-carregando")?.remove();

  const wrap = el("div", { class: "kanban" });

  // --- topo -------------------------------------------------------------
  const campoBusca = el("input", {
    type: "search",
    placeholder: "Buscar tarefas…",
    value: busca,
    oninput: (e) => {
      busca = e.target.value.toLowerCase().trim();
      desenhar(root);
      const novo = root.querySelector(".kanban-busca input");
      if (novo) {
        novo.focus();
        novo.setSelectionRange(novo.value.length, novo.value.length);
      }
    },
  });

  wrap.append(el("div", { class: "kanban-topo" },
    el("div", { class: "kanban-busca" },
      el("span", { html: icon("search", 18) }),
      campoBusca),
    el("span", { style: "flex:1" }),
    el("button", {
      class: "btn tonal",
      onclick: () => criarBucket(root),
    }, "+ Coluna")));

  // --- números ----------------------------------------------------------
  const todas = dados.flatMap((b) => b.atividades);
  const abertas = todas.filter((a) => !a.concluida).length;
  const concluidas = todas.length - abertas;
  const atrasadas = todas.filter((a) => a.atrasada).length;

  wrap.append(el("div", { class: "kanban-stats" },
    el("span", {}, el("b", {}, String(todas.length)), " atividades"),
    el("span", {}, el("b", {}, String(abertas)), " abertas"),
    el("span", {}, el("b", {}, String(concluidas)), " concluídas"),
    atrasadas
      ? el("span", {},
          el("span", { class: "ponto", style: "background:var(--md-sys-color-error)" }),
          el("b", {}, String(atrasadas)), " atrasadas")
      : el("span", {}, "nenhuma atrasada")));

  // --- trilho -----------------------------------------------------------
  const trilho = el("div", { class: "kanban-trilho" });

  if (!dados.length) {
    trilho.append(el("div", {
      style: "padding:32px 20px;text-align:center;color:var(--md-sys-color-on-surface-variant)",
    },
      el("p", { style: "margin:0 0 6px;font-weight:500" }, "Nenhuma coluna ainda"),
      el("p", { style: "margin:0;font-size:13px" },
        "Comece com “A fazer”, “Em andamento” e “Concluído”.")));
  }

  for (const bucket of dados) trilho.append(coluna(root, bucket));

  wrap.append(trilho);
  root.append(wrap);
}

function coluna(root, bucket) {
  const col = el("div", {
    class: "kanban-coluna",
    ondragover: (ev) => { ev.preventDefault(); col.classList.add("alvo"); },
    ondragleave: () => col.classList.remove("alvo"),
    ondrop: async (ev) => {
      ev.preventDefault();
      col.classList.remove("alvo");
      const id = Number(ev.dataTransfer.getData("text/plain"));
      if (id) await mover(root, id, bucket.id);
    },
  });

  col.append(el("div", { class: "kanban-cabecalho" },
    el("span", { class: "kanban-titulo", title: bucket.nome }, bucket.nome),
    el("span", { class: "kanban-contagem" }, String(bucket.atividades.length)),
    el("span", { style: "flex:1" }),
    el("button", {
      class: "iconbtn", title: "Renomear coluna",
      onclick: () => renomearBucket(root, bucket),
      html: icon("edit", 15),
    }),
    el("button", {
      class: "iconbtn", title: "Excluir coluna",
      onclick: () => excluirBucket(root, bucket),
      html: icon("trash", 15),
    })));

  const lista = el("div", { class: "kanban-cartoes" });

  const filtradas = bucket.atividades.filter((a) =>
    !busca || (a.titulo || "").toLowerCase().includes(busca));

  if (!filtradas.length) {
    lista.append(el("p", {
      style: "font-size:12.5px;color:var(--md-sys-color-on-surface-variant);margin:8px 6px",
    }, busca ? "Nada encontrado." : "Vazia."));
  }

  for (const a of filtradas) lista.append(cartao(root, a));

  col.append(lista, el("button", {
    class: "kanban-add",
    onclick: () => criarAtividade(root, bucket.id),
  },
    el("span", { html: icon("plus", 15) }),
    el("span", {}, "Adicionar atividade")));

  return col;
}

/** Iniciais para o avatar: "Ana Paula Souza" → "AS". */
function iniciais(nome) {
  const partes = String(nome || "").trim().split(/\s+/).filter(Boolean);
  if (!partes.length) return "?";
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
}

/** Cor estável por pessoa — o mesmo usuário sempre cai no mesmo tom. */
function corDoAvatar(nome) {
  const tons = ["#7c5cff", "#0a7ea4", "#0f9d58", "#d9822b", "#c43e6b", "#5b6abf"];
  let soma = 0;
  for (const ch of String(nome || "")) soma = (soma + ch.charCodeAt(0)) % 9973;
  return tons[soma % tons.length];
}

function cartao(root, a) {
  const d = dias(a.prazo);

  // --- selos ------------------------------------------------------------
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
    selos.push(el("span", { class: "kanban-selo" + classe },
      el("span", { class: "kanban-selo-icone", html: icon("calendario", 12) }),
      el("span", {}, texto)));
  }

  if (a.total_itens) {
    selos.push(el("span", {
      class: "kanban-selo" + (a.itens_feitos === a.total_itens ? " completo" : ""),
    },
      el("span", { class: "kanban-selo-icone", html: icon("check", 12) }),
      el("span", {}, `${a.itens_feitos}/${a.total_itens}`)));
  }

  // --- avatares ---------------------------------------------------------
  const avatares = (a.responsaveis || []).slice(0, 4).map((r) =>
    el("span", {
      class: "kanban-avatar",
      title: r.nome,
      style: `background:${corDoAvatar(r.nome)}`,
    }, iniciais(r.nome)));

  const extras = (a.responsaveis || []).length - avatares.length;

  // --- progresso --------------------------------------------------------
  // Barra fina no rodapé, como no Planner: cinza = não começou,
  // âmbar = em andamento, verde = concluída.
  const pct = a.total_itens ? Math.round((a.itens_feitos / a.total_itens) * 100) : 0;
  const estado = a.concluida ? "feita" : pct > 0 ? "andamento" : "parada";

  const card = el("div", {
    class: "kanban-cartao" + (a.concluida ? " concluida" : ""),
    draggable: "true",
    ondragstart: (ev) => {
      ev.dataTransfer.setData("text/plain", String(a.id));
      ev.dataTransfer.effectAllowed = "move";
      card.classList.add("arrastando");
    },
    ondragend: () => card.classList.remove("arrastando"),
  },
    el("input", {
      class: "kanban-check",
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

    el("div", { class: "kanban-corpo" },
      el("div", {
        class: "kanban-cartao-titulo",
        onclick: () => abrirAtividade(root, a),
      }, a.titulo),

      a.descricao ? el("div", { class: "kanban-cartao-desc" }, a.descricao) : null,

      (selos.length || avatares.length)
        ? el("div", { class: "kanban-rodape" },
            ...selos,
            el("span", { style: "flex:1" }),
            ...avatares,
            extras > 0 ? el("span", { class: "kanban-avatar extra" }, `+${extras}`) : null)
        : null,

      el("div", { class: "kanban-progresso" },
        el("span", {
          class: "kanban-progresso-barra " + estado,
          style: `width:${a.concluida ? 100 : pct}%`,
        }))),

    el("button", {
      class: "kanban-remover",
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
// Ações
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

function criarBucket(root) {
  const campo = el("input", { class: "field", placeholder: "Ex.: Em andamento" });
  dialog({
    title: "Nova coluna",
    body: el("div", {}, campo),
    actions: [
      { label: "Cancelar", variant: "text", onClick: (fechar) => fechar() },
      {
        label: "Criar",
        variant: "tonal",
        onClick: async (fechar) => {
          const nome = campo.value.trim();
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
  setTimeout(() => campo.focus(), 60);
}

function renomearBucket(root, bucket) {
  const campo = el("input", { class: "field", value: bucket.nome });
  dialog({
    title: "Renomear coluna",
    body: el("div", {}, campo),
    actions: [
      { label: "Cancelar", variant: "text", onClick: (fechar) => fechar() },
      {
        label: "Salvar",
        variant: "tonal",
        onClick: async (fechar) => {
          const nome = campo.value.trim();
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
  const campoTitulo = el("input", { class: "field", placeholder: "O que precisa ser feito?" });
  const campoPrazo = el("input", { class: "field", type: "date" });

  dialog({
    title: "Nova atividade",
    body: el("div", {},
      el("label", { class: "label-campo" }, "Título"),
      campoTitulo,
      el("label", { class: "label-campo" }, "Prazo"),
      campoPrazo),
    actions: [
      { label: "Cancelar", variant: "text", onClick: (fechar) => fechar() },
      {
        label: "Criar",
        variant: "tonal",
        onClick: async (fechar) => {
          const titulo = campoTitulo.value.trim();
          if (!titulo) { toast("Informe o título."); return; }
          try {
            await api.post("/kanban/atividades", {
              bucket_id: bucketId,
              titulo,
              prazo: campoPrazo.value ? `${campoPrazo.value}T12:00:00` : null,
            });
            fechar();
            await recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
    ],
  });
  setTimeout(() => campoTitulo.focus(), 60);
}

function abrirAtividade(root, a) {
  const corpo = el("div", {});

  const campoTitulo = el("input", { class: "field", value: a.titulo });
  const campoPrazo = el("input", {
    class: "field",
    type: "date",
    value: a.prazo ? new Date(a.prazo).toISOString().slice(0, 10) : "",
  });
  const campoDesc = el("textarea", {
    class: "field",
    rows: "3",
    placeholder: "Detalhes (opcional)",
  });
  campoDesc.value = a.descricao || "";

  corpo.append(
    el("label", { class: "label-campo" }, "Título"),
    campoTitulo,
    el("label", { class: "label-campo" }, "Descrição"),
    campoDesc,
    el("label", { class: "label-campo" }, "Prazo"),
    campoPrazo);

  // --- checklist --------------------------------------------------------
  const listaItens = el("div", {});
  let itens = a.itens || [];

  const desenharItens = () => {
    listaItens.innerHTML = "";
    if (!itens.length) {
      listaItens.append(el("p", {
        style: "font-size:12.5px;color:var(--md-sys-color-on-surface-variant);margin:4px 8px",
      }, "Nenhum item ainda."));
      return;
    }
    for (const item of itens) {
      listaItens.append(el("div", { class: "kanban-item" },
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
        el("span", { class: item.feito ? "feito" : "" }, item.texto),
        el("span", { style: "flex:1" }),
        el("button", {
          class: "iconbtn danger", title: "Remover",
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

  const novoItem = el("input", {
    class: "field",
    placeholder: "Adicionar item e pressionar Enter",
    style: "margin-top:8px",
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

  corpo.append(
    el("h3", { class: "secao-titulo" }, "Checklist"),
    listaItens,
    novoItem);

  // --- responsáveis (só administrador) ----------------------------------
  const podeAtribuir = state.papel === "admin";
  const escolhidos = new Set((a.responsaveis || []).map((r) => r.usuario_id));

  if (podeAtribuir) {
    const nomes = new Map();
    const caixas = el("div", { style: "max-height:150px;overflow:auto" });
    for (const u of usuarios) {
      nomes.set(u.id, u.nome);
      caixas.append(el("label", {
        class: "kanban-item",
        style: "cursor:pointer",
      },
        el("input", {
          type: "checkbox",
          checked: escolhidos.has(u.id) ? "checked" : null,
          "data-usuario": String(u.id),
          onchange: (ev) => {
            if (ev.target.checked) escolhidos.add(u.id);
            else escolhidos.delete(u.id);
          },
        }),
        el("span", {}, u.nome),
        el("span", { style: "flex:1" }),
        el("span", {
          style: "font-size:11px;color:var(--md-sys-color-on-surface-variant)",
        }, u.email || "")));
    }
    corpo.append(el("h3", { class: "secao-titulo" }, "Responsáveis"), caixas);
    corpo._nomes = nomes;
  }

  const acoes = [
    {
      label: a.concluida ? "Reabrir" : "Concluir",
      variant: "tonal",
      onClick: async () => {
        try {
          await api.post(`/kanban/atividades/${a.id}/concluir`);
          await recarregar(root);
        } catch (e) { mostrarErro(e); }
      },
    },
    {
      label: "Salvar",
      variant: "tonal",
      onClick: async (fechar) => {
        try {
          await api.patch(`/kanban/atividades/${a.id}`, {
            bucket_id: a.bucket_id,
            titulo: campoTitulo.value.trim(),
            descricao: campoDesc.value.trim() || null,
            prazo: campoPrazo.value ? `${campoPrazo.value}T12:00:00` : null,
          });

          if (podeAtribuir) {
            await api.post(`/kanban/atividades/${a.id}/responsaveis`,
              { usuario_ids: [...escolhidos] });
          }

          fechar();
          await recarregar(root);
        } catch (e) { mostrarErro(e); }
      },
    },
  ];

  dialog({ title: "Atividade", body: corpo, actions: acoes, wide: true });
}
