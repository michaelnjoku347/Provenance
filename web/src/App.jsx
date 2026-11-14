import { useEffect, useRef, useState } from 'react'
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  CircleHelp,
  Clipboard,
  Flag,
  ImagePlus,
  Link2,
  LoaderCircle,
  Search,
  Shield,
  X,
} from 'lucide-react'
import Logo from './components/Logo.jsx'
import { runCheck, STAGE_FALLBACK } from './lib/api.js'
import { cn } from './lib/cn.js'

const VERDICTS = {
  'Likely Real': { color: '#C8F54A', soft: 'rgba(200,245,74,0.12)', label: 'Likely Real' },
  'Likely AI or Fake': { color: '#FF5C7A', soft: 'rgba(255,92,122,0.12)', label: 'Likely AI or Fake' },
  'Out of Context': { color: '#FFB020', soft: 'rgba(255,176,32,0.12)', label: 'Out of Context' },
  Unverified: { color: '#8B97A6', soft: 'rgba(139,151,166,0.12)', label: 'Unverified' },
}

const STAMPS = {
  'Likely Real': ['REAL'],
  'Likely AI or Fake': ['AI-MADE'],
  'Out of Context': ['OUT OF', 'CONTEXT'],
  Unverified: ['UNVERIFIED'],
}

const HOW = [
  ['01', 'Read the file', 'EXIF and C2PA'],
  ['02', 'Search the web', 'You.com sources'],
  ['03', 'Score each clue', 'For, against, missed'],
  ['04', 'Stamp a receipt', 'Verdict and limits'],
]

const STATUS_LABEL = {
  queued: 'Waiting',
  running: 'Running',
  ok: 'Done',
  skipped: 'Skipped',
  error: 'Failed',
}

const RECENT_KEY = 'provenance-recent'

function themeFor(verdict) {
  return VERDICTS[verdict] || VERDICTS.Unverified
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const value = String(reader.result || '')
      const comma = value.indexOf(',')
      resolve(comma >= 0 ? value.slice(comma + 1) : value)
    }
    reader.onerror = () => reject(new Error('Could not read that file.'))
    reader.readAsDataURL(file)
  })
}

function acceptedFile(file) {
  const type = (file.type || '').toLowerCase()
  const name = (file.name || '').toLowerCase()
  const okType = ['image/jpeg', 'image/png', 'image/webp'].includes(type)
  const okName = /\.(jpe?g|png|webp)$/.test(name)
  if (!okType && !okName) return 'Use a JPEG, PNG, or WebP file.'
  if (file.size > 8_000_000) return 'That file is larger than 8 MB.'
  return ''
}

function loadRecents() {
  try {
    const saved = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
    return Array.isArray(saved) ? saved.slice(0, 4) : []
  } catch {
    return []
  }
}

