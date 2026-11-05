import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  Building2,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Eye,
  Loader2,
  Lock,
  PauseCircle,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  Shield,
  ShieldAlert,
  Trash2,
  Users,
  X,
  Zap,
} from 'lucide-react';
import {
  createPlatformOrganization,
  deletePlatformOrganization,
  getPlatformOrganizationDetails,
  getPlatformOrganizations,
  getPlatformOverview,
  getPlatformUsers,
  inspectPlatformTenant,
  updatePlatformOrganizationStatus,
} from '../../api/platform';
import { PlatformOrgListItem, PlatformOverviewResponse, PlatformUserListItem } from '../../types';

export const PlatformOrgsTab: React.FC = () => {
  const [organizations, setOrganizations] = useState<PlatformOrgListItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters & Pagination
  const [search, setSearch] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [page, setPage] = useState<number>(1);
  const pageSize = 12;

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [isSuspendModalOpen, setIsSuspendModalOpen] = useState<boolean>(false);
  const [isDetailsModalOpen, setIsDetailsModalOpen] = useState<boolean>(false);
  const [isInspectModalOpen, setIsInspectModalOpen] = useState<boolean>(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState<boolean>(false);
  const [orgToDelete, setOrgToDelete] = useState<PlatformOrgListItem | null>(null);

  const [selectedOrg, setSelectedOrg] = useState<PlatformOrgListItem | null>(null);
  const [orgDetails, setOrgDetails] = useState<any>(null);
  const [inspectData, setInspectData] = useState<any>(null);
  const [isLoadingModal, setIsLoadingModal] = useState<boolean>(false);

  // Form states
  const [createName, setCreateName] = useState<string>('');
  const [createDetails, setCreateDetails] = useState<string>('');
  const [createAdminEmail, setCreateAdminEmail] = useState<string>('');
  const [createAdminPassword, setCreateAdminPassword] = useState<string>('');
  const [createAdminFullName, setCreateAdminFullName] = useState<string>('');
  const [suspendReason, setSuspendReason] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Prevaylos-style Console KPIs & Quick User Email Lookup
  const [overviewStats, setOverviewStats] = useState<PlatformOverviewResponse | null>(null);
  const [userSearchEmail, setUserSearchEmail] = useState<string>('');
  const [userSearchResult, setUserSearchResult] = useState<PlatformUserListItem | null>(null);
  const [userSearchMsg, setUserSearchMsg] = useState<string | null>(null);
  const [isSearchingUser, setIsSearchingUser] = useState<boolean>(false);

  const fetchOrgs = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const res = await getPlatformOrganizations({
        search: search.trim() || undefined,
        status: statusFilter || undefined,
        limit: pageSize,
        offset,
      });
      setOrganizations(res.items);
      setTotalCount(res.total);
      try {
        const overview = await getPlatformOverview();
        setOverviewStats(overview);
      } catch {
        // Fallback silently if overview has network delay
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load platform organizations');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchOrgs();
  }, [page, statusFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchOrgs();
  };

  const handleSearchUserByEmail = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanEmail = userSearchEmail.trim();
    if (!cleanEmail) return;

    setIsSearchingUser(true);
    setUserSearchMsg(null);
    setUserSearchResult(null);
    try {
      const res = await getPlatformUsers({ search: cleanEmail, limit: 10 });
      const exactMatch = res.items.find(
        (u) => u.email.toLowerCase() === cleanEmail.toLowerCase()
      ) || (res.items.length > 0 ? res.items[0] : null);

      if (exactMatch) {
        setUserSearchResult(exactMatch);
      } else {
        setUserSearchMsg(`No user found matching email "${cleanEmail}" across any tenant organization.`);
      }
    } catch {
      setUserSearchMsg('User lookup failed. Please check network connection.');
    } finally {
      setIsSearchingUser(false);
    }
  };

  const handleOpenCreate = () => {
    setCreateName('');
    setCreateDetails('');
    setCreateAdminEmail('');
    setCreateAdminPassword('');
    setCreateAdminFullName('');
    setError(null);
    setIsCreateModalOpen(true);
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createName.trim()) {
      setError('Organization name is required');
      return;
    }
    if (createAdminEmail && !createAdminPassword) {
      setError('Password is required when providing an initial Organization Admin email');
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await createPlatformOrganization({
        name: createName.trim(),
        details: createDetails.trim() || undefined,
        admin_email: createAdminEmail.trim() || undefined,
        admin_password: createAdminPassword || undefined,
        admin_full_name: createAdminFullName.trim() || undefined,
      });
      setSuccessMsg(`Organization "${createName}" provisioned successfully.`);
      setIsCreateModalOpen(false);
      fetchOrgs();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create organization');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenSuspendToggle = (org: PlatformOrgListItem) => {
    setSelectedOrg(org);
    setSuspendReason(
      org.status === 'active' ? 'Suspended for maintenance or contract review' : 'Account reactivated'
    );
    setError(null);
    setIsSuspendModalOpen(true);
  };

  const handleSuspendToggleSubmit = async () => {
    if (!selectedOrg) return;
    setIsSubmitting(true);
    setError(null);
    const newStatus = selectedOrg.status === 'active' ? 'suspended' : 'active';
    try {
      await updatePlatformOrganizationStatus(selectedOrg.id, {
        status: newStatus,
        reason: suspendReason.trim(),
      });
      setSuccessMsg(
        `Organization "${selectedOrg.name}" has been ${newStatus === 'suspended' ? 'suspended' : 'reactivated'}.`
      );
      setIsSuspendModalOpen(false);
      fetchOrgs();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update organization status');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleViewDetails = async (org: PlatformOrgListItem) => {
    setSelectedOrg(org);
    setIsDetailsModalOpen(true);
    setIsLoadingModal(true);
    try {
      const details = await getPlatformOrganizationDetails(org.id);
      setOrgDetails(details);
    } catch (err: any) {
      setError('Could not retrieve organization details');
    } finally {
      setIsLoadingModal(false);
    }
  };

  const handleInspectTenant = async (org: PlatformOrgListItem) => {
    setSelectedOrg(org);
    setIsInspectModalOpen(true);
    setIsLoadingModal(true);
    try {
      const inspection = await inspectPlatformTenant(org.id);
      setInspectData(inspection);
    } catch (err: any) {
      setError('Could not perform tenant inspection');
    } finally {
      setIsLoadingModal(false);
    }
  };

  const handleOpenDelete = (org: PlatformOrgListItem) => {
    setOrgToDelete(org);
    setError(null);
    setIsDeleteModalOpen(true);
  };

  const handleDeleteSubmit = async () => {
    if (!orgToDelete) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await deletePlatformOrganization(orgToDelete.id);
      setSuccessMsg(`Organization "${orgToDelete.name}" and associated resources deleted successfully.`);
      setIsDeleteModalOpen(false);
      setOrgToDelete(null);
      fetchOrgs();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to delete organization');
    } finally {
      setIsSubmitting(false);
    }
  };

  const totalPages = Math.ceil(totalCount / pageSize);

  return (
    <div className="space-y-4">
      {/* Toast Messages */}
      {successMsg && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg flex items-center justify-between text-emerald-800 text-xs">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            <span>{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-700 hover:text-emerald-900 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg flex items-center justify-between text-rose-800 text-xs">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-700 hover:text-rose-900 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Platform Title Banner matching Prevaylos SaaS Admin Reference */}
      <div className="bg-slate-900 rounded-2xl border border-slate-800 p-5 shadow-sm text-white flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span className="text-[11px] font-mono tracking-widest text-slate-400 uppercase">
              Platform Admin Console • Multi-Tenant SaaS
            </span>
          </div>
          <h2 className="text-xl font-black tracking-tight text-white uppercase">
            Organization Management
          </h2>
          <p className="text-xs text-slate-400">
            All tenant organizations on the PlantIQ multi-tenant industrial telemetry platform
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-3 py-1 bg-slate-800 border border-slate-700 rounded-lg text-[11px] font-mono font-bold text-emerald-400 flex items-center gap-1.5 shadow-2xs">
            <Shield className="w-3.5 h-3.5 text-emerald-400" />
            SERVICE ROLE ACTIVE
          </span>
        </div>
      </div>

      {/* 4 Top KPI Cards matching Prevaylos Admin Screenshot */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="text-[11px] font-mono font-bold uppercase text-slate-500 tracking-wider">
            TOTAL ORGS
          </div>
          <div className="text-2xl font-black text-slate-900 mt-1">
            {overviewStats?.total_organizations ?? totalCount}
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">Registered SaaS Tenants</div>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="text-[11px] font-mono font-bold uppercase text-slate-500 tracking-wider">
            ACTIVE
          </div>
          <div className="text-2xl font-black text-emerald-600 mt-1">
            {overviewStats?.active_organizations ?? organizations.filter((o) => o.status === 'active').length}
          </div>
          <div className="text-[10px] text-emerald-600/80 font-mono mt-0.5">Operational Tenants</div>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="text-[11px] font-mono font-bold uppercase text-slate-500 tracking-wider">
            SUSPENDED
          </div>
          <div className="text-2xl font-black text-amber-600 mt-1">
            {overviewStats?.suspended_organizations ?? organizations.filter((o) => o.status === 'suspended').length}
          </div>
          <div className="text-[10px] text-amber-600/80 font-mono mt-0.5">Access Suspended</div>
        </div>
        <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs">
          <div className="text-[11px] font-mono font-bold uppercase text-slate-500 tracking-wider">
            TOTAL USERS
          </div>
          <div className="text-2xl font-black text-[#004874] mt-1">
            {overviewStats?.total_users ?? organizations.reduce((acc, o) => acc + (o.user_count || 0), 0)}
          </div>
          <div className="text-[10px] text-slate-400 font-mono mt-0.5">Across All Organizations</div>
        </div>
      </div>

      {/* SEARCH USER BY EMAIL Card matching Prevaylos Admin Screenshot */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-2xs space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-[11px] font-mono font-bold uppercase text-slate-600 tracking-wider">
            SEARCH USER BY EMAIL
          </label>
          <span className="text-[10px] font-mono text-slate-400">Locate cross-tenant user ownership</span>
        </div>
        <form onSubmit={handleSearchUserByEmail} className="flex items-center gap-2 max-w-lg">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={userSearchEmail}
              onChange={(e) => setUserSearchEmail(e.target.value)}
              placeholder="Enter email address..."
              className="w-full pl-9 pr-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#004874] text-slate-800 bg-white"
            />
          </div>
          <button
            type="submit"
            disabled={isSearchingUser}
            className="px-4 py-2 bg-[#004874] hover:bg-[#00385c] disabled:opacity-50 text-white rounded-lg text-xs font-mono font-bold tracking-wider uppercase cursor-pointer transition shadow-2xs shrink-0 flex items-center gap-1.5"
          >
            {isSearchingUser ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
            <span>SEARCH</span>
          </button>
        </form>

        {userSearchResult && (
          <div className="p-3 bg-purple-50/80 border border-purple-200 rounded-lg text-xs flex items-center justify-between animate-fadeIn">
            <div className="space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-900">{userSearchResult.full_name}</span>
                <span className="text-purple-700 font-mono text-[11px]">({userSearchResult.email})</span>
                <span className="px-1.5 py-0.5 bg-purple-200 text-purple-900 rounded text-[10px] font-mono uppercase font-bold">
                  {userSearchResult.role}
                </span>
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-mono uppercase font-bold ${
                    userSearchResult.is_active ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
                  }`}
                >
                  {userSearchResult.is_active ? 'Active' : 'Deactivated'}
                </span>
              </div>
              <div className="text-slate-600 text-[11px]">
                Tenant Organization:{' '}
                <span className="font-bold text-slate-900">{userSearchResult.org_name || 'Unassigned / Super Admin'}</span>{' '}
                {userSearchResult.org_id && (
                  <span className="text-slate-400 font-mono text-[10px]">({userSearchResult.org_id})</span>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setUserSearchResult(null)}
              className="p-1 text-slate-400 hover:text-slate-600 rounded cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {userSearchMsg && (
          <div className="p-2.5 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-600 flex items-center justify-between">
            <span>{userSearchMsg}</span>
            <button
              type="button"
              onClick={() => setUserSearchMsg(null)}
              className="p-1 text-slate-400 hover:text-slate-600 cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Control Bar: Search Input, Status Filter Pills (ALL / ACTIVE / SUSPENDED), Refresh, Create Org */}
      <div className="bg-white p-3.5 rounded-xl border border-slate-200 shadow-2xs flex flex-col md:flex-row items-center justify-between gap-3">
        <form onSubmit={handleSearchSubmit} className="flex-1 flex items-center gap-2 w-full md:w-auto">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search organizations..."
              className="w-full pl-9 pr-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#004874] text-slate-800 bg-white"
            />
          </div>
          <button
            type="submit"
            className="px-3.5 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold cursor-pointer transition font-mono uppercase"
          >
            Search
          </button>
        </form>

        <div className="flex items-center gap-2 w-full md:w-auto justify-end flex-wrap">
          {/* Status Filter Pills matching Prevaylos Screenshot (ALL / ACTIVE / SUSPENDED) */}
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg">
            <button
              type="button"
              onClick={() => {
                setStatusFilter('');
                setPage(1);
              }}
              className={`px-3 py-1 rounded-md text-[11px] font-mono font-bold uppercase transition cursor-pointer ${
                statusFilter === ''
                  ? 'bg-white text-slate-900 shadow-2xs'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              ALL
            </button>
            <button
              type="button"
              onClick={() => {
                setStatusFilter('active');
                setPage(1);
              }}
              className={`px-3 py-1 rounded-md text-[11px] font-mono font-bold uppercase transition cursor-pointer ${
                statusFilter === 'active'
                  ? 'bg-white text-emerald-700 shadow-2xs'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              ACTIVE
            </button>
            <button
              type="button"
              onClick={() => {
                setStatusFilter('suspended');
                setPage(1);
              }}
              className={`px-3 py-1 rounded-md text-[11px] font-mono font-bold uppercase transition cursor-pointer ${
                statusFilter === 'suspended'
                  ? 'bg-white text-amber-700 shadow-2xs'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              SUSPENDED
            </button>
          </div>

          <button
            onClick={fetchOrgs}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 rounded-lg text-slate-700 hover:bg-slate-50 cursor-pointer transition font-mono text-[11px] font-bold uppercase"
            title="Refresh organizations"
            aria-label="Refresh organizations"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin text-[#004874]' : ''}`} />
            <span>REFRESH</span>
          </button>

          <button
            onClick={handleOpenCreate}
            className="flex items-center gap-2 px-3.5 py-1.5 bg-[#004874] hover:bg-[#00385c] text-white rounded-lg text-xs font-semibold cursor-pointer transition shadow-2xs shrink-0"
          >
            <Plus className="w-4 h-4" />
            <span>Create Organization</span>
          </button>
        </div>
      </div>

      {/* Organizations Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono text-slate-500 uppercase">
                <th className="py-3 px-4 font-semibold">Tenant Organization</th>
                <th className="py-3 px-3 font-semibold">Status</th>
                <th className="py-3 px-3 font-semibold">Primary Org Admin</th>
                <th className="py-3 px-3 font-semibold text-center">Users</th>
                <th className="py-3 px-3 font-semibold text-center">Plants</th>
                <th className="py-3 px-3 font-semibold text-center">Devices</th>
                <th className="py-3 px-3 font-semibold">Created Date</th>
                <th className="py-3 px-4 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-slate-400 font-mono">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#004874] mb-2" />
                    LOADING SAAS TENANT ORGANIZATIONS...
                  </td>
                </tr>
              ) : organizations.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-slate-400 font-mono">
                    No organizations matched your filters.
                  </td>
                </tr>
              ) : (
                organizations.map((org) => {
                  const isActive = org.status === 'active';
                  return (
                    <tr key={org.id} className="hover:bg-slate-50/80 transition">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2.5">
                          <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-700 flex items-center justify-center shrink-0 font-bold font-mono">
                            <Building2 className="w-4 h-4" />
                          </div>
                          <div className="min-w-0">
                            <div className="font-bold text-slate-900 truncate max-w-[200px]">
                              {org.name}
                            </div>
                            <div className="text-[10px] font-mono text-slate-400 truncate max-w-[200px]" title={org.id}>
                              ID: {org.id.slice(0, 8)}...
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                            isActive
                              ? 'bg-emerald-100 text-emerald-800'
                              : 'bg-rose-100 text-rose-800'
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              isActive ? 'bg-emerald-600' : 'bg-rose-600'
                            }`}
                          />
                          {org.status}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        {org.admin_user ? (
                          <div className="min-w-0">
                            <div className="font-semibold text-slate-800 truncate">
                              {org.admin_user.full_name}
                            </div>
                            <div className="text-[10px] font-mono text-slate-400 truncate">
                              {org.admin_user.email}
                            </div>
                          </div>
                        ) : (
                          <span className="text-[11px] font-mono text-slate-400 italic">
                            No Admin Assigned
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-center font-bold text-slate-700 font-mono">
                        {org.user_count}
                      </td>
                      <td className="py-3 px-3 text-center font-bold text-slate-700 font-mono">
                        {org.plant_count}
                      </td>
                      <td className="py-3 px-3 text-center font-bold text-slate-700 font-mono">
                        {org.device_count}
                      </td>
                      <td className="py-3 px-3 text-slate-500 font-mono text-[11px]">
                        {new Date(org.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => handleViewDetails(org)}
                            className="px-2.5 py-1 text-[11px] font-mono font-bold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded transition cursor-pointer flex items-center gap-1 uppercase"
                            title="View Tenant Profile"
                          >
                            <span>VIEW &rarr;</span>
                          </button>
                          <button
                            onClick={() => handleOpenSuspendToggle(org)}
                            className={`px-2.5 py-1 text-[11px] font-mono font-bold rounded transition cursor-pointer flex items-center gap-1 uppercase ${
                              isActive
                                ? 'text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200/60'
                                : 'text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200/60'
                            }`}
                            title={isActive ? 'Suspend Organization' : 'Reactivate Organization'}
                          >
                            {isActive ? 'SUSPEND' : 'REACTIVATE'}
                          </button>
                          <button
                            onClick={() => handleInspectTenant(org)}
                            className="px-2 py-1 text-[11px] font-semibold text-purple-700 bg-purple-50 hover:bg-purple-100 rounded transition cursor-pointer flex items-center gap-1"
                            title="Audited Tenant Inspection"
                          >
                            <Shield className="w-3 h-3" />
                            <span>Inspect</span>
                          </button>
                          <button
                            onClick={() => handleOpenDelete(org)}
                            className="p-1 text-slate-400 hover:text-rose-600 rounded transition cursor-pointer hover:bg-rose-50"
                            title="Delete Organization"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="p-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-xs text-slate-500 font-mono">
          <div>
            Showing {organizations.length} of {totalCount} organizations
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1 rounded border border-slate-200 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white cursor-pointer transition"
              aria-label="Previous page"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="font-semibold text-slate-700">
              Page {page} of {totalPages || 1}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1 rounded border border-slate-200 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white cursor-pointer transition"
              aria-label="Next page"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* CREATE ORGANIZATION MODAL */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-md w-full p-6 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-purple-50 text-purple-700 flex items-center justify-center font-bold">
                  <Building2 className="w-4 h-4" />
                </div>
                <h3 className="text-sm font-bold text-slate-900">Provision New Organization</h3>
              </div>
              <button
                onClick={() => setIsCreateModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Organization Name *</label>
                <input
                  type="text"
                  required
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  placeholder="e.g., Pavilion Renewables Ltd"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#004874] text-slate-800"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">
                  Organization Details / Description
                </label>
                <input
                  type="text"
                  value={createDetails}
                  onChange={(e) => setCreateDetails(e.target.value)}
                  placeholder="e.g., 50MW Solar Plant in Rajasthan, Utility SCADA Telemetry"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#004874] text-slate-800"
                />
              </div>

              <div className="pt-2 border-t border-slate-100">
                <span className="text-[11px] font-mono text-slate-500 uppercase font-semibold">
                  Initial Organization Administrator (Optional)
                </span>
                <p className="text-[11px] text-slate-400 mb-3">
                  Provision initial tenant admin account with immediate login credentials.
                </p>

                <div className="space-y-3">
                  <div>
                    <label className="block font-semibold text-slate-700 mb-1">Admin Full Name</label>
                    <input
                      type="text"
                      value={createAdminFullName}
                      onChange={(e) => setCreateAdminFullName(e.target.value)}
                      placeholder="e.g., Jane Doe"
                      className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#004874] text-slate-800"
                    />
                  </div>
                  <div>
                    <label className="block font-semibold text-slate-700 mb-1">Admin Email Address</label>
                    <input
                      type="email"
                      value={createAdminEmail}
                      onChange={(e) => setCreateAdminEmail(e.target.value)}
                      placeholder="admin@pavilionenergy.com"
                      className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#004874] text-slate-800"
                    />
                  </div>
                  <div>
                    <label className="block font-semibold text-slate-700 mb-1">Initial Password</label>
                    <input
                      type="password"
                      value={createAdminPassword}
                      onChange={(e) => setCreateAdminPassword(e.target.value)}
                      placeholder="Minimum 6 characters"
                      className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#004874] text-slate-800 font-mono"
                    />
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3 py-2 text-slate-600 hover:bg-slate-100 rounded-lg font-semibold cursor-pointer transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex items-center gap-1.5 px-4 py-2 bg-[#004874] hover:bg-[#00385c] text-white rounded-lg font-semibold cursor-pointer transition disabled:opacity-50"
                >
                  {isSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                  <span>Create Organization</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* SUSPEND / REACTIVATE MODAL */}
      {isSuspendModalOpen && selectedOrg && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-md w-full p-6 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center gap-3 mb-3">
              <div
                className={`w-10 h-10 rounded-xl flex items-center justify-center font-bold ${
                  selectedOrg.status === 'active'
                    ? 'bg-rose-100 text-rose-700'
                    : 'bg-emerald-100 text-emerald-700'
                }`}
              >
                <ShieldAlert className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-slate-900">
                  {selectedOrg.status === 'active' ? 'Suspend Organization' : 'Reactivate Organization'}
                </h3>
                <span className="text-xs text-slate-500 font-semibold">{selectedOrg.name}</span>
              </div>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed mb-4">
              {selectedOrg.status === 'active' ? (
                <>
                  Suspending this organization will <strong>immediately revoke access</strong> for all
                  its users. They will be denied from logging in or calling API endpoints. All historical
                  telemetry, assets, and configuration will remain fully preserved and intact.
                </>
              ) : (
                <>
                  Reactivating will restore normal authentication and telemetry ingestion access for all
                  active members of this tenant organization.
                </>
              )}
            </p>

            <div className="space-y-3 mb-4">
              <label className="block text-xs font-semibold text-slate-700">Reason for this action</label>
              <textarea
                value={suspendReason}
                onChange={(e) => setSuspendReason(e.target.value)}
                rows={2}
                placeholder="Audit log justification..."
                className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#004874]"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setIsSuspendModalOpen(false)}
                className="px-3 py-2 text-slate-600 hover:bg-slate-100 rounded-lg font-semibold text-xs cursor-pointer transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSuspendToggleSubmit}
                disabled={isSubmitting}
                className={`flex items-center gap-1.5 px-4 py-2 text-white rounded-lg font-semibold text-xs cursor-pointer transition disabled:opacity-50 ${
                  selectedOrg.status === 'active'
                    ? 'bg-rose-600 hover:bg-rose-700'
                    : 'bg-emerald-600 hover:bg-emerald-700'
                }`}
              >
                {isSubmitting ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : selectedOrg.status === 'active' ? (
                  <PauseCircle className="w-3.5 h-3.5" />
                ) : (
                  <PlayCircle className="w-3.5 h-3.5" />
                )}
                <span>
                  {selectedOrg.status === 'active' ? 'Confirm Suspension' : 'Confirm Reactivation'}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* VIEW DETAILS MODAL */}
      {isDetailsModalOpen && selectedOrg && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-2xl w-full p-6 animate-in fade-in zoom-in-95 duration-150 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
              <div className="flex items-center gap-2">
                <Building2 className="w-5 h-5 text-purple-700" />
                <div>
                  <h3 className="text-sm font-bold text-slate-900">{selectedOrg.name}</h3>
                  <span className="text-[10px] font-mono text-slate-400">ID: {selectedOrg.id}</span>
                </div>
              </div>
              <button
                onClick={() => setIsDetailsModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {isLoadingModal || !orgDetails ? (
              <div className="py-12 text-center text-slate-400 font-mono text-xs">
                <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#004874] mb-2" />
                FETCHING TENANT ASSET PORTFOLIO...
              </div>
            ) : (
              <div className="space-y-4 text-xs">
                <div className="grid grid-cols-3 gap-3 p-3 bg-slate-50 rounded-lg border border-slate-200">
                  <div>
                    <span className="text-[10px] font-mono text-slate-500 uppercase font-semibold">Total Capacity</span>
                    <div className="text-sm font-bold text-slate-900 mt-0.5">{orgDetails.total_capacity_mw} MW</div>
                  </div>
                  <div>
                    <span className="text-[10px] font-mono text-slate-500 uppercase font-semibold">Registered Plants</span>
                    <div className="text-sm font-bold text-slate-900 mt-0.5">{orgDetails.plants?.length || 0}</div>
                  </div>
                  <div>
                    <span className="text-[10px] font-mono text-slate-500 uppercase font-semibold">Total Members</span>
                    <div className="text-sm font-bold text-slate-900 mt-0.5">{orgDetails.users?.length || 0}</div>
                  </div>
                </div>

                <div>
                  <h4 className="font-bold text-slate-800 mb-2">Connected Plants</h4>
                  {orgDetails.plants?.length === 0 ? (
                    <p className="text-slate-400 font-mono text-[11px]">No plants registered for this tenant.</p>
                  ) : (
                    <div className="space-y-1.5">
                      {orgDetails.plants.map((p: any) => (
                        <div key={p.id} className="p-2.5 rounded-lg border border-slate-100 bg-slate-50/50 flex items-center justify-between">
                          <div>
                            <span className="font-semibold text-slate-800">{p.name}</span>
                            <span className="ml-2 text-[10px] font-mono px-1.5 py-0.2 rounded bg-sky-100 text-sky-800 uppercase">
                              {p.plant_type}
                            </span>
                          </div>
                          <div className="font-mono text-slate-700 font-semibold">{p.capacity_mw} MW ({p.device_count} devices)</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div>
                  <h4 className="font-bold text-slate-800 mb-2">User Accounts</h4>
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {orgDetails.users.map((u: any) => (
                      <div key={u.id} className="p-2 rounded border border-slate-100 flex items-center justify-between text-[11px]">
                        <div>
                          <span className="font-semibold text-slate-800">{u.full_name}</span>
                          <span className="ml-2 font-mono text-slate-400">({u.email})</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className="px-1.5 py-0.2 rounded font-mono font-bold uppercase bg-slate-100 text-slate-700 text-[9px]">
                            {u.role}
                          </span>
                          <span className={`w-2 h-2 rounded-full ${u.is_active ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* INSPECT TENANT MODAL (AUDITED) */}
      {isInspectModalOpen && selectedOrg && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-2xl w-full p-6 animate-in fade-in zoom-in-95 duration-150 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-purple-100 text-purple-800 flex items-center justify-center font-bold">
                  <Shield className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                    <span>Tenant Inspection View</span>
                    <span className="px-1.5 py-0.2 text-[9px] font-mono font-bold bg-purple-100 text-purple-800 rounded uppercase">
                      Audited
                    </span>
                  </h3>
                  <span className="text-[10px] font-mono text-slate-400">{selectedOrg.name}</span>
                </div>
              </div>
              <button
                onClick={() => setIsInspectModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {isLoadingModal || !inspectData ? (
              <div className="py-12 text-center text-slate-400 font-mono text-xs">
                <Loader2 className="w-6 h-6 animate-spin mx-auto text-purple-600 mb-2" />
                EXECUTING AUDITED TENANT INSPECTION...
              </div>
            ) : (
              <div className="space-y-4 text-xs">
                <div className="p-3 bg-purple-50/70 border border-purple-100 rounded-lg text-purple-900 text-[11px] leading-relaxed">
                  Notice: This action was immutably recorded into the platform security audit trail under your Super Admin credentials.
                </div>

                <div className="grid grid-cols-4 gap-2 text-center">
                  <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-100">
                    <span className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Plants</span>
                    <div className="text-base font-bold text-slate-800 mt-1">{inspectData.summary?.plant_count ?? 0}</div>
                  </div>
                  <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-100">
                    <span className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Assets</span>
                    <div className="text-base font-bold text-slate-800 mt-1">{inspectData.summary?.asset_count ?? 0}</div>
                  </div>
                  <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-100">
                    <span className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Detectors</span>
                    <div className="text-base font-bold text-slate-800 mt-1">{inspectData.summary?.detectors_count ?? 0}</div>
                  </div>
                  <div className="p-2.5 bg-slate-50 rounded-lg border border-slate-100">
                    <span className="text-[10px] font-mono text-slate-400 uppercase font-semibold">Alert Rules</span>
                    <div className="text-base font-bold text-slate-800 mt-1">{inspectData.summary?.alert_rules_count ?? 0}</div>
                  </div>
                </div>

                <div>
                  <h4 className="font-bold text-slate-800 mb-2">Registered Plants & Generation Capacities</h4>
                  <div className="space-y-2">
                    {inspectData.plants?.map((p: any) => (
                      <div key={p.id} className="p-2.5 rounded-lg border border-slate-200 flex items-center justify-between">
                        <div>
                          <div className="font-bold text-slate-900">{p.name}</div>
                          <span className="text-[10px] font-mono text-slate-400 uppercase">{p.plant_type}</span>
                        </div>
                        <div className="font-mono font-bold text-slate-700">{p.capacity_mw} MW</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
      {/* DELETE ORGANIZATION MODAL */}
      {isDeleteModalOpen && orgToDelete && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-sm w-full p-6 animate-in fade-in zoom-in-95 duration-150">
            <div className="w-10 h-10 rounded-full bg-rose-100 text-rose-600 flex items-center justify-center mb-3">
              <Trash2 className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-slate-900 mb-1">Delete Organization</h3>
            <p className="text-xs text-slate-600 leading-relaxed mb-4">
              Are you sure you want to permanently delete <strong>{orgToDelete.name}</strong>?
              This will remove all associated plants, devices, readings, and member user accounts for this organization.
            </p>

            {error && (
              <div className="mb-4 p-2.5 bg-rose-50 border border-rose-200 rounded-lg flex items-center gap-2 text-rose-700 text-xs">
                <AlertCircle className="w-4 h-4 text-rose-500 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => {
                  setIsDeleteModalOpen(false);
                  setOrgToDelete(null);
                }}
                className="px-3 py-2 text-slate-600 hover:bg-slate-100 rounded-lg font-semibold text-xs cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteSubmit}
                disabled={isSubmitting}
                className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-lg font-semibold text-xs cursor-pointer disabled:opacity-50 flex items-center gap-1.5"
              >
                {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                <span>{isSubmitting ? 'Deleting...' : 'Delete Permanently'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};


