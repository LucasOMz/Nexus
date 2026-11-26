import { api } from "../api.js";
import { ctx } from "../context.js";
import { el, mostrarErro, skeleton, toast } from "../ui.js";

const caminho = "/admin/config/ollama";
const caminhoPolitica = caminho + "/politica";
const origens = {
  administracao: "Configuração salva no Nexus",
  ambiente: "Configuração da stack",
  sem_configuracao: "Sem configuração",
};

function formularioPolitica(politica) {
  const ativo = el("input", { name: "chat_ativo", type: "checkbox", checked: politica.chat_ativo });
  const dias = el("input", { name: "historico_dias", id: "ollama-retencao", type: "number", min: 1, max: 3650, step: 1,
    value: politica.historico_dias ?? "", placeholder: "Sem expiração", "aria-describedby": "ollama-retencao-dica" });
  const aviso = el("p", { class: "muted", role: "status" });
  const salvar = el("button", { type: "submit", class: "btn filled" }, "Salvar acesso e retenção");
  return el("form", { class: "card", onsubmit: async ev => {
    ev.preventDefault();
    if (salvar.disabled) return;
    const body = { chat_ativo: ativo.checked, historico_dias: dias.value === "" ? null : dias.valueAsNumber };
    ativo.disabled = dias.disabled = salvar.disabled = true;
    aviso.textContent = "Salvando…";
    try {
      await api.request("PUT", caminhoPolitica, { body, enfileirar: false });
      aviso.textContent = body.chat_ativo ? "Assistente habilitado para as contas autorizadas." : "Assistente desabilitado para todas as contas.";
      ctx.atualizarChat();
      if (salvar.isConnected) toast("Acesso e retenção salvos");
    } catch (erro) {
      aviso.textContent = erro.message;
    } finally {
      ativo.disabled = dias.disabled = salvar.disabled = false;
    }
  } },
    el("h2", { class: "section-title" }, "Acesso e retenção do histórico"),
    el("label", { class: "perm-item" }, ativo, el("span", {}, "Habilitar o assistente do Nexus")),
    el("p", { class: "muted" }, "Com o assistente ligado, libere ou bloqueie cada conta em Administração → Usuários & Permissões."),
    el("div", { class: "field" },
      el("label", { for: "ollama-retencao" }, "Manter mensagens do histórico por quantos dias?"), dias,
      el("span", { class: "hint", id: "ollama-retencao-dica" },
        "Deixe vazio para manter sem expiração. Ao salvar um prazo, mensagens mais antigas que ele são excluídas e o Nexus continua fazendo a limpeza automaticamente.")),
    aviso, salvar);
}

export async function renderOllama(root) {
  root.replaceChildren(skeleton(3));
  let cfg;
  let politica;
  try {
    [cfg, politica] = await Promise.all([api.get(caminho), api.get(caminhoPolitica)]);
  } catch (erro) {
    root.replaceChildren(el("div", { class: "card" },
      el("p", {}, erro.message),
      el("button", { type: "button", class: "btn tonal", onclick: () => renderOllama(root) }, "Tentar novamente")));
    return;
  }

  const origem = el("span", { class: "badge" }, origens[cfg.origem]);
  const url = el("input", { id: "ollama-url", type: "url", required: true, maxlength: 500,
    value: cfg.url, placeholder: "http://192.168.7.50:11434", "aria-describedby": "ollama-url-dica" });
  const modelo = el("select", { id: "ollama-modelo", disabled: true });
  const testar = el("button", { type: "button", class: "btn tonal" }, "Testar conexão");
  const salvar = el("button", { type: "submit", class: "btn filled", disabled: true }, "Salvar configuração");
  const status = el("p", { class: "muted", role: "status" });
  let modelos = [];
  let trabalhando = false;

  function atualizarBotoes() {
    url.disabled = trabalhando;
    testar.disabled = trabalhando;
    modelo.disabled = trabalhando || !modelos.length;
    salvar.disabled = trabalhando || !modelos.includes(modelo.value);
  }

  function exibirModeloAtual() {
    modelo.replaceChildren(el("option", { value: "" },
      cfg.url && cfg.modelo ? `Em uso: ${cfg.modelo}` : "Teste a conexão para carregar os modelos"));
  }

  const form = el("form", { class: "card" },
    el("div", { class: "row between" }, el("h2", { class: "section-title" }, "Ollama"), origem),
    el("p", { class: "muted" }, "Configure o servidor e o modelo usados pelo chat do inventário."),
    el("div", { class: "form-grid" },
      el("div", { class: "field" },
        el("label", { for: "ollama-url" }, "Endereço do Ollama"),
        url,
        el("span", { class: "hint", id: "ollama-url-dica" }, "Use o IP privado ou o nome de rede do computador com Ollama.")),
      el("div", { class: "field" },
        el("label", { for: "ollama-modelo" }, "Modelo"),
        modelo,
        el("span", { class: "hint" }, "Escolha um modelo com suporte a ferramentas, como qwen3:32b."))),
    status,
    el("div", { class: "row", style: "flex-wrap:wrap" }, testar, salvar));

  url.addEventListener("input", () => {
    modelos = [];
    status.textContent = "";
    exibirModeloAtual();
    atualizarBotoes();
  });
  modelo.addEventListener("change", atualizarBotoes);
  testar.addEventListener("click", async () => {
    if (!url.reportValidity()) return;
    const preferido = modelo.value || cfg.modelo;
    modelos = [];
    exibirModeloAtual();
    trabalhando = true;
    atualizarBotoes();
    status.textContent = "Testando a partir do servidor Nexus…";
    try {
      const dados = await api.request("POST", caminho + "/testar", { body: { url: url.value }, enfileirar: false });
      modelos = dados.modelos;
      if (modelos.length) {
        modelo.replaceChildren(el("option", { value: "" }, "Selecione um modelo"),
          ...modelos.map(nome => el("option", { value: nome }, nome)));
        modelo.value = modelos.includes(preferido) ? preferido : "";
      }
      status.textContent = modelos.length
        ? "Conexão confirmada. Selecione um modelo e salve."
        : "Conexão confirmada. O servidor Ollama ainda não tem modelos instalados.";
    } catch (erro) {
      status.textContent = erro.message;
    } finally {
      trabalhando = false;
      atualizarBotoes();
    }
  });
  form.addEventListener("submit", async ev => {
    ev.preventDefault();
    if (salvar.disabled) return;
    trabalhando = true;
    atualizarBotoes();
    status.textContent = "Salvando configuração…";
    try {
      cfg = await api.request("PUT", caminho, { body: { url: url.value, modelo: modelo.value }, enfileirar: false });
      url.value = cfg.url;
      origem.textContent = origens[cfg.origem];
      status.textContent = "Configuração salva. O chat já pode usar o modelo selecionado.";
      if (root.isConnected) toast("Configuração do Ollama salva");
    } catch (erro) {
      status.textContent = erro.message;
      if (root.isConnected && erro.campos?.length) mostrarErro(erro);
    } finally {
      trabalhando = false;
      atualizarBotoes();
    }
  });

  exibirModeloAtual();
  root.replaceChildren(formularioPolitica(politica), form);
}
