import { useCallback } from 'react';
import { useParams } from 'react-router-dom';

import { getNode } from '../api/endpoints';
import { Section } from '../components/Section';
import { DetailFallback } from '../components/DetailFallback';
import { DetailList } from '../components/DetailList';
import { EntityFailures } from '../components/EntityFailures';
import { EntityHeader } from '../components/EntityHeader';
import { GpuGrid } from '../components/GpuGrid';
import { GrafanaPanel } from '../components/GrafanaPanel';
import { formatEntityId, formatTimestamp } from '../domain/format';
import { useApiResource } from '../hooks/useApiResource';

const REFRESH_INTERVAL_MILLISECONDS = 15_000;

export function NodeDetailPage() {
    const nodeId = useParams<{ nodeId: string }>().nodeId ?? '';

    const fetcher = useCallback((signal: AbortSignal) => getNode(nodeId, signal), [nodeId]);
    const { data: node, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);

    if (node === null) {
        return (
            <DetailFallback title={`Node ${nodeId}`}>
                {isLoading
                    ? 'Loading this node…'
                    : error?.status === 404
                      ? `No node with the id ${nodeId} exists.`
                      : `Could not load this node — ${error?.detail ?? 'unknown error'}`}
            </DetailFallback>
        );
    }

    return (
        <section className="space-y-12">
            <EntityHeader state={node.health_state} entityType="node" entityId={node.id} />

            <Section title="Current State">
                <DetailList
                    details={[
                        { label: 'Cluster', value: formatEntityId(node.cluster_id) },
                        { label: 'CPU Cores', value: node.cpu_cores },
                        { label: 'Memory', value: `${String(node.memory_gb)} GB` },
                        { label: 'GPU Count', value: node.gpu_count },
                        { label: 'Last Updated', value: formatTimestamp(node.updated_at) },
                    ]}
                />
            </Section>

            <Section title="GPUs">
                <GpuGrid nodeId={node.id} gpus={node.gpus} />
            </Section>

            <Section title="Health State History">
                <GrafanaPanel
                    title={`Health State of ${formatEntityId(node.id)}`}
                    panel="nodeHealthState"
                    nodeId={node.id}
                />
            </Section>

            <Section title="GPU Utilization">
                <GrafanaPanel
                    title={`GPU Utilization on ${formatEntityId(node.id)}`}
                    panel="gpuUtilization"
                    nodeId={node.id}
                />
            </Section>

            <Section title="GPU Temperature">
                <GrafanaPanel
                    title={`GPU Temperature on ${formatEntityId(node.id)}`}
                    panel="gpuTemperature"
                    nodeId={node.id}
                />
            </Section>

            <Section title="Recent Failures">
                <EntityFailures entityType="node" entityId={node.id} />
            </Section>
        </section>
    );
}
