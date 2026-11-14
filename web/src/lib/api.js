export const STAGE_FALLBACK = [
  { id: 'credentials', label: 'Read EXIF and C2PA' },
  { id: 'detector', label: 'Note a weak AI-image prior' },
  { id: 'vision', label: 'SEE' },
  { id: 'youcom_search', label: 'PROVE' },
  { id: 'youcom_contents', label: 'Read sources' },
  { id: 'youcom_answer', label: 'Cited synthesis' },
  { id: 'reverse_image', label: 'FIND' },
  { id: 'verdict', label: 'Judge the claim' },
  { id: 'x402', label: 'XDC x402 pay-per-verify' },
]

function parseEvent(block) {
  let event = 'message'
  const data = []
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  if (!data.length) return null
  return { event, data: JSON.parse(data.join('\n')) }
}

async function readStream(response, handlers) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let gotResult = false
  let sawStage = false
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) {
      const parsed = parseEvent(part.trim())
      if (!parsed) continue
      if (parsed.event === 'stage') {
        sawStage = true
        handlers.onStage?.(parsed.data)
        // A local check returns every step in one burst. Pause so each flag can paint.
        await sleep(150)
      } else if (parsed.event === 'cache') handlers.onCache?.(parsed.data)
      else if (parsed.event === 'result') {
        if (!sawStage) await playStages(parsed.data, handlers)
        gotResult = true
        handlers.onResult?.(parsed.data)
      } else if (parsed.event === 'error') {
        throw new Error(parsed.data.detail || 'Check failed.')
      }
    }
  }
  if (!gotResult) throw new Error('The check stream ended without a result.')
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function flagsFor(stepId, result) {
  const exif = result.credentials?.exif || {}
  const c2pa = result.credentials?.c2pa || {}
  if (stepId === 'credentials') {
    const flags = []
    const camera = [exif.make, exif.model].filter(Boolean).join(' ')
    if (camera) flags.push({ label: camera, tone: 'real' })
    if (exif.datetime) flags.push({ label: `Captured ${exif.datetime}`, tone: 'neutral' })
    if (c2pa.generative) flags.push({ label: exif.software || 'Generative marker', tone: 'fake' })
    else if (exif.software && /diffusion|midjourney|dall-?e|firefly|generative/i.test(exif.software)) {
      flags.push({ label: exif.software, tone: 'fake' })
    } else if (c2pa.present) flags.push({ label: 'C2PA present', tone: 'real' })
    else flags.push({ label: 'No C2PA', tone: 'neutral' })
    return flags
  }
  if (stepId === 'detector') {
    const score = Number(result.detector?.score)
    if (!Number.isFinite(score)) return []
    return [{ label: `Prior ${score.toFixed(2)}`, tone: score >= 0.75 ? 'fake' : 'neutral' }]
  }
  if (stepId === 'vision') {
    return [{ label: (result.claim?.text || 'No caption').slice(0, 80), tone: 'neutral' }]
  }
  if (stepId === 'youcom_search') {
    return (result.sources || []).slice(0, 4).map((source) => ({ label: source.title || source.url || 'Source', tone: 'neutral' }))
  }
  if (stepId === 'verdict' && result.verdict) {
    return [{ label: result.verdict, tone: 'verdict' }]
  }
  return []
}

async function playStages(result, handlers) {
  const stages = result.stages || {}
  for (const step of STAGE_FALLBACK) {
    const row = stages[step.id] || { status: 'ok', detail: '' }
    handlers.onStage?.({
      id: step.id,
      status: 'running',
      label: step.label,
      detail: '',
      flags: [],
    })
    await sleep(140)
    handlers.onStage?.({
      id: step.id,
      status: row.status || 'ok',
      label: step.label,
      detail: row.detail || '',
      flags: flagsFor(step.id, result),
    })
    await sleep(90)
  }
}

async function replayStages(result, handlers) {
  await playStages(result, handlers)
  handlers.onResult?.(result)
}

export async function runCheck(body, handlers) {
  try {
    const response = await fetch('/api/check/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (
      response.ok &&
      response.body &&
      (response.headers.get('content-type') || '').includes('text/event-stream')
    ) {
      await readStream(response, handlers)
      return
    }
  } catch {
    // The JSON check is the fallback when the stream is unavailable.
  }
  const response = await fetch('/api/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.detail || 'Check failed.')
  await replayStages(payload, handlers)
}
