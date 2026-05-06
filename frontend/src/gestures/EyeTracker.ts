import { FilesetResolver, FaceLandmarker } from '@mediapipe/tasks-vision';
import type { Landmark } from './types';

const WASM_CDN = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm';
const MODEL_CDN = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task';

/** Iris landmark indices in MediaPipe FaceLandmarker (468 + 10 iris landmarks) */
const LEFT_IRIS_CENTER = 468; // Left iris center (indices 468-472)
const RIGHT_IRIS_CENTER = 473; // Right iris center (indices 473-477)

/** Eye corner landmarks for computing gaze direction */
const LEFT_EYE_INNER = 133;
const LEFT_EYE_OUTER = 33;
const RIGHT_EYE_INNER = 362;
const RIGHT_EYE_OUTER = 263;

/** Eyelid landmarks for vertical tracking */
const LEFT_EYE_UPPER = 159;  // Upper eyelid center
const LEFT_EYE_LOWER = 145;  // Lower eyelid center
const RIGHT_EYE_UPPER = 386; // Upper eyelid center
const RIGHT_EYE_LOWER = 374; // Lower eyelid center

/** Head pose landmarks (nose tip, forehead, chin) for head compensation */
const NOSE_TIP = 1;
const FOREHEAD = 10;
const CHIN = 152;

export interface GazePoint {
  /** Normalized screen x (0-1, 0=left) */
  x: number;
  /** Normalized screen y (0-1, 0=top) */
  y: number;
  /** Confidence that the gaze point is valid */
  confidence: number;
}

export type EyeTrackerCallback = (gaze: GazePoint) => void;

/** Calibration sample: raw iris ratio → known screen position */
interface CalibrationSample {
  rawX: number;
  rawY: number;
  screenX: number;
  screenY: number;
}

/** Affine transform coefficients: outX = ax*inX + bx*inY + cx */
interface AffineTransform {
  ax: number; bx: number; cx: number;
  ay: number; by: number; cy: number;
}

const CALIBRATION_STORAGE_KEY = 'neurosync_gaze_calibration';

/**
 * Eye/gaze tracker using MediaPipe FaceLandmarker iris detection.
 * Provides a normalized gaze point estimate based on iris position
 * relative to eye corners (similar to Vision Pro eye tracking).
 */
export class EyeTracker {
  private faceLandmarker: FaceLandmarker | null = null;
  private initPromise: Promise<void> | null = null;
  private pendingVideoElement: HTMLVideoElement | null = null;
  private onGaze: EyeTrackerCallback | null = null;
  private running = false;
  private animFrameId: number | null = null;
  private lastDetectionTime = 0;
  private detectionInterval = 33; // ~30fps for smoother tracking

  // Multi-point calibration (affine transform)
  private calibrationTransform: AffineTransform | null = null;
  private calibrationSamples: CalibrationSample[] = [];
  private isCollectingSample = false;
  private sampleBuffer: Array<{ x: number; y: number }> = [];

  // Legacy offset (used if no multi-point calibration)
  private calibrationOffsetX = 0;
  private calibrationOffsetY = 0;

  // Head pose baseline (established during calibration)
  private baseHeadX = 0;
  private baseHeadY = 0;
  private headCalibrated = false;

  // Double smoothing: fast filter + slow stabilizer
  private smoothX = 0.5;
  private smoothY = 0.5;
  private stableX = 0.5;
  private stableY = 0.5;
  private smoothAlpha = 0.25; // Fast response filter
  private stableAlpha = 0.12; // Slow stabilizer for steady gaze


  // Confidence tracking
  private consecutiveDetections = 0;
  private lastConfidence = 0;

  setOnGaze(cb: EyeTrackerCallback): void {
    this.onGaze = cb;
  }

  async init(): Promise<void> {
    this.initPromise = this._doInit();
    return this.initPromise;
  }

