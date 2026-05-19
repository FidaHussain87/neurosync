import { useState, useCallback } from 'react';
import * as neo4jService from '../services/neo4j';
import type { GraphData } from '../types';

interface SurprisingConnection {
  theory_a: { id: string; content: string };
  theory_b: { id: string; content: string };
  score: number;
  reasons: string[];
  connection_type: string;
}

interface SuggestedQuestion {
  question: string;
  type: string;
  why: string;
  related_theories: string[];
}

interface GodTheory {
  id: string;
  content: string;
  degree: number;
  domains: string[];
}

interface SurpriseData {
  surprises: SurprisingConnection[];
  questions: SuggestedQuestion[];
  god_theories: GodTheory[];
  stats: Record<string, unknown>;
}

interface Props {
  onVisualizeSurprise: (data: GraphData) => void;
}

const CONNECTION_TYPE_COLORS: Record<string, string> = {
  cross_domain: '#F59E0B',
  cross_project: '#8B5CF6',
  unexpected_similarity: '#06B6D4',
};

const CONNECTION_TYPE_LABELS: Record<string, string> = {
  cross_domain: 'Cross-Domain',
  cross_project: 'Cross-Project',
  unexpected_similarity: 'Unexpected',
};

const QUESTION_TYPE_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  bridge_node: { icon: '\u2693', color: '#F59E0B', label: 'Bridge' },
  weak_theory: { icon: '\u26A0\uFE0F', color: '#EF4444', label: 'Weak' },
  knowledge_gap: { icon: '\u2753', color: '#8B5CF6', label: 'Gap' },
  isolated: { icon: '\uD83C\uDFDD\uFE0F', color: '#06B6D4', label: 'Isolated' },
  ambiguous_link: { icon: '\u2694\uFE0F', color: '#EC4899', label: 'Ambiguous' },
};

type Tab = 'hubs' | 'surprises' | 'questions';

