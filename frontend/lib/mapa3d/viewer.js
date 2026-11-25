/* Cena 3D, interação, ferramentas e navegação ----------------------------- */

import * as THREE from '../three.module.js';
import { OrbitControls } from '../addons/OrbitControls.js';
import { RoomEnvironment } from '../addons/RoomEnvironment.js';
import { Emitter, clamp, deg2rad, easeInOutCubic, fmt, nextFrame, roundTo } from './util.js';
import { EQUIPMENT_TYPES, categoryOf, getType, statusOf } from './catalog.js';
import { buildModel, createSelectionRing } from './models.js';

const ACCENT = '#22d3ee';

function disposeGeometries(root) {
  root.traverse((o) => {
    if ((o.isMesh || o.isLine || o.isLineSegments) && !o.geometry?.userData?.shared) o.geometry?.dispose?.();
    if (o.isSprite) {
      o.material?.map?.dispose?.();
      o.material?.dispose?.();
    }
  });
}

function disposeMaterials(root) {
  root.traverse((o) => {
    if (o.isMesh && o.material && !o.material.userData?.shared) {
      o.material.dispose?.();
    }
  });
}

export class Viewer extends Emitter {
  constructor(container, canvas, store, { thumbnails = true, editable = true, showPlaceholder = true } = {}) {
    super();
    this.container = container;
    this.canvas = canvas;
    this.store = store;
    this.editable = editable;
    this.thumbnailsEnabled = thumbnails;
    this.showPlaceholder = showPlaceholder;
    this.equipmentFilter = null;
    this._events = new AbortController();
    this._subscriptions = [];
    this.mode = '3d';
    this.tool = 'select';
    this.placementType = null;
    this.plan = null;
    this.planW = 40;
    this.planH = 28;
    this.planTexture = null;
    this.planTextureSource = null;
    this.planToken = 0;
    this.items = new Map();
    this.pickables = [];
    this.wallMeshes = [];
    this.wallMap = new Map();
    this.selected = null;
    this.hovered = null;
    this.drag = null;
    this.down = null;
    this.calibration = null;
    this.measurePoints = [];
    this.wallDraft = null;
    this._tween = null;
    this._walkKeys = new Set();
    this._walkYaw = 0;
    this._walkPitch = 0;
    this._locked = false;
    this._lastCoord = { x: null, z: null };
    this._coordTimer = 0;
    this._labelClock = 0;
    this._labelsEnabled = true;
    this.thumbnails = new Map();
    this._thumbsStarted = false;
    this._disposed = false;
    this._hasFitted = false;
    this._savedPersp = null;
    this._walkPos = new THREE.Vector3();
    this._clock = new THREE.Clock();
    this._raycaster = new THREE.Raycaster();
    this._ndc = new THREE.Vector2();
    this._floorPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    this._tmpVec = new THREE.Vector3();
    this._tmpVec2 = new THREE.Vector3();
    this._walkCollisionPoint = new THREE.Vector3();
  }

  /* ======================= inicialização ======================= */

  init() {
    const width = this.container.clientWidth || 1;
    const height = this.container.clientHeight || 1;

    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      preserveDrawingBuffer: true,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(width, height, false);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x060a12);
    this.scene.fog = new THREE.Fog(0x060a12, 75, 240);

    this.camera = new THREE.PerspectiveCamera(50, width / height, 0.05, 500);
    this.camera.position.set(30, 32, 38);
    this.camera.lookAt(0, 0, 0);

