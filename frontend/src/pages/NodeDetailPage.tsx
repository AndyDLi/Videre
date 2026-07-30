import { useCallback } from 'react';
import { useParams } from 'react-router-dom';

import { getNode } from '../api/endpoints';
import { Card } from '../components/Card';
import { DetailFallback } from '../components/DetailFallback';
import { DetailList } from '../components/DetailList';
import { EntityFailures } from '../components/EntityFailures';
import { EntityHeader } from '../components/EntityHeader';
import { GpuChips } from '../components/GpuChips';
import { GrafanaPanel } from '../components/GrafanaPanel';
import { formatTimestamp } from '../domain/format';
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
        <section className="space-y-4">
            <EntityHeader
                title={`Node ${node.id}`}
                state={node.health_state}
                entityType="node"
                entityId={node.id}
            />

            <Card title="Current State">
                <DetailList
                    details={[
                        { label: 'Cluster', value: node.cluster_id },
                        { label: 'CPU Cores', value: node.cpu_cores },
                        { label: 'Memory', value: `${String(node.memory_gb)} GB` },
                        { label: 'GPU Count', value: node.gpu_count },
                        { label: 'Last Updated', value: formatTimestamp(node.updated_at) },
                    ]}
                />
            </Card>

            <Card title="GPUs">
                <GpuChips nodeId={node.id} gpus={node.gpus} />
            </Card>

            <Card title="Health State History">
                <GrafanaPanel
                    title={`Health state of ${node.id}`}
                    panel="nodeHealthState"
                    nodeId={node.id}
                />
            </Card>

            <Card title="GPU Utilization">
                <GrafanaPanel
                    title={`GPU utilization on ${node.id}`}
                    panel="gpuUtilization"
                    nodeId={node.id}
                />
            </Card>

            <Card title="GPU Temperature">
                <GrafanaPanel
                    title={`GPU temperature on ${node.id}`}
                    panel="gpuTemperature"
                    nodeId={node.id}
                />
            </Card>

            <Card title="Recent Failures">
                <EntityFailures entityType="node" entityId={node.id} />
            </Card>
        </section>
    );
}
