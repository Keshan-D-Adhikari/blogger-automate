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
  post: (items, publish) => call('/api/post', { items, publish }),
  history: () => call('/api/history'),
  posts: () => call('/api/posts'),
  prices: apply => call('/api/prices', { apply })
}
