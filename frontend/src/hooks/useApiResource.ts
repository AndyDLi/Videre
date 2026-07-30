import { useEffect, useState } from 'react';

import type { ApiError } from '../api/client';
import { toApiError } from '../api/client';

type Fetcher<DataT> = (signal: AbortSignal) => Promise<DataT>;

interface ApiResource<DataT> {
    data: DataT | null;
    error: ApiError | null;
    isLoading: boolean;
}

export function useApiResource<DataT>(
    fetcher: Fetcher<DataT>,
    pollIntervalMilliseconds?: number,
): ApiResource<DataT> {
    const [data, setData] = useState<DataT | null>(null);
    const [error, setError] = useState<ApiError | null>(null);
    const [isLoading, setIsLoading] = useState(true);

    const [previousFetcher, setPreviousFetcher] = useState(() => fetcher);
    if (previousFetcher !== fetcher) {
        setPreviousFetcher(() => fetcher);
        setData(null);
        setError(null);
        setIsLoading(true);
    }

    useEffect(() => {
        const controller = new AbortController();
        let isCurrent = true;

        const load = async (): Promise<void> => {
            try {
                const loaded = await fetcher(controller.signal);
                if (isCurrent) {
                    setData(loaded);
                    setError(null);
                    setIsLoading(false);
                }
            } catch (caught) {
                if (isCurrent) {
                    setError(toApiError(caught));
                    setIsLoading(false);
                }
            }
        };

        void load();

        const timer =
            pollIntervalMilliseconds === undefined
                ? undefined
                : setInterval(() => void load(), pollIntervalMilliseconds);

        return () => {
            isCurrent = false;
            clearInterval(timer);
            controller.abort();
        };
    }, [fetcher, pollIntervalMilliseconds]);

    return { data, error, isLoading };
}
