"use client";

import { useEffect, useState } from "react";

import { Badge, Card, ErrorText, Field, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime, formatRemaining, relativeTime } from "@/lib/format";
import type { FyersStatus, MarketStatus, SettingsMap } from "@/lib/types";
import { useApiData } from "@/lib/use-api-data";

function bool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

export default function SettingsPage() {
  const { data, loading, error, reload } = useApiData<{ settings: SettingsMap }>("/admin/settings");
  const market = useApiData<MarketStatus>("/market/status", { refetchOnFocus: true });
  const fyers = useApiData<FyersStatus>("/market/fyers/status", { refetchOnFocus: true });
  const [settings, setSettings] = useState<SettingsMap>({});
  const [message, setMessage] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [authCode, setAuthCode] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authMessage, setAuthMessage] = useState<string | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const provider = (market.data?.provider ?? "FYERS").toUpperCase();
  const isFyers = provider === "FYERS";

  const fyersData = fyers.data;
  const fyersBadge: { tone: "green" | "amber" | "red" | "gray"; label: string } = (() => {
    if (!fyersData) return { tone: "gray", label: fyers.loading ? "Checking…" : "Unknown" };
    if (fyersData.token_valid) {
      return fyersData.expires_soon
        ? { tone: "amber", label: "Expires soon" }
        : { tone: "green", label: "Connected" };
    }
    if (fyersData.token_present) return { tone: "red", label: "Re-login required" };
    return { tone: "amber", label: "Not connected" };
  })();
  const fyersConnectDisabled = Boolean(fyersData && !fyersData.login_available);

  useEffect(() => {
    if (data) setSettings(data.settings);
  }, [data]);

  function update(section: string, key: string, value: unknown) {
    setSettings((prev) => ({ ...prev, [section]: { ...(prev[section] || {}), [key]: value } }));
  }

  function section(name: string): Record<string, unknown> {
    return settings[name] || {};
  }

  async function save() {
    setSaving(true);
    setSaveError(null);
    setMessage(null);

    const payload: SettingsMap = {
      scanner: {
        enabled: bool(section("scanner").enabled, true),
        long_enabled: bool(section("scanner").long_enabled, true),
        short_enabled: bool(section("scanner").short_enabled, true),
        min_grade: text(section("scanner").min_grade, "C")
      },
      signal_policy: {
        allow_publish_without_stop_loss: bool(section("signal_policy").allow_publish_without_stop_loss)
      },
      market_data: {
        tracking_enabled: bool(section("market_data").tracking_enabled),
        persist_interval_seconds: Math.max(10, Math.round(numberValue(section("market_data").persist_interval_seconds, 60))),
        stale_after_seconds: Math.max(30, Math.round(numberValue(section("market_data").stale_after_seconds, 300)))
      }
    };

    try {
      const response = await api.updateSettings(payload);
      setSettings(response.settings);
      setMessage("Settings saved. Scanner changes apply to future scans.");
      reload();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading && !data) return <Spinner label="Loading settings" />;

  async function openFyersLogin() {
    setAuthError(null);
    setAuthMessage(null);

    // Open the tab inside the click gesture: browsers drop the user activation
    // after an await, so window.open() below would be treated as a pop-up.
    const tab = window.open("", "_blank");
    if (tab) tab.opener = null;

    try {
      const response = await api.get<{ url: string }>("/market/fyers/login-url");
      if (tab) {
        tab.location.replace(response.url);
        setAuthMessage("Complete the FYERS login in the new tab; this page refreshes when you return.");
      } else {
        // Pop-ups are blocked: continue in this tab instead of dead-ending.
        window.location.assign(response.url);
      }
    } catch (err) {
      if (tab) tab.close();
      setAuthError(err instanceof Error ? err.message : "Unable to build the FYERS login URL");
    }
  }

  async function exchangeCode(event: React.FormEvent) {
    event.preventDefault();
    const code = authCode.trim();
    if (!code) return;
    setAuthBusy(true);
    setAuthError(null);
    setAuthMessage(null);
    try {
      await api.post(`/market/fyers/exchange?code=${encodeURIComponent(code)}`);
      setAuthCode("");
      setAuthMessage("FYERS access token stored.");
      market.reload();
      fyers.reload();
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Token exchange failed");
    } finally {
      setAuthBusy(false);
    }
  }

  return (
    <>
      {message ? <div className="success-text">{message}</div> : null}
      <ErrorText error={error || saveError || market.error} />

      <Card
        title={`${provider} connection`}
        actions={
          <Badge tone={market.data?.configured ? "green" : "amber"}>
            {market.data?.configured ? "Connected" : "Not connected"}
          </Badge>
        }
      >
        <dl className="kv">
          <dt>Provider</dt>
          <dd>{market.data?.provider ?? "FYERS"}</dd>
          <dt>Transport</dt>
          <dd>
            {market.data?.transport === "websocket" ? "SFeed websocket" : "REST quotes"}
          </dd>
          <dt>Streaming session</dt>
          <dd>
            <Badge tone={market.data?.stream_ready ? "green" : "amber"}>
              {market.data?.stream_ready ? "Ready" : "Not ready"}
            </Badge>
          </dd>
          <dt>Tracking</dt>
          <dd>{market.data?.tracking_enabled ? "Enabled" : "Disabled"}</dd>
          <dt>Poll interval</dt>
          <dd>{market.data ? `${market.data.poll_interval_seconds}s` : "—"}</dd>
          <dt>Active signals</dt>
          <dd>{market.data?.active_signals ?? "—"}</dd>
          <dt>Last quote</dt>
          <dd>
            {market.data?.last_price_update
              ? `${formatDateTime(market.data.last_price_update)} (${relativeTime(market.data.last_price_update)})`
              : "No live quote observed yet"}
          </dd>
        </dl>

        {isFyers ? (
          <div className="muted small" style={{ marginTop: 12 }}>
            LTP tracking uses the FYERS access token managed under{" "}
            <strong>FYERS data connection</strong> below.
          </div>
        ) : (
          <div className="muted small" style={{ marginTop: 12 }}>
            Kotak Neo quotes and the scrip master use <code>KOTAK_CONSUMER_KEY</code>.
            The SFeed websocket additionally needs <code>KOTAK_MOBILE_NUMBER</code>,{" "}
            <code>KOTAK_UCC</code>, <code>KOTAK_MPIN</code> and <code>KOTAK_TOTP_SECRET</code>.
            Set them in <code>backend/.env</code> and restart the backend.
          </div>
        )}

        <div className="muted small" style={{ marginTop: 10 }}>
          Credentials stay in <code>backend/.env</code>. Tokens/sessions are held by the backend
          and never exposed to the browser. Target and stop-loss crossings close the signal
          automatically.
        </div>
      </Card>

      <Card
        title="FYERS data connection"
        actions={
          <div className="flex">
            <Badge tone={fyersBadge.tone}>{fyersBadge.label}</Badge>
            <button className="btn ghost small" onClick={fyers.reload} disabled={fyers.loading}>
              {fyers.loading ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        }
      >
        {fyersData && !fyersData.credentials_configured ? (
          <div className="warn-text" style={{ marginBottom: 12 }}>
            <code>FYERS_APP_ID</code> / <code>FYERS_SECRET_KEY</code> are not set. Add both to{" "}
            <code>backend/.env</code> and restart the backend before connecting.
          </div>
        ) : null}

        {fyersData && !fyersData.encryption_configured ? (
          <div className="warn-text" style={{ marginBottom: 12 }}>
            <code>FYERS_TOKEN_ENCRYPTION_KEY</code> is not set, so the callback refuses to store
            the token — there is no plaintext fallback. Generate one with{" "}
            <code>python -m app.cli generate-fyers-key</code>, add it to{" "}
            <code>backend/.env</code>, restart the backend, then connect again.
          </div>
        ) : null}

        {fyersData && fyersData.token_present && !fyersData.token_valid ? (
          <div className="warn-text" style={{ marginBottom: 12 }}>
            The stored FYERS token is no longer valid — it expired, or it cannot be decrypted with
            the current encryption key. Reconnect to restore LTP tracking and OI scans.
          </div>
        ) : null}

        {fyersData && fyersData.token_valid && fyersData.expires_soon ? (
          <div className="warn-text" style={{ marginBottom: 12 }}>
            The FYERS token expires {formatRemaining(fyersData.seconds_remaining)}. Reconnect to
            avoid an interruption in LTP tracking and OI scans.
          </div>
        ) : null}

        <dl className="kv">
          <dt>Status</dt>
          <dd>
            <Badge tone={fyersBadge.tone}>{fyersBadge.label}</Badge>
          </dd>
          <dt>Token</dt>
          <dd>{fyersData?.token_present ? "Stored encrypted" : "No token stored"}</dd>
          <dt>Valid until</dt>
          <dd>
            {fyersData?.expires_at
              ? `${formatDateTime(fyersData.expires_at)} (${formatRemaining(fyersData.seconds_remaining)})`
              : "Unknown — FYERS reported no expiry"}
          </dd>
          <dt>Last login</dt>
          <dd>
            {fyersData?.authenticated_at
              ? `${formatDateTime(fyersData.authenticated_at)} (${relativeTime(fyersData.authenticated_at)})`
              : "Never"}
          </dd>
          <dt>Login source</dt>
          <dd>{fyersData?.source ?? "—"}</dd>
          <dt>Encryption key</dt>
          <dd>
            <Badge tone={fyersData?.encryption_configured ? "green" : "amber"}>
              {fyersData?.encryption_configured ? "Configured" : "Missing"}
            </Badge>
          </dd>
          <dt>App credentials</dt>
          <dd>
            <Badge tone={fyersData?.credentials_configured ? "green" : "amber"}>
              {fyersData?.credentials_configured ? "Configured" : "Missing"}
            </Badge>
          </dd>
          <dt>Redirect URI</dt>
          <dd>
            <span className="mono small">{fyersData?.redirect_uri ?? "—"}</span>
          </dd>
          <dt>Used for</dt>
          <dd>
            {isFyers
              ? "Live LTP tracking and admin OI scans"
              : `Admin OI scans (LTP tracking uses ${provider})`}
          </dd>
        </dl>

        <div
          className="flex"
          style={{
            marginTop: 14,
            justifyContent: "space-between",
            alignItems: "flex-end",
            gap: 16,
            flexWrap: "wrap"
          }}
        >
          <div>
            <button className="btn small" onClick={openFyersLogin} disabled={fyersConnectDisabled}>
              {fyersData?.token_present ? "Reconnect FYERS" : "Connect FYERS"}
            </button>
            <div className="muted small" style={{ marginTop: 8 }}>
              Opens the official FYERS login page in a new tab. The redirect validates the signed
              state, exchanges the code server-side and stores the token encrypted; this card
              refreshes when you return to this tab.
            </div>
          </div>

          <form onSubmit={exchangeCode} style={{ display: "grid", gap: 8 }}>
            <Field label="Or paste the auth_code from the redirect URL">
              <input
                value={authCode}
                onChange={(event) => setAuthCode(event.target.value)}
                placeholder="auth_code=…"
                style={{ minWidth: 280 }}
              />
            </Field>
            <button type="submit" className="btn ghost small" disabled={authBusy || !authCode.trim()}>
              {authBusy ? "Exchanging…" : "Store token"}
            </button>
          </form>
        </div>

        {authMessage ? <div className="success-text" style={{ marginTop: 12 }}>{authMessage}</div> : null}
        <div style={{ marginTop: 10 }}>
          <ErrorText error={authError || fyersData?.error || fyers.error} />
        </div>
        <div className="muted small" style={{ marginTop: 10 }}>
          The access token is never shown in this page or any API response. FYERS tokens are daily:
          reconnect from this card after each expiry.
        </div>
      </Card>

      <Card
        title="Operational settings"
        actions={
          <button className="btn small" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        }
      >
        <div className="settings-block">
          <h3>Scanner</h3>
          <label className="checkbox" style={{ marginBottom: 10 }}>
            <input
              type="checkbox"
              checked={bool(section("scanner").enabled, true)}
              onChange={(event) => update("scanner", "enabled", event.target.checked)}
            />
            Scanner enabled
          </label>
          <div className="row">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={bool(section("scanner").long_enabled, true)}
                onChange={(event) => update("scanner", "long_enabled", event.target.checked)}
              />
              LONG candidates
            </label>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={bool(section("scanner").short_enabled, true)}
                onChange={(event) => update("scanner", "short_enabled", event.target.checked)}
              />
              SHORT candidates
            </label>
            <Field label="Minimum grade">
              <select
                value={text(section("scanner").min_grade, "C")}
                onChange={(event) => update("scanner", "min_grade", event.target.value)}
              >
                {["A+", "A", "B+", "B", "C"].map((grade) => (
                  <option key={grade} value={grade}>{grade}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="muted small" style={{ marginTop: 8 }}>
            The scoring formulas are versioned and are not editable here.
          </div>
        </div>

        <div className="settings-block">
          <h3>Signal policy</h3>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={bool(section("signal_policy").allow_publish_without_stop_loss)}
              onChange={(event) => update("signal_policy", "allow_publish_without_stop_loss", event.target.checked)}
            />
            Allow publishing without a stop-loss
          </label>
        </div>

        <div className="settings-block">
          <h3>Market data / FYERS tracking</h3>
          <label className="checkbox" style={{ marginBottom: 10 }}>
            <input
              type="checkbox"
              checked={bool(section("market_data").tracking_enabled)}
              onChange={(event) => update("market_data", "tracking_enabled", event.target.checked)}
            />
            Track active signals with live FYERS LTPs
          </label>
          <div className="row">
            <Field label="Persist price every (seconds)">
              <input
                type="number"
                min={10}
                value={numberValue(section("market_data").persist_interval_seconds, 60)}
                onChange={(event) => update("market_data", "persist_interval_seconds", Number(event.target.value))}
              />
            </Field>
            <Field label="Mark price stale after (seconds)">
              <input
                type="number"
                min={30}
                value={numberValue(section("market_data").stale_after_seconds, 300)}
                onChange={(event) => update("market_data", "stale_after_seconds", Number(event.target.value))}
              />
            </Field>
          </div>
          <div className="muted small" style={{ marginTop: 8 }}>
            FYERS credentials and the access token are configured through backend environment variables / the admin API, never in this page.
          </div>
        </div>

        <div className="flex" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save settings"}
          </button>
        </div>
      </Card>
    </>
  );
}
