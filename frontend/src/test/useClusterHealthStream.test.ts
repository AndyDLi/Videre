import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ClusterHealthSnapshot } from '../api/types';
import { useClusterHealthStream } from '../hooks/useClusterHealthStream';
import { jsonResponse } from './fixtures';

const SNAPSHOT: ClusterHealthSnapshot = {
    cluster_id: 'cluster-a',
    cluster_name: 'Cluster A',
    generated_at: '2026-07-29T00:00:00Z',
    nodes_by_health_state: { READY: 4 },
    gpus_by_health_state: { HEALTHY: 32 },
    jobs_by_lifecycle_state: { RUNNING: 3 },
    unresolved_failure_count: 0,
};

class FakeWebSocket {
    static instances: FakeWebSocket[] = [];

    readonly url: string;
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent<string>) => void) | null = null;
    onclose: ((event: CloseEvent) => void) | null = null;
    closed = false;

    constructor(url: string) {
        this.url = url;
        FakeWebSocket.instances.push(this);
    }

    close(): void {
        this.closed = true;
    }

    static get latest(): FakeWebSocket {
        const socket = FakeWebSocket.instances.at(-1);
        if (socket === undefined) {
            throw new Error('no WebSocket was constructed');
        }
        return socket;
    }
}

beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse([SNAPSHOT]));
});

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('useClusterHealthStream', () => {
    it('connects to the backend cluster-health endpoint', () => {
        renderHook(() => useClusterHealthStream());
        expect(FakeWebSocket.latest.url).toBe('ws://localhost:8000/ws/cluster-health');
    });

    it('renders from the initial REST fetch before any frame arrives', async () => {
        const { result } = renderHook(() => useClusterHealthStream());
        await waitFor(() => {
            expect(result.current.snapshots).toEqual([SNAPSHOT]);
        });
        expect(result.current.connectionStatus).toBe('connecting');
    });

    it('reports live once the socket opens', async () => {
        const { result } = renderHook(() => useClusterHealthStream());
        act(() => {
            FakeWebSocket.latest.onopen?.();
        });
        await waitFor(() => {
            expect(result.current.connectionStatus).toBe('live');
        });
    });

    it('replaces state from each pushed frame', async () => {
        const { result } = renderHook(() => useClusterHealthStream());
        const pushed = { ...SNAPSHOT, unresolved_failure_count: 7 };
        act(() => {
            FakeWebSocket.latest.onopen?.();
            FakeWebSocket.latest.onmessage?.(
                new MessageEvent('message', { data: JSON.stringify([pushed]) }),
            );
        });
        await waitFor(() => {
            expect(result.current.snapshots).toEqual([pushed]);
        });
    });

    it('surfaces an error for a malformed frame without losing prior data', async () => {
        const { result } = renderHook(() => useClusterHealthStream());
        await waitFor(() => {
            expect(result.current.snapshots).toEqual([SNAPSHOT]);
        });
        act(() => {
            FakeWebSocket.latest.onopen?.();
            FakeWebSocket.latest.onmessage?.(new MessageEvent('message', { data: 'not json' }));
        });
        await waitFor(() => {
            expect(result.current.error).not.toBeNull();
        });
        expect(result.current.snapshots).toEqual([SNAPSHOT]);
    });

    it('reconnects with exponential backoff after an unexpected close', () => {
        vi.useFakeTimers();
        renderHook(() => useClusterHealthStream());

        act(() => {
            FakeWebSocket.latest.onclose?.(new CloseEvent('close', { code: 1006 }));
        });
        expect(FakeWebSocket.instances).toHaveLength(1);

        act(() => {
            vi.advanceTimersByTime(1_000);
        });
        expect(FakeWebSocket.instances).toHaveLength(2);

        act(() => {
            FakeWebSocket.latest.onclose?.(new CloseEvent('close', { code: 1006 }));
            vi.advanceTimersByTime(1_999);
        });
        expect(FakeWebSocket.instances).toHaveLength(2);

        act(() => {
            vi.advanceTimersByTime(1);
        });
        expect(FakeWebSocket.instances).toHaveLength(3);
    });

    it('resets the backoff after a successful reconnect', () => {
        vi.useFakeTimers();
        renderHook(() => useClusterHealthStream());

        act(() => {
            FakeWebSocket.latest.onclose?.(new CloseEvent('close', { code: 1006 }));
            vi.advanceTimersByTime(1_000);
        });
        act(() => {
            FakeWebSocket.latest.onopen?.();
            FakeWebSocket.latest.onclose?.(new CloseEvent('close', { code: 1006 }));
            vi.advanceTimersByTime(1_000);
        });

        expect(FakeWebSocket.instances).toHaveLength(3);
    });

    it('stops reconnecting when the per-IP cap closes the socket with 1013', () => {
        vi.useFakeTimers();
        const { result } = renderHook(() => useClusterHealthStream());

        act(() => {
            FakeWebSocket.latest.onclose?.(new CloseEvent('close', { code: 1013 }));
            vi.advanceTimersByTime(60_000);
        });

        expect(result.current.connectionStatus).toBe('capped');
        expect(FakeWebSocket.instances).toHaveLength(1);
    });

    it('polls REST while disconnected and stops once reconnected', () => {
        vi.useFakeTimers();
        renderHook(() => useClusterHealthStream());
        const fetchMock = vi.mocked(globalThis.fetch);
        const callsAfterMount = fetchMock.mock.calls.length;

        act(() => {
            FakeWebSocket.latest.onclose?.(new CloseEvent('close', { code: 1006 }));
            vi.advanceTimersByTime(10_000);
        });
        const callsWhileDisconnected = fetchMock.mock.calls.length;
        expect(callsWhileDisconnected).toBeGreaterThan(callsAfterMount);

        act(() => {
            vi.advanceTimersByTime(1_000);
            FakeWebSocket.latest.onopen?.();
        });
        act(() => {
            vi.advanceTimersByTime(30_000);
        });
        expect(fetchMock.mock.calls.length).toBe(callsWhileDisconnected);
    });

    it('closes the socket on unmount', () => {
        const { unmount } = renderHook(() => useClusterHealthStream());
        const socket = FakeWebSocket.latest;
        unmount();
        expect(socket.closed).toBe(true);
    });
});
