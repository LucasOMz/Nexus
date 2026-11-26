import { api } from "./api.js";
import { state } from "./state.js";
import { el, icon } from "./ui.js";

const numero = new Intl.NumberFormat("pt-BR");

function botaoIcone(icone, rotulo, classe, tipo = "button") {
  return el("button", { type: tipo, class: classe, title: rotulo, "aria-label": rotulo, html: icon(icone, 20) });
}

function metricas(dados) {
  if (dados.operacao === "percentual" || "percentual" in dados) {
    return dados.percentual === null ? "Sem equipamentos no grupo"
      : `${numero.format(dados.percentual)}% · ${numero.format(dados.correspondentes)} de ${numero.format(dados.total)}`;
  }
  return numero.format(dados.total);
}

function listaEquipamentos(dados) {
  if (dados.aviso) return el("p", {}, dados.aviso);
  const { equipamentos, total } = dados;
  const lista = el("ul", { class: "chat-ia-lista" });
  for (const ativo of equipamentos) {
    const nome = ativo.hostname || ativo.modelo || `Equipamento #${ativo.id}`;
    const detalhes = [ativo.patrimonio ? `Patrimônio ${ativo.patrimonio}` : "Sem patrimônio", ativo.departamento, ativo.planta];
    lista.append(el("li", {}, el("strong", {}, nome), el("small", {}, detalhes.filter(Boolean).join(" · "))));
  }
  const legenda = total
    ? `Mostrando ${numero.format(equipamentos.length)} de ${numero.format(total)} equipamentos`
    : "Nenhum equipamento encontrado.";
  return el("div", {}, el("small", {}, legenda), lista);
}

