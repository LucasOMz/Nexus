/**
 * Todos os avisos do usuário.
 *
 * ## Por que uma tela, e não só o painel
 *
 * O sino é bom para três ou quatro avisos. Com trinta, o painel passa da
 * altura da tela e a pessoa perde o fim da lista — na prática, ninguém rola
 * até o final de um popover.
 *
 * Aqui os mesmos itens ganham espaço para ler, agrupamento por urgência e um
 * resumo no topo. A fonte é a **mesma** API (`/notificacoes`): não há regra
 * duplicada, só apresentação diferente.
 *
 * ## O que cada item permite
 *
 * Empréstimo abre o ativo. Contrato abre o calendário. O aviso do OCS leva à
 * tela de administração já na aba certa — o `painel` que o servidor devolve
 * diz para onde ir.
 *
 * @module views/avisos
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, skeleton, emptyState } from "../ui.js";

const ROTULO_NIVEL = {
  erro: "Atrasado",
  urgente: "Urgente",
  aviso: "Atenção",
  info: "Informativo",
};

const ORDEM_NIVEL = { erro: 0, urgente: 1, aviso: 2, info: 3 };

export async function renderAvisos(root) {
  ctx.setTitle("Avisos");
  ctx.setFab(null);

  root.innerHTML = "";
  root.append(
    el("h1", { class: "page-title" }, "Avisos"),
    el("p", { class: "muted", style: "margin:0 0 16px" },
      "Tudo o que precisa da sua atenção: devoluções, contratos vencendo e "
      + "pendências de integração."),
  );

  const alvo = el("div", {}, skeleton(5));
  root.append(alvo);

  let dados;
  try {
    dados = await api.get("/notificacoes");
  } catch (e) {
    alvo.innerHTML = "";
    alvo.append(emptyState("relatorios", "Não foi possível carregar", e.message));
    return;
  }

  alvo.innerHTML = "";

  const itens = [...(dados.itens || [])]
    .sort((a, b) => (ORDEM_NIVEL[a.nivel] ?? 9) - (ORDEM_NIVEL[b.nivel] ?? 9));

  if (!itens.length) {
    alvo.append(emptyState("relatorios", "Nada pendente",
      "Quando houver devolução, contrato vencendo ou pendência de integração, "
      + "o aviso aparece aqui."));
    return;
  }

  // --- resumo -----------------------------------------------------------
  const porNivel = {};
  for (const i of itens) porNivel[i.nivel] = (porNivel[i.nivel] || 0) + 1;

  const resumo = el("div", { class: "row wrap", style: "gap:8px;margin-bottom:16px" },
    el("span", { class: "chip" }, `${itens.length} aviso(s)`));
  for (const [nivel, rotulo] of Object.entries(ROTULO_NIVEL)) {
    if (!porNivel[nivel]) continue;
    const cor = nivel === "erro" ? " danger" : nivel === "urgente" ? " aviso" : "";
    resumo.append(el("span", { class: `chip${cor}` }, `${porNivel[nivel]} ${rotulo.toLowerCase()}`));
  }
  alvo.append(resumo);

  // --- lista ------------------------------------------------------------
  const lista = el("div", {});
  for (const item of itens) {
    const cor = item.nivel === "erro" ? " danger"
      : item.nivel === "urgente" ? " aviso" : "";

    lista.append(el("div", { class: "card", style: "margin-bottom:8px" },
      el("div", { class: "row between wrap", style: "gap:10px;align-items:flex-start" },
        el("div", { style: "flex:1;min-width:220px" },
          el("div", { class: "row", style: "gap:8px;align-items:baseline" },
            el("b", {}, item.titulo),
            el("span", { class: `chip${cor}` }, ROTULO_NIVEL[item.nivel] || item.nivel)),
          el("p", { class: "muted", style: "margin:6px 0 0;font-size:13px" },
            item.detalhe || ""),
        ),
        botaoDoItem(item),
      ),
    ));
  }
  alvo.append(lista);
}

/** O botão certo para cada tipo de aviso — ou nenhum. */
function botaoDoItem(item) {
  const ir = (rota) => () => { location.hash = rota; };

  if (item.painel === "ocs") {
    return el("button", { class: "btn tonal small", onclick: ir("#/admin?aba=ocs") },
      "Abrir OCS");
  }
  if (item.tipo === "contrato") {
    return el("button", { class: "btn tonal small", onclick: ir("#/calendario") },
      "Abrir calendário");
  }
  if (item.ativo_id) {
    return el("button", {
      class: "btn tonal small",
      onclick: ir(`#/ativos?abrir=${item.ativo_id}`),
    }, "Ver ativo");
  }
  if (String(item.tipo || "").startsWith("transferencia")) {
    return el("button", { class: "btn tonal small", onclick: ir("#/movimentacoes") },
      "Ver transferências");
  }
  return el("span", {}, "");
}
