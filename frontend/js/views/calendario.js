/**
 * Calendário de empréstimos — visão mensal da agenda de devoluções.
 *
 * Mostra quando cada ativo emprestado deve voltar. A devolução prevista
 * aparece como etiqueta no dia; os dias em que o ativo está fora ficam
 * levemente marcados, para dar noção do tempo total.
 *
 * @module views/calendario
 */
import { api } from "../api.js";
import { ctx } from "../context.js";
import { state } from "../state.js";
import { el, icon, toast, dialog, skeleton, fmtDate, mostrarErro } from "../ui.js";

const DIAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
  "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

let mesAtual = new Date();
let dados = null;

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const mesmoDia = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** Compara só a parte da data de uma string ISO. */
function diaDe(isoStr) {
  const [a, m, d] = isoStr.split("-").map(Number);
  return new Date(a, m - 1, d);
}

/** Detalhe de um empréstimo. */
function verEmprestimo(item) {
  dialog({
    title: `Empréstimo — ${item.patrimonio}`,
    body: el("div", {},
      ...[
        ["Chamado", item.numero_chamado || "—"],
        ["Ativo", `${item.patrimonio} — ${item.modelo || "sem modelo"}`],
        ["Planta", item.planta_sigla || "—"],
        ["Emprestado em", fmtDate(item.emprestado_em)],
        ["Devolução prevista", fmtDate(item.devolucao_prevista)],
        ["Situação", item.atrasado
          ? `Atrasado há ${Math.abs(item.dias_restantes)} dia(s)`
          : `Vence em ${item.dias_restantes} dia(s)`],
        ["Local", item.localizacao || "—"],
      ].map(([k, v]) => el("div", {
        class: "row",
        style: "justify-content:space-between;border-bottom:1px solid var(--md-sys-color-outline-variant);padding:6px 0",
      }, el("span", { class: "muted" }, k), el("span", {}, String(v)))),
    ),
    actions: [
      { label: "Fechar", variant: "text" },
      { label: "Ver no ativo", variant: "outlined", onClick: (close) => {
        close();
        location.hash = `#/ativos?busca=${encodeURIComponent(item.patrimonio)}&destaque=${item.ativo_id}`;
      } },
    ],
  });
}

/** Lista os empréstimos de um dia específico. */
function verDia(dia, emprestimos) {
  if (!emprestimos.length) return;
  dialog({
    title: `${dia.getDate()} de ${MESES[dia.getMonth()]}`,
    body: el("div", {}, ...emprestimos.map((e) => {
      const linha = el("div", { class: "list-row", style: "cursor:pointer" },
        el("div", { class: "list-main" },
          el("div", { class: "list-title" }, e.patrimonio),
          el("div", { class: "list-sub" },
            `Chamado ${e.numero_chamado || "—"} · ${e.modelo || "sem modelo"}`),
        ),
        el("span", { class: e.atrasado ? "badge danger" : "badge" }, e.atrasado ? "Atrasado" : `${e.dias_restantes}d`),
      );
      linha.addEventListener("click", () => verEmprestimo(e));
      return linha;
    })),
    actions: [{ label: "Fechar", variant: "text" }],
  });
}

/** Monta a grade do mês. */
function montarGrade() {
  const ano = mesAtual.getFullYear();
  const mes = mesAtual.getMonth();
  const primeiro = new Date(ano, mes, 1);
  const ultimo = new Date(ano, mes + 1, 0);

  // Começa no domingo da semana do dia 1.
  const inicio = new Date(primeiro);
  inicio.setDate(1 - primeiro.getDay());

  const itens = dados.itens || [];
  const hoje = new Date();

  const grade = el("div", { class: "cal-grade" });
  DIAS.forEach((d) => grade.append(el("div", { class: "cal-cabecalho" }, d)));

  const cursor = new Date(inicio);
  // 6 semanas cobrem qualquer mês.
  for (let s = 0; s < 6; s++) {
    for (let d = 0; d < 7; d++) {
      const dia = new Date(cursor);
      const foraDoMes = dia.getMonth() !== mes;
      const devolvem = itens.filter((i) => mesmoDia(diaDe(i.devolucao_prevista), dia));
      const emCurso = itens.filter((i) => {
        const ini = diaDe(i.emprestado_em);
        const fim = diaDe(i.devolucao_prevista);
        return ini <= dia && dia <= fim;
      });

      const classe = ["cal-dia"];
      if (foraDoMes) classe.push("fora");
      if (mesmoDia(dia, hoje)) classe.push("hoje");
      if (emCurso.length && !foraDoMes) classe.push("em-curso");
      if (devolvem.some((i) => i.atrasado)) classe.push("tem-atraso");

      const celula = el("div", { class: classe.join(" ") },
        el("div", { class: "cal-numero" }, String(dia.getDate())),
        el("div", { class: "cal-itens" },
          ...devolvem.slice(0, 4).map((i) => {
            const etiqueta = el("button", {
              type: "button",
              class: "cal-item" + (i.atrasado ? " atrasado" : ""),
              title: `Chamado ${i.numero_chamado || "—"} · devolver ${fmtDate(i.devolucao_prevista)}`,
              onclick: (ev) => { ev.stopPropagation(); verEmprestimo(i); },
            }, `${i.patrimonio}${i.planta_sigla ? ` · ${i.planta_sigla}` : ""}`);
            return etiqueta;
          }),
          devolvem.length > 4
            ? el("button", {
                type: "button", class: "cal-mais",
                onclick: (ev) => { ev.stopPropagation(); verDia(dia, devolvem); },
              }, `+${devolvem.length - 4} mais`)
            : null,
        ),
      );
      if (devolvem.length) celula.addEventListener("click", () => verDia(dia, devolvem));
      grade.append(celula);
      cursor.setDate(cursor.getDate() + 1);
    }
  }
  return grade;
}

