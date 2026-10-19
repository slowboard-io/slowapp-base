import type { App, BridgeError, JobResult, RunEvent, SecretStatus, SettingDecl, Theme } from "@slowboard/app";
import type { ReactNode } from "react";

export declare function AppProvider(props: {
  children?: ReactNode;
  fallback?: ReactNode;
  onError?: (e: BridgeError) => ReactNode;
  autoResize?: boolean;
  applyTheme?: boolean;
  connectOptions?: { waitMs?: number; timeoutMs?: number };
}): ReactNode;
export declare function useApp(): App;
export declare function useDoc<T>(name: string, initial?: T): [
  T,
  (next: T | ((prev: T) => T)) => Promise<number>,
  { rev: number; loading: boolean; saving: boolean; error: BridgeError | null; conflict: boolean },
];
export declare function useSettings(): [
  Record<string, unknown>,
  (values: Record<string, unknown>) => Promise<Record<string, unknown>>,
  { schema: Record<string, SettingDecl>; saving: boolean; errors: Record<string, string> | null },
];
export declare function useSecrets(): {
  status: SecretStatus[];
  isSet(name: string): boolean;
  set(name: string, value: string): Promise<{ name: string; set: boolean }>;
  clear(name: string, account?: string): Promise<{ name: string; set: boolean }>;
  /** Protocol 2: start an oauth sign-in; `status` updates when it finishes. */
  connect(name: string, opts?: { account?: string }): Promise<{ url: string }>;
  busy: boolean;
};
export declare function useJob<R = unknown>(name: string): {
  run(args?: Record<string, unknown>): Promise<JobResult<R>>;
  running: boolean;
  result: R | null;
  error: Error | null;
  last: JobResult<R> | null;
};
export declare function useRuns(): { running: string[]; last: RunEvent | null };
export declare function useTheme(): Theme;
