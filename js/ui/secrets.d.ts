// Types for @slowboard/ui/secrets: <sb-secret-field> and <sb-connect> (bridge protocol 2).
import type { App, SecretStatus } from "@slowboard/app";

export declare const css: string;
/** The app every element uses unless it has its own `app` property. */
export declare function setApp(app: App): void;
export declare function esc(v: unknown): string;
export declare function ago(iso: string | null | undefined, now?: Date): string;
export declare function day(iso: string): string;
export declare function scopeName(scope: string): string;

interface ElementState { busy?: boolean; error?: string | null; now?: Date }
export declare function renderSecretField(m: Partial<SecretStatus> & ElementState & { name: string; editing?: boolean }): string;
export declare function renderConnect(m: Partial<SecretStatus> & ElementState & { name: string; url?: string | null }): string;

declare class SecretElement extends HTMLElement {
  app: App | null;
  readonly status: SecretStatus | null;
}
/** A value secret: masked input, Save, a set or not-set chip with last used, Replace, Clear. */
export declare class SbSecretField extends SecretElement {}
/** An oauth secret: Connect, or Connected with scopes, date and accounts, and Disconnect. */
export declare class SbConnect extends SecretElement {}
export declare const ELEMENTS: { "sb-secret-field": typeof SbSecretField; "sb-connect": typeof SbConnect };
export declare function define(registry?: CustomElementRegistry): void;

declare global {
  interface HTMLElementTagNameMap { "sb-secret-field": SbSecretField; "sb-connect": SbConnect }
  interface HTMLElementEventMap {
    "sb-secret": CustomEvent<{ name: string; status: SecretStatus | null }>;
    "sb-connect-url": CustomEvent<{ name: string; url: string }>;
  }
}
