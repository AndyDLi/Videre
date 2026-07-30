import type { ApiError } from '../api/client';

interface LoadingOrErrorProps {
    isLoading: boolean;
    error: ApiError | null;
    subject: string;
}

export function LoadingOrError({ isLoading, error, subject }: LoadingOrErrorProps) {
    return (
        <p className={isLoading ? 'text-sm text-text-muted' : 'text-sm text-state-bad'}>
            {isLoading
                ? `Loading ${subject}…`
                : `Could not load ${subject} — ${error?.detail ?? 'unknown error'}`}
        </p>
    );
}
