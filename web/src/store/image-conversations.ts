"use client";

import localforage from "localforage";

import { httpRequest } from "@/lib/request";
import type { ImageModel } from "@/lib/api";

export type ImageConversationMode = "generate" | "edit";

export type StoredReferenceImage = {
  name: string;
  type: string;
  dataUrl: string;
};

export type StoredImage = {
  id: string;
  taskId?: string;
  status?: "loading" | "success" | "error";
  b64_json?: string;
  url?: string;
  revised_prompt?: string;
  error?: string;
};

export type ImageTurnStatus = "queued" | "generating" | "success" | "error";

export type ImageTurn = {
  id: string;
  prompt: string;
  model: ImageModel;
  mode: ImageConversationMode;
  referenceImages: StoredReferenceImage[];
  count: number;
  size: string;
  images: StoredImage[];
  createdAt: string;
  status: ImageTurnStatus;
  error?: string;
  promptDeleted?: boolean;
  resultsDeleted?: boolean;
};

export type ImageConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: ImageTurn[];
  isSummary?: boolean;
  turnCount?: number;
  queued?: number;
  running?: number;
  lastPrompt?: string;
};

export type ImageConversationStats = {
  queued: number;
  running: number;
};

export type ImageConversationPage = {
  items: ImageConversation[];
  nextCursor: string;
};

const imageConversationStorage = localforage.createInstance({
  name: "miaowazzImage",
  storeName: "image_conversations",
});

const IMAGE_CONVERSATIONS_KEY = "items";
let imageConversationWriteQueue: Promise<void> = Promise.resolve();
let imageConversationOwnerKey = "anonymous";

function currentStorageKey() {
  return `${IMAGE_CONVERSATIONS_KEY}:${imageConversationOwnerKey || "anonymous"}`;
}

export function setImageConversationOwner(ownerKey: string) {
  imageConversationOwnerKey = String(ownerKey || "anonymous").trim() || "anonymous";
}

function normalizeStoredImage(image: StoredImage): StoredImage {
  const normalized = {
    ...image,
    taskId: typeof image.taskId === "string" && image.taskId ? image.taskId : undefined,
    url: typeof image.url === "string" && image.url ? image.url : undefined,
    revised_prompt: typeof image.revised_prompt === "string" ? image.revised_prompt : undefined,
  };
  if (image.status === "loading" || image.status === "error" || image.status === "success") {
    return normalized;
  }
  return {
    ...normalized,
    status: image.b64_json || image.url ? "success" : "loading",
  };
}

function normalizeReferenceImage(image: StoredReferenceImage): StoredReferenceImage {
  return {
    name: image.name || "reference.png",
    type: image.type || "image/png",
    dataUrl: image.dataUrl,
  };
}

function dataUrlMimeType(dataUrl: string) {
  const match = dataUrl.match(/^data:(.*?);base64,/);
  return match?.[1] || "image/png";
}

function getLegacyReferenceImages(source: Record<string, unknown>): StoredReferenceImage[] {
  if (Array.isArray(source.referenceImages)) {
    return source.referenceImages
      .filter((image): image is StoredReferenceImage => {
        if (!image || typeof image !== "object") {
          return false;
        }
        const candidate = image as StoredReferenceImage;
        return typeof candidate.dataUrl === "string" && candidate.dataUrl.length > 0;
      })
      .map(normalizeReferenceImage);
  }

  if (source.sourceImage && typeof source.sourceImage === "object") {
    const image = source.sourceImage as { dataUrl?: unknown; fileName?: unknown };
    if (typeof image.dataUrl === "string" && image.dataUrl) {
      return [
        {
          name: typeof image.fileName === "string" && image.fileName ? image.fileName : "reference.png",
          type: dataUrlMimeType(image.dataUrl),
          dataUrl: image.dataUrl,
        },
      ];
    }
  }

  return [];
}

function normalizeTurn(turn: ImageTurn & Record<string, unknown>): ImageTurn {
  const normalizedImages = Array.isArray(turn.images) ? turn.images.map(normalizeStoredImage) : [];
  const derivedStatus: ImageTurnStatus =
    normalizedImages.some((image) => image.status === "loading")
      ? "generating"
      : normalizedImages.some((image) => image.status === "error")
        ? "error"
        : "success";

  return {
    id: String(turn.id || `${Date.now()}`),
    prompt: String(turn.prompt || ""),
    model: (turn.model as ImageModel) || "gpt-image-2",
    mode: turn.mode === "edit" ? "edit" : "generate",
    referenceImages: getLegacyReferenceImages(turn),
    count: Math.max(1, Number(turn.count || normalizedImages.length || 1)),
    size: typeof turn.size === "string" ? turn.size : "",
    images: normalizedImages,
    createdAt: String(turn.createdAt || new Date().toISOString()),
    status:
      turn.status === "queued" ||
      turn.status === "generating" ||
      turn.status === "success" ||
      turn.status === "error"
        ? turn.status
        : derivedStatus,
    error: typeof turn.error === "string" ? turn.error : undefined,
    promptDeleted: turn.promptDeleted === true,
    resultsDeleted: turn.resultsDeleted === true,
  };
}

