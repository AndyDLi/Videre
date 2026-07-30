import { useCallback } from 'react';
import { Link } from 'react-router-dom';

import { getCapacity, listNodes } from '../api/endpoints';
import type { CapacitySummary, NodeSummary } from '../api/types';
import { Card } from '../components/Card';
import { HealthBadge } from '../components/HealthBadge';
import { LoadingOrError } from '../components/LoadingOrError';
import { useApiResource } from '../hooks/useApiResource';

const NODE_PAGE_SIZE = 50;
const REFRESH_INTERVAL_MILLISECONDS = 20_000;

interface Bottleneck {
    label: string;
    count: number;
    description: string;
}

function bottlenecksByImpact(summary: CapacitySummary): Bottleneck[] {
    const bottlenecks: Bottleneck[] = [
        {
            label: 'Unavailable GPUs',
            count: summary.unavailable_gpus,
            description: 'GPUs sitting on nodes that are not READY.',
        },
        {
            label: 'Idle but Reserved GPUs',
            count: summary.idle_reserved_gpus,
            description: 'Healthy, near-zero-utilization GPUs on nodes running no job.',
        },
        {
            label: 'Fragmentation Events',
            count: summary.fragmentation_event_count,
            description: 'Queueing delays where free capacity could not be packed together.',
        },
        {
            label: 'Queued Jobs',
            count: summary.queued_job_count,
            description: 'Jobs still PENDING, waiting on a placement.',
        },
        {
            label: 'Drained Nodes',
            count: summary.drained_node_count,
            description: 'Nodes DRAINING for maintenance.',
        },
        {
            label: 'Unschedulable Nodes',
            count: summary.unschedulable_node_count,
            description: 'Nodes CORDONED out of the schedulable pool.',
        },
    ];
    return bottlenecks.sort((first, second) => second.count - first.count);
}

function AffectedNodes({ nodes }: { nodes: NodeSummary[] }) {
    if (nodes.length === 0) {
        return <p className="text-sm text-text-muted">Every node is READY.</p>;
    }

    return (
        <ul className="divide-y divide-border-subtle">
            {nodes.map((node) => (
                <li key={node.id} className="flex flex-wrap items-center gap-3 py-2">
                    <Link to={`/nodes/${node.id}`} className="font-medium hover:underline">
                        {node.id}
                    </Link>
                    <HealthBadge state={node.health_state} />
                    <span className="text-sm text-text-muted">{node.gpu_count} GPUs affected</span>
                </li>
            ))}
        </ul>
    );
}

export function CapacityPage() {
    const capacityFetcher = useCallback((signal: AbortSignal) => getCapacity(signal), []);
    const {
        data: summaries,
        error,
        isLoading,
    } = useApiResource(capacityFetcher, REFRESH_INTERVAL_MILLISECONDS);

    const nodesFetcher = useCallback(
        (signal: AbortSignal) => listNodes({ limit: NODE_PAGE_SIZE }, signal),
        [],
    );
    const { data: nodes } = useApiResource(nodesFetcher, REFRESH_INTERVAL_MILLISECONDS);

    if (summaries === null) {
        return (
            <section className="space-y-4">
                <h1 className="text-xl font-semibold">Capacity Bottlenecks</h1>
                <LoadingOrError isLoading={isLoading} error={error} subject="capacity" />
            </section>
        );
    }

    return (
        <section className="space-y-4">
            <div>
                <h1 className="text-xl font-semibold">Capacity Bottlenecks</h1>
                <p className="mt-1 text-sm text-text-muted">
                    Ranked by how much capacity each one is costing, highest first.
                </p>
            </div>

            {summaries.map((summary) => (
                <div key={summary.cluster_id} className="space-y-4">
                    <div>
                        <h2 className="text-lg font-semibold">{summary.cluster_id}</h2>
                        <p className="mt-1 text-sm text-text-muted">
                            {summary.total_gpus} GPUs total
                        </p>
                    </div>

                    <Card>
                        <ul className="divide-y divide-border-subtle">
                            {bottlenecksByImpact(summary).map((bottleneck) => (
                                <li
                                    key={bottleneck.label}
                                    className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-3"
                                >
                                    <span className="text-2xl font-semibold tabular-nums">
                                        {bottleneck.count}
                                    </span>
                                    <span className="font-medium">{bottleneck.label}</span>
                                    <span className="text-sm text-text-muted">
                                        {bottleneck.description}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </Card>

                    <Card title="Nodes Reducing Capacity" headingLevel={3}>
                        <AffectedNodes
                            nodes={(nodes?.items ?? []).filter(
                                (node) =>
                                    node.cluster_id === summary.cluster_id &&
                                    node.health_state !== 'READY',
                            )}
                        />
                    </Card>
                </div>
            ))}
        </section>
    );
}
