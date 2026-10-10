/**
 * Assistente de configuração inicial.
 *
 * Página independente do PWA: precisa funcionar antes de existir banco.
 * O estado dos passos vive num objeto só, e ao final tudo é enviado numa
 * única chamada — assim o sistema nunca fica meio configurado.
 */
const API = "/setup";

// ---------------------------------------------------------------------------
// O assistente precisa ficar FORA do service worker do PWA.
//
// O service worker controla tudo que está sob "/", inclusive esta página. Se
// ele estiver ativo com a versão anterior do sistema, pode servir o app antigo
// no lugar do assistente — e a tela fica presa em "Carregando…".
//
// Este código é externo (setup.js), e não embutido no HTML, porque a política
// de segurança do sistema bloqueia scripts inline (`script-src 'self'`).
// ---------------------------------------------------------------------------
(async function sairDoServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  const controlada = Boolean(navigator.serviceWorker.controller);
  const jaTentei = sessionStorage.getItem("setup-sem-sw") === "1";

  try {
    const registros = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registros.map((r) => r.unregister()));
    if (window.caches) {
      const nomes = await caches.keys();
      await Promise.all(nomes.map((n) => caches.delete(n)));
    }
  } catch {
    // Sem permissão para limpar: seguimos assim mesmo, o servidor responde igual.
  }

  if (controlada && !jaTentei) {
    // Sai do controle do service worker e recarrega UMA vez (sem laço).
    sessionStorage.setItem("setup-sem-sw", "1");
    location.reload();
  } else {
    sessionStorage.removeItem("setup-sem-sw");
  }
})();

const estado = {
  rootEmail: "",
  rootSenha: "",
  passo: 0,
  dados: {
    empresa: { nome: "", rodape: "" },
    banco: { tipo: "sqlite", arquivo: "./estoque.db", criar_estrutura: true },
    admin: { nome: "", email: "", senha: "" },
    planta: { nome: "", sigla: "" },
    ad: { ativo: false, porta: 636, filtro_usuario: "(sAMAccountName={usuario})" },
    ocs: { ativo: false },
    logo: null,
    favicon: null,
  },
  bancos: [],
  resumo: null,
};

const $ = (sel) => document.querySelector(sel);

async function pedir(caminho, opcoes = {}) {
  const res = await fetch(API + caminho, opcoes);
  let dados = null;
  try { dados = await res.json(); } catch { /* resposta sem JSON */ }
  if (!res.ok) {
    const detalhe = dados && dados.detail ? dados.detail : `Erro ${res.status}`;
    throw new Error(typeof detalhe === "string" ? detalhe : JSON.stringify(detalhe));
  }
  return dados;
}

function campo(id, rotulo, valor = "", extra = {}) {
  const { tipo = "text", dica = "", obrigatorio = false, placeholder = "", classe = "" } = extra;
  return `<div class="campo ${classe}">
    <label for="${id}">${rotulo}${obrigatorio ? " *" : ""}</label>
    <input type="${tipo}" id="${id}" value="${escapar(valor)}" placeholder="${escapar(placeholder)}">
    ${dica ? `<span class="dica">${dica}</span>` : ""}
  </div>`;
}

const escapar = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---------------------------------------------------------------------------
// Passos
// ---------------------------------------------------------------------------
const PASSOS = [
  { chave: "root", rotulo: "Acesso", titulo: "Acesso ao assistente",
    render: passoRoot, validar: validaRoot },
  { chave: "empresa", rotulo: "Empresa", titulo: "Dados da empresa",
    render: passoEmpresa, validar: validaEmpresa },
  { chave: "banco", rotulo: "Banco", titulo: "Banco de dados",
    render: passoBanco, validar: validaBanco },
  { chave: "admin", rotulo: "Administrador", titulo: "Usuário administrador",
    render: passoAdmin, validar: validaAdmin },
  { chave: "planta", rotulo: "Planta", titulo: "Primeira planta",
    render: passoPlanta, validar: validaPlanta },
  { chave: "ad", rotulo: "AD", titulo: "Active Directory (opcional)",
    render: passoAD, validar: () => true },
  { chave: "ocs", rotulo: "OCS", titulo: "OCS Inventory (opcional)",
    render: passoOCS, validar: () => true },
  { chave: "fim", rotulo: "Concluir", titulo: "Revisar e concluir",
    render: passoFim, validar: () => true },
];

