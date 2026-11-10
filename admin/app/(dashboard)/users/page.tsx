"use client";

import { useState } from "react";

import { Badge, Card, Empty, ErrorText, Field, Modal, Pagination, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApiData } from "@/lib/use-api-data";
import type { Page, User } from "@/lib/types";

const PAGE_SIZE = 25;

export default function UsersPage() {
  const [page, setPage] = useState(1);
  const [message, setMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("USER");
  const [createError, setCreateError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [editing, setEditing] = useState<User | null>(null);
  const [editName, setEditName] = useState("");
  const [editRole, setEditRole] = useState("USER");
  const [editActive, setEditActive] = useState(true);
  const [editPassword, setEditPassword] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const { data, loading, error, reload } = useApiData<Page<User>>(
    `/admin/users?page=${page}&page_size=${PAGE_SIZE}`
  );

  function openCreate() {
    setCreating(true);
    setName("");
    setEmail("");
    setPassword("");
    setRole("USER");
    setCreateError(null);
  }

  async function submitCreate(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setCreateError(null);
    try {
      await api.post<User>("/admin/users", { name, email, password, role });
      setMessage(`${email} created.`);
      setCreating(false);
      reload();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setSaving(false);
    }
  }

  function openEdit(user: User) {
    setEditing(user);
    setEditName(user.name);
    setEditRole(user.role);
    setEditActive(user.is_active);
    setEditPassword("");
    setEditError(null);
  }

  async function submitEdit(event: React.FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setEditError(null);
    try {
      const payload: Record<string, unknown> = {
        name: editName,
        role: editRole,
        is_active: editActive
      };
      if (editPassword.trim()) payload.password = editPassword;
      await api.patch<User>(`/admin/users/${editing.id}`, payload);
      setMessage(`${editing.email} updated.`);
      setEditing(null);
      reload();
    } catch (err) {
      setEditError(err instanceof Error ? err.message : "Update failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {message ? <div className="success-text">{message}</div> : null}
      <Card
        title="Users"
        actions={
          <div className="flex">
            <button className="btn ghost small" onClick={reload}>Refresh</button>
            <button className="btn small" onClick={openCreate}>New user</button>
          </div>
        }
      >
        <ErrorText error={error || actionError} />
        {loading && !data ? (
          <Spinner label="Loading users" />
        ) : data && data.items.length > 0 ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((user) => (
                    <tr key={user.id}>
                      <td className="strong">{user.name}</td>
                      <td>{user.email}</td>
                      <td><Badge tone={user.role === "ADMIN" ? "blue" : "gray"}>{user.role}</Badge></td>
                      <td><Badge tone={user.is_active ? "green" : "red"}>{user.is_active ? "ACTIVE" : "DISABLED"}</Badge></td>
                      <td className="nowrap small">{formatDateTime(user.created_at)}</td>
                      <td>
                        <button className="btn ghost small" onClick={() => openEdit(user)}>Edit</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />
          </>
        ) : (
          <Empty message="No users found." />
        )}
      </Card>

      <Modal open={creating} title="Create user" onClose={() => setCreating(false)}>
        <form onSubmit={submitCreate}>
          <Field label="Name">
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label="Email">
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </Field>
          <Field label="Password" hint="Minimum 8 characters">
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required />
          </Field>
          <Field label="Role">
            <select value={role} onChange={(event) => setRole(event.target.value)}>
              <option value="USER">USER</option>
              <option value="ADMIN">ADMIN</option>
            </select>
          </Field>
          <ErrorText error={createError} />
          <div className="modal-foot" style={{ padding: "14px 0 0", border: "none" }}>
            <button type="button" className="btn ghost" onClick={() => setCreating(false)}>Cancel</button>
            <button type="submit" className="btn" disabled={saving}>{saving ? "Creating…" : "Create user"}</button>
          </div>
        </form>
      </Modal>

      <Modal open={Boolean(editing)} title={editing ? `Edit ${editing.email}` : "Edit user"} onClose={() => setEditing(null)}>
        {editing ? (
          <form onSubmit={submitEdit}>
            <Field label="Name">
              <input value={editName} onChange={(event) => setEditName(event.target.value)} required />
            </Field>
            <Field label="Role">
              <select value={editRole} onChange={(event) => setEditRole(event.target.value)}>
                <option value="USER">USER</option>
                <option value="ADMIN">ADMIN</option>
              </select>
            </Field>
            <label className="checkbox" style={{ margin: "6px 0 12px" }}>
              <input type="checkbox" checked={editActive} onChange={(event) => setEditActive(event.target.checked)} />
              Account active
            </label>
            <Field label="New password (optional)" hint="Leave blank to keep the current password">
              <input type="password" value={editPassword} onChange={(event) => setEditPassword(event.target.value)} minLength={8} />
            </Field>
            <ErrorText error={editError} />
            <div className="modal-foot" style={{ padding: "14px 0 0", border: "none" }}>
              <button type="button" className="btn ghost" onClick={() => setEditing(null)}>Cancel</button>
              <button type="submit" className="btn" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
            </div>
          </form>
        ) : null}
      </Modal>
    </>
  );
}
