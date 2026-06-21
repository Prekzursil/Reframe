// ProvidersKeys.tsx — the "Providers & Keys" Settings sub-section (WU-PROVIDERS).
//
// The single home for cloud key + consent management — the #1 complaint fix.
// Composes the previously-orphaned components/{AddKeyRow, ProviderKeyRow,
// ConsentToggle} + UsageBar over the providers.* RPCs:
//
//   * lists configured providers (providers.list) — each with its catalog label,
//     a clear status badge (Configured / Needs key / Working), its REDACTED keys
//     (ProviderKeyRow) + Remove (providers.remove), a per-provider ConsentToggle
//     (text/frames) → providers.setConsent, and an AddKeyRow → providers.testKey
//     (pass/fail surfaced) → providers.upsert;
//   * a provider PICKER built from the curated catalog (providers.catalog, deduped
//     per provider) showing which are free + a "Get a free key" link to each
//     provider's console URL, to add a brand-new provider;
//   * live per-key usage (providers.usage → UsageBars).
//
// Security: the renderer NEVER receives a full key — providers.list returns
// last-4-redacted keys, and the RAW pasted key is handed straight to
// providers.upsert (stored RAW server-side, read back redacted). Keys are never
// logged here.
//
// Pure-logic (dedup / status / consent-read / routing) lives in
// providersKeysLogic.ts; connection metadata (slug/baseUrl/consoleUrl/free) in
// providerMeta.ts — both unit-tested separately.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import './providersKeys.css';
import { KeyIcon } from './providersKeysIcon';
import { ExternalLinkIcon } from './providerLinkIcon';
import { AddKeyRow } from '../components/AddKeyRow';
import { ProviderKeyRow } from '../components/ProviderKeyRow';
import { ConsentToggle, type ConsentType } from '../components/ConsentToggle';
import { UsageBars } from '../components/UsageBar';
import {
  client,
  type CatalogEntry,
  type ProviderConsent,
  type ProviderEntry,
  type UsageRow,
} from '../lib/rpc';
import {
  consentOf,
  providerOptions,
  providerStatus,
  statusLabel,
  type ProviderOption,
  type ProviderStatus,
} from './providersKeysLogic';
import { PROVIDER_META } from './providerMeta';

/** Error text from an unknown thrown value (mirrors the sibling panels). */
function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * The train-on-input disclosure for a configured provider: looked up from its
 * catalog row (display name match). Defaults to the safe "does not train"
 * disclosure when the provider is not in the catalog (custom provider).
 */
function trainsForProvider(
  catalog: CatalogEntry[],
  providerName: string | undefined,
): boolean | 'conditional' {
  const row = catalog.find((c) => c.provider === providerName);
  return row ? row.trainsOnInput : false;
}

/** The settings.get slice this panel reads (for per-provider consent). */
type SettingsConsentRead = {
  consent?: { perProvider?: Record<string, ProviderConsent> };
};

export interface ProvidersKeysProps {
  /** Inject the typed client for tests; defaults to the real lib/rpc client. */
  rpcClient?: Pick<typeof client, 'providers'> & {
    settings?: { get?: () => Promise<SettingsConsentRead> };
  };
  /**
   * Open the Models & System section (where per-function provider routing lives).
   * Optional; rendered as a quiet secondary link when wired.
   */
  onOpenModels?: () => void;
}

/** Status badge: text + color + data attr, so status is never hue-only (WCAG). */
function StatusBadge({ status }: { status: ProviderStatus }): React.ReactElement {
  return (
    <span
      className={`provider-status provider-status--${status}`}
      data-status={status}
      role="status"
    >
      {statusLabel(status)}
    </span>
  );
}

/** A configured provider's card: keys + status + consent + add-key. */
interface ProviderCardProps {
  entry: ProviderEntry;
  tested: boolean | undefined;
  trainsOnInput: boolean | 'conditional';
  consent: { text: boolean; frames: boolean };
  busy: boolean;
  onAddKey: (id: string, key: string) => void;
  onRemoveKey: (id: string, index: number) => void;
  onRemoveProvider: (id: string) => void;
  onConsentChange: (provider: string, type: ConsentType, value: boolean) => void;
}

