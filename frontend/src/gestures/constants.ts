/** Gesture detection thresholds */
export const GESTURE = {
  /** Pinch: max distance between thumb tip and index tip (normalized) */
  PINCH_THRESHOLD: 0.06,
  /** Pinch: minimum frames to confirm pinch start */
  PINCH_MIN_FRAMES: 2,

  /** Zoom: speed multiplier for pinch-spread delta → camera distance */
  ZOOM_SPEED: 600,
  /** Zoom: minimum spread delta to register */
  ZOOM_THRESHOLD: 0.008,

  /** Pan: speed multiplier for hand slide → screen pan */
  PAN_SPEED: 1800,
  /** Pan: non-linear acceleration exponent (>1 = faster hand → disproportionately more pan) */
  PAN_ACCELERATION: 1.6,
  /** Pan: momentum friction per frame (0 = instant stop, 1 = no friction) */
  PAN_MOMENTUM_FRICTION: 0.92,
  /** Pan: minimum momentum speed before stopping */
  PAN_MOMENTUM_MIN: 0.5,
  /** Rotate: minimum palm movement to register */
  ROTATE_THRESHOLD: 0.002,
  /** Rotate: speed multiplier (unused in new model, kept for compat) */
  ROTATE_SPEED: 3.0,

  /** Swipe: minimum palm velocity (normalized per frame) */
  SWIPE_VELOCITY_THRESHOLD: 0.08,
  /** Swipe: maximum duration (ms) */
  SWIPE_MAX_DURATION: 300,
  /** Swipe: cooldown after detection (ms) */
  SWIPE_COOLDOWN: 500,
  /** Swipe: pan amount per swipe */
  SWIPE_PAN_AMOUNT: 50,

  /** Fist: minimum hold duration (ms) */
  FIST_HOLD_DURATION: 500,

  /** Double tap: maximum time for two taps (ms) */
  DOUBLE_TAP_WINDOW: 600,
  /** Double tap: index finger must be curled below this y-threshold */
  TAP_CURL_THRESHOLD: 0.03,

  /** Finger extended: tip must be above (lower y) PIP by this amount */
  FINGER_EXTENDED_THRESHOLD: -0.02,

  /** Open palm: all fingers must be spread by at least this */
  PALM_SPREAD_THRESHOLD: 0.03,
} as const;

/** Performance tuning */
export const PERFORMANCE = {
  /** Target detection FPS (process every Nth ms) */
  DETECTION_INTERVAL_MS: 33, // ~30fps
  /** Fallback detection interval when graph is slow */
  DETECTION_INTERVAL_SLOW_MS: 50, // ~20fps
  /** Graph tick threshold to trigger slow mode (ms) */
  GRAPH_TICK_SLOW_THRESHOLD: 20,
  /** Max hands to detect */
  MAX_HANDS: 2,
  /** Detection confidence threshold */
  MIN_DETECTION_CONFIDENCE: 0.6,
  /** Tracking confidence threshold */
  MIN_TRACKING_CONFIDENCE: 0.5,
} as const;

/** Neon line colors for each finger pair (thumb→pinky) */
export const NEON_COLORS = [
  '#00FFFF', // Thumb - Cyan
  '#FF00FF', // Index - Magenta
  '#FFFF00', // Middle - Yellow
  '#00FF88', // Ring - Green
  '#FF6600', // Pinky - Orange
] as const;

/** Hand skeleton bone connections (pairs of landmark indices) */
export const HAND_CONNECTIONS: [number, number][] = [
  // Thumb
  [0, 1], [1, 2], [2, 3], [3, 4],
  // Index
  [0, 5], [5, 6], [6, 7], [7, 8],
  // Middle
  [0, 9], [9, 10], [10, 11], [11, 12],
  // Ring
  [0, 13], [13, 14], [14, 15], [15, 16],
  // Pinky
  [0, 17], [17, 18], [18, 19], [19, 20],
  // Palm
  [5, 9], [9, 13], [13, 17],
];

/** Visual styling */
export const VISUALS = {
  /** Skeleton line color */
  SKELETON_COLOR: 'rgba(255, 255, 255, 0.7)',
  /** Skeleton line width */
  SKELETON_WIDTH: 2,
  /** Landmark dot radius */
  LANDMARK_RADIUS: 4,
  /** Fingertip dot radius (larger) */
  FINGERTIP_RADIUS: 6,
  /** Neon line width */
  NEON_LINE_WIDTH: 3,
  /** Neon glow blur */
  NEON_GLOW_BLUR: 15,
  /** Neon outer glow blur */
  NEON_OUTER_GLOW_BLUR: 25,
  /** Particle count per neon line */
  PARTICLES_PER_LINE: 5,
  /** Particle radius */
  PARTICLE_RADIUS: 3,
  /** Particle speed (0-1 per second) */
  PARTICLE_SPEED: 0.8,
  /** Webcam preview width */
  PREVIEW_WIDTH: 280,
  /** Webcam preview height */
  PREVIEW_HEIGHT: 210,
} as const;

/** Gesture indicator colors */
export const GESTURE_COLORS: Record<string, string> = {
  idle: '#6B7280',
  pinch_grab: '#06B6D4',
  two_hand_zoom: '#8B5CF6',
  open_palm_rotate: '#10B981',
  double_tap: '#F59E0B',
  swipe: '#22D3EE',
  fist: '#EF4444',
};

/** Gesture display names */
export const GESTURE_NAMES: Record<string, string> = {
  idle: 'Ready',
  pinch_grab: 'Grabbing',
  two_hand_zoom: 'Zooming',
  open_palm_rotate: 'Panning',
  double_tap: 'Focus',
  swipe: 'Select',
  fist: 'Reset',
};
