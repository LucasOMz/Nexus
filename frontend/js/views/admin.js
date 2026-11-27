/**
 * Administração: usuários & permissões, dispositivos de impressão e banco de fotos.
 * @module views/admin
 */
import { api } from "../api.js";
import { fotoProtegida } from "../fotos.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, skeleton, emptyState, mostrarErro } from "../ui.js";
import { loadLookups, optionsOf } from "../lookups.js";
import { erroDeResposta } from "../erros.js";
import { renderTemplates } from "./admin_etiquetas.js";
import { renderBackups } from "./admin_backups.js";
import { renderAuth } from "./admin_auth.js";
import { renderLgpd } from "./admin_lgpd.js";
import { renderChecklist } from "./admin_checklist.js";
import { renderBanco } from "./admin_banco.js";
import { renderAuditoria } from "./admin_auditoria.js";
import { renderNotificacoes } from "./admin_notificacoes.js";
import { renderAgenteIA } from "./admin_ollama.js";
import { renderSessao } from "./admin_sessao.js";
import { renderManutencao } from "./admin_manutencao.js";
import { renderAgente } from "./admin_agente.js";
import { renderPlantas } from "./admin_plantas.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let meta = { modulos: [], inventarios: [] };

// ---------------------------------------------------------------------------
// Usuários & permissões
// ---------------------------------------------------------------------------
function blocoPermissoes(usuario, lookups) {
  const perms = usuario?.permissoes_efetivas || {};
  const modAtuais = perms.modulos || [];

  const modHtml = meta.modulos.map((m) => `
    <label class="perm-item ${modAtuais.includes(m.chave) ? "checked" : ""}">
      <input type="checkbox" name="mod_${m.chave}" ${modAtuais.includes(m.chave) ? "checked" : ""}>
      <span>${esc(m.rotulo)}</span>
    </label>`).join("");

  const inventarios = perms.inventarios || ["ti", "impressora"];
  const acessoTodos = inventarios.includes("ti") && inventarios.includes("impressora");
  const acessoValor = acessoTodos ? "ambos" : (inventarios[0] || "ambos");

  return `
    <div class="form-section">
      <h4>Acesso aos inventários</h4>
      <p class="muted" style="margin:0 0 10px;font-size:13px">
        Define <b>quais inventários</b> este usuário enxerga. A escolha vale para
        as telas de Ativos, Consumíveis, Relatórios, Leitura e Calendário.
      </p>
      <div class="field">
        <select name="inventarios" id="usuario-inventarios">
          <option value="ambos" ${acessoValor === "ambos" ? "selected" : ""}>Ambos — TI e Impressoras</option>
          <option value="ti" ${acessoValor === "ti" ? "selected" : ""}>Somente TI</option>
          <option value="impressora" ${acessoValor === "impressora" ? "selected" : ""}>Somente Impressoras</option>
        </select>
      </div>
    </div>
    <div class="form-section">
      <h4>Módulos liberados</h4>
      <div class="perm-grid">${modHtml}</div>
    </div>
    <div class="form-section">
      <h4>Assistente do Nexus</h4>
      <label class="perm-item">
        <input type="checkbox" name="chat_ia_ativo" ${usuario?.chat_ia_ativo !== false ? "checked" : ""}>
        <span>Permitir acesso ao assistente e ao histórico pessoal</span>
      </label>
    </div>
    <div class="form-section">
      <h4>Ações permitidas</h4>
      <div class="perm-grid">
        <label class="perm-item ${perms.pode_escrever ? "checked" : ""}">
          <input type="checkbox" name="pode_escrever" ${perms.pode_escrever ? "checked" : ""}>
          <span>Criar / editar</span>
        </label>
        <label class="perm-item ${perms.pode_excluir ? "checked" : ""}">
          <input type="checkbox" name="pode_excluir" ${perms.pode_excluir ? "checked" : ""}>
          <span>Excluir</span>
        </label>
        <label class="perm-item ${perms.pode_acoes_agente ? "checked" : ""}">
          <input type="checkbox" name="pode_acoes_agente" ${perms.pode_acoes_agente ? "checked" : ""}>
          <span>Ações remotas do agente</span>
        </label>
      </div>
    </div>`;
}

