import { useCallback } from 'react';

import { getCapacity } from '../api/endpoints';
import { JobList } from '../components/JobList';
import { NodeList } from '../components/NodeList';
import { PageHeading } from '../components/PageHeading';
import { Section } from '../components/Section';
import { StateCounts } from '../components/StateCounts';
import { UtilizationPanel } from '../components/UtilizationPanel';
import { formatEntityId } from '../domain/format';
import { deriveGpuUtilization } from '../domain/utilization';
import { useApiResource } from '../hooks/useApiResource';
import type { ConnectionStatus } from '../hooks/useClusterHealthStream';
import { useClusterHealthStream } from '../hooks/useClusterHealthStream';

const CAPACITY_REFRESH_INTERVAL_MILLISECONDS = 15_000;

const STATUS_TEXT: Record<ConnectionStatus, string> = {
    connecting: 'Connecting to the live stream…',
    live: 'Live',
    reconnecting: 'Reconnecting — polling every 10s',
    capped: 'Connection limit reached — polling every 10s',
};

const STATUS_CLASSES: Record<ConnectionStatus, string> = {
    connecting: 'text-text-muted',
    live: 'text-state-good',
    reconnecting: 'text-state-warning',
    capped: 'text-state-warning',
};

export function ClusterOverviewPage() {
    const { snapshots, error, connectionStatus, ageSeconds, isStale } = useClusterHealthStream();
    const capacityFetcher = useCallback((signal: AbortSignal) => getCapacity(signal), []);
    const { data: capacity } = useApiResource(
        capacityFetcher,
        CAPACITY_REFRESH_INTERVAL_MILLISECONDS,
    );

    if (snapshots === null) {
        return (
            <section>
                <PageHeading eyebrow="Real-Time Health" title="Cluster Overview" />
                <p className="mt-6 text-text-muted">
                    {error === null ? 'Loading cluster health…' : `Unavailable — ${error.detail}`}
                </p>
            </section>
        );
    }

    return (
        <section>
            <PageHeading
                eyebrow="Real-Time Health"
                title="Cluster Overview"
                aside={
                    <span
                        className={`eyebrow ${isStale || error !== null ? 'text-state-warning' : STATUS_CLASSES[connectionStatus]}`}
                        role="status"
                    >
                        {isStale
                            ? 'Stale'
                            : error !== null
                              ? 'Refresh failed'
                              : STATUS_TEXT[connectionStatus]}
                        {' · '}
                        {ageSeconds}s old
                    </span>
                }
            />

            {error !== null && (
                <p className="mt-6 text-state-warning" role="alert">
                    {error.detail}. Showing the last snapshot.
                </p>
            )}

            {snapshots.map((snapshot) => (
                <div key={snapshot.cluster_id} className="mt-12">
                    <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
                        <h2 className="display-title text-3xl">
                            {formatEntityId(snapshot.cluster_name)}
                        </h2>
                        <p className="text-sm text-text-muted">
                            {snapshot.unresolved_failure_count} unresolved failures
                        </p>
                    </div>
                    <div className="mt-8 grid gap-x-10 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
                        <StateCounts title="Nodes" counts={snapshot.nodes_by_health_state} />
                        <StateCounts title="GPUs" counts={snapshot.gpus_by_health_state} />
                        <StateCounts title="Jobs" counts={snapshot.jobs_by_lifecycle_state} />
                        <UtilizationPanel utilization={deriveGpuUtilization(capacity ?? [])} />
                    </div>
                </div>
            ))}

            <div className="mt-12">
                <Section title="All Nodes">
                    <NodeList />
                </Section>
            </div>

            <div className="mt-12">
                <Section title="Recent Jobs">
                    <JobList />
                </Section>
            </div>
        </section>
    );
}
