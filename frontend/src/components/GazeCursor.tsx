import type { GazePoint } from '../gestures/EyeTracker';

interface Props {
  gaze: GazePoint;
  visible: boolean;
}

/**
 * A soft gaze cursor that shows where the user is looking.
 * Appears as a subtle glowing dot — like Vision Pro's focus indicator.
 */
export default function GazeCursor({ gaze, visible }: Props) {
  if (!visible || gaze.confidence < 0.3) return null;

  const opacity = Math.min(0.8, gaze.confidence);

  return (
    <div
      className="fixed pointer-events-none z-50 -translate-x-1/2 -translate-y-1/2"
      style={{
        left: `${gaze.x * 100}%`,
        top: `${gaze.y * 100}%`,
        transition: 'left 0.1s ease-out, top 0.1s ease-out',
      }}
    >
      {/* Outer glow ring */}
      <div
        className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          width: 40,
          height: 40,
          border: `2px solid rgba(0, 255, 255, ${opacity * 0.4})`,
          boxShadow: `0 0 12px rgba(0, 255, 255, ${opacity * 0.3})`,
        }}
      />
      {/* Inner dot */}
      <div
        className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          width: 8,
          height: 8,
          backgroundColor: `rgba(0, 255, 255, ${opacity})`,
          boxShadow: `0 0 8px rgba(0, 255, 255, ${opacity * 0.8})`,
        }}
      />
    </div>
  );
}
