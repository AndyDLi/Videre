import { useCallback } from 'react';
import { Link } from 'react-router-dom';

import { listJobs } from '../api/endpoints';
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
        <ul className="divide-y divide-border-subtle">
            {data.items.map((job) => (
                <li key={job.id} className="flex flex-wrap items-center gap-3 py-2">
                    <Link to={`/jobs/${job.id}`} className="font-medium hover:underline">
                        {job.id}
                    </Link>
                    <HealthBadge state={job.lifecycle_state} />
                    <span className="text-sm text-text-muted">
                        {job.requested_gpu_count} GPUs · priority {job.priority}
                    </span>
                    {job.failure_reason !== null && (
                        <span className="text-sm text-state-bad">{job.failure_reason}</span>
                    )}
                </li>
            ))}
        </ul>
    );
}
