import { describe, expect, it } from 'vitest';

import type { CapacitySummary } from '../api/types';
import { deriveGpuUtilization } from '../domain/utilization';

function summary(overrides: Partial<CapacitySummary> = {}): CapacitySummary {
    return {
        cluster_id: 'cluster-a',
        total_gpus: 32,
        unavailable_gpus: 0,
        idle_reserved_gpus: 0,
        drained_node_count: 0,
        unschedulable_node_count: 0,
        queued_job_count: 0,
        fragmentation_event_count: 0,
        ...overrides,
    };
}

describe('deriveGpuUtilization', () => {
    it('returns null when no GPU capacity is reported', () => {
        expect(deriveGpuUtilization([])).toBeNull();
        expect(deriveGpuUtilization([summary({ total_gpus: 0 })])).toBeNull();
    });

    it('counts every GPU as in use when none are unavailable or idle-reserved', () => {
        expect(deriveGpuUtilization([summary()])).toMatchObject({
            inUseGpus: 32,
            inUsePercentage: 100,
        });
    });

    it('excludes unavailable and idle-reserved GPUs', () => {
        expect(
            deriveGpuUtilization([summary({ unavailable_gpus: 16, idle_reserved_gpus: 4 })]),
        ).toMatchObject({ inUseGpus: 12, inUsePercentage: 38 });
    });

    it('matches the live cluster reading of 16 of 32 unavailable', () => {
        expect(deriveGpuUtilization([summary({ unavailable_gpus: 16 })])).toMatchObject({
            inUseGpus: 16,
            inUsePercentage: 50,
        });
    });

    it('never reports a negative in-use count', () => {
        expect(
            deriveGpuUtilization([summary({ unavailable_gpus: 30, idle_reserved_gpus: 8 })]),
        ).toMatchObject({ inUseGpus: 0, inUsePercentage: 0 });
    });

    it('aggregates across clusters', () => {
        const result = deriveGpuUtilization([
            summary({ cluster_id: 'cluster-a', total_gpus: 16, unavailable_gpus: 8 }),
            summary({ cluster_id: 'cluster-b', total_gpus: 16 }),
        ]);
        expect(result).toMatchObject({ totalGpus: 32, inUseGpus: 24, inUsePercentage: 75 });
    });
});
