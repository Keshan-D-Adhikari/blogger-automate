import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const LABELS = ['Deals', 'Under $25', 'Home', 'Kitchen', 'Organization', 'Beauty', 'Tech', 'Fashion', 'Halloween', 'Gift Ideas']
const TABS = [['find', 'Find Products'], ['new', 'New Posts'], ['posts', 'Blog Posts'], ['pins', 'Queue'], ['prices', 'Price Update'], ['history', 'History']]
const imgSrc = u => (u && /^https:\/\/[a-z0-9.-]+\.(aliexpress-media\.com|alicdn\.com)\//.test(u) ? `/api/img?u=${encodeURIComponent(u)}` : u)
const fmtTime = t => new Date(t * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

export default function App() {
  const [tab, setTab] = useState('find')
  const [status, setStatus] = useState(null)
  const [toast, setToast] = useState('')

  useEffect(() => { api.status().then(setStatus).catch(e => setToast(e.message)) }, [])
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(''), 4500); return () => clearTimeout(t) } }, [toast])

  return (
    <div className="app">
      <aside className="side">
        <div className="logo"><span>&#9733;</span><b>Penny Wise <em>Finds</em></b></div>
        <nav>
          {TABS.map(([k, label]) => (
            <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{label}</button>
          ))}
        </nav>
        <StatusCard s={status} />
        <a className="blog-link" href="https://pennywisefinds.blogspot.com" target="_blank" rel="noreferrer">Open blog &#8599;</a>
      </aside>
      <main>
        {tab === 'new' && <NewPosts status={status} notify={setToast} onPosted={() => api.status().then(setStatus)} />}
        {tab === 'posts' && <BlogPosts status={status} notify={setToast} />}
        {tab === 'find' && <FindProducts status={status} notify={setToast} />}
        {tab === 'pins' && <><PostQueue notify={setToast} /><PinQueue /></>}
        {tab === 'prices' && <Prices notify={setToast} />}
        {tab === 'history' && <History />}
      </main>
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}

function StatusCard({ s }) {
  if (!s) return <div className="status">Checking setup&#8230;</div>
  const row = (ok, label) => <li className={ok ? 'ok' : 'bad'}>{ok ? '✔' : '✖'} {label}</li>
  return (
    <div className="status">
      <h4>Setup</h4>
      <ul>
        {row(s.aliKey && s.aliSecret, 'AliExpress API')}
        {row(s.clientSecret && s.signedIn, 'Blogger API')}
        {s.pinterest.connected ? row(true, `Pinterest${s.pinterest.sandbox ? ' (sandbox)' : ''}`)
          : s.pinterest.configured ? <li className="bad">&#10006; <a href="/api/pinterest/login">Connect Pinterest</a></li>
          : row(false, 'Pinterest (add keys to .env)')}
        <li className="ok">&#9679; Tracking: {s.trackingId}</li>
      </ul>
      <small>Filter: &#8805;{s.filters.minPositive}% positive, &#8805;{s.filters.minOrders} orders, &#8804;${s.filters.maxPrice}</small>
      <small>{s.published} links posted by this tool</small>
    </div>
  )
}

/* ------------------------------------------------------------- Pinterest boards */
function useBoards(status, notify) {
  const [boards, setBoards] = useState([])
  const [board, setBoard] = useState(() => { try { return localStorage.getItem('pinBoard') || '' } catch { return '' } })
  const pinReady = !!status?.pinterest?.connected
  useEffect(() => {
    if (!pinReady) return
    api.boards().then(r => { setBoards(r.items); if (r.error) notify(r.error) }).catch(e => notify(e.message))
  }, [pinReady])
  function pickBoard(id) {
    setBoard(id)
    try { localStorage.setItem('pinBoard', id) } catch { /* ignore */ }
  }
  return { boards, board, pickBoard, pinReady }
}

