"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Eye, EyeOff, LoaderCircle, LockKeyhole } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/theme-toggle";
import { passwordLogin, registerUser } from "@/lib/api";
import { useRedirectIfAuthenticated } from "@/lib/use-auth-guard";
import { getDefaultRouteForRole, setStoredAuthSession } from "@/store/auth";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { isCheckingAuth } = useRedirectIfAuthenticated();

  const handleLogin = async () => {
    const normalizedUsername = username.trim();
    if (!normalizedUsername || !password) {
      toast.error("请输入用户名和密码");
      return;
    }
    if (mode === "register" && password.length < 8) {
      toast.error("密码至少需要 8 个字符");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = mode === "register"
        ? await registerUser(normalizedUsername, password)
        : await passwordLogin(normalizedUsername, password);
      await setStoredAuthSession({
        key: data.token,
        role: data.user.role,
        subjectId: data.user.id,
        name: data.user.username,
      });
      router.replace(getDefaultRouteForRole(data.user.role));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : mode === "register" ? "注册失败" : "登录失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isCheckingAuth) {
    return (
      <div className="grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <div className="grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
      <div className="fixed top-4 right-4 z-10">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-[505px] rounded-[30px] border-white/80 bg-white/95 shadow-[0_28px_90px_rgba(28,25,23,0.10)]">
        <CardContent className="space-y-7 p-6 sm:p-8">
          <div className="space-y-4 text-center">
            <div className="mx-auto inline-flex size-14 items-center justify-center rounded-[18px] bg-stone-950 text-white shadow-sm">
              <LockKeyhole className="size-5" />
            </div>
            <div className="space-y-2">
              <h1 className="text-3xl font-semibold tracking-tight text-stone-950">账号登录</h1>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 rounded-2xl bg-stone-100 p-1 text-sm font-medium text-stone-600">
            <button
              type="button"
              className={`h-10 rounded-xl transition ${mode === "login" ? "bg-white text-stone-950 shadow-sm" : ""}`}
              onClick={() => setMode("login")}
            >
              登录
            </button>
            <button
              type="button"
              className={`h-10 rounded-xl transition ${mode === "register" ? "bg-white text-stone-950 shadow-sm" : ""}`}
              onClick={() => setMode("register")}
            >
              注册
            </button>
          </div>

          <div className="space-y-3">
            <label htmlFor="username" className="block text-sm font-medium text-stone-700">
              用户名
            </label>
            <Input
              id="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="请输入用户名"
              className="h-13 rounded-2xl border-stone-200 bg-white px-4"
            />
            <label htmlFor="password" className="block text-sm font-medium text-stone-700">
              密码
            </label>
            <div className="relative">
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void handleLogin();
                  }
                }}
                placeholder="请输入密码"
                className="h-13 rounded-2xl border-stone-200 bg-white px-4 pr-12"
              />
              <button
                type="button"
                aria-label={showPassword ? "隐藏密码" : "显示密码"}
                className="absolute top-1/2 right-3 inline-flex size-8 -translate-y-1/2 items-center justify-center rounded-full text-stone-400 transition hover:bg-stone-100 hover:text-stone-700"
                onClick={() => setShowPassword((value) => !value)}
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
            <p className="text-xs text-stone-500">密码至少 8 个字符</p>
          </div>

          <Button
            className="h-13 w-full rounded-2xl bg-stone-950 text-white hover:bg-stone-800"
            onClick={() => void handleLogin()}
            disabled={isSubmitting}
          >
            {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : null}
            {mode === "register" ? "注册并登录" : "登录"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
