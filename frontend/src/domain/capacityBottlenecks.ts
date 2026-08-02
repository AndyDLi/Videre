import type { CapacitySummary } from '../api/types';

export interface Bottleneck {
    label: string;
    count: number;
    description: string;
}

export function bottlenecksByImpact(summary: CapacitySummary): Bottleneck[] {
    const bottlenecks: Bottleneck[] = [
        {
            label: 'Unavailable GPUs',
            count: summary.unavailable_gpus,
            description: 'GPUs sitting on nodes that are not READY.',
        },
        {
            label: 'Idle but Reserved GPUs',
            count: summary.idle_reserved_gpus,
            description: 'Healthy, near-zero-utilization GPUs on nodes running no job.',
        },
        {
            label: 'Fragmentation Events',
            count: summary.fragmentation_event_count,
            description: 'Queueing delays where free capacity could not be packed together.',
        },
        {
            label: 'Queued Jobs',
            count: summary.queued_job_count,
            description: 'Jobs still PENDING, waiting on a placement.',
        },
        {
            label: 'Drained Nodes',
            count: summary.drained_node_count,
            description: 'Nodes DRAINING for maintenance.',
        },
        {
            label: 'Unschedulable Nodes',
            count: summary.unschedulable_node_count,
            description: 'Nodes CORDONED out of the schedulable pool.',
        },
    ];
    return bottlenecks.sort((first, second) => second.count - first.count);
}