export function criarChatIa() {
  const elemento = el("aside", { class: "chat-ia", "aria-label": "Assistente de inventário" });
  const abrir = botaoIcone("chat", "Abrir chat do inventário", "chat-ia-toggle");
  abrir.setAttribute("aria-controls", "chat-ia-painel");
  const limpar = botaoIcone("plus", "Nova conversa", "chat-ia-acao");
  const fechar = botaoIcone("close", "Fechar chat", "chat-ia-acao");
  const log = el("div", { class: "chat-ia-log", role: "log", "aria-label": "Conversa" });
  const entrada = el("textarea", { rows: 2, maxlength: 1000, "aria-label": "Pergunta ao inventário", placeholder: "Pergunte sobre seus equipamentos…" });
  const enviar = botaoIcone("enviar", "Enviar pergunta", "chat-ia-enviar", "submit");
  const formulario = el("form", { class: "chat-ia-form" }, entrada, enviar);
  const painel = el("section", { id: "chat-ia-painel", class: "chat-ia-painel", "aria-labelledby": "chat-ia-titulo", hidden: true },
    el("header", { class: "chat-ia-topo" },
      el("h2", { id: "chat-ia-titulo" }, "Chat do inventário"),
      limpar, fechar),
    log, formulario);
  elemento.append(painel, abrir);

  let escopo;
  let geracao = 0;
  let historico = [];

  function mostrar(visivel) {
    painel.hidden = !visivel;
    abrir.setAttribute("aria-expanded", String(visivel));
    abrir.setAttribute("aria-label", visivel ? "Fechar chat do inventário" : "Abrir chat do inventário");
    abrir.title = abrir.getAttribute("aria-label");
    abrir.innerHTML = icon(visivel ? "close" : "chat", 24);
    if (visivel) {
      fechar.focus();
      log.scrollTop = log.scrollHeight;
    } else if (elemento.contains(document.activeElement)) {
      abrir.focus();
    }
  }

  function mensagem(texto, classe = "") {
    const bloco = el("div", { class: `chat-ia-mensagem ${classe}` }, texto);
    log.append(bloco);
    log.scrollTop = log.scrollHeight;
    return bloco;
  }

  function reiniciar() {
    geracao++;
    historico = [];
    entrada.value = "";
    enviar.disabled = false;
    log.replaceChildren();
    mensagem("Pergunte sobre o inventário. Por exemplo: quantos computadores estão sem patrimônio por departamento?");
  }

  function resultado(dados, atual) {
    const bloco = el("div", { class: "chat-ia-resultado" });
    if (dados.aviso) {
      bloco.append(el("p", {}, dados.aviso));
      return bloco;
    }
    if (dados.operacao === "listar") {
      bloco.append(listaEquipamentos(dados));
      return bloco;
    }
    bloco.append(el("strong", {}, metricas(dados)), el("small", {}, "Total da consulta"));
    if (dados.grupos?.length) {
      const grupos = el("ul", { class: "chat-ia-lista chat-ia-grupos" });
      for (const grupo of dados.grupos) {
        grupos.append(el("li", {}, el("span", {}, grupo.valores.map(v => v || "Sem cadastro").join(" · ")),
          el("strong", {}, metricas(grupo))));
      }
      bloco.append(grupos);
      if (dados.truncado) bloco.append(el("small", {}, "Outros grupos ficaram fora do limite de exibição."));
    }
    if ((dados.correspondentes ?? dados.total) > 0) {
      const ver = el("button", { type: "button", class: "chat-ia-ver" }, "Ver equipamentos");
      const detalhe = el("div", {});
      ver.addEventListener("click", async () => {
        ver.disabled = true;
        detalhe.textContent = "Carregando equipamentos…";
        try {
          const lista = await api.request("POST", "/ia/equipamentos", { body: dados.consulta, enfileirar: false });
          if (atual !== geracao || !elemento.isConnected) return;
          detalhe.replaceChildren(listaEquipamentos(lista));
          ver.remove();
        } catch (erro) {
          if (atual !== geracao || !elemento.isConnected) return;
          detalhe.textContent = erro.message || "Não foi possível carregar os equipamentos.";
          ver.disabled = false;
        }
      });
      bloco.append(ver, detalhe);
    }
    return bloco;
  }

  abrir.addEventListener("click", () => mostrar(painel.hidden));
  fechar.addEventListener("click", () => mostrar(false));
  limpar.addEventListener("click", () => { reiniciar(); entrada.focus(); });
  elemento.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && !painel.hidden) {
      ev.stopPropagation();
      mostrar(false);
    }
  });
  entrada.addEventListener("keydown", ev => {
    if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
      ev.preventDefault();
      formulario.requestSubmit();
    }
  });
  formulario.addEventListener("submit", async ev => {
    ev.preventDefault();
    const pergunta = entrada.value.trim();
    if (!pergunta || enviar.disabled) return;
    const atual = geracao;
    const body = { pergunta, historico: historico.slice(-6) };
    mensagem(pergunta, "chat-ia-pergunta");
    entrada.value = "";
    enviar.disabled = true;
    const aguardando = mensagem("Consultando o inventário…", "chat-ia-aguarde");
    try {
      const dados = await api.request("POST", "/ia/chat", { body, enfileirar: false, prazoMs: 315000 });
      if (atual !== geracao || !elemento.isConnected) return;
      historico = [...body.historico, pergunta];
      aguardando.remove();
      const resposta = mensagem(dados.resposta);
      for (const item of dados.resultados) resposta.append(resultado(item, atual));
      log.scrollTop = resposta.offsetTop - log.offsetTop;
    } catch (erro) {
      if (atual !== geracao || !elemento.isConnected) return;
      aguardando.remove();
      mensagem(erro.message || "Não foi possível consultar o inventário.");
      if (!entrada.value) entrada.value = pergunta;
    } finally {
      if (atual === geracao) enviar.disabled = false;
    }
  });

  mostrar(false);
  return {
    elemento,
    atualizarEscopo() {
      const chave = JSON.stringify([state.user?.id, state.plantaAtiva]);
      if (chave !== escopo) {
        escopo = chave;
        reiniciar();
      }
    },
  };
}
