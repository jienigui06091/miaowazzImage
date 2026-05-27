"use client";

import { useState } from "react";
import { Eye, EyeOff, KeyRound, LoaderCircle } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { changeMyPassword } from "@/lib/api";
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
          className="h-12 rounded-2xl border-stone-200 bg-white pr-12 dark:border-white/10 dark:bg-white/5"
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

export default function PasswordPage() {
  const { isCheckingAuth, session } = useAuthGuard();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
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

    setIsSubmitting(true);
    try {
      await changeMyPassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      toast.success("密码已修改");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "修改密码失败");
    } finally {
      setIsSubmitting(false);
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
    <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
      <div className="mb-6 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-stone-950 dark:text-stone-50">修改密码</h1>
          <p className="mt-1 text-sm text-stone-500 dark:text-stone-400">当前账号：{session.name}</p>
        </div>
        <KeyRound className="size-6 text-stone-400" />
      </div>

      <Card className="rounded-3xl border-white/80 bg-white/95 shadow-[0_24px_80px_rgba(28,25,23,0.08)] dark:border-white/10 dark:bg-stone-900">
        <CardContent className="space-y-5 p-6">
          <PasswordField
            id="current-password"
            label="当前密码"
            value={currentPassword}
            show={showCurrent}
            onShowChange={() => setShowCurrent((value) => !value)}
            onChange={setCurrentPassword}
            onEnter={() => void handleSubmit()}
          />
          <PasswordField
            id="new-password"
            label="新密码"
            value={newPassword}
            show={showNew}
            onShowChange={() => setShowNew((value) => !value)}
            onChange={setNewPassword}
            onEnter={() => void handleSubmit()}
          />
          <PasswordField
            id="confirm-password"
            label="确认新密码"
            value={confirmPassword}
            show={showConfirm}
            onShowChange={() => setShowConfirm((value) => !value)}
            onChange={setConfirmPassword}
            onEnter={() => void handleSubmit()}
          />
          <p className="text-xs text-stone-500 dark:text-stone-400">新密码至少 8 个字符。</p>
          <Button
            className="h-11 rounded-2xl bg-stone-950 px-5 text-white hover:bg-stone-800"
            onClick={() => void handleSubmit()}
            disabled={isSubmitting}
          >
            {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
            保存新密码
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
