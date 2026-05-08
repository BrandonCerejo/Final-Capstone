import { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import './AnalyzePage.css'
import ReportChatbot from '../components/ReportChatbot'
import KnowledgeChatbot from '../components/KnowledgeChatbot'

const API_URL         = 'http://localhost:8000/analyze'
const PDF_PREVIEW_URL = 'http://localhost:8000/preview-pdf'
const PDF_GENERATE_URL = 'http://localhost:8000/generate-pdf'

const PRIORITY_META = {
  high:     { label: 'High Priority',     color: 'var(--high)',     dot: '#fc8181' },
  moderate: { label: 'Moderate Priority', color: 'var(--moderate)', dot: '#f6ad55' },
  low:      { label: 'Low Priority',      color: 'var(--low)',      dot: '#68d391' },
}

export default function AnalyzePage() {
  const navigate   = useNavigate()
  const inputRef   = useRef(null)
  const resultsRef = useRef(null)

  const [file,         setFile]         = useState(null)
  const [preview,      setPreview]      = useState(null)
  const [dragging,     setDragging]     = useState(false)
  const [loading,      setLoading]      = useState(false)
  const [progress,     setProgress]     = useState('')
  const [error,        setError]        = useState(null)
  const [result,       setResult]       = useState(null)
  const [lightbox,     setLightbox]     = useState(null)
  const [pdfLoading,   setPdfLoading]   = useState(false)
  const [sending,      setSending]      = useState(false)
  const [sentMsg,      setSentMsg]      = useState('')
  const [reportId,     setReportId]     = useState(null)
  const [doctors,        setDoctors]        = useState([])
  const [showDoctorPick, setShowDoctorPick] = useState(false)

  // ── PDF preview state ──────────────────────────────────────────────────────
  const [pdfPages,          setPdfPages]          = useState([])
  const [pdfPreviewLoading, setPdfPreviewLoading] = useState(false)
  const [pdfPreviewError,   setPdfPreviewError]   = useState(null)
  const [activeTab,         setActiveTab]         = useState('report')

  // ── fetch doctors on mount ─────────────────────────────────────────────────
  useEffect(() => {
    const fetchDoctors = async () => {
      try {
        const { data } = await axios.get('http://localhost:8000/doctor/list')
        setDoctors(data)
      } catch { /* silent */ }
    }
    fetchDoctors()
  }, [])

  // ── close dropdown when clicking outside ──────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (!e.target.closest('.ap-doctor-picker-wrap')) {
        setShowDoctorPick(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  /* ── file selection ── */
  const handleFile = (f) => {
    if (!f) return
    const ok = ['image/jpeg', 'image/jpg', 'image/png'].includes(f.type)
    if (!ok) { setError('Please upload a JPEG or PNG image.'); return }
    setError(null)
    setResult(null)
    setPdfPages([])
    setFile(f)
    setPreview(URL.createObjectURL(f))
  }

  const onInputChange = (e) => handleFile(e.target.files[0])
  const onDrop        = useCallback((e) => {
    e.preventDefault(); setDragging(false)
    handleFile(e.dataTransfer.files[0])
  }, [])
  const onDragOver  = (e) => { e.preventDefault(); setDragging(true) }
  const onDragLeave = () => setDragging(false)

  /* ── analyze ── */
  const handleAnalyze = async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    setResult(null)
    setPdfPages([])
    setReportId(null)
    setSentMsg('')
    setShowDoctorPick(false)

    const steps = [
      'Uploading image…',
      'Running DenseNet121 inference…',
      'Computing Grad-CAM heatmaps…',
      'Generating radiology report…',
    ]
    let si = 0
    setProgress(steps[si])
    const interval = setInterval(() => {
      si = Math.min(si + 1, steps.length - 1)
      setProgress(steps[si])
    }, 4000)

    try {
      const storedUser = JSON.parse(localStorage.getItem('user') || '{}')
      const form = new FormData()
      form.append('file',          file)
      form.append('patient_name',  storedUser.name   || '')
      form.append('patient_age',   String(storedUser.age || ''))
      form.append('patient_sex',   storedUser.gender || '')
      form.append('patient_email', storedUser.email  || '')

      const { data } = await axios.post(API_URL, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setResult(data)
      setReportId(data.report_id || null)
      clearInterval(interval)
      setLoading(false)
      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }, 100)
    } catch (err) {
      clearInterval(interval)
      setLoading(false)
      setError(
        err.response?.data?.detail ||
        'Something went wrong. Make sure the backend is running on port 8000.'
      )
    }
  }

  /* ── fetch PDF preview whenever result arrives ── */
  useEffect(() => {
    if (!result) return
    const fetchPreview = async () => {
      setPdfPreviewLoading(true)
      setPdfPreviewError(null)
      setPdfPages([])
      try {
        const { data } = await axios.post(PDF_PREVIEW_URL, {
          report:        result.report,
          gradcam_image: result.gradcam_image,
          xray_image:    result.xray_image,
          patient_email: JSON.parse(localStorage.getItem('user') || '{}').email || '',
        })
        setPdfPages(data.pages || [])
      } catch {
        setPdfPreviewError('Could not load PDF preview.')
      } finally {
        setPdfPreviewLoading(false)
      }
    }
    fetchPreview()
  }, [result])

  const reset = () => {
    setFile(null); setPreview(null); setResult(null); setError(null)
    setPdfPages([]); setPdfPreviewError(null); setActiveTab('report')
    setSentMsg(''); setShowDoctorPick(false)
  }

  const handleDownloadPdf = async () => {
    if (!result) return
    setPdfLoading(true)
    try {
      const response = await axios.post(
        PDF_GENERATE_URL,
        {
          report:        result.report,
          gradcam_image: result.gradcam_image,
          xray_image:    result.xray_image,
          patient_email: JSON.parse(localStorage.getItem('user') || '{}').email || '',
        },
        { responseType: 'blob' }
      )
      const url  = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href  = url
      link.setAttribute('download', 'PneumaVision_Report.pdf')
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      alert('PDF generation failed. Please try again.')
    } finally {
      setPdfLoading(false)
    }
  }

  /* ── send to doctor ── */
  const sendToDoctor = async (doctor) => {
    const storedUser = JSON.parse(localStorage.getItem('user') || '{}')
    if (!reportId || !storedUser.email) return
    setSending(true)
    setSentMsg('')
    setShowDoctorPick(false)
    try {
      await axios.post('http://localhost:8000/doctor/send-report', {
        report_id:     reportId,
        patient_email: storedUser.email,
        doctor_email:  doctor.email,
        doctor_name:   doctor.name,
      })
      setSentMsg(`✓ Sent to ${doctor.name}!`)
    } catch (err) {
      setSentMsg(err.response?.data?.detail || 'Failed to send.')
    } finally {
      setSending(false)
    }
  }

  /* ── render ── */
  return (
    <div className="ap">

      {/* ambient bg */}
      <div className="ap-bg">
        <div className="ap-orb ap-orb1" />
        <div className="ap-orb ap-orb2" />
        <div className="ap-grid" />
      </div>

      {/* nav */}
      <nav className="ap-nav">
        <button className="ap-nav-back" onClick={() => navigate('/')}>← Back</button>
        <div className="ap-nav-logo">
          <span className="ap-cross">✚</span> PneumaVision
        </div>
        <div style={{ width: 80 }} />
      </nav>

      {/* ── UPLOAD STATE ── */}
      {!result && (
        <div className="ap-upload-view container">
          <div className="ap-header">
            <div className="ap-section-label">Chest X-Ray Analyzer</div>
            <h1 className="ap-title">Upload & Analyse</h1>
            <p className="ap-subtitle">
              Upload a chest X-ray image to receive AI-generated findings and a structured radiology report.
            </p>
            <div className="ap-header-actions">
              <button
                className="ap-btn-reset"
                onClick={() => navigate('/reports')}
                style={{ marginTop: '1rem', padding: '0.75rem 1.4rem', fontSize: '0.9rem' }}
              >
                📋 View Previous Reports
              </button>
            </div>
          </div>

          <div
            className={`ap-dropzone ${dragging ? 'ap-dropzone--drag' : ''} ${preview ? 'ap-dropzone--has-preview' : ''}`}
            onDrop={onDrop}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onClick={() => !preview && inputRef.current?.click()}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".jpg,.jpeg,.png"
              style={{ display: 'none' }}
              onChange={onInputChange}
            />
            {preview ? (
              <div className="ap-preview-wrap">
                <img src={preview} alt="X-Ray preview" className="ap-preview-img" />
                <div className="ap-preview-info">
                  <span className="ap-preview-name">{file?.name}</span>
                  <span className="ap-preview-size">{(file?.size / 1024).toFixed(0)} KB</span>
                  <button
                    className="ap-preview-change"
                    onClick={(e) => { e.stopPropagation(); inputRef.current?.click() }}
                  >
                    Change image
                  </button>
                </div>
              </div>
            ) : (
              <div className="ap-dropzone-inner">
                <div className="ap-dropzone-icon">
                  <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <rect x="6" y="6" width="36" height="36" rx="6" stroke="currentColor" strokeWidth="2"/>
                    <path d="M16 30 L22 22 L27 28 L31 24 L36 30" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                    <circle cx="18" cy="18" r="2.5" fill="currentColor"/>
                    <path d="M24 12 L24 8 M24 8 L21 11 M24 8 L27 11" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <p className="ap-dropzone-title">Drop your X-ray here</p>
                <p className="ap-dropzone-sub">or <span>click to browse</span> — JPEG, PNG up to 20 MB</p>
              </div>
            )}
          </div>

          {error && <div className="ap-error">{error}</div>}

          {file && (
            <div className="ap-actions">
              <button className="ap-btn-analyze" onClick={handleAnalyze} disabled={loading}>
                {loading ? (
                  <span className="ap-loading-row">
                    <span className="ap-spinner" />
                    {progress}
                  </span>
                ) : 'Analyse X-Ray →'}
              </button>
              {!loading && (
                <button className="ap-btn-reset" onClick={reset}>Clear</button>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── RESULTS STATE ── */}
      {result && (
        <div className="ap-results-view" ref={resultsRef}>

          {/* top bar */}
          <div className="ap-results-topbar">
            <div>
              <div className="ap-section-label">Analysis Complete</div>
              <h2 className="ap-results-title">
                {result.num_findings} Finding{result.num_findings !== 1 ? 's' : ''} Detected
              </h2>
            </div>

            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>

              {/* Download PDF */}
              <button
                className="ap-btn-analyze"
                style={{ minWidth: 'unset', padding: '0.65rem 1.5rem', fontSize: '0.85rem' }}
                onClick={handleDownloadPdf}
                disabled={pdfLoading}
              >
                {pdfLoading ? (
                  <span className="ap-loading-row">
                    <span className="ap-spinner" /> Generating PDF…
                  </span>
                ) : '⬇ Download PDF'}
              </button>

              {/* Send to Doctor — dropdown */}
              {reportId && (
                <div className="ap-doctor-picker-wrap" style={{ position: 'relative' }}>
                  <button
                    className="ap-btn-analyze"
                    style={{
                      minWidth: 'unset', padding: '0.65rem 1.5rem', fontSize: '0.85rem',
                      background: sentMsg.startsWith('✓') ? '#2d6a4f' : undefined
                    }}
                    onClick={() => {
                      if (!sentMsg.startsWith('✓')) setShowDoctorPick(p => !p)
                    }}
                    disabled={sending || sentMsg.startsWith('✓')}
                  >
                    {sending
                      ? '📤 Sending…'
                      : sentMsg.startsWith('✓')
                        ? sentMsg
                        : '📤 Send to Doctor ▾'}
                  </button>

                  {showDoctorPick && (
                    <div style={{
                      position: 'absolute', top: '110%', right: 0,
                      background: '#1a202c', border: '1px solid #2d3748',
                      borderRadius: '8px', minWidth: '240px',
                      boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                      zIndex: 100, overflow: 'hidden'
                    }}>
                      <div style={{
                        padding: '0.5rem 0.75rem', fontSize: '0.75rem',
                        color: '#a0aec0', borderBottom: '1px solid #2d3748',
                        letterSpacing: '0.05em', textTransform: 'uppercase'
                      }}>
                        Select a Doctor
                      </div>
                      {doctors.length === 0 && (
                        <div style={{ padding: '0.75rem', color: '#a0aec0', fontSize: '0.85rem' }}>
                          No doctors available
                        </div>
                      )}
                    {doctors.map(doc => (
                        <div
                            key={doc.id}
                            onClick={() => sendToDoctor(doc)}
                            style={{
                                width: '100%', textAlign: 'left',
                                padding: '0.65rem 0.75rem',
                                borderBottom: '1px solid #2d3748',
                                color: '#e2e8f0', cursor: 'pointer',
                                fontSize: '0.875rem',
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = '#2d3748'}
                            onMouseLeave={e => e.currentTarget.style.background = '#1a202c'}
                        >
                            <div style={{ fontWeight: '600', pointerEvents: 'none' }}>{doc.name}</div>
                            <div style={{ fontSize: '0.75rem', color: '#a0aec0', marginTop: '0.15rem', pointerEvents: 'none' }}>
                                {doc.email}
                            </div>
                        </div>
                    ))}
                    </div>
                  )}
                </div>
              )}

              {/* My Reports + New Analysis */}
              <button
                className="ap-btn-reset"
                style={{ padding: '0.65rem 1.25rem', fontSize: '0.85rem' }}
                onClick={() => navigate('/reports')}
              >
                📋 My Reports
              </button>
              <button className="ap-btn-reset" onClick={reset}>New Analysis</button>
            </div>

            {sentMsg && !sentMsg.startsWith('✓') && (
              <div className="ap-error" style={{ marginTop: '0.5rem' }}>{sentMsg}</div>
            )}
          </div>

          {/* ── Tab switcher ── */}
          <div className="ap-tabs">
            <button
              className={`ap-tab ${activeTab === 'report' ? 'ap-tab--active' : ''}`}
              onClick={() => setActiveTab('report')}
            >
              📋 Interactive Report
            </button>
            <button
              className={`ap-tab ${activeTab === 'pdf' ? 'ap-tab--active' : ''}`}
              onClick={() => setActiveTab('pdf')}
            >
              📄 PDF Preview
              {pdfPreviewLoading && <span className="ap-tab-spinner" />}
            </button>
          </div>

          {/* ── TAB: Interactive Report ── */}
          {activeTab === 'report' && (
            <div className="ap-results-grid">

              {/* LEFT: images */}
              <div className="ap-left-col">
                <div className="ap-img-card">
                  <div className="ap-img-label">Grad-CAM Visualisation</div>
                  <img
                    src={`data:image/png;base64,${result.gradcam_image}`}
                    alt="Grad-CAM"
                    className="ap-result-img ap-result-img--gradcam"
                    onClick={() => setLightbox(`data:image/png;base64,${result.gradcam_image}`)}
                    style={{ cursor: 'zoom-in' }}
                  />
                </div>
                <div className="ap-img-card">
                  <div className="ap-img-label">Original X-Ray</div>
                  <img
                    src={preview}
                    alt="Original X-Ray"
                    className="ap-result-img ap-result-img--original"
                  />
                </div>
              </div>

              {/* RIGHT: report content */}
              <div className="ap-right-col">

                <div className="ap-section-block">
                  <h3 className="ap-block-title">Findings</h3>
                  {result.report.findings?.length > 0 ? (
                    <div className="ap-findings">
                      {result.report.findings.map((f, i) => {
                        const pm = PRIORITY_META[f.clinical_priority] || PRIORITY_META.low
                        return (
                          <div className="ap-finding-card" key={i}>
                            <div className="ap-finding-top">
                              <span className="ap-finding-name">{f.condition}</span>
                              <span className="ap-finding-priority" style={{ color: pm.color, borderColor: pm.color }}>
                                <span className="ap-finding-dot" style={{ background: pm.dot }} />
                                {pm.label}
                              </span>
                            </div>
                            <div className="ap-finding-meta">
                              <div className="ap-finding-meta-item">
                                <span className="ap-meta-label">Confidence</span>
                                <div className="ap-conf-bar-wrap">
                                  <div
                                    className="ap-conf-bar"
                                    style={{ width: `${(f.confidence * 100).toFixed(1)}%`, background: pm.dot }}
                                  />
                                </div>
                                <span className="ap-meta-val">{(f.confidence * 100).toFixed(1)}%</span>
                              </div>
                              <div className="ap-finding-meta-item">
                                <span className="ap-meta-label">Location</span>
                                <span className="ap-meta-val ap-meta-location">{f.anatomical_location}</span>
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="ap-no-findings">No findings above threshold detected.</p>
                  )}
                </div>

                {result.report.not_detected?.length > 0 && (
                  <div className="ap-section-block">
                    <h3 className="ap-block-title">Not Detected</h3>
                    <div className="ap-not-detected-grid">
                      {result.report.not_detected.map((nd, i) => (
                        <div className="ap-nd-chip" key={i}>
                          <span className="ap-nd-name">{nd.condition}</span>
                          <span className="ap-nd-score">{(nd.raw_score * 100).toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {result.report.impression && (
                  <div className="ap-section-block ap-impression-block">
                    <h3 className="ap-block-title">Radiologist Impression</h3>
                    <blockquote className="ap-impression">
                      {result.report.impression}
                    </blockquote>
                  </div>
                )}

                {result.report.disclaimer && (
                  <div className="ap-disclaimer">
                    <span className="ap-disclaimer-icon">⚠</span>
                    {result.report.disclaimer}
                  </div>
                )}

                <ReportChatbot
                  report={result.report}
                  gradcamImage={result.gradcam_image}
                  xrayImage={result.xray_image}
                />
              </div>
            </div>
          )}

          {/* ── TAB: PDF Preview ── */}
          {activeTab === 'pdf' && (
            <div className="ap-pdf-preview">
              {pdfPreviewLoading && (
                <div className="ap-pdf-loading">
                  <span className="ap-spinner ap-spinner--lg" />
                  <p>Rendering PDF preview…</p>
                </div>
              )}

              {pdfPreviewError && !pdfPreviewLoading && (
                <div className="ap-pdf-error">
                  <span>⚠ {pdfPreviewError}</span>
                  <p style={{ fontSize: '0.8rem', marginTop: '0.5rem', opacity: 0.7 }}>
                    Make sure PyMuPDF (fitz) is installed on the backend: <code>pip install pymupdf</code>
                  </p>
                </div>
              )}

              {!pdfPreviewLoading && !pdfPreviewError && pdfPages.length > 0 && (
                <>
                  <div className="ap-pdf-toolbar">
                    <span className="ap-pdf-page-count">{pdfPages.length} page{pdfPages.length !== 1 ? 's' : ''}</span>
                    <button
                      className="ap-btn-analyze"
                      style={{ minWidth: 'unset', padding: '0.5rem 1.25rem', fontSize: '0.82rem' }}
                      onClick={handleDownloadPdf}
                      disabled={pdfLoading}
                    >
                      {pdfLoading ? (
                        <span className="ap-loading-row"><span className="ap-spinner" /> Generating…</span>
                      ) : '⬇ Download PDF'}
                    </button>
                  </div>

                  <div className="ap-pdf-pages">
                    {pdfPages.map((page, i) => (
                      <div className="ap-pdf-page-wrap" key={i}>
                        <div className="ap-pdf-page-label">Page {i + 1}</div>
                        <img
                          src={`data:image/png;base64,${page}`}
                          alt={`Report page ${i + 1}`}
                          className="ap-pdf-page-img"
                          onClick={() => setLightbox(`data:image/png;base64,${page}`)}
                          style={{ cursor: 'zoom-in' }}
                        />
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

        </div>
      )}

      {lightbox && (
        <div className="ap-lightbox" onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="Fullscreen" className="ap-lightbox-img" />
          <button className="ap-lightbox-close">✕</button>
        </div>
      )}

      <KnowledgeChatbot />
    </div>
  )
}