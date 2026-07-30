import { useCallback } from 'react';

import type { ApiError } from '../api/client';
import { analyzeEntity } from '../api/endpoints';
import type { EntityType } from '../api/types';
import { useApiResource } from '../hooks/useApiResource';

const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;

function retryLabel(seconds: number): string {
    if (seconds < SECONDS_PER_MINUTE) {
        return `Try again in ${String(seconds)} seconds.`;
    }
    if (seconds < SECONDS_PER_HOUR) {
        return `Try again in ${String(Math.max(Math.round(seconds / SECONDS_PER_MINUTE), 1))} minutes.`;
    }
    return `Try again in ${String(Math.max(Math.round(seconds / SECONDS_PER_HOUR), 1))} hours.`;
}

function errorMessage(error: ApiError, entityType: EntityType): string {
    if (error.status === 429) {
        return error.retryAfterSeconds === null
            ? error.detail
            : `AI analysis is rate limited. ${retryLabel(error.retryAfterSeconds)}`;
    }
    if (error.status === 404) {
        return `This ${entityType} no longer exists, so there is nothing to analyze.`;
    }
    return error.detail;
}

function cacheLabel(cacheAgeSeconds: number | null): string {
    if (cacheAgeSeconds === null || cacheAgeSeconds < SECONDS_PER_MINUTE) {
        return 'Cached moments ago';
    }
    const minutes = Math.round(cacheAgeSeconds / SECONDS_PER_MINUTE);
    return `Cached ${String(minutes)} ${minutes === 1 ? 'minute' : 'minutes'} ago`;
}

interface AiAssistantPanelProps {
    entityType: EntityType;
    entityId: string;
    onClose: () => void;
}

export function AiAssistantPanel({ entityType, entityId, onClose }: AiAssistantPanelProps) {
    const fetcher = useCallback(
        (signal: AbortSignal) =>
            analyzeEntity({ entity_type: entityType, entity_id: entityId }, signal),
        [entityType, entityId],
    );
    const { data: analysis, error, isLoading } = useApiResource(fetcher);

    return (
        <section
            aria-label={`AI analysis of ${entityType} ${entityId}`}
            className="rounded border border-border-subtle bg-surface p-4"
        >
            <div className="flex flex-wrap items-center gap-3">
                <h2 className="text-sm font-semibold">AI Analysis — {entityId}</h2>
                {analysis?.from_cache === true && (
                    <span className="text-xs text-text-muted">
                        {cacheLabel(analysis.cache_age_seconds)}
                    </span>
                )}
                <button
                    type="button"
                    onClick={onClose}
                    className="ml-auto rounded border border-border-subtle px-2 py-1 text-xs font-medium hover:bg-surface-muted"
                >
                    Close
                </button>
            </div>

            <div className="mt-3">
                {isLoading && (
                    <p role="status" className="text-sm text-text-muted">
                        Analyzing this {entityType}…
                    </p>
                )}

                {error !== null && (
                    <p
                        className={`text-sm ${error.status === 429 ? 'text-state-warning' : 'text-state-bad'}`}
                    >
                        {errorMessage(error, entityType)}
                    </p>
                )}

                {analysis !== null && (
                    <>
                        <p className="text-sm">{analysis.summary}</p>
                        {analysis.next_steps.length > 0 && (
                            <>
                                <h3 className="mt-3 text-sm font-semibold">Suggested Next Steps</h3>
                                <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm">
                                    {analysis.next_steps.map((step, position) => (
                                        <li key={position}>{step}</li>
                                    ))}
                                </ol>
                            </>
                        )}
                    </>
                )}
            </div>
        </section>
    );
}
