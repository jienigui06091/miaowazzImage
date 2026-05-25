"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Plus, UserRoundCog } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  fetchOperationUsers,
  grantOperationUserQuota,
  setOperationUserStatus,
  type OperationUser,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

function formatTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function UsersPage() {
  const { isCheckingAuth, session } = useAuthGuard();
  const [items, setItems] = useState<OperationUser[]>([]);
  const [quotaInputs, setQuotaInputs] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [busyId, setBusyId] = useState("");

  const loadItems = async () => {
    setIsLoading(true);
    try {
      const data = await fetchOperationUsers();
      setItems(data.items);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "读取用户失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (session?.role === "admin") {
      void loadItems();
    }
  }, [session?.role]);

  const patchUser = (nextUser: OperationUser) => {
    setItems((current) => current.map((item) => (item.id === nextUser.id ? nextUser : item)));
  };

  const handleGrant = async (user: OperationUser) => {
    const amount = Math.floor(Number(quotaInputs[user.id] || 0));
    if (amount <= 0) {
      toast.error("请输入大于 0 的额度");
      return;
    }
    setBusyId(user.id);
    try {
      const data = await grantOperationUserQuota(user.id, amount, "管理员分配");
      patchUser(data.user);
      setQuotaInputs((current) => ({ ...current, [user.id]: "" }));
      toast.success("额度已更新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "分配额度失败");
    } finally {
      setBusyId("");
    }
  };

  const handleToggleStatus = async (user: OperationUser) => {
    setBusyId(user.id);
    try {
      const data = await setOperationUserStatus(user.id, user.status === "active" ? "disabled" : "active");
      patchUser(data.item);
      toast.success("用户状态已更新");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "更新用户失败");
    } finally {
      setBusyId("");
    }
  };

  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  if (session.role !== "admin") {
    return null;
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
      <div className="mb-6 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-stone-950 dark:text-stone-50">用户管理</h1>
        </div>
        <UserRoundCog className="size-6 text-stone-400" />
      </div>

      <div className="overflow-hidden rounded-xl border border-stone-200 bg-white dark:border-white/10 dark:bg-stone-900">
        <table className="w-full text-sm">
          <thead className="bg-stone-50 text-left text-stone-500 dark:bg-white/5">
            <tr>
              <th className="px-4 py-3 font-medium">用户名</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium">额度</th>
              <th className="px-4 py-3 font-medium">注册时间</th>
              <th className="px-4 py-3 text-right font-medium">分配额度</th>
              <th className="px-4 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td className="px-4 py-8 text-center text-stone-400" colSpan={6}>
                  <LoaderCircle className="mx-auto size-5 animate-spin" />
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td className="px-4 py-8 text-center text-stone-400" colSpan={6}>
                  暂无用户
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className="border-t border-stone-100 dark:border-white/10">
                  <td className="px-4 py-3 font-medium text-stone-900 dark:text-stone-100">{item.username}</td>
                  <td className="px-4 py-3 text-stone-600 dark:text-stone-300">{item.status === "active" ? "启用" : "禁用"}</td>
                  <td className="px-4 py-3 text-stone-900 dark:text-stone-100">{item.image_quota}</td>
                  <td className="px-4 py-3 text-stone-500">{formatTime(item.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="ml-auto flex max-w-[220px] justify-end gap-2">
                      <Input
                        value={quotaInputs[item.id] || ""}
                        onChange={(event) => setQuotaInputs((current) => ({ ...current, [item.id]: event.target.value }))}
                        inputMode="numeric"
                        placeholder="次数"
                        className="h-9 rounded-lg"
                      />
                      <Button className="h-9 rounded-lg bg-stone-950 text-white" onClick={() => void handleGrant(item)} disabled={busyId === item.id}>
                        <Plus className="size-4" />
                      </Button>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="outline" className="h-9 rounded-lg" onClick={() => void handleToggleStatus(item)} disabled={busyId === item.id}>
                      {item.status === "active" ? "禁用" : "启用"}
                    </Button>
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

