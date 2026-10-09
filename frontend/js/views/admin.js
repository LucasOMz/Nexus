/**
 * Administração: usuários & permissões, dispositivos de impressão e banco de fotos.
 * @module views/admin
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { ctx } from "../context.js";
import { el, icon, toast, dialog, confirmSheet, skeleton, emptyState, mostrarErro } from "../ui.js";
import { loadLookups, optionsOf } from "../lookups.js";
import { erroDeResposta } from "../erros.js";
import { renderTemplates } from "./admin_etiquetas.js";
import { renderBackups } from "./admin_backups.js";
import { renderAuth } from "./admin_auth.js";
import { renderOCS } from "./admin_ocs.js";
import { renderReconciliacao } from "./admin_ocs_reconciliacao.js";
import { renderBanco } from "./admin_banco.js";
import { renderAuditoria } from "./admin_auditoria.js";
import { renderPlantas } from "./admin_plantas.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fotoUrl = (id) => `/api/v1/admin/fotos/${id}/arquivo?token=${encodeURIComponent(state.access)}`;

let meta = { modulos: [], inventarios: [] };

// As opções da Administração começam OCULTAS e aparecem ao clicar numa
// categoria. Fica no módulo (e não na função) para sobreviver ao redesenho:
// navegar entre abas não deve fechar a barra que a pessoa acabou de abrir.
let barraAberta = false;
let abaAtiva = "usuarios";

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
    </div>
    ${blocoPermissoes(usuario, lookups)}
  ` });
  if (u.departamento_id) form.querySelector('[name="departamento_id"]').value = u.departamento_id;
  if (u.planta_id) form.querySelector('[name="planta_id"]').value = u.planta_id;

  // Busca no AD: preenche nome e e-mail a partir do usuário de logon.
  // É só uma conveniência — nada é liberado aqui; quem libera é o "Salvar".
  const campoLoginAd = form.querySelector("#usuario-login-ad");
  const resultadoAd = form.querySelector("#usuario-ad-resultado");
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
          // Usuário de logon no AD. Preenchido = conta de rede (sem senha local).
          login_ad: (fd.get("login_ad") || "").trim() || null,
          permissoes: {
            inventarios,
            modulos,
            pode_escrever: Boolean(fd.get("pode_escrever")),
            pode_excluir: Boolean(fd.get("pode_excluir")),
          },
        };
        const senha = fd.get("senha");
        const contaDeRede = Boolean(payload.login_ad);

        if (!contaDeRede && !senha && !isEdit) {
          toast("Informe uma senha (conta local) ou busque o usuário no AD");
          return;
        }
        try {
          if (isEdit) await api.put(`/usuarios/${u.id}`, payload);
          else await api.post("/usuarios", senha ? { ...payload, senha } : payload);
          close();
          toast("Usuário salvo");
          renderAdmin(document.getElementById("view"));
        } catch (e) { mostrarErro(e, isEdit ? "salvar as alterações do usuário" : "cadastrar o usuário"); }
      } },
    ],
  });
}

async function abaUsuarios(root) {
  const usuarios = await api.get("/usuarios").catch(() => []);
  const lookups = await loadLookups();

  root.append(el("div", { class: "card" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Usuários e permissões"),
        el("div", { class: "muted", style: "font-size:13px" }, "Defina o que cada pessoa pode ver e fazer no sistema."),
      ),
      el("button", { class: "btn tonal small", onclick: () => abrirUsuario(null, lookups), html: icon("add", 18) + " Novo usuário" }),
    ),
  ));

  const lista = el("div", { class: "card" });
  if (!usuarios.length) lista.append(emptyState("user", "Sem usuários", "Cadastre o primeiro usuário."));
  usuarios.forEach((u) => {
    const perms = u.permissoes_efetivas || {};
    lista.append(el("div", { class: "list-row" },
      el("div", { class: "list-main" },
        el("div", { class: "list-title" }, `${u.nome} ${u.papel === "admin" ? "· admin" : ""}`),
        el("div", { class: "list-sub" }, `${u.email} · ${(perms.modulos || []).length} módulos · ${perms.pode_escrever ? "pode editar" : "somente leitura"}${perms.pode_excluir ? " · pode excluir" : ""}`),
      ),
      el("div", { class: "row" },
        el("button", { class: "iconbtn", title: "Editar", onclick: () => abrirUsuario(u, lookups), html: icon("edit", 20) }),
        el("button", { class: "iconbtn", title: "Excluir", onclick: async () => {
          if (await confirmSheet("Excluir usuário", `Excluir ${u.nome}?`)) {
            try { await api.del(`/usuarios/${u.id}`); toast("Excluído"); renderAdmin(document.getElementById("view")); }
            catch (e) { mostrarErro(e); }
          }
        }, html: icon("trash", 20) }),
      ),
    ));
  });
  root.append(lista);
}

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
          <option value="agente" ${d.tipo === "agente" ? "selected" : ""}>Agente no Raspberry Pi (HTTP :9100)</option>
          <option value="cups" ${d.tipo === "cups" ? "selected" : ""}>Fila local do CUPS (lp)</option>
        </select>
      </div>
      <div class="field span-2"><label>Compartilhamento</label>
        <input name="compartilhamento" value="${esc(d.compartilhamento)}" placeholder="\\\\DTAT7777\\SATO">
        <span class="hint">Fila compartilhada no formato <code>\\\\servidor\\impressora</code> — ex.: <code>\\\\DTAT7777\\SATO</code>. Funciona nos dois sistemas: <b>no Windows</b> o sistema grava os bytes crus na fila (spooler); <b>no Linux</b> envia pelo <code>smbclient</code> (instale o pacote <code>smbclient</code>). Use formato ZPL ou TSPL.</span>
      </div>
      <div class="field"><label>URL do agente</label><input name="agente_url" value="${esc(d.agente_url)}" placeholder="http://RTAT0001:9100"></div>
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
  const file = el("input", { type: "file", accept: "image/*" });
  const nome = el("input", { placeholder: "Ex.: Notebook Dell Latitude" });
  const tags = el("input", { placeholder: "notebook, dell, ti" });
  const dominio = el("select", {}, el("option", { value: "" }, "Ambos"), el("option", { value: "ti" }, "TI"), el("option", { value: "impressora" }, "Impressoras"));
  const descricao = el("textarea", { placeholder: "Descrição (opcional)" });

  dialog({
    title: "Salvar foto no banco",
    body: el("div", {},
      el("div", { class: "field" }, el("label", {}, "Arquivo de imagem *"), file),
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
      el("img", { class: "photo-preview mb", src: fotoUrl(foto.id), alt: foto.nome }),
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
        el("img", { src: fotoUrl(f.id), alt: f.nome, loading: "lazy" }),
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
// View principal com abas
// ---------------------------------------------------------------------------
export async function renderAdmin(root) {
  ctx.setTitle("Administração");
  ctx.setFab(null);

  if (!state.isAdmin) {
    root.innerHTML = "";
    root.append(emptyState("shield", "Acesso restrito", "Somente administradores podem abrir esta área."));
    return;
  }

  root.innerHTML = "";
  root.append(el("h1", { class: "page-title" }, "Administração"));
  const conteudo = el("div", {}, skeleton(5));
  root.append(conteudo);

  try { meta = await api.get("/admin/metadados"); } catch { meta = { modulos: [], inventarios: [] }; }

  // A ordem desta lista é a ordem das abas na tela — e a ordem do despacho
  // logo abaixo. Mantenha as duas iguais.
  const abas = [
    ["usuarios", "Usuários & Permissões"],
    ["plantas", "Plantas"],
    ["dispositivos", "Impressão"],
    ["etiquetas", "Etiquetas"],
    ["fotos", "Banco de Fotos"],
    ["auditoria", "Logs"],
    ["backups", "Backups"],
    ["auth", "Autenticação (AD)"],
    ["ocs", "OCS Inventory"],
    ["reconciliacao", "Reconciliação OCS"],
    ["banco", "Conexão com DBA"],
  ];

  // Permite abrir o painel direto numa aba: `#/admin?aba=ocs`.
  // É o que o sino usa ao avisar de um problema na sincronização com o OCS.
  const pedida = new URLSearchParams((location.hash.split("?")[1] || "")).get("aba");
  if (pedida && abas.some(([chave]) => chave === pedida)) abaAtiva = pedida;

  // -------------------------------------------------------------------------
  // Categorias no topo; as opções aparecem logo ABAIXO delas, ao clicar.
  //
  // A barra começa oculta: o painel abre limpo, só com as quatro categorias.
  // Quem sabe onde quer ir clica e vê as opções; quem não sabe usa a busca.
  // -------------------------------------------------------------------------
  const AJUDA_ABA = {
    usuarios: ["pessoas", "acesso", "permissao", "login", "papel", "senha"],
    plantas: ["localidades", "unidade", "filial", "cnpj", "site"],
    dispositivos: ["impressoras", "zpl", "tspl", "rede", "termica"],
    etiquetas: ["template", "layout", "qr", "design", "modelo"],
    fotos: ["imagem", "galeria", "midia", "anexo"],
    auditoria: ["log", "historico", "trilha", "quem fez", "rastro"],
    backups: ["copia", "restaurar", "seguranca", "dump", "salvar"],
    auth: ["ad", "active directory", "ldap", "senha", "dominio", "login de rede"],
    ocs: ["inventario automatico", "servidor", "token", "sincronizacao", "agente"],
    reconciliacao: ["divergencia", "fantasma", "perdido", "rede", "comparar"],
    banco: ["dba", "conexao", "postgresql", "servidor", "sqlite", "mysql"],
  };

  const GRUPOS = [
    ["Pessoas e acessos", ["usuarios", "plantas", "auth"]],
    ["Patrimônio", ["dispositivos", "etiquetas", "fotos"]],
    // "Auditoria" reúne o que serve para CONFERIR: a trilha do que foi feito
    // (Logs) e a conferência do que existe na rede (Reconciliação).
    ["Auditoria", ["auditoria", "reconciliacao"]],
    // "Sistema" ficou com a configuração e a manutenção da própria ferramenta.
    ["Sistema", ["ocs", "backups", "banco"]],
  ];

  // Aba fora de qualquer grupo não pode sumir: cai em "Outros".
  const agrupadas = new Set(GRUPOS.flatMap(([, ks]) => ks));
  const semGrupo = abas.map(([k]) => k).filter((k) => !agrupadas.has(k));
  const grupos = semGrupo.length ? [...GRUPOS, ["Outros", semGrupo]] : GRUPOS;

  const rotuloDe = (chave) => (abas.find(([c]) => c === chave) || [, chave])[1];
  const grupoDaAba = (chave) => grupos.find(([, ks]) => ks.includes(chave));

  const busca = el("input", {
    type: "search",
    class: "busca-abas",
    placeholder: "Buscar opção…",
    "aria-label": "Buscar opção de administração",
  });
  const filaCategorias = el("div", { class: "categorias-admin" });
  const barra = el("div", { class: "opcoes-admin" });

  // Qual categoria está aberta. Fica no módulo para sobreviver ao redesenho:
  // navegar entre abas não deve fechar a barra que a pessoa acabou de abrir.
  let categoriaAberta = barraAberta ? (grupoDaAba(abaAtiva) || grupos[0])[0] : null;

  function irPara(chave) {
    abaAtiva = chave;
    barraAberta = true;
    const g = grupoDaAba(chave);
    if (g) categoriaAberta = g[0];
    renderAdmin(document.getElementById("view"));
  }

  function casa(chave, termo) {
    const alvo = `${rotuloDe(chave)} ${(AJUDA_ABA[chave] || []).join(" ")}`.toLowerCase();
    return alvo.includes(termo);
  }

  function pintarCategorias() {
    const termo = busca.value.trim().toLowerCase();
    filaCategorias.innerHTML = "";

    for (const [titulo, chaves] of grupos) {
      const temResultado = !termo || chaves.some((k) => casa(k, termo));
      filaCategorias.append(el("button", {
        class: [
          "categoria-admin",
          titulo === categoriaAberta ? "ativa" : "",
          temResultado ? "" : "sem-resultado",
        ].filter(Boolean).join(" "),
        onclick: () => {
          if (termo) return;   // durante a busca, a categoria não navega
          // Clicar na categoria que já está aberta fecha a barra.
          if (barraAberta && categoriaAberta === titulo) {
            barraAberta = false;
            categoriaAberta = null;
            pintar();
            return;
          }
          categoriaAberta = titulo;
          barraAberta = true;
          const primeira = chaves[0];
          // Só navega se a aba aberta não for desta categoria — assim abrir a
          // barra não troca de tela sem necessidade.
          if (primeira && grupoDaAba(abaAtiva)?.[0] !== titulo) irPara(primeira);
          else pintar();
        },
      },
        el("span", {}, titulo),
        el("span", { class: "categoria-conta" }, String(chaves.length)),
      ));
    }
  }

  function pintarBarra() {
    const termo = busca.value.trim().toLowerCase();
    // Visível ao clicar numa categoria, ou sempre que houver busca ativa.
    const visivel = barraAberta || Boolean(termo);
    barra.classList.toggle("oculto", !visivel);
    barra.innerHTML = "";
    if (!visivel) return;

    const itens = [];
    for (const [titulo, chaves] of grupos) {
      for (const k of chaves) {
        if (termo && !casa(k, termo)) continue;
        if (!termo && titulo !== categoriaAberta) continue;
        itens.push([k, titulo]);
      }
    }

    if (!itens.length) {
      barra.append(el("div", { class: "barra-vazia" }, "Nenhuma opção encontrada."));
      return;
    }

    barra.append(
      el("div", { class: "barra-rotulo" }, termo ? "Resultados" : categoriaAberta),
      el("div", { class: "barra-trilho" },
        ...itens.map(([chave, titulo]) => el("button", {
          class: `opcao-admin${chave === abaAtiva ? " ativa" : ""}`,
          title: termo ? titulo : undefined,
          onclick: () => irPara(chave),
        },
          rotuloDe(chave),
          // Na busca, mostra a categoria de origem: sem isso a pessoa não sabe
          // onde aquela opção mora.
          termo ? el("span", { class: "opcao-origem" }, titulo) : null,
        ))),
    );
  }

  function pintar() { pintarCategorias(); pintarBarra(); }

  busca.addEventListener("input", pintar);
  pintar();

  const tabsEl = el("div", { class: "tabs-wrap" }, busca, filaCategorias, barra);

  const alvo = el("div");
  root.insertBefore(tabsEl, conteudo);
  conteudo.replaceWith(alvo);

  // Despacho explícito, na mesma ordem das abas: usar um `else` genérico como
  // último caso escondia qual aba era o padrão.
  if (abaAtiva === "usuarios") await abaUsuarios(alvo);
  else if (abaAtiva === "plantas") await renderPlantas(alvo);
  else if (abaAtiva === "dispositivos") await abaDispositivos(alvo);
  else if (abaAtiva === "etiquetas") await renderTemplates(alvo);
  else if (abaAtiva === "fotos") await abaFotos(alvo);
  else if (abaAtiva === "auditoria") await renderAuditoria(alvo);
  else if (abaAtiva === "backups") await renderBackups(alvo);
  else if (abaAtiva === "auth") await renderAuth(alvo);
  else if (abaAtiva === "ocs") await renderOCS(alvo);
  else if (abaAtiva === "reconciliacao") await renderReconciliacao(alvo);
  else if (abaAtiva === "banco") await renderBanco(alvo);
}