// --- 0. Acesso -------------------------------------------------------------
function passoRoot() {
  return `
    <h2>Acesso ao assistente</h2>
    <p class="desc">
      Esta é a configuração inicial do sistema. Ela só pode ser feita uma vez:
      ao concluir, este assistente deixa de responder.
    </p>
    <div class="recado info">
      Use as credenciais padrão que acompanham o sistema. Elas estão na
      documentação de instalação.
    </div>
    <div style="height:16px"></div>
    ${campo("root-email", "Usuário padrão", estado.rootEmail, { obrigatorio: true, placeholder: "admin@empresa.com" })}
    ${campo("root-senha", "Senha padrão", "", { tipo: "password", obrigatorio: true })}
  `;
}

async function validaRoot() {
  const email = $("#root-email").value.trim();
  const senha = $("#root-senha").value;
  const fd = new FormData();
  fd.append("email", email);
  fd.append("senha", senha);
  const r = await pedir("/validar-root", { method: "POST", body: fd });
  estado.rootEmail = email;
  estado.rootSenha = senha;
  return r.mensagem;
}

// --- 1. Empresa ------------------------------------------------------------
function passoEmpresa() {
  const e = estado.dados.empresa;
  return `
    <h2>Dados da empresa</h2>
    <p class="desc">
      O nome e a marca aparecem no topo do sistema, na tela de login e na aba do
      navegador. Você pode trocar isso depois.
    </p>
    ${campo("emp-nome", "Nome da empresa", e.nome, { obrigatorio: true, placeholder: "Yazaki do Brasil" })}
    ${campo("emp-rodape", "Frase no login (opcional)", e.rodape, { dica: "Ex.: Gestão de ativos de TI — Unidade Tatuí" })}
    <div class="grade">
      <div class="campo">
        <label for="emp-logo">Logotipo (PNG)</label>
        <input type="file" id="emp-logo" accept="image/*">
        <span class="dica">Aparece no topo e no login. Fundo transparente fica melhor.</span>
      </div>
      <div class="campo">
        <label for="emp-favicon">Ícone da aba (PNG/ICO)</label>
        <input type="file" id="emp-favicon" accept="image/*">
        <span class="dica">O quadradinho ao lado do título da aba. 32×32 ou 64×64.</span>
      </div>
    </div>
    <div id="emp-previa"></div>
  `;
}

async function validaEmpresa() {
  const nome = $("#emp-nome").value.trim();
  if (nome.length < 2) throw new Error("Informe o nome da empresa.");
  estado.dados.empresa.nome = nome;
  estado.dados.empresa.rodape = $("#emp-rodape").value.trim();

  for (const [id, chave] of [["emp-logo", "logo"], ["emp-favicon", "favicon"]]) {
    const arquivo = $("#" + id).files[0];
    if (!arquivo) continue;
    const fd = new FormData();
    fd.append("tipo", chave);
    fd.append("file", arquivo);
    const r = await pedir("/arquivo-marca", { method: "POST", body: fd });
    estado.dados[chave] = r.caminho;
  }
  if (estado.dados.logo) aplicarMarca();
  return "Empresa definida.";
}

// --- 2. Banco --------------------------------------------------------------
function passoBanco() {
  const b = estado.dados.banco;
  return `
    <h2>Banco de dados</h2>
    <p class="desc">
      Onde o sistema vai guardar tudo. Escolha com calma: depois de instalado, trocar
      exige copiar os dados manualmente.
    </p>
    <div id="lista-bancos">
      ${estado.bancos.map((x) => `
        <label class="opcao">
          <input type="radio" name="bk" value="${x.valor}" ${b.tipo === x.valor ? "checked" : ""}
                 ${x.driver_instalado ? "" : ""}>
          <span>
            <strong>${escapar(x.rotulo)}${x.driver_instalado ? "" : " — driver não instalado"}</strong>
            <span class="dica">${escapar(x.ajuda)}</span>
          </span>
        </label>`).join("")}
    </div>
    <div id="campos-banco"></div>
    <div id="teste-banco"></div>
  `;
}