    this.topCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 500);
    this.topCamera.up.set(0, 0, -1);
    this.topCamera.position.set(0, 100, 0.001);
    this.topCamera.lookAt(0, 0, 0);

    this.orbit = new OrbitControls(this.camera, this.canvas);
    this.orbit.target.set(0, 0.4, 0);
    this.orbit.enableDamping = true;
    this.orbit.dampingFactor = 0.075;
    this.orbit.minDistance = 1.5;
    this.orbit.maxDistance = 190;
    this.orbit.maxPolarAngle = Math.PI / 2 - 0.035;
    this.orbit.screenSpacePanning = false;
    this.orbit.zoomSpeed = 1.6;
    this.orbit.zoomToCursor = true;
    this.orbit.panSpeed = 0.9;
    this.orbit.addEventListener('start', () => { this._tween = null; });
    this.orbit.update();

    this.orbitTop = new OrbitControls(this.topCamera, this.canvas);
    this.orbitTop.enableRotate = false;
    this.orbitTop.enableDamping = true;
    this.orbitTop.dampingFactor = 0.1;
    this.orbitTop.screenSpacePanning = true;
    this.orbitTop.zoomSpeed = 1.6;
    this.orbitTop.zoomToCursor = true;
    this.orbitTop.minZoom = 1 / 3;
    this.orbitTop.touches.ONE = THREE.TOUCH.PAN;
    this.orbitTop.enabled = false;
    this.orbitTop.target.set(0, 0, 0);
    this.orbitTop.update();

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    try {
      this.envRT = pmrem.fromScene(new RoomEnvironment(), 0.04);
      this.scene.environment = this.envRT.texture;
    } catch (err) {
      console.warn('[Mapa3D] ambiente PBR indisponível', err);
    }
    pmrem.dispose();

    this.hemi = new THREE.HemisphereLight(0xbfdbfe, 0x0b1220, 0.45);
    this.scene.add(this.hemi);

    this.keyLight = new THREE.DirectionalLight(0xfff7ed, 1.7);
    this.keyLight.position.set(22, 36, 18);
    this.keyLight.castShadow = true;
    this.keyLight.shadow.mapSize.set(2048, 2048);
    this.keyLight.shadow.camera.near = 0.5;
    this.keyLight.shadow.camera.far = 160;
    this.keyLight.shadow.bias = -0.00035;
    this.keyLight.shadow.normalBias = 0.035;
    this.scene.add(this.keyLight);
    this.scene.add(this.keyLight.target);

    this.fillLight = new THREE.DirectionalLight(0x38bdf8, 0.75);
    this.fillLight.position.set(-26, 16, -18);
    this.scene.add(this.fillLight);

    this.rimLight = new THREE.DirectionalLight(0x34d399, 0.4);
    this.rimLight.position.set(12, 10, -30);
    this.scene.add(this.rimLight);

    // Piso geral
    const groundMat = new THREE.MeshStandardMaterial({ color: 0x070b13, roughness: 0.97, metalness: 0 });
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.17;
    ground.receiveShadow = true;
    this.scene.add(ground);
    this.ground = ground;

    this.worldGrid = new THREE.GridHelper(240, 120, 0x1e293b, 0x0f172a);
    this.worldGrid.position.y = -0.16;
    this.worldGrid.material.transparent = true;
    this.worldGrid.material.opacity = 0.32;
    this.worldGrid.material.depthWrite = false;
    this.scene.add(this.worldGrid);

    this.floorGroup = new THREE.Group();
    this.wallsGroup = new THREE.Group();
    this.equipmentGroup = new THREE.Group();
    this.guidesGroup = new THREE.Group();
    this.ghostGroup = new THREE.Group();
    this.scene.add(this.floorGroup, this.wallsGroup, this.equipmentGroup, this.guidesGroup, this.ghostGroup);

    this._bindStore();
    this._bindEvents();
    this._resizeObserver = new ResizeObserver(() => this.resize());
    this._resizeObserver.observe(this.container);
    window.addEventListener('resize', () => this.resize(), { signal: this._events.signal });

    this.resize();
    this.compactEquipment = this.store.project.equipment.filter(item => !item.pendente).length > 200;
    this._applySettings(this.store.project.settings);
    this.syncAll();
    this.applyPlan(this.store.project.plan);

    this._loop = this._loop.bind(this);
    this._raf = requestAnimationFrame(this._loop);

    if (this.thumbnailsEnabled) setTimeout(() => this._generateThumbnails(), 180);
    return this;
  }

  _bindStore() {
    const on = (event, callback) => this._subscriptions.push(this.store.on(event, callback));
    on('equipment:add', (item) => this.addItem(item));
    on('equipment:update', ({ item }) => this.updateItem(item));
    on('equipment:remove', ({ id }) => this.removeItem(id));
    on('walls:change', () => this.rebuildWalls());
    on('plan:change', (plan) => this.applyPlan(plan));
    on('settings:change', (settings) => this._applySettings(settings));
    on('sync', () => this.syncAll());
    on('request:select', ({ kind, id }) => {
      if (this.tool !== 'select') this.setTool('select');
      this.select(kind, id, { focus: false });
    });
  }

  _bindEvents() {
    const options = { signal: this._events.signal };
    this.canvas.addEventListener('pointerdown', (e) => this._onPointerDown(e), options);
    this.canvas.addEventListener('pointermove', (e) => this._onPointerMove(e), options);
    this.canvas.addEventListener('pointerup', (e) => this._onPointerUp(e), options);
    this.canvas.addEventListener('pointerleave', () => this._onPointerLeave(), options);
    this.canvas.addEventListener('dblclick', () => {
      if (this.tool === 'wall') this.finishWall();
    }, options);
    this.canvas.addEventListener('click', () => {
      if (this.mode === 'walk' && document.pointerLockElement !== this.canvas) this.requestWalkLock();
    }, options);
    this.canvas.addEventListener('contextmenu', (e) => e.preventDefault(), options);

    this._onKeyDown = (e) => {
      if (this.mode !== 'walk') return;
      if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight'].includes(e.code)) {
        this._walkKeys.add(e.code);
        if (e.code.startsWith('Arrow')) e.preventDefault();
      }
    };
    this._onKeyUp = (e) => this._walkKeys.delete(e.code);
    document.addEventListener('keydown', this._onKeyDown, options);
    document.addEventListener('keyup', this._onKeyUp, options);

    document.addEventListener('pointerlockchange', () => {
      this._locked = document.pointerLockElement === this.canvas;
      this.emit('walk:locked', this._locked);
    }, options);
    document.addEventListener('mousemove', (e) => {
      if (this.mode !== 'walk' || !this._locked) return;
      this._walkYaw -= e.movementX * 0.0022;
      this._walkPitch = clamp(this._walkPitch - e.movementY * 0.0022, -1.35, 1.35);
    }, options);
  }

  resize() {
    if (!this.renderer) return;
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.updateTopFrustum();
    this.emit('resize');
  }

  /* ======================= planta ======================= */

  async applyPlan(plan) {
    const token = ++this.planToken;
    this._savedPersp = null;
    this.plan = plan || null;
    this.planW = plan ? plan.widthM : 40;
    this.planH = plan ? plan.heightM : 28;
    this.topViewHeight = null;
    this.fitAll({ animate: !!plan });

    if (!plan) {
      this.planTexture?.dispose();
      this.planTexture = null;
      this.planTextureSource = null;
      this._buildPlaceholder();
      this.updateShadowBounds();
      this.emit('plan:ready', null);
      return;
    }

    let texture = this.planTexture;
    try {
      if (!texture || this.planTextureSource !== plan.dataUrl) {
        texture = await new Promise((resolve, reject) => {
          new THREE.TextureLoader().load(
            plan.dataUrl,
            (tex) => resolve(tex),
            undefined,
            () => reject(new Error('Falha ao carregar a imagem da planta.')),
          );
        });
        if (token !== this.planToken) {
          texture.dispose();
          return;
        }
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
        this.planTexture?.dispose();
        this.planTexture = texture;
        this.planTextureSource = plan.dataUrl;
      }
      this._buildFloor(plan, texture);
      this.updateShadowBounds();
      this.emit('plan:ready', plan);
    } catch (err) {
      if (this._disposed || token !== this.planToken) return;
      console.error('[Mapa3D] planta', err);
      this.emit('error', { message: 'Não foi possível carregar a imagem da planta.' });
      this._buildPlaceholder();
    }
  }

  _aspect() {
    return Math.max(0.2, (this.container.clientWidth || 1) / (this.container.clientHeight || 1));
  }

  _clearFloor() {
    for (const child of [...this.floorGroup.children]) {
      disposeGeometries(child);
      disposeMaterials(child);
      this.floorGroup.remove(child);
    }
    this.planMesh = null;
    this.floorGrid = null;
    this.placeholderText = null;
  }

  _buildFloor(plan, texture) {
    this._clearFloor();
    const W = plan.widthM;
    const H = plan.heightM;

    const slabMat = new THREE.MeshStandardMaterial({ color: 0x0b1320, roughness: 0.92, metalness: 0.05 });
    const slab = new THREE.Mesh(new THREE.BoxGeometry(W + 0.9, 0.14, H + 0.9), slabMat);
    slab.position.y = -0.075;
    slab.receiveShadow = true;
    this.floorGroup.add(slab);

    const mat = new THREE.MeshBasicMaterial({
      map: texture,
      toneMapped: false,
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(W, H), mat);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = 0.004;
    mesh.receiveShadow = false;
    mesh.name = 'planta';
    this.floorGroup.add(mesh);
    this.planMesh = mesh;

    // Sombra suave dos equipamentos sobre a planta, sem lavar as cores do PDF.
    const shadowCatcher = new THREE.Mesh(
      new THREE.PlaneGeometry(W, H),
      new THREE.ShadowMaterial({ color: 0x050a12, opacity: 0.32, transparent: true, depthWrite: false }),
    );
    shadowCatcher.rotation.x = -Math.PI / 2;
    shadowCatcher.position.y = 0.007;
    shadowCatcher.receiveShadow = true;
    shadowCatcher.renderOrder = 1;
    this.floorGroup.add(shadowCatcher);

    const borderGeo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-W / 2, 0.02, -H / 2),
      new THREE.Vector3(W / 2, 0.02, -H / 2),
      new THREE.Vector3(W / 2, 0.02, H / 2),
      new THREE.Vector3(-W / 2, 0.02, H / 2),
      new THREE.Vector3(-W / 2, 0.02, -H / 2),
    ]);
    const border = new THREE.Line(borderGeo, new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.4 }));
    this.floorGroup.add(border);

    this.floorGrid = this._makeGrid(W, H);
    this.floorGrid.visible = !!this.store.project.settings.showGrid;
    this.floorGroup.add(this.floorGrid);
  }

  _buildPlaceholder() {
    this._clearFloor();
    const W = 40;
    const H = 28;
    this.planW = W;
    this.planH = H;
    this.planMesh = null;

    const slabMat = new THREE.MeshStandardMaterial({ color: 0x0a1322, roughness: 0.9, metalness: 0.08 });
    const slab = new THREE.Mesh(new THREE.BoxGeometry(W, 0.14, H), slabMat);
    slab.position.y = -0.07;
    slab.receiveShadow = true;
    this.floorGroup.add(slab);

    const topMat = new THREE.MeshStandardMaterial({ color: 0x0c1727, roughness: 0.95, metalness: 0.02 });
    const top = new THREE.Mesh(new THREE.PlaneGeometry(W, H), topMat);
    top.rotation.x = -Math.PI / 2;
    top.position.y = 0.001;
    top.receiveShadow = true;
    this.floorGroup.add(top);

    const border = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(-W / 2, 0.02, -H / 2),
        new THREE.Vector3(W / 2, 0.02, -H / 2),
        new THREE.Vector3(W / 2, 0.02, H / 2),
        new THREE.Vector3(-W / 2, 0.02, H / 2),
        new THREE.Vector3(-W / 2, 0.02, -H / 2),
      ]),
      new THREE.LineBasicMaterial({ color: 0x22d3ee, transparent: true, opacity: 0.22 }),
    );
    this.floorGroup.add(border);

    this.floorGrid = this._makeGrid(W, H);
    this.floorGrid.visible = !!this.store.project.settings.showGrid;
    this.floorGroup.add(this.floorGrid);

    if (!this.showPlaceholder) return;
    // Texto no piso
    const c = document.createElement('canvas');
    c.width = 1024;
    c.height = 256;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, 1024, 256);
    ctx.strokeStyle = 'rgba(34,211,238,.35)';
    ctx.lineWidth = 2;
    ctx.strokeRect(8, 8, 1008, 240);
    ctx.fillStyle = 'rgba(34,211,238,.65)';
    ctx.font = '600 64px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Importe sua planta baixa', 512, 116);
    ctx.fillStyle = 'rgba(148,163,184,.55)';
    ctx.font = '400 36px "Segoe UI", system-ui, sans-serif';
    ctx.fillText('PDF ou imagem · depois posicione os equipamentos', 512, 178);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false, opacity: 0.9, toneMapped: false });
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(20, 5), mat);
    plane.rotation.x = -Math.PI / 2;
    plane.position.set(0, 0.03, 0);
    plane.renderOrder = 2;
    plane.visible = this.store.project.equipment.length === 0;
    this.placeholderText = plane;
    this.floorGroup.add(plane);
  }

  _makeGrid(W, H) {
    const points = [];
    const step = Math.max(1, Math.ceil(Math.max(W, H) / 90));
    const x0 = -W / 2;
    const x1 = W / 2;
    const z0 = -H / 2;
    const z1 = H / 2;
    for (let x = Math.ceil(x0 / step) * step; x <= x1 + 1e-6; x += step) {
      points.push(x, 0.012, z0, x, 0.012, z1);
    }
    for (let z = Math.ceil(z0 / step) * step; z <= z1 + 1e-6; z += step) {
      points.push(x0, 0.012, z, x1, 0.012, z);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
    const mat = new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.13, depthWrite: false });
    const grid = new THREE.LineSegments(geo, mat);
    grid.renderOrder = 1;
    return grid;
  }

  updateShadowBounds() {
    if (!this.keyLight) return;
    const max = Math.max(this.planW, this.planH, 12);
    const size = max * 0.82;
    const cam = this.keyLight.shadow.camera;
    cam.left = -size;
    cam.right = size;
    cam.top = size;
    cam.bottom = -size;
    cam.near = 0.5;
    cam.far = max * 6;
    cam.updateProjectionMatrix();
    this.keyLight.position.set(max * 0.55, max * 1.55, max * 0.75);
    this.keyLight.target.position.set(0, 0, 0);
    this.keyLight.target.updateMatrixWorld();
  }

  /* ======================= sincronização ======================= */

  syncAll() {
    const previous = this.selected ? { ...this.selected } : null;
    for (const id of [...this.items.keys()]) this.removeItem(id, { silent: true });
    this.selected = null;
    this.wallMap.clear();
    this.wallMeshes = [];
    this.rebuildWalls();
    for (const item of this.store.project.equipment) this.addItem(item);
    this.pickables = [];
    for (const rec of this.items.values()) {
      rec.model.traverse((o) => {
        if (o.isMesh) this.pickables.push(o);
      });
    }
    this._applyLabelVisibility();
    if (previous) {
      const still = previous.kind === 'equipment' ? this.items.has(previous.id) : this.wallMap.has(previous.id);
      if (still) {
        this.select(previous.kind, previous.id, { focus: false, silent: true });
      } else {
        this.emit('selection', { kind: null, id: null, item: null });
      }
    }
    this.emit('scene:sync');
  }

  addItem(item) {
    if (!item || item.pendente || this.items.has(item.id)) return;
    const type = getType(item.type);
    const category = categoryOf(item.type);
    const group = new THREE.Group();
    group.name = `equip:${item.id}`;
    group.visible = !this.equipmentFilter || this.equipmentFilter.has(item.id);
    group.userData.equipmentId = item.id;

    const model = this.compactEquipment ? this._buildMapPin(item) : buildModel(item.type);
    model.scale.setScalar(item.scale || 1);
    model.traverse((o) => {
      if (o.isMesh) {
        o.userData.equipmentId = item.id;
        o.castShadow = true;
        o.receiveShadow = true;
      }
    });
    group.add(model);

    group.position.set(item.x, item.elevation || 0, item.z);
    group.rotation.y = deg2rad(item.rotation || 0);

    const label = this.compactEquipment ? null : this.makeLabel(item, model);
    if (label) group.add(label);

    const ring = createSelectionRing(item.mapColor || category.color);
    ring.raycast = () => {};
    ring.position.y = -(item.elevation || 0) + 0.025;
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const baseScale = Math.max(1.1, Math.max(size.x, size.z) * 1.35);
    ring.scale.setScalar(baseScale);
    ring.visible = false;
    group.add(ring);

    this.equipmentGroup.add(group);
    this.items.set(item.id, { group, model, label, ring, item, baseScale, labelY: label?.position.y });
    if (!this.plan && this.placeholderText) this.placeholderText.visible = false;
    if (label && this.store.project.settings.showLabels && this.mode !== 'walk') label.visible = true;
    if (this.selected?.kind === 'equipment' && this.selected.id === item.id) ring.visible = true;
    this.emit('item:added', item);
  }

  updateItem(item) {
    if (item.pendente) {
      this.removeItem(item.id);
      return;
    }
    const rec = this.items.get(item.id);
    if (!rec) {
      this.addItem(item);
      return;
    }
    rec.item = item;
    rec.group.position.set(item.x, item.elevation || 0, item.z);
    rec.group.rotation.y = deg2rad(item.rotation || 0);
    rec.model.scale.setScalar(item.scale || 1);
    rec.ring.position.y = -(item.elevation || 0) + 0.025;

    // recria o rótulo (nome/status/setor podem ter mudado)
    if (rec.label && !this.compactEquipment) {
      const oldLabel = rec.label;
      const label = this.makeLabel(item, rec.model);
      rec.group.add(label);
      rec.label = label;
      oldLabel.parent?.remove(oldLabel);
      oldLabel.material?.map?.dispose?.();
      oldLabel.material?.dispose?.();
      rec.labelY = label.position.y;
    }
    this._applyLabelVisibility();

    const category = categoryOf(item.type);
    rec.ring.material.color.set(item.mapColor || category.color);
  }

  _buildMapPin(item) {
    if (!this.pinGeometry) {
      this.pinGeometry = new THREE.CylinderGeometry(0.17, 0.22, 0.45, 8);
      this.pinGeometry.userData.shared = true;
      this.pinMaterials = new Map();
    }
    const color = item.mapColor || categoryOf(item.type).color;
    if (!this.pinMaterials.has(color)) {
      this.pinMaterials.set(color, new THREE.MeshBasicMaterial({ color }));
    }
    const pin = new THREE.Mesh(this.pinGeometry, this.pinMaterials.get(color));
    pin.position.y = 0.22;
    const model = new THREE.Group();
    model.add(pin);
    return model;
  }

  _clearCompactLabel() {
    if (!this.compactEquipment || this.selected?.kind !== 'equipment') return;
    const rec = this.items.get(this.selected.id);
    if (!rec?.label) return;
    rec.group.remove(rec.label);
    rec.label.material?.map?.dispose?.();
    rec.label.material?.dispose?.();
    rec.label = null;
  }

  setEquipmentFilter(ids) {
    this.equipmentFilter = ids;
    for (const [id, rec] of this.items) rec.group.visible = !ids || ids.has(id);
    this._applyLabelVisibility();
  }

  removeItem(id, { silent = false } = {}) {
    const rec = this.items.get(id);
    if (!rec) return;
    this.items.delete(id);
    this.equipmentGroup.remove(rec.group);
    disposeGeometries(rec.group);
    if (this.selected?.kind === 'equipment' && this.selected.id === id) {
      this.selected = null;
      if (!silent) this.emit('selection', { kind: null, id: null, item: null });
    }
    this.hovered = null;
    if (!this.plan && this.placeholderText && this.items.size === 0) this.placeholderText.visible = true;
    this.emit('item:removed', id);
  }

  /* ======================= rótulos ======================= */

  makeLabel(item, model = null) {
    const type = getType(item.type);
    const category = categoryOf(item.type);
    const status = statusOf(item.status);
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 200;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, 640, 200);

    const x = 8;
    const y = 10;
    const w = 624;
    const h = 180;
    const r = 22;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
    ctx.fillStyle = 'rgba(6, 12, 22, 0.9)';
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.32)';
    ctx.stroke();

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
    ctx.clip();
    ctx.fillStyle = item.mapColor || category.color;
    ctx.fillRect(x, y, 7, h);
    ctx.restore();

    ctx.beginPath();
    ctx.arc(44, 54, 9, 0, Math.PI * 2);
    ctx.fillStyle = status.color;
    ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,.25)';
    ctx.lineWidth = 2;
    ctx.stroke();

    let name = String(item.name || type.label);
    ctx.font = '600 34px "Segoe UI", system-ui, sans-serif';
    while (ctx.measureText(name).width > 440 && name.length > 4) name = name.slice(0, -2);
    if (name !== item.name) name = name.trimEnd() + '…';
    ctx.fillStyle = '#f1f5f9';
    ctx.textBaseline = 'middle';
    ctx.fillText(name, 66, 54);

    ctx.font = '600 18px "Segoe UI", system-ui, sans-serif';
    ctx.fillStyle = status.color;
    const statusText = (item.statusLabel || status.label).toUpperCase();
    ctx.textAlign = 'right';
    ctx.fillText(statusText, 610, 54);
    ctx.textAlign = 'left';

    const subParts = [];
    if (item.tag) subParts.push(item.tag);
    if (item.sector) subParts.push(item.sector);
    if (!subParts.length) subParts.push(type.label);
    let sub = subParts.join('  ·  ');
    ctx.font = '400 21px "Segoe UI", system-ui, sans-serif';
    ctx.fillStyle = 'rgba(148, 163, 184, 0.9)';
    while (ctx.measureText(sub).width > 530 && sub.length > 6) sub = sub.slice(0, -2);
    if (sub.length < subParts.join('  ·  ').length) sub = sub.trimEnd() + '…';
    ctx.fillText(sub, 66, 104);

    ctx.font = '400 17px "Segoe UI", system-ui, sans-serif';
    ctx.fillStyle = 'rgba(100, 116, 139, 0.9)';
    const extra = item.ip ? `IP ${item.ip}` : type.desc;
    ctx.fillText(extra, 66, 144);

    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 4;
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false, toneMapped: false });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(4.05, 1.266, 1);
    sprite.center.set(0.5, 0.5);
    sprite.renderOrder = 6;
    sprite.raycast = () => {};

    const box = new THREE.Box3().setFromObject(model || new THREE.Group());
    let top = box.max.y;
    let bottom = box.min.y;
    if (!Number.isFinite(top) || box.isEmpty()) {
      top = (getType(item.type).dims || [1, 1, 1])[1];
      bottom = 0;
    }
    const below = !!type.labelBelow;
    const baseWorld = below ? Math.min(bottom, 0) : Math.max(top, 0);
    sprite.position.set(0, below ? baseWorld - 0.75 : baseWorld + 0.82, 0);
    sprite.visible = false;
    return sprite;
  }

  _applyLabelVisibility() {
    this._updateLabels(true);
  }

  _updateLabels(force = false) {
    const enabled = !!this.store.project.settings.showLabels && this.mode !== 'walk';
    this._labelsEnabled = enabled;
    const cam = this._activeCamera();
    const vw = this.container.clientWidth || 1;
    const vh = this.container.clientHeight || 1;
    if (!enabled) {
      for (const rec of this.items.values()) if (rec.label) rec.label.visible = false;
      return;
    }
    const perspective = this.mode !== 'top';
    const tanHalfFov = Math.tan(deg2rad(this.camera.fov / 2));
    const compact = vw < 700;
    const labelPx = compact ? 30 : vw < 1000 ? 38 : 44;
    const topLabelPx = compact ? 27 : 38;
    const items = [];
    const world = new THREE.Vector3();
    const ndc = new THREE.Vector3();

    for (const [id, rec] of this.items) {
      const label = rec.label;
      if (!label) continue;
      if (!rec.group.visible) {
        label.visible = false;
        continue;
      }
      label.getWorldPosition(world);
      ndc.copy(world).project(cam);
      if (ndc.z < -1 || ndc.z > 1) {
        label.visible = false;
        continue;
      }
      let pxH;
      let distance = 0;
      if (perspective) {
        distance = cam.position.distanceTo(world);
        pxH = labelPx;
        const worldH = pxH * ((2 * distance * tanHalfFov) / vh);
        const h = clamp(worldH, 0.32, 3.6);
        label.scale.set(h * 3.2, h, 1);
      } else {
        const worldH = topLabelPx * ((cam.top - cam.bottom) / vh / cam.zoom);
        const h = clamp(worldH, 0.3, 6);
        label.scale.set(h * 3.2, h, 1);
        pxH = topLabelPx;
      }
      const pxW = pxH * 3.2;
      const sx = (ndc.x * 0.5 + 0.5) * vw;
      const sy = (-ndc.y * 0.5 + 0.5) * vh;
      const selected = this.selected?.kind === 'equipment' && this.selected.id === id;
      const priority = selected ? 0 : this.hovered === id ? 1 : rec.item.status === 'offline' || rec.item.status === 'manutencao' ? 2 : 3;
      items.push({
        label,
        sx,
        sy,
        w: pxW,
        h: pxH,
        priority,
        centerDist: Math.hypot(sx - vw / 2, sy - vh / 2),
        distance,
      });
    }

    items.sort((a, b) => a.priority - b.priority || a.centerDist - b.centerDist);
    const placed = [];
    for (const it of items) {
      const left = it.sx - it.w / 2;
      const top = it.sy - it.h / 2;
      const right = it.sx + it.w / 2;
      const bottom = it.sy + it.h / 2;
      let visible = right > -8 && left < vw + 8 && bottom > -8 && top < vh + 8;
      if (visible && it.priority > 0) {
        visible = !placed.some(
          (r) => left < r.right + 5 && right > r.left - 5 && top < r.bottom + 5 && bottom > r.top - 5,
        );
      }
      it.label.visible = visible;
      if (visible) placed.push({ left, right, top, bottom });
    }
  }

  /* ======================= paredes ======================= */

  rebuildWalls() {
    for (const child of [...this.wallsGroup.children]) {
      disposeGeometries(child);
      disposeMaterials(child);
      this.wallsGroup.remove(child);
    }
    this.wallMeshes = [];
    this.wallMap.clear();

    for (const wall of this.store.project.walls) {
      const meshes = [];
      for (let i = 0; i < wall.points.length - 1; i++) {
        const [x1, z1] = wall.points[i];
        const [x2, z2] = wall.points[i + 1];
        const dx = x2 - x1;
        const dz = z2 - z1;
        const len = Math.hypot(dx, dz);
        if (len < 0.01) continue;
        const mat = new THREE.MeshStandardMaterial({ color: 0x4b5d73, roughness: 0.8, metalness: 0.12 });
        const mesh = new THREE.Mesh(new THREE.BoxGeometry(len + wall.thickness, wall.height, wall.thickness), mat);
        mesh.position.set((x1 + x2) / 2, wall.height / 2, (z1 + z2) / 2);
        mesh.rotation.y = -Math.atan2(dz, dx);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.userData.wallId = wall.id;
        this.wallsGroup.add(mesh);
        meshes.push(mesh);
        this.wallMeshes.push(mesh);

        const capMat = new THREE.MeshStandardMaterial({ color: 0xa7b6c9, roughness: 0.55, metalness: 0.25 });
        const cap = new THREE.Mesh(
          new THREE.BoxGeometry(len + wall.thickness + 0.02, 0.055, wall.thickness + 0.025),
          capMat,
        );
        cap.position.set((x1 + x2) / 2, wall.height + 0.027, (z1 + z2) / 2);
        cap.rotation.y = -Math.atan2(dz, dx);
        cap.castShadow = true;
        cap.userData.wallId = wall.id;
        this.wallsGroup.add(cap);
        meshes.push(cap);
        this.wallMeshes.push(cap);
      }
      this.wallMap.set(wall.id, { wall, meshes });
    }
    if (this.selected?.kind === 'wall' && !this.wallMap.has(this.selected.id)) {
      this.selected = null;
      this.emit('selection', { kind: null, id: null, item: null });
    }
    if (this.selected?.kind === 'wall') this._highlightWall(this.selected.id);
  }

  _highlightWall(id) {
    for (const [wallId, rec] of this.wallMap) {
      const active = wallId === id;
      for (const mesh of rec.meshes) {
        mesh.material.emissive.set(active ? 0x0ea5e9 : 0x000000);
        mesh.material.emissiveIntensity = active ? 0.35 : 0;
      }
    }
  }

  /* ======================= seleção ======================= */

  select(kind, id, { focus = false, silent = false } = {}) {
    this._clearCompactLabel();
    if (!kind || !id) {
      this.selected = null;
      for (const rec of this.items.values()) rec.ring.visible = false;
      this._highlightWall(null);
      if (!silent) this.emit('selection', { kind: null, id: null, item: null });
      return;
    }
    if (this.selected?.kind === 'equipment') {
      const prev = this.items.get(this.selected.id);
      if (prev) prev.ring.visible = false;
    }
    this._highlightWall(null);

    if (kind === 'equipment') {
      const rec = this.items.get(id);
      if (!rec) return;
      rec.ring.visible = true;
      this.selected = { kind, id };
      if (this.compactEquipment) {
        rec.label = this.makeLabel(rec.item, rec.model);
        rec.group.add(rec.label);
      }
      if (focus) this.focusOn(id);
      if (!silent) this.emit('selection', { kind, id, item: rec.item });
    } else if (kind === 'wall') {
      const rec = this.wallMap.get(id);
      if (!rec) return;
      this.selected = { kind, id };
      this._highlightWall(id);
      if (focus) this.focusWall(id);
      if (!silent) this.emit('selection', { kind, id, item: rec.wall });
    }
  }

  clearSelection() {
    this.select(null, null);
  }

  focusOn(id) {
    const rec = this.items.get(id);
    if (!rec) return;
    const item = rec.item;
    const target = new THREE.Vector3(item.x, (item.elevation || 0) + 0.5, item.z);
    const dist = 10;
    const pos = target.clone().add(new THREE.Vector3(0.5, 1.25, 0.72).normalize().multiplyScalar(dist));
    if (this.mode === 'top') {
      this.orbitTop.target.copy(target);
      this.topCamera.position.set(target.x, 100, target.z + 0.001);
      this.orbitTop.update();
    } else {
      this._flyTo(pos, target, 650);
    }
  }

  focusWall(id) {
    const rec = this.wallMap.get(id);
    if (!rec) return;
    const pts = rec.wall.points;
    const mid = pts[Math.floor(pts.length / 2)];
    const target = new THREE.Vector3(mid[0], 1.2, mid[1]);
    const pos = target.clone().add(new THREE.Vector3(0.8, 0.7, 1).normalize().multiplyScalar(10));
    if (this.mode === 'top') {
      this.orbitTop.target.copy(target);
      this.topCamera.position.set(target.x, 100, target.z + 0.001);
      this.orbitTop.update();
    } else {
      this._flyTo(pos, target, 650);
    }
  }

  /* ======================= câmeras / modos ======================= */

  _flyTo(pos, target, duration = 700) {
    if (this.mode === 'top') {
      this.orbitTop.target.copy(target);
      this.updateTopFrustum();
      return;
    }
    this._tween = {
      fromPos: this.camera.position.clone(),
      toPos: pos.clone(),
      fromTarget: this.orbit.target.clone(),
      toTarget: target.clone(),
      elapsed: 0,
      duration: Math.max(1, duration),
    };
  }

  _computeFitDistance(w, h) {
    const aspect = this._aspect();
    const camera = new THREE.PerspectiveCamera(this.camera.fov, aspect, 0.1, 2000);
    const dir = new THREE.Vector3(0.72, 0.92, 0.82).normalize();
    const corners = [
      new THREE.Vector3(-w / 2, 0, -h / 2),
      new THREE.Vector3(w / 2, 0, -h / 2),
      new THREE.Vector3(w / 2, 0, h / 2),
      new THREE.Vector3(-w / 2, 0, h / 2),
    ];
    let lo = 1;
    let hi = Math.max(w, h, 10) * 8;
    const margin = aspect < 0.8 ? 0.94 : 0.87;
    for (let i = 0; i < 26; i++) {
      const mid = (lo + hi) / 2;
      camera.position.copy(dir).multiplyScalar(mid);
      camera.lookAt(0, 0, 0);
      camera.updateMatrixWorld(true);
      camera.updateProjectionMatrix();
      const fits = corners.every((corner) => {
        const p = corner.clone().project(camera);
        return p.z < 1 && Math.abs(p.x) <= margin && Math.abs(p.y) <= margin;
      });
      if (fits) hi = mid;
      else lo = mid;
    }
    return hi * 1.02;
  }

  fitAll({ animate = true } = {}) {
    let minX = -this.planW / 2, maxX = this.planW / 2;
    let minZ = -this.planH / 2, maxZ = this.planH / 2;
    const incluir = (x, z) => {
      minX = Math.min(minX, x - 2);
      minZ = Math.min(minZ, z - 2);
      maxX = Math.max(maxX, x + 2);
      maxZ = Math.max(maxZ, z + 2);
    };
    for (const { group, item } of this.items.values()) {
      if (group.visible) incluir(item.x, item.z);
    }
    for (const wall of this.store.project.walls) wall.points.forEach(([x, z]) => incluir(x, z));
    const w = Math.max(maxX - minX, 4);
    const h = Math.max(maxZ - minZ, 4);
    const center = new THREE.Vector3((minX + maxX) / 2, 0.4, (minZ + maxZ) / 2);
    const aspect = this._aspect();
    if (this.mode === 'top') {
      this.topViewHeight = Math.max(h, w / aspect) * 1.08;
      this.orbitTop.maxZoom = Math.max(1, this.topViewHeight / 1.5);
      this.topCamera.zoom = 1;
      this.orbitTop.target.copy(center);
      this.topCamera.position.set(center.x, 100, center.z + 0.001);
      this.updateTopFrustum();
      this.orbitTop.update();
      this._hasFitted = true;
      return;
    }
    const dir = new THREE.Vector3(0.72, 0.92, 0.82).normalize();
    const dist = this._computeFitDistance(w, h);
    const pos = center.clone().add(dir.multiplyScalar(dist));
    const shouldAnimate = animate && this._hasFitted;
    if (shouldAnimate) {
      this._flyTo(pos, center, 750);
    } else {
      this._tween = null;
      this.camera.position.copy(pos);
      this.orbit.target.copy(center);
      this.orbit.update();
    }
    this._hasFitted = true;
  }

  updateTopFrustum() {
    if (!this.topCamera) return;
    const aspect = this._aspect();
    const vh = this.topViewHeight || Math.max(this.planH, this.planW / aspect) * 1.08;
    this.topCamera.left = (-vh * aspect) / 2;
    this.topCamera.right = (vh * aspect) / 2;
    this.topCamera.top = vh / 2;
    this.topCamera.bottom = -vh / 2;
    this.topCamera.near = 0.1;
    this.topCamera.far = 600;
    this.topCamera.updateProjectionMatrix();
  }

  setMode(mode) {
    if (!['3d', 'top', 'walk'].includes(mode) || mode === this.mode) return;
    const prev = this.mode;

    if (prev === 'walk' && document.pointerLockElement === this.canvas) {
      document.exitPointerLock?.();
    }
    if (prev === '3d') {
      this._savedPersp = { pos: this.camera.position.clone(), target: this.orbit.target.clone() };
    }

    this.mode = mode;
    this._tween = null;
    this.hovered = null;
    this.emit('hover', { item: null });

    if (mode === '3d') {
      this.orbitTop.enabled = false;
      this.orbit.enabled = true;
      this.camera.fov = 50;
      this.camera.updateProjectionMatrix();
      this.scene.fog = new THREE.Fog(0x060a12, 75, 240);
      if (this._savedPersp) {
        this.camera.position.copy(this._savedPersp.pos);
        this.orbit.target.copy(this._savedPersp.target);
        this.orbit.update();
      } else {
        this.fitAll({ animate: false });
      }
    } else if (mode === 'top') {
      this.orbit.enabled = false;
      this.orbitTop.enabled = true;
      this.scene.fog = null;
      if (this.topViewHeight === null) this.fitAll({ animate: false });
    } else if (mode === 'walk') {
      this.orbit.enabled = false;
      this.orbitTop.enabled = false;
      this.scene.fog = new THREE.Fog(0x060a12, 60, 220);
      this.camera.fov = 72;
      this.camera.updateProjectionMatrix();
      this.camera.rotation.order = 'YXZ';
      this._walkYaw = 0;
      this._walkPitch = -0.04;
      this._walkPos.set(0, 0, Math.max(2, this.planH / 2 - 2));
      this.camera.position.set(this._walkPos.x, 1.68, this._walkPos.z);
      this.camera.rotation.set(this._walkPitch, this._walkYaw, 0);
      this._walkKeys.clear();
    }

    this._applyLabelVisibility();
    this.emit('modechange', mode);
    this.emit('walk:locked', false);
  }

  requestWalkLock() {
    if (this.mode !== 'walk') return;
    try {
      const p = this.canvas.requestPointerLock?.();
      if (p && typeof p.catch === 'function') p.catch(() => {});
    } catch {
      /* alguns navegadores bloqueiam sem gesto */
    }
  }

  exitWalk() {
    if (this.mode !== 'walk') return;
    if (document.pointerLockElement === this.canvas) document.exitPointerLock?.();
    this._walkKeys.clear();
    this.setMode('3d');
  }

  _updateWalk(dt) {
    if (this.mode !== 'walk') return;
    const keys = this._walkKeys;
    const speed = keys.has('ShiftLeft') || keys.has('ShiftRight') ? 7 : 3.6;
    const forward = new THREE.Vector3(-Math.sin(this._walkYaw), 0, -Math.cos(this._walkYaw));
    const right = new THREE.Vector3(Math.cos(this._walkYaw), 0, -Math.sin(this._walkYaw));
    const move = new THREE.Vector3();
    if (keys.has('KeyW') || keys.has('ArrowUp')) move.add(forward);
    if (keys.has('KeyS') || keys.has('ArrowDown')) move.sub(forward);
    if (keys.has('KeyD') || keys.has('ArrowRight')) move.add(right);
    if (keys.has('KeyA') || keys.has('ArrowLeft')) move.sub(right);
    const moving = move.lengthSq() > 0;
    if (moving) {
      move.normalize().multiplyScalar(speed * dt);
      const next = this.camera.position.clone().add(move);
      this._resolveWalkCollision(next);
      const maxX = this.planW / 2 - 0.5;
      const maxZ = this.planH / 2 - 0.5;
      next.x = clamp(next.x, -maxX, maxX);
      next.z = clamp(next.z, -maxZ, maxZ);
      this.camera.position.x = next.x;
      this.camera.position.z = next.z;
    }
    const bob = moving ? Math.sin(this._clock.elapsedTime * 9) * 0.018 : 0;
    this.camera.position.y = 1.68 + bob;
    this.camera.rotation.set(this._walkPitch, this._walkYaw, 0);

    this._coordTimer += dt;
    if (this._coordTimer > 0.12) {
      this._coordTimer = 0;
      this.emit('pointer', { x: this.camera.position.x, z: this.camera.position.z, walking: true });
    }
  }

  _resolveWalkCollision(pos) {
    const radius = 0.42;
    for (const wall of this.store.project.walls) {
      const half = wall.thickness / 2;
      for (let i = 0; i < wall.points.length - 1; i++) {
        const [x1, z1] = wall.points[i];
        const [x2, z2] = wall.points[i + 1];
        const dx = x2 - x1;
        const dz = z2 - z1;
        const lenSq = dx * dx + dz * dz;
        if (lenSq < 1e-6) continue;
        let t = ((pos.x - x1) * dx + (pos.z - z1) * dz) / lenSq;
        t = clamp(t, 0, 1);
        const cx = x1 + dx * t;
        const cz = z1 + dz * t;
        const ox = pos.x - cx;
        const oz = pos.z - cz;
        const dist = Math.hypot(ox, oz);
        const minDist = radius + half;
        if (dist < minDist && dist > 1e-5) {
          pos.x = cx + (ox / dist) * minDist;
          pos.z = cz + (oz / dist) * minDist;
        }
      }
    }
  }

  _activeCamera() {
    return this.mode === 'top' ? this.topCamera : this.camera;
  }

  /* ======================= ferramentas ======================= */

  setTool(tool, opts = {}) {
    if (!['select', 'add', 'calibrate', 'measure', 'wall'].includes(tool)) return;
    const prev = this.tool;
    if (prev === tool && !(tool === 'add' && opts.typeId !== this.placementType)) {
      if (tool !== 'add') return;
    }
    this.tool = tool;
    this.placementType = tool === 'add' ? opts.typeId || this.placementType : null;
    this.hovered = null;
    this.emit('hover', { item: null });

    if (tool !== 'add') this._clearGhost();
    if (tool !== 'calibrate') this.clearCalibration({ keepTool: true });
    if (tool !== 'wall') this.clearWallDraft();
    if (tool === 'add') this._buildGhost(this.placementType);
    if (tool === 'measure') this.clearMeasurements();
    if (tool === 'wall') this.wallDraft = { points: [] };

    this.orbit.enabled = this.mode === '3d';
    this.orbitTop.enabled = this.mode === 'top';
    this.emit('toolchange', { tool, typeId: this.placementType });
  }

  startPlacement(typeId, equipmentId = null) {
    this.placementId = equipmentId;
    this.placementType = typeId;
    this.setTool('add', { typeId });
  }

  _clearGhost() {
    for (const child of [...this.ghostGroup.children]) {
      disposeGeometries(child);
      disposeMaterials(child);
      this.ghostGroup.remove(child);
    }
  }

  _buildGhost(typeId) {
    this._clearGhost();
    if (!typeId) return;
    const type = getType(typeId);
    const group = new THREE.Group();
    const model = buildModel(typeId);
    model.traverse((o) => {
      if (o.isMesh) {
        const cloned = o.material.clone();
        cloned.transparent = true;
        cloned.opacity = 0.42;
        cloned.depthWrite = false;
        cloned.emissive = new THREE.Color('#22d3ee');
        cloned.emissiveIntensity = 0.18;
        o.material = cloned;
        o.castShadow = false;
      }
    });
    group.add(model);
    const ring = createSelectionRing(ACCENT);
    ring.position.y = 0.02;
    ring.scale.setScalar(1.5);
    group.add(ring);
    group.position.y = type.elevation || 0;
    group.visible = false;
    this.ghostGroup.add(group);
    this._ghost = group;
    this.emit('ghost:ready', { typeId });
  }

  _handleAdd(p) {
    if (!this.placementType) return;
    const type = getType(this.placementType);
    const position = {
      type: this.placementType,
      x: this._snap(p.x),
      z: this._snap(p.z),
      elevation: type.elevation || 0,
      rotation: 0,
      sector: '',
    };
    if (Math.max(Math.abs(position.x), Math.abs(position.z)) > 500) {
      this.emit('error', { message: 'Escolha um ponto dentro dos limites do mapa.' });
      return;
    }
    const item = this.placementId
      ? this.store.updateEquipment(this.placementId, { x: position.x, z: position.z, pendente: false })
      : this.store.addEquipment(position);
    if (!item) return;
    this.setTool('select');
    this.select('equipment', item.id, { focus: false });
    this.emit('placed', item);
  }

  startCalibration() {
    this.setTool('calibrate');
    this.calibration = { points: [] };
    this._drawCalibration();
    this.emit('calibration:start');
  }

  clearCalibration({ keepTool = false } = {}) {
    this.calibration = null;
    for (const child of [...this.guidesGroup.children]) {
      if (child.userData.guide === 'calibration') {
        disposeGeometries(child);
        disposeMaterials(child);
        this.guidesGroup.remove(child);
      }
    }
    if (!keepTool && this.tool === 'calibrate') this.setTool('select');
  }

  _handleCalibration(p) {
    if (!this.calibration) this.calibration = { points: [] };
    if (this.calibration.points.length >= 2) this.calibration.points = [];
    this.calibration.points.push([p.x, p.z]);
    this._drawCalibration();
    if (this.calibration.points.length === 2) {
      const [a, b] = this.calibration.points;
      const dist = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (dist < 0.05) {
        this.calibration.points = [a];
        this._drawCalibration();
        return;
      }
      this.calibration.worldDistance = dist;
      this.emit('calibration:ready', { worldDistance: dist });
    }
  }

  _drawCalibration() {
    for (const child of [...this.guidesGroup.children]) {
      if (child.userData.guide === 'calibration') {
        disposeGeometries(child);
        disposeMaterials(child);
        this.guidesGroup.remove(child);
      }
    }
    if (!this.calibration?.points?.length) return;
    const pts = this.calibration.points;
    const group = new THREE.Group();
    group.userData.guide = 'calibration';
    for (const [x, z] of pts) {
      const marker = new THREE.Mesh(new THREE.SphereGeometry(0.12, 12, 8), new THREE.MeshBasicMaterial({ color: 0xfb7185 }));
      marker.position.set(x, 0.12, z);
      marker.raycast = () => {};
      group.add(marker);
      const ring = createSelectionRing('#fb7185');
      ring.position.set(x, 0.03, z);
      ring.scale.setScalar(1.6);
      group.add(ring);
    }
    if (pts.length === 2) {
      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(pts[0][0], 0.05, pts[0][1]),
        new THREE.Vector3(pts[1][0], 0.05, pts[1][1]),
      ]);
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xfb7185, linewidth: 2 }));
      group.add(line);
      const dist = Math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]);
      const label = this._makeTextSprite(`${fmt(dist)} m (escala atual)`, '#fecdd3');
      label.position.set((pts[0][0] + pts[1][0]) / 2, 0.6, (pts[0][1] + pts[1][1]) / 2);
      group.add(label);
    }
    this.guidesGroup.add(group);
    this.emit('calibration:update', { points: pts.length });
  }

  applyCalibration(realMeters) {
    if (!this.calibration?.worldDistance || !(realMeters > 0)) return;
    const ratio = realMeters / this.calibration.worldDistance;
    this.store.scaleBy(ratio);
    this.emit('calibration:apply', { ratio });
    this.clearCalibration({ keepTool: true });
    this.setTool('select');
    this.fitAll({ animate: true });
    this.emit('calibrated', { ratio, meters: realMeters });
  }

  cancelCalibration() {
    this.clearCalibration();
    this.setTool('select');
  }

  startMeasure() {
    this.setTool('measure');
    this.measurePoints = [];
    this.clearMeasurements();
    this.emit('measure:start');
  }

  _handleMeasure(p) {
    this.measurePoints.push([p.x, p.z]);
    if (this.measurePoints.length === 1) {
      this._drawMeasurePoint(this.measurePoints[0]);
      return;
    }
    for (const child of [...this.guidesGroup.children]) {
      if (child.userData.guide === 'measure-temp') {
        disposeGeometries(child);
        disposeMaterials(child);
        this.guidesGroup.remove(child);
      }
    }
    const [a, b] = this.measurePoints;
    const dist = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const group = new THREE.Group();
    group.userData.guide = 'measure';
    const geo = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(a[0], 0.06, a[1]),
      new THREE.Vector3(b[0], 0.06, b[1]),
    ]);
    group.add(new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xa78bfa })));
    for (const [x, z] of [a, b]) {
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.075, 10, 8), new THREE.MeshBasicMaterial({ color: 0xa78bfa }));
      dot.position.set(x, 0.1, z);
      group.add(dot);
    }
    const label = this._makeTextSprite(`${fmt(dist)} m`, '#ddd6fe');
    label.position.set((a[0] + b[0]) / 2, 0.55, (a[1] + b[1]) / 2);
    group.add(label);
    this.guidesGroup.add(group);
    this._measureGroup = group;
    this.measurePoints = [];
    this.emit('measure:add', { distance: dist, total: this.measureCount() + 1 });
  }

  _drawMeasurePoint([x, z]) {
    const dot = new THREE.Mesh(new THREE.SphereGeometry(0.08, 10, 8), new THREE.MeshBasicMaterial({ color: 0xc4b5fd }));
    dot.position.set(x, 0.1, z);
    dot.userData.guide = 'measure-temp';
    this.guidesGroup.add(dot);
  }

  measureCount() {
    return this.guidesGroup.children.filter((c) => c.userData.guide === 'measure').length;
  }

  clearMeasurements() {
    for (const child of [...this.guidesGroup.children]) {
      if (child.userData.guide === 'measure' || child.userData.guide === 'measure-temp') {
        disposeGeometries(child);
        disposeMaterials(child);
        this.guidesGroup.remove(child);
      }
    }
    this.measurePoints = [];
  }

  startWall() {
    this.setTool('wall');
    this.wallDraft = { points: [] };
  }

  _handleWallPoint(p) {
    if (!this.wallDraft) this.wallDraft = { points: [] };
    const pt = [this._snap(p.x), this._snap(p.z)];
    if (this.wallDraft.points.length >= 120 || pt.some(n => Math.abs(n) > 500)) {
      this.emit('error', { message: 'Finalize a parede antes de adicionar novos pontos.' });
      return;
    }
    const last = this.wallDraft.points[this.wallDraft.points.length - 1];
    if (last && Math.hypot(last[0] - pt[0], last[1] - pt[1]) < 0.05) return;
    this.wallDraft.points.push(pt);
    this._drawWallDraft();
    this.emit('wall:point', { count: this.wallDraft.points.length });
  }

  _drawWallDraft(hoverPoint = null) {
    for (const child of [...this.guidesGroup.children]) {
      if (child.userData.guide === 'wall') {
        disposeGeometries(child);
        disposeMaterials(child);
        this.guidesGroup.remove(child);
      }
    }
    if (!this.wallDraft?.points?.length) return;
    const pts = this.wallDraft.points;
    const group = new THREE.Group();
    group.userData.guide = 'wall';
    const linePts = pts.map(([x, z]) => new THREE.Vector3(x, 0.06, z));
    if (hoverPoint) linePts.push(new THREE.Vector3(this._snap(hoverPoint.x), 0.06, this._snap(hoverPoint.z)));
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(linePts),
      new THREE.LineBasicMaterial({ color: 0xfbbf24 }),
    );
    group.add(line);
    for (const [x, z] of pts) {
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.07, 8, 6), new THREE.MeshBasicMaterial({ color: 0xfbbf24 }));
      dot.position.set(x, 0.1, z);
      group.add(dot);
    }
    this.guidesGroup.add(group);
  }

  finishWall() {
    if (!this.wallDraft || this.wallDraft.points.length < 2) return;
    const pts = [...this.wallDraft.points];
    const dedup = [];
    for (const p of pts) {
      const last = dedup[dedup.length - 1];
      if (last && Math.hypot(last[0] - p[0], last[1] - p[1]) < 0.1) continue;
      dedup.push(p);
    }
    if (dedup.length >= 2) {
      const wall = this.store.addWall(dedup, { height: 3, thickness: 0.16 });
      this.emit('wall:added', wall);
    }
    this.wallDraft = { points: [] };
    this._drawWallDraft();
  }

  clearWallDraft() {
    this.wallDraft = null;
    for (const child of [...this.guidesGroup.children]) {
      if (child.userData.guide === 'wall') {
        disposeGeometries(child);
        disposeMaterials(child);
        this.guidesGroup.remove(child);
      }
    }
  }

  cancelCurrent() {
    if (this.tool === 'calibrate') {
      this.cancelCalibration();
      return true;
    }
    if (this.tool === 'wall') {
      this.clearWallDraft();
      this.setTool('select');
      return true;
    }
    if (this.tool === 'add') {
      this.setTool('select');
      return true;
    }
    if (this.tool === 'measure') {
      this.setTool('select');
      return true;
    }
    return false;
  }

  /* ======================= ponteiro ======================= */

  _pointerNdc(e) {
    const rect = this.canvas.getBoundingClientRect();
    this._ndc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this._ndc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    return this._ndc;
  }

  _floorPointFromEvent(e) {
    const ndc = this._pointerNdc(e);
    this._raycaster.setFromCamera(ndc, this._activeCamera());
    const hit = this._raycaster.ray.intersectPlane(this._floorPlane, this._tmpVec);
    return hit ? hit.clone() : null;
  }

  _pickEquipment(e) {
    const ndc = this._pointerNdc(e);
    this._raycaster.setFromCamera(ndc, this._activeCamera());
    const hits = this._raycaster.intersectObjects(this.equipmentGroup.children, true);
    for (const hit of hits) {
      let obj = hit.object;
      while (obj && !obj.userData?.equipmentId) obj = obj.parent;
      if (obj?.userData?.equipmentId) {
        const rec = this.items.get(obj.userData.equipmentId);
        if (rec?.group.visible) return rec;
      }
    }
    return null;
  }

  _pickWall(e) {
    if (!this.store.project.settings.showWalls) return null;
    const ndc = this._pointerNdc(e);
    this._raycaster.setFromCamera(ndc, this._activeCamera());
    const hits = this._raycaster.intersectObjects(this.wallMeshes, false);
    if (!hits.length) return null;
    const id = hits[0].object.userData.wallId;
    return this.wallMap.get(id) || null;
  }

  _snap(v) {
    const s = this.store.project.settings;
    if (!s.snap) return v;
    return Math.round(v / (s.snapSize || 0.25)) * (s.snapSize || 0.25);
  }

  _emitPointer(p) {
    if (!p) return;
    if (this._lastCoord.x !== null && Math.abs(this._lastCoord.x - p.x) < 0.005 && Math.abs(this._lastCoord.z - p.z) < 0.005) return;
    this._lastCoord = { x: p.x, z: p.z };
    this.emit('pointer', { x: p.x, z: p.z });
  }

  _onPointerDown(e) {
    if (e.button !== 0) return;
    if (this.mode === 'walk') {
      this.requestWalkLock();
      return;
    }
    try {
      this.canvas.setPointerCapture?.(e.pointerId);
    } catch {
      /* teste/ambiente sem captura de ponteiro ativa */
    }
    this.down = { x: e.clientX, y: e.clientY, time: performance.now() };
    if (this.tool !== 'select') return;

    const rec = this._pickEquipment(e);
    if (rec) {
      this.hovered = null;
      this.emit('hover', { item: null });
      this.select('equipment', rec.item.id, { focus: false });
      if (!this.editable) return;
      const p = this._floorPointFromEvent(e);
      if (p) {
        this.drag = {
          id: rec.item.id,
          offsetX: p.x - rec.item.x,
          offsetZ: p.z - rec.item.z,
          startX: rec.item.x,
          startZ: rec.item.z,
          moved: false,
        };
        this.orbit.enabled = false;
        this.orbitTop.enabled = false;
        this.canvas.classList.add('grabbing');
      }
      return;
    }
    const wall = this._pickWall(e);
    if (wall) {
      this.select('wall', wall.wall.id, { focus: false });
      return;
    }
    this.clearSelection();
  }

  _onPointerMove(e) {
    if (this.mode === 'walk' || this.mode === 'top') {
      // ainda emite coordenadas no modo planta
    }
    if (this.mode === 'walk') return;

    const p = this._floorPointFromEvent(e);
    if (p) this._emitPointer(p);

    if (this.drag) {
      if (!p) return;
      const rec = this.items.get(this.drag.id);
      if (!rec) return;
      const nx = this._snap(p.x - this.drag.offsetX);
      const nz = this._snap(p.z - this.drag.offsetZ);
      rec.group.position.x = nx;
      rec.group.position.z = nz;
      if (Math.abs(nx - this.drag.startX) > 0.01 || Math.abs(nz - this.drag.startZ) > 0.01) this.drag.moved = true;
      this.canvas.classList.add('grabbing');
      this.emit('drag:move', { id: this.drag.id, x: nx, z: nz });
      return;
    }

    if (this.tool === 'add' && this._ghost && p) {
      this._ghost.position.x = this._snap(p.x);
      this._ghost.position.z = this._snap(p.z);
      this._ghost.visible = true;
      return;
    }

    if (this.tool === 'wall' && this.wallDraft) {
      this._drawWallDraft(p);
      return;
    }

    if (this.tool === 'select') {
      const rec = this._pickEquipment(e);
      if (rec) {
        this.canvas.classList.add('pointer');
        if (this.hovered !== rec.item.id) {
          this.hovered = rec.item.id;
          this.emit('hover', { item: rec.item, clientX: e.clientX, clientY: e.clientY });
        } else {
          this.emit('hover:move', { clientX: e.clientX, clientY: e.clientY });
        }
      } else {
        this.canvas.classList.remove('pointer');
        if (this.hovered) {
          this.hovered = null;
          this.emit('hover', { item: null });
        }
      }
    }
  }

  _onPointerUp(e) {
    try {
      if (this.canvas.hasPointerCapture?.(e.pointerId)) this.canvas.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    if (this.mode === 'walk') return;
    const down = this.down;
    this.down = null;
    const moved = down ? Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5 : false;

    if (this.drag) {
      const rec = this.items.get(this.drag.id);
      const wasMoved = this.drag.moved;
      const pos = rec ? { x: rec.item.x, z: rec.item.z } : null;
      // posição visual atual
      const nx = rec ? rec.group.position.x : 0;
      const nz = rec ? rec.group.position.z : 0;
      this.drag = null;
      this.orbit.enabled = this.mode === '3d';
      this.orbitTop.enabled = this.mode === 'top';
      this.canvas.classList.remove('grabbing');
      if (rec && wasMoved && Math.max(Math.abs(nx), Math.abs(nz)) <= 500) {
        this.store.updateEquipment(rec.item.id, { x: nx, z: nz }, { coalesceKey: `move:${rec.item.id}` });
      } else if (rec && wasMoved) {
        rec.group.position.x = pos.x;
        rec.group.position.z = pos.z;
        this.emit('error', { message: 'Escolha um ponto dentro dos limites do mapa.' });
      }
      return;
    }

    if (moved || !down) return;
    const p = this._floorPointFromEvent(e);
    if (!p) return;

    if (this.tool === 'add') {
      this._handleAdd(p);
      return;
    }
    if (this.tool === 'calibrate') {
      this._handleCalibration(p);
      return;
    }
    if (this.tool === 'measure') {
      this._handleMeasure(p);
      return;
    }
    if (this.tool === 'wall') {
      this._handleWallPoint(p);
    }
  }

  _onPointerLeave() {
    this.canvas.classList.remove('pointer');
    if (this._ghost) this._ghost.visible = false;
    if (this.hovered) {
      this.hovered = null;
      this.emit('hover', { item: null });
    }
  }

  _makeTextSprite(text, color = '#e2e8f0') {
    const c = document.createElement('canvas');
    c.width = 512;
    c.height = 128;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, 512, 128);
    ctx.fillStyle = 'rgba(8, 13, 22, .88)';
    ctx.strokeStyle = 'rgba(148, 163, 184, .35)';
    ctx.lineWidth = 3;
    const r = 26;
    ctx.beginPath();
    ctx.moveTo(8 + r, 8);
    ctx.arcTo(504, 8, 504, 120, r);
    ctx.arcTo(504, 120, 8, 120, r);
    ctx.arcTo(8, 120, 8, 8, r);
    ctx.arcTo(8, 8, 504, 8, r);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = '600 46px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 256, 66);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false, toneMapped: false });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(3.4, 0.85, 1);
    sprite.raycast = () => {};
    return sprite;
  }

  /* ======================= configurações e animação ======================= */

  _applySettings(settings = {}) {
    if (this.floorGrid) this.floorGrid.visible = !!settings.showGrid || !this.plan;
    if (this.wallsGroup) this.wallsGroup.visible = settings.showWalls !== false;
    this._applyLabelVisibility();
    if (this.orbit) this.orbit.autoRotate = !!settings.autoRotate;
    this.emit('settings:applied', settings);
  }

  _loop() {
    if (this._disposed) return;
    this._raf = requestAnimationFrame(this._loop);
    const dt = Math.min(0.05, this._clock.getDelta());
    const t = this._clock.elapsedTime;

    if (this._tween) {
      this._tween.elapsed += dt * 1000;
      const k = clamp(this._tween.elapsed / this._tween.duration, 0, 1);
      const e = easeInOutCubic(k);
      this.camera.position.lerpVectors(this._tween.fromPos, this._tween.toPos, e);
      this.orbit.target.lerpVectors(this._tween.fromTarget, this._tween.toTarget, e);
      if (k >= 1) this._tween = null;
    }

    if (this.mode === 'walk') {
      this._updateWalk(dt);
    } else if (this.mode === 'top') {
      this.orbitTop.update();
    } else {
      this.orbit.update();
    }

    // pulso dos anéis
    for (const rec of this.items.values()) {
      const rings = rec.model.userData.pulseRings;
      if (rings) {
        for (const ring of rings) {
          const phase = (ring.userData.phase || 0) + t * 1.7;
          const s = 1 + Math.sin(phase) * 0.14;
          ring.scale.set(s, s, s);
          if (ring.material) ring.material.opacity = 0.08 + (0.5 + 0.5 * Math.sin(phase)) * 0.18;
        }
      }
      if (rec.ring?.visible) {
        const s = rec.baseScale * (1 + Math.sin(t * 2.6) * 0.045);
        rec.ring.scale.set(s, s, s);
      }
    }
    if (this._ghost?.visible) {
      this._ghost.rotation.y = Math.sin(t * 0.9) * 0.02;
    }

    this._labelClock += dt;
    if (this._labelClock > 0.12) {
      this._labelClock = 0;
      this._updateLabels();
    }

    this.renderer.render(this.scene, this._activeCamera());
  }

  /* ======================= miniaturas ======================= */

  async _generateThumbnails() {
    if (this._thumbsStarted || this._disposed) return;
    this._thumbsStarted = true;
    try {
      await nextFrame();
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      renderer.setPixelRatio(1);
      renderer.setSize(256, 256, false);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.15;
      const scene = new THREE.Scene();
      scene.add(new THREE.HemisphereLight(0xdbeafe, 0x0b1220, 2.4));
      const d1 = new THREE.DirectionalLight(0xffffff, 2.6);
      d1.position.set(4, 7, 6);
      scene.add(d1);
      const d2 = new THREE.DirectionalLight(0x93c5fd, 1.5);
      d2.position.set(-6, 4, -5);
      scene.add(d2);
      const camera = new THREE.PerspectiveCamera(34, 1, 0.01, 100);
      const canvas = renderer.domElement;

      for (const type of EQUIPMENT_TYPES) {
        try {
          const model = buildModel(type.id);
          scene.add(model);
          const box = new THREE.Box3().setFromObject(model);
          const sphere = box.getBoundingSphere(new THREE.Sphere());
          const dist = (sphere.radius / Math.sin(deg2rad(17))) * 1.02;
          camera.position.copy(sphere.center).add(new THREE.Vector3(1, 0.78, 1.25).normalize().multiplyScalar(dist + 0.2));
          camera.lookAt(sphere.center);
          renderer.render(scene, camera);
          const dataUrl = canvas.toDataURL('image/png');
          this.thumbnails.set(type.id, dataUrl);
          this.emit('thumb:item', { id: type.id, dataUrl });
          scene.remove(model);
          disposeGeometries(model);
        } catch (err) {
          console.warn('[Mapa3D] miniatura falhou para', type.id, err);
        }
        if (EQUIPMENT_TYPES.indexOf(type) % 4 === 3) await nextFrame();
      }
      renderer.dispose();
      renderer.forceContextLoss?.();
      this.emit('thumbs:ready', this.thumbnails);
    } catch (err) {
      console.warn('[Mapa3D] não foi possível gerar miniaturas', err);
    }
  }

  /* ======================= extras ======================= */

  async screenshot() {
    this.renderer.render(this.scene, this._activeCamera());
    return new Promise((resolve) => this.canvas.toBlob((blob) => resolve(blob), 'image/png', 0.95));
  }

  getState() {
    return {
      mode: this.mode,
      tool: this.tool,
      placementType: this.placementType,
      selected: this.selected,
      planW: this.planW,
      planH: this.planH,
      items: this.items.size,
      locked: this._locked,
    };
  }

  dispose() {
    this._disposed = true;
    this.planToken++;
    this._events.abort();
    this._subscriptions.forEach(off => off());
    if (document.pointerLockElement === this.canvas) document.exitPointerLock?.();
    cancelAnimationFrame(this._raf);
    this._resizeObserver?.disconnect();
    this.orbit?.dispose();
    this.orbitTop?.dispose();
    if (this.scene) disposeGeometries(this.scene);
    this.planTexture?.dispose();
    this.pinGeometry?.dispose();
    this.pinMaterials?.forEach(mat => mat.dispose());
    this.envRT?.dispose();
    this.renderer?.dispose();
  }
}
