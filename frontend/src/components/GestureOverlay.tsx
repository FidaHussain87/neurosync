import { useRef, useEffect, useCallback } from 'react';
import type { DetectedHand } from '../gestures/types';
import { HAND_CONNECTIONS, NEON_COLORS, VISUALS } from '../gestures/constants';
import { FINGER_TIPS } from '../gestures/types';

interface Props {
  hands: DetectedHand[];
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  width: number;
  height: number;
}

/** Particle state for neon line animation */
interface Particle {
  progress: number; // 0-1 along the line
  fingerIndex: number;
}

/**
 * Renders hand skeleton and neon finger connection lines on a 2D canvas overlay.
 * Draws each frame via requestAnimationFrame for smooth animation.
 */
export default function GestureOverlay({ hands, canvasRef, width, height }: Props) {
  const particlesRef = useRef<Particle[]>([]);
  const animFrameRef = useRef<number | null>(null);
  const handsRef = useRef<DetectedHand[]>(hands);

  // Keep hands ref in sync
  handsRef.current = hands;

  // Initialize particles
  useEffect(() => {
    const particles: Particle[] = [];
    for (let f = 0; f < 5; f++) {
      for (let p = 0; p < VISUALS.PARTICLES_PER_LINE; p++) {
        particles.push({
          progress: (p / VISUALS.PARTICLES_PER_LINE),
          fingerIndex: f,
        });
      }
    }
    particlesRef.current = particles;
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const currentHands = handsRef.current;

    // Clear
    ctx.clearRect(0, 0, width, height);

    if (currentHands.length === 0) return;

    // Draw skeleton for each hand
    for (const hand of currentHands) {
      drawSkeleton(ctx, hand.landmarks, width, height);
      drawLandmarkDots(ctx, hand.landmarks, width, height);
    }

    // Draw neon connecting lines between matching fingertips (both hands)
    if (currentHands.length >= 2) {
      drawNeonLines(ctx, currentHands[0], currentHands[1], width, height);
      drawParticles(ctx, currentHands[0], currentHands[1], width, height, particlesRef.current);

      // Advance particles
      for (const particle of particlesRef.current) {
        particle.progress += VISUALS.PARTICLE_SPEED / 60; // assuming ~60fps
        if (particle.progress > 1) particle.progress -= 1;
      }
    }
  }, [canvasRef, width, height]);

  // Animation loop
  useEffect(() => {
    let running = true;

    const loop = () => {
      if (!running) return;
      draw();
      animFrameRef.current = requestAnimationFrame(loop);
    };

    animFrameRef.current = requestAnimationFrame(loop);

    return () => {
      running = false;
      if (animFrameRef.current !== null) {
        cancelAnimationFrame(animFrameRef.current);
      }
    };
  }, [draw]);

  return null; // Renders directly to the canvas ref
}

// ─── Drawing Functions ─────────────────────────────────────────────────

function drawSkeleton(
  ctx: CanvasRenderingContext2D,
  landmarks: DetectedHand['landmarks'],
  w: number,
  h: number,
) {
  ctx.strokeStyle = VISUALS.SKELETON_COLOR;
  ctx.lineWidth = VISUALS.SKELETON_WIDTH;
  ctx.lineCap = 'round';

  for (const [start, end] of HAND_CONNECTIONS) {
    const p1 = landmarks[start];
    const p2 = landmarks[end];
    ctx.beginPath();
    ctx.moveTo(p1.x * w, p1.y * h);
    ctx.lineTo(p2.x * w, p2.y * h);
    ctx.stroke();
  }
}

