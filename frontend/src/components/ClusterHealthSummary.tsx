import { useCallback } from 'react';

import { listClusters } from '../api/endpoints';
import type { HealthTone } from '../domain/clusterHealth';
import { summarizeClusterHealth } from '../domain/clusterHealth';
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

    if (isLoading && data === null && error === null) {
        return <span className="text-sm text-text-muted">checking cluster health…</span>;
    }

    if (error !== null || data === null) {
        return (
            <span className="text-sm font-semibold text-state-bad" role="status">
                {error?.isNetworkFailure === true
                    ? 'backend unreachable'
                    : 'cluster health unavailable'}
            </span>
        );
    }

    const overall = summarizeClusterHealth(data);
    return (
        <span className="text-sm" role="status">
            <span className={`font-semibold ${TONE_CLASSES[overall.tone]}`}>{overall.label}</span>
            <span className="ml-2 text-text-muted">{overall.detail}</span>
        </span>
    );
}
