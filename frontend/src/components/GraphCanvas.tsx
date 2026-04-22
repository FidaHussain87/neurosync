import { useRef, useCallback, useEffect, useState } from 'react';
import ForceGraph3D, { type ForceGraphMethods } from 'react-force-graph-3d';
import * as THREE from 'three';
import type { GraphData, GraphNode, GraphLink, NodeType } from '../types';
import { NODE_STYLES, LINK_STYLES, DEFAULT_LINK_STYLE, NODE_TIER, type VisualTier } from '../constants';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FGMethods = ForceGraphMethods<any, any>;

interface Props {
  graphData: GraphData;
  selectedNode: GraphNode | null;
  onNodeClick: (node: GraphNode) => void;
  onBackgroundClick: () => void;
  viewResetCount: number;
}

// Episode event_type color variations
const EPISODE_TYPE_HUE: Record<string, string> = {
  decision:     '#9333EA',
  discovery:    '#A855F7',
  pattern:      '#7C3AED',
  debugging:    '#6D28D9',
  architecture: '#8B5CF6',
  causal:       '#A78BFA',
  frustration:  '#C084FC',
  question:     '#7E22CE',
  correction:   '#B91C1C',
  explicit:     '#D946EF',
  file_change:  '#6366F1',
  observed:     '#818CF8',
};

function getNodeRadius(node: GraphNode): number {
  const base = NODE_STYLES[node.label as NodeType]?.size ?? 6;
  if (node.label === 'Theory') {
    const confidence = Number(node.properties.confidence ?? 0.5);
    return 4 + confidence * 10;
  }
  return base;
}

function getEpisodeColor(node: GraphNode): string {
  const eventType = String(node.properties.event_type ?? '');
  return EPISODE_TYPE_HUE[eventType] ?? NODE_STYLES.Episode.color;
}

function getNodeMass(node: GraphNode): number {
  switch (node.label) {
    case 'Session': return 12;
    case 'Theory': return 5 + Number(node.properties.confidence ?? 0.5) * 5;
    case 'Concept': return 4;
    case 'FailureRecord': return 4;
    case 'StructuralPattern': return 3;
    case 'Episode': return 1.5;
    case 'Contradiction': return 1.5;
    case 'UserKnowledge': return 1.2;
    default: return 1;
  }
}

function getNodeTier(node: GraphNode): VisualTier {
  return NODE_TIER[node.label as NodeType] ?? 3;
}

// ─────────────────────────────────────────────────────────
// Glow texture generator — cached per color
// ─────────────────────────────────────────────────────────

const glowTextureCache = new Map<string, THREE.CanvasTexture>();

function createGlowTexture(hexColor: string): THREE.CanvasTexture {
  const cached = glowTextureCache.get(hexColor);
  if (cached) return cached;

  const size = 128;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;

  const cx = size / 2;
  const cy = size / 2;
  const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, cx);
  grad.addColorStop(0,    hexColor + 'FF');
  grad.addColorStop(0.1,  hexColor + 'EE');
  grad.addColorStop(0.25, hexColor + 'AA');
  grad.addColorStop(0.45, hexColor + '55');
  grad.addColorStop(0.7,  hexColor + '1A');
  grad.addColorStop(1,    hexColor + '00');

  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  glowTextureCache.set(hexColor, texture);
  return texture;
}

// ─────────────────────────────────────────────────────────
// Shared geometry/material pools — avoids per-node GPU alloc
// ─────────────────────────────────────────────────────────

const sharedGeometries = {
  core: new Map<string, THREE.SphereGeometry>(),
  ring: new Map<string, THREE.RingGeometry>(),
};

function getCoreSphereGeo(radius: number): THREE.SphereGeometry {
  const key = radius.toFixed(2);
  let geo = sharedGeometries.core.get(key);
  if (!geo) {
    geo = new THREE.SphereGeometry(radius, 16, 16);
    sharedGeometries.core.set(key, geo);
  }
  return geo;
}