function abrirUsuario(usuario, lookups) {
  const isEdit = Boolean(usuario);
  const u = usuario || {};
  const form = el("form", { html: `
    <div class="form-section" id="bloco-ad">
      <h4>Conta de rede (Active Directory)</h4>
      <p class="muted" style="margin:0 0 12px;font-size:13px">
        Digite o <b>usuário de logon</b> da pessoa e clique em Buscar: o nome e o
        e-mail vêm preenchidos do diretório. A senha dela é a <b>senha de rede</b>
        — não é cadastrada aqui. O acesso só existe depois que você salvar.
      </p>
      <div class="form-grid">
        <div class="field span-2"><label>Usuário de rede</label>
          <div class="row" style="gap:8px;align-items:flex-start">
            <input name="login_ad" id="usuario-login-ad" style="flex:1"
                   placeholder="ex.: 20110030" value="${esc(u.login_ad)}">
            <button type="button" class="btn outlined" id="usuario-buscar-ad"
                    style="white-space:nowrap">Buscar no AD</button>
          </div>
          <span class="hint" id="usuario-ad-resultado">Em branco = conta local, com senha do próprio sistema.</span>
        </div>
      </div>
    </div>
    <div class="form-grid">
      <div class="field"><label>Nome *</label><input name="nome" required value="${esc(u.nome)}"></div>
      <div class="field"><label>E-mail *</label><input type="email" name="email" required value="${esc(u.email)}"></div>
      <div class="field"><label>Perfil</label>
        <select name="papel">${["admin", "ti", "leitor", "auditor"].map((p) => `<option ${u.papel === p ? "selected" : ""}>${p}</option>`).join("")}</select>
        <span class="hint">O perfil define as permissões padrão; ajuste abaixo se quiser.</span>
      </div>
      <div class="field"><label>Departamento</label><select name="departamento_id">${optionsOf(lookups.departamentos, { placeholder: "Sem departamento" })}</select></div>
      <div class="field"><label>Planta</label>
        <select name="planta_id">
          <option value="">Acesso a TODAS as plantas</option>
          ${(lookups.plantas || []).map((p) => `<option value="${p.id}" ${u.planta_id === p.id ? "selected" : ""}>${esc(p.sigla)} — ${esc(p.nome)}</option>`).join("")}
        </select>
        <span class="hint">Tudo o que este usuário cadastrar ficará nesta planta. Deixe em <b>TODAS</b> apenas para administradores.</span>
      </div>
      <div class="field span-2"><label>${isEdit ? "Nova senha (deixe vazio para manter)" : "Senha (contas locais)"}</label>
        <input type="password" name="senha">
        <span class="hint">Para conta de <b>rede</b> deixe vazio — a senha validada é a do AD.</span></div>
      <div class="field span-2" id="usuario-modo-conta"></div>
    </div>
    ${blocoPermissoes(usuario, lookups)}
  ` });
  if (u.departamento_id) form.querySelector('[name="departamento_id"]').value = u.departamento_id;
  if (u.planta_id) form.querySelector('[name="planta_id"]').value = u.planta_id;

  // Busca no AD: preenche nome e e-mail a partir do usuário de logon.
  // É só uma conveniência — nada é liberado aqui; quem libera é o "Salvar".
  const campoLoginAd = form.querySelector("#usuario-login-ad");
  const resultadoAd = form.querySelector("#usuario-ad-resultado");
  const campoSenha = form.querySelector('[name="senha"]');
  const avisoModo = form.querySelector("#usuario-modo-conta");

  // Deixa EXPLÍCITO qual tipo de conta será criada.
  //
  // Antes, bastava o campo de rede ter qualquer conteúdo para a conta nascer
  // como conta de AD — e a senha digitada era descartada em silêncio. Ao
  // tentar entrar com ela, a resposta era "senha incorreta", sem que nada
  // estivesse quebrado: aquela senha nunca chegou a ser gravada.
  function pintarModo(loginAd, nomeAd) {
    const ehRede = Boolean((loginAd || "").trim());
    if (!avisoModo) return;

    if (ehRede) {
      avisoModo.innerHTML = `<div class="recado info" style="margin:0">
        <b>Conta de rede (AD)</b>${nomeAd ? ` — ${esc(nomeAd)}` : ""}<br>
        A senha abaixo <b>não será usada</b>: quem valida é o diretório, com a
        senha de rede da pessoa. Deixe o campo de senha em branco.
      </div>`;
    } else {
      avisoModo.innerHTML = `<div class="recado" style="margin:0">
        <b>Conta local</b><br>
        A senha abaixo é a que a pessoa vai usar no primeiro acesso — e o
        sistema vai <b>exigir a troca</b> assim que ela entrar.
      </div>`;
    }
    if (campoSenha) {
      // Com conta de rede o campo fica desabilitado: evita digitar uma senha
      // que seria ignorada.
      campoSenha.disabled = ehRede;
      if (ehRede) campoSenha.value = "";
    }
  }
  pintarModo(campoLoginAd.value);
  campoLoginAd.addEventListener("input", () => pintarModo(campoLoginAd.value));

  form.querySelector("#usuario-buscar-ad")?.addEventListener("click", async () => {
    const login = campoLoginAd.value.trim();
    if (!login) { toast("Digite o usuário de rede"); return; }

    resultadoAd.textContent = "Consultando o diretório…";
    try {
      const r = await api.post("/admin/config/buscar-ad", { usuario: login });
      if (!r.ok) {
        resultadoAd.textContent = r.mensagem;
        toast(r.mensagem);
        return;
      }
      const d = r.dados || {};
      form.querySelector('[name="nome"]').value = d.nome || "";
      form.querySelector('[name="email"]').value = d.email || "";
      campoLoginAd.value = d.login || login;

      let texto = `Encontrado: ${d.nome}`;
      if (d.departamento) texto += ` · ${d.departamento}`;
      resultadoAd.textContent = texto;
      if (r.ja_cadastrado) {
        resultadoAd.textContent = `${texto} — ATENÇÃO: já cadastrado como "${r.ja_cadastrado.nome}".`;
        resultadoAd.style.color = "var(--md-sys-color-error)";
      } else {
        resultadoAd.style.color = "";
      }
    } catch (e) {
      resultadoAd.textContent = "Não foi possível consultar o AD.";
      mostrarErro(e, "buscar no AD");
    }
  });

  // Marca visualmente os itens ao alternar.
  form.querySelectorAll(".perm-item input").forEach((inp) => {
    inp.addEventListener("change", () => inp.closest(".perm-item").classList.toggle("checked", inp.checked));
  });

  if (isEdit) form.prepend(secaoMfaUsuario(u));

  dialog({
    title: isEdit ? `Editar usuário: ${u.nome}` : "Novo usuário",
    body: form,
    wide: true,
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        const fd = new FormData(form);
        const modulos = meta.modulos.map((m) => m.chave).filter((k) => fd.get(`mod_${k}`));
        // "ambos" vira a lista completa; a escolha única garante que NUNCA
        // fique sem inventário (os dois checkboxes antigos permitiam isso).
        const escolhaInv = fd.get("inventarios") || "ambos";
        const inventarios = escolhaInv === "ambos" ? ["ti", "impressora"] : [escolhaInv];
        const payload = {
          nome: fd.get("nome"),
          email: fd.get("email"),
          papel: fd.get("papel"),
          departamento_id: fd.get("departamento_id") ? Number(fd.get("departamento_id")) : null,
          planta_id: fd.get("planta_id") ? Number(fd.get("planta_id")) : null,
          ativo: true,
          chat_ia_ativo: Boolean(fd.get("chat_ia_ativo")),
          // Usuário de logon no AD. Preenchido = conta de rede (sem senha local).
          login_ad: (fd.get("login_ad") || "").trim() || null,
          permissoes: {
            inventarios,
            modulos,
            pode_escrever: Boolean(fd.get("pode_escrever")),
            pode_excluir: Boolean(fd.get("pode_excluir")),
            pode_acoes_agente: Boolean(fd.get("pode_acoes_agente")),
            permissoes_extra: usuario?.permissoes?.permissoes_extra || [],
          },
        };
        const senha = fd.get("senha");
        const contaDeRede = Boolean(payload.login_ad);

        if (!contaDeRede && !senha && !isEdit) {
          toast("Informe uma senha (conta local) ou busque o usuário no AD");
          return;
        }
        try {
          // A senha entra no corpo **nos dois caminhos**.
          //
          // Antes ela só era anexada no cadastro novo: ao editar, o campo era
          // lido, o formulário aceitava, a tela dizia "Usuário salvo" — e a
          // senha nunca chegava ao servidor. Quem tentasse entrar recebia
          // "senha incorreta", sem nada estar quebrado.
          const corpo = senha ? { ...payload, senha } : payload;
          if (isEdit) await api.put(`/usuarios/${u.id}`, corpo);
          else await api.post("/usuarios", corpo);
          if (u.id === state.user?.id) ctx.atualizarChat();
          close();
          toast("Usuário salvo");
          renderAdmin(document.getElementById("view"));
        } catch (e) { mostrarErro(e, isEdit ? "salvar as alterações do usuário" : "cadastrar o usuário"); }
      } },
    ],
  });
}

