import { useMemo, useState } from "react";

import { ApiError, createRequest } from "../api";
import { humanize } from "../format";
import type { Config } from "../types";

interface Props {
  config: Config;
  onCreated: (id: number) => void;
  onClose: () => void;
}

const EMPTY = {
  customer_id: "",
  customer_name: "",
  order_id: "",
  amount: "",
  note: "",
};

export function NewRequestForm({ config, onCreated, onClose }: Props) {
  const [form, setForm] = useState(EMPTY);
  const [reason, setReason] = useState(config.reasons[0]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Stable for the life of the form, so a double submit cannot create two rows.
  const idempotencyKey = useMemo(() => crypto.randomUUID(), []);

  const amountCents = Math.round(Number(form.amount) * 100);
  const valid =
    form.customer_id.trim() !== "" &&
    form.customer_name.trim() !== "" &&
    form.order_id.trim() !== "" &&
    Number.isFinite(amountCents) &&
    amountCents > 0;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createRequest({
        customer_id: form.customer_id.trim(),
        customer_name: form.customer_name.trim(),
        order_id: form.order_id.trim(),
        reason,
        amount_cents: amountCents,
        note: form.note.trim(),
        idempotency_key: idempotencyKey,
      });
      onCreated(created.id);
    } catch (err) {
      setError((err as ApiError).detail);
      setBusy(false);
    }
  }

  const update = (field: keyof typeof EMPTY) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: event.target.value }));

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(event) => event.stopPropagation()} onSubmit={submit}>
        <h2>New refund request</h2>
        <div className="grid">
          <label>
            Customer ID
            <input value={form.customer_id} onChange={update("customer_id")} placeholder="CUS-1041" />
          </label>
          <label>
            Customer name
            <input value={form.customer_name} onChange={update("customer_name")} />
          </label>
          <label>
            Order ID
            <input value={form.order_id} onChange={update("order_id")} placeholder="ORD-40231" />
          </label>
          <label>
            Amount (USD)
            <input
              value={form.amount}
              onChange={update("amount")}
              inputMode="decimal"
              placeholder="49.99"
            />
          </label>
          <label className="span">
            Reason
            <select value={reason} onChange={(event) => setReason(event.target.value)}>
              {config.reasons.map((option) => (
                <option key={option} value={option}>
                  {humanize(option)}
                </option>
              ))}
            </select>
          </label>
          <label className="span">
            Note
            <textarea value={form.note} onChange={update("note")} rows={3} />
          </label>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="actions">
          <button type="button" className="link" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="approve" disabled={!valid || busy}>
            {busy ? "Submitting…" : "Submit request"}
          </button>
        </div>
      </form>
    </div>
  );
}
