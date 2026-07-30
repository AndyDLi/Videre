import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { CapacitySummary, NodeSummary } from '../api/types';
import { CapacityPage } from '../pages/CapacityPage';
import { capacitySummary, jsonResponse, nodeSummary, requestUrl } from './fixtures';

function mockCapacity(summaries: CapacitySummary[], nodes: NodeSummary[]): void {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
        if (requestUrl(input).includes('/capacity')) {
            return Promise.resolve(jsonResponse(summaries));
        }
        return Promise.resolve(
            jsonResponse({ items: nodes, total: nodes.length, limit: 50, offset: 0 }),
        );
    });
}

function renderCapacityPage(): void {
    render(
        <MemoryRouter>
            <CapacityPage />
        </MemoryRouter>,
    );
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe('CapacityPage', () => {
    it('ranks the bottlenecks by count, highest impact first', async () => {
        mockCapacity([capacitySummary()], []);
        renderCapacityPage();

        await waitFor(() => {
            expect(screen.getByText('Fragmentation Events')).toBeInTheDocument();
        });

        const expectedOrder = [
            'Fragmentation Events',
            'Unavailable GPUs',
            'Queued Jobs',
            'Idle but Reserved GPUs',
            'Unschedulable Nodes',
            'Drained Nodes',
        ];
        const renderedOrder = screen
            .getAllByRole('listitem')
            .map((item) => expectedOrder.find((label) => item.textContent?.includes(label)));
        expect(renderedOrder).toEqual(expectedOrder);
        expect(screen.getByText('167')).toBeInTheDocument();
    });

    it('links the nodes costing capacity to their drill-downs', async () => {
        mockCapacity(
            [capacitySummary()],
            [
                nodeSummary({ id: 'node-0', health_state: 'NOT_READY' }),
                nodeSummary({ id: 'node-1', health_state: 'READY' }),
                nodeSummary({ id: 'node-2', health_state: 'DRAINING' }),
            ],
        );
        renderCapacityPage();

        await waitFor(() => {
            expect(screen.getByRole('link', { name: 'node-0' })).toHaveAttribute(
                'href',
                '/nodes/node-0',
            );
        });
        expect(screen.getByRole('link', { name: 'node-2' })).toBeInTheDocument();
        expect(screen.queryByRole('link', { name: 'node-1' })).toBeNull();
        expect(screen.getByText('NOT_READY')).toHaveAttribute('data-tone', 'bad');
    });

    it('says so when no node is costing capacity', async () => {
        mockCapacity([capacitySummary()], [nodeSummary({ health_state: 'READY' })]);
        renderCapacityPage();

        await waitFor(() => {
            expect(screen.getByText('Every node is READY.')).toBeInTheDocument();
        });
    });

    it('reports a failed fetch', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'capacity unavailable' }, 503),
        );
        renderCapacityPage();

        await waitFor(() => {
            expect(screen.getByText(/capacity unavailable/)).toBeInTheDocument();
        });
    });
});
