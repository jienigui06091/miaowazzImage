"use client";

import { useEffect, useMemo, useState } from "react";
import { Copy, Gift, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { deleteRedeemCode, disableRedeemCode, fetchRedeemCodes, generateRedeemCodes, type RedeemCode } from "@/lib/api";
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

function statusLabel(status: string) {
  if (status === "active") return "可用";
  if (status === "used") return "已兑换";
  if (status === "disabled") return "已禁用";
  if (status === "expired") return "已过期";
  return status || "-";
}

export default function RedeemCodesPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);
  const [items, setItems] = useState<RedeemCode[]>([]);
  const [generatedItems, setGeneratedItems] = useState<RedeemCode[]>([]);
  const [quotaAmount, setQuotaAmount] = useState("10");
  const [count, setCount] = useState("1");
  const [expiresAt, setExpiresAt] = useState("");
  const [note, setNote] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [busyId, setBusyId] = useState("");

  const generatedText = useMemo(
    () => generatedItems.map((item) => `${item.code || ""}\t${item.quota_amount}`).filter((line) => line.trim()).join("\n"),
    [generatedItems],
  );

  const loadItems = async () => {
    setIsLoading(true);
    try {
      const data = await fetchRedeemCodes();
      setItems(data.items);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "读取兑换码失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (session?.role === "admin") {
      void loadItems();
    }
  }, [session?.role]);

  const handleGenerate = async () => {
    const amount = Math.floor(Number(quotaAmount || 0));
    const total = Math.floor(Number(count || 0));
    if (amount <= 0 || total <= 0) {
      toast.error("额度和数量必须大于 0");
      return;
    }
    setIsGenerating(true);
    try {
      const data = await generateRedeemCodes({
        quota_amount: amount,
        count: total,
        expires_at: expiresAt,
        note,
      });
      setGeneratedItems(data.items);
      setNote("");
      await loadItems();
      toast.success(`已生成 ${data.items.length} 个兑换码`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "生成兑换码失败");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleCopyGenerated = async () => {
    if (!generatedText) return;
    await navigator.clipboard.writeText(generatedText);
    toast.success("已复制");
  };

  const handleDisable = async (item: RedeemCode) => {
    setBusyId(item.id);
    try {
      const data = await disableRedeemCode(item.id);
      setItems((current) => current.map((row) => (row.id === item.id ? data.item : row)));
      toast.success("兑换码已禁用");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "禁用失败");
    } finally {
      setBusyId("");
    }
  };

  const handleDelete = async (item: RedeemCode) => {
    setBusyId(item.id);
    try {
      await deleteRedeemCode(item.id);
      setItems((current) => current.filter((row) => row.id !== item.id));
      toast.success("兑换码已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除失败");
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
          <h1 className="text-2xl font-semibold tracking-tight text-stone-950 dark:text-stone-50">兑换码管理</h1>
        </div>
        <Gift className="size-6 text-stone-400" />
      </div>

      <div className="mb-5 grid gap-2 rounded-xl border border-stone-200 bg-white p-4 dark:border-white/10 dark:bg-stone-900 sm:grid-cols-[120px_120px_170px_1fr_auto]">
        <Input value={quotaAmount} onChange={(event) => setQuotaAmount(event.target.value)} inputMode="numeric" placeholder="额度" className="h-10 rounded-xl border-stone-200 bg-white" />
        <Input value={count} onChange={(event) => setCount(event.target.value)} inputMode="numeric" placeholder="数量" className="h-10 rounded-xl border-stone-200 bg-white" />
        <Input type="date" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} className="h-10 rounded-xl border-stone-200 bg-white" />
        <Input value={note} onChange={(event) => setNote(event.target.value)} placeholder="备注，可选" className="h-10 rounded-xl border-stone-200 bg-white" />
        <Button className="h-10 rounded-xl bg-stone-950 text-white" onClick={() => void handleGenerate()} disabled={isGenerating}>
          {isGenerating ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
          生成
        </Button>
      </div>

      {generatedItems.length > 0 ? (
        <div className="mb-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="font-medium">本次生成的兑换码只完整显示一次</div>
            <Button variant="outline" className="h-9 rounded-lg bg-white" onClick={() => void handleCopyGenerated()}>
              <Copy className="size-4" />
              复制
            </Button>
          </div>
          <pre className="max-h-40 overflow-auto rounded-lg bg-white p-3 text-xs leading-6">{generatedText}</pre>
        </div>
      ) : null}

      <div className="overflow-hidden rounded-xl border border-stone-200 bg-white dark:border-white/10 dark:bg-stone-900">
        <table className="w-full text-sm">
          <thead className="bg-stone-50 text-left text-stone-500 dark:bg-white/5">
            <tr>
              <th className="px-4 py-3 font-medium">兑换码</th>
              <th className="px-4 py-3 font-medium">额度</th>
              <th className="px-4 py-3 font-medium">状态</th>
              <th className="px-4 py-3 font-medium">兑换用户</th>
              <th className="px-4 py-3 font-medium">过期时间</th>
              <th className="px-4 py-3 font-medium">备注</th>
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
                  暂无兑换码
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className="border-t border-stone-100 dark:border-white/10">
                  <td className="px-4 py-3 font-medium text-stone-900 dark:text-stone-100">{item.code_preview}</td>
                  <td className="px-4 py-3 text-stone-900 dark:text-stone-100">{item.quota_amount}</td>
                  <td className="px-4 py-3 text-stone-600 dark:text-stone-300">{statusLabel(item.status)}</td>
                  <td className="px-4 py-3 text-stone-500">{item.redeemed_by || "-"}</td>
                  <td className="px-4 py-3 text-stone-500">{formatTime(item.expires_at)}</td>
                  <td className="max-w-[220px] truncate px-4 py-3 text-stone-500">{item.note || "-"}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      <Button variant="outline" className="h-9 rounded-lg" onClick={() => void handleDisable(item)} disabled={busyId === item.id || item.status !== "active"}>
                        禁用
                      </Button>
                      <Button variant="outline" className="h-9 rounded-lg text-rose-600" onClick={() => void handleDelete(item)} disabled={busyId === item.id}>
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