/** Navega entre meses e recarrega. */
async function irPara(delta, root) {
  mesAtual = new Date(mesAtual.getFullYear(), mesAtual.getMonth() + delta, 1);
  await renderCalendario(root);
}

export async function renderCalendario(root) {
  ctx.setTitle("Calendário");
  ctx.setFab(null);
  root.innerHTML = "";

  // Busca o mês inteiro (com uma semana de folga de cada lado, para os dias
  // das bordas que aparecem na grade).
  const primeiro = new Date(mesAtual.getFullYear(), mesAtual.getMonth(), 1);
  const ultimo = new Date(mesAtual.getFullYear(), mesAtual.getMonth() + 1, 0);
  const de = new Date(primeiro); de.setDate(de.getDate() - 7);
  const ate = new Date(ultimo); ate.setDate(ate.getDate() + 7);

  const alvo = el("div", {}, skeleton(4));
  root.append(
    el("h1", { class: "page-title" }, "Calendário de empréstimos"),
    alvo,
  );

  try {
    [dados] = await Promise.all([
      api.get("/calendario/emprestimos", { inicio: iso(de), fim: iso(ate) }),
    ]);
  } catch (e) {
    alvo.innerHTML = "";
    alvo.append(el("div", { class: "card" }, el("p", { class: "text-error" }, e.message)));
    return;
  }

  const resumo = await api.get("/calendario/resumo").catch(() => null);

  alvo.innerHTML = "";
  alvo.append(
    el("div", { class: "card" },
      el("div", { class: "row between", style: "flex-wrap:wrap;gap:10px" },
        el("div", { class: "row", style: "gap:8px" },
          el("button", { class: "iconbtn", title: "Mês anterior", onclick: () => irPara(-1, root), html: icon("chevL") }),
          el("button", { class: "btn tonal small", onclick: () => { mesAtual = new Date(); renderCalendario(root); } }, "Hoje"),
          el("button", { class: "iconbtn", title: "Próximo mês", onclick: () => irPara(1, root), html: icon("chevR") }),
          el("strong", { style: "margin-left:6px;font-size:16px" },
            `${MESES[mesAtual.getMonth()]} de ${mesAtual.getFullYear()}`),
        ),
        resumo
          ? el("div", { class: "row", style: "gap:8px;flex-wrap:wrap" },
              el("span", { class: "chip" }, `${resumo.emprestados} emprestado(s)`),
              resumo.atrasados ? el("span", { class: "chip danger" }, `${resumo.atrasados} atrasado(s)`) : null,
              resumo.devolvem_hoje ? el("span", { class: "chip" }, `${resumo.devolvem_hoje} devolve(m) hoje`) : null,
              resumo.proximos_7_dias ? el("span", { class: "chip" }, `${resumo.proximos_7_dias} em 7 dias`) : null,
              resumo.chamados_abertos ? el("span", { class: "chip" }, `${resumo.chamados_abertos} chamado(s)`) : null,
            )
          : null,
      ),
    ),
    el("div", { class: "card" }, montarGrade()),
  );

  if (!dados.total) {
    alvo.append(el("p", { class: "muted", style: "text-align:center;padding:12px" },
      "Nenhum empréstimo neste período. Empreste um ativo pela tela de Ativos "
      + "(ou pela Leitura) para ele aparecer aqui."));
  }
}
