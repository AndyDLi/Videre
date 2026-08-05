import { useCallback } from 'react';
import { Link } from 'react-router-dom';

import { getCapacity, listNodes } from '../api/endpoints';
import type { NodeSummary } from '../api/types';
import { HealthBadge } from '../components/HealthBadge';
import { LoadingOrError } from '../components/LoadingOrError';
import { PageHeading } from '../components/PageHeading';
import { Section } from '../components/Section';
import { bottlenecksByImpact } from '../domain/capacityBottlenecks';
import { formatEntityId } from '../domain/format';
import { useApiResource } from '../hooks/useApiResource';

const NODE_PAGE_SIZE = 50;
const REFRESH_INTERVAL_MILLISECONDS = 20_000;

function AffectedNodes({ nodes }: { nodes: NodeSummary[] }) {
    if (nodes.length === 0) {
        return <p className="text-sm text-text-muted">Every node is READY.</p>;
    }

    return (
        <ul className="divide-y divide-border-subtle border-b border-border-subtle">
            {nodes.map((node) => (
                <li key={node.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
                    <Link to={`/nodes/${node.id}`} className="entity-link">
                        {formatEntityId(node.id)}
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
            <section>
                <PageHeading eyebrow="Where Capacity Goes" title="Capacity Bottlenecks" />
                <div className="mt-6">
                    <LoadingOrError isLoading={isLoading} error={error} subject="capacity" />
                </div>
            </section>
        );
    }

    return (
        <section>
            <PageHeading
                eyebrow="Where Capacity Goes"
                title="Capacity Bottlenecks"
                description="Ranked by how much capacity each one is costing."
            />

            {summaries.map((summary) => (
                <div key={summary.cluster_id} className="mt-12">
                    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
                        <h2 className="display-title text-3xl">
                            {formatEntityId(summary.cluster_id)}
                        </h2>
                        <p className="text-sm text-text-muted">{summary.total_gpus} GPUs total</p>
                    </div>

                    <div className="mt-8">
                        <Section>
                            <ul className="divide-y divide-border-subtle border-b border-border-subtle">
                                {bottlenecksByImpact(summary).map((bottleneck) => (
                                    <li
                                        key={bottleneck.label}
                                        className="flex flex-wrap items-baseline gap-x-5 gap-y-1 py-5"
                                    >
                                        <span className="metric w-16 shrink-0 text-4xl">
                                            {bottleneck.count}
                                        </span>
                                        <span className="font-display text-lg text-text-primary">
                                            {bottleneck.label}
                                        </span>
                                        <span className="text-sm text-text-muted">
                                            {bottleneck.description}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        </Section>
                    </div>

                    <div className="mt-12">
                        <Section title="Nodes Reducing Capacity" headingLevel={3}>
                            <AffectedNodes
                                nodes={(nodes?.items ?? []).filter(
                                    (node) =>
                                        node.cluster_id === summary.cluster_id &&
                                        node.health_state !== 'READY',
                                )}
                            />
                        </Section>
                    </div>
                </div>
            ))}
        </section>
    );
}