export default function SurprisePanel({ onVisualizeSurprise }: Props) {
  const [data, setData] = useState<SurpriseData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>('surprises');

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await neo4jService.runQuery(`
        MATCH (t:Theory {active: true})
        OPTIONAL MATCH (t)-[r:RELATED_TO|PARENT_OF]->(t2:Theory {active: true})
        WITH t, collect(DISTINCT t2) AS related, count(r) AS degree
        RETURN t, degree, related
        ORDER BY degree DESC
        LIMIT 200
      `);

      const surpriseData = analyzeGraphForSurprises(result);
      setData(surpriseData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const visualizeSurprise = useCallback(async (theoryAId: string, theoryBId: string) => {
    try {
      const result = await neo4jService.runQuery(
        `MATCH (a {id: $idA}), (b {id: $idB})
         OPTIONAL MATCH path = shortestPath((a)-[*..4]-(b))
         OPTIONAL MATCH (a)-[ra]-(na)
         OPTIONAL MATCH (b)-[rb]-(nb)
         RETURN a, b, path, ra, na, rb, nb`,
        { idA: theoryAId, idB: theoryBId },
      );
      onVisualizeSurprise(result);
    } catch {
      // silent fail
    }
  }, [onVisualizeSurprise]);

  const tabCounts = data ? {
    hubs: data.god_theories.length,
    surprises: data.surprises.length,
    questions: data.questions.length,
  } : { hubs: 0, surprises: 0, questions: 0 };

  return (
    <div className="border-b border-gray-800 pb-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center justify-between w-full text-left group"
      >
        <div className="flex items-center gap-1.5">
          <svg width="14" height="14" viewBox="0 0 16 16" className="text-amber-500 flex-shrink-0">
            <path d="M8 1l2.2 4.4 4.8.7-3.5 3.4.8 4.9L8 12l-4.3 2.4.8-4.9L1 6.1l4.8-.7z" fill="currentColor" opacity="0.8"/>
          </svg>
          <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider">
            Surprises
          </h3>
          {data && (
            <span className="text-[10px] text-amber-500/70 font-medium ml-1">
              {data.surprises.length + data.god_theories.length + data.questions.length}
            </span>
          )}
        </div>
        <span className="text-gray-600 text-xs group-hover:text-gray-400 transition-colors">
          {expanded ? '\u25BC' : '\u25B6'}
        </span>
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          {/* Action button */}
          <button
            onClick={runAnalysis}
            disabled={loading}
            className="w-full bg-gradient-to-r from-amber-600/20 to-orange-600/20 hover:from-amber-600/30 hover:to-orange-600/30 border border-amber-600/40 text-amber-200 text-xs py-2 rounded-md transition-all disabled:opacity-50 flex items-center justify-center gap-1.5"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Analyzing\u2026
              </>
            ) : (
              <>
                <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" opacity="0.8">
                  <path d="M8 1l2.2 4.4 4.8.7-3.5 3.4.8 4.9L8 12l-4.3 2.4.8-4.9L1 6.1l4.8-.7z"/>
                </svg>
                Detect Surprises
              </>
            )}
          </button>

          {error && (
            <div className="text-xs text-red-400 bg-red-900/20 border border-red-800/40 rounded px-2 py-1.5">
              {error}
            </div>
          )}

          {data && (
            <div className="space-y-2">
              {/* Stats summary */}
              <div className="grid grid-cols-3 gap-1">
                <div className="bg-gray-900/60 rounded px-2 py-1.5 text-center">
                  <p className="text-xs font-semibold text-gray-200">{(data.stats.theories_analyzed as number) ?? 0}</p>
                  <p className="text-[9px] text-gray-500 uppercase">Theories</p>
                </div>
                <div className="bg-gray-900/60 rounded px-2 py-1.5 text-center">
                  <p className="text-xs font-semibold text-gray-200">{(data.stats.edges_analyzed as number) ?? 0}</p>
                  <p className="text-[9px] text-gray-500 uppercase">Edges</p>
                </div>
                <div className="bg-gray-900/60 rounded px-2 py-1.5 text-center">
                  <p className="text-xs font-semibold text-gray-200">{(data.stats.domains_covered as number) ?? 0}</p>
                  <p className="text-[9px] text-gray-500 uppercase">Domains</p>
                </div>
              </div>

              {/* Tabs */}
              <div className="flex border-b border-gray-800">
                {([
                  { key: 'hubs' as Tab, label: 'Hubs' },
                  { key: 'surprises' as Tab, label: 'Links' },
                  { key: 'questions' as Tab, label: 'Questions' },
                ]).map(tab => (
                  <button
                    key={tab.key}
                    onClick={() => setActiveTab(tab.key)}
                    className={`flex-1 py-1.5 text-[11px] font-medium transition-colors relative ${
                      activeTab === tab.key
                        ? 'text-amber-400'
                        : 'text-gray-500 hover:text-gray-300'
                    }`}
                  >
                    {tab.label}
                    {tabCounts[tab.key] > 0 && (
                      <span className={`ml-1 text-[9px] px-1 py-0.5 rounded-full ${
                        activeTab === tab.key ? 'bg-amber-500/20 text-amber-400' : 'bg-gray-800 text-gray-500'
                      }`}>
                        {tabCounts[tab.key]}
                      </span>
                    )}
                    {activeTab === tab.key && (
                      <span className="absolute bottom-0 left-1 right-1 h-0.5 bg-amber-500 rounded-full" />
                    )}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div className="max-h-[320px] overflow-y-auto pr-0.5">
                {/* Hubs tab */}
                {activeTab === 'hubs' && (
                  <div className="space-y-1.5">
                    {data.god_theories.length === 0 ? (
                      <p className="text-xs text-gray-500 italic py-2 text-center">No hub theories detected</p>
                    ) : data.god_theories.map((god, i) => (
                      <div
                        key={god.id}
                        className="p-2 rounded-md bg-gray-900/60 border-l-2 border-amber-500/60 hover:bg-gray-900/80 transition-colors"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-[11px] text-gray-200 leading-relaxed flex-1">{god.content}</p>
                          <span className="flex-shrink-0 bg-amber-500/20 text-amber-400 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                            {god.degree}
                          </span>
                        </div>
                        {god.domains.length > 0 && (
                          <div className="flex gap-1 mt-1.5 flex-wrap">
                            {god.domains.map(d => (
                              <span key={d} className="text-[9px] px-1.5 py-0.5 rounded-full bg-gray-800 text-gray-400 border border-gray-700/50">
                                {d}
                              </span>
                            ))}
                          </div>
                        )}
                        <div className="mt-1.5 flex items-center gap-1">
                          <span className="text-[9px] text-gray-600">#{i + 1}</span>
                          <div className="flex-1 h-1 bg-gray-800 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-amber-500/50 rounded-full"
                              style={{ width: `${Math.min(100, (god.degree / (data.god_theories[0]?.degree || 1)) * 100)}%` }}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {/* Surprises tab */}
                {activeTab === 'surprises' && (
                  <div className="space-y-1.5">
                    {data.surprises.length === 0 ? (
                      <p className="text-xs text-gray-500 italic py-2 text-center">No surprising connections found</p>
                    ) : (
                      <>
                        {/* Legend */}
                        <div className="flex flex-wrap gap-2 py-1.5 mb-1">
                          {Object.entries(CONNECTION_TYPE_COLORS).map(([type, color]) => (
                            <div key={type} className="flex items-center gap-1">
                              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                              <span className="text-[9px] text-gray-500">{CONNECTION_TYPE_LABELS[type]}</span>
                            </div>
                          ))}
                        </div>

                        {data.surprises.map((s, i) => (
                          <button
                            key={i}
                            onClick={() => visualizeSurprise(s.theory_a.id, s.theory_b.id)}
                            className="w-full text-left p-2 rounded-md bg-gray-900/60 border-l-2 hover:bg-gray-900/80 transition-all group"
                            style={{ borderLeftColor: CONNECTION_TYPE_COLORS[s.connection_type] || '#6B7280' }}
                          >
                            {/* Header with type badge and score */}
                            <div className="flex items-center justify-between mb-1.5">
                              <span
                                className="text-[9px] font-medium px-1.5 py-0.5 rounded-full"
                                style={{
                                  backgroundColor: (CONNECTION_TYPE_COLORS[s.connection_type] || '#6B7280') + '20',
                                  color: CONNECTION_TYPE_COLORS[s.connection_type] || '#6B7280',
                                }}
                              >
                                {CONNECTION_TYPE_LABELS[s.connection_type] || s.connection_type}
                              </span>
                              <div className="flex items-center gap-1">
                                <span className="text-[9px] text-gray-500">score</span>
                                <span className="text-[10px] font-bold text-gray-300 bg-gray-800 px-1.5 py-0.5 rounded">
                                  {s.score}
                                </span>
                              </div>
                            </div>

                            {/* Theory pair */}
                            <div className="space-y-1">
                              <p className="text-[11px] text-gray-200 leading-relaxed line-clamp-2">{s.theory_a.content}</p>
                              <div className="flex items-center gap-1.5 py-0.5">
                                <span className="flex-1 h-px bg-gray-700/50" />
                                <svg width="10" height="10" viewBox="0 0 16 16" className="text-gray-500 flex-shrink-0 group-hover:text-amber-500 transition-colors">
                                  <path d="M8 2v12M4 10l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
                                </svg>
                                <span className="flex-1 h-px bg-gray-700/50" />
                              </div>
                              <p className="text-[11px] text-gray-200 leading-relaxed line-clamp-2">{s.theory_b.content}</p>
                            </div>

                            {/* Reasons */}
                            {s.reasons.length > 0 && (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {s.reasons.slice(0, 2).map((r, ri) => (
                                  <span key={ri} className="text-[9px] text-gray-500 bg-gray-800/80 px-1.5 py-0.5 rounded">
                                    {r}
                                  </span>
                                ))}
                              </div>
                            )}

                            {/* Click hint */}
                            <p className="text-[9px] text-gray-600 mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                              Click to visualize path
                            </p>
                          </button>
                        ))}
                      </>
                    )}
                  </div>
                )}

                {/* Questions tab */}
                {activeTab === 'questions' && (
                  <div className="space-y-1.5">
                    {data.questions.length === 0 ? (
                      <p className="text-xs text-gray-500 italic py-2 text-center">No research questions generated</p>
                    ) : data.questions.map((q, i) => {
                      const config = QUESTION_TYPE_CONFIG[q.type] || { icon: '\u2753', color: '#6B7280', label: q.type };
                      return (
                        <div
                          key={i}
                          className="p-2 rounded-md bg-gray-900/60 border-l-2 hover:bg-gray-900/80 transition-colors"
                          style={{ borderLeftColor: config.color }}
                        >
                          {/* Type badge */}
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className="text-sm leading-none">{config.icon}</span>
                            <span
                              className="text-[9px] font-medium px-1.5 py-0.5 rounded-full uppercase"
                              style={{ backgroundColor: config.color + '20', color: config.color }}
                            >
                              {config.label}
                            </span>
                          </div>

                          {/* Question text */}
                          <p className="text-[11px] text-gray-200 leading-relaxed">{q.question}</p>

                          {/* Why explanation */}
                          <p className="text-[10px] text-gray-500 mt-1 leading-snug">{q.why}</p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Empty state */}
              {data.surprises.length === 0 && data.questions.length === 0 && data.god_theories.length === 0 && (
                <div className="text-center py-3">
                  <p className="text-xs text-gray-500">No surprises detected.</p>
                  <p className="text-[10px] text-gray-600 mt-0.5">Your knowledge graph is well-connected.</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Client-side graph analysis (lightweight mirror of backend SurpriseEngine)
// ---------------------------------------------------------------------------

function analyzeGraphForSurprises(graphData: GraphData): SurpriseData {
  const theories = graphData.nodes.filter(n => n.label === 'Theory');
  if (theories.length < 3) {
    return { surprises: [], questions: [], god_theories: [], stats: { theories_analyzed: theories.length, insufficient: true } };
  }

  // Build adjacency
  const adj = new Map<string, Set<string>>();
  for (const n of theories) adj.set(n.id, new Set());
  for (const link of graphData.links) {
    const src = typeof link.source === 'object' ? (link.source as { id: string }).id : link.source;
    const tgt = typeof link.target === 'object' ? (link.target as { id: string }).id : link.target;
    if (adj.has(src) && adj.has(tgt)) {
      adj.get(src)!.add(tgt);
      adj.get(tgt)!.add(src);
    }
  }

  // God theories (highest degree)
  const degreeList = theories.map(t => ({
    theory: t,
    degree: adj.get(t.id)?.size ?? 0,
  })).sort((a, b) => b.degree - a.degree);

  const god_theories: GodTheory[] = degreeList.slice(0, 5)
    .filter(d => d.degree >= 2)
    .map(d => ({
      id: d.theory.id,
      content: truncate(String(d.theory.properties.content ?? d.theory.name ?? ''), 120),
      degree: d.degree,
      domains: extractDomains(d.theory),
    }));

  // Surprising connections: find pairs with high degree sum but different domains
  const surprises: SurprisingConnection[] = [];
  const seen = new Set<string>();

  for (const link of graphData.links) {
    const src = typeof link.source === 'object' ? (link.source as { id: string }).id : link.source;
    const tgt = typeof link.target === 'object' ? (link.target as { id: string }).id : link.target;
    const pairKey = [src, tgt].sort().join('::');
    if (seen.has(pairKey)) continue;
    seen.add(pairKey);

    const nodeA = theories.find(t => t.id === src);
    const nodeB = theories.find(t => t.id === tgt);
    if (!nodeA || !nodeB) continue;

    const domainsA = extractDomains(nodeA);
    const domainsB = extractDomains(nodeB);
    const projectA = String(nodeA.properties.scope_qualifier ?? '');
    const projectB = String(nodeB.properties.scope_qualifier ?? '');

    let score = 0;
    const reasons: string[] = [];

    // Cross-domain
    if (domainsA.length > 0 && domainsB.length > 0) {
      const shared = domainsA.filter(d => domainsB.includes(d));
      if (shared.length === 0) {
        score += 3;
        reasons.push(`crosses domains: ${domainsA[0]} \u2194 ${domainsB[0]}`);
      }
    }

    // Cross-project
    if (projectA && projectB && projectA !== projectB) {
      score += 2;
      reasons.push(`crosses projects: ${projectA} \u2194 ${projectB}`);
    }

    // Confidence disparity
    const confA = Number(nodeA.properties.confidence ?? 0.5);
    const confB = Number(nodeB.properties.confidence ?? 0.5);
    if (Math.abs(confA - confB) > 0.3) {
      score += 1;
      reasons.push(`confidence gap: ${confA.toFixed(2)} vs ${confB.toFixed(2)}`);
    }

    if (score >= 3) {
      const connType = projectA && projectB && projectA !== projectB
        ? 'cross_project'
        : domainsA.length > 0 && domainsB.length > 0
          ? 'cross_domain'
          : 'unexpected_similarity';

      surprises.push({
        theory_a: { id: nodeA.id, content: truncate(String(nodeA.properties.content ?? nodeA.name), 120) },
        theory_b: { id: nodeB.id, content: truncate(String(nodeB.properties.content ?? nodeB.name), 120) },
        score,
        reasons,
        connection_type: connType,
      });
    }
  }

  surprises.sort((a, b) => b.score - a.score);

  // Questions
  const questions: SuggestedQuestion[] = [];

  // Weak but connected theories
  for (const d of degreeList) {
    const conf = Number(d.theory.properties.confidence ?? 0.5);
    if (d.degree >= 3 && conf < 0.4) {
      questions.push({
        question: `Is '${truncate(String(d.theory.properties.content ?? d.theory.name), 60)}' correct? High connectivity but low confidence.`,
        type: 'weak_theory',
        why: 'High-impact if wrong.',
        related_theories: [d.theory.id],
      });
    }
  }

  // Isolated confirmed theories
  for (const d of degreeList) {
    const confirmations = Number(d.theory.properties.confirmation_count ?? 0);
    if (d.degree === 0 && confirmations > 0) {
      questions.push({
        question: `What connects '${truncate(String(d.theory.properties.content ?? d.theory.name), 60)}' to the rest?`,
        type: 'isolated',
        why: 'Confirmed but structurally disconnected.',
        related_theories: [d.theory.id],
      });
    }
  }

  return {
    surprises: surprises.slice(0, 10),
    questions: questions.slice(0, 7),
    god_theories,
    stats: {
      theories_analyzed: theories.length,
      edges_analyzed: graphData.links.length,
      domains_covered: new Set(theories.flatMap(t => extractDomains(t))).size,
    },
  };
}

function extractDomains(node: { properties: Record<string, unknown> }): string[] {
  const qualifier = String(node.properties.scope_qualifier ?? '');
  const domains: string[] = [];
  if (qualifier) domains.push(qualifier);
  return domains;
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '\u2026' : s;
}