  private async _doInit(): Promise<void> {
    const vision = await FilesetResolver.forVisionTasks(WASM_CDN);
    // Use CPU delegate to avoid GPU context conflict with HandLandmarker
    this.faceLandmarker = await FaceLandmarker.createFromOptions(vision, {
      baseOptions: {
        modelAssetPath: MODEL_CDN,
        delegate: 'CPU',
      },
      runningMode: 'VIDEO',
      numFaces: 1,
      outputFacialTransformationMatrixes: false,
      outputFaceBlendshapes: false,
    });
    console.log('[EyeTracker] FaceLandmarker initialized (CPU delegate)');
    // If start() was called while init was in progress, start now
    if (this.pendingVideoElement) {
      const el = this.pendingVideoElement;
      this.pendingVideoElement = null;
      this.startDetectionLoop(el);
    }
  }

  /** Start eye tracking on the same video element as hand tracker */
  start(videoElement: HTMLVideoElement): void {
    if (!this.faceLandmarker) {
      // Init still in progress — queue for when it completes
      this.pendingVideoElement = videoElement;
      return;
    }
    // Stop any existing loop before starting a new one
    if (this.running) {
      this.running = false;
      if (this.animFrameId !== null) {
        cancelAnimationFrame(this.animFrameId);
        this.animFrameId = null;
      }
    }
    this.startDetectionLoop(videoElement);
  }

  private startDetectionLoop(videoElement: HTMLVideoElement): void {
    this.running = true;
    this.lastDetectionTime = 0;
    let loggedOnce = false;
    let frameCount = 0;
    let lastTimestamp = -1;

    // Use an off-screen HTMLCanvasElement to snapshot the video frame before
    // passing to FaceLandmarker. This avoids GPU texture conflicts with the
    // HandLandmarker which reads the same video element on its own RAF loop.
    let snapshotCanvas: HTMLCanvasElement | null = null;
    let snapshotCtx: CanvasRenderingContext2D | null = null;

    console.log('[EyeTracker] Detection loop started, video readyState:', videoElement?.readyState);

    const detect = () => {
      if (!this.running) return;
      this.animFrameId = requestAnimationFrame(detect);

      const now = performance.now();
      if (now - this.lastDetectionTime < this.detectionInterval) return;

      if (!videoElement || videoElement.readyState < 2) {
        if (frameCount < 3) {
          console.log(`[EyeTracker] Waiting for video readyState (current: ${videoElement?.readyState})`);
        }
        return;
      }

      // Lazily create snapshot canvas matching video dimensions
      const vw = videoElement.videoWidth || 640;
      const vh = videoElement.videoHeight || 480;
      if (!snapshotCanvas || snapshotCanvas.width !== vw || snapshotCanvas.height !== vh) {
        snapshotCanvas = document.createElement('canvas');
        snapshotCanvas.width = vw;
        snapshotCanvas.height = vh;
        snapshotCtx = snapshotCanvas.getContext('2d');
        console.log(`[EyeTracker] Created snapshot canvas ${vw}x${vh}`);
      }

      if (!snapshotCtx) return;

      // Draw current video frame to snapshot canvas
      snapshotCtx.drawImage(videoElement, 0, 0, vw, vh);

      this.lastDetectionTime = now;

      // Strictly increasing timestamp for MediaPipe
      const timestamp = Math.max(Math.round(now), lastTimestamp + 1);
      lastTimestamp = timestamp;

      frameCount++;
      let results;
      try {
        results = this.faceLandmarker!.detectForVideo(snapshotCanvas, timestamp);
      } catch (e) {
        if (frameCount <= 5) console.warn('[EyeTracker] detectForVideo error:', e);
        return;
      }

      if (results.faceLandmarks && results.faceLandmarks.length > 0) {
        const landmarks = results.faceLandmarks[0];

        if (!loggedOnce) {
          console.log(`[EyeTracker] Face detected! ${landmarks.length} landmarks (frame ${frameCount})`);
          loggedOnce = true;
        }

        const gaze = this.computeGaze(landmarks);
        if (gaze) {
          this.consecutiveDetections++;

          // Collect sample if in calibration mode
          if (this.isCollectingSample) {
            this.sampleBuffer.push({ x: gaze.x, y: gaze.y });
          }

          // Apply calibration: affine transform (multi-point) or simple offset
          let targetX: number;
          let targetY: number;
          if (this.calibrationTransform) {
            const t = this.calibrationTransform;
            targetX = t.ax * gaze.x + t.bx * gaze.y + t.cx;
            targetY = t.ay * gaze.x + t.by * gaze.y + t.cy;
          } else {
            targetX = gaze.x + this.calibrationOffsetX;
            targetY = gaze.y + this.calibrationOffsetY;
          }

          // Two-stage smoothing:
          // Stage 1: responsive filter (tracks movement quickly)
          this.smoothX += this.smoothAlpha * (targetX - this.smoothX);
          this.smoothY += this.smoothAlpha * (targetY - this.smoothY);

          // Stage 2: stability filter (reduces jitter when holding gaze steady)
          const moveDist = Math.sqrt(
            (this.smoothX - this.stableX) ** 2 +
            (this.smoothY - this.stableY) ** 2,
          );
          const adaptiveAlpha = moveDist > 0.05
            ? Math.min(0.4, this.stableAlpha + moveDist * 2)
            : this.stableAlpha;

          this.stableX += adaptiveAlpha * (this.smoothX - this.stableX);
          this.stableY += adaptiveAlpha * (this.smoothY - this.stableY);

          // Confidence ramps up over consecutive detections
          const rampConfidence = Math.min(1, this.consecutiveDetections / 5);
          this.lastConfidence = gaze.confidence * rampConfidence;

          this.onGaze?.({
            x: Math.max(0, Math.min(1, this.stableX)),
            y: Math.max(0, Math.min(1, this.stableY)),
            confidence: this.lastConfidence,
          });
        } else {
          this.consecutiveDetections = 0;
        }
      } else {
        this.consecutiveDetections = 0;
        if (frameCount <= 10) {
          console.log(`[EyeTracker] Frame ${frameCount}: no face detected`);
        }
      }
    };

    this.animFrameId = requestAnimationFrame(detect);
  }

