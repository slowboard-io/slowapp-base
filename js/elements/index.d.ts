/** A catalog bundle (catalog.json, version 1; sdk/slowapp_sdk/schema/catalog.schema.json), or the part a host has. */
export interface Catalog {
  catalog?: 1;
  app: { id?: string; title?: string; version?: string; author?: string; blurb?: string; about?: string;
    ink?: "black" | "white" | "yellow" | "red"; license?: string; repo?: string; [k: string]: unknown };
  grants?: { network: "none" | "egress"; memory: string; secrets?: string[]; optional_secrets?: string[]; prompts?: boolean;
    ui?: boolean; backend?: boolean; data_mb?: number; cache_mb?: number; imports?: string[]; exports?: string[]; events?: string[] };
  feeds?: { name: string; size: string; surfaces?: Record<string, { ok: boolean; error?: string }>; supported?: string[];
    inks?: string[]; ink_sets?: ("k4" | "g16")[] }[];
  examples?: { name: string; caption?: string; error?: string; frames?: { kind: string; file: string }[] }[];
  screens?: { example: string; feed: string; surface: string; card: string; kind: string; title: string; file: string }[];
  image?: { platforms: Record<string, { download: number; adds_download?: number }> };
  release?: { version: string };
  [k: string]: unknown;
}
export interface Card { src: string; alt: string; synthetic?: boolean; width?: number; height?: number }
export interface Touches { internet: string; secrets: string; memory: string }
export interface Link { href: string; label: string; tone?: "black" | "red" | "yellow" | "plain" }
export interface SheetInput {
  catalog?: Catalog; base?: string; no?: string; cards?: Card[]; touches?: Touches; links?: Link[];
  crumb?: { href: string; label: string }; note?: string; titles?: Record<string, string>;
}
export interface SheetModel {
  id: string; title: string; no: string; author: string; version: string; ink: string; about: string;
  crumb: { href: string; label: string } | null;
  decks: { id: string; label: string; w: number; h: number; cards: { src: string; alt: string; w: number; h: number; synthetic: boolean }[] }[];
  note: string; touches: Touches | null; also: string[];
  facts: { label: string; value: string; sizes?: { label: string; ok: boolean; error: string }[]; inks?: string[] }[];
  links: Link[];
}

export declare const VERSION: string;
export declare const css: string;
export declare function sheetModel(input: SheetInput | Catalog): SheetModel;
export declare function renderSheet(m: SheetModel, opts?: { head?: boolean }): string;
export declare function renderScreens(m: SheetModel): string;
export declare function renderGrants(m: SheetModel): string;
export declare function renderFacts(m: SheetModel): string;
export declare function renderDisk(o?: { no?: string; title?: string; ink?: string; size?: "feature" | "tile"; cls?: string }): string;
export declare function shadowTemplate(inner: string, opts?: { css?: string }): string;
export declare function esc(s: unknown): string;
export declare function safeUrl(u: unknown): string;
export declare function grantSize(s: string): string;
export declare function bytes(n: number): string;
export declare function surface(s: string): { id: string; w: number; h: number; inks: "k4" | "g16"; label: string } | null;
export declare function stylesheet(): CSSStyleSheet | null;
export declare function define(registry?: CustomElementRegistry): void;

declare class SlowappElement extends HTMLElement {
  catalog?: Catalog; cards?: Card[]; touches?: Touches; links?: Link[]; crumb?: { href: string; label: string }; note?: string; titles?: Record<string, string>;
  readonly model: SheetModel;
  render(): void;
}
export declare class SlowappSheet extends SlowappElement {}
export declare class SlowappScreens extends SlowappElement {}
export declare class SlowappGrants extends SlowappElement {}
export declare class SlowappFacts extends SlowappElement {}
export declare class SlowappDisk extends SlowappElement {}
export declare const ELEMENTS: Record<string, typeof SlowappElement>;

declare global {
  interface HTMLElementTagNameMap {
    "slowapp-sheet": SlowappSheet; "slowapp-screens": SlowappScreens; "slowapp-grants": SlowappGrants;
    "slowapp-facts": SlowappFacts; "slowapp-disk": SlowappDisk;
  }
  interface HTMLElementEventMap {
    "slowapp-card": CustomEvent<{ deck: number; index: number; src: string }>;
    "slowapp-size": CustomEvent<{ index: number; size: string }>;
  }
}
