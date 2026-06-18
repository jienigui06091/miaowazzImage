import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "登录 — Miaowazz",
};

export default function LoginLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 bg-background overflow-auto">
      {children}
    </div>
  );
}
