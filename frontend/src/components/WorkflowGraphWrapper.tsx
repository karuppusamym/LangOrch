"use client";

import { useEffect, useState } from "react";
import WorkflowGraph from "./WorkflowGraph";

import type { NodeStatus } from "./WorkflowGraph";

/**
 * Wrapper that only mounts WorkflowGraph on the client side.
 * This avoids both SSR issues with @xyflow/react (which needs DOM APIs)
 * and Next.js webpack chunking issues with React.lazy / next/dynamic.
 */
export default function WorkflowGraphWrapper({
  graph,
  nodeStates,
}: {
  graph: { nodes: any[]; edges: any[] };
  nodeStates?: Record<string, NodeStatus>;
}) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return <p className="text-sm text-gray-400">Loading graph...</p>;
  }

  return <WorkflowGraph graph={graph} nodeStates={nodeStates} />;
}
