/** Hand landmark point (normalized 0-1 coordinates from MediaPipe) */
export interface Landmark {
  x: number;
  y: number;
  z: number;
  visibility?: number;
}

/** 21 landmarks per hand */
export type HandLandmarks = Landmark[];

/** Which hand */
export type Handedness = 'Left' | 'Right';

/** A single detected hand with landmarks and classification */
export interface DetectedHand {
  landmarks: HandLandmarks;
  worldLandmarks: HandLandmarks;
  handedness: Handedness;
}

/** Frame result from hand tracker */
export interface HandTrackingResult {
  hands: DetectedHand[];
  timestamp: number;
}

/** All possible gesture states */
export type GestureType =
  | 'idle'
  | 'pinch_grab'
  | 'two_hand_zoom'
  | 'open_palm_rotate'
  | 'double_tap'
  | 'swipe'
  | 'fist';

/** Direction for swipe gesture */
export type SwipeDirection = 'left' | 'right' | 'up' | 'down';

/** Current gesture state with metadata */
export interface GestureState {
  type: GestureType;
  confidence: number;
  /** For pinch: normalized grab point (midpoint of thumb+index) */
  grabPoint?: { x: number; y: number; z: number };
  /** For two-hand zoom: delta distance between hands (positive = spread) */
  zoomDelta?: number;
  /** For open palm rotate: movement delta of palm center */
  rotateDelta?: { dx: number; dy: number };
  /** For swipe: direction */
  swipeDirection?: SwipeDirection;
  /** For pinch: whether we just started (to initiate grab) vs continuing */
  isNewGrab?: boolean;
  /** For double tap: the tap position */
  tapPoint?: { x: number; y: number };
  /** Duration this gesture has been active (ms) */
  duration: number;
}

/** Commands sent to ForceGraph3D */
export type GraphCommandType =
  | 'grab_start'
  | 'grab_move'
  | 'grab_release'
  | 'zoom'
  | 'rotate'
  | 'pan'
  | 'select_node'
  | 'focus_node'
  | 'reset_view';

export interface GraphCommand {
  type: GraphCommandType;
  /** Normalized screen coordinates for raycasting */
  screenPoint?: { x: number; y: number };
  /** 3D world delta for node movement */
  worldDelta?: { x: number; y: number; z: number };
  /** Zoom factor (>1 = zoom in, <1 = zoom out) */
  zoomFactor?: number;
  /** Rotation in radians */
  rotation?: { azimuth: number; elevation: number };
  /** Pan direction */
  panDelta?: { x: number; y: number };
}

/** Finger tip landmark indices */
export const FINGER_TIPS = [4, 8, 12, 16, 20] as const;

/** Finger MCP (base) landmark indices */
export const FINGER_MCPS = [2, 5, 9, 13, 17] as const;

/** Finger PIP (middle joint) landmark indices */
export const FINGER_PIPS = [3, 6, 10, 14, 18] as const;

/** Finger DIP landmark indices */
export const FINGER_DIPS = [3, 7, 11, 15, 19] as const;

/** All finger indices grouped */
export const FINGERS = {
  thumb:  { mcp: 2, pip: 3, dip: 3, tip: 4 },
  index:  { mcp: 5, pip: 6, dip: 7, tip: 8 },
  middle: { mcp: 9, pip: 10, dip: 11, tip: 12 },
  ring:   { mcp: 13, pip: 14, dip: 15, tip: 16 },
  pinky:  { mcp: 17, pip: 18, dip: 19, tip: 20 },
} as const;

/** Hand tracker state */
export type TrackerState = 'idle' | 'loading' | 'ready' | 'active' | 'error';

/** Gesture mode state for the overall system */
export interface GestureModeState {
  enabled: boolean;
  trackerState: TrackerState;
  currentGesture: GestureState;
  hands: DetectedHand[];
  error?: string;
}

/** Imperative handle exposed by GraphCanvas for gesture control */
export interface GraphCanvasHandle {
  getCamera: () => THREE.Camera | null;
  getScene: () => THREE.Scene | null;
  getControls: () => any;
  getCameraDistance: () => number;
  zoom: (targetDist: number) => void;
  clickNode: (node: any) => void;
  resetView: () => void;
  setControlsEnabled: (enabled: boolean) => void;
  getContainerBounds: () => DOMRect | null;
  getNodePositions: () => Array<{ id: string; x: number; y: number; z: number }>;
}

// Three.js type import (for type reference only)
import type * as THREE from 'three';
