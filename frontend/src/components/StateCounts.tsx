import { Section } from './Section';
import { HealthBadge } from './HealthBadge';

interface StateCountsProps {
    title: string;
    counts: Partial<Record<string, number>>;
}

export function StateCounts({ title, counts }: StateCountsProps) {
    const entries = Object.entries(counts)
        .map(([state, count]) => ({ state, count: count ?? 0 }))
        .sort((first, second) => second.count - first.count);

    return (
        <Section title={title} headingLevel={3}>
            {entries.length === 0 ? (
                <p className="text-sm text-text-muted">No data yet.</p>
            ) : (
                <ul className="space-y-2.5">
                    {entries.map((entry) => (
                        <li key={entry.state} className="flex items-center justify-between gap-3">
                            <HealthBadge state={entry.state} />
                            <span className="metric text-xl">{entry.count}</span>
                        </li>
                    ))}
                </ul>
            )}
        </Section>
    );
}
