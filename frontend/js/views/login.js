/**
 * Tela de login.
 * @module views/login
 */
import { state } from "../state.js";
import { el, icon, toast, mostrarErro } from "../ui.js";
import { erroDeResposta } from "../erros.js";

export function renderLogin(root) {
  document.title = "Entrar — Gestão Patrimonial";
  root.innerHTML = "";
  const card = el("div", { class: "login-card card elevated" },
    el("div", { class: "login-logo", html: `<div style="font-size:40px">${icon("dashboard", 48)}</div><h2 style="margin:8px 0 0">Gestão Patrimonial</h2><p class="muted">Inventário de TI e Impressoras</p>` }),
    el("form", {},
      el("div", { class: "field" },
        el("label", { for: "login-email" }, "E-mail"),
        el("input", { id: "login-email", type: "email", autocomplete: "username", required: "" }),
      ),
      el("div", { class: "field" },
        el("label", { for: "login-senha" }, "Senha"),
        el("input", { id: "login-senha", type: "password", autocomplete: "current-password", required: "" }),
      ),
      el("button", { class: "btn filled", type: "submit", style: "width:100%" }, "Entrar"),
    ),
  );

  const form = card.querySelector("form");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = card.querySelector("#login-email").value.trim();
    const senha = card.querySelector("#login-senha").value;
    const btn = form.querySelector("button");
    btn.disabled = true;
    btn.textContent = "Entrando…";
    try {
      const body = new URLSearchParams({ username: email, password: senha });
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw erroDeResposta(res.status, data);
      state.setAuth(data);
      // Após entrar, o usuário escolhe qual inventário vai abrir.
      location.hash = "#/selecao";
      location.reload();
    } catch (err) {
      mostrarErro(err);
      btn.disabled = false;
      btn.textContent = "Entrar";
    }
  });

  root.append(card);
}
