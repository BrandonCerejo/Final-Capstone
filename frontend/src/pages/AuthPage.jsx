import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import './AuthPage.css'

const initialForm = {
  name: '',
  gender: 'female',
  age: '',
  email: '',
  password: '',
}

export default function AuthPage({ onAuth }) {
  const navigate = useNavigate()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState(initialForm)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const title = useMemo(
    () => (mode === 'login' ? 'Welcome back' : 'Create your account'),
    [mode]
  )

  const handleChange = (e) => {
    const { name, value } = e.target
    setForm((prev) => ({ ...prev, [name]: value }))
  }

  const parseResponse = async (response) => {
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      const msg = data?.detail || data?.message || 'Request failed. Please try again.'
      throw new Error(msg)
    }
    return data
  }

  const registerUser = async () => {
    const response = await fetch('http://127.0.0.1:8000/register', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name: form.name,
        gender: form.gender,
        age: Number(form.age),
        email: form.email,
        password: form.password,
      }),
    })

    return parseResponse(response)
  }

  const loginUser = async () => {
    const response = await fetch('http://127.0.0.1:8000/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        email: form.email,
        password: form.password,
      }),
    })

    return parseResponse(response)
  }

  const loginDoctor = async () => {
    const response = await fetch('http://127.0.0.1:8000/doctor/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: form.email, password: form.password }),
    })
    return parseResponse(response)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    setNotice('')

    try {
      if (mode === 'doctor') {
        const data = await loginDoctor()
        localStorage.setItem('doctor', JSON.stringify(data.doctor))
        navigate('/doctor')
      } else if (mode === 'login') {
        const data = await loginUser()
        localStorage.setItem('user', JSON.stringify(data.user))
        onAuth(true)
        navigate('/')
      } else {
        await registerUser()
        setNotice('Account created. Please sign in to continue.')
        setMode('login')
        setForm((prev) => ({ ...prev, password: '' }))
      }
    } catch (err) {
      setError(err.message || 'Something went wrong. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth">
      <div className="auth-bg">
        <div className="auth-orb auth-orb1" />
        <div className="auth-orb auth-orb2" />
        <div className="auth-grid" />
      </div>

      <div className="auth-card">
        <aside className="auth-hero">
          <div className="auth-brand">
            <span className="auth-cross">✚</span>
            <span>PneumaVision</span>
          </div>
          <h1>{title}</h1>
          <p>
            Secure access to AI-powered chest X-ray analysis, structured reports, and
            clinical-grade insights in seconds.
          </p>
          <div className="auth-stats">
            <div>
              <span>14</span>
              <small>Conditions detected</small>
            </div>
            <div>
              <span>100k+</span>
              <small>NIH X-rays trained on</small>
            </div>
            <div>
              <span>LLM</span>
              <small>Radiology narrative</small>
            </div>
          </div>
        </aside>

        <section className="auth-panel">
          <div className="auth-tabs">
            <button
              className={`auth-tab ${mode === 'login' ? 'is-active' : ''}`}
              type="button"
              onClick={() => setMode('login')}
            >
              Sign In
            </button>
            <button
              className={`auth-tab ${mode === 'register' ? 'is-active' : ''}`}
              type="button"
              onClick={() => setMode('register')}
            >
              Register
            </button>
            <button
              className={`auth-tab ${mode === 'doctor' ? 'is-active' : ''}`}
              type="button"
              onClick={() => setMode('doctor')}
            >
              Doctor Sign-in
            </button>
          </div>

          <form className="auth-form" onSubmit={handleSubmit}>
            {mode === 'register' && (
              <div className="auth-grid-2">
                <label className="auth-field">
                  <span>Full name</span>
                  <input
                    name="name"
                    value={form.name}
                    onChange={handleChange}
                    placeholder="Dr. Alex Morgan"
                    required
                  />
                </label>
                <label className="auth-field">
                  <span>Gender</span>
                  <select name="gender" value={form.gender} onChange={handleChange}>
                    <option value="female">Female</option>
                    <option value="male">Male</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                <label className="auth-field">
                  <span>Age</span>
                  <input
                    name="age"
                    type="number"
                    min="1"
                    max="120"
                    value={form.age}
                    onChange={handleChange}
                    placeholder="29"
                    required
                  />
                </label>
              </div>
            )}

            <label className="auth-field">
              <span>Email</span>
              <input
                name="email"
                type="email"
                value={form.email}
                onChange={handleChange}
                placeholder="you@hospital.org"
                required
              />
            </label>

            <label className="auth-field">
              <span>Password</span>
              <input
                name="password"
                type="password"
                value={form.password}
                onChange={handleChange}
                placeholder="••••••••"
                required
              />
            </label>

            {error && <div className="auth-alert auth-alert--error">{error}</div>}
            {notice && <div className="auth-alert auth-alert--notice">{notice}</div>}

            <button className="auth-submit" type="submit" disabled={loading}>
              {loading ? 'Please wait…' : mode === 'login' ? 'Sign In' : mode === 'doctor' ? 'Doctor Sign In' : 'Create Account'}
            </button>

            <button
              type="button"
              className="auth-ghost"
              onClick={() => navigate('/')}
            >
              Explore the landing page
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}
