import * as THREE from 'three';
import type { GestureState, GraphCommand, GraphCanvasHandle } from './types';
import type { GazePoint } from './EyeTracker';
import { GESTURE } from './constants';

/**
 * Maps recognized gestures into ForceGraph3D commands.
 *
 * New Jarvis/Vision Pro model:
 * - Open hand slide → PAN the graph (move left/right/up/down)
 * - Pinch (thumb+index) → SELECT node (at gaze point)
 * - Pinch + spread to L-shape → ZOOM in/out
 * - Fist hold → RESET view
 * - Tap (quick pinch-release) → CLICK node at gaze point
 */
export class GestureMapper {
  private graphHandle: GraphCanvasHandle | null = null;
  private gazePoint: GazePoint = { x: 0.5, y: 0.5, confidence: 0 };
  private grabbedNodeId: string | null = null;
  private raycaster = new THREE.Raycaster();
  private fistTriggered = false; // prevent repeated reset

  // Momentum state for pan
  private momentumVx = 0;
  private momentumVy = 0;
  private momentumActive = false;

  setGraphHandle(handle: GraphCanvasHandle): void {
    this.graphHandle = handle;
  }

  /** Update gaze point from eye tracker */
  setGazePoint(gaze: GazePoint): void {
    this.gazePoint = gaze;
  }

  /** Get current gaze point for UI rendering */
  getGazePoint(): GazePoint {
    return this.gazePoint;
  }

  /** Map gesture to graph command */
  map(gesture: GestureState): GraphCommand | null {
    switch (gesture.type) {
      case 'open_palm_rotate':
        return this.mapHandSlide(gesture);
      case 'pinch_grab':
        return this.mapPinchHold(gesture);
      case 'two_hand_zoom':
        return this.mapPinchZoom(gesture);
      case 'swipe':
        return this.mapSingleTap(gesture);
      case 'double_tap':
        return this.mapDoubleTapFocus(gesture);
      case 'fist':
        return this.mapFist();
      case 'idle':
        return this.mapIdle();
      default:
        return null;
    }
  }

  /**
   * Open hand slide → Pan the graph
   * Hand moves left → graph pans left, etc.
   * Uses non-linear acceleration: faster hand = exponentially more pan.
   * Stores velocity for momentum when hand leaves frame.
   */
  private mapHandSlide(gesture: GestureState): GraphCommand | null {
    if (!gesture.rotateDelta) return null;

    const dx = -gesture.rotateDelta.dx; // inverted for mirrored webcam
    const dy = gesture.rotateDelta.dy;

    // Non-linear acceleration: small movements stay precise, fast sweeps cover distance
    const magnitude = Math.sqrt(dx * dx + dy * dy);
    const accelerated = Math.pow(magnitude, GESTURE.PAN_ACCELERATION);
    const scale = magnitude > 0 ? (accelerated / magnitude) * GESTURE.PAN_SPEED : 0;

    const panX = dx * scale;
    const panY = dy * scale;

    // Store velocity for momentum when hand leaves frame
    this.momentumVx = panX;
    this.momentumVy = panY;
    this.momentumActive = true;

    return {
      type: 'pan',
      panDelta: { x: panX, y: panY },
    };
  }

  /**
   * Tick momentum — called when gesture is idle but momentum is active.
   * Returns a pan command with decaying velocity, or null when stopped.
   */
  tickMomentum(): GraphCommand | null {
    if (!this.momentumActive) return null;

    this.momentumVx *= GESTURE.PAN_MOMENTUM_FRICTION;
    this.momentumVy *= GESTURE.PAN_MOMENTUM_FRICTION;

    const speed = Math.sqrt(this.momentumVx * this.momentumVx + this.momentumVy * this.momentumVy);
    if (speed < GESTURE.PAN_MOMENTUM_MIN) {
      this.momentumActive = false;
      this.momentumVx = 0;
      this.momentumVy = 0;
      return null;
    }

    return {
      type: 'pan',
      panDelta: { x: this.momentumVx, y: this.momentumVy },
    };
  }

  /** Whether momentum is currently active */
  hasMomentum(): boolean {
    return this.momentumActive;
  }

  /** Kill momentum immediately (e.g., on fist reset or new gesture) */
  stopMomentum(): void {
    this.momentumActive = false;
    this.momentumVx = 0;
    this.momentumVy = 0;
  }

