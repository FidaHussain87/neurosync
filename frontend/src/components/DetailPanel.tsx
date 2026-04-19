import React from 'react';
import type { GraphNode, GraphLink, NodeType } from '../types';
import { NODE_STYLES } from '../constants';

interface Props {
  node: GraphNode;
  links: GraphLink[];
  allNodes: GraphNode[];
  onNodeClick: (nodeId: string, label: string) => void;
  onClose: () => void;
}

function formatValue(key: string, value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-gray-600">null</span>;

  // Confidence as progress bar
  if (key === 'confidence' && typeof value === 'number') {
    return (
      <div className="flex items-center gap-2">
        <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-amber-500 rounded-full transition-all"
            style={{ width: `${value * 100}%` }}
          />
        </div>
        <span className="text-xs text-gray-400">{(value * 100).toFixed(0)}%</span>
      </div>
    );
  }

  // Arrays as tag chips
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-gray-600">[]</span>;
    return (
      <div className="flex flex-wrap gap-1">
        {value.map((item, i) => (
          <span key={i} className="px-1.5 py-0.5 bg-gray-800 rounded text-xs text-gray-300">
            {String(item)}
          </span>
        ))}
      </div>
    );
  }

  // Timestamps
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value)) {
    try {
      return <span>{new Date(value).toLocaleString()}</span>;
    } catch {
      // fall through
    }
  }

  // Booleans
  if (typeof value === 'boolean') {
    return <span className={value ? 'text-green-400' : 'text-red-400'}>{value.toString()}</span>;
  }

  // Long text
  const str = String(value);
  if (str.length > 200) {
    return <span className="text-gray-300 break-words whitespace-pre-wrap">{str}</span>;
  }
  return <span className="text-gray-300 break-words">{str}</span>;
}

export default function DetailPanel({ node, links, allNodes, onNodeClick, onClose }: Props) {
  const style = NODE_STYLES[node.label as NodeType] ?? { color: '#6B7280' };

  // Find connected nodes
  const connections = links
    .filter(l => {
      const src = typeof l.source === 'object' ? (l.source as GraphNode).id : l.source;
      const tgt = typeof l.target === 'object' ? (l.target as GraphNode).id : l.target;
      return src === node.id || tgt === node.id;
    })
    .map(l => {
      const src = typeof l.source === 'object' ? (l.source as GraphNode).id : l.source;
      const tgt = typeof l.target === 'object' ? (l.target as GraphNode).id : l.target;
      const otherId = src === node.id ? tgt : src;
      const direction = src === node.id ? 'outgoing' : 'incoming';
      const other = allNodes.find(n => n.id === otherId);
      return { relType: l.type, direction, otherId, other };
    });

  // Group by relationship type
  const grouped = connections.reduce<Record<string, typeof connections>>((acc, c) => {
    const key = `${c.direction === 'incoming' ? '\u2190' : '\u2192'} ${c.relType}`;
    (acc[key] ??= []).push(c);
    return acc;
  }, {});

  // Filter out internal/uninteresting properties
  const displayProps = Object.entries(node.properties).filter(
    ([key]) => !['id'].includes(key),
  );

  return (
    <div className="w-96 h-full bg-gray-950 border-l border-gray-800 overflow-y-auto shadow-[-8px_0_24px_rgba(0,0,0,0.5)]">
      {/* Header */}
      <div className="sticky top-0 bg-gray-950 border-b border-gray-800 p-4 flex items-start justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="px-2 py-0.5 rounded text-xs font-medium flex-shrink-0"
            style={{ backgroundColor: style.color + '30', color: style.color }}
          >
            {node.label}
          </span>
          <p className="text-sm font-medium text-gray-100 truncate">{node.name}</p>
        </div>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-white transition-colors flex-shrink-0 ml-2"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Properties */}
      <div className="p-4">
        <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Properties</h3>
        <div className="space-y-2">
          {displayProps.map(([key, value]) => (
            <div key={key}>
              <dt className="text-xs text-gray-500 mb-0.5">{key}</dt>
              <dd className="text-sm">{formatValue(key, value)}</dd>
            </div>
          ))}
          {displayProps.length === 0 && (
            <p className="text-xs text-gray-600">No properties</p>
          )}
        </div>
      </div>

      {/* Connections */}
      {Object.keys(grouped).length > 0 && (
        <div className="p-4 border-t border-gray-800">
          <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
            Connections ({connections.length})
          </h3>
          <div className="space-y-3">
            {Object.entries(grouped).map(([key, conns]) => (
              <div key={key}>
                <p className="text-xs text-gray-500 font-mono mb-1">{key}</p>
                <div className="space-y-1">
                  {conns.map((c, i) => {
                    const otherStyle = c.other
                      ? NODE_STYLES[c.other.label as NodeType] ?? { color: '#6B7280' }
                      : { color: '#6B7280' };
                    return (
                      <button
                        key={i}
                        onClick={() => c.other && onNodeClick(c.other.id, c.other.label)}
                        className="w-full text-left flex items-center gap-2 px-2 py-1 rounded hover:bg-gray-900 transition-colors"
                      >
                        <span
                          className="w-2 h-2 rounded-full flex-shrink-0"
                          style={{ backgroundColor: otherStyle.color }}
                        />
                        <span className="text-xs text-gray-300 truncate">
                          {c.other?.name ?? c.otherId}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