function normalizeConversation(conversation: ImageConversation & Record<string, unknown>): ImageConversation {
  const turns = Array.isArray(conversation.turns)
    ? conversation.turns.map((turn) => normalizeTurn(turn as ImageTurn & Record<string, unknown>))
    : [
        normalizeTurn({
          id: String(conversation.id || `${Date.now()}`),
          prompt: String(conversation.prompt || ""),
          model: (conversation.model as ImageModel) || "gpt-image-2",
          mode: conversation.mode === "edit" ? "edit" : "generate",
          referenceImages: getLegacyReferenceImages(conversation),
          count: Number(conversation.count || 1),
          size: typeof conversation.size === "string" ? conversation.size : "",
          images: Array.isArray(conversation.images) ? (conversation.images as StoredImage[]) : [],
          createdAt: String(conversation.createdAt || new Date().toISOString()),
          status:
            conversation.status === "generating" || conversation.status === "success" || conversation.status === "error"
              ? conversation.status
              : "success",
          error: typeof conversation.error === "string" ? conversation.error : undefined,
        }),
      ];
  const lastTurn = turns.length > 0 ? turns[turns.length - 1] : null;

  return {
    id: String(conversation.id || `${Date.now()}`),
    title: String(conversation.title || ""),
    createdAt: String(conversation.createdAt || lastTurn?.createdAt || new Date().toISOString()),
    updatedAt: String(conversation.updatedAt || lastTurn?.createdAt || new Date().toISOString()),
    turns,
    isSummary: conversation.isSummary === true || (turns.length === 0 && typeof conversation.turnCount === "number"),
    turnCount: typeof conversation.turnCount === "number" ? conversation.turnCount : turns.length,
    queued: typeof conversation.queued === "number" ? conversation.queued : undefined,
    running: typeof conversation.running === "number" ? conversation.running : undefined,
    lastPrompt: typeof conversation.lastPrompt === "string" ? conversation.lastPrompt : undefined,
  };
}

