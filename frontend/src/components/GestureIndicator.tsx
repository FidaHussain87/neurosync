import type { GestureState } from '../gestures/types';
import { GESTURE_COLORS, GESTURE_NAMES } from '../gestures/constants';

interface Props {
  gesture: GestureState;
  visible: boolean;
}

const GESTURE_ICONS: Record<string, string> = {
  idle: '\u270B',              // raised hand
  pinch_grab: '\u{1F91C}',    // pinching hand
  two_hand_zoom: '\u{1F50D}', // magnifying glass
  open_palm_rotate: '\u{1F590}', // open hand (pan)
  double_tap: '\u{1F3AF}',   // dart/target (focus!)
  swipe: '\u{1F4A1}',        // light bulb (select)
  fist: '\u{1F504}',         // reset arrows
};

/**
 * Floating pill-shaped indicator showing the currently recognized gesture.
 * Positioned top-center of viewport.
 */
export default function GestureIndicator({ gesture, visible }: Props) {
  if (!visible || gesture.type === 'idle') return null;

  const color = GESTURE_COLORS[gesture.type] ?? '#6B7280';
  const name = GESTURE_NAMES[gesture.type] ?? 'Unknown';
  const icon = GESTURE_ICONS[gesture.type] ?? '';

  return (
    <div
      className="absolute top-4 left-1/2 -translate-x-1/2 z-40 flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium text-white shadow-lg backdrop-blur-sm animate-pulse"
      style={{
        backgroundColor: `${color}33`,
        border: `1.5px solid ${color}`,
        boxShadow: `0 0 15px ${color}44, 0 4px 12px rgba(0,0,0,0.3)`,
      }}
    >
      <span className="text-base">{icon}</span>
      <span>{name}</span>
      {gesture.confidence < 1 && (
        <span className="text-xs opacity-60">
          {Math.round(gesture.confidence * 100)}%
        </span>
      )}
    </div>
  );
}