  stop(): void {
    this.running = false;
    this.pendingVideoElement = null;
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
  }

  destroy(): void {
    this.stop();
    this.faceLandmarker?.close();
    this.faceLandmarker = null;
  }

  /** Simple center calibrate (legacy fallback) */
  calibrate(): void {
    this.calibrationOffsetX = 0.5 - this.stableX;
    this.calibrationOffsetY = 0.5 - this.stableY;
    this.headCalibrated = false;
  }

  /**
   * Start collecting a calibration sample.
   * Call this when the user is looking at a known screen point.
   * After ~30 frames, call finishSample(screenX, screenY) to record it.
   */
  startCollectingSample(): void {
    this.isCollectingSample = true;
    this.sampleBuffer = [];
  }

  /**
   * Finish collecting a sample. Averages the raw gaze readings
   * and maps them to the known screen position.
   */
  finishSample(screenX: number, screenY: number): boolean {
    this.isCollectingSample = false;
    console.log(`[EyeTracker] finishSample: collected ${this.sampleBuffer.length} samples`);

    if (this.sampleBuffer.length < 2) return false;

    // Use all samples if we got very few; otherwise trim outliers
    let trimmed: Array<{ x: number; y: number }>;
    if (this.sampleBuffer.length <= 5) {
      trimmed = this.sampleBuffer;
    } else {
      trimmed = this.sampleBuffer.slice(
        Math.floor(this.sampleBuffer.length * 0.15),
        Math.floor(this.sampleBuffer.length * 0.85),
      );
    }
    if (trimmed.length < 1) return false;

    const avgX = trimmed.reduce((s, p) => s + p.x, 0) / trimmed.length;
    const avgY = trimmed.reduce((s, p) => s + p.y, 0) / trimmed.length;

    this.calibrationSamples.push({ rawX: avgX, rawY: avgY, screenX, screenY });
    console.log(`[EyeTracker] Calibration point ${this.calibrationSamples.length}: raw(${avgX.toFixed(3)}, ${avgY.toFixed(3)}) → screen(${screenX.toFixed(2)}, ${screenY.toFixed(2)})`);
    return true;
  }

