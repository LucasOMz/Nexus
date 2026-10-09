/**
 * Administração → Autenticação (AD/LDAP).
 * Permite configurar servidor, conta de serviço e o filtro de busca pela
 * própria interface, com teste antes de ativar.
 *
 * O AD aqui é usado para AUTENTICAR (conferir a senha de rede) e para BUSCAR
 * o nome da pessoa no cadastro. Quem pode entrar é decidido no cadastro de
 * usuário, feito pelo administrador — grupo do AD não libera acesso.
 * @module views/admin_auth
 */
import { api } from "../api.js";
import { el, icon, toast, dialog, mostrarErro } from "../ui.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/**
 * Uma opção de ligar/desligar, como LINHA própria.
 *
 * Os interruptores ficavam soltos dentro da grade de campos, misturados com os
 * inputs de texto — a leitura virava uma sequência irregular e o mais
 * importante (ativar o AD) parecia só mais um campo entre vários.
 */
function opcao(nome, titulo, dica, marcado) {
  return `
    <label class="opcao">
      <input type="checkbox" name="${nome}" ${marcado ? "checked" : ""}>
      <span class="opcao-texto">
        <span class="opcao-titulo">${esc(titulo)}</span>
        ${dica ? `<span class="opcao-dica">${dica}</span>` : ""}
      </span>
    </label>`;
}