function secaoMfaUsuario(usuario) {
  const titulo = el("h4", {}, "Verificação em duas etapas (MFA)");
  if (usuario.id === state.user?.id) {
    return el("section", { class: "usuario-seguranca" }, titulo,
      el("p", { class: "muted" }, "Se perdeu o acesso ao autenticador, peça a outro administrador para redefinir seu MFA nesta tela."));
  }
  const redefinir = el("button", { type: "button", class: "btn outlined", onclick: () => {
    redefinir.hidden = true;
    confirmacao.hidden = false;
    cancelar.focus();
  } }, "Redefinir MFA");
  const cancelar = el("button", { type: "button", class: "btn text", onclick: () => {
    recolherConfirmacao();
    redefinir.focus();
  } }, "Cancelar redefinição");
  const confirmar = el("button", { type: "button", class: "btn danger", onclick: async () => {
    confirmar.disabled = cancelar.disabled = true;
    try {
      await api.request("POST", `/usuarios/${usuario.id}/mfa/redefinir`, { enfileirar: false });
      recolherConfirmacao();
      redefinir.focus();
      toast("MFA redefinido. O usuário deve cadastrar um autenticador no próximo login.");
    } catch (e) {
      mostrarErro(e, "redefinir o MFA");
    } finally {
      confirmar.disabled = cancelar.disabled = false;
    }
  } }, "Confirmar redefinição do MFA");
  const confirmacao = el("div", { class: "recado erro", hidden: true },
    el("p", {}, `Redefinir o MFA de ${usuario.nome} (${usuario.email})? As sessões serão encerradas. No próximo login, essa pessoa precisará cadastrar um autenticador.`),
    el("div", { class: "row wrap" }, cancelar, confirmar));
  function recolherConfirmacao() {
    confirmacao.hidden = true;
    redefinir.hidden = false;
  }

  return el("section", { class: "usuario-seguranca" },
    el("div", { class: "row between wrap" }, titulo, redefinir), confirmacao);
}

