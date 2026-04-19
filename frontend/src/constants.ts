import type { NodeType, PrebuiltQuery } from './types';

export interface NodeStyle {
  color: string;
  size: number;
  borderColor: string;
}

export interface LinkStyle {
  color: string;
  width: number;
  dashed: boolean;
}

export const NODE_STYLES: Record<NodeType, NodeStyle> = {
  Session:          { color: '#3B82F6', size: 10, borderColor: '#60A5FA' },
  Episode:          { color: '#8B5CF6', size: 6,  borderColor: '#A78BFA' },
  Theory:           { color: '#F59E0B', size: 8,  borderColor: '#FBBF24' },
  Concept:          { color: '#10B981', size: 7,  borderColor: '#34D399' },
  StructuralPattern:{ color: '#EC4899', size: 5,  borderColor: '#F472B6' },
  FailureRecord:    { color: '#EF4444', size: 7,  borderColor: '#F87171' },
  Contradiction:    { color: '#F97316', size: 6,  borderColor: '#FB923C' },
  UserKnowledge:    { color: '#06B6D4', size: 6,  borderColor: '#22D3EE' },
};

export const LINK_STYLES: Record<string, LinkStyle> = {
  CONTAINS:       { color: 'rgba(255,255,255,0.3)', width: 1, dashed: false },
  EXTRACTED_FROM: { color: 'rgba(245,158,11,0.5)',  width: 1, dashed: true },
  RELATED_TO:     { color: 'rgba(156,163,175,0.4)', width: 1, dashed: false },
  PARENT_OF:      { color: 'rgba(245,158,11,0.6)',  width: 2, dashed: false },
  SUPERSEDED_BY:  { color: 'rgba(107,114,128,0.4)', width: 1, dashed: true },
  CAUSES:         { color: 'rgba(16,185,129,0.6)',   width: 2, dashed: false },
  EVIDENCES:      { color: 'rgba(16,185,129,0.3)',   width: 1, dashed: false },
  CONTRADICTS:    { color: 'rgba(239,68,68,0.7)',    width: 2, dashed: false },
  OBSERVED_IN:    { color: 'rgba(249,115,22,0.4)',   width: 1, dashed: false },
  FAILED_IN:      { color: 'rgba(239,68,68,0.5)',    width: 1, dashed: false },
  HAS_PATTERN:    { color: 'rgba(236,72,153,0.4)',   width: 1, dashed: true },
};

export const DEFAULT_LINK_STYLE: LinkStyle = {
  color: 'rgba(107,114,128,0.3)',
  width: 1,
  dashed: false,
};

export const PREBUILT_QUERIES: PrebuiltQuery[] = [
  {
    name: 'theory_network',
    description: 'All active theories and their relationships',
    cypher: `MATCH (t:Theory {active: true})
OPTIONAL MATCH (t)-[r:RELATED_TO|PARENT_OF|SUPERSEDED_BY]->(t2:Theory)
RETURN t, r, t2`,
  },
  {
    name: 'causal_chains',
    description: 'All cause-effect chains with strength',
    cypher: `MATCH (c1:Concept)-[r:CAUSES]->(c2:Concept)
RETURN c1, r, c2
ORDER BY r.strength DESC`,
  },
  {
    name: 'causal_chain_from',
    description: 'Trace downstream effects from a concept',
    cypher: `MATCH path = (c:Concept {text: $concept})-[:CAUSES*1..5]->(effect:Concept)
RETURN path`,
    parameters: { concept: 'Enter concept text' },
  },
  {
    name: 'high_confidence_theories',
    description: 'Theories with confidence > 0.7 and structural patterns',
    cypher: `MATCH (t:Theory) WHERE t.confidence > 0.7 AND t.active = true
OPTIONAL MATCH (t)-[r:HAS_PATTERN]->(p:StructuralPattern)
RETURN t, r, p`,
  },
  {
    name: 'theory_hierarchy',
    description: 'Parent-child tree structure of theories',
    cypher: `MATCH (parent:Theory)-[r:PARENT_OF]->(child:Theory)
WHERE parent.active = true
RETURN parent, r, child`,
  },
  {
    name: 'failure_hotspots',
    description: 'Failures linked to episodes and sessions',
    cypher: `MATCH (f:FailureRecord)-[r1:FAILED_IN]->(e:Episode)<-[r2:CONTAINS]-(s:Session)
RETURN f, r1, e, r2, s`,
  },
  {
    name: 'pattern_clusters',
    description: 'Structural patterns shared across entities',
    cypher: `MATCH (entity)-[r:HAS_PATTERN]->(p:StructuralPattern)
RETURN entity, r, p`,
  },
  {
    name: 'project_timeline',
    description: 'Sessions and their episodes per project',
    cypher: `MATCH (s:Session)-[r:CONTAINS]->(e:Episode)
RETURN s, r, e`,
  },
  {
    name: 'contradiction_analysis',
    description: 'Theories with contradictions',
    cypher: `MATCH (c:Contradiction)-[r1:CONTRADICTS]->(t:Theory)
OPTIONAL MATCH (c)-[r2:OBSERVED_IN]->(e:Episode)
RETURN c, r1, t, r2, e`,
  },
  {
    name: 'cross_project_patterns',
    description: 'Theories spanning multiple projects',
    cypher: `MATCH (t:Theory)-[r1:EXTRACTED_FROM]->(e:Episode)<-[r2:CONTAINS]-(s:Session)
RETURN t, r1, e, r2, s`,
  },
  {
    name: 'knowledge_graph_overview',
    description: 'Full graph overview — all connected nodes',
    cypher: `MATCH (n)-[r]->(m)
RETURN n, r, m
LIMIT 1000
UNION ALL
MATCH (orphan) WHERE NOT (orphan)--()
RETURN orphan AS n, null AS r, null AS m
LIMIT 100`,
  },
  {
    name: 'episode_to_theory_lineage',
    description: 'How episodes consolidated into theories',
    cypher: `MATCH (t:Theory)-[r:EXTRACTED_FROM]->(e:Episode)
RETURN t, r, e
LIMIT 200`,
  },
];

export const STORAGE_KEY = 'neurosync-neo4j-config';

export const DEFAULT_NEO4J_CONFIG = {
  uri: 'bolt://localhost:7687',
  user: 'neo4j',
  password: '',
  database: 'neo4j',
};
