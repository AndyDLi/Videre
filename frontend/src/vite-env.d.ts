interface ImportMetaEnv {
    readonly VITE_API_BASE_URL: string;
    readonly VITE_GRAFANA_BASE_URL: string;
}

interface ImportMeta {
    readonly env: ImportMetaEnv;
}
