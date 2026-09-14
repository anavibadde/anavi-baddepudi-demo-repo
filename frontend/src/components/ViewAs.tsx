import { useEffect, useState } from "react";

import { getUsers, switchUser } from "../api";
import type { User } from "../types";

/** Demo-only identity switcher. Picking someone mints a real session for them,
 * so the queue that comes back is theirs under the ordinary rules. */
export function ViewAs({ viewer, onSwitched }: { viewer: User; onSwitched: (user: User) => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    getUsers()
      .then((list) => {
        if (active) setUsers(list);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [viewer.id]);

  async function choose(id: number) {
    if (id === viewer.id) return;
    setBusy(true);
    try {
      const result = await switchUser(id);
      onSwitched(result.user);
    } finally {
      setBusy(false);
    }
  }

  return (
    <label className="view-as">
      <span className="small muted">Viewing as</span>
      <select
        value={viewer.id}
        disabled={busy || users.length === 0}
        onChange={(event) => void choose(Number(event.target.value))}
      >
        {users
          .filter((user) => user.is_active || user.id === viewer.id)
          .map((user) => (
            <option key={user.id} value={user.id}>
              {user.name} — {user.role}
            </option>
          ))}
      </select>
    </label>
  );
}