  /** Reset calibration and start fresh */
  resetCalibration(): void {
    this.calibrationSamples = [];
    this.calibrationTransform = null;
    this.calibrationOffsetX = 0;
    this.calibrationOffsetY = 0;
    this.headCalibrated = false;
    this.smoothX = 0.5;
    this.smoothY = 0.5;
    this.stableX = 0.5;
    this.stableY = 0.5;
    try { localStorage.removeItem(CALIBRATION_STORAGE_KEY); } catch { /* */ }
  }

  /** How many calibration points collected so far */
  getCalibrationPointCount(): number {
    return this.calibrationSamples.length;
  }

  /**
   * Compute the affine calibration transform from collected samples.
   * Needs at least 3 points (ideally 5-9 for good coverage).
   * Persists to localStorage for next session.
   */
  finalizeCalibration(): boolean {
    console.log(`[EyeTracker] finalizeCalibration: ${this.calibrationSamples.length} samples collected`);
    if (this.calibrationSamples.length < 3) {
      console.warn(`[EyeTracker] Not enough samples (need 3, got ${this.calibrationSamples.length})`);
      return false;
    }

    const transform = this.computeAffineTransform(this.calibrationSamples);
    if (!transform) {
      console.warn('[EyeTracker] Affine transform computation failed (degenerate matrix)');
      return false;
    }

    this.calibrationTransform = transform;
    this.headCalibrated = false; // reset head baseline for clean start

    // Reset smoothing so it starts fresh with calibrated values
    this.smoothX = 0.5;
    this.smoothY = 0.5;
    this.stableX = 0.5;
    this.stableY = 0.5;

    // Persist to localStorage
    try {
      localStorage.setItem(CALIBRATION_STORAGE_KEY, JSON.stringify({
        transform,
        samples: this.calibrationSamples,
        timestamp: Date.now(),
      }));
    } catch { /* storage may be unavailable */ }

    return true;
  }

  /** Load calibration from localStorage (call after init) */
  loadCalibration(): boolean {
    try {
      const stored = localStorage.getItem(CALIBRATION_STORAGE_KEY);
      if (!stored) return false;
      const data = JSON.parse(stored);
      // Reject calibrations older than 7 days
      if (Date.now() - data.timestamp > 7 * 24 * 60 * 60 * 1000) {
        localStorage.removeItem(CALIBRATION_STORAGE_KEY);
        return false;
      }
      if (data.transform) {
        this.calibrationTransform = data.transform;
        this.calibrationSamples = data.samples ?? [];
        return true;
      }
    } catch { /* */ }
    return false;
  }

  /** Whether a valid calibration is loaded */
  isCalibrated(): boolean {
    return this.calibrationTransform !== null;
  }

