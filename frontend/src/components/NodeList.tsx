import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';

import { getNode, listNodes } from '../api/endpoints';
import { useApiResource } from '../hooks/useApiResource';
import { GpuChips } from './GpuChips';
import { HealthBadge } from './HealthBadge';
import { LoadingOrError } from './LoadingOrError';

const NODE_PAGE_SIZE = 50;
const REFRESH_INTERVAL_MILLISECONDS = 15_000;

function ExpandedGpus({ nodeId }: { nodeId: string }) {
    const fetcher = useCallback((signal: AbortSignal) => getNode(nodeId, signal), [nodeId]);
    const { data, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);

    if (data === null) {
        return (
            <div className="mt-2">
                <LoadingOrError isLoading={isLoading} error={error} subject="GPUs" />
            </div>
        );
    }

    return (
        <div className="mt-2">
            <GpuChips nodeId={nodeId} gpus={data.gpus} />
        </div>
    );
}

export function NodeList() {
    const fetcher = useCallback(
        (signal: AbortSignal) => listNodes({ limit: NODE_PAGE_SIZE }, signal),
        [],
    );
    const { data, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);
    const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);

    if (data === null) {
        return <LoadingOrError isLoading={isLoading} error={error} subject="nodes" />;
    }

    return (
        <ul className="divide-y divide-border-subtle">
            {data.items.map((node) => (
                <li key={node.id} className="py-3">
                    <div className="flex flex-wrap items-center gap-3">
                        <Link to={`/nodes/${node.id}`} className="font-medium hover:underline">
                            {node.id}
                        </Link>
                        <HealthBadge state={node.health_state} />
                        <span className="text-sm text-text-muted">
                            {node.cpu_cores} cores · {node.memory_gb} GB · {node.gpu_count} GPUs
                        </span>
                        <button
                            type="button"
                            aria-expanded={expandedNodeId === node.id}
                            aria-label={`Toggle GPUs for ${node.id}`}
                            onClick={() => {
                                setExpandedNodeId(expandedNodeId === node.id ? null : node.id);
                            }}
                            className="ml-auto rounded border border-border-subtle px-2 py-1 text-xs font-medium hover:bg-surface-muted"
                        >
                            {expandedNodeId === node.id ? 'Hide GPUs' : 'Show GPUs'}
                        </button>
                    </div>
                    {expandedNodeId === node.id && <ExpandedGpus nodeId={node.id} />}
                </li>
            ))}
        </ul>
    );
}
