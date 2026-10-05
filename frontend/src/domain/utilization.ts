import type { CapacitySummary } from '../api/types';

export interface GpuAvailability {
    totalGpus: number;
    unavailableGpus: number;
    degradedGpus: number;
    idleGpus: number;
    activeGpus: number;
}

export function deriveGpuAvailability(summaries: CapacitySummary[]): GpuAvailability | null {
    const totalGpus = summaries.reduce((total, summary) => total + summary.total_gpus, 0);
    if (totalGpus === 0) {
        return null;
    }

    const unavailableGpus = summaries.reduce(
        (total, summary) => total + summary.unavailable_gpus,
        0,
    );
    const degradedGpus = summaries.reduce((total, summary) => total + summary.degraded_gpus, 0);
    const idleGpus = summaries.reduce((total, summary) => total + summary.idle_gpus, 0);
    const activeGpus = summaries.reduce((total, summary) => total + summary.active_gpus, 0);

    return {
        totalGpus,
        unavailableGpus,
        degradedGpus,
        idleGpus,
        activeGpus,
    };
}
