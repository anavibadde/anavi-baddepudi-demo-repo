import { useState } from "react";

import { ApiError, login } from "../api";
import type { User } from "../types";

interface Props {
  onSignedIn: (user: User) => void;
}

export function LoginForm({ onSignedIn }: Props) {
  const [userId, setUserId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await login(Number(userId), password);
      onSignedIn(result.user);
    } catch (err) {
      const apiError = err as ApiError;
      setError(
        apiError.status === 401 ? "That user id and password don't match." : apiError.detail,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <h1>Refund review</h1>
        <p className="muted">Sign in to see the queue you are responsible for.</p>

        <label>
          User ID
          <input
            value={userId}
            onChange={(event) => setUserId(event.target.value)}
            inputMode="numeric"
            autoFocus
            required
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>

        <button className="approve" type="submit" disabled={busy || userId.trim() === ""}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        {error && <p className="error">{error}</p>}

        <p className="login-hint small muted">
          Demo accounts, password <code>refunds123</code>: <strong>1</strong> admin,{" "}
          <strong>3</strong> manager, <strong>9</strong> analyst. The seed script prints the
          full list.
        </p>
      </form>
    </div>
  );
}