async function abaUsuarios(root) {
  const usuarios = await api.get("/usuarios").catch(() => []);
  const lookups = await loadLookups();
  if (!root.isConnected) return;

  const perfis = { admin: "Administrador", ti: "TI", leitor: "Leitor", auditor: "Auditor" };
  const busca = el("input", { class: "search-input", type: "search", placeholder: "Buscar por nome ou e-mail",
    "aria-label": "Buscar por nome ou e-mail" });
  const perfil = el("select", { "aria-label": "Filtrar por perfil" },
    el("option", { value: "" }, "Todos os perfis"),
    ...Object.entries(perfis).map(([valor, rotulo]) => el("option", { value: valor }, rotulo)));
  const lista = el("div", { class: "table-wrap" });
  function linha(u) {
    const perms = u.permissoes_efetivas || {};
    const planta = (lookups.plantas || []).find(p => p.id === u.planta_id);
    const iniciais = u.nome.trim().split(/\s+/).slice(0, 2).map(s => s[0]).join("").toUpperCase();
    const liberado = u.chat_ia_ativo !== false;
    return el("tr", {},
      el("td", {}, el("div", { class: "admin-identidade" },
        el("span", { class: "admin-avatar", "aria-hidden": "true" }, iniciais),
        el("div", {}, el("strong", {}, u.nome), el("div", { class: "list-sub" }, u.email),
          el("div", { class: "list-sub" }, `${(perms.modulos || []).length} módulos · ${perms.pode_escrever ? "pode editar" : "somente leitura"}${perms.pode_excluir ? " · pode excluir" : ""}`)))),
      el("td", {}, perfis[u.papel] || u.papel),
      el("td", {}, planta?.nome || u.planta_sigla || (u.papel === "admin" ? "Todas as plantas" : "Sem planta")),
      el("td", {}, el("span", { class: `admin-acesso ${liberado ? "ok" : "bloqueado"}` }, liberado ? "Liberado" : "Bloqueado")),
      el("td", {}, el("div", { class: "row" },
        el("button", { class: "iconbtn", title: "Editar", "aria-label": `Editar ${u.nome}`, onclick: () => abrirUsuario(u, lookups), html: icon("edit", 20) }),
        el("button", { class: "iconbtn", title: "Excluir", "aria-label": `Excluir ${u.nome}`, onclick: async () => {
          if (await confirmSheet("Excluir usuário", `Excluir ${u.nome}?`)) {
            try { await api.del(`/usuarios/${u.id}`); toast("Excluído"); renderAdmin(document.getElementById("view")); }
            catch (e) { mostrarErro(e); }
          }
        }, html: icon("trash", 20) }))));
  }
  function atualizar() {
    const termo = normalizarBuscaAdmin(busca.value);
    const encontrados = usuarios.filter(u =>
      (!perfil.value || u.papel === perfil.value) && normalizarBuscaAdmin(`${u.nome} ${u.email}`).includes(termo));
    if (!encontrados.length) {
      lista.replaceChildren(usuarios.length
        ? emptyState("search", "Nenhum usuário encontrado", "Ajuste os filtros de busca.")
        : emptyState("user", "Sem usuários", "Cadastre o primeiro usuário."));
      return;
    }
    lista.replaceChildren(el("table", { class: "data admin-usuarios-tabela" },
      el("thead", {}, el("tr", {}, ...["Usuário", "Perfil", "Planta", "Assistente", "Ações"].map(rotulo =>
        el("th", { scope: "col" }, rotulo)))),
      el("tbody", {}, ...encontrados.map(linha))));
  }
  busca.addEventListener("input", atualizar);
  perfil.addEventListener("change", atualizar);
  atualizar();
  root.append(el("section", { class: "card admin-usuarios" },
    el("div", { class: "row between wrap admin-usuarios-topo" },
      el("h2", { class: "section-title" }, "Usuários e permissões"),
      el("button", { class: "btn filled", onclick: () => abrirUsuario(null, lookups), html: icon("add", 18) + " Novo usuário" })),
    el("div", { class: "admin-usuarios-filtros" }, busca, perfil), lista));
}

const normalizarBuscaAdmin = (texto) => String(texto).normalize("NFD").replace(/\p{M}/gu, "").trim().toLowerCase();

// ---------------------------------------------------------------------------
// Dispositivos de impressão
// ---------------------------------------------------------------------------
// Dispositivos de impressão
//
// Esta aba é usada em DOIS lugares: dentro da Administração e na tela
// "Impressão" (perfil TI). O recarregamento precisa voltar para a tela de
// origem — antes estava fixo em `renderAdmin`, o que jogava o técnico de TI
// para uma tela sem acesso e só o F5 resolvia.
// ---------------------------------------------------------------------------
let recarregarImpressoras = () => renderAdmin(document.getElementById("view"));

