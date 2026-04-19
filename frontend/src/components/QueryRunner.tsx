import { useState, useRef, useEffect } from 'react';
import { PREBUILT_QUERIES } from '../constants';

interface Props {
  onRunPrebuilt: (cypher: string, params?: Record<string, unknown>) => void;
  onRunCustom: (cypher: string) => void;
  disabled: boolean;
}

export default function QueryRunner({ onRunPrebuilt, onRunCustom, disabled }: Props) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [showCustom, setShowCustom] = useState(false);
  const [customCypher, setCustomCypher] = useState('');
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selected = PREBUILT_QUERIES[selectedIdx];

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [dropdownOpen]);

  const handleRunPrebuilt = () => {
    if (!selected) return;
    const params: Record<string, unknown> = {};
    if (selected.parameters) {
      for (const key of Object.keys(selected.parameters)) {
        if (paramValues[key]) params[key] = paramValues[key];
      }
    }
    onRunPrebuilt(selected.cypher, Object.keys(params).length > 0 ? params : undefined);
  };

  return (
    <div className="border-b border-gray-800 pb-3">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Queries</h3>

      {/* Custom dropdown */}
      <div ref={dropdownRef} className="relative mb-2">
        <button
          type="button"
          onClick={() => !disabled && setDropdownOpen(!dropdownOpen)}
          disabled={disabled}
          className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 text-left flex items-center justify-between focus:border-blue-500 focus:outline-none disabled:opacity-50"
        >
          <span className="truncate">{selected?.name.replace(/_/g, ' ') ?? 'Select query'}</span>
          <svg
            className={`w-3.5 h-3.5 text-gray-500 flex-shrink-0 ml-1 transition-transform ${dropdownOpen ? 'rotate-180' : ''}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {dropdownOpen && (
          <div className="absolute z-20 mt-1 w-full bg-gray-900 border border-gray-700 rounded shadow-lg max-h-52 overflow-y-auto scrollbar-hidden">
            {PREBUILT_QUERIES.map((q, i) => (
              <button
                key={q.name}
                onClick={() => {
                  setSelectedIdx(i);
                  setParamValues({});
                  setDropdownOpen(false);
                }}
                className={`w-full text-left px-2.5 py-1.5 text-sm transition-colors ${
                  i === selectedIdx
                    ? 'bg-purple-600/20 text-purple-300'
                    : 'text-gray-300 hover:bg-gray-800 hover:text-gray-100'
                }`}
              >
                {q.name.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
        )}
      </div>

      <p className="text-xs text-gray-500 mb-2">{selected?.description}</p>

      {selected?.parameters && Object.entries(selected.parameters).map(([key, placeholder]) => (
        <input
          key={key}
          type="text"
          placeholder={placeholder}
          value={paramValues[key] ?? ''}
          onChange={e => setParamValues({ ...paramValues, [key]: e.target.value })}
          disabled={disabled}
          className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none mb-2"
        />
      ))}

      <button
        onClick={handleRunPrebuilt}
        disabled={disabled}
        className="w-full bg-purple-600 hover:bg-purple-700 disabled:bg-gray-700 text-white text-sm py-1.5 rounded transition-colors mb-2"
      >
        Run Query
      </button>

      <button
        onClick={() => setShowCustom(!showCustom)}
        className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
      >
        {showCustom ? 'Hide' : 'Show'} custom Cypher
      </button>

      {showCustom && (
        <div className="mt-2">
          <textarea
            value={customCypher}
            onChange={e => setCustomCypher(e.target.value)}
            disabled={disabled}
            placeholder="MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 100"
            rows={4}
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 font-mono focus:border-blue-500 focus:outline-none resize-y"
          />
          <button
            onClick={() => customCypher.trim() && onRunCustom(customCypher)}
            disabled={disabled || !customCypher.trim()}
            className="w-full mt-1 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 text-white text-sm py-1.5 rounded transition-colors"
          >
            Execute Cypher
          </button>
        </div>
      )}
    </div>
  );
}
