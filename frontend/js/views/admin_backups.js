/**
 * Administração → Backups.
 * Lista/baixa/valida/restaura backups, e exporta/importa o CSV total.
 * @module views/admin_backups
 */
import { api } from "../api.js";
import { state } from "../state.js";
import { el, icon, toast, dialog, emptyState, fmtDate, mostrarErro } from "../ui.js";
import { erroDeResposta } from "../erros.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function bytes(n) {
  if (!n) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}

async function baixar(url, nome) {
  const res = await fetch(url, { headers: { Authorization: "Bearer " + state.access } });
  if (!res.ok) { toast("Falha ao baixar"); return; }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = nome;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function resumoTexto(resumo) {
  if (!resumo) return "";
  return Object.entries(resumo).map(([k, v]) => `${v} ${k}`).join(" · ");
}

// ---------------------------------------------------------------------------
// Validação + restauração
// ---------------------------------------------------------------------------
async function validar(item) {
  toast("Validando o backup num banco temporário…");
  const r = await api.post("/admin/backups/validar", { arquivo: item.arquivo });
  return r;
}

async function restaurar(item) {
  let validacao;
  try {
    validacao = await validar(item);
  } catch (e) {
    mostrarErro(e);
    return;
  }

  const senha = el("input", { type: "password", placeholder: "Sua senha de administrador" });
  const conf = el("input", { placeholder: 'Digite RESTAURAR' });

  const relatorio = el("div", { style: "margin-bottom:16px" },
    el("p", { style: `font-weight:600;color:${validacao.ok ? "var(--cor-ok)" : "var(--md-sys-color-error)"}` }, validacao.mensagem || ""),
    validacao.resumo ? el("p", { class: "muted", style: "font-size:13px" }, resumoTexto(validacao.resumo)) : null,
    ...(validacao.avisos || []).map((a) => el("p", { style: "color:var(--cor-aviso);font-size:13px;margin:4px 0" }, `⚠ ${a}`)),
  );

  dialog({
    title: `Restaurar ${item.arquivo}`,
    body: el("div", {},
      relatorio,
      el("div", { class: "card", style: "background:var(--md-sys-color-surface-container)" },
        el("p", { style: "margin:0 0 10px;font-weight:600" }, "Esta ação substitui TODOS os dados atuais."),
        el("p", { class: "muted", style: "margin:0;font-size:13px" },
          "Antes de restaurar, o sistema cria automaticamente um backup do estado atual — se algo der errado, dá para voltar. " +
          "Todos os usuários serão desconectados e precisarão entrar novamente. " +
          "As fotos, termos e anexos ficam na pasta media/ e devem ser restaurados separadamente."),
      ),
      el("div", { class: "field", style: "margin-top:16px" }, el("label", {}, "Confirme sua senha"), senha),
      el("div", { class: "field" }, el("label", {}, 'Digite RESTAURAR para confirmar'), conf),
    ),
    actions: [
      { label: "Cancelar", variant: "text" },
      { label: "Restaurar agora", variant: "danger", onClick: async (close) => {
        if (!validacao.ok) { toast("O backup não passou na validação"); return; }
        if (!senha.value || conf.value.trim().toUpperCase() !== "RESTAURAR") {
          toast('Informe a senha e digite RESTAURAR'); return;
        }
        try {
          const r = await api.post("/admin/backups/restaurar", {
            arquivo: item.arquivo, senha: senha.value, confirmacao: conf.value.trim(),
          });
          close();
          if (!r.ok) { toast(r.mensagem || "Falha na restauração"); return; }
          // Sessões foram invalidadas: volta para o login.
          state.logout();
          toast("Backup restaurado. Entre novamente.");
          setTimeout(() => { location.href = "/"; }, 1200);
        } catch (e) { mostrarErro(e); }
      } },
    ],
  });
}

// ---------------------------------------------------------------------------
// CSV total
// ---------------------------------------------------------------------------
async function importarCsv() {
  const arquivo = el("input", { type: "file", accept: ".zip" });
  const atualizar = el("input", { type: "checkbox" });
  const resultadoBox = el("div", { class: "mt" });

  async function enviar(close, aplicar) {
    const file = arquivo.files[0];
    if (!file) { toast("Selecione o arquivo .zip exportado pelo sistema"); return; }
    const fd = new FormData();
    fd.append("file", file);
    const url = `/api/v1/admin/importar?dry_run=${aplicar ? "false" : "true"}&atualizar=${atualizar.checked}`;
    try {
      const res = await fetch(url, { method: "POST", headers: { Authorization: "Bearer " + state.access }, body: fd });
      const dados = await res.json();
      if (!res.ok) throw erroDeResposta(res.status, dados);
      const linhas = Object.entries(dados.tabelas || {})
        .filter(([, v]) => v.novos || v.duplicados || v.ignorados)
        .map(([k, v]) => el("div", { class: "list-row" },
          el("div", { class: "list-main" }, el("div", { class: "list-title" }, k),
            el("div", { class: "list-sub" }, `novos: ${v.novos} · duplicados: ${v.duplicados} · ignorados: ${v.ignorados}`)),
        ));
      resultadoBox.innerHTML = "";
      resultadoBox.append(
        el("p", { style: "font-weight:600" }, dados.mensagem || ""),
        ...(linhas.length ? linhas : [el("p", { class: "muted" }, "Nada a importar.")]),
        dados.dry_run ? el("p", { class: "muted", style: "font-size:13px" }, "Nada foi alterado. Clique em “Aplicar importação” para gravar.") : null,
      );
      if (!dados.dry_run) toast("Importação aplicada");
    } catch (e) { mostrarErro(e); }
  }

  dialog({
    title: "Importar CSV total",
    body: el("div", {},
      el("p", { class: "muted" }, "Envie o arquivo .zip gerado em “Exportar CSV total”. O sistema valida antes de gravar e ignora registros duplicados pela chave de cada entidade (patrimônio, SKU, e-mail, nome…)."),
      el("div", { class: "field" }, el("label", {}, "Arquivo .zip"), arquivo),
      el("label", { class: "switch" }, atualizar, "Atualizar registros já existentes (em vez de apenas ignorar)"),
      resultadoBox,
    ),
    wide: true,
    actions: [
      { label: "Fechar", variant: "text" },
      { label: "Simular", variant: "outlined", onClick: (close) => enviar(close, false) },
      { label: "Aplicar importação", variant: "filled", onClick: (close) => enviar(close, true) },
    ],
  });
}

// ---------------------------------------------------------------------------
// Tela
// ---------------------------------------------------------------------------
export async function renderBackups(root) {
  const dados = await api.get("/admin/backups").catch((e) => { mostrarErro(e); return { status: {}, itens: [] }; });
  const status = dados.status || {};
  const itens = dados.itens || [];

  root.innerHTML = "";

  // Status
  const ultimo = status.ultimo;
  const alerta = !ultimo ? "Nenhum backup encontrado" :
    (status.alerta_atrasado ? `Último backup há ${ultimo.horas_atras} h — verifique o agendamento` : `Último backup há ${ultimo.horas_atras} h`);
  root.append(el("div", { class: "card" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Backups do banco"),
        el("div", { class: "muted", style: "font-size:13px" }, `Pasta: ${status.pasta || "—"} · retenção: ${status.retencao ?? "—"} arquivos`),
      ),
      el("div", { class: "row" },
        el("button", { class: "btn outlined small", onclick: () => baixar("/api/v1/admin/exportar", "nexus-csv.zip"), html: icon("download", 18) + " Exportar CSV total" }),
        el("button", { class: "btn tonal small", onclick: () => importarCsv(), html: icon("add", 18) + " Importar CSV" }),
        el("button", { class: "btn filled small", onclick: async () => {
          try { await api.post("/admin/backups", { motivo: "manual" }); toast("Backup criado"); renderBackups(document.getElementById("view")); }
          catch (e) { mostrarErro(e); }
        }, html: icon("download", 18) + " Criar backup agora" }),
      ),
    ),
    el("p", { style: `margin:14px 0 0;font-weight:600;color:${status.alerta_atrasado ? "var(--cor-aviso)" : "inherit"}` }, alerta),
  ));

  // Lista
  const lista = el("div", { class: "card" });
  if (!itens.length) {
    lista.append(emptyState("download", "Nenhum backup", "Crie o primeiro backup — e o ideal é agendar a geração diária no servidor."));
  }
  itens.forEach((b) => {
    lista.append(el("div", { class: "list-row" },
      el("div", { class: "list-main" },
        el("div", { class: "list-title" }, b.arquivo || "—"),
        el("div", { class: "list-sub" },
          `${fmtDate(b.criado_em, true)} · ${bytes(b.tamanho_bytes)} · v${b.app_version || "?"} · ${b.motivo || "manual"}${b.existe ? "" : " · ARQUIVO AUSENTE"}`),
        b.resumo ? el("div", { class: "list-sub" }, resumoTexto(b.resumo)) : null,
      ),
      el("div", { class: "row" },
        el("button", { class: "btn text small", onclick: async () => {
          const v = await validar(b);
          dialog({
            title: "Validação do backup",
            body: el("div", {},
              el("p", { style: `font-weight:600;color:${v.ok ? "var(--cor-ok)" : "var(--md-sys-color-error)"}` }, v.mensagem || ""),
              v.resumo ? el("p", { class: "muted" }, resumoTexto(v.resumo)) : null,
              ...(v.avisos || []).map((a) => el("p", { style: "color:var(--cor-aviso);font-size:13px" }, `⚠ ${a}`)),
            ),
            actions: [{ label: "Fechar", variant: "text" }],
          });
        }, html: icon("check", 16) + " Validar" }),
        el("button", { class: "iconbtn", title: "Baixar", onclick: () => baixar(`/api/v1/admin/backups/${encodeURIComponent(b.arquivo)}/download`, b.arquivo), html: icon("download", 20) }),
        el("button", { class: "btn danger small", onclick: () => restaurar(b), html: "Restaurar" }),
      ),
    ));
  });
  root.append(lista);
}
