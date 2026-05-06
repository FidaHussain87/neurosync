import { useState, useEffect, useRef } from 'react';

interface Props {
  visible: boolean;
  onComplete: () => void;
  onCancel: () => void;
  startSample: () => void;
  finishSample: (screenX: number, screenY: number) => boolean;
  finalizeCalibration: () => boolean;
}

// 9-point grid positions (normalized 0-1)
const CALIBRATION_POINTS = [
  { x: 0.5,  y: 0.5  }, // center first
  { x: 0.15, y: 0.15 }, // top-left
  { x: 0.85, y: 0.15 }, // top-right
  { x: 0.15, y: 0.85 }, // bottom-left
  { x: 0.85, y: 0.85 }, // bottom-right
  { x: 0.5,  y: 0.15 }, // top-center
  { x: 0.5,  y: 0.85 }, // bottom-center
  { x: 0.15, y: 0.5  }, // left-center
  { x: 0.85, y: 0.5  }, // right-center
];

const SETTLE_TIME = 1500;
const SAMPLE_TIME = 1200;

type Phase = 'intro' | 'active' | 'done' | 'failed';

export default function GazeCalibration({
  visible,
  onComplete,
  onCancel,
  startSample,
  finishSample,
  finalizeCalibration,
}: Props) {
  const [phase, setPhase] = useState<Phase>('intro');
  const [pointIndex, setPointIndex] = useState(0);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState('');

  const animFrameRef = useRef(0);
  const cancelledRef = useRef(false);
  const retryRef = useRef(0);

  // Keep prop refs current for RAF callbacks
  const startSampleRef = useRef(startSample);
  const finishSampleRef = useRef(finishSample);
  const finalizeCbRef = useRef(finalizeCalibration);
  const onCompleteRef = useRef(onComplete);
  startSampleRef.current = startSample;
  finishSampleRef.current = finishSample;
  finalizeCbRef.current = finalizeCalibration;
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (visible) {
      setPhase('intro');
      setPointIndex(0);
      setProgress(0);
      cancelledRef.current = false;
      retryRef.current = 0;
    } else {
      cancelledRef.current = true;
      if (animFrameRef.current) {
        cancelAnimationFrame(animFrameRef.current);
        animFrameRef.current = 0;
      }
    }
  }, [visible]);

  useEffect(() => {
    return () => {
      cancelledRef.current = true;
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, []);

  const advanceOrFinalize = (nextIdx: number) => {
    if (nextIdx >= CALIBRATION_POINTS.length) {
      const ok = finalizeCbRef.current();
      if (ok) {
        setPhase('done');
        setTimeout(() => {
          if (!cancelledRef.current) onCompleteRef.current();
        }, 1000);
      } else {
        setPhase('failed');
      }
    } else {
      setProgress(0);
      setTimeout(() => {
        if (!cancelledRef.current) runPoint(nextIdx);
      }, 500);
    }
  };

  const runPoint = (idx: number) => {
    if (cancelledRef.current) return;

    setPointIndex(idx);
    setProgress(0);
    setStatus('Look at the dot...');
    retryRef.current = 0;

    const settleStart = performance.now();
    let samplingStarted = false;

    const tick = () => {
      if (cancelledRef.current) return;
      const now = performance.now();
      const elapsed = now - settleStart;

      // Phase 1: settling
      if (elapsed < SETTLE_TIME) {
        setProgress((elapsed / SETTLE_TIME) * 0.3);
        animFrameRef.current = requestAnimationFrame(tick);
        return;
      }

      // Phase 2: start sample collection (once)
      if (!samplingStarted) {
        samplingStarted = true;
        setStatus('Hold your gaze...');
        startSampleRef.current();
      }

      const sampleElapsed = elapsed - SETTLE_TIME;

      if (sampleElapsed < SAMPLE_TIME) {
        setProgress(0.3 + (sampleElapsed / SAMPLE_TIME) * 0.7);
        animFrameRef.current = requestAnimationFrame(tick);
        return;
      }

      // Phase 3: finish
      const point = CALIBRATION_POINTS[idx];
      const success = finishSampleRef.current(point.x, point.y);

      if (success) {
        advanceOrFinalize(idx + 1);
      } else {
        retryRef.current++;
        if (retryRef.current >= 2) {
          // Skip this point after 2 failures
          console.warn(`[Calibration] Skipping point ${idx + 1} after ${retryRef.current} retries`);
          advanceOrFinalize(idx + 1);
        } else {
          // Retry
          setTimeout(() => {
            if (!cancelledRef.current) runPoint(idx);
          }, 300);
        }
      }
    };

    animFrameRef.current = requestAnimationFrame(tick);
  };

  const handleStart = () => {
    setPhase('active');
    cancelledRef.current = false;
    runPoint(0);
  };

  const handleCancel = () => {
    cancelledRef.current = true;
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = 0;
    }
    onCancel();
  };

  if (!visible) return null;

  const point = CALIBRATION_POINTS[pointIndex];

  return (
    <div className="fixed inset-0 z-[100] bg-gray-950/90 flex items-center justify-center">
      {phase === 'intro' && (
        <div className="text-center max-w-md">
          <div className="w-16 h-16 mx-auto mb-6 rounded-full border-2 border-cyan-400 flex items-center justify-center">
            <div className="w-4 h-4 rounded-full bg-cyan-400 animate-pulse" />
          </div>
          <h2 className="text-xl font-medium text-white mb-3">Eye Tracking Calibration</h2>
          <p className="text-gray-400 mb-2 text-sm leading-relaxed">
            Look at each dot as it appears on screen. Keep your head still and only move your eyes.
          </p>
          <p className="text-gray-500 mb-6 text-xs">
            Make sure your face is visible in the laptop camera. Takes about 25 seconds.
          </p>
          <div className="flex gap-3 justify-center">
            <button
              onClick={handleCancel}
              className="px-4 py-2 text-sm text-gray-400 hover:text-white border border-gray-700 rounded-lg hover:border-gray-500 transition-colors"
            >
              Skip
            </button>
            <button
              onClick={handleStart}
              className="px-6 py-2 text-sm text-white bg-cyan-600 hover:bg-cyan-500 rounded-lg transition-colors font-medium"
            >
              Start Calibration
            </button>
          </div>
        </div>
      )}

      {phase === 'active' && (
        <>
          <div className="absolute top-6 left-1/2 -translate-x-1/2 text-gray-500 text-xs">
            Point {pointIndex + 1} of {CALIBRATION_POINTS.length}
          </div>

          <div
            className="absolute transition-all duration-400 ease-out"
            style={{
              left: `${point.x * 100}%`,
              top: `${point.y * 100}%`,
              transform: 'translate(-50%, -50%)',
            }}
          >
            <svg width="60" height="60" className="absolute -top-[30px] -left-[30px]">
              <circle cx="30" cy="30" r="25" fill="none" stroke="rgba(34, 211, 238, 0.15)" strokeWidth="3" />
              <circle
                cx="30" cy="30" r="25"
                fill="none" stroke="#22D3EE" strokeWidth="3"
                strokeDasharray={`${progress * 157} 157`}
                strokeLinecap="round"
                transform="rotate(-90 30 30)"
              />
            </svg>

            <div
              className={`w-5 h-5 rounded-full transition-all duration-300 ${
                progress > 0.3
                  ? 'bg-cyan-300 shadow-[0_0_25px_rgba(34,211,238,0.9)]'
                  : 'bg-cyan-500 shadow-[0_0_12px_rgba(34,211,238,0.5)]'
              }`}
              style={{ transform: 'translate(-50%, -50%)' }}
            />

            {progress > 0.3 && (
              <div
                className="absolute w-10 h-10 rounded-full border-2 border-cyan-400/40 animate-ping"
                style={{ top: '-5px', left: '-5px', transform: 'translate(-50%, -50%)', animationDuration: '1.5s' }}
              />
            )}
          </div>

          <div className="absolute bottom-10 left-1/2 -translate-x-1/2 text-gray-500 text-xs">
            {status}
          </div>

          <button
            onClick={handleCancel}
            className="absolute top-6 right-6 text-gray-500 hover:text-white text-xs border border-gray-700 px-3 py-1.5 rounded hover:border-gray-500 transition-colors"
          >
            Cancel
          </button>
        </>
      )}

      {phase === 'done' && (
        <div className="text-center">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-green-500/20 border-2 border-green-400 flex items-center justify-center">
            <svg className="w-8 h-8 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-lg font-medium text-white mb-2">Calibration Complete</h2>
          <p className="text-gray-400 text-sm">Eye tracking is personalized to your setup.</p>
        </div>
      )}

      {phase === 'failed' && (
        <div className="text-center max-w-sm">
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-red-500/20 border-2 border-red-400 flex items-center justify-center">
            <span className="text-2xl text-red-400">!</span>
          </div>
          <h2 className="text-lg font-medium text-white mb-2">Calibration Failed</h2>
          <p className="text-gray-400 text-sm mb-4">
            Could not detect your eyes. Make sure your face is well-lit and visible in the laptop camera.
          </p>
          <div className="flex gap-3 justify-center">
            <button
              onClick={handleCancel}
              className="px-4 py-2 text-sm text-gray-400 border border-gray-700 rounded-lg hover:border-gray-500 transition-colors"
            >
              Close
            </button>
            <button
              onClick={() => { setPhase('intro'); }}
              className="px-4 py-2 text-sm text-white bg-cyan-600 hover:bg-cyan-500 rounded-lg transition-colors"
            >
              Try Again
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
