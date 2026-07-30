import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { Layout } from './components/Layout';
import { CapacityPage } from './pages/CapacityPage';
import { ClusterOverviewPage } from './pages/ClusterOverviewPage';
import { FailuresPage } from './pages/FailuresPage';
import { GpuDetailPage } from './pages/GpuDetailPage';
import { JobDetailPage } from './pages/JobDetailPage';
import { NodeDetailPage } from './pages/NodeDetailPage';
import { NotFoundPage } from './pages/NotFoundPage';

export function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route element={<Layout />}>
                    <Route path="/" element={<ClusterOverviewPage />} />
                    <Route path="/failures" element={<FailuresPage />} />
                    <Route path="/capacity" element={<CapacityPage />} />
                    <Route path="/nodes/:nodeId" element={<NodeDetailPage />} />
                    <Route path="/nodes/:nodeId/gpus/:gpuId" element={<GpuDetailPage />} />
                    <Route path="/jobs/:jobId" element={<JobDetailPage />} />
                    <Route path="*" element={<NotFoundPage />} />
                </Route>
            </Routes>
        </BrowserRouter>
    );
}