function BoardSelect({ boards, board, pickBoard, pinReady, empty = "Don't pin" }) {
  return (
    <select className="board" value={pinReady ? board : ''} disabled={!pinReady} onChange={e => pickBoard(e.target.value)}
      title={pinReady ? 'Pinterest board' : 'Connect Pinterest to pin posts'}>
      <option value="">{pinReady ? empty : 'Pinterest not connected'}</option>
      {boards.map(b => <option key={b.id} value={b.id}>📌 {b.name}</option>)}
    </select>
  )
}

/* ------------------------------------------------------------- New posts */
function NewPosts({ status, notify, onPosted }) {
  const [links, setLinks] = useState(() => Array(10).fill(''))
  const text = links.map(l => l.trim()).filter(Boolean).join('\n')
  const setLink = (i, v) => setLinks(links.map((l, j) => (j === i ? v : l)))
  const [items, setItems] = useState([])
  const [busy, setBusy] = useState('')
  const { boards, board, pickBoard, pinReady } = useBoards(status, notify)
  const [summary, setSummary] = useState(null)

  async function loadFile() {
    const r = await api.linksFile()
    const file = r.text.split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('#'))
    setLinks([...file, ...Array(10).fill('')].slice(0, Math.max(10, file.length)))
  }

  async function preview() {
    if (!text.trim()) { notify('Paste at least one AliExpress link.'); return null }
    const n = text.split('\n').filter(l => l.trim() && !l.trim().startsWith('#')).length
    setBusy(`Fetching ${n} product(s) from AliExpress…`)
    setSummary(null)
    try {
      const r = await api.preview(text)
      const list = r.items.map(it => ({ ...it, selected: it.status === 'ok' }))
      setItems(list)
      setBusy('')
      return list
    } catch (e) { notify(e.message) }
    setBusy('')
    return null
  }

  // one click: fetch every link, then publish each good product as its own post
  async function publishAll() {
    const n = text.split('\n').filter(l => l.trim() && !l.trim().startsWith('#')).length
    if (!n) return notify('Paste at least one AliExpress link.')
    const boardName = pinReady ? boards.find(b => b.id === board)?.name : ''
    if (!confirm(`Publish ${n} link(s) as ${n} separate post(s)${boardName ? ` and pin them to "${boardName}"` : ''}?\nProducts with errors or quality warnings are skipped.`)) return
    const list = await preview()
    if (list) await send(true, list, true)
  }

  const update = (i, patch) => setItems(items.map((it, j) => (j === i ? { ...it, ...patch } : it)))
  const chosen = items.filter(it => it.selected && it.content)

  async function send(publish, list = items, skipConfirm = false) {
    const chosen = list.filter(it => it.selected && it.content)
    if (!chosen.length) return notify('No products ready to post.')
    const pinTo = publish && pinReady ? board : ''
    const boardName = boards.find(b => b.id === pinTo)?.name
    if (publish && !skipConfirm && !confirm(`Publish ${chosen.length} post(s) live on the blog${boardName ? ` and pin them to "${boardName}"` : ''}?`)) return
    setBusy(publish ? `Publishing ${chosen.length} post(s)…` : `Saving ${chosen.length} draft(s)…`)
    try {
      const r = await api.post(chosen, publish, pinTo)
      const okLinks = new Set(r.results.filter(x => x.ok).map(x => x.link))
      setItems(list.map(it => okLinks.has(it.link)
        ? (x => ({ ...it, selected: false, status: 'posted', message: x.url, pinAt: x.pinAt }))(r.results.find(x => x.link === it.link)) : it))
      const fails = r.results.filter(x => !x.ok)
      const pins = r.results.filter(x => x.pinAt).length
      const sent = new Set(chosen.map(c => c.link))
      const skipped = list.filter(it => !sent.has(it.link) && it.status !== 'posted').map(it => ({
        link: it.link, title: it.title || it.link,
        why: it.status === 'duplicate' ? 'Already posted'
          : it.status === 'warning' ? `Quality filter: ${it.problems.join(', ')}`
          : it.content ? 'Not selected' : it.message || 'Error'
      }))
      const failed = fails.map(f => ({ link: f.link, title: list.find(it => it.link === f.link)?.title || f.link, why: f.message }))
      setSummary({ done: okLinks.size, publish, pins, skipped, failed })
      notify(`${okLinks.size} ${publish ? 'published' : 'saved as draft'}${failed.length ? `, ${failed.length} failed` : ''}`
        + `${skipped.length ? `, ${skipped.length} skipped` : ''}${pins ? ` · ${pins} pins scheduled` : ''}.`)
      onPosted()
    } catch (e) { notify(e.message) }
    setBusy('')
  }

  return (
    <section>
      <header className="page-head">
        <div><h1>New Posts</h1><p>Paste AliExpress links, preview the products, then save them as drafts or publish.</p></div>
      </header>

      <div className="card input-card">
        <div className="link-boxes">
          {links.map((l, i) => (
            <label key={i} className="link-box">
              <span>{i + 1}</span>
              <input value={l} onChange={e => setLink(i, e.target.value)} placeholder="https://s.click.aliexpress.com/e/_..." />
            </label>
          ))}
        </div>
        <div className="row">
          <button className="ghost" onClick={loadFile}>Load links.txt</button>
          <button className="ghost" onClick={() => setLinks(Array(10).fill(''))}>Clear boxes</button>
          <span className="hint">One link per box. Optional labels after <code>|</code></span>
          <BoardSelect boards={boards} board={board} pickBoard={pickBoard} pinReady={pinReady} />
          <button className="secondary" onClick={preview} disabled={!!busy}>Preview products</button>
          <button className="primary" onClick={publishAll} disabled={!!busy}>Publish all &#9889;</button>
        </div>
      </div>

      {busy && <div className="busy"><span className="spin" />{busy}</div>}

      {summary && !busy && (
        <div className="card summary">
          <div className="sum-head">
            <span className="badge ok">{summary.done} {summary.publish ? 'published' : 'drafts saved'}</span>
            {summary.skipped.length > 0 && <span className="badge draft">{summary.skipped.length} skipped</span>}
            {summary.failed.length > 0 && <span className="badge error">{summary.failed.length} failed</span>}
            {summary.pins > 0 && <span className="badge">📌 {summary.pins} pins scheduled</span>}
            <span className="grow" />
            <button className="ghost" onClick={() => setSummary(null)}>Close</button>
          </div>
          {[...summary.failed.map(x => ({ ...x, kind: 'Failed' })), ...summary.skipped.map(x => ({ ...x, kind: 'Skipped' }))].map((x, i) => (
            <div key={i} className="sum-row">
              <b className={x.kind === 'Failed' ? 'bad' : ''}>{x.kind}</b>
              <span title={x.link}>{x.title}</span>
              <small>{x.why}</small>
            </div>
          ))}
        </div>
      )}

      {items.length > 0 && (
        <>
          <div className="toolbar">
            <b>{chosen.length} selected</b>
            <button className="ghost" onClick={() => setItems(items.map(it => ({ ...it, selected: !!it.content && it.status !== 'posted' })))}>Select all</button>
            <button className="ghost" onClick={() => setItems(items.map(it => ({ ...it, selected: false })))}>Clear</button>
            <span className="grow" />
            <button className="secondary" disabled={!!busy} onClick={() => send(false)}>Save as drafts</button>
            <button className="primary" disabled={!!busy} onClick={() => send(true)}>Publish</button>
          </div>
          <div className="grid">
            {items.map((it, i) => <ProductCard key={it.link + i} it={it} onChange={p => update(i, p)} />)}
          </div>
        </>
      )}
    </section>
  )
}

