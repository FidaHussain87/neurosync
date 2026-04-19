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
        <div className="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center">
          <span className="text-white text-xs font-bold">N</span>
        </div>
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
