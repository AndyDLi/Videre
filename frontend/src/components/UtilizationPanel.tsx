import type { GpuAvailability } from '../domain/utilization';
import { Section } from './Section';

export function UtilizationPanel({ availability }: { availability: GpuAvailability | null }) {
    if (availability === null) {
        return (
            <Section title="GPU Availability" headingLevel={3}>
                <p className="text-sm text-text-muted">No GPU capacity reported yet.</p>
            </Section>
        );
    }

    const rows = [
        { label: 'Total GPUs', value: availability.totalGpus },
        { label: 'Unavailable for New Work', value: availability.unavailableGpus },
        { label: 'Degraded', value: availability.degradedGpus },
        { label: 'Healthy Idle', value: availability.idleGpus },
        { label: 'Healthy Active', value: availability.activeGpus },
    ];

    return (
        <Section title="GPU Availability" headingLevel={3}>
            <dl className="space-y-1.5 text-sm text-text-muted">
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