function ProductCard({ it, onChange }) {
  if (!it.content) {
    return (
      <div className={`pcard ${it.status}`}>
        <div className="pbody">
          <span className={`badge ${it.status}`}>{it.status === 'duplicate' ? 'Already posted' : 'Error'}</span>
          <p className="link">{it.link}</p>
          <p className="msg">{it.message}</p>
        </div>
      </div>
    )
  }
  const toggle = l => onChange({ labels: it.labels.includes(l) ? it.labels.filter(x => x !== l) : [...it.labels, l] })
  return (
    <div className={`pcard ${it.status} ${it.selected ? 'sel' : ''}`}>
      <div className="pimg">
        <img src={imgSrc(it.image)} alt="" />
        {it.status !== 'posted' && (
          <label className="check"><input type="checkbox" checked={!!it.selected} onChange={e => onChange({ selected: e.target.checked })} /></label>
        )}
        {it.oldPrice > it.price && <span className="off">-{Math.round((1 - it.price / it.oldPrice) * 100)}%</span>}
      </div>
      <div className="pbody">
        {it.status === 'posted' && <span className="badge posted">Posted &#10003;</span>}
        {it.problems?.length > 0 && <div className="warn">&#9888; {it.problems.join(' · ')}</div>}
        <textarea className="title" rows={2} value={it.title} onChange={e => onChange({ title: e.target.value })} />
        <div className="stats">
          <b>${it.price.toFixed(2)}</b>
          {it.oldPrice > it.price && <s>${it.oldPrice.toFixed(2)}</s>}
          {it.positive && <span>&#9733; {it.positive}</span>}
          <span>{it.orders.toLocaleString()} sold</span>
        </div>
        <div className="chips">
          {LABELS.map(l => <button key={l} className={it.labels.includes(l) ? 'chip on' : 'chip'} onClick={() => toggle(l)}>{l}</button>)}
        </div>
        <p className="raw" title={it.rawTitle}>{it.rawTitle}</p>
        {it.status === 'posted' && <a className="posted-link" href={it.message} target="_blank" rel="noreferrer">{it.message}</a>}
        {it.pinAt && <span className="badge">📌 Pin at {fmtTime(it.pinAt)}</span>}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- Blog posts */
function BlogPosts({ status, notify }) {
  const [items, setItems] = useState(null)
  const [filter, setFilter] = useState('ALL')
  const [pinned, setPinned] = useState({})
  const { boards, board, pickBoard, pinReady } = useBoards(status, notify)
  useEffect(() => {
    api.pinQueue().then(r => setPinned(Object.fromEntries(r.items.map(x => [x.link, x.status])))).catch(() => {})
  }, [])
  async function pin(p) {
    if (!board) return notify('Pick a Pinterest board first.')
    const r = await api.pinPost(p.id, board).catch(e => ({ ok: false, message: e.message }))
    if (!r.ok) return notify(r.message)
    setPinned({ ...pinned, [p.url]: 'queued' })
    notify(`Pin scheduled for ${fmtTime(r.pinAt)}.`)
  }
  useEffect(() => { api.posts().then(r => setItems(r.items)).catch(e => notify(e.message)) }, [])
  if (!items) return <div className="busy"><span className="spin" />Loading posts&#8230;</div>
  const shown = items.filter(p => filter === 'ALL' || p.status === filter)
  return (
    <section>
      <header className="page-head">
        <div><h1>Blog Posts</h1><p>{items.filter(p => p.status === 'LIVE').length} live &#183; {items.filter(p => p.status === 'DRAFT').length} drafts</p></div>
        <BoardSelect boards={boards} board={board} pickBoard={pickBoard} pinReady={pinReady} empty="Pick a board" />
        <div className="seg">
          {['ALL', 'LIVE', 'DRAFT'].map(f => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f}</button>)}
        </div>
      </header>
      <div className="list">
        {shown.map(p => (
          <div key={p.id} className="lrow">
            {p.image ? <img src={p.image} alt="" /> : <span className="ph" />}
            <div>
              <a href={p.status === 'LIVE' ? p.url : `https://www.blogger.com/blog/post/edit/2976840353661435945/${p.id}`} target="_blank" rel="noreferrer"><b>{p.title}</b></a>
              <small>{p.labels.join(' · ')}</small>
            </div>
            {p.status === 'LIVE' && (pinned[p.url]
              ? <span className="badge">📌 {pinned[p.url]}</span>
              : <button className="ghost" disabled={!pinReady} onClick={() => pin(p)}>📌 Pin</button>)}
            <span className={`badge ${p.status === 'LIVE' ? 'ok' : 'draft'}`}>{p.status}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------- Prices */
function Prices({ notify }) {
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState('')
  async function run(apply) {
    if (apply && !confirm('Update prices and titles on the live blog?')) return
    setBusy(apply ? 'Updating posts…' : 'Checking prices (this can take a minute)…')
    try { setRes(await api.prices(apply)) } catch (e) { notify(e.message) }
    setBusy('')
  }
  return (
    <section>
      <header className="page-head">
        <div><h1>Price Update</h1><p>Refresh every post with the current US price from the AliExpress API.</p></div>
        <div className="row">
          <button className="secondary" disabled={!!busy} onClick={() => run(false)}>Check prices</button>
          <button className="primary" disabled={!!busy || !res || res.applied || !res.rows.length} onClick={() => run(true)}>Apply changes</button>
        </div>
      </header>
      <AutoUpdate notify={notify} />
      {busy && <div className="busy"><span className="spin" />{busy}</div>}
      {res && (
        <div className="card">
          <p className="sum">{res.found}/{res.links} products found &#183; {res.rows.length} posts {res.applied ? 'updated ✔' : 'would change'}</p>
          {res.rows.length === 0 && <p className="hint">Everything is up to date.</p>}
          <table>
            <thead><tr><th>Post</th><th>Price changes</th></tr></thead>
            <tbody>
              {res.rows.map((r, i) => (
                <tr key={i}>
                  <td><b>{r.title}</b>{r.newTitle && <small>&#8594; {r.newTitle}</small>}</td>
                  <td>{r.changes.join(', ') || 'text only'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/* ------------------------------------------------------------- History */
function History() {
  const [items, setItems] = useState(null)
  useEffect(() => { api.history().then(r => setItems(r.items)) }, [])
  if (!items) return <div className="busy"><span className="spin" />Loading&#8230;</div>
  return (
    <section>
      <header className="page-head"><div><h1>History</h1><p>Links posted with this tool ({items.length}).</p></div></header>
      <div className="list">
        {items.length === 0 && <p className="hint">Nothing posted yet.</p>}
        {items.map(h => (
          <div key={h.link} className="lrow">
            <div><b>{h.link}</b><small>{h.url}</small></div>
          </div>
        ))}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------- Pin queue */
function PinQueue() {
  const [data, setData] = useState(null)
  useEffect(() => {
    const load = () => api.pinQueue().then(setData).catch(() => {})
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])
  if (!data) return <div className="busy"><span className="spin" />Loading&#8230;</div>
  const queued = data.items.filter(x => x.status === 'queued').length
  return (
    <section>
      <header className="page-head"><div><h1>Pin Queue</h1>
        <p>{queued} waiting &#183; one pin every {data.intervalMin} minutes. Keep the dashboard running so pins go out.</p></div></header>
      <div className="list">
        {data.items.length === 0 && <p className="hint">No pins yet. Pick a board and Publish to schedule pins.</p>}
        {data.items.map((x, i) => (
          <a key={i} className="lrow" href={x.pin || x.link} target="_blank" rel="noreferrer">
            {x.image ? <img src={imgSrc(x.image)} alt="" /> : <span className="ph" />}
            <div>
              <b>{x.title}</b>
              <small>{x.status === 'pinned' ? `Pinned ${fmtTime(x.done_at)}` : x.status === 'failed' ? `Failed: ${x.error}` : `Scheduled ${fmtTime(x.due)}${x.error ? ` · retrying (${x.error})` : ''}`}</small>
            </div>
            <span className={`badge ${x.status === 'pinned' ? 'ok' : x.status === 'failed' ? 'error' : 'draft'}`}>{x.status}</span>
          </a>
        ))}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------- Find products */
const SORTS = [['orders', 'Best selling'], ['discount', 'Biggest discount'], ['price_low', 'Price: low to high'], ['price_high', 'Price: high to low']]

function FindProducts({ status, notify }) {
  const [cats, setCats] = useState([])
  useEffect(() => { api.categories().then(r => setCats(r.items)).catch(() => {}) }, [])
  const [q, setQ] = useState({ keywords: '', category: '', sort: 'orders', minPrice: '', maxPrice: '25', minOrders: '100', minRating: '90' })
  const [res, setRes] = useState(null)
  const [page, setPage] = useState(1)
  const [busy, setBusy] = useState('')
  const [publish, setPublish] = useState(true)
  const { boards, board, pickBoard, pinReady } = useBoards(status, notify)
  const set = (k, v) => setQ({ ...q, [k]: v })

  async function search(nextPage = 1) {
    if (!q.keywords.trim() && !q.category) return notify('Type a keyword or pick a category.')
    setBusy(nextPage === 1 ? 'Searching AliExpress…' : 'Loading more…')
    try {
      const r = await api.search({ ...q, page: nextPage })
      if (r.error) notify(r.error)
      const fresh = r.items.map(it => ({ ...it, selected: !it.state && !it.problems.length }))
      setRes(prev => nextPage === 1 || !prev ? { ...r, items: fresh }
        : { ...r, items: [...prev.items, ...fresh.filter(f => !prev.items.some(p => p.productId === f.productId))] })
      setPage(nextPage)
    } catch (e) { notify(e.message) }
    setBusy('')
  }

  const items = res?.items || []
  const chosen = items.filter(it => it.selected)
  const update = (id, patch) => setRes({ ...res, items: items.map(it => (it.productId === id ? { ...it, ...patch } : it)) })
  const selectAll = on => setRes({ ...res, items: items.map(it => ({ ...it, selected: on && !it.state && !it.problems.length })) })

  async function addToQueue() {
    if (!chosen.length) return notify('Select at least one product.')
    const pinTo = publish && pinReady ? board : ''
    setBusy('Adding to the post queue…')
    try {
      const r = await api.importProducts(chosen.map(it => ({ product: it.product, title: it.title, labels: it.labels })), publish, pinTo)
      const ids = new Set(chosen.map(c => c.productId))
      setRes({ ...res, items: items.map(it => (ids.has(it.productId) ? { ...it, selected: false, state: 'queued' } : it)) })
      notify(`${r.added} added to the post queue${r.skipped ? ` (${r.skipped} were already queued or posted)` : ''}. See the Queue tab.`)
    } catch (e) { notify(e.message) }
    setBusy('')
  }

  return (
    <section>
      <header className="page-head">
        <div><h1>Find Products</h1><p>Search AliExpress affiliate products, pick the good ones, and add them to the post queue.</p></div>
      </header>

      <form className="card find-form" onSubmit={e => { e.preventDefault(); search(1) }}>
        <input className="kw" value={q.keywords} onChange={e => set('keywords', e.target.value)} placeholder='Keyword, e.g. "kitchen gadgets", "halloween decor", "phone holder"' />
        <div className="filters">
          <label>Category<select value={q.category} onChange={e => set('category', e.target.value)}>
            <option value="">All categories</option>
            {cats.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></label>
          <label>Sort<select value={q.sort} onChange={e => set('sort', e.target.value)}>{SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label>Min $<input value={q.minPrice} onChange={e => set('minPrice', e.target.value)} inputMode="decimal" /></label>
          <label>Max $<input value={q.maxPrice} onChange={e => set('maxPrice', e.target.value)} inputMode="decimal" /></label>
          <label>Min orders<input value={q.minOrders} onChange={e => set('minOrders', e.target.value)} inputMode="numeric" /></label>
          <label>Min positive %<input value={q.minRating} onChange={e => set('minRating', e.target.value)} inputMode="numeric" /></label>
          <button className="primary" disabled={!!busy}>Search</button>
        </div>
      </form>

      {busy && <div className="busy"><span className="spin" />{busy}</div>}

      {res && (
        <>
          <div className="toolbar">
            <b>{chosen.length} selected</b>
            <span className="hint">{items.length} shown · {res.total.toLocaleString()} on AliExpress</span>
            <button className="ghost" onClick={() => selectAll(true)}>Select all</button>
            <button className="ghost" onClick={() => selectAll(false)}>Clear</button>
            <span className="grow" />
            <div className="seg">
              <button type="button" className={publish ? 'on' : ''} onClick={() => setPublish(true)}>Publish</button>
              <button type="button" className={!publish ? 'on' : ''} onClick={() => setPublish(false)}>Draft</button>
            </div>
            {publish && <BoardSelect boards={boards} board={board} pickBoard={pickBoard} pinReady={pinReady} />}
            <button className="primary" disabled={!!busy || !chosen.length} onClick={addToQueue}>Add {chosen.length || ''} to queue</button>
          </div>
          {items.length === 0 && <p className="hint">No products matched. Try another keyword or loosen the filters.</p>}
          <div className="grid">
            {items.map(it => <FindCard key={it.productId} it={it} onChange={p => update(it.productId, p)} />)}
          </div>
          {res.found > 0 && items.length < res.total && (
            <p style={{ textAlign: 'center', margin: '18px 0' }}>
              <button className="ghost" disabled={!!busy} onClick={() => search(page + 1)}>Load more</button>
            </p>
          )}
        </>
      )}
    </section>
  )
}

function FindCard({ it, onChange }) {
  const toggle = l => onChange({ labels: it.labels.includes(l) ? it.labels.filter(x => x !== l) : [...it.labels, l] })
  return (
    <div className={`pcard ${it.selected ? 'sel' : ''} ${it.state ? 'done' : ''}`}>
      <div className="pimg">
        <img src={imgSrc(it.image)} alt="" loading="lazy" />
        {!it.state && <label className="check"><input type="checkbox" checked={!!it.selected} onChange={e => onChange({ selected: e.target.checked })} /></label>}
        {it.oldPrice > it.price && <span className="off">-{Math.round((1 - it.price / it.oldPrice) * 100)}%</span>}
      </div>
      <div className="pbody">
        {it.state && <span className={`badge ${it.state === 'posted' ? 'posted' : 'draft'}`}>{it.state === 'posted' ? 'Already posted' : 'In queue'}</span>}
        {it.problems.length > 0 && <div className="warn">&#9888; {it.problems.join(' · ')}</div>}
        <textarea className="title" rows={2} value={it.title} onChange={e => onChange({ title: e.target.value })} />
        <div className="stats">
          <b>${it.price.toFixed(2)}</b>
          {it.oldPrice > it.price && <s>${it.oldPrice.toFixed(2)}</s>}
          {it.positive && <span>&#9733; {it.positive}</span>}
          <span>{it.orders.toLocaleString()} sold</span>
          {it.commission && <span className="comm">{it.commission} commission</span>}
        </div>
        <div className="chips">
          {LABELS.map(l => <button key={l} className={it.labels.includes(l) ? 'chip on' : 'chip'} onClick={() => toggle(l)}>{l}</button>)}
        </div>
        <p className="raw" title={it.product.product_title}>{it.category} · {it.product.product_title}</p>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- Post queue */
function PostQueue({ notify }) {
  const [data, setData] = useState(null)
  const load = () => api.postQueue().then(setData).catch(() => {})
  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])
  if (!data) return <div className="busy"><span className="spin" />Loading&#8230;</div>
  async function remove(id) {
    await api.removeQueued(id).catch(e => notify(e.message))
    load()
  }
  return (
    <section style={{ marginBottom: 30 }}>
      <header className="page-head"><div><h1>Post Queue</h1>
        <p>{data.queued} waiting &#183; {data.postedToday}/{data.dailyLimit} posted in the last 24 h &#183; one post every {data.intervalMin} min
          {data.queued > 0 && <> &#183; next around {fmtTime(data.next)}</>}. Keep the dashboard running.</p></div></header>
      <div className="list">
        {data.items.length === 0 && <p className="hint">Nothing queued. Use Find Products to add some.</p>}
        {data.items.map(x => (
          <div key={x.productId + x.status} className="lrow">
            {x.image ? <img src={imgSrc(x.image)} alt="" /> : <span className="ph" />}
            <div>
              {x.url ? <a href={x.url} target="_blank" rel="noreferrer"><b>{x.title}</b></a> : <b>{x.title}</b>}
              <small>{x.status === 'posted' ? `${x.publish ? 'Published' : 'Draft saved'} ${fmtTime(x.doneAt)}`
                : x.status === 'failed' ? `Failed: ${x.error}` : x.publish ? 'Will publish' : 'Will save as draft'}</small>
            </div>
            {x.status === 'queued' && <button className="ghost" onClick={() => remove(x.productId)}>Remove</button>}
            <span className={`badge ${x.status === 'posted' ? 'ok' : x.status === 'failed' ? 'error' : 'draft'}`}>{x.status}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------- Auto price update */
function AutoUpdate({ notify }) {
  const [st, setSt] = useState(null)
  const load = () => api.autoStatus().then(setSt).catch(() => {})
  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [])
  if (!st) return null

  async function runNow() {
    await api.autoRun().catch(e => notify(e.message))
    notify('Auto update started. It runs in the background and takes a few minutes.')
    setTimeout(load, 1500)
  }
  async function draft(u) {
    if (!confirm(`Move "${u.title}" back to draft?`)) return
    const r = await api.draftUnavailable(u.postId).catch(e => ({ ok: false, message: e.message }))
    notify(r.ok ? 'Moved to draft.' : r.message)
    load()
  }
  const last = st.last
  return (
    <div className="card auto-card">
      <div className="auto-head">
        <div>
          <h3>Daily auto update {st.enabled ? <span className="badge ok">On</span> : <span className="badge draft">Off</span>}</h3>
          <p className="hint">
            {st.running ? 'Running now…'
              : st.lastRun ? `Last run ${fmtTime(st.lastRun)} · next ${fmtTime(st.next)}`
              : st.enabled ? 'First run starts a couple of minutes after the dashboard opens.' : 'Turn on with AUTO_PRICE_UPDATE=true in .env'}
          </p>
          {last && <p className="hint">{last.found}/{last.links} products found · {last.changed} posts updated · {last.unavailable} unavailable</p>}
        </div>
        <button className="secondary" disabled={st.running} onClick={runNow}>{st.running ? 'Running…' : 'Run now'}</button>
      </div>
      {st.unavailable.length > 0 && (
        <div className="unavail">
          <b>Unavailable products</b>
          <p className="hint">Not found on AliExpress for {st.days}+ daily checks in a row.
            {st.autoDraft ? ' Live posts are moved to draft automatically.' : ' Check them, then move to draft if they are really gone.'}</p>
          {st.unavailable.map(u => (
            <div key={u.postId} className="sum-row">
              <b className={u.status === 'LIVE' ? 'bad' : ''}>{u.status}</b>
              {u.url ? <a href={u.url} target="_blank" rel="noreferrer"><span>{u.title}</span></a> : <span>{u.title}</span>}
              <small>{u.days} checks · {u.status === 'LIVE' && <button className="ghost" onClick={() => draft(u)}>Move to draft</button>}</small>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
