import React, { useEffect, useState } from 'react';
import {
  Activity,
  ShieldCheck,
  Lock,
  Mail,
  User as UserIcon,
  Eye,
  EyeOff,
  AlertCircle,
  Loader2,
  CheckCircle2,
  Building2,
  Ticket,
  ArrowRight,
  ShieldAlert,
  BarChart3,
  LayoutGrid,
  Shield,
  ArrowLeft,
} from 'lucide-react';
import { acceptInvitationApi, registerApi, verifyInvitationApi } from '../api/auth';
import { LiveTelemetryWidget } from '../components/common/LiveTelemetryWidget';

interface RegisterPageProps {
  onNavigateLogin: (registeredEmail?: string) => void;
}

export const RegisterPage: React.FC<RegisterPageProps> = ({ onNavigateLogin }) => {
  const [invitationToken, setInvitationToken] = useState<string>('');
  const [isVerifyingToken, setIsVerifyingToken] = useState<boolean>(false);
  const [verifiedInvitation, setVerifiedInvitation] = useState<{
    email: string;
    full_name: string;
    role: string;
    org_id: string;
    org_name: string;
    expires_at: string;
  } | null>(null);

  // Form states
  const [fullName, setFullName] = useState<string>('');
  const [email, setEmail] = useState<string>('');
  const [password, setPassword] = useState<string>('');
  const [confirmPassword, setConfirmPassword] = useState<string>('');

  const [showPassword, setShowPassword] = useState<boolean>(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Check URL parameters for invitation_token on mount
  useEffect(() => {
    try {
      const searchParams = new URLSearchParams(window.location.search);
      const token = searchParams.get('invitation_token') || searchParams.get('token');
      if (token) {
        setInvitationToken(token.trim());
        verifyToken(token.trim());
      }
    } catch {
      // ignore
    }
  }, []);

  const verifyToken = async (tokenToVerify: string) => {
    if (!tokenToVerify) return;
    setIsVerifyingToken(true);
    setErrorMessage(null);
    try {
      const res = await verifyInvitationApi(tokenToVerify);
      if (res.valid) {
        setVerifiedInvitation(res);
        setEmail(res.email);
        setFullName(res.full_name);
      }
    } catch (err: any) {
      console.error('Token verification error:', err);
      const detail = err?.response?.data?.detail || 'Invalid or expired invitation token.';
      setErrorMessage(detail);
      setVerifiedInvitation(null);
    } finally {
      setIsVerifyingToken(false);
    }
  };

  const handleManualVerify = (e: React.FormEvent) => {
    e.preventDefault();
    if (!invitationToken.trim()) {
      setErrorMessage('Please enter an invitation token.');
      return;
    }
    verifyToken(invitationToken.trim());
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setErrorMessage(null);

    // Validation 1: Passwords
    if (!password || !confirmPassword) {
      setErrorMessage('Please enter and confirm your password.');
      return;
    }
    if (password.length < 6) {
      setErrorMessage('Password must be at least 6 characters long.');
      return;
    }
    if (password !== confirmPassword) {
      setErrorMessage('Passwords do not match.');
      return;
    }

    setIsSubmitting(true);

    try {
      if (verifiedInvitation && invitationToken) {
        // Controlled Invitation Acceptance workflow
        await acceptInvitationApi(invitationToken, password);
        setSuccessMessage('Account activated successfully! Redirecting to login...');
        setTimeout(() => {
          onNavigateLogin(email);
        }, 1500);
      } else {
        // Fallback public registration without invitation: strictly unprivileged viewer with NO organization
        if (!fullName.trim() || !email.trim()) {
          setErrorMessage('Please fill in your full name and email address.');
          setIsSubmitting(false);
          return;
        }
        await registerApi({
          email: email.trim(),
          password,
          full_name: fullName.trim(),
          role: 'viewer', // Never trust client; strictly unprivileged viewer
        });
        setSuccessMessage('Registration successful! Redirecting to login...');
        setTimeout(() => {
          onNavigateLogin(email.trim());
        }, 1500);
      }
    } catch (err: any) {
      console.error('Registration/Activation failed:', err);
      const detail = err?.response?.data?.detail || 'Registration failed. Please verify your details.';
      setErrorMessage(detail);
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

        {/* Top Right Actions */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onNavigateLogin()}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-slate-900/60 hover:bg-slate-900/90 border border-white/20 backdrop-blur-md text-xs text-white font-mono shadow-md transition cursor-pointer"
          >
            <ArrowLeft className="w-3.5 h-3.5 text-sky-400" />
            <span>Sign In to SCADA</span>
          </button>
        </div>
      </header>

      {/* Main Container - Split Screen Hero & Registration Card */}
      <main className="flex-1 w-full max-w-[1550px] mx-auto px-6 py-4 md:py-6 flex flex-col lg:flex-row items-center justify-between gap-8 z-10">
        {/* LEFT HERO SECTION */}
        <div className="w-full lg:w-[48%] flex flex-col justify-between space-y-8 text-white my-auto">
          <div className="space-y-3">
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-extrabold text-white tracking-tight leading-[1.1] drop-shadow-lg">
              Powering Smarter <br />
              <span className="text-white">Solar Operations</span>
            </h1>
            <p className="text-sm md:text-base text-slate-200 font-normal leading-relaxed max-w-lg drop-shadow">
              Real-time SCADA telemetry, analytics and insights for a more reliable and sustainable future.
            </p>
          </div>

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
                <Shield className="w-5 h-5 text-emerald-300" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white">Controlled</h4>
                <p className="text-[11px] text-slate-200">Access & RBAC</p>
              </div>
            </div>
          </div>

          <LiveTelemetryWidget />

          <div className="text-[11px] font-mono text-slate-300 flex items-center gap-3">
            <span className="w-6 border-b border-sky-400/50" />
            <span>Enterprise Multi-Tenant Security &nbsp;|&nbsp; Role-Based Access Control</span>
          </div>
        </div>

        {/* RIGHT REGISTRATION / INVITATION ACCEPTANCE CARD */}
        <div className="w-full lg:w-[48%] max-w-[540px] bg-white/95 text-slate-800 rounded-[28px] shadow-2xl backdrop-blur-lg p-6 md:p-8 border border-white/60 my-auto">
          {/* Card Top Header */}
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-[#004874] flex items-center justify-center text-sky-300 shrink-0 shadow-md">
              <Ticket className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-slate-900 tracking-tight">PlantIQ</span>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-wider bg-sky-100 text-[#004874]">
                  {verifiedInvitation ? 'INVITATION ACCEPTANCE' : 'CONTROLLED ONBOARDING'}
                </span>
              </div>
              <p className="text-[9px] font-mono text-slate-500 uppercase tracking-wider font-semibold">
                INDUSTRIAL TELEMETRY PLATFORM
              </p>
            </div>
          </div>

          {/* Title Section */}
          <div className="mb-4">
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">
              {verifiedInvitation ? 'Accept Organization Invitation' : 'Create Operator Account'}
            </h2>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              {verifiedInvitation
                ? 'Set up your credentials to join your assigned organization'
                : 'Controlled onboarding for verified Field Engineers, Viewers, and Operators'}
            </p>
          </div>

          {/* Feedback Banners */}
          {errorMessage && (
            <div className="bg-rose-50 border border-rose-200 text-rose-800 p-3 rounded-xl text-xs flex items-center gap-2.5 font-medium mb-4">
              <AlertCircle className="w-4 h-4 text-rose-600 shrink-0" />
              <span>{errorMessage}</span>
            </div>
          )}

          {successMessage && (
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 p-3 rounded-xl text-xs flex items-center gap-2.5 font-medium mb-4">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>{successMessage}</span>
            </div>
          )}

          {/* SCENARIO A: Verified Invitation Form */}
          {verifiedInvitation ? (
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Organization & Role Locked Badges */}
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-[10px] text-slate-500 uppercase font-semibold">
                    ASSIGNED ORGANIZATION
                  </span>
                  <span className="font-bold text-slate-800 flex items-center gap-1.5">
                    <Building2 className="w-3.5 h-3.5 text-[#004874]" />
                    {verifiedInvitation.org_name}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs pt-2 border-t border-slate-200">
                  <span className="font-mono text-[10px] text-slate-500 uppercase font-semibold">
                    VERIFIED ROLE
                  </span>
                  <span className="px-2 py-0.5 rounded text-[11px] font-mono font-bold uppercase bg-[#004874] text-white">
                    {verifiedInvitation.role.toUpperCase()}
                  </span>
                </div>
              </div>

              {/* Full Name */}
              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                  FULL NAME
                </label>
                <div className="relative">
                  <UserIcon className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    className="w-full text-xs font-sans bg-slate-50 border border-slate-200 rounded-xl pl-9 pr-3 py-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
                  />
                </div>
              </div>

              {/* Email Address (Read-only) */}
              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                  INVITED EMAIL ADDRESS (VERIFIED)
                </label>
                <div className="relative">
                  <Mail className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="email"
                    readOnly
                    value={email}
                    className="w-full text-xs font-mono bg-slate-100 border border-slate-200 rounded-xl pl-9 pr-3 py-2.5 text-slate-600 cursor-not-allowed"
                  />
                </div>
              </div>

              {/* Password */}
              <div>
                <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                  SET ACCOUNT PASSWORD (MIN 6 CHARACTERS)
                </label>
                <div className="relative">
                  <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type={showPassword ? 'text' : 'password'}
                    required
                    minLength={6}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Enter your new password"
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
                    type={showConfirmPassword ? 'text' : 'password'}
                    required
                    minLength={6}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm your password"
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

              {/* Submit Button */}
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full py-3.5 bg-[#004874] hover:bg-[#003354] text-white font-bold text-xs rounded-xl transition shadow-md flex items-center justify-center gap-2 border border-sky-300/30 disabled:opacity-60 cursor-pointer mt-2"
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin text-white" />
                    <span>Activating Account...</span>
                  </>
                ) : (
                  <>
                    <ShieldCheck className="w-4 h-4" />
                    <span>Activate Account & Join Organization</span>
                  </>
                )}
              </button>
            </form>
          ) : (
            /* SCENARIO B: No Token / Manual Token Entry */
            <div className="space-y-4">
              {/* Enterprise Security Notice */}
              <div className="p-3.5 bg-sky-50/70 border border-sky-200 rounded-xl space-y-1.5 text-xs">
                <div className="flex items-center gap-2 font-bold text-sky-950">
                  <ShieldAlert className="w-4 h-4 text-[#004874]" />
                  <span>Enterprise Role-Based Access Policy</span>
                </div>
                <p className="text-slate-600 leading-relaxed text-[11px]">
                  Public role selection is disabled. Super Admin, Organization Admin, Field Engineer, and Viewer accounts cannot be self-registered. Admin accounts provisioned by Platform Admin.
                </p>
                <p className="text-slate-500 text-[10px] italic">
                  Organization Admin or Super Admin access? Contact platform administration for credential provisioning.
                </p>
              </div>

              {/* Manual Invitation Token Input */}
              <form onSubmit={handleManualVerify} className="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
                <label className="block text-[10px] font-mono uppercase text-slate-600 font-bold">
                  HAVE AN INVITATION TOKEN?
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={invitationToken}
                    onChange={(e) => setInvitationToken(e.target.value)}
                    placeholder="Paste invitation token (e.g. qxKWq2...)"
                    className="flex-1 text-xs font-mono bg-white border border-slate-300 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#004874]"
                  />
                  <button
                    type="submit"
                    disabled={isVerifyingToken || !invitationToken.trim()}
                    className="px-3.5 py-2 bg-[#004874] hover:bg-[#003354] text-white font-bold text-xs rounded-lg transition disabled:opacity-50 cursor-pointer flex items-center gap-1.5 shrink-0"
                  >
                    {isVerifyingToken ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <ArrowRight className="w-3.5 h-3.5" />
                    )}
                    <span>Verify</span>
                  </button>
                </div>
                <p className="text-[10px] text-slate-500 font-mono">
                  Organization Admins issue invitation tokens to Field Engineers and Viewers from the Admin Console.
                </p>
              </form>

              {/* Fallback Uninvited Viewer Self-Registration Form */}
              <div className="pt-2 border-t border-slate-200">
                <div className="mb-2">
                  <span className="text-[10px] font-mono uppercase text-slate-400 font-bold">
                    UNASSIGNED VIEWER REGISTRATION (READ-ONLY)
                  </span>
                  <p className="text-[11px] text-slate-500">
                    Registers an unprivileged Viewer account with no plant access until assigned.
                  </p>
                </div>

                <form onSubmit={handleSubmit} className="space-y-3">
                  <div>
                    <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                      FULL NAME
                    </label>
                    <input
                      type="text"
                      required
                      value={fullName}
                      onChange={(e) => setFullName(e.target.value)}
                      placeholder="e.g. John Doe"
                      className="w-full text-xs font-sans bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                    />
                  </div>

                  <div>
                    <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                      EMAIL ADDRESS
                    </label>
                    <input
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="e.g. john@example.com"
                      className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                        PASSWORD
                      </label>
                      <input
                        type="password"
                        required
                        minLength={6}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="Min 6 chars"
                        className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                      />
                    </div>
                    <div>
                      <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
                        CONFIRM
                      </label>
                      <input
                        type="password"
                        required
                        minLength={6}
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        placeholder="Re-enter"
                        className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                      />
                    </div>
                  </div>

                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="w-full py-2.5 bg-slate-800 hover:bg-slate-900 text-white font-bold text-xs rounded-xl transition shadow flex items-center justify-center gap-2 cursor-pointer disabled:opacity-60"
                  >
                    {isSubmitting ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    )}
                    <span>Register Viewer Account</span>
                  </button>
                </form>
              </div>
            </div>
          )}

          {/* Footer Back to Login Link */}
          <div className="mt-4 pt-3 border-t border-slate-100 text-center">
            <span className="text-xs text-slate-500">Already have an account? </span>
            <button
              type="button"
              onClick={() => onNavigateLogin()}
              className="text-xs font-bold text-[#004874] hover:underline cursor-pointer"
            >
              Sign In
            </button>
          </div>
        </div>
      </main>

      {/* Footer Line */}
      <footer className="w-full py-3 text-center text-[10px] font-mono text-slate-300 z-10 bg-slate-950/40 backdrop-blur-xs">
        PlantIQ Enterprise Industrial Telemetry • Strict Multi-Tenant Organization Governance
      </footer>
    </div>
  );
};

export default RegisterPage;
