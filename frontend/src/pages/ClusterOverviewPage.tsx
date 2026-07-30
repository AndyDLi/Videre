import { useCallback } from 'react';

import { apiBaseUrl } from '../api/config';
import { getHealth } from '../api/endpoints';
import { PageContainer } from '../components/PageContainer';
import { useApiResource } from '../hooks/useApiResource';

export function ClusterOverviewPage() {
    const fetcher = useCallback((signal: AbortSignal) => getHealth(signal), []);
    const { data, error, isLoading, reload } = useApiResource(fetcher);

    return (
        <PageContainer
            title="Cluster Overview"
            description="Real-time cluster health lands here in Task 7.2."
        >
            <dl className="grid gap-2 text-sm sm:grid-cols-[10rem_1fr]">
                <dt className="font-medium">API Base URL</dt>
                <dd className="font-mono break-all">
                    {apiBaseUrl === '' ? '(same origin)' : apiBaseUrl}
                </dd>

                <dt className="font-medium">Backend /healthz</dt>
                <dd>
                    {isLoading && <span className="text-text-muted">checking…</span>}
                    {error !== null && (
                        <span className="text-state-bad">
                            {error.isNetworkFailure
                                ? `unreachable or blocked by CORS — ${error.detail}`
                                : `HTTP ${String(error.status)} — ${error.detail}`}
                        </span>
                    )}
                    {data !== null && error === null && (
                        <span
                            className={
                                data.status === 'healthy' ? 'text-state-good' : 'text-state-warning'
                            }
                        >
                            {data.status} (postgres: {String(data.checks.postgres)}, redis:{' '}
                            {String(data.checks.redis)})
                        </span>
                    )}
                </dd>
            </dl>

            <button
                type="button"
                onClick={reload}
                className="mt-4 rounded border border-border-subtle px-3 py-1.5 text-sm font-medium hover:bg-surface-muted"
            >
                Re-check
            </button>
        </PageContainer>
    );
}
