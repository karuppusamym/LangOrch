"use client";

import { useEffect, useState } from "react";
import WorkflowBuilder from "./WorkflowBuilder";

/**
 * Wrapper that only mounts WorkflowBuilder on the client side.
 * @xyflow/react requires DOM APIs unavailable during SSR.
 */
export default function WorkflowBuilderWrapper({
  initialWorkflowGraph,
  onSave,
  saving,
}: {
  initialWorkflowGraph: Record<string, unknown> | null;
  onSave: (workflowGraph: Record<string, unknown>) => void;
  saving?: boolean;
}) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div className="flex h-[740px] w-full items-center justify-center rounded-xl border border-gray-200 bg-gray-50">
        <p className="text-sm text-gray-400">Loading workflow builder…</p>
      </div>
    );
  }

  return (
    <WorkflowBuilder
      initialWorkflowGraph={initialWorkflowGraph}
      onSave={onSave}
      saving={saving}
    />
  );
}
