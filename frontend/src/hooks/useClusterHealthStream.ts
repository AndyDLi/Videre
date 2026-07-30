import { useEffect, useState } from 'react';

import type { ApiError } from '../api/client';
import { toApiError } from '../api/client';
import { clusterHealthStreamUrl, listClusters } from '../api/endpoints';
import type { ClusterHealthSnapshot } from '../api/types';

const CAPPED_CLOSE_CODE = 1013;
const INITIAL_RECONNECT_DELAY_MILLISECONDS = 1_000;
const MAXIMUM_RECONNECT_DELAY_MILLISECONDS = 30_000;
const FALLBACK_POLL_INTERVAL_MILLISECONDS = 10_000;

export type ConnectionStatus = 'connecting' | 'live' | 'reconnecting' | 'capped';

interface ClusterHealthStream {
    snapshots: ClusterHealthSnapshot[] | null;
    error: ApiError | null;
    connectionStatus: ConnectionStatus;
}

export function useClusterHealthStream(): ClusterHealthStream {
    const [snapshots, setSnapshots] = useState<ClusterHealthSnapshot[] | null>(null);
    const [error, setError] = useState<ApiError | null>(null);
    const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');

    useEffect(() => {
        let isActive = true;
        let socket: WebSocket | null = null;
        let reconnectTimer: number | undefined;
        let pollTimer: number | undefined;
        let attempt = 0;

        const loadOverRest = async (): Promise<void> => {
            try {
                const clusters = await listClusters();
                if (isActive) {
                    setSnapshots(clusters);
                    setError(null);
                }
            } catch (caught) {
                if (isActive) {
                    setError(toApiError(caught));
                }
            }
        };

        const stopPolling = (): void => {
            clearInterval(pollTimer);
            pollTimer = undefined;
        };

        const startPolling = (): void => {
            pollTimer ??= window.setInterval(() => {
                void loadOverRest();
            }, FALLBACK_POLL_INTERVAL_MILLISECONDS);
        };

        const connect = (): void => {
            socket = new WebSocket(clusterHealthStreamUrl());

            socket.onopen = () => {
                if (!isActive) {
                    return;
                }
                attempt = 0;
                stopPolling();
                setConnectionStatus('live');
            };

            socket.onmessage = (event: MessageEvent<string>) => {
                if (!isActive) {
                    return;
                }
                try {
                    setSnapshots(JSON.parse(event.data) as ClusterHealthSnapshot[]);
                    setError(null);
                } catch {
                    setError(toApiError(new Error('received a malformed cluster health frame')));
                }
            };

            socket.onclose = (event: CloseEvent) => {
                if (!isActive) {
                    return;
                }
                socket = null;
                startPolling();

                if (event.code === CAPPED_CLOSE_CODE) {
                    setConnectionStatus('capped');
                    return;
                }

                setConnectionStatus('reconnecting');
                const delay = Math.min(
                    INITIAL_RECONNECT_DELAY_MILLISECONDS * 2 ** attempt,
                    MAXIMUM_RECONNECT_DELAY_MILLISECONDS,
                );
                attempt += 1;
                reconnectTimer = window.setTimeout(connect, delay);
            };
        };

        void loadOverRest();
        connect();

        return () => {
            isActive = false;
            clearTimeout(reconnectTimer);
            stopPolling();
            socket?.close();
        };
    }, []);

    return { snapshots, error, connectionStatus };
}