function ProviderCard({
  entry,
  tested,
  trainsOnInput,
  consent,
  busy,
  onAddKey,
  onRemoveKey,
  onRemoveProvider,
  onConsentChange,
}: ProviderCardProps): React.ReactElement {
  const name = entry.provider || entry.id;
  const keys = Array.isArray(entry.apiKeys) ? entry.apiKeys : [];
  const status = providerStatus(entry, tested);
  return (
    <li className="provider-card" data-provider={entry.id}>
      <div className="provider-card__head">
        <span className="provider-card__name">{name}</span>
        <StatusBadge status={status} />
        <button
          type="button"
          className="provider-card__remove"
          aria-label={`Remove provider ${name}`}
          disabled={busy}
          title={busy ? 'Working…' : undefined}
          onClick={() => onRemoveProvider(entry.id)}
        >
          Remove provider
        </button>
      </div>

      {keys.length > 0 ? (
        <ul className="provider-card__keys">
          {keys.map((redactedKey, index) => (
            <ProviderKeyRow
              key={`${entry.id}:${index}`}
              providerId={entry.id}
              redactedKey={redactedKey}
              index={index}
              onRemove={onRemoveKey}
            />
          ))}
        </ul>
      ) : (
        <p className="provider-card__no-keys">
          No key yet — paste one below to enable this provider.
        </p>
      )}

      <AddKeyRow providerId={entry.id} onAdd={onAddKey} />

      <ConsentToggle
        providerId={name}
        text={consent.text}
        frames={consent.frames}
        trainsOnInput={trainsOnInput}
        onChange={onConsentChange}
      />
    </li>
  );
}

/** The "add a provider" picker row: free badge + get-a-free-key link + base URL. */
interface PickerOptionProps {
  option: ProviderOption;
  configured: boolean;
  busy: boolean;
  onAdd: (option: ProviderOption) => void;
}

function PickerOption({ option, configured, busy, onAdd }: PickerOptionProps): React.ReactElement {
  const { meta, freeLimits, privacyTier } = option;
  const disabled = configured || busy;
  const reason = configured ? 'Already added below' : busy ? 'Working…' : undefined;
  return (
    <li className="picker-option" data-provider={meta.slug}>
      <div className="picker-option__info">
        <span className="picker-option__name">{meta.label}</span>
        {meta.free ? (
          <span className="picker-option__free" data-free="true">
            Free tier
          </span>
        ) : (
          <span className="picker-option__paid" data-free="false">
            Paid
          </span>
        )}
        <span className="picker-option__limits">{freeLimits}</span>
        <span className="picker-option__privacy" data-privacy={privacyTier}>
          {privacyTier}
        </span>
      </div>
      <div className="picker-option__actions">
        <a
          className="picker-option__getkey"
          href={meta.consoleUrl}
          target="_blank"
          rel="noreferrer noopener"
        >
          {meta.free ? 'Get a free key' : 'Get an API key'}
          <ExternalLinkIcon />
        </a>
        <button
          type="button"
          className="picker-option__add"
          disabled={disabled}
          aria-disabled={disabled}
          title={reason}
          onClick={() => onAdd(option)}
        >
          {configured ? 'Added' : 'Add provider'}
        </button>
      </div>
    </li>
  );
}

/**
 * Providers & Keys — the full key + consent management surface (WU-PROVIDERS).
 */
