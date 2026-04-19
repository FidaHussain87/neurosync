import { useState, useCallback, useRef, useMemo } from 'react';
import Graph from 'graphology';
import louvain from 'graphology-communities-louvain';
import type { GraphData, GraphNode, NodeType } from '../types';
import * as neo4jService from '../services/neo4j';

// Map node types to cluster IDs for fallback grouping
const TYPE_CLUSTER: Record<string, number> = {
  Session: 0, Episode: 1, Theory: 2, Concept: 3,
  StructuralPattern: 4, FailureRecord: 5, Contradiction: 6, UserKnowledge: 7,
};

function assignClusters(data: GraphData): GraphData {
  if (data.nodes.length === 0) return data;

  const g = new Graph({ type: 'undirected', allowSelfLoops: false });
  for (const n of data.nodes) {
    if (!g.hasNode(n.id)) g.addNode(n.id);
  }
  for (const l of data.links) {
    const src = typeof l.source === 'object' ? (l.source as GraphNode).id : l.source;
    const tgt = typeof l.target === 'object' ? (l.target as GraphNode).id : l.target;
    if (g.hasNode(src) && g.hasNode(tgt) && !g.hasEdge(src, tgt)) {
      g.addEdge(src, tgt);
    }
  }

  let communities: Record<string, number> = {};
  try {
    communities = louvain(g, { resolution: 1.5 });
  } catch {
    // Louvain can fail on disconnected or trivial graphs
  }

  // Check if Louvain produced meaningful clusters (more than 1)
  const uniqueCommunities = new Set(Object.values(communities));
  const useLouvain = uniqueCommunities.size > 1;

  return {
    ...data,
    nodes: data.nodes.map(n => ({
      ...n,
      cluster: useLouvain
        ? (communities[n.id] ?? 0)
        : (TYPE_CLUSTER[n.label] ?? 0),
    })),
    links: data.links,
  };
}

function mergeGraphData(existing: GraphData, incoming: GraphData): GraphData {
  const nodeMap = new Map<string, GraphNode>();
  for (const n of existing.nodes) nodeMap.set(n.id, n);
  // Incoming nodes: preserve existing positions if the node already exists
  for (const n of incoming.nodes) {
    const prev = nodeMap.get(n.id);
    if (prev) {
      // Keep existing force-sim positions, update properties
      nodeMap.set(n.id, { ...n, x: prev.x, y: prev.y, vx: prev.vx, vy: prev.vy, cluster: prev.cluster });
    } else {
      nodeMap.set(n.id, n);
    }
  }

  const linkSet = new Map<string, typeof incoming.links[0]>();
  for (const l of existing.links) {
    const src = typeof l.source === 'object' ? (l.source as GraphNode).id : l.source;
    const tgt = typeof l.target === 'object' ? (l.target as GraphNode).id : l.target;
    linkSet.set(`${src}-${l.type}-${tgt}`, { ...l, source: src, target: tgt });
  }
  for (const l of incoming.links) {
    const src = typeof l.source === 'object' ? (l.source as GraphNode).id : l.source;
    const tgt = typeof l.target === 'object' ? (l.target as GraphNode).id : l.target;
    linkSet.set(`${src}-${l.type}-${tgt}`, { ...l, source: src, target: tgt });
  }

  const nodes = Array.from(nodeMap.values());
  const nodeIds = new Set(nodes.map(n => n.id));
  const links = Array.from(linkSet.values()).filter(
    l => nodeIds.has(l.source as string) && nodeIds.has(l.target as string),
  );

  return { nodes, links };
}

