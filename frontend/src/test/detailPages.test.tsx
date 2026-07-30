import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AnalysisResponse, JobDetail, NodeDetail } from '../api/types';
import { GpuDetailPage } from '../pages/GpuDetailPage';
import { JobDetailPage } from '../pages/JobDetailPage';
import { NodeDetailPage } from '../pages/NodeDetailPage';
import { failureRecord, gpu, jobSummary, jsonResponse, nodeSummary, requestUrl } from './fixtures';

const NODE_ONE: NodeDetail = {
    ...nodeSummary({ id: 'node-1', health_state: 'NOT_READY' }),
    gpus: [
        gpu({ id: 'gpu-1-0', utilization_percentage: 82.4, temperature_celsius: 61.7 }),
        gpu({ id: 'gpu-1-1', health_state: 'THROTTLING', temperature_celsius: 91.2 }),
    ],
};

const JOB_ONE: JobDetail = {
    ...jobSummary({ id: 'job-1', lifecycle_state: 'FAILED', failure_reason: 'oom_kill' }),
    assigned_node_ids: ['node-1'],
};

const ANALYSIS: AnalysisResponse = {
    entity_type: 'node',
    entity_id: 'node-1',
    summary: 'Node node-1 is degraded.',
    next_steps: ['Check the kubelet.'],
    from_cache: false,
    cache_age_seconds: null,
};

function mockDetail(detail: NodeDetail | JobDetail | null, failures = [failureRecord()]): void {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
        const url = requestUrl(input);
        if (url.includes('/ai/analyze')) {
            return Promise.resolve(jsonResponse(ANALYSIS));
        }
        if (url.includes('/failures')) {
            return Promise.resolve(
                jsonResponse({ items: failures, total: failures.length, limit: 10, offset: 0 }),
            );
        }
        if (detail === null) {
            return Promise.resolve(jsonResponse({ detail: 'node not found' }, 404));
        }
        return Promise.resolve(jsonResponse(detail));
    });
}

function renderAt(path: string, route: string, element: React.ReactElement): void {
    render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path={route} element={element} />
            </Routes>
        </MemoryRouter>,
    );
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe('NodeDetailPage', () => {
    it('shows the node state, its GPUs, and its Grafana panels', async () => {
        mockDetail(NODE_ONE);
        renderAt('/nodes/node-1', '/nodes/:nodeId', <NodeDetailPage />);

        await waitFor(() => {
            expect(screen.getByRole('heading', { name: 'Node node-1' })).toBeInTheDocument();
        });
        expect(screen.getByText('512 GB')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /gpu-1-0/ })).toHaveAttribute(
            'href',
            '/nodes/node-1/gpus/gpu-1-0',
        );

        const utilization = screen.getByTitle('GPU utilization on node-1');
        expect(utilization).toHaveAttribute(
            'src',
            expect.stringContaining('panelId=2&var-node=node-1'),
        );
        expect(screen.getByTitle('Health state of node-1')).toBeInTheDocument();
        expect(screen.getByTitle('GPU temperature on node-1')).toBeInTheDocument();
    });

    it('lists the failure records for this node', async () => {
        mockDetail(NODE_ONE);
        renderAt('/nodes/node-1', '/nodes/:nodeId', <NodeDetailPage />);

        await waitFor(() => {
            expect(screen.getByText('node.kubelet_not_reporting')).toBeInTheDocument();
        });
    });

    it('shows a not-found state instead of a broken page', async () => {
        mockDetail(null);
        renderAt('/nodes/node-99', '/nodes/:nodeId', <NodeDetailPage />);

        await waitFor(() => {
            expect(screen.getByText('No node with the id node-99 exists.')).toBeInTheDocument();
        });
        expect(
            screen.getByRole('link', { name: 'Back to the Cluster Overview' }),
        ).toBeInTheDocument();
    });

    it('opens and closes the AI assistant for this node', async () => {
        const user = userEvent.setup();
        mockDetail(NODE_ONE);
        renderAt('/nodes/node-1', '/nodes/:nodeId', <NodeDetailPage />);

        const trigger = await waitFor(() =>
            screen.getByRole('button', { name: 'Ask the AI Assistant' }),
        );
        expect(screen.queryByRole('region', { name: /AI analysis/ })).toBeNull();

        await user.click(trigger);
        expect(
            screen.getByRole('region', { name: 'AI analysis of node node-1' }),
        ).toBeInTheDocument();

        await user.click(screen.getByRole('button', { name: 'Close' }));
        expect(screen.queryByRole('region', { name: /AI analysis/ })).toBeNull();
    });
});

describe('GpuDetailPage', () => {
    it('shows the GPU named in the route, not the first on the node', async () => {
        mockDetail(NODE_ONE);
        renderAt('/nodes/node-1/gpus/gpu-1-1', '/nodes/:nodeId/gpus/:gpuId', <GpuDetailPage />);

        await waitFor(() => {
            expect(screen.getByRole('heading', { name: 'GPU gpu-1-1' })).toBeInTheDocument();
        });
        expect(screen.getByText('91°C')).toBeInTheDocument();
        expect(screen.getByText('THROTTLING')).toHaveAttribute('data-tone', 'warning');
        expect(screen.getByTitle('Utilization of gpu-1-1')).toHaveAttribute(
            'src',
            expect.stringContaining('var-gpu=gpu-1-1'),
        );
        expect(screen.getByRole('link', { name: 'node-1' })).toHaveAttribute(
            'href',
            '/nodes/node-1',
        );
    });

    it('reports a GPU id that is not on this node', async () => {
        mockDetail(NODE_ONE);
        renderAt('/nodes/node-1/gpus/gpu-9-9', '/nodes/:nodeId/gpus/:gpuId', <GpuDetailPage />);

        await waitFor(() => {
            expect(
                screen.getByText('Node node-1 has no GPU with the id gpu-9-9.'),
            ).toBeInTheDocument();
        });
    });
});

describe('JobDetailPage', () => {
    it('shows the job state, its assigned node, and its node GPU panel', async () => {
        mockDetail(JOB_ONE, []);
        renderAt('/jobs/job-1', '/jobs/:jobId', <JobDetailPage />);

        await waitFor(() => {
            expect(screen.getByRole('heading', { name: 'Job job-1' })).toBeInTheDocument();
        });
        expect(screen.getByText('FAILED')).toHaveAttribute('data-tone', 'bad');
        expect(screen.getByText('oom_kill')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'node-1' })).toHaveAttribute(
            'href',
            '/nodes/node-1',
        );
        expect(screen.getByTitle('GPU utilization on node-1')).toBeInTheDocument();
        await waitFor(() => {
            expect(screen.getByText('No failures recorded for this entity.')).toBeInTheDocument();
        });
    });

    it('omits the node panel for a job that has no placement yet', async () => {
        mockDetail({ ...JOB_ONE, lifecycle_state: 'PENDING', assigned_node_ids: [] }, []);
        renderAt('/jobs/job-1', '/jobs/:jobId', <JobDetailPage />);

        await waitFor(() => {
            expect(
                screen.getByText('This job has not been placed on a node yet.'),
            ).toBeInTheDocument();
        });
        expect(screen.queryByTitle(/GPU utilization/)).toBeNull();
    });

    it('shows a not-found state instead of a broken page', async () => {
        mockDetail(null);
        renderAt('/jobs/job-99', '/jobs/:jobId', <JobDetailPage />);

        await waitFor(() => {
            expect(screen.getByText('No job with the id job-99 exists.')).toBeInTheDocument();
        });
    });
});
