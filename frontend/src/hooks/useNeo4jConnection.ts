import { useState, useEffect, useCallback } from 'react';
import type { Neo4jConfig } from '../types';
import { STORAGE_KEY, DEFAULT_NEO4J_CONFIG } from '../constants';
import * as neo4jService from '../services/neo4j';

function loadConfig(): Neo4jConfig {
  try {
    // Non-sensitive fields from localStorage, password from sessionStorage
    const stored = localStorage.getItem(STORAGE_KEY);
    const base = stored ? JSON.parse(stored) : { ...DEFAULT_NEO4J_CONFIG };
    const password = sessionStorage.getItem(STORAGE_KEY + '-pw') ?? '';
    return { ...base, password };
  } catch {
    // ignore
  }
  return { ...DEFAULT_NEO4J_CONFIG };
}

function saveConfig(config: Neo4jConfig) {
  // Persist connection details without password in localStorage
  const { password, ...rest } = config;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...rest, password: '' }));
  // Password only in sessionStorage (cleared when tab closes)
  sessionStorage.setItem(STORAGE_KEY + '-pw', password);
}

export function useNeo4jConnection() {
  const [config, setConfig] = useState<Neo4jConfig>(loadConfig);
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connectToNeo4j = useCallback(async (cfg?: Neo4jConfig) => {
    const c = cfg ?? config;
    setConnecting(true);
    setError(null);
    try {
      await neo4jService.connect(c);
      setConnected(true);
      saveConfig(c);
      if (cfg) setConfig(c);
    } catch (err) {
      setConnected(false);
      setError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setConnecting(false);
    }
  }, [config]);

  const disconnectFromNeo4j = useCallback(async () => {
    await neo4jService.disconnect();
    setConnected(false);
    setError(null);
  }, []);

  // Auto-connect on mount if credentials exist
  useEffect(() => {
    if (config.password) {
      connectToNeo4j();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    config,
    setConfig,
    connected,
    connecting,
    error,
    connect: connectToNeo4j,
    disconnect: disconnectFromNeo4j,
  };
}
