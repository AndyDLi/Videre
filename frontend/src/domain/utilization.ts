import type { CapacitySummary } from '../api/types';

export interface GpuUtilization {
    totalGpus: number;
    inUseGpus: number;
    unavailableGpus: number;
    idleReservedGpus: number;
    inUsePercentage: number;
}

export function deriveGpuUtilization(summaries: CapacitySummary[]): GpuUtilization | null {
    const totalGpus = summaries.reduce((total, summary) => total + summary.total_gpus, 0);
    if (totalGpus === 0) {
        return null;
    }

    const unavailableGpus = summaries.reduce(
        (total, summary) => total + summary.unavailable_gpus,
        0,
    );
    const idleReservedGpus = summaries.reduce(
        (total, summary) => total + summary.idle_reserved_gpus,
        0,
    );
    const inUseGpus = Math.max(totalGpus - unavailableGpus - idleReservedGpus, 0);

    return {
        totalGpus,
        inUseGpus,
        unavailableGpus,
        idleReservedGpus,
        inUsePercentage: Math.round((inUseGpus / totalGpus) * 100),
    };
}
