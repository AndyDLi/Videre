import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { NodeDetail, NodeSummary, Page } from '../api/types';
import { NodeList } from '../components/NodeList';
import { gpu, jsonResponse, nodeSummary, requestUrl } from './fixtures';

const NODE_PAGE: Page<NodeSummary> = {
    items: [
        nodeSummary({ id: 'node-0', health_state: 'READY' }),
        nodeSummary({ id: 'node-1', health_state: 'NOT_READY' }),
    ],
    total: 2,
    limit: 50,
    offset: 0,
};

const NODE_ONE_DETAIL: NodeDetail = {
    ...nodeSummary({ id: 'node-1', health_state: 'NOT_READY' }),
    gpus: [gpu({ id: 'gpu-1-0' }), gpu({ id: 'gpu-1-1', health_state: 'THROTTLING' })],
};

function mockFetch(detailResponse: () => Response): void {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
        const url = requestUrl(input);
        if (url.includes('/nodes/node-1')) {
            return Promise.resolve(detailResponse());
        }
        return Promise.resolve(jsonResponse(NODE_PAGE));
    });
}

function renderNodeList(): void {
    render(
        <MemoryRouter>
            <NodeList />
        </MemoryRouter>,
    );
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe('NodeList', () => {
    it('links each node row to its drill-down and shows its health state', async () => {
        mockFetch(() => jsonResponse(NODE_ONE_DETAIL));
        renderNodeList();

        await waitFor(() => {
            expect(screen.getByRole('link', { name: 'node-0' })).toHaveAttribute(
                'href',
                '/nodes/node-0',
            );
        });
        expect(screen.getByRole('link', { name: 'node-1' })).toHaveAttribute(
            'href',
            '/nodes/node-1',
        );
        expect(screen.getByText('READY')).toHaveAttribute('data-tone', 'good');
        expect(screen.getByText('NOT_READY')).toHaveAttribute('data-tone', 'bad');
    });

    it('shows node capacity alongside each row', async () => {
        mockFetch(() => jsonResponse(NODE_ONE_DETAIL));
        renderNodeList();

        await waitFor(() => {
            expect(screen.getAllByText('64 cores · 512 GB · 8 GPUs')).toHaveLength(2);
        });
    });

    it('fetches GPUs only when a row is expanded, scoped to that node', async () => {
        const user = userEvent.setup();
        mockFetch(() => jsonResponse(NODE_ONE_DETAIL));
        renderNodeList();

        const toggle = await waitFor(() =>
            screen.getByRole('button', { name: 'Toggle GPUs for node-1' }),
        );
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByRole('link', { name: /^gpu-/ })).toBeNull();

        await user.click(toggle);

        expect(toggle).toHaveAttribute('aria-expanded', 'true');
        await waitFor(() => {
            expect(screen.getByRole('link', { name: /gpu-1-0/ })).toHaveAttribute(
                'href',
                '/nodes/node-1/gpus/gpu-1-0',
            );
        });
        expect(screen.getByRole('link', { name: /gpu-1-1/ })).toHaveAttribute(
            'href',
            '/nodes/node-1/gpus/gpu-1-1',
        );
        expect(screen.getByText('THROTTLING')).toHaveAttribute('data-tone', 'warning');
    });

    it('rounds GPU utilization and temperature for display', async () => {
        const user = userEvent.setup();
        mockFetch(() => jsonResponse(NODE_ONE_DETAIL));
        renderNodeList();

        await user.click(
            await waitFor(() => screen.getByRole('button', { name: 'Toggle GPUs for node-1' })),
        );

        await waitFor(() => {
            expect(screen.getAllByText('82% · 62°C')).toHaveLength(2);
        });
    });

    it('collapses an expanded row on a second click', async () => {
        const user = userEvent.setup();
        mockFetch(() => jsonResponse(NODE_ONE_DETAIL));
        renderNodeList();

        const toggle = await waitFor(() =>
            screen.getByRole('button', { name: 'Toggle GPUs for node-1' }),
        );
        await user.click(toggle);
        await waitFor(() => {
            expect(screen.getByRole('link', { name: /gpu-1-0/ })).toBeInTheDocument();
        });

        await user.click(toggle);

        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByRole('link', { name: /^gpu-/ })).toBeNull();
    });

    it('reports a failed GPU fetch without breaking the row', async () => {
        const user = userEvent.setup();
        mockFetch(() => jsonResponse({ detail: 'node not found' }, 404));
        renderNodeList();

        await user.click(
            await waitFor(() => screen.getByRole('button', { name: 'Toggle GPUs for node-1' })),
        );

        await waitFor(() => {
            expect(screen.getByText(/Could not load GPUs — node not found/)).toBeInTheDocument();
        });
        expect(screen.getByRole('link', { name: 'node-1' })).toBeInTheDocument();
    });

    it('reports a failed node list fetch', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'nodes unavailable' }, 503),
        );
        renderNodeList();

        await waitFor(() => {
            expect(screen.getByText(/nodes unavailable/)).toBeInTheDocument();
        });
    });
});