async function abrirDispositivo(disp) {
  const isEdit = Boolean(disp);
  const d = disp || { tipo: "compartilhamento", formato: "zpl", ativo: true, padrao: false };
  // Lista de plantas para o administrador escolher. Para o perfil TI o
  // endpoint responde 403 e a lista vem vazia — a planta dele é usada.
  const plantas = await api.get("/admin/plantas").catch(() => []);
  const plantaPadraoId = plantas.length ? plantas[0].id : null;
  const form = el("form", { html: `
    <div class="form-grid">
      <div class="field span-2"><label>Planta ${plantas.length ? "*" : ""}</label>
        <select name="planta_id" ${plantas.length ? "required" : "disabled"}>
          ${plantas.length
            ? plantas.map((p) => `<option value="${p.id}" ${(d.planta_id === p.id || (!d.planta_id && plantaPadraoId === p.id)) ? "selected" : ""}>${esc(p.sigla)} — ${esc(p.nome)}</option>`).join("")
            : `<option value="">Sua planta (definida no seu usuário)</option>`}
        </select>
        <span class="hint">Cada planta imprime na <b>sua</b> impressora. Como administrador você escolhe a planta aqui; o técnico de TI só enxerga a dele.</span>
      </div>
      <div class="field"><label>Nome do dispositivo *</label><input name="nome" required value="${esc(d.nome)}" placeholder="Ex.: Recepção"></div>
      <div class="field"><label>Hostname</label><input name="hostname" value="${esc(d.hostname)}" placeholder="RTAT0001"></div>
      <div class="field span-2"><label>Como enviar a impressão</label>
        <select name="tipo">
          <option value="compartilhamento" ${d.tipo === "compartilhamento" ? "selected" : ""}>Windows — fila compartilhada (\\\\host\\impressora)</option>
          <option value="agente" ${d.tipo === "agente" ? "selected" : ""}>Agente no Raspberry Pi (HTTPS)</option>
          <option value="cups" ${d.tipo === "cups" ? "selected" : ""}>Fila local do CUPS (lp)</option>
        </select>
      </div>
      <div class="field span-2"><label>Compartilhamento</label>
        <input name="compartilhamento" value="${esc(d.compartilhamento)}" placeholder="\\\\DTAT7777\\SATO">
        <span class="hint">Fila compartilhada no formato <code>\\\\servidor\\impressora</code> — ex.: <code>\\\\DTAT7777\\SATO</code>. Funciona nos dois sistemas: <b>no Windows</b> o sistema grava os bytes crus na fila (spooler); <b>no Linux</b> envia pelo <code>smbclient</code> (instale o pacote <code>smbclient</code>). Use formato ZPL ou TSPL.</span>
      </div>
      <div class="field"><label>URL do agente</label><input name="agente_url" value="${esc(d.agente_url)}" placeholder="https://impressao.exemplo.com:9100"></div>
      <div class="field"><label>Fila no CUPS</label><input name="fila_cups" value="${esc(d.fila_cups)}" placeholder="sip"></div>
      <div class="field"><label>Formato da etiqueta</label>
        <select name="formato">${["zpl", "tspl", "pdf"].map((f) => `<option ${d.formato === f ? "selected" : ""}>${f}</option>`).join("")}</select>
      </div>
      <div class="field"><label>Inventário</label>
        <select name="dominio">
          <option value="">Ambos</option>
          <option value="ti" ${d.dominio === "ti" ? "selected" : ""}>TI</option>
          <option value="impressora" ${d.dominio === "impressora" ? "selected" : ""}>Impressoras</option>
        </select>
      </div>
      <div class="field span-2"><label>Observações</label><textarea name="observacoes">${esc(d.observacoes)}</textarea></div>
    </div>
    <div class="row" style="gap:20px;margin-top:6px">
      <label class="switch"><input type="checkbox" name="padrao" ${d.padrao ? "checked" : ""}> Usar como padrão</label>
      <label class="switch"><input type="checkbox" name="ativo" ${d.ativo !== false ? "checked" : ""}> Ativo</label>
    </div>
  ` });

  dialog({
    title: isEdit ? `Editar: ${d.nome}` : "Novo dispositivo de impressão",
    body: form,
    wide: true,
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        const fd = new FormData(form);
        const payload = {
          nome: fd.get("nome"),
          tipo: fd.get("tipo"),
          hostname: fd.get("hostname") || null,
          compartilhamento: fd.get("compartilhamento") || null,
          agente_url: fd.get("agente_url") || null,
          fila_cups: fd.get("fila_cups") || null,
          formato: fd.get("formato"),
          dominio: fd.get("dominio") || null,
          padrao: Boolean(fd.get("padrao")),
          ativo: Boolean(fd.get("ativo")),
          observacoes: fd.get("observacoes") || null,
          planta_id: fd.get("planta_id") ? Number(fd.get("planta_id")) : null,
        };
        try {
          if (isEdit) await api.put(`/admin/dispositivos/${d.id}`, payload);
          else await api.post("/admin/dispositivos", payload);
          close(); toast("Dispositivo salvo");
          recarregarImpressoras();
        } catch (e) { mostrarErro(e, isEdit ? "salvar as alterações da impressora" : "cadastrar a impressora"); }
      } },
    ],
  });
}

/**
 * Aba de impressoras. Exportada porque o perfil **TI** também a usa, numa tela
 * própria (Impressão), sem acesso ao restante da administração.
 *
 * @param {HTMLElement} root onde renderizar
 * @param {() => void} [aoAtualizar] para onde voltar depois de salvar/excluir.
 *   Sem ele, recarrega a própria Administração.
 */
