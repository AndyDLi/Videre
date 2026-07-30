import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

interface DetailFallbackProps {
    title: string;
    children: ReactNode;
}

export function DetailFallback({ title, children }: DetailFallbackProps) {
    return (
        <section className="space-y-4">
            <h1 className="text-xl font-semibold">{title}</h1>
            <p className="text-sm text-text-muted">{children}</p>
            <Link to="/" className="text-sm font-medium underline">
                Back to the Cluster Overview
            </Link>
        </section>
    );
}
