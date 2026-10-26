import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const LABELS = ['Deals', 'Under $25', 'Home', 'Kitchen', 'Organization', 'Beauty', 'Tech', 'Fashion', 'Halloween', 'Gift Ideas']
const TABS = [['new', 'New Posts'], ['posts', 'Blog Posts'], ['prices', 'Price Update'], ['history', 'History']]

export default function App() {
  const [tab, setTab] = useState('new')
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
        {tab === 'new' && <NewPosts notify={setToast} onPosted={() => api.status().then(setStatus)} />}
        {tab === 'posts' && <BlogPosts notify={setToast} />}
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
        <li className="ok">&#9679; Tracking: {s.trackingId}</li>
      </ul>
      <small>Filter: &#8805;{s.filters.minPositive}% positive, &#8805;{s.filters.minOrders} orders, &#8804;${s.filters.maxPrice}</small>
      <small>{s.published} links posted by this tool</small>
    </div>
  )
}

/* ------------------------------------------------------------- New posts */
function NewPosts({ notify, onPosted }) {
  const [text, setText] = useState('')
  const [items, setItems] = useState([])
  const [busy, setBusy] = useState('')

  async function loadFile() {
    const r = await api.linksFile()
    setText(r.text.split('\n').filter(l => l.trim() && !l.startsWith('#')).join('\n'))
  }

  async function preview() {
    if (!text.trim()) return notify('Paste at least one AliExpress link.')
    setBusy('Fetching product details from AliExpress…')
    try {
      const r = await api.preview(text)
      setItems(r.items.map(it => ({ ...it, selected: it.status === 'ok' })))
    } catch (e) { notify(e.message) }
    setBusy('')
  }

  const update = (i, patch) => setItems(items.map((it, j) => (j === i ? { ...it, ...patch } : it)))
  const chosen = items.filter(it => it.selected && it.content)

  async function send(publish) {
    if (!chosen.length) return notify('Select at least one product.')
    if (publish && !confirm(`Publish ${chosen.length} post(s) live on the blog?`)) return
    setBusy(publish ? 'Publishing…' : 'Saving drafts…')
    try {
      const r = await api.post(chosen, publish)
      const okLinks = new Set(r.results.filter(x => x.ok).map(x => x.link))
      setItems(items.map(it => okLinks.has(it.link)
        ? { ...it, selected: false, status: 'posted', message: r.results.find(x => x.link === it.link).url } : it))
      const fails = r.results.filter(x => !x.ok)
      notify(`${okLinks.size} ${publish ? 'published' : 'saved as draft'}${fails.length ? `, ${fails.length} failed` : ''}.`)
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
        <textarea value={text} onChange={e => setText(e.target.value)} rows={5}
          placeholder={'https://s.click.aliexpress.com/e/_xxxx\nhttps://s.click.aliexpress.com/e/_yyyy | Home, Gift Ideas'} />
        <div className="row">
          <button className="ghost" onClick={loadFile}>Load links.txt</button>
          <span className="hint">One link per line. Optional labels after <code>|</code></span>
          <button className="primary" onClick={preview} disabled={!!busy}>Preview products</button>
        </div>
      </div>

      {busy && <div className="busy"><span className="spin" />{busy}</div>}

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
        <img src={it.image} alt="" />
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
      </div>
    </div>
  )
}

/* ------------------------------------------------------------- Blog posts */
function BlogPosts({ notify }) {
  const [items, setItems] = useState(null)
  const [filter, setFilter] = useState('ALL')
  useEffect(() => { api.posts().then(r => setItems(r.items)).catch(e => notify(e.message)) }, [])
  if (!items) return <div className="busy"><span className="spin" />Loading posts&#8230;</div>
  const shown = items.filter(p => filter === 'ALL' || p.status === filter)
  return (
    <section>
      <header className="page-head">
        <div><h1>Blog Posts</h1><p>{items.filter(p => p.status === 'LIVE').length} live &#183; {items.filter(p => p.status === 'DRAFT').length} drafts</p></div>
        <div className="seg">
          {['ALL', 'LIVE', 'DRAFT'].map(f => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f}</button>)}
        </div>
      </header>
      <div className="list">
        {shown.map(p => (
          <a key={p.id} className="lrow" href={p.status === 'LIVE' ? p.url : `https://www.blogger.com/blog/post/edit/2976840353661435945/${p.id}`} target="_blank" rel="noreferrer">
            {p.image ? <img src={p.image} alt="" /> : <span className="ph" />}
            <div>
              <b>{p.title}</b>
              <small>{p.labels.join(' · ')}</small>
            </div>
            <span className={`badge ${p.status === 'LIVE' ? 'ok' : 'draft'}`}>{p.status}</span>
          </a>
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