export async function abaDispositivos(root, aoAtualizar) {
  recarregarImpressoras = aoAtualizar || (() => renderAdmin(document.getElementById("view")));
  const dispositivos = await api.get("/admin/dispositivos").catch(() => []);
  root.append(el("div", { class: "card" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Dispositivos de impressão"),
        el("div", { class: "muted", style: "font-size:13px" }, "Cadastre o Raspberry Pi (hostname) e o compartilhamento da impressora térmica."),
      ),
      el("button", { class: "btn tonal small", onclick: () => abrirDispositivo(null), html: icon("add", 18) + " Novo dispositivo" }),
    ),
  ));

  const lista = el("div", { class: "card" });
  if (!dispositivos.length) {
    lista.append(emptyState("print", "Nenhum dispositivo", "Cadastre o primeiro destino de impressão (ex.: hostname RTAT0001 e compartilhamento \\\\RTAT0001\\sip)."));
  }
  const TIPO = { compartilhamento: "Fila compartilhada (Windows)", agente: "Agente Raspberry", cups: "CUPS" };
  dispositivos.forEach((d) => {
    lista.append(el("div", { class: "list-row" },
      el("div", { class: "list-main" },
        el("div", { class: "list-title" }, `${d.nome}${d.padrao ? " · padrão" : ""}${d.ativo ? "" : " (inativo)"}`),
        el("div", { class: "list-sub" }, `${TIPO[d.tipo] || d.tipo}${d.hostname ? ` · ${d.hostname}` : ""}${d.compartilhamento ? ` · ${d.compartilhamento}` : ""}${d.formato ? ` · ${d.formato.toUpperCase()}` : ""}`),
      ),
      el("div", { class: "row" },
        el("button", { class: "iconbtn", title: "Editar", onclick: () => abrirDispositivo(d), html: icon("edit", 20) }),
        el("button", { class: "iconbtn", title: "Excluir", onclick: async () => {
          if (await confirmSheet("Excluir dispositivo", `Excluir ${d.nome}?`)) {
            try { await api.del(`/admin/dispositivos/${d.id}`); toast("Excluído"); recarregarImpressoras(); }
            catch (e) { mostrarErro(e); }
          }
        }, html: icon("trash", 20) }),
      ),
    ));
  });
  root.append(lista);
}

// ---------------------------------------------------------------------------
// Banco de fotos
// ---------------------------------------------------------------------------
function abrirUploadFoto() {
  const file = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp,image/gif" });
  const nome = el("input", { placeholder: "Ex.: Notebook Dell Latitude" });
  const tags = el("input", { placeholder: "notebook, dell, ti" });
  const dominio = el("select", {}, el("option", { value: "" }, "Ambos"), el("option", { value: "ti" }, "TI"), el("option", { value: "impressora" }, "Impressoras"));
  const descricao = el("textarea", { placeholder: "Descrição (opcional)" });

  dialog({
    title: "Salvar foto no banco",
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Arquivo de imagem *"), file,
        el("span", { class: "hint" }, "PNG, JPG, WebP ou GIF. Limite de 12 MB.")),
      el("div", { class: "field" }, el("label", {}, "Nome *"), nome),
      el("div", { class: "form-grid" },
        el("div", { class: "field" }, el("label", {}, "Etiquetas (tags)"), tags),
        el("div", { class: "field" }, el("label", {}, "Inventário"), dominio),
      ),
      el("div", { class: "field" }, el("label", {}, "Descrição"), descricao),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Enviar", variant: "filled", onClick: async (close) => {
        if (!file.files.length || !nome.value.trim()) { toast("Informe o arquivo e o nome"); return; }
        if (file.files[0].size > 12 * 1024 * 1024) { toast("A foto pode ter até 12 MB"); return; }
        const fd = new FormData();
        fd.append("file", file.files[0]);
        fd.append("nome", nome.value.trim());
        if (tags.value) fd.append("tags", tags.value);
        if (dominio.value) fd.append("dominio", dominio.value);
        if (descricao.value) fd.append("descricao", descricao.value);
        try {
          const res = await fetch("/api/v1/admin/fotos", { method: "POST", headers: { Authorization: "Bearer " + state.access }, body: fd });
          if (!res.ok) throw erroDeResposta(res.status, await res.json().catch(() => null));
          close(); toast("Foto salva no banco");
          renderAdmin(document.getElementById("view"));
        } catch (e) { mostrarErro(e, "enviar a foto"); }
      } },
    ],
  });
}

