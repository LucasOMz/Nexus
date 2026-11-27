import { api } from "../api.js";
import { atualizarPrazoSessao } from "../sessao.js";
import { el, skeleton, toast } from "../ui.js";

export async function renderSessao(root) {
  root.replaceChildren(skeleton(2));
  let politica;
  try {
    politica = await api.get("/auth/politica-sessao");
  } catch (erro) {
    root.replaceChildren(el("div", { class: "card" }, el("p", {}, erro.message),
      el("button", { class: "btn tonal", type: "button", onclick: () => renderSessao(root) }, "Tentar novamente")));
    return;
  }
  const minutos = el("input", { id: "sessao-minutos", type: "number", min: 1, max: 1440, step: 1,
    required: true, value: politica.inatividade_minutos, "aria-describedby": "sessao-minutos-dica" });
  const salvar = el("button", { type: "submit", class: "btn filled" }, "Salvar tempo de inatividade");
  const recado = el("p", { class: "muted", role: "status" });
  root.replaceChildren(el("form", { class: "card", onsubmit: async (evento) => {
    evento.preventDefault();
    if (salvar.disabled) return;
    const valor = minutos.valueAsNumber;
    salvar.disabled = minutos.disabled = true;
    recado.textContent = "";
    try {
      const atualizado = await api.request("PUT", "/admin/config/politica-sessao", {
        body: { inatividade_minutos: valor }, enfileirar: false,
      });
      atualizarPrazoSessao(atualizado.inatividade_minutos);
      recado.textContent = "Prazo atualizado para todas as contas.";
      if (root.isConnected) toast("Tempo de inatividade salvo");
    } catch (erro) {
      recado.textContent = erro.message;
    } finally {
      salvar.disabled = minutos.disabled = false;
    }
  } },
  el("div", { class: "field" },
    el("label", { for: "sessao-minutos" }, "Tempo de inatividade (minutos)"), minutos,
    el("span", { class: "hint", id: "sessao-minutos-dica" },
      "De 1 a 1440 minutos. O Nexus pede novo login após esse tempo sem interação. O padrão é 10 minutos.")),
  recado, salvar));
}
