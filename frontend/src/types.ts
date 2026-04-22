export type NodeType =
  | 'Session'
  | 'Episode'
  | 'Theory'
  | 'Concept'
  | 'StructuralPattern'
  | 'FailureRecord'
  | 'Contradiction'
  | 'UserKnowledge';

export type RelType =
  | 'CONTAINS'
  | 'EXTRACTED_FROM'
  | 'RELATED_TO'
  | 'PARENT_OF'
  | 'SUPERSEDED_BY'
  | 'CAUSES'
  | 'EVIDENCES'
  | 'CONTRADICTS'
  | 'OBSERVED_IN'
  | 'FAILED_IN'
  | 'HAS_PATTERN';

export interface GraphNode {
  id: string;
  label: NodeType;
  name: string;
  properties: Record<string, unknown>;
  cluster?: number;
  // force-graph internal fields
  x?: number;
  y?: number;
  z?: number;
  vx?: number;
  vy?: number;
  vz?: number;
}

export interface GraphLink {
  source: string;
  target: string;
  type: RelType | string;
  properties: Record<string, unknown>;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface Neo4jConfig {
  uri: string;
  user: string;
  password: string;
  database: string;
}

export interface PrebuiltQuery {
  name: string;
  description: string;
  cypher: string;
  parameters?: Record<string, string>;
}

export interface NodeStats {
  nodes: Record<string, number>;
  relationships: Record<string, number>;
}
