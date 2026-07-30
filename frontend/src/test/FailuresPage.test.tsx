import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { FailureRecord, Page } from '../api/types';
import { FailuresPage } from '../pages/FailuresPage';
import { failureRecord, jsonResponse, requestUrl } from './fixtures';

function mockFailures(page: Page<FailureRecord>): string[] {
    const requestedUrls: string[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
        requestedUrls.push(requestUrl(input));
        return Promise.resolve(jsonResponse(page));
    });
    return requestedUrls;
}

function renderFailuresPage(): void {
    render(
        <MemoryRouter>
            <FailuresPage />
        </MemoryRouter>,
    );
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe('FailuresPage', () => {
    it('renders each record with its entity link, root cause tag, and timestamps', async () => {
        mockFailures({
            items: [
                failureRecord(),
                failureRecord({
                    id: 'failure-2',
                    entity_type: 'gpu',
                    entity_id: 'gpu-2-3',
                    category: 'gpu',
                    root_cause_tag: 'gpu.thermal_throttling',
                    resolved_at: '2026-07-30T10:05:00Z',
                }),
            ],
            total: 2,
            limit: 25,
            offset: 0,
        });
        renderFailuresPage();

        await waitFor(() => {
            expect(screen.getByRole('link', { name: 'node-0' })).toHaveAttribute(
                'href',
                '/nodes/node-0',
            );
        });
        expect(screen.getByRole('link', { name: 'gpu-2-3' })).toHaveAttribute(
            'href',
            '/nodes/node-2/gpus/gpu-2-3',
        );
        expect(screen.getByText('node.kubelet_not_reporting')).toBeInTheDocument();

        const records = within(screen.getByRole('list'));
        expect(records.getByText('Unresolved')).toBeInTheDocument();
        expect(records.getByText('Resolved')).toBeInTheDocument();
        expect(records.getByText(/^Detected .*· resolved /)).toBeInTheDocument();
    });

    it('sends the selected entity type, status, and time range to the backend', async () => {
        const user = userEvent.setup();
        const requestedUrls = mockFailures({ items: [], total: 0, limit: 25, offset: 0 });
        renderFailuresPage();

        await waitFor(() => {
            expect(screen.getByText('No failure records match these filters.')).toBeInTheDocument();
        });

        await user.selectOptions(screen.getByLabelText('Entity Type'), 'gpu');
        await user.selectOptions(screen.getByLabelText('Status'), 'unresolved');
        await user.selectOptions(screen.getByLabelText('Time Range'), '1');

        await waitFor(() => {
            expect(requestedUrls.at(-1)).toContain('since=');
        });
        const latest = requestedUrls.at(-1) ?? '';
        expect(latest).toContain('entity_type=gpu');
        expect(latest).toContain('resolved=false');
    });

    it('omits filters the user left on their "all" option', async () => {
        const requestedUrls = mockFailures({ items: [], total: 0, limit: 25, offset: 0 });
        renderFailuresPage();

        await waitFor(() => {
            expect(requestedUrls).toHaveLength(1);
        });
        expect(requestedUrls[0]).toContain('limit=25&offset=0');
        expect(requestedUrls[0]).not.toContain('entity_type');
        expect(requestedUrls[0]).not.toContain('resolved');
        expect(requestedUrls[0]).not.toContain('since');
    });

    it('pages forward through the server-side offsets', async () => {
        const user = userEvent.setup();
        const requestedUrls = mockFailures({
            items: [failureRecord()],
            total: 60,
            limit: 25,
            offset: 0,
        });
        renderFailuresPage();

        await waitFor(() => {
            expect(screen.getByText('Showing 1–1 of 60')).toBeInTheDocument();
        });
        expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();

        await user.click(screen.getByRole('button', { name: 'Next' }));

        await waitFor(() => {
            expect(requestedUrls.at(-1)).toContain('offset=25');
        });
    });

    it('reports a failed fetch', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'failures unavailable' }, 503),
        );
        renderFailuresPage();

        await waitFor(() => {
            expect(screen.getByText(/failures unavailable/)).toBeInTheDocument();
        });
    });
});
