import { describe, expect, it } from 'vitest';

import type { ClusterHealthSnapshot } from '../api/types';
import { summarizeClusterHealth } from '../domain/clusterHealth';

function snapshot(overrides: Partial<ClusterHealthSnapshot> = {}): ClusterHealthSnapshot {
    return {
        cluster_id: 'cluster-1',
        cluster_name: 'Cluster One',
        generated_at: '2026-07-29T00:00:00Z',
        nodes_by_health_state: { READY: 4 },
        gpus_by_health_state: { HEALTHY: 32 },
        jobs_by_lifecycle_state: { RUNNING: 3 },
        unresolved_failure_count: 0,
        ...overrides,
    };
}

describe('summarizeClusterHealth', () => {
    it('reports healthy when nothing is affected', () => {
        expect(summarizeClusterHealth([snapshot()])).toMatchObject({
            tone: 'good',
            label: 'HEALTHY',
        });
    });

    it('reports degraded when a node is not ready', () => {
        const result = summarizeClusterHealth([
            snapshot({ nodes_by_health_state: { READY: 3, NOT_READY: 1 } }),
        ]);
        expect(result).toMatchObject({ tone: 'bad', label: 'DEGRADED' });
        expect(result.detail).toContain('1 nodes');
    });

    it('reports degraded for a draining or cordoned node, not only NOT_READY', () => {
        const result = summarizeClusterHealth([
            snapshot({ nodes_by_health_state: { READY: 2, DRAINING: 1, CORDONED: 1 } }),
        ]);
        expect(result).toMatchObject({ tone: 'bad', label: 'DEGRADED' });
        expect(result.detail).toContain('2 nodes');
    });

    it('reports a warning when only GPUs are affected', () => {
        const result = summarizeClusterHealth([
            snapshot({
                gpus_by_health_state: { HEALTHY: 30, THROTTLING: 2 },
                unresolved_failure_count: 2,
            }),
        ]);
        expect(result).toMatchObject({ tone: 'warning', label: 'WARNING' });
        expect(result.detail).toContain('2 GPUs');
        expect(result.detail).toContain('2 unresolved');
    });

    it('reports a warning when only unresolved failures remain', () => {
        const result = summarizeClusterHealth([snapshot({ unresolved_failure_count: 3 })]);
        expect(result).toMatchObject({ tone: 'warning', label: 'WARNING' });
        expect(result.detail).toContain('3 unresolved');
    });

    it('handles an empty cluster list', () => {
        expect(summarizeClusterHealth([])).toMatchObject({ tone: 'neutral', label: 'NO CLUSTERS' });
    });

    it('aggregates across clusters', () => {
        const result = summarizeClusterHealth([
            snapshot({ cluster_id: 'cluster-1', unresolved_failure_count: 1 }),
            snapshot({ cluster_id: 'cluster-2', gpus_by_health_state: { FAILED: 1 } }),
        ]);
        expect(result.detail).toContain('1 GPUs');
        expect(result.detail).toContain('1 unresolved');
    });
});
