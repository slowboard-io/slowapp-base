// Types for @slowboard/app (protocol 2).

export declare const PROTOCOL: 2;
export declare const CALLS: readonly string[];

export type ErrorCode =
  | "conflict" | "invalid" | "forbidden" | "not_found" | "too_big" | "no_backend"
  | "unknown_call" | "failed" | "kind" | "timeout" | "no_hub" | "protocol";

export declare class BridgeError extends Error {
  code: ErrorCode;
  /** On a conflict: the doc's current revision and value. */
  rev?: number;
  value?: unknown;
  /** On "invalid": a message per field. */
  errors?: Record<string, string>;
}

export interface Doc<T = unknown> { rev: number; value: T | null; at: string | null }
/** One connected account of an oauth secret. */
export interface SecretAccount { account: string; scopes: string[]; granted_at: string | null; last_used: string | null }
/**
 * A secret's status, never its value. Protocol 1 hubs send only name, optional and set; protocol 2
 * adds the rest (times are RFC 3339). For an oauth secret, `set` means connected.
 */
export interface SecretStatus {
  name: string;
  optional: boolean;
  set: boolean;
  kind?: "value" | "oauth";
  label?: string;
  help?: string;
  last_used?: string | null;
  /** oauth: the [auth] provider, whether it holds several accounts, and what was granted. */
  auth?: string;
  multiple?: boolean;
  scopes?: string[];
  granted_at?: string | null;
  accounts?: SecretAccount[];
}
export interface SecretEvent extends SecretStatus { event: "secret" }
export interface JobResult<R = unknown> {
  run: string;
  outcome: string;
  ok: boolean;
  exit: number | null;
  result: R | null;
  message: string | null;
}
export interface RunEvent { app: string; job: string; run: string; phase: "started" | "ended"; outcome?: string }
export interface Theme { theme: "light" | "dark"; tokens: Record<string, string> }

export interface SettingDecl {
  type: "string" | "number" | "integer" | "boolean" | "choice";
  label?: string; help?: string; optional?: boolean; default?: unknown;
  min?: number; max?: number; choices?: string[];
}

export interface AppInfo extends Theme {
  app: string;
  title: string;
  contract: number;
  tz: string;
  locale: string;
  protocol: number;
  settings_schema: Record<string, SettingDecl>;
  settings: Record<string, unknown>;
  docs: Record<string, { writer: "ui" | "job" | "both"; max_kb: number }>;
  secrets: SecretStatus[];
  jobs: { name: string; args: Record<string, "string" | "number" | "integer" | "boolean"> }[];
  backend: boolean;
}

export interface App {
  port: MessagePort;
  info: AppInfo;
  /** The protocol agreed at connect: 2, or 1 from an older hub. */
  readonly protocol: number;
  call<T = unknown>(name: string, ...args: unknown[]): Promise<T>;
  on(event: string, f: (m: any) => void): () => void;
  docs: {
    get<T = unknown>(name: string): Promise<Doc<T>>;
    put<T = unknown>(name: string, value: T, rev: number): Promise<{ rev: number }>;
    watch<T = unknown>(name: string, f: (d: Doc<T>) => void): () => void;
  };
  settings: {
    get(): Promise<Record<string, unknown>>;
    set(values: Record<string, unknown>): Promise<Record<string, unknown>>;
  };
  secrets: {
    status(): Promise<SecretStatus[]>;
    set(name: string, value: string): Promise<{ name: string; set: boolean }>;
    clear(name: string, account?: string): Promise<{ name: string; set: boolean }>;
    /** Protocol 2: start an oauth sign-in at top level; the outcome comes as a `secret` event. */
    connect(name: string, opts?: { account?: string }): Promise<{ url: string }>;
    watch(f: (e: SecretEvent) => void): () => void;
  };
  jobs: { run<R = unknown>(name: string, args?: Record<string, unknown>): Promise<JobResult<R>> };
  events: { runs(f: (e: RunEvent) => void): () => void };
  ui: {
    title(text: string): Promise<true>;
    toast(text: string, opts?: { tone?: "bad" }): Promise<true>;
    confirm(text: string): Promise<boolean>;
    resize(height: number): Promise<true>;
    autoResize(el?: Element): () => void;
  };
  device: { preview(): Promise<{ type: string; bytes: ArrayBuffer }> };
  backend: { fetch(path: string, init?: unknown): Promise<unknown> };
  onTheme(f: (t: Theme) => void): () => void;
  applyTheme(el?: HTMLElement): () => void;
}

export declare function fromPort(port: MessagePort, opts?: { timeoutMs?: number }): App;
export declare function connect(opts?: { waitMs?: number; timeoutMs?: number; win?: Window }): Promise<App>;
