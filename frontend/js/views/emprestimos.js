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
// O termo fica no módulo, e não no input: a tela é reconstruída a cada troca
// de filtro, e sem isto a busca se apagaria ao clicar num chip.
let busca = "";

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

  // --- busca no histórico ---------------------------------------------
  //
  // Responde as duas perguntas de quem audita: "o que a Ana já levou?" e
  // "por quais mãos este notebook passou?". O servidor procura em patrimônio,
  // número de série, nome e e-mail do usuário, nome digitado livremente e
  // número do chamado — é o que alguém tem à mão quando procura.
  const campoBusca = el("input", {
    type: "search",
    class: "search-input",
    placeholder: "Buscar por equipamento, pessoa ou chamado…",
    value: busca,
    autocomplete: "off",
  });

  let timerBusca = null;
  campoBusca.addEventListener("input", () => {
    clearTimeout(timerBusca);
    timerBusca = setTimeout(() => {
      const novo = campoBusca.value.trim();
      if (novo === busca) return;
      busca = novo;
      page = 1;
      renderEmprestimos(root);
    }, 320);
  });

  root.append(el("div", { class: "field", style: "margin-bottom:12px" }, campoBusca));

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
    if (busca) q.search = busca;
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

/** Baixa a caixa e tira acentos, para comparar nomes. */
function normalizarTexto(texto) {
  return String(texto || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

async function abrirReserva(root) {
  // --- equipamento ------------------------------------------------------
  //
  // A busca do servidor já cobre patrimônio, número de série, modelo, marca,
  // hostname, IP e MAC. O texto do campo é que estava desatualizado: dizia
  // só "Patrimônio ou hostname", e quem tem o número de série na mão não
  // sabia que podia digitar aquilo.
  const busca = el("input", { placeholder: "Patrimônio, nº de série, hostname ou IP" });
  const resultados = el("div", { class: "busca-ativos" });
  const escolhido = el("div", { class: "ativo-escolhido oculto" });

  // --- pessoa -----------------------------------------------------------
  //
  // Antes era texto livre puro. Texto livre não erra, mas também não liga o
  // empréstimo a um usuário do sistema — então o histórico de quem levou o
  // quê não existia, e a cobrança de atraso não tinha a quem se dirigir.
  //
  // Agora procura na lista de usuários (nome ou e-mail) e, se não achar,
  // aceita o nome digitado como antes. Os dois casos continuam válidos:
  // nem todo mundo que leva um equipamento tem conta no sistema.
  const buscaPessoa = el("input", { placeholder: "Nome ou e-mail — ou digite um nome livre" });
  const listaPessoas = el("div", { class: "busca-ativos" });
  const pessoaEscolhida = el("div", { class: "ativo-escolhido oculto" });

  const fim = el("input", { type: "date" });

  let ativo = null;
  let pessoa = null;        // usuário do sistema, quando escolhido
  let seq = 0;
  let timer = null;

  // Carrega os usuários uma vez. São poucos: cabe filtrar no cliente, e
  // assim a busca responde a cada tecla sem ir ao servidor.
  let usuarios = [];
  api.get("/usuarios").then((r) => { usuarios = r || []; }).catch(() => {});

  function limparAtivo() {
    ativo = null;
    escolhido.classList.add("oculto");
  }

  busca.addEventListener("input", () => {
    limparAtivo();
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
              escolhido.append(
                el("span", { class: "chip" }, a.patrimonio || a.numero_serie || `#${a.id}`),
                el("span", { class: "muted", style: "font-size:12.5px;margin-left:8px" },
                  [a.numero_serie, host, [a.marca, a.modelo].filter(Boolean).join(" ")]
                    .filter(Boolean).join(" · ")),
              );
            },
          }, el("b", {}, a.patrimonio || a.numero_serie || "(sem identificação)"),
             host ? el("span", { class: "busca-host" }, host) : null,
             el("span", { class: "busca-modelo" }, [a.marca, a.modelo].filter(Boolean).join(" "))));
        }
      } catch { /* busca auxiliar */ }
    }, 250);
  });

  buscaPessoa.addEventListener("input", () => {
    pessoa = null;
    pessoaEscolhida.classList.add("oculto");
    const termo = buscaPessoa.value.trim();
    const alvo = normalizarTexto(termo);
    if (alvo.length < 2) { listaPessoas.innerHTML = ""; listaPessoas.classList.remove("aberto"); return; }

    const achados = usuarios
      .filter((u) => normalizarTexto(u.nome).includes(alvo)
                  || normalizarTexto(u.email).includes(alvo))
      .slice(0, 8);

    listaPessoas.innerHTML = "";
    listaPessoas.classList.add("aberto");
    if (!achados.length) {
      // Não é erro: pode ser alguém de fora do sistema. O nome digitado vale.
      listaPessoas.append(el("div", { class: "busca-vazia" },
        "Nenhum usuário com esse nome. O texto digitado será usado como está."));
      return;
    }
    for (const u of achados) {
      listaPessoas.append(el("button", {
        type: "button", class: "busca-item",
        onclick: () => {
          pessoa = u;
          listaPessoas.innerHTML = "";
          listaPessoas.classList.remove("aberto");
          pessoaEscolhida.classList.remove("oculto");
          pessoaEscolhida.innerHTML = "";
          pessoaEscolhida.append(
            el("span", { class: "chip" }, u.nome),
            el("span", { class: "muted", style: "font-size:12.5px;margin-left:8px" },
              u.email || ""),
          );
        },
      }, el("b", {}, u.nome), el("span", { class: "busca-modelo" }, u.email || "")));
    }
  });

  dialog({
    title: "Novo empréstimo",
    wide: true,
    body: el("div", {},
      el("div", { class: "field" },
        el("label", {}, "Equipamento"), busca, escolhido, resultados),
      el("div", { class: "field" },
        el("label", {}, "Para quem"), buscaPessoa, pessoaEscolhida, listaPessoas),
      el("div", { class: "field" }, el("label", {}, "Devolução prevista"), fim),
      el("p", { class: "dica" },
        "A retirada é registrada depois, com o termo e a conferência. "
        + "Escolher um usuário da lista liga o empréstimo ao histórico dele."),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Reservar", variant: "filled", onClick: async (close) => {
        if (!ativo) { mostrarErro(new Error("Escolha o equipamento na lista.")); return; }
        const nomeLivre = buscaPessoa.value.trim();
        if (!pessoa && !nomeLivre) {
          mostrarErro(new Error("Informe para quem é o empréstimo."));
          return;
        }
        try {
          await api.post("/emprestimos", {
            ativo_id: ativo.id,
            // Usuário do sistema E nome: o nome fica no registro mesmo que a
            // conta seja removida depois, e o id liga ao histórico.
            usuario_id: pessoa?.id ?? null,
            retirado_por_nome: pessoa ? pessoa.nome : nomeLivre,
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
