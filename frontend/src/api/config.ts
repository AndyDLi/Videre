const configuredBaseUrl: string = import.meta.env.VITE_API_BASE_URL ?? '';

export const apiBaseUrl: string = configuredBaseUrl.replace(/\/+$/, '');

export function restUrl(path: string): string {
    if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
        return `${apiBaseUrl}${path}`;
    }
    return `${window.location.origin}${apiBaseUrl}${path}`;
}

export function webSocketUrl(path: string): string {
    return restUrl(path).replace(/^http/, 'ws');
}
