import React, { useState } from 'react';
import { Shield, Lock, Eye, EyeOff, Activity, CheckCircle2, X } from 'lucide-react';
import { Badge } from '../common/Badge';

interface TerminalModalProps {
  isOpen: boolean;
  onClose: () => void;
  onAuthenticate?: () => void;
}

export const TerminalModal: React.FC<TerminalModalProps> = ({ isOpen, onClose, onAuthenticate }) => {
  const [showKey, setShowKey] = useState(false);
  const [operatorId, setOperatorId] = useState('k.vance@plantiq.energy');
  const [accessKey, setAccessKey] = useState('••••••••••••••••');
  const [isBound, setIsBound] = useState(true);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-md bg-[#f0f4fa] rounded-2xl border border-sky-100 shadow-2xl p-6 text-slate-800">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-200/50 transition"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Logo & Header */}
        <div className="flex flex-col items-center text-center mb-5">
          <div className="w-12 h-12 bg-white rounded-xl shadow-md border border-slate-200/80 flex items-center justify-center p-2 mb-3 relative">
            <span className="w-2.5 h-2.5 bg-emerald-500 rounded-full absolute -top-1 -right-1 ring-2 ring-white animate-pulse" />
            <div className="flex items-center gap-1">
              <Activity className="w-6 h-6 text-[#004874]" />
            </div>
          </div>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-xl font-bold text-slate-900 tracking-tight">PlantIQ</h2>
            <Badge variant="navy">SCADA v2.4</Badge>
          </div>
          <p className="text-xs text-slate-500 max-w-xs mb-2">
            Solar Asset Intelligence & Inverter Telemetry Control
          </p>
          <div className="inline-flex items-center gap-1.5 px-3 py-1 bg-white rounded-full border border-sky-200/80 text-[11px] font-mono text-sky-800 shadow-sm">
            <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
            SCADA Enterprise Ingest • Synchronized
          </div>
        </div>

        {/* Form Card */}
        <div className="bg-white rounded-xl p-5 border border-sky-100 shadow-sm mb-4 space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-100">
            <div>
              <h3 className="text-sm font-semibold text-slate-900">Terminal Access</h3>
              <p className="text-[11px] text-slate-500">Authenticate operator clearance</p>
            </div>
            <Badge variant="blue"><Shield className="w-3 h-3 mr-1 inline" /> AES-256</Badge>
          </div>

          <div>
            <label className="block text-[10px] font-mono uppercase text-slate-500 font-semibold mb-1">
              PLANT / SCADA NODE CLUSTER
            </label>
            <select className="w-full text-xs font-medium bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500">
              <option>Surya Solar Farm (Primary SCADA)</option>
              <option>Surya Solar Farm Phase 2</option>
            </select>
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="text-[10px] font-mono uppercase text-slate-500 font-semibold">
                OPERATOR CLEARANCE ID
              </label>
              <span className="text-[10px] font-mono text-slate-400">@plantiq.energy</span>
            </div>
            <input
              type="email"
              value={operatorId}
              onChange={(e) => setOperatorId(e.target.value)}
              className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg p-2.5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="text-[10px] font-mono uppercase text-slate-500 font-semibold">
                CRYPTOGRAPHIC ACCESS KEY
              </label>
              <span className="text-[10px] font-mono text-emerald-600 font-semibold">HSM Enclave</span>
            </div>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={accessKey}
                onChange={(e) => setAccessKey(e.target.value)}
                className="w-full text-xs font-mono bg-slate-50 border border-slate-200 rounded-lg p-2.5 pr-9 text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-600"
              >
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between text-xs pt-1">
            <label className="flex items-center gap-2 text-slate-600 cursor-pointer">
              <input
                type="checkbox"
                checked={isBound}
                onChange={(e) => setIsBound(e.target.checked)}
                className="rounded border-slate-300 text-sky-600 focus:ring-sky-500"
              />
              <span>Bind Hardware Terminal</span>
            </label>
            <a href="#forgot" className="text-sky-600 hover:underline font-medium text-[11px]">
              Forgot SCADA key?
            </a>
          </div>

          <div className="flex items-center gap-2 p-2 bg-sky-50/80 rounded-lg border border-sky-200/60 text-[11px] text-sky-800 font-mono">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            <span>256-bit AES SCADA Tunnel • Node Handshake Ready</span>
          </div>

          <button
            onClick={() => {
              if (onAuthenticate) onAuthenticate();
              onClose();
            }}
            className="w-full py-2.5 bg-[#004874] hover:bg-[#003354] text-white font-semibold text-xs rounded-lg transition shadow-md flex items-center justify-center gap-2 border border-sky-300/30"
          >
            <Lock className="w-4 h-4" />
            Sign In to PlantIQ SCADA
          </button>
        </div>

        {/* Live Telemetry Link Box */}
        <div className="bg-sky-100/60 rounded-xl p-3 border border-sky-200/80 mb-3 space-y-2">
          <div className="flex items-center justify-between text-[11px] font-mono">
            <span className="flex items-center gap-1.5 font-semibold text-slate-700">
              <span className="w-2 h-2 bg-emerald-500 rounded-full animate-ping" />
              LIVE TELEMETRY LINK
            </span>
            <span className="text-emerald-700 font-semibold">99.98% Uptime</span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center">
            <div className="bg-white p-2 rounded-lg border border-slate-200/80">
              <div className="text-[10px] font-mono text-slate-400 uppercase">GATEWAY</div>
              <div className="text-xs font-bold text-emerald-600 font-mono">ONLINE</div>
            </div>
            <div className="bg-white p-2 rounded-lg border border-slate-200/80">
              <div className="text-[10px] font-mono text-slate-400 uppercase">LATENCY</div>
              <div className="text-xs font-bold text-slate-800 font-mono">14ms</div>
            </div>
            <div className="bg-white p-2 rounded-lg border border-slate-200/80">
              <div className="text-[10px] font-mono text-slate-400 uppercase">INVERTERS</div>
              <div className="text-xs font-bold text-sky-700 font-mono">22 / 22 Sync</div>
            </div>
          </div>

          <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 pt-1">
            <span>MODBUS TCP/IP</span>
            <span>TLS 1.3 Certified</span>
            <span className="text-amber-600 font-semibold">⚡ 48.2 MW Net</span>
          </div>
        </div>

        <p className="text-[10px] text-center text-slate-400 font-mono">
          Authorized personnel only. Sessions logged to immutable ledger.
          <br />
          NERC-CIP Level 4 • IEC 62443 Certified • Grid Dispatch SOS
        </p>
      </div>
    </div>
  );
};
