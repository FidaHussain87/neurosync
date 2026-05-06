import type { Landmark, HandLandmarks } from './types';

/**
 * Exponential Moving Average filter for reducing jitter in landmark positions.
 * Lower alpha = more smoothing (more lag), higher alpha = less smoothing (more responsive).
 */
export class EMAFilter {
  private state: HandLandmarks | null = null;
  private alpha: number;

  constructor(alpha: number = 0.4) {
    this.alpha = alpha;
  }

  /** Update with new landmarks and return smoothed result */
  update(landmarks: HandLandmarks): HandLandmarks {
    if (!this.state) {
      this.state = landmarks.map(l => ({ ...l }));
      return this.state;
    }

    this.state = this.state.map((prev, i) => {
      const curr = landmarks[i];
      return {
        x: prev.x + this.alpha * (curr.x - prev.x),
        y: prev.y + this.alpha * (curr.y - prev.y),
        z: prev.z + this.alpha * (curr.z - prev.z),
        visibility: curr.visibility,
      };
    });

    return this.state;
  }

  /** Reset filter state (call when hand is lost and re-detected) */
  reset(): void {
    this.state = null;
  }

  /** Update smoothing factor */
  setAlpha(alpha: number): void {
    this.alpha = Math.max(0, Math.min(1, alpha));
  }
}

/** Linear interpolation */
export function lerp(a: number, b: number, t: number): number {
  return a + (a - b) * -t;
}

/** 3D distance between two landmarks */
export function distance3D(a: Landmark, b: Landmark): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = a.z - b.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

/** 2D distance between two landmarks (ignoring z) */
export function distance2D(a: Landmark, b: Landmark): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/** Midpoint between two landmarks */
export function midpoint(a: Landmark, b: Landmark): Landmark {
  return {
    x: (a.x + b.x) / 2,
    y: (a.y + b.y) / 2,
    z: (a.z + b.z) / 2,
  };
}

/** Calculate palm center (average of wrist + finger MCPs) */
export function palmCenter(landmarks: HandLandmarks): Landmark {
  const indices = [0, 5, 9, 13, 17]; // wrist + 4 finger bases
  let x = 0, y = 0, z = 0;
  for (const i of indices) {
    x += landmarks[i].x;
    y += landmarks[i].y;
    z += landmarks[i].z;
  }
  const n = indices.length;
  return { x: x / n, y: y / n, z: z / n };
}

/** Velocity tracker - tracks position over time to compute velocity */
export class VelocityTracker {
  private history: Array<{ x: number; y: number; t: number }> = [];
  private maxHistory = 5;

  push(x: number, y: number, t: number): void {
    this.history.push({ x, y, t });
    if (this.history.length > this.maxHistory) {
      this.history.shift();
    }
  }

  /** Get velocity in normalized units per millisecond */
  getVelocity(): { vx: number; vy: number; speed: number } {
    if (this.history.length < 2) return { vx: 0, vy: 0, speed: 0 };

    const newest = this.history[this.history.length - 1];
    const oldest = this.history[0];
    const dt = newest.t - oldest.t;
    if (dt === 0) return { vx: 0, vy: 0, speed: 0 };

    const vx = (newest.x - oldest.x) / dt;
    const vy = (newest.y - oldest.y) / dt;
    return { vx, vy, speed: Math.sqrt(vx * vx + vy * vy) };
  }

  reset(): void {
    this.history = [];
  }
}

/**
 * One-Euro Filter - adaptive smoothing that increases responsiveness
 * during fast movements and smoothness during slow movements.
 */
export class OneEuroFilter {
  private freq: number;
  private minCutoff: number;
  private beta: number;
  private dCutoff: number;
  private xPrev: number | null = null;
  private dxPrev: number = 0;
  private tPrev: number | null = null;

  constructor(freq: number = 30, minCutoff: number = 1.0, beta: number = 0.007, dCutoff: number = 1.0) {
    this.freq = freq;
    this.minCutoff = minCutoff;
    this.beta = beta;
    this.dCutoff = dCutoff;
  }

  private alpha(cutoff: number): number {
    const tau = 1.0 / (2 * Math.PI * cutoff);
    const te = 1.0 / this.freq;
    return 1.0 / (1.0 + tau / te);
  }

  filter(x: number, t?: number): number {
    if (this.xPrev === null) {
      this.xPrev = x;
      this.tPrev = t ?? null;
      return x;
    }

    if (t !== undefined && this.tPrev !== null) {
      this.freq = 1.0 / ((t - this.tPrev) / 1000);
    }
    this.tPrev = t ?? this.tPrev;

    const dx = (x - this.xPrev) * this.freq;
    const edx = this.alpha(this.dCutoff) * dx + (1 - this.alpha(this.dCutoff)) * this.dxPrev;
    this.dxPrev = edx;

    const cutoff = this.minCutoff + this.beta * Math.abs(edx);
    const result = this.alpha(cutoff) * x + (1 - this.alpha(cutoff)) * this.xPrev;
    this.xPrev = result;

    return result;
  }

  reset(): void {
    this.xPrev = null;
    this.dxPrev = 0;
    this.tPrev = null;
  }
}
