import { el } from "./ui.js";

const root = document.getElementById("termo-publico");
const codigo = location.hash.slice(1);
const base = "/api/v1/termo-entrega";
let sessao = "", imagemAtual = "";

async function solicitar(rota, body, binario = false) {
  const headers = { Authorization: "Bearer " + codigo };
  if (sessao) headers["X-Termo-Sessao"] = sessao;
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(base + rota, { method: body ? "POST" : "GET", headers,
    body: body ? JSON.stringify(body) : undefined, cache: "no-store", referrerPolicy: "no-referrer" });
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail;
    throw new Error(typeof detail === "string" ? detail : "Não foi possível concluir esta operação.");
  }
  return binario ? res.blob() : res.json();
}

function cartao(titulo, texto, ...acoes) {
  root.replaceChildren(el("section", { class: "card termo-mensagem" },
    el("div", { class: "termo-marca-nexus" }, el("span", { class: "nexus-marca-icone" }), "Nexus"),
    el("h1", {}, titulo), el("p", {}, texto), ...acoes));
}

const finalizados = {
  assinado: ["Termo já enviado", "Seu checklist foi recebido e o termo está assinado."],
  expirado: ["Link expirado", "O termo ainda está pendente. Peça à TI um novo link."],
  substituido: ["Convite substituído", "Esta entrega mudou. Consulte o último e-mail recebido da TI."],
  falha_envio: ["Convite indisponível", "Peça à TI para reenviar o termo."],
  enviando: ["Envio em andamento", "Aguarde alguns instantes e abra novamente o link."],
};

function mostrarEstado(dados) {
  if (!finalizados[dados.estado]) return false;
  sessao = "";
  if (imagemAtual) URL.revokeObjectURL(imagemAtual);
  imagemAtual = "";
  cartao(...finalizados[dados.estado]);
  return true;
}

function login() {
  const usuario = el("input", { id: "termo-login", required: true, maxlength: 120, autocomplete: "username" });
  const senha = el("input", { id: "termo-senha", required: true, maxlength: 256, autocomplete: "current-password", type: "password" });
  const continuar = el("button", { type: "submit", class: "btn filled" }, "Abrir termo");
  const recado = el("p", { role: "status" });
  const form = el("form", {},
    el("label", { class: "field" }, "Login de rede", usuario),
    el("label", { class: "field" }, "Senha de rede", senha), continuar, recado);
  form.onsubmit = async evento => {
    evento.preventDefault();
    if (continuar.disabled) return;
    continuar.disabled = true;
    recado.textContent = "Confirmando identidade…";
    const body = { login: usuario.value, senha: senha.value };
    senha.value = "";
    try { await preencher(await solicitar("/autenticar", body)); }
    catch (erro) { recado.textContent = erro.message; }
    finally { continuar.disabled = false; }
  };
  cartao("Seu termo de entrega", "Entre com sua conta de rede para abrir o checklist e assinar o termo.", form);
}