  /**
   * Least-squares affine transform fitting.
   * Solves: screenX = ax*rawX + bx*rawY + cx
   *         screenY = ay*rawX + by*rawY + cy
   */
  private computeAffineTransform(samples: CalibrationSample[]): AffineTransform | null {
    const n = samples.length;
    if (n < 3) return null;

    // Build matrices for least-squares: A * params = B
    // A = [[rawX, rawY, 1], ...], B_x = [screenX, ...], B_y = [screenY, ...]
    // Solve separately for X and Y transforms

    let sumX = 0, sumY = 0, sumXX = 0, sumYY = 0, sumXY = 0;
    let sumSxX = 0, sumSxY = 0, sumSx = 0;
    let sumSyX = 0, sumSyY = 0, sumSy = 0;

    for (const s of samples) {
      sumX += s.rawX;
      sumY += s.rawY;
      sumXX += s.rawX * s.rawX;
      sumYY += s.rawY * s.rawY;
      sumXY += s.rawX * s.rawY;
      sumSxX += s.screenX * s.rawX;
      sumSxY += s.screenX * s.rawY;
      sumSx += s.screenX;
      sumSyX += s.screenY * s.rawX;
      sumSyY += s.screenY * s.rawY;
      sumSy += s.screenY;
    }

    // Solve 3x3 system using Cramer's rule
    // [sumXX, sumXY, sumX] [ax]   [sumSxX]
    // [sumXY, sumYY, sumY] [bx] = [sumSxY]
    // [sumX,  sumY,  n   ] [cx]   [sumSx ]

    const det = sumXX * (sumYY * n - sumY * sumY)
              - sumXY * (sumXY * n - sumY * sumX)
              + sumX * (sumXY * sumY - sumYY * sumX);

    if (Math.abs(det) < 1e-10) return null;

    const ax = (sumSxX * (sumYY * n - sumY * sumY)
              - sumXY * (sumSxY * n - sumY * sumSx)
              + sumX * (sumSxY * sumY - sumYY * sumSx)) / det;

    const bx = (sumXX * (sumSxY * n - sumY * sumSx)
              - sumSxX * (sumXY * n - sumY * sumX)
              + sumX * (sumXY * sumSx - sumSxY * sumX)) / det;

    const cx = (sumXX * (sumYY * sumSx - sumY * sumSxY)
              - sumXY * (sumXY * sumSx - sumY * sumSxX)
              + sumSxX * (sumXY * sumY - sumYY * sumX)) / det;

    const ay = (sumSyX * (sumYY * n - sumY * sumY)
              - sumXY * (sumSyY * n - sumY * sumSy)
              + sumX * (sumSyY * sumY - sumYY * sumSy)) / det;

    const by = (sumXX * (sumSyY * n - sumY * sumSy)
              - sumSyX * (sumXY * n - sumY * sumX)
              + sumX * (sumXY * sumSy - sumSyY * sumX)) / det;

    const cy = (sumXX * (sumYY * sumSy - sumY * sumSyY)
              - sumXY * (sumXY * sumSy - sumY * sumSyX)
              + sumSyX * (sumXY * sumY - sumYY * sumX)) / det;

    return { ax, bx, cx, ay, by, cy };
  }

