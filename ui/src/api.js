// Called when the login expires, so the app can show the login screen again
let onLoggedOut = () => {}
export const setOnLoggedOut = fn => { onLoggedOut = fn }

async function call(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (res.status === 401 && path !== '/api/login') {
    onLoggedOut()
    throw new Error('Please log in again.')
  }
  const data = await res.json().catch(() => null)
  if (res.ok || (path === '/api/login' && data)) return data
  throw new Error(data?.message || data?.error || `Server error ${res.status}. Try again in a moment.`)
}

export const api = {
  session: () => call('/api/session'),
  login: password => call('/api/login', { password }),
  logout: () => call('/api/logout', {}),
  status: () => call('/api/status'),
  linksFile: () => call('/api/links-file'),
  preview: text => call('/api/preview', { text }),
  post: (items, publish, board) => call('/api/post', { items, publish, board }),
  boards: () => call('/api/pinterest/boards'),
  pinQueue: () => call('/api/pinterest/queue'),
  search: q => call('/api/search', q),
  categories: () => call('/api/categories'),
  importProducts: (items, publish, board) => call('/api/import', { items, publish, board }),
  postQueue: () => call('/api/post-queue'),
  postNow: productId => call('/api/post-queue/post-now', { productId }),
  removeQueued: productIds => call('/api/post-queue/remove', { productIds }),
  retryQueued: productIds => call('/api/post-queue/retry', { productIds }),
  pinPost: (postId, board) => call('/api/pinterest/pin-post', { postId, board }),
  history: () => call('/api/history'),
  posts: () => call('/api/posts'),
  prices: apply => call('/api/prices', { apply }),
  autoStatus: () => call('/api/auto-update'),
  autoRun: () => call('/api/auto-update/run', {}),
  draftUnavailable: postId => call('/api/unavailable/draft', { postId })
}