function abrirEdicaoFoto(foto) {
  const nome = el("input", { value: foto.nome });
  const tags = el("input", { value: foto.tags || "" });
  const descricao = el("textarea", {});
  descricao.value = foto.descricao || "";
  dialog({
    title: "Editar foto",
    body: el("div", {},
      fotoProtegida(foto.id, { class: "photo-preview mb", alt: foto.nome }),
      el("div", { class: "field" }, el("label", {}, "Nome"), nome),
      el("div", { class: "field" }, el("label", {}, "Etiquetas"), tags),
      el("div", { class: "field" }, el("label", {}, "Descrição"), descricao),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Salvar", variant: "filled", onClick: async (close) => {
        try {
          await api.put(`/admin/fotos/${foto.id}`, { nome: nome.value, tags: tags.value || null, descricao: descricao.value || null });
          close(); toast("Foto atualizada"); renderAdmin(document.getElementById("view"));
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

async function abaFotos(root) {
  const fotos = await api.get("/admin/fotos").catch(() => []);
  root.append(el("div", { class: "card" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Banco de fotos"),
        el("div", { class: "muted", style: "font-size:13px" }, "Padrões de imagem reutilizáveis, que podem ser atribuídos aos ativos no inventário."),
      ),
      el("button", { class: "btn tonal small", onclick: () => abrirUploadFoto(), html: icon("add", 18) + " Salvar foto" }),
    ),
  ));

  const card = el("div", { class: "card" });
  if (!fotos.length) {
    card.append(emptyState("image", "Banco vazio", "Envie fotos de modelos de equipamentos para reutilizar nos ativos."));
  } else {
    const grid = el("div", { class: "photo-grid" });
    fotos.forEach((f) => {
      grid.append(el("div", { class: "photo-card" },
        fotoProtegida(f.id, { alt: f.nome, loading: "lazy" }),
        el("div", { class: "photo-meta" },
          el("strong", {}, f.nome),
          el("div", { class: "muted" }, f.tags || "sem tags"),
          el("div", { class: "row", style: "gap:2px;margin-top:6px;justify-content:flex-end" },
            el("button", { class: "iconbtn", title: "Editar", onclick: () => abrirEdicaoFoto(f), html: icon("edit", 18) }),
            el("button", { class: "iconbtn", title: "Excluir", onclick: async () => {
              if (await confirmSheet("Excluir foto", `Excluir ${f.nome}?`)) {
                try { await api.del(`/admin/fotos/${f.id}`); toast("Excluída"); renderAdmin(document.getElementById("view")); }
                catch (e) { mostrarErro(e); }
              }
            }, html: icon("trash", 18) }),
          ),
        ),
      ));
    });
    card.append(grid);
  }
  root.append(card);
}

// ---------------------------------------------------------------------------
// Navegação da Administração
// ---------------------------------------------------------------------------
const SECOES_ADMIN = [
  { chave: "usuarios", rotulo: "Usuários e permissões", icone: "cadastros", opcoes: [
    ["usuarios", "Usuários e permissões", "cadastros", "Contas, perfis, permissões e verificação em duas etapas.", abaUsuarios, "pessoas acesso login papel senha mfa"],
  ] },
  { chave: "plantas", rotulo: "Plantas", icone: "plantas", opcoes: [
    ["plantas", "Plantas", "plantas", "Unidades e localidades dos equipamentos.", renderPlantas, "localidades unidade filial cnpj site"],
  ] },
  { chave: "patrimonio", rotulo: "Patrimônio", icone: "ativos", opcoes: [
    ["dispositivos", "Impressão", "print", "Configure as impressoras usadas para emitir etiquetas.", abaDispositivos, "impressoras zpl tspl rede térmica"],
    ["etiquetas", "Etiquetas", "qr", "Gerencie os modelos de etiquetas de patrimônio.", renderTemplates, "template layout design qr"],
    ["checklist", "Checklist de empréstimo", "contagens", "Defina os itens de conferência na retirada e na devolução.", renderChecklist, "inventário vistoria"],
    ["fotos", "Banco de Fotos", "image", "Gerencie as imagens usadas nas fichas dos equipamentos.", abaFotos, "imagem galeria mídia anexo"],
  ] },
  { chave: "auditoria", rotulo: "Auditoria", icone: "contagens", opcoes: [
    ["auditoria", "Logs de auditoria", "contagens", "Consulte a trilha de alterações do sistema.", renderAuditoria, "histórico trilha quem fez rastro"],
  ] },
  { chave: "lgpd", rotulo: "Privacidade", icone: "shield", opcoes: [
    ["lgpd", "Privacidade (LGPD)", "shield", "Consulte os prazos de retenção e execute o expurgo de dados vencidos.", renderLgpd, "dados retenção anonimização"],
  ] },
  { chave: "sistema", rotulo: "Sistema", icone: "settings", opcoes: [
    ["auth", "Autenticação (AD)", "shield", "Configure o acesso com as contas de rede.", renderAuth, "active directory ldap senha domínio login de rede"],
    ["sessao", "Tempo de inatividade", "historico", "Defina quando o Nexus deve solicitar um novo login.", renderSessao, "sessão expiração login timeout segurança minutos"],
    ["agente-ia", "Agente de IA", "chat", "Configure o provedor do chat, o acesso e a retenção do histórico.", renderAgenteIA, "ollama openai openrouter token modelo inteligência artificial"],
    ["notificacoes", "Notificações", "bell", "Gerencie os envios e alertas do sistema.", renderNotificacoes, "email smtp aviso alerta toner devolução"],
    ["backups", "Backups", "arquivo", "Crie, baixe e restaure cópias do banco.", renderBackups, "cópia restaurar segurança dump salvar"],
    ["manutencao", "Modo Manutenção", "manutencoes", "Gerencie o acesso durante manutenções.", renderManutencao, "sessão derrubar logado online bloqueio"],
    ["agente", "Agente Nexus", "ativos", "Gerencie a integração com os agentes instalados nos equipamentos.", renderAgente, "instalação serial token pendente"],
    ["banco", "Conexão com DBA", "server", "Consulte a configuração atual da conexão com o banco.", renderBanco, "postgresql servidor sqlite mysql"],
  ] },
];

const rotaOpcao = (chave) => `#/admin?aba=${chave}`;
const rotaSecao = ({ chave, opcoes }) => opcoes.length === 1 ? rotaOpcao(opcoes[0][0]) : `#/admin?secao=${chave}`;

function buscaAdministracao() {
  const busca = el("input", { type: "search", class: "busca-abas", placeholder: "Buscar opção de administração",
    "aria-label": "Buscar opção de administração", "aria-controls": "admin-resultados" });
  const mensagem = el("p", { class: "muted", role: "status" });
  const lista = el("ul", { class: "admin-resultados-lista" });
  const resultados = el("section", { id: "admin-resultados", class: "card admin-resultados", "aria-label": "Resultados da busca", hidden: true },
    mensagem, lista);

  busca.addEventListener("input", () => {
    const termo = normalizarBuscaAdmin(busca.value);
    resultados.hidden = !termo;
    const itens = [];
    if (termo) {
      for (const { rotulo: secao, opcoes } of SECOES_ADMIN) {
        for (const [chave, rotulo, icone, descricao, , palavras] of opcoes) {
          if (!normalizarBuscaAdmin(`${secao} ${rotulo} ${descricao} ${palavras}`).includes(termo)) continue;
          itens.push(el("li", {}, el("a", { class: "admin-resultado", href: rotaOpcao(chave) },
            el("span", { html: icon(icone, 20) }), el("strong", {}, rotulo), el("span", { class: "muted" }, secao))));
        }
      }
    }
    mensagem.textContent = itens.length ? `${itens.length} opção(ões) encontrada(s)` : "Nenhuma opção encontrada.";
    lista.replaceChildren(...itens);
  });
  busca.addEventListener("keydown", ev => {
    if (ev.key === "Escape" && busca.value) {
      ev.stopPropagation();
      busca.value = "";
      busca.dispatchEvent(new Event("input"));
    }
  });
  return el("div", { class: "admin-busca" }, busca, resultados);
}

export async function renderAdmin(root) {
  ctx.setTitle("Administração");
  ctx.setFab(null);

  if (!state.isAdmin) {
    root.replaceChildren(emptyState("shield", "Acesso restrito", "Somente administradores podem abrir esta área."));
    return;
  }

  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const abaAnterior = params.get("aba");
  const abaPedida = abaAnterior === "ollama" || (!abaAnterior && params.get("secao") === "integracoes")
    ? "agente-ia" : abaAnterior;
  const secao = SECOES_ADMIN.find(s => s.opcoes.some(([chave]) => chave === abaPedida))
    || SECOES_ADMIN.find(s => s.chave === params.get("secao")) || SECOES_ADMIN[0];
  const opcao = secao.opcoes.find(([chave]) => chave === abaPedida)
    || (secao.opcoes.length === 1 ? secao.opcoes[0] : null);

  const menu = el("nav", { class: "card admin-destinos", "aria-label": "Seções da administração" },
    el("div", { class: "categorias-admin" }, ...SECOES_ADMIN.map(item => el("a", {
      class: "categoria-admin" + (item === secao ? " ativa" : ""),
      href: rotaSecao(item),
      "aria-current": item === secao ? (opcao && secao.opcoes.length > 1 ? "location" : "page") : null,
    }, el("span", { html: icon(item.icone, 19) }), item.rotulo))));
  const area = el("section", { class: "admin-area", "aria-label": secao.rotulo });
  const alvo = el("div", { class: "admin-conteudo" });
  if (opcao && secao.opcoes.length > 1) {
    area.append(el("nav", { class: "admin-caminho", "aria-label": "Caminho da configuração" },
      el("a", { href: rotaSecao(secao) }, secao.rotulo),
      el("span", { html: icon("chevR", 14) }),
      el("span", { "aria-current": "page" }, opcao[1])));
  }
  area.append(alvo);
  root.replaceChildren(el("h1", { class: "page-title" }, "Administração"), buscaAdministracao(),
    el("div", { class: "admin-layout" }, menu, area));

  if (!opcao) {
    alvo.append(el("h2", { class: "admin-secao-titulo" }, secao.rotulo),
      el("div", { class: "admin-grade-opcoes" }, ...secao.opcoes.map(([chave, rotulo, icone, descricao]) =>
        el("a", { class: "card admin-opcao-card", href: rotaOpcao(chave) },
          el("span", { class: "nexus-pagina-icone", html: icon(icone, 22) }),
          el("span", {}, el("strong", {}, rotulo), el("small", { class: "muted" }, descricao)),
          el("span", { html: icon("chevR", 17) })))));
    return;
  }

  const carregando = el("div", {}, skeleton(5));
  alvo.append(carregando);
  if (opcao[0] === "usuarios") {
    meta = await api.get("/admin/metadados").catch(() => ({ modulos: [], inventarios: [] }));
    if (!alvo.isConnected) return;
  }
  try {
    await opcao[4](alvo);
  } finally {
    carregando.remove();
  }
}
