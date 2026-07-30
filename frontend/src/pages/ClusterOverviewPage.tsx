import { useCallback } from 'react';

import { getCapacity } from '../api/endpoints';
import { Card } from '../components/Card';
import { JobList } from '../components/JobList';
import { NodeList } from '../components/NodeList';
import { StateCounts } from '../components/StateCounts';
import { UtilizationPanel } from '../components/UtilizationPanel';
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
    const { snapshots, error, connectionStatus } = useClusterHealthStream();
    const capacityFetcher = useCallback((signal: AbortSignal) => getCapacity(signal), []);
    const { data: capacity } = useApiResource(
        capacityFetcher,
        CAPACITY_REFRESH_INTERVAL_MILLISECONDS,
    );

    if (snapshots === null) {
        return (
            <section>
                <h1 className="text-xl font-semibold">Cluster Overview</h1>
                <p className="mt-4 text-sm text-text-muted">
                    {error === null ? 'Loading cluster health…' : `Unavailable — ${error.detail}`}
                </p>
            </section>
        );
    }

    return (
        <section className="space-y-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h1 className="text-xl font-semibold">Cluster Overview</h1>
                <span
                    className={`text-sm font-medium ${STATUS_CLASSES[connectionStatus]}`}
                    role="status"
                >
                    {STATUS_TEXT[connectionStatus]}
                </span>
            </div>

            {snapshots.map((snapshot) => (
                <div key={snapshot.cluster_id} className="space-y-3">
                    <div>
                        <h2 className="text-lg font-semibold">{snapshot.cluster_name}</h2>
                        <p className="mt-1 text-sm text-text-muted">
                            {snapshot.unresolved_failure_count} unresolved failures
                        </p>
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                        <StateCounts title="Nodes" counts={snapshot.nodes_by_health_state} />
                        <StateCounts title="GPUs" counts={snapshot.gpus_by_health_state} />
                        <StateCounts title="Jobs" counts={snapshot.jobs_by_lifecycle_state} />
                        <UtilizationPanel utilization={deriveGpuUtilization(capacity ?? [])} />
                    </div>
                </div>
            ))}

            <Card title="All Nodes">
                <NodeList />
            </Card>

            <Card title="Recent Jobs">
                <JobList />
            </Card>
        </section>
    );
}
