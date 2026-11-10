"use client";

import { useEffect, useState } from "react";

import { Badge, Card, ErrorText, Field, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime, relativeTime } from "@/lib/format";
import type { MarketStatus, SettingsMap } from "@/lib/types";
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
  const market = useApiData<MarketStatus>("/market/status");
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
    try {
      const response = await api.get<{ url: string }>("/market/fyers/login-url");
      window.open(response.url, "_blank", "noopener,noreferrer");
      setAuthMessage("Complete the FYERS login in the new tab; this page updates after you return.");
    } catch (err) {
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
          <div className="flex" style={{ marginTop: 14, justifyContent: "space-between", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
            <div>
              <button className="btn small" onClick={openFyersLogin}>
                Connect FYERS
              </button>
              <div className="muted small" style={{ marginTop: 8 }}>
                Opens the FYERS login page. After approving, the redirect stores the token on the backend.
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
        ) : (
          <div className="muted small" style={{ marginTop: 12 }}>
            Kotak Neo quotes and the scrip master use <code>KOTAK_CONSUMER_KEY</code>.
            The SFeed websocket additionally needs <code>KOTAK_MOBILE_NUMBER</code>,{" "}
            <code>KOTAK_UCC</code>, <code>KOTAK_MPIN</code> and <code>KOTAK_TOTP_SECRET</code>.
            Set them in <code>backend/.env</code> and restart the backend.
          </div>
        )}

        {authMessage ? <div className="success-text" style={{ marginTop: 12 }}>{authMessage}</div> : null}
        <ErrorText error={authError} />
        <div className="muted small" style={{ marginTop: 10 }}>
          Credentials stay in <code>backend/.env</code>. Tokens/sessions are held by the backend
          and never exposed to the browser. Target and stop-loss crossings close the signal
          automatically.
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
