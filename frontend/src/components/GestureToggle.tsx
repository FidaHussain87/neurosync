import type { TrackerState } from '../gestures/types';

interface Props {
  enabled: boolean;
  trackerState: TrackerState;
  onToggle: () => void;
  error: string | null;
}

/**
 * Toggle button for hand gesture control mode.
 * Shows loading spinner during model initialization.
 */
export default function GestureToggle({ enabled, trackerState, onToggle, error }: Props) {
  const isLoading = trackerState === 'loading';

  return (
    <div className="absolute bottom-4 left-4 z-30 flex flex-col items-start gap-2">
      <button
        onClick={onToggle}
        disabled={isLoading}
        className={`
          flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium
          transition-all duration-300 backdrop-blur-sm
          ${enabled
            ? 'bg-cyan-900/60 text-cyan-200 border-2 border-cyan-400 shadow-[0_0_20px_rgba(0,255,255,0.3)]'
            : 'bg-gray-900/70 text-gray-300 border border-gray-700 hover:border-cyan-600 hover:text-cyan-200 hover:shadow-[0_0_10px_rgba(0,255,255,0.15)]'
          }
          ${isLoading ? 'opacity-70 cursor-wait' : 'cursor-pointer'}
        `}
      >
        {isLoading ? (
          <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        ) : (
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M7 11.5V14m0-2.5v-6a1.5 1.5 0 113 0m-3 6a1.5 1.5 0 00-3 0v2a7.5 7.5 0 0015 0v-5a1.5 1.5 0 00-3 0m-6-3V11m0-5.5v-1a1.5 1.5 0 013 0v1m0 0V11m0-5.5a1.5 1.5 0 013 0v3m0 0V11" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
        <span>{enabled ? 'Hand Control Active' : 'Enable Hand Control'}</span>
        {enabled && (
          <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
        )}
      </button>

      {/* Keyboard shortcut hint */}
      {!enabled && !error && (
        <span className="text-[10px] text-gray-600 pl-1">Press G to toggle</span>
      )}

      {/* Error message */}
      {error && (
        <div className="text-xs text-red-400 bg-red-900/40 border border-red-800/50 rounded-lg px-3 py-1.5 max-w-[240px]">
          {error}
        </div>
      )}
    </div>
  );
}
