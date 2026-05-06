import type {
  DetectedHand,
  GestureState,
  GestureType,
  HandLandmarks,
  Landmark,
} from './types';
import { GESTURE } from './constants';
import { distance2D, palmCenter, VelocityTracker } from './smoothing';

/**
 * Redesigned gesture recognizer — Jarvis / Vision Pro interaction model:
 *
 * GESTURES:
 * 1. OPEN HAND SLIDE → Pan/move the graph (hand moves left/right/up/down)
 * 2. PINCH (thumb+index touch) → Click/select (at gaze point or nearest node)
 * 3. PINCH + SPREAD (L-shape) → Zoom in; reverse → Zoom out
 * 4. FIST (hold 500ms) → Reset view
 * 5. TAP (single quick pinch-release) → Confirm selection at gaze point
 *
 * Priority: PINCH_ZOOM > PINCH_TAP > FIST > HAND_SLIDE > IDLE
 */
export class GestureRecognizer {
  // Pinch state
  private pinchActive = false;
  private pinchStartTime = 0;
  private pinchFrameCount = 0;

  // Double-tap state (two quick pinch-releases)
  private lastTapTime = 0;
  private lastTapPoint: { x: number; y: number } | null = null;

  // Slide state (open hand pan)
  private prevPalmCenter: Landmark | null = null;
  private palmVelocityTracker = new VelocityTracker();

  // Fist state
  private fistStartTime: number | null = null;

  // Zoom state (pinch then spread)
  private pinchZoomActive = false;
  private prevThumbIndexDist = 0;

  // General
  private gestureStartTime = 0;
  private lastGestureType: GestureType = 'idle';

  /** Process a frame and return the recognized gesture */
  recognize(hands: DetectedHand[], now: number): GestureState {
    if (hands.length === 0) {
      this.reset();
      return this.idle();
    }

    const primary = hands[0];
    const landmarks = primary.landmarks;

    // 1. Detect pinch state (thumb + index finger touching)
    const thumbTip = landmarks[4];
    const indexTip = landmarks[8];
    const thumbIndexDist = distance2D(thumbTip, indexTip);
    const isPinching = thumbIndexDist < GESTURE.PINCH_THRESHOLD;

    // 2. Check if this is a PINCH-ZOOM (pinch then spread into L-shape)
    if (isPinching && !this.pinchActive) {
      // Pinch just started
      this.pinchFrameCount++;
      if (this.pinchFrameCount >= 2) {
        this.pinchActive = true;
        this.pinchStartTime = now;
        this.prevThumbIndexDist = thumbIndexDist;
        this.pinchZoomActive = false;
      }
    } else if (this.pinchActive && !isPinching) {
      // Pinch released — check if it was a quick tap or a zoom gesture
      const duration = now - this.pinchStartTime;

      if (this.pinchZoomActive) {
        // Was zooming, now released
        this.pinchZoomActive = false;
        this.pinchActive = false;
        this.pinchFrameCount = 0;
        return this.idle();
      }

      if (duration < 300) {
        // Quick tap detected
        const tapPoint = { x: (thumbTip.x + indexTip.x) / 2, y: (thumbTip.y + indexTip.y) / 2 };
        const timeSinceLastTap = now - this.lastTapTime;

        if (timeSinceLastTap < GESTURE.DOUBLE_TAP_WINDOW && this.lastTapPoint) {
          // Double-tap! Two quick pinches within 600ms → FOCUS mode (zoom into node)
          this.pinchActive = false;
          this.pinchFrameCount = 0;
          this.lastTapTime = 0;
          this.lastTapPoint = null;
          return this.setGesture({
            type: 'double_tap',
            confidence: 0.98,
            tapPoint,
            duration: 0,
          }, now);
        }

        // First tap → fire immediately as select, store for double-tap detection
        this.lastTapTime = now;
        this.lastTapPoint = tapPoint;
        this.pinchActive = false;
        this.pinchFrameCount = 0;
        return this.setGesture({
          type: 'swipe', // reusing as "single tap select"
          confidence: 0.92,
          tapPoint,
          duration: 0,
        }, now);
      }

      // Longer pinch without zoom — just release
      this.pinchActive = false;
      this.pinchFrameCount = 0;
    } else if (!isPinching) {
      this.pinchFrameCount = 0;
    }

    // 3. While pinching, check for zoom (thumb-index spreading into L-shape)
    if (this.pinchActive) {
      // After initial pinch, if they start spreading thumb and index apart → zoom
      const spreadAmount = thumbIndexDist - this.prevThumbIndexDist;
      this.prevThumbIndexDist = thumbIndexDist;

      // Check if thumb and index are starting to separate (L-shape forming)
      if (thumbIndexDist > GESTURE.PINCH_THRESHOLD * 1.5) {
        this.pinchZoomActive = true;
      }

      if (this.pinchZoomActive) {
        // Spreading = zoom in, coming back together = zoom out
        const zoomDelta = spreadAmount * 3; // amplify
        return this.setGesture({
          type: 'two_hand_zoom', // reusing type for zoom
          confidence: Math.min(1, Math.abs(zoomDelta) / 0.02),
          zoomDelta: zoomDelta,
          duration: now - this.pinchStartTime,
        }, now);
      }

      // Still pinching but not zooming yet — report as pinch hold
      return this.setGesture({
        type: 'pinch_grab',
        confidence: 1,
        grabPoint: {
          x: (thumbTip.x + indexTip.x) / 2,
          y: (thumbTip.y + indexTip.y) / 2,
          z: (thumbTip.z + indexTip.z) / 2,
        },
        isNewGrab: (now - this.pinchStartTime) < 50,
        duration: now - this.pinchStartTime,
      }, now);
    }

    // 4. Fist detection (reset view)
    const fistGesture = this.detectFist(landmarks, now);
    if (fistGesture) return this.setGesture(fistGesture, now);

    // 5. Open hand slide (pan the graph)
    const slideGesture = this.detectHandSlide(landmarks, now);
    if (slideGesture) return this.setGesture(slideGesture, now);

    return this.idle();
  }

