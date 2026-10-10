/**
 * Empréstimos — o ciclo na prática.
 *
 * Reserva → Retirada (termo + conferência) → Uso → Devolução (conferência)
 * → Vistoria. A tela não decide nada: pergunta ao servidor quais passos são
 * válidos e mostra o motivo quando não são.
 *
 * @module views/emprestimos
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, emptyState, skeleton, fmtDate, mostrarErro } from "../ui.js";

const PAGE_SIZE = 20;
let page = 1;
let filtro = "";

const ROTULO = {
  reservado: "Reservado", retirado: "Em uso", devolvido: "Aguardando vistoria",
  vistoriado: "Concluído", cancelado: "Cancelado",
};
const COR = {
  reservado: "chip", retirado: "chip aviso", devolvido: "chip info",
  vistoriado: "chip ok", cancelado: "chip neutro",
};

export async function renderEmprestimos(root) {
  ctx.setTitle("Empréstimos");
  ctx.setFab(state.canWrite
    ? { label: "Novo empréstimo", icon: "plus", onClick: () => abrirReserva(root) }
    : null);

  root.innerHTML = "";
  root.append(
    el("h1", { class: "page-title" }, "Empréstimos"),
    el("p", { class: "muted", style: "margin:0 0 16px" },
      "Reserva, retirada com termo e conferência, devolução e vistoria."),
  );

  const filtros = el("div", { class: "row wrap", style: "gap:8px;margin-bottom:16px" });
  for (const [v, r] of [["", "Todos"], ["reservado", "Reservados"], ["retirado", "Em uso"],
                        ["devolvido", "Aguardando vistoria"], ["vistoriado", "Concluídos"]]) {
    filtros.append(el("button", {
      class: `chip${filtro === v ? " selected" : ""}`,
      onclick: () => { filtro = v; page = 1; renderEmprestimos(root); },
    }, r));
  }
  root.append(filtros);

  const lista = el("div", {}, skeleton(4));
  root.append(lista);

  let dados;
  try {
    const q = { page, size: PAGE_SIZE };
    if (filtro) q.situacao = filtro;
    dados = await api.get("/emprestimos", q);
  } catch (e) {
    lista.innerHTML = "";
    lista.append(el("p", { class: "text-error" }, e.message));
    return;
  }

  lista.innerHTML = "";
  if (!dados.items?.length) {
    lista.append(emptyState("Nenhum empréstimo",
      filtro ? "Nenhum empréstimo nesta situação." : "Use o botão + para registrar o primeiro."));
    return;
  }
  lista.append(el("div", { class: "cartoes" },
    ...dados.items.map((e) => cartao(e, root))));
}

function cartao(e, root) {
  const alerta = e.alerta || {};
  return el("div", { class: "cartao-contagem" },
    el("div", { class: "row between wrap", style: "gap:10px" },
      el("b", { style: "font-size:15px" }, e.ativo_patrimonio || `Ativo #${e.ativo_id}`),
      el("span", { class: COR[e.situacao] || "chip" }, ROTULO[e.situacao] || e.situacao)),

    el("div", { class: "muted", style: "font-size:12.5px;margin-top:4px" },
      [e.retirado_por ? `Para ${e.retirado_por}` : null,
       e.reservado_em ? `reservado ${fmtDate(e.reservado_em, true)}` : null,
       e.devolucao_prevista ? `devolver até ${fmtDate(e.devolucao_prevista)}` : null,
      ].filter(Boolean).join(" · ")),

    alerta.nivel > 0
      ? el("div", { class: `recado ${alerta.nivel >= 3 ? "erro" : "info"}`, style: "margin-top:10px" },
          alerta.mensagem)
      : null,

    e.tem_avaria
      ? el("div", { class: "recado erro", style: "margin-top:8px" },
          "Avaria registrada na devolução.")
      : null,

    e.pendencias?.length
      ? el("div", { class: "muted", style: "font-size:12.5px;margin-top:8px" },
          `Pendente: ${e.pendencias.join(" · ")}`)
      : null,

    el("div", { class: "row wrap", style: "gap:8px;margin-top:12px" },
      ...(e.proximos_passos || []).map((p) => {
        const principal = p.situacao === "retirado" || p.situacao === "devolvido";
        const bloqueado = !state.canWrite;
        return el("button", {
          class: `btn ${principal ? "filled" : "tonal"}`,
          disabled: bloqueado,
          onclick: () => passo(e, p, root),
        }, p.rotulo);
      }),
    ),
  );
}

async function passo(e, p, root) {
  if (p.situacao === "cancelado") {
    if (!(await confirmSheet("Cancelar reserva", `Descartar a reserva de ${e.ativo_patrimonio}?`))) return;
    try {
      await api.post(`/emprestimos/${e.id}/cancelar`, {});
      toast("Reserva cancelada"); renderEmprestimos(root);
    } catch (err) { mostrarErro(err); }
    return;
  }

  if (p.situacao === "vistoriado") {
    return vistoriar(e, root);
  }

  // Retirada e devolução usam o mesmo checklist.
  const momento = p.situacao === "retirado" ? "entrega" : "devolucao";
  const itens = await carregarChecklist(momento);
  if (!itens.length) {
    mostrarErro(new Error(
      "Nenhum item de checklist cadastrado. Cadastre em Administração antes de conferir."));
    return;
  }

  const marcados = {};
  const linhas = itens.map((i) => {
    const cb = el("input", { type: "checkbox" });
    cb.checked = true;
    marcados[i.rotulo] = cb;
    return el("label", { class: "opcao" },
      cb,
      el("span", { class: "opcao-texto" },
        el("span", { class: "opcao-titulo" }, i.rotulo),
        i.ajuda ? el("span", { class: "opcao-dica" }, i.ajuda) : null));
  });

  const termoCb = el("input", { type: "checkbox" });
  const comTermo = momento === "entrega" && !e.termo_id;

  dialog({
    title: momento === "entrega"
      ? `Retirada — ${e.ativo_patrimonio}`
      : `Devolução — ${e.ativo_patrimonio}`,
    wide: true,
    body: el("div", {},
      el("p", { class: "muted", style: "margin:0 0 12px" },
        momento === "entrega"
          ? "Confira o estado do equipamento ao entregar. É esta conferência que permite cobrar depois."
          : "Confira o que voltou. Itens que estavam OK na entrega e voltaram com problema contam como avaria."),
      ...linhas,
      comTermo
        ? el("label", { class: "opcao", style: "margin-top:12px" },
            termoCb,
            el("span", { class: "opcao-texto" },
              el("span", { class: "opcao-titulo" }, "Termo de responsabilidade assinado"),
              el("span", { class: "opcao-dica" },
                "Ao marcar, o sistema registra o termo com data e assinatura digital.")))
        : null,
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Registrar", variant: "filled", onClick: async (close) => {
        const corpo = {
          itens: itens.map((i) => ({ rotulo: i.rotulo, ok: marcados[i.rotulo].checked })),
          confirmar_termo: comTermo ? termoCb.checked : false,
        };
        try {
          const r = await api.post(`/emprestimos/${e.id}/${momento === "entrega" ? "retirar" : "devolver"}`, corpo);
          close();
          if (r.laudo?.avarias?.length) {
            toast(`${r.laudo.avarias.length} avaria(s) registrada(s)`);
          } else {
            toast(momento === "entrega" ? "Retirada registrada" : "Devolução registrada");
          }
          renderEmprestimos(root);
        } catch (err) { mostrarErro(err); }
      } },
    ],
  });
}

async function vistoriar(e, root) {
  const cb = el("input", { type: "checkbox" });
  dialog({
    title: `Vistoria — ${e.ativo_patrimonio}`,
    body: el("div", {},
      el("p", { class: "muted", style: "margin:0 0 12px" },
        "Concluir o ciclo deste empréstimo?"),
      e.tem_avaria
        ? el("label", { class: "opcao" },
            cb,
            el("span", { class: "opcao-texto" },
              el("span", { class: "opcao-titulo" }, "Abrir manutenção"),
              el("span", { class: "opcao-dica" },
                "Cria a ordem de serviço com a descrição da avaria já preenchida.")))
        : el("div", { class: "recado info" }, "Nenhuma avaria — nada a consertar."),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Concluir", variant: "filled", onClick: async (close) => {
        try {
          const r = await api.post(`/emprestimos/${e.id}/vistoriar`, { abrir_manutencao: cb.checked });
          close();
          toast(r.manutencao_id ? "Concluído — manutenção aberta" : "Empréstimo concluído");
          renderEmprestimos(root);
        } catch (err) { mostrarErro(err); }
      } },
    ],
  });
}

async function carregarChecklist(momento) {
  const r = await api.get("/emprestimos/checklist/modelo", {});
  return (r || []).filter((i) => (momento === "entrega" ? i.na_entrega : i.na_devolucao));
}

async function abrirReserva(root) {
  const busca = el("input", { placeholder: "Patrimônio ou hostname" });
  const resultados = el("div", { class: "busca-ativos" });
  const escolhido = el("div", { class: "ativo-escolhido oculto" });
  const nome = el("input", { placeholder: "Nome de quem vai levar" });
  const fim = el("input", { type: "date" });
  let ativo = null;
  let seq = 0;
  let timer = null;

  busca.addEventListener("input", () => {
    ativo = null;
    escolhido.classList.add("oculto");
    clearTimeout(timer);
    const termo = busca.value.trim();
    if (termo.length < 2) { resultados.innerHTML = ""; resultados.classList.remove("aberto"); return; }
    timer = setTimeout(async () => {
      const meu = ++seq;
      try {
        const r = await api.get("/ativos", { search: termo, size: 12, dominio: state.dominio });
        if (meu !== seq) return;
        resultados.innerHTML = "";
        resultados.classList.add("aberto");
        if (!r.items?.length) {
          resultados.append(el("div", { class: "busca-vazia" }, "Nenhum ativo encontrado."));
          return;
        }
        for (const a of r.items) {
          const host = a.ti?.hostname || a.hostname || "";
          resultados.append(el("button", {
            type: "button", class: "busca-item",
            onclick: () => {
              ativo = a;
              busca.value = "";
              resultados.innerHTML = "";
              resultados.classList.remove("aberto");
              escolhido.classList.remove("oculto");
              escolhido.innerHTML = "";
              escolhido.append(el("span", { class: "chip" }, a.patrimonio));
            },
          }, el("b", {}, a.patrimonio || "(sem patrimônio)"),
             host ? el("span", { class: "busca-host" }, host) : null,
             el("span", { class: "busca-modelo" }, [a.marca, a.modelo].filter(Boolean).join(" "))));
        }
      } catch { /* busca auxiliar */ }
    }, 250);
  });

  dialog({
    title: "Novo empréstimo",
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Equipamento"), busca, escolhido, resultados),
      el("div", { class: "field" }, el("label", {}, "Para quem"), nome),
      el("div", { class: "field" }, el("label", {}, "Devolução prevista"), fim),
      el("p", { class: "dica" }, "A retirada é registrada depois, com o termo e a conferência."),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Reservar", variant: "filled", onClick: async (close) => {
        if (!ativo) { mostrarErro(new Error("Escolha o equipamento na lista.")); return; }
        if (!nome.value.trim()) { mostrarErro(new Error("Informe para quem é o empréstimo.")); return; }
        try {
          await api.post("/emprestimos", {
            ativo_id: ativo.id,
            retirado_por_nome: nome.value.trim(),
            devolucao_prevista: fim.value ? `${fim.value}T12:00:00Z` : null,
          });
          close();
          toast("Empréstimo reservado");
          renderEmprestimos(root);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}
