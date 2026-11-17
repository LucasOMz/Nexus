/**
 * Mapa 3D do parque — visualização dos ativos reais do Nexus.
 *
 * ## O que este mapa é
 *
 * A planta baixa da unidade **desenhada em 3D**, com cada computador e cada
 * impressora na posição em que está. Não é um cadastro paralelo: os ativos
 * são os mesmos do inventário, e clicar num deles abre a ficha do ativo.
 *
 * ## Por que o desenho é uma textura e não geometria
 *
 * A planta baixa é uma imagem. Transformá-la em paredes exigiria vetorização
 * — e um erro de vetorização deforma o prédio. A imagem como piso, com a
 * escala calibrada, dá a mesma noção de espaço e não mente sobre a forma.
 *
 * As **paredes** existem como geometria só quando o usuário desenha — são
 * para dar profundidade e permitir a caminhada.
 *
 * ## Posicionamento
 *
 * O modo "Posicionar" mostra a lista de ativos **sem posição**. Escolhe um,
 * clica no piso, pronto. Quem já está no mapa pode ser arrastado.
 *
 * @module views/mapa
 */
import { api } from "../api.js";
import { el, icon, toast, skeleton, mostrarErro, dialog } from "../ui.js";
import { state } from "../state.js";
import { ctx } from "../context.js";

/* Três.js vem do `lib/`, versionado junto: o sistema roda em rede interna e
   não pode depender de CDN. */
let THREE = null;
let OrbitControls = null;

async function carregarThree() {
  if (THREE) return;
  THREE = await import("../../lib/three.module.js");
  const mod = await import("../../lib/addons/OrbitControls.js");
  OrbitControls = mod.OrbitControls;
}

const ESCALA_PADRAO = 0.02; // metros por pixel

