"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Plus, UserRoundCog } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  fetchAccounts,
  fetchOperationUserAccounts,
  fetchOperationUsers,
  grantOperationUserQuota,
  setOperationUserAccounts,
  setOperationUserStatus,
  type Account,
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

function accountTitle(account: Account) {
  const token = String(account.access_token || "");
  return account.email || account.account_id || `${token.slice(0, 10)}...${token.slice(-6)}`;
}

export default function UsersPage() {
  const { isCheckingAuth, session } = useAuthGuard();
  const [items, setItems] = useState<OperationUser[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountTarget, setAccountTarget] = useState<OperationUser | null>(null);
  const [selectedAccountTokens, setSelectedAccountTokens] = useState<string[]>([]);
  const [quotaInputs, setQuotaInputs] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [isSavingAccounts, setIsSavingAccounts] = useState(false);

  const loadItems = async () => {
    setIsLoading(true);
    try {
      const [usersData, accountsData] = await Promise.all([fetchOperationUsers(), fetchAccounts()]);
      setItems(usersData.items);
      setAccounts(accountsData.items);
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

  const openAccountDialog = async (user: OperationUser) => {
    setBusyId(user.id);
    try {
      const [bindingsData, accountsData] = await Promise.all([
        fetchOperationUserAccounts(user.id),
        fetchAccounts(),
      ]);
      setAccounts(accountsData.items);
      setSelectedAccountTokens(
        bindingsData.items
          .map((item) => item.account?.access_token)
          .filter((token): token is string => typeof token === "string" && token.length > 0),
      );
      setAccountTarget(user);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "读取账号分配失败");
    } finally {
      setBusyId("");
    }
  };

  const toggleAccountToken = (token: string, checked: boolean) => {
    setSelectedAccountTokens((current) =>
      checked ? Array.from(new Set([...current, token])) : current.filter((item) => item !== token),
    );
  };

  const saveAccountBindings = async () => {
    if (!accountTarget) return;
    setIsSavingAccounts(true);
    try {
      const data = await setOperationUserAccounts(accountTarget.id, selectedAccountTokens);
      if (data.user) {
        patchUser(data.user);
      } else {
        patchUser({ ...accountTarget, assigned_account_count: selectedAccountTokens.length });
      }
      setAccountTarget(null);
      toast.success("账号分配已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存账号分配失败");
    } finally {
      setIsSavingAccounts(false);
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
              <th className="px-4 py-3 font-medium">账号</th>
              <th className="px-4 py-3 font-medium">额度</th>
              <th className="px-4 py-3 font-medium">注册时间</th>
              <th className="px-4 py-3 text-right font-medium">分配额度</th>
              <th className="px-4 py-3 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td className="px-4 py-8 text-center text-stone-400" colSpan={7}>
                  <LoaderCircle className="mx-auto size-5 animate-spin" />
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td className="px-4 py-8 text-center text-stone-400" colSpan={7}>
                  暂无用户
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className="border-t border-stone-100 dark:border-white/10">
                  <td className="px-4 py-3 font-medium text-stone-900 dark:text-stone-100">{item.username}</td>
                  <td className="px-4 py-3 text-stone-600 dark:text-stone-300">{item.status === "active" ? "启用" : "禁用"}</td>
                  <td className="px-4 py-3 text-stone-600 dark:text-stone-300">{item.role === "admin" ? "全部号池" : `${item.assigned_account_count || 0} 个`}</td>
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
                    <div className="flex justify-end gap-2">
                      {item.role !== "admin" ? (
                        <Button variant="outline" className="h-9 rounded-lg" onClick={() => void openAccountDialog(item)} disabled={busyId === item.id}>
                          分配账号
                        </Button>
                      ) : null}
                      <Button variant="outline" className="h-9 rounded-lg" onClick={() => void handleToggleStatus(item)} disabled={busyId === item.id}>
                        {item.status === "active" ? "禁用" : "启用"}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <Dialog open={Boolean(accountTarget)} onOpenChange={(open) => (!open ? setAccountTarget(null) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>分配账号 - {accountTarget?.username}</DialogTitle>
          </DialogHeader>
          <div className="max-h-[420px] space-y-2 overflow-y-auto pr-1">
            {accounts.length === 0 ? (
              <div className="rounded-xl border border-stone-200 p-6 text-center text-sm text-stone-500">暂无号池账号</div>
            ) : (
              accounts.map((account) => {
                const token = account.access_token;
                const checked = selectedAccountTokens.includes(token);
                return (
                  <label key={token} className="flex cursor-pointer items-center gap-3 rounded-xl border border-stone-200 p-3 hover:bg-stone-50">
                    <Checkbox checked={checked} onCheckedChange={(value) => toggleAccountToken(token, Boolean(value))} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-stone-900">{accountTitle(account)}</div>
                      <div className="text-xs text-stone-500">
                        状态 {account.status} · 额度 {account.image_quota_unknown ? "未知" : account.quota} · 成功 {account.success || 0}
                      </div>
                    </div>
                  </label>
                );
              })
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" className="rounded-xl" onClick={() => setAccountTarget(null)} disabled={isSavingAccounts}>
              取消
            </Button>
            <Button className="rounded-xl bg-stone-950 text-white" onClick={() => void saveAccountBindings()} disabled={isSavingAccounts}>
              {isSavingAccounts ? <LoaderCircle className="size-4 animate-spin" /> : null}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}
