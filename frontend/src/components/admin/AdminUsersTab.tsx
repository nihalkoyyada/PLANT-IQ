import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  Check,
  ChevronLeft,
  ChevronRight,
  Edit2,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Shield,
  Trash2,
  UserCheck,
  UserX,
  X,
  Copy,
  Mail,
  Ticket,
  Clock,
  Send,
  ExternalLink,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import {
  createAdminUser,
  deleteAdminUser,
  getAdminUsers,
  getOrganizations,
  updateAdminUser,
  inviteUserApi,
  listInvitationsApi,
  revokeInvitationApi,
  UserInvitation,
} from '../../api/admin';
import { formatApiError } from '../../api/client';
import { Organization, User } from '../../types';

export const AdminUsersTab: React.FC = () => {
  const { user: currentUser } = useAuth();
  const isSuperAdmin = currentUser?.role === 'super_admin';

  // View mode switcher: 'members' | 'invitations'
  const [viewMode, setViewMode] = useState<'members' | 'invitations'>('members');

  const [users, setUsers] = useState<User[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters & Pagination for Members
  const [search, setSearch] = useState<string>('');
  const [roleFilter, setRoleFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [page, setPage] = useState<number>(1);
  const pageSize = 15;

  // Organizations for Super Admin
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrgFilter, setSelectedOrgFilter] = useState<string>('');

  // Invitations state
  const [invitations, setInvitations] = useState<UserInvitation[]>([]);
  const [isLoadingInvitations, setIsLoadingInvitations] = useState<boolean>(false);
  const [isInviteModalOpen, setIsInviteModalOpen] = useState<boolean>(false);
  const [inviteEmail, setInviteEmail] = useState<string>('');
  const [inviteFullName, setInviteFullName] = useState<string>('');
  const [inviteRole, setInviteRole] = useState<string>('engineer');
  const [inviteOrgId, setInviteOrgId] = useState<string>('');
  const [createdInvitation, setCreatedInvitation] = useState<UserInvitation | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  // Modals state for Add / Edit / Delete
  const [isAddModalOpen, setIsAddModalOpen] = useState<boolean>(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState<boolean>(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  // Form states for Add User
  const [addEmail, setAddEmail] = useState<string>('');
  const [addFullName, setAddFullName] = useState<string>('');
  const [addPassword, setAddPassword] = useState<string>('');
  const [addRole, setAddRole] = useState<string>('engineer');
  const [addIsActive, setAddIsActive] = useState<boolean>(true);
  const [addOrgId, setAddOrgId] = useState<string>('');
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Form states for Edit User
  const [editFullName, setEditFullName] = useState<string>('');
  const [editRole, setEditRole] = useState<string>('engineer');
  const [editIsActive, setEditIsActive] = useState<boolean>(true);
  const [editPassword, setEditPassword] = useState<string>('');

  const fetchUsers = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const res = await getAdminUsers({
        search: search.trim() || undefined,
        role: roleFilter || undefined,
        is_active: statusFilter === '' ? undefined : statusFilter === 'true',
        org_id: selectedOrgFilter || undefined,
        limit: pageSize,
        offset,
      });
      setUsers(res.items);
      setTotalCount(res.total);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to load users'));
    } finally {
      setIsLoading(false);
    }
  };

  const fetchInvitations = async () => {
    setIsLoadingInvitations(true);
    try {
      const res = await listInvitationsApi({
        org_id: isSuperAdmin && selectedOrgFilter ? selectedOrgFilter : undefined,
      });
      setInvitations(res.items);
    } catch {
      // non-blocking
    } finally {
      setIsLoadingInvitations(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [page, roleFilter, statusFilter, selectedOrgFilter]);

  useEffect(() => {
    fetchInvitations();
  }, [selectedOrgFilter]);

  useEffect(() => {
    if (isSuperAdmin) {
      getOrganizations()
        .then((orgs) => setOrganizations(orgs))
        .catch(() => {});
    }
  }, [isSuperAdmin]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchUsers();
  };

  // --- Handlers for User Invitations ---
  const handleOpenInvite = () => {
    setInviteEmail('');
    setInviteFullName('');
    setInviteRole('engineer');
    setInviteOrgId(organizations[0]?.id || '');
    setCreatedInvitation(null);
    setError(null);
    setIsInviteModalOpen(true);
  };

  const handleSendInvitation = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail || !inviteFullName) {
      setError('Please provide full name and email address for invitation');
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const inv = await inviteUserApi({
        email: inviteEmail.trim(),
        full_name: inviteFullName.trim(),
        role: inviteRole as 'admin' | 'engineer' | 'viewer',
        org_id: isSuperAdmin && inviteOrgId ? inviteOrgId : undefined,
      });
      setCreatedInvitation(inv);
      setSuccessMsg(`Invitation created for ${inv.email}`);
      fetchInvitations();
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to send user invitation'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRevokeInvitation = async (invId: string) => {
    try {
      await revokeInvitationApi(invId);
      setSuccessMsg('Invitation revoked successfully');
      fetchInvitations();
      setTimeout(() => setSuccessMsg(null), 3000);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to revoke invitation'));
    }
  };

  const copyInviteLink = (linkOrToken: string) => {
    const fullLink = linkOrToken.startsWith('http')
      ? linkOrToken
      : `${window.location.origin}/register?invitation_token=${linkOrToken}`;
    navigator.clipboard.writeText(fullLink);
    setCopiedToken(linkOrToken);
    setSuccessMsg('Invitation link copied to clipboard!');
    setTimeout(() => {
      setCopiedToken(null);
      setSuccessMsg(null);
    }, 3000);
  };

  // --- Handlers for Direct Add User ---
  const handleOpenAdd = () => {
    setAddEmail('');
    setAddFullName('');
    setAddPassword('');
    setAddRole('engineer');
    setAddIsActive(true);
    setAddOrgId(organizations[0]?.id || '');
    setError(null);
    setIsAddModalOpen(true);
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addEmail || !addPassword || !addFullName) {
      setError('Please fill in all required fields');
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await createAdminUser({
        email: addEmail.trim(),
        full_name: addFullName.trim(),
        password: addPassword,
        role: addRole,
        is_active: addIsActive,
        org_id: isSuperAdmin && addOrgId ? addOrgId : undefined,
      });
      setSuccessMsg(`User ${addEmail} created successfully`);
      setIsAddModalOpen(false);
      fetchUsers();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to create user'));
    } finally {
      setIsSubmitting(false);
    }
  };

  // --- Handlers for Edit / Delete ---
  const handleOpenEdit = (u: User) => {
    setSelectedUser(u);
    setEditFullName(u.full_name);
    setEditRole(u.role);
    setEditIsActive(u.is_active);
    setEditPassword('');
    setError(null);
    setIsEditModalOpen(true);
  };

  const handleUpdateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await updateAdminUser(selectedUser.id, {
        full_name: editFullName.trim() || undefined,
        role: editRole,
        is_active: editIsActive,
        password: editPassword ? editPassword : undefined,
      });
      setSuccessMsg(`User ${selectedUser.email} updated successfully`);
      setIsEditModalOpen(false);
      fetchUsers();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to update user'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenDelete = (u: User) => {
    setSelectedUser(u);
    setError(null);
    setIsDeleteModalOpen(true);
  };

  const handleDeleteUser = async () => {
    if (!selectedUser) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await deleteAdminUser(selectedUser.id);
      setSuccessMsg(`User ${selectedUser.email} deleted successfully`);
      setIsDeleteModalOpen(false);
      fetchUsers();
      setTimeout(() => setSuccessMsg(null), 4000);
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to delete user'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const pendingInvitationsCount = invitations.filter((i) => i.status === 'pending').length;

  return (
    <div className="space-y-4">
      {/* Toast Feedback */}
      {successMsg && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs rounded-lg flex items-center justify-between animate-fadeIn">
          <div className="flex items-center gap-2">
            <Check className="w-4 h-4 text-emerald-600" />
            <span className="font-semibold">{successMsg}</span>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="text-emerald-500 hover:text-emerald-700">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {error && (
        <div className="p-3 bg-rose-50 border border-rose-200 text-rose-800 text-xs rounded-lg flex items-center justify-between animate-fadeIn">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-rose-600" />
            <span>{error}</span>
          </div>
          <button onClick={() => setError(null)} className="text-rose-500 hover:text-rose-700">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Organization Team Management Banner */}
      <div className="bg-gradient-to-r from-sky-950 via-[#004874] to-sky-900 rounded-xl p-4 text-white flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-xs">
        <div>
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-[10px] font-mono tracking-widest text-sky-200 uppercase font-bold">
              Organization User Management • {currentUser?.org_name || 'Surya Solar Farm'}
            </span>
          </div>
          <h3 className="text-sm font-bold text-white">
            Manage Company Field Engineers & Viewers
          </h3>
          <p className="text-xs text-sky-100/80 mt-0.5">
            Provision and invite Field Engineers (telemetry monitoring & inverter diagnostics) and Viewers (read-only monitoring) for your organization.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={handleOpenInvite}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-sky-700/80 hover:bg-sky-600 text-white text-xs font-semibold rounded-lg transition border border-sky-500/50 cursor-pointer shadow-xs"
          >
            <Mail className="w-3.5 h-3.5" />
            <span>Invite User</span>
          </button>
          <button
            onClick={handleOpenAdd}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-semibold rounded-lg transition border border-emerald-400/50 cursor-pointer shadow-xs"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>+ Add User</span>
          </button>
        </div>
      </div>

      {/* Top Navigation Row: Switcher & Action Buttons */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-white p-3 rounded-xl border border-slate-200/80 shadow-xs">
        <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-lg border border-slate-200">
          <button
            type="button"
            onClick={() => setViewMode('members')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-md transition ${
              viewMode === 'members'
                ? 'bg-white text-slate-800 shadow-xs'
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <span>Active Members ({totalCount})</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode('invitations')}
            className={`px-3.5 py-1.5 text-xs font-semibold rounded-md transition flex items-center gap-1.5 ${
              viewMode === 'invitations'
                ? 'bg-white text-slate-800 shadow-xs'
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <Ticket className="w-3.5 h-3.5 text-sky-600" />
            <span>Invitations</span>
            {pendingInvitationsCount > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] font-mono bg-sky-100 text-sky-800 font-bold border border-sky-200">
                {pendingInvitationsCount}
              </span>
            )}
          </button>
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          <button
            onClick={handleOpenInvite}
            className="flex-1 sm:flex-initial flex items-center justify-center gap-1.5 px-3.5 py-1.5 bg-[#004874] hover:bg-sky-800 text-white text-xs font-semibold rounded-lg transition shadow-xs cursor-pointer"
          >
            <Mail className="w-3.5 h-3.5" />
            <span>Invite User</span>
          </button>

          <button
            onClick={handleOpenAdd}
            className="flex-1 sm:flex-initial flex items-center justify-center gap-1.5 px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold rounded-lg transition shadow-xs cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add User</span>
          </button>
        </div>
      </div>

      {/* VIEW: ACTIVE MEMBERS */}
      {viewMode === 'members' && (
        <>
          {/* Control Bar: Search, Filters */}
          <div className="bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-xs flex flex-col md:flex-row items-center justify-between gap-3">
            <form onSubmit={handleSearchSubmit} className="flex-1 w-full flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search by email or name..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#004874] text-slate-800"
                />
              </div>
              <button
                type="submit"
                className="px-3 py-1.5 text-xs font-semibold bg-[#004874] text-white rounded-lg hover:bg-sky-800 transition shadow-xs"
              >
                Search
              </button>
            </form>

            <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
              {/* Org Filter (Super Admin only) */}
              {isSuperAdmin && organizations.length > 0 && (
                <select
                  value={selectedOrgFilter}
                  onChange={(e) => {
                    setSelectedOrgFilter(e.target.value);
                    setPage(1);
                  }}
                  className="px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                >
                  <option value="">All Organizations</option>
                  {organizations.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                    </option>
                  ))}
                </select>
              )}

              {/* Role Filter */}
              <select
                value={roleFilter}
                onChange={(e) => {
                  setRoleFilter(e.target.value);
                  setPage(1);
                }}
                className="px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#004874]"
              >
                <option value="">All Roles</option>
                {isSuperAdmin && <option value="super_admin">Super Admin</option>}
                <option value="admin">Admin</option>
                <option value="engineer">Engineer</option>
                <option value="viewer">Viewer</option>
              </select>

              {/* Status Filter */}
              <select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setPage(1);
                }}
                className="px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg text-slate-700 focus:outline-none focus:ring-1 focus:ring-[#004874]"
              >
                <option value="">All Statuses</option>
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </select>

              <button
                onClick={() => {
                  setSearch('');
                  setRoleFilter('');
                  setStatusFilter('');
                  setSelectedOrgFilter('');
                  setPage(1);
                  fetchUsers();
                }}
                title="Refresh user list"
                className="p-1.5 text-slate-600 hover:text-slate-900 border border-slate-200 rounded-lg hover:bg-slate-50 transition"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Users Data Table */}
          <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono uppercase text-slate-500">
                    <th className="py-2.5 px-4 font-semibold">User / Full Name</th>
                    <th className="py-2.5 px-4 font-semibold">Email</th>
                    <th className="py-2.5 px-4 font-semibold">Organization</th>
                    <th className="py-2.5 px-4 font-semibold">Role</th>
                    <th className="py-2.5 px-4 font-semibold">Status</th>
                    <th className="py-2.5 px-4 font-semibold">Created</th>
                    <th className="py-2.5 px-4 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {isLoading ? (
                    <tr>
                      <td colSpan={7} className="py-12 text-center text-slate-500 font-mono">
                        <div className="flex items-center justify-center gap-2">
                          <Loader2 className="w-4 h-4 animate-spin text-[#004874]" />
                          <span>Loading authorized users...</span>
                        </div>
                      </td>
                    </tr>
                  ) : users.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-12 text-center text-slate-400 font-mono">
                        No users matching criteria.
                      </td>
                    </tr>
                  ) : (
                    users.map((u) => {
                      const isCurrent = u.id === currentUser?.id;
                      const roleBadgeClass =
                        u.role === 'super_admin'
                          ? 'bg-purple-100 text-purple-800 border-purple-200'
                          : u.role === 'admin'
                          ? 'bg-sky-100 text-sky-800 border-sky-200'
                          : u.role === 'engineer'
                          ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
                          : 'bg-amber-100 text-amber-800 border-amber-200';

                      return (
                        <tr key={u.id} className="hover:bg-slate-50/60 transition">
                          <td className="py-2.5 px-4">
                            <div className="flex items-center gap-2">
                              <div className="w-7 h-7 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center font-bold text-xs uppercase border border-slate-200">
                                {u.full_name?.charAt(0) || u.email.charAt(0)}
                              </div>
                              <div>
                                <div className="font-semibold text-slate-900 flex items-center gap-1.5">
                                  <span>{u.full_name}</span>
                                  {isCurrent && (
                                    <span className="text-[9px] font-mono uppercase bg-slate-100 text-slate-600 px-1 rounded font-bold">
                                      YOU
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="py-2.5 px-4 font-mono text-slate-700">{u.email}</td>
                          <td className="py-2.5 px-4">
                            {u.role === 'super_admin' && !u.org_id ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-purple-50 text-purple-700 border border-purple-200">
                                <Shield className="w-3 h-3 text-purple-500" />
                                <span>Universal Platform (All Tenants)</span>
                              </span>
                            ) : (
                              <span className="text-slate-800 font-medium">
                                {u.org_name || 'Surya Power Corp - Surya Solar Farm (50MW)'}
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 px-4">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border ${roleBadgeClass}`}>
                              {u.role}
                            </span>
                          </td>
                          <td className="py-2.5 px-4">
                            {u.is_active ? (
                              <span className="inline-flex items-center gap-1 text-emerald-700 font-semibold text-[11px]">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                                <span>Active</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-slate-400 font-semibold text-[11px]">
                                <span className="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                                <span>Inactive</span>
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 px-4 text-slate-400 font-mono text-[11px]">
                            {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                          </td>
                          <td className="py-2.5 px-4 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                onClick={() => handleOpenEdit(u)}
                                title="Edit user"
                                className="p-1 text-slate-500 hover:text-[#004874] hover:bg-sky-50 rounded transition"
                              >
                                <Edit2 className="w-3.5 h-3.5" />
                              </button>
                              {!isCurrent && (
                                <button
                                  onClick={() => handleOpenDelete(u)}
                                  title="Delete user"
                                  className="p-1 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded transition"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="px-4 py-2.5 bg-slate-50/60 border-t border-slate-200 flex items-center justify-between text-xs text-slate-500">
              <div>
                Showing {users.length > 0 ? (page - 1) * pageSize + 1 : 0} to{' '}
                {Math.min(page * pageSize, totalCount)} of {totalCount} users
              </div>
              <div className="flex items-center gap-1">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="p-1 border border-slate-200 rounded hover:bg-slate-100 disabled:opacity-30 disabled:pointer-events-none"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span className="px-2 font-mono text-[11px]">
                  Page {page} of {totalPages}
                </span>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="p-1 border border-slate-200 rounded hover:bg-slate-100 disabled:opacity-30 disabled:pointer-events-none"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* VIEW: PENDING INVITATIONS */}
      {viewMode === 'invitations' && (
        <div className="bg-white rounded-xl border border-slate-200/80 shadow-xs overflow-hidden">
          <div className="p-3.5 bg-slate-50/50 border-b border-slate-200 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Ticket className="w-4 h-4 text-sky-600" />
              <span className="text-xs font-bold text-slate-800">
                User Onboarding Invitations ({invitations.length})
              </span>
            </div>
            <button
              onClick={fetchInvitations}
              title="Refresh invitations"
              className="p-1.5 text-slate-600 hover:text-slate-900 border border-slate-200 rounded-lg hover:bg-slate-50 transition"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono uppercase text-slate-500">
                  <th className="py-2.5 px-4 font-semibold">Invitee / Full Name</th>
                  <th className="py-2.5 px-4 font-semibold">Email</th>
                  <th className="py-2.5 px-4 font-semibold">Assigned Role</th>
                  <th className="py-2.5 px-4 font-semibold">Status</th>
                  <th className="py-2.5 px-4 font-semibold">Expires At</th>
                  <th className="py-2.5 px-4 font-semibold text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {isLoadingInvitations ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-500 font-mono">
                      <div className="flex items-center justify-center gap-2">
                        <Loader2 className="w-4 h-4 animate-spin text-[#004874]" />
                        <span>Loading invitations...</span>
                      </div>
                    </td>
                  </tr>
                ) : invitations.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                      No invitations generated yet. Click "Invite User" to onboard an Engineer or Viewer.
                    </td>
                  </tr>
                ) : (
                  invitations.map((inv) => {
                    const isPending = inv.status === 'pending';
                    const roleBadgeClass =
                      inv.role === 'admin'
                        ? 'bg-sky-100 text-sky-800 border-sky-200'
                        : inv.role === 'engineer'
                        ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
                        : 'bg-amber-100 text-amber-800 border-amber-200';

                    return (
                      <tr key={inv.id} className="hover:bg-slate-50/60 transition">
                        <td className="py-2.5 px-4">
                          <div className="font-semibold text-slate-900">{inv.full_name}</div>
                        </td>
                        <td className="py-2.5 px-4 font-mono text-slate-700">{inv.email}</td>
                        <td className="py-2.5 px-4">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border ${roleBadgeClass}`}>
                            {inv.role}
                          </span>
                        </td>
                        <td className="py-2.5 px-4">
                          {inv.status === 'accepted' ? (
                            <span className="inline-flex items-center gap-1 text-emerald-700 font-semibold text-[11px] bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                              <Check className="w-3 h-3" />
                              <span>Accepted</span>
                            </span>
                          ) : inv.status === 'pending' ? (
                            <span className="inline-flex items-center gap-1 text-sky-700 font-semibold text-[11px] bg-sky-50 px-2 py-0.5 rounded-full border border-sky-200">
                              <Clock className="w-3 h-3" />
                              <span>Pending Setup</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-slate-400 font-semibold text-[11px] bg-slate-100 px-2 py-0.5 rounded-full border border-slate-200">
                              <span>Revoked / Expired</span>
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 px-4 font-mono text-[11px] text-slate-500">
                          {inv.expires_at ? new Date(inv.expires_at).toLocaleString() : '—'}
                        </td>
                        <td className="py-2.5 px-4 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            {isPending && (
                              <>
                                <button
                                  type="button"
                                  onClick={() => copyInviteLink(inv.token)}
                                  className="flex items-center gap-1 px-2.5 py-1 bg-sky-50 hover:bg-sky-100 text-[#004874] border border-sky-200 rounded text-[11px] font-semibold transition"
                                >
                                  <Copy className="w-3 h-3" />
                                  <span>{copiedToken === inv.token ? 'Copied!' : 'Copy Link'}</span>
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleRevokeInvitation(inv.id)}
                                  title="Revoke invitation"
                                  className="p-1 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded transition"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* MODAL: INVITE USER */}
      {isInviteModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-[#004874] text-white flex items-center justify-center">
                  <Mail className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="font-bold text-sm text-slate-800">Invite New Organization Member</h3>
                  <p className="text-[11px] text-slate-500">Send an onboarding invite token to set up password securely</p>
                </div>
              </div>
              <button
                onClick={() => setIsInviteModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {createdInvitation ? (
              <div className="p-5 space-y-4 text-xs">
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg flex items-start gap-2.5">
                  <Check className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <div className="font-bold text-emerald-900">Invitation Link Generated!</div>
                    <div className="text-[11px] text-emerald-700">
                      Share this secure registration link with{' '}
                      <span className="font-semibold text-emerald-950 font-mono">{createdInvitation.email}</span>:
                    </div>
                  </div>
                </div>

                <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg space-y-2">
                  <div className="text-[10px] font-mono uppercase text-slate-500 font-semibold">
                    Invitation URL:
                  </div>
                  <div className="p-2 bg-white border border-slate-200 rounded text-[11px] font-mono text-slate-800 break-all select-all">
                    {window.location.origin}/register?invitation_token={createdInvitation.token}
                  </div>
                  <button
                    type="button"
                    onClick={() => copyInviteLink(createdInvitation.token)}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-[#004874] hover:bg-sky-800 text-white font-semibold rounded-lg text-xs shadow-xs transition"
                  >
                    <Copy className="w-3.5 h-3.5" />
                    <span>{copiedToken === createdInvitation.token ? 'Copied to Clipboard!' : 'Copy Invitation Link'}</span>
                  </button>
                </div>

                <div className="text-[11px] text-slate-500 flex items-center gap-1.5 justify-center">
                  <Clock className="w-3.5 h-3.5 text-slate-400" />
                  <span>Valid for 7 days. The user selects their own password on arrival.</span>
                </div>

                <div className="pt-2 border-t border-slate-100 flex justify-end">
                  <button
                    type="button"
                    onClick={() => {
                      setIsInviteModalOpen(false);
                      setViewMode('invitations');
                    }}
                    className="px-4 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 font-semibold rounded-lg text-xs transition"
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleSendInvitation} className="p-5 space-y-3.5 text-xs">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Full Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Rajesh Kumar"
                    value={inviteFullName}
                    onChange={(e) => setInviteFullName(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  />
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Email Address *</label>
                  <input
                    type="email"
                    required
                    placeholder="e.g. rajesh@surya.plantiq.ai"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block font-semibold text-slate-700 mb-1">Role *</label>
                    <select
                      value={inviteRole}
                      onChange={(e) => setInviteRole(e.target.value)}
                      className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                    >
                      {isSuperAdmin && <option value="admin">Organization Admin</option>}
                      <option value="engineer">Field Engineer</option>
                      <option value="viewer">Viewer</option>
                    </select>
                  </div>

                  {isSuperAdmin && organizations.length > 0 && (
                    <div>
                      <label className="block font-semibold text-slate-700 mb-1">Organization *</label>
                      <select
                        value={inviteOrgId}
                        onChange={(e) => setInviteOrgId(e.target.value)}
                        className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                      >
                        {organizations.map((org) => (
                          <option key={org.id} value={org.id}>
                            {org.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                <div className="p-3 bg-sky-50 border border-sky-100 rounded-lg text-[11px] text-sky-800 space-y-1">
                  <div className="font-semibold flex items-center gap-1.5">
                    <Shield className="w-3.5 h-3.5 text-sky-600" />
                    <span>Secure Onboarding Guarantee</span>
                  </div>
                  <div>
                    The invitee receives a tamper-proof cryptographic token tied to your organization. They choose their own password upon activation.
                  </div>
                </div>

                <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setIsInviteModalOpen(false)}
                    className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmitting}
                    className="px-4 py-1.5 bg-[#004874] hover:bg-sky-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition"
                  >
                    {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    <span>Generate Invitation</span>
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* MODAL: DIRECT ADD USER */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <h3 className="font-bold text-sm text-slate-800">Add User Account (Direct Provisioning)</h3>
              <button
                onClick={() => setIsAddModalOpen(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateUser} className="p-5 space-y-3.5 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Email Address *</label>
                <input
                  type="email"
                  required
                  placeholder="engineer@plant.com"
                  value={addEmail}
                  onChange={(e) => setAddEmail(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Full Name *</label>
                <input
                  type="text"
                  required
                  placeholder="Priya Sharma"
                  value={addFullName}
                  onChange={(e) => setAddFullName(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Password * (min 6 characters)</label>
                <input
                  type="password"
                  required
                  minLength={6}
                  placeholder="••••••••"
                  value={addPassword}
                  onChange={(e) => setAddPassword(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Role *</label>
                  <select
                    value={addRole}
                    onChange={(e) => setAddRole(e.target.value)}
                    className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                  >
                    {isSuperAdmin && <option value="super_admin">Super Admin</option>}
                    {isSuperAdmin && <option value="admin">Organization Admin</option>}
                    <option value="engineer">Field Engineer</option>
                    <option value="viewer">Viewer</option>
                  </select>
                </div>

                {isSuperAdmin && organizations.length > 0 && (
                  <div>
                    <label className="block font-semibold text-slate-700 mb-1">Organization *</label>
                    <select
                      value={addOrgId}
                      onChange={(e) => setAddOrgId(e.target.value)}
                      className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                    >
                      {organizations.map((org) => (
                        <option key={org.id} value={org.id}>
                          {org.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="addActiveToggle"
                  checked={addIsActive}
                  onChange={(e) => setAddIsActive(e.target.checked)}
                  className="rounded text-[#004874] focus:ring-0"
                />
                <label htmlFor="addActiveToggle" className="text-slate-700 font-medium">
                  Active account (permitted to log in)
                </label>
              </div>

              <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-1.5 bg-[#004874] hover:bg-sky-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition"
                >
                  {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Create Account</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: EDIT USER */}
      {isEditModalOpen && selectedUser && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-md overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div>
                <h3 className="font-bold text-sm text-slate-800">Edit User Account</h3>
                <p className="text-[11px] font-mono text-slate-500">{selectedUser.email}</p>
              </div>
              <button
                onClick={() => setIsEditModalOpen(false)}
                className="text-slate-400 hover:text-slate-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleUpdateUser} className="p-5 space-y-3.5 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Full Name</label>
                <input
                  type="text"
                  value={editFullName}
                  onChange={(e) => setEditFullName(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Role</label>
                <select
                  value={editRole}
                  onChange={(e) => setEditRole(e.target.value)}
                  disabled={!isSuperAdmin && selectedUser.role === 'super_admin'}
                  className="w-full px-2.5 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874] disabled:bg-slate-100"
                >
                  {isSuperAdmin && <option value="super_admin">Super Admin</option>}
                  {isSuperAdmin && <option value="admin">Organization Admin</option>}
                  <option value="engineer">Field Engineer</option>
                  <option value="viewer">Viewer</option>
                </select>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1 flex items-center gap-1">
                  <KeyRound className="w-3.5 h-3.5 text-slate-400" />
                  <span>Reset Password (leave empty to keep current)</span>
                </label>
                <input
                  type="password"
                  minLength={6}
                  placeholder="New password (min 6 characters)"
                  value={editPassword}
                  onChange={(e) => setEditPassword(e.target.value)}
                  className="w-full px-3 py-1.5 border border-slate-200 rounded-lg text-slate-800 focus:outline-none focus:ring-1 focus:ring-[#004874]"
                />
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="editActiveToggle"
                  checked={editIsActive}
                  onChange={(e) => setEditIsActive(e.target.checked)}
                  disabled={selectedUser.id === currentUser?.id}
                  className="rounded text-[#004874] focus:ring-0 disabled:opacity-50"
                />
                <label htmlFor="editActiveToggle" className="text-slate-700 font-medium">
                  Active account
                </label>
                {selectedUser.id === currentUser?.id && (
                  <span className="text-[10px] text-slate-400 font-mono">(Cannot deactivate self)</span>
                )}
              </div>

              <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-1.5 bg-[#004874] hover:bg-sky-800 text-white font-semibold rounded-lg shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition"
                >
                  {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Save Changes</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: DELETE CONFIRMATION */}
      {isDeleteModalOpen && selectedUser && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 w-full max-w-sm overflow-hidden animate-in fade-in zoom-in-95 duration-150 p-5 space-y-4">
            <div className="w-10 h-10 rounded-full bg-rose-100 text-rose-600 flex items-center justify-center mx-auto">
              <Trash2 className="w-5 h-5" />
            </div>
            <div className="text-center space-y-1">
              <h3 className="font-bold text-sm text-slate-800">Delete User Account</h3>
              <p className="text-xs text-slate-600">
                Are you sure you want to permanently delete{' '}
                <span className="font-semibold text-slate-900 font-mono">{selectedUser.email}</span>?
              </p>
              <p className="text-[11px] text-rose-600 font-medium">This action cannot be undone.</p>
            </div>
            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setIsDeleteModalOpen(false)}
                className="px-3 py-1.5 border border-slate-200 text-slate-600 rounded-lg hover:bg-slate-50 text-xs transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteUser}
                disabled={isSubmitting}
                className="px-4 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-semibold rounded-lg text-xs shadow-xs disabled:opacity-50 flex items-center gap-1.5 transition"
              >
                {isSubmitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                <span>Confirm Delete</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
