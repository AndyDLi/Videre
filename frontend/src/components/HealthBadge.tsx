import type { HealthTone } from '../domain/clusterHealth';
import { toneForState } from '../domain/healthState';

const TONE_CLASSES: Record<HealthTone, string> = {
    good: 'bg-state-good/10 text-state-good border-state-good/40',
    warning: 'bg-state-warning/10 text-state-warning border-state-warning/40',
    bad: 'bg-state-bad/10 text-state-bad border-state-bad/40',
    neutral: 'bg-state-neutral/10 text-state-neutral border-state-neutral/40',
};

export function HealthBadge({ state }: { state: string }) {
    const tone = toneForState(state);
    return (
        <span
            data-tone={tone}
            className={`inline-block rounded border px-2 py-0.5 text-xs font-semibold tracking-wide ${TONE_CLASSES[tone]}`}
        >
            {state}
        </span>
    );
}
