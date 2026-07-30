import type { GpuUtilization } from '../domain/utilization';
import { Card } from './Card';

export function UtilizationPanel({ utilization }: { utilization: GpuUtilization | null }) {
    if (utilization === null) {
        return (
            <Card title="GPU Utilization" headingLevel={3}>
                <p className="text-sm text-text-muted">No GPU capacity reported yet.</p>
            </Card>
        );
    }

    return (
        <Card title="GPU Utilization" headingLevel={3}>
            <p className="text-2xl font-semibold tabular-nums">{utilization.inUsePercentage}%</p>
            <div
                className="mt-2 h-2 w-full overflow-hidden rounded bg-surface-muted"
                role="progressbar"
                aria-label="GPUs in use"
                aria-valuenow={utilization.inUsePercentage}
                aria-valuemin={0}
                aria-valuemax={100}
            >
                <div
                    className="h-full bg-state-good"
                    style={{ width: `${String(utilization.inUsePercentage)}%` }}
                />
            </div>
            <dl className="mt-3 space-y-1 text-sm text-text-muted">
                <div className="flex justify-between">
                    <dt>In Use</dt>
                    <dd className="tabular-nums">
                        {utilization.inUseGpus} / {utilization.totalGpus}
                    </dd>
                </div>
                <div className="flex justify-between">
                    <dt>Unavailable</dt>
                    <dd className="tabular-nums">{utilization.unavailableGpus}</dd>
                </div>
                <div className="flex justify-between">
                    <dt>Idle but Reserved</dt>
                    <dd className="tabular-nums">{utilization.idleReservedGpus}</dd>
                </div>
            </dl>
        </Card>
    );
}
