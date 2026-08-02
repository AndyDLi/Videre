import { useCallback } from 'react';
import { Link } from 'react-router-dom';

import { listJobs } from '../api/endpoints';
import { formatEntityId } from '../domain/format';
import { useApiResource } from '../hooks/useApiResource';
import { HealthBadge } from './HealthBadge';
import { LoadingOrError } from './LoadingOrError';

const JOB_PAGE_SIZE = 10;
const REFRESH_INTERVAL_MILLISECONDS = 15_000;

export function JobList() {
    const fetcher = useCallback(
        (signal: AbortSignal) => listJobs({ limit: JOB_PAGE_SIZE }, signal),
        [],
    );
    const { data, error, isLoading } = useApiResource(fetcher, REFRESH_INTERVAL_MILLISECONDS);

    if (data === null) {
        return <LoadingOrError isLoading={isLoading} error={error} subject="jobs" />;
    }

    return (
        <ul className="divide-y divide-border-subtle border-b border-border-subtle">
            {data.items.map((job) => (
                <li key={job.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
                    <Link to={`/jobs/${job.id}`} className="entity-link">
                        {formatEntityId(job.id)}
                    </Link>
                    <HealthBadge state={job.lifecycle_state} />
                    <span className="text-sm text-text-muted">
                        {job.requested_gpu_count} GPUs · priority {job.priority}
                    </span>
                    {job.failure_reason !== null && (
                        <span className="ml-auto text-sm text-state-bad">{job.failure_reason}</span>
                    )}
                </li>
            ))}
        </ul>
    );
}
