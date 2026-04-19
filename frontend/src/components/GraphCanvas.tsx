import { useRef, useCallback, useEffect, useMemo, useState } from 'react';
import ForceGraph2D, { type ForceGraphMethods, type NodeObject, type LinkObject } from 'react-force-graph-2d';
import type { GraphData, GraphNode, GraphLink, NodeType } from '../types';
import { NODE_STYLES, LINK_STYLES, DEFAULT_LINK_STYLE } from '../constants';

interface Props {
  graphData: GraphData;
  selectedNode: GraphNode | null;
  onNodeClick: (node: GraphNode) => void;
  onBackgroundClick: () => void;
  onClusterDrillIn?: () => void;
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

// ─────────────────────────────────────────────────────────────
// Multi-layer parallax star field — generated once, static
// ─────────────────────────────────────────────────────────────

interface Star {
  x: number;         // normalized 0..1 position within layer
  y: number;
  r: number;         // base radius in screen pixels
  brightness: number; // peak alpha
  temperature: number; // 0 = warm (amber/red), 1 = cool (blue/white)
  twinklePhase: number;
  twinkleSpeed: number;
  hasDiffraction: boolean;
}

// Layer 0: distant nebula dust (screen-space, no parallax)
// Layer 1: far stars (screen-space, slow parallax)
// Layer 2: mid stars (screen-space, medium parallax)
// Layer 3: near stars (screen-space, fast parallax — closest to camera)
interface StarLayer {
  stars: Star[];
  parallaxFactor: number;  // 0 = fixed to screen, 1 = moves with graph
  sizeScale: number;       // multiplier for star radius
}

function generateStarLayer(count: number, parallax: number, sizeScale: number, diffractionChance: number): StarLayer {
  const stars: Star[] = [];
  for (let i = 0; i < count; i++) {
    stars.push({
      x: Math.random(),
      y: Math.random(),
      r: (0.2 + Math.random() * 0.8) * sizeScale,
      brightness: 0.15 + Math.random() * 0.65,
      temperature: Math.random(),
      twinklePhase: Math.random() * Math.PI * 2,
      twinkleSpeed: 0.3 + Math.random() * 1.5,
      hasDiffraction: Math.random() < diffractionChance,
    });
  }
  return { stars, parallaxFactor: parallax, sizeScale };
}

// Pre-generate 4 layers with increasing parallax
const STAR_LAYERS: StarLayer[] = [
  generateStarLayer(200, 0.0, 0.4, 0.0),   // dust — pinned to screen
  generateStarLayer(150, 0.02, 0.7, 0.02),  // distant
  generateStarLayer(100, 0.05, 1.0, 0.08),  // mid
  generateStarLayer(40,  0.10, 1.6, 0.25),  // near — larger, more diffraction
];

// Star color from temperature (Planck-like simplified)
function starColor(temp: number, alpha: number): string {
  // temp 0..1 maps from warm (3000K orange) to cool (10000K blue-white)
  let r: number, g: number, b: number;
  if (temp < 0.25) {
    // Red / orange giant
    r = 255; g = 180 + temp * 200; b = 140;
  } else if (temp < 0.5) {
    // Yellow / white (sun-like)
    r = 255; g = 240; b = 200 + (temp - 0.25) * 220;
  } else if (temp < 0.75) {
    // White
    r = 220 + (0.75 - temp) * 140; g = 225 + (0.75 - temp) * 60; b = 255;
  } else {
    // Blue-white hot star
    r = 180; g = 200; b = 255;
  }
  return `rgba(${Math.round(r)},${Math.round(g)},${Math.round(b)},${alpha.toFixed(3)})`;
}

// ─────────────────────────────────────────────────────────────
// Space fabric grid — Gaussian curvature near massive nodes
// ─────────────────────────────────────────────────────────────

function drawSpaceFabric(
  ctx: CanvasRenderingContext2D,
  nodes: GraphNode[],
  globalScale: number,
) {
  // Only draw when zoomed in enough to see detail
  if (globalScale < 1.5) return;

  const massiveNodes = nodes.filter(n =>
    n.x !== undefined && n.y !== undefined &&
    (n.label === 'Theory' || n.label === 'Session' || n.label === 'Concept'),
  );
  if (massiveNodes.length === 0) return;

  const gridAlpha = Math.min(0.12, 0.04 * globalScale);

  ctx.strokeStyle = `rgba(100, 120, 180, ${gridAlpha})`;
  ctx.lineWidth = 0.3 / globalScale;

  for (const node of massiveNodes) {
    const nx = node.x!;
    const ny = node.y!;
    const mass = node.label === 'Theory'
      ? 2 + Number(node.properties.confidence ?? 0.5) * 4
      : node.label === 'Session' ? 3 : 1.5;
    const fieldRadius = (30 + mass * 12) / globalScale * 3;

    // Draw concentric distortion rings (geodesics in curved space)
    for (let ring = 1; ring <= 4; ring++) {
      const baseR = ring * fieldRadius * 0.25;
      ctx.beginPath();
      const segments = 48;
      for (let s = 0; s <= segments; s++) {
        const angle = (s / segments) * Math.PI * 2;
        // Schwarzschild-like radial distortion: r_apparent = r * (1 + rs/(2r))
        // Simplified: rings closer to center are pushed outward slightly
        const distortion = 1 + (mass * 2) / (baseR * globalScale + mass * 4);
        const r = baseR * distortion;
        const px = nx + Math.cos(angle) * r;
        const py = ny + Math.sin(angle) * r;
        if (s === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();
    }

    // Radial field lines
    for (let spoke = 0; spoke < 12; spoke++) {
      const angle = (spoke / 12) * Math.PI * 2;
      ctx.beginPath();
      const innerR = fieldRadius * 0.15;
      const outerR = fieldRadius;
      ctx.moveTo(
        nx + Math.cos(angle) * innerR,
        ny + Math.sin(angle) * innerR,
      );
      // Slight spiral (frame dragging)
      const twist = mass * 0.05;
      ctx.quadraticCurveTo(
        nx + Math.cos(angle + twist) * (outerR * 0.6),
        ny + Math.sin(angle + twist) * (outerR * 0.6),
        nx + Math.cos(angle + twist * 2) * outerR,
        ny + Math.sin(angle + twist * 2) * outerR,
      );
      ctx.stroke();
    }
  }
}

// ─────────────────────────────────────────────────────────────
// Node mass for gravitational force computation
// ─────────────────────────────────────────────────────────────
function getNodeMass(node: GraphNode): number {
  switch (node.label) {
    case 'Session': return 8;
    case 'Theory': return 4 + Number(node.properties.confidence ?? 0.5) * 6;
    case 'Concept': return 3;
    case 'FailureRecord': return 3;
    case 'Contradiction': return 2.5;
    case 'Episode': return 1.5;
    case 'StructuralPattern': return 2;
    case 'UserKnowledge': return 2;
    default: return 1;
  }
}

// ── Component ──────────────────────────────────────────────
const CLUSTER_ZOOM_THRESHOLD = 3.0;

export default function GraphCanvas({ graphData, selectedNode, onNodeClick, onBackgroundClick, onClusterDrillIn, viewResetCount }: Props) {
  const fgRef = useRef<ForceGraphMethods<NodeObject<GraphNode>, LinkObject<GraphNode, GraphLink>> | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [zoomLevel, setZoomLevel] = useState(1);
  const prevResetCountRef = useRef(viewResetCount);
  const timeRef = useRef(0);
  const idleTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const animatingRef = useRef(true);

  // ── Idle-aware animation tick (pauses after 5s of no interaction) ──
  useEffect(() => {
    let running = true;
    let last = performance.now();
    let rafId = 0;

    const tick = (now: number) => {
      if (!running) return;
      timeRef.current += (now - last) * 0.001;
      last = now;
      if (animatingRef.current) {
        rafId = requestAnimationFrame(tick);
      }
    };

    const startAnimating = () => {
      if (!animatingRef.current) {
        animatingRef.current = true;
        last = performance.now();
        rafId = requestAnimationFrame(tick);
      }
      // Reset idle timer
      if (idleTimeoutRef.current) clearTimeout(idleTimeoutRef.current);
      idleTimeoutRef.current = setTimeout(() => {
        animatingRef.current = false;
      }, 5000); // Pause animation after 5s idle
    };

    // Start initial animation
    startAnimating();
    rafId = requestAnimationFrame(tick);

    // Wake on user interaction
    const el = containerRef.current;
    const wake = () => startAnimating();
    if (el) {
      el.addEventListener('mousemove', wake, { passive: true });
      el.addEventListener('mousedown', wake, { passive: true });
      el.addEventListener('wheel', wake, { passive: true });
      el.addEventListener('touchstart', wake, { passive: true });
    }

    return () => {
      running = false;
      animatingRef.current = false;
      cancelAnimationFrame(rafId);
      if (idleTimeoutRef.current) clearTimeout(idleTimeoutRef.current);
      if (el) {
        el.removeEventListener('mousemove', wake);
        el.removeEventListener('mousedown', wake);
        el.removeEventListener('wheel', wake);
        el.removeEventListener('touchstart', wake);
      }
    };
  }, []);

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

  // ── Wake animation when graph data changes ──
  useEffect(() => {
    if (graphData.nodes.length > 0) {
      animatingRef.current = true;
      if (idleTimeoutRef.current) clearTimeout(idleTimeoutRef.current);
      idleTimeoutRef.current = setTimeout(() => { animatingRef.current = false; }, 5000);
    }
  }, [graphData]);

  // ── Configure gravitational forces (once on mount) ──
  const forcesConfigured = useRef(false);
  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || forcesConfigured.current) return;
    forcesConfigured.current = true;

    // Mass-weighted charge: heavier nodes repel more strongly
    const charge = fg.d3Force('charge');
    if (charge && typeof charge.strength === 'function') {
      charge.strength((node: GraphNode) => {
        return -30 * getNodeMass(node);
      });
      if (typeof charge.distanceMax === 'function') {
        charge.distanceMax(400);
      }
    }

    // Link force: distance varies by relationship semantic weight
    const link = fg.d3Force('link');
    if (link && typeof link.distance === 'function') {
      link.distance((l: GraphLink) => {
        const type = l.type;
        if (type === 'CONTAINS') return 40;
        if (type === 'EXTRACTED_FROM') return 60;
        if (type === 'CAUSES') return 50;
        if (type === 'CONTRADICTS') return 80;
        if (type === 'PARENT_OF') return 45;
        return 70;
      });
      if (typeof link.strength === 'function') {
        link.strength((l: GraphLink) => {
          if (l.type === 'CONTAINS') return 0.8;
          if (l.type === 'CAUSES') return 0.6;
          return 0.3;
        });
      }
    }

    fg.d3ReheatSimulation();
  });

