import { Link } from 'react-router-dom';

import type { Gpu } from '../api/types';
import { HealthBadge } from './HealthBadge';

interface GpuChipsProps {
    nodeId: string;
    gpus: Gpu[];
}

export function GpuChips({ nodeId, gpus }: GpuChipsProps) {
    return (
        <ul className="flex flex-wrap gap-2">
            {gpus.map((gpu) => (
                <li key={gpu.id}>
                    <Link
                        to={`/nodes/${nodeId}/gpus/${gpu.id}`}
                        className="flex items-center gap-2 rounded border border-border-subtle px-2 py-1 text-xs hover:bg-surface-muted"
                    >
                        <span className="font-medium">{gpu.id}</span>
                        <HealthBadge state={gpu.health_state} />
                        <span className="tabular-nums text-text-muted">
                            {Math.round(gpu.utilization_percentage)}% ·{' '}
                            {Math.round(gpu.temperature_celsius)}°C
                        </span>
                    </Link>
                </li>
            ))}
        </ul>
    );
}
