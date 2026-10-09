/**
 * Sino de notificações da barra superior.
 *
 * Avisa o que precisa de atenção AGORA — principalmente empréstimos: quando
 * chega o dia de devolver, quando atrasou e quando está chegando a hora.
 *
 * @module notificacoes
 */
import { api } from "./api.js";
import { el, icon } from "./ui.js";

// Reconsulta de tempos em tempos: o sino precisa estar certo mesmo com a
// página aberta o dia inteiro.
const INTERVALO_MS = 5 * 60 * 1000;

const CORES = {
  erro: "erro",
  urgente: "urgente",
  info: "info",
};

function irPara(item, fechar) {
  fechar();
  // Aviso da integração com o OCS: abre o painel já na aba certa.
  if (item.painel === "ocs") {
    location.hash = "#/admin?aba=ocs";
    return;
  }
  // Transferência pendente: leva direto para a tela de decisão.
  if (item.transferencia_id) {
    location.hash = "#/movimentacoes";
    return;
  }
  // Abre a tela de Ativos já filtrada e com o item destacado.
  location.hash = `#/ativos?busca=${encodeURIComponent(item.patrimonio)}&destaque=${item.ativo_id}`;
}

function abrirPainel(dados, fechar) {
  const itens = dados.itens || [];
  const painel = el("div", { class: "notif-painel" },
    el("div", { class: "notif-cabecalho" },
      el("strong", {}, "Notificações"),
      itens.length ? el("span", { class: "muted" }, `${itens.length} no total`) : null,
    ),
  );

  if (!itens.length) {
    painel.append(el("div", { class: "notif-vazio" }, "Nada pendente por aqui. Tudo em dia. 🎉"));
  } else {
    itens.forEach((n) => {
      const linha = el("button", { type: "button", class: `notif-item ${CORES[n.nivel] || "info"}` },
        el("span", { class: "notif-ponto" }),
        el("span", { class: "notif-texto" },
          el("strong", {}, n.titulo),
          el("span", { class: "notif-detalhe" }, n.detalhe),
        ),
      );
      linha.addEventListener("click", () => irPara(n, fechar));
      painel.append(linha);
    });
  }

  painel.append(el("div", { class: "notif-rodape" },
    el("button", {
      type: "button", class: "btn text small",
      onclick: () => { fechar(); location.hash = "#/calendario"; },
    }, "Abrir calendário"),
  ));

  return painel;
}

/**
 * Cria o botão do sino já ligado à API.
 * @returns {HTMLElement}
 */
export function sinoNotificacoes() {
  let aberto = null;
  let dados = { total: 0, urgentes: 0, itens: [] };

  const contador = el("span", { class: "notif-contador hidden" });
  const botao = el("button", {
    class: "iconbtn notif-sino",
    title: "Notificações",
    html: icon("bell", 22),
  });
  botao.append(contador);

  function fechar() {
    if (!aberto) return;
    aberto.remove();
    aberto = null;
    document.removeEventListener("click", foraDoPainel);
    document.removeEventListener("keydown", porEsc);
  }

  function foraDoPainel(ev) {
    if (aberto && !aberto.contains(ev.target) && !botao.contains(ev.target)) fechar();
  }

  function porEsc(ev) {
    if (ev.key === "Escape") fechar();
  }

  function alternar() {
    if (aberto) { fechar(); return; }
    aberto = abrirPainel(dados, fechar);
    botao.parentElement.style.position = "relative";
    botao.parentElement.append(aberto);
    // Um tick de espera para o clique atual não fechar o painel na hora.
    setTimeout(() => {
      document.addEventListener("click", foraDoPainel);
      document.addEventListener("keydown", porEsc);
    }, 0);
  }

  function pintar() {
    const n = dados.urgentes || 0;
    if (!n) {
      contador.classList.add("hidden");
    } else {
      contador.textContent = n > 99 ? "99+" : String(n);
      contador.classList.remove("hidden");
      botao.classList.toggle("tem-urgente", dados.itens.some((i) => i.nivel === "erro"));
    }
  }

  async function atualizar() {
    try {
      dados = await api.get("/notificacoes");
    } catch {
      // Sem resposta (offline, por exemplo): mantém o que já tinha.
      return;
    }
    pintar();
    if (aberto) { fechar(); alternar(); }
  }

  botao.addEventListener("click", (ev) => { ev.stopPropagation(); alternar(); });
  botao.addEventListener("mousedown", (ev) => ev.preventDefault());

  atualizar();
  setInterval(atualizar, INTERVALO_MS);

  /** Permite reconsultar na hora (ex.: depois de registrar um empréstimo). */
  botao.atualizarNotificacoes = atualizar;
  return botao;
}