  // ── Warm-start: spread new nodes in a circle ──
  useEffect(() => {
    const count = graphData.nodes.length;
    if (count === 0) return;

    const radius = Math.max(80, count * 3);
    graphData.nodes.forEach((node, i) => {
      if (node.x === undefined && node.y === undefined) {
        const angle = (2 * Math.PI * i) / count;
        node.x = Math.cos(angle) * radius + (Math.random() - 0.5) * 20;
        node.y = Math.sin(angle) * radius + (Math.random() - 0.5) * 20;
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

  // ── Cluster aggregation for zoomed-out view ──
  const clusterData = useMemo(() => {
    if (graphData.nodes.length === 0) return null;
    const clusters = new Map<number, GraphNode[]>();
    for (const n of graphData.nodes) {
      const c = n.cluster ?? 0;
      if (!clusters.has(c)) clusters.set(c, []);
      clusters.get(c)!.push(n);
    }
    if (clusters.size <= 1) return null;

    const clusterNodes: GraphNode[] = [];
    const memberMap = new Map<string, number>();

    for (const [clusterId, members] of clusters) {
      memberMap.set(`cluster-${clusterId}`, clusterId);
      for (const m of members) memberMap.set(m.id, clusterId);

      const typeCounts: Record<string, number> = {};
      for (const m of members) typeCounts[m.label] = (typeCounts[m.label] ?? 0) + 1;
      const dominantType = Object.entries(typeCounts).sort((a, b) => b[1] - a[1])[0][0] as NodeType;

      const shortType = dominantType === 'StructuralPattern' ? 'Pattern'
        : dominantType === 'FailureRecord' ? 'Failure'
        : dominantType === 'UserKnowledge' ? 'Knowledge'
        : dominantType;

      let cx = 0, cy = 0, posCount = 0;
      for (const m of members) {
        if (m.x !== undefined && m.y !== undefined) {
          cx += m.x; cy += m.y; posCount++;
        }
      }

      clusterNodes.push({
        id: `cluster-${clusterId}`,
        label: dominantType,
        name: `${shortType} (${members.length})`,
        properties: { count: members.length, types: typeCounts },
        cluster: clusterId,
        ...(posCount > 0 ? { x: cx / posCount, y: cy / posCount } : {}),
      });
    }

    const clusterLinks: GraphLink[] = [];
    const linkSet = new Set<string>();
    for (const l of graphData.links) {
      const srcId = typeof l.source === 'object' ? (l.source as GraphNode).id : l.source;
      const tgtId = typeof l.target === 'object' ? (l.target as GraphNode).id : l.target;
      const srcCluster = memberMap.get(srcId);
      const tgtCluster = memberMap.get(tgtId);
      if (srcCluster !== undefined && tgtCluster !== undefined && srcCluster !== tgtCluster) {
        const key = `${Math.min(srcCluster, tgtCluster)}-${Math.max(srcCluster, tgtCluster)}`;
        if (!linkSet.has(key)) {
          linkSet.add(key);
          clusterLinks.push({
            source: `cluster-${srcCluster}`,
            target: `cluster-${tgtCluster}`,
            type: 'CLUSTER',
            properties: {},
          });
        }
      }
    }

    return { nodes: clusterNodes, links: clusterLinks };
  }, [graphData]);

  const showClusters = zoomLevel < CLUSTER_ZOOM_THRESHOLD && clusterData !== null;
  const displayData = showClusters ? clusterData! : graphData;

  // ─────────────────────────────────────────────────────────
  // Pre-render: screen-space star field + world-space fabric
  // ─────────────────────────────────────────────────────────
  const paintPre = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number) => {
      const t = timeRef.current;
      const canvas = ctx.canvas;
      const dpr = window.devicePixelRatio || 1;
      const cw = canvas.width / dpr;
      const ch = canvas.height / dpr;

      // ── Get current viewport offset for parallax ──
      // Save current world-space transform, then extract translation
      const transform = ctx.getTransform();
      const vpX = -transform.e / transform.a; // graph X at screen left
      const vpY = -transform.f / transform.d; // graph Y at screen top

      // ── Switch to screen-space for star field ──
      ctx.save();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Deep space gradient background
      const bgGrad = ctx.createRadialGradient(cw / 2, ch / 2, 0, cw / 2, ch / 2, Math.max(cw, ch) * 0.7);
      bgGrad.addColorStop(0, '#080c18');
      bgGrad.addColorStop(0.5, '#050810');
      bgGrad.addColorStop(1, '#020408');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, cw, ch);

      // Render each star layer with parallax offset
      for (const layer of STAR_LAYERS) {
        // Parallax: screen position shifts based on viewport position in graph space
        const px = (vpX * layer.parallaxFactor) % cw;
        const py = (vpY * layer.parallaxFactor) % ch;

        for (const star of layer.stars) {
          // Tile star positions across screen, offset by parallax
          let sx = ((star.x * cw * 2 - px) % cw + cw) % cw;
          let sy = ((star.y * ch * 2 - py) % ch + ch) % ch;

          // Twinkle: sinusoidal brightness oscillation
          const twinkle = 0.6 + 0.4 * Math.sin(t * star.twinkleSpeed + star.twinklePhase);
          const alpha = star.brightness * twinkle;

          const r = star.r;

          if (star.hasDiffraction && r > 0.8) {
            // ── Realistic star with diffraction spikes ──
            const spikeLen = r * 5;
            const coreAlpha = alpha;

            // Soft glow halo
            const glow = ctx.createRadialGradient(sx, sy, 0, sx, sy, r * 3);
            glow.addColorStop(0, starColor(star.temperature, coreAlpha * 0.5));
            glow.addColorStop(0.4, starColor(star.temperature, coreAlpha * 0.15));
            glow.addColorStop(1, starColor(star.temperature, 0));
            ctx.beginPath();
            ctx.arc(sx, sy, r * 3, 0, Math.PI * 2);
            ctx.fillStyle = glow;
            ctx.fill();

            // 4-point diffraction cross
            ctx.strokeStyle = starColor(star.temperature, coreAlpha * 0.4);
            ctx.lineWidth = 0.5;
            ctx.beginPath();
            ctx.moveTo(sx - spikeLen, sy);
            ctx.lineTo(sx + spikeLen, sy);
            ctx.moveTo(sx, sy - spikeLen);
            ctx.lineTo(sx, sy + spikeLen);
            ctx.stroke();

            // Bright core
            ctx.beginPath();
            ctx.arc(sx, sy, r * 0.6, 0, Math.PI * 2);
            ctx.fillStyle = starColor(star.temperature, coreAlpha);
            ctx.fill();
          } else {
            // ── Simple point star ──
            ctx.beginPath();
            ctx.arc(sx, sy, Math.max(r, 0.4), 0, Math.PI * 2);
            ctx.fillStyle = starColor(star.temperature, alpha);
            ctx.fill();
          }
        }
      }

      ctx.restore(); // back to world-space

      // ── World-space: space-time fabric near massive nodes ──
      drawSpaceFabric(ctx, graphData.nodes, globalScale);
    },
    [graphData.nodes],
  );

  // ─────────────────────────────────────────────────────────
  // Node rendering
  // ─────────────────────────────────────────────────────────
  const nodeCanvasObject = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const style = NODE_STYLES[node.label as NodeType] ?? { color: '#6B7280', borderColor: '#9CA3AF' };
      const isSelected = selectedNode?.id === node.id;
      const t = timeRef.current;

      // Breathing: subtle radius oscillation unique to each node
      const breathe = Math.sin(t * 1.2 + (node.cluster ?? 0) * 0.7) * 0.3;

      if (showClusters) {
        const count = Number(node.properties.count ?? 1);
        const baseRadius = 10 + Math.sqrt(count) * 4;
        const radius = baseRadius + breathe;
        const clusterColor = style.color;

        // Outer nebula haze
        const haze = ctx.createRadialGradient(x, y, radius * 0.6, x, y, radius * 2.5);
        haze.addColorStop(0, clusterColor + '20');
        haze.addColorStop(0.4, clusterColor + '0A');
        haze.addColorStop(1, clusterColor + '00');
        ctx.beginPath();
        ctx.arc(x, y, radius * 2.5, 0, Math.PI * 2);
        ctx.fillStyle = haze;
        ctx.fill();

        // Core gradient
        const grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
        grad.addColorStop(0, clusterColor + '60');
        grad.addColorStop(0.7, clusterColor + '25');
        grad.addColorStop(1, clusterColor + '10');
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.strokeStyle = clusterColor + '50';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Count label
        const fontSize = Math.max(12 / globalScale, 3);
        ctx.font = `bold ${fontSize}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#E5E7EB';
        ctx.fillText(String(count), x, y);

        // Type label below
        const labelSize = Math.max(9 / globalScale, 2.5);
        ctx.font = `${labelSize}px sans-serif`;
        ctx.textBaseline = 'top';
        ctx.fillStyle = clusterColor + 'CC';
        ctx.fillText(node.name, x, y + radius + 3);
        return;
      }

      const baseRadius = getNodeRadius(node);
      const radius = baseRadius + breathe * 0.5;
      const fillColor = node.label === 'Episode' ? getEpisodeColor(node) : style.color;
      const mass = getNodeMass(node);

      // Gravitational corona — scaled by node mass
      if (mass > 2) {
        const coronaR = radius + mass * 1.8;
        const corona = ctx.createRadialGradient(x, y, radius * 0.7, x, y, coronaR);
        corona.addColorStop(0, fillColor + '20');
        corona.addColorStop(0.5, fillColor + '08');
        corona.addColorStop(1, fillColor + '00');
        ctx.beginPath();
        ctx.arc(x, y, coronaR, 0, Math.PI * 2);
        ctx.fillStyle = corona;
        ctx.fill();
      }

      // Theory: confidence glow (like stellar luminosity class)
      if (node.label === 'Theory') {
        const confidence = Number(node.properties.confidence ?? 0.5);
        const glowRadius = radius + 3 + confidence * 6;
        const grad = ctx.createRadialGradient(x, y, radius * 0.8, x, y, glowRadius);
        grad.addColorStop(0, style.color + '35');
        grad.addColorStop(1, style.color + '00');
        ctx.beginPath();
        ctx.arc(x, y, glowRadius, 0, Math.PI * 2);
        ctx.fillStyle = grad;
        ctx.fill();
      }

      // Node circle
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = fillColor + 'CC';
      ctx.fill();

      // Inner highlight (Fresnel-like rim light from top-left)
      const highlight = ctx.createRadialGradient(
        x - radius * 0.3, y - radius * 0.3, radius * 0.1,
        x, y, radius,
      );
      highlight.addColorStop(0, 'rgba(255,255,255,0.15)');
      highlight.addColorStop(0.6, 'rgba(255,255,255,0)');
      highlight.addColorStop(1, 'rgba(0,0,0,0.1)');
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = highlight;
      ctx.fill();

      // Border
      ctx.strokeStyle = isSelected ? '#FFFFFF' : style.borderColor + '50';
      ctx.lineWidth = isSelected ? 1.5 : 0.5;
      ctx.stroke();

      // Selection indicator — dashed orbit ring
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(x, y, radius + 3, 0, Math.PI * 2);
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = '#FFFFFFA0';
        ctx.lineWidth = 0.8;
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // Labels
      const showLabel = isSelected || globalScale > 2.5;
      if (showLabel) {
        const maxLen = globalScale > 4 ? 20 : 12;
        const label = node.name.length > maxLen ? node.name.slice(0, maxLen - 1) + '\u2026' : node.name;
        const fontSize = Math.max(10 / globalScale, 2);
        ctx.font = `${fontSize}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillStyle = isSelected ? '#E5E7EB' : '#9CA3AF';
        ctx.fillText(label, x, y + radius + 2);
      }
    },
    [selectedNode, showClusters],
  );

