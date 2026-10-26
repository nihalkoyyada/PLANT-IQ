import React, { useEffect, useRef, useState } from 'react';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Bell,
  Boxes,
  Check,
  CheckCircle2,
  ChevronRight,
  FileCheck,
  LayoutDashboard,
  LineChart,
  LogOut,
  Search,
  ShieldAlert,
  Sun,
  User as UserIcon,
  X,
} from 'lucide-react';
import { Plant, Asset, Channel, Anomaly } from '../../types';
import { useAuth } from '../../context/AuthContext';
import { NavTab } from './Sidebar';
import { getAssets } from '../../api/assets';
import { getChannels } from '../../api/channels';
import { getAnomalies } from '../../api/anomalies';

interface HeaderProps {
  plants: Plant[];
  selectedPlant: Plant | null;
  onSelectPlant: (plant: Plant) => void;
  onNavigateTab?: (tab: NavTab) => void;
}

interface SearchItem {
  id: string;
  type: 'page' | 'asset' | 'signal' | 'anomaly';
  title: string;
  subtitle: string;
  tab: NavTab;
}

interface NotificationItem {
  id: string;
  title: string;
  description: string;
  time: string;
  severity: 'critical' | 'high' | 'info';
  read: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  plants,
  selectedPlant,
  onSelectPlant,
  onNavigateTab,
}) => {
  const { user, logout } = useAuth();
  const [showProfileMenu, setShowProfileMenu] = useState<boolean>(false);

  // Search state
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isSearchOpen, setIsSearchOpen] = useState<boolean>(false);
  const [isMobileSearchOpen, setIsMobileSearchOpen] = useState<boolean>(false);
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);

  // Notifications state
  const [showNotifications, setShowNotifications] = useState<boolean>(false);
  const [notifications, setNotifications] = useState<NotificationItem[]>([
    {
      id: 'notif-1',
      title: 'Inverter Trip Outlier',
      description: 'Inverter INV-04 tripped at midday peak. Estimated generation loss: 1,250 kW.',
      time: '12m ago',
      severity: 'critical',
      read: false,
    },
    {
      id: 'notif-2',
      title: 'Performance Ratio Deviation',
      description: 'Plant PR dropped below 78% threshold (74.2% observed).',
      time: '45m ago',
      severity: 'high',
      read: false,
    },
    {
      id: 'notif-3',
      title: 'POA Telemetry Sync Nominal',
      description: 'Weather Station WS-01 POA irradiance sync verified across 88 channels.',
      time: '2h ago',
      severity: 'info',
      read: false,
    },
  ]);

  const searchContainerRef = useRef<HTMLDivElement | null>(null);
  const notifContainerRef = useRef<HTMLDivElement | null>(null);
  const profileContainerRef = useRef<HTMLDivElement | null>(null);

  // Load assets and channels for search indexing
  useEffect(() => {
    getAssets()
      .then((data) => setAssets(data))
      .catch(() => {});
    getChannels()
      .then((data) => setChannels(data))
      .catch(() => {});
    getAnomalies({ limit: 10 })
      .then((data) => {
        if (data && data.length > 0) {
          setAnomalies(data);
          // Update live notifications if real anomalies are available
          const liveNotifs: NotificationItem[] = data.slice(0, 4).map((a, idx) => ({
            id: a.id || `anom-notif-${idx}`,
            title: `${a.severity.toUpperCase()}: ${a.summary || 'Detected Outlier'}`,
            description: `${a.asset_name || 'Asset'} • Deficit: ${a.estimated_loss_kw || 0} kW`,
            time: new Date(a.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            severity: (a.severity === 'critical' ? 'critical' : a.severity === 'high' ? 'high' : 'info') as any,
            read: false,
          }));
          setNotifications(liveNotifs);
        }
      })
      .catch(() => {});
  }, [selectedPlant?.id]);

  // Click outside to close dropdowns
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(e.target as Node)) {
        setIsSearchOpen(false);
        setIsMobileSearchOpen(false);
      }
      if (notifContainerRef.current && !notifContainerRef.current.contains(e.target as Node)) {
        setShowNotifications(false);
      }
      if (profileContainerRef.current && !profileContainerRef.current.contains(e.target as Node)) {
        setShowProfileMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Quick navigation pages when search query is empty
  const quickPages: SearchItem[] = [
    { id: 'quick-dashboard', type: 'page', title: 'Dashboard', subtitle: 'Overview, PR Index, SCADA sync', tab: 'dashboard' },
    { id: 'quick-devices', type: 'page', title: 'Devices & Inverters', subtitle: 'Inverter telemetry, clipping & efficiency', tab: 'devices' },
    { id: 'quick-telemetry', type: 'page', title: 'Telemetry Explorer', subtitle: 'Multi-channel charts & CSV export', tab: 'telemetry' },
    { id: 'quick-anomalies', type: 'page', title: 'Anomaly Inbox', subtitle: 'Fault triage, trip events & alarms', tab: 'anomalies' },
    { id: 'quick-quality', type: 'page', title: 'Data Quality & QC', subtitle: 'Missing readings & channel staleness', tab: 'quality' },
  ];

  // Filter searchable items
  const getSearchResults = (): SearchItem[] => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return quickPages;

    const results: SearchItem[] = [];

    // Static Navigation Pages
    const pages: Array<{ tab: NavTab; title: string; subtitle: string }> = [
      { tab: 'dashboard', title: 'Dashboard', subtitle: 'Overview, Performance Ratio, SCADA sync' },
      { tab: 'plants', title: 'Plants Fleet', subtitle: 'Plant configurations, locations, capacities' },
      { tab: 'devices', title: 'Devices / Inverters', subtitle: 'Inverter telemetry, clipping, and conversion' },
      { tab: 'telemetry', title: 'Telemetry Explorer', subtitle: 'Timeseries charts, multi-channel comparison' },
      { tab: 'anomalies', title: 'Anomaly Inbox', subtitle: 'Fault triage, trip events, detector alarms' },
      { tab: 'quality', title: 'Data Quality & QC', subtitle: 'Missing readings, stale channels, cadence' },
      { tab: 'ingestion', title: 'Upload & Mapping', subtitle: 'CSV ingestion, column profiling, mapping templates' },
    ];

    pages.forEach((p) => {
      if (p.title.toLowerCase().includes(q) || p.subtitle.toLowerCase().includes(q)) {
        results.push({
          id: `page-${p.tab}`,
          type: 'page',
          title: p.title,
          subtitle: p.subtitle,
          tab: p.tab,
        });
      }
    });

    // Inverter Assets
    assets.forEach((a) => {
      if (a.name.toLowerCase().includes(q) || a.asset_type.toLowerCase().includes(q)) {
        results.push({
          id: `asset-${a.id}`,
          type: 'asset',
          title: a.name,
          subtitle: `${a.asset_type.toUpperCase()} • Rated: ${a.rated_kw || 1000} kW`,
          tab: 'devices',
        });
      }
    });

    // Telemetry Channels
    channels.forEach((c) => {
      if (
        c.canonical_key.toLowerCase().includes(q) ||
        (c.source_name && c.source_name.toLowerCase().includes(q))
      ) {
        results.push({
          id: `channel-${c.id}`,
          type: 'signal',
          title: c.canonical_key,
          subtitle: `Source: ${c.source_name} (${c.receive_unit || 'kW'})`,
          tab: 'telemetry',
        });
      }
    });

    // Anomalies
    anomalies.forEach((anom) => {
      if (
        (anom.summary && anom.summary.toLowerCase().includes(q)) ||
        (anom.asset_name && anom.asset_name.toLowerCase().includes(q))
      ) {
        results.push({
          id: `anom-${anom.id}`,
          type: 'anomaly',
          title: anom.summary || 'Detected Anomaly',
          subtitle: `${anom.asset_name || 'Asset'} • ${anom.severity.toUpperCase()} • Deficit: ${anom.estimated_loss_kw || 0} kW`,
          tab: 'anomalies',
        });
      }
    });

    return results.slice(0, 8);
  };

  const displayedItems = getSearchResults();

  const handleSelectSearchResult = (item: SearchItem) => {
    onNavigateTab?.(item.tab);
    setSearchQuery('');
    setIsSearchOpen(false);
    setIsMobileSearchOpen(false);
    setSelectedIndex(-1);
  };

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (displayedItems.length > 0 ? (prev + 1) % displayedItems.length : -1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (displayedItems.length > 0 ? (prev <= 0 ? displayedItems.length - 1 : prev - 1) : -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (selectedIndex >= 0 && selectedIndex < displayedItems.length) {
        handleSelectSearchResult(displayedItems[selectedIndex]);
      } else if (displayedItems.length > 0) {
        handleSelectSearchResult(displayedItems[0]);
      }
    } else if (e.key === 'Escape') {
      setIsSearchOpen(false);
      setIsMobileSearchOpen(false);
      setSelectedIndex(-1);
    }
  };

  const unreadCount = notifications.filter((n) => !n.read).length;

  const handleMarkAllRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  const handleNotificationClick = (item: NotificationItem) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === item.id ? { ...n, read: true } : n))
    );
    setShowNotifications(false);
    onNavigateTab?.('anomalies');
  };

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

        {/* Live Telemetry Badge */}
        <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 rounded-md border border-emerald-200/80 text-[11px] font-mono font-medium text-emerald-700">
          <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
          LIVE TELEMETRY
        </div>
      </div>

      {/* Right Actions */}
      <div className="flex items-center gap-2">
        {/* Interactive Search Bar (Desktop) */}
        <div ref={searchContainerRef} className="relative hidden md:block">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            id="global-search-input"
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setIsSearchOpen(true);
              setSelectedIndex(-1);
            }}
            onFocus={() => setIsSearchOpen(true)}
            onKeyDown={handleSearchKeyDown}
            placeholder="Search assets, telemetry..."
            className="pl-8 pr-7 py-1.5 bg-slate-100/80 border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 w-48 lg:w-64 transition"
          />
          {searchQuery && (
            <button
              onClick={() => {
                setSearchQuery('');
                setSelectedIndex(-1);
              }}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-0.5"
            >
              <X className="w-3 h-3" />
            </button>
          )}

          {/* Search Results Dropdown */}
          {isSearchOpen && (
            <div className="absolute right-0 top-full mt-1.5 w-80 bg-white border border-slate-200 rounded-xl shadow-2xl py-2 z-50 text-xs animate-in fade-in duration-100">
              <div className="px-3 py-1 text-[10px] font-mono uppercase tracking-wider text-slate-400 border-b border-slate-100 pb-1 mb-1 flex items-center justify-between">
                <span>
                  {searchQuery.trim().length > 0
                    ? `Matching Results (${displayedItems.length})`
                    : 'Quick Navigation'}
                </span>
                <span className="text-[9px] text-slate-400">↑↓ to navigate • Enter</span>
              </div>

              {displayedItems.length === 0 ? (
                <div className="p-4 text-center text-slate-500 text-xs">
                  No matching assets, signals, or pages for "{searchQuery}"
                </div>
              ) : (
                <div className="max-h-72 overflow-y-auto space-y-0.5 px-1">
                  {displayedItems.map((item, idx) => {
                    const isPage = item.type === 'page';
                    const isAsset = item.type === 'asset';
                    const isSignal = item.type === 'signal';
                    const isSelected = selectedIndex === idx;

                    return (
                      <button
                        key={item.id}
                        onClick={() => handleSelectSearchResult(item)}
                        className={`w-full text-left p-2 rounded-lg flex items-start gap-2.5 transition group cursor-pointer ${
                          isSelected
                            ? 'bg-sky-50 text-[#004874] ring-1 ring-sky-300'
                            : 'hover:bg-sky-50/80 text-slate-800'
                        }`}
                      >
                        <div
                          className={`mt-0.5 p-1 rounded transition shrink-0 ${
                            isSelected
                              ? 'bg-[#004874] text-white'
                              : 'bg-slate-100 text-slate-600 group-hover:bg-[#004874] group-hover:text-white'
                          }`}
                        >
                          {isPage ? (
                            <LayoutDashboard className="w-3.5 h-3.5" />
                          ) : isAsset ? (
                            <Boxes className="w-3.5 h-3.5" />
                          ) : isSignal ? (
                            <LineChart className="w-3.5 h-3.5" />
                          ) : (
                            <ShieldAlert className="w-3.5 h-3.5 text-rose-600" />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center justify-between gap-1">
                            <span className="font-bold text-xs group-hover:text-[#004874] truncate">
                              {item.title}
                            </span>
                            <span className="text-[9px] font-mono px-1 rounded uppercase font-semibold text-slate-400 bg-slate-100">
                              {item.type}
                            </span>
                          </div>
                          <div className="text-[11px] text-slate-500 truncate">
                            {item.subtitle}
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Mobile Search Button */}
        <button
          onClick={() => {
            setIsMobileSearchOpen((prev) => !prev);
            setIsSearchOpen(true);
          }}
          className="md:hidden p-2 rounded-lg text-slate-600 hover:bg-slate-100 transition cursor-pointer"
          title="Search"
          aria-label="Search assets and signals"
        >
          <Search className="w-4 h-4" />
        </button>

        {/* Interactive Notification Bell */}
        <div ref={notifContainerRef} className="relative">
          <button
            id="header-notification-bell"
            onClick={() => setShowNotifications((prev) => !prev)}
            className="relative p-2 rounded-lg text-slate-600 hover:bg-slate-100 transition cursor-pointer"
            title="Operational Notifications"
            aria-label="Operational Notifications"
          >
            <Bell className="w-4 h-4" />
            {unreadCount > 0 && (
              <span className="absolute top-1 right-1 w-4 h-4 bg-rose-500 text-white font-mono text-[9px] font-bold rounded-full flex items-center justify-center ring-2 ring-white">
                {unreadCount}
              </span>
            )}
          </button>

          {/* Notifications Popover */}
          {showNotifications && (
            <div className="absolute right-0 top-full mt-1.5 w-80 sm:w-96 bg-white border border-slate-200 rounded-xl shadow-2xl p-3 z-50 animate-in fade-in slide-in-from-top-1 duration-150">
              <div className="flex items-center justify-between pb-2 border-b border-slate-100 mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-slate-900">Notifications</span>
                  {unreadCount > 0 && (
                    <span className="px-1.5 py-0.2 bg-rose-100 text-rose-800 font-mono text-[9px] font-bold rounded-full">
                      {unreadCount} new
                    </span>
                  )}
                </div>
                {unreadCount > 0 && (
                  <button
                    onClick={handleMarkAllRead}
                    className="text-[11px] text-[#004874] hover:text-sky-700 font-semibold cursor-pointer"
                  >
                    Mark all as read
                  </button>
                )}
              </div>

              <div className="max-h-72 overflow-y-auto space-y-1.5">
                {notifications.length === 0 ? (
                  <div className="p-4 text-center text-xs text-slate-500 font-mono">
                    No active notifications
                  </div>
                ) : (
                  notifications.map((n) => (
                    <div
                      key={n.id}
                      onClick={() => handleNotificationClick(n)}
                      className={`p-2.5 rounded-lg border transition cursor-pointer flex items-start gap-2.5 ${
                        n.read
                          ? 'bg-white border-slate-100 hover:bg-slate-50 text-slate-600'
                          : 'bg-sky-50/50 border-sky-100 hover:bg-sky-50 text-slate-800'
                      }`}
                    >
                      <div className="mt-0.5 shrink-0">
                        {n.severity === 'critical' ? (
                          <AlertTriangle className="w-4 h-4 text-rose-600" />
                        ) : n.severity === 'high' ? (
                          <AlertCircle className="w-4 h-4 text-amber-600" />
                        ) : (
                          <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-1">
                          <span className={`text-xs font-bold truncate ${n.read ? 'text-slate-700' : 'text-slate-900'}`}>
                            {n.title}
                          </span>
                          <span className="text-[10px] font-mono text-slate-400 shrink-0">
                            {n.time}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-500 leading-relaxed line-clamp-2 mt-0.5">
                          {n.description}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>

              <div className="pt-2 mt-2 border-t border-slate-100 text-center">
                <button
                  onClick={() => {
                    setShowNotifications(false);
                    onNavigateTab?.('anomalies');
                  }}
                  className="w-full py-1 text-xs text-[#004874] hover:text-sky-700 font-bold flex items-center justify-center gap-1 transition cursor-pointer"
                >
                  <span>View Anomaly Inbox</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Authenticated User Profile */}
        <div ref={profileContainerRef} className="relative">
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
