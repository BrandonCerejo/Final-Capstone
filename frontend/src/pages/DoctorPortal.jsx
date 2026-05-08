import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import './DoctorPortal.css'

const API = 'http://localhost:8000'

const PRIORITY_META = {
  high:     { label: 'High',     color: '#fc8181' },
  moderate: { label: 'Moderate', color: '#f6ad55' },
  low:      { label: 'Low',      color: '#68d391' },
}

const DISEASE_LABELS = [
  "Atelectasis","Cardiomegaly","Effusion","Infiltration","Mass",
  "Nodule","Pneumonia","Pneumothorax","Consolidation","Edema",
  "Emphysema","Fibrosis","Pleural_Thickening","Hernia"
]

export default function DoctorPortal() {
  const navigate = useNavigate()

  const [doctor]   = useState(() => JSON.parse(localStorage.getItem('doctor') || 'null'))
  const [reports,  setReports]  = useState([])
  const [selected, setSelected] = useState(null)
  const [feedback, setFeedback] = useState('')
  const [saving,   setSaving]   = useState(false)
  const [savedMsg, setSavedMsg] = useState('')
  const [loading,  setLoading]  = useState(false)
  const [lightbox, setLightbox] = useState(null)

  const [labelCorrect,   setLabelCorrect]   = useState(null)
  const [selectedLabels, setSelectedLabels] = useState([])
  const [corrSaving,     setCorrSaving]     = useState(false)
  const [corrMsg,        setCorrMsg]        = useState('')
  const [exportReady,    setExportReady]    = useState(false)
  const [corrSubmitted,  setCorrSubmitted]  = useState(false)

  useEffect(() => {
    if (!doctor) { navigate('/auth'); return }
    fetchReports()
  }, [])

const fetchReports = async () => {
    setLoading(true)
    try {
      // const { data } = await axios.get(`${API}/doctor/reports`)
      const { data } = await axios.get(`${API}/doctor/reports`, {
    params: { doctor_email: doctor.email }
})
      setReports(data.reports)
      setExportReady(data.export_ready)
    } catch { /* silent */ }
    finally { setLoading(false) }
}

  const openReport = (r) => {
    setSelected(r)
    setFeedback(r.feedback || '')
    setSavedMsg('')
    setLabelCorrect(null)
    setSelectedLabels([])
    setCorrMsg('')
    // Only mark submitted if backend explicitly says so
    setCorrSubmitted(r.has_label_correction === true)
  }

  const submitFeedback = async () => {
    if (!feedback.trim()) return
    setSaving(true)
    setSavedMsg('')
    try {
      await axios.post(`${API}/doctor/feedback`, {
        report_id:    selected.id,
        doctor_email: doctor.email,
        feedback:     feedback.trim(),
      })
      setSavedMsg('Feedback saved successfully.')
      setReports(prev => prev.map(r =>
        r.id === selected.id ? { ...r, has_feedback: true, feedback: feedback.trim() } : r
      ))
      setSelected(prev => ({ ...prev, has_feedback: true, feedback: feedback.trim() }))
    } catch {
      setSavedMsg('Failed to save. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  const submitLabelCorrection = async () => {
    if (labelCorrect === null) return
    setCorrSaving(true)
    setCorrMsg('')
    const predictedLabels = (selected.report?.findings || []).map(f => f.condition)
    try {
      const { data } = await axios.post(`${API}/doctor/label-correction`, {
        report_id:        selected.id,
        doctor_email:     doctor.email,
        predicted_labels: predictedLabels,
        is_correct:       labelCorrect,
        correct_labels:   labelCorrect ? predictedLabels : selectedLabels,
      })
      setCorrMsg('Correction saved!')
      setExportReady(data.export_ready)
      setCorrSubmitted(true)
      // Update local reports list so switching away and back stays correct
      setReports(prev => prev.map(r =>
        r.id === selected.id ? { ...r, has_label_correction: true } : r
      ))
      setSelected(prev => ({ ...prev, has_label_correction: true }))
    } catch {
      setCorrMsg('Failed to save. Try again.')
    } finally {
      setCorrSaving(false)
    }
  }

  const downloadTrainingData = async () => {
    const res  = await fetch(`${API}/doctor/export-training-data`)
    const blob = await res.blob()
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = 'training_data.zip'
    a.click()
    URL.revokeObjectURL(url)
    setExportReady(false)
  }

  const handleSignOut = () => {
    localStorage.removeItem('doctor')
    navigate('/login')
  }

  if (!doctor) return null

  return (
    <div className="dp-portal">

      {/* ── Sidebar ── */}
      <aside className="dp-sidebar">
        <div className="dp-sidebar-logo"><span className="dp-cross">✚</span> PneumaVision</div>
        <div className="dp-sidebar-role">Doctor Portal</div>

        <div className="dp-sidebar-doctor">
          <div className="dp-doctor-avatar">{doctor?.name?.[0] ?? 'D'}</div>
          <div>
            <div className="dp-doctor-name">{doctor?.name}</div>
            <div className="dp-doctor-email">{doctor?.email}</div>
          </div>
        </div>

        <div className="dp-sidebar-label">Patient Reports</div>
        {loading && <div className="dp-sidebar-loading">Loading…</div>}

        <div className="dp-report-list">
          {reports.map(r => (
            <button
              key={r.id}
              className={`dp-report-item ${selected?.id === r.id ? 'dp-report-item--active' : ''}`}
              onClick={() => openReport(r)}
            >
              <div className="dp-report-item-top">
                <span className="dp-report-patient">{r.name}</span>
                {r.has_feedback
                  ? <span className="dp-badge dp-badge--done">✓ Reviewed</span>
                  : <span className="dp-badge dp-badge--pending">Pending</span>
                }
              </div>
              <div className="dp-report-item-meta">
                {r.age   && <span>{r.age} yrs</span>}
                {r.sex   && <span> · {r.sex}</span>}
                {r.sent_at && <span> · {new Date(r.sent_at).toLocaleDateString()}</span>}
              </div>
            </button>
          ))}
          {!loading && reports.length === 0 && (
            <div className="dp-empty">No reports sent yet.</div>
          )}
        </div>

        {/* {exportReady && (
    <button
        onClick={downloadTrainingData}
        style={{
            margin: '0 1rem 0.75rem',
            padding: '0.6rem 1rem',
            borderRadius: '6px',
            border: 'none',
            background: '#d69e2e',
            color: '#000',
            fontWeight: '700',
            cursor: 'pointer',
            width: 'calc(100% - 2rem)',
            fontSize: '0.85rem',
            lineHeight: '1.4'
        }}
    >⬇ Download Training ZIP<br/>
        <span style={{ fontSize:'0.75rem', fontWeight:'400' }}>
            50+ corrections ready
        </span>
    </button>
)} */}
<button className="dp-btn-logout" onClick={handleSignOut}>Sign Out</button>

       
      </aside>

      {/* ── Main ── */}
      <main className="dp-main">
        {!selected ? (
          <div className="dp-placeholder">
            <div className="dp-placeholder-icon">🩺</div>
            <p>Select a patient report from the sidebar to review it.</p>
          </div>
        ) : (
          <div className="dp-report-view">

            <div className="dp-report-header">
              <div>
                <h2 className="dp-report-name">{selected.name}</h2>
                <span className="dp-report-meta-row">
                  {selected.age && <span>{selected.age} yrs</span>}
                  {selected.sex && <span> · {selected.sex}</span>}
                  {selected.created_at && (
                    <span> · {new Date(selected.created_at).toLocaleDateString()}</span>
                  )}
                </span>
              </div>
            </div>

            <div className="dp-report-body">

              <div className="dp-images-col">
                {selected.xray_image && (
                  <div className="dp-img-card">
                    <div className="dp-img-label">Original X-Ray</div>
                    <img
                      src={`data:image/png;base64,${selected.xray_image}`}
                      alt="X-Ray" className="dp-img"
                      onClick={() => setLightbox(`data:image/png;base64,${selected.xray_image}`)}
                      style={{ cursor: 'zoom-in' }}
                    />
                  </div>
                )}
                {selected.gradcam_image && (
                  <div className="dp-img-card">
                    <div className="dp-img-label">Grad-CAM Visualisation</div>
                    <img
                      src={`data:image/png;base64,${selected.gradcam_image}`}
                      alt="Grad-CAM" className="dp-img"
                      onClick={() => setLightbox(`data:image/png;base64,${selected.gradcam_image}`)}
                      style={{ cursor: 'zoom-in' }}
                    />
                  </div>
                )}
              </div>

              <div className="dp-detail-col">

                <div className="dp-section">
                  <h3 className="dp-section-title">Findings</h3>
                  {selected.report?.findings?.length > 0 ? (
                    <div className="dp-findings">
                      {selected.report.findings.map((f, i) => {
                        const pm = PRIORITY_META[f.clinical_priority] || PRIORITY_META.low
                        return (
                          <div className="dp-finding" key={i}>
                            <div className="dp-finding-top">
                              <span className="dp-finding-name">{f.condition}</span>
                              <span className="dp-finding-priority" style={{ color: pm.color }}>
                                <span className="dp-finding-dot" style={{ background: pm.color }} />
                                {pm.label}
                              </span>
                            </div>
                            <div className="dp-finding-bar-row">
                              <div className="dp-bar-wrap">
                                <div className="dp-bar" style={{ width: `${(f.confidence*100).toFixed(1)}%`, background: pm.color }} />
                              </div>
                              <span className="dp-bar-val">{(f.confidence*100).toFixed(1)}%</span>
                            </div>
                            <div className="dp-finding-loc">{f.anatomical_location}</div>
                          </div>
                        )
                      })}
                    </div>
                  ) : <p className="dp-empty">No findings above threshold.</p>}
                </div>

                {selected.report?.impression && (
                  <div className="dp-section">
                    <h3 className="dp-section-title">AI Impression</h3>
                    <blockquote className="dp-impression">{selected.report.impression}</blockquote>
                  </div>
                )}

                <div className="dp-section dp-feedback-section">
                  <h3 className="dp-section-title">Your Feedback</h3>
                  <textarea
                    className="dp-feedback-input"
                    rows={5}
                    placeholder="Write your clinical feedback for the patient here…"
                    value={feedback}
                    onChange={e => setFeedback(e.target.value)}
                  />
                  <div className="dp-feedback-actions">
                    {savedMsg && (
                      <span className={`dp-saved-msg ${savedMsg.includes('Failed') ? 'dp-saved-msg--err' : ''}`}>
                        {savedMsg}
                      </span>
                    )}
                    <button
                      className="dp-btn-primary dp-btn-submit"
                      onClick={submitFeedback}
                      disabled={saving || !feedback.trim()}
                    >
                      {saving ? 'Saving…' : selected.has_feedback ? 'Update Feedback' : 'Submit Feedback'}
                    </button>
                  </div>
                </div>

                {/* ── Label Correction ── */}
                <div className="dp-section">
                  <h3 className="dp-section-title">Label Correction</h3>

                  {corrSubmitted ? (
                    <div style={{
                      padding: '0.75rem 1rem', borderRadius: '8px',
                      background: '#1a2e1a', border: '1px solid #38a169',
                      display: 'flex', alignItems: 'center', gap: '0.6rem'
                    }}>
                      <span style={{ fontSize: '1.1rem' }}>✅</span>
                      <div>
                        <div style={{ color: '#68d391', fontWeight: '600', fontSize: '0.9rem' }}>
                          Correction already submitted
                        </div>
                        <div style={{ color: '#a0aec0', fontSize: '0.78rem', marginTop: '0.2rem' }}>
                          Label correction has been recorded for this report.
                        </div>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p style={{ fontSize: '0.85rem', color: '#a0aec0', marginBottom: '0.75rem' }}>
                        AI predicted: <strong style={{ color: '#fff' }}>
                          {(selected.report?.findings || []).map(f => f.condition).join(', ') || 'No findings'}
                        </strong>
                      </p>

                      <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem' }}>
                        <button
                          onClick={() => { setLabelCorrect(true); setSelectedLabels([]) }}
                          style={{
                            padding: '0.4rem 1rem', borderRadius: '6px', border: 'none',
                            cursor: 'pointer', fontWeight: '600',
                            background: labelCorrect === true ? '#38a169' : '#2d3748',
                            color: '#fff'
                          }}
                        >✅ Correct</button>
                        <button
                          onClick={() => setLabelCorrect(false)}
                          style={{
                            padding: '0.4rem 1rem', borderRadius: '6px', border: 'none',
                            cursor: 'pointer', fontWeight: '600',
                            background: labelCorrect === false ? '#e53e3e' : '#2d3748',
                            color: '#fff'
                          }}
                        >❌ Incorrect</button>
                      </div>

                      {labelCorrect === false && (
                        <div style={{ marginBottom: '1rem' }}>
                          <p style={{ fontSize: '0.8rem', color: '#a0aec0', marginBottom: '0.5rem' }}>
                            Select correct labels:
                          </p>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem' }}>
                            {DISEASE_LABELS.map(lbl => (
                              <label key={lbl} style={{
                                display: 'flex', alignItems: 'center',
                                gap: '0.4rem', fontSize: '0.82rem', color: '#e2e8f0', cursor: 'pointer'
                              }}>
                                <input
                                  type="checkbox"
                                  checked={selectedLabels.includes(lbl)}
                                  onChange={e => setSelectedLabels(prev =>
                                    e.target.checked ? [...prev, lbl] : prev.filter(x => x !== lbl)
                                  )}
                                />
                                {lbl}
                              </label>
                            ))}
                          </div>
                        </div>
                      )}

                      {labelCorrect !== null && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                          <button
                            onClick={submitLabelCorrection}
                            disabled={corrSaving || (labelCorrect === false && selectedLabels.length === 0)}
                            style={{
                              padding: '0.45rem 1.2rem', borderRadius: '6px', border: 'none',
                              background: '#3182ce', color: '#fff', fontWeight: '600', cursor: 'pointer'
                            }}
                          >{corrSaving ? 'Saving…' : 'Submit Correction'}</button>
                          {corrMsg && (
                            <span style={{
                              fontSize: '0.82rem',
                              color: corrMsg.includes('Failed') ? '#fc8181' : '#68d391'
                            }}>
                              {corrMsg}
                            </span>
                          )}
                        </div>
                      )}
                    </>
                  )}

                  {/* {exportReady && (
                    <button
                      onClick={downloadTrainingData}
                      style={{
                        marginTop: '1rem', padding: '0.5rem 1.2rem', borderRadius: '6px',
                        border: 'none', background: '#d69e2e', color: '#000',
                        fontWeight: '700', cursor: 'pointer'
                      }}
                    >⬇ Download Training ZIP (50+ ready)</button>
                  )} */}
                </div>

              </div>
            </div>
          </div>
        )}
      </main>

      {lightbox && (
        <div className="dp-lightbox" onClick={() => setLightbox(null)}>
          <img src={lightbox} alt="Fullscreen" className="dp-lightbox-img" />
          <button className="dp-lightbox-close">✕</button>
        </div>
      )}
    </div>
  )
}