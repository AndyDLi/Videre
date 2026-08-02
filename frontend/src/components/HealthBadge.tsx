import { formatTerm } from '../domain/format';
import type { HealthTone } from '../domain/healthState';
import { toneForState } from '../domain/healthState';

const TONE_CLASSES: Record<HealthTone, string> = {
    good: 'border-state-good/45 text-state-good',
    warning: 'border-state-warning/45 text-state-warning',
    bad: 'border-state-bad/45 text-state-bad',
    neutral: 'border-state-neutral/45 text-state-neutral',
};

const TONE_MARK_CLASSES: Record<HealthTone, string> = {
    good: 'rounded-full bg-current',
    warning: 'rotate-45 bg-current',
    bad: 'bg-current',
    neutral: 'rounded-full border border-current',
};

export function HealthBadge({ state }: { state: string }) {
    const tone = toneForState(state);
    return (
        <span
            data-tone={tone}
            className={`inline-flex items-center gap-1.5 rounded-[3px] border px-2 py-0.5 text-[0.625rem] tracking-[0.12em] whitespace-nowrap ${TONE_CLASSES[tone]}`}
        >
            <span
                aria-hidden="true"
                className={`h-1.5 w-1.5 shrink-0 ${TONE_MARK_CLASSES[tone]}`}
            />
            {formatTerm(state)}
        </span>
    );
}
