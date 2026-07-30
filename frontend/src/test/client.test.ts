import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, get, post, toApiError } from '../api/client';
import { apiBaseUrl, restUrl, webSocketUrl } from '../api/config';
import { listFailures } from '../api/endpoints';

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json', ...headers },
    });
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe('url construction', () => {
    it('reads the base URL from the environment without a trailing slash', () => {
        expect(apiBaseUrl).toBe('http://localhost:8000');
    });

    it('builds absolute REST urls', () => {
        expect(restUrl('/healthz')).toBe('http://localhost:8000/healthz');
    });

    it('converts the scheme for WebSocket urls', () => {
        expect(webSocketUrl('/ws/cluster-health')).toBe('ws://localhost:8000/ws/cluster-health');
    });
});

describe('toApiError', () => {
    it('passes an ApiError through unchanged', () => {
        const original = new ApiError(404, 'node not found', null);
        expect(toApiError(original)).toBe(original);
    });

    it('wraps anything else as a network failure', () => {
        const wrapped = toApiError(new TypeError('Failed to fetch'));
        expect(wrapped.status).toBe(0);
        expect(wrapped.isNetworkFailure).toBe(true);
        expect(wrapped.detail).toBe('Failed to fetch');
    });
});

describe('get', () => {
    it('returns the parsed body on success', async () => {
        const fetchMock = vi
            .spyOn(globalThis, 'fetch')
            .mockResolvedValue(jsonResponse({ status: 'healthy' }));

        await expect(get<{ status: string }>('/healthz')).resolves.toEqual({ status: 'healthy' });
        expect(fetchMock).toHaveBeenCalledWith(
            'http://localhost:8000/healthz',
            expect.objectContaining({ method: 'GET' }),
        );
    });

    it('omits undefined query parameters and serializes the rest', async () => {
        const fetchMock = vi
            .spyOn(globalThis, 'fetch')
            .mockResolvedValue(jsonResponse({ items: [], total: 0, limit: 50, offset: 0 }));

        await listFailures({ entity_type: 'gpu', resolved: false, limit: 25, offset: undefined });

        expect(fetchMock.mock.calls[0]?.[0]).toBe(
            'http://localhost:8000/failures?entity_type=gpu&resolved=false&limit=25',
        );
    });

    it('raises ApiError carrying the backend detail for a 404', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'node not found' }, 404),
        );

        const error = (await get('/nodes/missing').catch((caught: unknown) => caught)) as ApiError;

        expect(error).toBeInstanceOf(ApiError);
        expect(error.status).toBe(404);
        expect(error.detail).toBe('node not found');
        expect(error.retryAfterSeconds).toBeNull();
    });

    it('reports the status when the body has no string detail and no reason phrase', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: [{ msg: 'too large' }] }, 422),
        );

        const error = (await get('/nodes').catch((caught: unknown) => caught)) as ApiError;

        expect(error.status).toBe(422);
        expect(error.detail).toBe('request failed with status 422');
    });

    it('prefers the reason phrase over the status when one is present', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            new Response(null, { status: 503, statusText: 'Service Unavailable' }),
        );

        const error = (await get('/clusters').catch((caught: unknown) => caught)) as ApiError;

        expect(error.detail).toBe('Service Unavailable');
    });

    it('raises a network failure when the request never reaches the backend', async () => {
        vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));

        const error = (await get('/healthz').catch((caught: unknown) => caught)) as ApiError;

        expect(error.isNetworkFailure).toBe(true);
    });
});

describe('post', () => {
    it('sends a JSON body and a JSON content type', async () => {
        const fetchMock = vi
            .spyOn(globalThis, 'fetch')
            .mockResolvedValue(jsonResponse({ summary: 'ok' }));

        await post('/ai/analyze', { entity_type: 'gpu', entity_id: 'gpu-1-2' });

        expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{"entity_type":"gpu","entity_id":"gpu-1-2"}',
        });
    });

    it('exposes Retry-After from a 429 so the caller can say when to retry', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            jsonResponse({ detail: 'rate limited' }, 429, { 'Retry-After': '72260' }),
        );

        const error = (await post('/ai/analyze', {}).catch(
            (caught: unknown) => caught,
        )) as ApiError;

        expect(error.status).toBe(429);
        expect(error.retryAfterSeconds).toBe(72260);
    });
});
