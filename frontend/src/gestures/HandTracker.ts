import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision';
import type { DetectedHand, HandTrackingResult, TrackerState } from './types';
import { PERFORMANCE } from './constants';
import { EMAFilter } from './smoothing';

const WASM_CDN = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm';
const MODEL_CDN = 'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task';

export type TrackerCallback = (result: HandTrackingResult) => void;
export type StateCallback = (state: TrackerState) => void;

/**
 * Wraps MediaPipe HandLandmarker with webcam access and a RAF detection loop.
 * Runs detection at ~30fps and emits smoothed landmark results.
 */
export class HandTracker {
  private handLandmarker: HandLandmarker | null = null;
  private videoElement: HTMLVideoElement | null = null;
  private stream: MediaStream | null = null;
  private animFrameId: number | null = null;
  private lastDetectionTime = 0;
  private state: TrackerState = 'idle';

  private onResult: TrackerCallback | null = null;
  private onStateChange: StateCallback | null = null;

  // One EMA filter per hand (indexed by handedness)
  private filters: Map<string, EMAFilter> = new Map();
  private smoothingAlpha = 0.5; // Higher = more responsive, lower = smoother

  /** Current detection interval (adaptive) */
  private detectionInterval: number = PERFORMANCE.DETECTION_INTERVAL_MS;

  constructor() {
    this.filters.set('Left', new EMAFilter(this.smoothingAlpha));
    this.filters.set('Right', new EMAFilter(this.smoothingAlpha));
  }

  /** Set callback for tracking results */
  setOnResult(cb: TrackerCallback): void {
    this.onResult = cb;
  }

  /** Set callback for state changes */
  setOnStateChange(cb: StateCallback): void {
    this.onStateChange = cb;
  }

  /** Get current tracker state */
  getState(): TrackerState {
    return this.state;
  }

  /** Initialize MediaPipe model (downloads WASM + model) */
  async init(): Promise<void> {
    this.setState('loading');
    try {
      const vision = await FilesetResolver.forVisionTasks(WASM_CDN);
      this.handLandmarker = await HandLandmarker.createFromOptions(vision, {
        baseOptions: {
          modelAssetPath: MODEL_CDN,
          delegate: 'GPU',
        },
        numHands: PERFORMANCE.MAX_HANDS,
        runningMode: 'VIDEO',
        minHandDetectionConfidence: PERFORMANCE.MIN_DETECTION_CONFIDENCE,
        minTrackingConfidence: PERFORMANCE.MIN_TRACKING_CONFIDENCE,
        minHandPresenceConfidence: PERFORMANCE.MIN_TRACKING_CONFIDENCE,
      });
      this.setState('ready');
    } catch (err) {
      console.error('[HandTracker] Failed to initialize:', err);
      this.setState('error');
      throw err;
    }
  }

  /** Start webcam and begin detection loop */
  async start(videoElement: HTMLVideoElement): Promise<void> {
    if (!this.handLandmarker) {
      throw new Error('HandTracker not initialized. Call init() first.');
    }

    this.videoElement = videoElement;

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 640 },
          height: { ideal: 480 },
          facingMode: 'user',
          frameRate: { ideal: 30 },
        },
      });

      videoElement.srcObject = this.stream;
      await videoElement.play();

      this.setState('active');
      this.startDetectionLoop();
    } catch (err) {
      console.error('[HandTracker] Camera access denied:', err);
      this.setState('error');
      throw err;
    }
  }

  /** Stop detection and release camera */
  stop(): void {
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }

    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
      this.stream = null;
    }

    if (this.videoElement) {
      this.videoElement.srcObject = null;
      this.videoElement = null;
    }

    this.filters.forEach(f => f.reset());
    this.setState('ready');
  }

  /** Destroy tracker entirely (release model) */
  destroy(): void {
    this.stop();
    if (this.handLandmarker) {
      this.handLandmarker.close();
      this.handLandmarker = null;
    }
    this.setState('idle');
  }

  /** Adjust detection frequency for performance */
  setSlowMode(slow: boolean): void {
    this.detectionInterval = slow
      ? PERFORMANCE.DETECTION_INTERVAL_SLOW_MS
      : PERFORMANCE.DETECTION_INTERVAL_MS;
  }

  /** Adjust smoothing (0 = max smooth, 1 = no smooth) */
  setSmoothingAlpha(alpha: number): void {
    this.smoothingAlpha = alpha;
    this.filters.forEach(f => f.setAlpha(alpha));
  }

  private setState(state: TrackerState): void {
    this.state = state;
    this.onStateChange?.(state);
  }

  private startDetectionLoop(): void {
    const detect = (now: number) => {
      this.animFrameId = requestAnimationFrame(detect);

      if (now - this.lastDetectionTime < this.detectionInterval) return;
      if (!this.videoElement || !this.handLandmarker) return;
      if (this.videoElement.readyState < 2) return; // HAVE_CURRENT_DATA

      this.lastDetectionTime = now;

      const results = this.handLandmarker.detectForVideo(this.videoElement, now);

      const hands: DetectedHand[] = [];

      if (results.landmarks && results.landmarks.length > 0) {
        for (let i = 0; i < results.landmarks.length; i++) {
          const handedness = results.handednesses?.[i]?.[0]?.categoryName as 'Left' | 'Right' ?? 'Right';

          // Apply EMA smoothing
          const filter = this.filters.get(handedness);
          const smoothedLandmarks = filter
            ? filter.update(results.landmarks[i])
            : results.landmarks[i];

          hands.push({
            landmarks: smoothedLandmarks,
            worldLandmarks: results.worldLandmarks?.[i] ?? results.landmarks[i],
            handedness,
          });
        }
      } else {
        // No hands detected - reset filters
        this.filters.forEach(f => f.reset());
      }

      this.onResult?.({ hands, timestamp: now });
    };

    this.animFrameId = requestAnimationFrame(detect);
  }
}