function getRingGeo(inner: number, outer: number): THREE.RingGeometry {
  const key = `${inner.toFixed(2)}-${outer.toFixed(2)}`;
  let geo = sharedGeometries.ring.get(key);
  if (!geo) {
    geo = new THREE.RingGeometry(inner, outer, 32);
    sharedGeometries.ring.set(key, geo);
  }
  return geo;
}

const sharedMaterials = new Map<string, THREE.MeshBasicMaterial | THREE.SpriteMaterial>();

function getCoreMaterial(hexColor: string): THREE.MeshBasicMaterial {
  const key = `core-${hexColor}`;
  let mat = sharedMaterials.get(key) as THREE.MeshBasicMaterial | undefined;
  if (!mat) {
    mat = new THREE.MeshBasicMaterial({
      color: new THREE.Color(hexColor),
      transparent: true,
      opacity: 0.9,
    });
    sharedMaterials.set(key, mat);
  }
  return mat;
}

const selectionRingMaterial = new THREE.MeshBasicMaterial({
  color: 0xffffff,
  transparent: true,
  opacity: 0.7,
  side: THREE.DoubleSide,
  depthWrite: false,
});

function getGlowSpriteMaterial(hexColor: string, opacity: number): THREE.SpriteMaterial {
  const key = `glow-${hexColor}-${opacity.toFixed(2)}`;
  let mat = sharedMaterials.get(key) as THREE.SpriteMaterial | undefined;
  if (!mat) {
    mat = new THREE.SpriteMaterial({
      map: createGlowTexture(hexColor),
      transparent: true,
      opacity,
      depthWrite: false,
    });
    sharedMaterials.set(key, mat);
  }
  return mat;
}

// ─────────────────────────────────────────────────────────
// Starfield helper — creates a THREE.Points cloud
// ─────────────────────────────────────────────────────────

function createStarField(count: number, spread: number): THREE.Points {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);

  for (let i = 0; i < count; i++) {
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = spread * (0.3 + Math.random() * 0.7);

    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = r * Math.cos(phi);

    const temp = Math.random();
    if (temp < 0.25) {
      colors[i * 3] = 1.0; colors[i * 3 + 1] = 0.75; colors[i * 3 + 2] = 0.55;
    } else if (temp < 0.5) {
      colors[i * 3] = 1.0; colors[i * 3 + 1] = 0.94; colors[i * 3 + 2] = 0.85;
    } else if (temp < 0.75) {
      colors[i * 3] = 0.9; colors[i * 3 + 1] = 0.92; colors[i * 3 + 2] = 1.0;
    } else {
      colors[i * 3] = 0.7; colors[i * 3 + 1] = 0.8; colors[i * 3 + 2] = 1.0;
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

  const material = new THREE.PointsMaterial({
    size: 1.5,
    vertexColors: true,
    transparent: true,
    opacity: 0.7,
    sizeAttenuation: true,
    depthWrite: false,
  });

  return new THREE.Points(geometry, material);
}

// ─────────────────────────────────────────────────────────
// Extract hex color + alpha from rgba() string
// ─────────────────────────────────────────────────────────

function rgbaToHexAlpha(rgba: string): { hex: string; alpha: number } {
  const m = rgba.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)/);
  if (!m) return { hex: rgba, alpha: 1 };
  const r = parseInt(m[1], 10);
  const g = parseInt(m[2], 10);
  const b = parseInt(m[3], 10);
  const a = m[4] !== undefined ? parseFloat(m[4]) : 1;
  const hex = '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
  return { hex, alpha: a };
}

// ── Zoom constants ──
const ZOOM_MIN_DIST = 30;
const ZOOM_MAX_DIST = 5000;

// Log-scale mapping: slider position (0–1) ↔ camera distance
// Top of slider = zoomed in (min dist), bottom = zoomed out (max dist)
const LOG_MIN = Math.log(ZOOM_MIN_DIST);
const LOG_MAX = Math.log(ZOOM_MAX_DIST);