export async function renderMapa(root) {
  root.innerHTML = "";
  root.append(skeleton(4));

  await carregarThree();

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

  // ------------------------------------------------------------ estado
  const cena3d = {
    moda: "visualizar", // ou "posicionar"
    selecionado: null,  // ativo escolhido para posicionar
    objetos: new Map(), // ativo_id -> mesh
  };

  // ------------------------------------------------------------ barra
  const botaoModa = el("button", {
    class: "btn tonal small",
    onclick: () => {
      cena3d.moda = cena3d.moda === "visualizar" ? "posicionar" : "visualizar";
      cena3d.selecionado = null;
      atualizarBarra();
    },
  }, "Posicionar");

  const info = el("span", { class: "muted", style: "font-size:12.5px" },
    `${dados.posicionados.length} no mapa · ${dados.pendentes.length} sem posição`);

  const atualizarBarra = () => {
    botaoModa.textContent = cena3d.moda === "visualizar" ? "Posicionar" : "Visualizar";
    info.textContent = cena3d.moda === "posicionar"
      ? (cena3d.selecionado
        ? `Clique no piso para colocar: ${cena3d.selecionado.patrimonio || cena3d.selecionado.numero_serie}`
        : "Escolha um ativo na lista à direita")
      : `${dados.posicionados.length} no mapa · ${dados.pendentes.length} sem posição`;
  };

  // ------------------------------------------------------------ canvas
  const canvas = el("div", {
    style: "width:100%;height:calc(100vh - 210px);min-height:420px;"
      + "border-radius:12px;overflow:hidden;background:#0f1419;position:relative",
  });

  const lateral = el("div", {
    style: "width:230px;flex-shrink:0;max-height:calc(100vh - 210px);"
      + "overflow-y:auto",
  });

  root.append(
    el("div", { class: "row between wrap", style: "gap:10px;margin-bottom:12px" },
      el("div", { class: "row", style: "gap:8px;align-items:center" },
        botaoModa,
        el("button", {
          class: "btn text small",
          onclick: () => abrirPlantas(planta, projeto),
        }, "Planta baixa"),
        info),
      el("button", {
        class: "btn text small",
        onclick: () => { desenharLateral(); },
      }, "Atualizar lista")),
    el("div", { class: "row", style: "gap:14px;align-items:flex-start" },
      canvas, lateral));

  // ------------------------------------------------------------ cena
  const cena = new THREE.Scene();
  cena.background = new THREE.Color(0x0f1419);

  const largura = canvas.clientWidth || 900;
  const altura = canvas.clientHeight || 500;
  const camera = new THREE.PerspectiveCamera(50, largura / altura, 0.1, 2000);
  camera.position.set(12, 16, 22);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(largura, altura);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  canvas.append(renderer.domElement);

  const controles = new OrbitControls(camera, renderer.domElement);
  controles.enableDamping = true;
  controles.maxPolarAngle = Math.PI / 2.1;
  controles.target.set(0, 0, 0);

  cena.add(new THREE.AmbientLight(0xffffff, 1.6));
  const sol = new THREE.DirectionalLight(0xffffff, 2.2);
  sol.position.set(18, 30, 14);
  sol.castShadow = true;
  sol.shadow.mapSize.set(1024, 1024);
  cena.add(sol);

  // Piso neutro, para o mapa não flutuar no vazio.
  const piso = new THREE.Mesh(
    new THREE.PlaneGeometry(400, 400),
    new THREE.MeshStandardMaterial({ color: 0x1a2330, roughness: 1 }),
  );
  piso.rotation.x = -Math.PI / 2;
  piso.position.y = -0.02;
  piso.receiveShadow = true;
  cena.add(piso);

  const escala = projeto.escala_metros_por_pixel || ESCALA_PADRAO;
  let larguraMundo = 40;
  let profundidadeMundo = 30;

  // ------------------------------------------------------------ planta baixa
  if (projeto.imagem) {
    const textura = await new THREE.TextureLoader().loadAsync(
      `/api/v1/mapas/${planta}/imagem?_=${Date.now()}`,
      // A textura precisa do header de autorização, então buscamos manualmente.
    ).catch(() => null);

    if (textura) {
      larguraMundo = (projeto.largura_px || 1024) * escala;
      profundidadeMundo = (projeto.altura_px || 768) * escala;
      textura.colorSpace = THREE.SRGBColorSpace;

      const plano = new THREE.Mesh(
        new THREE.PlaneGeometry(larguraMundo, profundidadeMundo),
        new THREE.MeshStandardMaterial({ map: textura, roughness: 0.95 }),
      );
      plano.rotation.x = -Math.PI / 2;
      plano.receiveShadow = true;
      cena.add(plano);

      camera.position.set(larguraMundo * 0.7, larguraMundo * 0.8, profundidadeMundo * 1.1);
      controles.target.set(0, 0, 0);
    }
  } else {
    // Sem planta: um grid dá a noção de escala para posicionar.
    const grid = new THREE.GridHelper(60, 60, 0x2a3a4a, 0x1e2a36);
    cena.add(grid);
  }

  // ------------------------------------------------------------ marcadores
  /**
   * Um marcador por ativo. A forma distingue o domínio:
   * caixa achatada para computador, cilindro para impressora.
   */
  function criarMarcador(item) {
    const grupo = new THREE.Group();
    const impressora = item.dominio === "impressora";

    const cor = item.status === "manutencao"
      ? 0xf2b01e
      : impressora ? 0x7b5cff : 0x2f9be0;

    const material = new THREE.MeshStandardMaterial({
      color: cor, roughness: 0.45, metalness: 0.25,
    });

    if (impressora) {
      const corpo = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.5, 0.85), material);
      corpo.position.y = 0.45;
      grupo.add(corpo);
      const tampa = new THREE.Mesh(
        new THREE.BoxGeometry(1.0, 0.12, 0.6),
        new THREE.MeshStandardMaterial({ color: 0xdddddd, roughness: 0.6 }),
      );
      tampa.position.set(0, 0.76, -0.05);
      grupo.add(tampa);
    } else {
      const monitor = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.42, 0.07), material);
      monitor.position.y = 0.72;
      grupo.add(monitor);
      const base = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.04, 0.22), material);
      base.position.y = 0.42;
      grupo.add(base);
      const haste = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.28, 0.07), material);
      haste.position.y = 0.56;
      grupo.add(haste);
    }

    grupo.traverse((o) => { if (o.isMesh) { o.castShadow = true; } });
    grupo.userData.ativo = item;
    return grupo;
  }

  function desenharMarcadores() {
    for (const mesh of cena3d.objetos.values()) cena.remove(mesh);
    cena3d.objetos.clear();

    for (const item of dados.posicionados) {
      const g = criarMarcador(item);
      g.position.set(item.x, 0, item.z);
      g.rotation.y = THREE.MathUtils.degToRad(item.rotacao || 0);
      cena.add(g);
      cena3d.objetos.set(item.id, g);
    }
  }

  desenharMarcadores();

  // ------------------------------------------------------------ clique
  const raycaster = new THREE.Raycaster();
  const ponteiro = new THREE.Vector2();

  const planoClique = new THREE.Mesh(
    new THREE.PlaneGeometry(400, 400),
    new THREE.MeshBasicMaterial({ visible: false }),
  );
  planoClique.rotation.x = -Math.PI / 2;
  cena.add(planoClique);

  renderer.domElement.addEventListener("pointerdown", (ev) => {
    const r = renderer.domElement.getBoundingClientRect();
    ponteiro.x = ((ev.clientX - r.left) / r.width) * 2 - 1;
    ponteiro.y = -((ev.clientY - r.top) / r.height) * 2 + 1;
    raycaster.setFromCamera(ponteiro, camera);

    // Modo posicionar: o piso manda.
    if (cena3d.moda === "posicionar" && cena3d.selecionado) {
      const alvo = raycaster.intersectObject(planoClique);
      if (!alvo.length) return;
      const p = alvo[0].point;
      api.patch(`/mapas/ativos/${cena3d.selecionado.id}/posicao`, {
        x: Math.round(p.x * 100) / 100,
        z: Math.round(p.z * 100) / 100,
        rotacao: 0,
      }).then(() => {
        const item = dados.pendentes.find((x) => x.id === cena3d.selecionado.id);
        if (item) {
          dados.pendentes = dados.pendentes.filter((x) => x.id !== item.id);
          dados.posicionados.push({ ...item, x: p.x, z: p.z, rotacao: 0 });
        }
        cena3d.selecionado = null;
        desenharMarcadores();
        desenharLateral();
        atualizarBarra();
        toast("Posicionado");
      }).catch((e) => toast(e.message));
      return;
    }

    // Modo visualizar: clicar num ativo abre a ficha.
    const hits = raycaster.intersectObjects([...cena3d.objetos.values()], true);
    if (!hits.length) return;

    let obj = hits[0].object;
    while (obj && !obj.userData.ativo) obj = obj.parent;
    if (obj?.userData.ativo) abrirAtivo(obj.userData.ativo);
  });

  function abrirAtivo(item) {
    const rotulo = item.patrimonio || item.numero_serie || `#${item.id}`;
    dialog({
      title: rotulo,
      body: el("div", {},
        linhaInfo("Tipo", item.dominio === "impressora" ? "Impressora" : "Computador"),
        linhaInfo("Modelo", item.modelo),
        linhaInfo("Marca", item.marca),
        linhaInfo("Status", item.status),
        linhaInfo("Departamento", item.departamento),
        linhaInfo("Localização", item.localizacao),
        linhaInfo("Hostname", item.hostname),
        linhaInfo("IP", item.ip || item.impressora_ip)),
      actions: [
        { label: "Fechar", variant: "text" },
        { label: "Abrir ficha", variant: "tonal", onClick: () => {
          location.hash = `#/ativos?abrir=${item.id}`;
        } },
      ],
    });
  }

  function linhaInfo(rotulo, valor) {
    if (!valor) return el("span", {});
    return el("div", {
      class: "row between",
      style: "padding:6px 0;border-bottom:1px solid var(--md-sys-color-outline-variant);font-size:13px",
    },
      el("span", { class: "muted" }, rotulo),
      el("span", {}, String(valor)));
  }

  // ------------------------------------------------------------ lateral
  function desenharLateral() {
    lateral.innerHTML = "";

    lateral.append(el("p", {
      class: "muted",
      style: "font-size:12px;margin:0 0 8px",
    }, "Sem posição no mapa"));

    if (!dados.pendentes.length) {
      lateral.append(el("p", { class: "muted", style: "font-size:12.5px" },
        "Todos os ativos desta planta estão posicionados."));
      return;
    }

    for (const item of dados.pendentes) {
      const ativo = item.id === cena3d.selecionado?.id;
      lateral.append(el("button", {
        class: "btn text small",
        style: "width:100%;justify-content:flex-start;text-align:left;"
          + "font-size:12.5px;padding:6px 8px"
          + (ativo ? ";background:var(--md-sys-color-secondary-container)" : ""),
        onclick: () => {
          if (cena3d.moda !== "posicionar") {
            cena3d.moda = "posicionar";
          }
          cena3d.selecionado = item;
          atualizarBarra();
          desenharLateral();
        },
      },
        el("span", { style: "margin-right:6px;opacity:.7" },
          item.dominio === "impressora" ? "🖨" : "🖥"),
        el("span", {}, item.patrimonio || item.numero_serie || `#${item.id}`)));
    }
  }

  desenharLateral();

  // ------------------------------------------------------------ loop
  function animar() {
    requestAnimationFrame(animar);
    controles.update();
    renderer.render(cena, camera);
  }
  animar();

  const redimensionar = () => {
    const l = canvas.clientWidth;
    const a = canvas.clientHeight;
    if (!l || !a) return;
    camera.aspect = l / a;
    camera.updateProjectionMatrix();
    renderer.setSize(l, a);
  };
  window.addEventListener("resize", redimensionar);

  // ------------------------------------------------------------ planta baixa
  function abrirPlantas(plantaId, proj) {
    const entrada = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp" });
    const campoLargura = el("input", {
      class: "field", type: "number", min: "100", max: "20000",
      value: String(proj.largura_px || 1024), style: "width:110px",
    });
    const campoAltura = el("input", {
      class: "field", type: "number", min: "100", max: "20000",
      value: String(proj.altura_px || 768), style: "width:110px",
    });
    const campoEscala = el("input", {
      class: "field", type: "number", step: "0.001", min: "0.001", max: "5",
      value: String(proj.escala_metros_por_pixel || ESCALA_PADRAO), style: "width:130px",
    });

    dialog({
      title: "Planta baixa",
      body: el("div", {},
        el("p", { class: "muted", style: "margin:0 0 12px;font-size:12.5px" },
          "Envie a planta como PNG ou JPG. Informe as dimensões em pixels da "
          + "imagem e quantos metros vale um pixel — é o que permite medir "
          + "distâncias no mapa."),
        el("div", { class: "field" }, el("label", {}, "Imagem"), entrada),
        el("div", { class: "row", style: "gap:10px" },
          el("div", { class: "field" }, el("label", {}, "Largura (px)"), campoLargura),
          el("div", { class: "field" }, el("label", {}, "Altura (px)"), campoAltura),
          el("div", { class: "field" }, el("label", {}, "m / pixel"), campoEscala))),
      actions: [
        { label: "Cancelar", variant: "text" },
        { label: "Salvar", variant: "tonal", onClick: async () => {
          try {
            await api.put(`/mapas/${plantaId}`, {
              largura_px: Number(campoLargura.value),
              altura_px: Number(campoAltura.value),
              escala_metros_por_pixel: Number(campoEscala.value),
            });

            const arquivo = entrada.files?.[0];
            if (arquivo) {
              const fd = new FormData();
              fd.append("arquivo", arquivo);
              await api.postForm(`/mapas/${plantaId}/imagem`, fd);
            }

            toast("Planta salva");
            renderMapa(root);
          } catch (e) {
            mostrarErro(e);
          }
        } },
      ],
    });
  }

  ctx.limpar = () => {
    window.removeEventListener("resize", redimensionar);
    renderer.dispose();
  };
}
