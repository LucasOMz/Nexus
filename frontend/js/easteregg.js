/**
 * Easter egg — um botão minúsculo e discreto no rodapé da barra lateral.
 *
 * Não aparece em menu nenhum e não tem rótulo: quem sabe, sabe. Depois de
 * `CLIQUE_ALVO` cliques abre a foto com a frase. É um ponto de 7px no rodapé —
 * some no meio da interface de propósito (o tamanho fica no CSS, em
 * `.easteregg-btn`).
 *
 * Fica fora da navegação por teclado (`tabindex="-1"`) para não atrapalhar
 * quem usa leitor de tela ou navega por Tab — é um segredo, não um controle.
 *
 * @module easteregg
 */
import { el, dialog } from "./ui.js";

const MENSAGEM = "Uma vez eu amei tanto uma flor, que ao invés de pegar ela, eu a deixei em paz.";
/** Quantos cliques no pontinho abrem a foto. */
export const CLIQUE_ALVO = 22;

let cliques = 0;

/** Abre a janela do easter egg. */
function revelar() {
  cliques = 0;
  dialog({
    title: "Ozzy",
    body: el("div", { class: "easteregg" },
      el("img", { class: "easteregg-foto", src: "/img/ozzy.png", alt: "Ozzy" }),
      el("p", { class: "easteregg-frase" }, MENSAGEM),
    ),
    actions: [{ label: "Fechar", variant: "text" }],
  });
}

/**
 * Cria o botão do rodapé. É minúsculo de propósito: precisa ser descoberto.
 * @returns {HTMLElement}
 */
export function botaoEasterEgg() {
  return el("button", {
    class: "easteregg-btn",
    type: "button",
    tabindex: "-1",
    "aria-hidden": "true",
    onclick: () => {
      cliques += 1;
      if (cliques >= CLIQUE_ALVO) revelar();
    },
  });
}
