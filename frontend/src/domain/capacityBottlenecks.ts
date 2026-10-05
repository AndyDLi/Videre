import type { CapacitySummary } from '../api/types';

export interface CapacityIndicator {
    label: string;
    count: number;
    description: string;
}

export function capacityIndicators(summary: CapacitySummary): CapacityIndicator[] {
    return [
        {
            label: 'Unavailable GPUs',
            count: summary.unavailable_gpus,
            description: 'GPUs on NOT_READY, DRAINING or CORDONED nodes, or FAILED GPUs.',
        },
        {
            label: 'Degraded GPUs',
            count: summary.degraded_gpus,
            description: 'DEGRADED or THROTTLING GPUs on READY nodes, at any utilization.',
        },
        {
            label: 'Healthy Idle GPUs',
            count: summary.idle_gpus,
            description: 'HEALTHY GPUs on READY nodes with utilization below 5%.',
        },
        {
            label: 'Healthy Active GPUs',
            count: summary.active_gpus,
            description: 'HEALTHY GPUs on READY nodes with utilization at least 5%.',
        },
        {
            label: 'Pending Jobs',
            count: summary.queued_job_count,
            description: 'Jobs still PENDING, waiting on a placement.',
        },
        {
            label: 'Draining Nodes',
            count: summary.drained_node_count,
            description: 'Nodes DRAINING for maintenance.',
        },
        {
            label: 'Cordoned Nodes',
            count: summary.unschedulable_node_count,
            description: 'Nodes CORDONED out of the schedulable pool.',
        },
        {
            label: 'Queueing-Delay Events (Last 3 Days)',
            count: summary.queueing_delay_event_count,
            description: 'Node-linked QUEUEING_DELAY records stored within the last 3 days.',
        },
    ];
}
