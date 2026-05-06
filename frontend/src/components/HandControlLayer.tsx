import { useRef, useEffect, useCallback, useState } from 'react';
import type { GraphCanvasHandle } from '../gestures/types';
import { VISUALS } from '../gestures/constants';
import { useHandGestures } from '../hooks/useHandGestures';
import WebcamPreview, { type WebcamPreviewHandle } from './WebcamPreview';
import GestureOverlay from './GestureOverlay';
import GestureToggle from './GestureToggle';
import GestureIndicator from './GestureIndicator';
import GazeCursor from './GazeCursor';
import GazeCalibration from './GazeCalibration';

interface Props {
  graphHandle: GraphCanvasHandle | null;
  children: React.ReactNode;
}

/**
 * Parent layer wrapping the graph canvas with gesture control UI:
 * - Toggle button
 * - Webcam preview with hand skeleton + neon lines
 * - Gesture state indicator
 * - Eye gaze cursor
 */
export default function HandControlLayer({ graphHandle, children }: Props) {
  const webcamRef = useRef<WebcamPreviewHandle>(null);
  const gestures = useHandGestures();
  const [showCalibration, setShowCalibration] = useState(false);

  // Connect graph handle to gesture mapper
  useEffect(() => {
    if (graphHandle) {
      gestures.setGraphHandle(graphHandle);
    }
  }, [graphHandle, gestures.setGraphHandle]);

  // Connect video element from webcam preview
  useEffect(() => {
    const video = webcamRef.current?.getVideoElement();
    gestures.setVideoElement(video ?? null);
  });

  // Keyboard shortcut: G to toggle
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'g' || e.key === 'G') {
        if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
        gestures.toggle();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [gestures.toggle]);

  // Auto-prompt calibration on first enable if not calibrated
  const hasPromptedRef = useRef(false);
  useEffect(() => {
    if (gestures.enabled && !gestures.isCalibrated && !hasPromptedRef.current) {
      hasPromptedRef.current = true;
      // Delay to let eye tracker model download + init
      const timer = setTimeout(() => setShowCalibration(true), 3000);
      return () => clearTimeout(timer);
    }
  }, [gestures.enabled, gestures.isCalibrated]);

  // Set video element once webcam preview mounts
  const handleWebcamMount = useCallback(() => {
    const video = webcamRef.current?.getVideoElement();
    if (video) {
      gestures.setVideoElement(video);
    }
  }, [gestures.setVideoElement]);

  useEffect(() => {
    if (gestures.enabled) {
      handleWebcamMount();
    }
  }, [gestures.enabled, handleWebcamMount]);

  return (
    <div className="relative flex-1 flex">
      {children}

      {/* Gesture toggle button */}
      <GestureToggle
        enabled={gestures.enabled}
        trackerState={gestures.trackerState}
        onToggle={gestures.toggle}
        error={gestures.error}
      />

      {/* Gesture state indicator */}
      <GestureIndicator
        gesture={gestures.gesture}
        visible={gestures.enabled}
      />

      {/* Gaze cursor (Vision Pro style) */}
      <GazeCursor
        gaze={gestures.gazePoint}
        visible={gestures.enabled}
      />

      {/* Webcam preview with overlay */}
      <WebcamPreview
        ref={webcamRef}
        visible={gestures.enabled || gestures.trackerState === 'loading'}
      />

      {/* Hand skeleton + neon lines overlay */}
      {gestures.enabled && webcamRef.current?.getCanvas() && (
        <GestureOverlay
          hands={gestures.hands}
          canvasRef={{ current: webcamRef.current.getCanvas() }}
          width={VISUALS.PREVIEW_WIDTH}
          height={VISUALS.PREVIEW_HEIGHT}
        />
      )}

      {/* Calibrate Eye Tracking button (shown when enabled but not calibrated) */}
      {gestures.enabled && !showCalibration && (
        <button
          onClick={() => setShowCalibration(true)}
          className={`absolute bottom-4 left-1/2 -translate-x-1/2 z-30 px-3 py-1.5 text-xs rounded-lg border transition-colors ${
            gestures.isCalibrated
              ? 'text-green-400 border-green-800 bg-green-950/50 hover:bg-green-900/50'
              : 'text-cyan-400 border-cyan-800 bg-cyan-950/50 hover:bg-cyan-900/50 animate-pulse'
          }`}
        >
          {gestures.isCalibrated ? 'Re-calibrate Eyes' : 'Calibrate Eye Tracking'}
        </button>
      )}

      {/* Auto-prompt calibration on first enable if not calibrated */}
      {/* Calibration overlay */}
      <GazeCalibration
        visible={showCalibration}
        onComplete={() => setShowCalibration(false)}
        onCancel={() => setShowCalibration(false)}
        startSample={gestures.startCalibrationSample}
        finishSample={gestures.finishCalibrationSample}
        finalizeCalibration={gestures.finalizeCalibration}
      />
    </div>
  );
}
