// The moon app's UI. Everything here works without starting the app's container except the
// "Coming up" list, which asks the phases job (a second or two on the board, cold).
import { useEffect, useState } from "react";
import { useApp, useDoc, useJob, useSettings } from "@slowboard/app-react";
import { Button, Card, Field, Hint, List, ListItem, Notice, Num, Row, Segmented, Stack, TextInput, Title } from "@slowboard/ui";

function Hemisphere() {
  const [settings, save, { saving, errors }] = useSettings();
  return (
    <Card title="Hemisphere">
      <Row>
        <Segmented label="Hemisphere" value={settings.south ? "south" : "north"}
          options={[{ value: "north", label: "North" }, { value: "south", label: "South" }]}
          onChange={(v) => save({ ...settings, south: v === "south" }).catch(() => {})} />
        {saving ? <Hint>Saving…</Hint> : null}
      </Row>
      <Hint>The lit side flips south of the equator. The panel shows it at the next update.</Hint>
      {errors ? <Notice tone="bad">{Object.values(errors).join(" ")}</Notice> : null}
    </Card>
  );
}

function Note() {
  const app = useApp();
  const [note, save, { saving, error, conflict }] = useDoc("note", "");
  const [draft, setDraft] = useState(note);
  useEffect(() => setDraft(note || ""), [note]);
  const submit = async (e) => {
    e.preventDefault();
    try {
      await save(draft.trim());
      app.ui.toast("Saved. The moon card redraws in a moment.");
    } catch { /* shown below */ }
  };
  return (
    <Card title="A note on the moon card">
      <form onSubmit={submit}>
        <Stack>
          <Field label="Note" hint="Up to 30 characters, in place of the new-moon date. Empty: the date again."
            error={conflict ? "Changed somewhere else: this is the latest. Save again to replace it." : error?.message}>
            <TextInput value={draft} maxLength={30} onChange={(e) => setDraft(e.target.value)} placeholder="Hunter's moon" />
          </Field>
          <Row><Button tone="solid" type="submit" disabled={saving || draft.trim() === (note || "")}>{saving ? "Saving…" : "Save"}</Button></Row>
        </Stack>
      </form>
    </Card>
  );
}

function ComingUp() {
  const phases = useJob("phases");
  useEffect(() => { phases.run({ count: 8 }).catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const r = phases.result;
  return (
    <Card title="Coming up">
      {r ? <Hint>Now: {r.now}, <Num>{Math.round(r.lit * 100)}%</Num> lit</Hint> : null}
      {phases.running && !r ? <Hint>Asking the moon app…</Hint> : null}
      {phases.error ? <Notice tone="bad">Couldn't work it out: {phases.error.message}</Notice> : null}
      {r ? (
        <List>
          {r.phases.map((p) => <ListItem key={p.at}><span>{p.name}</span><Num>{p.day}</Num></ListItem>)}
        </List>
      ) : null}
      <Row><Button onClick={() => phases.run({ count: 8 }).catch(() => {})} disabled={phases.running}>Refresh</Button></Row>
    </Card>
  );
}

export default function App() {
  const app = useApp();
  return (
    <Stack>
      <Title>{app.info.title}</Title>
      <Hemisphere />
      <Note />
      <ComingUp />
    </Stack>
  );
}
