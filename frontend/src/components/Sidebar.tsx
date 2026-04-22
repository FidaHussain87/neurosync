import { useEffect, useState } from 'react';
import type { Neo4jConfig, NodeType, NodeStats } from '../types';
import { NODE_STYLES } from '../constants';
import ConnectionForm from './ConnectionForm';
import QueryRunner from './QueryRunner';
import * as neo4jService from '../services/neo4j';

const ALL_TYPES: NodeType[] = [
  'Session', 'Episode', 'Theory', 'Concept',
  'StructuralPattern', 'FailureRecord', 'Contradiction', 'UserKnowledge',
];

interface Props {
  config: Neo4jConfig;
  connected: boolean;
  connecting: boolean;
  connectionError: string | null;
  onConnect: (config: Neo4jConfig) => void;
  onDisconnect: () => void;
  visibleTypes: Set<NodeType>;
  onToggleType: (type: NodeType) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  projects: string[];
  projectFilter: string;
  onProjectChange: (project: string) => void;
  onRunPrebuilt: (cypher: string, params?: Record<string, unknown>) => void;
  onRunCustom: (cypher: string) => void;
  onLoadOverview: () => void;
  nodeCount: number;
  linkCount: number;
}

export default function Sidebar({
  config, connected, connecting, connectionError,
  onConnect, onDisconnect,
  visibleTypes, onToggleType,
  searchQuery, onSearchChange,
  projects, projectFilter, onProjectChange,
  onRunPrebuilt, onRunCustom,
  onLoadOverview,
  nodeCount, linkCount,
}: Props) {
  const [stats, setStats] = useState<NodeStats | null>(null);

  useEffect(() => {
    if (connected) {
      neo4jService.getStats().then(setStats).catch(() => {});
    } else {
      setStats(null);
    }
  }, [connected]);

  return (
    <aside className="w-72 lg:w-80 flex-shrink-0 bg-gray-950 border-r border-gray-800 p-3 lg:p-4 overflow-y-auto flex flex-col gap-3">
      <div className="flex items-center gap-2 mb-1">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="24" height="24" className="flex-shrink-0">
          <path d="M16 2.5a13.5 13.5 0 0 1 12.73 9" fill="none" stroke="#8B5CF6" strokeWidth="1.5" strokeLinecap="round" opacity="0.6"/>
          <path d="M16 29.5a13.5 13.5 0 0 1-12.73-9" fill="none" stroke="#8B5CF6" strokeWidth="1.5" strokeLinecap="round" opacity="0.6"/>
          <polygon points="28.2,10.5 29.5,12.5 26.5,12" fill="#8B5CF6" opacity="0.6"/>
          <polygon points="3.8,21.5 2.5,19.5 5.5,20" fill="#8B5CF6" opacity="0.6"/>
          <line x1="16" y1="16" x2="10" y2="8" stroke="#3B82F6" strokeWidth="1" opacity="0.5"/>
          <line x1="16" y1="16" x2="23" y2="9" stroke="#F59E0B" strokeWidth="1" opacity="0.5"/>
          <line x1="16" y1="16" x2="8" y2="22" stroke="#06B6D4" strokeWidth="1" opacity="0.5"/>
          <line x1="16" y1="16" x2="24" y2="22" stroke="#EC4899" strokeWidth="1" opacity="0.5"/>
          <line x1="16" y1="16" x2="16" y2="26" stroke="#10B981" strokeWidth="1" opacity="0.5"/>
          <line x1="10" y1="8" x2="23" y2="9" stroke="#6B7280" strokeWidth="0.5" opacity="0.3"/>
          <line x1="8" y1="22" x2="16" y2="26" stroke="#6B7280" strokeWidth="0.5" opacity="0.3"/>
          <line x1="24" y1="22" x2="16" y2="26" stroke="#6B7280" strokeWidth="0.5" opacity="0.3"/>
          <circle cx="10" cy="8" r="2.5" fill="#3B82F6"/>
          <circle cx="23" cy="9" r="2.5" fill="#F59E0B"/>
          <circle cx="8" cy="22" r="2.5" fill="#06B6D4"/>
          <circle cx="24" cy="22" r="2.5" fill="#EC4899"/>
          <circle cx="16" cy="26" r="2" fill="#10B981"/>
          <circle cx="16" cy="16" r="4" fill="#8B5CF6"/>
          <circle cx="16" cy="16" r="4" fill="none" stroke="#A78BFA" strokeWidth="0.8" opacity="0.7"/>
        </svg>
        <h1 className="text-sm font-semibold text-gray-100">NeuroSync Graph</h1>
      </div>

      <ConnectionForm
        config={config}
        connected={connected}
        connecting={connecting}
        error={connectionError}
        onConnect={onConnect}
        onDisconnect={onDisconnect}
      />

      {connected && (
        <>
          <button
            onClick={onLoadOverview}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white text-sm py-1.5 rounded transition-colors"
          >
            Load Overview
          </button>

          {/* Search */}
          <div className="border-b border-gray-800 pb-3">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Search</h3>
            <input
              type="text"
              placeholder="Filter nodes by content\u2026"
              value={searchQuery}
              onChange={e => onSearchChange(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
            />
          </div>

          {/* Project filter */}
          {projects.length > 0 && (
            <div className="border-b border-gray-800 pb-3">
              <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Project</h3>
              <select
                value={projectFilter}
                onChange={e => onProjectChange(e.target.value)}
                className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1.5 text-sm text-gray-200 focus:border-blue-500 focus:outline-none"
              >
                <option value="">All projects</option>
                {projects.map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
          )}

          {/* Node type filters */}
          <div className="border-b border-gray-800 pb-3">
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Node Types</h3>
            <div className="flex flex-wrap gap-1.5">
              {ALL_TYPES.map(type => {
                const style = NODE_STYLES[type];
                const active = visibleTypes.has(type);
                return (
                  <button
                    key={type}
                    onClick={() => onToggleType(type)}
                    className={`px-2 py-0.5 rounded-full text-xs font-medium transition-all ${
                      active ? 'opacity-100' : 'opacity-30'
                    }`}
                    style={{
                      backgroundColor: active ? style.color + '30' : 'transparent',
                      color: style.color,
                      border: `1px solid ${style.color}${active ? '80' : '30'}`,
                    }}
                  >
                    {type === 'StructuralPattern' ? 'Pattern' : type === 'FailureRecord' ? 'Failure' : type === 'UserKnowledge' ? 'Knowledge' : type}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Query runner */}
          <QueryRunner
            onRunPrebuilt={onRunPrebuilt}
            onRunCustom={onRunCustom}
            disabled={!connected}
          />

          {/* Stats */}
          <div>
            <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Current View</h3>
            <div className="text-xs text-gray-500 space-y-0.5">
              <p>{nodeCount} nodes &middot; {linkCount} relationships</p>
            </div>
            {stats && (
              <>
                <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mt-3 mb-2">Database</h3>
                <div className="text-xs text-gray-500 space-y-0.5">
                  {Object.entries(stats.nodes).map(([label, count]) => (
                    <p key={label}>
                      <span style={{ color: NODE_STYLES[label as NodeType]?.color ?? '#6B7280' }}>
                        {label}
                      </span>
                      : {count}
                    </p>
                  ))}
                  <p className="mt-1 text-gray-600">
                    {Object.values(stats.relationships).reduce((a, b) => a + b, 0)} total relationships
                  </p>
                </div>
              </>
            )}
          </div>
        </>
      )}
    </aside>
  );
}
