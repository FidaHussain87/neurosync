import neo4j, { Driver, Record as Neo4jRecord, Node, Relationship, Integer, Path } from 'neo4j-driver';
import type { Neo4jConfig, GraphData, GraphNode, GraphLink, NodeType, NodeStats } from '../types';

let driver: Driver | null = null;
let currentConfig: Neo4jConfig | null = null;

export async function connect(config: Neo4jConfig): Promise<void> {
  if (driver) {
    await driver.close();
  }
  driver = neo4j.driver(config.uri, neo4j.auth.basic(config.user, config.password));
  await driver.verifyConnectivity();
  currentConfig = config;
}

export async function disconnect(): Promise<void> {
  if (driver) {
    await driver.close();
    driver = null;
    currentConfig = null;
  }
}

export function isConnected(): boolean {
  return driver !== null;
}

function toNumber(value: unknown): number {
  if (value instanceof Integer || (value && typeof value === 'object' && 'low' in value)) {
    return (value as Integer).toNumber();
  }
  if (typeof value === 'number') return value;
  if (typeof value === 'string') return parseFloat(value) || 0;
  return 0;
}

function cleanProperties(props: Record<string, unknown>): Record<string, unknown> {
  const cleaned: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    if (value instanceof Integer || (value && typeof value === 'object' && 'low' in value && 'high' in value)) {
      cleaned[key] = toNumber(value);
    } else if (Array.isArray(value)) {
      cleaned[key] = value.map(v =>
        v instanceof Integer || (v && typeof v === 'object' && 'low' in v) ? toNumber(v) : v,
      );
    } else {
      cleaned[key] = value;
    }
  }
  return cleaned;
}

function extractDisplayName(node: Node): string {
  const label = node.labels[0] as NodeType;
  const props = node.properties;
  switch (label) {
    case 'Theory':
      return truncate(String(props.content ?? props.id ?? ''), 80);
    case 'Episode':
      return truncate(String(props.content ?? props.id ?? ''), 60);
    case 'Session':
      return `${props.project ?? ''}${props.branch ? ' / ' + props.branch : ''}`;
    case 'Concept':
      return String(props.text ?? '');
    case 'FailureRecord':
      return truncate(String(props.what_failed ?? props.id ?? ''), 60);
    case 'Contradiction':
      return truncate(String(props.description ?? props.id ?? ''), 60);
    case 'UserKnowledge':
      return String(props.topic ?? props.id ?? '');
    case 'StructuralPattern':
      return String(props.name ?? '');
    default:
      return String(props.id ?? props.name ?? node.elementId);
  }
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '\u2026' : s;
}

function nodeId(node: Node): string {
  return String(node.properties.id ?? node.properties.text ?? node.properties.name ?? node.elementId);
}

function extractFromRecords(records: Neo4jRecord[]): GraphData {
  const nodeMap = new Map<string, GraphNode>();
  const linkSet = new Map<string, GraphLink>();

  function addNode(node: Node) {
    const id = nodeId(node);
    if (!nodeMap.has(id)) {
      nodeMap.set(id, {
        id,
        label: (node.labels[0] ?? 'Unknown') as NodeType,
        name: extractDisplayName(node),
        properties: cleanProperties(node.properties),
      });
    }
  }

  function addRelationship(rel: Relationship, startNode?: Node, endNode?: Node) {
    const srcId = startNode ? nodeId(startNode) : rel.startNodeElementId;
    const tgtId = endNode ? nodeId(endNode) : rel.endNodeElementId;
    const linkId = `${srcId}-${rel.type}-${tgtId}`;
    if (!linkSet.has(linkId)) {
      linkSet.set(linkId, {
        source: srcId,
        target: tgtId,
        type: rel.type,
        properties: cleanProperties(rel.properties),
      });
    }
  }

  // Map elementId to our stable node id for relationship resolution
  const elementIdMap = new Map<string, string>();

  for (const record of records) {
    for (const field of record.keys) {
      const value = record.get(field);
      if (value === null || value === undefined) continue;

      if (isNode(value)) {
        addNode(value);
        elementIdMap.set(value.elementId, nodeId(value));
      } else if (isRelationship(value)) {
        // Will resolve source/target after all nodes are processed
      } else if (isPath(value)) {
        for (const seg of value.segments) {
          addNode(seg.start);
          addNode(seg.end);
          elementIdMap.set(seg.start.elementId, nodeId(seg.start));
          elementIdMap.set(seg.end.elementId, nodeId(seg.end));
          addRelationship(seg.relationship, seg.start, seg.end);
        }
      } else if (Array.isArray(value)) {
        for (const item of value) {
          if (isNode(item)) {
            addNode(item);
            elementIdMap.set(item.elementId, nodeId(item));
          } else if (isRelationship(item)) {
            // Defer
          } else if (isPath(item)) {
            for (const seg of item.segments) {
              addNode(seg.start);
              addNode(seg.end);
              elementIdMap.set(seg.start.elementId, nodeId(seg.start));
              elementIdMap.set(seg.end.elementId, nodeId(seg.end));
              addRelationship(seg.relationship, seg.start, seg.end);
            }
          }
        }
      }
    }
  }

  // Second pass: pick up relationships that weren't part of paths
  for (const record of records) {
    for (const field of record.keys) {
      const value = record.get(field);
      if (value === null || value === undefined) continue;

      if (isRelationship(value)) {
        const srcId = elementIdMap.get(value.startNodeElementId);
        const tgtId = elementIdMap.get(value.endNodeElementId);
        if (srcId && tgtId) {
          const linkId = `${srcId}-${value.type}-${tgtId}`;
          if (!linkSet.has(linkId)) {
            linkSet.set(linkId, {
              source: srcId,
              target: tgtId,
              type: value.type,
              properties: cleanProperties(value.properties),
            });
          }
        }
      } else if (Array.isArray(value)) {
        for (const item of value) {
          if (isRelationship(item)) {
            const srcId = elementIdMap.get(item.startNodeElementId);
            const tgtId = elementIdMap.get(item.endNodeElementId);
            if (srcId && tgtId) {
              const linkId = `${srcId}-${item.type}-${tgtId}`;
              if (!linkSet.has(linkId)) {
                linkSet.set(linkId, {
                  source: srcId,
                  target: tgtId,
                  type: item.type,
                  properties: cleanProperties(item.properties),
                });
              }
            }
          }
        }
      }
    }
  }

  const nodes = Array.from(nodeMap.values());
  const nodeIds = new Set(nodes.map(n => n.id));
  // Only keep links where both endpoints exist
  const links = Array.from(linkSet.values()).filter(
    l => nodeIds.has(l.source) && nodeIds.has(l.target),
  );

  return { nodes, links };
}

