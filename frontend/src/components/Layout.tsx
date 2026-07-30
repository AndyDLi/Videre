import { Link, NavLink, Outlet } from 'react-router-dom';

import { ClusterHealthSummary } from './ClusterHealthSummary';

const NAVIGATION_ITEMS = [
    { to: '/', label: 'Cluster Overview' },
    { to: '/failures', label: 'Failures' },
    { to: '/capacity', label: 'Capacity' },
];

function navigationClasses(isActive: boolean): string {
    const base = 'rounded px-3 py-2 text-sm font-medium';
    return isActive
        ? `${base} bg-surface-muted text-text-primary`
        : `${base} text-text-muted hover:bg-surface-muted`;
}

export function Layout() {
    return (
        <div className="min-h-screen">
            <header className="border-b border-border-subtle bg-surface">
                <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <Link to="/" className="text-lg font-semibold">
                        Videre
                    </Link>
                    <ClusterHealthSummary />
                </div>
                <nav
                    aria-label="Primary"
                    className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-4 pb-2"
                >
                    {NAVIGATION_ITEMS.map((item) => (
                        <NavLink
                            key={item.to}
                            to={item.to}
                            end={item.to === '/'}
                            className={({ isActive }) => navigationClasses(isActive)}
                        >
                            {item.label}
                        </NavLink>
                    ))}
                </nav>
            </header>

            <main className="mx-auto max-w-6xl px-4 py-6">
                <Outlet />
            </main>
        </div>
    );
}