export async function renderAuth(root) {
  const cfg = await api.get("/admin/config").catch((e) => { mostrarErro(e); return {}; });

  root.innerHTML = "";
  root.append(el("div", { class: "card" },
    el("div", { class: "section-title", style: "margin:0" }, "Autenticação via Active Directory (LDAP)"),
    el("div", { class: "muted", style: "font-size:13px" },
      "O AD confirma quem é a pessoa (a senha de rede). Quem entra no sistema, e com qual perfil, é definido no cadastro de usuário. O administrador local (root) continua entrando pela senha do sistema, sem depender do AD — é a sua rota de emergência."),
  ));

  const form = el("form", {}, );
  form.innerHTML = `    <div class="form-section">
      <div class="row between" style="flex-wrap:wrap;gap:10px;margin-bottom:4px">
        <h4 style="margin:0">Situação</h4>
        <span class="badge ${cfg.ldap_ativo ? "ok" : "aviso"}" id="ad-situacao">
          ${cfg.ldap_ativo ? "Ativado" : "Desativado"}
        </span>
      </div>
      <p class="muted" style="margin:0 0 12px;font-size:13px">
        Enquanto estiver desativado, o login pelo AD fica indisponível e apenas
        o administrador local entra no sistema.
      </p>
      <div class="opcoes">
        ${opcao("ldap_ativo", "Ativar login via AD",
          "Ligue somente depois de preencher os dados abaixo e o teste de conexão passar.",
          cfg.ldap_ativo)}
      </div>
    </div>

    <div class="form-section"><h4>Conexão com o servidor</h4>
      <div class="form-grid">
        <div class="field"><label>Servidor *</label><input name="ldap_servidor" value="${esc(cfg.ldap_servidor)}" placeholder="dc01.empresa.local"></div>
        <div class="field"><label>Porta</label><input type="number" name="ldap_porta" value="${cfg.ldap_porta ?? 636}">
          <span class="hint">LDAPS costuma usar 636; LDAP sem TLS usa 389.</span></div>
      </div>
      <h5 class="sub-titulo">Segurança da conexão</h5>
      <div class="opcoes">
        ${opcao("ldap_tls", "Usar SSL/TLS (LDAPS)",
          "Recomendado. Sem TLS, a senha do usuário trafega em texto claro na rede.",
          cfg.ldap_tls !== false)}
        ${opcao("ldap_ignorar_certificado", "Ignorar a validação do certificado",
          "Use <b>apenas</b> se o certificado da sua CA interna não estiver instalado no servidor do sistema.",
          cfg.ldap_ignorar_certificado)}
      </div>
    </div>

    <div class="form-section"><h4>Base e conta de serviço</h4>
      <p class="muted" style="margin:0 0 12px;font-size:13px">
        A conta de serviço é usada para consultar o diretório. Ela só precisa de
        permissão de <b>leitura</b> — não é uma conta de administrador do domínio.
      </p>
      <div class="form-grid">
        <div class="field span-2"><label>Base DN *</label><input name="ldap_base_dn" value="${esc(cfg.ldap_base_dn)}" placeholder="DC=empresa,DC=local"></div>
        <div class="field"><label>Conta de serviço *</label><input name="ldap_bind_dn" value="${esc(cfg.ldap_bind_dn)}" placeholder="svc_patrimonio@empresa.local"></div>
        <div class="field"><label>Senha da conta de serviço</label>
          <input type="password" name="ldap_bind_senha" placeholder="${cfg.ldap_bind_senha_definida ? "(definida — deixe vazio para manter)" : "informe a senha"}">
          <span class="hint">${cfg.ldap_bind_senha_definida ? (cfg.ldap_bind_senha_cifrada ? "Guardada cifrada no banco." : "Atenção: guardada sem cifra.") : "Ainda não definida."}</span>
        </div>
      </div>
    </div>

    <div class="form-section"><h4>Busca no diretório</h4>
      <p class="muted" style="margin:0 0 12px;font-size:13px">
        Com o AD ligado, a tela de <b>cadastro de usuário</b> ganha uma busca: você
        digita o usuário de rede (ex.: <code>20110030</code>) e o nome completo
        vem preenchido do diretório.
      </p>
      <div class="form-grid">
        <div class="field span-2"><label>Filtro de busca do usuário</label>
          <input name="ldap_filtro_usuario" value="${esc(cfg.ldap_filtro_usuario || "(sAMAccountName={usuario})")}">
          <span class="hint">Use <code>{usuario}</code> onde o login digitado deve entrar. Para UPN: <code>(userPrincipalName={usuario})</code>.</span></div>
      </div>
    </div>

    <div class="form-section"><h4>Quem pode entrar no sistema</h4>
      <div class="avisos">
        <div class="aviso-linha">
          <span class="aviso-icone">${icon("lock", 18)}</span>
          <span>
            <b>O AD não libera mais o acesso.</b> Ele só confirma a identidade —
            a senha de rede. Quem entra, e com qual perfil, é definido no
            <b>cadastro de usuário</b>, feito por você.
          </span>
        </div>
        <div class="aviso-linha">
          <span class="aviso-icone">${icon("user", 18)}</span>
          <span>
            Alguém com usuário e senha de rede válidos, mas <b>sem cadastro aqui</b>,
            recebe a mensagem de que ainda não tem acesso — e nada é criado
            automaticamente.
          </span>
        </div>
        <div class="aviso-linha">
          <span class="aviso-icone">${icon("check", 18)}</span>
          <span>
            O administrador local (root) continua entrando pela senha do sistema,
            sem depender do AD — é a sua rota de emergência.
          </span>
        </div>
      </div>
    </div>`;

  const resultadoBox = el("div");

  // O distintivo de situação acompanha o interruptor enquanto se edita — assim
  // dá para ver o efeito antes mesmo de salvar.
  const interruptorAd = form.querySelector('[name="ldap_ativo"]');
  const distintivo = form.querySelector("#ad-situacao");
  interruptorAd?.addEventListener("change", () => {
    const ligado = interruptorAd.checked;
    distintivo.textContent = ligado ? "Ativado" : "Desativado";
    distintivo.className = `badge ${ligado ? "ok" : "aviso"}`;
  });

  async function salvar() {
    const fd = new FormData(form);
    const payload = {
      ldap_ativo: Boolean(fd.get("ldap_ativo")),
      ldap_servidor: fd.get("ldap_servidor") || null,
      ldap_porta: Number(fd.get("ldap_porta")) || 636,
      ldap_tls: Boolean(fd.get("ldap_tls")),
      ldap_ignorar_certificado: Boolean(fd.get("ldap_ignorar_certificado")),
      ldap_base_dn: fd.get("ldap_base_dn") || null,
      ldap_bind_dn: fd.get("ldap_bind_dn") || null,
      ldap_filtro_usuario: fd.get("ldap_filtro_usuario") || "(sAMAccountName={usuario})",
    };
    const senha = fd.get("ldap_bind_senha");
    if (senha) payload.ldap_bind_senha = senha;
    await api.put("/admin/config", payload);
    toast("Configuração salva");
  }

  root.append(el("div", { class: "card" }, form,
    el("div", { class: "row", style: "gap:10px;margin-top:8px" },
      el("button", { class: "btn filled", type: "button", onclick: async () => {
        try { await salvar(); } catch (e) { mostrarErro(e); }
      }, html: icon("check", 18) + " Salvar" }),
      el("button", { class: "btn outlined", type: "button", onclick: async () => {
        try {
          await salvar();
          const r = await api.post("/admin/config/testar-ldap");
          resultadoBox.innerHTML = "";
          resultadoBox.append(el("p", { style: `font-weight:600;color:${r.ok ? "var(--cor-ok)" : "var(--md-sys-color-error)"}` }, (r.ok ? "✓ " : "✗ ") + r.mensagem));
        } catch (e) { mostrarErro(e); }
      }, html: icon("server", 18) + " Testar conexão" }),
      el("button", { class: "btn tonal", type: "button", onclick: () => testarLogin(resultadoBox), html: icon("user", 18) + " Testar login de usuário" }),
    ),
    resultadoBox,
  ));

  // Diagnóstico
  const diag = await api.get("/admin/config/diagnostico").catch(() => null);
  if (diag) {
    root.append(el("div", { class: "card" },
      el("div", { class: "section-title", style: "margin:0 0 10px" }, "Diagnóstico"),
      ...[
        ["Login via AD", diag.ldap_ativo ? "ativado" : "desativado"],
        ["Administrador local (não depende do AD)", diag.admin_local],
        ["Senha da conta de serviço guardada", diag.senha_servico_guardada ? (diag.senha_servico_decifravel ? "sim (cifrada)" : "sim, mas não foi possível decifrar") : "não"],
        ["Quem libera o acesso", "o cadastro de usuário (o AD não libera)"],
        ["Assinatura do QR", diag.qr_exigir_assinatura ? "exigida" : "opcional (etiquetas antigas continuam válidas)"],
        ["Segredos de QR aceitos", String(diag.segredos_qr_aceitos)],
        ["Pasta de backups", diag.pasta_backups],
      ].map(([k, v]) => el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:9px 0" },
        el("span", { class: "muted" }, k), el("span", {}, String(v)))),
    ));
  }
}

