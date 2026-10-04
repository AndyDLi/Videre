import { useEffect, useState } from 'react';

import type { ApiError } from '../api/client';
import { toApiError } from '../api/client';
import { clusterHealthStreamUrl, listClusters } from '../api/endpoints';
import type { ClusterHealthSnapshot } from '../api/types';

const CAPPED_CLOSE_CODE = 1013;
const INITIAL_RECONNECT_DELAY_MILLISECONDS = 1_000;
const MAXIMUM_RECONNECT_DELAY_MILLISECONDS = 30_000;
const FALLBACK_POLL_INTERVAL_MILLISECONDS = 10_000;
const STALE_AFTER_MILLISECONDS = 20_000;

export type ConnectionStatus = 'connecting' | 'live' | 'reconnecting' | 'capped';

function isCountMap(value: unknown): boolean {
    return (
        typeof value === 'object' &&
        value !== null &&
        !Array.isArray(value) &&
        Object.values(value).every(
            (count: unknown) => typeof count === 'number' && Number.isInteger(count) && count >= 0,
        )
    );
}

interface ClusterHealthStream {
    snapshots: ClusterHealthSnapshot[] | null;
    error: ApiError | null;
    connectionStatus: ConnectionStatus;
    ageSeconds: number | null;
    isStale: boolean;
}

export function useClusterHealthStream(): ClusterHealthStream {
    const [snapshots, setSnapshots] = useState<ClusterHealthSnapshot[] | null>(null);
    const [error, setError] = useState<ApiError | null>(null);
    const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
    const [now, setNow] = useState(Date.now);

    useEffect(() => {
        let isActive = true;
        let socket: WebSocket | null = null;
        let reconnectTimer: number | undefined;
        let pollTimer: number | undefined;
        let attempt = 0;
        const ageTimer = window.setInterval(() => setNow(Date.now()), 1_000);

        const acceptSnapshots = (data: unknown): void => {
            if (
                !Array.isArray(data) ||
                data.length === 0 ||
                data.some(
                    (snapshot: Partial<ClusterHealthSnapshot> | null) =>
                        typeof snapshot !== 'object' ||
                        snapshot === null ||
                        typeof snapshot.cluster_id !== 'string' ||
                        typeof snapshot.cluster_name !== 'string' ||
                        typeof snapshot.generated_at !== 'string' ||
                        !Number.isFinite(Date.parse(snapshot.generated_at)) ||
                        !isCountMap(snapshot.nodes_by_health_state) ||
                        !isCountMap(snapshot.gpus_by_health_state) ||
                        !isCountMap(snapshot.jobs_by_lifecycle_state) ||
                        typeof snapshot.unresolved_failure_count !== 'number' ||
                        !Number.isInteger(snapshot.unresolved_failure_count) ||
                        snapshot.unresolved_failure_count < 0,
                )
            ) {
                throw new Error('cluster health snapshots are missing or malformed');
            }
            setSnapshots(data as ClusterHealthSnapshot[]);
            setNow(Date.now());
            setError(null);
        };

        const loadOverRest = async (): Promise<void> => {
            try {
                const clusters = await listClusters();
                if (isActive) {
                    acceptSnapshots(clusters);
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
                    acceptSnapshots(JSON.parse(event.data));
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
            clearInterval(ageTimer);
            stopPolling();
            socket?.close();
        };
    }, []);

    const ageMilliseconds =
        snapshots === null
            ? null
            : Math.max(
                  0,
                  now - Math.min(...snapshots.map((snapshot) => Date.parse(snapshot.generated_at))),
              );

    return {
        snapshots,
        error,
        connectionStatus,
        ageSeconds: ageMilliseconds === null ? null : Math.floor(ageMilliseconds / 1_000),
        isStale: ageMilliseconds !== null && ageMilliseconds >= STALE_AFTER_MILLISECONDS,
    };
}
