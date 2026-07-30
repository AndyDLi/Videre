import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';

import { getNode } from '../api/endpoints';
import { Card } from '../components/Card';
import { DetailFallback } from '../components/DetailFallback';
import { DetailList } from '../components/DetailList';
import { EntityFailures } from '../components/EntityFailures';
import { EntityHeader } from '../components/EntityHeader';
import { GrafanaPanel } from '../components/GrafanaPanel';
import { formatTimestamp } from '../domain/format';
import { useApiResource } from '../hooks/useApiResource';

const REFRESH_INTERVAL_MILLISECONDS = 15_000;

export function GpuDetailPage() {
    const { nodeId = '', gpuId = '' } = useParams<{ nodeId: string; gpuId: string }>();

    const fetcher = useCallback((signal: AbortSignal) => getNode(nodeId, signal), [nodeId]);
    const { data: node, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);
    const gpu = node?.gpus.find((candidate) => candidate.id === gpuId) ?? null;

    if (gpu === null) {
        return (
            <DetailFallback title={`GPU ${gpuId}`}>
                {isLoading
                    ? 'Loading this GPU…'
                    : node !== null
                      ? `Node ${nodeId} has no GPU with the id ${gpuId}.`
                      : error?.status === 404
                        ? `No node with the id ${nodeId} exists.`
                        : `Could not load this GPU — ${error?.detail ?? 'unknown error'}`}
            </DetailFallback>
        );
    }

    return (
        <section className="space-y-4">
            <EntityHeader
                title={`GPU ${gpu.id}`}
                state={gpu.health_state}
                entityType="gpu"
                entityId={gpu.id}
            />

            <Card title="Current State">
                <DetailList
                    details={[
                        {
                            label: 'Node',
                            value: (
                                <Link
                                    to={`/nodes/${gpu.node_id}`}
                                    className="font-medium hover:underline"
                                >
                                    {gpu.node_id}
                                </Link>
                            ),
                        },
                        {
                            label: 'Utilization',
                            value: `${String(Math.round(gpu.utilization_percentage))}%`,
                        },
                        {
                            label: 'Temperature',
                            value: `${String(Math.round(gpu.temperature_celsius))}°C`,
                        },
                        {
                            label: 'Memory Used',
                            value: `${String(gpu.memory_used_mb)} / ${String(gpu.memory_total_mb)} MB`,
                        },
                        { label: 'ECC Correctable Errors', value: gpu.ecc_correctable_count },
                        { label: 'ECC Uncorrectable Errors', value: gpu.ecc_uncorrectable_count },
                        { label: 'Xid Errors', value: gpu.xid_error_count },
                        { label: 'Last Updated', value: formatTimestamp(gpu.last_updated_at) },
                    ]}
                />
            </Card>

            <Card title="Utilization">
                <GrafanaPanel
                    title={`Utilization of ${gpu.id}`}
                    panel="gpuUtilization"
                    nodeId={gpu.node_id}
                    gpuId={gpu.id}
                />
            </Card>

            <Card title="Temperature">
                <GrafanaPanel
                    title={`Temperature of ${gpu.id}`}
                    panel="gpuTemperature"
                    nodeId={gpu.node_id}
                    gpuId={gpu.id}
                />
            </Card>

            <Card title="Recent Failures">
                <EntityFailures entityType="gpu" entityId={gpu.id} />
            </Card>
        </section>
    );
}
