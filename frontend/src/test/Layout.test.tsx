import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ClusterHealthSnapshot } from '../api/types';
import { Layout } from '../components/Layout';
import { jsonResponse } from './fixtures';

const HEALTHY_SNAPSHOT: ClusterHealthSnapshot = {
    cluster_id: 'cluster-1',
    cluster_name: 'Cluster One',
    generated_at: '2026-07-29T00:00:00Z',
    nodes_by_health_state: { READY: 4 },
    gpus_by_health_state: { HEALTHY: 32 },
    jobs_by_lifecycle_state: { RUNNING: 3 },
    unresolved_failure_count: 0,
};

function renderLayout(): void {
    render(
        <MemoryRouter initialEntries={['/']}>
            <Routes>
                <Route element={<Layout />}>
                    <Route path="/" element={<p>overview content</p>} />
                </Route>
            </Routes>
        </MemoryRouter>,
    );
}

describe('Layout', () => {
    beforeEach(() => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse([HEALTHY_SNAPSHOT]));
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('renders navigation for every top-level view', () => {
        renderLayout();
        expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument();
        for (const label of ['Cluster Overview', 'Failures', 'Capacity']) {
            expect(screen.getByRole('link', { name: label })).toBeInTheDocument();
        }
    });

    it('renders the routed page inside the shell', () => {
        renderLayout();
        expect(screen.getByText('overview content')).toBeInTheDocument();
    });

    it('shows overall cluster health in the header', async () => {
        renderLayout();
        await waitFor(() => {
            expect(screen.getByText('HEALTHY')).toBeInTheDocument();
        });
    });

    it('distinguishes an unreachable backend from an unavailable cache', async () => {
        vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
        renderLayout();
        await waitFor(() => {
            expect(screen.getByText('Backend unreachable')).toBeInTheDocument();
        });
    });

    it('shows cluster health unavailable when the cache is empty', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'cluster health cache is empty' }, 503),
        );
        renderLayout();
        await waitFor(() => {
            expect(screen.getByText('Cluster health unavailable')).toBeInTheDocument();
        });
    });
});