function testarLogin(resultadoBox) {
  const usuario = el("input", { placeholder: "login ou usuario@empresa.com" });
  const senha = el("input", { type: "password" });
  dialog({
    title: "Testar login de um usuário",
    body: el("div", {},
      el("p", { class: "muted" }, "Valida a senha no AD e informa se esta pessoa já tem cadastro no sistema. Nada é gravado."),
      el("div", { class: "field" }, el("label", {}, "Usuário"), usuario),
      el("div", { class: "field" }, el("label", {}, "Senha"), senha),
    ),
    actions: [
      { label: "Fechar", variant: "text" },
      { label: "Testar", variant: "filled", onClick: async (close) => {
        try {
          const r = await api.post("/admin/config/testar-login", { usuario: usuario.value, senha: senha.value });
          close();
          resultadoBox.innerHTML = "";
          resultadoBox.append(
            el("p", { style: `font-weight:600;color:${r.ok ? "var(--cor-ok)" : "var(--md-sys-color-error)"}` }, (r.ok ? "✓ " : "✗ ") + r.mensagem),
            r.nome ? el("p", { class: "muted" }, `${r.nome} · ${r.email || ""}`) : null,
                        r.grupos && r.grupos.length ? el("details", {}, el("summary", { class: "muted" }, `${r.grupos.length} grupo(s) no diretório`), el("div", { class: "mono" }, r.grupos.join("\n"))) : null,
          );
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}
