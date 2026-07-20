export class ApiError extends Error {
    status: number
    code: string
    errors?: unknown

    constructor(status: number, body: { detail?: string; title?: string; code?: string; errors?: unknown }) {
        super(body.detail || body.title || '请求失败')
        this.name = 'ApiError'
        this.status = status
        this.code = body.code || 'request_error'
        this.errors = body.errors
    }
}

function cookie(name: string): string {
    const item = document.cookie.split('; ').find((part) => part.startsWith(`${name}=`))
    return item ? decodeURIComponent(item.split('=').slice(1).join('=')) : ''
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers)
    if (options.body && !(options.body instanceof FormData)) {
        headers.set('Content-Type', 'application/json')
    }
    const method = (options.method || 'GET').toUpperCase()
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        headers.set('X-CSRFToken', cookie('csrftoken'))
    }
    const response = await fetch(`/api/v1${path}`, {
        ...options,
        headers,
        credentials: 'include'
    })
    if (response.status === 204) return undefined as T
    const contentType = response.headers.get('content-type') || ''
    const body = contentType.includes('json') ? await response.json() : await response.text()
    if (!response.ok) {
        throw new ApiError(response.status, typeof body === 'object' ? body : { detail: body })
    }
    return body as T
}

export const api = {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, data?: unknown) =>
        request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) }),
    patch: <T>(path: string, data: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(data) }),
    upload: <T>(path: string, form: FormData) => request<T>(path, { method: 'POST', body: form })
}
