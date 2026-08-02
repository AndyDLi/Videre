import { useCallback } from 'react';

import { listClusters } from '../api/endpoints';
import { summarizeClusterHealth } from '../domain/clusterHealth';
import type { HealthTone } from '../domain/healthState';
import { useApiResource } from '../hooks/useApiResource';

const POLL_INTERVAL_MILLISECONDS = 15_000;

const TONE_CLASSES: Record<HealthTone, string> = {
    good: 'text-state-good',
    warning: 'text-state-warning',
    bad: 'text-state-bad',
    neutral: 'text-state-neutral',
};

export function ClusterHealthSummary() {
    const fetcher = useCallback((signal: AbortSignal) => listClusters(signal), []);
    const { data, error, isLoading } = useApiResource(fetcher, POLL_INTERVAL_MILLISECONDS);

    if (isLoading) {
        return <span className="text-sm text-text-muted">Checking cluster health…</span>;
    }

    if (error !== null || data === null) {
        return (
            <span className="text-sm text-state-bad" role="status">
                {error?.isNetworkFailure === true
                    ? 'Backend unreachable'
                    : 'Cluster health unavailable'}
            </span>
        );
    }

    const overall = summarizeClusterHealth(data);
    return (
        <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5" role="status">
            <span className={`eyebrow ${TONE_CLASSES[overall.tone]}`}>{overall.label}</span>
            <span className="text-sm text-text-muted">{overall.detail}</span>
        </span>
    );
}