function sortImageConversations(conversations: ImageConversation[]): ImageConversation[] {
  return [...conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

function getTimestamp(value: string) {
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function pickLatestConversation(current: ImageConversation, next: ImageConversation) {
  return getTimestamp(next.updatedAt) >= getTimestamp(current.updatedAt) ? next : current;
}

function mergeImageConversations(...groups: ImageConversation[][]): ImageConversation[] {
  const conversationMap = new Map<string, ImageConversation>();
  for (const group of groups) {
    for (const conversation of group.map(normalizeConversation)) {
      const current = conversationMap.get(conversation.id);
      conversationMap.set(conversation.id, current ? pickLatestConversation(current, conversation) : conversation);
    }
  }
  return sortImageConversations([...conversationMap.values()]);
}

function queueImageConversationWrite<T>(operation: () => Promise<T>): Promise<T> {
  const result = imageConversationWriteQueue.then(operation);
  imageConversationWriteQueue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

async function readStoredImageConversations(): Promise<ImageConversation[]> {
  const items =
    (await imageConversationStorage.getItem<Array<ImageConversation & Record<string, unknown>>>(
      currentStorageKey(),
    )) || [];
  return items.map(normalizeConversation);
}

async function writeStoredImageConversations(conversations: ImageConversation[]): Promise<void> {
  await imageConversationStorage.setItem(currentStorageKey(), sortImageConversations(conversations));
}

async function fetchRemoteImageConversations(cursor = ""): Promise<ImageConversationPage> {
  const params = new URLSearchParams({ summary: "true", limit: "30" });
  if (cursor) {
    params.set("cursor", cursor);
  }
  const response = await httpRequest<{ items: Array<ImageConversation & Record<string, unknown>>; next_cursor?: string }>(
    `/api/image-conversations?${params.toString()}`,
  );
  return {
    items: (Array.isArray(response.items) ? response.items : []).map((item) => normalizeConversation({ ...item, isSummary: true })),
    nextCursor: String(response.next_cursor || ""),
  };
}

async function fetchRemoteImageConversation(id: string): Promise<ImageConversation> {
  const response = await httpRequest<{ item: ImageConversation & Record<string, unknown> }>(
    `/api/image-conversations/${encodeURIComponent(id)}`,
  );
  return normalizeConversation({ ...response.item, isSummary: false });
}

async function saveRemoteImageConversation(conversation: ImageConversation): Promise<ImageConversation> {
  const response = await httpRequest<{ item: ImageConversation & Record<string, unknown> }>(
    "/api/image-conversations",
    {
      method: "POST",
      body: normalizeConversation(conversation),
    },
  );
  return normalizeConversation(response.item);
}

async function saveRemoteImageConversations(conversations: ImageConversation[]): Promise<ImageConversation[]> {
  const response = await httpRequest<{ items: Array<ImageConversation & Record<string, unknown>> }>(
    "/api/image-conversations/bulk",
    {
      method: "POST",
      body: { items: conversations.map(normalizeConversation) },
    },
  );
  return (Array.isArray(response.items) ? response.items : []).map(normalizeConversation);
}

async function deleteRemoteImageConversation(id: string): Promise<void> {
  await httpRequest(`/api/image-conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
}

async function clearRemoteImageConversations(): Promise<void> {
  await httpRequest("/api/image-conversations/clear", { method: "POST" });
}

export async function listImageConversations(): Promise<ImageConversation[]> {
  try {
    const page = await fetchRemoteImageConversations();
    return sortImageConversations(page.items);
  } catch (error) {
    console.warn("Failed to load remote image conversations", error);
    const localItems = await readStoredImageConversations();
    return sortImageConversations(localItems);
  }
}

export async function listImageConversationPage(cursor = ""): Promise<ImageConversationPage> {
  const page = await fetchRemoteImageConversations(cursor);
  return {
    items: sortImageConversations(page.items),
    nextCursor: page.nextCursor,
  };
}

export async function getImageConversation(id: string): Promise<ImageConversation | null> {
  const conversationId = String(id || "").trim();
  if (!conversationId) {
    return null;
  }
  try {
    const remoteItem = await fetchRemoteImageConversation(conversationId);
    await queueImageConversationWrite(async () => {
      const items = await readStoredImageConversations();
      await writeStoredImageConversations(mergeImageConversations(items, [remoteItem]));
    });
    return remoteItem;
  } catch (error) {
    console.warn("Failed to load remote image conversation", error);
    const localItems = await readStoredImageConversations();
    return localItems.find((item) => item.id === conversationId) ?? null;
  }
}

export async function saveImageConversations(conversations: ImageConversation[]): Promise<void> {
  await queueImageConversationWrite(async () => {
    const items = await readStoredImageConversations();
    const merged = mergeImageConversations(items, conversations);
    await writeStoredImageConversations(merged);
    try {
      await saveRemoteImageConversations(conversations.map(normalizeConversation));
    } catch (error) {
      console.warn("Failed to save remote image conversations", error);
    }
  });
}

export async function saveImageConversation(conversation: ImageConversation): Promise<void> {
  await queueImageConversationWrite(async () => {
    const items = await readStoredImageConversations();
    const nextConversation = normalizeConversation(conversation);
    const current = items.find((item) => item.id === nextConversation.id);
    const persistedConversation = current ? pickLatestConversation(current, nextConversation) : nextConversation;
    const nextItems = mergeImageConversations(items, [persistedConversation]);
    await writeStoredImageConversations(nextItems);
    try {
      const remoteConversation = await saveRemoteImageConversation(persistedConversation);
      await writeStoredImageConversations(mergeImageConversations(nextItems, [remoteConversation]));
    } catch (error) {
      console.warn("Failed to save remote image conversation", error);
    }
  });
}

export async function renameImageConversation(id: string, title: string): Promise<void> {
  await queueImageConversationWrite(async () => {
    const items = await readStoredImageConversations();
    const target = items.find((item) => item.id === id);
    if (!target) return;
    const updated = { ...target, title, updatedAt: new Date().toISOString() };
    const nextItems = sortImageConversations([
      updated,
      ...items.filter((item) => item.id !== id),
    ]);
    await writeStoredImageConversations(nextItems);
    try {
      await saveRemoteImageConversation(updated);
    } catch (error) {
      console.warn("Failed to rename remote image conversation", error);
    }
  });
}

export async function deleteImageConversation(id: string): Promise<void> {
  await queueImageConversationWrite(async () => {
    const items = await readStoredImageConversations();
    await writeStoredImageConversations(items.filter((item) => item.id !== id));
    try {
      await deleteRemoteImageConversation(id);
    } catch (error) {
      console.warn("Failed to delete remote image conversation", error);
    }
  });
}

export async function clearImageConversations(): Promise<void> {
  await queueImageConversationWrite(async () => {
    await imageConversationStorage.removeItem(currentStorageKey());
    try {
      await clearRemoteImageConversations();
    } catch (error) {
      console.warn("Failed to clear remote image conversations", error);
    }
  });
}

export function getImageConversationStats(conversation: ImageConversation | null): ImageConversationStats {
  if (!conversation) {
    return { queued: 0, running: 0 };
  }
  if (conversation.isSummary) {
    return {
      queued: Math.max(0, Number(conversation.queued || 0)),
      running: Math.max(0, Number(conversation.running || 0)),
    };
  }

  return conversation.turns.reduce(
    (acc, turn) => {
      if (turn.resultsDeleted) {
        return acc;
      }
      if (turn.status === "queued") {
        acc.queued += 1;
      } else if (turn.status === "generating") {
        acc.running += 1;
      }
      return acc;
    },
    { queued: 0, running: 0 },
  );
}
