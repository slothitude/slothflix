// Auth-aware fetch wrapper
// Gets the auth header from the page (injected by the server via a meta tag or data attribute)
// Uses credentials: 'same-origin' for cookie-based auth

const AUTH_HEADER = document.documentElement.dataset.authHeader || '';

export async function authFetch(url, opts = {}) {
    const headers = { ...opts.headers };
    if (AUTH_HEADER) {
        headers['Authorization'] = AUTH_HEADER;
    }
    return fetch(url, { ...opts, headers, credentials: 'same-origin' });
}