function camposPorTipo() {
  const b = estado.dados.banco;
  if (b.tipo === "sqlite") {
    return campo("bk-arquivo", "Arquivo do banco", b.arquivo || "./estoque.db",
      { obrigatorio: true, dica: "Caminho relativo à pasta do sistema. Ex.: ./estoque.db" });
  }
  const porta = estado.bancos.find((x) => x.valor === b.tipo)?.porta_padrao || "";
  return `<div class="grade">
    ${campo("bk-servidor", "Servidor", b.servidor || "", { obrigatorio: true, placeholder: "192.168.1.50" })}
    ${campo("bk-porta", "Porta", b.porta || porta, { tipo: "number" })}
    ${campo("bk-banco", "Banco de dados", b.banco || "", { obrigatorio: true, placeholder: "estoque" })}
    ${campo("bk-usuario", "Usuário", b.usuario || "", { obrigatorio: true })}
  </div>
  ${campo("bk-senha", "Senha", b.senha || "", { tipo: "password" })}`;
}

function ligarCamposBanco() {
  document.querySelectorAll('input[name="bk"]').forEach((r) => {
    r.addEventListener("change", () => {
      estado.dados.banco.tipo = r.value;
      $("#campos-banco").innerHTML = camposPorTipo() + `
        <button class="btn text" type="button" id="btn-testar">Testar conexão</button>`;
      ligarTesteBanco();
    });
  });
  $("#campos-banco").innerHTML = camposPorTipo() + `
    <button class="btn text" type="button" id="btn-testar">Testar conexão</button>`;
  ligarTesteBanco();
}

function lerCamposBanco() {
  const b = estado.dados.banco;
  b.arquivo = $("#bk-arquivo")?.value.trim() || b.arquivo;
  b.servidor = $("#bk-servidor")?.value.trim() || null;
  b.porta = Number($("#bk-porta")?.value) || null;
  b.banco = $("#bk-banco")?.value.trim() || null;
  b.usuario = $("#bk-usuario")?.value.trim() || null;
  b.senha = $("#bk-senha")?.value || null;
  return b;
}

function ligarTesteBanco() {
  $("#btn-testar")?.addEventListener("click", async () => {
    const caixa = $("#teste-banco");
    caixa.innerHTML = `<div class="recado info">Testando…</div>`;
    try {
      const r = await pedir("/testar-banco", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(lerCamposBanco()),
      });
      caixa.innerHTML = `<div class="recado ${r.ok ? "ok" : "erro"}">${escapar(r.mensagem)}</div>`;
    } catch (e) {
      caixa.innerHTML = `<div class="recado erro">${escapar(e.message)}</div>`;
    }
  });
}

async function validaBanco() {
  lerCamposBanco();
  const b = estado.dados.banco;
  if (b.tipo === "sqlite" && !b.arquivo) throw new Error("Informe o arquivo do banco.");
  if (b.tipo !== "sqlite" && (!b.servidor || !b.banco || !b.usuario)) {
    throw new Error("Preencha servidor, banco e usuário.");
  }
  const r = await pedir("/testar-banco", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b),
  });
  if (r.ja_configurado) {
    estado.dados.banco.criar_estrutura = false;
    throw new Error("Este banco já tem a estrutura do sistema. Use um banco vazio ou marque para reutilizar.");
  }
  return r.mensagem;
}

// --- 3. Administrador ------------------------------------------------------
function passoAdmin() {
  const a = estado.dados.admin;
  return `
    <h2>Usuário administrador</h2>
    <p class="desc">
      Esta é a conta principal do sistema — a que cria usuários, define plantas e
      configura tudo. O acesso padrão do assistente <b>não</b> continua valendo depois.
    </p>
    ${campo("adm-nome", "Nome completo", a.nome, { obrigatorio: true })}
    ${campo("adm-email", "E-mail", a.email, { obrigatorio: true, placeholder: "ti@empresa.com" })}
    ${campo("adm-senha", "Senha", a.senha, { tipo: "password", obrigatorio: true, dica: "Mínimo de 8 caracteres." })}
    ${campo("adm-senha2", "Repita a senha", "", { tipo: "password", obrigatorio: true })}
  `;
}

