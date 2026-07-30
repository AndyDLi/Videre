import type { ClusterHealthSnapshot } from '../api/types';

export type HealthTone = 'good' | 'warning' | 'bad' | 'neutral';

interface OverallHealth {
    tone: HealthTone;
    label: string;
    detail: string;
}

function countExcept(counts: Partial<Record<string, number>>, healthyState: string): number {
    return Object.entries(counts)
        .filter(([state]) => state !== healthyState)
        .reduce((total, [, count]) => total + (count ?? 0), 0);
}

function sumAcross(
    snapshots: ClusterHealthSnapshot[],
    count: (snapshot: ClusterHealthSnapshot) => number,
): number {
    return snapshots.reduce((total, snapshot) => total + count(snapshot), 0);
}

export function summarizeClusterHealth(snapshots: ClusterHealthSnapshot[]): OverallHealth {
    if (snapshots.length === 0) {
        return { tone: 'neutral', label: 'NO CLUSTERS', detail: 'no cluster data yet' };
    }

    const affectedNodes = sumAcross(snapshots, (snapshot) =>
        countExcept(snapshot.nodes_by_health_state, 'READY'),
    );
    const affectedGpus = sumAcross(snapshots, (snapshot) =>
        countExcept(snapshot.gpus_by_health_state, 'HEALTHY'),
    );
    const unresolvedFailures = sumAcross(
        snapshots,
        (snapshot) => snapshot.unresolved_failure_count,
    );

    if (affectedNodes === 0 && affectedGpus === 0 && unresolvedFailures === 0) {
        return {
            tone: 'good',
            label: 'HEALTHY',
            detail: `${String(snapshots.length)} cluster(s) nominal`,
        };
    }

    const detail = `${String(affectedNodes)} nodes, ${String(affectedGpus)} GPUs affected · ${String(unresolvedFailures)} unresolved`;
    return affectedNodes > 0
        ? { tone: 'bad', label: 'DEGRADED', detail }
        : { tone: 'warning', label: 'WARNING', detail };
}
