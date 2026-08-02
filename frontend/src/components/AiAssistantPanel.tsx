import { useCallback } from 'react';

import type { ApiError } from '../api/client';
import { analyzeEntity } from '../api/endpoints';
import type { EntityType } from '../api/types';
import { formatEntityId } from '../domain/format';
import { useApiResource } from '../hooks/useApiResource';

const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;

function retryLabel(seconds: number): string {
    if (seconds < SECONDS_PER_MINUTE) {
        return `Try again in ${String(seconds)} seconds.`;
    }
    if (seconds < SECONDS_PER_HOUR) {
        return `Try again in ${String(Math.round(seconds / SECONDS_PER_MINUTE))} minutes.`;
    }
    return `Try again in ${String(Math.round(seconds / SECONDS_PER_HOUR))} hours.`;
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
            aria-label={`AI Analysis of ${formatEntityId(entityId)}`}
            className="border border-border-subtle p-6 sm:p-8"
        >
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                <h2 className="eyebrow text-accent">AI Analysis — {formatEntityId(entityId)}</h2>
                {analysis?.from_cache === true && (
                    <span className="text-xs text-text-muted">
                        {cacheLabel(analysis.cache_age_seconds)}
                    </span>
                )}
                <button
                    type="button"
                    onClick={onClose}
                    className="eyebrow ml-auto text-text-muted hover:text-accent"
                >
                    Close
                </button>
            </div>

            <div className="mt-4 max-w-3xl">
                {isLoading && (
                    <p role="status" className="text-text-muted">
                        Analyzing this {entityType}…
                    </p>
                )}

                {error !== null && (
                    <p className={error.status === 429 ? 'text-state-warning' : 'text-state-bad'}>
                        {errorMessage(error, entityType)}
                    </p>
                )}

                {analysis !== null && (
                    <>
                        <p className="font-display text-xl leading-relaxed text-text-primary">
                            {analysis.summary}
                        </p>
                        {analysis.next_steps.length > 0 && (
                            <>
                                <h3 className="eyebrow mt-7 border-t border-border-subtle pt-4 text-accent">
                                    Suggested Next Steps
                                </h3>
                                <ol className="mt-3 list-[decimal-leading-zero] space-y-2.5 pl-9 marker:font-body marker:text-[0.6875rem] marker:text-accent">
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
