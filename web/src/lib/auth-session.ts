"use client";

import { fetchMe } from "@/lib/api";
import { clearStoredAuthSession, getStoredAuthSession, setStoredAuthSession, type StoredAuthSession } from "@/store/auth";

export async function getValidatedAuthSession(): Promise<StoredAuthSession | null> {
  const storedSession = await getStoredAuthSession();
  if (!storedSession) {
    return null;
  }

  try {
    const data = await fetchMe();
    const nextSession: StoredAuthSession = {
      key: storedSession.key,
      role: data.user.role,
      subjectId: data.user.id,
      name: data.user.username,
    };
    await setStoredAuthSession(nextSession);
    return nextSession;
  } catch {
    await clearStoredAuthSession();
    return null;
  }
}