export default function App() {
  const [health, setHealth] = useState(null)
  const [meta, setMeta] = useState(null)
  const [demos, setDemos] = useState([])
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState('')
  const [claim, setClaim] = useState('')
  const [imageUrl, setImageUrl] = useState('')
  const [demoId, setDemoId] = useState('')
  const [drag, setDrag] = useState(false)
  const [busy, setBusy] = useState(false)
  const [stages, setStages] = useState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [helpOpen, setHelpOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [flagOpen, setFlagOpen] = useState(false)
  const [flagReason, setFlagReason] = useState('disagree')
  const [flagExpected, setFlagExpected] = useState('')
  const [flagNote, setFlagNote] = useState('')
  const [flagState, setFlagState] = useState('')
  const [recents, setRecents] = useState([])
  const inputRef = useRef(null)
  const stageRef = useRef(null)

  useEffect(() => {
    setRecents(loadRecents())
    fetch('/api/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth(null))
    fetch('/api/meta')
      .then((r) => r.json())
      .then(setMeta)
      .catch(() => setMeta(null))
    fetch('/api/demos')
      .then((r) => r.json())
      .then((body) => setDemos(body.demos || []))
      .catch(() => setDemos([]))
  }, [])

  const autoRan = useRef(false)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const wanted = params.get('demo')
    if (!wanted || autoRan.current) return
    autoRan.current = true
    setDemoId(wanted)
    setPreview(`/api/demos/${wanted}/image`)
    fetch('/api/demos')
      .then((r) => r.json())
      .then((body) => {
        const demo = (body.demos || []).find((item) => item.id === wanted)
        if (demo?.claim) setClaim(demo.claim)
      })
      .catch(() => {})
    const timer = setTimeout(() => {
      void startCheck({ demo_id: wanted })
    }, 200)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function clearPreview() {
    if (preview && preview.startsWith('blob:')) URL.revokeObjectURL(preview)
  }

  function remember(payload) {
    const row = {
      receipt_id: payload.receipt_id,
      verdict: payload.verdict,
      confidence: payload.confidence,
      claim: (payload.claim?.text || '').slice(0, 96),
      demo_id: payload.demo_id || '',
      at: payload.checked_at || '',
    }
    setRecents((prev) => {
      const next = [row, ...prev.filter((item) => item.receipt_id !== row.receipt_id)].slice(0, 4)
      try {
        localStorage.setItem(RECENT_KEY, JSON.stringify(next))
      } catch {
        // recent checks are a convenience; the receipt itself is the record
      }
      return next
    })
  }

  function onPickFile(next) {
    if (!next) return
    const problem = acceptedFile(next)
    if (problem) {
      setError(problem)
      return
    }
    clearPreview()
    setFile(next)
    setPreview(URL.createObjectURL(next))
    setDemoId('')
    setError('')
    setResult(null)
  }

  function chooseDemo(demo) {
    clearPreview()
    setFile(null)
    setDemoId(demo.id)
    setClaim(demo.claim || '')
    setPreview(`/api/demos/${demo.id}/image`)
    setError('')
    setResult(null)
  }

  function resetDesk() {
    clearPreview()
    setFile(null)
    setPreview('')
    setDemoId('')
    setClaim('')
    setImageUrl('')
    setResult(null)
    setError('')
    setStages([])
    setBusy(false)
    setFlagOpen(false)
    setFlagState('')
  }

  async function startCheck(overrides = {}) {
    const body = { ...overrides }
    const usingDemo = body.demo_id || demoId
    if (usingDemo && !body.image_base64) {
      body.demo_id = usingDemo
      if (!body.claim) body.claim = claim
      if (!body.image_url) body.image_url = imageUrl
    } else {
      const chosen = file
      if (!chosen && !body.image_base64) {
        setError('Drop a viral image, or pick one of the demos.')
        return
      }
      if (chosen && !body.image_base64) {
        body.image_base64 = await fileToBase64(chosen)
        body.filename = chosen.name
        body.media_type = chosen.type || 'image/jpeg'
      }
      if (!body.claim) body.claim = claim
      if (!body.image_url) body.image_url = imageUrl
    }

    setBusy(true)
    setError('')
    setResult(null)
    setFlagOpen(false)
    setFlagState('')
    setStages(
      STAGE_FALLBACK.map((step) => ({
        id: step.id,
        label: step.label,
        status: 'queued',
        detail: '',
        flags: [],
      })),
    )
    stageRef.current?.scrollTo({ top: 0 })

    try {
      await runCheck(body, {
        onStage: (stage) => {
          setStages((prev) => {
            const next = prev.length ? [...prev] : STAGE_FALLBACK.map((s) => ({ ...s, status: 'queued', detail: '', flags: [] }))
            const index = next.findIndex((item) => item.id === stage.id)
            const row = {
              id: stage.id,
              label: stage.label || STAGE_FALLBACK.find((s) => s.id === stage.id)?.label || stage.id,
              status: stage.status,
              detail: stage.detail || '',
              flags: stage.flags || [],
            }
            if (index >= 0) next[index] = row
            else next.push(row)
            return next
          })
        },
        onResult: (payload) => {
          setResult(payload)
          setBusy(false)
          if (payload.preview_url) setPreview(payload.preview_url)
          remember(payload)
          requestAnimationFrame(() => stageRef.current?.scrollTo({ top: 0, behavior: 'smooth' }))
        },
      })
    } catch (err) {
      setBusy(false)
      setError(err.message || 'The check could not be finished.')
    }
  }

  async function copyReceipt() {
    if (!result) return
    await navigator.clipboard.writeText(JSON.stringify(result, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  async function submitFlag(event) {
    event.preventDefault()
    if (!result) return
    const payload = {
      receipt_id: result.receipt_id,
      verdict: result.verdict,
      reason: flagReason,
      expected: flagExpected,
      note: flagNote,
    }
    try {
      const key = 'provenance-feedback'
      const prior = JSON.parse(localStorage.getItem(key) || '[]')
      prior.push({ ...payload, at: new Date().toISOString() })
      localStorage.setItem(key, JSON.stringify(prior))
    } catch {
      // local storage is a backup; the file on the server is the record that matters
    }
    try {
      const response = await fetch('/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!response.ok) throw new Error('Could not record that flag.')
      setFlagState('saved')
      setFlagOpen(false)
    } catch (err) {
      setFlagState(err.message || 'Could not record that flag.')
    }
  }

  function openRecent(item) {
    if (busy || !item.demo_id) return
    const demo = demos.find((entry) => entry.id === item.demo_id)
    if (!demo) return
    chooseDemo(demo)
    void startCheck({ demo_id: demo.id, claim: demo.claim })
  }

  const currentPreview = preview || (demoId ? `/api/demos/${demoId}/image` : '')
  const selectedDemo = demos.find((demo) => demo.id === demoId)
  const mode = busy ? 'live' : result ? 'receipt' : currentPreview ? 'ready' : 'idle'
  const connected = Boolean(health?.keys?.youcom)

  return (
    <div className="flex min-h-dvh flex-col bg-ink text-paper lg:h-dvh lg:overflow-hidden">
      <header className="z-30 shrink-0 border-b border-line bg-ink/90 backdrop-blur-md">
        <div className="flex h-14 items-center justify-between gap-3 px-3 sm:px-4">
          <button type="button" onClick={resetDesk} className="flex items-center gap-2.5 text-left">
            <Logo className="h-8 w-8" />
            <span>
              <span className="block text-[15px] font-semibold leading-none tracking-tight">Provenance</span>
              <span className="mt-1 block font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Newsroom desk</span>
            </span>
          </button>
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'hidden items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider sm:inline-flex',
                connected ? 'border-lime/20 bg-lime/10 text-lime' : 'border-line text-mist',
              )}
            >
              <span className={cn('h-1.5 w-1.5 rounded-full', connected ? 'bg-lime' : 'bg-mist/70')} />
              {connected ? 'You.com connected' : 'You.com offline'}
            </span>
            <button
              type="button"
              onClick={() => setHelpOpen(true)}
              className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-2.5 py-1.5 text-[13px] text-paper/90 transition hover:border-lime/40 hover:text-lime sm:px-3"
            >
              <CircleHelp className="h-3.5 w-3.5" />
              What can I check?
            </button>
            <a
              href="/docs"
              className="hidden rounded-full border border-line px-3 py-1.5 text-sm text-mist transition hover:text-paper sm:inline-flex"
            >
              API
            </a>
          </div>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(320px,392px)_minmax(0,1fr)]">
        <aside className="intake flex min-h-0 flex-col gap-2.5 overflow-y-auto border-line px-3 py-3 sm:px-3.5 lg:border-r">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-lime">Image check</p>
            <h1 className="mt-1 font-serif text-[1.85rem] leading-none tracking-tight">Drop a viral image</h1>
            <p className="mt-1.5 text-[13px] leading-5 text-mist">
              Real, AI-made, or out of context — with the clues that led there. The checker can be wrong. The receipt is yours to judge.
            </p>
          </div>

          <div className="lg:hidden">
            <DemoTray demos={demos} demoId={demoId} onChoose={chooseDemo} layout="strip" />
          </div>

          <label
            onDragOver={(e) => {
              e.preventDefault()
              setDrag(true)
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDrag(false)
              onPickFile(e.dataTransfer.files?.[0])
            }}
            className={cn(
              'group relative flex cursor-pointer overflow-hidden rounded-2xl border border-dashed bg-[#10161d] text-left transition',
              drag ? 'border-lime bg-lime/5' : 'border-line hover:border-lime/35',
              currentPreview ? 'min-h-0 items-center gap-3 p-2' : 'min-h-[92px] flex-col items-center justify-center px-4 py-3 text-center',
            )}
          >
            {currentPreview ? (
              <>
                <img src={currentPreview} alt="" className="h-14 w-[4.75rem] shrink-0 rounded-lg object-cover" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{file?.name || selectedDemo?.title || 'Image on the desk'}</span>
                  <span className="mt-0.5 block text-xs text-mist">Click or drop to replace. Up to 8 MB.</span>
                </span>
              </>
            ) : (
              <>
                <span className="flex h-9 w-9 items-center justify-center rounded-full border border-line bg-panel-2">
                  <ImagePlus className="h-4 w-4 text-lime" />
                </span>
                <span className="mt-2 block text-sm font-medium">Drop a JPEG, PNG, or WebP</span>
                <span className="mt-0.5 block text-xs text-mist">Up to 8 MB. Click to browse.</span>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
              className="hidden"
              onChange={(e) => onPickFile(e.target.files?.[0])}
            />
          </label>

          <div className="space-y-2 rounded-2xl border border-line bg-[#10161d] p-2.5">
            <label className="block">
              <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Caption or claim</span>
              <textarea
                value={claim}
                onChange={(e) => setClaim(e.target.value)}
                rows={2}
                placeholder="What is this image being said to show?"
                className="mt-1.5 w-full resize-none rounded-xl border border-line bg-ink px-3 py-2 text-sm leading-5 text-paper placeholder:text-mist/60 focus:border-lime/50"
              />
            </label>
            <label className="block">
              <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Public image link, optional</span>
              <div className="relative mt-1.5">
                <Link2 className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-mist" />
                <input
                  value={imageUrl}
                  onChange={(e) => setImageUrl(e.target.value)}
                  placeholder="https://… used only for reverse image search"
                  className="w-full rounded-xl border border-line bg-ink py-2 pl-9 pr-3 text-sm text-paper placeholder:text-mist/60 focus:border-lime/50"
                />
              </div>
            </label>
            <button
              type="button"
              disabled={busy}
              onClick={() => void startCheck()}
              className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-lime px-4 py-2.5 text-sm font-semibold text-ink shadow-[0_0_24px_rgba(200,245,74,0.16)] transition hover:bg-lime/90 disabled:cursor-wait disabled:opacity-70"
            >
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {busy ? 'Checking…' : 'Check image'}
            </button>
          </div>

          <div className="hidden lg:mt-auto lg:block">
            <DemoTray demos={demos} demoId={demoId} onChoose={chooseDemo} layout="stack" />
          </div>
        </aside>

        <section className="flex min-h-[70vh] min-w-0 flex-col bg-[#080c11] lg:min-h-0">
          <div ref={stageRef} className="stage-scroll flex min-h-0 flex-1 flex-col overflow-y-auto">
            {error ? (
              <div className="mx-4 mt-4 flex items-start gap-2 rounded-xl border border-rose/30 bg-rose/10 px-3 py-2.5 text-sm text-paper lg:mx-5">
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose" />
                <span>{error}</span>
              </div>
            ) : null}

            {mode === 'idle' ? <StageIdle onHelp={() => setHelpOpen(true)} /> : null}
            {mode === 'ready' ? (
              <ReadyStage src={currentPreview} title={file?.name || selectedDemo?.title || 'Selected image'} claim={claim} />
            ) : null}
            {mode === 'live' ? (
              <>
                <Hero src={currentPreview} alt="Image being checked">
                  <div className="absolute left-4 top-4 inline-flex items-center gap-2 rounded-full bg-ink/75 px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-lime backdrop-blur">
                    <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-lime" />
                    Live
                  </div>
                </Hero>
                <ProgressPanel stages={stages} />
              </>
            ) : null}
            {mode === 'receipt' && result ? (
              <>
                <Hero src={currentPreview} alt="Checked image">
                  <div className="absolute right-5 top-5 sm:right-7 sm:top-6">
                    <Stamp verdict={result.verdict} />
                  </div>
                  <div className="absolute inset-x-0 bottom-0 p-4 sm:p-5">
                    <div className="max-w-xl">
                      <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-white/70">Receipt {result.receipt_id}</div>
                      <p className="mt-1 line-clamp-2 text-sm leading-5 text-white">{result.summary}</p>
                      <div className="mt-3 flex items-center gap-3">
                        <div className="h-1.5 w-36 overflow-hidden rounded-full bg-white/20">
                          <div className="h-full rounded-full" style={{ width: `${result.confidence}%`, background: themeFor(result.verdict).color }} />
                        </div>
                        <span className="font-mono text-xs text-white">{result.confidence}%</span>
                        <span className="font-mono text-[10px] uppercase tracking-wider text-white/60">Not a guarantee</span>
                      </div>
                    </div>
                  </div>
                </Hero>
                <Receipt
                  result={result}
                  copied={copied}
                  onCopy={copyReceipt}
                  flagOpen={flagOpen}
                  setFlagOpen={setFlagOpen}
                  flagReason={flagReason}
                  setFlagReason={setFlagReason}
                  flagExpected={flagExpected}
                  setFlagExpected={setFlagExpected}
                  flagNote={flagNote}
                  setFlagNote={setFlagNote}
                  flagState={flagState}
                  onFlag={submitFlag}
                />
              </>
            ) : null}
          </div>
        </section>
      </div>

      <footer className="shrink-0 border-t border-line bg-[#0c1117] px-3 py-2.5 sm:px-4">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <ol className="flex gap-x-4 gap-y-1 overflow-x-auto">
            {HOW.map(([num, title, detail]) => (
              <li key={num} className="flex items-baseline gap-2 whitespace-nowrap">
                <span className="font-mono text-[10px] text-lime">{num}</span>
                <span className="text-xs font-medium">{title}</span>
                <span className="hidden text-[11px] text-mist xl:inline">{detail}</span>
              </li>
            ))}
          </ol>
          <div className="flex min-w-0 items-center gap-2 overflow-x-auto">
            <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Recent</span>
            {recents.length ? (
              recents.map((item) => {
                const theme = themeFor(item.verdict)
                return (
                  <button
                    key={item.receipt_id}
                    type="button"
                    onClick={() => openRecent(item)}
                    disabled={!item.demo_id || busy}
                    title={item.claim || item.verdict}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-ink px-2 py-1 text-[11px] text-paper/90 transition hover:border-lime/40 disabled:cursor-default disabled:opacity-80"
                  >
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: theme.color }} />
                    <span className="max-w-[9rem] truncate">{item.verdict}</span>
                    <span className="font-mono text-mist">{item.confidence}%</span>
                  </button>
                )
              })
            ) : (
              <span className="text-xs text-mist">No checks on this desk yet.</span>
            )}
          </div>
        </div>
      </footer>

      {helpOpen ? <HelpPanel meta={meta} onClose={() => setHelpOpen(false)} /> : null}
    </div>
  )
}

function DemoTray({ demos, demoId, onChoose, layout }) {
  if (!demos.length) {
    return <p className="text-xs text-mist">Sample cases load with the desk.</p>
  }
  const strip = layout === 'strip'
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <h2 className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Case files</h2>
        <span className="font-mono text-[10px] text-mist">{demos.length} samples</span>
      </div>
      <div className={cn(strip ? '-mx-1 flex gap-2 overflow-x-auto px-1 pb-1' : 'grid grid-cols-3 gap-2')}>
        {demos.map((demo, index) => {
          const selected = demoId === demo.id
          return (
            <button
              key={demo.id}
              type="button"
              onClick={() => onChoose(demo)}
              aria-pressed={selected}
              className={cn(
                'overflow-hidden rounded-xl border bg-[#10161d] text-left transition hover:border-lime/40',
                strip ? 'w-[15.5rem] shrink-0 snap-start' : 'flex flex-col',
                selected ? 'border-lime/70 ring-1 ring-lime/30' : 'border-line',
              )}
            >
              <span className="relative block">
                <img
                  src={`/api/demos/${demo.id}/image`}
                  alt=""
                  className={cn('w-full object-cover', strip ? 'h-28' : 'h-[4.75rem]')}
                />
                <span className="absolute left-1.5 top-1.5 rounded bg-ink/80 px-1 py-0.5 font-mono text-[9px] text-lime">0{index + 1}</span>
                {selected && !strip ? (
                  <span className="absolute bottom-1.5 right-1.5 rounded bg-ink/80 px-1 py-0.5 font-mono text-[9px] uppercase tracking-wider text-lime">
                    On stage
                  </span>
                ) : null}
              </span>
              <span className={cn('block min-w-0', strip ? 'px-2.5 py-2' : 'px-1.5 py-1.5')}>
                <span className={cn('block font-medium leading-4', strip ? 'text-[13px]' : 'line-clamp-2 min-h-8 text-[12px]')}>{demo.title}</span>
                {strip ? <span className="mt-0.5 block line-clamp-2 text-[11px] leading-4 text-mist">{demo.claim}</span> : null}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function CropMarks() {
  const corner = 'absolute h-4 w-4 border-lime/50'
  return (
    <>
      <span className={cn(corner, 'left-4 top-4 border-l border-t')} />
      <span className={cn(corner, 'right-4 top-4 border-r border-t')} />
      <span className={cn(corner, 'bottom-4 left-4 border-b border-l')} />
      <span className={cn(corner, 'bottom-4 right-4 border-b border-r')} />
    </>
  )
}

function StageIdle({ onHelp }) {
  return (
    <div className="flex h-full min-h-[520px] flex-col p-4 sm:p-5">
      <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden rounded-2xl border border-line bg-[radial-gradient(ellipse_at_center,rgba(200,245,74,0.07),transparent_62%)]">
        <CropMarks />
        <Logo className="h-14 w-14" />
        <h2 className="mt-4 px-6 text-center font-serif text-3xl tracking-tight sm:text-4xl">A receipt, not a black box</h2>
        <p className="mt-3 max-w-md px-6 text-center text-sm leading-6 text-mist">
          The picture lands here. You will see each step as it happens, then how every clue scored — including the ones we could not run.
        </p>
        <button type="button" onClick={onHelp} className="mt-4 text-sm text-lime hover:underline">
          What can I check?
        </button>
      </div>
      <ol className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
        {[
          ['01', 'The file is read for EXIF and C2PA.'],
          ['02', 'You.com searches and opens sources.'],
          ['03', 'Each clue is scored for or against the claim.'],
          ['04', 'You get the verdict, the limits, and what to check next.'],
        ].map(([num, line]) => (
          <li key={num} className="rounded-xl border border-line bg-[#10161d] px-3 py-2.5">
            <div className="font-mono text-[10px] text-lime">{num}</div>
            <p className="mt-1 text-[12px] leading-4 text-mist">{line}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}

function ReadyStage({ src, title, claim }) {
  return (
    <div className="flex h-full min-h-[420px] flex-col">
      <div className="relative flex min-h-[280px] flex-1 items-center justify-center overflow-hidden p-4 sm:p-6">
        <div
          className="pointer-events-none absolute inset-0 opacity-50"
          style={{
            backgroundImage:
              'linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px)',
            backgroundSize: '28px 28px',
          }}
        />
        <img src={src} alt={title} className="relative max-h-full max-w-full rounded-xl shadow-[0_24px_80px_rgba(0,0,0,0.5)]" />
      </div>
      <div className="flex items-end justify-between gap-4 border-t border-line px-4 py-3 sm:px-5">
        <div className="min-w-0">
          <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-lime">On the desk</div>
          <div className="truncate text-sm font-medium">{title}</div>
          <p className="truncate text-xs text-mist">{claim || 'Add a caption, then check the image.'}</p>
        </div>
        <div className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-mist">Ready</div>
      </div>
    </div>
  )
}

function Hero({ src, alt, children }) {
  return (
    <div className="relative h-[220px] shrink-0 overflow-hidden bg-[#05070a] sm:h-[260px] lg:h-[280px]">
      {src ? <img src={src} alt={alt} className="h-full w-full object-cover" /> : null}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-[#070a0d] via-[#070a0d]/15 to-[#070a0d]/25" />
      {children}
    </div>
  )
}

function Stamp({ verdict }) {
  const theme = themeFor(verdict)
  const lines = STAMPS[verdict] || STAMPS.Unverified
  return (
    <div className="stamp" style={{ color: theme.color }} aria-label={verdict}>
      {lines.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>
  )
}

function ProgressPanel({ stages }) {
  const flagCount = stages.reduce((count, stage) => count + (stage.flags?.length || 0), 0)
  return (
    <div className="fade-up px-4 py-4 sm:px-5">
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-lime">Live check</p>
          <h2 className="mt-1 text-base font-semibold">Flags appear as each step finishes</h2>
        </div>
        <div className="font-mono text-[11px] text-mist">
          {flagCount} flag{flagCount === 1 ? '' : 's'}
        </div>
      </div>
      <ol className="mt-4">
        {stages.map((stage, index) => (
          <li key={stage.id} className="relative flex gap-3 pb-3.5">
            {index < stages.length - 1 ? <span className="absolute left-[7px] top-4 h-[calc(100%-4px)] w-px bg-line" /> : null}
            <StatusDot status={stage.status} />
            <div className="min-w-0 flex-1 rounded-xl border border-transparent px-2 py-0.5 transition" style={stage.status === 'running' ? { background: 'rgba(200,245,74,0.05)' } : undefined}>
              <div className="flex items-baseline justify-between gap-3">
                <div className="text-sm font-medium">{stage.label}</div>
                <div className={cn('font-mono text-[10px] uppercase tracking-wider', stage.status === 'running' ? 'text-lime' : 'text-mist')}>
                  {STATUS_LABEL[stage.status] || stage.status}
                </div>
              </div>
              {stage.detail ? <p className="mt-0.5 text-xs leading-5 text-mist">{stage.detail}</p> : null}
              {stage.flags?.length ? (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {stage.flags.map((flag, i) => (
                    <span
                      key={`${flag.label}-${i}`}
                      className={cn(
                        'flag-in rounded-full border border-line bg-ink px-2 py-0.5 text-[11px] text-paper/85',
                        flag.tone === 'fake' && 'border-rose/40 text-rose',
                        flag.tone === 'real' && 'border-lime/40 text-lime',
                        flag.tone === 'verdict' && 'border-amber/40 text-amber',
                      )}
                    >
                      {flag.label}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

function StatusDot({ status }) {
  if (status === 'running') return <span className="pulse-dot mt-1.5 h-2 w-2 shrink-0 rounded-full bg-lime" />
  if (status === 'ok') {
    return (
      <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-lime/15 text-lime">
        <Check className="h-3 w-3" />
      </span>
    )
  }
  if (status === 'error') return <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-rose" />
  if (status === 'skipped') return <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full border border-mist/40" />
  return <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-line" />
}

function Receipt({
  result,
  copied,
  onCopy,
  flagOpen,
  setFlagOpen,
  flagReason,
  setFlagReason,
  flagExpected,
  setFlagExpected,
  flagNote,
  setFlagNote,
  flagState,
  onFlag,
}) {
  const theme = themeFor(result.verdict)
  const groups = result.evidence_groups || { toward_real: [], toward_fake_or_ooc: [], couldnt_check: [] }
  const scores = result.scores || { real: 0, fake: 0, out_of_context: 0 }
  const total = Math.max(1, scores.real + scores.fake + scores.out_of_context)

  return (
    <div className="fade-up space-y-3 px-4 py-4 sm:px-5 sm:pb-6">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="rounded-2xl border border-line bg-[#10161d] p-4">
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">How strong the clues are</div>
              <div className="mt-1 text-3xl font-semibold tabular-nums" style={{ color: theme.color }}>
                {result.confidence}%
              </div>
            </div>
            <div className="text-right">
              <div className="text-[11px] text-mist">Not a guarantee</div>
              <div className="mt-1 text-sm font-medium" style={{ color: theme.color }}>
                {result.verdict}
              </div>
            </div>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-ink">
            <div className="h-full rounded-full" style={{ width: `${result.confidence}%`, background: theme.color }} />
          </div>
          <p className="mt-3 text-sm leading-6 text-paper/85">{result.confidence_note}</p>
        </section>

        {result.claim?.text ? (
          <section className="rounded-2xl border border-line bg-[#10161d] p-4">
            <h3 className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">The claim</h3>
            <p className="mt-2 text-sm leading-6">{result.claim.text}</p>
          </section>
        ) : (
          <section className="rounded-2xl border border-line bg-[#10161d] p-4 text-sm text-mist">No caption was attached to this check.</section>
        )}
      </div>

      <section className="rounded-2xl border border-line bg-[#10161d] p-4 sm:p-5">
        <h3 className="text-sm font-semibold">How this verdict was reached</h3>
        <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-ink">
          <div className="bg-lime" style={{ width: `${(100 * scores.real) / total}%` }} />
          <div className="bg-rose" style={{ width: `${(100 * scores.fake) / total}%` }} />
          <div className="bg-amber" style={{ width: `${(100 * scores.out_of_context) / total}%` }} />
        </div>
        <div className="mt-2 flex flex-wrap gap-4 font-mono text-[10px] uppercase tracking-wider text-mist">
          <span className="text-lime">Real {scores.real}</span>
          <span className="text-rose">Fake {scores.fake}</span>
          <span className="text-amber">Out of context {scores.out_of_context}</span>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <EvidenceBlock title="Points toward real" accent="text-lime" items={groups.toward_real} empty="Nothing scored toward real." />
          <EvidenceBlock
            title="Points toward fake / out of context"
            accent="text-amber"
            items={groups.toward_fake_or_ooc}
            empty="Nothing scored toward fake or out of context."
          />
        </div>
        <EvidenceBlock title="Couldn't check" accent="text-mist" items={groups.couldnt_check} empty="Every step in the pipeline ran." />
      </section>

      <section className="rounded-2xl border border-line bg-[#10161d] p-4 sm:p-5">
        <h3 className="text-sm font-semibold">Sources</h3>
        <ul className="mt-3 space-y-3">
          {(result.sources || []).length ? (
            result.sources.map((source) => (
              <li key={source.url} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-cyan">{hostOf(source.url)}</span>
                    {source.credible ? (
                      <span className="rounded-full border border-lime/20 bg-lime/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-lime">
                        Credible
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-0.5 text-sm">{source.title}</div>
                </div>
                <a href={source.url} target="_blank" rel="noreferrer" className="shrink-0 text-mist hover:text-lime">
                  <ArrowUpRight className="h-4 w-4" />
                </a>
              </li>
            ))
          ) : (
            <li className="text-sm text-mist">No sources were attached to this receipt.</li>
          )}
        </ul>
      </section>

      {(result.timeline || []).length ? (
        <section className="rounded-2xl border border-line bg-[#10161d] p-4 sm:p-5">
          <h3 className="text-sm font-semibold">Timeline</h3>
          <ol className="mt-3 space-y-3">
            {result.timeline.map((event, i) => (
              <li key={`${event.at}-${i}`} className="grid grid-cols-[7.5rem_1fr] gap-3 text-sm">
                <span className="font-mono text-[11px] text-mist">{event.at}</span>
                <span>{event.label}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className="rounded-2xl border border-line bg-[#10161d] p-4 sm:p-5">
        <h3 className="text-sm font-semibold">What you can do next</h3>
        <p className="mt-1 text-sm text-mist">These are checks you can run yourself if you want a second look.</p>
        <ul className="mt-4 space-y-4">
          {(result.next_steps || []).map((step) => (
            <li key={step.id}>
              <div className="text-sm font-medium">{step.title}</div>
              <p className="mt-0.5 text-sm leading-6 text-mist">{step.why}</p>
              {step.links?.length ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {step.links.map((link) => (
                    <a
                      key={link.url + link.label}
                      href={link.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[12px] text-paper transition hover:border-lime/40 hover:text-lime"
                    >
                      {link.label}
                      <ArrowUpRight className="h-3 w-3" />
                    </a>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      {result.caveats?.length > 1 ? (
        <section className="rounded-2xl border border-line bg-[#10161d] p-4 sm:p-5">
          <h3 className="text-sm font-semibold">What could make this wrong</h3>
          <ul className="mt-3 space-y-2">
            {result.caveats.slice(1).map((note) => (
              <li key={note.id} className="text-sm leading-6 text-mist">
                {note.text}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setFlagOpen((open) => !open)}
          className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-2 text-sm hover:border-amber/50 hover:text-amber"
        >
          <Flag className="h-3.5 w-3.5" />
          Disagree? Flag this result
        </button>
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-2 text-sm text-mist hover:text-paper"
        >
          <Clipboard className="h-3.5 w-3.5" />
          {copied ? 'Copied' : 'Copy receipt JSON'}
        </button>
        {flagState === 'saved' ? <span className="text-sm text-lime">Thanks. That flag was recorded.</span> : null}
        {flagState && flagState !== 'saved' ? <span className="text-sm text-rose">{flagState}</span> : null}
      </div>

      {flagOpen ? (
        <form onSubmit={onFlag} className="space-y-3 rounded-2xl border border-line bg-[#10161d] p-4 sm:p-5">
          <p className="text-sm leading-6 text-mist">
            If this reading looks off, say why. The flag is stored with the receipt so it can be reviewed later.
          </p>
          <label className="block text-sm">
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">What feels wrong</span>
            <select
              value={flagReason}
              onChange={(e) => setFlagReason(e.target.value)}
              className="mt-1.5 w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="disagree">I disagree with the verdict</option>
              <option value="missing_evidence">A clue seems missing</option>
              <option value="wrong_source">A source is off or unrelated</option>
              <option value="other">Something else</option>
            </select>
          </label>
          <label className="block text-sm">
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">What it should be, if you know</span>
            <select
              value={flagExpected}
              onChange={(e) => setFlagExpected(e.target.value)}
              className="mt-1.5 w-full rounded-xl border border-line bg-ink px-3 py-2 text-sm"
            >
              <option value="">I’m not sure</option>
              <option value="Likely Real">Likely Real</option>
              <option value="Likely AI or Fake">Likely AI or Fake</option>
              <option value="Out of Context">Out of Context</option>
              <option value="Unverified">Unverified</option>
            </select>
          </label>
          <label className="block text-sm">
            <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">A short note, optional</span>
            <textarea
              value={flagNote}
              onChange={(e) => setFlagNote(e.target.value)}
              rows={3}
              className="mt-1.5 w-full resize-none rounded-xl border border-line bg-ink px-3 py-2.5 text-sm leading-6"
            />
          </label>
          <button type="submit" className="rounded-full bg-paper px-4 py-2 text-sm font-medium text-ink">
            Record this flag
          </button>
        </form>
      ) : null}
    </div>
  )
}

function EvidenceBlock({ title, accent, items, empty }) {
  return (
    <div className="mt-1">
      <h4 className={cn('font-mono text-[10px] uppercase tracking-[0.16em]', accent)}>{title}</h4>
      {items?.length ? (
        <ul className="mt-2 divide-y divide-line">
          {items.map((item, i) => (
            <li key={`${item.title}-${i}`} className="flex items-start justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <div className="text-sm font-medium">{item.title}</div>
                <p className="mt-0.5 text-sm leading-6 text-mist">{item.why}</p>
                {item.url ? (
                  <a href={item.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-[12px] text-cyan hover:underline">
                    {hostOf(item.url)}
                    <ArrowUpRight className="h-3 w-3" />
                  </a>
                ) : null}
              </div>
              <div className={cn('shrink-0 font-mono text-sm tabular-nums', item.points > 0 ? accent : 'text-mist')}>
                {item.points > 0 ? `+${item.points}` : item.points < 0 ? item.points : '—'}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-mist">{empty}</p>
      )}
    </div>
  )
}

function HelpPanel({ meta, onClose }) {
  const accepted = meta?.accepted || {
    formats: ['JPEG', 'PNG', 'WebP'],
    max_mb: 8,
  }
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-ink/70 p-4 sm:items-center">
      <div className="max-h-[88vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-[#10161d] p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-lime">
              <Shield className="h-4 w-4" />
              <h2 className="text-lg font-semibold text-paper">What can I check?</h2>
            </div>
            <p className="mt-1 text-sm text-mist">What this desk accepts, and which domains it treats as more credible.</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-1 text-mist hover:text-paper">
            <X className="h-4 w-4" />
          </button>
        </div>
        <dl className="mt-5 space-y-4 text-sm">
          <div>
            <dt className="font-medium">File types</dt>
            <dd className="mt-1 text-mist">{(accepted.formats || []).join(', ')}. Maximum {accepted.max_mb || 8} MB.</dd>
          </div>
          <div>
            <dt className="font-medium">Links</dt>
            <dd className="mt-1 text-mist">
              {accepted.image_url || 'Optional public http or https URL of the same image, used only for reverse-image lookup.'} A caption or claim is optional, but it helps.
            </dd>
          </div>
          <div>
            <dt className="font-medium">Domains treated as credible</dt>
            <dd className="mt-2 flex flex-wrap gap-1.5">
              {(meta?.credible_domains || []).map((domain) => (
                <span key={domain} className="rounded-full border border-line bg-ink px-2 py-0.5 font-mono text-[11px] text-paper/80">
                  {domain}
                </span>
              ))}
            </dd>
          </div>
          <div>
            <dt className="font-medium">Fact-check outlets</dt>
            <dd className="mt-2 flex flex-wrap gap-1.5">
              {(meta?.factcheck_domains || []).map((domain) => (
                <span key={domain} className="rounded-full border border-line bg-ink px-2 py-0.5 font-mono text-[11px] text-paper/80">
                  {domain}
                </span>
              ))}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  )
}
