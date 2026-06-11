import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

type JobStatus = 'idle' | 'processing' | 'completed' | 'failed'
type UpscaleFactor = '2x' | '4x'
type GenerationMode = 'text' | 'image'

interface GenerateResponse {
  job_id: string
  status: JobStatus
  video_url?: string | null
  error?: string | null
  music_added?: boolean
  upscaled?: boolean
  warnings?: string[]
}

interface VideoListItem {
  filename: string
  video_url: string
  created_at: string
}

interface VideoListResponse {
  videos: VideoListItem[]
}

const ENV_API_BASE = import.meta.env.VITE_API_BASE_URL?.trim() ?? ''
const API_BASE = ENV_API_BASE.replace(/\/$/, '')
const API_PREFIX = API_BASE ? '' : '/api'

const apiUrl = (path: string) => `${API_BASE}${API_PREFIX}${path}`
const mediaUrl = (url: string) => {
  if (/^https?:\/\//i.test(url)) return url
  if (!url.startsWith('/')) return url
  return API_BASE ? `${API_BASE}${url}` : url
}

function App() {
  const [mode, setMode] = useState<GenerationMode>('text')
  const [prompt, setPrompt] = useState('')
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [jobId, setJobId] = useState<string | null>(null)
  const [status, setStatus] = useState<JobStatus>('idle')
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<VideoListItem[]>([])

  const [addMusic, setAddMusic] = useState(true)
  const [musicPrompt, setMusicPrompt] = useState('cinematic ambient background music')
  const [upscale, setUpscale] = useState(false)
  const [upscaleFactor, setUpscaleFactor] = useState<UpscaleFactor>('2x')

  const [jobWarnings, setJobWarnings] = useState<string[]>([])
  const [musicAdded, setMusicAdded] = useState(false)
  const [upscaled, setUpscaled] = useState(false)

  const isGenerating = status === 'processing'

  const sortedHistory = useMemo(
    () => [...history].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
    [history],
  )

  const loadHistory = async () => {
    try {
      const response = await fetch(apiUrl('/videos?limit=12'))
      if (!response.ok) throw new Error('Could not load video history')

      const data: VideoListResponse = await response.json()
      setHistory(data.videos.map((item) => ({ ...item, video_url: mediaUrl(item.video_url) })))
    } catch (err) {
      console.error(err)
    }
  }

  const handleImageSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    setImageFile(file)
    const reader = new FileReader()
    reader.onload = () => setImagePreview(reader.result as string)
    reader.readAsDataURL(file)
  }

  const handleClearImage = () => {
    setImageFile(null)
    setImagePreview(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleGenerate = async () => {
    const cleanPrompt = prompt.trim()
    if (isGenerating) return

    if (mode === 'text' && !cleanPrompt) return
    if (mode === 'image' && !imageFile) return

    setStatus('processing')
    setError(null)
    setVideoUrl(null)
    setJobWarnings([])
    setMusicAdded(false)
    setUpscaled(false)

    try {
      let response: Response

      if (mode === 'text') {
        response = await fetch(apiUrl('/generate'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: cleanPrompt,
            add_music: addMusic,
            music_prompt: musicPrompt.trim() || undefined,
            upscale,
            upscale_factor: upscaleFactor,
          }),
        })
      } else {
        const formData = new FormData()
        if (imageFile) formData.append('file', imageFile)
        if (cleanPrompt) formData.append('prompt', cleanPrompt)
        formData.append('add_music', String(addMusic))
        if (musicPrompt.trim()) formData.append('music_prompt', musicPrompt.trim())
        formData.append('upscale', String(upscale))
        formData.append('upscale_factor', upscaleFactor)

        response = await fetch(apiUrl('/generate-from-image'), {
          method: 'POST',
          body: formData,
        })
      }

      if (!response.ok) {
        const message = await response.text()
        throw new Error(message || 'Failed to start generation')
      }

      const data: GenerateResponse = await response.json()
      setJobId(data.job_id)
    } catch (err) {
      setStatus('failed')
      setError(err instanceof Error ? err.message : 'Unknown error while starting generation')
    }
  }

  useEffect(() => {
    loadHistory()
  }, [])

  useEffect(() => {
    if (!jobId || status !== 'processing') return

    const interval = setInterval(async () => {
      try {
        const response = await fetch(apiUrl(`/status/${jobId}`))
        if (!response.ok) return

        const data: GenerateResponse = await response.json()

        if (data.status === 'completed' && data.video_url) {
          setVideoUrl(mediaUrl(data.video_url))
          setStatus('completed')
          setError(null)
          setMusicAdded(Boolean(data.music_added))
          setUpscaled(Boolean(data.upscaled))
          setJobWarnings(data.warnings ?? [])
          loadHistory()
          clearInterval(interval)
        } else if (data.status === 'failed') {
          setStatus('failed')
          setError(data.error ?? 'Generation failed on the server.')
          setJobWarnings(data.warnings ?? [])
          clearInterval(interval)
        }
      } catch (err) {
        console.error('Error checking status:', err)
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [jobId, status])

  const handleReset = () => {
    setPrompt('')
    setJobId(null)
    setVideoUrl(null)
    setStatus('idle')
    setJobWarnings([])
    setImageFile(null)
    setImagePreview(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  return (
    <div className="container">
      <header>
        <h1>QuickVid AI</h1>
        <p className="subtitle">Generate social-ready AI videos from text prompts or images</p>
      </header>

      <main>
        <section className="card">
          <div className="mode-toggle">
            <button
              className={`mode-btn ${mode === 'text' ? 'active' : ''}`}
              onClick={() => setMode('text')}
              disabled={isGenerating}
            >
              📝 Text to Video
            </button>
            <button
              className={`mode-btn ${mode === 'image' ? 'active' : ''}`}
              onClick={() => setMode('image')}
              disabled={isGenerating}
            >
              🖼️ Image to Video
            </button>
          </div>

          <div className="input-group">
            {mode === 'text' ? (
              <>
                <label htmlFor="prompt">Describe your video</label>
                <textarea
                  id="prompt"
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="A golden retriever puppy playing in the snow, cinematic lighting..."
                  disabled={isGenerating}
                />
              </>
            ) : (
              <>
                <label>Upload an image to animate</label>
                <div className="image-upload-area">
                  {imagePreview ? (
                    <div className="image-preview-container">
                      <img src={imagePreview} alt="Uploaded preview" className="image-preview" />
                      <button
                        type="button"
                        className="clear-image-btn"
                        onClick={handleClearImage}
                        disabled={isGenerating}
                      >
                        ✕ Remove
                      </button>
                    </div>
                  ) : (
                    <div
                      className="image-dropzone"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <p>Click to select an image</p>
                      <p className="small">PNG, JPG, WebP, BMP supported</p>
                    </div>
                  )}
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".png,.jpg,.jpeg,.webp,.bmp"
                    onChange={handleImageSelect}
                    disabled={isGenerating}
                    hidden
                  />
                </div>
                <label htmlFor="prompt-img">Motion prompt (optional)</label>
                <textarea
                  id="prompt-img"
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Describe the desired motion, e.g. 'A cat running in a park, cinematic style'"
                  disabled={isGenerating}
                />
              </>
            )}

            <div className="enhancements">
              <h4>Enhancements</h4>

              <label className="option-row">
                <input
                  type="checkbox"
                  checked={addMusic}
                  onChange={(e) => setAddMusic(e.target.checked)}
                  disabled={isGenerating}
                />
                <span>Add AI background music (MusicGen)</span>
              </label>

              {addMusic && (
                <input
                  className="inline-input"
                  value={musicPrompt}
                  onChange={(e) => setMusicPrompt(e.target.value)}
                  placeholder="cinematic ambient background music"
                  disabled={isGenerating}
                />
              )}

              <label className="option-row">
                <input
                  type="checkbox"
                  checked={upscale}
                  onChange={(e) => setUpscale(e.target.checked)}
                  disabled={isGenerating}
                />
                <span>Upscale output quality</span>
              </label>

              {upscale && (
                <select
                  className="inline-input"
                  value={upscaleFactor}
                  onChange={(e) => setUpscaleFactor(e.target.value as UpscaleFactor)}
                  disabled={isGenerating}
                >
                  <option value="2x">2x</option>
                  <option value="4x">4x</option>
                </select>
              )}
            </div>

            <button
              className="generate-btn"
              onClick={handleGenerate}
              disabled={
                isGenerating ||
                (mode === 'text' && !prompt.trim()) ||
                (mode === 'image' && !imageFile)
              }
            >
              {isGenerating
                ? 'Generating…'
                : mode === 'text'
                  ? 'Generate Video'
                  : 'Generate from Image'}
            </button>
          </div>
        </section>

        {error && <div className="error-message">{error}</div>}

        {jobWarnings.length > 0 && (
          <section className="warning-card">
            <strong>Enhancement notices:</strong>
            <ul>
              {jobWarnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </section>
        )}

        <section className="output-section">
          {status === 'processing' && (
            <div className="loading-card">
              <div className="spinner" />
              <p>Your video is being generated.</p>
              <p className="small">This may take 30-120 seconds depending on queue load and selected enhancements.</p>
            </div>
          )}

          {status === 'completed' && videoUrl && (
            <div className="result-card">
              <h3>Generation complete</h3>

              <div className="badge-row">
                {musicAdded && <span className="badge">🎵 Music added</span>}
                {upscaled && <span className="badge">✨ Upscaled</span>}
                {!musicAdded && !upscaled && <span className="badge muted">Base render</span>}
              </div>

              <div className="video-wrapper">
                <video src={videoUrl} controls autoPlay loop />
              </div>

              <div className="actions">
                <a href={videoUrl} download={`quickvid-${jobId}.mp4`} className="download-link">
                  Download MP4
                </a>
                <button onClick={handleReset} className="reset-btn">
                  Generate Another
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="history-section card">
          <div className="history-header">
            <h3>Recent videos</h3>
            <button type="button" className="refresh-btn" onClick={loadHistory}>
              Refresh
            </button>
          </div>

          {sortedHistory.length === 0 ? (
            <p className="small">No generated videos yet.</p>
          ) : (
            <div className="history-grid">
              {sortedHistory.map((item) => (
                <article key={item.filename} className="history-item">
                  <video src={item.video_url} controls preload="metadata" />
                  <div className="history-meta">
                    <span className="history-name">{item.filename}</span>
                    <span className="history-time">{new Date(item.created_at).toLocaleString()}</span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>

      <footer>
        <p>Text-to-Video: ByteDance/AnimateDiff-Lightning • Image-to-Video: Wan2.1 • Enhancements: MusicGen + RealESRGAN</p>
      </footer>
    </div>
  )
}

export default App