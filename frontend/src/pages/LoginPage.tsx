import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  Activity,
  Shield,
  Lock,
  Mail,
  Eye,
  EyeOff,
  AlertCircle,
  Loader2,
  CheckCircle2,
  BarChart3,
  LayoutGrid,
  Leaf,
  Building2,
} from 'lucide-react';

interface LoginPageProps {
  onNavigateRegister?: () => void;
  successMessage?: string | null;
  initialEmail?: string;
}

export const LoginPage: React.FC<LoginPageProps> = ({
  onNavigateRegister,
  initialEmail = '',
}) => {
  const { login } = useAuth();
  const [email, setEmail] = useState<string>(initialEmail);
  const [password, setPassword] = useState<string>('');
  const [showPassword, setShowPassword] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setErrorMessage(null);
    setIsSubmitting(true);

    try {
      await login(email.trim(), password);
    } catch (err: any) {
      console.error('Login failed:', err);
      if (!err.response) {
        setErrorMessage('Unable to connect to PlantIQ authentication service. Please try again.');
      } else if (err.response.status === 401) {
        setErrorMessage('Invalid email or password');
      } else {
        const detail = err.response?.data?.detail || 'Authentication failed. Please try again.';
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
          <Shield className="w-4 h-4 text-emerald-400" />
          <span>Secure • Reliable • Scalable</span>
        </div>
      </header>

      {/* Main Container - Split Screen Hero & Login Card */}
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
                <Shield className="w-5 h-5 text-sky-300" />
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
              <div className="flex-1 h-14 relative">
                <svg className="w-full h-full" viewBox="0 0 200 60" preserveAspectRatio="none">
                  <defs>
                    <linearGradient id="cyanGradientLogin" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.4" />
                      <stop offset="100%" stopColor="#0284c7" stopOpacity="0.0" />
                    </linearGradient>
                  </defs>
                  <path
                    d="M 0,40 Q 30,15 60,30 T 120,20 T 170,35 L 200,25 L 200,60 L 0,60 Z"
                    fill="url(#cyanGradientLogin)"
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

        {/* RIGHT SIGN IN CARD */}
        <div className="w-full lg:w-[48%] max-w-[520px] bg-white/95 text-slate-800 rounded-[28px] shadow-2xl backdrop-blur-lg p-6 md:p-8 border border-white/60 my-auto">
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
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Secure SCADA Access</h2>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Authenticate your PlantIQ operator account
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
                ORGANIZATION / PLANT SELECTOR
              </label>
              <div className="relative">
                <Building2 className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                <select className="w-full text-xs font-semibold bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-8 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500 cursor-pointer appearance-none">
                  <option>🟢 Surya Power Corp — Surya Solar Farm (50MW)</option>
                  <option>🟢 Surya Power Corp — Surya Solar Farm Phase 2 (25MW)</option>
                </select>
              </div>
            </div>

            {/* Operator Email */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                OPERATOR EMAIL
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  name="op_login_email_field"
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

            {/* Password */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                PASSWORD
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  name="op_login_password_field"
                  style={{ WebkitTextSecurity: showPassword ? 'none' : 'disc' } as any}
                  required
                  autoComplete="off"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="e.g. Enter your password"
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

            {/* Sign In Button */}
            <button
              type="button"
              onClick={() => handleSubmit()}
              disabled={isSubmitting}
              className="w-full py-3.5 bg-[#004874] hover:bg-[#003354] text-white font-bold text-xs rounded-xl transition shadow-md flex items-center justify-center gap-2 border border-sky-300/30 disabled:opacity-60 cursor-pointer mt-2"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin text-white" />
                  <span>Authenticating...</span>
                </>
              ) : (
                <>
                  <Lock className="w-4 h-4" />
                  <span>Sign In to PlantIQ</span>
                </>
              )}
            </button>

            {/* Link to Registration */}
            <div className="text-center pt-2 border-t border-slate-100 text-xs text-slate-500">
              Don't have an account?{' '}
              <button
                type="button"
                onClick={onNavigateRegister}
                className="font-bold text-[#004874] hover:underline cursor-pointer ml-1"
              >
                Register
              </button>
            </div>

            {/* Secure Session Indicator */}
            <div className="flex items-center justify-center gap-2 text-[11px] font-mono text-sky-800 bg-sky-50 py-2 px-3 rounded-lg border border-sky-100">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
              <span>Secure JWT Session • Organization-isolated access</span>
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
