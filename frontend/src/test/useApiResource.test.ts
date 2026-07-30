import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ApiError } from '../api/client';
import { useApiResource } from '../hooks/useApiResource';

type Fetcher = (signal: AbortSignal) => Promise<string>;

describe('useApiResource', () => {
    it('drops the previous resource as soon as the fetcher changes', async () => {
        const loadNodeOne: Fetcher = () => Promise.resolve('node-1');
        const loadMissingNode: Fetcher = () =>
            Promise.reject(new ApiError(404, 'node not found', null));

        const { result, rerender } = renderHook(({ fetcher }) => useApiResource(fetcher), {
            initialProps: { fetcher: loadNodeOne },
        });
        await waitFor(() => {
            expect(result.current.data).toBe('node-1');
        });

        rerender({ fetcher: loadMissingNode });

        expect(result.current.data).toBeNull();
        expect(result.current.isLoading).toBe(true);
        await waitFor(() => {
            expect(result.current.error?.status).toBe(404);
        });
        expect(result.current.data).toBeNull();
    });

    it('lets a superseded request write nothing, even once it settles', async () => {
        const loadNodeOne: Fetcher = (signal) =>
            new Promise((_, reject) => {
                signal.addEventListener('abort', () => {
                    reject(new DOMException('aborted', 'AbortError'));
                });
            });
        let resolveNodeTwo = (value: string): void => void value;
        const loadNodeTwo: Fetcher = () =>
            new Promise<string>((resolve) => {
                resolveNodeTwo = resolve;
            });

        const { result, rerender } = renderHook(({ fetcher }) => useApiResource(fetcher), {
            initialProps: { fetcher: loadNodeOne },
        });
        rerender({ fetcher: loadNodeTwo });

        await new Promise((resolve) => setTimeout(resolve, 20));
        expect(result.current.isLoading).toBe(true);
        expect(result.current.error).toBeNull();
        expect(result.current.data).toBeNull();

        resolveNodeTwo('node-2');
        await waitFor(() => {
            expect(result.current.data).toBe('node-2');
        });
        expect(result.current.isLoading).toBe(false);
    });

    it('ignores a stale success that arrives after the fetcher changed', async () => {
        let resolveNodeOne = (value: string): void => void value;
        const loadNodeOne: Fetcher = () =>
            new Promise<string>((resolve) => {
                resolveNodeOne = resolve;
            });
        const loadNodeTwo: Fetcher = () => Promise.resolve('node-2');

        const { result, rerender } = renderHook(({ fetcher }) => useApiResource(fetcher), {
            initialProps: { fetcher: loadNodeOne },
        });
        rerender({ fetcher: loadNodeTwo });
        await waitFor(() => {
            expect(result.current.data).toBe('node-2');
        });

        resolveNodeOne('node-1');
        await new Promise((resolve) => setTimeout(resolve, 20));

        expect(result.current.data).toBe('node-2');
    });

    it('keeps the last good data when a later poll fails', async () => {
        let attempt = 0;
        const flakyFetcher: Fetcher = () => {
            attempt += 1;
            return attempt === 1
                ? Promise.resolve('nodes')
                : Promise.reject(new ApiError(503, 'nodes unavailable', null));
        };

        const { result } = renderHook(() => useApiResource(flakyFetcher, 20));
        await waitFor(() => {
            expect(result.current.data).toBe('nodes');
        });

        await waitFor(() => {
            expect(result.current.error?.status).toBe(503);
        });
        expect(result.current.data).toBe('nodes');
    });
});
