import { el, icon } from "./ui.js";

export function criarPlantaConsulta(selecionar, signal) {
  const imagem = el("img", { alt: "Planta baixa da unidade", draggable: "false", hidden: "" });
  const paredes = el("div", { "aria-hidden": "true" });
  const marcadores = el("div");
  const conteudo = el("div", { class: "mapa-planta-conteudo" }, imagem, paredes, marcadores);
  const elemento = el("div", { class: "mapa-planta-consulta", role: "region", tabindex: "0", "aria-label": "Planta dos equipamentos" }, conteudo);
  const pinos = new Map();
  let limites, plantaAnterior, paredesAnteriores, x = 0, z = 0, zoom = 1, base = 1, gesto;

  function aplicar() {
    if (!limites || !elemento.clientWidth || !elemento.clientHeight) return;
    const margem = elemento.clientWidth < 500 ? 46 : 104;
    base = Math.min(Math.max(40, elemento.clientWidth - margem) / (limites.dir - limites.esq),
      Math.max(40, elemento.clientHeight - margem) / (limites.baixo - limites.cima));
    const escala = base * zoom;
    conteudo.style.setProperty("--mapa-metro", `${escala}px`);
    conteudo.style.transform = `translate(${elemento.clientWidth / 2 - x * escala}px, ${elemento.clientHeight / 2 - z * escala}px)`;
  }

  function enquadrar() {
    if (!limites) return;
    x = (limites.esq + limites.dir) / 2;
    z = (limites.cima + limites.baixo) / 2;
    zoom = 1;
    aplicar();
  }

  function ampliar(fator, px = 0, pz = 0) {
    const anterior = zoom;
    zoom = Math.max(0.65, Math.min(zoom * fator, 8));
    const delta = (1 / anterior - 1 / zoom) / base;
    x += px * delta;
    z += pz * delta;
    aplicar();
  }

  function atualizar(projeto, equipamentos, selecionado) {
    const { plan, walls, equipment } = projeto;
    const refazerPlanta = !limites || plan !== plantaAnterior;
    const geometriaParedes = JSON.stringify(walls);
    const largura = plan?.widthM || 12;
    const altura = plan?.heightM || 8;
    const novas = { esq: -largura / 2, dir: largura / 2, cima: -altura / 2, baixo: altura / 2 };
    function incluir(px, pz) {
      novas.esq = Math.min(novas.esq, px - 0.6);
      novas.dir = Math.max(novas.dir, px + 0.6);
      novas.cima = Math.min(novas.cima, pz - 0.6);
      novas.baixo = Math.max(novas.baixo, pz + 0.6);
    }
    walls.forEach(wall => wall.points.forEach(([px, pz]) => incluir(px, pz)));
    equipment.forEach(eq => { if (!eq.pendente) incluir(eq.x, eq.z); });
    limites = novas;
    if (refazerPlanta) {
      plantaAnterior = plan;
      imagem.hidden = !plan?.dataUrl;
      if (plan?.dataUrl) imagem.src = plan.dataUrl;
      else imagem.removeAttribute("src");
      geometria(imagem, -largura / 2, -altura / 2, largura, altura);
      enquadrar();
    }
    if (geometriaParedes !== paredesAnteriores) {
      paredesAnteriores = geometriaParedes;
      paredes.replaceChildren(...walls.flatMap(wall => wall.points.slice(1).map(([px, pz], i) => {
        const [origemX, origemZ] = wall.points[i];
        const parede = el("div", { class: "mapa-planta-parede" });
        geometria(parede, origemX, origemZ, Math.hypot(px - origemX, pz - origemZ), wall.thickness);
        parede.style.transform = `rotate(${Math.atan2(pz - origemZ, px - origemX)}rad) translateY(-50%)`;
        return parede;
      })));
    }
    const ids = new Set(equipamentos.map(eq => eq.id));
    for (const [id, pino] of pinos) {
      if (ids.has(id)) continue;
      pino.remove();
      pinos.delete(id);
    }
    for (const eq of equipamentos) {
      let pino = pinos.get(eq.id);
      if (!pino) {
        const impressora = eq.ativo.dominio === "impressora";
        pino = el("button", { type: "button", class: `mapa-pino${impressora ? " impressora" : ""}`,
          onclick: () => selecionar(eq.id), "aria-label": eq.name, title: eq.name },
        el("span", { html: icon(impressora ? "print" : "ativos", 16), "aria-hidden": "true" }),
        el("span", { class: "mapa-pino-rotulo", "aria-hidden": "true" }, eq.name));
        pinos.set(eq.id, pino);
        marcadores.append(pino);
      }
      geometria(pino, eq.x, eq.z);
      pino.setAttribute("aria-pressed", String(eq.id === selecionado));
    }
    aplicar();
  }

  const observer = new ResizeObserver(aplicar);
  observer.observe(elemento);
  signal.addEventListener("abort", () => observer.disconnect(), { once: true });
  elemento.addEventListener("wheel", ev => {
    ev.preventDefault();
    const r = elemento.getBoundingClientRect();
    const delta = ev.deltaY * (ev.deltaMode === 1 ? 16 : ev.deltaMode === 2 ? r.height : 1);
    ampliar(Math.exp(-Math.max(-160, Math.min(160, delta)) * 0.0025), ev.clientX - r.left - r.width / 2, ev.clientY - r.top - r.height / 2);
  }, { passive: false, signal });
  elemento.addEventListener("pointerdown", ev => {
    if (ev.button !== 0 || gesto || ev.target.closest("button")) return;
    gesto = { id: ev.pointerId, x: ev.clientX, z: ev.clientY };
    elemento.setPointerCapture(ev.pointerId);
  }, { signal });
  elemento.addEventListener("pointermove", ev => {
    if (gesto?.id !== ev.pointerId) return;
    x -= (ev.clientX - gesto.x) / (base * zoom);
    z -= (ev.clientY - gesto.z) / (base * zoom);
    gesto.x = ev.clientX;
    gesto.z = ev.clientY;
    aplicar();
  }, { signal });
  elemento.addEventListener("lostpointercapture", ev => {
    if (gesto?.id === ev.pointerId) gesto = null;
  }, { signal });
  elemento.addEventListener("keydown", ev => {
    if (ev.target !== elemento) return;
    const direcao = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[ev.key];
    if (!direcao) return;
    ev.preventDefault();
    x += direcao[0] * 40 / (base * zoom);
    z += direcao[1] * 40 / (base * zoom);
    aplicar();
  }, { signal });

  return { elemento, atualizar, enquadrar, ampliar, focar(eq) {
    x = eq.x;
    z = eq.z;
    aplicar();
  } };
}

function geometria(elemento, x, z, largura, altura) {
  elemento.style.left = `calc(${x} * var(--mapa-metro))`;
  elemento.style.top = `calc(${z} * var(--mapa-metro))`;
  if (largura !== undefined) elemento.style.width = `calc(${largura} * var(--mapa-metro))`;
  if (altura !== undefined) elemento.style.height = `calc(${altura} * var(--mapa-metro))`;
}
