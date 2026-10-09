/**
 * Administração → Conexão com DBA.
 *
 * Tela **somente leitura**, por decisão de projeto: a conexão é fixada quando
 * o sistema sobe. Se o endereço pudesse ser trocado daqui e estivesse errado,
 * esta própria tela deixaria de abrir — e o sistema perderia a única forma de
 * se consertar pela interface.
 *
 * @module views/admin_banco
 */
import { api } from "../api.js";
import { el, icon, mostrarErro } from "../ui.js";

/** Uma linha "rótulo → valor" do painel. */
function linha(rotulo, valor, extra = {}) {
  return el("div", { class: "row between", style: "border-bottom:1px solid var(--md-sys-color-outline-variant);padding:9px 0;gap:12px" },
    el("span", { class: "muted" }, rotulo),
    el("span", { style: "text-align:right;word-break:break-word", ...extra }, String(valor ?? "—")),
  );
}

function cartao(titulo, ...conteudo) {
  return el("div", { class: "card" },
    el("div", { class: "section-title", style: "margin:0 0 10px" }, titulo),
    ...conteudo,
  );
}

export async function renderBanco(root) {
  root.innerHTML = "";

  let d;
  try {
    d = await api.get("/admin/banco");
  } catch (e) {
    mostrarErro(e, "consultar o banco de dados");
    return;
  }

  const cx = d.conexao || {};
  const saudavel = d.saudavel !== false;

  // ---------------------------------------------------------------- situação
  root.append(el("div", { class: "card" },
    el("div", { class: "row between", style: "flex-wrap:wrap;gap:10px" },
      el("div", {},
        el("div", { class: "section-title", style: "margin:0" }, "Conexão com o banco de dados"),
        el("div", { class: "muted", style: "font-size:13px" },
          "Situação atual. Esta tela é apenas de visualização."),
      ),
      el("span", { class: `badge ${saudavel ? "ok" : "aviso"}` },
        saudavel ? "Conectado" : "Sem resposta"),
    ),
  ));

  // ------------------------------------------------------------------ detalhes
  const detalhes = [
    linha("Tipo de banco", cx.tipo),
    linha("Endereço", el("code", { style: "font-size:12.5px" }, cx.url || "—")),
  ];
  if (cx.servidor) detalhes.push(linha("Servidor", `${cx.servidor}${cx.porta ? `:${cx.porta}` : ""}`));
  if (cx.banco) detalhes.push(linha("Banco", cx.banco));
  if (cx.usuario) detalhes.push(linha("Usuário", cx.usuario));
  if (cx.driver) detalhes.push(linha("Driver", cx.driver));
  detalhes.push(linha("Senha", cx.senha_definida ? "definida (não é exibida)" : "não definida"));
  detalhes.push(linha("Versão do servidor", d.servidor_versao));
  if (d.tamanho_legivel) detalhes.push(linha("Tamanho do banco", d.tamanho_legivel));
  if (d.total_tabelas != null) detalhes.push(linha("Tabelas", d.total_tabelas));

  root.append(cartao("Detalhes da conexão", ...detalhes));

  // ------------------------------------------------------------------- SQLite
  if (d.sqlite) {
    root.append(cartao("Arquivo do banco (SQLite)",
      linha("Caminho", el("code", { style: "font-size:12.5px" }, d.sqlite.arquivo || "—")),
      linha("Caminho completo", el("code", { style: "font-size:12px" }, d.sqlite.absoluto || "—")),
      linha("Tamanho", d.sqlite.tamanho_legivel),
      linha("Situação", d.sqlite.existe ? "arquivo encontrado" : "arquivo NÃO encontrado"),
      el("p", { class: "muted", style: "margin:10px 0 0;font-size:12.5px" },
        "Este é o arquivo que você copia para fazer uma cópia de segurança manual. "
        + "Com o sistema em uso, prefira a aba Backups — ela copia de forma consistente."),
    ));
  }

  // --------------------------------------------------------------- PostgreSQL
  if (d.postgres) {
    const p = d.postgres;
    root.append(cartao("Pool de conexões (PostgreSQL)",
      linha("Conexões abertas", p.pool_tamanho),
      linha("Em uso agora", p.pool_em_uso),
      linha("Disponíveis", p.pool_disponivel),
      el("p", { class: "muted", style: "margin:10px 0 0;font-size:12.5px" },
        "O pool reaproveita conexões entre requisições. Verificações de saúde "
        + "automáticas descartam conexões mortas."),
    ));
  }

  // ---------------------------------------------------------------- contagens
  if ((d.contagens || []).length) {
    const total = d.contagens.reduce((s, c) => s + c.linhas, 0);
    root.append(cartao("Conteúdo do banco",
      ...d.contagens.map((c) => linha(c.tabela, c.linhas.toLocaleString("pt-BR"))),
      linha(el("b", {}, "Total das principais"), el("b", {}, total.toLocaleString("pt-BR"))),
    ));
  }

  // ------------------------------------------------------------ como alterar
  root.append(el("div", { class: "card" },
    el("div", { class: "row", style: "gap:10px;align-items:flex-start" },
      el("span", { class: "aviso-icone", html: icon("lock", 20) }),
      el("div", {},
        el("div", { style: "font-weight:600;margin-bottom:6px" },
          "Esta tela não altera a conexão — de propósito."),
        el("p", { class: "muted", style: "margin:0;font-size:13px;line-height:1.6" }, d.como_alterar),
      ),
    ),
  ));

  if (!saudavel) {
    root.append(el("div", { class: "card" },
      el("p", { class: "text-error", style: "margin:0" }, d.mensagem)));
  }
}
