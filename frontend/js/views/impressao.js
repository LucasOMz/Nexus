/**
 * Tela de Impressão — gestão das impressoras da PRÓPRIA planta.
 *
 * Acessível ao administrador e ao perfil **TI**. O técnico cadastra e ajusta
 * apenas a impressora da sua planta; as etiquetas (templates) são padronizadas
 * pelo administrador e aparecem aqui só para conferência.
 * @module views/impressao
 */
import { api } from "../api.js";
import { el, icon, mostrarErro } from "../ui.js";
import { abaDispositivos } from "./admin.js";

/** Mostra a etiqueta padrão (somente leitura para o perfil TI). */
async function cartaoEtiquetaPadrao() {
  const cartao = el("div", { class: "card" },
    el("div", { class: "section-title", style: "margin:0" }, "Etiqueta padrão"),
    el("p", { class: "muted", style: "font-size:13px;margin:6px 0 0" },
      "O layout da etiqueta é definido pelo administrador e vale para todas as plantas."),
  );

  try {
    const templates = await api.get("/admin/etiquetas").catch(() => []);
    const tpl = (templates || []).find((t) => t.padrao) || (templates || [])[0];
    if (!tpl) {
      cartao.append(el("p", { class: "muted", style: "margin-top:12px" },
        "Nenhuma etiqueta padrão definida ainda. Fale com o administrador."));
      return cartao;
    }
    cartao.append(el("p", { style: "margin:12px 0 0;font-weight:600" },
      `${tpl.nome || "Padrão"} — ${tpl.largura_mm} × ${tpl.altura_mm} mm a ${tpl.dpi} dpi`
      + (tpl.padrao ? "  (padrão do sistema)" : "")));
  } catch (e) {
    mostrarErro(e, "carregar a etiqueta padrão");
  }
  return cartao;
}

export async function renderImpressao(root) {
  root.innerHTML = "";

  // Mostra de qual planta é esta tela (o técnico vê a dele; o administrador
  // vê que está na visão de todas).
  const minhas = await api.get("/plantas/minhas").catch(() => []);
  const rotuloPlanta = minhas.length === 1
    ? minhas[0].sigla
    : (minhas.length ? "Todas as plantas" : "Minha planta");

  root.append(el("div", { class: "card" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Impressão"),
        el("div", { class: "muted", style: "font-size:13px" },
          "Cada planta imprime na sua própria impressora. Você gerencia a impressora "
          + "da sua planta; a etiqueta é padronizada pelo administrador."),
      ),
      el("span", { class: "chip", html: icon("print", 16) + " " + rotuloPlanta }),
    ),
  ));

  const area = el("div", {});
  root.append(area);

  // Reaproveita a MESMA tela de impressoras da administração: uma única
  // implementação, com o escopo de planta aplicado pelo backend.
  // O segundo argumento faz o "salvar" recarregar ESTA tela (e não a
  // administração, à qual o perfil TI não tem acesso).
  await abaDispositivos(area, () => renderImpressao(root));

  root.append(el("div", { style: "margin-top:16px" }, await cartaoEtiquetaPadrao()));
}