function distToSliderPct(dist: number): number {
  const clamped = Math.max(ZOOM_MIN_DIST, Math.min(ZOOM_MAX_DIST, dist));
  return (Math.log(clamped) - LOG_MIN) / (LOG_MAX - LOG_MIN);
}

function sliderPctToDist(pct: number): number {
  const p = Math.max(0, Math.min(1, pct));
  return Math.exp(LOG_MIN + p * (LOG_MAX - LOG_MIN));
}

// ── Component ──────────────────────────────────────────────

export default function GraphCanvas({ graphData, selectedNode, onNodeClick, onBackgroundClick, viewResetCount }: Props) {
  const fgRef = useRef<FGMethods | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [zoomDist, setZoomDist] = useState(400);
  const zoomAnimRef = useRef(0);
  const prevResetCountRef = useRef(viewResetCount);
  const timeRef = useRef(0);
  const lastTickRef = useRef(performance.now());
  const sceneInitRef = useRef(false);
  const starFieldRef = useRef<THREE.Points | null>(null);
  const cameraDistRef = useRef(400);
  const controlsAttached = useRef(false);
  const forcesConfigured = useRef(false);
  const hasData = graphData.nodes.length > 0;

  // Track selected node ID in a ref so nodeThreeObject doesn't
  // depend on selectedNode. Selection ring is managed in onEngineTick.
  const selectedNodeIdRef = useRef<string | null>(null);
  selectedNodeIdRef.current = selectedNode?.id ?? null;

  // ── Container resize tracking ──
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      setDimensions({ width, height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // ── Scene setup + force config + camera — all done from onEngineTick ──
  // The kapsule-based ForceGraph3D initializes Three.js internals asynchronously.
  // useEffect with [] deps fires too early — scene/controls/camera aren't ready.
  // Instead, we do all initialization lazily inside onEngineTick, which only
  // fires once the renderer is actually running.

  const initScene = useCallback(() => {
    if (sceneInitRef.current) return;
    const fg = fgRef.current;
    if (!fg) return;

    let scene: THREE.Scene | undefined;
    try { scene = fg.scene() as THREE.Scene; } catch { return; }
    if (!scene) return;

    sceneInitRef.current = true;
    scene.background = new THREE.Color('#050810');
    scene.fog = new THREE.FogExp2(0x050810, 0.00015);

    const starField = createStarField(2000, 4000);
    starFieldRef.current = starField;
    scene.add(starField);

    // Set initial camera position: 36-degree elevation angle
    const dist = 400;
    const elevationRad = (36 * Math.PI) / 180;
    const y = dist * Math.sin(elevationRad);
    const xz = dist * Math.cos(elevationRad);
    fg.cameraPosition({ x: xz, y, z: xz }, { x: 0, y: 0, z: 0 }, 0);

    // Attach controls listener for camera distance tracking
    if (!controlsAttached.current) {
      let controls: any;
      try { controls = fg.controls(); } catch { /* */ }
      if (controls && typeof controls.addEventListener === 'function') {
        controlsAttached.current = true;
        controls.addEventListener('change', () => {
          let cam: THREE.Camera | undefined;
          try { cam = fg.camera() as THREE.Camera; } catch { return; }
          if (cam) {
            const pos = cam.position;
            cameraDistRef.current = Math.sqrt(pos.x * pos.x + pos.y * pos.y + pos.z * pos.z);
          }
        });
      }
    }
  }, []);

  const initForces = useCallback(() => {
    if (forcesConfigured.current || !hasData) return;
    const fg = fgRef.current;
    if (!fg) return;
    forcesConfigured.current = true;

    const charge = fg.d3Force('charge');
    if (charge && typeof (charge as any).strength === 'function') {
      (charge as any).strength((node: GraphNode) => {
        const mass = getNodeMass(node);
        const tier = getNodeTier(node);
        // T1 strong gravity, T2 medium, T3 enough repulsion to spread out
        const multiplier = tier === 1 ? -50 : tier === 2 ? -30 : -25;
        return multiplier * mass;
      });
      if (typeof (charge as any).distanceMax === 'function') {
        (charge as any).distanceMax(800);
      }
    }

    const link = fg.d3Force('link');
    if (link && typeof (link as any).distance === 'function') {
      (link as any).distance((l: GraphLink) => {
        const type = l.type;
        if (type === 'CONTAINS') return 60;
        if (type === 'EXTRACTED_FROM') return 70;
        if (type === 'CAUSES') return 55;
        if (type === 'CONTRADICTS') return 80;
        if (type === 'PARENT_OF') return 50;
        return 70;
      });
      if (typeof (link as any).strength === 'function') {
        (link as any).strength((l: GraphLink) => {
          if (l.type === 'CONTAINS') return 0.4;
          if (l.type === 'PARENT_OF') return 0.6;
          if (l.type === 'CAUSES') return 0.5;
          return 0.3;
        });
      }
    }

    try { fg.d3ReheatSimulation(); } catch { /* layout may not be ready */ }
  }, [hasData]);

  // ── Adapt fog density and starfield scale to graph extent ──
  useEffect(() => {
    if (!hasData || !sceneInitRef.current) return;
    const fg = fgRef.current;
    if (!fg) return;

    let scene: THREE.Scene | undefined;
    try { scene = fg.scene() as THREE.Scene; } catch { return; }
    if (!scene || !scene.fog) return;

    let maxR = 0;
    for (const n of graphData.nodes) {
      const x = n.x ?? 0, y = n.y ?? 0, z = n.z ?? 0;
      const r = Math.sqrt(x * x + y * y + z * z);
      if (r > maxR) maxR = r;
    }
    if (maxR < 100) maxR = 100;

    const fog = scene.fog as THREE.FogExp2;
    fog.density = Math.sqrt(-Math.log(0.05)) / (maxR * 12);

    const starField = starFieldRef.current;
    if (starField) {
      const desiredScale = Math.max(4000, maxR * 5) / 4000;
      starField.scale.setScalar(desiredScale);
    }
  }, [graphData, hasData]);

  // ── Warm-start: Fibonacci sphere distribution for 3D ──
  useEffect(() => {
    const count = graphData.nodes.length;
    if (count === 0) return;

    const radius = Math.max(120, count * 4);
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));

    graphData.nodes.forEach((node, i) => {
      if (node.x === undefined && node.y === undefined && node.z === undefined) {
        const y = 1 - (i / (count - 1 || 1)) * 2;
        const radiusAtY = Math.sqrt(1 - y * y);
        const theta = goldenAngle * i;

        node.x = Math.cos(theta) * radiusAtY * radius + (Math.random() - 0.5) * 20;
        node.y = y * radius + (Math.random() - 0.5) * 20;
        node.z = Math.sin(theta) * radiusAtY * radius + (Math.random() - 0.5) * 20;
      }
    });

    if (viewResetCount !== prevResetCountRef.current) {
      prevResetCountRef.current = viewResetCount;
      const timer = setTimeout(() => {
        fgRef.current?.zoomToFit(400, 60);
      }, 800);
      return () => clearTimeout(timer);
    }
  }, [graphData, viewResetCount]);

  // ─────────────────────────────────────────────────────────
  // Node Three.js object builder — tier-specific visuals
  // ─────────────────────────────────────────────────────────
  const nodeThreeObject = useCallback(
    (node: GraphNode) => {
      const style = NODE_STYLES[node.label as NodeType] ?? { color: '#6B7280', borderColor: '#9CA3AF' };
      const fillColor = node.label === 'Episode' ? getEpisodeColor(node) : style.color;
      const mass = getNodeMass(node);
      const baseRadius = getNodeRadius(node);
      const tier = getNodeTier(node);

      const group = new THREE.Group();
      group.userData.breathePhase = Math.random() * Math.PI * 2;
      group.userData.nodeId = node.id;
      group.userData.baseRadius = baseRadius;
      group.userData.tier = tier;

      if (tier === 1) {
        // ── Tier 1: Galaxy Center (Session) ──
        // Bright nebula halo
        const nebulaSprite = new THREE.Sprite(getGlowSpriteMaterial(fillColor, 0.8));
        nebulaSprite.scale.set(baseRadius * 3, baseRadius * 3, 1);
        nebulaSprite.userData.isNebula = true;
        group.add(nebulaSprite);

        // Secondary halo in borderColor
        const haloSprite = new THREE.Sprite(getGlowSpriteMaterial(style.borderColor, 0.4));
        haloSprite.scale.set(baseRadius * 2, baseRadius * 2, 1);
        group.add(haloSprite);

        // Core sphere — bright center
        const coreMesh = new THREE.Mesh(getCoreSphereGeo(baseRadius * 0.35), getCoreMaterial(fillColor));
        group.add(coreMesh);

      } else if (tier === 2) {
        // ── Tier 2: Stars (Theory, Concept, FailureRecord, StructuralPattern) ──
        // Bright star glow
        const glowSprite = new THREE.Sprite(getGlowSpriteMaterial(fillColor, 0.85));
        glowSprite.scale.set(baseRadius * 3, baseRadius * 3, 1);
        group.add(glowSprite);

        // Core sphere
        const coreMesh = new THREE.Mesh(getCoreSphereGeo(baseRadius * 0.4), getCoreMaterial(fillColor));
        group.add(coreMesh);

        // Corona for massive stars (mass > 4)
        if (mass > 4) {
          const coronaSize = baseRadius * 2.5 + mass * 1;
          const coronaSprite = new THREE.Sprite(getGlowSpriteMaterial(fillColor, 0.3));
          coronaSprite.scale.set(coronaSize, coronaSize, 1);
          group.add(coronaSprite);
        }

        // Theory confidence extra glow — brighter with confidence
        if (node.label === 'Theory') {
          const confidence = Number(node.properties.confidence ?? 0.5);
          const glowSize = baseRadius * 2 + confidence * 5;
          const opacity = 0.2 + confidence * 0.4;
          const confSprite = new THREE.Sprite(getGlowSpriteMaterial(style.color, opacity));
          confSprite.scale.set(glowSize, glowSize, 1);
          group.add(confSprite);
        }

      } else {
        // ── Tier 3: Distant stars (Episode, Contradiction, UserKnowledge) ──
        // Glow — clone material so per-node opacity fading works
        const glowMat = getGlowSpriteMaterial(fillColor, 0.6).clone();
        const glowSprite = new THREE.Sprite(glowMat);
        glowSprite.scale.set(baseRadius * 2.5, baseRadius * 2.5, 1);
        glowSprite.userData.isDustGlow = true;
        group.add(glowSprite);

        // Core sphere — clone material for per-node opacity
        const coreMat = getCoreMaterial(fillColor).clone();
        const coreMesh = new THREE.Mesh(getCoreSphereGeo(baseRadius * 0.35), coreMat);
        coreMesh.userData.isDustCore = true;
        group.add(coreMesh);
      }

      return group;
    },
    [],
  );

  // ─────────────────────────────────────────────────────────
  // Engine tick: lazy init + tier-aware animation + selection ring
  // ─────────────────────────────────────────────────────────
  const onEngineTick = useCallback(() => {
    // Lazy init — runs once the renderer is truly alive
    initScene();
    initForces();

    const now = performance.now();
    const dt = (now - lastTickRef.current) * 0.001;
    lastTickRef.current = now;
    timeRef.current += dt;
    const t = timeRef.current;

    const fg = fgRef.current;
    if (!fg) return;

    let cam: THREE.Camera | undefined;
    try { cam = fg.camera() as THREE.Camera; } catch { /* not ready */ }

    if (cam) {
      const pos = cam.position;
      cameraDistRef.current = Math.sqrt(pos.x * pos.x + pos.y * pos.y + pos.z * pos.z);
    }

    // Smooth zoom slider sync via rAF — only schedule one update per frame
    if (!zoomAnimRef.current) {
      zoomAnimRef.current = requestAnimationFrame(() => {
        zoomAnimRef.current = 0;
        setZoomDist(cameraDistRef.current);
      });
    }

    const camDist = cameraDistRef.current;
    const selectedId = selectedNodeIdRef.current;

    // Per-node: breathing, tier fading, selection ring
    (graphData.nodes as any[]).forEach((node: any) => {
      const obj = node.__threeObj as THREE.Group | undefined;
      if (!obj) return;

      const tier: VisualTier = obj.userData.tier ?? 3;
      const phase = obj.userData.breathePhase ?? 0;

      // ── Tier 1: slower/larger nebula pulse ──
      if (tier === 1) {
        const breathe = 1 + Math.sin(t * 0.6 + phase) * 0.08;
        obj.scale.set(breathe, breathe, breathe);

        // Pulse nebula opacity
        const nebulaChild = obj.children.find((c: THREE.Object3D) => c.userData.isNebula) as THREE.Sprite | undefined;
        if (nebulaChild?.material) {
          (nebulaChild.material as THREE.SpriteMaterial).opacity = 0.3 + Math.sin(t * 0.8 + phase) * 0.1;
        }
      }
      // ── Tier 2: standard breathe ──
      else if (tier === 2) {
        const breathe = 1 + Math.sin(t * 1.2 + phase) * 0.04;
        obj.scale.set(breathe, breathe, breathe);
      }
      // ── Tier 3: zoom-dependent fade ──
      else {
        const breathe = 1 + Math.sin(t * 1.2 + phase) * 0.04;
        obj.scale.set(breathe, breathe, breathe);

        // Fade: full opacity at <=400, dim to minimum at >=2000 (never fully invisible)
        const fadeFactor = camDist <= 400 ? 1 : camDist >= 2000 ? 0.12 : 0.12 + 0.88 * (1 - (camDist - 400) / 1600);

        // Update cloned materials
        obj.visible = true;
        for (const child of obj.children) {
          if (child.userData.isDustGlow && (child as THREE.Sprite).material) {
            ((child as THREE.Sprite).material as THREE.SpriteMaterial).opacity = 0.6 * fadeFactor;
          }
          if (child.userData.isDustCore && (child as THREE.Mesh).material) {
            ((child as THREE.Mesh).material as THREE.MeshBasicMaterial).opacity = 0.95 * fadeFactor;
          }
        }
      }

      // Manage selection ring dynamically
      const isSelected = node.id === selectedId;
      const existingRing = obj.children.find((c: THREE.Object3D) => c.userData.isSelectionRing);

      if (isSelected && !existingRing) {
        const baseRadius = obj.userData.baseRadius ?? 6;
        const ring = new THREE.Mesh(getRingGeo(baseRadius * 1.2, baseRadius * 1.5), selectionRingMaterial);
        ring.userData.isSelectionRing = true;
        obj.add(ring);
      } else if (!isSelected && existingRing) {
        obj.remove(existingRing);
      }

      // Make selection rings face camera
      if (cam && isSelected) {
        const ring = obj.children.find((c: THREE.Object3D) => c.userData.isSelectionRing);
        if (ring) ring.lookAt(cam.position);
      }
    });
  }, [graphData, initScene, initForces]);

  // ─────────────────────────────────────────────────────────
  // Link styling
  // ─────────────────────────────────────────────────────────
  const getLinkColor = useCallback((link: GraphLink) => {
    const style = LINK_STYLES[link.type] ?? DEFAULT_LINK_STYLE;
    const { hex } = rgbaToHexAlpha(style.color);
    return hex;
  }, []);

  const getLinkWidth = useCallback((link: GraphLink) => {
    const style = LINK_STYLES[link.type] ?? DEFAULT_LINK_STYLE;
    if (link.type === 'CAUSES') {
      const strength = Number(link.properties.strength ?? 1);
      return 1 + strength * 2;
    }
    return style.width;
  }, []);

  const getLinkParticles = useCallback((link: GraphLink) => {
    return link.type === 'CAUSES' ? 3 : 0;
  }, []);

  const getLinkParticleColor = useCallback((link: GraphLink) => {
    return LINK_STYLES[link.type]?.color ?? DEFAULT_LINK_STYLE.color;
  }, []);

  // Dashed links via linkMaterial
  const dashedMaterialCache = useRef(new Map<string, THREE.LineDashedMaterial>());
  const getLinkMaterial = useCallback((link: GraphLink) => {
    const style = LINK_STYLES[link.type] ?? DEFAULT_LINK_STYLE;
    if (!style.dashed) return false;
    const { hex, alpha } = rgbaToHexAlpha(style.color);
    const key = `${hex}-${alpha.toFixed(2)}`;
    let mat = dashedMaterialCache.current.get(key);
    if (!mat) {
      mat = new THREE.LineDashedMaterial({
        color: new THREE.Color(hex),
        transparent: true,
        opacity: alpha,
        dashSize: 3,
        gapSize: 2,
        depthWrite: false,
      });
      dashedMaterialCache.current.set(key, mat);
    }
    return mat;
  }, []);

  // ─────────────────────────────────────────────────────────
  // Click handlers
  // ─────────────────────────────────────────────────────────
  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      onNodeClick(node);
      const fg = fgRef.current;
      if (fg && node.x !== undefined && node.y !== undefined) {
        const nx = node.x;
        const ny = node.y;
        const nz = node.z ?? 0;
        const targetDist = 80;

        let cam: THREE.Camera | undefined;
        try { cam = fg.camera() as THREE.Camera; } catch { /* */ }

        let dx = 1, dy = 0.5, dz = 1;
        if (cam) {
          dx = cam.position.x - nx;
          dy = cam.position.y - ny;
          dz = cam.position.z - nz;
          const len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
          dx /= len; dy /= len; dz /= len;
        } else {
          const len = Math.sqrt(dx * dx + dy * dy + dz * dz);
          dx /= len; dy /= len; dz /= len;
        }

        fg.cameraPosition(
          { x: nx + dx * targetDist, y: ny + dy * targetDist, z: nz + dz * targetDist },
          { x: nx, y: ny, z: nz },
          1000,
        );
      }
    },
    [onNodeClick],
  );

  const getNodeLabel = useCallback((node: GraphNode) => {
    return `${node.label}: ${node.name}`;
  }, []);

  // ─────────────────────────────────────────────────────────
  // Zoom handler — moves camera along current direction vector
  // ─────────────────────────────────────────────────────────
  const handleZoom = useCallback((targetDist: number) => {
    const fg = fgRef.current;
    if (!fg) return;
    const clamped = Math.max(ZOOM_MIN_DIST, Math.min(ZOOM_MAX_DIST, targetDist));

    let cam: THREE.Camera | undefined;
    try { cam = fg.camera() as THREE.Camera; } catch { return; }
    if (!cam) return;

    const pos = cam.position;
    const len = Math.sqrt(pos.x * pos.x + pos.y * pos.y + pos.z * pos.z) || 1;
    const dx = pos.x / len;
    const dy = pos.y / len;
    const dz = pos.z / len;

    fg.cameraPosition(
      { x: dx * clamped, y: dy * clamped, z: dz * clamped },
      { x: 0, y: 0, z: 0 },
      0,
    );
    cameraDistRef.current = clamped;
    setZoomDist(clamped);
  }, []);

  return (
    <div ref={containerRef} className="flex-1 relative overflow-hidden">
      <ForceGraph3D
        ref={fgRef as any}
        width={dimensions.width}
        height={dimensions.height}
        graphData={graphData}
        nodeId="id"
        nodeThreeObject={nodeThreeObject}
        nodeThreeObjectExtend={false}
        nodeLabel={getNodeLabel}
        linkColor={getLinkColor}
        linkWidth={getLinkWidth}
        linkOpacity={1.0}
        linkCurvature={0.1}
        linkMaterial={getLinkMaterial as any}
        linkDirectionalParticles={getLinkParticles}
        linkDirectionalParticleWidth={2}
        linkDirectionalParticleColor={getLinkParticleColor}
        onNodeClick={handleNodeClick}
        onBackgroundClick={onBackgroundClick}
        onEngineTick={onEngineTick}
        numDimensions={3}
        cooldownTicks={100}
        d3AlphaDecay={0.04}
        d3VelocityDecay={0.55}
        warmupTicks={50}
        showNavInfo={false}
        backgroundColor="#050810"
        enableNodeDrag={true}
      />
      {!hasData && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-center text-gray-600">
            <p className="text-lg mb-2">No graph data loaded</p>
            <p className="text-sm">Connect to Neo4j and load an overview or run a query</p>
          </div>
        </div>
      )}
      {/* ── Zoom Slider (log-scale) ── */}
      {hasData && (
        <div
          className={`absolute top-1/2 -translate-y-1/2 z-10 pointer-events-auto flex flex-col items-center gap-1 transition-all duration-200 ${
            selectedNode ? 'right-[340px]' : 'right-3'
          }`}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {/* + button (zoom in) */}
          <button
            className="w-7 h-7 rounded bg-gray-900/70 backdrop-blur-sm text-gray-300 hover:text-white hover:bg-gray-800/80 flex items-center justify-center text-sm font-bold border border-gray-700/50 select-none"
            onClick={() => handleZoom(cameraDistRef.current * 0.8)}
          >
            +
          </button>

          {/* Track */}
          <div
            className="relative w-2 rounded-full bg-gray-800/60 backdrop-blur-sm border border-gray-700/40"
            style={{ height: 200 }}
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const pct = (e.clientY - rect.top) / rect.height;
              handleZoom(sliderPctToDist(pct));
            }}
          >
            {/* Handle */}
            <div
              className="absolute left-1/2 -translate-x-1/2 w-4 h-4 rounded-full bg-blue-500 border-2 border-blue-300 shadow-[0_0_8px_rgba(59,130,246,0.6)] cursor-grab active:cursor-grabbing"
              style={{
                top: `${distToSliderPct(zoomDist) * 100}%`,
                transform: 'translate(-50%, -50%)',
              }}
              onMouseDown={(e) => {
                e.preventDefault();
                e.stopPropagation();
                const track = e.currentTarget.parentElement!;
                const onMove = (me: MouseEvent) => {
                  const rect = track.getBoundingClientRect();
                  const pct = Math.max(0, Math.min(1, (me.clientY - rect.top) / rect.height));
                  handleZoom(sliderPctToDist(pct));
                };
                const onUp = () => {
                  document.removeEventListener('mousemove', onMove);
                  document.removeEventListener('mouseup', onUp);
                };
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
              }}
            />
          </div>

          {/* - button (zoom out) */}
          <button
            className="w-7 h-7 rounded bg-gray-900/70 backdrop-blur-sm text-gray-300 hover:text-white hover:bg-gray-800/80 flex items-center justify-center text-sm font-bold border border-gray-700/50 select-none"
            onClick={() => handleZoom(cameraDistRef.current * 1.25)}
          >
            -
          </button>
        </div>
      )}

      {hasData && (
        <div className="absolute bottom-4 right-4 text-xs text-gray-600 bg-gray-900/60 px-2 py-1 rounded">
          {graphData.nodes.length} nodes
        </div>
      )}
    </div>
  );
}
