/**
 * Tela de login — em etapas.
 *
 * O servidor decide o que ainda falta e devolve em `acao_requerida`. A tela não
 * adivinha: ela mostra a etapa que o servidor pediu. Isso mantém a regra num
 * lugar só (o backend) e evita a tela liberar algo que o servidor vai recusar.
 *
 * As etapas possíveis, nesta ordem:
 *
 * 1. **senha** — sempre
 * 2. **código** — quando o MFA já está cadastrado
 * 3. **troca de senha** — quando a senha foi definida pelo administrador
 * 4. **cadastro do MFA** — quando a conta é nova
 *
 * @module views/login
 */
import { state } from "../state.js";
import { api } from "../api.js";
import { el, icon, toast, mostrarErro } from "../ui.js";
import { erroDeResposta } from "../erros.js";

export function renderLogin(root) {
  document.title = "Entrar — Nexus";
  root.innerHTML = "";

  // Credenciais guardadas entre as etapas: a segunda precisa reenviar a senha,
  // e pedir para digitar tudo de novo a cada tentativa seria hostil.
  const credenciais = { email: "", senha: "" };

  const miolo = el("div");
  const card = el("div", { class: "login-card card elevated" },
    el("div", { class: "login-logo", html:
      `<div style="font-size:40px">${icon("dashboard", 48)}</div>` +
      '<h2 style="margin:8px 0 0">Nexus</h2>' +
      '<p class="muted">Inventário de TI e Impressoras</p>' }),
    miolo,
  );
  root.append(card);

  // -------------------------------------------------------------------------
  function mostrarSenha(aviso) {
    miolo.innerHTML = "";
    const email = el("input", { id: "login-email", type: "email",
      autocomplete: "username", required: "", value: credenciais.email });
    const senha = el("input", { id: "login-senha", type: "password",
      autocomplete: "current-password", required: "" });
    const botao = el("button", { class: "btn filled", type: "submit", style: "width:100%" }, "Entrar");

    const form = el("form", {},
      el("div", { class: "field" }, el("label", { for: "login-email" }, "E-mail ou usuário de rede"), email),
      el("div", { class: "field" }, el("label", { for: "login-senha" }, "Senha"), senha),
      aviso ? el("div", { class: "recado info" }, aviso) : null,
      botao,
    );
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      credenciais.email = email.value.trim();
      credenciais.senha = senha.value;
      botao.disabled = true;
      botao.textContent = "Entrando…";
      await tentar();
      botao.disabled = false;
      botao.textContent = "Entrar";
    });

    miolo.append(form);
    setTimeout(() => (credenciais.email ? senha : email).focus(), 60);
  }

  // -------------------------------------------------------------------------
  function mostrarCodigo() {
    miolo.innerHTML = "";
    const codigo = el("input", { id: "login-codigo", inputmode: "numeric",
      autocomplete: "one-time-code", maxlength: "6",
      style: "font-size:22px;letter-spacing:6px;text-align:center", required: "" });
    const botao = el("button", { class: "btn filled", type: "submit", style: "width:100%" }, "Confirmar");

    const form = el("form", {},
      el("p", { class: "muted", style: "margin:0 0 12px" },
        "Abra o aplicativo autenticador e informe o código de 6 dígitos."),
      el("div", { class: "field" }, el("label", { for: "login-codigo" }, "Código"), codigo),
      el("div", { class: "field" }, el("span", { class: "dica" },
        "Perdeu o celular? Use um dos códigos de recuperação que você guardou — "
        + "eles também entram aqui.")),
      botao,
    );
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      botao.disabled = true;
      botao.textContent = "Verificando…";
      await tentar(codigo.value.trim());
      botao.disabled = false;
      botao.textContent = "Confirmar";
    });

    miolo.append(
      form,
      el("button", { class: "btn text", style: "width:100%;margin-top:6px", type: "button",
        onclick: () => mostrarSenha("Entre novamente para reiniciar.") }, "Voltar"),
    );
    setTimeout(() => codigo.focus(), 60);
  }

  // -------------------------------------------------------------------------
  /** Troca obrigatória: a senha atual é a que o administrador definiu. */
  function mostrarTrocaSenha() {
    miolo.innerHTML = "";
    const atual = el("input", { type: "password", value: credenciais.senha, required: "" });
    const nova = el("input", { type: "password", autocomplete: "new-password", required: "" });
    const confirma = el("input", { type: "password", autocomplete: "new-password", required: "" });
    const botao = el("button", { class: "btn filled", type: "submit", style: "width:100%" }, "Definir nova senha");

    const form = el("form", {},
      el("div", { class: "recado info" },
        el("b", {}, "Primeiro acesso."),
        " Sua senha foi definida pelo administrador — escolha uma senha sua para continuar."),
      el("div", { class: "field" }, el("label", {}, "Senha atual"), atual),
      el("div", { class: "field" }, el("label", {}, "Nova senha"), nova,
        el("span", { class: "dica" }, "Pelo menos 8 caracteres, com letras e números.")),
      el("div", { class: "field" }, el("label", {}, "Repita a nova senha"), confirma),
      botao,
    );

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (nova.value !== confirma.value) {
        mostrarErro(new Error("A confirmação não confere com a senha nova."));
        return;
      }
      botao.disabled = true;
      botao.textContent = "Salvando…";
      try {
        const r = await api.post("/auth/trocar-senha", {
          senha_atual: atual.value,
          senha_nova: nova.value,
          confirmacao: confirma.value,
        });
        // A senha mudou: guardamos para o próximo login e seguimos.
        credenciais.senha = nova.value;
        toast("Senha alterada");
        if (r.acao_requerida === "cadastrar_mfa") {
          irParaCadastroDoMfa();
        } else {
          entrarNoSistema();
        }
      } catch (e) {
        mostrarErro(e);
        botao.disabled = false;
        botao.textContent = "Definir nova senha";
      }
    });

    miolo.append(
      el("p", { class: "muted", style: "margin:0 0 12px;font-size:13px" },
        `Entrando como ${credenciais.email}`),
      form,
    );
    setTimeout(() => nova.focus(), 60);
  }

  // -------------------------------------------------------------------------
  async function tentar(codigo) {
    try {
      const body = new URLSearchParams({ username: credenciais.email, password: credenciais.senha });
      const url = codigo
        ? `/api/v1/auth/login?codigo=${encodeURIComponent(codigo)}`
        : "/api/v1/auth/login";
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      const data = await res.json().catch(() => ({}));

      // O servidor avisa que falta o código — sinal próprio, distinto de
      // "senha errada". Sem essa distinção a tela não saberia qual mostrar.
      if (res.status === 401 && data.detail === "mfa_necessario") {
        mostrarCodigo();
        return;
      }
      if (!res.ok) throw erroDeResposta(res.status, data);

      state.setAuth(data);

      if (data.acao_requerida === "trocar_senha") { mostrarTrocaSenha(); return; }
      if (data.acao_requerida === "cadastrar_mfa") { irParaCadastroDoMfa(); return; }
      entrarNoSistema();
    } catch (err) {
      mostrarErro(err);
    }
  }

  function irParaCadastroDoMfa() {
    // Já autenticado: o token vale, e a tela de segurança conduz o cadastro.
    location.hash = "#/seguranca";
    location.reload();
  }

  function entrarNoSistema() {
    location.hash = "#/selecao";
    location.reload();
  }

  mostrarSenha();
}
