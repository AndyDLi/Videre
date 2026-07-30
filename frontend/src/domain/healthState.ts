import type { GpuHealthState, JobLifecycleState, NodeHealthState } from '../api/types';
import type { HealthTone } from './clusterHealth';

type EntityState = NodeHealthState | GpuHealthState | JobLifecycleState;

const STATE_TONES: Record<EntityState, HealthTone> = {
    READY: 'good',
    NOT_READY: 'bad',
    DRAINING: 'warning',
    CORDONED: 'warning',
    HEALTHY: 'good',
    THROTTLING: 'warning',
    DEGRADED: 'warning',
    FAILED: 'bad',
    PENDING: 'neutral',
    RUNNING: 'good',
    COMPLETED: 'neutral',
};

export function toneForState(state: string): HealthTone {
    return STATE_TONES[state as EntityState] ?? 'neutral';
}
