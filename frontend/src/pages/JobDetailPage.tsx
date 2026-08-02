import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';

import { getJob } from '../api/endpoints';
import { Section } from '../components/Section';
import { DetailFallback } from '../components/DetailFallback';
import { DetailList } from '../components/DetailList';
import { EntityFailures } from '../components/EntityFailures';
import { EntityHeader } from '../components/EntityHeader';
import { GrafanaPanel } from '../components/GrafanaPanel';
import { formatEntityId, formatTimestamp } from '../domain/format';
import { useApiResource } from '../hooks/useApiResource';

const REFRESH_INTERVAL_MILLISECONDS = 15_000;

export function JobDetailPage() {
    const jobId = useParams<{ jobId: string }>().jobId ?? '';

    const fetcher = useCallback((signal: AbortSignal) => getJob(jobId, signal), [jobId]);
    const { data: job, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);

    if (job === null) {
        return (
            <DetailFallback title={`Job ${jobId}`}>
                {isLoading
                    ? 'Loading this job…'
                    : error?.status === 404
                      ? `No job with the id ${jobId} exists.`
                      : `Could not load this job — ${error?.detail ?? 'unknown error'}`}
            </DetailFallback>
        );
    }

    const [firstAssignedNodeId] = job.assigned_node_ids;

    return (
        <section className="space-y-12">
            <EntityHeader state={job.lifecycle_state} entityType="job" entityId={job.id} />

            <Section title="Current State">
                <DetailList
                    details={[
                        { label: 'Cluster', value: formatEntityId(job.cluster_id) },
                        { label: 'Priority', value: job.priority },
                        { label: 'Requested CPU Cores', value: job.requested_cpu_cores },
                        {
                            label: 'Requested Memory',
                            value: `${String(job.requested_memory_gb)} GB`,
                        },
                        { label: 'Requested GPUs', value: job.requested_gpu_count },
                        {
                            label: 'Pod Name',
                            value:
                                job.pod_name === null ? (
                                    'not scheduled yet'
                                ) : (
                                    <span className="identifier">{job.pod_name}</span>
                                ),
                        },
                        { label: 'Failure Reason', value: job.failure_reason ?? 'none' },
                        { label: 'Created', value: formatTimestamp(job.created_at) },
                        {
                            label: 'Started',
                            value:
                                job.started_at === null
                                    ? 'not started'
                                    : formatTimestamp(job.started_at),
                        },
                        {
                            label: 'Completed',
                            value:
                                job.completed_at === null
                                    ? 'not completed'
                                    : formatTimestamp(job.completed_at),
                        },
                    ]}
                />
            </Section>

            <Section title="Assigned Nodes">
                {job.assigned_node_ids.length === 0 ? (
                    <p className="text-sm text-text-muted">
                        This job has not been placed on a node yet.
                    </p>
                ) : (
                    <ul className="flex flex-wrap gap-2">
                        {job.assigned_node_ids.map((assignedNodeId) => (
                            <li key={assignedNodeId}>
                                <Link
                                    to={`/nodes/${assignedNodeId}`}
                                    className="identifier inline-block rounded-[3px] border border-border-strong px-2.5 py-1 hover:bg-surface-raised"
                                >
                                    {formatEntityId(assignedNodeId)}
                                </Link>
                            </li>
                        ))}
                    </ul>
                )}
            </Section>

            {firstAssignedNodeId !== undefined && (
                <Section title={`GPU Utilization on ${formatEntityId(firstAssignedNodeId)}`}>
                    <GrafanaPanel
                        title={`GPU Utilization on ${formatEntityId(firstAssignedNodeId)}`}
                        panel="gpuUtilization"
                        nodeId={firstAssignedNodeId}
                    />
                </Section>
            )}

            <Section title="Recent Failures">
                <EntityFailures entityType="job" entityId={job.id} />
            </Section>
        </section>
    );
}
