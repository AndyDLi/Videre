import { restUrl } from './config';

export type QueryParameters = Record<string, string | number | boolean | undefined | null>;

export class ApiError extends Error {
    readonly status: number;
    readonly detail: string;
    readonly retryAfterSeconds: number | null;

    constructor(status: number, detail: string, retryAfterSeconds: number | null) {
        super(`${String(status)}: ${detail}`);
        this.name = 'ApiError';
        this.status = status;
        this.detail = detail;
        this.retryAfterSeconds = retryAfterSeconds;
    }

    get isNetworkFailure(): boolean {
        return this.status === 0;
    }
}

export function toApiError(caught: unknown): ApiError {
    if (caught instanceof ApiError) {
        return caught;
    }
    return new ApiError(0, caught instanceof Error ? caught.message : 'request failed', null);
}

function queryString(parameters: QueryParameters | undefined): string {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(parameters ?? {})) {
        if (value !== undefined && value !== null) {
            search.append(key, String(value));
        }
    }

    const query = search.toString();
    return query === '' ? '' : `?${query}`;
}

function responseDetail(body: unknown, response: Response): string {
    if (typeof body === 'object' && body !== null && 'detail' in body) {
        if (typeof body.detail === 'string') {
            return body.detail;
        }
    }
    if (response.statusText !== '') {
        return response.statusText;
    }
    return `request failed with status ${String(response.status)}`;
}

function retryAfterSeconds(response: Response): number | null {
    const header = response.headers.get('Retry-After');
    if (header === null) {
        return null;
    }
    const seconds = Number.parseInt(header, 10);
    return Number.isNaN(seconds) ? null : seconds;
}

interface RequestOptions {
    query?: QueryParameters;
    body?: unknown;
    signal?: AbortSignal;
}

async function request<ResponseT>(
    method: 'GET' | 'POST',
    path: string,
    options: RequestOptions,
): Promise<ResponseT> {
    const hasBody = options.body !== undefined;

    let response: Response;
    try {
        response = await fetch(`${restUrl(path)}${queryString(options.query)}`, {
            method,
            headers: hasBody ? { 'Content-Type': 'application/json' } : {},
            body: hasBody ? JSON.stringify(options.body) : null,
            signal: options.signal,
        });
    } catch (caught) {
        throw new ApiError(
            0,
            caught instanceof Error ? caught.message : 'network request failed',
            null,
        );
    }

    if (!response.ok) {
        const body: unknown = await response.json().catch(() => null);
        throw new ApiError(
            response.status,
            responseDetail(body, response),
            retryAfterSeconds(response),
        );
    }

    return (await response.json()) as ResponseT;
}

export function get<ResponseT>(
    path: string,
    query?: QueryParameters,
    signal?: AbortSignal,
): Promise<ResponseT> {
    return request<ResponseT>('GET', path, { query, signal });
}

export function post<ResponseT>(
    path: string,
    body: unknown,
    signal?: AbortSignal,
): Promise<ResponseT> {
    return request<ResponseT>('POST', path, { body, signal });
}
