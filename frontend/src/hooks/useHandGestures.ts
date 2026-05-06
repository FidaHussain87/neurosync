import { useRef, useCallback, useState, useEffect } from 'react';
import * as THREE from 'three';
import { HandTracker } from '../gestures/HandTracker';
import { GestureRecognizer } from '../gestures/GestureRecognizer';
import { GestureMapper } from '../gestures/GestureMapper';
import { EyeTracker, type GazePoint } from '../gestures/EyeTracker';
import type {
  DetectedHand,
  GestureState,
  GraphCanvasHandle,
  GraphCommand,
  TrackerState,
} from '../gestures/types';

/** Raycast from a normalized screen point to find the nearest node */
function findNodeAtScreenPoint(
  screenPoint: { x: number; y: number },
  gh: GraphCanvasHandle,
): string | null {
  const nodes = gh.getNodePositions();
  const camera = gh.getCamera();
  if (!camera || nodes.length === 0) return null;

  const ndcX = screenPoint.x * 2 - 1;
  const ndcY = -(screenPoint.y * 2 - 1);
  const raycaster = new THREE.Raycaster();
  raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);

  let closestId: string | null = null;
  let closestDist = Infinity;
  for (const node of nodes) {
    const pos = new THREE.Vector3(node.x, node.y, node.z);
    const dist = raycaster.ray.distanceToPoint(pos);
    if (dist < 30 && dist < closestDist) {
      closestDist = dist;
      closestId = node.id;
    }
  }
  return closestId;
}

interface UseHandGesturesReturn {
  enabled: boolean;
  toggle: () => void;
  trackerState: TrackerState;
  hands: DetectedHand[];
  gesture: GestureState;
  gazePoint: GazePoint;
  error: string | null;
  setGraphHandle: (handle: GraphCanvasHandle) => void;
  getVideoElement: () => HTMLVideoElement | null;
  setVideoElement: (el: HTMLVideoElement | null) => void;
  // Calibration
  isCalibrated: boolean;
  startCalibrationSample: () => void;
  finishCalibrationSample: (screenX: number, screenY: number) => boolean;
  finalizeCalibration: () => boolean;
  resetCalibration: () => void;
  calibrationPointCount: number;
}

/**
 * Orchestration hook — ties HandTracker, EyeTracker, GestureRecognizer,
 * and GestureMapper into a single reactive interface.
 *
 * New interaction model:
 * - Open hand slide → PAN
 * - Pinch tap → SELECT (at gaze point)
 * - Pinch + spread → ZOOM
 * - Fist → RESET
 * - Eye tracking → cursor for node targeting
 */
