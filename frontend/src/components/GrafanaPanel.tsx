import { grafanaBaseUrl } from '../api/config';

const PANEL_IDS = {
    nodeHealthState: 1,
    gpuUtilization: 2,
    gpuTemperature: 3,
};

const DASHBOARD_PATH = 'd-solo/videre-node-gpu-drilldown/node-gpu-drill-down';
const ALL_GPUS = '$__all';

interface GrafanaPanelProps {
    title: string;
    panel: keyof typeof PANEL_IDS;
    nodeId: string;
    gpuId?: string;
}

export function GrafanaPanel({ title, panel, nodeId, gpuId }: GrafanaPanelProps) {
    const parameters = new URLSearchParams({
        panelId: String(PANEL_IDS[panel]),
        'var-node': nodeId,
        'var-gpu': gpuId ?? ALL_GPUS,
        from: 'now-3h',
        to: 'now',
        refresh: '15s',
        theme: 'light',
    });

    return (
        <iframe
            title={title}
            src={`${grafanaBaseUrl}/${DASHBOARD_PATH}?${parameters.toString()}`}
            className="h-64 w-full border border-border-subtle"
        />
    );
}
