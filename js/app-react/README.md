# @slowboard/app-react

React hooks over `@slowboard/app`.

```jsx
<AppProvider fallback={<p>Connecting…</p>}><Tags /></AppProvider>

function Tags() {
  const [tags, saveTags, { saving, conflict }] = useDoc("tags", {});
  const sync = useJob("sync");
  return <button disabled={sync.running} onClick={() => sync.run()}>Sync now</button>;
}
```

`useApp`, `useDoc`, `useSettings`, `useSecrets`, `useJob`, `useRuns`, `useTheme`.
