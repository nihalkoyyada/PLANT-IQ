import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Activity, Shield, Lock, Mail, Eye, EyeOff, AlertCircle, Loader2, KeyRound, CheckCircle2 } from 'lucide-react';
import { Badge } from '../components/common/Badge';

export const LoginPage: React.FC = () => {
  const { login } = useAuth();
  const [email, setEmail] = useState<string>('admin@surya.plantiq.ai');
  const [password, setPassword] = useState<string>('SuryaAdmin#2026');
  const [showPassword, setShowPassword] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
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

  const fillDemoCredentials = (demoEmail: string, demoPw: string) => {
    setEmail(demoEmail);
    setPassword(demoPw);
    setErrorMessage(null);
  };

  return (
    <div className="min-h-screen bg-[#f0f4fa] flex flex-col items-center justify-center p-4 font-sans text-slate-800">
      <div className="w-full max-w-[520px] bg-white rounded-2xl border border-slate-200/90 shadow-xl overflow-hidden my-6">
        {/* Top Header Card */}
        <div className="bg-[#004874] p-6 text-white text-center border-b border-sky-600/30">
          <div className="flex items-center justify-center gap-2 mb-2">
            <div className="w-10 h-10 rounded-xl bg-white/10 backdrop-blur-md flex items-center justify-center border border-white/20">
              <Activity className="w-6 h-6 text-sky-300" />
            </div>
            <div className="text-left">
              <div className="flex items-center gap-2">
                <span className="text-xl font-bold tracking-tight text-white">PlantIQ</span>
                <Badge variant="navy">SCADA v2.4</Badge>
              </div>
              <p className="text-[10px] font-mono text-sky-200 uppercase tracking-wider font-semibold">
                Industrial Telemetry Platform
              </p>
            </div>
          </div>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 md:p-8 space-y-5">
          <div className="text-center pb-1">
            <h2 className="text-lg font-bold text-slate-900">Secure SCADA Access</h2>
            <p className="text-xs text-slate-500 font-medium">Authenticate your PlantIQ operator account</p>
          </div>

          {errorMessage && (
            <div className="bg-rose-50 border border-rose-200 text-rose-800 p-3 rounded-xl text-xs flex items-center gap-2.5">
              <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
              <span>{errorMessage}</span>
            </div>
          )}

          {/* Plant / Node Selector */}
          <div>
            <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
              ORGANIZATION / PLANT SELECTOR
            </label>
            <select className="w-full text-xs font-semibold bg-slate-50 border border-slate-200 rounded-xl p-3 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500 cursor-pointer">
              <option>🟢 Surya Power Corp — Surya Solar Farm (50MW)</option>
              <option>🟢 Surya Power Corp — Surya Solar Farm Phase 2 (25MW)</option>
            </select>
          </div>

          {/* Email */}
          <div>
            <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
              OPERATOR EMAIL
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@surya.plantiq.ai"
                className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-3 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
            </div>
          </div>

          {/* Password */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-[10px] font-mono uppercase text-slate-500 font-semibold">
                PASSWORD
              </label>
            </div>
            <div className="relative">
              <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type={showPassword ? 'text' : 'password'}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
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
            type="submit"
            disabled={isSubmitting}
            className="w-full py-3 bg-[#004874] hover:bg-[#003354] text-white font-bold text-xs rounded-xl transition shadow-md flex items-center justify-center gap-2 border border-sky-300/30 disabled:opacity-60 cursor-pointer"
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

          {/* Secure Session Indicator */}
          <div className="flex items-center justify-center gap-2 text-[11px] font-mono text-sky-800 bg-sky-50 py-2 px-3 rounded-lg border border-sky-100">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
            <span>Secure JWT Session • Organization-isolated access</span>
          </div>

          {/* Quick Demo Credentials Assistant */}
          <div className="pt-3 border-t border-slate-100 space-y-2">
            <div className="flex items-center justify-between text-[11px] font-mono font-semibold text-slate-500">
              <span className="flex items-center gap-1">
                <KeyRound className="w-3.5 h-3.5 text-sky-600" /> SELECT REAL DEMO ROLE:
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              <button
                type="button"
                onClick={() => fillDemoCredentials('admin@surya.plantiq.ai', 'SuryaAdmin#2026')}
                className="p-2 bg-slate-50 hover:bg-sky-50 border border-slate-200 hover:border-sky-300 rounded-xl text-center text-xs font-semibold transition cursor-pointer"
              >
                <div className="font-bold text-slate-800">Admin Demo</div>
                <div className="text-[9px] font-mono text-sky-700 font-bold">ADMIN</div>
              </button>
              <button
                type="button"
                onClick={() => fillDemoCredentials('engineer@surya.plantiq.ai', 'SuryaEngineer#2026')}
                className="p-2 bg-slate-50 hover:bg-sky-50 border border-slate-200 hover:border-sky-300 rounded-xl text-center text-xs font-semibold transition cursor-pointer"
              >
                <div className="font-bold text-slate-800">Engineer Demo</div>
                <div className="text-[9px] font-mono text-sky-700 font-bold">ENGINEER</div>
              </button>
              <button
                type="button"
                onClick={() => fillDemoCredentials('viewer@surya.plantiq.ai', 'SuryaViewer#2026')}
                className="p-2 bg-slate-50 hover:bg-sky-50 border border-slate-200 hover:border-sky-300 rounded-xl text-center text-xs font-semibold transition cursor-pointer"
              >
                <div className="font-bold text-slate-800">Viewer Demo</div>
                <div className="text-[9px] font-mono text-sky-700 font-bold">VIEWER</div>
              </button>
            </div>
          </div>
        </form>

        {/* Footer */}
        <div className="bg-slate-50 px-6 py-3 border-t border-slate-200/80 text-center text-[10px] font-mono text-slate-500">
          PlantIQ SCADA v2.4 • Secure Industrial Telemetry Platform
        </div>
      </div>
    </div>
  );
};
