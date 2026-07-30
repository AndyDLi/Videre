import { Card } from './Card';
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
        <Card title={title} headingLevel={3}>
            {entries.length === 0 ? (
                <p className="text-sm text-text-muted">No data yet.</p>
            ) : (
                <ul className="space-y-1">
                    {entries.map((entry) => (
                        <li key={entry.state} className="flex items-center justify-between gap-3">
                            <HealthBadge state={entry.state} />
                            <span className="text-sm font-medium tabular-nums">{entry.count}</span>
                        </li>
                    ))}
                </ul>
            )}
        </Card>
    );
}