function validaAdmin() {
  const a = estado.dados.admin;
  a.nome = $("#adm-nome").value.trim();
  a.email = $("#adm-email").value.trim();
  a.senha = $("#adm-senha").value;
  if (a.nome.length < 2) throw new Error("Informe o nome do administrador.");
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a.email)) throw new Error("Informe um e-mail válido.");
  if (a.senha.length < 8) throw new Error("A senha precisa de pelo menos 8 caracteres.");
  if (a.senha !== $("#adm-senha2").value) throw new Error("As senhas não conferem.");
  return "Administrador definido.";
}

// --- 4. Planta -------------------------------------------------------------
function passoPlanta() {
  const p = estado.dados.planta;
  return `
    <h2>Primeira planta</h2>
    <p class="desc">
      Cada planta é um inventário próprio: os ativos pertencem a ela e cada usuário
      enxerga a sua. Dá para cadastrar as outras depois.
    </p>
    ${campo("pl-nome", "Nome da planta", p.nome, { obrigatorio: true, placeholder: "Tatuí" })}
    ${campo("pl-sigla", "Sigla", p.sigla, { obrigatorio: true, placeholder: "TAT", dica: "3 a 5 letras. Aparece nas listas e relatórios." })}
  `;
}

function validaPlanta() {
  const p = estado.dados.planta;
  p.nome = $("#pl-nome").value.trim();
  p.sigla = $("#pl-sigla").value.trim().toUpperCase();
  if (p.nome.length < 2) throw new Error("Informe o nome da planta.");
  if (p.sigla.length < 2) throw new Error("Informe a sigla da planta.");
  return "Planta definida.";
}

// --- 5. AD -----------------------------------------------------------------
function passoAD() {
  const a = estado.dados.ad;
  return `
    <h2>Active Directory (opcional)</h2>
    <p class="desc">
      Se a empresa usa AD, os técnicos entram com o <b>usuário e senha de rede</b>.
      O AD confirma quem é a pessoa; quem libera o acesso continua sendo você, no
      cadastro de usuário.
    </p>
    <label class="opcao"><input type="checkbox" id="ad-ativo" ${a.ativo ? "checked" : ""}>
      <span><strong>Usar login pelo Active Directory</strong>
      <span class="dica">Pode configurar depois, em Administração → Autenticação.</span></span></label>
    <div id="ad-campos" class="${a.ativo ? "" : "oculto"}">
      <div class="grade">
        ${campo("ad-servidor", "Servidor", a.servidor || "", { placeholder: "dc01.empresa.local" })}
        ${campo("ad-porta", "Porta", a.porta, { tipo: "number", dica: "636 com SSL (recomendado)" })}
        ${campo("ad-base", "Base DN", a.base_dn || "", { classe: "largo", placeholder: "DC=empresa,DC=local" })}
        ${campo("ad-conta", "Conta de serviço", a.conta_servico || "", { placeholder: "svc_patrimonio@empresa.local" })}
        ${campo("ad-senha", "Senha da conta de serviço", "", { tipo: "password" })}
      </div>
      <div id="teste-ad"></div>
    </div>
  `;
}

function ligarAD() {
  const chk = $("#ad-ativo");
  chk?.addEventListener("change", () => {
    estado.dados.ad.ativo = chk.checked;
    $("#ad-campos").classList.toggle("oculto", !chk.checked);
  });
}

function lerCamposAD() {
  const a = estado.dados.ad;
  a.servidor = $("#ad-servidor")?.value.trim() || null;
  a.porta = Number($("#ad-porta")?.value) || 636;
  a.base_dn = $("#ad-base")?.value.trim() || null;
  a.conta_servico = $("#ad-conta")?.value.trim() || null;
  a.senha_servico = $("#ad-senha")?.value || null;
  return a;
}

