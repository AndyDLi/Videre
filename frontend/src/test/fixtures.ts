import type { CapacitySummary, FailureRecord, Gpu, JobSummary, NodeSummary } from '../api/types';

export function jsonResponse(
    body: unknown,
    status = 200,
    headers: Record<string, string> = {},
): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json', ...headers },
    });
}

export function requestUrl(input: RequestInfo | URL): string {
    if (typeof input === 'string') {
        return input;
    }
    return input instanceof URL ? input.href : input.url;
}

export function nodeSummary(overrides: Partial<NodeSummary> = {}): NodeSummary {
    return {
        id: 'node-0',
        cluster_id: 'cluster-a',
        cpu_cores: 64,
        memory_gb: 512,
        gpu_count: 8,
        health_state: 'READY',
        updated_at: '2026-07-29T00:00:00Z',
        ...overrides,
    };
}

export function gpu(overrides: Partial<Gpu> = {}): Gpu {
    return {
        id: 'gpu-1-0',
        node_id: 'node-1',
        utilization_percentage: 82.4,
        temperature_celsius: 61.7,
        memory_used_mb: 40_000,
        memory_total_mb: 81_920,
        ecc_correctable_count: 0,
        ecc_uncorrectable_count: 0,
        xid_error_count: 0,
        health_state: 'HEALTHY',
        last_updated_at: '2026-07-29T00:00:00Z',
        ...overrides,
    };
}

export function jobSummary(overrides: Partial<JobSummary> = {}): JobSummary {
    return {
        id: 'job-1',
        cluster_id: 'cluster-a',
        lifecycle_state: 'RUNNING',
        requested_cpu_cores: 8,
        requested_memory_gb: 64,
        requested_gpu_count: 4,
        priority: 5,
        pod_name: 'sim-job-1',
        failure_reason: null,
        created_at: '2026-07-29T00:00:00Z',
        started_at: '2026-07-29T00:00:01Z',
        completed_at: null,
        ...overrides,
    };
}

export function failureRecord(overrides: Partial<FailureRecord> = {}): FailureRecord {
    return {
        id: 'failure-1',
        entity_type: 'node',
        entity_id: 'node-0',
        category: 'node_not_ready',
        root_cause_tag: 'node.kubelet_not_reporting',
        correlation_id: 'correlation-1',
        detected_at: '2026-07-30T10:00:00Z',
        resolved_at: null,
        ...overrides,
    };
}

export function capacitySummary(overrides: Partial<CapacitySummary> = {}): CapacitySummary {
    return {
        cluster_id: 'cluster-a',
        total_gpus: 32,
        unavailable_gpus: 8,
        idle_reserved_gpus: 2,
        drained_node_count: 0,
        unschedulable_node_count: 1,
        queued_job_count: 3,
        fragmentation_event_count: 167,
        ...overrides,
    };
}