  // ─────────────────────────────────────────────────────────
  // Link rendering: curved gravitational field lines
  // ─────────────────────────────────────────────────────────
  const linkCanvasObject = useCallback(
    (link: GraphLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const src = link.source as unknown as { x?: number; y?: number };
      const tgt = link.target as unknown as { x?: number; y?: number };
      if (src?.x === undefined || src?.y === undefined || tgt?.x === undefined || tgt?.y === undefined) return;

      const linkStyle = LINK_STYLES[link.type] ?? DEFAULT_LINK_STYLE;
      let width = linkStyle.width;

      if (link.type === 'CAUSES') {
        const strength = Number(link.properties.strength ?? 1);
        width = 1 + strength * 2;
      }

      // Quadratic curve: offset midpoint perpendicular to the line
      const mx = (src.x + tgt.x) / 2;
      const my = (src.y + tgt.y) / 2;
      const dx = tgt.x - src.x;
      const dy = tgt.y - src.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 0.01) return;

      const curvature = Math.min(dist * 0.08, 15);
      const cpx = mx + (-dy / dist) * curvature;
      const cpy = my + (dx / dist) * curvature;

      // Distance-based opacity (inverse-square falloff like gravity)
      const distFade = Math.max(0.2, 1 / (1 + dist * 0.003));

      ctx.beginPath();
      if (linkStyle.dashed) {
        ctx.setLineDash([4 / globalScale, 4 / globalScale]);
      } else {
        ctx.setLineDash([]);
      }
      ctx.moveTo(src.x, src.y);
      ctx.quadraticCurveTo(cpx, cpy, tgt.x, tgt.y);
      ctx.strokeStyle = linkStyle.color.replace(/[\d.]+\)$/, `${distFade})`);
      ctx.lineWidth = width / Math.max(globalScale * 0.5, 1);
      ctx.stroke();
      ctx.setLineDash([]);
    },
    [],
  );

  // ─────────────────────────────────────────────────────────
  // Click handlers
  // ─────────────────────────────────────────────────────────
  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      if (showClusters && node.id.startsWith('cluster-')) {
        const x = node.x ?? 0;
        const y = node.y ?? 0;
        fgRef.current?.centerAt(x, y, 0);
        setTimeout(() => {
          fgRef.current?.zoom(CLUSTER_ZOOM_THRESHOLD + 1.5, 500);
        }, 50);
        onClusterDrillIn?.();
        return;
      }
      onNodeClick(node);
      if (fgRef.current && node.x !== undefined && node.y !== undefined) {
        fgRef.current.centerAt(node.x, node.y, 0);
        if (zoomLevel < 4) {
          setTimeout(() => {
            fgRef.current?.zoom(5.0, 400);
          }, 50);
        }
      }
    },
    [onNodeClick, onClusterDrillIn, showClusters, zoomLevel],
  );

  const handleZoom = useCallback((transform: { k: number }) => {
    setZoomLevel(transform.k);
  }, []);

  return (
    <div ref={containerRef} className="flex-1 relative overflow-hidden">
      {graphData.nodes.length === 0 ? (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center text-gray-600">
            <p className="text-lg mb-2">No graph data loaded</p>
            <p className="text-sm">Connect to Neo4j and load an overview or run a query</p>
          </div>
        </div>
      ) : (
        <>
          <ForceGraph2D
            ref={fgRef}
            width={dimensions.width}
            height={dimensions.height}
            graphData={displayData}
            nodeId="id"
            nodeCanvasObject={nodeCanvasObject}
            nodePointerAreaPaint={(node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => {
              const r = showClusters
                ? 10 + Math.sqrt(Number(node.properties.count ?? 1)) * 4
                : getNodeRadius(node);
              ctx.beginPath();
              ctx.arc(node.x ?? 0, node.y ?? 0, r + 3, 0, Math.PI * 2);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkCanvasObject={linkCanvasObject}
            onRenderFramePre={paintPre}
            onNodeClick={handleNodeClick}
            onBackgroundClick={onBackgroundClick}
            onZoom={handleZoom}
            cooldownTicks={100}
            d3AlphaDecay={0.04}
            d3VelocityDecay={0.55}
            warmupTicks={50}
            autoPauseRedraw={false}
            linkDirectionalParticles={(link: GraphLink) => (link.type === 'CAUSES' ? 3 : 0)}
            linkDirectionalParticleWidth={2}
            linkDirectionalParticleColor={(link: GraphLink) =>
              LINK_STYLES[link.type]?.color ?? DEFAULT_LINK_STYLE.color
            }
            backgroundColor="transparent"
            enableNodeDrag={true}
          />
          <div className="absolute bottom-4 right-4 text-xs text-gray-600 bg-gray-900/60 px-2 py-1 rounded">
            {zoomLevel.toFixed(1)}x {showClusters ? '(clusters)' : ''}
          </div>
        </>
      )}
    </div>
  );
}