  /**
   * Compute gaze point from iris position relative to eye boundaries.
   * Uses eyelids for vertical accuracy and head pose compensation.
   * Falls back to eye-corner-only method if iris landmarks unavailable.
   * Returns normalized 0-1 coordinates where (0.5, 0.5) = center.
   */
  private computeGaze(landmarks: Landmark[]): GazePoint | null {
    // Need at least basic face landmarks (468)
    if (landmarks.length < 468) return null;

    const hasIris = landmarks.length >= 478;

    // Get eye corners for reference frame
    const leftInner = landmarks[LEFT_EYE_INNER];
    const leftOuter = landmarks[LEFT_EYE_OUTER];
    const rightInner = landmarks[RIGHT_EYE_INNER];
    const rightOuter = landmarks[RIGHT_EYE_OUTER];

    // Get eyelids for vertical reference
    const leftUpper = landmarks[LEFT_EYE_UPPER];
    const leftLower = landmarks[LEFT_EYE_LOWER];
    const rightUpper = landmarks[RIGHT_EYE_UPPER];
    const rightLower = landmarks[RIGHT_EYE_LOWER];

    // Compute eye dimensions
    const leftEyeWidth = distance(leftInner, leftOuter);
    const rightEyeWidth = distance(rightInner, rightOuter);
    const leftEyeHeight = Math.abs(leftUpper.y - leftLower.y);
    const rightEyeHeight = Math.abs(rightUpper.y - rightLower.y);

    if (leftEyeWidth < 0.001 || rightEyeWidth < 0.001) return null;

    let avgX: number;
    let avgY: number;
    let confidence: number;

    if (hasIris) {
      // ── High-accuracy mode: use iris landmarks ──
      const leftIris = landmarks[LEFT_IRIS_CENTER];
      const rightIris = landmarks[RIGHT_IRIS_CENTER];

      // Horizontal: iris X relative to eye width
      const leftRatioX = (leftIris.x - leftOuter.x) / (leftInner.x - leftOuter.x);
      const rightRatioX = (rightIris.x - rightOuter.x) / (rightInner.x - rightOuter.x);

      // Vertical: iris Y relative to eyelid bounds
      const leftRatioY = leftEyeHeight > 0.001
        ? (leftIris.y - leftUpper.y) / leftEyeHeight
        : 0.5;
      const rightRatioY = rightEyeHeight > 0.001
        ? (rightIris.y - rightUpper.y) / rightEyeHeight
        : 0.5;

      // Average both eyes (weighted by eye aperture)
      const totalWidth = leftEyeWidth + rightEyeWidth;
      avgX = leftRatioX * (leftEyeWidth / totalWidth) + rightRatioX * (rightEyeWidth / totalWidth);
      avgY = leftRatioY * (leftEyeWidth / totalWidth) + rightRatioY * (rightEyeWidth / totalWidth);
      confidence = 0.85;
    } else {
      // ── Fallback mode: estimate gaze from pupil landmarks (less accurate) ──
      // Use landmarks 468 (left pupil center) and 473 (right pupil center)
      // These are actually the standard eye center landmarks at indices 159/386 (upper eyelid)
      // and the geometric center of the eye region
      const leftEyeCenterX = (leftInner.x + leftOuter.x) / 2;
      const leftEyeCenterY = (leftUpper.y + leftLower.y) / 2;
      const rightEyeCenterX = (rightInner.x + rightOuter.x) / 2;
      const rightEyeCenterY = (rightUpper.y + rightLower.y) / 2;

      // Use upper eyelid center (159/386) as approximate pupil position proxy
      const leftPupilX = landmarks[159].x;
      const leftPupilY = landmarks[159].y;
      const rightPupilX = landmarks[386].x;
      const rightPupilY = landmarks[386].y;

      // Compute deviation of pupil-proxy from eye center
      const leftRatioX = leftEyeWidth > 0 ? (leftPupilX - leftEyeCenterX) / leftEyeWidth + 0.5 : 0.5;
      const rightRatioX = rightEyeWidth > 0 ? (rightPupilX - rightEyeCenterX) / rightEyeWidth + 0.5 : 0.5;
      const leftRatioY = leftEyeHeight > 0.001 ? (leftPupilY - leftEyeCenterY) / leftEyeHeight + 0.5 : 0.5;
      const rightRatioY = rightEyeHeight > 0.001 ? (rightPupilY - rightEyeCenterY) / rightEyeHeight + 0.5 : 0.5;

      avgX = (leftRatioX + rightRatioX) / 2;
      avgY = (leftRatioY + rightRatioY) / 2;
      confidence = 0.5; // Lower confidence without iris data
    }

    // ── Head pose compensation ──
    const noseTip = landmarks[NOSE_TIP];
    const forehead = landmarks[FOREHEAD];
    const chin = landmarks[CHIN];

    const faceCenterX = (forehead.x + chin.x) / 2;
    const headYaw = (noseTip.x - faceCenterX) * 2;

    const faceCenterY = (forehead.y + chin.y) / 2;
    const faceHeight = Math.abs(forehead.y - chin.y);
    const headPitch = faceHeight > 0.01 ? (noseTip.y - faceCenterY) / faceHeight : 0;

    if (!this.headCalibrated) {
      this.baseHeadX = headYaw;
      this.baseHeadY = headPitch;
      this.headCalibrated = true;
    }

    const headCompX = (headYaw - this.baseHeadX) * 0.4;
    const headCompY = (headPitch - this.baseHeadY) * 0.3;

    // Map to screen coordinates with amplification
    const amplifyX = hasIris ? 3.0 : 4.0;
    const amplifyY = hasIris ? 2.8 : 3.5;
    const gazeX = 0.5 + (avgX - 0.5 - headCompX) * amplifyX;
    const gazeY = 0.5 + (avgY - 0.5 - headCompY) * amplifyY;

    // Confidence based on eye openness
    const avgEyeOpenness = (leftEyeHeight + rightEyeHeight) / 2;
    const openConfidence = Math.min(1, avgEyeOpenness / 0.015);

    return {
      x: Math.max(0, Math.min(1, gazeX)),
      y: Math.max(0, Math.min(1, gazeY)),
      confidence: Math.min(confidence, openConfidence * confidence),
    };
  }
}

function distance(a: Landmark, b: Landmark): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}
