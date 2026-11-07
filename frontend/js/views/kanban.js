/**
 * Kanban — quadro de atividades em colunas.
 *
 * ## Por que arrastar com HTML5 nativo
 *
 * `dragstart` / `dragover` / `drop` é API do navegador, sem biblioteca. Numa
 * tela que já carrega módulos ES sem bundler, trazer uma lib de drag só para
 * isso contradiz o resto do sistema.
 *
 * A limitação é não haver arraste no toque (celular) — nesse caso os botões
 * ← → do cartão resolvem, e é por isso que eles existem além do arraste.
 *
 * ## Ordem
 *
 * A posição dentro da coluna é um inteiro. Arrastar envia a nova ordem; o
 * servidor reescreve. Não há "ordem parcial" nem data de modificação — a
 * sequência é explícita.
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

function fmtPrazo(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
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

export async function renderKanban(root) {
  ctx.setTitle("Kanban");
  ctx.setFab(null);

  root.innerHTML = "";
  const alvo = el("div", {}, skeleton(4));
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
  root.querySelector(".kanban-wrap")?.remove();

  const wrap = el("div", { class: "kanban-wrap" });

  // --- barra de busca e ações -------------------------------------------
  const campo = el("input", {
    class: "field",
    placeholder: "Buscar atividade…",
    value: busca,
    style: "max-width:320px",
    oninput: (e) => {
      busca = e.target.value.toLowerCase().trim();
      desenhar(root);
      // Devolve o foco e o cursor ao campo depois de redesenhar.
      const novo = root.querySelector(".kanban-wrap input.field");
      if (novo) { novo.focus(); novo.setSelectionRange(novo.value.length, novo.value.length); }
    },
  });

  wrap.append(el("div", {
    class: "row between wrap",
    style: "gap:10px;align-items:center;margin-bottom:14px",
  },
    campo,
    el("button", {
      class: "btn tonal small",
      onclick: () => criarBucket(root),
    }, "+ Nova coluna")));

  // --- colunas ----------------------------------------------------------
  const trilho = el("div", { class: "kanban-trilho" });

  if (!dados.length) {
    trilho.append(el("div", { class: "card", style: "padding:24px;text-align:center" },
      el("p", { class: "muted", style: "margin:0" },
        "Nenhuma coluna ainda. Comece criando “A fazer”, “Em andamento” e “Concluído”.")));
  }

  for (const bucket of dados) {
    trilho.append(coluna(root, bucket));
  }

  wrap.append(trilho);
  root.append(wrap);
}

function coluna(root, bucket) {
  const col = el("div", {
    class: "kanban-coluna",
    ondragover: (ev) => { ev.preventDefault(); ev.currentTarget.classList.add("alvo"); },
    ondragleave: (ev) => ev.currentTarget.classList.remove("alvo"),
    ondrop: async (ev) => {
      ev.preventDefault();
      ev.currentTarget.classList.remove("alvo");
      const id = Number(ev.dataTransfer.getData("text/plain"));
      if (!id) return;
      await mover(root, id, bucket.id);
    },
  });

  const titulo = el("div", { class: "kanban-cabecalho" },
    el("span", { class: "kanban-titulo" }, bucket.nome),
    el("span", { class: "muted", style: "font-size:12px" },
      String(bucket.atividades.length)),
    el("span", { style: "flex:1" }),
    el("button", {
      class: "iconbtn", title: "Adicionar atividade",
      onclick: () => criarAtividade(root, bucket.id),
      html: icon("plus", 16),
    }),
    el("button", {
      class: "iconbtn", title: "Renomear coluna",
      onclick: () => renomearBucket(root, bucket),
      html: icon("edit", 16),
    }),
    el("button", {
      class: "iconbtn danger", title: "Excluir coluna",
      onclick: () => excluirBucket(root, bucket),
      html: icon("trash", 16),
    }),
  );

  const lista = el("div", { class: "kanban-cartoes" });

  const filtradas = bucket.atividades.filter((a) => {
    if (!busca) return true;
    return (a.titulo || "").toLowerCase().includes(busca);
  });

  if (!filtradas.length) {
    lista.append(el("p", { class: "muted", style: "font-size:12.5px;margin:8px 4px" },
      busca ? "Nada encontrado." : "Nenhuma atividade."));
  }

  for (const a of filtradas) lista.append(cartao(root, bucket, a));

  col.append(titulo, lista);
  return col;
}

function cartao(root, bucket, a) {
  const pct = a.total_itens ? Math.round((a.itens_feitos / a.total_itens) * 100) : null;
  const d = dias(a.prazo);

  // Tom pelo prazo: vencido = erro, até 3 dias = aviso.
  const tom = a.concluida ? "" : d === null ? "" : d < 0 ? " danger" : d <= 3 ? " aviso" : "";

  const card = el("div", {
    class: "kanban-cartao" + (a.concluida ? " concluida" : ""),
    draggable: "true",
    ondragstart: (ev) => {
      ev.dataTransfer.setData("text/plain", String(a.id));
      ev.dataTransfer.effectAllowed = "move";
    },
    onclick: (ev) => {
      if (ev.target.closest("button")) return;
      abrirAtividade(root, bucket, a);
    },
  },
    el("div", { class: "kanban-cartao-titulo" }, a.titulo),
    a.descricao ? el("div", { class: "kanban-cartao-desc" }, a.descricao) : null,

    // Rodapé: prazo, checklist, responsáveis
    el("div", { class: "kanban-rodape" },
      a.prazo
        ? el("span", { class: "chip" + tom, title: `Prazo: ${fmtPrazo(a.prazo)}` },
            fmtPrazo(a.prazo))
        : null,
      pct !== null
        ? el("span", {
            class: "chip",
            title: `${a.itens_feitos} de ${a.total_itens} itens`,
          }, `☑ ${a.itens_feitos}/${a.total_itens}`)
        : null,
      ...(a.responsaveis || []).slice(0, 3).map((r) => el("span", {
        class: "chip",
        title: r.email,
      }, r.nome.split(" ")[0]))),
  );

  return card;
}

async function mover(root, atividadeId, bucketId) {
  try {
    await api.post(`/kanban/atividades/${atividadeId}/mover`,
      { bucket_id: bucketId, ordem: 0 });
    recarregar(root);
  } catch (e) { mostrarErro(e); }
}

async function recarregar(root) {
  try {
    dados = await api.get("/kanban");
  } catch (e) { mostrarErro(e); }
  desenhar(root);
}

// ---------------------------------------------------------------------------
// Criação e edição
// ---------------------------------------------------------------------------

async function criarBucket(root) {
  const campo = el("input", { class: "field", placeholder: "Nome da coluna" });
  const dlg = dialog({
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
            recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
    ],
  });
  return dlg;
}

async function renomearBucket(root, bucket) {
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
            recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
    ],
  });
}

async function excluirBucket(root, bucket) {
  const quantas = bucket.atividades.length;
  const aviso = quantas
    ? `A coluna tem ${quantas} atividade(s). Elas serão excluídas junto.`
    : "A coluna está vazia.";
  if (!confirm(`Excluir a coluna "${bucket.nome}"?\n\n${aviso}`)) return;
  try {
    await api.del(`/kanban/buckets/${bucket.id}`);
    toast("Coluna excluída.");
    recarregar(root);
  } catch (e) { mostrarErro(e); }
}

async function criarAtividade(root, bucketId) {
  const campoTitulo = el("input", { class: "field", placeholder: "O que precisa ser feito?" });
  const campoPrazo = el("input", { class: "field", type: "date" });

  dialog({
    title: "Nova atividade",
    body: el("div", {},
      el("label", { class: "muted", style: "font-size:12.5px" }, "Título"),
      campoTitulo,
      el("label", { class: "muted", style: "font-size:12.5px;margin-top:10px" }, "Prazo (opcional)"),
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
            recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
    ],
  });
}

async function abrirAtividade(root, bucket, a) {
  const corpo = el("div", {});

  // --- título e prazo ---------------------------------------------------
  const campoTitulo = el("input", { class: "field", value: a.titulo });
  const campoPrazo = el("input", {
    class: "field", type: "date",
    value: a.prazo ? new Date(a.prazo).toISOString().slice(0, 10) : "",
  });

  corpo.append(
    el("label", { class: "muted", style: "font-size:12.5px" }, "Título"),
    campoTitulo,
    el("label", { class: "muted", style: "font-size:12.5px;margin-top:10px" }, "Prazo"),
    campoPrazo);

  // --- checklist --------------------------------------------------------
  const listaItens = el("div", { style: "margin-top:14px" });
  const desenharItens = () => {
    listaItens.innerHTML = "";
    if (!a.itens.length) {
      listaItens.append(el("p", { class: "muted", style: "font-size:12.5px" },
        "Nenhum item ainda."));
      return;
    }
    for (const item of a.itens) {
      listaItens.append(el("label", {
        class: "kanban-item",
        style: "display:flex;gap:8px;align-items:center;padding:6px 0;cursor:pointer",
        onclick: async (ev) => {
          if (ev.target.tagName === "BUTTON") return;
          try {
            const r = await api.post(`/kanban/itens/${item.id}/alternar`);
            a.itens = r.itens;
            a.itens_feitos = r.itens_feitos;
            desenharItens();
            recarregar(root);
          } catch (e) { mostrarErro(e); }
        },
      },
        el("input", {
          type: "checkbox",
          checked: item.feito ? "checked" : null,
          onchange: async () => {
            try {
              const r = await api.post(`/kanban/itens/${item.id}/alternar`);
              a.itens = r.itens;
              a.itens_feitos = r.itens_feitos;
              desenharItens();
              recarregar(root);
            } catch (e) { mostrarErro(e); }
          },
        }),
        el("span", {
          style: item.feito ? "text-decoration:line-through;opacity:.6" : "",
        }, item.texto),
        el("span", { style: "flex:1" }),
        el("button", {
          class: "iconbtn danger", title: "Remover",
          onclick: async () => {
            try {
              await api.del(`/kanban/itens/${item.id}`);
              a.itens = a.itens.filter((x) => x.id !== item.id);
              desenharItens();
              recarregar(root);
            } catch (e) { mostrarErro(e); }
          },
          html: icon("trash", 14),
        })));
    }
  };
  desenharItens();

  const novoItem = el("input", {
    class: "field", placeholder: "Novo item e Enter",
    style: "margin-top:8px",
    onkeydown: async (ev) => {
      if (ev.key !== "Enter") return;
      const texto = ev.target.value.trim();
      if (!texto) return;
      try {
        const r = await api.post(`/kanban/atividades/${a.id}/itens`, { texto });
        a.itens = r.itens;
        ev.target.value = "";
        desenharItens();
        recarregar(root);
      } catch (e) { mostrarErro(e); }
    },
  });

  corpo.append(
    el("h3", { class: "secao-titulo", style: "margin:16px 0 6px" }, "Checklist"),
    listaItens, novoItem);

  // --- responsáveis (só admin) -----------------------------------------
  if (state.papel === "admin" || state.canDelete) {
    const selecionados = new Set((a.responsaveis || []).map((r) => r.usuario_id));
    const caixas = el("div", { style: "max-height:140px;overflow:auto;margin-top:6px" });
    for (const u of usuarios) {
      caixas.append(el("label", {
        style: "display:flex;gap:8px;align-items:center;padding:4px 0;font-size:13px",
      },
        el("input", {
          type: "checkbox",
          checked: selecionados.has(u.id) ? "checked" : null,
          onchange: (ev) => {
            if (ev.target.checked) selecionados.add(u.id);
            else selecionados.delete(u.id);
          },
        }),
        el("span", {}, u.nome)));
    }
    corpo.append(
      el("h3", { class: "secao-titulo", style: "margin:16px 0 0" }, "Responsáveis"),
      caixas);
  }

  // --- ações ------------------------------------------------------------
  const acoes = [
    {
      label: a.concluida ? "Reabrir" : "Concluir",
      variant: "tonal",
      onClick: async () => {
        try {
          await api.post(`/kanban/atividades/${a.id}/concluir`);
          recarregar(root);
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
            descricao: a.descricao,
            prazo: campoPrazo.value ? `${campoPrazo.value}T12:00:00` : null,
          });

          // Responsáveis só se a seção foi renderizada (admin).
          const extras = corpo.querySelectorAll("input[type=checkbox]");
          if (extras.length) {
            const ids = [];
            // As primeiras caixas são do checklist; as últimas, dos usuários.
            const totalItens = a.itens.length;
            for (let i = totalItens; i < extras.length; i++) {
              if (extras[i].checked) {
                const rotulo = extras[i].parentElement.textContent.trim();
                const achado = usuarios.find((u) => u.nome === rotulo);
                if (achado) ids.push(achado.id);
              }
            }
            await api.post(`/kanban/atividades/${a.id}/responsaveis`,
              { usuario_ids: ids });
          }
          fechar();
          recarregar(root);
        } catch (e) { mostrarErro(e); }
      },
    },
    {
      label: "Excluir",
      variant: "danger",
      onClick: async (fechar) => {
        if (!confirm(`Excluir "${a.titulo}"?`)) return;
        try {
          await api.del(`/kanban/atividades/${a.id}`);
          fechar();
          recarregar(root);
        } catch (e) { mostrarErro(e); }
      },
    },
  ];

  dialog({ title: "Atividade", body: corpo, actions: acoes, wide: true });
}
