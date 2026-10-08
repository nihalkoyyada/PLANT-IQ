import React, { useState } from 'react';
import {
  Activity,
  ShieldCheck,
  Lock,
  Mail,
  User,
  Eye,
  EyeOff,
  AlertCircle,
  Loader2,
  CheckCircle2,
  UserPlus,
  ArrowRight,
  Crown,
  Settings,
  BarChart3,
  LayoutGrid,
  Leaf,
  Building2,
} from 'lucide-react';
import { registerApi } from '../api/auth';

interface RegisterPageProps {
  onNavigateLogin: (registeredEmail?: string) => void;
}

export const RegisterPage: React.FC<RegisterPageProps> = ({ onNavigateLogin }) => {
  const [organizationName, setOrganizationName] = useState<string>(
    'Surya Power Corp — Surya Solar Farm (50MW)'
  );
  const [fullName, setFullName] = useState<string>('');
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');
  const [role, setRole] = useState<'admin' | 'engineer' | 'viewer'>('viewer');

  const [showPassword, setShowPassword] = useState<boolean>(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setErrorMessage(null);

    const trimmedFullName = fullName.trim();
    const trimmedEmail = email.trim();

    // Validation 1: Required fields
    if (!trimmedFullName || !trimmedEmail || !password || !confirmPassword || !role) {
      setErrorMessage('Please fill in all required fields.');
      return;
    }

    // Validation 2: Role check
    if (!['admin', 'engineer', 'viewer'].includes(role)) {
      setErrorMessage('Invalid role selected.');
      return;
    }

    // Validation 3: Email format
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(trimmedEmail)) {
      setErrorMessage('Please enter a valid email address.');
      return;
    }

    // Validation 4: Password minimum length (backend enforces min 6 chars)
    if (password.length < 6) {
      setErrorMessage('Password must be at least 6 characters long.');
      return;
    }

    // Validation 5: Password match
    if (password !== confirmPassword) {
      setErrorMessage('Passwords do not match.');
      return;
    }

    setIsSubmitting(true);

    try {
      await registerApi({
        email: trimmedEmail,
        password,
        full_name: trimmedFullName,
        organization_name: organizationName,
        role,
      });

      // Registration successful -> Navigate back to login screen
      onNavigateLogin();
    } catch (err: any) {
      console.error('Registration failed:', err);
      if (!err.response) {
        setErrorMessage('Unable to connect to PlantIQ authentication service. Please try again.');
      } else if (
        err.response.status === 409 ||
        err.response.data?.detail?.toLowerCase().includes('already exists')
      ) {
        setErrorMessage('An account with this email already exists.');
      } else if (err.response.status === 422) {
        const detail = err.response.data?.detail;
        if (typeof detail === 'string') {
          setErrorMessage(detail);
        } else if (Array.isArray(detail) && detail[0]?.msg) {
          setErrorMessage(detail[0].msg);
        } else {
          setErrorMessage('Invalid role or registration details provided.');
        }
      } else {
        const detail = err.response?.data?.detail || 'Registration failed. Please try again.';
        setErrorMessage(detail);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="min-h-screen bg-cover bg-center bg-no-repeat text-slate-800 flex flex-col justify-between font-sans relative overflow-x-hidden"
      style={{ backgroundImage: `url('/solar_farm_daylight_bg.jpg')` }}
    >
      {/* Background Gradient Vignette Overlay for Readability */}
      <div className="absolute inset-0 bg-gradient-to-r from-slate-950/80 via-slate-900/40 to-slate-900/10 pointer-events-none" />

      {/* Top Navigation Bar Header */}
      <header className="w-full max-w-[1550px] mx-auto px-6 py-5 flex items-center justify-between z-20">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#004874] flex items-center justify-center shadow-lg border border-sky-400/30">
            <Activity className="w-6 h-6 text-sky-300" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-2xl font-black tracking-tight text-white drop-shadow-md">
                PlantIQ
              </span>
            </div>
            <p className="text-[10px] font-mono text-sky-100 uppercase tracking-widest font-semibold drop-shadow">
              Industrial Telemetry Platform
            </p>
          </div>
        </div>

        {/* Top Right Floating Translucent Badge */}
        <div className="hidden sm:flex items-center gap-2 px-4 py-1.5 rounded-full bg-slate-900/50 border border-white/20 backdrop-blur-md text-xs text-white font-mono shadow-md">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span>Secure • Reliable • Scalable</span>
        </div>
      </header>

      {/* Main Container - Split Screen Hero & Registration Card */}
      <main className="flex-1 w-full max-w-[1550px] mx-auto px-6 py-4 md:py-6 flex flex-col lg:flex-row items-center justify-between gap-8 z-10">
        {/* LEFT HERO SECTION */}
        <div className="w-full lg:w-[48%] flex flex-col justify-between space-y-8 text-white my-auto">
          {/* Main Headline */}
          <div className="space-y-3">
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold text-white tracking-tight leading-[1.1] drop-shadow-lg">
              Powering Smarter <br />
              <span className="text-white">Solar Operations</span>
            </h1>
            <p className="text-sm md:text-base text-slate-200 font-normal leading-relaxed max-w-lg drop-shadow">
              Real-time SCADA telemetry, analytics and insights for a more reliable and sustainable future.
            </p>
          </div>

          {/* 4 Feature Highlights Grid (2x2 Layout) */}
          <div className="grid grid-cols-2 gap-4 max-w-md">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-white/10 backdrop-blur-md border border-white/20 flex items-center justify-center shrink-0">
                <BarChart3 className="w-5 h-5 text-sky-300" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white">Real-time</h4>
                <p className="text-[11px] text-slate-200">Monitoring</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-white/10 backdrop-blur-md border border-white/20 flex items-center justify-center shrink-0">
                <ShieldCheck className="w-5 h-5 text-sky-300" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white">Data-driven</h4>
                <p className="text-[11px] text-slate-200">Insights</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-white/10 backdrop-blur-md border border-white/20 flex items-center justify-center shrink-0">
                <LayoutGrid className="w-5 h-5 text-sky-300" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white">Multi-plant</h4>
                <p className="text-[11px] text-slate-200">Management</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-white/10 backdrop-blur-md border border-white/20 flex items-center justify-center shrink-0">
                <Leaf className="w-5 h-5 text-emerald-300" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white">Reliable &</h4>
                <p className="text-[11px] text-slate-200">Sustainable</p>
              </div>
            </div>
          </div>

          {/* Telemetry Visualization Card */}
          <div className="p-5 rounded-2xl bg-slate-900/60 backdrop-blur-md border border-cyan-500/30 shadow-2xl max-w-md space-y-3">
            <div className="flex items-center justify-between text-xs font-mono">
              <span className="text-slate-300 font-bold">PLANT GENERATION (MW)</span>
              <span className="flex items-center gap-1.5 text-emerald-400 font-bold bg-emerald-500/20 px-2.5 py-0.5 rounded-full border border-emerald-500/30 text-[10px]">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                LIVE
              </span>
            </div>

            <div className="flex items-end justify-between pt-1 gap-4">
              {/* Wave SVG Area Chart */}
              <div className="flex-1 h-14 relative">
                <svg className="w-full h-full" viewBox="0 0 200 60" preserveAspectRatio="none">
                  <defs>
                    <linearGradient id="cyanGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.4" />
                      <stop offset="100%" stopColor="#0284c7" stopOpacity="0.0" />
                    </linearGradient>
                  </defs>
                  <path
                    d="M 0,40 Q 30,15 60,30 T 120,20 T 170,35 L 200,25 L 200,60 L 0,60 Z"
                    fill="url(#cyanGradient)"
                  />
                  <path
                    d="M 0,40 Q 30,15 60,30 T 120,20 T 170,35 L 200,25"
                    fill="none"
                    stroke="#38bdf8"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                  />
                </svg>
              </div>

              {/* Power Metrics */}
              <div className="space-y-1 font-mono text-right shrink-0">
                <div>
                  <span className="text-[10px] text-slate-300 uppercase mr-2">AC Power</span>
                  <span className="text-sm font-bold text-white">24.02 MW</span>
                </div>
                <div>
                  <span className="text-[10px] text-slate-300 uppercase mr-2">DC Power</span>
                  <span className="text-sm font-bold text-sky-300">53.27 MW</span>
                </div>
              </div>
            </div>

            <div className="pt-2 border-t border-slate-700/60 flex items-center justify-between text-[10px] font-mono text-slate-300">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                SCADA TELEMETRY ACTIVE
              </span>
              <span>LAST UPDATE 17:30</span>
            </div>
          </div>

          {/* Footer Line */}
          <div className="text-[11px] font-mono text-slate-300 flex items-center gap-3">
            <span className="w-6 border-b border-sky-400/50" />
            <span>Clean Energy &nbsp;|&nbsp; Operational Excellence &nbsp;|&nbsp; A Sustainable Tomorrow</span>
          </div>
        </div>

        {/* RIGHT REGISTRATION CARD */}
        <div className="w-full lg:w-[48%] max-w-[540px] bg-white/95 text-slate-800 rounded-[28px] shadow-2xl backdrop-blur-lg p-6 md:p-8 border border-white/60">
          {/* Card Top Header */}
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[#004874] flex items-center justify-center text-sky-300 shrink-0 shadow-md">
              <Activity className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-slate-900 tracking-tight">PlantIQ</span>
              </div>
              <p className="text-[9px] font-mono text-slate-500 uppercase tracking-wider font-semibold">
                INDUSTRIAL TELEMETRY PLATFORM
              </p>
            </div>
          </div>

          {/* Title Section */}
          <div className="mb-5">
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Create Operator Account</h2>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Register for secure SCADA telemetry access
            </p>
          </div>

          {/* Form */}
          <form onSubmit={(e) => e.preventDefault()} autoComplete="off" className="space-y-4">
            {errorMessage && (
              <div className="bg-rose-50 border border-rose-200 text-rose-800 p-3 rounded-xl text-xs flex items-center gap-2.5 font-medium">
                <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
                <span>{errorMessage}</span>
              </div>
            )}

            {/* Plant / Organization Selector */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                ORGANIZATION / PLANT
              </label>
              <div className="relative">
                <Building2 className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                <select
                  value={organizationName}
                  onChange={(e) => setOrganizationName(e.target.value)}
                  className="w-full text-xs font-semibold bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-8 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500 cursor-pointer appearance-none"
                >
                  <option value="Surya Power Corp — Surya Solar Farm (50MW)">
                    🟢 Surya Power Corp — Surya Solar Farm (50MW)
                  </option>
                  <option value="Surya Power Corp — Surya Solar Farm Phase 2 (25MW)">
                    🟢 Surya Power Corp — Surya Solar Farm Phase 2 (25MW)
                  </option>
                </select>
              </div>
            </div>

            {/* Full Name */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                FULL NAME
              </label>
              <div className="relative">
                <User className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  name="user_fullname_field"
                  required
                  autoComplete="off"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="e.g. John Doe"
                  className="w-full text-xs font-sans bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-3 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
            </div>

            {/* Email Address */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                EMAIL ADDRESS
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  name="user_email_field"
                  required
                  autoComplete="off"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="e.g. john@example.com"
                  className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-3 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
              </div>
            </div>

            {/* Role Selection (3 Cards) */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1 flex items-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5 text-[#004874]" /> SELECT ROLE
              </label>
              <div className="grid grid-cols-3 gap-2">
                {/* Admin Role Card */}
                <button
                  type="button"
                  onClick={() => setRole('admin')}
                  className={`p-2.5 border rounded-xl text-left transition relative cursor-pointer flex flex-col justify-between min-h-[85px] ${
                    role === 'admin'
                      ? 'bg-sky-50/80 border-sky-500 ring-2 ring-sky-500/20 shadow-sm'
                      : 'bg-slate-50 border-slate-200 hover:border-slate-300'
                  }`}
                >
                  {role === 'admin' && (
                    <CheckCircle2 className="w-4 h-4 text-sky-600 absolute top-2 right-2" />
                  )}
                  <div className="flex items-center gap-1.5 text-amber-500">
                    <Crown className="w-4 h-4 fill-amber-400/20" />
                    <span className="font-bold text-xs text-slate-900">Admin</span>
                  </div>
                  <p className="text-[9px] text-slate-500 leading-tight">Full access & user management</p>
                </button>

                {/* Engineer Role Card */}
                <button
                  type="button"
                  onClick={() => setRole('engineer')}
                  className={`p-2.5 border rounded-xl text-left transition relative cursor-pointer flex flex-col justify-between min-h-[85px] ${
                    role === 'engineer'
                      ? 'bg-sky-50/80 border-sky-500 ring-2 ring-sky-500/20 shadow-sm'
                      : 'bg-slate-50 border-slate-200 hover:border-slate-300'
                  }`}
                >
                  {role === 'engineer' && (
                    <CheckCircle2 className="w-4 h-4 text-sky-600 absolute top-2 right-2" />
                  )}
                  <div className="flex items-center gap-1.5 text-sky-600">
                    <Settings className="w-4 h-4" />
                    <span className="font-bold text-xs text-slate-900">Engineer</span>
                  </div>
                  <p className="text-[9px] text-slate-500 leading-tight">Operations & data management</p>
                </button>

                {/* Viewer Role Card */}
                <button
                  type="button"
                  onClick={() => setRole('viewer')}
                  className={`p-2.5 border rounded-xl text-left transition relative cursor-pointer flex flex-col justify-between min-h-[85px] ${
                    role === 'viewer'
                      ? 'bg-sky-50/80 border-sky-500 ring-2 ring-sky-500/20 shadow-sm'
                      : 'bg-slate-50 border-slate-200 hover:border-slate-300'
                  }`}
                >
                  {role === 'viewer' && (
                    <CheckCircle2 className="w-4 h-4 text-sky-600 absolute top-2 right-2" />
                  )}
                  <div className="flex items-center gap-1.5 text-cyan-600">
                    <Eye className="w-4 h-4" />
                    <span className="font-bold text-xs text-slate-900">Viewer</span>
                  </div>
                  <p className="text-[9px] text-slate-500 leading-tight">Read-only access to telemetry</p>
                </button>
              </div>
            </div>

            {/* Password */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                PASSWORD (MIN 6 CHARS)
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  name="user_password_field"
                  style={{ WebkitTextSecurity: showPassword ? 'none' : 'disc' } as any}
                  required
                  autoComplete="off"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="e.g. Min 6 characters"
                  className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-9 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Confirm Password */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                CONFIRM PASSWORD
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  name="user_confirm_password_field"
                  style={{ WebkitTextSecurity: showConfirmPassword ? 'none' : 'disc' } as any}
                  required
                  autoComplete="off"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="e.g. Re-enter password"
                  className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-9 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                >
                  {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Primary Action Button */}
            <button
              type="button"
              onClick={() => handleSubmit()}
              disabled={isSubmitting}
              className="w-full py-3.5 bg-[#004874] hover:bg-[#003354] text-white font-bold text-xs rounded-xl transition shadow-md flex items-center justify-center gap-2 border border-sky-300/30 disabled:opacity-60 cursor-pointer mt-2"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin text-white" />
                  <span>Registering...</span>
                </>
              ) : (
                <>
                  <UserPlus className="w-4 h-4" />
                  <span>Register Operator Account</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>

            {/* Footer Link */}
            <div className="text-center pt-2 border-t border-slate-100 text-xs text-slate-500">
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => onNavigateLogin()}
                className="font-bold text-[#004874] hover:underline cursor-pointer ml-1"
              >
                Sign in
              </button>
            </div>
          </form>
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full py-3 text-center text-[10px] font-mono text-slate-300 z-10">
        PlantIQ SCADA v2.4 • Secure Industrial Telemetry Platform
      </footer>
    </div>
  );
};
