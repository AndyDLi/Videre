import { useParams } from 'react-router-dom';

import { PageContainer } from '../components/PageContainer';

export function JobDetailPage() {
    const { jobId } = useParams<{ jobId: string }>();
    return (
        <PageContainer
            title={`Job ${jobId ?? ''}`}
            description="Built in Task 7.4 from GET /jobs/{id}."
        >
            <p className="text-sm text-text-muted">Not implemented yet.</p>
        </PageContainer>
    );
}
