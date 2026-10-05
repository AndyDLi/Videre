export type NodeHealthState = 'READY' | 'NOT_READY' | 'DRAINING' | 'CORDONED';

export type GpuHealthState = 'HEALTHY' | 'THROTTLING' | 'DEGRADED' | 'FAILED';

export type JobLifecycleState = 'PENDING' | 'RUNNING' | 'FAILED' | 'COMPLETED';

export type EntityType = 'node' | 'gpu' | 'job';

export type FailureCategory = 'node_not_ready' | 'gpu' | 'job' | 'capacity';

export interface Page<ItemT> {
    items: ItemT[];
    total: number;
    limit: number;
    offset: number;
}

export interface HealthResponse {
    status: 'healthy' | 'degraded';
    checks: {
        postgres: boolean;
        redis: boolean;
    };
}

export interface ClusterHealthSnapshot {
    cluster_id: string;
    cluster_name: string;
    generated_at: string;
    nodes_by_health_state: Partial<Record<NodeHealthState, number>>;
    gpus_by_health_state: Partial<Record<GpuHealthState, number>>;
    jobs_by_lifecycle_state: Partial<Record<JobLifecycleState, number>>;
    unresolved_failure_count: number;
}

export interface NodeSummary {
    id: string;
    cluster_id: string;
    cpu_cores: number;
    memory_gb: number;
    gpu_count: number;
    health_state: NodeHealthState;
    updated_at: string;
}

export interface Gpu {
    id: string;
    node_id: string;
    utilization_percentage: number;
    temperature_celsius: number;
    memory_used_mb: number;
    memory_total_mb: number;
    ecc_correctable_count: number;
    ecc_uncorrectable_count: number;
    xid_error_count: number;
    health_state: GpuHealthState;
    last_updated_at: string;
}

export interface NodeDetail extends NodeSummary {
    gpus: Gpu[];
}

export interface JobSummary {
    id: string;
    cluster_id: string;
    lifecycle_state: JobLifecycleState;
    requested_cpu_cores: number;
    requested_memory_gb: number;
    requested_gpu_count: number;
    priority: number;
    pod_name: string | null;
    failure_reason: string | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
}

export interface JobDetail extends JobSummary {
    assigned_node_ids: string[];
}

export interface FailureRecord {
    id: string;
    entity_type: EntityType;
    entity_id: string;
    category: FailureCategory;
    root_cause_tag: string;
    correlation_id: string;
    detected_at: string;
    resolved_at: string | null;
}

export interface CapacitySummary {
    cluster_id: string;
    total_gpus: number;
    unavailable_gpus: number;
    degraded_gpus: number;
    idle_gpus: number;
    active_gpus: number;
    drained_node_count: number;
    unschedulable_node_count: number;
    queued_job_count: number;
    queueing_delay_event_count: number;
}

export interface AnalysisRequest {
    entity_type: EntityType;
    entity_id: string;
}

export interface AnalysisResponse {
    entity_type: EntityType;
    entity_id: string;
    summary: string;
    next_steps: string[];
    from_cache: boolean;
    cache_age_seconds: number | null;
}
