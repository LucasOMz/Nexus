/**
 * Mapa 3D do parque — a tela do Nexus sobre o Viewer original.
 *
 * ## O que é reaproveitado
 *
 * **Todo o 3D vem do projeto "Mapa 3D"**:
 *
 * * `viewer.js` (1.875 linhas) — órbita, planta baixa, caminhada com colisão,
 *   etiquetas inteligentes, paredes, medição, calibração, ferramentas.
 * * `models.js` (848 linhas) — os 26 modelos procedurais com LEDs e animação.
 * * `catalog.js` — tipos, categorias e status.
 * * `store.js` (533 linhas) — projeto, histórico de desfazer/refazer.
 *
 * **Esta tela só acrescenta o que o Nexus tem e o original não**: login,
 * planta ativa, e ativos que vêm do banco em vez do `localStorage`.
 *
 * ## Por que não reescrevi
 *
 * A primeira versão desta tela tinha 400 linhas de Three.js próprio e
 * reproduzia mal o que já existia: sem etiquetas, sem caminhada, sem medição,
 * sem os modelos. **Portar é mais barato que reescrever — e não perde
 * recurso.**
 *
 * @module views/mapa
 */
import { api } from "../api.js";
import { el, icon, toast, skeleton, mostrarErro, dialog } from "../ui.js";
import { state } from "../state.js";
import { ctx } from "../context.js";

let Viewer = null;
let StoreNexus = null;

async function carregarModulos() {
  if (Viewer) return;
  const v = await import("../../lib/mapa3d/viewer.js");
  const s = await import("../../lib/mapa3d/store_nexus.js");
  Viewer = v.Viewer;
  StoreNexus = s.StoreNexus;
}