  /** Reset all state */
  reset(): void {
    this.pinchActive = false;
    this.pinchFrameCount = 0;
    this.pinchZoomActive = false;
    this.fistStartTime = null;
    this.prevPalmCenter = null;
    this.palmVelocityTracker.reset();
    this.lastGestureType = 'idle';
    // Don't reset lastTapTime/lastTapPoint — double-tap needs to persist across brief hand loss
  }

  // ─── Gesture Detectors ──────────────────────────────────────────────

  private detectFist(landmarks: HandLandmarks, now: number): GestureState | null {
    const isFist = this.isAllFingersCurled(landmarks);

    if (isFist) {
      if (this.fistStartTime === null) {
        this.fistStartTime = now;
      }
      const heldFor = now - this.fistStartTime;
      if (heldFor >= GESTURE.FIST_HOLD_DURATION) {
        return {
          type: 'fist',
          confidence: Math.min(1, heldFor / (GESTURE.FIST_HOLD_DURATION * 1.5)),
          duration: heldFor,
        };
      }
    } else {
      this.fistStartTime = null;
    }

    return null;
  }

  private detectHandSlide(landmarks: HandLandmarks, now: number): GestureState | null {
    // Only activate when hand is open (most fingers extended) — prevents
    // accidental pan during other gestures
    if (!this.isHandOpen(landmarks)) {
      this.prevPalmCenter = null;
      this.palmVelocityTracker.reset();
      return null;
    }

    const center = palmCenter(landmarks);
    this.palmVelocityTracker.push(center.x, center.y, now);

    if (this.prevPalmCenter === null) {
      this.prevPalmCenter = center;
      return null;
    }

    const dx = center.x - this.prevPalmCenter.x;
    const dy = center.y - this.prevPalmCenter.y;
    this.prevPalmCenter = center;

    const movement = Math.sqrt(dx * dx + dy * dy);

    // Only register if there's meaningful movement (lowered threshold for responsiveness)
    if (movement > 0.002) {
      return {
        type: 'open_palm_rotate', // reusing as "slide/pan"
        confidence: Math.min(1, movement / 0.02),
        rotateDelta: { dx, dy },
        duration: this.lastGestureType === 'open_palm_rotate' ? now - this.gestureStartTime : 0,
      };
    }

    return null;
  }

  // ─── Helpers ─────────────────────────────────────────────────────────

  private isHandOpen(landmarks: HandLandmarks): boolean {
    // At least 3 fingers extended (allows relaxed hand shape)
    let extended = 0;
    if (this.isFingerExtended(landmarks, 8, 6)) extended++;
    if (this.isFingerExtended(landmarks, 12, 10)) extended++;
    if (this.isFingerExtended(landmarks, 16, 14)) extended++;
    if (this.isFingerExtended(landmarks, 20, 18)) extended++;
    return extended >= 3;
  }

  private isFingerExtended(landmarks: HandLandmarks, tipIdx: number, pipIdx: number): boolean {
    return (landmarks[tipIdx].y - landmarks[pipIdx].y) < GESTURE.FINGER_EXTENDED_THRESHOLD;
  }

  private isAllFingersCurled(landmarks: HandLandmarks): boolean {
    const indexCurled = landmarks[8].y > landmarks[5].y;
    const middleCurled = landmarks[12].y > landmarks[9].y;
    const ringCurled = landmarks[16].y > landmarks[13].y;
    const pinkyCurled = landmarks[20].y > landmarks[17].y;
    const thumbTucked = distance2D(landmarks[4], landmarks[5]) < 0.08;
    return indexCurled && middleCurled && ringCurled && pinkyCurled && thumbTucked;
  }

  private setGesture(gesture: GestureState, now: number): GestureState {
    if (gesture.type !== this.lastGestureType) {
      this.gestureStartTime = now;
      this.lastGestureType = gesture.type;
    }
    return gesture;
  }

  private idle(): GestureState {
    this.lastGestureType = 'idle';
    return { type: 'idle', confidence: 1, duration: 0 };
  }
}
