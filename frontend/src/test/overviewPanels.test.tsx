import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { JobSummary, Page } from '../api/types';
import { JobList } from '../components/JobList';
import { StateCounts } from '../components/StateCounts';
import { UtilizationPanel } from '../components/UtilizationPanel';
import { jobSummary, jsonResponse } from './fixtures';

afterEach(() => {
    vi.restoreAllMocks();
});

describe('StateCounts', () => {
    it('orders states by descending count', () => {
        render(<StateCounts title="Jobs" counts={{ PENDING: 3, COMPLETED: 90, RUNNING: 12 }} />);
        const badges = screen.getAllByText(/PENDING|COMPLETED|RUNNING/);
        expect(badges.map((badge) => badge.textContent)).toEqual([
            'COMPLETED',
            'RUNNING',
            'PENDING',
        ]);
    });

    it('renders each count next to its badge', () => {
        render(<StateCounts title="Nodes" counts={{ READY: 3, NOT_READY: 1 }} />);
        expect(screen.getByText('Nodes')).toBeInTheDocument();
        expect(screen.getByText('3')).toBeInTheDocument();
        expect(screen.getByText('1')).toBeInTheDocument();
        expect(screen.getByText('NOT_READY')).toHaveAttribute('data-tone', 'bad');
    });

    it('shows an empty state when the backend reported no states', () => {
        render(<StateCounts title="GPUs" counts={{}} />);
        expect(screen.getByText('No data yet.')).toBeInTheDocument();
    });
});

describe('UtilizationPanel', () => {
    it('reports missing capacity rather than rendering a zero', () => {
        render(<UtilizationPanel utilization={null} />);
        expect(screen.getByText('No GPU capacity reported yet.')).toBeInTheDocument();
        expect(screen.queryByRole('progressbar')).toBeNull();
    });

    it('renders the percentage, the meter, and the numbers behind it', () => {
        render(
            <UtilizationPanel
                utilization={{
                    totalGpus: 32,
                    inUseGpus: 24,
                    unavailableGpus: 8,
                    idleReservedGpus: 0,
                    inUsePercentage: 75,
                }}
            />,
        );
        expect(screen.getByText('75%')).toBeInTheDocument();
        const meter = screen.getByRole('progressbar', { name: 'GPUs in use' });
        expect(meter).toHaveAttribute('aria-valuenow', '75');
        expect(meter).toHaveAttribute('aria-valuemin', '0');
        expect(meter).toHaveAttribute('aria-valuemax', '100');
        expect(screen.getByText('24 / 32')).toBeInTheDocument();
        expect(screen.getByText('8')).toBeInTheDocument();
    });
});

describe('JobList', () => {
    function mockJobs(page: Page<JobSummary>): void {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(page));
    }

    it('links each job to its drill-down with its lifecycle state', async () => {
        mockJobs({
            items: [
                jobSummary({ id: 'job-1' }),
                jobSummary({ id: 'job-2', lifecycle_state: 'PENDING' }),
            ],
            total: 2,
            limit: 10,
            offset: 0,
        });
        render(
            <MemoryRouter>
                <JobList />
            </MemoryRouter>,
        );

        await waitFor(() => {
            expect(screen.getByRole('link', { name: 'job-1' })).toHaveAttribute(
                'href',
                '/jobs/job-1',
            );
        });
        expect(screen.getByText('RUNNING')).toHaveAttribute('data-tone', 'good');
        expect(screen.getByText('PENDING')).toHaveAttribute('data-tone', 'neutral');
    });

    it('surfaces a failure reason when the job has one', async () => {
        mockJobs({
            items: [
                jobSummary({
                    id: 'job-3',
                    lifecycle_state: 'FAILED',
                    failure_reason: 'nccl_timeout',
                }),
            ],
            total: 1,
            limit: 10,
            offset: 0,
        });
        render(
            <MemoryRouter>
                <JobList />
            </MemoryRouter>,
        );

        await waitFor(() => {
            expect(screen.getByText('nccl_timeout')).toBeInTheDocument();
        });
        expect(screen.getByText('FAILED')).toHaveAttribute('data-tone', 'bad');
    });

    it('reports a failed fetch', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'jobs unavailable' }, 503),
        );
        render(
            <MemoryRouter>
                <JobList />
            </MemoryRouter>,
        );

        await waitFor(() => {
            expect(screen.getByText(/jobs unavailable/)).toBeInTheDocument();
        });
    });
});
