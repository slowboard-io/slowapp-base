// @slowboard/ui: React components in the hub's look, on slowboard.io's tokens.
//
//   import { Card, Button, Field, TextInput, Toggle, Segmented, List, KeyCap } from "@slowboard/ui";
//
// Importing this module brings in ui.css (tokens, fonts, component styles). Each component
// passes other props through to its element.

import { createElement as h } from "react";
import "./ui.css";

// The secrets elements (<sb-secret-field>, <sb-connect>): framework-free, defined on import. In
// React 19, <sb-connect name="google" app={app} /> sets the app as a property.
export { SbConnect, SbSecretField, setApp } from "./secrets.js";

const cx = (...c) => c.filter(Boolean).join(" ");

export function Stack({ className, ...p }) { return h("div", { className: cx("sb-stack", className), ...p }); }
export function Row({ className, ...p }) { return h("div", { className: cx("sb-row", className), ...p }); }
export function Title({ className, ...p }) { return h("h1", { className: cx("sb-title", className), ...p }); }
export function Hint({ className, ...p }) { return h("p", { className: cx("sb-hint", className), ...p }); }

/** A bordered section with an optional small-caps heading. */
export function Card({ title, className, children, ...p }) {
  return h("section", { className: cx("sb-card", className), ...p }, title ? h("h2", null, title) : null, children);
}

/** tone: "plain" (default), "solid", "red" or "quiet". `href` makes it a link. */
export function Button({ tone = "plain", className, href, type = "button", ...p }) {
  const cls = cx("sb-btn", tone !== "plain" && `sb-btn--${tone}`, className);
  return href ? h("a", { className: cls, href, ...p }) : h("button", { className: cls, type, ...p });
}

/** A labelled control: <Field label="City" hint="…" error={errors.city}><TextInput … /></Field> */
export function Field({ label, hint, error, children, className, ...p }) {
  return h("label", { className: cx("sb-field", className), "data-bad": error ? "" : undefined, ...p },
    h("span", null, label), children,
    hint && !error ? h("span", { className: "sb-hint" }, hint) : null,
    error ? h("span", { className: "sb-field__error", role: "alert" }, error) : null);
}

export function TextInput({ className, ...p }) { return h("input", { className: cx("sb-input", className), type: "text", ...p }); }

/** A switch: checked, onChange(bool). */
export function Toggle({ label, checked, onChange, className, ...p }) {
  return h("label", { className: cx("sb-toggle", className) },
    h("input", { type: "checkbox", role: "switch", checked: !!checked, onChange: (e) => onChange?.(e.target.checked), ...p }),
    label ? h("span", null, label) : null);
}

/** One of a few: options [{value, label}] or strings; value; onChange(value). */
export function Segmented({ options, value, onChange, label, className }) {
  return h("div", { className: cx("sb-seg", className), role: "group", "aria-label": label },
    options.map((o) => {
      const v = typeof o === "string" ? o : o.value;
      return h("button", { key: v, type: "button", "aria-pressed": v === value, onClick: () => onChange?.(v) },
        typeof o === "string" ? o : o.label ?? v);
    }));
}

export function List({ className, ...p }) { return h("ul", { className: cx("sb-list", className), ...p }); }
export function ListItem(p) { return h("li", p); }

/** A key cap in its ink: red ▲, yellow ◆, black ■, white ●. */
const GLYPH = { red: "▲", yellow: "◆", black: "■", white: "●" };
export function KeyCap({ ink, className, ...p }) {
  return h("span", { className: cx("sb-key", className), "data-ink": ink, "aria-label": `${ink} key`, ...p }, GLYPH[ink] || "?");
}

/** A number in the hub's numeral face (VT323). */
export function Num({ className, ...p }) { return h("span", { className: cx("sb-num", className), ...p }); }

export function Notice({ tone, className, ...p }) {
  return h("p", { className: cx("sb-notice", className), "data-tone": tone, role: tone === "bad" ? "alert" : "status", ...p });
}
