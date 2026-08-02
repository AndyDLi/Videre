import type { GpuUtilization } from '../domain/utilization';
import { Section } from './Section';

export function UtilizationPanel({ utilization }: { utilization: GpuUtilization | null }) {
    if (utilization === null) {
        return (
            <Section title="GPU Utilization" headingLevel={3}>
                <p className="text-sm text-text-muted">No GPU capacity reported yet.</p>
            </Section>
        );
    }

    const rows = [
        {
            label: 'In Use',
            value: `${String(utilization.inUseGpus)} / ${String(utilization.totalGpus)}`,
        },
        { label: 'Unavailable', value: utilization.unavailableGpus },
        { label: 'Idle but Reserved', value: utilization.idleReservedGpus },
    ];

    return (
        <Section title="GPU Utilization" headingLevel={3}>
            <p className="metric text-5xl">{utilization.inUsePercentage}%</p>
            <div
                className="mt-4 h-0.5 w-full bg-border-subtle"
                role="progressbar"
                aria-label="GPUs In Use"
                aria-valuenow={utilization.inUsePercentage}
                aria-valuemin={0}
                aria-valuemax={100}
            >
                <div
                    className="h-0.5 bg-state-good"
                    style={{ width: `${String(utilization.inUsePercentage)}%` }}
                />
            </div>
            <dl className="mt-4 space-y-1.5 text-sm text-text-muted">
                {rows.map((row) => (
                    <div key={row.label} className="flex justify-between gap-3">
                        <dt>{row.label}</dt>
                        <dd className="tabular-nums">{row.value}</dd>
                    </div>
                ))}
            </dl>
        </Section>
    );
}