// --- 6. OCS ----------------------------------------------------------------
function passoOCS() {
  const o = estado.dados.ocs;
  return `
    <h2>OCS Inventory (opcional)</h2>
    <p class="desc">
      Se a empresa usa OCS, o sistema pode importar o parque de máquinas
      automaticamente — com sistema operacional, memória e número de série. Planta,
      responsável e patrimônio continuam sendo seus.
    </p>
    <label class="opcao"><input type="checkbox" id="ocs-ativo" ${o.ativo ? "checked" : ""}>
      <span><strong>Importar máquinas do OCS</strong>
      <span class="dica">Pode configurar depois, em Administração → OCS Inventory.</span></span></label>
    <div id="ocs-campos" class="${o.ativo ? "" : "oculto"}">
      ${campo("ocs-servidor", "Endereço do OCS", o.servidor || "", { placeholder: "http://ocs-server/ocsinventory" })}
      ${campo("ocs-token", "Token da API", "", { tipo: "password" })}
      <div id="teste-ocs"></div>
    </div>
  `;
}

function ligarOCS() {
  const chk = $("#ocs-ativo");
  chk?.addEventListener("change", () => {
    estado.dados.ocs.ativo = chk.checked;
    $("#ocs-campos").classList.toggle("oculto", !chk.checked);
  });
}

// --- 7. Fim ----------------------------------------------------------------
function passoFim() {
  const d = estado.dados;
  return `
    <h2>Revisar e concluir</h2>
    <p class="desc">
      Confira os dados. Ao concluir, o sistema cria a estrutura no banco, cadastra o
      administrador e passa a valer no próximo início.
    </p>
    <div class="resumo">
      <div><span>Empresa</span><span>${escapar(d.empresa.nome)}</span></div>
      <div><span>Logotipo</span><span>${d.logo ? "enviado" : "não enviado"}</span></div>
      <div><span>Banco</span><span>${escapar(descricaoBanco())}</span></div>
      <div><span>Administrador</span><span>${escapar(d.admin.email)}</span></div>
      <div><span>Planta</span><span>${escapar(d.planta.nome)} (${escapar(d.planta.sigla)})</span></div>
      <div><span>Active Directory</span><span>${d.ad.ativo ? escapar(d.ad.servidor || "configurado") : "não usado"}</span></div>
      <div><span>OCS Inventory</span><span>${d.ocs.ativo ? escapar(d.ocs.servidor || "configurado") : "não usado"}</span></div>
    </div>
    <div id="resultado"></div>
  `;
}

function descricaoBanco() {
  const b = estado.dados.banco;
  if (b.tipo === "sqlite") return `SQLite — ${b.arquivo}`;
  return `${b.tipo} — ${b.servidor}:${b.porta}/${b.banco}`;
}

