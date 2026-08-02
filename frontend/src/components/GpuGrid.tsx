import { Link } from 'react-router-dom';

import type { Gpu } from '../api/types';
import { formatEntityId } from '../domain/format';
import { HealthBadge } from './HealthBadge';

interface GpuGridProps {
    nodeId: string;
    gpus: Gpu[];
}

export function GpuGrid({ nodeId, gpus }: GpuGridProps) {
    return (
        <ul className="grid gap-x-8 sm:grid-cols-2 lg:grid-cols-4">
            {gpus.map((gpu) => (
                <li key={gpu.id} className="border-t border-border-subtle">
                    <Link
                        to={`/nodes/${nodeId}/gpus/${gpu.id}`}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 hover:bg-surface-raised"
                    >
                        <span className="identifier">{formatEntityId(gpu.id)}</span>
                        <HealthBadge state={gpu.health_state} />
                        <span className="ml-auto text-sm tabular-nums text-text-muted">
                            {Math.round(gpu.utilization_percentage)}% ·{' '}
                            {Math.round(gpu.temperature_celsius)}°C
                        </span>
                    </Link>
                </li>
            ))}
        </ul>
    );
}
