import { Link } from 'react-router-dom';

import { PageContainer } from '../components/PageContainer';

export function NotFoundPage() {
    return (
        <PageContainer title="Page Not Found" description="This route does not exist.">
            <Link to="/" className="text-sm font-medium underline">
                Back to the Cluster Overview
            </Link>
        </PageContainer>
    );
}
