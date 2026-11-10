"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { ErrorText } from "@/components/ui";

export default function LoginPage() {
  const { login, user, loading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace("/overview");
  }, [loading, user, router]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email.trim(), password);
      router.replace("/overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="brand">
          <span className="brand-mark">OI</span>
          <div>
            <strong>Sensibull OI</strong>
            <span>Admin Console</span>
          </div>
        </div>
        <h1>Sign in</h1>
        <p>Administrator access is required to review scans and publish signals.</p>

        <label className="field">
          <span className="field-label">Email</span>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label className="field">
          <span className="field-label">Password</span>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        <ErrorText error={error} />

        <button className="btn full" style={{ marginTop: 14 }} disabled={submitting || loading} type="submit">
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
