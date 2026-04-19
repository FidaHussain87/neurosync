import { useState, useEffect } from 'react';
import type { Neo4jConfig } from '../types';

interface Props {
  config: Neo4jConfig;
  connected: boolean;
  connecting: boolean;
  error: string | null;
  onConnect: (config: Neo4jConfig) => void;
  onDisconnect: () => void;
}

export default function ConnectionForm({ config, connected, connecting, error, onConnect, onDisconnect }: Props) {
  const [form, setForm] = useState<Neo4jConfig>(config);
  const [expanded, setExpanded] = useState(false);

  // Auto-collapse when connection succeeds, auto-expand when disconnected
  useEffect(() => {
    setExpanded(!connected);
  }, [connected]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onConnect(form);
  };

  // When connected, show compact status bar
  if (connected && !expanded) {
    return (
      <div className="border-b border-gray-800 pb-3">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" />
          <span className="text-xs text-gray-400 truncate flex-1" title={form.uri}>
            {form.uri}
          </span>
          <button
            onClick={() => setExpanded(true)}
            className="text-gray-600 hover:text-gray-300 transition-colors flex-shrink-0"
            title="Edit connection"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </button>
          <button
            onClick={onDisconnect}
            className="text-xs text-red-500 hover:text-red-400 transition-colors flex-shrink-0"
          >
            Disconnect
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="border-b border-gray-800 pb-3">
      {/* Header — only show when form is expanded and connected (editing mode) */}
      {connected && expanded && (
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-xs text-gray-400">Connected</span>
          </div>
          <button
            onClick={() => setExpanded(false)}
            className="text-gray-600 hover:text-gray-300 text-xs"
          >
            Collapse
          </button>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-2">
        <input
          type="text"
          placeholder="bolt://localhost:7687"
          value={form.uri}
          onChange={e => setForm({ ...form, uri: e.target.value })}
          className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
        />
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="User"
            value={form.user}
            onChange={e => setForm({ ...form, user: e.target.value })}
            className="flex-1 min-w-0 bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
          <input
            type="password"
            placeholder="Password"
            value={form.password}
            onChange={e => setForm({ ...form, password: e.target.value })}
            className="flex-1 min-w-0 bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
          />
        </div>
        <input
          type="text"
          placeholder="Database (neo4j)"
          value={form.database}
          onChange={e => setForm({ ...form, database: e.target.value })}
          className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
        />
        <div className="flex gap-2">
          {!connected ? (
            <button
              type="submit"
              disabled={connecting}
              className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-700 text-white text-sm py-1.5 rounded transition-colors"
            >
              {connecting ? 'Connecting\u2026' : 'Connect'}
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={() => setExpanded(false)}
                className="flex-1 bg-gray-700 hover:bg-gray-600 text-white text-sm py-1.5 rounded transition-colors"
              >
                Done
              </button>
              <button
                type="button"
                onClick={onDisconnect}
                className="flex-1 bg-red-600 hover:bg-red-700 text-white text-sm py-1.5 rounded transition-colors"
              >
                Disconnect
              </button>
            </>
          )}
        </div>
        {error && <p className="text-red-400 text-xs">{error}</p>}
      </form>
    </div>
  );
}
