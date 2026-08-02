import { Link, NavLink, Outlet } from 'react-router-dom';

import { ClusterHealthSummary } from './ClusterHealthSummary';

const NAVIGATION_ITEMS = [
    { to: '/', label: 'Cluster Overview' },
    { to: '/failures', label: 'Failures' },
    { to: '/capacity', label: 'Capacity' },
];

const CONTAINER_CLASSES = 'mx-auto w-full max-w-[1180px] px-6 sm:px-10';

function navigationClasses(isActive: boolean): string {
    const base = 'eyebrow border-b-2 py-3 whitespace-nowrap';
    return isActive
        ? `${base} border-accent-border text-accent`
        : `${base} border-transparent text-text-muted hover:text-text-primary`;
}

export function Layout() {
    return (
        <div className="min-h-screen">
            <header className="sticky top-0 z-10 border-b border-border-subtle bg-surface/92 backdrop-blur">
                <div
                    className={`${CONTAINER_CLASSES} flex flex-col gap-1 py-4 sm:flex-row sm:items-baseline sm:justify-between sm:gap-6`}
                >
                    <Link
                        to="/"
                        className="font-display text-lg tracking-[0.18em] text-accent uppercase"
                    >
                        Videre
                    </Link>
                    <ClusterHealthSummary />
                </div>
                <nav
                    aria-label="Primary"
                    className={`${CONTAINER_CLASSES} flex gap-7 overflow-x-auto border-t border-border-subtle`}
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

            <main className={`${CONTAINER_CLASSES} py-10 sm:py-14`}>
                <Outlet />
            </main>
        </div>
    );
}