function drawLandmarkDots(
  ctx: CanvasRenderingContext2D,
  landmarks: DetectedHand['landmarks'],
  w: number,
  h: number,
) {
  const tipSet = new Set(FINGER_TIPS);

  for (let i = 0; i < landmarks.length; i++) {
    const lm = landmarks[i];
    const isTip = tipSet.has(i as any);
    const radius = isTip ? VISUALS.FINGERTIP_RADIUS : VISUALS.LANDMARK_RADIUS;

    // Fingertips get neon colors
    if (isTip) {
      const fingerIdx = FINGER_TIPS.indexOf(i as any);
      ctx.fillStyle = NEON_COLORS[fingerIdx] ?? '#FFFFFF';
      ctx.shadowColor = NEON_COLORS[fingerIdx] ?? '#FFFFFF';
      ctx.shadowBlur = 8;
    } else {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
    }

    ctx.beginPath();
    ctx.arc(lm.x * w, lm.y * h, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  // Reset shadow
  ctx.shadowColor = 'transparent';
  ctx.shadowBlur = 0;
}

function drawNeonLines(
  ctx: CanvasRenderingContext2D,
  hand0: DetectedHand,
  hand1: DetectedHand,
  w: number,
  h: number,
) {
  ctx.lineCap = 'round';

  for (let i = 0; i < FINGER_TIPS.length; i++) {
    const tipIdx = FINGER_TIPS[i];
    const p1 = hand0.landmarks[tipIdx];
    const p2 = hand1.landmarks[tipIdx];
    const color = NEON_COLORS[i];

    const x1 = p1.x * w;
    const y1 = p1.y * h;
    const x2 = p2.x * w;
    const y2 = p2.y * h;

    // Outer glow layer
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.strokeStyle = color;
    ctx.lineWidth = VISUALS.NEON_LINE_WIDTH + 4;
    ctx.shadowColor = color;
    ctx.shadowBlur = VISUALS.NEON_OUTER_GLOW_BLUR;
    ctx.globalAlpha = 0.3;
    ctx.stroke();

    // Inner bright line
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.strokeStyle = color;
    ctx.lineWidth = VISUALS.NEON_LINE_WIDTH;
    ctx.shadowColor = color;
    ctx.shadowBlur = VISUALS.NEON_GLOW_BLUR;
    ctx.globalAlpha = 0.9;
    ctx.stroke();

    // Core white line (bright center)
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.strokeStyle = '#FFFFFF';
    ctx.lineWidth = 1;
    ctx.shadowColor = color;
    ctx.shadowBlur = 5;
    ctx.globalAlpha = 0.7;
    ctx.stroke();

    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
  }
}

function drawParticles(
  ctx: CanvasRenderingContext2D,
  hand0: DetectedHand,
  hand1: DetectedHand,
  w: number,
  h: number,
  particles: Particle[],
) {
  for (const particle of particles) {
    const tipIdx = FINGER_TIPS[particle.fingerIndex];
    const p1 = hand0.landmarks[tipIdx];
    const p2 = hand1.landmarks[tipIdx];
    const color = NEON_COLORS[particle.fingerIndex];

    // Interpolate position along the line
    const x = (p1.x + (p2.x - p1.x) * particle.progress) * w;
    const y = (p1.y + (p2.y - p1.y) * particle.progress) * h;

    // Particle with glow
    ctx.beginPath();
    ctx.arc(x, y, VISUALS.PARTICLE_RADIUS, 0, Math.PI * 2);
    ctx.fillStyle = '#FFFFFF';
    ctx.shadowColor = color;
    ctx.shadowBlur = 12;
    ctx.globalAlpha = 0.9;
    ctx.fill();

    // Trailing glow
    const trailProgress = particle.progress - 0.05;
    if (trailProgress > 0) {
      const tx = (p1.x + (p2.x - p1.x) * trailProgress) * w;
      const ty = (p1.y + (p2.y - p1.y) * trailProgress) * h;
      ctx.beginPath();
      ctx.arc(tx, ty, VISUALS.PARTICLE_RADIUS * 0.6, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.4;
      ctx.fill();
    }

    ctx.globalAlpha = 1;
    ctx.shadowBlur = 0;
  }
}