export function useHandGestures(): UseHandGesturesReturn {
  const [enabled, setEnabled] = useState(false);
  const [trackerState, setTrackerState] = useState<TrackerState>('idle');
  const [hands, setHands] = useState<DetectedHand[]>([]);
  const [gesture, setGesture] = useState<GestureState>({ type: 'idle', confidence: 1, duration: 0 });
  const [gazePoint, setGazePoint] = useState<GazePoint>({ x: 0.5, y: 0.5, confidence: 0 });
  const [error, setError] = useState<string | null>(null);

  const trackerRef = useRef<HandTracker | null>(null);
  const eyeTrackerRef = useRef<EyeTracker | null>(null);
  const recognizerRef = useRef<GestureRecognizer>(new GestureRecognizer());
  const mapperRef = useRef<GestureMapper>(new GestureMapper());
  const videoElRef = useRef<HTMLVideoElement | null>(null);
  const graphHandleRef = useRef<GraphCanvasHandle | null>(null);
  const grabbedNodeRef = useRef<string | null>(null);

  // Apply graph commands from gesture mapper
  const applyCommand = useCallback((cmd: GraphCommand | null) => {
    if (!cmd || !graphHandleRef.current) return;
    const gh = graphHandleRef.current;

    switch (cmd.type) {
      case 'grab_start': {
        const grabbedId = mapperRef.current.getGrabbedNodeId();
        grabbedNodeRef.current = grabbedId;
        break;
      }
      case 'grab_move': {
        if (cmd.worldDelta && grabbedNodeRef.current) {
          // The grabbed node should follow the hand — update its fixed position
          // Note: ForceGraph3D nodes are mutated in-place
          const nodes = gh.getNodePositions();
          const node = nodes.find(n => n.id === grabbedNodeRef.current);
          if (node) {
            (node as any).fx = cmd.worldDelta.x;
            (node as any).fy = cmd.worldDelta.y;
            (node as any).fz = cmd.worldDelta.z;
          }
        }
        break;
      }
      case 'grab_release': {
        if (grabbedNodeRef.current) {
          const nodes = gh.getNodePositions();
          const node = nodes.find(n => n.id === grabbedNodeRef.current);
          if (node) {
            (node as any).fx = undefined;
            (node as any).fy = undefined;
            (node as any).fz = undefined;
          }
          grabbedNodeRef.current = null;
        }
        break;
      }
      case 'zoom': {
        if (cmd.zoomFactor) {
          const currentDist = gh.getCameraDistance();
          gh.zoom(currentDist * cmd.zoomFactor);
        }
        break;
      }
      case 'pan': {
        if (cmd.panDelta) {
          // Pan in screen-space using camera's local right/up vectors
          const camera = gh.getCamera();
          const controls = gh.getControls();
          if (camera && controls && controls.target) {
            // Get camera's right vector (screen-space horizontal)
            const right = new THREE.Vector3();
            camera.getWorldDirection(right);
            right.cross(camera.up).normalize();

            // Get camera's up vector (screen-space vertical)
            const up = new THREE.Vector3();
            camera.getWorldDirection(up);
            up.negate();
            const screenUp = new THREE.Vector3().crossVectors(right, up).normalize();

            // Apply pan in screen space
            const panOffset = new THREE.Vector3()
              .addScaledVector(right, cmd.panDelta.x)
              .addScaledVector(screenUp, cmd.panDelta.y);

            controls.target.add(panOffset);
            camera.position.add(panOffset);
            controls.update?.();
          }
        }
        break;
      }
      case 'rotate': {
        if (cmd.rotation) {
          const controls = gh.getControls();
          if (controls && controls.rotateLeft) {
            controls.rotateLeft(cmd.rotation.azimuth);
            controls.rotateUp(cmd.rotation.elevation);
            controls.update();
          }
        }
        break;
      }
      case 'select_node': {
        if (cmd.screenPoint) {
          const nodeId = findNodeAtScreenPoint(cmd.screenPoint, gh);
          if (nodeId) {
            gh.clickNode(nodeId);
          }
        }
        break;
      }
      case 'focus_node': {
        // Double-tap: select + zoom into the node (focus mode)
        if (cmd.screenPoint) {
          const nodeId = findNodeAtScreenPoint(cmd.screenPoint, gh);
          if (nodeId) {
            gh.clickNode(nodeId);
            // Zoom camera to focus on this node
            const nodes = gh.getNodePositions();
            const node = nodes.find(n => n.id === nodeId);
            if (node) {
              const camera = gh.getCamera();
              const controls = gh.getControls();
              if (camera && controls) {
                // Animate camera to close distance from the node
                const targetDist = 80;
                const dx = camera.position.x - node.x;
                const dy = camera.position.y - node.y;
                const dz = camera.position.z - node.z;
                const len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;

                const newPos = {
                  x: node.x + (dx / len) * targetDist,
                  y: node.y + (dy / len) * targetDist,
                  z: node.z + (dz / len) * targetDist,
                };

                // Smooth camera animation
                const startPos = { x: camera.position.x, y: camera.position.y, z: camera.position.z };
                const startTarget = controls.target ? { x: controls.target.x, y: controls.target.y, z: controls.target.z } : { x: 0, y: 0, z: 0 };
                const duration = 800;
                const startTime = performance.now();

                const animate = () => {
                  const elapsed = performance.now() - startTime;
                  const t = Math.min(1, elapsed / duration);
                  // Ease out cubic
                  const ease = 1 - Math.pow(1 - t, 3);

                  camera.position.set(
                    startPos.x + (newPos.x - startPos.x) * ease,
                    startPos.y + (newPos.y - startPos.y) * ease,
                    startPos.z + (newPos.z - startPos.z) * ease,
                  );
                  if (controls.target) {
                    controls.target.set(
                      startTarget.x + (node.x - startTarget.x) * ease,
                      startTarget.y + (node.y - startTarget.y) * ease,
                      startTarget.z + (node.z - startTarget.z) * ease,
                    );
                  }
                  controls.update?.();

                  if (t < 1) requestAnimationFrame(animate);
                };
                requestAnimationFrame(animate);
              }
            }
          }
        }
        break;
      }
      case 'reset_view': {
        gh.resetView();
        break;
      }
    }
  }, []);

  const toggle = useCallback(async () => {
    if (enabled) {
      // Disable
      trackerRef.current?.stop();
      eyeTrackerRef.current?.stop();
      setEnabled(false);
      setHands([]);
      setGesture({ type: 'idle', confidence: 1, duration: 0 });
      setGazePoint({ x: 0.5, y: 0.5, confidence: 0 });
      mapperRef.current.releaseGrab();
      graphHandleRef.current?.setControlsEnabled(true);
    } else {
      // Enable
      setError(null);
      try {
        // Initialize hand tracker
        if (!trackerRef.current) {
          trackerRef.current = new HandTracker();
          trackerRef.current.setOnResult((result) => {
            setHands(result.hands);
            const recognized = recognizerRef.current.recognize(result.hands, result.timestamp);
            setGesture(recognized);
            const command = mapperRef.current.map(recognized);
            applyCommand(command);
          });
          trackerRef.current.setOnStateChange(setTrackerState);
          await trackerRef.current.init();
        }

        // Initialize eye tracker (non-blocking — eye tracking is optional enhancement)
        if (!eyeTrackerRef.current) {
          eyeTrackerRef.current = new EyeTracker();
          eyeTrackerRef.current.setOnGaze((gaze) => {
            setGazePoint(gaze);
            mapperRef.current.setGazePoint(gaze);
          });
          // Init in background — don't block hand tracking start
          eyeTrackerRef.current.init().catch((err) => {
            console.warn('[EyeTracker] Failed to init (optional):', err);
          });
        }

        if (videoElRef.current) {
          await trackerRef.current.start(videoElRef.current);
          // Start eye tracker on same video element
          eyeTrackerRef.current?.start(videoElRef.current);
          setEnabled(true);
          graphHandleRef.current?.setControlsEnabled(false);
        } else {
          setError('Video element not ready');
        }
      } catch (err: any) {
        setError(err.message ?? 'Failed to start hand tracking');
        setEnabled(false);
      }
    }
  }, [enabled, applyCommand]);

  const setGraphHandle = useCallback((handle: GraphCanvasHandle) => {
    graphHandleRef.current = handle;
    mapperRef.current.setGraphHandle(handle);
  }, []);

  const setVideoElement = useCallback((el: HTMLVideoElement | null) => {
    videoElRef.current = el;
  }, []);

  const getVideoElement = useCallback(() => videoElRef.current, []);

  // ─── Calibration ─────────────────────────────────────────────
  const [isCalibrated, setIsCalibrated] = useState(false);
  const [calibrationPointCount, setCalibrationPointCount] = useState(0);

  const startCalibrationSample = useCallback(() => {
    eyeTrackerRef.current?.startCollectingSample();
  }, []);

  const finishCalibrationSample = useCallback((screenX: number, screenY: number): boolean => {
    const success = eyeTrackerRef.current?.finishSample(screenX, screenY) ?? false;
    if (success) {
      setCalibrationPointCount(eyeTrackerRef.current?.getCalibrationPointCount() ?? 0);
    }
    return success;
  }, []);

  const finalizeCalibration = useCallback((): boolean => {
    const success = eyeTrackerRef.current?.finalizeCalibration() ?? false;
    if (success) {
      setIsCalibrated(true);
    }
    return success;
  }, []);

  const resetCalibration = useCallback(() => {
    eyeTrackerRef.current?.resetCalibration();
    setIsCalibrated(false);
    setCalibrationPointCount(0);
  }, []);

  // Load saved calibration when eye tracker initializes
  useEffect(() => {
    if (eyeTrackerRef.current) {
      const loaded = eyeTrackerRef.current.loadCalibration();
      if (loaded) {
        setIsCalibrated(true);
        setCalibrationPointCount(eyeTrackerRef.current.getCalibrationPointCount());
      }
    }
  }, [enabled]); // Re-check when toggled on

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      trackerRef.current?.destroy();
      eyeTrackerRef.current?.destroy();
    };
  }, []);

  return {
    enabled,
    toggle,
    trackerState,
    hands,
    gesture,
    gazePoint,
    error,
    setGraphHandle,
    getVideoElement,
    setVideoElement,
    isCalibrated,
    startCalibrationSample,
    finishCalibrationSample,
    finalizeCalibration,
    resetCalibration,
    calibrationPointCount,
  };
}