export function useGraphData() {
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [visibleTypes, setVisibleTypes] = useState<Set<NodeType>>(
    new Set(['Session', 'Episode', 'Theory', 'Concept', 'StructuralPattern', 'FailureRecord', 'Contradiction', 'UserKnowledge']),
  );
  const [searchQuery, setSearchQuery] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const fullDataRef = useRef<GraphData>({ nodes: [], links: [] });
  // Counter that increments on full data replacement (overview, prebuilt, custom) — NOT on expand
  const [viewResetCount, setViewResetCount] = useState(0);

  const updateData = useCallback((data: GraphData, fullReplace: boolean) => {
    const clustered = assignClusters(data);
    fullDataRef.current = clustered;
    setGraphData(clustered);
    if (fullReplace) setViewResetCount(c => c + 1);
  }, []);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await neo4jService.fetchOverview();
      updateData(data, true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load overview');
    } finally {
      setLoading(false);
    }
  }, [updateData]);

  const expandNode = useCallback(async (nodeId: string, label: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await neo4jService.expandNode(nodeId, label);
      const merged = mergeGraphData(fullDataRef.current, data);
      updateData(merged, false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to expand node');
    } finally {
      setLoading(false);
    }
  }, [updateData]);

  const runPrebuilt = useCallback(async (cypher: string, params?: Record<string, unknown>) => {
    setLoading(true);
    setError(null);
    try {
      const data = await neo4jService.fetchPrebuilt(cypher, params);
      if (data.nodes.length === 0) {
        setError('Query returned no results');
      } else {
        updateData(data, true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Query failed');
    } finally {
      setLoading(false);
    }
  }, [updateData]);

  const runCustomQuery = useCallback(async (cypher: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await neo4jService.runQuery(cypher);
      if (data.nodes.length === 0) {
        setError('Query returned no results');
      } else {
        updateData(data, true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Query failed');
    } finally {
      setLoading(false);
    }
  }, [updateData]);

  // Extract unique project names from Session nodes
  const projects = useMemo((): string[] => {
    const projectSet = new Set<string>();
    for (const n of graphData.nodes) {
      const p = (n.properties.project as string) ?? '';
      if (p) projectSet.add(p);
    }
    return Array.from(projectSet).sort();
  }, [graphData.nodes]);

  const filteredData = useMemo((): GraphData => {
    let nodes = graphData.nodes;

    // Filter by visible types
    nodes = nodes.filter(n => visibleTypes.has(n.label));

    // Filter by project (Session nodes carry project; other nodes included if linked)
    if (projectFilter) {
      const projectSessionIds = new Set(
        graphData.nodes
          .filter(n => n.label === 'Session' && n.properties.project === projectFilter)
          .map(n => n.id),
      );
      // Keep nodes that are: in the project, or linked to a session in the project
      const linkedIds = new Set<string>();
      for (const l of graphData.links) {
        const src = typeof l.source === 'object' ? (l.source as GraphNode).id : l.source;
        const tgt = typeof l.target === 'object' ? (l.target as GraphNode).id : l.target;
        if (projectSessionIds.has(src)) linkedIds.add(tgt);
        if (projectSessionIds.has(tgt)) linkedIds.add(src);
      }
      nodes = nodes.filter(n =>
        projectSessionIds.has(n.id) ||
        linkedIds.has(n.id) ||
        (n.properties.project as string) === projectFilter ||
        (n.properties.scope_qualifier as string) === projectFilter,
      );
    }

    // Filter by search query
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      nodes = nodes.filter(n => n.name.toLowerCase().includes(q));
    }

    const nodeIds = new Set(nodes.map(n => n.id));
    const links = graphData.links.filter(l => {
      const src = typeof l.source === 'object' ? (l.source as GraphNode).id : l.source;
      const tgt = typeof l.target === 'object' ? (l.target as GraphNode).id : l.target;
      return nodeIds.has(src) && nodeIds.has(tgt);
    });

    return { nodes, links };
  }, [graphData, visibleTypes, searchQuery, projectFilter]);

  const toggleType = useCallback((type: NodeType) => {
    setVisibleTypes(prev => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }, []);

  return {
    graphData,
    filteredData,
    loading,
    error,
    visibleTypes,
    searchQuery,
    setSearchQuery,
    projects,
    projectFilter,
    setProjectFilter,
    toggleType,
    loadOverview,
    expandNode,
    runPrebuilt,
    runCustomQuery,
    viewResetCount,
  };
}
