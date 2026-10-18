// The Mac app's setup and sign-in flow (Figma page "Desktop app (M7)"). Each screen has its own file
// in this folder: Startup, Welcome, Install IB Gateway, Sign in (and its error state), Approve on
// phone, Login not approved.
import { useEffect, useState } from 'react'
import { gatewayStatus } from '../../desktop/appGateway.js'
import { cancelSignIn, savedLogin, signIn } from '../../desktop/appSession.js'
import { sizeWindowFor } from '../../desktop/appWindow.js'
import ApproveOnPhone from './ApproveOnPhone.jsx'
import InstallGateway from './InstallGateway.jsx'
import LoginNotApproved from './LoginNotApproved.jsx'
import SignInForm from './SignInForm.jsx'
import Startup from './Startup.jsx'
import Welcome from './Welcome.jsx'

// The setup flow, shown until the app is signed in to IBKR. `login` is the state from useLogin;
// `onChange` asks it to check again right away.
function Setup({ login, onChange }) {
  // null while loading; then 'welcome' (first run), 'install' or 'signin'
  const [step, setStep] = useState(null)
  // The password stays in this form only until signing in works; it's never stored
  const [form, setForm] = useState({ mode: 'paper', username: '', password: '', error: null })
  // True once this screen started a sign-in, so its progress shows on the form (an automatic
  // sign-in at launch shows the startup screen instead)
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    Promise.all([savedLogin(), gatewayStatus()])
      .then(([saved, gateway]) => {
        setForm((f) => ({ ...f, username: saved.username ?? '', mode: saved.mode ?? 'paper' }))
        if (!saved.username) setStep('welcome')
        else setStep(gateway.installed ? 'signin' : 'install')
      })
      .catch(() => setStep('signin'))
  }, [])

  const state = login?.state
  const busy = submitted && (state === 'starting' || state === 'signing_in')

  let screen = step
  if (state === 'awaiting_approval') screen = 'approve'
  else if (state === 'not_approved') screen = 'not_approved'
  else if (!submitted && (state === 'starting' || state === 'signing_in')) screen = 'auto'

  useEffect(() => {
    if (screen === 'welcome' || screen === 'install') sizeWindowFor(screen)
    else if (screen && screen !== 'auto') sizeWindowFor('signin')
  }, [screen])

  async function submit() {
    if (!form.username.trim() || !form.password) {
      setForm((f) => ({ ...f, error: 'Enter your IBKR username and password.' }))
      return
    }
    setSubmitted(true)
    try {
      await signIn(form)
      onChange()
    } catch (err) {
      setForm((f) => ({ ...f, error: String(err) }))
    }
  }

  async function backToForm() {
    await cancelSignIn()
    setSubmitted(false)
    setStep('signin')
    onChange()
  }

  if (screen === null) return <Startup />
  if (screen === 'auto') return <Startup label="Signing in to IBKR…" />
  if (screen === 'welcome') return <Welcome onStart={() => setStep('install')} />
  if (screen === 'install') return <InstallGateway onBack={() => setStep('welcome')} onContinue={() => setStep('signin')} />
  if (screen === 'approve') return <ApproveOnPhone username={form.username} onCancel={backToForm} />
  if (screen === 'not_approved') return <LoginNotApproved onBack={backToForm} onTryAgain={submit} />
  return <SignInForm form={form} setForm={setForm} busy={busy} login={login} onSubmit={submit} />
}

export default Setup
