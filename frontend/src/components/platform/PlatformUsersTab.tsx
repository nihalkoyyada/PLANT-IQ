import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
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
  Users,
  UserX,
  X,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import {
  createPlatformUser,
  deletePlatformUser,
  getPlatformOrganizations,
  getPlatformUsers,
  updatePlatformUser,
} from '../../api/platform';
import { PlatformOrgListItem, PlatformUserListItem } from '../../types';

export const PlatformUsersTab: React.FC = () => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<PlatformUserListItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [organizations, setOrganizations] = useState<PlatformOrgListItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Filters & Pagination
  const [search, setSearch] = useState<string>('');
  const [roleFilter, setRoleFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [orgFilter, setOrgFilter] = useState<string>('');
  const [page, setPage] = useState<number>(1);
  const pageSize = 15;

  // Modals
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState<boolean>(false);
  const [selectedUser, setSelectedUser] = useState<PlatformUserListItem | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Form states - Create
  const [createEmail, setCreateEmail] = useState<string>('');
  const [createFullName, setCreateFullName] = useState<string>('');
  const [createPassword, setCreatePassword] = useState<string>('');
  const [createRole, setCreateRole] = useState<string>('engineer');
  const [createOrgId, setCreateOrgId] = useState<string>('');
  const [createIsActive, setCreateIsActive] = useState<boolean>(true);

  // Form states - Edit
  const [editFullName, setEditFullName] = useState<string>('');
  const [editRole, setEditRole] = useState<string>('engineer');
  const [editIsActive, setEditIsActive] = useState<boolean>(true);
  const [editPassword, setEditPassword] = useState<string>('');
  const [editOrgId, setEditOrgId] = useState<string>('');

  const fetchUsers = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const offset = (page - 1) * pageSize;
      const res = await getPlatformUsers({
        search: search.trim() || undefined,
        role: roleFilter || undefined,
        is_active: statusFilter === '' ? undefined : statusFilter === 'true',
        org_id: orgFilter || undefined,
        limit: pageSize,
        offset,
      });
      setUsers(res.items);
      setTotalCount(res.total);
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to load platform users');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [page, roleFilter, statusFilter, orgFilter]);

  useEffect(() => {
    getPlatformOrganizations({ limit: 100 })
      .then((res) => {
        setOrganizations(res.items);
        if (res.items.length > 0 && !createOrgId) {
          setCreateOrgId(res.items[0].id);
        }
      })
      .catch(() => {});
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchUsers();
  };

  const handleOpenCreate = () => {
    setCreateEmail('');
    setCreateFullName('');
    setCreatePassword('');
    setCreateRole('admin');
    setCreateIsActive(true);
    if (organizations.length > 0) {
      setCreateOrgId(organizations[0].id);
    }
    setError(null);
    setIsCreateModalOpen(true);
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createEmail.trim() || !createFullName.trim() || !createPassword || (createRole !== 'super_admin' && !createOrgId)) {
      setError('All required fields must be completed');
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await createPlatformUser({
        email: createEmail.trim(),
        full_name: createFullName.trim(),
        password: createPassword,
        role: createRole,
        org_id: createRole === 'super_admin' ? undefined : createOrgId,
        is_active: createIsActive,
      });
      setSuccessMsg(`User "${createEmail}" created successfully.`);
      setIsCreateModalOpen(false);
      fetchUsers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create user');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenEdit = (user: PlatformUserListItem) => {
    setSelectedUser(user);
    setEditFullName(user.full_name);
    setEditRole(user.role);
    setEditIsActive(user.is_active);
    setEditPassword('');
    setEditOrgId(user.org_id);
    setError(null);
    setIsEditModalOpen(true);
  };

  const handleEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedUser) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await updatePlatformUser(selectedUser.id, {
        full_name: editFullName.trim() || undefined,
        role: editRole,
        is_active: editIsActive,
        password: editPassword.trim() ? editPassword : undefined,
        org_id: editRole === 'super_admin' ? undefined : (editOrgId || undefined),
      });
      setSuccessMsg(`User "${selectedUser.email}" updated successfully.`);
      setIsEditModalOpen(false);
      fetchUsers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to update user');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleOpenDelete = (user: PlatformUserListItem) => {
    setSelectedUser(user);
    setError(null);
    setIsDeleteModalOpen(true);
  };

  const handleDeleteSubmit = async () => {
    if (!selectedUser) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await deletePlatformUser(selectedUser.id);
      setSuccessMsg(`User "${selectedUser.email}" deleted successfully.`);
      setIsDeleteModalOpen(false);
      fetchUsers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to delete user');
    } finally {
      setIsSubmitting(false);
    }
  };

  const totalPages = Math.ceil(totalCount / pageSize);

  return (
    <div className="space-y-4">
      {/* Toast Feedback */}
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

      {/* Control Bar: Search & Filters */}
      <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex flex-col md:flex-row items-center justify-between gap-3">
        <form onSubmit={handleSearchSubmit} className="flex-1 flex items-center gap-2 w-full md:w-auto">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search across all tenants by name or email..."
              className="w-full pl-9 pr-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#004874] text-slate-800 bg-white"
            />
          </div>
          <button
            type="submit"
            className="px-3 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-xs font-semibold cursor-pointer transition"
          >
            Search
          </button>
        </form>

        <div className="flex items-center gap-2 flex-wrap w-full md:w-auto justify-end">
          <select
            value={orgFilter}
            onChange={(e) => {
              setOrgFilter(e.target.value);
              setPage(1);
            }}
            aria-label="Filter users by organization"
            className="px-3 py-2 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-[#004874] max-w-[160px] truncate"
          >
            <option value="">All Organizations</option>
            {organizations.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
              </option>
            ))}
          </select>

          <select
            value={roleFilter}
            onChange={(e) => {
              setRoleFilter(e.target.value);
              setPage(1);
            }}
            aria-label="Filter users by role"
            className="px-3 py-2 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-[#004874]"
          >
            <option value="">All Roles</option>
            <option value="super_admin">Super Admin</option>
            <option value="admin">Org Admin</option>
            <option value="engineer">Engineer</option>
            <option value="viewer">Viewer</option>
          </select>

          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            aria-label="Filter users by status"
            className="px-3 py-2 text-xs border border-slate-200 rounded-lg bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-[#004874]"
          >
            <option value="">All Statuses</option>
            <option value="true">Active Only</option>
            <option value="false">Inactive Only</option>
          </select>

          <button
            onClick={fetchUsers}
            className="p-2 border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 cursor-pointer transition"
            title="Refresh Users"
            aria-label="Refresh users"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-[#004874]' : ''}`} />
          </button>

          <button
            onClick={handleOpenCreate}
            className="flex items-center gap-2 px-3.5 py-2 bg-[#004874] hover:bg-[#00385c] text-white rounded-lg text-xs font-semibold cursor-pointer transition shadow-xs shrink-0"
          >
            <Plus className="w-4 h-4" />
            <span>Provision Admin</span>
          </button>
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-mono text-slate-500 uppercase">
                <th className="py-3 px-4 font-semibold">User</th>
                <th className="py-3 px-3 font-semibold">Organization</th>
                <th className="py-3 px-3 font-semibold">Role</th>
                <th className="py-3 px-3 font-semibold">Status</th>
                <th className="py-3 px-3 font-semibold">Created Date</th>
                <th className="py-3 px-4 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto text-[#004874] mb-2" />
                    LOADING PLATFORM USERS...
                  </td>
                </tr>
              ) : users.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400 font-mono">
                    No users matched your search criteria.
                  </td>
                </tr>
              ) : (
                users.map((u) => {
                  const isCurrent = u.id === currentUser?.id;
                  const isSuper = u.role === 'super_admin';
                  return (
                    <tr key={u.id} className="hover:bg-slate-50/80 transition">
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2.5">
                          <div
                            className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs shrink-0 ${
                              isSuper ? 'bg-purple-100 text-purple-800' : 'bg-slate-100 text-slate-700'
                            }`}
                          >
                            {u.full_name?.charAt(0).toUpperCase() || 'U'}
                          </div>
                          <div className="min-w-0">
                            <div className="font-bold text-slate-900 flex items-center gap-1.5 truncate">
                              <span>{u.full_name}</span>
                              {isCurrent && (
                                <span className="px-1.5 py-0.2 rounded text-[9px] font-mono font-bold bg-sky-100 text-sky-800 uppercase">
                                  You
                                </span>
                              )}
                            </div>
                            <div className="text-[11px] font-mono text-slate-400 truncate">
                              {u.email}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        {isSuper ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-purple-50 text-purple-700 border border-purple-200">
                            <Shield className="w-3 h-3 text-purple-600" />
                            Universal Platform (All Tenants)
                          </span>
                        ) : (
                          <span className="font-semibold text-slate-800">{u.org_name || 'Unassigned'}</span>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                            isSuper
                              ? 'bg-purple-100 text-purple-800 border border-purple-200'
                              : u.role === 'admin'
                              ? 'bg-sky-100 text-sky-800'
                              : u.role === 'engineer'
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-slate-100 text-slate-700'
                          }`}
                        >
                          {u.role}
                        </span>
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase ${
                            u.is_active
                              ? 'bg-emerald-100 text-emerald-800'
                              : 'bg-slate-100 text-slate-500'
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              u.is_active ? 'bg-emerald-600' : 'bg-slate-400'
                            }`}
                          />
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-slate-500 font-mono text-[11px]">
                        {new Date(u.created_at).toLocaleDateString()}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => handleOpenEdit(u)}
                            className="p-1.5 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded transition cursor-pointer"
                            title="Edit User"
                            aria-label="Edit User"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleOpenDelete(u)}
                            disabled={isCurrent}
                            className={`p-1.5 rounded transition cursor-pointer ${
                              isCurrent
                                ? 'text-slate-300 cursor-not-allowed'
                                : 'text-rose-600 hover:text-rose-800 hover:bg-rose-50'
                            }`}
                            title={isCurrent ? 'Cannot delete self' : 'Delete User'}
                            aria-label="Delete User"
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
            Showing {users.length} of {totalCount} users
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

      {/* CREATE MODAL */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-md w-full p-6 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900">Provision Administrator</h3>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  Super Admin provisions Organization Admins (tenant operators) or Platform Super Admins.
                </p>
              </div>
              <button onClick={() => setIsCreateModalOpen(false)} className="text-slate-400 hover:text-slate-600 cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-2.5 bg-sky-50 border border-sky-100 rounded-lg text-[11px] text-sky-900 leading-relaxed mb-3">
              <strong>Delegated Team Administration:</strong> Organization Admins manage their own company's Field Engineers and Viewers from their dedicated Organization Admin Console.
            </div>

            <form onSubmit={handleCreateSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Organization Scope *</label>
                {createRole === 'super_admin' ? (
                  <div className="px-3 py-2 bg-purple-50 border border-purple-200 rounded-lg text-purple-800 text-xs flex items-center gap-2">
                    <Shield className="w-3.5 h-3.5 text-purple-600 shrink-0" />
                    <span><strong>Universal Platform Scope</strong>: Super Admins oversee all organizations across the platform.</span>
                  </div>
                ) : (
                  <select
                    required
                    value={createOrgId}
                    onChange={(e) => setCreateOrgId(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 bg-white"
                  >
                    {organizations.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Full Name *</label>
                <input
                  type="text"
                  required
                  value={createFullName}
                  onChange={(e) => setCreateFullName(e.target.value)}
                  placeholder="e.g., Sarah Connor"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Email Address *</label>
                <input
                  type="email"
                  required
                  value={createEmail}
                  onChange={(e) => setCreateEmail(e.target.value)}
                  placeholder="user@organization.com"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Password *</label>
                <input
                  type="password"
                  required
                  value={createPassword}
                  onChange={(e) => setCreatePassword(e.target.value)}
                  placeholder="Minimum 6 characters"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Role *</label>
                  <select
                    value={createRole}
                    onChange={(e) => setCreateRole(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 bg-white"
                  >
                    <option value="admin">Org Admin (Tenant Administrator)</option>
                    <option value="super_admin">Super Admin (Platform Operator)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Account Status</label>
                  <select
                    value={createIsActive ? 'true' : 'false'}
                    onChange={(e) => setCreateIsActive(e.target.value === 'true')}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 bg-white"
                  >
                    <option value="true">Active</option>
                    <option value="false">Inactive</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3 py-2 text-slate-600 hover:bg-slate-100 rounded-lg font-semibold cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex items-center gap-1.5 px-4 py-2 bg-[#004874] hover:bg-[#00385c] text-white rounded-lg font-semibold cursor-pointer disabled:opacity-50"
                >
                  {isSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
                  <span>Create User</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* EDIT MODAL */}
      {isEditModalOpen && selectedUser && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-md w-full p-6 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
              <div>
                <h3 className="text-sm font-bold text-slate-900">Modify Platform User</h3>
                <span className="text-[10px] font-mono text-slate-400">{selectedUser.email}</span>
              </div>
              <button onClick={() => setIsEditModalOpen(false)} className="text-slate-400 hover:text-slate-600 cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleEditSubmit} className="space-y-3 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Full Name</label>
                <input
                  type="text"
                  value={editFullName}
                  onChange={(e) => setEditFullName(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Organization Scope</label>
                {editRole === 'super_admin' ? (
                  <div className="px-3 py-2 bg-purple-50 border border-purple-200 rounded-lg text-purple-800 text-xs flex items-center gap-2">
                    <Shield className="w-3.5 h-3.5 text-purple-600 shrink-0" />
                    <span><strong>Universal Platform Scope</strong>: Super Admins oversee all organizations across the platform.</span>
                  </div>
                ) : (
                  <select
                    value={editOrgId}
                    onChange={(e) => setEditOrgId(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 bg-white"
                  >
                    {organizations.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Role</label>
                  <select
                    value={editRole}
                    onChange={(e) => setEditRole(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 bg-white"
                  >
                    {editRole === 'engineer' && <option value="engineer">Engineer (Company Team Member)</option>}
                    {editRole === 'viewer' && <option value="viewer">Viewer (Company Team Member)</option>}
                    <option value="admin">Org Admin (Tenant Administrator)</option>
                    <option value="super_admin">Super Admin (Platform Operator)</option>
                  </select>
                </div>

                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Account Status</label>
                  <select
                    value={editIsActive ? 'true' : 'false'}
                    onChange={(e) => setEditIsActive(e.target.value === 'true')}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 bg-white"
                  >
                    <option value="true">Active</option>
                    <option value="false">Inactive</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Reset Password (Optional)</label>
                <input
                  type="password"
                  value={editPassword}
                  onChange={(e) => setEditPassword(e.target.value)}
                  placeholder="Leave blank to preserve password"
                  className="w-full px-3 py-2 border border-slate-200 rounded-lg text-slate-800 font-mono"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  className="px-3 py-2 text-slate-600 hover:bg-slate-100 rounded-lg font-semibold cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="px-4 py-2 bg-[#004874] hover:bg-[#00385c] text-white rounded-lg font-semibold cursor-pointer disabled:opacity-50"
                >
                  {isSubmitting ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* DELETE MODAL */}
      {isDeleteModalOpen && selectedUser && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl border border-slate-200 shadow-2xl max-w-sm w-full p-6 animate-in fade-in zoom-in-95 duration-150">
            <div className="w-10 h-10 rounded-full bg-rose-100 text-rose-600 flex items-center justify-center mb-3">
              <Trash2 className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-slate-900 mb-1">Delete User Account</h3>
            <p className="text-xs text-slate-600 leading-relaxed mb-4">
              Are you sure you want to permanently remove <strong>{selectedUser.full_name}</strong> (
              <span className="font-mono">{selectedUser.email}</span>) from organization{' '}
              <strong>{selectedUser.org_name}</strong>?
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
                onClick={() => setIsDeleteModalOpen(false)}
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