  /**
   * Pinch hold → Grab and drag node (or just hold for later zoom)
   * Uses gaze point to determine which node to grab
   */
  private mapPinchHold(gesture: GestureState): GraphCommand | null {
    this.stopMomentum();
    if (!gesture.grabPoint) return null;

    if (gesture.isNewGrab) {
      // New pinch — try to grab node at gaze point (or pinch point as fallback)
      const targetX = this.gazePoint.confidence > 0.4 ? this.gazePoint.x : gesture.grabPoint.x;
      const targetY = this.gazePoint.confidence > 0.4 ? this.gazePoint.y : gesture.grabPoint.y;
      const nodeId = this.findNearestNode(targetX, targetY);
      if (nodeId) {
        this.grabbedNodeId = nodeId;
        return { type: 'grab_start', screenPoint: { x: targetX, y: targetY } };
      }
    }

    // If holding a node, move it with the pinch point
    if (this.grabbedNodeId && gesture.grabPoint) {
      const worldPos = this.projectToDepthPlane(gesture.grabPoint.x, gesture.grabPoint.y);
      if (worldPos) {
        return {
          type: 'grab_move',
          screenPoint: { x: gesture.grabPoint.x, y: gesture.grabPoint.y },
          worldDelta: { x: worldPos.x, y: worldPos.y, z: worldPos.z },
        };
      }
    }

    return null;
  }

  /**
   * Pinch + spread (L-shape) → Zoom in/out
   * Spreading thumb and index apart = zoom in, bringing together = zoom out
   */
  private mapPinchZoom(gesture: GestureState): GraphCommand | null {
    if (gesture.zoomDelta === undefined) return null;

    // Positive delta = spreading = zoom in (decrease camera distance)
    const zoomFactor = 1 - gesture.zoomDelta * GESTURE.ZOOM_SPEED * 0.003;
    return {
      type: 'zoom',
      zoomFactor: Math.max(0.95, Math.min(1.05, zoomFactor)),
    };
  }

  /**
   * Single tap (one quick pinch-release) → Select node at gaze point
   */
  private mapSingleTap(gesture: GestureState): GraphCommand | null {
    this.stopMomentum();
    const targetX = this.gazePoint.confidence > 0.3
      ? this.gazePoint.x
      : (gesture.tapPoint?.x ?? 0.5);
    const targetY = this.gazePoint.confidence > 0.3
      ? this.gazePoint.y
      : (gesture.tapPoint?.y ?? 0.5);

    return {
      type: 'select_node',
      screenPoint: { x: targetX, y: targetY },
    };
  }

  /**
   * Double tap (two quick pinch-releases) → Focus node at gaze point
   * Selects the node AND zooms the camera to it (focus mode)
   */
  private mapDoubleTapFocus(gesture: GestureState): GraphCommand | null {
    this.stopMomentum();
    const targetX = this.gazePoint.confidence > 0.3
      ? this.gazePoint.x
      : (gesture.tapPoint?.x ?? 0.5);
    const targetY = this.gazePoint.confidence > 0.3
      ? this.gazePoint.y
      : (gesture.tapPoint?.y ?? 0.5);

    return {
      type: 'focus_node',
      screenPoint: { x: targetX, y: targetY },
    };
  }

  /**
   * Fist → Reset view (only fires once per fist hold)
   */
  private mapFist(): GraphCommand | null {
    this.stopMomentum();
    if (!this.fistTriggered) {
      this.fistTriggered = true;
      return { type: 'reset_view' };
    }
    return null;
  }

  /**
   * Idle → Release any grabbed node, reset fist trigger.
   * Does NOT kill momentum — momentum continues naturally with friction.
   */
  private mapIdle(): GraphCommand | null {
    this.fistTriggered = false;
    if (this.grabbedNodeId) {
      this.grabbedNodeId = null;
      return { type: 'grab_release' };
    }
    // Return momentum pan if active (hand left frame but still coasting)
    return this.tickMomentum();
  }

  getGrabbedNodeId(): string | null {
    return this.grabbedNodeId;
  }

  releaseGrab(): void {
    this.grabbedNodeId = null;
  }

  // ─── Raycasting Helpers ────────────────────────────────────────────

  private findNearestNode(normX: number, normY: number): string | null {
    if (!this.graphHandle) return null;
    const camera = this.graphHandle.getCamera();
    if (!camera) return null;

    const ndcX = normX * 2 - 1;
    const ndcY = -(normY * 2 - 1);

    this.raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);
    const ray = this.raycaster.ray;
    const nodes = this.graphHandle.getNodePositions();

    let closestId: string | null = null;
    let closestDist = Infinity;
    const threshold = 25; // generous hit zone

    for (const node of nodes) {
      const pos = new THREE.Vector3(node.x, node.y, node.z);
      const dist = ray.distanceToPoint(pos);
      if (dist < threshold && dist < closestDist) {
        closestDist = dist;
        closestId = node.id;
      }
    }

    return closestId;
  }

  private projectToDepthPlane(normX: number, normY: number): THREE.Vector3 | null {
    if (!this.graphHandle) return null;
    const camera = this.graphHandle.getCamera();
    if (!camera) return null;

    const ndcX = normX * 2 - 1;
    const ndcY = -(normY * 2 - 1);

    this.raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);

    // Project onto a plane at the graph's center depth, facing camera
    const camDir = new THREE.Vector3();
    camera.getWorldDirection(camDir);
    const plane = new THREE.Plane(camDir.negate(), 0);

    const target = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(plane, target);
  }
}
