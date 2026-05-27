"use client";

import { useEffect, useState } from "react";
import { Eye, EyeOff, Gift, KeyRound, LoaderCircle, UserRound } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { changeMyPassword, fetchMe, fetchMyRedeemRecords, redeemMyCode, type OperationUser, type RedeemRecord } from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

type PasswordFieldProps = {
  id: string;
  label: string;
  value: string;
  show: boolean;
  onShowChange: () => void;
  onChange: (value: string) => void;
  onEnter: () => void;
};

function formatTime(value?: string | null) {
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

function PasswordField({ id, label, value, show, onShowChange, onChange, onEnter }: PasswordFieldProps) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-sm font-medium text-stone-700 dark:text-stone-200">
        {label}
      </label>
      <div className="relative">
        <Input
          id={id}
          type={show ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              onEnter();
            }
          }}
          className="h-11 rounded-xl border-stone-200 bg-white pr-12 dark:border-white/10 dark:bg-white/5"
        />
        <button
          type="button"
          aria-label={show ? "隐藏密码" : "显示密码"}
          className="absolute top-1/2 right-3 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-full text-stone-400 transition hover:bg-stone-100 hover:text-stone-700 dark:hover:bg-white/10 dark:hover:text-stone-100"
          onClick={onShowChange}
        >
          {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const { isCheckingAuth, session } = useAuthGuard();
  const [user, setUser] = useState<OperationUser | null>(null);
  const [records, setRecords] = useState<RedeemRecord[]>([]);
  const [redeemCode, setRedeemCode] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isRedeeming, setIsRedeeming] = useState(false);
  const [isSavingPassword, setIsSavingPassword] = useState(false);

  const loadProfile = async () => {
    setIsLoading(true);
    try {
      const me = await fetchMe();
      setUser(me.user);
      if (me.user.role === "user") {
        const data = await fetchMyRedeemRecords();
        setRecords(data.items);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "读取个人信息失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (session) {
      void loadProfile();
    }
  }, [session?.subjectId]);

  const handleRedeem = async () => {
    const code = redeemCode.trim();
    if (!code) {
      toast.error("请输入兑换码");
      return;
    }
    setIsRedeeming(true);
    try {
      const data = await redeemMyCode(code);
      setUser(data.user);
      setRedeemCode("");
      const recordsData = await fetchMyRedeemRecords();
      setRecords(recordsData.items);
      toast.success(`兑换成功，增加 ${data.record.quota_amount} 次额度`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "兑换失败");
    } finally {
      setIsRedeeming(false);
    }
  };

  const handleChangePassword = async () => {
    if (!currentPassword || !newPassword || !confirmPassword) {
      toast.error("请填写完整密码信息");
      return;
    }
    if (newPassword.length < 8) {
      toast.error("新密码至少需要 8 个字符");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error("两次输入的新密码不一致");
      return;
    }
    setIsSavingPassword(true);
    try {
      await changeMyPassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      toast.success("密码已修改");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "修改密码失败");
    } finally {
      setIsSavingPassword(false);
    }
  };

  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
      <div className="mb-6 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-stone-950 dark:text-stone-50">个人信息</h1>
          <p className="mt-1 text-sm text-stone-500 dark:text-stone-400">当前账号：{session.name}</p>
        </div>
        <UserRound className="size-6 text-stone-400" />
      </div>

      {isLoading ? (
        <div className="flex min-h-[28vh] items-center justify-center">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_1fr]">
          <div className="space-y-5">
            <Card className="rounded-3xl border-white/80 bg-white/95 shadow-[0_24px_80px_rgba(28,25,23,0.08)] dark:border-white/10 dark:bg-stone-900">
              <CardContent className="space-y-4 p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-sm text-stone-500 dark:text-stone-400">当前额度</div>
                    <div className="mt-1 text-4xl font-semibold tracking-tight text-stone-950 dark:text-stone-50">{user?.role === "admin" ? "不限" : user?.image_quota ?? 0}</div>
                  </div>
                  <Gift className="size-6 text-stone-400" />
                </div>
                {user?.role === "user" ? (
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Input
                      value={redeemCode}
                      onChange={(event) => setRedeemCode(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          void handleRedeem();
                        }
                      }}
                      placeholder="输入兑换码"
                      className="h-11 rounded-xl border-stone-200 bg-white"
                    />
                    <Button className="h-11 rounded-xl bg-stone-950 text-white" onClick={() => void handleRedeem()} disabled={isRedeeming}>
                      {isRedeeming ? <LoaderCircle className="size-4 animate-spin" /> : null}
                      兑换
                    </Button>
                  </div>
                ) : (
                  <p className="text-sm text-stone-500 dark:text-stone-400">管理员账号默认使用号池，不消耗个人额度。</p>
                )}
              </CardContent>
            </Card>

            {user?.role === "user" ? (
              <Card className="rounded-3xl border-white/80 bg-white/95 shadow-[0_24px_80px_rgba(28,25,23,0.08)] dark:border-white/10 dark:bg-stone-900">
                <CardContent className="p-0">
                  <div className="border-b border-stone-100 px-6 py-4 text-sm font-semibold text-stone-900 dark:border-white/10 dark:text-stone-100">兑换记录</div>
                  <div className="max-h-[320px] overflow-y-auto">
                    {records.length === 0 ? (
                      <div className="px-6 py-8 text-center text-sm text-stone-400">暂无兑换记录</div>
                    ) : (
                      records.map((record) => (
                        <div key={record.id} className="flex items-center justify-between gap-4 border-b border-stone-100 px-6 py-3 text-sm last:border-0 dark:border-white/10">
                          <div>
                            <div className="font-medium text-stone-900 dark:text-stone-100">{record.code_preview}</div>
                            <div className="text-xs text-stone-500">{formatTime(record.created_at)}</div>
                          </div>
                          <div className="text-right">
                            <div className="font-semibold text-emerald-600">+{record.quota_amount}</div>
                            <div className="text-xs text-stone-500">余额 {record.balance_after}</div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </CardContent>
              </Card>
            ) : null}
          </div>

          <Card className="rounded-3xl border-white/80 bg-white/95 shadow-[0_24px_80px_rgba(28,25,23,0.08)] dark:border-white/10 dark:bg-stone-900">
            <CardContent className="space-y-5 p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold text-stone-950 dark:text-stone-50">修改密码</h2>
                <KeyRound className="size-5 text-stone-400" />
              </div>
              <PasswordField id="current-password" label="当前密码" value={currentPassword} show={showCurrent} onShowChange={() => setShowCurrent((value) => !value)} onChange={setCurrentPassword} onEnter={() => void handleChangePassword()} />
              <PasswordField id="new-password" label="新密码" value={newPassword} show={showNew} onShowChange={() => setShowNew((value) => !value)} onChange={setNewPassword} onEnter={() => void handleChangePassword()} />
              <PasswordField id="confirm-password" label="确认新密码" value={confirmPassword} show={showConfirm} onShowChange={() => setShowConfirm((value) => !value)} onChange={setConfirmPassword} onEnter={() => void handleChangePassword()} />
              <p className="text-xs text-stone-500 dark:text-stone-400">新密码至少 8 个字符。</p>
              <Button className="h-11 rounded-2xl bg-stone-950 px-5 text-white hover:bg-stone-800" onClick={() => void handleChangePassword()} disabled={isSavingPassword}>
                {isSavingPassword ? <LoaderCircle className="size-4 animate-spin" /> : null}
                保存新密码
              </Button>
            </CardContent>
          </Card>
        </div>
      )}
    </main>
  );
}