export function ProvidersKeys({ rpcClient, onOpenModels }: ProvidersKeysProps): React.ReactElement {
  /* v8 ignore next -- the `?? client` default only runs in the real app; every test injects rpcClient. */
  const api = rpcClient ?? client;

  const [providers, setProviders] = useState<ProviderEntry[]>([]);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [consentMap, setConsentMap] = useState<Record<string, ProviderConsent>>({});
  // Last in-session testKey outcome per provider id (pass/fail), drives "Working".
  const [tested, setTested] = useState<Record<string, boolean>>({});
  // Per-provider transient add-key feedback ("Validating…" / pass / fail).
  const [addStatus, setAddStatus] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  // Load the configured pool + catalog + usage + consent on mount.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    Promise.all([
      Promise.resolve(api.providers.list()),
      Promise.resolve(api.providers.catalog()),
      Promise.resolve(api.providers.usage()),
      /* v8 ignore next -- the optional-chaining fallback only fires when a test omits settings.get; every meaningful test injects it. */
      Promise.resolve<SettingsConsentRead>(api.settings?.get?.() ?? {}),
    ])
      .then(([list, cat, use, settings]) => {
        if (alive) {
          setProviders(Array.isArray(list?.providers) ? list.providers : []);
          setCatalog(Array.isArray(cat?.providers) ? cat.providers : []);
          setUsage(Array.isArray(use?.usage) ? use.usage : []);
          setConsentMap(settings?.consent?.perProvider ?? {});
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (alive) {
          setError(errText(err));
          setLoading(false);
        }
      });
    return () => {
      alive = false;
    };
  }, [api]);

  const options = useMemo(() => providerOptions(catalog), [catalog]);
  const configuredIds = useMemo(() => new Set(providers.map((p) => p.id)), [providers]);

  // Add a brand-new provider from the picker (no key yet → status "Needs key").
  const addProvider = useCallback(
    async (option: ProviderOption): Promise<void> => {
      setBusy(true);
      setError('');
      try {
        const res = await api.providers.upsert({
          id: option.meta.slug,
          provider: option.meta.label,
          baseUrl: option.meta.baseUrl,
          // A REAL per-provider API model id — without it the egress pool +
          // testKey fall back to gpt-4o-mini, which 404s on non-OpenAI providers.
          model: option.meta.defaultModel,
        });
        setProviders(Array.isArray(res?.providers) ? res.providers : []);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  // Paste-add a key: validate it (providers.testKey) THEN store it
  // (providers.upsert). The pass/fail is surfaced; a failed test still stores the
  // key (the user may have a transient issue) but does NOT promote to "Working".
  const addKey = useCallback(
    async (id: string, key: string): Promise<void> => {
      const entry = providers.find((p) => p.id === id);
      /* v8 ignore next -- addKey is only invoked from a card bound to a live entry; the guard is defensive. */
      if (!entry) return;
      // Resolve baseUrl + a REAL model id from the entry, falling back to the
      // provider's connection meta (a picker-added entry already carries both,
      // but a key pasted before either was set still validates correctly).
      const meta = entry.provider ? PROVIDER_META[entry.provider] : undefined;
      const baseUrl = entry.baseUrl || meta?.baseUrl || '';
      const model = entry.model || meta?.defaultModel;
      setBusy(true);
      setError('');
      setAddStatus((s) => ({ ...s, [id]: 'Validating key…' }));
      try {
        const result = await api.providers.testKey({
          baseUrl,
          apiKey: key,
          model,
          capabilities: entry.capabilities,
        });
        setTested((t) => ({ ...t, [id]: result.ok }));
        setAddStatus((s) => ({
          ...s,
          [id]: result.ok ? 'Key verified — working.' : `Key failed: ${result.error ?? 'invalid'}`,
        }));
        const existingKeys = Array.isArray(entry.apiKeys) ? entry.apiKeys : [];
        const res = await api.providers.upsert({
          id,
          apiKeys: [...existingKeys, key],
        });
        setProviders(Array.isArray(res?.providers) ? res.providers : []);
      } catch (err) {
        setAddStatus((s) => ({ ...s, [id]: '' }));
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [api, providers],
  );

  // Remove one key from a provider (re-upsert the surviving keys).
  const removeKey = useCallback(
    async (id: string, index: number): Promise<void> => {
      const entry = providers.find((p) => p.id === id);
      /* v8 ignore next 2 -- removeKey is bound to a live key row, so entry exists AND its apiKeys is a non-empty array; both guards are defensive. */
      if (!entry) return;
      const keys = (Array.isArray(entry.apiKeys) ? entry.apiKeys : []).filter(
        (_, i) => i !== index,
      );
      setBusy(true);
      setError('');
      try {
        const res = await api.providers.upsert({ id, apiKeys: keys });
        setProviders(Array.isArray(res?.providers) ? res.providers : []);
        setTested((t) => ({ ...t, [id]: false }));
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [api, providers],
  );

  // Drop a whole provider (providers.remove).
  const removeProvider = useCallback(
    async (id: string): Promise<void> => {
      setBusy(true);
      setError('');
      try {
        const res = await api.providers.remove(id);
        setProviders(Array.isArray(res?.providers) ? res.providers : []);
      } catch (err) {
        setError(errText(err));
      } finally {
        setBusy(false);
      }
    },
    [api],
  );

  // Toggle one data-type consent for a provider (providers.setConsent).
  const changeConsent = useCallback(
    async (provider: string, type: ConsentType, value: boolean): Promise<void> => {
      setError('');
      // Optimistic: reflect immediately, roll back on failure.
      const prev = consentMap;
      setConsentMap((m) => ({ ...m, [provider]: { ...m[provider], [type]: value } }));
      try {
        const res = await api.providers.setConsent(provider, { [type]: value });
        setConsentMap(res?.consent?.perProvider ?? {});
      } catch (err) {
        setConsentMap(prev);
        setError(errText(err));
      }
    },
    [api, consentMap],
  );

  if (loading) {
    return (
      <section className="feature-panel providers-keys" aria-label="Providers and Keys">
        <div className="providers-keys__loading" aria-busy="true">
          Loading providers…
        </div>
      </section>
    );
  }

  return (
    <section className="feature-panel providers-keys" aria-labelledby="providers-keys-title">
      <header className="providers-keys__header">
        <h2 id="providers-keys-title" className="providers-keys__title">
          Providers &amp; API Keys
        </h2>
        <p className="providers-keys__hint">
          Bring a free API key from one or more providers to unlock Cloud-quality
          processing. Keys are stored locally, shown only as the last 4 characters, and
          never leave your machine except to the provider you choose.
        </p>
      </header>

      {error ? (
        <p className="providers-keys__error" role="alert">
          {error}
        </p>
      ) : null}

      {/* Configured providers (or a helpful empty-state). */}
      {providers.length === 0 ? (
        <div className="providers-keys__empty">
          <span className="providers-keys__icon" aria-hidden="true">
            <KeyIcon />
          </span>
          <p className="providers-keys__empty-msg">
            No provider keys yet. Pick a provider below, grab a free key, and paste it in
            to start using Cloud quality.
          </p>
        </div>
      ) : (
        <ul className="providers-keys__list" aria-label="Configured providers">
          {providers.map((entry) => (
            <ProviderCard
              key={entry.id}
              entry={entry}
              tested={tested[entry.id]}
              trainsOnInput={trainsForProvider(catalog, entry.provider)}
              consent={consentOf(consentMap, entry.provider || entry.id)}
              busy={busy}
              onAddKey={(id, key) => void addKey(id, key)}
              onRemoveKey={(id, index) => void removeKey(id, index)}
              onRemoveProvider={(id) => void removeProvider(id)}
              onConsentChange={(provider, type, value) => void changeConsent(provider, type, value)}
            />
          ))}
        </ul>
      )}

      {/* Per-provider add-key feedback (pass/fail), announced politely. */}
      {Object.entries(addStatus).some(([, v]) => v) ? (
        <ul className="providers-keys__feedback" aria-live="polite">
          {Object.entries(addStatus)
            .filter(([, v]) => v)
            .map(([id, msg]) => (
              <li key={id} className="providers-keys__feedback-row" data-provider={id}>
                {msg}
              </li>
            ))}
        </ul>
      ) : null}

      {/* Provider picker — add a new provider. */}
      <section className="providers-keys__picker" aria-labelledby="providers-picker-title">
        <h3 id="providers-picker-title" className="providers-keys__picker-title">
          Add a provider
        </h3>
        {options.length === 0 ? (
          <p className="providers-keys__picker-empty">No providers available to add right now.</p>
        ) : (
          <ul className="providers-keys__picker-list">
            {options.map((option) => (
              <PickerOption
                key={option.meta.slug}
                option={option}
                configured={configuredIds.has(option.meta.slug)}
                busy={busy}
                onAdd={(o) => void addProvider(o)}
              />
            ))}
          </ul>
        )}
      </section>

      {/* Live per-key usage. */}
      <section className="providers-keys__usage" aria-label="Provider usage">
        <h3 className="providers-keys__usage-title">Usage</h3>
        <UsageBars rows={usage} />
      </section>

      {onOpenModels ? (
        <button type="button" className="providers-keys__models-link" onClick={onOpenModels}>
          Review model routing in Models &amp; System
        </button>
      ) : null}
    </section>
  );
}

export default ProvidersKeys;