async function preencher(dados) {
  sessao = dados.sessao;
  const rascunho = dados.rascunho;
  let pagina = 1, versao = 0, paginaRenderizada = 0, assinatura = rascunho?.assinatura_png || null;
  const campos = {};
  const recado = el("p", { role: "status" });
  const foto = el("img", { alt: "Página do termo de entrega" });
  const legenda = el("strong");
  const voltar = el("button", { type: "button", class: "btn text", onclick: () => carregar(pagina - 1) }, "Anterior");
  const avancar = el("button", { type: "button", class: "btn text", onclick: () => carregar(pagina + 1) }, "Próxima");
  const ampliar = el("a", { class: "termo-ampliar", target: "_blank", rel: "noopener noreferrer", hidden: true },
    "Ampliar página");
  const marcas = el("div", { class: "termo-marcadores" });
  const camposFormulario = el("div");
  async function carregar(numero, selecionado = "") {
    pagina = Math.min(Math.max(numero, 1), dados.paginas);
    const revisao = ++versao;
    legenda.textContent = `Página ${pagina} de ${dados.paginas}`;
    voltar.disabled = pagina <= 1;
    avancar.disabled = pagina >= dados.paginas;
    marcas.replaceChildren(...dados.campos.filter(c => c.pagina === pagina && c.id === selecionado).map(c =>
      el("span", { class: "termo-marca ativa", style: `left:${c.x}%;top:${c.y}%;width:${c.largura}%;height:${c.altura}%` })));
    if (paginaRenderizada === pagina && !foto.hidden) return;
    foto.hidden = true;
    ampliar.hidden = true;
    try {
      const imagem = URL.createObjectURL(await solicitar("/pagina/" + pagina, null, true));
      if (versao !== revisao || !foto.isConnected) { URL.revokeObjectURL(imagem); return; }
      if (imagemAtual) URL.revokeObjectURL(imagemAtual);
      imagemAtual = imagem;
      foto.src = imagem;
      ampliar.href = imagem;
      ampliar.hidden = false;
      foto.hidden = false;
      paginaRenderizada = pagina;
    } catch (erro) { if (versao === revisao) recado.textContent = erro.message; }
  }
  for (const c of dados.campos) {
    if (c.tipo === "assinatura") continue;
    const campo = el("input", { type: c.tipo === "leitura" ? "checkbox" : c.tipo === "data" ? "date" : "text",
      maxlength: 200, required: c.obrigatorio,
      checked: c.tipo === "leitura" && rascunho?.campos[c.id] === true,
      value: c.tipo === "nome" ? dados.colaborador : c.tipo === "patrimonio" ? dados.equipamento : rascunho?.campos[c.id] || "",
      readonly: c.tipo === "nome" || c.tipo === "patrimonio" });
    campo.addEventListener("focus", () => carregar(c.pagina, c.id));
    campos[c.id] = campo;
    camposFormulario.append(c.tipo === "leitura"
      ? el("label", { class: "row termo-opcao" }, campo, c.rotulo + ` · página ${c.pagina}`)
      : el("label", { class: "field" }, c.rotulo, campo));
  }
  const fonte = el("select", { "aria-label": "Fonte da assinatura" },
    el("option", { value: "classica" }, "Clássica"), el("option", { value: "inclinada" }, "Inclinada"),
    el("option", { value: "manuscrita" }, "Monoespaçada"));
  fonte.value = rascunho?.fonte || "classica";
  const previa = el("div", { class: "termo-assinatura", "data-fonte": fonte.value }, dados.colaborador);
  if (assinatura) previa.replaceChildren(el("img", { src: "data:image/png;base64," + assinatura, alt: "Assinatura em PNG" }));
  const png = el("input", { type: "file", accept: "image/png,.png" });
  fonte.onchange = () => { previa.dataset.fonte = fonte.value; };
  png.onchange = async () => {
    const arquivo = png.files[0];
    enviar.disabled = false;
    assinatura = null;
    previa.textContent = dados.colaborador;
    if (!arquivo) return;
    if (arquivo.size > 530000 || arquivo.type !== "image/png") {
      recado.textContent = "Escolha um PNG de até 530 KB.";
      png.value = "";
      return;
    }
    const leitor = new FileReader();
    enviar.disabled = true;
    leitor.onload = () => {
      if (png.files[0] !== arquivo) return;
      assinatura = String(leitor.result).split(",")[1];
      previa.replaceChildren(el("img", { src: String(leitor.result), alt: "Imagem da assinatura selecionada" }));
      recado.textContent = "";
    };
    leitor.onloadend = () => { if (png.files[0] === arquivo) enviar.disabled = false; };
    leitor.readAsDataURL(arquivo);
  };
  const agente = el("input", { type: "checkbox", checked: dados.exigir_agente || rascunho?.confirmar_no_agente, disabled: dados.exigir_agente });
  const enviar = el("button", { type: "submit", class: "btn filled" }, "Enviar termo");
  const form = el("form", { id: "termo-checklist", class: "card termo-form-publico" },
    el("h2", {}, "Checklist e assinatura"), camposFormulario, previa, fonte,
    el("label", { class: "field" }, "Ou importe uma assinatura em PNG", png),
    dados.agente_vinculado ? el("label", { class: "row termo-opcao" }, agente, "Também confirmar no computador atribuído") : null,
    enviar, recado);
  form.onsubmit = async evento => {
    evento.preventDefault();
    if (enviar.disabled) return;
    enviar.disabled = true;
    recado.textContent = "Registrando o termo…";
    const valores = Object.fromEntries(Object.entries(campos).map(([id, campo]) =>
      [id, campo.type === "checkbox" ? campo.checked : campo.value]));
    try {
      dados.rascunho = { campos: valores, fonte: fonte.value, assinatura_png: assinatura, confirmar_no_agente: agente.checked };
      const resultado = await solicitar("/assinar", dados.rascunho);
      if (!mostrarEstado(resultado)) aguardarAgente(resultado.codigo, dados);
    } catch (erro) { recado.textContent = erro.message; }
    finally { enviar.disabled = false; }
  };
  root.replaceChildren(el("header", {},
    el("h1", {}, "Termo de entrega"), el("p", {}, dados.colaborador + " · " + dados.equipamento)),
    el("div", { class: "termo-editor termo-leitura" }, el("section", { class: "card" },
      el("div", { class: "row wrap" }, voltar, legenda, avancar, ampliar), el("div", { class: "termo-folha" }, foto, marcas)), form));
  await carregar(1);
}

function aguardarAgente(codigoAgente, dados) {
  const atual = el("p", { role: "status" });
  let timer;
  const voltar = el("button", { class: "btn text", type: "button", onclick: () => {
    clearTimeout(timer); preencher(dados);
  } }, "Voltar ao checklist");
  cartao("Confirme no computador atribuído", "No Agente Nexus, abra Confirmar termo de entrega e informe este código.",
    el("strong", { class: "termo-codigo" }, codigoAgente), atual, voltar);
  async function consultar() {
    if (!atual.isConnected) return;
    try {
      const estado = await solicitar("/estado");
      if (mostrarEstado(estado)) return;
      if (estado.estado === "codigo_expirado") {
        atual.textContent = "O código venceu. Volte ao checklist para gerar outro.";
        return;
      }
      atual.textContent = "Aguardando a confirmação do agente…";
    } catch { atual.textContent = "Sem comunicação com o Nexus. Tentando novamente…"; }
    timer = setTimeout(consultar, 5000);
  }
  consultar();
}

if (!window.isSecureContext) {
  cartao("Acesso por HTTPS", "Abra o endereço HTTPS do Nexus enviado pela TI.");
} else if (!codigo) {
  cartao("Convite necessário", "Abra o link do termo que você recebeu por e-mail.");
} else {
  cartao("Termo de entrega", "Verificando o convite…");
  solicitar("/estado").then(dados => { if (!mostrarEstado(dados)) login(); })
    .catch(erro => cartao("Convite indisponível", erro.message));
}
