import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  ShieldAlert,
  ShieldCheck,
  Lock,
  Mail,
  Eye,
  EyeOff,
  AlertCircle,
  Loader2,
  CheckCircle2,
  ArrowLeft,
  Building2,
  KeyRound,
  Shield,
} from 'lucide-react';

interface PlatformAdminLoginPageProps {
  onNavigateLogin?: () => void;
  onLoginSuccess?: (role: string) => void;
  initialEmail?: string;
}

export const PlatformAdminLoginPage: React.FC<PlatformAdminLoginPageProps> = ({
  onNavigateLogin,
  onLoginSuccess,
  initialEmail = '',
}) => {
  const { login, logout } = useAuth();
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
      // Pass 'platform_admin' to enforce backend validation
      const user = await login(email.trim(), password, 'platform_admin');
      const role = user?.role?.toLowerCase() || 'viewer';

      // Strict client verification of trusted backend role
      if (role !== 'super_admin') {
        logout();
        setErrorMessage(
          'Access Denied: This portal is strictly for Platform Super Administrators. Organization Administrators must sign in through the SCADA Operational Login.'
        );
        return;
      }

      if (onLoginSuccess) {
        onLoginSuccess(role);
      }
    } catch (err: any) {
      console.error('Platform admin login failed:', err);
      if (!err.response) {
        setErrorMessage('Unable to connect to PlantIQ security service. Please verify network access.');
      } else if (err.response.status === 403) {
        const detail = err.response?.data?.detail;
        setErrorMessage(
          detail || 'Access Denied: This account is not authorized as a Platform Super Administrator.'
        );
      } else if (err.response.status === 401) {
        setErrorMessage('Invalid administrative credentials. Please verify email and security key.');
      } else {
        const detail = err.response?.data?.detail || 'Platform authentication failed.';
        setErrorMessage(detail);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#070d18] text-slate-100 flex flex-col justify-between font-sans relative overflow-x-hidden selection:bg-purple-500 selection:text-white">
      {/* Background Subtle Tech Grid and Radial Glow */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(168,85,247,0.18),rgba(255,255,255,0))] pointer-events-none" />
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: `radial-gradient(circle, #ffffff 1px, transparent 1px)`,
          backgroundSize: '24px 24px',
        }}
      />

      {/* Top Header */}
      <header className="w-full max-w-6xl mx-auto px-6 py-6 flex items-center justify-between z-20">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-purple-700 to-indigo-600 flex items-center justify-center shadow-lg shadow-purple-950/50 border border-purple-400/30">
            <ShieldCheck className="w-6 h-6 text-purple-200" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl font-black tracking-tight text-white">
                PlantIQ
              </span>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-wider bg-purple-950/80 text-purple-300 border border-purple-500/40">
                PLATFORM SUPER ADMIN CONSOLE
              </span>
            </div>
            <p className="text-[10px] font-mono text-slate-400 uppercase tracking-widest font-semibold">
              Root SaaS Infrastructure & Tenant Governance
            </p>
          </div>
        </div>

        {/* Back to SCADA Operations Button */}
        {onNavigateLogin && (
          <button
            type="button"
            onClick={onNavigateLogin}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-lg bg-slate-900/80 hover:bg-slate-800 border border-slate-700/80 text-xs font-semibold text-slate-300 hover:text-white transition cursor-pointer backdrop-blur-sm"
          >
            <ArrowLeft className="w-3.5 h-3.5 text-sky-400" />
            <span>SCADA Operational Login</span>
          </button>
        )}
      </header>

      {/* Main Admin Login Card */}
      <main className="flex-1 w-full max-w-md mx-auto px-6 py-8 flex flex-col justify-center z-10">
        <div className="bg-slate-900/95 border border-purple-900/50 rounded-2xl p-7 md:p-8 shadow-2xl shadow-black/80 backdrop-blur-xl relative">
          {/* Top Accent Border */}
          <div className="absolute top-0 left-8 right-8 h-[2px] bg-gradient-to-r from-transparent via-purple-500 to-transparent" />

          {/* Header section */}
          <div className="mb-6 text-center">
            <div className="w-12 h-12 rounded-xl bg-purple-950/60 border border-purple-500/40 text-purple-300 flex items-center justify-center mx-auto mb-3 shadow-inner">
              <KeyRound className="w-6 h-6" />
            </div>
            <h1 className="text-lg font-bold text-white tracking-tight">
              Platform Super Admin Sign In
            </h1>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              Restricted strictly to Platform Super Administrators (<span className="font-mono text-purple-300 font-semibold">super_admin</span>).
            </p>
          </div>

          {/* Error Banner */}
          {errorMessage && (
            <div className="mb-5 p-3 rounded-xl bg-rose-950/60 border border-rose-800/80 flex items-start gap-2.5 text-xs text-rose-200 animate-in fade-in duration-200">
              <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <div className="leading-relaxed font-medium">{errorMessage}</div>
            </div>
          )}

          {/* Admin Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Scope Badge */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-400 font-semibold mb-1">
                SECURITY PRIVILEGE
              </label>
              <div className="flex items-center gap-2 px-3 py-2 bg-slate-950/70 border border-purple-900/40 rounded-xl text-xs font-mono text-purple-300">
                <Building2 className="w-4 h-4 text-purple-400 shrink-0" />
                <span className="truncate">Root Multi-Tenant Platform Control Plane</span>
              </div>
            </div>

            {/* Admin Email */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-400 font-semibold mb-1">
                SUPER ADMIN EMAIL
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type="email"
                  name="super_admin_email"
                  required
                  autoComplete="off"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="root_superadmin@plantiq.io"
                  className="w-full text-xs font-mono bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-3 py-2.5 text-white placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-purple-500/80 focus:border-purple-500/80"
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <label className="block text-[10px] font-mono uppercase text-slate-400 font-semibold mb-1">
                SECURITY CREDENTIAL
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  name="super_admin_password"
                  required
                  autoComplete="off"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full text-xs font-mono bg-slate-950/80 border border-slate-800 rounded-xl pl-9 pr-9 py-2.5 text-white placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-purple-500/80 focus:border-purple-500/80"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 cursor-pointer"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3.5 bg-gradient-to-r from-purple-800 to-indigo-600 hover:from-purple-700 hover:to-indigo-500 text-white font-bold text-xs rounded-xl transition shadow-lg shadow-purple-950/60 flex items-center justify-center gap-2 border border-purple-400/30 disabled:opacity-60 cursor-pointer mt-2"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin text-white" />
                  <span>Verifying Super Admin Credentials...</span>
                </>
              ) : (
                <>
                  <ShieldCheck className="w-4 h-4" />
                  <span>Authenticate Super Admin</span>
                </>
              )}
            </button>

            {/* Notice for Org Admins & Operators */}
            <div className="pt-3 border-t border-slate-800/80 text-center space-y-1.5">
              <p className="text-[11px] text-slate-400">
                Organization Admins, Field Engineers & Viewers:{' '}
                {onNavigateLogin ? (
                  <button
                    type="button"
                    onClick={onNavigateLogin}
                    className="font-bold text-purple-400 hover:underline cursor-pointer"
                  >
                    Go to SCADA Login
                  </button>
                ) : (
                  <a href="/login" className="font-bold text-purple-400 hover:underline">
                    Go to SCADA Login
                  </a>
                )}
              </p>
              <p className="text-[10px] text-slate-500">
                Organization Admins must authenticate via their designated operational entry point.
              </p>
            </div>

            {/* Security clearance badge */}
            <div className="flex items-center justify-center gap-2 text-[10px] font-mono text-purple-300/80 bg-purple-950/40 py-2 px-3 rounded-lg border border-purple-900/40">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>Multi-Tenant Platform Control • Audited Session</span>
            </div>
          </form>
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full py-4 text-center text-[10px] font-mono text-slate-500 z-10 border-t border-slate-900/60">
        PlantIQ SaaS Platform Administration • Strictly Restricted to Platform Super Administrators
      </footer>
    </div>
  );
};

export default PlatformAdminLoginPage;