function isNode(value: unknown): value is Node {
  if (value === null || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return Array.isArray(v.labels) && v.properties !== undefined && typeof v.elementId === 'string';
}

function isRelationship(value: unknown): value is Relationship {
  if (value === null || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return typeof v.type === 'string' && typeof v.startNodeElementId === 'string' && typeof v.endNodeElementId === 'string';
}

function isPath(value: unknown): value is Path {
  if (value === null || typeof value !== 'object') return false;
  return 'segments' in value && Array.isArray((value as { segments: unknown }).segments);
}

export async function runQuery(cypher: string, params?: Record<string, unknown>): Promise<GraphData> {
  if (!driver) throw new Error('Not connected to Neo4j');
  const session = driver.session({ database: currentConfig?.database ?? 'neo4j' });
  try {
    const result = await session.run(cypher, params ?? {});
    return extractFromRecords(result.records);
  } finally {
    await session.close();
  }
}

export async function fetchOverview(): Promise<GraphData> {
  // Use UNION to avoid Cartesian product between Sessions and Theories
  const [sessionData, theoryData] = await Promise.all([
    runQuery(`
      MATCH (s:Session)
      OPTIONAL MATCH (s)-[r:CONTAINS]->(e:Episode)
      RETURN s, r, e
      LIMIT 300
    `),
    runQuery(`
      MATCH (t:Theory {active: true})
      OPTIONAL MATCH (t)-[r1:EXTRACTED_FROM]->(e:Episode)
      OPTIONAL MATCH (t)-[r2:RELATED_TO|PARENT_OF|SUPERSEDED_BY]->(t2:Theory)
      RETURN t, r1, e, r2, t2
      LIMIT 300
    `),
  ]);

  // Merge the two result sets
  const nodeMap = new Map<string, GraphNode>();
  const linkMap = new Map<string, GraphLink>();

  for (const data of [sessionData, theoryData]) {
    for (const n of data.nodes) nodeMap.set(n.id, n);
    for (const l of data.links) {
      linkMap.set(`${l.source}-${l.type}-${l.target}`, l);
    }
  }

  const nodes = Array.from(nodeMap.values());
  const nodeIds = new Set(nodes.map(n => n.id));
  const links = Array.from(linkMap.values()).filter(
    l => nodeIds.has(l.source) && nodeIds.has(l.target),
  );

  return { nodes, links };
}

export async function expandNode(nodeId: string, nodeLabel: string): Promise<GraphData> {
  // Use the appropriate property for matching based on label
  let matchClause: string;
  if (nodeLabel === 'Concept') {
    matchClause = `MATCH (n:Concept {text: $id})`;
  } else if (nodeLabel === 'StructuralPattern') {
    matchClause = `MATCH (n:StructuralPattern {name: $id})`;
  } else {
    matchClause = `MATCH (n {id: $id})`;
  }

  return runQuery(
    `${matchClause}
     OPTIONAL MATCH (n)-[r]-(connected)
     RETURN n, r, connected`,
    { id: nodeId },
  );
}

export async function fetchPrebuilt(cypher: string, params?: Record<string, unknown>): Promise<GraphData> {
  return runQuery(cypher, params);
}

export async function getStats(): Promise<NodeStats> {
  if (!driver) throw new Error('Not connected to Neo4j');
  const session = driver.session({ database: currentConfig?.database ?? 'neo4j' });
  try {
    const nodeResult = await session.run(
      `CALL { MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt }
       RETURN label, cnt ORDER BY cnt DESC`,
    );
    const relResult = await session.run(
      `CALL { MATCH ()-[r]->() RETURN type(r) AS rtype, count(r) AS cnt }
       RETURN rtype, cnt ORDER BY cnt DESC`,
    );

    const nodes: Record<string, number> = {};
    for (const r of nodeResult.records) {
      const label = r.get('label');
      if (label) nodes[label] = toNumber(r.get('cnt'));
    }
    const relationships: Record<string, number> = {};
    for (const r of relResult.records) {
      const rtype = r.get('rtype');
      if (rtype) relationships[rtype] = toNumber(r.get('cnt'));
    }
    return { nodes, relationships };
  } finally {
    await session.close();
  }
}
