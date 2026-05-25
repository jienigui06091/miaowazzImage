"use client";

import { useEffect, useState } from "react";
import { Copy, KeyRound, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createMyApiKey, deleteMyApiKey, fetchMyApiKeys, updateMyApiKey, type PersonalApiKey } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

function formatTime(value: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function ApiKeysPage() {
  const { isCheckingAuth, session } = useAuthGuard();
  const [items, setItems] = useState<PersonalApiKey[]>([]);
  const [name, setName] = useState("");
  const [createdKey, setCreatedKey] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const loadItems = async () => {
    setIsLoading(true);
    try {
      const data = await fetchMyApiKeys();
      setItems(data.items);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "读取 API Key 失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (session?.role === "user") {
      void loadItems();
    }
  }, [session?.role]);

  const handleCreate = async () => {
    setIsSubmitting(true);
    try {
      const data = await createMyApiKey(name.trim());
      setItems(data.items);
      setCreatedKey(data.key);
      setName("");
      toast.success("API Key 已创建");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "创建失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleToggle = async (item: PersonalApiKey) => {
    try {
      const data = await updateMyApiKey(item.id, { enabled: !item.enabled });
      setItems(data.items);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "更新失败");
    }
  };

  const handleDelete = async (item: PersonalApiKey) => {
    try {
      const data = await deleteMyApiKey(item.id);
      setItems(data.items);
      toast.success("API Key 已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const handleCopy = async () => {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey);
    toast.success("已复制");
  };

  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  if (session.role !== "user") {
    return null;
  }

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-6">
      <div className="mb-6 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-stone-950 dark:text-stone-50">API Key</h1>
        </div>
        <KeyRound className="size-6 text-stone-400" />
      </div>

      <div className="mb-5 flex flex-col gap-2 sm:flex-row">
        <Input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Key 名称"
          className="h-11 rounded-xl border-stone-200 bg-white"
        />
        <Button className="h-11 rounded-xl bg-stone-950 text-white" onClick={() => void handleCreate()} disabled={isSubmitting}>
          {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
          创建
        </Button>
      </div>

      {createdKey ? (
        <div className="mb-5 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <code className="min-w-0 flex-1 truncate">{createdKey}</code>
          <Button variant="outline" className="h-9 rounded-lg bg-white" onClick={() => void handleCopy()}>
            <Copy className="size-4" />
          </Button>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-stone-200 bg-white dark:border-white/10 dark:bg-stone-900">
        <table className="w-full text-sm">
          <thead className="bg-stone-50 text-left text-stone-500 dark:bg-white/5">
            <tr>
              <th className="px-4 py-3 font-medium">名称</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium">创建时间</th>
              <th className="px-4 py-3 font-medium">最后使用</th>
              <th className="px-4 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td className="px-4 py-8 text-center text-stone-400" colSpan={5}>
                  <LoaderCircle className="mx-auto size-5 animate-spin" />
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td className="px-4 py-8 text-center text-stone-400" colSpan={5}>
                  暂无 API Key
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className="border-t border-stone-100 dark:border-white/10">
                  <td className="px-4 py-3 font-medium text-stone-900 dark:text-stone-100">{item.name}</td>
                  <td className="px-4 py-3 text-stone-600 dark:text-stone-300">{item.enabled ? "启用" : "禁用"}</td>
                  <td className="px-4 py-3 text-stone-500">{formatTime(item.created_at)}</td>
                  <td className="px-4 py-3 text-stone-500">{formatTime(item.last_used_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" className="h-9 rounded-lg" onClick={() => void handleToggle(item)}>
                        {item.enabled ? "禁用" : "启用"}
                      </Button>
                      <Button variant="outline" className="h-9 rounded-lg text-rose-600" onClick={() => void handleDelete(item)}>
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </main>
  );
}

