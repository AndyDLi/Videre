import { useCallback, useEffect, useState } from 'react';

import type { ApiError } from '../api/client';
import { toApiError } from '../api/client';

export interface ApiResource<DataT> {
    data: DataT | null;
    error: ApiError | null;
    isLoading: boolean;
    reload: () => void;
}

export function useApiResource<DataT>(
    fetcher: (signal: AbortSignal) => Promise<DataT>,
    pollIntervalMilliseconds?: number,
): ApiResource<DataT> {
    const [data, setData] = useState<DataT | null>(null);
    const [error, setError] = useState<ApiError | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [reloadCounter, setReloadCounter] = useState(0);

    const reload = useCallback(() => {
        setReloadCounter((counter) => counter + 1);
    }, []);

    useEffect(() => {
        const controller = new AbortController();

        const load = async (): Promise<void> => {
            try {
                setData(await fetcher(controller.signal));
                setError(null);
            } catch (caught) {
                if (!controller.signal.aborted) {
                    setError(toApiError(caught));
                }
            } finally {
                setIsLoading(false);
            }
        };

        void load();

        const timer =
            pollIntervalMilliseconds === undefined
                ? undefined
                : setInterval(() => void load(), pollIntervalMilliseconds);

        return () => {
            clearInterval(timer);
            controller.abort();
        };
    }, [fetcher, pollIntervalMilliseconds, reloadCounter]);

    return { data, error, isLoading, reload };
}
