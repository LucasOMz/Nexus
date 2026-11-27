import { api } from "./api.js";
import { state } from "./state.js";
import { dialog, el, fmtDate, toast } from "./ui.js";

const estados = { enviado: "Enviado · aguardando aceite", assinando: "Finalizando",
  aguardando_agente: "Aguardando confirmação no computador", codigo_expirado: "Código do agente vencido",
  expirado: "Link expirado", assinado: "Termo assinado", substituido: "Atribuição substituída",
  enviando: "Enviando", falha_envio: "Falha no envio" };

export function abrirTermoEntrega(ativoId, prepararAgora = false) {
  const rota = `/ativos/${ativoId}/termo-entrega`;
  const corpo = el("div", { class: "termo-historico" });
  const modal = dialog({ title: "Termo de entrega", body: corpo, wide: true,
    actions: [{ label: "Fechar", variant: "text" }] });
  async function carregar(preparar = false) {
    corpo.replaceChildren(el("p", { role: "status" }, "Carregando…"));
    try {
      const dados = await api.get(rota);
      if (!corpo.isConnected) return;
      const atual = dados.entregas.find(e => e.termo_id === dados.termo_atual);
      const enviar = el("button", { type: "button", class: "btn filled" }, atual ? "Preparar novo envio" : "Preparar envio");
      const status = el("p", { role: "status", class: "muted" });
      const envio = el("div");
      const podeEnviar = state.canWrite && dados.termo_atual &&
        (!atual || ["expirado", "falha_envio", "enviando"].includes(atual.estado));
      corpo.replaceChildren(
        el("p", { class: "muted" }, atual ? estados[atual.estado] : dados.termo_atual ? "Termo ainda não enviado." : "Atribua o computador a um colaborador primeiro."),
        podeEnviar ? enviar : null, status, envio,
        ...dados.entregas.map(item => {
          const c = item.comprovante;
          const detalhe = el("details", {},
            el("summary", {}, `${estados[item.estado] || item.estado} · ${item.destinatario}`),
            el("p", {}, item.assinado_em ? `Assinado em ${fmtDate(item.assinado_em, true)}` : `Validade até ${fmtDate(item.expira_em, true)}`));
          if (c) {
            const baixar = el("button", { class: "btn tonal", type: "button", onclick: async () => {
              baixar.disabled = true;
              try {
                const url = await api.blob(`${rota}/${item.id}/pdf`);
                const link = el("a", { href: url, download: `termo-entrega-${item.id}.pdf` });
                document.body.append(link); link.click(); link.remove();
                setTimeout(() => URL.revokeObjectURL(url), 1500);
              } catch (erro) { status.textContent = erro.message; }
              finally { baixar.disabled = false; }
            } }, "Baixar termo assinado");
            detalhe.append(el("dl", {},
              el("dt", {}, "Colaborador confirmado no AD"), el("dd", {}, c.colaborador + " · " + c.login_ad),
              el("dt", {}, "Evidência do computador"), el("dd", {}, c.agente ? c.confirmacao_agente : "Sem confirmação pelo agente"),
              el("dt", {}, "Integridade do PDF (SHA-256)"), el("dd", {}, el("code", {}, c.hash_pdf)),
              el("dt", {}, "Selo Nexus"), el("dd", {}, el("code", {}, c.selo))), baixar);
            if (item.respostas?.length) detalhe.append(el("h3", {}, "Checklist respondido"),
              el("dl", {}, ...item.respostas.flatMap(resposta => [
                el("dt", {}, `${resposta.rotulo} · página ${resposta.pagina}`),
                el("dd", {}, typeof resposta.valor === "boolean" ? resposta.valor ? "Confirmado" : "Não marcado" : resposta.valor || "Em branco"),
              ])));
          }
          return detalhe;
        }));
      enviar.onclick = async () => {
        enviar.disabled = true;
        status.textContent = "Consultando o e-mail no AD…";
        try {
          const pessoa = await api.request("POST", `${rota}/${dados.termo_atual}/preparar`, { enfileirar: false });
          if (!corpo.isConnected) return;
          status.textContent = "";
          const confirmar = el("button", { type: "button", class: "btn filled" }, "Enviar termo");
          confirmar.onclick = async () => {
            confirmar.disabled = true;
            status.textContent = "Enviando o termo…";
            try {
              await api.request("POST", `${rota}/${dados.termo_atual}/enviar`, { body: { email: pessoa.email }, enfileirar: false });
              toast("Termo enviado por e-mail");
              await carregar();
            } catch (erro) {
              status.textContent = erro.message;
              confirmar.disabled = false;
            }
          };
          envio.replaceChildren(el("section", { class: "card" },
            el("strong", {}, "Confirme o destinatário"), el("p", {}, pessoa.colaborador + " · " + pessoa.email),
            el("p", { class: "muted" }, `Validade do link de ${pessoa.prazo_horas} h.`), confirmar));
        } catch (erro) {
          status.textContent = erro.message;
          enviar.disabled = false;
        }
      };
      if (preparar && podeEnviar) enviar.click();
    } catch (erro) {
      corpo.replaceChildren(el("p", { role: "alert" }, erro.message));
    }
  }
  carregar(prepararAgora);
  return modal;
}