async function aplicar() {
  const caixa = $("#resultado");
  caixa.innerHTML = `<div class="recado info">Aplicando a configuração… não feche a página.</div>`;
  $("#avancar").disabled = true;
  try {
    const r = await pedir("/aplicar", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        root_email: estado.rootEmail, root_senha: estado.rootSenha,
        empresa: estado.dados.empresa, banco: estado.dados.banco,
        admin: estado.dados.admin, planta: estado.dados.planta,
        ad: estado.dados.ad, ocs: estado.dados.ocs,
        logo: estado.dados.logo, favicon: estado.dados.favicon,
      }),
    });
    caixa.innerHTML = `
      <div class="recado ok">
        <b>${escapar(r.mensagem)}</b>
        <ul>${r.passos.map((p) => `<li>${escapar(p)}</li>`).join("")}</ul>
        ${r.avisos?.length ? `<ul>${r.avisos.map((a) => `<li>${escapar(a)}</li>`).join("")}</ul>` : ""}
      </div>
      <div class="recado info">
        <b>Reinicie o sistema</b> e acesse com <b>${escapar(estado.dados.admin.email)}</b>
        e a senha que você definiu. Este assistente não abre mais.
      </div>`;
    $("#avancar").classList.add("oculto");
    $("#voltar").classList.add("oculto");
  } catch (e) {
    caixa.innerHTML = `<div class="recado erro">${escapar(e.message)}</div>`;
    $("#avancar").disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Navegação
// ---------------------------------------------------------------------------
function desenharPassos() {
  $("#passos").innerHTML = PASSOS.map((p, i) =>
    `<span class="passo ${i === estado.passo ? "atual" : i < estado.passo ? "feito" : ""}">${p.rotulo}</span>`
  ).join("");
}

function aplicarMarca() {
  $("#marca-titulo").textContent = estado.dados.empresa.nome || "Nexus";
  if (estado.dados.logo) {
    $("#marca-icone").style.backgroundImage = `url("${API}/marca/${estado.dados.logo}")`;
    $("#marca-icone").textContent = "";
  }
  if (estado.dados.favicon) {
    let link = document.querySelector("link[rel=icon]");
    if (!link) { link = document.createElement("link"); link.rel = "icon"; document.head.append(link); }
    link.href = `${API}/marca/${estado.dados.favicon}`;
  }
}

function ligarPasso() {
  const passo = PASSOS[estado.passo];
  if (passo.chave === "banco") ligarCamposBanco();
  if (passo.chave === "ad") ligarAD();
  if (passo.chave === "ocs") ligarOCS();
  if (passo.chave === "empresa") {
    $("#emp-nome").addEventListener("input", () => { estado.dados.empresa.nome = $("#emp-nome").value; });
  }
}

function renderizar() {
  const passo = PASSOS[estado.passo];
  $("#conteudo").innerHTML = passo.render();
  $("#aviso").textContent = "";
  $("#voltar").classList.toggle("oculto", estado.passo === 0);
  $("#avancar").textContent = estado.passo === PASSOS.length - 1 ? "Concluir instalação" : "Continuar";
  $("#avancar").disabled = false;
  desenharPassos();
  ligarPasso();
}

async function avancar() {
  const passo = PASSOS[estado.passo];
  const botao = $("#avancar");
  botao.disabled = true;
  try {
    const recado = await passo.validar();
    if (recado) $("#aviso").textContent = recado;
    if (estado.passo === PASSOS.length - 1) { await aplicar(); return; }
    estado.passo++;
    renderizar();
  } catch (e) {
    $("#aviso").textContent = "";
    const alvo = $("#conteudo");
    alvo.insertAdjacentHTML("beforeend", `<div class="recado erro">${escapar(e.message)}</div>`);
    botao.disabled = false;
  }
}

async function iniciar() {
  try {
    const s = await pedir("/estado");
    estado.bancos = s.bancos || [];
    if (s.instalado) {
      $("#conteudo").innerHTML = `
        <h2>Sistema já instalado</h2>
        <p class="desc">
          Este sistema já passou pela configuração inicial. O assistente não abre
          de novo — é o que impede que alguém aponte o sistema para outro banco.
        </p>
        <div class="recado info">Para começar a usar, acesse a página principal.</div>`;
      $("#avancar").classList.add("oculto");
      $("#voltar").classList.add("oculto");
      return;
    }
    renderizar();
  } catch (e) {
    $("#conteudo").innerHTML = `<div class="recado erro">Não foi possível falar com o servidor: ${escapar(e.message)}</div>`;
  }
}

$("#avancar").addEventListener("click", avancar);
$("#voltar").addEventListener("click", () => {
  if (estado.passo > 0) { estado.passo--; renderizar(); }
});

iniciar();

// ---------------------------------------------------------------------------
// Rede de segurança: se em 8 segundos nada apareceu, explicamos o motivo em vez
// de deixar a tela presa num "Carregando…" que não diz nada.
// ---------------------------------------------------------------------------
window.addEventListener("load", () => {
  setTimeout(() => {
    const alvo = document.getElementById("conteudo");
    if (!alvo || alvo.textContent.trim() !== "Carregando…") return;
    alvo.innerHTML = `
      <h2>A página não carregou</h2>
      <p class="desc">O assistente abriu, mas o JavaScript não respondeu.</p>
      <div class="recado erro">
        <b>Como resolver</b>
        <ul>
          <li>Recarregue com <b>Ctrl + Shift + R</b> (recarga forçada, sem cache).</li>
          <li>Se continuar, abra numa <b>janela anônima</b> — a versão anterior
              do sistema pode estar em cache no navegador.</li>
          <li>Confirme que o endereço é <code>/instalacao</code>.</li>
        </ul>
      </div>`;
  }, 8000);
});
