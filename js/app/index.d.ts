// Types for @slowboard/app (protocol 1).

export declare const PROTOCOL: 1;
export declare const CALLS: readonly string[];

export type ErrorCode =
  | "conflict" | "invalid" | "forbidden" | "not_found" | "too_big" | "no_backend"
  | "unknown_call" | "failed" | "timeout" | "no_hub" | "protocol";

export declare class BridgeError extends Error {
  code: ErrorCode;
  /** On a conflict: the doc's current revision and value. */
  rev?: number;
  value?: unknown;
  /** On "invalid": a message per field. */
  errors?: Record<string, string>;
}

export interface Doc<T = unknown> { rev: number; value: T | null; at: string | null }
export interface SecretStatus { name: string; optional: boolean; set: boolean }
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
    clear(name: string): Promise<{ name: string; set: boolean }>;
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
