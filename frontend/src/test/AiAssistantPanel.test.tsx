import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AnalysisResponse } from '../api/types';
import { AiAssistantPanel } from '../components/AiAssistantPanel';
import { jsonResponse, requestUrl } from './fixtures';

const ANALYSIS: AnalysisResponse = {
    entity_type: 'node',
    entity_id: 'node-0',
    summary: 'Node node-0 is NOT_READY because of disk pressure and image pull failures.',
    next_steps: ['Investigate disk space usage on node-0.', 'Check the image registry.'],
    from_cache: false,
    cache_age_seconds: null,
};

function renderPanel(): void {
    render(<AiAssistantPanel entityType="node" entityId="node-0" onClose={vi.fn()} />);
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe('AiAssistantPanel', () => {
    it('renders the summary and next steps as readable text, not raw JSON', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(ANALYSIS));
        renderPanel();

        expect(screen.getByRole('status')).toHaveTextContent('Analyzing this node…');

        await waitFor(() => {
            expect(screen.getByText(ANALYSIS.summary)).toBeInTheDocument();
        });
        const steps = screen.getAllByRole('listitem');
        expect(steps.map((step) => step.textContent)).toEqual(ANALYSIS.next_steps);
        expect(screen.queryByText(/next_steps|from_cache/)).toBeNull();
    });

    it('posts the entity to the analyze endpoint', async () => {
        let url = '';
        let options: RequestInit | undefined;
        vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
            url = requestUrl(input);
            options = init;
            return Promise.resolve(
                jsonResponse({ ...ANALYSIS, entity_type: 'gpu', entity_id: 'gpu-1-1' }),
            );
        });
        render(<AiAssistantPanel entityType="gpu" entityId="gpu-1-1" onClose={vi.fn()} />);

        await waitFor(() => {
            expect(url).toContain('/ai/analyze');
        });
        expect(options?.method).toBe('POST');
        expect(options?.body).toBe(JSON.stringify({ entity_type: 'gpu', entity_id: 'gpu-1-1' }));
    });

    it('marks a cached analysis with its age', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ ...ANALYSIS, from_cache: true, cache_age_seconds: 184 }),
        );
        renderPanel();

        await waitFor(() => {
            expect(screen.getByText('Cached 3 minutes ago')).toBeInTheDocument();
        });
    });

    it('says nothing about caching for a fresh analysis', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(ANALYSIS));
        renderPanel();

        await waitFor(() => {
            expect(screen.getByText(ANALYSIS.summary)).toBeInTheDocument();
        });
        expect(screen.queryByText(/Cached/)).toBeNull();
    });

    it('turns a rate-limit rejection into a wait time, not a generic error', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'AI analysis is rate limited.' }, 429, {
                'Retry-After': '300',
            }),
        );
        renderPanel();

        await waitFor(() => {
            expect(
                screen.getByText('AI analysis is rate limited. Try again in 5 minutes.'),
            ).toBeInTheDocument();
        });
    });

    it('falls back to the provider message when no Retry-After is sent', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'AI analysis is rate limited. Please try again shortly.' }, 429),
        );
        renderPanel();

        await waitFor(() => {
            expect(
                screen.getByText('AI analysis is rate limited. Please try again shortly.'),
            ).toBeInTheDocument();
        });
    });

    it('distinguishes a missing entity from a general failure', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'node not found' }, 404),
        );
        renderPanel();

        await waitFor(() => {
            expect(
                screen.getByText('This node no longer exists, so there is nothing to analyze.'),
            ).toBeInTheDocument();
        });
    });

    it('shows the backend reason when the assistant is unavailable', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse(
                { detail: 'The AI assistant is temporarily unavailable. Please try again later.' },
                503,
            ),
        );
        renderPanel();

        await waitFor(() => {
            expect(
                screen.getByText(
                    'The AI assistant is temporarily unavailable. Please try again later.',
                ),
            ).toBeInTheDocument();
        });
    });
});
