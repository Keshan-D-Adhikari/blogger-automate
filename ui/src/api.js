async function call(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}

export const api = {
  status: () => call('/api/status'),
  linksFile: () => call('/api/links-file'),
  preview: text => call('/api/preview', { text }),
  post: (items, publish, board) => call('/api/post', { items, publish, board }),
  boards: () => call('/api/pinterest/boards'),
  pinQueue: () => call('/api/pinterest/queue'),
  search: q => call('/api/search', q),
  importProducts: (items, publish, board) => call('/api/import', { items, publish, board }),
  postQueue: () => call('/api/post-queue'),
  removeQueued: productId => call('/api/post-queue/remove', { productId }),
  pinPost: (postId, board) => call('/api/pinterest/pin-post', { postId, board }),
  history: () => call('/api/history'),
  posts: () => call('/api/posts'),
  prices: apply => call('/api/prices', { apply }),
  autoStatus: () => call('/api/auto-update'),
  autoRun: () => call('/api/auto-update/run', {}),
  draftUnavailable: postId => call('/api/unavailable/draft', { postId })
}
