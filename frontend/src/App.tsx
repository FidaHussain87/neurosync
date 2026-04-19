import { useState, useCallback, useEffect } from 'react';
import type { GraphNode } from './types';
import { useNeo4jConnection } from './hooks/useNeo4jConnection';
import { useGraphData } from './hooks/useGraphData';
import Sidebar from './components/Sidebar';
import GraphCanvas from './components/GraphCanvas';
import DetailPanel from './components/DetailPanel';

export default function App() {
  const connection = useNeo4jConnection();
  const graph = useGraphData();
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  // Auto-load overview on first connect
  const [initialLoaded, setInitialLoaded] = useState(false);
  useEffect(() => {
    if (connection.connected && !initialLoaded) {
      graph.loadOverview();
      setInitialLoaded(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection.connected]);

  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      setSelectedNode(node);
      graph.expandNode(node.id, node.label);
    },
    [graph.expandNode],
  );

  const handleDetailNodeClick = useCallback(
    (nodeId: string, label: string) => {
      const node = graph.filteredData.nodes.find(n => n.id === nodeId);
      if (node) {
        setSelectedNode(node);
        graph.expandNode(nodeId, label);
      }
    },
    [graph.filteredData.nodes, graph.expandNode],
  );

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 relative">
      <Sidebar
        config={connection.config}
        connected={connection.connected}
        connecting={connection.connecting}
        connectionError={connection.error}
        onConnect={connection.connect}
        onDisconnect={connection.disconnect}
        visibleTypes={graph.visibleTypes}
        onToggleType={graph.toggleType}
        searchQuery={graph.searchQuery}
        onSearchChange={graph.setSearchQuery}
        onRunPrebuilt={graph.runPrebuilt}
        onRunCustom={graph.runCustomQuery}
        onLoadOverview={graph.loadOverview}
        nodeCount={graph.filteredData.nodes.length}
        linkCount={graph.filteredData.links.length}
      />

      <GraphCanvas
        graphData={graph.filteredData}
        selectedNode={selectedNode}
        onNodeClick={handleNodeClick}
        onBackgroundClick={handleBackgroundClick}
        onClusterDrillIn={() => setSelectedNode(null)}
        viewResetCount={graph.viewResetCount}
      />

      {selectedNode && (
        <div className="absolute top-0 right-0 h-full z-20">
          <DetailPanel
            node={selectedNode}
            links={graph.filteredData.links}
            allNodes={graph.filteredData.nodes}
            onNodeClick={handleDetailNodeClick}
            onClose={() => setSelectedNode(null)}
          />
        </div>
      )}

      {/* Loading overlay */}
      {graph.loading && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-300 shadow-lg z-10">
          Loading\u2026
        </div>
      )}

      {/* Error toast */}
      {graph.error && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-red-900/80 border border-red-700 rounded-lg px-4 py-2 text-sm text-red-200 shadow-lg z-10">
          {graph.error}
        </div>
      )}
    </div>
  );
}
