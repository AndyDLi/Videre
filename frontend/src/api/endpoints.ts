import { get, post } from './client';
import { webSocketUrl } from './config';
import type {
    AnalysisRequest,
    AnalysisResponse,
    CapacitySummary,
    ClusterHealthSnapshot,
    EntityType,
    FailureRecord,
    HealthResponse,
    JobDetail,
    JobLifecycleState,
    JobSummary,
    NodeDetail,
    NodeHealthState,
    NodeSummary,
    Page,
} from './types';

export interface PaginationParameters {
    limit?: number;
    offset?: number;
}

export interface NodeListParameters extends PaginationParameters {
    cluster_id?: string;
    health_state?: NodeHealthState;
}

export interface JobListParameters extends PaginationParameters {
    cluster_id?: string;
    lifecycle_state?: JobLifecycleState;
}

export interface FailureListParameters extends PaginationParameters {
    entity_type?: EntityType;
    entity_id?: string;
    resolved?: boolean;
    since?: string;
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    return get<HealthResponse>('/healthz', undefined, signal);
}

export function listClusters(signal?: AbortSignal): Promise<ClusterHealthSnapshot[]> {
    return get<ClusterHealthSnapshot[]>('/clusters', undefined, signal);
}

export function getCluster(
    clusterId: string,
    signal?: AbortSignal,
): Promise<ClusterHealthSnapshot> {
    return get<ClusterHealthSnapshot>(
        `/clusters/${encodeURIComponent(clusterId)}`,
        undefined,
        signal,
    );
}

export function listNodes(
    parameters: NodeListParameters = {},
    signal?: AbortSignal,
): Promise<Page<NodeSummary>> {
    return get<Page<NodeSummary>>('/nodes', { ...parameters }, signal);
}

export function getNode(nodeId: string, signal?: AbortSignal): Promise<NodeDetail> {
    return get<NodeDetail>(`/nodes/${encodeURIComponent(nodeId)}`, undefined, signal);
}

export function listJobs(
    parameters: JobListParameters = {},
    signal?: AbortSignal,
): Promise<Page<JobSummary>> {
    return get<Page<JobSummary>>('/jobs', { ...parameters }, signal);
}

export function getJob(jobId: string, signal?: AbortSignal): Promise<JobDetail> {
    return get<JobDetail>(`/jobs/${encodeURIComponent(jobId)}`, undefined, signal);
}

export function listFailures(
    parameters: FailureListParameters = {},
    signal?: AbortSignal,
): Promise<Page<FailureRecord>> {
    return get<Page<FailureRecord>>('/failures', { ...parameters }, signal);
}

export function getCapacity(signal?: AbortSignal): Promise<CapacitySummary[]> {
    return get<CapacitySummary[]>('/capacity', undefined, signal);
}

export function analyzeEntity(
    body: AnalysisRequest,
    signal?: AbortSignal,
): Promise<AnalysisResponse> {
    return post<AnalysisResponse>('/ai/analyze', body, signal);
}

export function clusterHealthStreamUrl(): string {
    return webSocketUrl('/ws/cluster-health');
}