export async function renderMapa(root) {
  root.innerHTML = "";
  root.append(skeleton(4));

  await carregarModulos();

  const planta = state.plantaAtiva || state.user?.planta_id;
  if (!planta) {
    root.innerHTML = "";
    root.append(el("div", { class: "card" },
      el("p", { style: "margin:0" },
        "Escolha uma planta no topo da tela para ver o mapa.")));
    return;
  }

  let projeto = null;
  let dados = { posicionados: [], pendentes: [] };

  try {
    [projeto, dados] = await Promise.all([
      api.get(`/mapas/${planta}`),
      api.get(`/mapas/${planta}/ativos`),
    ]);
  } catch (e) {
    root.innerHTML = "";
    root.append(el("div", { class: "card" },
      el("p", { class: "text-error", style: "margin:0" }, e.message)));
    return;
  }

  root.innerHTML = "";

  const store = new StoreNexus(planta, dados, projeto);

  // ------------------------------------------------------------ estrutura
  //
  // O Viewer desenha dentro do `canvas` e usa `container` para posicionar
  // rótulos HTML (etiquetas dos equipamentos). Os dois precisam existir.
  const canvas = el("canvas", {
    style: "display:block;width:100%;height:100%;outline:none",
  });

  const container = el("div", {
    style: "position:relative;width:100%;height:calc(100vh - 190px);"
      + "min-height:460px;border-radius:12px;overflow:hidden;"
      + "background:#0f1419",
  }, canvas);

  const barra = el("div", {
    class: "row between wrap",
    style: "gap:10px;margin-bottom:12px",
  });

  root.append(barra, container);

  const viewer = new Viewer(container, canvas, store);
  await viewer.init?.();

  // ------------------------------------------------------------ barra
  const modo3d = el("button", { class: "btn tonal small", onclick: () => {
    viewer.setMode("3d");
    atualizarBarra();
  } }, "3D");

  const modoPlanta = el("button", { class: "btn text small", onclick: () => {
    viewer.setMode("top");
    atualizarBarra();
  } }, "Planta baixa");

  const modoCaminhada = el("button", { class: "btn text small", onclick: () => {
    viewer.setMode("walk");
    atualizarBarra();
  } }, "Caminhada");

  const contagem = el("span", { class: "muted", style: "font-size:12.5px" });

  const atualizarBarra = () => {
    const m = viewer.getState?.().mode || "3d";
    for (const [b, alvo] of [[modo3d, "3d"], [modoPlanta, "top"], [modoCaminhada, "walk"]]) {
      b.className = (m === alvo ? "btn tonal small" : "btn text small");
    }
    const pend = store.project.equipment.filter((e) => e.pendente).length;
    // Montado numa expressão só: o guarda de DOM rejeita `el()` concatenado
    // com texto na linha seguinte.
    const partes = [`${store.project.equipment.length - pend} no mapa`];
    if (pend) partes.push(`${pend} sem posição`);
    if (!store.project.plan) partes.push("sem planta baixa");
    contagem.textContent = partes.join(" · ");
  };

  barra.append(
    el("div", { class: "row", style: "gap:6px;align-items:center" },
      modo3d, modoPlanta, modoCaminhada, contagem),
    el("div", { class: "row", style: "gap:6px" },
      el("button", {
        class: "btn text small",
        onclick: () => trocarPlanta(planta, projeto, root),
      }, "Planta baixa"),
      el("button", {
        class: "btn text small",
        onclick: () => { viewer.fitAll?.(); },
      }, "Enquadrar"),
      el("button", {
        class: "btn text small",
        onclick: () => painelPendentes(),
      }, "Pendentes")));

  atualizarBarra();

  // ------------------------------------------------------------ clique
  //
  // O Viewer emite `select` com o item; abrimos a ficha do Nexus.
  store.on?.("select", () => {});
  viewer.container?.addEventListener?.("mapa:select", () => {});

  // O Viewer original emite eventos pelo store — escutamos aqui.
  // `item:added` e `placed` servem para atualizar a contagem.
  store.on("item:added", atualizarBarra);
  store.on("item:removed", atualizarBarra);
  store.on("plan:change", atualizarBarra);

  /** Lista os ativos ainda fora do mapa, para o técnico posicionar. */
  function painelPendentes() {
    const pendentes = store.project.equipment.filter((e) => e.pendente);

    dialog({
      title: "Ativos sem posição",
      body: el("div", {},
        el("p", { class: "muted", style: "margin:0 0 10px;font-size:12.5px" },
          "Escolha um ativo e clique no piso do mapa para colocá-lo. "
          + "Sem esta lista, um ativo novo nunca apareceria no desenho."),
        ...(pendentes.length
          ? pendentes.map((eq) => el("button", {
            class: "btn text small",
            style: "width:100%;justify-content:flex-start;font-size:12.5px",
            onclick: () => {
              viewer.select?.("item", eq.id);
              viewer.startPlacement?.(eq.type);
              toast(`Clique no piso para colocar ${eq.name}`);
            },
          }, `${eq.dominio === "impressora" ? "🖨" : "🖥"} ${eq.name}`))
          : [el("p", { class: "muted" }, "Todos os ativos estão posicionados.")])),
      actions: [{ label: "Fechar", variant: "text" }],
    });
  }

  /** Upload da planta baixa: grava dimensões e escala, depois a imagem. */
  function trocarPlanta(plantaId, proj, raiz) {
    const entrada = el("input", {
      type: "file", accept: "image/png,image/jpeg,image/webp",
    });
    const campoLargura = el("input", {
      class: "field", type: "number", min: "100", max: "20000",
      value: String(proj.largura_px || 1600), style: "width:110px",
    });
    const campoAltura = el("input", {
      class: "field", type: "number", min: "100", max: "20000",
      value: String(proj.altura_px || 1000), style: "width:110px",
    });
    const campoMetros = el("input", {
      class: "field", type: "number", step: "0.5", min: "1", max: "1000",
      value: String(
        Math.round((proj.largura_px || 1600) * (proj.escala_metros_por_pixel || 0.02)),
      ),
      style: "width:130px",
    });

    dialog({
      title: "Planta baixa da unidade",
      body: el("div", {},
        el("p", { class: "muted", style: "margin:0 0 12px;font-size:12.5px" },
          "Envie a planta como PNG ou JPG. Informe a largura em pixels da "
          + "imagem e a largura real em metros — é o que permite medir "
          + "distâncias e dimensionar os equipamentos."),
        el("div", { class: "field" }, el("label", {}, "Imagem"), entrada),
        el("div", { class: "row", style: "gap:10px;flex-wrap:wrap" },
          el("div", { class: "field" }, el("label", {}, "Largura (px)"), campoLargura),
          el("div", { class: "field" }, el("label", {}, "Altura (px)"), campoAltura),
          el("div", { class: "field" }, el("label", {}, "Largura real (m)"), campoMetros))),
      actions: [
        { label: "Cancelar", variant: "text" },
        { label: "Salvar", variant: "tonal", onClick: async () => {
          try {
            const larguraPx = Number(campoLargura.value) || 1600;
            const metros = Number(campoMetros.value) || 32;

            await api.put(`/mapas/${plantaId}`, {
              largura_px: larguraPx,
              altura_px: Number(campoAltura.value) || 1000,
              escala_metros_por_pixel: metros / larguraPx,
            });

            const arquivo = entrada.files?.[0];
            if (arquivo) {
              const fd = new FormData();
              fd.append("arquivo", arquivo);
              await api.upload?.(`/mapas/${plantaId}/imagem`, fd)
                ?? await fetchUpload(`/mapas/${plantaId}/imagem`, fd);
            }

            toast("Planta salva");
            renderMapa(raiz);
          } catch (e) {
            mostrarErro(e);
          }
        } },
      ],
    });
  }

  ctx.limpar = () => {
    viewer.dispose?.();
  };
}

/** Upload com o token, quando `api.upload` não existir. */
async function fetchUpload(caminho, formData) {
  const { state: st } = await import("../state.js");
  const headers = {};
  if (st.access) headers.Authorization = "Bearer " + st.access;
  if (st.plantaAtiva) headers["X-Planta-Id"] = String(st.plantaAtiva);

  const res = await fetch("/api/v1" + caminho, {
    method: "POST", headers, body: formData,
  });
  if (!res.ok) throw new Error(`Falha ao enviar a imagem (${res.status})`);
  return res.json();
}
