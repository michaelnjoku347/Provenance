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
  const inputRef = useRef(null)
  const receiptRef = useRef(null)

  useEffect(() => {
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
          setTimeout(() => receiptRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
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

  const currentPreview = preview || (demoId ? `/api/demos/${demoId}/image` : '')

  return (
    <div className="min-h-screen bg-ink text-paper">
      <header className="sticky top-0 z-30 border-b border-line/80 bg-ink/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-5">
          <div className="flex items-center gap-3">
            <Logo className="h-8 w-8" />
            <div>
              <div className="text-[15px] font-semibold tracking-tight">Provenance</div>
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Newsroom desk</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {health?.keys?.youcom ? (
              <span className="hidden items-center gap-1.5 rounded-full border border-lime/20 bg-lime/10 px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-lime sm:inline-flex">
                <span className="h-1.5 w-1.5 rounded-full bg-lime" />
                You.com connected
              </span>
            ) : (
              <span className="hidden rounded-full border border-line px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-mist sm:inline-flex">
                You.com offline
              </span>
            )}
            <button
              type="button"
              onClick={() => setHelpOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-sm text-paper/90 transition hover:border-lime/40 hover:text-lime"
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

      <main className="mx-auto grid max-w-6xl gap-6 px-5 py-8 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] lg:items-start">
        <section className="space-y-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-lime">Image check</p>
            <h1 className="mt-1 text-3xl font-semibold tracking-tight sm:text-[2.1rem]">Drop a viral image</h1>
            <p className="mt-2 max-w-md text-sm leading-6 text-mist">
              See whether it looks real, AI-made, or out of context — and exactly which clues led there. The checker can be wrong. The receipt is there so you can judge it yourself.
            </p>
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
              'group relative flex min-h-[200px] cursor-pointer flex-col items-center justify-center overflow-hidden rounded-2xl border border-dashed border-line bg-panel text-center transition',
              drag && 'border-lime bg-lime/5',
            )}
          >
            {currentPreview ? (
              <img src={currentPreview} alt="Selected file" className="absolute inset-0 h-full w-full object-cover opacity-80" />
            ) : null}
            <div className={cn('relative z-10 flex flex-col items-center gap-2 px-6 py-8', currentPreview && 'rounded-xl bg-ink/70 backdrop-blur-sm')}>
              <div className="flex h-10 w-10 items-center justify-center rounded-full border border-line bg-panel-2">
                <ImagePlus className="h-4 w-4 text-lime" />
              </div>
              <div className="text-sm font-medium">{file?.name || (demoId ? `${demoId} demo` : 'Drop a JPEG, PNG, or WebP')}</div>
              <div className="text-xs text-mist">Up to 8 MB. Click to browse.</div>
            </div>
            <input
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
              className="hidden"
              onChange={(e) => onPickFile(e.target.files?.[0])}
            />
          </label>

          <div className="space-y-3 rounded-2xl border border-line bg-panel p-4">
            <label className="block">
              <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Caption or claim</span>
              <textarea
                value={claim}
                onChange={(e) => setClaim(e.target.value)}
                rows={3}
                placeholder="What is this image being said to show?"
                className="mt-1.5 w-full resize-none rounded-xl border border-line bg-ink px-3 py-2.5 text-sm leading-6 text-paper placeholder:text-mist/60"
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
                  className="w-full rounded-xl border border-line bg-ink py-2.5 pl-9 pr-3 text-sm text-paper placeholder:text-mist/60"
                />
              </div>
            </label>
            <button
              type="button"
              disabled={busy}
              onClick={() => void startCheck()}
              className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-lime px-4 py-2.5 text-sm font-semibold text-ink transition hover:bg-lime/90 disabled:cursor-wait disabled:opacity-70"
            >
              {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {busy ? 'Checking…' : 'Check image'}
            </button>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Try a demo</h2>
            </div>
            <div className="grid gap-2 sm:grid-cols-3">
              {demos.map((demo) => (
                <button
                  key={demo.id}
                  type="button"
                  onClick={() => chooseDemo(demo)}
                  className={cn(
                    'overflow-hidden rounded-xl border border-line bg-panel text-left transition hover:border-lime/40',
                    demoId === demo.id && 'border-lime/60 ring-1 ring-lime/30',
                  )}
                >
                  <img src={`/api/demos/${demo.id}/image`} alt="" className="h-16 w-full object-cover" />
                  <div className="px-2.5 py-2">
                    <div className="text-xs font-medium">{demo.title}</div>
                    <div className="mt-0.5 line-clamp-2 text-[11px] leading-4 text-mist">{demo.claim}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section ref={receiptRef} className="min-h-[28rem]">
          {error ? (
            <div className="fade-up rounded-2xl border border-rose/30 bg-rose/10 p-5 text-sm leading-6 text-paper">
              <div className="flex items-center gap-2 font-medium text-rose">
                <CircleAlert className="h-4 w-4" />
                Something needs a look
              </div>
              <p className="mt-2 text-paper/80">{error}</p>
            </div>
          ) : null}

          {busy ? <ProgressPanel stages={stages} preview={currentPreview} /> : null}

          {!busy && result ? (
            <Receipt
              result={result}
              preview={currentPreview}
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
          ) : null}

          {!busy && !result && !error ? <EmptyState onHelp={() => setHelpOpen(true)} /> : null}
        </section>
      </main>

      {helpOpen ? <HelpPanel meta={meta} onClose={() => setHelpOpen(false)} /> : null}
    </div>
  )
}

function EmptyState({ onHelp }) {
  return (
    <div className="fade-up flex min-h-[28rem] flex-col justify-between rounded-2xl border border-line bg-panel p-6">
      <div>
        <Logo className="h-12 w-12" />
        <h2 className="mt-5 text-xl font-semibold">A receipt, not a black box</h2>
        <p className="mt-2 max-w-sm text-sm leading-6 text-mist">
          When you run a check, you will see each step as it happens, then how every clue scored — including the ones we could not run.
        </p>
      </div>
      <ol className="space-y-3 text-sm">
        {[
          'The file is read for EXIF and C2PA.',
          'You.com searches and opens sources.',
          'Each clue is scored for or against the claim.',
          'You get the verdict, the limits, and what to check next.',
        ].map((line, i) => (
          <li key={line} className="flex gap-3 text-mist">
            <span className="font-mono text-[11px] text-lime">0{i + 1}</span>
            {line}
          </li>
        ))}
      </ol>
      <button type="button" onClick={onHelp} className="self-start text-sm text-lime hover:underline">
        What can I check?
      </button>
    </div>
  )
}

function ProgressPanel({ stages, preview }) {
  return (
    <div className="fade-up rounded-2xl border border-line bg-panel p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-lime">Live check</p>
          <h2 className="mt-1 text-lg font-semibold">Working through the evidence</h2>
        </div>
        {preview ? <img src={preview} alt="" className="h-14 w-14 rounded-lg object-cover" /> : null}
      </div>
      <ol className="mt-5 space-y-0">
        {stages.map((stage, index) => (
          <li key={stage.id} className="relative flex gap-3 pb-4">
            {index < stages.length - 1 ? <span className="absolute left-[7px] top-4 h-full w-px bg-line" /> : null}
            <StatusDot status={stage.status} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-3">
                <div className="text-sm font-medium">{stage.label}</div>
                <div className="font-mono text-[10px] uppercase tracking-wider text-mist">{stage.status}</div>
              </div>
              {stage.detail ? <p className="mt-0.5 text-xs leading-5 text-mist">{stage.detail}</p> : null}
              {stage.flags?.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {stage.flags.map((flag, i) => (
                    <span
                      key={`${flag.label}-${i}`}
                      className={cn(
                        'rounded-full border border-line bg-ink px-2 py-0.5 text-[11px] text-paper/80',
                        flag.tone === 'fake' && 'border-rose/30 text-rose',
                        flag.tone === 'real' && 'border-lime/30 text-lime',
                        flag.tone === 'verdict' && 'border-amber/30 text-amber',
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
  preview,
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
    <div className="fade-up space-y-4">
      <article className="overflow-hidden rounded-2xl border border-line bg-panel">
        <div className="flex flex-wrap items-stretch gap-0 border-b border-line">
          <div className="min-w-[16rem] flex-1 p-5">
            <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">Receipt {result.receipt_id}</p>
            <div
              className="mt-3 inline-block rounded-lg border px-3 py-2 font-mono text-xl font-semibold uppercase tracking-wide sm:text-2xl"
              style={{ color: theme.color, borderColor: theme.color, background: theme.soft }}
            >
              {result.verdict}
            </div>
            <p className="mt-3 max-w-lg text-sm leading-6 text-mist">{result.summary}</p>
          </div>
          {preview ? <img src={preview} alt="" className="h-40 w-44 object-cover sm:h-auto" /> : null}
        </div>

        <div className="space-y-2 p-5">
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">How strong the clues are</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">{result.confidence}%</div>
            </div>
            <div className="text-right text-[11px] text-mist">Not a guarantee</div>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-ink">
            <div className="h-full rounded-full transition-all" style={{ width: `${result.confidence}%`, background: theme.color }} />
          </div>
          <p className="text-sm leading-6 text-paper/85">{result.confidence_note}</p>
        </div>
      </article>

      {result.claim?.text ? (
        <section className="rounded-2xl border border-line bg-panel p-5">
          <h3 className="font-mono text-[10px] uppercase tracking-[0.16em] text-mist">The claim</h3>
          <p className="mt-2 text-sm leading-6">{result.claim.text}</p>
        </section>
      ) : null}

      <section className="rounded-2xl border border-line bg-panel p-5">
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

        <EvidenceBlock title="Points toward real" accent="text-lime" items={groups.toward_real} empty="Nothing scored toward real." />
        <EvidenceBlock
          title="Points toward fake / out of context"
          accent="text-amber"
          items={groups.toward_fake_or_ooc}
          empty="Nothing scored toward fake or out of context."
        />
        <EvidenceBlock title="Couldn't check" accent="text-mist" items={groups.couldnt_check} empty="Every step in the pipeline ran." />
      </section>

      <section className="rounded-2xl border border-line bg-panel p-5">
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
        <section className="rounded-2xl border border-line bg-panel p-5">
          <h3 className="text-sm font-semibold">Timeline</h3>
          <ol className="mt-3 space-y-3">
            {result.timeline.map((event, i) => (
              <li key={`${event.at}-${i}`} className="grid grid-cols-[7rem_1fr] gap-3 text-sm">
                <span className="font-mono text-[11px] text-mist">{event.at}</span>
                <span>{event.label}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className="rounded-2xl border border-line bg-panel p-5">
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
        <section className="rounded-2xl border border-line bg-panel p-5">
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
        <form onSubmit={onFlag} className="space-y-3 rounded-2xl border border-line bg-panel p-5">
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
    <div className="mt-5">
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
      <div className="max-h-[88vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-panel p-5 shadow-2xl">
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
