import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';

import { getNode, listNodes } from '../api/endpoints';
import { formatEntityId } from '../domain/format';
import { useApiResource } from '../hooks/useApiResource';
import { GpuGrid } from './GpuGrid';
import { HealthBadge } from './HealthBadge';
import { LoadingOrError } from './LoadingOrError';

const NODE_PAGE_SIZE = 50;
const REFRESH_INTERVAL_MILLISECONDS = 15_000;

function ExpandedGpus({ nodeId }: { nodeId: string }) {
    const fetcher = useCallback((signal: AbortSignal) => getNode(nodeId, signal), [nodeId]);
    const { data, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);

    if (data === null) {
        return (
            <div className="pb-3">
                <LoadingOrError isLoading={isLoading} error={error} subject="GPUs" />
            </div>
        );
    }

    return (
        <div className="pb-3">
            <GpuGrid nodeId={nodeId} gpus={data.gpus} />
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
        <ul className="divide-y divide-border-subtle border-b border-border-subtle">
            {data.items.map((node) => (
                <li key={node.id}>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3.5">
                        <Link to={`/nodes/${node.id}`} className="entity-link">
                            {formatEntityId(node.id)}
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
                            className="eyebrow ml-auto text-text-muted hover:text-accent"
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
