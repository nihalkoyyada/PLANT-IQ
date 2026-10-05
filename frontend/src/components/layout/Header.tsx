import React, { useState } from 'react';
import { Activity, Search, Bell, User as UserIcon, LogOut } from 'lucide-react';
import { Plant } from '../../types';
import { useAuth } from '../../context/AuthContext';

interface HeaderProps {
  plants: Plant[];
  selectedPlant: Plant | null;
  onSelectPlant: (plant: Plant) => void;
}

export const Header: React.FC<HeaderProps> = ({
  plants,
  selectedPlant,
  onSelectPlant,
}) => {
  const { user, logout } = useAuth();
  const [showProfileMenu, setShowProfileMenu] = useState<boolean>(false);

  return (
    <header className="sticky top-0 z-30 bg-white/95 backdrop-blur-md border-b border-slate-200/80 px-4 py-2.5 flex items-center justify-between shadow-xs">
      {/* Left: Brand + Plant Switcher */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-[#004874] flex items-center justify-center text-white shadow-sm">
            <Activity className="w-5 h-5" />
          </div>
          <div className="hidden sm:block">
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-slate-900 tracking-tight text-base">PlantIQ</span>
              <span className="text-[10px] font-mono px-1.5 py-0.2 bg-sky-100 text-sky-800 rounded font-semibold">
                SCADA
              </span>
            </div>
          </div>
        </div>

        <div className="h-5 w-px bg-slate-200 hidden sm:block" />

        {/* Plant Dropdown */}
        <div className="relative">
          <select
            value={selectedPlant?.id || ''}
            onChange={(e) => {
              const plant = plants.find((p) => p.id === e.target.value);
              if (plant) onSelectPlant(plant);
            }}
            className="appearance-none bg-slate-100/80 hover:bg-slate-200/60 border border-slate-200 rounded-lg px-3 py-1.5 pr-8 text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500 transition cursor-pointer"
          >
            {plants.length > 0 ? (
              plants.map((plant) => (
                <option key={plant.id} value={plant.id}>
                  🟢 {plant.name} - {plant.capacity_ac_kw ? `${(plant.capacity_ac_kw / 1000).toFixed(0)}MW` : '50MW'}
                </option>
              ))
            ) : (
              <option value="">🟢 Surya Solar Farm - 50MW</option>
            )}
          </select>
          <div className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 text-xs">
            ▼
          </div>
        </div>

        {/* Live Cadence Badge */}
        <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 rounded-md border border-emerald-200/80 text-[11px] font-mono font-medium text-emerald-700">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          LIVE 15M CADENCE
        </div>
      </div>

      {/* Right Actions */}
      <div className="flex items-center gap-2">
        {/* Search */}
        <div className="relative hidden md:block">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search assets, telemetry..."
            className="pl-8 pr-3 py-1.5 bg-slate-100/70 border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 w-44 lg:w-60 transition"
          />
        </div>

        {/* Notification Bell */}
        <button className="relative p-2 rounded-lg text-slate-600 hover:bg-slate-100 transition">
          <Bell className="w-4 h-4" />
          <span className="absolute top-1 right-1 w-4 h-4 bg-rose-500 text-white font-mono text-[9px] font-bold rounded-full flex items-center justify-center ring-2 ring-white">
            3
          </span>
        </button>

        {/* Authenticated User Profile */}
        <div className="relative">
          <div
            onClick={() => setShowProfileMenu(!showProfileMenu)}
            className="flex items-center gap-2 pl-2 pr-3 py-1 bg-slate-100 hover:bg-slate-200/80 rounded-lg cursor-pointer transition border border-slate-200/80"
          >
            <div className="w-7 h-7 rounded-full bg-[#004874] text-white flex items-center justify-center font-bold text-xs shadow-xs">
              <UserIcon className="w-3.5 h-3.5" />
            </div>
            <div className="hidden sm:block text-left leading-tight">
              <div className="text-xs font-bold text-slate-800 truncate max-w-[130px]">
                {user?.full_name || 'Surya Admin'}
              </div>
              <div className="text-[9px] font-mono font-bold text-sky-800 uppercase">
                {user?.role || 'ADMIN'}
              </div>
            </div>
          </div>

          {showProfileMenu && (
            <div className="absolute right-0 mt-2 w-60 bg-white border border-slate-200 rounded-xl shadow-xl py-2 z-50 animate-in fade-in slide-in-from-top-1 duration-150">
              <div className="px-4 py-2.5 border-b border-slate-100">
                <p className="text-xs font-bold text-slate-900">{user?.full_name}</p>
                <p className="text-[10px] font-mono text-slate-500 truncate">{user?.email}</p>
                <div className="mt-1">
                  <span className="px-1.5 py-0.5 bg-sky-100 text-sky-800 text-[9px] font-mono font-bold rounded uppercase">
                    ROLE: {user?.role}
                  </span>
                </div>
              </div>
              <button
                onClick={() => {
                  setShowProfileMenu(false);
                  logout();
                }}
                className="w-full text-left px-4 py-2 text-xs text-rose-600 hover:bg-rose-50 flex items-center gap-2 transition font-medium cursor-pointer"
              >
                <LogOut className="w-3.5 h-3.5 text-rose-500" />
                <span>Sign Out</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
