import { useRef, useEffect, forwardRef, useImperativeHandle } from 'react';
import { VISUALS } from '../gestures/constants';

interface Props {
  visible: boolean;
}

export interface WebcamPreviewHandle {
  getVideoElement: () => HTMLVideoElement | null;
  getCanvas: () => HTMLCanvasElement | null;
  getContext: () => CanvasRenderingContext2D | null;
}

/**
 * Picture-in-picture webcam feed with canvas overlay for drawing hand skeleton.
 * Positioned bottom-right of the viewport.
 */
const WebcamPreview = forwardRef<WebcamPreviewHandle, Props>(({ visible }, ref) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useImperativeHandle(ref, () => ({
    getVideoElement: () => videoRef.current,
    getCanvas: () => canvasRef.current,
    getContext: () => canvasRef.current?.getContext('2d') ?? null,
  }));

  // Keep canvas size in sync with video
  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const syncSize = () => {
      canvas.width = VISUALS.PREVIEW_WIDTH;
      canvas.height = VISUALS.PREVIEW_HEIGHT;
    };
    syncSize();
    video.addEventListener('loadedmetadata', syncSize);
    return () => video.removeEventListener('loadedmetadata', syncSize);
  }, []);

  if (!visible) return null;

  return (
    <div
      className="absolute bottom-4 right-4 z-30 rounded-xl overflow-hidden shadow-2xl"
      style={{
        width: VISUALS.PREVIEW_WIDTH,
        height: VISUALS.PREVIEW_HEIGHT,
        boxShadow: '0 0 20px rgba(0, 255, 255, 0.3), 0 0 40px rgba(0, 255, 255, 0.1)',
        border: '2px solid rgba(0, 255, 255, 0.5)',
      }}
    >
      {/* Mirrored webcam feed */}
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-cover"
        style={{ transform: 'scaleX(-1)' }}
        autoPlay
        playsInline
        muted
      />
      {/* Canvas overlay for hand skeleton + neon lines */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full"
        style={{ transform: 'scaleX(-1)' }}
      />
      {/* Corner label */}
      <div className="absolute top-2 left-2 bg-black/60 rounded px-2 py-0.5 text-[10px] text-cyan-300 font-mono">
        HAND TRACKING
      </div>
    </div>
  );
});

WebcamPreview.displayName = 'WebcamPreview';
export default WebcamPreview;
